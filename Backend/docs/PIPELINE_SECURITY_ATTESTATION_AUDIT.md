# Pipeline security attestation audit (Sentinel-QA)

Full-scope review of dynamic security testing, verdict classification, Surface
Map binding, and Healer — June 2026.

## Executive summary

The pipeline had **one fatal semantic bug** affecting every “missing control”
story (rate limit, title XSS, security headers):

| Pytest outcome | Meaning for gap tests (Rule 4) | Old classifier | Fixed classifier |
|----------------|--------------------------------|----------------|------------------|
| **passed** | Weakness confirmed | **resilient** (wrong) | **vulnerable** |
| **failed** | Often still OK via forbidden-body tiers | mixed | unchanged |

Login brute-force and title-XSS demos exposed the same inversion. This was
**not** per-attack-type randomness — it was a **single shared code path** in
`pytest_runner.py` (adversarial + `passed` → always resilient).

Structural fix: explicit `attestation_mode` on every adversarial `TestCase`:

- `missing_control` — pass = **vulnerable**
- `defense_confirming` — pass = **resilient** (Rule 11b, SEC-* mutations)

Shared module: `Backend/agents/attestation.py`.

---

## Pipeline stages — risk matrix

| Stage | Attack types affected | Risk | Mitigation |
|-------|----------------------|------|------------|
| **Surface Resolver** | Missing control (A04 login, A03 XSS title, A05 headers) | Was `NOT_IMPLEMENTED` when defense code absent | `_promote_missing_control_binding` → `BACKEND_API` + `missing_control` |
| **Generator** | All | Gap tests not stamped → classifier guessed | `stamp_attestation_mode()` on every security test |
| **Security Compiler** | A03 SQLi/XSS mutations (`SEC-*`) | Could inherit wrong mode | Force `defense_confirming` on mutations |
| **pytest_runner pass** | All adversarial | **Critical** — inverted verdict | `adversarial_verdict_on_pass()` |
| **pytest_runner fail** | GET list SQLi, register bcrypt | False vulnerable on 200 | Tier 1/2 forbidden + route rules (existing) |
| **Executor / posture** | All | `resilience_pct` lied | Uses `is_vulnerable` / `resilient` from fixed logs |
| **Healer** | All | Only runs on `vulnerable` or functional fail | More app patches once classifier fixed |
| **Healer opt-out** | Functional harness (404 task_id) | Correct “test defect” | Keep; fix generator workflows separately |
| **UI attestation** | Empty suite | `OK` + `NO_TESTS_GENERATED` | `NOT_ATTESTED` when 0 tests |
| **SAST (Bandit)** | Static | Independent | Do not conflate with dynamic verdict |

---

## Two adversarial paradigms (do not mix)

### 1. Defense-confirming (pass = resilient)

- **Rule 11b** / `DEFENSIVE_INVERTED` with defense code in RAG
- **SEC-*** compiler mutations (SQLi, XSS probes)
- Asserts: 4xx rejection, or 200 + body does **not** contain forbidden tokens
- **Example:** parameterized query — SQLi string in title returns 201, no leak

### 2. Missing-control (pass = vulnerable)

- **Rule 4** — control required by AC but **absent** in code
- Asserts: weak behavior still works (no 429, unsanitized `<script>` in JSON title)
- **Example:** no rate limit on `POST /login`, title not passed through `_strip_html`

---

## Repo-cache stories — expected behaviour after fix

| Demo JSON | Real gap | Expect vulnerable | Healer target |
|-----------|----------|-------------------|---------------|
| `healer_app_bugs_story_upload.json` | No login throttle | Yes | `routers/auth_router.py` |
| `healer_task_xss_story_upload.json` | Title not sanitized | Yes | `schemas.py` |
| `healer_security_headers_story_upload.json` | No CSP/XFO headers | Yes | `main.py` |
| Lifecycle / FR validation | App mostly correct | Few | Functional only |
| `SEC-*` mutations on PATCH | Neutralized | No (resilient) | None |

---

## Remaining known limitations

1. **Heuristic fallback** — unstamped legacy tests still use title keywords; prefer `attestation_mode` in artifact.
2. **Partial defenses** — description sanitized but not title; resolver may still see `_strip_html` in RAG and bias DEFENSIVE_INVERTED; binding promotion helps but LLM variance remains.
3. **Workflow tests** — PATCH 404 when `{task_id}` not captured; Healer opt-out is correct.
4. **GET 200 + SQLi** — not auto-vulnerable (by design); body must leak via forbidden tiers.
5. **Healer quality** — LLM may still opt-out or propose partial files; not a classifier issue.
6. **LangChain env** — unit tests need project venv to import `agents` package.

---

## Operator checklist

1. Restart **shim** after any `agents/` change.
2. Re-ingest **repo_cache** if routes/schemas changed.
3. Upload **one story JSON** per run.
4. Read **resilience vs vulnerable** — not pytest pass rate.
5. Download **patches .md** — empty `target_file` = test defect or Healer opt-out.
6. Trust **SAST** separately from dynamic posture.

---

## Files touched in structural fix

- `agents/attestation.py` (new)
- `agents/pytest_runner.py`
- `agents/generator.py`
- `agents/surface_resolver.py`
- `agents/security_compiler.py`
- `state/project_state.py` (`attestation_mode` on `TestCase`)
- `agents/executor.py` (`NOT_ATTESTED`)
- `frontend` — `RunValiditySchema`, `RunValidityHero`
