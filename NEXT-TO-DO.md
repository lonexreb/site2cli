# Next Steps — Post v0.3.0

## 5-Step Roadmap

- [x] **Step 1: Claude Code MCP Integration** — `site2cli --mcp` works e2e (11 tools, real API calls), docs added
- [x] **Step 2: LLM-Driven Exploration (`--action`)** — REST Countries: LLM found /v3.1/all in 8 steps. Open Library: LLM searched in 4 steps (SSR, no API)
- [x] **Step 3: End-to-End "Discover Then Run"** — httpbin, JSONPlaceholder, PokeAPI all return real data via Router
- [x] **Step 4: Community Spec Export/Import** — Export/remove/reimport roundtrip works, API calls succeed from imported spec
- [x] **Step 5: Terminal Demo GIF** — Recorded with asciinema, converted to GIF (assets/demo.gif, 416K)

## All Steps Complete

### Key Results
| Step | Result |
|------|--------|
| 1 | Fixed tool name sanitization + Console.print bug. 11 MCP tools from 3 sites, real PokeAPI data (39K chars) |
| 2 | LLM exploration validated for API-backed sites. SSR sites correctly return 0 API exchanges |
| 3 | Router executes actions via Tier 3 (direct API) — httpbin (IP lookup), JSONPlaceholder (100 posts), PokeAPI (39K Pokemon data) |
| 4 | 3,331-byte bundle exported → removed from registry → reimported → API call succeeds (25K chars) |
| 5 | asciinema recording → agg GIF conversion, demo.gif in assets/ |
