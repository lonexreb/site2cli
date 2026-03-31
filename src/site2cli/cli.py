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
    invoke_without_command=True,
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main_callback(
    mcp: bool = typer.Option(False, "--mcp", help="Run as unified MCP server for all sites"),
) -> None:
    """site2cli — Turn any website into a CLI/API for AI agents."""
    if mcp:
        mcp_serve_all()
        raise typer.Exit()


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
    profile: Optional[str] = typer.Option(None, "--profile", help="Browser profile to use"),
    session: Optional[str] = typer.Option(None, "--session", help="Session name to reuse"),
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
    if profile:
        config.browser.profile = profile
    if session:
        config.browser.session = session

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
    grep: Optional[str] = typer.Option(
        None, "--grep", "-g", help="Filter output keys matching pattern"
    ),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Limit array results"),
    keys_only: bool = typer.Option(False, "--keys-only", help="Show only top-level keys"),
    compact: bool = typer.Option(False, "--compact", help="Single-line JSON"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Browser profile to use"),
    session: Optional[str] = typer.Option(None, "--session", help="Session name to reuse"),
) -> None:
    """Execute a discovered action on a site."""
    from site2cli.router import Router

    config = get_config()
    if no_headless:
        config.browser.headless = False
    if profile:
        config.browser.profile = profile
    if session:
        config.browser.session = session

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

    # Apply output filters
    if grep or limit is not None or keys_only:
        from site2cli.output_filter import filter_result

        result = filter_result(result, grep=grep, limit=limit, keys_only=keys_only)

    indent = None if compact else 2
    if json_output or compact:
        console.print(json.dumps(result, indent=indent, default=str))
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


# --- Profile Commands ---


@auth_app.command("profile-import")
def auth_profile_import(
    browser_type: str = typer.Option(
        "chrome", "--browser", "-b", help="Browser: chrome or firefox"
    ),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Profile name"),
) -> None:
    """Import a browser profile for authenticated sessions."""
    from site2cli.auth.profiles import ProfileManager

    pm = ProfileManager()
    if browser_type == "chrome":
        profiles = pm.detect_chrome_profiles()
    elif browser_type == "firefox":
        profiles = pm.detect_firefox_profiles()
    else:
        console.print(f"[red]Unknown browser: {browser_type}[/red]")
        raise typer.Exit(1)

    if not profiles:
        console.print(f"[yellow]No {browser_type} profiles found.[/yellow]")
        raise typer.Exit(1)

    # Show available profiles and let user pick
    if len(profiles) == 1:
        source = profiles[0]
    else:
        console.print(f"[bold]Available {browser_type} profiles:[/bold]")
        for i, p in enumerate(profiles):
            console.print(f"  [{i}] {p.name}")
        idx = typer.prompt("Select profile number", type=int, default=0)
        source = profiles[idx]

    profile_name = name or f"{browser_type}-{source.name.lower().replace(' ', '-')}"
    with console.status(f"[bold green]Importing profile {source.name}..."):
        dest = pm.copy_profile(source, profile_name)
    console.print(f"[green]Profile imported as '{profile_name}'[/green] → {dest}")
    console.print(f"\nUse with: site2cli discover <url> --profile {profile_name}")


@auth_app.command("profile-list")
def auth_profile_list() -> None:
    """List imported browser profiles."""
    from site2cli.auth.profiles import ProfileManager

    pm = ProfileManager()
    profiles = pm.list_profiles()
    if not profiles:
        console.print("[yellow]No profiles imported yet.[/yellow]")
        return
    for name in profiles:
        console.print(f"  {name}")


@auth_app.command("profile-remove")
def auth_profile_remove(
    name: str = typer.Argument(help="Profile name to remove"),
) -> None:
    """Remove an imported browser profile."""
    from site2cli.auth.profiles import ProfileManager

    pm = ProfileManager()
    if pm.remove_profile(name):
        console.print(f"[green]Removed profile '{name}'[/green]")
    else:
        console.print(f"[red]Profile '{name}' not found[/red]")


# --- Cookie Commands ---

cookies_app = typer.Typer(help="Cookie management")
app.add_typer(cookies_app, name="cookies")


@cookies_app.command("list")
def cookies_list(
    domain: Optional[str] = typer.Argument(None, help="Domain (all domains if omitted)"),
) -> None:
    """List stored cookies."""
    from site2cli.auth.cookies import CookieManager

    cm = CookieManager()
    if domain:
        cookies = cm.list(domain)
        if not cookies:
            console.print(f"[yellow]No cookies stored for {domain}[/yellow]")
            return
        table = Table(title=f"Cookies for {domain}")
        table.add_column("Name", style="bold")
        table.add_column("Value")
        table.add_column("Path")
        table.add_column("Secure")
        table.add_column("HttpOnly")
        for c in cookies:
            table.add_row(
                c["name"],
                c["value"][:40] + ("..." if len(c["value"]) > 40 else ""),
                c["path"],
                str(c["secure"]),
                str(c["httpOnly"]),
            )
        console.print(table)
    else:
        domains = cm.list_domains()
        if not domains:
            console.print("[yellow]No cookies stored.[/yellow]")
            return
        for d in domains:
            count = len(cm.list(d))
            console.print(f"  {d} ({count} cookies)")


@cookies_app.command("set")
def cookies_set(
    domain: str = typer.Argument(help="Cookie domain"),
    name: str = typer.Argument(help="Cookie name"),
    value: str = typer.Argument(help="Cookie value"),
    path: str = typer.Option("/", help="Cookie path"),
    secure: bool = typer.Option(False, help="Secure flag"),
    http_only: bool = typer.Option(False, "--http-only", help="HttpOnly flag"),
) -> None:
    """Set a cookie for a domain."""
    from site2cli.auth.cookies import CookieManager

    cm = CookieManager()
    cm.set(domain, name, value, path=path, secure=secure, http_only=http_only)
    console.print(f"[green]Set cookie {name} for {domain}[/green]")


@cookies_app.command("clear")
def cookies_clear(
    domain: str = typer.Argument(help="Domain to clear cookies for"),
) -> None:
    """Clear all cookies for a domain."""
    from site2cli.auth.cookies import CookieManager

    cm = CookieManager()
    cm.clear(domain)
    console.print(f"[green]Cleared cookies for {domain}[/green]")


@cookies_app.command("export")
def cookies_export(
    domain: str = typer.Argument(help="Domain to export cookies for"),
) -> None:
    """Export cookies to a JSON file."""
    from site2cli.auth.cookies import CookieManager

    cm = CookieManager()
    path = cm.export(domain)
    console.print(f"[green]Exported to {path}[/green]")


@cookies_app.command("import")
def cookies_import(
    path: str = typer.Argument(help="Path to cookies JSON file"),
) -> None:
    """Import cookies from a JSON file."""
    from site2cli.auth.cookies import CookieManager

    cm = CookieManager()
    domain, count = cm.import_file(Path(path))
    console.print(f"[green]Imported {count} cookies for {domain}[/green]")


# --- Session Commands ---

session_app = typer.Typer(help="Browser session management")
app.add_typer(session_app, name="session")


@session_app.command("list")
def session_list() -> None:
    """List active browser sessions."""
    from site2cli.browser.session import get_session_manager

    sm = get_session_manager()
    sessions = sm.list()
    if not sessions:
        console.print("[yellow]No active sessions.[/yellow]")
        return
    for name in sessions:
        console.print(f"  {name}")


@session_app.command("close")
def session_close(
    name: str = typer.Argument(help="Session name to close"),
) -> None:
    """Close a browser session."""
    from site2cli.browser.session import get_session_manager

    sm = get_session_manager()
    _run_async(sm.close(name))
    console.print(f"[green]Closed session '{name}'[/green]")


@session_app.command("close-all")
def session_close_all() -> None:
    """Close all browser sessions."""
    from site2cli.browser.session import get_session_manager

    sm = get_session_manager()
    _run_async(sm.close_all())
    console.print("[green]Closed all sessions[/green]")


# --- Workflow Commands ---

workflows_app = typer.Typer(help="Manage recorded workflows")
app.add_typer(workflows_app, name="workflows")


@workflows_app.command("list")
def workflows_list() -> None:
    """List recorded workflows."""
    registry = _get_registry()
    workflows = registry.list_workflows()
    if not workflows:
        console.print("[yellow]No workflows recorded yet.[/yellow]")
        return
    table = Table(title="Recorded Workflows")
    table.add_column("ID", style="bold")
    table.add_column("Domain")
    table.add_column("Action")
    table.add_column("Steps")
    table.add_column("Replays")
    table.add_column("Recorded")
    for wf in workflows:
        table.add_row(
            wf.id[:8],
            wf.site_domain,
            wf.action_name,
            str(len(wf.steps)),
            str(wf.replay_count),
            wf.recorded_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@workflows_app.command("show")
def workflows_show(
    workflow_id: str = typer.Argument(help="Workflow ID (prefix match)"),
) -> None:
    """Show details of a recorded workflow."""
    registry = _get_registry()
    workflows = registry.list_workflows()
    match = None
    for wf in workflows:
        if wf.id.startswith(workflow_id):
            match = wf
            break
    if not match:
        console.print(f"[red]Workflow '{workflow_id}' not found[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]Workflow {match.id}[/bold]")
    console.print(f"  Domain: {match.site_domain}")
    console.print(f"  Action: {match.action_name}")
    console.print(f"  Recorded: {match.recorded_at}")
    console.print(f"  Replays: {match.replay_count}")
    console.print(f"\n[bold]Steps ({len(match.steps)}):[/bold]")
    for i, step in enumerate(match.steps):
        desc = step.description or f"{step.action} {step.selector or step.value or ''}"
        console.print(f"  {i + 1}. {desc}")


@workflows_app.command("delete")
def workflows_delete(
    workflow_id: str = typer.Argument(help="Workflow ID (prefix match)"),
) -> None:
    """Delete a recorded workflow."""
    registry = _get_registry()
    workflows = registry.list_workflows()
    for wf in workflows:
        if wf.id.startswith(workflow_id):
            registry.delete_workflow(wf.id)
            console.print(f"[green]Deleted workflow {wf.id[:8]}[/green]")
            return
    console.print(f"[red]Workflow '{workflow_id}' not found[/red]")


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


@mcp_app.command("serve-all")
def mcp_serve_all() -> None:
    """Start a unified MCP server for ALL discovered sites."""
    try:
        from site2cli.mcp.server import run_unified_mcp_server
    except ImportError:
        console.print(
            "[red]MCP SDK not installed.[/red]"
            " Install with: pip install site2cli[mcp]"
        )
        raise typer.Exit(1)

    registry = _get_registry()
    sites = registry.list_sites()
    if not sites:
        console.print(
            "[yellow]No sites discovered yet.[/yellow]"
            " Run `site2cli discover <url>` first."
        )
        raise typer.Exit(1)

    console.print(
        f"[green]Starting unified MCP server"
        f" with {len(sites)} sites...[/green]",
        err=True,
    )
    _run_async(run_unified_mcp_server(registry))


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
def init(
    agent: str = typer.Option("claude", help="Agent type: claude, generic, all"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path"),
) -> None:
    """Generate agent configuration for discovered sites."""
    from site2cli.generators.agent_config import (
        generate_claude_mcp_config,
        generate_generic_agent_prompt,
    )

    registry = _get_registry()
    sites = registry.list_sites()

    if agent in ("claude", "all"):
        config = generate_claude_mcp_config(sites)
        config_json = json.dumps(config, indent=2)
        if output and agent == "claude":
            output.write_text(config_json)
            console.print(f"[green]Claude MCP config written to {output}[/green]")
        else:
            console.print("[bold]Claude Code MCP Configuration:[/bold]")
            console.print(config_json)

    if agent in ("generic", "all"):
        prompt = generate_generic_agent_prompt(sites)
        if output and agent == "generic":
            output.write_text(prompt)
            console.print(f"[green]Agent prompt written to {output}[/green]")
        else:
            if agent == "all":
                console.print()
            console.print("[bold]Generic Agent Prompt:[/bold]")
            console.print(prompt)

    if not sites:
        console.print(
            "\n[yellow]No sites discovered yet.[/yellow]"
            " Run `site2cli discover <url>` first."
        )


# --- Daemon Commands ---

daemon_app = typer.Typer(help="Persistent browser daemon")
app.add_typer(daemon_app, name="daemon")


@daemon_app.command("start")
def daemon_start() -> None:
    """Start the background browser daemon."""
    from site2cli.daemon.server import DaemonServer

    config = get_config()
    server = DaemonServer(config.daemon_socket_path)
    console.print(
        f"[green]Starting daemon on {config.daemon_socket_path}...[/green]"
    )
    _run_async(server.run())


@daemon_app.command("stop")
def daemon_stop() -> None:
    """Stop the background browser daemon."""
    from site2cli.daemon.client import DaemonClient

    config = get_config()
    client = DaemonClient(config.daemon_socket_path)
    try:
        result = _run_async(client.send("shutdown", {}))
        console.print(f"[green]Daemon stopped: {result}[/green]")
    except Exception as e:
        console.print(f"[yellow]Daemon not running or error: {e}[/yellow]")
    # Clean up socket file
    if config.daemon_socket_path.exists():
        config.daemon_socket_path.unlink()


@daemon_app.command("status")
def daemon_status() -> None:
    """Check if the daemon is running."""
    config = get_config()
    if not config.daemon_socket_path.exists():
        console.print("[yellow]Daemon is not running.[/yellow]")
        return
    from site2cli.daemon.client import DaemonClient

    client = DaemonClient(config.daemon_socket_path)
    try:
        result = _run_async(client.send("list_sessions", {}))
        sessions = result.get("sessions", [])
        console.print(f"[green]Daemon is running.[/green] {len(sessions)} active sessions.")
    except Exception:
        console.print("[yellow]Daemon socket exists but is not responding.[/yellow]")


@app.command()
def version() -> None:
    """Show site2cli version."""
    console.print(f"site2cli v{__version__}")


if __name__ == "__main__":
    app()
