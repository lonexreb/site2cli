"""Tests for multi-site orchestration executor."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from site2cli.models import (
    DataMapping,
    OrchestrationPipeline,
    OrchestrationStep,
)
from site2cli.orchestration.orchestrator import Orchestrator


@pytest.fixture()
def mock_router():
    router = AsyncMock()
    router.execute = AsyncMock(return_value={"data": "ok"})
    return router


@pytest.fixture()
def orchestrator(mock_router):
    return Orchestrator(mock_router)


def _pipeline(steps, name="test", pipeline_id="p1"):
    return OrchestrationPipeline(id=pipeline_id, name=name, steps=steps)


# --- Basic execution ---


@pytest.mark.asyncio
async def test_single_step_executes(orchestrator, mock_router):
    pipeline = _pipeline([
        OrchestrationStep(step_id="s1", domain="api.com", action="list"),
    ])
    result = await orchestrator.execute(pipeline)
    assert result.success
    assert len(result.step_results) == 1
    assert result.step_results[0].step_id == "s1"
    mock_router.execute.assert_called_once_with("api.com", "list", {})


@pytest.mark.asyncio
async def test_two_steps_with_data_flow(orchestrator, mock_router):
    mock_router.execute = AsyncMock(side_effect=[
        {"user_id": 42, "name": "Alice"},
        {"booking": "confirmed"},
    ])
    pipeline = _pipeline([
        OrchestrationStep(step_id="find", domain="a.com", action="search"),
        OrchestrationStep(
            step_id="book", domain="b.com", action="reserve",
            data_mappings=[
                DataMapping(source_path="$result.user_id", target_param="uid"),
            ],
        ),
    ])
    result = await orchestrator.execute(pipeline)
    assert result.success
    assert len(result.step_results) == 2
    # Verify second call got the mapped param
    second_call = mock_router.execute.call_args_list[1]
    assert second_call.args == ("b.com", "reserve", {"uid": 42})


@pytest.mark.asyncio
async def test_static_and_dynamic_params_merged(orchestrator, mock_router):
    mock_router.execute = AsyncMock(side_effect=[
        {"city": "NYC"},
        {"result": "ok"},
    ])
    pipeline = _pipeline([
        OrchestrationStep(step_id="s1", domain="a.com", action="lookup"),
        OrchestrationStep(
            step_id="s2", domain="b.com", action="book",
            params={"hotel": "Hilton"},
            data_mappings=[
                DataMapping(source_path="$result.city", target_param="destination"),
            ],
        ),
    ])
    result = await orchestrator.execute(pipeline)
    assert result.success
    second_call = mock_router.execute.call_args_list[1]
    assert second_call.args[2] == {"hotel": "Hilton", "destination": "NYC"}


# --- Error handling ---


@pytest.mark.asyncio
async def test_step_failure_with_on_error_fail(orchestrator, mock_router):
    mock_router.execute = AsyncMock(side_effect=Exception("API down"))
    pipeline = _pipeline([
        OrchestrationStep(step_id="s1", domain="a.com", action="test", on_error="fail"),
        OrchestrationStep(step_id="s2", domain="b.com", action="test"),
    ])
    result = await orchestrator.execute(pipeline)
    assert not result.success
    assert len(result.step_results) == 1  # stopped at s1
    assert result.step_results[0].error == "API down"


@pytest.mark.asyncio
async def test_step_failure_with_on_error_skip(orchestrator, mock_router):
    mock_router.execute = AsyncMock(side_effect=[
        Exception("API down"),
        {"data": "ok"},
    ])
    pipeline = _pipeline([
        OrchestrationStep(step_id="s1", domain="a.com", action="test", on_error="skip"),
        OrchestrationStep(step_id="s2", domain="b.com", action="test"),
    ])
    result = await orchestrator.execute(pipeline)
    assert result.success  # skip doesn't fail the pipeline
    assert len(result.step_results) == 2
    assert not result.step_results[0].success
    assert result.step_results[1].success


@pytest.mark.asyncio
async def test_step_failure_with_retry(orchestrator, mock_router):
    call_count = 0

    async def flaky(*args):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise Exception("transient")
        return {"data": "ok"}

    mock_router.execute = AsyncMock(side_effect=flaky)
    pipeline = _pipeline([
        OrchestrationStep(
            step_id="s1", domain="a.com", action="test",
            on_error="retry", retries=3,
        ),
    ])
    result = await orchestrator.execute(pipeline)
    assert result.success
    assert call_count == 3  # failed 2x, succeeded on 3rd


# --- Result tracking ---


@pytest.mark.asyncio
async def test_duration_tracked(orchestrator, mock_router):
    pipeline = _pipeline([
        OrchestrationStep(step_id="s1", domain="a.com", action="test"),
    ])
    result = await orchestrator.execute(pipeline)
    assert result.total_duration_ms >= 0
    assert result.step_results[0].duration_ms >= 0


@pytest.mark.asyncio
async def test_empty_pipeline(orchestrator):
    pipeline = _pipeline([])
    result = await orchestrator.execute(pipeline)
    assert result.success
    assert result.step_results == []


@pytest.mark.asyncio
async def test_pipeline_metadata(orchestrator, mock_router):
    pipeline = _pipeline(
        [OrchestrationStep(step_id="s1", domain="a.com", action="test")],
        name="my-pipeline",
        pipeline_id="pid-123",
    )
    result = await orchestrator.execute(pipeline)
    assert result.pipeline_id == "pid-123"
    assert result.pipeline_name == "my-pipeline"


@pytest.mark.asyncio
async def test_three_step_cascade(orchestrator, mock_router):
    mock_router.execute = AsyncMock(side_effect=[
        {"flight_id": "FL001"},
        {"hotel_id": "HT002", "checkin": "2025-06-15"},
        {"confirmation": "CONF-999"},
    ])
    pipeline = _pipeline([
        OrchestrationStep(step_id="flight", domain="kayak.com", action="search"),
        OrchestrationStep(
            step_id="hotel", domain="booking.com", action="find",
            data_mappings=[
                DataMapping(source_path="$result.flight_id", target_param="ref"),
            ],
        ),
        OrchestrationStep(
            step_id="confirm", domain="travel.com", action="book",
            data_mappings=[
                DataMapping(source_path="$steps.flight.result.flight_id", target_param="flight"),
                DataMapping(source_path="$steps.hotel.result.hotel_id", target_param="hotel"),
            ],
        ),
    ])
    result = await orchestrator.execute(pipeline)
    assert result.success
    assert len(result.step_results) == 3
    # Verify cascade
    third_call = mock_router.execute.call_args_list[2]
    assert third_call.args[2] == {"flight": "FL001", "hotel": "HT002"}


@pytest.mark.asyncio
async def test_initial_params_passed_to_first_step(orchestrator, mock_router):
    pipeline = _pipeline([
        OrchestrationStep(
            step_id="s1", domain="a.com", action="test",
            data_mappings=[
                DataMapping(source_path="$result.query", target_param="q"),
            ],
        ),
    ])
    result = await orchestrator.execute(pipeline, initial_params={"query": "hello"})
    assert result.success
    call_args = mock_router.execute.call_args
    assert call_args.args[2] == {"q": "hello"}


@pytest.mark.asyncio
async def test_non_dict_result_wrapped(orchestrator, mock_router):
    mock_router.execute = AsyncMock(return_value=[1, 2, 3])
    pipeline = _pipeline([
        OrchestrationStep(step_id="s1", domain="a.com", action="test"),
    ])
    result = await orchestrator.execute(pipeline)
    assert result.success
    assert result.step_results[0].result == {"data": [1, 2, 3]}
