# Research & Experiment Log

Records of experiments, findings, and learnings during WebCLI development.

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
- CLI installs and runs (`webcli --help` shows all commands)
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

## Experiment #2: Real Site Discovery (TODO)

**Date**: TBD
**Status**: Planned

### Hypothesis
The discovery pipeline can extract useful API endpoints from real-world sites like Hacker News, GitHub, or a weather API.

### Plan
1. Run `webcli discover news.ycombinator.com` and evaluate discovered endpoints
2. Run `webcli discover httpbin.org` as a controlled test (known API surface)
3. Compare generated OpenAPI spec against actual API documentation
4. Measure: endpoint count, parameter accuracy, schema correctness

### Success Criteria
- Discover at least 3 valid endpoints from HN
- Generated client can make successful API calls
- OpenAPI spec validates against openapi-spec-validator

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
2. Generate MCP server with `webcli mcp generate`
3. Configure Claude Code to use the generated MCP server
4. Ask Claude to perform actions using the generated tools

### Success Criteria
- MCP server starts and responds to tool listing
- Claude can call at least 2 generated tools successfully
- Response latency < 500ms for direct API calls (Tier 3)

---

## Experiment #5: Tier Promotion Cycle (TODO)

**Date**: TBD
**Status**: Planned

### Hypothesis
The router correctly falls back through tiers and auto-promotes actions after consistent success.

### Plan
1. Register a site with actions at Tier 1 (browser only)
2. Execute actions multiple times via router
3. Verify tier promotion: Browser → Workflow → API
4. Introduce a simulated API breakage, verify fallback to lower tier

### Success Criteria
- Action auto-promotes to Tier 2 after 5 successes at Tier 1
- Fallback works when higher tier fails
- Health monitor detects the breakage

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

## Learnings & Mistakes

### L1: pytest-asyncio version compatibility (2026-03-11)
The `asyncio_mode = "auto"` config requires pytest-asyncio >= 0.21. Older versions need explicit `@pytest.mark.asyncio` decorators. Pinned to >= 0.24 in pyproject.toml.

### L2: Hatchling requires README.md to exist (2026-03-11)
Even with `readme = "README.md"` in pyproject.toml, hatchling fails the build if the file doesn't exist. Must create it before `pip install -e .`.

### L3: pip 21.x doesn't support hatchling editable installs (2026-03-11)
Python 3.10 ships with pip 21.2.3 which can't do PEP 660 editable installs with hatchling. Must `pip install --upgrade pip` first.
