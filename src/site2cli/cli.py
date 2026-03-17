"""site2cli — Turn any website into a CLI/API for AI agents."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.table import Table

from site2cli import __version__
from site2cli.config import get_config

app = typer.Typer(
    name="site2cli",
    help="Turn any website into a CLI/API for AI agents.",
    no_args_is_help=True,
)
console = Console()


def _get_registry():
    from site2cli.config import get_config
    from site2cli.registry import SiteRegistry

    config = get_config()
    return SiteRegistry(config.db_path)


def _run_async(coro):
    """Run an async function from sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# --- Core Commands ---


@app.command()
def discover(
    url: str = typer.Argument(help="URL or domain to discover APIs for"),
    action: Optional[str] = typer.Option(
        None, "--action", "-a", help="Specific action to discover"
    ),
    headless: bool = typer.Option(True, help="Run browser in headless mode"),
    enhance: bool = typer.Option(True, help="Use LLM to enhance discovered endpoints"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output spec to file"),
) -> None:
    """Discover API endpoints for a website by capturing network traffic."""
    from site2cli.config import get_config
    from site2cli.discovery.analyzer import TrafficAnalyzer
    from site2cli.discovery.capture import TrafficCapture
    from site2cli.discovery.client_generator import generate_client_code, save_client
    from site2cli.discovery.spec_generator import generate_openapi_spec, save_spec
    from site2cli.models import (
        DiscoveredAPI,
        SiteAction,
        SiteEntry,
        Tier,
    )

    # Normalize URL
    if not url.startswith("http"):
        url = f"https://{url}"
    parsed = urlparse(url)
    domain = parsed.hostname or url

    config = get_config()
    config.browser.headless = headless

    console.print(f"[bold]Discovering APIs for[/bold] {domain}...")

    # Step 1: Capture traffic
    capture = TrafficCapture(target_domain=domain)

    async def do_capture():
        goal = action or "explore the main features"
        if action:
            from site2cli.tiers.browser_explorer import BrowserExplorer

            explorer = BrowserExplorer()
            result = await explorer.explore(url, goal)
            return result.get("exchanges", [])
        else:
            return await capture.capture_page_traffic(url, duration_seconds=15)

    with console.status("[bold green]Launching browser and capturing traffic..."):
        exchanges = _run_async(do_capture())

    api_exchanges = [
        ex for ex in exchanges if capture._is_api_like(ex.request.url, ex.response.content_type)
    ] if not action else exchanges

    if not api_exchanges:
        console.print(
            "[yellow]No API traffic captured.[/yellow]"
            " The site may not use XHR/Fetch APIs."
        )
        console.print("Try with --action to specify what to do on the site.")
        raise typer.Exit(1)

    console.print(f"  Captured [bold]{len(api_exchanges)}[/bold] API requests")

    # Step 2: Analyze traffic
    analyzer = TrafficAnalyzer(api_exchanges)
    endpoints = analyzer.extract_endpoints()
    auth_type = analyzer.detect_auth()

    console.print(f"  Found [bold]{len(endpoints)}[/bold] unique endpoints")

    # Step 3: LLM enhancement
    if enhance and endpoints:
        with console.status("[bold green]Enhancing with LLM analysis..."):
            endpoints = _run_async(analyzer.analyze_with_llm(endpoints))

    # Step 4: Generate OpenAPI spec
    api = DiscoveredAPI(
        site_url=domain,
        base_url=f"{parsed.scheme}://{parsed.netloc}",
        endpoints=endpoints,
        auth_type=auth_type,
        description=f"Auto-discovered API for {domain}",
    )
    spec = generate_openapi_spec(api)

    # Save spec
    spec_path = Path(output) if output else config.specs_dir / f"{domain}.json"
    save_spec(spec, spec_path)
    console.print(f"  Saved OpenAPI spec to [bold]{spec_path}[/bold]")

    # Step 5: Generate client
    client_code = generate_client_code(spec)
    client_path = config.clients_dir / f"{domain.replace('.', '_')}_client.py"
    save_client(client_code, client_path)
    console.print(f"  Generated client at [bold]{client_path}[/bold]")

    # Step 6: Register site
    registry = _get_registry()
    actions = [
        SiteAction(
            name=(
                ep.description.replace(" ", "_").lower()
                if ep.description
                else f"{ep.method}_{ep.path_pattern}"
            ),
            description=ep.description,
            tier=Tier.API,
            endpoint=ep,
        )
        for ep in endpoints
    ]
    site = SiteEntry(
        domain=domain,
        base_url=api.base_url,
        description=api.description,
        actions=actions,
        auth_type=auth_type,
        openapi_spec_path=str(spec_path),
        client_module_path=str(client_path),
    )
    registry.add_site(site)

    # Summary
    console.print()
    console.print(
        f"[bold green]Discovered {len(endpoints)}"
        f" capabilities for {domain}:[/bold green]"
    )
    for ep in endpoints:
        name = ep.description or f"{ep.method} {ep.path_pattern}"
        params = ", ".join(p.name for p in ep.parameters[:5])
        console.print(f"  - {name} ({params})")


@app.command()
def run(
    domain: str = typer.Argument(help="Site domain"),
    action: str = typer.Argument(help="Action to execute"),
    params: Optional[list[str]] = typer.Argument(None, help="key=value parameters"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
    no_headless: bool = typer.Option(False, "--no-headless", help="Show browser window"),
) -> None:
    """Execute a discovered action on a site."""
    from site2cli.router import Router

    config = get_config()
    if no_headless:
        config.browser.headless = False

    registry = _get_registry()
    router = Router(registry)

    # Parse key=value params
    param_dict = {}
    if params:
        for p in params:
            if "=" in p:
                k, v = p.split("=", 1)
                param_dict[k] = v

    with console.status(f"[bold green]Executing {action} on {domain}..."):
        result = _run_async(router.execute(domain, action, param_dict))

    if json_output:
        console.print(json.dumps(result, indent=2, default=str))
    else:
        from rich.json import JSON

        console.print(JSON(json.dumps(result, indent=2, default=str)))


# --- Site Management Commands ---

sites_app = typer.Typer(help="Manage discovered sites")
app.add_typer(sites_app, name="sites")


@sites_app.command("list")
def sites_list() -> None:
    """List all discovered sites."""
    registry = _get_registry()
    sites = registry.list_sites()

    if not sites:
        console.print(
            "[yellow]No sites discovered yet.[/yellow]"
            " Run `site2cli discover <url>` to get started."
        )
        return

    table = Table(title="Discovered Sites")
    table.add_column("Domain", style="bold")
    table.add_column("Actions")
    table.add_column("Health")
    table.add_column("Auth")
    table.add_column("Last Updated")

    for site in sites:
        table.add_row(
            site.domain,
            str(len(site.actions)),
            site.health.value,
            site.auth_type.value,
            site.updated_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


@sites_app.command("show")
def sites_show(domain: str = typer.Argument(help="Site domain to show")) -> None:
    """Show details for a discovered site."""
    registry = _get_registry()
    site = registry.get_site(domain)

    if not site:
        console.print(f"[red]Site {domain} not found.[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]{site.domain}[/bold]")
    console.print(f"  Base URL: {site.base_url}")
    console.print(f"  Auth: {site.auth_type.value}")
    console.print(f"  Health: {site.health.value}")
    console.print(f"  Discovered: {site.discovered_at.strftime('%Y-%m-%d %H:%M')}")
    console.print()

    if site.actions:
        table = Table(title="Actions")
        table.add_column("Name", style="bold")
        table.add_column("Tier")
        table.add_column("Health")
        table.add_column("Success/Fail")
        table.add_column("Description")

        for action in site.actions:
            table.add_row(
                action.name,
                action.tier.value,
                action.health.value,
                f"{action.success_count}/{action.failure_count}",
                action.description[:50] if action.description else "",
            )
        console.print(table)


@sites_app.command("remove")
def sites_remove(domain: str = typer.Argument(help="Site domain to remove")) -> None:
    """Remove a site from the registry."""
    registry = _get_registry()
    if registry.remove_site(domain):
        console.print(f"[green]Removed {domain}[/green]")
    else:
        console.print(f"[red]Site {domain} not found[/red]")


# --- Auth Commands ---

auth_app = typer.Typer(help="Manage authentication")
app.add_typer(auth_app, name="auth")


@auth_app.command("login")
def auth_login(
    domain: str = typer.Argument(help="Site domain"),
    method: str = typer.Option("cookie", help="Auth method: cookie, api-key, token"),
) -> None:
    """Set up authentication for a site."""
    from site2cli.auth.manager import AuthManager

    auth = AuthManager()

    if method == "cookie":
        console.print(f"Extracting cookies from browser for {domain}...")
        cookies = auth.extract_browser_cookies(domain)
        if cookies:
            console.print(f"[green]Extracted {len(cookies)} cookies[/green]")
        else:
            console.print(
                "[yellow]Could not extract cookies.[/yellow]"
                " Make sure you're logged in via your browser."
            )
    elif method == "api-key":
        key = typer.prompt("API Key", hide_input=True)
        auth.store_api_key(domain, key)
        console.print("[green]API key stored[/green]")
    elif method == "token":
        token = typer.prompt("Bearer Token", hide_input=True)
        auth.store_token(domain, token)
        console.print("[green]Token stored[/green]")


@auth_app.command("logout")
def auth_logout(domain: str = typer.Argument(help="Site domain")) -> None:
    """Clear stored authentication for a site."""
    from site2cli.auth.manager import AuthManager

    AuthManager().clear_auth(domain)
    console.print(f"[green]Cleared auth for {domain}[/green]")


# --- MCP Commands ---

mcp_app = typer.Typer(help="MCP server management")
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("generate")
def mcp_generate(
    domain: str = typer.Argument(help="Site domain to generate MCP server for"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
) -> None:
    """Generate an MCP server for a discovered site."""
    from site2cli.config import get_config
    from site2cli.discovery.spec_generator import load_spec
    from site2cli.generators.mcp_gen import generate_mcp_server_code, save_mcp_server

    config = get_config()
    registry = _get_registry()
    site = registry.get_site(domain)

    if not site:
        console.print(
            f"[red]Site {domain} not found.[/red]"
            f" Run `site2cli discover {domain}` first."
        )
        raise typer.Exit(1)

    if not site.openapi_spec_path:
        console.print("[red]No OpenAPI spec found for this site.[/red]")
        raise typer.Exit(1)

    spec = load_spec(Path(site.openapi_spec_path))
    code = generate_mcp_server_code(site, spec)

    output_path = (
        Path(output)
        if output
        else config.data_dir / "mcp" / f"{domain.replace('.', '_')}_mcp.py"
    )
    save_mcp_server(code, output_path)
    console.print(f"[green]MCP server generated at {output_path}[/green]")
    console.print(f"\nRun it with: python {output_path}")


@mcp_app.command("serve")
def mcp_serve(
    domain: str = typer.Argument(help="Site domain to serve MCP for"),
) -> None:
    """Start an MCP server for a discovered site."""
    from site2cli.config import get_config

    config = get_config()
    server_path = config.data_dir / "mcp" / f"{domain.replace('.', '_')}_mcp.py"

    if not server_path.exists():
        console.print("[yellow]MCP server not found. Generating...[/yellow]")
        mcp_generate(domain)

    import subprocess
    import sys

    console.print(f"[green]Starting MCP server for {domain}...[/green]")
    subprocess.run([sys.executable, str(server_path)])


# --- Health Commands ---

health_app = typer.Typer(help="API health monitoring")
app.add_typer(health_app, name="health")


@health_app.command("check")
def health_check(
    domain: Optional[str] = typer.Argument(None, help="Site domain (all if omitted)"),
) -> None:
    """Check health of discovered APIs."""
    from site2cli.health.monitor import HealthMonitor

    registry = _get_registry()
    monitor = HealthMonitor(registry)

    if domain:
        with console.status(f"[bold green]Checking {domain}..."):
            results = _run_async(monitor.check_site(domain))

        for action, status in results.items():
            icon = {"healthy": "[green]OK", "degraded": "[yellow]WARN", "broken": "[red]FAIL"}.get(
                status.value, "[dim]?"
            )
            console.print(f"  {icon}[/] {action}")
    else:
        with console.status("[bold green]Checking all sites..."):
            results = _run_async(monitor.check_all_sites())

        for site_domain, actions in results.items():
            console.print(f"\n[bold]{site_domain}[/bold]")
            for action, status in actions.items():
                status_icons = {
                    "healthy": "[green]OK",
                    "degraded": "[yellow]WARN",
                    "broken": "[red]FAIL",
                }
                icon = status_icons.get(status.value, "[dim]?")
                console.print(f"  {icon}[/] {action}")


@health_app.command("repair")
def health_repair(
    domain: str = typer.Argument(help="Site domain"),
    action: str = typer.Argument(help="Action to repair"),
) -> None:
    """Attempt to auto-repair a broken action."""
    from site2cli.health.self_heal import SelfHealer

    registry = _get_registry()
    healer = SelfHealer(registry)

    with console.status(f"[bold green]Diagnosing {domain}/{action}..."):
        result = _run_async(healer.diagnose_and_repair(domain, action))

    status = result.get("status", "unknown")
    if status == "repaired":
        console.print(f"[green]Repaired![/green] {result.get('message', '')}")
    else:
        console.print(f"[red]{status}[/red]: {result.get('message', '')}")


# --- Community Commands ---

community_app = typer.Typer(help="Community spec sharing")
app.add_typer(community_app, name="community")


@community_app.command("export")
def community_export(
    domain: str = typer.Argument(help="Site domain to export"),
    output: Optional[str] = typer.Option(None, "--output", "-o"),
) -> None:
    """Export a site spec for community sharing."""
    from site2cli.community.registry import CommunityRegistry

    registry = _get_registry()
    community = CommunityRegistry(registry)
    path = community.export_site(domain, Path(output) if output else None)
    console.print(f"[green]Exported to {path}[/green]")


@community_app.command("import")
def community_import(
    path: str = typer.Argument(help="Path to .site2cli.json bundle"),
) -> None:
    """Import a community-shared site spec."""
    from site2cli.community.registry import CommunityRegistry

    registry = _get_registry()
    community = CommunityRegistry(registry)
    site = community.import_site(Path(path))
    console.print(f"[green]Imported {site.domain} with {len(site.actions)} actions[/green]")


@community_app.command("list")
def community_list() -> None:
    """List available community specs."""
    from site2cli.community.registry import CommunityRegistry

    registry = _get_registry()
    community = CommunityRegistry(registry)
    specs = community.list_available()

    if not specs:
        console.print("[yellow]No community specs found.[/yellow]")
        return

    table = Table(title="Community Specs")
    table.add_column("Domain", style="bold")
    table.add_column("Actions")
    table.add_column("Description")

    for spec in specs:
        table.add_row(spec["domain"], str(spec["actions"]), spec["description"][:60])
    console.print(table)


# --- Config Commands ---

config_app = typer.Typer(help="Configuration management")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    """Show current configuration."""
    from site2cli.config import get_config

    config = get_config()
    console.print(json.dumps(config.model_dump(mode="json"), indent=2, default=str))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(help="Config key (dot notation, e.g. llm.model)"),
    value: str = typer.Argument(help="Config value"),
) -> None:
    """Set a configuration value."""
    from site2cli.config import get_config, reset_config

    config = get_config()
    parts = key.split(".")

    # Navigate to the right attribute
    obj = config
    for part in parts[:-1]:
        obj = getattr(obj, part)
    setattr(obj, parts[-1], value)
    config.save()
    reset_config()
    console.print(f"[green]Set {key} = {value}[/green]")


@app.command()
def setup() -> None:
    """Set up site2cli: install browsers, validate dependencies, create directories."""
    import sys

    from site2cli.config import get_config

    config = get_config()
    config.ensure_dirs()
    console.print(f"[green]OK[/green] Data directory: {config.data_dir}")

    # Check Python version
    v = sys.version_info
    if v >= (3, 10):
        console.print(f"[green]OK[/green] Python {v.major}.{v.minor}.{v.micro}")
    else:
        console.print(f"[red]FAIL[/red] Python >= 3.10 required, got {v.major}.{v.minor}")

    # Check Playwright
    try:
        import importlib.util
        if importlib.util.find_spec("playwright") is None:
            raise ImportError
        console.print("[green]OK[/green] Playwright installed")

        # Try to install browsers
        import subprocess

        console.print("    Installing Chromium browser...")
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print("[green]OK[/green] Chromium browser installed")
        else:
            console.print(f"[yellow]WARN[/yellow] Browser install failed: {result.stderr[:100]}")
    except ImportError:
        console.print(
            "[yellow]SKIP[/yellow] Playwright not installed"
            " (install with: pip install site2cli[browser])"
        )

    # Check Anthropic SDK
    try:
        import importlib.util
        if importlib.util.find_spec("anthropic") is None:
            raise ImportError
        console.print("[green]OK[/green] Anthropic SDK installed")
        try:
            config.llm.get_api_key()
            console.print("[green]OK[/green] ANTHROPIC_API_KEY configured")
        except ValueError:
            console.print(
                "[yellow]SKIP[/yellow] ANTHROPIC_API_KEY not set"
                " (needed for LLM-enhanced discovery)"
            )
    except ImportError:
        console.print(
            "[yellow]SKIP[/yellow] Anthropic SDK not installed"
            " (install with: pip install site2cli[llm])"
        )

    # Check MCP SDK
    try:
        import importlib.util
        if importlib.util.find_spec("mcp") is None:
            raise ImportError
        console.print("[green]OK[/green] MCP SDK installed")
    except ImportError:
        console.print(
            "[yellow]SKIP[/yellow] MCP SDK not installed"
            " (install with: pip install site2cli[mcp])"
        )

    # Check keyring
    try:
        import keyring
        backend = keyring.get_keyring().__class__.__name__
        console.print(f"[green]OK[/green] Keyring backend: {backend}")
    except Exception as e:
        console.print(f"[yellow]WARN[/yellow] Keyring issue: {e}")

    console.print()
    console.print("[bold]Setup complete.[/bold] Run `site2cli discover <url>` to get started.")


@app.command()
def version() -> None:
    """Show site2cli version."""
    console.print(f"site2cli v{__version__}")


if __name__ == "__main__":
    app()
