"""Shared state object passed between all LangGraph nodes in Sentinel-QA."""

from __future__ import annotations

from typing import List, Literal, Optional, Dict, Any, Union
from pydantic import BaseModel, Field


# Layer A — Surface Map types.
#
# A SurfaceMap is the typed contract between Critic and Generator about
# WHICH testable surface each requirement maps to in the codebase. Before
# Layer A every agent re-interpreted the story from raw text, which drove
# the proxy-test / false-positive-vulnerability family of bugs. With the
# SurfaceMap, the Resolver decides this ONCE per pipeline run, and the
# Generator + Compiler + Classifier are bound to the decision.
SurfaceState = Literal[
    "BACKEND_API",          # implemented as a real backend endpoint
    "FRONTEND_ONLY",        # rendered UI but no logic (e.g. static display)
    "CLIENT_SIDE_ONLY",     # logic in browser (e.g. .filter() over local data)
    "NOT_IMPLEMENTED",      # story names something with no surface in code
    "NEEDS_CLARIFICATION",  # ambiguous — multiple plausible surfaces or contradiction
]


# Layer A — anti-pattern translation (Refinement 1).
#
# Stories often use anti-pattern language ("must accept any length", "must
# allow unlimited retries", "must display sensitive data") — the narrator
# is asking for insecure behavior. The Critic flags them as security risks
# precisely because the INVERSE (rejection / enforcement / hiding) is the
# defense. Without threat-class classification, the Resolver reads them
# literally:
#
#   "Story wants no length limit; code has String(255); therefore
#    NOT_IMPLEMENTED."
#
# That's true but useless. The right security test is "verify the app
# safely rejects 1000-char input (422)" against the endpoint where the
# defense lives. ThreatClass lets the Resolver bind those requirements to
# the defense's endpoint and the Generator emit defense-confirming tests.
ThreatClass = Literal[
    "DEFENSIVE_NORMAL",     # ordinary feature; test the feature directly
    "DEFENSIVE_INVERTED",   # anti-pattern story; test that the inverse defense holds
    "NON_FUNCTIONAL",       # cross-cutting property assertion (→ NEEDS_CLARIFICATION)
]


# Layer A Refinement 1.1 — defense taxonomy.
#
# DEFENSIVE_INVERTED is too coarse on its own: the right test shape
# depends on HOW the defense expresses itself. Forcing "expected_status_code
# must be 4xx" universally (as the first version of Rule 11b did) made
# output-redaction and implicit-filter defenses ungeneratable — the
# Generator correctly refused to emit tests because 200 OK is the right
# success status for "the body doesn't leak X" and "the filter hid Y".
#
# These five kinds cover the defenses observed across login/search/org/
# filter/taskshare. The Generator's Rule 11b reads this field and applies
# the right status-code and assertion rules per kind.
DefenseKind = Literal[
    "INPUT_REJECTION",     # 4xx + clean body. e.g. 422 on over-long input.
    "TRANSPORT",           # 3xx + HSTS. e.g. http://→https:// redirect.
    "OUTPUT_REDACTION",    # 200 + forbidden_response_content. e.g. response strips internal IDs.
    "IMPLICIT_FILTER",     # 200 + assert filtered/empty. e.g. ownership filter, soft-delete.
    "ERROR_SANITIZATION",  # 5xx + forbidden_response_content. e.g. generic 500, no SQL fragment.
]

# Offensive-security attestation — control absent but attack surface exists.
AttestationMode = Literal[
    "defense_confirming",  # default: verify an implemented defense (Rule 11b)
    "missing_control",     # required control absent; attest via Rule 4 adversarial tests
]


# Verdict supersedes the legacy is_vulnerable/resilient pair on ExecutionLog.
# The mapping in `_legacy_fields_from_verdict` keeps back-compat consumers
# (drift_report, needs_healing, _security_posture) working unchanged.
Verdict = Literal[
    "resilient",            # adversarial test fired, app neutralized
    "vulnerable",           # adversarial test fired, app exposed a real weakness
    "off_target",           # test landed outside its bound surface — semantically null
    "inconclusive",         # forbidden-content tier fired but cannot disambiguate
    "n/a",                  # functional test, or no verdict applicable
]


def _legacy_fields_from_verdict(v: str):
    """Translate a verdict into the legacy (is_vulnerable, resilient) pair.

    Applied at ExecutionLog construction time by pytest_runner so legacy
    consumers (drift_report builds `exploited` from is_vulnerable;
    needs_healing reads is_vulnerable; _security_posture reads resilient)
    keep working without per-consumer edits. Single source of truth for the
    mapping — change here, the whole pipeline picks it up.
    """
    return {
        "vulnerable":   (True,  False),
        "resilient":    (False, True),
        "off_target":   (False, None),    # not a vuln, not a resilience proof
        "inconclusive": (None,  None),
        "n/a":          (None,  None),
    }[v]


class BackendEndpoint(BaseModel):
    """A concrete backend route that a requirement is bound to."""
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    path: str                                   # e.g. "/tasks/" or "/tasks/{task_id}"
    handler_file: str                           # e.g. "routers/task_router.py"
    handler_line: Optional[int] = None
    request_schema: Optional[str] = None        # e.g. "schemas.TaskCreate"
    response_schema: Optional[str] = None       # e.g. "schemas.PaginatedTaskResponse"


class FrontendSurface(BaseModel):
    """A frontend component a requirement is bound to (UI track — Layer C)."""
    component: str                              # e.g. "Dashboard"
    file: str                                   # e.g. "frontend/src/components/Dashboard.jsx"
    line: Optional[int] = None
    behavior: str                               # 1-sentence: "client-side filter via .filter()"


class ACOverride(BaseModel):
    """Per-AC override when ACs within one REQ disagree on surface state.
    Persisted by the Resolver; consulted by Day-2+ Generator. MVP ignores."""
    acceptance_criterion: str
    state: SurfaceState
    backend_endpoints: List[BackendEndpoint] = Field(default_factory=list)
    frontend_surfaces: List[FrontendSurface] = Field(default_factory=list)
    rationale: str


class SurfaceBinding(BaseModel):
    """The binding for a single requirement_id — Resolver's output unit."""
    requirement_id: str
    state: SurfaceState
    backend_endpoints: List[BackendEndpoint] = Field(default_factory=list)
    frontend_surfaces: List[FrontendSurface] = Field(default_factory=list)
    rationale: str                              # 1-2 sentences why this state was chosen
    grounding_refs: List[str] = Field(default_factory=list)  # file:line evidence
    confidence: Literal["high", "medium", "low"]
    ac_overrides: List[ACOverride] = Field(default_factory=list)
    # Layer A Refinement 1 — anti-pattern translation.
    # `threat_class` defaults to None for back-compat with bindings from runs
    # that pre-date this refinement. When populated:
    #   - DEFENSIVE_INVERTED: `anti_pattern_summary` names the story's
    #     insecure ask; `defense_assertion` describes what a defense-
    #     confirming response looks like. Generator's Rule 11b consumes
    #     these to emit "verify defense holds" tests instead of
    #     "verify anti-pattern" tests.
    #   - DEFENSIVE_NORMAL: ordinary feature. Both string fields may be None.
    #   - NON_FUNCTIONAL: cross-cutting. Both string fields may be None;
    #     state should be NEEDS_CLARIFICATION.
    threat_class: Optional[ThreatClass] = None
    anti_pattern_summary: Optional[str] = None
    defense_assertion: Optional[str] = None
    defense_kind: Optional[DefenseKind] = None
    # When ``missing_control``, Generator MUST emit Rule 4 adversarial tests
    # against ``backend_endpoints`` even though the control is not in code yet.
    attestation_mode: Optional[AttestationMode] = None


class WorkflowStep(BaseModel):
    """One HTTP hop in a state_transition test (ISTQB state-transition / API workflow).

    Steps run in order inside one pytest. Use ``capture_json_key`` on step N to
    stash a response field (e.g. ``id`` from POST /tasks/) and reference it in
    later paths as ``/tasks/{task_id}`` — the harness substitutes ``{task_id}``
    from the capture named ``task_id`` or from capture key ``id`` when the
    placeholder name matches.
    """

    method: str
    path: str
    input_data: Dict[str, Any] = Field(default_factory=dict)
    expected_status_code: int
    capture_json_key: Optional[str] = None
    expected_json_keys: List[str] = Field(default_factory=list)


class ValidatedRequirement(BaseModel):
    requirement_id: str
    statement: str
    ambiguity_score: float = Field(ge=0.0, le=1.0)
    ambiguity_notes: Optional[str] = None
    # NEW: Severity scoring (1-10) and dependency tracking
    severity_score: int = Field(ge=1, le=10, default=5)  # 1=low, 10=critical
    severity_rationale: Optional[str] = None  # Why this severity level
    dependencies: List[str] = Field(default_factory=list)  # Other requirement IDs this depends on
    owasp_mapping: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)


class TestCase(BaseModel):
    test_id: str
    title: str
    action: str
    input_data: Union[Dict[str, Any], List[Any]] = Field(default_factory=dict)
    # Declared pre-state the runner must seed before executing the test.
    # Each entry is a single imperative sentence (e.g. "Seed DB with user
    # test@example.com"). Empty list is treated as undeclared state — the
    # Generator must emit ["none"] for truly stateless tests.
    setup_fixtures: List[str] = Field(default_factory=list)
    # Traditional field (kept for backward compatibility)
    expected_result: str
    # NEW: Technical Schema for Assertions
    expected_status_code: Optional[int] = None  # e.g., 200, 400, 403
    expected_json_keys: List[str] = Field(default_factory=list)  # Keys expected in JSON response
    forbidden_response_content: List[str] = Field(default_factory=list)  # Content that should NOT appear
    response_match_regex: Optional[str] = None  # Regex pattern to match response
    # Resilience & Vulnerability Signatures
    resilience_signature: Optional[str] = None  # What a "safe/blocked" response looks like
    vulnerability_signature: Optional[str] = None  # What an "exploited" response looks like
    # Coverage & Test Metadata
    coverage_rationale: Optional[str] = None
    boundary_value_used: Optional[str] = None  # Exact boundary tested (e.g., "256 chars for 255-limit")
    test_category: Optional[str] = None  # positive|negative|boundary|security|state_transition
    # P1 (ISTQB / ISO 29119-4) — the formal test-DESIGN technique this case
    # embodies. `test_category` says WHAT outcome class (positive/negative/…);
    # `test_technique` says WHICH design discipline produced it. Inferred from
    # category + shape when the Generator omits it. Reported as by_technique in
    # the artifact so a reviewer can map coverage to recognized techniques.
    #   equivalence_partition | boundary_value | decision_table |
    #   state_transition | requirements_based | security_adversarial
    test_technique: Optional[str] = None
    # For equivalence_partition tests: the partition/class this case represents
    # (e.g. "valid", "invalid-empty", "invalid-type", "auth-missing"). Lets the
    # artifact show one test per meaningful class without duplicates.
    equivalence_class: Optional[str] = None
    # Multi-step workflow (state_transition only). Single-shot tests leave this empty.
    workflow_steps: List[WorkflowStep] = Field(default_factory=list)
    covered_requirement_id: Optional[str] = None
    covered_acceptance_criterion: Optional[str] = None
    source_refs: List[str] = Field(default_factory=list)
    is_adversarial: bool = False
    owasp_category: Optional[str] = None
    payload: Optional[str] = None
    exploit_target: Optional[str] = None
    mutated_fields: List[str] = Field(default_factory=list)
    parent_test_id: Optional[str] = None
    # Layer A — SurfaceMap binding stamped at Generator validation time.
    # Compiler reads bound_method/bound_path directly (no 4-tier inference);
    # Classifier tier 0 reads bound_path to detect off-target tests.
    # All three are None for back-compat / unbound tests.
    bound_method: Optional[str] = None
    bound_path: Optional[str] = None
    bound_surface_state: Optional[SurfaceState] = None
    # Rule 4 missing-control: pytest pass confirms vulnerability, not resilience.
    attestation_mode: Optional[AttestationMode] = None


class CoverageGap(BaseModel):
    requirement_id: str
    acceptance_criterion: Optional[str] = None
    reason: str


class SecurityRisk(BaseModel):
    owasp_id: str
    title: str
    severity: str
    rationale: str
    affected_requirements: List[str] = Field(default_factory=list)


class ExecutionLog(BaseModel):
    test_id: str
    status: str  # "passed" | "failed" | "error" | "skipped"
    is_adversarial: bool = False
    # Functional verdict
    passed: Optional[bool] = None
    # Adversarial verdicts — mutually exclusive: exploit succeeded vs. app blocked it.
    # Both stay None when the test was skipped (e.g. no bearer token) — a skipped
    # test never observed the attacker class and must NOT count as resilient.
    is_vulnerable: Optional[bool] = None
    resilient: Optional[bool] = None
    # Which heal cycle produced this log. None for legacy / out-of-band logs.
    # needs_healing filters on this to avoid re-routing on stale failures.
    heal_attempt: Optional[int] = None
    # Telemetry captured on failure
    duration_ms: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    trace: Optional[str] = None
    console_logs: List[str] = Field(default_factory=list)
    html_snapshot: Optional[str] = None
    exploit_target: Optional[str] = None
    # Layer A — verdict supersedes is_vulnerable/resilient. The legacy
    # pair is derived from verdict via _legacy_fields_from_verdict at log
    # construction time, so back-compat consumers (drift_report,
    # needs_healing, _security_posture) keep reading the legacy fields
    # without any per-consumer edits.
    verdict: Verdict = "n/a"
    verdict_confidence: Literal["high", "medium", "low"] = "low"
    verdict_evidence: List[str] = Field(default_factory=list)
    bound_surface_state: Optional[SurfaceState] = None


class Patch(BaseModel):
    target_file: str
    bug_explanation: str
    suggested_fix: str
    related_test_ids: List[str] = Field(default_factory=list)
    owasp_category: Optional[str] = None

class DesignContract(BaseModel):
    requirement_id: str
    endpoint: str
    method: str
    request_fields: Dict[str, str] = Field(default_factory=dict)
    response_fields: Dict[str, str] = Field(default_factory=dict)
    error_codes: Dict[str, str] = Field(default_factory=dict)
    validation_rules: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class SecurityChecklistItem(BaseModel):
    owasp_id: str
    requirement_id: str
    instruction: str
    rationale: str
    definition_of_done: str

class ProjectState(BaseModel):
    """Single source of truth threaded through the LangGraph pipeline."""

    user_story: str
    story_title: Optional[str] = None
    story_id: Optional[str] = None
    acceptance_criteria: List[str] = Field(default_factory=list)
    module: Optional[str] = None

    validated_requirements: List[ValidatedRequirement] = Field(default_factory=list)
    test_suite: List[TestCase] = Field(default_factory=list)
    coverage_gaps: List[CoverageGap] = Field(default_factory=list)
    security_risks: List[SecurityRisk] = Field(default_factory=list)
    logs: List[ExecutionLog] = Field(default_factory=list)
    suggested_patches: List[Patch] = Field(default_factory=list)

    # Two-phase Agile extension fields
    pipeline_mode: str = "POST_CODE"
    design_contracts: List[DesignContract] = Field(default_factory=list)
    security_checklist: List[SecurityChecklistItem] = Field(default_factory=list)
    phase1_risk_ids: List[str] = Field(default_factory=list)

    # Layer A — SurfaceMap, keyed by requirement_id. Populated by
    # surface_resolver_node between Critic and Generator; immutable through
    # heal cycles. Empty dict means Resolver did not run (back-compat) — the
    # downstream gates fall through harmlessly when this is empty.
    surface_map: Dict[str, SurfaceBinding] = Field(default_factory=dict)

    heal_attempts: int = 0
    max_heal_attempts: int = 2
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True
