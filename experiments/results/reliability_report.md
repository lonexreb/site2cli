# Reliability benchmark

Generated 2026-11-28T01:51:19+00:00 at commit `c481185`. Python 3.10.0, httpx 0.28.1, playwright 1.58.0.
Mode: headless Chromium; direct HTTP via httpx; no proxy; LLM browser tier stubbed. Targets: local fixture only (127.0.0.1). Each case ran 3 times.

The challenge case is a synthetic page. It tests handling only and is not a Cloudflare, DataDome or Akamai result. No protected third-party site was tested.

| Scenario | Expected | Correct | Requests per attempt | Duplicate side effects | Fallbacks | Human steps | Median latency | Status |
|---|---|---|---|---|---|---|---|---|
| Public JSON read with parameters | success | 3/3 | /items: 1 | 0 | 0 | 0 | 5 ms | verified |
| Cookie-authenticated read | success | 3/3 | /account: 1 | 0 | 0 | 0 | 5 ms | verified |
| Same read after the cookie expired | auth_required | 3/3 | /account: 1 | 0 | 3 | 0 | 6 ms | verified |
| Forbidden endpoint | forbidden | 3/3 | /forbidden: 1 | 0 | 3 | 0 | 5 ms | verified |
| Rate-limited endpoint | rate_limited | 3/3 | /limited: 1 | 0 | 0 | 0 | 5 ms | verified |
| HTTP 200 synthetic challenge page (handling test only) | challenge | 3/3 | /challenge: 1 | 0 | 3 | 0 | 5 ms | verified |
| Expected HTML that mentions CAPTCHA | success | 3/3 | /article: 1 | 0 | 0 | 0 | 6 ms | verified |
| POST applied, response dropped | unknown | 3/3 | /order: 1 | 0 | 0 | 0 | 5 ms | verified |
| Browser workflow, storage reused in a named session | success | 3/3 | /login: 1, /me: 1 | 0 | 0 | 0 | 2446 ms | verified |
| Same workflow in fresh browsers (no session) | success | 3/3 | /login: 1, /me: 1 | 0 | 0 | 0 | 2642 ms | verified |
| Workflow whose final step cannot complete | failed | 3/3 | /me: 1 | 0 | 0 | 0 | 6385 ms | verified |

Notes:
- Same read after the cookie expired: Browser fallback is attempted (the request was refused) and fails here.
- Forbidden endpoint: Browser fallback is attempted and fails here.
- HTTP 200 synthetic challenge page (handling test only): Synthetic marker page; not a protection-provider evaluation.
- Same workflow in fresh browsers (no session): Control: without a session, login state must not carry over.

Not covered: real bot-protection providers, CAPTCHA solving, human challenge handoff, proxies, the LLM-driven browser tier, and cross-process daemon use.
