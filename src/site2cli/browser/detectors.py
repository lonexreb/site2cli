"""Page-level auth and CAPTCHA detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from playwright.async_api import Page

AuthKind = Literal["login", "sso", "oauth", "mfa", "captcha", "unknown"]

# URL patterns indicating auth pages
AUTH_URL_PATTERNS: list[tuple[str, AuthKind, str | None]] = [
    # SSO providers
    (r"accounts\.google\.com", "sso", "google"),
    (r"login\.microsoftonline\.com", "sso", "microsoft"),
    (r".*\.auth0\.com/login", "sso", "auth0"),
    (r".*\.okta\.com", "sso", "okta"),
    (r"github\.com/login", "sso", "github"),
    (r"appleid\.apple\.com", "sso", "apple"),
    # OAuth flows
    (r"/oauth/authorize", "oauth", None),
    (r"/oauth2/authorize", "oauth", None),
    (r"/oauth/callback", "oauth", None),
    # Generic login paths
    (r"/login\b", "login", None),
    (r"/signin\b", "login", None),
    (r"/sign-in\b", "login", None),
    (r"/auth\b", "login", None),
    (r"/sso\b", "sso", None),
]

# CAPTCHA iframe patterns
CAPTCHA_PATTERNS: list[str] = [
    "recaptcha",
    "hcaptcha",
    "turnstile",
    "captcha",
    "challenge-platform",
]

# Page content signals
LOGIN_HEADING_PATTERNS: list[str] = [
    r"\bsign\s*in\b",
    r"\blog\s*in\b",
    r"\blogin\b",
    r"\bcreate\s+account\b",
    r"\bregister\b",
]

MFA_KEYWORDS: list[str] = [
    "two-factor",
    "2fa",
    "mfa",
    "verification code",
    "authenticator",
    "one-time password",
    "otp",
]


@dataclass
class AuthDetectionResult:
    """Result of auth page detection."""

    detected: bool = False
    kind: AuthKind = "unknown"
    provider: str | None = None
    requires_human: bool = False


async def detect_auth_page(page: Page) -> AuthDetectionResult:
    """Detect if the current page is an authentication page.

    Checks URL patterns, page content signals (password fields, login headings),
    MFA keywords, and CAPTCHA iframes.

    Returns:
        AuthDetectionResult with detection details.
    """
    url = page.url.lower()

    # Check URL patterns
    for pattern, kind, provider in AUTH_URL_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return AuthDetectionResult(
                detected=True,
                kind=kind,
                provider=provider,
                requires_human=kind in ("sso", "oauth"),
            )

    # Check page content
    try:
        signals = await page.evaluate("""() => {
            const result = {
                hasPasswordField: false,
                hasLoginHeading: false,
                hasCaptchaIframe: false,
                hasMfaKeyword: false,
                headingTexts: [],
                bodyText: '',
            };

            // Password fields
            const pwFields = document.querySelectorAll('input[type="password"]');
            result.hasPasswordField = pwFields.length > 0;

            // Heading texts
            const headings = document.querySelectorAll('h1, h2, h3');
            result.headingTexts = Array.from(headings)
                .map(h => h.textContent?.trim().toLowerCase() || '')
                .filter(t => t.length > 0);

            // CAPTCHA iframes — only flag VISIBLE ones (invisible reCAPTCHA
            // scoring iframes are hidden 0x0 and should not block discovery)
            const iframes = document.querySelectorAll('iframe');
            for (const iframe of iframes) {
                const src = (iframe.src || '').toLowerCase();
                if (src.includes('recaptcha') || src.includes('hcaptcha')
                    || src.includes('turnstile')
                    || src.includes('challenge-platform')) {
                    const rect = iframe.getBoundingClientRect();
                    const style = window.getComputedStyle(iframe);
                    const isVisible = rect.width > 10 && rect.height > 10
                        && style.display !== 'none'
                        && style.visibility !== 'hidden';
                    if (isVisible) {
                        result.hasCaptchaIframe = true;
                        break;
                    }
                }
            }

            // Body text for MFA detection (limited)
            result.bodyText = (document.body?.innerText || '').toLowerCase().slice(0, 5000);

            return result;
        }""")
    except Exception:
        return AuthDetectionResult()

    # CAPTCHA detection
    if signals.get("hasCaptchaIframe"):
        return AuthDetectionResult(
            detected=True, kind="captcha", requires_human=True
        )

    # MFA detection
    body_text = signals.get("bodyText", "")
    if any(kw in body_text for kw in MFA_KEYWORDS):
        return AuthDetectionResult(
            detected=True, kind="mfa", requires_human=True
        )

    # Login heading detection
    heading_texts = signals.get("headingTexts", [])
    has_login_heading = any(
        re.search(pat, text)
        for text in heading_texts
        for pat in LOGIN_HEADING_PATTERNS
    )

    # Password field + login heading = login page
    if signals.get("hasPasswordField") and has_login_heading:
        return AuthDetectionResult(
            detected=True, kind="login", requires_human=True
        )

    # Password field alone (might be a login page)
    if signals.get("hasPasswordField"):
        return AuthDetectionResult(
            detected=True, kind="login", requires_human=True
        )

    return AuthDetectionResult()
