import type { Story, RunHistoryItem, ProjectState, RunSummary } from "@/api/types";

export const mockStories: Story[] = [
  {
    id: "story-search-001",
    title: "Task Search",
    body: "As a user I want to search tasks by keyword so I can find work quickly.",
    acceptance_criteria: [
      "Given I am logged in, When I search by title, Then matching tasks are returned.",
      "Given no matches, When I search, Then an empty list is returned.",
      "Given SQL injection in query, When I search, Then the app rejects safely.",
    ],
    created_at: "2026-05-28T10:00:00Z",
  },
  {
    id: "story-nfr-security",
    title: "Security (NFR 8–10)",
    body: "As a platform owner I need authentication and input validation enforced.",
    acceptance_criteria: [
      "Given invalid registration input, When submitted, Then 422 is returned.",
      "Given SQLi in search, When queried, Then request is rejected safely.",
    ],
    created_at: "2026-05-27T09:00:00Z",
  },
];

export const mockRuns: Record<string, RunHistoryItem[]> = {
  "story-search-001": [
    {
      run_id: "r_demo_8f",
      started_at: "2026-05-29T10:00:00Z",
      pipeline_mode: "post_code",
      run_validity: "OK",
      suite_quality: "ATTESTABLE",
      resilience_pct: 100,
    },
  ],
  "story-nfr-security": [
    {
      run_id: "r_nfr_sec",
      started_at: "2026-05-31T05:29:00Z",
      pipeline_mode: "post_code",
      run_validity: "OK",
      suite_quality: "ATTESTABLE",
      resilience_pct: 87.5,
    },
  ],
};

export const mockArtifact: ProjectState = {
  pipeline_mode: "POST_CODE",
  run_validity: "OK",
  coverage_quality: "ATTESTABLE",
  suite_quality: "ATTESTABLE",
  attestation_banner: "Suite ran with meaningful coverage.",
  resilience_pct: 87.5,
  security_posture: {
    attempted: 16,
    resilient: 14,
    vulnerable: 2,
    skipped: 0,
    errored: 0,
    resilience_pct: 87.5,
    by_exploit_target: {
      "A04:2021": { attempted: 4, resilient: 4, vulnerable: 0, skipped: 0, errored: 0 },
      "A03:2021": { attempted: 4, resilient: 2, vulnerable: 2, skipped: 0, errored: 0 },
      "A04-Insecure": { attempted: 8, resilient: 8, vulnerable: 0, skipped: 0, errored: 0 },
    },
  },
  surface_map: {
    "REQ-001": {
      req_id: "REQ-001",
      requirement_text: "Registration rejects invalid email formats",
      state: "BACKEND_API",
      threat_class: "DEFENSIVE_INVERTED",
      defense_kind: "INPUT_REJECTION",
      backend_endpoints: [
        {
          method: "POST",
          path: "/register",
          handler_file: "routers/auth_router.py",
          handler_line: 27,
        },
      ],
      grounding_refs: ["auth_router.py:27-58"],
      confidence: "high",
      assertion_hint: "422 when email exceeds max length",
    },
    "REQ-002": {
      req_id: "REQ-002",
      requirement_text: "Search rejects SQL injection payloads",
      state: "BACKEND_API",
      threat_class: "DEFENSIVE_INVERTED",
      defense_kind: "INPUT_REJECTION",
      backend_endpoints: [
        {
          method: "GET",
          path: "/tasks/search",
          handler_file: "routers/task_router.py",
          handler_line: 42,
        },
      ],
      grounding_refs: ["task_router.py:42-68"],
      confidence: "high",
    },
    "REQ-003": {
      req_id: "REQ-003",
      requirement_text: "Offline sync queue",
      state: "NOT_IMPLEMENTED",
      threat_class: "NON_FUNCTIONAL",
      backend_endpoints: [],
      grounding_refs: [],
      confidence: "low",
    },
  },
  test_suite: [
    {
      test_id: "TC-REQ-001-01",
      title: "Valid registration succeeds",
      category: "positive",
      technique: "equivalence_partitioning",
      method: "POST",
      path: "/register",
      expected_status_code: 201,
      adversarial: false,
    },
    {
      test_id: "TC-REQ-002-01",
      title: "SQLi payload rejected on search",
      category: "security",
      technique: "security_adversarial",
      method: "GET",
      path: "/tasks/search?q=' OR 1=1--",
      expected_status_code: 422,
      adversarial: true,
      forbidden_response_content: ["syntax error", "sqlite"],
    },
  ],
  execution_logs: [
    {
      test_id: "TC-REQ-001-01",
      status: "passed",
      verdict: "n/a",
      verdict_confidence: "high",
      duration_ms: 142,
    },
    {
      test_id: "TC-REQ-002-01",
      status: "passed",
      verdict: "resilient",
      verdict_confidence: "high",
      duration_ms: 88,
      exploit_target: "A03:2021",
    },
  ],
  suggested_patches: [
    {
      patch_id: "patch-001",
      test_id: "TC-REQ-002-01",
      summary: "Tighten forbidden_content check for SQL error leakage",
      decision: "pending",
    },
  ],
  drift_report: {
    summary: {
      predicted: 3,
      confirmed_in_phase2: 3,
      missed_in_phase2: 0,
      new_in_phase2_only: 0,
    },
    confirmed_risks: ["A01", "A03", "A04"],
  },
  sast_summary: {
    tool: "bandit",
    ran: true,
    findings_total: 2,
    files_scanned: 12,
    by_severity: { MEDIUM: 1, LOW: 1 },
    top_findings: [
      {
        test_id: "B105",
        test_name: "hardcoded_password_string",
        severity: "MEDIUM",
        confidence: "MEDIUM",
        issue: "Possible hardcoded password: 'admin123'",
        path: "repo_cache/app/auth.py",
        line: 14,
        cwe: 259,
      },
      {
        test_id: "B608",
        test_name: "hardcoded_sql_expressions",
        severity: "LOW",
        confidence: "HIGH",
        issue: "Possible SQL injection vector through string-based query construction.",
        path: "repo_cache/app/db.py",
        line: 42,
        cwe: 89,
      },
    ],
    note: "STATIC analysis — separate from dynamic security_posture; never auto-healed",
  },
  test_suite_summary: {
    totals: { planned: 24, executed: 24 },
    by_category: {
      security: { planned: 16, executed: 16, resilient: 14, vulnerable: 2 },
    },
  },
};

export const mockRunSummary: RunSummary = {
  run_id: "r_demo_8f",
  status: "paused",
  current_phase: "surface_resolver",
  phases: [
    { phase: "critic", status: "completed", duration_ms: 2100 },
    { phase: "surface_resolver", status: "completed", duration_ms: 18044 },
    { phase: "generator", status: "pending" },
    { phase: "security_compiler", status: "pending" },
    { phase: "executor", status: "pending" },
  ],
  partial_artifact: mockArtifact,
};

export const mockScript = `# Generated by Sentinel-QA — pytest API harness
import pytest
import httpx

BASE_URL = "http://localhost:8000"

def test_registration_valid():
    r = httpx.post(f"{BASE_URL}/register", json={"email": "u@ex.com", "password": "Str0ng!pass"})
    assert r.status_code == 201

def test_sqli_search_rejected():
    r = httpx.get(f"{BASE_URL}/tasks/search", params={"q": "' OR 1=1--"})
    assert r.status_code == 422
`;
