<p align="center">
  <img src="assets/banner.png" alt="site2cli" width="100%">
</p>

<p align="center">
  <strong>Turn any website into a CLI/API for AI agents.</strong>
</p>

<p align="center">
  <a href="https://github.com/lonexreb/site2cli/actions/workflows/ci.yml"><img src="https://github.com/lonexreb/site2cli/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/site2cli/"><img src="https://img.shields.io/pypi/v/site2cli" alt="PyPI"></a>
  <a href="https://pypi.org/project/site2cli/"><img src="https://img.shields.io/pypi/pyversions/site2cli" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/lonexreb/site2cli" alt="License"></a>
  <a href="#testing"><img src="https://img.shields.io/badge/tests-156_passing-brightgreen" alt="Tests"></a>
</p>

---

## The Problem

AI agents interact with websites through browser automation, which is slow, expensive, and unreliable:

| | Without site2cli | With site2cli |
|---|---|---|
| **Speed** | 10-30s per action (browser) | <1s per action (API) |
| **Cost** | Thousands of LLM tokens per page | Zero tokens for cached actions |
| **Reliability** | ~15-35% on benchmarks | >95% for discovered APIs |
| **Setup** | Write custom Playwright scripts | `site2cli discover <url>` |
| **Output** | Screenshots, raw HTML | Structured JSON, typed clients |

## How It Works

site2cli uses **Progressive Formalization** — a 3-tier system that automatically graduates interactions from slow-but-universal to fast-but-specific:

```mermaid
graph LR
    A["Tier 1: Browser<br/>Exploration"] -->|"Pattern<br/>detected"| B["Tier 2: Cached<br/>Workflow"]
    B -->|"API<br/>discovered"| C["Tier 3: Direct<br/>API Call"]
    style A fill:#ff6b6b,color:#fff
    style B fill:#ffd93d,color:#000
    style C fill:#6bcb77,color:#fff
```

The **Discovery Pipeline** captures browser traffic and converts it into structured interfaces:

```mermaid
graph TD
    A[Launch Browser + CDP] --> B[Capture Network Traffic]
    B --> C[Group by Endpoint Pattern]
    C --> D[LLM-Assisted Analysis]
    D --> E[OpenAPI 3.1 Spec]
    E --> F[Python Client]
    E --> G[CLI Commands]
    E --> H[MCP Server]
```

## Comparison

| Feature | browser-use | Hand-built CLIs | CLI-Anything | **site2cli** |
|---|---|---|---|---|
| Works on any site | Yes | No | Yes | Yes |
| Structured output | No | Yes | Yes | Yes |
| Auto-discovery | No | No | No | **Yes** |
| MCP server generation | No | No | No | **Yes** |
| Progressive optimization | No | N/A | No | **Yes** |
| Self-healing | No | No | No | **Yes** |
| No browser needed (after discovery) | No | Yes | No | **Yes** |
| Community spec sharing | No | No | No | **Yes** |

## Quick Start

```bash
# Install (lightweight - no browser deps by default)
pip install site2cli

# Install with all features
pip install site2cli[all]

# Or pick what you need
pip install site2cli[browser]   # Playwright for traffic capture
pip install site2cli[llm]       # Claude API for smart analysis
pip install site2cli[mcp]       # MCP server generation
```

### Discover a Site's API

```bash
# Capture traffic and discover API endpoints
site2cli discover kayak.com --action "search flights"

# site2cli launches a browser, captures network traffic,
# and generates: OpenAPI spec + Python client + MCP tools
```

### Use the Generated Interface

```bash
# CLI
site2cli run kayak.com search_flights from=SFO to=JFK date=2025-04-01

# Or as MCP tools for AI agents
site2cli mcp generate kayak.com
site2cli mcp serve kayak.com
```

## As a Python Library

```python
from site2cli.discovery.analyzer import TrafficAnalyzer
from site2cli.discovery.spec_generator import generate_openapi_spec
from site2cli.generators.mcp_gen import generate_mcp_server_code

# Analyze captured traffic
analyzer = TrafficAnalyzer(exchanges)
endpoints = analyzer.extract_endpoints()

# Generate OpenAPI spec
spec = generate_openapi_spec(api)

# Generate MCP server
mcp_code = generate_mcp_server_code(site, spec)
```

## What Gets Generated

From a single discovery session, site2cli produces:

| Output | Description |
|---|---|
| **OpenAPI 3.1 Spec** | Full API specification with schemas, parameters, auth |
| **Python Client** | Typed httpx client with methods for each endpoint |
| **CLI Commands** | Typer commands you can run from terminal |
| **MCP Server** | Tools that AI agents (Claude, etc.) can call directly |

## Architecture

```mermaid
graph TB
    subgraph "Interface Layer"
        CLI[CLI - Typer]
        MCP[MCP Server]
        SDK[Python SDK]
    end
    subgraph "Router"
        R[Tier Router + Fallback]
    end
    subgraph "Execution Tiers"
        T1[Tier 1: Browser]
        T2[Tier 2: Workflow]
        T3[Tier 3: API]
    end
    subgraph "Discovery Engine"
        CAP[Traffic Capture - CDP]
        ANA[Pattern Analyzer]
        GEN[Code Generators]
    end
    CLI --> R
    MCP --> R
    SDK --> R
    R --> T1
    R --> T2
    R --> T3
    CAP --> ANA --> GEN
```

## Testing

**156 tests** (150 unit/integration + 6 live), all passing on Python 3.10+.

| Test File | Tests | Coverage Area |
|---|---|---|
| `test_analyzer.py` | 24 | Traffic analysis, path normalization, schema inference, auth detection |
| `test_cli.py` | 17 | All CLI subcommands via CliRunner |
| `test_models.py` | 15 | Pydantic model validation, serialization, defaults |
| `test_registry.py` | 10 | SQLite CRUD, tier updates, health tracking |
| `test_router.py` | 15 | Tier routing, fallback, promotion, param forwarding |
| `test_config.py` | 8 | Config singleton, dirs, YAML save/load, API key |
| `test_auth.py` | 11 | Keyring store/get, auth headers, cookie extraction |
| `test_health.py` | 8 | Health check with mock httpx, status persistence |
| `test_community.py` | 6 | Export/import roundtrip, community listing |
| `test_generated_code.py` | 8 | compile() validation of generated code |
| `test_spec_generator.py` | 6 | OpenAPI spec generation and persistence |
| `test_client_generator.py` | 4 | Python client code generation |
| `test_integration_pipeline.py` | 12 | Full pipeline with mock data |
| `test_tier_promotion.py` | 6 | Tier auto-promotion logic |
| `test_integration_live.py` | 6 | Live tests against JSONPlaceholder + httpbin |

## Development

```bash
# Clone and install with dev dependencies
git clone https://github.com/lonexreb/site2cli.git
cd site2cli
pip install -e ".[dev]"

# Run tests
pytest                         # Unit + integration tests (no network)
pytest -m live                 # Live tests (hits real APIs)
pytest -v                      # Verbose output

# Lint
ruff check src/ tests/
```

## API Keys

- **Anthropic API key** (`ANTHROPIC_API_KEY`): Used for LLM-assisted endpoint analysis. Optional — discovery works without it, just without enhanced descriptions.
- **No other keys required** for core functionality.

## Roadmap

- [x] Core discovery pipeline (traffic capture → OpenAPI → client)
- [x] MCP server generation
- [x] Community spec sharing (export/import)
- [x] Health monitoring and self-healing
- [x] Tier auto-promotion (Browser → Workflow → API)
- [x] PyPI package publication
- [ ] OAuth device flow support
- [ ] Workflow recording UI
- [ ] Multi-site orchestration
- [ ] Trained endpoint classifier (replace heuristics)

## License

MIT
