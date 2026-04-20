"""Agent C — The Red-Teamer / OWASP Security Auditor.

Takes the functional test_suite produced by the Generator and mutates it into
adversarial variants using the OWASP Top 10 payload library. Each mutation is
scoped to the security_risks the Critic actually identified — the Red-Teamer
does NOT invent risks; it operationalises them.

For every adversarial TestCase emitted:
  * is_adversarial = True
  * exploit_target = "<OWASP id + label>"   (answers "what are we trying to trigger?")
  * payload        = <the raw attack string>
  * owasp_category = "<Axx:2021>"
  * mutated_fields = ["<field1>", ...]      (which input_data keys were replaced)
  * parent_test_id = <functional test it was derived from>
"""

from __future__ import annotations

import copy
from typing import Dict, List, Optional

from state import ProjectState, SecurityRisk, TestCase
from utils import Payload, get_payloads
from utils.boundaries import RESILIENCE_SIGNATURES, VULNERABILITY_SIGNATURES


def _functional_tests_for_requirement(
    tests: List[TestCase], requirement_id: str
) -> List[TestCase]:
    return [
        t for t in tests
        if not t.is_adversarial and t.covered_requirement_id == requirement_id
    ]


def _string_input_fields(tc: TestCase) -> List[str]:
    return [k for k, v in tc.input_data.items() if isinstance(v, str)]


def _mutate(
    base: TestCase,
    payload: Payload,
    risk: SecurityRisk,
    counter: int,
) -> TestCase:
    """Return an adversarial clone of `base` with string inputs replaced by the payload.
    
    CRITICAL: Include resilience signatures to define what "safe" looks like technically.
    """

    mutated_input: Dict[str, object] = copy.deepcopy(base.input_data)
    mutated_fields = _string_input_fields(base)

    if mutated_fields:
        for field in mutated_fields:
            mutated_input[field] = payload.value
    else:
        # No string input to mutate — attach the payload as an explicit probe field
        # so the Executor still fires something meaningful at the target.
        mutated_input["__adversarial_probe__"] = payload.value
        mutated_fields = ["__adversarial_probe__"]

    # Look up resilience signature for this OWASP category
    owasp_short = risk.owasp_id.split(':')[0]  # Extract "A03", "A01", etc.
    resilience_key = f"{owasp_short}_INJECTION" if owasp_short == "A03" else \
                     f"{owasp_short}_ACCESS_CONTROL" if owasp_short == "A01" else \
                     f"{owasp_short}_AUTH_FAILURE" if owasp_short == "A07" else \
                     f"{owasp_short}_INSECURE_DESIGN"
    
    resilience_sig = RESILIENCE_SIGNATURES.get(resilience_key, {})
    vuln_sig = VULNERABILITY_SIGNATURES.get(resilience_key, {})

    return TestCase(
        test_id=f"SEC-{risk.owasp_id.split(':')[0]}-{base.test_id}-{counter}",
        title=f"[{payload.technique}] {base.title}",
        action=base.action,
        input_data=mutated_input,
        expected_result=(
            f"Attack is neutralised: {payload.expected_signal}. "
            f"Original success path ('{base.expected_result}') must NOT occur "
            f"with an attacker-controlled value."
        ),
        # TECHNICAL ASSERTIONS: Expected for SAFE/RESILIENT response
        expected_status_code=resilience_sig.get("http_status", [200])[0],
        expected_json_keys=[],  # Attacker should NOT get data
        forbidden_response_content=resilience_sig.get("forbidden_keywords", []),
        # RESILIENCE SIGNATURE: What technically counts as "blocked" or "safe"
        resilience_signature=(
            f"Status code in {resilience_sig.get('http_status', [200])}. "
            f"Forbidden keywords: {', '.join(resilience_sig.get('forbidden_keywords', []))}. "
            f"Behavior: {resilience_sig.get('expected_behavior', 'N/A')}"
        ),
        # VULNERABILITY SIGNATURE: What technically counts as "exploited"
        vulnerability_signature=(
            f"Status code {vuln_sig.get('http_status', [200])[0]} with leaked data. "
            f"Contains keywords: {', '.join(vuln_sig.get('expected_keywords', []))}. "
            f"Behavior: {vuln_sig.get('expected_behavior', 'N/A')}"
        ),
        coverage_rationale=(
            f"Adversarial mutation of {base.test_id} targeting {payload.exploit_target}. "
            f"Technique: {payload.technique}. "
            f"Risk rationale (from Critic): {risk.rationale}"
        ),
        covered_requirement_id=base.covered_requirement_id,
        covered_acceptance_criterion=base.covered_acceptance_criterion,
        source_refs=list(base.source_refs),
        is_adversarial=True,
        owasp_category=risk.owasp_id,
        payload=payload.value,
        exploit_target=payload.exploit_target,
        mutated_fields=mutated_fields,
        parent_test_id=base.test_id,
    )


def _candidate_tests_for_risk(state: ProjectState, risk: SecurityRisk) -> List[TestCase]:
    """Which functional tests should this risk attack?

    If the Critic tied the risk to specific requirements, only mutate tests
    covering those. Otherwise fan out across the full functional suite.
    """
    functional = [t for t in state.test_suite if not t.is_adversarial]
    if not risk.affected_requirements:
        return functional

    targeted: List[TestCase] = []
    for req_id in risk.affected_requirements:
        targeted.extend(_functional_tests_for_requirement(functional, req_id))
    return targeted or functional


def red_teamer_node(state: ProjectState) -> ProjectState:
    """LangGraph node: expand test_suite with adversarial variants per security_risk."""

    if not state.security_risks:
        state.metadata["red_teamer_skipped"] = "no security_risks in state"
        return state
    if not any(not t.is_adversarial for t in state.test_suite):
        state.metadata["red_teamer_skipped"] = "no functional tests to mutate"
        return state

    adversarial: List[TestCase] = []
    unmatched_risks: List[str] = []

    for risk in state.security_risks:
        payloads = get_payloads(risk.owasp_id)
        if not payloads:
            unmatched_risks.append(risk.owasp_id)
            continue

        candidates = _candidate_tests_for_risk(state, risk)
        if not candidates:
            unmatched_risks.append(
                f"{risk.owasp_id} (no functional tests matched affected_requirements)"
            )
            continue

        counter = 0
        for base in candidates:
            for payload in payloads:
                counter += 1
                adversarial.append(_mutate(base, payload, risk, counter))

    state.test_suite.extend(adversarial)
    state.metadata["red_teamer_generated"] = len(adversarial)
    if unmatched_risks:
        state.metadata["red_teamer_unmatched_risks"] = unmatched_risks
    return state
