# Contributing to site2cli

Thanks for thinking about contributing. site2cli is MIT-licensed and built in the open. Even one-line doc fixes get merged.

## Quick Setup

```bash
git clone https://github.com/lonexreb/site2cli.git
cd site2cli
pip install -e ".[dev]"

pytest                  # 553 offline tests, should finish in <8s
pytest -m live          # 6 live tests (hits jsonplaceholder + httpbin)
ruff check src/ tests/
```

## Good First Issues

Pick whichever fits your background.

| Area | Examples |
|---|---|
| **Discovery adapters** | `HAR` file ingest in `src/site2cli/discovery/trace.py`; Bruno / Postman collection exporters from OpenAPI |
| **Code generators** | TypeScript client (mirror `js_client_generator.py`); Go client; `curl` snippets per endpoint |
| **RAG** | Token-based chunking (`tiktoken`), sliding-window sentence chunker, code-block-aware splitter in `src/site2cli/content/chunker.py` |
| **Search backends** | Brave Search, SearXNG, Bing Web Search adapters next to `src/site2cli/search/engine.py` |
| **Browser** | Firefox profile import (Chrome already supported), Safari cookie import in `src/site2cli/auth/profiles.py` |
| **Docs** | Recipe cookbook in `docs/`, more demo GIFs in `assets/`, walkthroughs for popular SaaS APIs |

## Pull Request Checklist

Before opening a PR:

- [ ] `pytest` passes locally
- [ ] `ruff check src/ tests/` is clean
- [ ] New behavior has a test (we keep coverage tight — currently 559 tests)
- [ ] Public functions have type annotations
- [ ] No new top-level dependencies without discussion — add to `pyproject.toml` optional extras instead
- [ ] README updated when you add a new CLI command or flag

## Reporting Issues

Please include:

1. site2cli version (`site2cli --version`)
2. Python version (`python --version`)
3. OS and architecture
4. The exact command you ran
5. The full output (use `--no-headless` for browser issues, redact secrets)
6. The site you were targeting if it's public

## Adding a New CLI Command

Pattern (mirroring `chunk`, `search`, `discover`):

1. Implement the core logic under `src/site2cli/<feature>/` as plain Python — no Typer imports.
2. Wire a Typer entry in `src/site2cli/cli.py`.
3. Add tests under `tests/test_<feature>.py`.
4. Add a section to `README.md` under the relevant family (extraction / discovery / RAG / etc).
5. Tick the roadmap item in `README.md`.

## Adding a New OpenAPI Output Format

The generator pipeline lives in `src/site2cli/discovery/`. Each output is one file:

- `spec_generator.py` — OpenAPI 3.1 (`.json` / `.yaml`)
- `client_generator.py` — Python client
- `js_client_generator.py` — JavaScript ES module
- `coverage_report.py` — HTML report

Add a sibling module (e.g. `ts_client_generator.py`), wire it into the `discover` command in `cli.py`, and add a test in `tests/test_browser_to_api.py`.

## Code Style

- `ruff` for lint (config in `pyproject.toml`)
- Type hints on all public functions
- Pydantic v2 for data models
- Prefer many small files to few large ones; soft target 200–400 lines, hard ceiling 800

## License

By contributing, you agree your contributions are licensed under MIT.
