"""Shared state object passed between all LangGraph nodes in Sentinel-QA."""

from __future__ import annotations

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ValidatedRequirement(BaseModel):
    requirement_id: str
    statement: str
    ambiguity_score: float = Field(ge=0.0, le=1.0)
    ambiguity_notes: Optional[str] = None
    owasp_mapping: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)


class TestCase(BaseModel):
    test_id: str
    title: str
    action: str
    input_data: Dict[str, Any] = Field(default_factory=dict)
    expected_result: str
    coverage_rationale: Optional[str] = None
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
