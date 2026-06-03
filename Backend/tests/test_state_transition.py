"""Unit tests for state_transition workflow test category."""

from __future__ import annotations

from agents.generator import (
    _normalize_workflow_steps,
    _probe_workflow_path,
    _validate_workflow_test_against_binding,
    _workflow_stamp_for_binding,
)
from agents.pytest_runner import _tier0_off_target
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


def test_workflow_stamp_prefers_step_matching_req_binding():
    """PATCH-only REQ-003: stamp /tasks/{task_id}, not setup POST /tasks/."""
    patch_binding = SurfaceBinding(
        requirement_id="REQ-003",
        state="BACKEND_API",
        threat_class="DEFENSIVE_NORMAL",
        rationale="PATCH task by id",
        confidence="high",
        backend_endpoints=[
            BackendEndpoint(
                method="PATCH", path="/tasks/{task_id}",
                handler_file="routers/task_router.py",
            ),
        ],
    )
    tc = TestCase(
        test_id="TC-REQ-003-01",
        title="Update task priority to High and verify persistence",
        action="POST /tasks/ then PATCH /tasks/{task_id}",
        expected_result="ok",
        test_category="state_transition",
        covered_requirement_id="REQ-003",
        workflow_steps=[
            WorkflowStep(
                method="POST",
                path="/tasks/",
                input_data={"title": "X", "priority": "High", "status": "Active"},
                expected_status_code=201,
                capture_json_key="id",
            ),
            WorkflowStep(
                method="PATCH",
                path="/tasks/{task_id}",
                input_data={"priority": "High"},
                expected_status_code=200,
            ),
        ],
        expected_status_code=200,
    )
    meth, path = _workflow_stamp_for_binding(tc, patch_binding)
    assert meth == "PATCH"
    assert path == "/tasks/{task_id}"

    create_binding = SurfaceBinding(
        requirement_id="REQ-001",
        state="BACKEND_API",
        threat_class="DEFENSIVE_NORMAL",
        rationale="create",
        confidence="high",
        backend_endpoints=[
            BackendEndpoint(
                method="POST", path="/tasks/", handler_file="routers/task_router.py",
            ),
        ],
    )
    ok, bm, bp, reason = _validate_workflow_test_against_binding(
        tc,
        patch_binding,
        {"REQ-001": create_binding, "REQ-003": patch_binding},
    )
    assert ok, reason
    assert bm == "PATCH"
    assert bp == "/tasks/{task_id}"


def test_tier0_workflow_with_patch_step_not_off_target():
    """Tier-0 must not reject workflows whose first step is POST /tasks/ setup."""
    patch_binding = SurfaceBinding(
        requirement_id="REQ-003",
        state="BACKEND_API",
        threat_class="DEFENSIVE_NORMAL",
        rationale="PATCH task by id",
        confidence="high",
        backend_endpoints=[
            BackendEndpoint(
                method="PATCH", path="/tasks/{task_id}",
                handler_file="routers/task_router.py",
            ),
        ],
    )
    tc = TestCase(
        test_id="TC-REQ-003-01",
        title="Update task priority",
        action="POST /tasks/ then PATCH /tasks/{task_id}",
        expected_result="ok",
        test_category="state_transition",
        covered_requirement_id="REQ-003",
        bound_method="POST",
        bound_path="/tasks/",
        workflow_steps=[
            WorkflowStep(
                method="POST",
                path="/tasks/",
                expected_status_code=201,
                capture_json_key="id",
            ),
            WorkflowStep(
                method="PATCH",
                path="/tasks/{task_id}",
                expected_status_code=200,
            ),
        ],
        expected_status_code=200,
    )
    surface_map = {"REQ-003": patch_binding}
    assert _tier0_off_target(tc, surface_map) is None


def test_tier0_state_transition_action_paths_without_workflow_steps():
    """LLM often sets category + action chain but omits workflow_steps array."""
    patch_binding = SurfaceBinding(
        requirement_id="REQ-003",
        state="BACKEND_API",
        threat_class="DEFENSIVE_NORMAL",
        rationale="PATCH",
        confidence="high",
        backend_endpoints=[
            BackendEndpoint(
                method="PATCH", path="/tasks/{task_id}",
                handler_file="routers/task_router.py",
            ),
        ],
    )
    tc = TestCase(
        test_id="TC-REQ-003-01",
        title="Update task priority",
        action="POST /tasks/ then PATCH /tasks/{task_id}",
        expected_result="ok",
        test_category="state_transition",
        covered_requirement_id="REQ-003",
        bound_method="POST",
        bound_path="/tasks/",
        workflow_steps=[],
        expected_status_code=200,
    )
    assert _tier0_off_target(tc, {"REQ-003": patch_binding}) is None


def test_tier0_workflow_without_matching_step_is_off_target():
    patch_binding = SurfaceBinding(
        requirement_id="REQ-003",
        state="BACKEND_API",
        threat_class="DEFENSIVE_NORMAL",
        rationale="PATCH only",
        confidence="high",
        backend_endpoints=[
            BackendEndpoint(
                method="PATCH", path="/tasks/{task_id}",
                handler_file="routers/task_router.py",
            ),
        ],
    )
    tc = TestCase(
        test_id="TC-REQ-003-99",
        title="Wrong workflow",
        action="GET /health",
        expected_result="ok",
        covered_requirement_id="REQ-003",
        workflow_steps=[
            WorkflowStep(method="GET", path="/health", expected_status_code=200),
            WorkflowStep(method="GET", path="/docs", expected_status_code=200),
        ],
        expected_status_code=200,
    )
    verdict, evidence = _tier0_off_target(tc, {"REQ-003": patch_binding})
    assert verdict == "off_target"
    assert "no workflow step matches" in evidence[0]


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
