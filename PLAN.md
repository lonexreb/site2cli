# Plan to implement

# site2cli: Turn Any Website Into a CLI/API for AI Agents

## Context

**Problem**: AI agents today interact with websites through browser automation (Playwright, Puppeteer, Computer Use), which is slow (10-100x), expensive (10-100x tokens), and unreliable (~15-35% success rates on academic benchmarks). This is fundamentally an impedance mismatch — agents work best with structured function calls, not visual GUIs.

**Vision**: Build a system that converts arbitrary browser-based web interactions into structured CLI commands and MCP tools, so agents can interact with any web service as effortlessly as running `gh pr create` or `aws s3 ls`.

**Goal**: Build a product/tool that bridges the gap between "browser-use (slow but works on anything)" and "hand-built CLIs (fast but expensive to build)."

---

## Research Summary

### The Landscape Today

| Category | Examples | Speed | Reliability | Generality |
|----------|----------|-------|-------------|------------|
| Hand-built CLIs | `gh`, `aws`, `stripe` | Fast | High | One service each |
| MCP servers | GitHub MCP, Slack MCP, Notion MCP | Fast | High | One service each, hand-built |
| Browser agents | browser-use, Stagehand, Skyvern | Slow | Medium (~30%) | Any website |
| Computer Use | Anthropic CU, OpenAI Operator | Very slow | Low | Anything |
| Scraping tools | Firecrawl, Crawl4AI, ScrapeGraphAI | Medium | Medium | Read-only |
| API wrappers | Apify actors, RapidAPI | Medium | Medium | Pre-built only |

**The gap**: No tool auto-generates fast, structured CLI/MCP interfaces from arbitrary websites.

### Key Existing Projects

**Browser Automation for Agents**:
- **browser-use** (~55k stars) — LLM-driven Playwright automation, DOM + vision
- **Stagehand** (~10k stars) — `act()`, `extract()`, `observe()` primitives, by Browserbase
- **Skyvern** (~10k stars) — Vision + DOM, handles complex forms
- **Playwright MCP** (Microsoft) — Browser actions exposed as MCP tools
- **Multion** — Autonomous web agent API (commercial)

**Traffic-to-API Tools**:
- **mitmproxy2swagger** (~5k stars) — Converts proxy traffic captures to OpenAPI specs
- **mitmproxy** — HTTPS proxy for intercepting browser traffic
- **openapi-generator** (~22k stars) — Generates 50+ language clients from OpenAPI specs
- **restish** (~2k stars) — Generic CLI for any API with OpenAPI spec
- **curlconverter** — Converts curl commands to SDK code

**AI-Powered Extraction**:
- **Firecrawl** (~20k stars) — Web pages to LLM-ready markdown + structured data
- **ScrapeGraphAI** (~15k stars) — LLM-powered scraping, "say what you want"
- **Crawl4AI** (~25k stars) — LLM-optimized crawler
- **Gorilla** (~11k stars) — LLM fine-tuned for API call generation

**Standards & Protocols**:
- **MCP** (Anthropic) — Protocol for exposing tools/data to AI models. 100+ servers exist. THE emerging standard.
- **A2A** (Google) — Agent-to-agent protocol, complementary to MCP. Agent Cards for discovery.
- **llms.txt** — Read-only site description for LLMs (like robots.txt). No action support.
- **OpenAPI** — Existing API description standard. Auto-generation from specs is solved.

**Infrastructure**:
- **Browserbase** (YC) — Cloud browser sessions for agents
- **Steel** — Self-hostable browser API
- **Composio** (YC) — 150+ pre-built tool integrations for agents
- **Anon** (YC) — Auth infrastructure for agents accessing web services

### Why This Hasn't Been Solved

1. **Business model conflict** — Companies want users in GUIs (ads, upsells). APIs commoditize services.
2. **Auth complexity** — OAuth, MFA, CAPTCHAs designed for humans, not agents
3. **Anti-bot arms race** — Cloudflare, fingerprinting, behavioral detection
4. **Legal gray area** — ToS prohibitions on automation (but hiQ v LinkedIn favors scraping public data)
5. **Maintenance burden** — Websites change constantly; wrappers break

---

## Product Architecture: site2cli

### Core Concept: Progressive Formalization

The system uses a 3-tier approach, automatically graduating interactions from slow-but-universal to fast-but-specific:

```
Tier 3: Direct API Calls (fastest, most reliable)
  ↑ Auto-generated from discovered API patterns
Tier 2: Cached Workflows (medium speed)
  ↑ Recorded browser workflows, parameterized + replayed
Tier 1: Browser-Use Exploration (slowest, universal)
  ↑ LLM-driven browser automation for unknown sites
```

### System Architecture

```
┌─────────────────────────────────────────────────────┐
│                    site2cli Core                       │
├──────────┬──────────────┬──────────────┬────────────┤
│  CLI     │  MCP Server  │  Python SDK  │  REST API  │
│  Layer   │  Layer       │  Layer       │  Layer     │
├──────────┴──────────────┴──────────────┴────────────┤
│                  Router / Resolver                   │
│  (Picks best available tier for a given site+action) │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌─────────────┐ ┌──────────────┐ ┌───────────────┐ │
│  │ Tier 1:     │ │ Tier 2:      │ │ Tier 3:       │ │
│  │ Browser     │ │ Cached       │ │ Direct API    │ │
│  │ Explorer    │ │ Workflows    │ │ Clients       │ │
│  │ (Playwright │ │ (Recorded    │ │ (OpenAPI-gen  │ │
│  │  + LLM)     │ │  + replay)   │ │  clients)     │ │
│  └─────────────┘ └──────────────┘ └───────────────┘ │
│                                                      │
├─────────────────────────────────────────────────────┤
│              API Discovery Engine                    │
│  ┌──────────────────────────────────────┐           │
│  │ Network Traffic Interceptor (CDP)    │           │
│  │ → Pattern Analyzer (LLM-assisted)    │           │
│  │ → OpenAPI Spec Generator             │           │
│  │ → Client Code Generator              │           │
│  └──────────────────────────────────────┘           │
├─────────────────────────────────────────────────────┤
│              Auth Manager                            │
│  (OAuth Device Flow, Cookie Jar, API Keys, Sessions) │
├─────────────────────────────────────────────────────┤
│              Site Registry / Cache                   │
│  (Known sites, their tiers, generated specs, health) │
└─────────────────────────────────────────────────────┘
```

### Component Breakdown

#### 1. CLI Layer
- Built with Python **Typer** (or **Click**)
- Dynamic command generation from site registry
- Example usage:
  ```bash
  site2cli discover kayak.com          # Explore site, discover capabilities
  site2cli kayak search-flights --from SFO --to JFK --date 2026-04-01
  site2cli amazon search "headphones" --max-price 100
  site2cli chase get-balance --account checking
  ```

#### 2. MCP Server Layer
- Exposes all discovered site capabilities as MCP tools
- Auto-generated tool schemas from OpenAPI specs
- AI agents (Claude, etc.) connect and use directly
- Example MCP tools after discovering kayak.com:
  ```json
  {"name": "kayak_search_flights", "inputSchema": {"from": "string", "to": "string", "date": "string"}}
  {"name": "kayak_get_flight_details", "inputSchema": {"flight_id": "string"}}
  ```

#### 3. API Discovery Engine (the core innovation)

**Step 1 — Traffic Capture**:
- Launch headless Playwright browser with CDP Network interception enabled
- User or LLM-agent navigates the site, performing target actions
- All XHR/Fetch requests captured with full request/response data

**Step 2 — Pattern Analysis** (LLM-assisted):
- Group captured requests by endpoint pattern
- Use LLM to infer:
  - Endpoint purpose ("this is a flight search endpoint")
  - Required vs optional parameters
  - Authentication scheme
  - Response schema

**Step 3 — OpenAPI Spec Generation**:
- Use mitmproxy2swagger as starting point
- Enhance with LLM-inferred descriptions and schemas
- Human review step for high-value sites

**Step 4 — Client Generation**:
- Generate Python client from OpenAPI spec (openapi-generator or custom)
- Wrap in CLI commands (Typer)
- Wrap as MCP server tools
- Store in site registry

#### 4. Auth Manager
- **OAuth Device Flow** for services that support it (like `gh auth login`)
- **Cookie extraction** from user's real browser (browser_cookie3)
- **Session replay** for cookie-based auth
- **API key management** with secure storage (keyring)
- **CAPTCHA handling** — prompt user when encountered, cache auth for reuse

#### 5. Site Registry
- SQLite database of discovered sites
- Stores: OpenAPI specs, generated clients, auth configs, health status
- Tracks which tier each site/action is at
- Auto-promotes actions: Tier 1 → Tier 2 → Tier 3 as patterns stabilize
- Community-contributed specs (like yt-dlp's extractor model)

### Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python (>=3.10) | Consistent with your preferences, rich ecosystem (Playwright, mitmproxy, Typer, MCP SDK) |
| Browser engine | Playwright | Best current option, Microsoft-backed, CDP support |
| CLI framework | Typer | Modern, type-annotated, auto-generates help |
| API spec format | OpenAPI 3.1 | Industry standard, massive tooling ecosystem |
| Data models | Pydantic v2 | Schema validation, JSON Schema generation |
| MCP SDK | mcp (Python) | Official Anthropic SDK |
| Storage | SQLite | Simple, no server needed, portable |
| Traffic analysis | mitmproxy2swagger + custom | Proven base, extend with LLM |
| LLM for inference | Claude API | Schema generation, pattern analysis |

### Use Case Walkthrough: Booking a Flight

**First time (Tier 1 → discovers API → graduates to Tier 3):**
```bash
# 1. User initiates discovery
$ site2cli discover kayak.com --action "search flights"

# site2cli launches Playwright, navigates kayak.com
# LLM fills in the search form with test data
# CDP captures: POST /api/search/flights {origin, dest, dates, ...}
# Captures response schema: {results: [{price, airline, ...}]}
# Generates OpenAPI spec + CLI commands

✓ Discovered 3 capabilities for kayak.com:
  - search_flights (from, to, date, passengers, cabin_class)
  - get_flight_details (flight_id)
  - get_price_history (route, date_range)

# 2. Now the agent (or user) can use it directly
$ site2cli kayak search-flights --from SFO --to JFK --date 2026-04-01

# This now uses the discovered API directly (Tier 3)
# No browser needed, returns structured JSON in ~200ms
```

**As MCP tool for AI agents:**
```
Agent: "Find me the cheapest flight from SFO to JFK next Friday"
→ Calls MCP tool: kayak_search_flights(from="SFO", to="JFK", date="2026-04-04")
→ Gets structured JSON response in 200ms
→ "The cheapest flight is United UA456 at $189, departing 6:00 AM"
```

---

## Implementation Plan

### Phase 1: Core Foundation (Week 1-2) ✅ COMPLETE

**Files created:**
- `pyproject.toml` — Project setup with deps
- `src/site2cli/__init__.py`
- `src/site2cli/cli.py` — Typer CLI entry point
- `src/site2cli/config.py` — Configuration management
- `src/site2cli/registry.py` — Site registry (SQLite)
- `src/site2cli/models.py` — Pydantic models for specs, sites, actions

**What it does:**
- Basic CLI skeleton (`site2cli --help`)
- Site registry CRUD
- Config management (API keys, storage paths)

### Phase 2: Traffic Capture & API Discovery (Week 3-4) ✅ COMPLETE

**Files created:**
- `src/site2cli/discovery/capture.py` — CDP-based network traffic capture
- `src/site2cli/discovery/analyzer.py` — LLM-assisted pattern analysis
- `src/site2cli/discovery/spec_generator.py` — OpenAPI spec generation
- `src/site2cli/discovery/client_generator.py` — Python client from spec

**What it does:**
- `site2cli discover <url>` launches browser, captures traffic
- Groups requests into endpoint patterns
- Generates OpenAPI spec from captured traffic
- Generates Python client code

### Phase 3: CLI & MCP Generation (Week 5-6) ✅ COMPLETE

**Files created:**
- `src/site2cli/generators/cli_gen.py` — Dynamic CLI command generation from specs
- `src/site2cli/generators/mcp_gen.py` — MCP server generation from specs
- `src/site2cli/auth/manager.py` — Auth flow management

**What it does:**
- Auto-generates CLI commands from discovered APIs
- Auto-generates MCP server with tools for each discovered action
- Auth handling (cookie extraction, OAuth device flow)

### Phase 4: Progressive Formalization (Week 7-8) ✅ COMPLETE

**Files created:**
- `src/site2cli/tiers/browser_explorer.py` — Tier 1: LLM-driven browser
- `src/site2cli/tiers/cached_workflow.py` — Tier 2: Recorded workflows
- `src/site2cli/tiers/direct_api.py` — Tier 3: Direct API calls
- `src/site2cli/router.py` — Tier router (picks best available method)

**What it does:**
- Tier 1: Falls back to browser-use for unknown sites
- Tier 2: Records and replays parameterized workflows
- Tier 3: Uses generated API clients directly
- Router automatically picks the best tier
- Auto-promotion from Tier 1 → 2 → 3 as patterns stabilize

### Phase 5: Community & Polish (Week 9-10) ✅ COMPLETE

**Files created:**
- `src/site2cli/community/registry.py` — Community spec sharing
- `src/site2cli/health/monitor.py` — API health checking
- `src/site2cli/health/self_heal.py` — LLM-powered breakage detection + repair

**What it does:**
- Share/import community-contributed site specs (like yt-dlp extractors)
- Health monitoring for discovered APIs
- Self-healing when sites change their APIs

---

## Verification & Testing

1. **Unit tests**: Test each component in isolation (capture, analyze, generate) — ✅ 150 tests passing across 14 test files
2. **Integration test — simple site**: Full pipeline test with mock JSONPlaceholder-like traffic — ✅ 12 tests passing (`test_integration_pipeline.py`)
3. **Integration test — real site**: Live tests against jsonplaceholder.typicode.com and httpbin.org — ✅ 6 tests passing (`test_integration_live.py`)
4. **MCP test**: Generated MCP server code validates (syntax + structure) — ✅ Covered in pipeline + live tests + `test_generated_code.py` (8 tests)
5. **CLI test**: CLI commands tested via Typer CliRunner — ✅ 17 tests passing (`test_cli.py`)
6. **Tier promotion test**: Tier fallback order, action finding, auto-promotion after 5 successes, no promotion with failures — ✅ 6 tests passing (`test_tier_promotion.py`)
7. **Config test**: Config singleton, dirs, YAML save/load, API key from env — ✅ 8 tests (`test_config.py`)
8. **Auth test**: Keyring store/get, auth headers, cookie extraction — ✅ 11 tests (`test_auth.py`)
9. **Health test**: Health check with mock httpx, status persistence — ✅ 8 tests (`test_health.py`)
10. **Router test**: Router execution, fallback, promotion, param forwarding — ✅ 15 tests (`test_router.py`)
11. **Community test**: Export/import roundtrip, community listing — ✅ 6 tests (`test_community.py`)

**Total: 156 tests, all passing** (150 unit/integration + 6 live)

### Bugs Found & Fixed by Integration Tests
- `models.py`: `example_response` typed as `dict | None` but API responses can be arrays — fixed to `dict | list | None`
- `analyzer.py`: Query params only extracted from first exchange in endpoint group — fixed to merge across all exchanges
- `mcp_gen.py`: f-string brace escaping bug in generated code — replaced with `"\n".join()` approach
- `test_integration_live.py`: Generated client `close()` method hit before API methods — fixed by skipping utility methods

---

## Key Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Sites block automation | Stealth plugins (playwright-stealth), rotating proxies, user's real cookies |
| Generated APIs break when sites change | Health monitoring + LLM self-healing |
| Auth complexity | Start with simple sites, support cookie extraction from user's browser |
| Legal concerns | Focus on sites with existing APIs or user's own accounts; respect robots.txt |
| LLM costs for discovery | One-time cost per site; cache everything; community sharing |

---

## Tech Stack Summary

```
Python >=3.10
├── Typer (CLI)
├── Playwright (browser automation + CDP)
├── mitmproxy (traffic interception)
├── mitmproxy2swagger (traffic → OpenAPI)
├── openapi-generator (OpenAPI → client code)
├── Pydantic v2 (data models)
├── MCP Python SDK (MCP server)
├── anthropic SDK (LLM for analysis)
├── SQLite (site registry)
├── browser-use (Tier 1 fallback)
├── browser_cookie3 (cookie extraction)
├── keyring (secure credential storage)
├── pytest + pytest-asyncio (testing)
└── ruff (linting)
```
