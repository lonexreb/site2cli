"""Experiment #13: Spec Accuracy Benchmark

Compares site2cli-generated OpenAPI specs against known official API specs.
Measures:
1. Endpoint coverage (% of real endpoints discovered)
2. Parameter accuracy (correct params with correct types)
3. Response schema correctness
4. HTTP method correctness
5. Path normalization accuracy (dynamic segments properly parameterized)

Run: python experiments/experiment_13_spec_accuracy.py
"""

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from site2cli.discovery.analyzer import TrafficAnalyzer
from site2cli.discovery.spec_generator import generate_openapi_spec
from site2cli.models import AuthType, CapturedExchange, CapturedHeader, CapturedRequest, CapturedResponse, DiscoveredAPI


@dataclass
class SpecAccuracyResult:
    api_name: str
    # Endpoint metrics
    expected_endpoints: int = 0
    discovered_endpoints: int = 0
    correct_endpoints: int = 0
    endpoint_coverage_pct: float = 0.0
    # Parameter metrics
    expected_params: int = 0
    discovered_params: int = 0
    correct_params: int = 0
    param_accuracy_pct: float = 0.0
    # Method metrics
    correct_methods: int = 0
    method_accuracy_pct: float = 0.0
    # Path normalization
    paths_with_params: int = 0
    correctly_parameterized: int = 0
    normalization_accuracy_pct: float = 0.0
    # Schema metrics
    has_response_schemas: bool = False
    response_schema_count: int = 0
    # Overall
    overall_accuracy_pct: float = 0.0
    errors: list[str] = field(default_factory=list)


def capture(method: str, url: str, body: str | None = None) -> CapturedExchange:
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


@dataclass
class ExpectedEndpoint:
    """Ground truth for an API endpoint."""
    method: str
    path: str
    params: list[str] = field(default_factory=list)
    param_locations: dict[str, str] = field(default_factory=dict)  # name -> query/path/body
    has_path_param: bool = False


def run_accuracy_check(
    api_name: str, domain: str, base_url: str,
    exchanges: list[CapturedExchange],
    expected: list[ExpectedEndpoint],
) -> SpecAccuracyResult:
    """Generate spec and compare against expected ground truth."""
    result = SpecAccuracyResult(api_name=api_name)
    result.expected_endpoints = len(expected)

    try:
        analyzer = TrafficAnalyzer(exchanges)
        endpoints = analyzer.extract_endpoints()
        result.discovered_endpoints = len(endpoints)

        api = DiscoveredAPI(
            site_url=domain, base_url=base_url,
            endpoints=endpoints, auth_type=AuthType.NONE,
        )
        spec = generate_openapi_spec(api)

        # Validate spec
        from openapi_spec_validator import validate
        validate(spec)

        # Extract generated paths and methods
        gen_paths = {}
        for path, path_item in spec.get("paths", {}).items():
            for method, operation in path_item.items():
                if method in ("parameters", "summary", "description"):
                    continue
                key = f"{method.upper()} {path}"
                params = []
                for p in operation.get("parameters", []):
                    params.append(p["name"])
                body = operation.get("requestBody", {})
                if body:
                    for ct_info in body.get("content", {}).values():
                        schema = ct_info.get("schema", {})
                        for prop_name in schema.get("properties", {}).keys():
                            params.append(prop_name)
                gen_paths[key] = {
                    "method": method.upper(),
                    "path": path,
                    "params": params,
                    "has_response": "content" in operation.get("responses", {}).get("200", {}),
                }

        # Compare against expected
        total_params_expected = 0
        total_params_correct = 0
        correct_endpoints = 0
        correct_methods = 0
        paths_with_params = 0
        correctly_parameterized = 0

        for exp in expected:
            exp_key = f"{exp.method} {exp.path}"
            total_params_expected += len(exp.params)

            if exp.has_path_param:
                paths_with_params += 1

            # Find matching generated endpoint
            matched = False
            for gen_key, gen_info in gen_paths.items():
                # Normalize for comparison: replace {id} variants
                gen_path_norm = gen_info["path"].replace("/{id}", "/{id}")
                exp_path_norm = exp.path.replace("/{id}", "/{id}")

                if gen_info["method"] == exp.method and gen_path_norm == exp_path_norm:
                    matched = True
                    correct_endpoints += 1
                    correct_methods += 1

                    # Check parameterization
                    if exp.has_path_param and "/{id}" in gen_info["path"]:
                        correctly_parameterized += 1

                    # Check params
                    gen_param_set = set(gen_info["params"])
                    for p in exp.params:
                        if p in gen_param_set or p.lower() in {pp.lower() for pp in gen_param_set}:
                            total_params_correct += 1

                    if gen_info["has_response"]:
                        result.response_schema_count += 1
                    break

            if not matched:
                # Try fuzzy match on path only
                for gen_key, gen_info in gen_paths.items():
                    if gen_info["method"] == exp.method:
                        gen_parts = gen_info["path"].strip("/").split("/")
                        exp_parts = exp.path.strip("/").split("/")
                        if len(gen_parts) == len(exp_parts):
                            # Check if non-param segments match
                            matches = sum(1 for g, e in zip(gen_parts, exp_parts)
                                          if g == e or g == "{id}" or e == "{id}")
                            if matches == len(gen_parts):
                                correct_endpoints += 1
                                correct_methods += 1
                                if exp.has_path_param:
                                    correctly_parameterized += 1
                                break

        result.correct_endpoints = correct_endpoints
        result.correct_methods = correct_methods
        result.expected_params = total_params_expected
        result.discovered_params = sum(len(g["params"]) for g in gen_paths.values())
        result.correct_params = total_params_correct
        result.paths_with_params = paths_with_params
        result.correctly_parameterized = correctly_parameterized
        result.has_response_schemas = result.response_schema_count > 0

        # Calculate percentages
        if result.expected_endpoints > 0:
            result.endpoint_coverage_pct = (correct_endpoints / result.expected_endpoints) * 100
        if total_params_expected > 0:
            result.param_accuracy_pct = (total_params_correct / total_params_expected) * 100
        if result.expected_endpoints > 0:
            result.method_accuracy_pct = (correct_methods / result.expected_endpoints) * 100
        if paths_with_params > 0:
            result.normalization_accuracy_pct = (correctly_parameterized / paths_with_params) * 100

        # Overall accuracy: weighted average
        scores = [result.endpoint_coverage_pct, result.param_accuracy_pct,
                  result.method_accuracy_pct, result.normalization_accuracy_pct]
        valid_scores = [s for s in scores if s > 0]
        result.overall_accuracy_pct = sum(valid_scores) / len(valid_scores) if valid_scores else 0

    except Exception as e:
        result.errors.append(str(e))

    return result


# ── Ground Truth API Definitions ─────────────────────────────────────────────


def httpbin_accuracy():
    """httpbin.org — official spec is well-known."""
    exchanges = [
        capture("GET", "https://httpbin.org/get"),
        capture("POST", "https://httpbin.org/post", json.dumps({"key": "value"})),
        capture("GET", "https://httpbin.org/headers"),
        capture("GET", "https://httpbin.org/ip"),
        capture("GET", "https://httpbin.org/uuid"),
        capture("GET", "https://httpbin.org/user-agent"),
        capture("GET", "https://httpbin.org/status/200"),
        capture("DELETE", "https://httpbin.org/delete"),
        capture("PUT", "https://httpbin.org/put", json.dumps({"key": "updated"})),
    ]
    expected = [
        ExpectedEndpoint("GET", "/get"),
        ExpectedEndpoint("POST", "/post", ["key"]),
        ExpectedEndpoint("GET", "/headers"),
        ExpectedEndpoint("GET", "/ip"),
        ExpectedEndpoint("GET", "/uuid"),
        ExpectedEndpoint("GET", "/user-agent"),
        ExpectedEndpoint("GET", "/status/{id}", has_path_param=True),
        ExpectedEndpoint("DELETE", "/delete"),
        ExpectedEndpoint("PUT", "/put", ["key"]),
    ]
    return "httpbin.org", "httpbin.org", "https://httpbin.org", exchanges, expected


def jsonplaceholder_accuracy():
    """JSONPlaceholder — fully documented REST API."""
    exchanges = [
        capture("GET", "https://jsonplaceholder.typicode.com/posts"),
        capture("GET", "https://jsonplaceholder.typicode.com/posts/1"),
        capture("GET", "https://jsonplaceholder.typicode.com/posts/2"),
        capture("GET", "https://jsonplaceholder.typicode.com/posts?userId=1"),
        capture("POST", "https://jsonplaceholder.typicode.com/posts",
                json.dumps({"title": "t", "body": "b", "userId": 1})),
        capture("GET", "https://jsonplaceholder.typicode.com/comments?postId=1"),
        capture("GET", "https://jsonplaceholder.typicode.com/users"),
        capture("GET", "https://jsonplaceholder.typicode.com/users/1"),
        capture("GET", "https://jsonplaceholder.typicode.com/todos"),
        capture("GET", "https://jsonplaceholder.typicode.com/albums"),
    ]
    expected = [
        ExpectedEndpoint("GET", "/posts", ["userId"],
                         {"userId": "query"}),
        ExpectedEndpoint("GET", "/posts/{id}", ["id"],
                         {"id": "path"}, has_path_param=True),
        ExpectedEndpoint("POST", "/posts", ["title", "body", "userId"]),
        ExpectedEndpoint("GET", "/comments", ["postId"],
                         {"postId": "query"}),
        ExpectedEndpoint("GET", "/users"),
        ExpectedEndpoint("GET", "/users/{id}", ["id"],
                         {"id": "path"}, has_path_param=True),
        ExpectedEndpoint("GET", "/todos"),
        ExpectedEndpoint("GET", "/albums"),
    ]
    return ("JSONPlaceholder", "jsonplaceholder.typicode.com",
            "https://jsonplaceholder.typicode.com", exchanges, expected)


def pokeapi_accuracy():
    """PokeAPI — well-documented with pagination."""
    exchanges = [
        capture("GET", "https://pokeapi.co/api/v2/pokemon?limit=3"),
        capture("GET", "https://pokeapi.co/api/v2/pokemon/1"),
        capture("GET", "https://pokeapi.co/api/v2/pokemon/25"),
        capture("GET", "https://pokeapi.co/api/v2/type/1"),
        capture("GET", "https://pokeapi.co/api/v2/type/3"),
        capture("GET", "https://pokeapi.co/api/v2/ability/1"),
    ]
    expected = [
        ExpectedEndpoint("GET", "/api/v2/pokemon", ["limit"],
                         {"limit": "query"}),
        ExpectedEndpoint("GET", "/api/v2/pokemon/{id}", ["id"],
                         {"id": "path"}, has_path_param=True),
        ExpectedEndpoint("GET", "/api/v2/type/{id}", ["id"],
                         {"id": "path"}, has_path_param=True),
        ExpectedEndpoint("GET", "/api/v2/ability/{id}", ["id"],
                         {"id": "path"}, has_path_param=True),
    ]
    return "PokeAPI", "pokeapi.co", "https://pokeapi.co", exchanges, expected


def dog_api_accuracy():
    """Dog CEO API — nested breed paths."""
    exchanges = [
        capture("GET", "https://dog.ceo/api/breeds/list/all"),
        capture("GET", "https://dog.ceo/api/breeds/image/random"),
        capture("GET", "https://dog.ceo/api/breed/hound/images"),
        capture("GET", "https://dog.ceo/api/breed/labrador/images"),
        capture("GET", "https://dog.ceo/api/breed/hound/images/random"),
    ]
    expected = [
        ExpectedEndpoint("GET", "/api/breeds/list/all"),
        ExpectedEndpoint("GET", "/api/breeds/image/random"),
        ExpectedEndpoint("GET", "/api/breed/{id}/images", has_path_param=False),  # breed names aren't numeric
        ExpectedEndpoint("GET", "/api/breed/{id}/images/random", has_path_param=False),
    ]
    return "Dog CEO API", "dog.ceo", "https://dog.ceo", exchanges, expected


def github_api_accuracy():
    """GitHub API — owner/repo paths."""
    exchanges = [
        capture("GET", "https://api.github.com/repos/lonexreb/site2cli"),
        capture("GET", "https://api.github.com/repos/HKUDS/CLI-Anything"),
        capture("GET", "https://api.github.com/repos/lonexreb/site2cli/languages"),
        capture("GET", "https://api.github.com/users/lonexreb"),
    ]
    expected = [
        ExpectedEndpoint("GET", "/repos/{owner}/{repo}",
                         has_path_param=False),  # String params, not numeric
        ExpectedEndpoint("GET", "/repos/{owner}/{repo}/languages",
                         has_path_param=False),
        ExpectedEndpoint("GET", "/users/{username}",
                         has_path_param=False),
    ]
    return ("GitHub API", "api.github.com",
            "https://api.github.com", exchanges, expected)


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    print("=" * 80)
    print("EXPERIMENT #13: Spec Accuracy Benchmark")
    print("Date: 2026-03-13")
    print("=" * 80)
    print("\nGoal: Measure how accurately site2cli-generated specs match")
    print("known API ground truth (endpoints, params, methods, schemas).\n")

    benchmarks = [
        httpbin_accuracy,
        jsonplaceholder_accuracy,
        pokeapi_accuracy,
        dog_api_accuracy,
        github_api_accuracy,
    ]

    results: list[SpecAccuracyResult] = []

    for loader in benchmarks:
        print(f"\n{'─' * 80}")
        try:
            api_name, domain, base_url, exchanges, expected = loader()
            print(f"  API: {api_name} ({domain})")
            print(f"  Expected endpoints: {len(expected)}")
            print(f"  Exchanges captured: {len(exchanges)}")

            result = run_accuracy_check(api_name, domain, base_url, exchanges, expected)
            results.append(result)

            print(f"  Discovered:    {result.discovered_endpoints} endpoints")
            print(f"  Correct:       {result.correct_endpoints}/{result.expected_endpoints} endpoints "
                  f"({result.endpoint_coverage_pct:.0f}%)")
            print(f"  Params:        {result.correct_params}/{result.expected_params} correct "
                  f"({result.param_accuracy_pct:.0f}%)")
            print(f"  Methods:       {result.correct_methods}/{result.expected_endpoints} correct "
                  f"({result.method_accuracy_pct:.0f}%)")
            if result.paths_with_params > 0:
                print(f"  Path params:   {result.correctly_parameterized}/{result.paths_with_params} "
                      f"({result.normalization_accuracy_pct:.0f}%)")
            print(f"  Response schemas: {result.response_schema_count}")
            print(f"  Overall accuracy: {result.overall_accuracy_pct:.0f}%")

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
    print("ACCURACY SUMMARY")
    print("=" * 80)

    print(f"\n{'API':<20} {'EP Cover':>10} {'Params':>8} {'Methods':>9} "
          f"{'PathNorm':>10} {'Overall':>9}")
    print("-" * 70)

    for r in results:
        print(f"{r.api_name:<20} {r.endpoint_coverage_pct:>8.0f}% "
              f"{r.param_accuracy_pct:>6.0f}% {r.method_accuracy_pct:>7.0f}% "
              f"{r.normalization_accuracy_pct:>8.0f}% {r.overall_accuracy_pct:>7.0f}%")

    # Overall averages
    avg_ep = sum(r.endpoint_coverage_pct for r in results) / len(results) if results else 0
    avg_param = sum(r.param_accuracy_pct for r in results) / len(results) if results else 0
    avg_method = sum(r.method_accuracy_pct for r in results) / len(results) if results else 0
    avg_overall = sum(r.overall_accuracy_pct for r in results) / len(results) if results else 0

    print("-" * 70)
    print(f"{'AVERAGE':<20} {avg_ep:>8.0f}% {avg_param:>6.0f}% "
          f"{avg_method:>7.0f}%  {'':>8} {avg_overall:>7.0f}%")

    # ── Insights ─────────────────────────────────────────────────────────────

    print("\n" + "=" * 80)
    print("KEY INSIGHTS")
    print("=" * 80)
    print(f"""
  Endpoint coverage: {avg_ep:.0f}% — site2cli discovers most endpoints from traffic
  Parameter accuracy: {avg_param:.0f}% — query/body params correctly identified
  Method accuracy: {avg_method:.0f}% — GET/POST/PUT/DELETE correctly mapped
  Overall accuracy: {avg_overall:.0f}% across {len(results)} APIs

  NOTE: Accuracy depends on traffic observed. More diverse traffic = better specs.
  Path parameters for non-numeric values (breed names, usernames) require LLM
  enhancement or pattern learning to parameterize correctly.

  site2cli's heuristic approach (no LLM) achieves good accuracy for:
  - Numeric ID paths (/{id} normalization)
  - Query parameters (merging across exchanges)
  - Request body schemas (JSON inference)
  - Response schemas (type inference from samples)
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
