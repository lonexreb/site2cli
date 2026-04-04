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
    proxy: Optional[str] = typer.Option(None, "--proxy", help="Proxy URL for requests"),
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
    if proxy:
        config.proxy.url = proxy

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
    output_format: Optional[str] = typer.Option(
        None, "--format", "-f", help="Output format: json, markdown, text"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Browser profile to use"),
    session: Optional[str] = typer.Option(None, "--session", help="Session name to reuse"),
    proxy: Optional[str] = typer.Option(None, "--proxy", help="Proxy URL for requests"),
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
    if proxy:
        config.proxy.url = proxy

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

    # Format-specific output
    if output_format == "markdown":
        text = json.dumps(result, indent=2, default=str)
        console.print(text)
    elif output_format == "text":
        text = json.dumps(result, indent=2, default=str)
        console.print(text)
    else:
        indent = None if compact else 2
        if json_output or compact:
            console.print(json.dumps(result, indent=indent, default=str))
        else:
            from rich.json import JSON

            console.print(JSON(json.dumps(result, indent=2, default=str)))


# --- Extract & Scrape Commands ---


@app.command()
def extract(
    url: str = typer.Argument(help="URL to extract structured data from"),
    urls: Optional[list[str]] = typer.Option(
        None, "--url", "-u", help="Additional URLs to extract from"
    ),
    prompt: Optional[str] = typer.Option(
        None, "--prompt", "-p", help="What data to extract (natural language)"
    ),
    schema: Optional[str] = typer.Option(
        None, "--schema", "-s",
        help="JSON Schema: inline JSON, .json file path, or Pydantic model (module.Class)",
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save result to file"),
    compact: bool = typer.Option(False, "--compact", help="Single-line JSON output"),
    proxy: Optional[str] = typer.Option(None, "--proxy", help="Proxy URL"),
    main_content: bool = typer.Option(
        True, "--main-content/--full-page", help="Extract main content only"
    ),
) -> None:
    """Extract structured data from a web page using LLM + schema validation.

    Like Firecrawl /extract but local, free, and schema-driven.

    Examples:
        site2cli extract https://example.com -p "Extract the page title and description"
        site2cli extract https://example.com -s schema.json
        site2cli extract https://example.com -s schema.json -p "Get all product prices"
    """
    from site2cli.extract.extractor import extract as do_extract
    from site2cli.extract.extractor import extract_batch

    all_urls = [url] + (urls or [])

    async def _extract():
        if len(all_urls) == 1:
            return await do_extract(
                all_urls[0],
                prompt=prompt,
                schema=schema,
                main_content_only=main_content,
                proxy=proxy,
            )
        else:
            results = await extract_batch(
                all_urls, prompt=prompt, schema=schema,
                main_content_only=main_content, proxy=proxy,
            )
            return results

    with console.status("[bold green]Extracting structured data..."):
        result = _run_async(_extract())

    # Handle single vs batch results
    if isinstance(result, list):
        output_data = [r.model_dump(mode="json") for r in result]
        successes = sum(1 for r in result if r.success)
        console.print(
            f"[bold]Extracted from {successes}/{len(result)} URLs[/bold]"
        )
    else:
        output_data = result.model_dump(mode="json")
        if result.success:
            console.print("[bold green]Extraction successful[/bold green]")
            if result.usage:
                tokens = result.usage.get("input_tokens", 0) + result.usage.get("output_tokens", 0)
                console.print(f"  Tokens used: {tokens}")
        else:
            console.print(f"[bold red]Extraction failed:[/bold red] {result.error}")

    # Output
    if output:
        Path(output).write_text(json.dumps(output_data, indent=2, default=str))
        console.print(f"  Saved to [bold]{output}[/bold]")
    else:
        # Show just the data for clean output
        if isinstance(result, list):
            display = [r.data for r in result if r.success]
        else:
            display = result.data if result.success else output_data
        from rich.json import JSON

        console.print(JSON(json.dumps(display, indent=2, default=str)))


@app.command()
def scrape(
    url: str = typer.Argument(help="URL to scrape"),
    output_format: str = typer.Option(
        "markdown", "--format", "-f", help="Output format: markdown, text, html"
    ),
    main_content: bool = typer.Option(
        True, "--main-content/--full-page", help="Extract main content only"
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save to file"),
    proxy: Optional[str] = typer.Option(None, "--proxy", help="Proxy URL"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Browser profile for auth"),
) -> None:
    """Scrape a web page and convert to markdown, text, or HTML.

    Examples:
        site2cli scrape https://example.com
        site2cli scrape https://example.com --format text
        site2cli scrape https://example.com --format html --full-page
    """
    from site2cli.content.converter import fetch_and_convert

    with console.status("[bold green]Fetching and converting..."):
        result = fetch_and_convert(
            url,
            output_format=output_format,
            main_content_only=main_content,
            proxy=proxy,
        )

    content = result["content"]
    console.print(f"[dim]Source: {result['url']} ({result['status_code']})[/dim]\n")

    if output:
        Path(output).write_text(content)
        console.print(f"Saved to [bold]{output}[/bold] ({len(content)} chars)")
    else:
        if output_format == "markdown":
            from rich.markdown import Markdown

            console.print(Markdown(content))
        else:
            console.print(content)


# --- Crawl, Monitor & Screenshot Commands ---


@app.command()
def crawl(
    url: str = typer.Argument(help="URL to start crawling from"),
    depth: int = typer.Option(3, "--depth", "-d", help="Maximum crawl depth"),
    max_pages: int = typer.Option(100, "--max-pages", "-n", help="Maximum pages to crawl"),
    output_format: Optional[str] = typer.Option(
        "markdown", "--format", "-f", help="Output format: markdown, text, html, jsonl"
    ),
    main_content: bool = typer.Option(
        True, "--main-content/--full-page", help="Extract main content only"
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save to file/directory"),
    stream: bool = typer.Option(False, "--stream", help="Stream JSONL as pages are crawled"),
    sitemap: bool = typer.Option(False, "--sitemap", help="Only list discovered URLs"),
    no_robots: bool = typer.Option(False, "--no-robots", help="Ignore robots.txt"),
    resume: Optional[str] = typer.Option(None, "--resume", help="Resume a previous crawl by ID"),
    proxy: Optional[str] = typer.Option(None, "--proxy", help="Proxy URL"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Browser profile"),
    session: Optional[str] = typer.Option(None, "--session", help="Session name"),
) -> None:
    """Crawl an entire website and convert pages to markdown/text/HTML.

    Examples:
        site2cli crawl https://docs.example.com
        site2cli crawl https://example.com -d 2 -n 50 --format jsonl --stream
        site2cli crawl https://example.com --sitemap
    """
    from site2cli.config import get_config
    from site2cli.crawl.crawler import SiteCrawler

    config = get_config()
    if proxy:
        config.proxy.url = proxy

    # Resume support
    visited: set[str] | None = None
    job_id = resume
    if resume:
        registry = _get_registry()
        visited = registry.get_crawled_urls(resume)
        console.print(f"[dim]Resuming crawl {resume} ({len(visited)} pages already crawled)[/dim]")

    crawler = SiteCrawler(
        start_url=url,
        max_depth=depth,
        max_pages=max_pages,
        output_format=output_format or "markdown",
        main_content_only=main_content,
        respect_robots=not no_robots,
        sitemap_only=sitemap,
        delay_ms=config.crawl.delay_ms,
        concurrent=config.crawl.concurrent_requests,
        proxy=config.proxy.get_httpx_proxy(),
        user_agent=config.crawl.user_agent,
        job_id=job_id,
        visited=visited,
    )

    pages: list = []
    registry = _get_registry()
    job = crawler.get_job()
    registry.save_crawl_job(job)

    async def _crawl():
        async for page in crawler.crawl():
            registry.save_crawl_page(job.id, page)
            pages.append(page)

    if stream or sitemap:
        # Stream mode: print as we go
        async def _stream():
            async for page in crawler.crawl():
                registry.save_crawl_page(job.id, page)
                pages.append(page)
                if sitemap:
                    console.print(page.url)
                else:
                    import json as _json
                    line = _json.dumps(
                        {"url": page.url, "title": page.title, "depth": page.depth,
                         "status_code": page.status_code, "content": page.content},
                        default=str,
                    )
                    console.print(line)

        _run_async(_stream())
    else:
        with console.status("[bold green]Crawling...") as status:
            async def _crawl_with_progress():
                async for page in crawler.crawl():
                    registry.save_crawl_page(job.id, page)
                    pages.append(page)
                    status.update(
                        f"[bold green]Crawling... {len(pages)}/{max_pages} pages"
                        f" (depth {page.depth}) — {page.url[:60]}"
                    )

            _run_async(_crawl_with_progress())

    # Update job status
    from site2cli.models import CrawlStatus
    job.status = CrawlStatus.COMPLETED
    job.pages_crawled = len(pages)
    from datetime import datetime
    job.completed_at = datetime.utcnow()
    registry.save_crawl_job(job)

    errors = sum(1 for p in pages if p.error)
    console.print(
        f"\n[bold]Crawled {len(pages)} pages[/bold]"
        f" ({errors} errors) from {crawler.domain}"
        f"\n[dim]Job ID: {job.id}[/dim]"
    )

    # Save to output
    if output and not sitemap and not stream:
        out_path = Path(output)
        if output_format == "jsonl":
            with open(out_path, "w") as f:
                for p in pages:
                    f.write(json.dumps(
                        {"url": p.url, "title": p.title, "depth": p.depth,
                         "status_code": p.status_code, "content": p.content},
                        default=str,
                    ) + "\n")
        else:
            out_path.mkdir(parents=True, exist_ok=True)
            for p in pages:
                if p.content:
                    from urllib.parse import urlparse
                    slug = urlparse(p.url).path.strip("/").replace("/", "_") or "index"
                    ext = {"markdown": "md", "text": "txt", "html": "html"}.get(
                        output_format or "markdown", "md"
                    )
                    (out_path / f"{slug}.{ext}").write_text(p.content)
        console.print(f"Saved to [bold]{output}[/bold]")


@app.command()
def monitor(
    url: str = typer.Argument("", help="URL to monitor for changes"),
    interval: Optional[int] = typer.Option(
        None, "--interval", "-i", help="Polling interval in seconds"
    ),
    webhook: Optional[str] = typer.Option(
        None, "--webhook", "-w", help="Webhook URL for notifications"
    ),
    output_format: Optional[str] = typer.Option(
        "diff", "--format", "-f", help="Output format: diff, json, markdown"
    ),
    main_content: bool = typer.Option(
        True, "--main-content/--full-page", help="Monitor main content only"
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save diff to file"),
    proxy: Optional[str] = typer.Option(None, "--proxy", help="Proxy URL"),
    list_watches: bool = typer.Option(False, "--list", help="List active watches"),
    stop: Optional[str] = typer.Option(None, "--stop", help="Stop a watch by ID"),
    history: Optional[str] = typer.Option(None, "--history", help="Show history for watch ID"),
) -> None:
    """Monitor a URL for content changes with diffing.

    Examples:
        site2cli monitor https://example.com/pricing
        site2cli monitor https://example.com --interval 300
        site2cli monitor https://example.com --webhook https://hooks.slack.com/xxx
        site2cli monitor --list
    """
    import uuid

    from site2cli.config import get_config
    from site2cli.models import MonitorWatch
    from site2cli.monitor.differ import format_diff
    from site2cli.monitor.watcher import ChangeWatcher

    registry = _get_registry()
    config = get_config()
    proxy_url = proxy or config.proxy.get_httpx_proxy()

    if list_watches:
        watches = registry.list_monitor_watches(active_only=False)
        if not watches:
            console.print("[yellow]No watches configured.[/yellow]")
            return
        table = Table(title="Monitor Watches")
        table.add_column("ID", style="dim", max_width=8)
        table.add_column("URL", style="bold")
        table.add_column("Checks")
        table.add_column("Changes")
        table.add_column("Active")
        table.add_column("Last Checked")
        for w in watches:
            table.add_row(
                w.id[:8],
                w.url[:60],
                str(w.check_count),
                str(w.change_count),
                "Yes" if w.active else "No",
                w.last_checked.strftime("%Y-%m-%d %H:%M") if w.last_checked else "-",
            )
        console.print(table)
        return

    if stop:
        # Find watch by prefix
        watches = registry.list_monitor_watches(active_only=False)
        match = [w for w in watches if w.id.startswith(stop)]
        if not match:
            console.print(f"[red]Watch {stop} not found.[/red]")
            raise typer.Exit(1)
        w = match[0]
        w.active = False
        registry.save_monitor_watch(w)
        console.print(f"[green]Stopped watch {w.id[:8]} for {w.url}[/green]")
        return

    if history:
        snapshots = registry.get_snapshot_history(history, limit=20)
        if not snapshots:
            # Try prefix match
            watches = registry.list_monitor_watches(active_only=False)
            match = [w for w in watches if w.id.startswith(history)]
            if match:
                snapshots = registry.get_snapshot_history(match[0].id, limit=20)
        if not snapshots:
            console.print(f"[red]No history found for {history}.[/red]")
            return
        table = Table(title="Snapshot History")
        table.add_column("Time")
        table.add_column("Status")
        table.add_column("Hash", style="dim", max_width=12)
        for s in snapshots:
            table.add_row(
                s.captured_at.strftime("%Y-%m-%d %H:%M:%S"),
                str(s.status_code),
                s.content_hash[:12],
            )
        console.print(table)
        return

    if not url:
        console.print("[red]URL is required (or use --list, --stop, --history).[/red]")
        raise typer.Exit(1)

    # Create or find existing watch
    watches = registry.list_monitor_watches(active_only=False)
    existing = [w for w in watches if w.url == url]
    if existing:
        watch = existing[0]
        watch.active = True
        if webhook:
            watch.webhook_url = webhook
    else:
        watch = MonitorWatch(
            id=str(uuid.uuid4()),
            url=url,
            interval_seconds=interval or 0,
            webhook_url=webhook,
            output_format=output_format or "diff",
            main_content_only=main_content,
        )
    registry.save_monitor_watch(watch)

    watcher = ChangeWatcher(registry)

    if interval:
        # Polling mode
        import asyncio

        console.print(
            f"[bold]Monitoring {url} every {interval}s[/bold]"
            f" (Ctrl+C to stop)"
        )

        async def _poll():
            while True:
                try:
                    diff = await watcher.check(watch, proxy=proxy_url)
                    if diff.changed:
                        console.print(
                            f"\n[bold yellow]Change detected![/bold yellow]"
                            f" +{diff.added_lines} -{diff.removed_lines}"
                        )
                        console.print(format_diff(diff, output_format or "diff"))
                    else:
                        console.print(f"[dim]{watch.check_count} checks, no change[/dim]")
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
                await asyncio.sleep(interval)

        try:
            _run_async(_poll())
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped monitoring.[/dim]")
    else:
        # One-shot mode
        with console.status("[bold green]Checking for changes..."):
            diff = _run_async(watcher.check(watch, proxy=proxy_url))

        if diff.changed:
            console.print(
                f"[bold yellow]Change detected![/bold yellow]"
                f" +{diff.added_lines} -{diff.removed_lines}"
            )
            diff_text = format_diff(diff, output_format or "diff")
            console.print(diff_text)
            if output:
                Path(output).write_text(diff_text)
                console.print(f"Saved to [bold]{output}[/bold]")
        else:
            is_baseline = watch.check_count <= 1
            if is_baseline:
                console.print(
                    f"[green]Baseline snapshot saved for {url}[/green]"
                    f"\n[dim]Watch ID: {watch.id[:8]}[/dim]"
                    f"\nRun again to check for changes."
                )
            else:
                console.print(f"[green]No changes detected for {url}[/green]")


@app.command()
def screenshot(
    url: str = typer.Argument(help="URL to capture"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
    selector: Optional[str] = typer.Option(
        None, "--selector", "-s", help="CSS selector for element"
    ),
    full_page: bool = typer.Option(True, "--full-page/--viewport", help="Full page or viewport"),
    fmt: str = typer.Option("png", "--format", "-f", help="Image format: png, jpeg"),
    quality: Optional[int] = typer.Option(None, "--quality", "-q", help="JPEG quality (1-100)"),
    width: int = typer.Option(1920, "--width", help="Viewport width"),
    height: int = typer.Option(1080, "--height", help="Viewport height"),
    wait: Optional[str] = typer.Option(None, "--wait", help="Wait condition before capture"),
    proxy: Optional[str] = typer.Option(None, "--proxy", help="Proxy URL"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Browser profile"),
    session: Optional[str] = typer.Option(None, "--session", help="Session name"),
) -> None:
    """Capture a screenshot of a web page.

    Examples:
        site2cli screenshot https://example.com
        site2cli screenshot https://example.com -o page.png
        site2cli screenshot https://example.com --selector ".main-content"
        site2cli screenshot https://example.com --viewport --format jpeg --quality 80
    """
    from site2cli.config import get_config
    from site2cli.screenshot.capture import take_screenshot

    config = get_config()
    proxy_dict = None
    if proxy:
        config.proxy.url = proxy
        proxy_dict = config.proxy.get_playwright_proxy()
    elif config.proxy.get_proxy_url():
        proxy_dict = config.proxy.get_playwright_proxy()

    with console.status("[bold green]Capturing screenshot..."):
        result = _run_async(take_screenshot(
            url=url,
            output=output,
            selector=selector,
            full_page=full_page,
            fmt=fmt,
            quality=quality,
            width=width,
            height=height,
            wait=wait,
            proxy=proxy_dict,
            profile=profile,
            session=session,
        ))

    console.print(f"[green]Screenshot saved to[/green] [bold]{result.path}[/bold]")
    console.print(f"[dim]{result.width}x{result.height}, {result.format}[/dim]")


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

    err_console = Console(stderr=True)
    err_console.print(
        f"[green]Starting unified MCP server"
        f" with {len(sites)} sites...[/green]",
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
