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
├── generators/
│   ├── cli_gen.py      # Dynamic CLI command generation
│   └── mcp_gen.py      # MCP server generation
├── auth/
│   └── manager.py      # Auth flow management
├── tiers/
│   ├── browser_explorer.py  # Tier 1: LLM-driven browser
│   ├── cached_workflow.py   # Tier 2: Recorded workflow replay
│   └── direct_api.py        # Tier 3: Direct API calls
├── health/
│   ├── monitor.py      # API health checking
│   └── self_heal.py    # LLM-powered breakage repair
└── community/
    └── registry.py     # Community spec sharing
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
pytest                    # 150 unit/integration tests (no network)
pytest -m live            # 6 live tests (hits jsonplaceholder + httpbin)
pytest -v                 # Verbose output
```

**Test files:**
- `test_models.py` — Pydantic model validation (15 tests)
- `test_registry.py` — SQLite registry CRUD (10 tests)
- `test_analyzer.py` — Traffic analysis & grouping (24 tests)
- `test_spec_generator.py` — OpenAPI spec generation (6 tests)
- `test_client_generator.py` — Python client code gen (4 tests)
- `test_cli.py` — CLI commands via CliRunner (17 tests)
- `test_integration_pipeline.py` — Full pipeline with mock data (12 tests)
- `test_integration_live.py` — Live API tests, marked `@pytest.mark.live` (6 tests)
- `test_tier_promotion.py` — Tier fallback & auto-promotion (6 tests)
- `test_config.py` — Config singleton, dirs, YAML save/load (8 tests)
- `test_auth.py` — Keyring store/get, auth headers (11 tests)
- `test_health.py` — Health check with mock httpx (8 tests)
- `test_router.py` — Router execution, fallback, promotion (15 tests)
- `test_community.py` — Export/import roundtrip (6 tests)
- `test_generated_code.py` — compile() validation (8 tests)

**Total: 156 tests (150 + 6 live), all passing.**

## Optional Dependencies

Heavy deps are optional to keep base install lightweight:
- `site2cli[browser]` — Playwright, browser-cookie3
- `site2cli[llm]` — Anthropic SDK
- `site2cli[mcp]` — MCP Python SDK
- `site2cli[all]` — Everything
- `site2cli[dev]` — All + pytest, ruff, mypy

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
