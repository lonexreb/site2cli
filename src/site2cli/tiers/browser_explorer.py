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

    def __init__(self) -> None:
        self._config = get_config()

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
        self, url: str, action: str, params: dict | None = None
    ) -> dict:
        """Execute a specific action on a website using browser automation.

        Args:
            url: The URL to navigate to.
            action: The action to perform (e.g., "search flights").
            params: Parameters for the action.

        Returns:
            Dict with the result of the action.
        """
        from playwright.async_api import async_playwright

        config = self._config
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=config.browser.headless)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=config.browser.timeout_ms)
            except Exception:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=config.browser.timeout_ms
                )

            result = await self._llm_driven_interaction(
                page, action, params
            )

            await browser.close()
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

            # Get visible text content (simplified DOM)
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

            # Ask LLM what to do
            prompt = f"""You are navigating a website to accomplish a goal.

Goal: {goal}
Parameters: {json.dumps(params) if params else "None"}

Current page:
- Title: {page_title}
- URL: {page_url}

Interactive elements on page:
{json.dumps(visible_text, indent=2)}

Previous actions taken:
{json.dumps(history, indent=2)}

What should I do next? Respond with a JSON object:
- If an action is needed: {{"action": "click|fill|select|navigate|scroll|wait|press|download", \
"selector": "CSS selector", "value": "value if filling/pressing key/download URL", "reason": "why"}}
- Use "press" with value like "Enter", "Tab", "Escape" for keyboard actions
- Use "download" with value as the file URL to download a file
- Use "scroll" with value as pixels to scroll (default 500)
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
                    await page.click(selector, timeout=5000)
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception as e:
                    history.append({"step": step, "error": str(e)})
            elif action == "fill":
                selector = instruction.get("selector", "")
                value = instruction.get("value", "")
                try:
                    await page.fill(selector, value)
                except Exception as e:
                    history.append({"step": step, "error": str(e)})
            elif action == "select":
                selector = instruction.get("selector", "")
                value = instruction.get("value", "")
                try:
                    await page.select_option(selector, value)
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
                    await page.keyboard.press(key)
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
            elif action == "scroll":
                distance = int(instruction.get("value", "500"))
                await page.evaluate(f"window.scrollBy(0, {distance})")
            elif action == "wait":
                await page.wait_for_timeout(2000)

        return {
            "result": result_data,
            "steps_taken": len(history),
            "history": history,
        }


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.hostname or url
