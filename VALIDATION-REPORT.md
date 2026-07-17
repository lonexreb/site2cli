# site2cli v0.7.0 — Independent Validation Report

**Date:** 2026-07-17
**Method:** Fresh install in a clean Linux container (Python 3.11), full test suite, and a
live end-to-end exercise of the entire CLI surface against a purpose-built local test
website (HTML storefront backed by a JSON XHR API, multi-page site, robots.txt, mutable
content page) using a real headless Chromium via Playwright.

The sandbox's network policy blocks arbitrary external hosts, so the 8 live experiments
(`experiments/`) and the 6 `@pytest.mark.live` tests could not reach their targets
(jsonplaceholder, httpbin, etc.). Everything else was validated for real — including full
browser-based CDP capture — against localhost.

---

## Verdict

**The core claim is real.** `site2cli discover` drove a real browser, captured the site's
XHR traffic over CDP, and produced — with zero LLM involvement (`--no-enhance`) — a valid
OpenAPI 3.1 spec with correctly templatized path parameters (`/api/users/{id}`), inferred
query and JSON-body parameters, a working Python client, a working zero-dep JS ES-module
client, an HTML coverage report with gap candidates, and a replayable trace. `site2cli run`
then executed those endpoints as direct HTTP calls (Tier 3) with no browser. The
progressive-formalization architecture is not vaporware.

**But it's an alpha with real rough edges.** One headline command (`screenshot`) is
completely broken, generated MCP tool names violate the MCP spec, robots.txt handling
fails open, and several of the README's quantified claims are simulations or estimates,
not measurements.

---

## What was verified working (against a live local site)

| Area | Result |
|---|---|
| Unit tests | **553 passed, 1 skipped** (claim: 553) in 16.5s (claim: <8s; machine-dependent) |
| ruff lint | clean (`src/` + `tests/`) |
| `discover` (real browser, CDP capture) | 4/4 XHR endpoints captured; GET query params, POST JSON body params, path-ID templatization all correct |
| OpenAPI 3.1 output | validates with `openapi-spec-validator`; correct `servers` URL incl. port |
| Generated Python client | all 4 methods executed successfully against the live API (after working around naming bug #1) |
| Generated JS client (`client.mjs`) | loads as ES module in Node, exports `createClient` |
| HTML coverage report | contains endpoint table + gap candidates |
| Trace save/replay | `--save-trace` then `--replay` re-generates all artifacts fully offline |
| `run` (Tier 3 direct API) | path substitution, POST bodies, `--json/--compact/--keys-only/--grep/--limit` all work; success counters increment |
| `scrape` | correct main-content markdown extraction |
| `crawl` | BFS crawled all 6 pages, correct per-page markdown files, `--sitemap` mode works |
| `monitor` | baseline snapshot → content change → clean unified diff + watch registry. Works exactly as advertised |
| `chunk` | heading-strategy chunking correct |
| `mcp generate` + MCP protocol | spoke JSON-RPC to the generated server: `initialize`, `tools/list`, `tools/call` all execute real API calls end-to-end |
| `init` | valid Claude MCP config JSON |
| `community export` | bundle produced |
| `daemon` | JSON-RPC over Unix socket: status + graceful stop work |
| `sites list/show`, `config show`, `version` | work |

Not testable in this environment: `search` (DuckDuckGo blocked), `extract` (needs
`ANTHROPIC_API_KEY`), LLM-enhanced discovery, auth/OAuth device flow against real
providers, experiments 8–15 (network policy).

---

## Bugs found (all reproduced, with locations)

1. **Generated Python client is syntactically invalid for digit-leading hosts** —
   `src/site2cli/discovery/client_generator.py:50`. `_sanitize_name()` prefixes `_` for
   names starting with a digit, but the following `.replace("_", "")` strips it back off:
   `127.0.0.1` → `class 127001Client:` → `SyntaxError`. Affects any digit-leading domain
   (e.g. `9gag.com`). Tier 3 then silently skips the broken client. Ironically, CLAUDE.md
   documents a previous naming bug fix in this same function.

2. **Registry stores the user's relative `-o` path as `openapi_spec_path`** — after
   `discover ... -o spec.json`, running `site2cli mcp generate <domain>` from any other
   directory crashes with `FileNotFoundError: 'spec.json'`, and Tier 3 spec loading
   breaks the same way. The spec path should be resolved to absolute (or the registry
   copy under `~/.site2cli/specs/` should be authoritative).

3. **Action-name mismatch + silent browser fallback** — actions are registered as
   `GET_/api/products`, but `discover` prints `GET /api/products` and the spec/client use
   `operationId: get_api_products`. Running the natural name doesn't error — the router
   silently falls back to Tier 1 and navigates to `https://{domain}/` (dropping the
   registered `base_url`'s scheme *and* port), surfacing as a confusing Playwright
   `ERR_CONNECTION_REFUSED` traceback. Unknown actions should fail fast with the list of
   valid names; the browser fallback should honor `base_url`.

4. **robots.txt compliance fails open on non-standard ports** —
   `src/site2cli/crawl/crawler.py:41` uses `parsed.hostname` (port stripped), so
   `RobotsChecker` fetches `http://host/robots.txt` instead of `http://host:8777/robots.txt`;
   the fetch fails and the checker allows everything (`load()` swallows all exceptions).
   Verified: the crawler happily fetched `/private/secret.html` despite
   `Disallow: /private/`. Standard-port sites are unaffected, but fail-open is the wrong
   default for a compliance feature.

5. **`screenshot` is completely broken in v0.7.0** — `src/site2cli/screenshot/capture.py:60`
   calls `create_browser_context(proxy=..., profile=..., session=...)` but the factory
   (`src/site2cli/browser/context.py:21`) accepts neither `proxy` nor `session` →
   instant `TypeError` on every invocation. The 8 screenshot tests cover the model/help/
   formats but never invoke the capture path.

6. **Generated MCP tool names violate the MCP spec** — `tools/list` returns names like
   `127_get_api_users_{id}`. Tool names must match `^[a-zA-Z0-9_-]+$`; real clients
   (Claude Desktop, Claude API) will reject these tools. Path-parameter braces must be
   sanitized. Also, parameter typing is inconsistent for agents: query params are typed
   `string` while JSON-body params are typed `integer` (e.g. `limit` vs `max_results`),
   producing validation errors for the obvious call.

7. **`daemon start` doesn't daemonize** — `cli.py:1852` runs the server in the foreground
   despite the help text "Start the *background* browser daemon".

8. **Health checks give false negatives** — `src/site2cli/health/monitor.py:63` probes GET
   endpoints with `HEAD` (others with `OPTIONS`). Servers that don't implement HEAD
   (common; Python's stdlib server returns 501) are marked BROKEN even when every real
   call succeeds — observed here: all 4 endpoints FAIL while Tier 3 `run` works perfectly.

---

## Claims audit

| Claim | Verdict |
|---|---|
| "553 unit tests, all passing" | **True** (1 skipped) |
| Discover → spec → clients → MCP pipeline works | **True**, verified end-to-end with a real browser |
| "Four artifacts every run" | **True** (spec, .py client, .mjs client, HTML report) |
| "<1s per action (API)" after discovery | **True** for Tier 3 (~100ms locally) |
| "74% cheaper than browser-use" | **Simulation, not a measurement** — experiment 11 uses hardcoded cost constants ($0.05/run browser-use vs $0.0001 Tier 3, "based on industry data") |
| "2M x faster than manual" | **Arithmetic on an assumption** — experiment 10 divides an assumed 40 hours/API of manual effort by measured runtime |
| "Reliability ~15-35% on benchmarks vs >95%" | **Uncited** in README |
| "100% health check accuracy" | Measured against the experiment's own scenario set; real-world HEAD-based probes false-negative (bug #8) |
| "62% coverage of known unofficial APIs" | Plausible methodology (compares against documented endpoint lists) but not reproducible here (network) |
| CLAUDE.md internal consistency | Contradicts itself: "559 tests" in one place, "500 tests" in another |

---

## Update: all 8 bugs fixed

All bugs below were fixed on this branch and re-verified live against the same
local test site (plus 16 new regression tests; suite now 569 passing):

1. Digit-leading hosts now generate `class Site127001Client:` (valid Python).
2. `discover` stores absolute spec/client paths; `mcp generate` also falls back
   to `~/.site2cli/specs/` for legacy relative entries.
3. Action names are now canonical operationIds (`get_api_products`) shared by
   the spec, registry, clients, and MCP tools; `discover` prints the runnable
   name per endpoint; unknown actions fail fast listing valid names (with
   normalized matching for legacy `GET_/path` registries).
4. robots.txt is fetched from the full `host:port` netloc; the crawler no
   longer fetches `Disallow`ed paths on non-standard ports.
5. `screenshot` works (context factory gained a `proxy` override; capture now
   passes `session_manager`/`session_name`).
6. MCP tool names are sanitized to `^[a-zA-Z0-9_-]+$`, and query params are
   type-inferred (`limit=5` → integer) so tool schemas are consistent.
7. `daemon start` detaches by default (logs to `~/.site2cli/daemon.log`);
   `--foreground` preserves the old behavior.
8. Health checks fall back to GET when a server answers 405/501 to
   HEAD/OPTIONS — no more BROKEN reports for healthy endpoints.

## How big a deal is it?

The differentiated core — watch a site's own frontend traffic, formalize it into a typed,
agent-ready API surface (CLI + OpenAPI + clients + MCP), then never pay browser/LLM cost
again for those actions — **works as described and is genuinely useful**. That loop, plus
offline trace replay, is something Firecrawl-style scrapers don't do, and the local-first,
no-API-key posture is real.

Tempering that: it's `0.7.0` alpha-quality at the edges (one command dead on arrival, MCP
names that real clients would reject, fail-open robots), the headline benchmark numbers
are projections rather than measurements, and discovery inherently only finds what the
frontend happens to call while you browse. Treat the engineering as solid and promising,
and the marketing numbers as directional.
