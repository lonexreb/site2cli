"""Execution outcomes shared by every tier.

A tier result is a plain dict. Non-success results carry ``"outcome"`` and
``"error"`` keys; the router uses the outcome to decide whether to record a
success, promote the action, or try another tier.
"""

from __future__ import annotations

from enum import Enum

import httpx


class Outcome(str, Enum):
    SUCCESS = "success"
    AUTH_REQUIRED = "auth_required"
    FORBIDDEN = "forbidden"
    RATE_LIMITED = "rate_limited"
    CHALLENGE = "challenge"
    UNEXPECTED_RESPONSE = "unexpected_response"
    FAILED = "failed"
    # The request was dispatched but completion could not be established.
    UNKNOWN = "unknown"


# The server refused the request, so nothing was executed: trying another
# tier cannot duplicate a side effect.
REJECTED = frozenset({Outcome.AUTH_REQUIRED, Outcome.FORBIDDEN, Outcome.CHALLENGE})

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Markup that only appears on interstitial challenge pages. Prose that merely
# mentions "captcha" must not match, so these are widget/script identifiers.
# ponytail: fixed marker list; add per-vendor detectors if this misses real pages.
_CHALLENGE_MARKERS = (
    "/cdn-cgi/challenge-platform/",
    "cf-turnstile",
    'class="g-recaptcha"',
    'class="h-captcha"',
    "captcha-delivery.com",
    "_incapsula_resource",
)


class TierUnavailableError(Exception):
    """A tier cannot run this action. Raised strictly before any dispatch."""


def failure(outcome: Outcome, error: str, **extra: object) -> dict:
    """Build a non-success result dict."""
    return {"outcome": outcome.value, "error": error, **extra}


def outcome_of(result: object) -> Outcome:
    """Classify a tier result dict, whichever tier produced it."""
    if not isinstance(result, dict):
        return Outcome.SUCCESS
    if "outcome" in result:
        return Outcome(result["outcome"])
    # Tiers tag their own outcome. Untagged dicts are only read structurally:
    # a top-level error, never the payload, which may legitimately say "error".
    if result.get("error"):
        return Outcome.FAILED
    # Workflow replay: {"steps_executed", "steps_total", "results": [...]}
    if "steps_total" in result:
        steps = result.get("results") or []
        if result.get("steps_executed") != result["steps_total"] or any(
            s.get("success") is False for s in steps
        ):
            return Outcome.FAILED
    return Outcome.SUCCESS


def is_challenge(headers: httpx.Headers, body: str) -> bool:
    """True only for a recognizable bot-challenge interstitial."""
    if headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    if "html" not in headers.get("content-type", "").lower():
        return False
    lowered = body[:20000].lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


def classify_response(response: httpx.Response, *, expects_json: bool) -> dict:
    """Turn an HTTP response into a tier result dict."""
    status = response.status_code
    headers = response.headers
    is_json = "json" in headers.get("content-type", "").lower()
    data: object = None
    parsed = False
    if response.content:
        try:
            data = response.json()
            parsed = True
        except ValueError:
            data = {"text": response.text}

    base = {
        "status_code": status,
        "data": data,
        # Set-Cookie carries session secrets; keep it out of results and logs.
        "headers": {k: v for k, v in headers.items() if k.lower() != "set-cookie"},
    }

    def fail(outcome: Outcome, error: str, **extra: object) -> dict:
        return {**base, **failure(outcome, error, **extra)}

    if status == 429:
        return fail(
            Outcome.RATE_LIMITED,
            "Rate limited (HTTP 429)",
            retry_after=headers.get("retry-after"),
        )
    # A JSON body is the API answering, never an interstitial. HTML that the
    # caller asked for is only a challenge if the server says so in a header.
    if headers.get("cf-mitigated", "").lower() == "challenge" or (
        not is_json
        and (expects_json or not response.is_success)
        and is_challenge(headers, response.text)
    ):
        return fail(Outcome.CHALLENGE, f"Bot challenge page returned (HTTP {status})")
    if status == 401:
        return fail(Outcome.AUTH_REQUIRED, "Authentication required (HTTP 401)")
    if status == 403:
        return fail(Outcome.FORBIDDEN, "Forbidden (HTTP 403)")
    if response.is_redirect:
        # Redirects are not followed. After a POST this is usually
        # post/redirect/get, i.e. the action ran: never auto-retry it.
        return fail(
            Outcome.UNEXPECTED_RESPONSE,
            f"Unfollowed redirect (HTTP {status})",
            location=headers.get("location"),
            requires_review=True,
        )
    if not response.is_success:
        return fail(Outcome.FAILED, f"HTTP {status}")
    if expects_json and response.content and not parsed:
        return fail(
            Outcome.UNEXPECTED_RESPONSE,
            f"Expected JSON but got {headers.get('content-type', 'unknown content')}",
        )
    return {**base, "outcome": Outcome.SUCCESS.value}


def classify_exception(exc: Exception) -> dict:
    """Classify an exception raised while a request was in flight."""
    if isinstance(exc, httpx.HTTPStatusError):
        return classify_response(exc.response, expects_json=False)
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        # No connection was established, so nothing reached the server.
        return failure(
            Outcome.FAILED, f"Connection failed: {type(exc).__name__}", dispatched=False
        )
    if isinstance(exc, ValueError):  # includes json.JSONDecodeError
        return failure(
            Outcome.UNEXPECTED_RESPONSE,
            "Response could not be decoded; the request was already sent",
            requires_review=True,
        )
    return failure(
        Outcome.UNKNOWN,
        f"Request was sent but completion is unknown: {type(exc).__name__}",
        requires_review=True,
    )
