# WebCLI

Turn any website into a CLI/API for AI agents.

## Architecture

Progressive Formalization: 3-tier system that auto-graduates from browser automation (Tier 1) → cached workflows (Tier 2) → direct API calls (Tier 3).

## Project Structure

```
src/webcli/
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

## Key Docs

- `PLAN.md` — Full architecture plan, research bible, implementation phases
- `RESEARCH-EXPERIMENT.md` — Experiment records, findings, learnings & mistakes
- `CLAUDE.md` — This file; conventions and project structure

## Running

```bash
pip install -e ".[dev]"
pytest
webcli --help
```
