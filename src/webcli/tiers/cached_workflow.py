"""Tier 2: Cached/recorded workflow replay."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, async_playwright

from webcli.config import get_config
from webcli.models import ParameterInfo, RecordedWorkflow, WorkflowStep


class WorkflowRecorder:
    """Records browser interactions as replayable workflows."""

    def __init__(self) -> None:
        self._config = get_config()
        self._steps: list[WorkflowStep] = []
        self._parameters: list[ParameterInfo] = []

    def add_step(self, step: WorkflowStep) -> None:
        self._steps.append(step)

    def parameterize(self, param_map: dict[str, str]) -> None:
        """Replace hardcoded values with parameter templates.

        Args:
            param_map: Maps parameter names to the literal values to replace.
                       e.g., {"departure_city": "SFO", "arrival_city": "JFK"}
        """
        for name, literal_value in param_map.items():
            self._parameters.append(
                ParameterInfo(name=name, location="body", param_type="string", required=True)
            )
            for step in self._steps:
                if step.value and literal_value in step.value:
                    step.value = step.value.replace(literal_value, f"{{{name}}}")
                    step.parameterized = True

    def build(self, site_domain: str, action_name: str) -> RecordedWorkflow:
        return RecordedWorkflow(
            id=str(uuid.uuid4()),
            site_domain=site_domain,
            action_name=action_name,
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
    ) -> dict:
        """Replay a recorded workflow with substituted parameters.

        Returns:
            Dict with results from the workflow execution.
        """
        config = self._config
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=config.browser.headless)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()

            if start_url:
                await page.goto(start_url, wait_until="networkidle", timeout=config.browser.timeout_ms)

            results = []
            for i, step in enumerate(workflow.steps):
                try:
                    result = await self._execute_step(page, step, params)
                    results.append({"step": i, "action": step.action, "success": True, **result})
                except Exception as e:
                    results.append({"step": i, "action": step.action, "success": False, "error": str(e)})
                    break

            # Try to extract final page data
            final_data = {}
            try:
                final_data["url"] = page.url
                final_data["title"] = await page.title()
            except Exception:
                pass

            await browser.close()

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
