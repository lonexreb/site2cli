"""Experiment #9: API Discovery Breadth — Proving "any website" claim

Tests site2cli's discovery pipeline against 10 diverse public APIs covering:
- Simple REST (PokeAPI, CatFacts, ChuckNorris)
- Deep nested paths (Star Wars API)
- Query-param heavy (Open Library, USGS Earthquake)
- Government/science (NASA APOD, USGS)
- Cultural (Metropolitan Museum, Art Institute of Chicago)
- Rich response schemas (all of the above)

Run: python experiments/experiment_9_api_breadth.py
"""

import importlib.util
import json
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from site2cli.discovery.analyzer import TrafficAnalyzer
from site2cli.discovery.client_generator import generate_client_code, save_client
from site2cli.discovery.spec_generator import generate_openapi_spec
from site2cli.generators.mcp_gen import generate_mcp_server_code
from site2cli.models import AuthType, CapturedExchange, CapturedHeader, CapturedRequest, CapturedResponse, DiscoveredAPI, SiteEntry


@dataclass
class BreadthResult:
    api_name: str
    category: str
    endpoints_discovered: int = 0
    spec_valid: bool = False
    client_compiles: bool = False
    client_works: bool = False
    client_call_result: str = ""
    mcp_compiles: bool = False
    mcp_tool_count: int = 0
    pipeline_time_ms: int = 0
    response_schema_types: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def capture(method: str, url: str, body: str | None = None) -> CapturedExchange:
    """Make a real HTTP request and wrap it as a CapturedExchange."""
    headers = {"Accept": "application/json", "User-Agent": "site2cli/0.2.0 experiment"}
    if body:
        headers["Content-Type"] = "application/json"
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        resp = client.request(method, url, content=body, headers=headers)
    return CapturedExchange(
        request=CapturedRequest(
            method=method, url=url,
            headers=[CapturedHeader(name=k, value=v) for k, v in headers.items()],
            body=body, content_type=headers.get("Content-Type"),
        ),
        response=CapturedResponse(
            status=resp.status_code, body=resp.text,
            content_type=resp.headers.get("content-type", ""),
            headers=[CapturedHeader(name=k, value=v) for k, v in resp.headers.items()],
        ),
    )


def run_pipeline(api_name: str, category: str, domain: str, base_url: str,
                 exchanges: list[CapturedExchange], tmp_dir: Path,
                 fallback_kwargs: list[dict] | None = None) -> BreadthResult:
    """Run full discovery pipeline and validate outputs."""
    result = BreadthResult(api_name=api_name, category=category)
    t0 = time.monotonic()

    # Step 1: Analyze traffic
    try:
        analyzer = TrafficAnalyzer(exchanges)
        endpoints = analyzer.extract_endpoints()
        result.endpoints_discovered = len(endpoints)
        for ep in endpoints:
            if ep.response_schema:
                result.response_schema_types.append(ep.response_schema.get("type", "unknown"))
    except Exception as e:
        result.errors.append(f"Analysis failed: {e}")
        return result

    # Step 2: Generate OpenAPI spec
    try:
        api = DiscoveredAPI(
            site_url=domain, base_url=base_url,
            endpoints=endpoints, auth_type=AuthType.NONE,
        )
        spec = generate_openapi_spec(api)
        from openapi_spec_validator import validate
        validate(spec)
        result.spec_valid = True
    except Exception as e:
        result.errors.append(f"Spec validation failed: {e}")
        return result

    # Step 3: Generate and test Python client
    try:
        class_name = api_name.replace(" ", "").replace("-", "").replace(".", "") + "Client"
        code = generate_client_code(spec, class_name=class_name)
        compile(code, f"<{api_name}_client>", "exec")
        result.client_compiles = True

        client_path = tmp_dir / f"{domain.replace('.', '_')}_client.py"
        save_client(code, client_path)
        mod_spec = importlib.util.spec_from_file_location("client", client_path)
        module = importlib.util.module_from_spec(mod_spec)
        mod_spec.loader.exec_module(module)

        client_cls = getattr(module, class_name)
        client = client_cls()
        try:
            # Build list of call attempts: no-args first, then fallback kwargs
            call_attempts = [{}]
            if fallback_kwargs:
                call_attempts.extend(fallback_kwargs)

            for attr_name in sorted(dir(client)):
                if attr_name.startswith("_") or attr_name in ("close", "__enter__", "__exit__"):
                    continue
                method = getattr(client, attr_name)
                if not callable(method):
                    continue
                for kwargs in call_attempts:
                    try:
                        data = method(**kwargs)
                        if isinstance(data, (dict, list)):
                            result.client_works = True
                            preview = json.dumps(data, default=str)[:150]
                            kw_str = f"(**{kwargs})" if kwargs else "()"
                            result.client_call_result = f"{attr_name}{kw_str} → {preview}"
                            break
                    except (TypeError, httpx.HTTPStatusError, json.JSONDecodeError):
                        continue
                if result.client_works:
                    break
        finally:
            client.close()
    except Exception as e:
        result.errors.append(f"Client generation failed: {e}")

    # Step 4: Generate MCP server
    try:
        site = SiteEntry(domain=domain, base_url=base_url)
        mcp_code = generate_mcp_server_code(site, spec)
        compile(mcp_code, f"<{api_name}_mcp>", "exec")
        result.mcp_compiles = True
        result.mcp_tool_count = mcp_code.count("Tool(")
    except Exception as e:
        result.errors.append(f"MCP generation failed: {e}")

    result.pipeline_time_ms = int((time.monotonic() - t0) * 1000)
    return result


# ── API Definitions ──────────────────────────────────────────────────────────


def pokeapi_exchanges():
    """PokeAPI — well-structured REST, 100+ endpoints, no auth."""
    return (
        "PokeAPI", "Structured REST",
        "pokeapi.co", "https://pokeapi.co",
        [
            capture("GET", "https://pokeapi.co/api/v2/pokemon/1"),
            capture("GET", "https://pokeapi.co/api/v2/pokemon/25"),
            capture("GET", "https://pokeapi.co/api/v2/pokemon?limit=5"),
            capture("GET", "https://pokeapi.co/api/v2/type/1"),
            capture("GET", "https://pokeapi.co/api/v2/ability/1"),
            capture("GET", "https://pokeapi.co/api/v2/generation/1"),
        ],
    )


def catfacts_exchanges():
    """Cat Facts — simple single-endpoint API."""
    return (
        "CatFacts", "Simple REST",
        "catfact.ninja", "https://catfact.ninja",
        [
            capture("GET", "https://catfact.ninja/fact"),
            capture("GET", "https://catfact.ninja/facts"),
            capture("GET", "https://catfact.ninja/facts?limit=3"),
            capture("GET", "https://catfact.ninja/breeds"),
            capture("GET", "https://catfact.ninja/breeds?limit=5"),
        ],
    )


def chucknorris_exchanges():
    """Chuck Norris API — jokes with categories."""
    return (
        "ChuckNorris", "Simple REST",
        "api.chucknorris.io", "https://api.chucknorris.io",
        [
            capture("GET", "https://api.chucknorris.io/jokes/random"),
            capture("GET", "https://api.chucknorris.io/jokes/categories"),
            capture("GET", "https://api.chucknorris.io/jokes/random?category=dev"),
            capture("GET", "https://api.chucknorris.io/jokes/search?query=python"),
        ],
    )


def swapi_exchanges():
    """Star Wars API — deep nested paths, pagination."""
    return (
        "SWAPI", "Nested Paths",
        "swapi.dev", "https://swapi.dev",
        [
            capture("GET", "https://swapi.dev/api/people/1/"),
            capture("GET", "https://swapi.dev/api/people/2/"),
            capture("GET", "https://swapi.dev/api/planets/1/"),
            capture("GET", "https://swapi.dev/api/starships/9/"),
            capture("GET", "https://swapi.dev/api/films/1/"),
            capture("GET", "https://swapi.dev/api/species/1/"),
        ],
        [{"id": "1"}],
    )


def openlibrary_exchanges():
    """Open Library — query-param-heavy search API."""
    return (
        "OpenLibrary", "Query Params",
        "openlibrary.org", "https://openlibrary.org",
        [
            capture("GET", "https://openlibrary.org/search.json?q=python&limit=3"),
            capture("GET", "https://openlibrary.org/search.json?q=javascript&limit=3"),
            capture("GET", "https://openlibrary.org/search.json?author=tolkien&limit=3"),
            capture("GET", "https://openlibrary.org/api/books?bibkeys=ISBN:0451526538&format=json&jscmd=data"),
        ],
    )


def usgs_earthquake_exchanges():
    """USGS Earthquake API — government science data."""
    return (
        "USGS Earthquake", "Government/Science",
        "earthquake.usgs.gov", "https://earthquake.usgs.gov",
        [
            capture("GET", "https://earthquake.usgs.gov/fdsnws/event/1/count?format=geojson&starttime=2024-01-01&endtime=2024-01-02"),
            capture("GET", "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2024-01-01&endtime=2024-01-02&minmagnitude=5&limit=5"),
            capture("GET", "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2024-01-01&endtime=2024-01-02&limit=3"),
        ],
        [{"format": "geojson", "starttime": "2024-01-01", "endtime": "2024-01-02", "limit": "3"}],
    )


def nasa_apod_exchanges():
    """NASA Astronomy Picture of the Day — public science API."""
    return (
        "NASA APOD", "Government/Science",
        "api.nasa.gov", "https://api.nasa.gov",
        [
            capture("GET", "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY"),
            capture("GET", "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY&date=2024-01-01"),
            capture("GET", "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY&count=3"),
        ],
        [{"api_key": "DEMO_KEY"}],
    )


def met_museum_exchanges():
    """Metropolitan Museum of Art — cultural data API."""
    return (
        "Met Museum", "Cultural",
        "collectionapi.metmuseum.org", "https://collectionapi.metmuseum.org",
        [
            capture("GET", "https://collectionapi.metmuseum.org/public/collection/v1/objects/1"),
            capture("GET", "https://collectionapi.metmuseum.org/public/collection/v1/objects/2"),
            capture("GET", "https://collectionapi.metmuseum.org/public/collection/v1/departments"),
            capture("GET", "https://collectionapi.metmuseum.org/public/collection/v1/search?q=sunflowers"),
        ],
        [{"q": "sunflowers"}],
    )


def art_institute_exchanges():
    """Art Institute of Chicago — rich JSON:API format."""
    return (
        "Art Institute Chicago", "Cultural",
        "api.artic.edu", "https://api.artic.edu",
        [
            capture("GET", "https://api.artic.edu/api/v1/artworks?limit=3"),
            capture("GET", "https://api.artic.edu/api/v1/artworks/27992"),
            capture("GET", "https://api.artic.edu/api/v1/artists?limit=3"),
            capture("GET", "https://api.artic.edu/api/v1/artworks/search?q=monet&limit=3"),
        ],
    )


def restcountries_exchanges():
    """REST Countries — geographic data with nested responses."""
    return (
        "REST Countries", "Geographic",
        "restcountries.com", "https://restcountries.com",
        [
            capture("GET", "https://restcountries.com/v3.1/name/france"),
            capture("GET", "https://restcountries.com/v3.1/name/japan"),
            capture("GET", "https://restcountries.com/v3.1/alpha/US"),
            capture("GET", "https://restcountries.com/v3.1/region/europe?fields=name,capital,population"),
            capture("GET", "https://restcountries.com/v3.1/currency/usd"),
        ],
    )


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    print("=" * 80)
    print("EXPERIMENT #9: API Discovery Breadth")
    print("Date: 2026-03-13")
    print("=" * 80)
    print("\nGoal: Prove site2cli handles diverse API styles — simple REST,")
    print("nested paths, query-param-heavy, government, cultural, geographic.\n")

    api_loaders = [
        pokeapi_exchanges,
        catfacts_exchanges,
        chucknorris_exchanges,
        swapi_exchanges,
        openlibrary_exchanges,
        usgs_earthquake_exchanges,
        nasa_apod_exchanges,
        met_museum_exchanges,
        art_institute_exchanges,
        restcountries_exchanges,
    ]

    results: list[BreadthResult] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        for loader in api_loaders:
            print(f"\n{'─' * 80}")
            try:
                loaded = loader()
                if len(loaded) == 6:
                    api_name, category, domain, base_url, exchanges, fallback_kwargs = loaded
                else:
                    api_name, category, domain, base_url, exchanges = loaded
                    fallback_kwargs = None
                print(f"  [{category}] {api_name} ({domain})")
                print(f"  Exchanges captured: {len(exchanges)}")
                result = run_pipeline(api_name, category, domain, base_url, exchanges, tmp_path, fallback_kwargs)
                results.append(result)

                print(f"  Endpoints found:    {result.endpoints_discovered}")
                print(f"  Spec valid:         {'✓' if result.spec_valid else '✗'}")
                print(f"  Client compiles:    {'✓' if result.client_compiles else '✗'}")
                print(f"  Client works:       {'✓' if result.client_works else '✗'}")
                if result.client_call_result:
                    print(f"  Client call:        {result.client_call_result[:100]}")
                print(f"  MCP compiles:       {'✓' if result.mcp_compiles else '✗'}")
                print(f"  MCP tools:          {result.mcp_tool_count}")
                print(f"  Schema types:       {', '.join(result.response_schema_types)}")
                print(f"  Pipeline time:      {result.pipeline_time_ms}ms")
                if result.errors:
                    for err in result.errors:
                        print(f"  ERROR: {err}")
            except httpx.ConnectError as e:
                print(f"  SKIPPED (no network): {e}")
            except Exception as e:
                print(f"  FAILED: {e}")
                import traceback
                traceback.print_exc()

    # ── Summary ──────────────────────────────────────────────────────────────

    print("\n" + "=" * 80)
    print("SUMMARY — API Discovery Breadth")
    print("=" * 80)

    print(f"\n{'API':<25} {'Category':<18} {'EP':>4} {'Spec':>5} {'Client':>7} "
          f"{'Works':>6} {'MCP':>4} {'Tools':>6} {'Time':>8}")
    print("-" * 95)

    total_endpoints = 0
    total_tools = 0
    specs_valid = 0
    clients_work = 0
    mcp_compile = 0
    categories_seen = set()

    for r in results:
        total_endpoints += r.endpoints_discovered
        total_tools += r.mcp_tool_count
        if r.spec_valid:
            specs_valid += 1
        if r.client_works:
            clients_work += 1
        if r.mcp_compiles:
            mcp_compile += 1
        categories_seen.add(r.category)

        print(f"{r.api_name:<25} {r.category:<18} {r.endpoints_discovered:>4} "
              f"{'✓' if r.spec_valid else '✗':>5} "
              f"{'✓' if r.client_compiles else '✗':>7} "
              f"{'✓' if r.client_works else '✗':>6} "
              f"{'✓' if r.mcp_compiles else '✗':>4} "
              f"{r.mcp_tool_count:>6} "
              f"{r.pipeline_time_ms:>6}ms")

    n = len(results)
    avg_time = sum(r.pipeline_time_ms for r in results) // n if n else 0
    print("-" * 95)
    print(f"{'TOTAL':<25} {len(categories_seen)} categories  {total_endpoints:>4} "
          f"{specs_valid}/{n}    {clients_work}/{n}     {mcp_compile}/{n}  "
          f"{total_tools:>6}  avg {avg_time}ms")

    # ── Verdict ──────────────────────────────────────────────────────────────

    print("\n" + "=" * 80)
    print("BREADTH CLAIMS VALIDATION")
    print("=" * 80)

    claims = [
        (f"Tested {n} diverse APIs", n >= 10),
        (f"Covered {len(categories_seen)} API categories", len(categories_seen) >= 5),
        (f"All {specs_valid}/{n} specs are valid OpenAPI 3.1", specs_valid == n),
        (f"All {mcp_compile}/{n} MCP servers compile", mcp_compile == n),
        (f"{clients_work}/{n} generated clients make real API calls", clients_work >= n * 0.7),
        (f"{total_endpoints} total endpoints discovered", total_endpoints >= 30),
        (f"{total_tools} MCP tools generated", total_tools >= 30),
        (f"Avg pipeline time: {avg_time}ms (< 5s)", avg_time < 5000),
    ]

    all_pass = True
    for claim, passed in claims:
        status = "PROVED" if passed else "FAILED"
        if not passed:
            all_pass = False
        print(f"  [{status}] {claim}")

    print(f"\nOverall: {'ALL BREADTH CLAIMS VALIDATED ✓' if all_pass else 'SOME CLAIMS FAILED ✗'}")
    print("=" * 80)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
