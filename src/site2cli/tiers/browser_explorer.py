"""Tier 1: LLM-driven browser automation for unknown sites."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from site2cli.config import get_config
from site2cli.discovery.capture import TrafficCapture

if TYPE_CHECKING:
    from playwright.async_api import Page


class BrowserExplorer:
    """Tier 1 executor: uses LLM to drive browser interactions."""

    def __init__(self, registry: object | None = None) -> None:
        self._config = get_config()
        self._registry = registry  # SiteRegistry for saving workflows

    async def explore(self, url: str, goal: str) -> dict:
        """Use LLM-driven browser to accomplish a goal on a website.

        Args:
            url: The URL to navigate to.
            goal: Natural language description of what to accomplish.

        Returns:
            Dict with extracted data and captured traffic.
        """
        capture = TrafficCapture(target_domain=_extract_domain(url))

        async def interaction(page: Page) -> None:
            await self._llm_driven_interaction(page, goal)

        await capture.capture_page_traffic(url, interaction_callback=interaction)

        return {
            "exchanges": capture.get_api_exchanges(),
            "summary": capture.summarize(),
        }

    async def execute_action(
        self,
        url: str,
        action: str,
        params: dict | None = None,
        *,
        profile: str | None = None,
        inject_cookies_for: str | None = None,
    ) -> dict:
        """Execute a specific action on a website using browser automation.

        Args:
            url: The URL to navigate to.
            action: The action to perform (e.g., "search flights").
            params: Parameters for the action.
            profile: Browser profile name to use.
            inject_cookies_for: Domain to inject stored cookies for.

        Returns:
            Dict with the result of the action.
        """
        from site2cli.browser.context import create_browser_context

        config = self._config
        domain = _extract_domain(url)
        async with create_browser_context(
            profile=profile or config.browser.profile,
            inject_cookies_for=inject_cookies_for or domain,
        ) as (_browser, _context, page):
            try:
                await page.goto(url, wait_until="networkidle", timeout=config.browser.timeout_ms)
            except Exception:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=config.browser.timeout_ms
                )

            # Dismiss cookie banners before interaction
            try:
                from site2cli.browser.cookie_banner import dismiss_cookie_banner

                await dismiss_cookie_banner(page)
            except Exception:
                pass

            result = await self._llm_driven_interaction(
                page, action, params
            )

            # Record workflow from LLM exploration history
            if self._registry and result.get("history"):
                self._record_workflow(
                    domain=domain,
                    action_name=action,
                    history=result["history"],
                )

            return result

    async def _llm_driven_interaction(
        self, page: Page, goal: str, params: dict | None = None
    ) -> dict:
        """Use LLM to decide what actions to take on the page.

        This is the core LLM-browser loop:
        1. Get page state (DOM snapshot, screenshot)
        2. Ask LLM what to do next
        3. Execute the action
        4. Repeat until goal is achieved or max steps reached
        """
        config = self._config
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=config.llm.get_api_key())
        except (ImportError, ValueError) as e:
            return {"error": str(e), "message": "LLM not available for browser exploration"}

        max_steps = 25
        history: list[dict] = []
        result_data: dict = {}

        # Step 0: Page preparation — cookie banners and auth detection
        try:
            from site2cli.browser.cookie_banner import dismiss_cookie_banner

            await dismiss_cookie_banner(page)
        except Exception:
            pass

        try:
            from site2cli.browser.detectors import detect_auth_page

            auth_result = await detect_auth_page(page)
            if auth_result.detected and auth_result.requires_human:
                from urllib.parse import urlparse as _urlparse

                _domain = _urlparse(page.url).hostname or ""
                return {
                    "error": "Auth required",
                    "auth_kind": auth_result.kind,
                    "provider": auth_result.provider,
                    "suggestion": f"Run site2cli auth login {_domain}",
                }
        except Exception:
            pass

        for step in range(max_steps):
            # Get page state
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            try:
                page_title = await page.title()
            except Exception:
                page_title = "(loading)"
            page_url = page.url

            # Get page elements — prefer a11y tree, fall back to CSS queries
            use_a11y = False
            a11y_nodes = []
            try:
                from site2cli.browser.a11y import extract_a11y_tree, format_a11y_for_llm

                a11y_nodes = await extract_a11y_tree(page)
                if a11y_nodes:
                    page_elements_str = format_a11y_for_llm(a11y_nodes)
                    use_a11y = True
            except Exception:
                pass

            if not use_a11y:
                visible_text = await page.evaluate("""() => {
                    const elements = document.querySelectorAll(
                        'a, button, input, select, textarea, '
                        + 'h1, h2, h3, p, span, label, '
                        + '[role="button"], [role="link"]'
                    );
                    const items = [];
                    for (const el of elements) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 && rect.height === 0) continue;
                        const tag = el.tagName.toLowerCase();
                        const text = el.textContent?.trim().slice(0, 200) || '';
                        if (!text && !el.href && !el.name && !el.placeholder) continue;
                        const attrs = {};
                        if (el.id) attrs.id = el.id;
                        if (el.name) attrs.name = el.name;
                        if (el.type) attrs.type = el.type;
                        if (el.placeholder) attrs.placeholder = el.placeholder;
                        if (el.href) attrs.href = el.href;
                        if (el.value) attrs.value = el.value.slice(0, 50);
                        if (el.download !== undefined && el.download !== '')
                            attrs.download = el.download;
                        const selector = el.id ? '#' + el.id
                            : el.name ? `${tag}[name="${el.name}"]`
                            : el.className ? `${tag}.${el.className.split(' ')[0]}`
                            : tag;
                        items.push({tag, text, attrs, selector});
                    }
                    return items.slice(0, 100);
                }""")
                page_elements_str = json.dumps(visible_text, indent=2)

            # Ask LLM what to do
            elements_label = "Accessibility tree" if use_a11y else "Interactive elements on page"
            a11y_note = (
                "\n- Interactive elements are shown as [@N] [role] \"name\"."
                " You can use click_index/fill_index with the element number N"
                " for more reliable interaction, or use CSS selectors."
                if use_a11y
                else ""
            )
            prompt = f"""You are navigating a website to accomplish a goal.

Goal: {goal}
Parameters: {json.dumps(params) if params else "None"}

Current page:
- Title: {page_title}
- URL: {page_url}{a11y_note}

{elements_label}:
{page_elements_str}

Previous actions taken:
{json.dumps(history, indent=2)}

What should I do next? Respond with a JSON object:
- If an action is needed: {{"action": "click|fill|select|navigate|scroll|wait|press|download|\
click_index|fill_index", \
"selector": "CSS selector", "index": N, "value": "value if filling/pressing key/download URL", \
"reason": "why"}}
- Use "click_index" with "index": N to click element [@N] (preferred over CSS selectors)
- Use "fill_index" with "index": N and "value" to type into element [@N]
- Use "press" with value like "Enter", "Tab", "Escape" for keyboard actions
- Use "download" with value as the file URL to download a file
- Use "scroll" with value as pixels to scroll (default 500)
- Use "wait" with value as condition: "network-idle", "load", "domcontentloaded", \
"exists:<selector>", "visible:<selector>", "hidden:<selector>", \
"url-contains:<text>", "text-contains:<text>", "stable"
- If the goal is achieved: {{"action": "done", \
"result": {{"extracted data here"}}, "reason": "why"}}
- If the goal can't be achieved: {{"action": "fail", \
"reason": "why"}}

Respond with ONLY the JSON object."""

            try:
                response = client.messages.create(
                    model=config.llm.model,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()
                # Parse JSON from response
                import re
                json_match = re.search(r"\{.*\}", text, re.DOTALL)
                if not json_match:
                    break
                instruction = json.loads(json_match.group())
            except Exception:
                break

            action = instruction.get("action", "fail")
            history.append({"step": step, "instruction": instruction})

            if action == "done":
                result_data = instruction.get("result", {})
                break
            elif action == "fail":
                result_data = {"error": instruction.get("reason", "Unknown failure")}
                break
            elif action == "click":
                selector = instruction.get("selector", "")
                try:
                    from site2cli.browser.retry import with_retry

                    await with_retry(
                        lambda: page.click(selector, timeout=5000),
                        retries=config.browser.action_retries,
                        delay_ms=config.browser.retry_delay_ms,
                    )
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception as e:
                    history.append({"step": step, "error": str(e)})
            elif action == "fill":
                selector = instruction.get("selector", "")
                value = instruction.get("value", "")
                try:
                    from site2cli.browser.retry import with_retry

                    await with_retry(
                        lambda: page.fill(selector, value),
                        retries=config.browser.action_retries,
                        delay_ms=config.browser.retry_delay_ms,
                    )
                except Exception as e:
                    history.append({"step": step, "error": str(e)})
            elif action == "select":
                selector = instruction.get("selector", "")
                value = instruction.get("value", "")
                try:
                    from site2cli.browser.retry import with_retry

                    await with_retry(
                        lambda: page.select_option(selector, value),
                        retries=config.browser.action_retries,
                        delay_ms=config.browser.retry_delay_ms,
                    )
                except Exception as e:
                    history.append({"step": step, "error": str(e)})
            elif action == "navigate":
                url = instruction.get("value", "")
                if url:
                    try:
                        await page.goto(url, wait_until="networkidle", timeout=10000)
                    except Exception as e:
                        history.append({"step": step, "error": str(e)})
            elif action == "press":
                key = instruction.get("value", "Enter")
                try:
                    from site2cli.browser.retry import with_retry

                    await with_retry(
                        lambda: page.keyboard.press(key),
                        retries=config.browser.action_retries,
                        delay_ms=config.browser.retry_delay_ms,
                    )
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception as e:
                    history.append({"step": step, "error": str(e)})
            elif action == "download":
                download_url = instruction.get("value", "")
                if download_url:
                    try:
                        from pathlib import Path

                        import httpx

                        resp = httpx.get(download_url, follow_redirects=True)
                        fname = download_url.split("/")[-1]
                        if not fname or "." not in fname:
                            fname = "download.pdf"
                        dl_dir = Path.cwd() / "downloads"
                        dl_dir.mkdir(exist_ok=True)
                        dl_path = dl_dir / fname
                        dl_path.write_bytes(resp.content)
                        result_data = {
                            "downloaded": str(dl_path),
                            "size_bytes": len(resp.content),
                        }
                        history.append({
                            "step": step,
                            "info": f"Downloaded {len(resp.content)} bytes to {dl_path}",
                        })
                    except Exception as e:
                        history.append({"step": step, "error": str(e)})
            elif action == "click_index":
                idx = instruction.get("index")
                if idx is not None and a11y_nodes:
                    try:
                        from site2cli.browser.a11y import get_node_by_index
                        from site2cli.browser.retry import with_retry

                        target = get_node_by_index(a11y_nodes, int(idx))
                        if target:
                            await with_retry(
                                lambda: page.get_by_role(
                                    target.role, name=target.name
                                ).first.click(timeout=5000),
                                retries=config.browser.action_retries,
                                delay_ms=config.browser.retry_delay_ms,
                            )
                            await page.wait_for_load_state("networkidle", timeout=5000)
                        else:
                            history.append({"step": step, "error": f"No element at index {idx}"})
                    except Exception as e:
                        history.append({"step": step, "error": str(e)})
            elif action == "fill_index":
                idx = instruction.get("index")
                value = instruction.get("value", "")
                if idx is not None and a11y_nodes:
                    try:
                        from site2cli.browser.a11y import get_node_by_index
                        from site2cli.browser.retry import with_retry

                        target = get_node_by_index(a11y_nodes, int(idx))
                        if target:
                            await with_retry(
                                lambda: page.get_by_role(
                                    target.role, name=target.name
                                ).first.fill(value),
                                retries=config.browser.action_retries,
                                delay_ms=config.browser.retry_delay_ms,
                            )
                        else:
                            history.append({"step": step, "error": f"No element at index {idx}"})
                    except Exception as e:
                        history.append({"step": step, "error": str(e)})
            elif action == "scroll":
                distance = int(instruction.get("value", "500"))
                await page.evaluate(f"window.scrollBy(0, {distance})")
            elif action == "wait":
                condition = instruction.get("value", "network-idle")
                timeout = int(instruction.get("timeout", "5000"))
                try:
                    from site2cli.browser.wait import wait_for_condition

                    await wait_for_condition(page, condition, timeout)
                except ValueError:
                    await page.wait_for_timeout(2000)

        return {
            "result": result_data,
            "steps_taken": len(history),
            "history": history,
        }


    def _record_workflow(
        self, domain: str, action_name: str, history: list[dict]
    ) -> None:
        """Convert LLM exploration history into a RecordedWorkflow and save it."""
        from site2cli.models import WorkflowStep
        from site2cli.tiers.cached_workflow import WorkflowRecorder

        recorder = WorkflowRecorder()
        for entry in history:
            instruction = entry.get("instruction", {})
            act = instruction.get("action", "")
            if act in ("done", "fail", ""):
                continue
            selector = instruction.get("selector")
            value = instruction.get("value")
            idx = instruction.get("index")
            description = instruction.get("reason", "")

            # For index-based actions, note the index in description
            if act in ("click_index", "fill_index") and idx is not None:
                description = f"{act} [@{idx}]: {description}"

            recorder.add_step(WorkflowStep(
                action=act.replace("_index", ""),  # normalize to base action
                selector=selector,
                value=value,
                description=description,
            ))

        if recorder.steps:
            workflow = recorder.build(domain, action_name)
            try:
                self._registry.save_workflow(workflow)
                # Update action tier to WORKFLOW
                self._registry.update_action_tier(
                    domain,
                    action_name,
                    __import__("site2cli.models", fromlist=["Tier"]).Tier.WORKFLOW,
                )
            except Exception:
                pass  # Don't fail the action if recording fails


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.hostname or url
