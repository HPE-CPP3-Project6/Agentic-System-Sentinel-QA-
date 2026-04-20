"""Shared state object passed between all LangGraph nodes in Sentinel-QA."""

from __future__ import annotations

from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field


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
    test_category: Optional[str] = None  # "positive", "negative", "boundary", "security"
    covered_requirement_id: Optional[str] = None
    covered_acceptance_criterion: Optional[str] = None
    source_refs: List[str] = Field(default_factory=list)
    is_adversarial: bool = False
    owasp_category: Optional[str] = None
    payload: Optional[str] = None
    exploit_target: Optional[str] = None
    mutated_fields: List[str] = Field(default_factory=list)
    parent_test_id: Optional[str] = None


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
    status: str  # "passed" | "failed" | "error"
    is_adversarial: bool = False
    # Functional verdict
    passed: Optional[bool] = None
    # Adversarial verdicts — mutually exclusive: exploit succeeded vs. app blocked it
    is_vulnerable: Optional[bool] = None
    resilient: Optional[bool] = None
    # Telemetry captured on failure
    duration_ms: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    trace: Optional[str] = None
    console_logs: List[str] = Field(default_factory=list)
    html_snapshot: Optional[str] = None
    exploit_target: Optional[str] = None


class Patch(BaseModel):
    target_file: str
    bug_explanation: str
    suggested_fix: str
    related_test_ids: List[str] = Field(default_factory=list)
    owasp_category: Optional[str] = None


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

    heal_attempts: int = 0
    max_heal_attempts: int = 2
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True
