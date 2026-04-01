"""Sequential multi-site orchestration executor."""

from __future__ import annotations

import time
from datetime import datetime

from site2cli.models import (
    OrchestrationPipeline,
    OrchestrationResult,
    StepResult,
)
from site2cli.orchestration.data_flow import resolve_params
from site2cli.router import Router


class Orchestrator:
    """Executes multi-site orchestration pipelines sequentially."""

    def __init__(self, router: Router) -> None:
        self._router = router

    async def execute(
        self,
        pipeline: OrchestrationPipeline,
        initial_params: dict | None = None,
    ) -> OrchestrationResult:
        """Execute all steps in sequence, passing data between them."""
        start = time.time()
        step_results: dict[str, StepResult] = {}
        all_results: list[StepResult] = []
        previous_result: dict | None = initial_params
        success = True

        for step in pipeline.steps:
            # Resolve params (static + data mappings from prior steps)
            resolved = resolve_params(step, step_results, previous_result)

            # Execute with retry support
            step_result = await self._execute_step_with_retry(
                step.domain, step.action, resolved, step.step_id, step.retries
            )
            step_results[step.step_id] = step_result
            all_results.append(step_result)

            if step_result.success:
                previous_result = step_result.result
            else:
                if step.on_error == "fail":
                    success = False
                    break
                elif step.on_error == "skip":
                    continue
                # "retry" already handled in _execute_step_with_retry

        total_ms = (time.time() - start) * 1000
        return OrchestrationResult(
            pipeline_id=pipeline.id,
            pipeline_name=pipeline.name,
            success=success,
            step_results=all_results,
            total_duration_ms=round(total_ms, 1),
            started_at=datetime.utcnow(),
        )

    async def _execute_step_with_retry(
        self,
        domain: str,
        action: str,
        params: dict,
        step_id: str,
        retries: int = 0,
    ) -> StepResult:
        """Execute a single step, retrying on failure."""
        last_error = ""
        for attempt in range(retries + 1):
            start = time.time()
            try:
                result = await self._router.execute(domain, action, params)
                duration = (time.time() - start) * 1000
                return StepResult(
                    step_id=step_id,
                    domain=domain,
                    action=action,
                    success=True,
                    result=result if isinstance(result, dict) else {"data": result},
                    duration_ms=round(duration, 1),
                )
            except Exception as e:
                last_error = str(e)
                duration = (time.time() - start) * 1000

        return StepResult(
            step_id=step_id,
            domain=domain,
            action=action,
            success=False,
            error=last_error,
            duration_ms=round(duration, 1),
        )
