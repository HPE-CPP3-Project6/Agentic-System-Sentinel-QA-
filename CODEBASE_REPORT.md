# Sentinel-QA — Codebase Audit & HPE Integration Report

**Date:** 2026-05-26
**Scope:** Full repository — all Python files in `Backend/`, target app in `Backend/repo_cache/`, cloud scaffolding in `Backend/cloud/`, merged precode pipeline, Dockerfile/runbook, config files.
**Lens:** Honest brutal — what's broken, what's fragile, what's missing, and the HPE-specific integrations that are cheap to ship.

---

## Executive summary

| Dimension | Grade | Trend |
|---|---|---|
| Architecture & design | **A−** | Stable |
| RAG subsystem | **B+** | Stable |
| Agent implementation | **B** | ↑ (healer fixed, posture fixed) |
| Closing the loop (executor → real app) | **B−** | ↑ from D+ (cloud scaffolding shipped; demo pending venv rebuild) |
| Testing & engineering hygiene | **D+** | ↑ from D (5 golden tests added, still no CI) |
| Self-reporting honesty | **B+** | Stable |
| **Composite** | **B− / 76** | ↑ from C+/74 |

The needle moved on three things this week: (1) the orphaned-healer regression got fixed, (2) the Phase-1 cloud sidecar shipped, and (3) the security-posture skipped-vs-resilient lie got fixed. The composite stays in B-territory because **the loop has still never been observed closing against a live target**, and the merged PRE_CODE pipeline has unwired plumbing (`phase_bridge/` dead code).

The top three things that will move this to a confident A− are: (1) one real end-to-end demo run that produces `patches_proposed > 0`, (2) wiring `phase_bridge` so the drift report has a caller, (3) GitHub Code Scanning integration (SARIF) — the single most pitch-ready HPE-adjacent integration.

---

## CRITICAL bugs (will produce wrong results)

### C1 — `phase_bridge/` is dead code
**Location:** [Backend/phase_bridge/](Backend/phase_bridge/) — none of `save_phase1`, `load_phase1`, `generate_drift_report` are referenced outside the package itself.
**Impact:** The entire PRE_CODE ↔ POST_CODE bridge — the *defining feature* of the merged feature/precode-pipeline branch — does nothing. After a PRE_CODE run nothing is persisted; there is no script that calls `load_phase1 + generate_drift_report`.
**Fix:** Wire `save_phase1(state)` into `main.py` at the end of PRE_CODE runs; add `--mode drift_report` to `main.py` that loads + computes.

### C2 — `drift_report` `exploit_target` split bug
**Location:** [Backend/phase_bridge/drift_report.py:39-44](Backend/phase_bridge/drift_report.py#L39-L44).
`exploited_owasp_ids` uses `.split()[0]` which yields `"A03:2021-Injection"`. `confirmed_risks` carries `"A03:2021"`. Set membership fails → `confirmed_and_exploited` is **almost always empty** even when a predicted risk was confirmed exploited. The checklist check 6 lines below uses `.split(":")[0]` — inconsistent.
**Fix:** Normalize both to short id (`.split(":")[0]`) consistently.

### C3 — `github_sync` does not handle file renames or type changes
**Location:** [Backend/database/github_sync.py:265-270](Backend/database/github_sync.py#L265-L270). Only `A`/`M`/`D` are mapped. A renamed file leaves **stale vectors at the old path** AND **never adds vectors at the new path**. File moves are common in any active repo.
**Fix:** Handle `R` (rename: treat as delete-old + add-new) and `T` (typechange: treat as modify). 8 lines.

### C4 — `github_sync` re-indexes everything on every restart
**Location:** [Backend/database/github_sync.py:198](Backend/database/github_sync.py#L198) — `previous_commit = None` is set in `_setup_repository` and forgotten on daemon restart.
**Impact:** Daemon restart = full re-embed of the entire corpus (every file flagged as "added"). On a 5k-file repo this is 30+ minutes of Jina embedding and gigabytes of GPU/CPU work.
**Fix:** Persist `previous_commit` to a sidecar file (`./repo_cache/.sentinel_last_sync_sha`) and load it on init.

### C5 — `vector_store.query_source_snippets` swallows every exception silently
**Location:** [Backend/database/vector_store.py:706-715](Backend/database/vector_store.py#L706-L715). Two bare `except Exception: return []` blocks.
**Impact:** A 30-second OOM during embedding returns `[]`. The Generator sees no context → every requirement becomes a coverage gap. The actual failure is invisible. Triaging this is genuinely painful — it looks like a Chroma index problem when it's actually a process resource problem.
**Fix:** Log at WARNING with exception type + first-line message before returning `[]`. Two lines.

### C6 — `_security_posture` lumps timeouts with skips
**Location:** [Backend/agents/executor.py:334-348](Backend/agents/executor.py#L334-L348) (my recent fix). I count "skipped" as `resilient is None AND is_vulnerable is None`. But [pytest_runner.py timeout path](Backend/agents/pytest_runner.py) also produces logs with both None — status="error", not "skipped".
**Impact:** A pytest TimeoutExpired (real failure) gets reported as "skipped" in the security posture. Inflates the appearance of "tests not run" and hides actual infrastructure failures.
**Fix:** Distinguish via `log.status` — `"skipped"` → skipped bucket; `"error"` → error bucket (new), still excluded from resilient/vulnerable. ~6 lines.

### C7 — `config.SECRET_KEY` ships a known default
**Location:** [Backend/repo_cache/config.py:26](Backend/repo_cache/config.py#L26) — `SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION_use_a_long_random_secret_key_here"`.
**Impact:** Target app demo running without env override has a known JWT signing key. For Phase 1 sidecar this is fine (ephemeral container, never exposed). For any Phase 2+ deployment this is a critical anti-pattern. Generated by Pydantic-settings `BaseSettings` default — fails open silently.
**Fix:** Make it required (no default → fail-fast on missing env), generate one in the entrypoint with `secrets.token_hex(64)` for sidecar mode.

---

## HIGH-priority improvements

### H1 — Generator system prompt is a 620-line embedded string
**Location:** [Backend/agents/generator.py](Backend/agents/generator.py) — `GENERATOR_SYSTEM_PROMPT` from line 54 spans most of the file.
**Impact:** Cannot version it independently. Cannot A/B compare prompt revisions. Cannot diff cleanly across edits. Every change ships intertwined with code changes.
**Fix:** Extract to `agents/prompts/generator_v1.md`, load via `Path(__file__).parent / 'prompts' / 'generator_v1.md'`. ~10 lines. Add `prompt_version` field to Generator output metadata so runs can be correlated with prompt revisions.

### H2 — `_default_runner` is still a stub that always fails
**Location:** [Backend/agents/executor.py:62-67](Backend/agents/executor.py#L62-L67). Production path is now pytest_runner, but if `security_compiler_generated_files` is empty (compilation failed; empty test_suite; PRE_CODE upstream feeding POST_CODE downstream), we fall into the `else` branch which calls `_default_runner` → every test is logged as a failure → heal loop fires on phantom failures.
**Fix:** Either delete the stub path entirely (raise on missing pytest output), or build a real default runner that emits `status="error"` with a clear "no pytest file available" message instead of `passed=False`.

### H3 — `state.logs.extend` still accumulates across heal cycles, plus stale logs from generator
**Location:** [Backend/agents/executor.py:430](Backend/agents/executor.py#L430). Even with my B1+B2 fix (heal_attempt stamping + filtering), the *accumulation* itself is unbounded. After 5 heal cycles you have 5× logs in memory and in the artifact JSON.
**Fix:** Either replace instead of extend (lose history), or expose the latest-cycle logs via a property and stop extending. The former is simpler; the latter preserves audit trail.

### H4 — `vector_store` retrieves the same 5 queries every heal cycle
**Location:** [Backend/database/vector_store.py:865-983](Backend/database/vector_store.py#L865-L983). Generator's heal re-entry rebuilds the test suite from scratch (line 971-973 in `generator_node`) → re-issues 5 Chroma queries per requirement × N requirements × M heal cycles.
**Impact:** Wasted compute. A 10-requirement story with 2 heal cycles = 100 Chroma queries; only 50 produce new information.
**Fix:** Memoize `query_source_context` by `(action, intent, context_keywords)` for the lifetime of one `ProjectState`. Cache invalidates per pipeline invocation. ~20 lines.

### H5 — No test coverage on Critic, Generator, Security+Compiler
**Location:** [Backend/tests/test_executor.py](Backend/tests/test_executor.py) is the only test file. 5 tests, all on the executor. Critic / Generator / Security+Compiler / vector_store / pytest_runner / setup_target / publish_results all have **zero coverage**.
**Impact:** The next refactor (any of them) breaks something silently. The recent orphaned-healer regression was caught because I scanned the diff line-by-line, not because tests failed.
**Fix:** Add at minimum: one golden test per Critic OWASP mapping rule (5–8 tests), one Generator output schema test, one Security+Compiler `_mutate` field-targeting test, one `vector_store._chunk_source` AST chunker test. ~200 lines total, single afternoon.

### H6 — No CI / lint enforcement
**Location:** [Backend/pyproject.toml](Backend/pyproject.toml) configures ruff + pytest but **nothing runs them**.
**Impact:** Lint config drifts away from reality. Tests rot. The first PR review for HPE will catch this immediately.
**Fix:** `.github/workflows/ci.yml` — 30 lines, runs `pytest` + `ruff check`. Use the Cloud Build trigger from Phase 2 to also gate the Sentinel pipeline.

### H7 — `setup_target.py` test user is shared across runs
**Location:** [Backend/cloud/setup_target.py:34](Backend/cloud/setup_target.py#L34) — defaults to `sentinel-qa@example.com`. Two concurrent runs against the same target share the same user → race conditions on `/register` (idempotent thanks to 409 handling) but token collisions if both runs login simultaneously.
**Impact:** In Phase 1 sidecar this is harmless (each run has its own target SQLite). In Phase 2 (shared target, per-PR Sentinel) this is a real concurrency bug.
**Fix:** Randomize email per run: `f"sentinel-qa-{uuid4().hex[:8]}@example.com"`. ~3 lines.

### H8 — Healer prompt does not get the previous failed-patch context
**Location:** [Backend/agents/executor.py:280-319](Backend/agents/executor.py#L280-L319). On heal cycle 2, the LLM sees the same failure log + same RAG context as cycle 1 and is asked to propose a fix again — with no awareness that cycle 1's fix didn't work.
**Impact:** LLM tends to propose the same patch twice. Heal cycles burn tokens with no diversity.
**Fix:** Add `state.suggested_patches` (filtered to related_test_ids) to the user prompt as "previous patches that did not resolve the failure — propose a different approach". ~15 lines.

---

## MEDIUM-priority improvements

### M1 — `_default_runner` path NameError on empty `test_suite`
Already noted — if `state.test_suite` is empty and pytest path is skipped, `for tc in state.test_suite` is a no-op, but my zip-based heal pass is also empty, so safe. But pre-merge code (in the friend's older fork copy in main now via merge) had a NameError on empty. Verify post-merge it doesn't.

### M2 — `run_critic_generator.py` and `run_three_agents.py` duplicate `build_graph` logic
**Location:** [Backend/run_critic_generator.py](Backend/run_critic_generator.py), [Backend/run_three_agents.py](Backend/run_three_agents.py). Both hand-build a sub-graph. `main.py` is the canonical entrypoint post-merge.
**Fix:** Replace both with thin wrappers around `main.build_graph()` that prune to 2 / 3 nodes, OR delete them and add `--up-to <node>` flag to `main.py`.

### M3 — `samples/sample_stories.py` mixes prod-realistic and deliberately-vulnerable stories
The "security stories" (`login`, `search`, `perms`, `ratelimit`, `dataexport`) have ACs that are intentionally bad ("must accept any username and password without length restrictions"). They're test fixtures for the Critic. **They should be obviously marked as such** — currently the AC text reads as if a real PO wrote it. A future reader could mistake them for real requirements.
**Fix:** Prefix titles with `[VULN-DEMO]` and add a module-level docstring warning.

### M4 — `.env.example` documentation drift
**Location:** [Backend/.env.example:36-44](Backend/.env.example#L36-L44). Comments say "Default is `naive`" but [vector_store.py:86](Backend/database/vector_store.py#L86) defaults to `STANDARD`. Lying documentation is worse than no documentation.
**Fix:** One-line edit.

### M5 — Generator `_generate_for_requirement` exception handling is overly broad
**Location:** [Backend/agents/generator.py:1027-1036](Backend/agents/generator.py#L1027-L1036) — `except Exception` with `noqa: BLE001`. Records a coverage gap but doesn't log the exception type/message.
**Fix:** Add `logger.exception(...)` before the gap, and include `type(exc).__name__` in the gap reason. ~3 lines.

### M6 — `pytest_runner` runs ALL tests in ONE subprocess
**Location:** [Backend/agents/pytest_runner.py:88](Backend/agents/pytest_runner.py#L88). One hung test = the whole batch killed by timeout. JUnit XML won't have partial results when timeout fires.
**Fix:** Run adversarial tests in a separate subprocess from functional, OR use pytest's per-test timeout plugin (`pytest-timeout`). The plugin is one extra dep + a config line.

### M7 — `ast_chunker` cannot subdivide giant declarations
**Location:** [Backend/database/ast_chunker.py:155-162](Backend/database/ast_chunker.py#L155-L162) — explicitly documented as a known limitation. A 1000-line React component becomes one chunk. The reranker can rescore it but the chunk itself dominates the prompt token budget.
**Fix:** Subdivide via class methods / nested function_declarations rather than top-level children. Tar-pit risk acknowledged in the existing docstring.

### M8 — `vector_store._SKIP_DIRS` includes `"repo_cache"`
**Location:** [Backend/database/vector_store.py:145](Backend/database/vector_store.py#L145). If anyone runs `python -m database.ingest .` from `Backend/`, the target app under `repo_cache/` gets skipped silently. Only the cloud path (which targets `repo_cache` directly) works.
**Fix:** Drop `repo_cache` from `_SKIP_DIRS` (it's an artifact of past workflow) or make the skip configurable.

### M9 — Empty `Dockerfile`, `entrypoint.sh` permission on Windows
**Location:** [Backend/cloud/entrypoint.sh](Backend/cloud/entrypoint.sh) won't have executable bit when committed from Windows. Dockerfile does `chmod +x` so this is handled in-image, but `git update-index --chmod=+x Backend/cloud/entrypoint.sh` should be run once to set the file mode in the index.

### M10 — `bootstrap.py` runs `configure_caches()` at module import
**Location:** [Backend/bootstrap.py:55](Backend/bootstrap.py#L55) — `CACHE_DIR = configure_caches()`. Idempotent, but a non-obvious side effect of `import bootstrap` (creates a directory). Surprising in tests that don't want the directory created.
**Fix:** Move the auto-invocation to an explicit `if __name__ == "__main__"` or remove it (every caller already invokes explicitly).

---

## LOW-priority / code quality

| # | Issue | Location |
|---|---|---|
| L1 | `json_parse` loses original JSONDecodeError context on json_repair fallback | [json_parse.py:125](Backend/utils/json_parse.py#L125) |
| L2 | `placeholders._ALPHABETS["ascii"]` is alias for `"alnum"` — misleading | [placeholders.py:27](Backend/utils/placeholders.py#L27) |
| L3 | `utils/llm.py` silently disables retries if `google-api-core` missing | [llm.py:74-76](Backend/utils/llm.py#L74-L76) |
| L4 | `setup_target.py` doesn't set User-Agent for httpx | [setup_target.py](Backend/cloud/setup_target.py) |
| L5 | `security_compiler.py` now 500+ lines after merge — split candidate | [security_compiler.py](Backend/agents/security_compiler.py) |
| L6 | No `agents/templates/__init__.py` — fine but trips some tools | — |
| L7 | `github_sync.py` writes `sync.log` in CWD — non-portable | [github_sync.py:42](Backend/database/github_sync.py#L42) |
| L8 | No HTTP `User-Agent` from generated pytest — target logs can't distinguish | [pytest_api.jinja2](Backend/agents/templates/pytest_api.jinja2) |
| L9 | `ProjectState` has no schema_version field — artifact JSONs won't validate after model changes | [project_state.py](Backend/state/project_state.py) |
| L10 | Docker image is ~4.5 GB; could split builder-only stage for ingestion vs slim runtime for inference | [Dockerfile](Backend/Dockerfile) |

---

## HPE INTEGRATION OPPORTUNITIES

Ranked by **effort × strategic value for HPE specifically**. The first three are the ones I'd ship next; they're cheap and they all land squarely in tools HPE engineering already uses.

### TIER 1 — Easy + high strategic value (ship these next)

#### 1. GitHub Code Scanning via SARIF upload
**Why HPE will love this:** HPE migrated to GitHub Enterprise. Code Scanning is the native security UI surface on every PR. Sentinel findings showing up there means "another GHAS scanner" in reviewers' minds — zero new tooling to adopt.
**What it looks like:** Convert `suggested_patches` + `confirmed_and_exploited` risks → SARIF 2.1 → `POST /repos/{owner}/{repo}/code-scanning/sarifs`. Findings render with file:line, severity, rule, fix-suggestion right in the PR's "Files changed" view.
**Effort:** ~150 lines (SARIF schema is well-specified, jsonschema in any IDE). 1 day including PR-level testing.
**Where it plugs in:** `Backend/cloud/publish_results.py` gains a `_emit_sarif()` step alongside the GCS upload.

#### 2. Jira sub-task creation for `SecurityChecklistItem`
**Why HPE will love this:** HPE Engineering uses Jira (Atlassian Cloud) as the system-of-record for sprint work. Pushing `SecurityChecklistItem`s as sub-tasks of the story epic means the security checklist appears **in the dev's normal sprint board** — not in a separate tool they have to remember to check. This is the single biggest shift-left UX win in the project.
**What it looks like:** REST `POST /rest/api/3/issue` with parent=story-key, summary=instruction, description=rationale + "Verified when…", custom field "Sentinel-managed=true".
**Effort:** ~80 lines + 1 secret (Jira API token in Secret Manager). 1 day.
**Where it plugs in:** New `Backend/cloud/jira_push.py` called by entrypoint when PRE_CODE mode completes.

#### 3. Slack / MS Teams webhook on run completion
**Why HPE will love this:** Both are pervasive at HPE. A `#sec-qa` channel that posts every run's headline (passed/failed, patches proposed, vulnerabilities confirmed) is the cheapest possible "we have visibility" demo. Sells itself in any leadership review.
**What it looks like:** One `POST` per run to an Incoming Webhook URL. Block Kit formatting for Slack, Adaptive Card for Teams. Both formats are 30 lines of JSON.
**Effort:** ~30 lines + 1 webhook URL (no auth, no SDK). Half a day.
**Where it plugs in:** Append to `publish_results.py`.

### TIER 2 — Easy + medium value

#### 4. Splunk HTTP Event Collector (HEC)
**Why HPE will love this:** HPE OpsRamp (their AIOps platform, acquired 2023) and HPE customer deployments routinely feed Splunk. HEC accepts JSON via a single HTTPS POST with a token. Sentinel's per-stage timing/cost/RAG-hit telemetry maps cleanly to Splunk events.
**Effort:** ~30 lines, one env var (`SPLUNK_HEC_URL`, `SPLUNK_HEC_TOKEN`). Half a day.
**Where it plugs in:** Wrap `logger` calls in agent nodes with an additional `splunk_emit()` when configured.

#### 5. PagerDuty Events API v2
**Why:** On `confirmed_and_exploited` (predicted risk that exploited successfully), trigger a PD incident. Real ops integration HPE customers will recognize.
**Effort:** ~40 lines, one routing key. Half a day.

#### 6. Confluence page per `DesignContract`
**Why:** PMs read Confluence. Auto-published API contracts per story = "Sentinel speaks PM."
**Effort:** ~70 lines. 1 day.

### TIER 3 — Medium effort + high strategic value (Phase 3+)

#### 7. HPE OpsRamp event ingestion
**Why:** This is the *crown-jewel* HPE-native integration. OpsRamp is HPE's AIOps + ITOM platform; they're aggressively positioning it as their unified observability tier. Sentinel feeding OpsRamp events ("vulnerability detected", "patch proposed", "drift confirmed") puts Sentinel inside the HPE product surface area.
**Effort:** ~150 lines + OpsRamp API credentials. OpsRamp REST API is documented; auth is via JWT obtained from `POST /tenants/{tenantId}/token`. 2–3 days including event-schema design.
**Where it plugs in:** New `Backend/cloud/opsramp_emit.py`.

#### 8. ServiceNow Security Operations
**Why:** HPE internal uses ServiceNow heavily. Pushing `Patch` + confirmed vulnerabilities as `sn_si_incident` records gives security operations a native incident view.
**Effort:** ~60 lines + ServiceNow OAuth or basic-auth credential.

#### 9. HPE Ezmeral Runtime Enterprise — Helm chart packaging
**Why:** For HPE customers not on GCP. Same container image, packaged as a Helm chart pointing at a K8s cluster (any CNCF distro, but Ezmeral specifically is HPE's branded story). Phase 1 already uses standard Linux containers — porting is ~200 lines of Helm + a values.yaml.
**Effort:** 2 days for first chart; subsequent app changes are zero-cost.

### TIER 4 — Strategic but harder (defer)

| # | Integration | Why deferred |
|---|---|---|
| 10 | Fortify on Demand bidirectional | HPE-origin SAST but now OpenText-owned; SAML auth is a project on its own |
| 11 | HPE Vertica run-history analytics | Needs ETL; premature optimization until run volume exists |
| 12 | HPE GreenLake for AI Sentinel-as-a-Service | Requires partnership engagement, not engineering |
| 13 | Microsoft Entra ID OIDC on dashboard | Only relevant if Phase-3 dashboard ships |

---

## Recommended action plan (the next 4 weeks)

| Week | Priority | Deliverables |
|---|---|---|
| **1** | Critical bugs | C1 (wire phase_bridge), C2 (drift_report fix), C3 (rename handling), C5 (log retrieval errors), C7 (SECRET_KEY required). Plus the demo run that earns the headline metric. |
| **2** | Tests + CI | H5 (tests for Critic/Generator/Security+Compiler), H6 (GitHub Actions CI). |
| **3** | HPE Tier-1 integrations | Integration #1 (SARIF), #2 (Jira), #3 (Slack/Teams). |
| **4** | Phase-2 cloud + Tier-2 | Per-PR Cloud Run revisions, WIF, GitHub status checks. Integration #4 (Splunk HEC). |

By end of week 4 the project has: a closed-loop demo, real test coverage, automated CI, three HPE-native integrations, and per-PR cloud isolation. That's the **defensible pitch**.

---

## Per-file reference (post-merge, post-Phase-1)

| File | Lines | Owner | Quality | Open issues |
|---|---|---|---|---|
| `main.py` | 175 | mine (CLI rewrite) | A− | Hardcoded story default `taskshare`; could read from env |
| `bootstrap.py` | 55 | original | A | M10 (import-time side effect) |
| `agents/critic.py` | 261 | original | A− | H5 (no tests) |
| `agents/generator.py` | 1120 | original | B | H1 (embedded prompt), M5 (broad exception) |
| `agents/security_compiler.py` | ~500 | merged | B+ | L5 (size) |
| `agents/executor.py` | ~470 | recently fixed | B | H2 (stub runner), H3 (log accumulation), H8 (no patch history) |
| `agents/pytest_runner.py` | ~250 | recently fixed | B+ | C6 (timeout-as-skipped), M6 (one subprocess) |
| `database/vector_store.py` | 984 | original | B+ | C5 (silent retrieve errors), H4 (no query cache), M8 (repo_cache skip) |
| `database/ast_chunker.py` | 257 | original | A− | M7 (no subdivision) |
| `database/github_sync.py` | 520 | original | B− | C3 (rename), C4 (re-index), L7 (sync.log) |
| `database/ingest.py` | 40 | original | A | — |
| `database/reranker.py` | 162 | original | B+ | Empirically slow (10 min/req per docstring) |
| `phase_bridge/*` | ~130 | merged | C+ | C1 (unwired), C2 (split bug) |
| `state/project_state.py` | 144 | mine (heal_attempt) | A | L9 (no schema_version) |
| `utils/llm.py` | 149 | original | A | L3 (silent retry-disable) |
| `utils/json_parse.py` | 126 | original | A− | L1 (lost error context) |
| `utils/payloads.py` | 150 | original | A | — |
| `utils/boundaries.py` | ~357 | merged | A | — |
| `utils/placeholders.py` | 56 | original | A− | L2 (alias) |
| `samples/sample_stories.py` | 206 | merged | B | M3 (vuln demos look real) |
| `cloud/setup_target.py` | 175 | mine | A | H7 (shared test user) |
| `cloud/publish_results.py` | 240 | mine | A− | — |
| `cloud/entrypoint.sh` | 145 | mine | A− | M9 (Windows exec bit) |
| `cloud/RUNBOOK.md` | 240 | mine | A | — |
| `Dockerfile` | 100 | mine | A− | L10 (size) |
| `tests/test_executor.py` | 175 | mine | A− | — |
| `pyproject.toml` | 53 | original | B | H6 (lint config exists, no CI) |
| `.env.example` | 113 | original | B | M4 (doc drift on RAG mode default) |
| `repo_cache/config.py` | 52 | target app | C+ | C7 (default SECRET_KEY) |
| `repo_cache/models.py` | 197 | target app | A | — |
| `repo_cache/auth.py` | 194 | target app | A | — |

---

## What this audit deliberately does NOT cover

- **The frontend** (React) in `repo_cache/frontend/` — Sentinel doesn't ingest or test it yet; out of scope for Phase 1.
- **External dep CVEs** — `pip-audit` / `safety` belongs in CI (H6); not a code-audit question.
- **Prompt-injection hardening** of Critic/Generator outputs — real concern, but the entire LLM landscape has open work here. Worth a dedicated review.
- **Run-cost optimization at scale** — current Vertex costs are fine for demo; revisit when volume justifies.

---

## Final word

The project's **architecture is genuinely good**. The bugs are concentrated in (a) the unfinished PRE_CODE pipeline plumbing and (b) the still-untested healing logic. None of them are deep — most fixes are < 20 lines. The HPE integrations in Tier 1 are *days* of work each, not weeks, and three of them together would transform this from "interesting prototype" into "credible enterprise pilot."

Ship the demo run, write the tests, and pick two Tier-1 integrations. That's the path to A−.
