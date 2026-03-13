# Research & Experiment Log

Records of experiments, findings, and learnings during site2cli development.

---

## Experiment #1: Project Scaffolding & Core Architecture

**Date**: 2026-03-11
**Status**: Complete

### Hypothesis
A 3-tier progressive formalization architecture (Browser → Workflow → API) can be built as a single Python CLI tool that auto-discovers website APIs from network traffic.

### Setup
- Python 3.10, Typer CLI, Pydantic v2, Playwright, SQLite
- 18 source files across 7 modules
- 5 test files, 45 unit tests

### Results
- All 45 tests pass in 0.58s
- CLI installs and runs (`site2cli --help` shows all commands)
- Full pipeline implemented: capture → analyze → spec generate → client generate → register

### Key Findings
1. **CDP Network interception** works well for capturing XHR/Fetch traffic — no need for mitmproxy as a separate process
2. **Path normalization** (numeric IDs, UUIDs → `{id}`) is sufficient for basic endpoint grouping without LLM
3. **JSON Schema inference** from sample responses works for simple cases but will need LLM enhancement for complex/nested schemas
4. **Pydantic v2** model_dump_json/model_validate_json roundtrip is clean for SQLite storage of complex objects (endpoints stored as JSON blobs)

### Open Questions
- How well does CDP capture work on SPAs with WebSocket-heavy communication?
- What's the false positive rate for API-like request detection on ad-heavy sites?
- Does browser_cookie3 still work with latest Chrome cookie encryption (2025+)?

---

## Experiment #2: Pipeline Integration & Real Site Discovery

**Date**: 2026-03-12
**Status**: Complete

### Hypothesis
The discovery pipeline can extract useful API endpoints from real-world sites and the full pipeline works end-to-end (traffic → analysis → spec → client → MCP server).

### Setup
- Mock traffic data simulating JSONPlaceholder API (GET /posts, GET /posts?userId=1, POST /posts, GET /posts/1)
- Live HTTP requests against jsonplaceholder.typicode.com and httpbin.org
- Full pipeline test: capture → analyze → group → extract → spec generate → client generate → MCP generate → register

### Results
- **11 pipeline tests** pass with mock data (steps 1-10 + full end-to-end)
- **6 live tests** pass against real APIs
- Generated client successfully calls JSONPlaceholder API and returns JSON data
- Generated OpenAPI specs have correct structure (paths, parameters, schemas)
- Generated MCP server code is valid Python with correct tool registrations
- httpbin.org: correctly discovers GET /get and POST /post endpoints with all params

### Key Findings
1. **Query param merging is essential** — when multiple exchanges hit the same endpoint with different query params (e.g., `/posts` and `/posts?userId=1`), all params must be collected across exchanges, not just from the first one
2. **Response types vary** — API responses can be JSON arrays (not just objects). The `example_response` field needed `dict | list | None` typing
3. **Code generation brace escaping** — f-strings containing `{key}` intended for the *generated* code get evaluated at generation time. String concatenation (`"{" + key + "}"`) avoids this
4. **Generated client method iteration** — when probing generated clients for callable methods, utility methods like `close()` must be skipped

### Bugs Found
- `models.py`: `example_response: dict | None` → `dict | list | None`
- `analyzer.py`: Query params only from first exchange → merged across all exchanges in group
- `mcp_gen.py`: f-string brace escaping → replaced with `"\n".join(code_parts)` approach
- Test: `close()` method called before API methods when iterating `dir(client)` alphabetically

---

## Experiment #3: LLM Enhancement Quality (TODO)

**Date**: TBD
**Status**: Planned

### Hypothesis
LLM-assisted analysis significantly improves endpoint descriptions and parameter identification compared to purely heuristic analysis.

### Plan
1. Run analyzer on captured traffic WITHOUT LLM enhancement
2. Run same traffic WITH LLM enhancement (Claude Sonnet)
3. Compare: description quality, parameter name accuracy, required/optional correctness
4. Measure LLM token usage and cost per site discovery

### Success Criteria
- LLM descriptions are meaningfully better than heuristic names
- Cost per discovery is < $0.10 for typical sites
- LLM doesn't hallucinate non-existent endpoints

---

## Experiment #4: MCP Server Integration (TODO)

**Date**: TBD
**Status**: Planned

### Hypothesis
Generated MCP servers are functional and can be used by Claude to perform real web actions.

### Plan
1. Discover a simple API (httpbin.org or JSONPlaceholder)
2. Generate MCP server with `site2cli mcp generate`
3. Configure Claude Code to use the generated MCP server
4. Ask Claude to perform actions using the generated tools

### Success Criteria
- MCP server starts and responds to tool listing
- Claude can call at least 2 generated tools successfully
- Response latency < 500ms for direct API calls (Tier 3)

---

## Experiment #5: Tier Promotion Cycle

**Date**: 2026-03-12
**Status**: Complete

### Hypothesis
The router correctly falls back through tiers and auto-promotes actions after consistent success.

### Setup
- SQLite registry with test sites at various tiers
- Router with `_maybe_promote()` method
- `_tier_fallback_order()` for deterministic fallback ordering

### Results
- **9 tests** passing in `test_tier_promotion.py`
- Tier fallback order is correct: API → [API, WORKFLOW, BROWSER], WORKFLOW → [WORKFLOW, BROWSER, API], BROWSER → [BROWSER, API, WORKFLOW]
- Action finding works for existing and missing actions
- No promotion with fewer than 5 successes
- Promotion from BROWSER → WORKFLOW after 5 consecutive successes
- No promotion when failure_count > 0 (even with enough successes)
- API tier (highest) does not promote further

### Key Findings
1. **Promotion threshold of 5** is a good balance — enough to establish reliability without making users wait too long
2. **Failure count as a gate** is important — a single failure resets confidence, preventing premature promotion of unreliable endpoints
3. **API tier ceiling** prevents over-promotion — actions at the highest tier stay there

---

## Experiment #6: Self-Healing on API Change (TODO)

**Date**: TBD
**Status**: Planned

### Hypothesis
The self-healing system can detect and repair endpoint changes (path renames, parameter changes) without manual intervention.

### Plan
1. Discover API for a test site
2. Modify the test site's API (rename path, add parameter)
3. Trigger health check → should detect breakage
4. Run self-heal → should re-discover and update endpoint

### Success Criteria
- Detects breakage within one health check cycle
- Correctly identifies the new endpoint via LLM matching
- Updated endpoint works for subsequent calls

---

## Experiment #7: Full Rename (webcli → site2cli) + Test Expansion + README Overhaul

**Date**: 2026-03-13
**Status**: Complete

### Hypothesis
A comprehensive rename, test expansion (71 → 156), and README overhaul will bring the project to a publishable, professional state matching competitors like CLI-Anything.

### Changes Made

**Rename (webcli → site2cli):**
- Renamed `src/webcli/` → `src/site2cli/`, updated all imports and string references across 25 source files and 15 test files
- Updated `pyproject.toml` entry points, build paths, and GitHub URLs
- Added backward compatibility: data dir auto-migration (`~/.webcli/` → `~/.site2cli/`), keyring service fallback, community bundle format compat (`.webcli.json` still accepted)
- Renamed GitHub repo via `gh repo rename site2cli`

**Test Expansion (71 → 156 tests):**
- Created 6 new test files: `test_config.py` (8), `test_auth.py` (11), `test_health.py` (8), `test_router.py` (15), `test_community.py` (6), `test_generated_code.py` (8)
- Expanded 3 existing files: `test_analyzer.py` (+12), `test_cli.py` (+12), `test_models.py` (+7)
- Total: 150 unit/integration + 6 live = 156 tests

**README Overhaul:**
- Banner image, shields.io badges (CI, PyPI, Python, License, Tests)
- Problem comparison table, 3 Mermaid diagrams, feature comparison vs competitors
- Full testing table with per-file breakdown

### Key Findings
1. **Backward compat matters** — keyring entries and data dirs from old installs would silently break without fallback reads
2. **Community bundle format** needs both old and new extensions accepted for smooth migration
3. **Test count** went from 71 → 156 with good coverage of previously untested modules (config, auth, health, router, community, generated code)

---

## Learnings & Mistakes

### L1: pytest-asyncio version compatibility (2026-03-11)
The `asyncio_mode = "auto"` config requires pytest-asyncio >= 0.21. Older versions need explicit `@pytest.mark.asyncio` decorators. Pinned to >= 0.24 in pyproject.toml.

### L2: Hatchling requires README.md to exist (2026-03-11)
Even with `readme = "README.md"` in pyproject.toml, hatchling fails the build if the file doesn't exist. Must create it before `pip install -e .`.

### L3: pip 21.x doesn't support hatchling editable installs (2026-03-11)
Python 3.10 ships with pip 21.2.3 which can't do PEP 660 editable installs with hatchling. Must `pip install --upgrade pip` first.

### L4: f-string brace escaping in code generators (2026-03-12)
When generating Python code that contains `{variable}` expressions (like `placeholder = "{" + key + "}"`), using f-strings causes the braces to be evaluated at generation time. Either use string concatenation inside the generated code, or build lines as plain strings and join them. The `"\n".join(code_parts)` pattern is cleaner than deeply nested f-string escaping (`{{{{{key}}}}}`).

### L5: Test iteration order matters for generated code (2026-03-12)
`dir(obj)` returns attributes alphabetically. When probing a generated client for callable API methods, utility methods like `close()` come before API methods like `get_posts()`. Always filter out known utility/lifecycle methods before testing.

### L6: API response types are not always objects (2026-03-12)
Many REST APIs return JSON arrays at the top level (e.g., `GET /posts` returns `[{...}, {...}]`). Pydantic models that store example responses must accept `dict | list | None`, not just `dict | None`.

### L7: Query parameter extraction needs cross-exchange merging (2026-03-12)
When grouping HTTP exchanges by endpoint pattern, different exchanges to the same endpoint may have different query parameters. Extracting params from only the first exchange misses optional params that appear in later requests. Must iterate all exchanges in the group.
