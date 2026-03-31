"""Tier 2: Cached/recorded workflow replay."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from site2cli.config import get_config
from site2cli.models import ParameterInfo, RecordedWorkflow, WorkflowStep

if TYPE_CHECKING:
    from playwright.async_api import Page


class WorkflowRecorder:
    """Records browser interactions as replayable workflows."""

    def __init__(self, domain: str = "", name: str = "") -> None:
        self._config = get_config()
        self._domain = domain
        self._name = name
        self._steps: list[WorkflowStep] = []
        self._parameters: list[ParameterInfo] = []

    @property
    def steps(self) -> list[WorkflowStep]:
        return self._steps

    def add_step(self, step: WorkflowStep) -> None:
        self._steps.append(step)

    def parameterize(
        self, literal_or_map: str | dict[str, str], param_name: str | None = None
    ) -> None:
        """Replace hardcoded values with parameter templates.

        Supports two calling conventions:
            parameterize("SFO", "departure_city")          # (literal, name)
            parameterize({"departure_city": "SFO", ...})   # dict mapping name→literal
        """
        if isinstance(literal_or_map, dict):
            param_map = literal_or_map
        else:
            if param_name is None:
                raise ValueError("param_name required when first arg is a literal value")
            param_map = {param_name: literal_or_map}

        for name, literal_value in param_map.items():
            self._parameters.append(
                ParameterInfo(name=name, location="body", param_type="string", required=True)
            )
            for step in self._steps:
                if step.value and literal_value in step.value:
                    step.value = step.value.replace(literal_value, f"{{{name}}}")
                    step.parameterized = True

    def build(
        self, site_domain: str | None = None, action_name: str | None = None
    ) -> RecordedWorkflow:
        return RecordedWorkflow(
            id=str(uuid.uuid4()),
            site_domain=site_domain or self._domain,
            action_name=action_name or self._name,
            steps=self._steps,
            parameters=self._parameters,
            recorded_at=datetime.utcnow(),
        )


class WorkflowPlayer:
    """Replays recorded workflows with parameter substitution."""

    def __init__(self) -> None:
        self._config = get_config()

    async def replay(
        self,
        workflow: RecordedWorkflow,
        params: dict[str, str],
        start_url: str | None = None,
        *,
        profile: str | None = None,
        inject_cookies_for: str | None = None,
    ) -> dict:
        """Replay a recorded workflow with substituted parameters.

        Returns:
            Dict with results from the workflow execution.
        """
        from site2cli.browser.context import create_browser_context

        config = self._config
        cookie_domain = inject_cookies_for or workflow.site_domain
        async with create_browser_context(
            profile=profile or config.browser.profile,
            inject_cookies_for=cookie_domain,
        ) as (_browser, _context, page):
            if start_url:
                await page.goto(
                    start_url,
                    wait_until="networkidle",
                    timeout=config.browser.timeout_ms,
                )

            results = []
            for i, step in enumerate(workflow.steps):
                try:
                    result = await self._execute_step(page, step, params)
                    results.append({"step": i, "action": step.action, "success": True, **result})
                except Exception as e:
                    results.append({
                        "step": i,
                        "action": step.action,
                        "success": False,
                        "error": str(e),
                    })
                    break

            # Try to extract final page data
            final_data = {}
            try:
                final_data["url"] = page.url
                final_data["title"] = await page.title()
            except Exception:
                pass

        return {
            "steps_executed": len(results),
            "steps_total": len(workflow.steps),
            "results": results,
            "final_page": final_data,
        }

    async def _execute_step(
        self, page: Page, step: WorkflowStep, params: dict[str, str]
    ) -> dict:
        """Execute a single workflow step."""
        # Substitute parameters in value
        value = step.value
        if value and step.parameterized:
            for param_name, param_value in params.items():
                value = value.replace(f"{{{param_name}}}", param_value)

        if step.action == "navigate":
            url = step.url or value or ""
            for param_name, param_value in params.items():
                url = url.replace(f"{{{param_name}}}", param_value)
            await page.goto(url, wait_until="networkidle", timeout=10000)
            return {"url": page.url}

        elif step.action == "click":
            await page.click(step.selector or "", timeout=5000)
            await page.wait_for_load_state("networkidle", timeout=5000)
            return {}

        elif step.action == "fill":
            await page.fill(step.selector or "", value or "")
            return {"filled": value}

        elif step.action == "select":
            await page.select_option(step.selector or "", value or "")
            return {"selected": value}

        elif step.action == "wait":
            await page.wait_for_timeout(int(value or "2000"))
            return {}

        elif step.action == "extract":
            selector = step.selector or "body"
            text = await page.text_content(selector)
            return {"extracted": text}

        else:
            return {"warning": f"Unknown action: {step.action}"}


def save_workflow(workflow: RecordedWorkflow, output_dir: Path) -> Path:
    """Save a recorded workflow to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{workflow.id}.json"
    with open(path, "w") as f:
        f.write(workflow.model_dump_json(indent=2))
    return path


def load_workflow(path: Path) -> RecordedWorkflow:
    """Load a recorded workflow from disk."""
    with open(path) as f:
        return RecordedWorkflow.model_validate_json(f.read())
