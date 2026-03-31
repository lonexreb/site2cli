"""Tests for workflow recording and registry CRUD.

Covers WorkflowRecorder (add_step, build, parameterize) and
SiteRegistry workflow methods (save, get, list, delete).
~14 tests total.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from site2cli.cli import app
from site2cli.config import reset_config
from site2cli.models import ParameterInfo, RecordedWorkflow, WorkflowStep
from site2cli.registry import SiteRegistry
from site2cli.tiers.cached_workflow import WorkflowRecorder


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Isolate data dirs and reset config singleton for every test."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_config()
    yield
    reset_config()


@pytest.fixture()
def registry(tmp_path) -> SiteRegistry:
    """Return a SiteRegistry backed by a temp directory."""
    return SiteRegistry(tmp_path / "registry.db")


@pytest.fixture()
def sample_steps() -> list[WorkflowStep]:
    """Return a small list of workflow steps for reuse."""
    return [
        WorkflowStep(
            action="navigate",
            url="https://example.com",
            selector=None,
            value=None,
        ),
        WorkflowStep(
            action="click",
            url="https://example.com/login",
            selector="#login-btn",
            value=None,
        ),
        WorkflowStep(
            action="fill",
            url="https://example.com/login",
            selector="#username",
            value="testuser",
        ),
    ]


@pytest.fixture()
def sample_workflow(sample_steps) -> RecordedWorkflow:
    return RecordedWorkflow(
        id="wf-001",
        site_domain="example.com",
        action_name="login-flow",
        steps=sample_steps,
        parameters=[
            ParameterInfo(name="username", location="step:2:value", required=True),
        ],
        recorded_at=datetime.now(timezone.utc),
    )


# ---------- WorkflowRecorder unit tests ----------


def test_add_step_appends(sample_steps):
    """add_step() increases the step list."""
    recorder = WorkflowRecorder(domain="example.com", name="test")
    assert len(recorder.steps) == 0

    recorder.add_step(sample_steps[0])
    assert len(recorder.steps) == 1

    recorder.add_step(sample_steps[1])
    assert len(recorder.steps) == 2


def test_build_creates_recorded_workflow(sample_steps):
    """build() returns a RecordedWorkflow with the correct fields."""
    recorder = WorkflowRecorder(domain="example.com", name="my-flow")
    for step in sample_steps:
        recorder.add_step(step)

    workflow = recorder.build()
    assert isinstance(workflow, RecordedWorkflow)
    assert workflow.site_domain == "example.com"
    assert workflow.action_name == "my-flow"
    assert len(workflow.steps) == len(sample_steps)
    assert workflow.id  # should have a generated id
    assert workflow.recorded_at  # should have a timestamp


def test_build_with_empty_steps():
    """build() works even with an empty step list."""
    recorder = WorkflowRecorder(domain="example.com", name="empty")
    workflow = recorder.build()
    assert isinstance(workflow, RecordedWorkflow)
    assert workflow.steps == []


def test_parameterize_replaces_values(sample_steps):
    """parameterize() replaces literal values with template placeholders."""
    recorder = WorkflowRecorder(domain="example.com", name="param-test")
    for step in sample_steps:
        recorder.add_step(step)

    recorder.parameterize("testuser", "username")
    # The step that had value="testuser" should now have a template reference
    fill_step = recorder.steps[2]
    assert "username" in (fill_step.value or "")
    assert "testuser" not in (fill_step.value or "")


# ---------- SiteRegistry workflow CRUD tests ----------


def test_save_and_get_workflow_roundtrip(registry, sample_workflow):
    """save_workflow + get_workflow round-trips correctly."""
    registry.save_workflow(sample_workflow)
    loaded = registry.get_workflow(sample_workflow.id)
    assert loaded is not None
    assert loaded.id == sample_workflow.id
    assert loaded.site_domain == sample_workflow.site_domain
    assert loaded.action_name == sample_workflow.action_name
    assert len(loaded.steps) == len(sample_workflow.steps)


def test_get_workflow_returns_none_for_missing(registry):
    """get_workflow() returns None when the ID does not exist."""
    assert registry.get_workflow("nonexistent-id") is None


def test_list_workflows_returns_all(registry, sample_steps):
    """list_workflows() returns all saved workflows."""
    for i in range(3):
        wf = RecordedWorkflow(
            id=f"wf-{i}",
            site_domain="example.com",
            action_name=f"flow-{i}",
            steps=sample_steps,
            parameters=[],
            recorded_at=datetime.now(timezone.utc),
        )
        registry.save_workflow(wf)

    workflows = registry.list_workflows()
    assert len(workflows) >= 3


def test_list_workflows_empty(registry):
    """list_workflows() returns empty list when no workflows saved."""
    workflows = registry.list_workflows()
    assert workflows == []


def test_delete_workflow_removes(registry, sample_workflow):
    """delete_workflow() removes the workflow and returns True."""
    registry.save_workflow(sample_workflow)
    result = registry.delete_workflow(sample_workflow.id)
    assert result is True
    assert registry.get_workflow(sample_workflow.id) is None


def test_delete_workflow_returns_false_for_missing(registry):
    """delete_workflow() returns False when the ID does not exist."""
    result = registry.delete_workflow("nonexistent-id")
    assert result is False


def test_workflow_steps_serialization(registry, sample_workflow):
    """Steps survive serialization through save/get round-trip."""
    registry.save_workflow(sample_workflow)
    loaded = registry.get_workflow(sample_workflow.id)
    assert loaded is not None
    for original, loaded_step in zip(sample_workflow.steps, loaded.steps):
        assert original.action == loaded_step.action
        assert original.url == loaded_step.url
        assert original.selector == loaded_step.selector
        assert original.value == loaded_step.value


def test_workflow_parameters_serialization(registry, sample_workflow):
    """Parameters survive serialization through save/get round-trip."""
    registry.save_workflow(sample_workflow)
    loaded = registry.get_workflow(sample_workflow.id)
    assert loaded is not None
    assert len(loaded.parameters) == len(sample_workflow.parameters)
    assert loaded.parameters[0].name == "username"
    assert loaded.parameters[0].required is True


def test_multiple_workflows_same_domain(registry, sample_steps):
    """Multiple workflows for the same domain coexist."""
    for name in ("login", "search", "checkout"):
        wf = RecordedWorkflow(
            id=f"wf-{name}",
            site_domain="example.com",
            action_name=name,
            steps=sample_steps,
            parameters=[],
            recorded_at=datetime.now(timezone.utc),
        )
        registry.save_workflow(wf)

    workflows = registry.list_workflows()
    domains = {w.site_domain for w in workflows}
    assert domains == {"example.com"}
    assert len(workflows) == 3


# ---------- CLI workflow commands ----------


def test_cli_workflows_list(tmp_path, monkeypatch):
    """'workflows list' CLI command shows saved workflows."""
    registry = SiteRegistry(tmp_path / "registry.db")
    wf = RecordedWorkflow(
        id="wf-cli-1",
        site_domain="example.com",
        action_name="cli-test",
        steps=[],
        parameters=[],
        recorded_at=datetime.now(timezone.utc),
    )
    registry.save_workflow(wf)

    # Point the CLI at our temp registry
    monkeypatch.setattr(
        "site2cli.cli._get_registry",
        lambda: registry,
    )

    runner = CliRunner()
    result = runner.invoke(app, ["workflows", "list"])
    assert result.exit_code == 0
    # Output should mention the workflow name or id
    assert "cli-test" in result.output or "wf-cli-1" in result.output


def test_cli_workflows_show_and_delete(tmp_path, monkeypatch):
    """'workflows show' and 'workflows delete' CLI commands work."""
    registry = SiteRegistry(tmp_path / "registry.db")
    wf = RecordedWorkflow(
        id="wf-cli-2",
        site_domain="example.com",
        action_name="to-delete",
        steps=[],
        parameters=[],
        recorded_at=datetime.now(timezone.utc),
    )
    registry.save_workflow(wf)

    monkeypatch.setattr(
        "site2cli.cli._get_registry",
        lambda: registry,
    )

    runner = CliRunner()

    # Show
    show_result = runner.invoke(app, ["workflows", "show", "wf-cli-2"])
    assert show_result.exit_code == 0
    assert "to-delete" in show_result.output or "wf-cli-2" in show_result.output

    # Delete
    delete_result = runner.invoke(app, ["workflows", "delete", "wf-cli-2"])
    assert delete_result.exit_code == 0
