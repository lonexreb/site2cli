# site2cli

Turn any website into a CLI/API for AI agents.

## Architecture

Progressive Formalization: 3-tier system that auto-graduates from browser automation (Tier 1) → cached workflows (Tier 2) → direct API calls (Tier 3).

## Project Structure

```
src/site2cli/
├── cli.py              # Typer CLI entry point
├── config.py           # Configuration management
├── models.py           # Pydantic v2 data models
├── registry.py         # SQLite site registry
├── router.py           # Tier router (picks best execution method)
├── discovery/
│   ├── capture.py      # CDP-based network traffic capture
│   ├── analyzer.py     # LLM-assisted pattern analysis
│   ├── spec_generator.py  # OpenAPI spec generation
│   └── client_generator.py # Python client code generation
├── browser/
│   ├── retry.py        # Async retry with delay for browser actions
│   ├── wait.py         # Rich wait conditions (network-idle, selector, stable)
│   ├── cookie_banner.py # Cookie consent auto-dismissal (3 strategies)
│   ├── detectors.py    # Auth/SSO/CAPTCHA page detection
│   ├── a11y.py         # Accessibility tree extraction + indexed [@N] notation
│   ├── context.py      # Unified browser context factory (profiles + sessions)
│   └── session.py      # Named browser session persistence and reuse
├── output_filter.py    # Output filtering (grep, limit, keys-only)
├── generators/
│   ├── cli_gen.py      # Dynamic CLI command generation
│   ├── mcp_gen.py      # MCP server generation
│   └── agent_config.py # Agent config generation (Claude MCP, generic)
├── content/
│   └── converter.py    # HTML to markdown/text conversion, main content extraction
├── crawl/
│   ├── crawler.py      # Async BFS site crawler with resume and streaming
│   ├── links.py        # Link extraction and normalization from HTML
│   └── robots.py       # robots.txt parser and URL filtering
├── extract/
│   └── extractor.py    # LLM-powered structured extraction with schema validation
├── monitor/
│   ├── watcher.py      # Change detection with snapshot comparison and webhooks
│   └── differ.py       # Line-level diff engine (stdlib difflib)
├── screenshot/
│   └── capture.py      # Full-page and element screenshots via Playwright
├── auth/
│   ├── manager.py      # Auth flow management (Playwright cookie format)
│   ├── cookies.py      # Cookie CRUD, import/export (Playwright-compatible)
│   ├── profiles.py     # Chrome/Firefox profile detection & import
│   ├── device_flow.py  # OAuth device flow (RFC 8628)
│   └── providers.py    # Pre-configured OAuth providers (GitHub, Google, Microsoft)
├── tiers/
│   ├── browser_explorer.py  # Tier 1: LLM-driven browser
│   ├── cached_workflow.py   # Tier 2: Recorded workflow replay
│   └── direct_api.py        # Tier 3: Direct API calls
├── daemon/
│   ├── server.py       # Background browser daemon (JSON-RPC over Unix socket)
│   └── client.py       # Daemon client for CLI commands
├── mcp/
│   └── server.py       # Unified MCP server for ALL discovered sites
├── orchestration/
│   ├── data_flow.py    # JSONPath-like data extraction between pipeline steps
│   ├── loader.py       # YAML/JSON pipeline loading
│   └── orchestrator.py # Sequential pipeline executor with error policies
├── health/
│   ├── monitor.py      # API health checking
│   └── self_heal.py    # LLM-powered breakage repair
└── community/
    └── registry.py     # Community spec sharing

experiments/
├── experiment_8_live_validation.py   # Live validation against 5 real APIs
├── experiment_9_api_breadth.py       # Breadth test across 10 diverse APIs
├── experiment_10_unofficial_api_benchmark.py  # Coverage vs known unofficial APIs
├── experiment_11_speed_cost_benchmark.py      # Speed, cost, throughput benchmarks
├── experiment_12_mcp_validation.py   # Deep MCP server validation
├── experiment_13_spec_accuracy.py    # Spec accuracy vs ground truth
├── experiment_14_resilience.py       # Health monitoring & resilience
├── experiment_15_live_browser_validation.py  # Real Playwright browser → CDP capture pipeline
└── run_all_experiments.py            # Master runner for all experiments
```

## Conventions

- Python >=3.10, type hints everywhere
- Pydantic v2 for all data models
- async/await for I/O-bound operations
- Typer for CLI, Rich for output formatting
- SQLite for local storage (no server deps)
- ruff for linting

## Testing

```bash
pytest                    # 494 unit/integration tests (no network)
pytest -m live            # 6 live tests (hits jsonplaceholder + httpbin)
pytest -v                 # Verbose output
```

**Test files:**
- `test_analyzer.py` — Traffic analysis & grouping (23 tests)
- `test_cli.py` — CLI commands via CliRunner (16 tests)
- `test_models.py` — Pydantic model validation (15 tests)
- `test_router.py` — Router execution, fallback, promotion (15 tests)
- `test_cookie_banner.py` — Cookie banner detection & dismissal (12 tests)
- `test_auth.py` — Keyring store/get, auth headers (11 tests)
- `test_integration_pipeline.py` — Full pipeline with mock data (11 tests)
- `test_registry.py` — SQLite registry CRUD (10 tests)
- `test_wait_conditions.py` — Rich wait conditions (10 tests)
- `test_detectors.py` — Auth/CAPTCHA page detection (10 tests)
- `test_tier_promotion.py` — Tier fallback & auto-promotion (9 tests)
- `test_config.py` — Config singleton, dirs, YAML save/load (8 tests)
- `test_health.py` — Health check with mock httpx (8 tests)
- `test_generated_code.py` — compile() validation (8 tests)
- `test_retry.py` — Async retry utility (8 tests)
- `test_a11y.py` — Accessibility tree extraction (8 tests)
- `test_output_filter.py` — Output filtering (grep, limit, keys-only) (8 tests)
- `test_agent_config.py` — Agent config generation (8 tests)
- `test_spec_generator.py` — OpenAPI spec generation (6 tests)
- `test_community.py` — Export/import roundtrip (6 tests)
- `test_integration_live.py` — Live API tests, marked `@pytest.mark.live` (6 tests)
- `test_client_generator.py` — Python client code gen (4 tests)
- `test_cookies.py` — Cookie CRUD, import/export, migration (23 tests)
- `test_workflow_recorder.py` — Workflow recording, parameterization, CRUD (15 tests)
- `test_mcp_server.py` — Unified MCP server, tool schemas, registry (14 tests)
- `test_profiles.py` — Chrome/Firefox profile detection, import (12 tests)
- `test_daemon.py` — Daemon server lifecycle, JSON-RPC protocol (12 tests)
- `test_session.py` — Named session persistence and reuse (10 tests)
- `test_content_converter.py` — HTML-to-markdown/text conversion, main content extraction (21 tests)
- `test_extract.py` — Schema loading, validation, extraction prompt building (26 tests)
- `test_proxy.py` — ProxyConfig: URL building, Playwright/httpx formats, auth (13 tests)
- `test_data_flow.py` — JSONPath extraction, data flow between pipeline steps (17 tests)
- `test_device_flow.py` — OAuth device code request, polling, token refresh (14 tests)
- `test_orchestrator.py` — Pipeline execution, error policies, step result tracking (12 tests)
- `test_providers.py` — OAuth provider configs (GitHub, Google, Microsoft) (8 tests)
- `test_crawl.py` — Link extraction, BFS crawler, dedup, resume, formats (35 tests)
- `test_crawl_robots.py` — robots.txt parsing, allow/disallow, sitemaps (12 tests)
- `test_monitor.py` — Diff computation, watcher, webhook, registry CRUD (41 tests)
- `test_screenshot.py` — Screenshot model, CLI help, formats (8 tests)

**Total: 500 tests (494 + 6 live), all passing.**

## Live Validation (8 Experiments)

Full pre-launch validation suite: `python experiments/run_all_experiments.py`

| # | Experiment | What It Proves |
|---|-----------|----------------|
| 8 | Live Validation | 5 APIs, full pipeline end-to-end |
| 9 | API Breadth | 10 diverse APIs (33 endpoints), 7 categories |
| 10 | Unofficial API Benchmark | 62% coverage of known APIs, 2M x faster than manual |
| 11 | Speed & Cost | 74% cheaper than browser-use, 80% time in HTTP capture |
| 12 | MCP Validation | 20 tools, 14/14 quality checks, schema-spec match |
| 13 | Spec Accuracy | 80% accuracy vs ground truth (5 APIs) |
| 14 | Resilience | 100% health check accuracy, drift detection, bundle integrity |
| 15 | Live Browser Discovery | Real Playwright browser → CDP capture → full pipeline (5 sites) |

Experiments 8-14 pass in ~74 seconds. Experiment 15 requires `site2cli[browser]` + Chromium.

## Backward Compatibility (webcli → site2cli)

The project was renamed from `webcli` to `site2cli`. These migration paths exist:
- **Data dir**: `config.py` auto-migrates `~/.webcli/` → `~/.site2cli/` on first run
- **Keyring**: `auth/manager.py` falls back to old `"webcli"` keyring service when credentials aren't found under `"site2cli"`
- **Community bundles**: `community/registry.py` accepts both `.site2cli.json` and `.webcli.json` bundle formats

## Optional Dependencies

Heavy deps are optional to keep base install lightweight:
- `site2cli[browser]` — Playwright, browser-cookie3
- `site2cli[llm]` — Anthropic SDK
- `site2cli[mcp]` — MCP Python SDK
- `site2cli[content]` — markdownify for HTML conversion
- `site2cli[all]` — Everything (browser, llm, mcp, content)
- `site2cli[dev]` — All + pytest, ruff, mypy

## Bug Fixes

- **client_generator.py**: Fixed Python syntax error where required params could follow optional params in generated methods. Required params are now sorted before optional ones.

## Key Docs

- `PLAN.md` — Full architecture plan, research bible, implementation phases
- `RESEARCH-EXPERIMENT.md` — Experiment records, findings, learnings & mistakes
- `RESEARCH-DEEP-DIVE.md` — Market analysis (Perplexity, WebMCP, competitive landscape)
- `CLAUDE.md` — This file; conventions and project structure

## Running

```bash
pip install -e ".[dev]"
pytest
site2cli --help
```
