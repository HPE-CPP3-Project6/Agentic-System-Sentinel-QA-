"""Unit tests for state_transition workflow test category."""

from __future__ import annotations

from agents.generator import (
    _normalize_workflow_steps,
    _probe_workflow_path,
    _validate_workflow_test_against_binding,
)
from agents.security_compiler import _materialize_pytest_workspace
from state import BackendEndpoint, SurfaceBinding, TestCase, WorkflowStep


def test_normalize_workflow_steps_min_two():
    steps = _normalize_workflow_steps(
        [
            {
                "method": "post",
                "path": "/tasks/",
                "input_data": {"title": "A", "priority": "High", "status": "Active"},
                "expected_status_code": 201,
                "capture_json_key": "id",
            },
            {
                "method": "GET",
                "path": "/tasks/{task_id}",
                "expected_status_code": 200,
            },
        ]
    )
    assert len(steps) == 2
    assert steps[0]["method"] == "POST"
    assert steps[0]["capture_json_key"] == "id"


def test_probe_workflow_path_matches_template():
    probe = _probe_workflow_path("/tasks/{task_id}")
    assert "{task_id}" not in probe
    assert "00000000" in probe


def test_validate_workflow_against_binding():
    binding = SurfaceBinding(
        requirement_id="REQ-001",
        state="BACKEND_API",
        threat_class="DEFENSIVE_NORMAL",
        rationale="Task CRUD endpoints in task_router.",
        confidence="high",
        backend_endpoints=[
            BackendEndpoint(method="POST", path="/tasks/", handler_file="routers/task_router.py"),
            BackendEndpoint(method="GET", path="/tasks/{task_id}", handler_file="routers/task_router.py"),
            BackendEndpoint(method="PATCH", path="/tasks/{task_id}", handler_file="routers/task_router.py"),
            BackendEndpoint(method="DELETE", path="/tasks/{task_id}", handler_file="routers/task_router.py"),
        ],
    )
    tc = TestCase(
        test_id="TC-REQ-001-01",
        title="lifecycle",
        action="POST /tasks/ then GET /tasks/{task_id}",
        expected_result="ok",
        test_category="state_transition",
        workflow_steps=[
            WorkflowStep(
                method="POST",
                path="/tasks/",
                input_data={"title": "X", "priority": "High", "status": "Active"},
                expected_status_code=201,
                capture_json_key="id",
            ),
            WorkflowStep(
                method="GET",
                path="/tasks/{task_id}",
                expected_status_code=200,
            ),
        ],
        expected_status_code=200,
    )
    surface_map = {
        "REQ-001": binding,
        "REQ-002": SurfaceBinding(
            requirement_id="REQ-002",
            state="BACKEND_API",
            threat_class="DEFENSIVE_NORMAL",
            rationale="x",
            confidence="high",
            backend_endpoints=[
                BackendEndpoint(
                    method="GET", path="/tasks/{task_id}",
                    handler_file="routers/task_router.py",
                ),
            ],
        ),
        "REQ-003": SurfaceBinding(
            requirement_id="REQ-003",
            state="BACKEND_API",
            threat_class="DEFENSIVE_NORMAL",
            rationale="x",
            confidence="high",
            backend_endpoints=[
                BackendEndpoint(
                    method="PATCH", path="/tasks/{task_id}",
                    handler_file="routers/task_router.py",
                ),
            ],
        ),
        "REQ-004a": SurfaceBinding(
            requirement_id="REQ-004a",
            state="BACKEND_API",
            threat_class="DEFENSIVE_NORMAL",
            rationale="x",
            confidence="high",
            backend_endpoints=[
                BackendEndpoint(
                    method="DELETE", path="/tasks/{task_id}",
                    handler_file="routers/task_router.py",
                ),
            ],
        ),
    }
    ok, meth, path, reason = _validate_workflow_test_against_binding(
        tc, binding, surface_map
    )
    assert ok, reason
    assert meth == "POST"
    assert path == "/tasks/"


def test_compiler_emits_workflow_block():
    """Generated pytest contains workflow runner when workflow_steps are set."""
    from state import ProjectState

    tc = TestCase(
        test_id="TC-LIFE-01",
        title="create then read",
        action="POST /tasks/ then GET /tasks/{task_id}",
        expected_result="ok",
        test_category="state_transition",
        workflow_steps=[
            WorkflowStep(
                method="POST",
                path="/tasks/",
                input_data={"title": "Probe", "priority": "High", "status": "Active"},
                expected_status_code=201,
                capture_json_key="id",
            ),
            WorkflowStep(method="GET", path="/tasks/{task_id}", expected_status_code=200),
        ],
        expected_status_code=200,
        bound_method="POST",
        bound_path="/tasks/",
    )
    state = ProjectState(
        user_story="lifecycle",
        acceptance_criteria=[],
        test_suite=[tc],
    )
    _materialize_pytest_workspace(state)
    run_dir = state.metadata.get("security_compiler_run_dir")
    assert run_dir
    from pathlib import Path

    files = list(Path(run_dir).glob("test_sentinel_api_generated.py"))
    assert files
    content = files[0].read_text(encoding="utf-8")
    assert "_run_workflow_steps" in content
    assert "capture_json_key" in content or '"id"' in content
