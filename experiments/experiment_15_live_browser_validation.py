"""Experiment 15: Live Browser-Based Discovery Validation.

Tests the REAL Playwright browser → CDP traffic capture → analyze → spec → client → MCP
pipeline against 5 public websites. This is the critical untested path — previous experiments
used direct httpx requests, NOT browser-based traffic capture.

Requires: pip install site2cli[browser,llm]
          playwright install chromium

Usage: ANTHROPIC_API_KEY=sk-... python experiments/experiment_15_live_browser_validation.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import traceback
from pathlib import Path

# Ensure project is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rich.console import Console
from rich.table import Table

from site2cli.config import get_config, reset_config
from site2cli.models import AuthType, DiscoveredAPI, SiteAction, SiteEntry, Tier

console = Console()

# ---------------------------------------------------------------------------
# Target sites: public, no auth, known to make XHR/Fetch API calls
# ---------------------------------------------------------------------------

TARGETS = [
    {
        "name": "JSONPlaceholder",
        "url": "https://jsonplaceholder.typicode.com/",
        "domain": "jsonplaceholder.typicode.com",
        "expected_min_endpoints": 2,
        "description": "Fake REST API — should capture /posts, /users, /albums etc.",
    },
    {
        "name": "httpbin",
        "url": "https://httpbin.org/",
        "domain": "httpbin.org",
        "expected_min_endpoints": 1,
        "description": "HTTP request/response testing — should capture /get, /ip etc.",
    },
    {
        "name": "Dog CEO",
        "url": "https://dog.ceo/dog-api/",
        "domain": "dog.ceo",
        "expected_min_endpoints": 1,
        "description": "Dog image API — homepage makes API calls to /api/breeds/image/random.",
    },
    {
        "name": "PokeAPI",
        "url": "https://pokeapi.co/",
        "domain": "pokeapi.co",
        "expected_min_endpoints": 1,
        "description": "Pokemon API — homepage may make calls to /api/v2/pokemon etc.",
    },
    {
        "name": "REST Countries",
        "url": "https://restcountries.com/",
        "domain": "restcountries.com",
        "expected_min_endpoints": 1,
        "description": "Country data API — should capture /v3.1/all or similar.",
    },
]


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


async def run_browser_discovery(target: dict) -> dict:
    """Run the full browser-based discovery pipeline for a single target."""
    result = {
        "name": target["name"],
        "url": target["url"],
        "domain": target["domain"],
        "exchanges_captured": 0,
        "endpoints_discovered": 0,
        "spec_valid": False,
        "spec_paths": 0,
        "client_compiles": False,
        "client_methods": 0,
        "mcp_compiles": False,
        "mcp_tools": 0,
        "errors": [],
        "duration_s": 0,
    }

    start = time.time()

    try:
        # --- Step 1: Browser traffic capture via CDP ---
        console.print(f"\n[bold cyan]{'='*60}[/bold cyan]")
        console.print(f"[bold]{target['name']}[/bold] — {target['url']}")
        console.print(f"[dim]{target['description']}[/dim]")

        from site2cli.discovery.capture import TrafficCapture

        capture = TrafficCapture(target_domain=target["domain"])
        console.print("  [dim]Launching browser & capturing traffic...[/dim]")

        exchanges = await capture.capture_page_traffic(
            target["url"], duration_seconds=12
        )
        result["exchanges_captured"] = len(exchanges)
        console.print(f"  Captured [green]{len(exchanges)}[/green] API exchanges")

        if not exchanges:
            result["errors"].append("No API exchanges captured")
            result["duration_s"] = round(time.time() - start, 2)
            return result

        # --- Step 2: Analyze traffic ---
        from site2cli.discovery.analyzer import TrafficAnalyzer

        analyzer = TrafficAnalyzer(exchanges)
        endpoints = analyzer.extract_endpoints()
        auth_type = analyzer.detect_auth()
        result["endpoints_discovered"] = len(endpoints)
        console.print(
            f"  Discovered [green]{len(endpoints)}[/green] endpoints"
            f" (auth: {auth_type.value})"
        )

        if not endpoints:
            result["errors"].append("No endpoints extracted from traffic")
            result["duration_s"] = round(time.time() - start, 2)
            return result

        # --- Step 3: Generate OpenAPI spec ---
        from site2cli.discovery.spec_generator import generate_openapi_spec

        api = DiscoveredAPI(
            site_url=target["url"],
            base_url=f"https://{target['domain']}",
            endpoints=endpoints,
            auth_type=auth_type,
            description=f"Auto-discovered API for {target['domain']}",
        )
        spec = generate_openapi_spec(api)
        result["spec_paths"] = len(spec.get("paths", {}))

        # Validate spec
        try:
            from openapi_spec_validator import validate

            validate(spec)
            result["spec_valid"] = True
            console.print(
                f"  OpenAPI spec: [green]valid[/green]"
                f" ({result['spec_paths']} paths)"
            )
        except Exception as e:
            result["errors"].append(f"Spec validation: {e}")
            console.print(f"  OpenAPI spec: [red]invalid[/red] — {e}")

        # --- Step 4: Generate Python client ---
        from site2cli.discovery.client_generator import generate_client_code

        client_code = generate_client_code(spec)
        try:
            compile(client_code, "<generated_client>", "exec")
            result["client_compiles"] = True
            # Count methods
            result["client_methods"] = client_code.count("def ") - 3  # minus __init__, __enter__, __exit__
            console.print(
                f"  Python client: [green]compiles[/green]"
                f" ({result['client_methods']} methods)"
            )
        except SyntaxError as e:
            result["errors"].append(f"Client compile: {e}")
            console.print(f"  Python client: [red]syntax error[/red] — {e}")

        # --- Step 5: Generate MCP server ---
        from site2cli.generators.mcp_gen import generate_mcp_server_code

        site = SiteEntry(
            domain=target["domain"],
            base_url=f"https://{target['domain']}",
            description=api.description,
            auth_type=auth_type,
            actions=[
                SiteAction(name=ep.description or f"{ep.method}_{ep.path_pattern}", tier=Tier.API)
                for ep in endpoints
            ],
        )
        mcp_code = generate_mcp_server_code(site, spec)
        try:
            compile(mcp_code, "<generated_mcp>", "exec")
            result["mcp_compiles"] = True
            result["mcp_tools"] = mcp_code.count("types.Tool(")
            console.print(
                f"  MCP server: [green]compiles[/green]"
                f" ({result['mcp_tools']} tools)"
            )
        except SyntaxError as e:
            result["errors"].append(f"MCP compile: {e}")
            console.print(f"  MCP server: [red]syntax error[/red] — {e}")

        # --- Step 6: Try calling generated client against real API ---
        try:
            ns = {}
            exec(client_code, ns)
            # Find the client class
            client_cls = None
            for v in ns.values():
                if isinstance(v, type) and v.__name__ != "type":
                    client_cls = v
                    break
            if client_cls:
                client_inst = client_cls()
                # Try calling the first method
                methods = [
                    m for m in dir(client_inst)
                    if not m.startswith("_") and callable(getattr(client_inst, m))
                ]
                if methods:
                    first_method = getattr(client_inst, methods[0])
                    try:
                        resp = first_method()
                        if resp is not None:
                            console.print(
                                f"  Client call [green]{methods[0]}()[/green]:"
                                f" got {type(resp).__name__}"
                                f" ({len(str(resp))} chars)"
                            )
                        else:
                            console.print(
                                f"  Client call {methods[0]}(): returned None"
                            )
                    except Exception as e:
                        console.print(
                            f"  Client call {methods[0]}():"
                            f" [yellow]{type(e).__name__}: {e}[/yellow]"
                        )
        except Exception as e:
            console.print(f"  Client execution: [yellow]{e}[/yellow]")

    except Exception as e:
        result["errors"].append(f"Pipeline error: {e}")
        console.print(f"  [red]Pipeline error: {e}[/red]")
        traceback.print_exc()

    result["duration_s"] = round(time.time() - start, 2)
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    console.print("\n[bold]Experiment 15: Live Browser-Based Discovery Validation[/bold]")
    console.print("[dim]Testing real Playwright browser → CDP capture → full pipeline[/dim]\n")

    results = []
    for target in TARGETS:
        reset_config()  # fresh config per site
        r = await run_browser_discovery(target)
        results.append(r)

    # --- Summary table ---
    console.print(f"\n\n[bold]{'='*70}[/bold]")
    console.print("[bold]RESULTS SUMMARY[/bold]\n")

    table = Table(title="Experiment 15: Live Browser Discovery")
    table.add_column("Site", style="bold")
    table.add_column("Exchanges", justify="right")
    table.add_column("Endpoints", justify="right")
    table.add_column("Spec", justify="center")
    table.add_column("Client", justify="center")
    table.add_column("MCP", justify="center")
    table.add_column("Tools", justify="right")
    table.add_column("Time", justify="right")
    table.add_column("Errors", justify="right")

    total_exchanges = 0
    total_endpoints = 0
    total_tools = 0
    specs_valid = 0
    clients_ok = 0
    mcps_ok = 0

    for r in results:
        total_exchanges += r["exchanges_captured"]
        total_endpoints += r["endpoints_discovered"]
        total_tools += r["mcp_tools"]
        if r["spec_valid"]:
            specs_valid += 1
        if r["client_compiles"]:
            clients_ok += 1
        if r["mcp_compiles"]:
            mcps_ok += 1

        table.add_row(
            r["name"],
            str(r["exchanges_captured"]),
            str(r["endpoints_discovered"]),
            "[green]OK[/green]" if r["spec_valid"] else "[red]FAIL[/red]",
            "[green]OK[/green]" if r["client_compiles"] else "[red]FAIL[/red]",
            "[green]OK[/green]" if r["mcp_compiles"] else "[red]FAIL[/red]",
            str(r["mcp_tools"]),
            f"{r['duration_s']}s",
            str(len(r["errors"])) if r["errors"] else "-",
        )

    table.add_section()
    table.add_row(
        "[bold]TOTAL[/bold]",
        str(total_exchanges),
        str(total_endpoints),
        f"{specs_valid}/{len(results)}",
        f"{clients_ok}/{len(results)}",
        f"{mcps_ok}/{len(results)}",
        str(total_tools),
        "",
        "",
    )

    console.print(table)

    # --- Validation checks ---
    console.print("\n[bold]Validation Checks:[/bold]")
    checks = [
        ("At least 3/5 sites captured API traffic", sum(1 for r in results if r["exchanges_captured"] > 0) >= 3),
        ("At least 3/5 specs are valid OpenAPI", specs_valid >= 3),
        ("At least 3/5 clients compile", clients_ok >= 3),
        ("At least 3/5 MCP servers compile", mcps_ok >= 3),
        ("Total endpoints discovered >= 5", total_endpoints >= 5),
    ]

    all_pass = True
    for desc, passed in checks:
        icon = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        console.print(f"  {icon}  {desc}")
        if not passed:
            all_pass = False

    # --- Error details ---
    any_errors = any(r["errors"] for r in results)
    if any_errors:
        console.print("\n[bold yellow]Error Details:[/bold yellow]")
        for r in results:
            if r["errors"]:
                for e in r["errors"]:
                    console.print(f"  [{r['name']}] {e}")

    console.print(
        f"\n[bold]{'ALL CHECKS PASSED' if all_pass else 'SOME CHECKS FAILED'}[/bold]"
    )

    return all_pass


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
