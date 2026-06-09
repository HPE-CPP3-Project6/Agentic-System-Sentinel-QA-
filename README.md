# Sentinel-QA

**Agentic QA pipeline for HPE-style API security and functional attestation.**  
Given a user story, acceptance criteria, and an indexed codebase, Sentinel-QA produces **grounded test cases**, **OWASP-aligned adversarial variants**, **runnable pytest**, and a **categorized execution report** — with honest **coverage gaps** when the spec outruns the code.

This is a **full-stack repository**: LangGraph multi-agent backend + FastAPI shim + React 19 reviewer UI with live WebSocket streaming.

The reference application under test is **Smart Task Manager** (FastAPI + SQLAlchemy + React), populated locally under `Backend/repo_cache/` (gitignored). The reviewer UI (`frontend/`) is production-ready — it drives the pipeline through a staged step-by-step workspace with PRE_CODE and POST_CODE dual-mode dashboards.

---

## What it does (one paragraph)

1. **Critic** — turns prose ACs into atomic requirements, ambiguity scores, and OWASP-linked risks.  
2. **Surface Resolver** — binds each requirement to a real code surface (`BACKEND_API`, `NOT_IMPLEMENTED`, …) and a **defense kind** for inverted security stories.  
3. **Generator** — POST_CODE: RAG over ChromaDB → `test_suite` + `coverage_gaps`; PRE_CODE: `design_contracts` (no RAG) and derives `surface_map` from them.  
4. **Security+Compiler** — POST_CODE: adversarial expansion + pytest file; PRE_CODE: `security_checklist` from Critic risks (no pytest).  
5. **Executor** — POST_CODE: pytest, heal loop, `run_validity` / `test_suite_summary`; PRE_CODE: `run_validity=DESIGN_ONLY`, `design_summary`, no execution.

---

## Pipeline (POST_CODE)

```mermaid
flowchart LR
  subgraph in [Inputs]
    ST[User story + ACs]
    IDX[ChromaDB index of repo_cache]
  end

  subgraph graph [LangGraph — Backend/main.py]
    C[Critic]
    S[Surface Resolver]
    G[Generator]
    SC[Security+Compiler]
    E[Executor / Healer]
    C --> S --> G --> SC --> E
    E -->|needs_healing| G
    E --> END([Artifact JSON])
  end

  ST --> C
  IDX --> S
  IDX --> G
```

| Mode | Command | What runs |
|------|---------|-----------|
| **POST_CODE** (default) | `python main.py post_code <story>` | Full graph: generate, compile, execute, heal (if configured). Requires Chroma ingest + live API for meaningful execution. |
| **PRE_CODE** | `python main.py --mode pre_code <story>` | Critic through Compiler; **design contracts** + **security checklist**; `run_validity=DESIGN_ONLY`. Saves Phase-1 snapshot for drift on the next POST_CODE run. |

**Entry point:** `Backend/main.py` only. Story keys come from `Backend/samples/sample_stories.py`.

```bash
cd Backend
python main.py --mode post_code search
python main.py lifecycle          # post_code is default
```

---

## Sample stories

| Key | Story ID | Intent |
|-----|----------|--------|
| `filter` | US-001 | Functional — client-side filter behavior |
| `lifecycle` | LIFE-001 | **State-transition** — CRUD + soft-delete on `/tasks/{task_id}` |
| `validation` | VALID-001 | Task create validation & sanitization (POST /tasks/) |
| `org` | ORG-001 | Functional — organization create (often thin / not in app) |
| `login` | AUTH-001 | Security anti-patterns → defense confirmation (A07, A03) |
| `search` | SEARCH-001 | Injection / search surface (A03) |
| `perms` | AUTHZ-001 | IDOR / access control (A01) — see [known limits](#known-limitations) |
| `ratelimit` | RATELIMIT-001 | Rate limit story (often honest empty in repo_cache) |
| `dataexport` | DATAEXP-001 | Data exposure anti-patterns |
| `taskshare` | TASK-002 | Public share links (often `NOT_IMPLEMENTED`) |

Default CLI story: `taskshare`.

**Mentor FR/NFR catalog** (19 category stories from the assignment requirements doc):
see [`samples/mentor_requirements/README.md`](Backend/samples/mentor_requirements/README.md).
Run e.g. `python main.py post_code req-fr-filter` or `req-nfr-security`.

---

## Quick start

### 1. Prerequisites

- **Python 3.10+**
- **Node.js 18+** (for the React frontend)
- **Google Cloud** project with Vertex AI enabled
- **ADC:** `gcloud auth application-default login` (or `GOOGLE_APPLICATION_CREDENTIALS`)
- For execution: **target API** running (see [Run the app under test](#run-the-app-under-test))

### 2. Install (Backend)

```powershell
cd Backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
pip install "tree-sitter>=0.23.0" "tree-sitter-language-pack>=0.4.0"
```

AST chunking **requires** `tree-sitter-language-pack`. Without it, ingest silently falls back to line-based chunks (worse citations).

### 3. Configure environment

```powershell
copy .env.example .env
```

Minimum:

| Variable | Purpose |
|----------|---------|
| `VERTEX_AI_PROJECT_ID` | GCP project (no default — fail-fast if missing) |
| `VERTEX_AI_LOCATION` | e.g. `us-central1` or `global` for preview models |
| `SENTINEL_LLM_MODEL` | Optional; default `gemini-2.5-flash` |

For **POST_CODE execution**:

| Variable | Purpose |
|----------|---------|
| `SENTINEL_BASE_URL` | Live API origin, e.g. `http://127.0.0.1:8000` |
| `SENTINEL_TEST_BEARER_TOKEN` | JWT from `POST /login` or `POST /register` |
| `SENTINEL_EXECUTOR_RUN_PYTEST` | `1` (default) to run generated pytest; `0` to skip |
| `SENTINEL_COMPILER_MAX_TESTS_PER_FILE` | Cap compiled tests (default `80`; use `25` for demos) |
| `SENTINEL_MAX_HEAL` | Cap graph heal cycles (`0`–`2`; lower for faster demos) |
| `SENTINEL_SAST` | `1` (default) runs Bandit after POST_CODE; `0` to skip |

Full list: [`Backend/.env.example`](Backend/.env.example).

### 4. Index the codebase (RAG)

From `Backend/`:

```powershell
python -m database.ingest repo_cache --reset
```

- **AST chunking** (Python, JS, JSX, TS, TSX) when tree-sitter is installed; else line-based fallback.  
- Embeddings: **Jina code embeddings** → `chroma_data/` (or `CHROMA_PERSIST_DIR`).  
- Optional sync: `database/github_sync.py` for remote repo → `repo_cache/`.

### 5. Run the app under test

In a second terminal:

```powershell
cd Backend\repo_cache
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --reload --port 8000
```

Obtain a token (example):

```powershell
curl -X POST http://127.0.0.1:8000/register -H "Content-Type: application/json" -d "{\"email\":\"demo@example.com\",\"password\":\"Secret1\"}"
```

Paste `access_token` into `Backend/.env` as `SENTINEL_TEST_BEARER_TOKEN`.

### 6. Run via the Reviewer UI (recommended)

The UI drives the full pipeline interactively. Start both processes:

```powershell
# Terminal 1 — API shim (wraps LangGraph for the frontend)
cd Backend
python run_shim.py          # listens on http://localhost:8080

# Terminal 2 — React frontend
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

Set `VITE_USE_MSW=false` in `frontend/.env` (or `.env.local`) to connect to the live shim instead of mock data.

The workspace has 6 tabs: **Input → Surface Map → Scenarios → Scripts → Run → Report**.  
PRE_CODE runs produce design contracts + security checklist; POST_CODE runs produce grounded tests, pytest execution, and a full security posture dashboard.

### 7. Run via CLI (headless)

```powershell
cd Backend
$env:SENTINEL_RAG_MODE = "standard"
python main.py --mode post_code search
```

Wall time is often **10–25 minutes** per story (LLM + pytest + optional heal). Use `SENTINEL_COMPILER_MAX_TESTS_PER_FILE=25` for faster demos.

---

## RAG modes (`SENTINEL_RAG_MODE`)

| Mode | Use when |
|------|----------|
| **`standard`** (default) | Daily runs — multi-query retrieval into labeled buckets (router / schema / model / frontend / api_client). |
| **`naive`** | Fast smoke only — **do not trust coverage-gap output** (empty buckets look like misses). |
| **`full`** | Evaluation — adds cross-encoder reranker; very slow on CPU. |

---

## Agents (responsibilities)

| # | Agent | Module | Output |
|---|--------|--------|--------|
| 1 | **Critic** | `agents/critic.py` | `validated_requirements`, `security_risks`, ambiguity flags |
| 1.5 | **Surface Resolver** | `agents/surface_resolver.py` | POST_CODE: `surface_map` from Chroma; PRE_CODE: skipped (Generator derives map from design contracts) |
| 2 | **Generator** | `agents/generator.py` | POST_CODE: `test_suite`, `coverage_gaps`; PRE_CODE: `design_contracts` + `surface_map` |
| 3 | **Security+Compiler** | `agents/security_compiler.py` | POST_CODE: adversarial rows + pytest; PRE_CODE: `security_checklist` |
| 4 | **Executor** | `agents/executor.py` | POST_CODE: `logs`, patches, `security_posture`, `test_suite_summary`; PRE_CODE: `design_summary`, `DESIGN_ONLY` attestation |

**Heal loop:** `needs_healing` → Generator when functional failures, vulnerabilities, or errors remain and heal budget allows (`heal_attempts` / `max_heal_attempts` on `ProjectState`).

---

## Layer A — Surface map and defenses

Stories that describe **insecure** behavior are translated into **defense-confirming** tests:

| `ThreatClass` | Meaning |
|---------------|---------|
| `DEFENSIVE_NORMAL` | Test the feature as specified |
| `DEFENSIVE_INVERTED` | Story asks for bad behavior; test that the **inverse** defense holds |
| `NON_FUNCTIONAL` | Cross-cutting; often `NEEDS_CLARIFICATION` |

| `DefenseKind` | Typical assertion shape |
|---------------|-------------------------|
| `INPUT_REJECTION` | 4xx on bad input |
| `OUTPUT_REDACTION` | 200 + forbidden fields absent |
| `IMPLICIT_FILTER` | 200 + peer data not leaked (404 on IDOR) |
| `ERROR_SANITIZATION` | No stack/SQL in errors |
| `TRANSPORT` | HTTPS / redirect policy |

Generator **Rule 11** drops tests that target paths outside the bound surface (honest abstention vs proxy noise).

---

## Test design and categorization

Tests carry **`test_category`** on each `TestCase`:

| Category | Role |
|----------|------|
| `positive` | Happy path / expected success |
| `negative` | Validation / controlled failure |
| `boundary` | BVA-style limits (`boundaries.py`, `boundary_value_used`) |
| `state_transition` | Multi-step workflows (`workflow_steps` in pytest template) |
| `security` | Adversarial / OWASP (`is_adversarial`, payloads from `utils/payloads.py`) |

Each `TestCase` also carries **`test_technique`** — the formal **ISTQB / ISO 29119-4** design discipline it embodies (distinct from `test_category`, which names the outcome class). Inferred from category + shape when the LLM omits it:

| `test_technique` | Discipline |
|------------------|-----------|
| `equivalence_partition` | One representative test per input class (`valid`, `invalid-empty`, `invalid-type`, `auth-missing`, …); the class is recorded in `equivalence_class` |
| `boundary_value` | Value at/adjacent to a limit (BVA) |
| `decision_table` | One row of a condition→action table (opportunistic — multi-condition stories) |
| `state_transition` | Ordered multi-step workflow (`workflow_steps`) |
| `requirements_based` | Direct AC restatement, no sharper technique |
| `security_adversarial` | Attack / abuse case |

After execution, **`test_suite_summary`** rolls up planned vs executed per category **and per technique** (`by_technique`), plus `equivalence_partitions` (req → class → test ids), `by_owasp`, and `by_defense_kind` — surfaced in the JSON artifact and CLI.

---

## Attestation cascade

Every adversarial test carries an **`attestation_mode`** stamp that drives the verdict — not the test title:

| `attestation_mode` | Set by | Meaning |
|--------------------|--------|---------|
| `missing_control` | Surface Resolver on the binding | Test is *attesting a gap* — the control is absent; a passing test (4xx) proves the gap is real |
| `defense_confirming` | Surface Resolver on the binding | Test is *verifying a defense* — the control exists; a passing test proves it holds |
| *(null)* | Not stamped | **UNCLASSIFIED** — excluded from resilience % and surfaced as amber in the UI |

The stamp flows: `SurfaceBinding.attestation_mode` → `TestCase.attestation_mode` (Generator inherits) → `VerdictRecord.attestation_mode` (Executor inherits). The UI shows the stamp at every stage: binding detail panel, Scenarios table, Findings table, and per-test in the Report.

---

## Output artifacts

Each run writes **`outputs/exec-demo-<story>-<mode>-<timestamp>.json`** (repo root, gitignored). PRE_CODE and POST_CODE share the **same top-level envelope**; `pipeline_mode` is the discriminator.

| Top-level field | Meaning |
|-----------------|--------|
| `pipeline_mode` | `PRE_CODE` or `POST_CODE` |
| `run_validity` | **Check this FIRST.** POST_CODE: `OK`, `TARGET_UNREACHABLE`, `FUNCTIONALLY_UNRELIABLE`. PRE_CODE: `DESIGN_ONLY` |
| `coverage_quality` | POST_CODE (when `run_validity==OK`): `ATTESTABLE`, `INSUFFICIENT`, … PRE_CODE: `DESIGN_COMPLETE`, `DESIGN_INSUFFICIENT`, `NO_REQUIREMENTS` |
| `suite_quality` | Deprecated alias of `coverage_quality` (one release) |
| `attestation_banner` | Human-readable warning when POST_CODE `run_validity != OK` |
| `design_contracts` | PRE_CODE: API contracts; POST_CODE: empty unless Phase-1 loaded |
| `security_checklist` | PRE_CODE: shift-left checklist; POST_CODE: empty unless Phase-1 loaded |
| `surface_map` | Always present; populated in both modes when bindings exist |
| `design_summary` | PRE_CODE: contract/checklist counts (`design_summary`); POST_CODE: null |
| `test_suite_summary` | POST_CODE: by category / technique / OWASP; PRE_CODE: null |
| `logs_detail` | POST_CODE: per-test final-cycle slice; PRE_CODE: empty |
| `sast_summary` | POST_CODE: Bandit sidecar (`SENTINEL_SAST=0` to skip); PRE_CODE: null |
| `validated_requirements` | Critic output |
| `security_risks` | OWASP mapping |
| `test_suite_size` | POST_CODE: total tests; PRE_CODE: `0` |
| `coverage_gaps` | Spec claims not grounded in code |
| `logs_summary` | POST_CODE: final heal cycle; PRE_CODE: empty |
| `drift_report` | POST_CODE vs Phase-1 snapshot when `phase_bridge_data` exists |
| `metadata` | POST_CODE: `security_posture`, pytest paths, …; mode-specific extras |

**Generated pytest (POST_CODE only):** `Backend/workspace/runs/run_<utc>/test_sentinel_api_generated.py` (gitignored).

**Phase bridge:** `Backend/phase_bridge_data/` — PRE_CODE snapshots for drift on the next POST_CODE run.

---

## Shared state (`ProjectState`)

Defined in [`Backend/state/project_state.py`](Backend/state/project_state.py).

Key fields: `user_story`, `acceptance_criteria`, `surface_map`, `test_suite`, `design_contracts`, `security_checklist`, `coverage_gaps`, `logs`, `suggested_patches`, `heal_attempts`, `metadata`.

Each **`TestCase`** includes `action`, `input_data`, `expected_status_code`, `source_refs`, `test_category`, optional `workflow_steps`, and adversarial fields (`payload`, `owasp_category`, `bound_method`, `bound_path`, …).

Each **`ExecutionLog`** includes `status`, `verdict` (`resilient` / `vulnerable` / `off_target` / `inconclusive` / `n/a`), and legacy `passed` / `is_vulnerable` for dashboards.

---

## Repository layout

```
HPE Project/
├── README.md
├── sentinel-qa-architecture.md        # Architecture reference
├── docs/
│   └── design-notes/
│       └── idor-path-template-tests.md
├── outputs/                           # Run artifacts (gitignored)
├── frontend/                          # React 19 reviewer UI
│   ├── src/
│   │   ├── api/                       # TanStack Query hooks + Zod schemas
│   │   ├── components/
│   │   │   ├── charts/                # OwaspBarChart, ResilienceGauge
│   │   │   ├── report/                # FindingsTable, SuggestedPatchesPanel, …
│   │   │   └── workspace/tabs/        # InputTab, SurfaceMapTab, ScenariosTab, …
│   │   ├── hooks/                     # useAutoPipelineNavigation, …
│   │   ├── stores/                    # Zustand (uiStore, runStreamStore)
│   │   └── lib/                       # exportReport, theme, cn
│   ├── public/SentinalQA-logo.jpeg
│   └── package.json
└── Backend/
    ├── main.py                        # LangGraph entry + artifact dump (CLI)
    ├── run_shim.py                    # FastAPI shim entry (for frontend)
    ├── bootstrap.py                   # CHROMA_HOME / HF cache setup
    ├── .env.example
    ├── requirements.txt
    ├── pyproject.toml                 # ruff + pytest
    ├── shim/                          # FastAPI REST + WebSocket shim
    │   ├── app.py                     # Route definitions
    │   ├── artifact.py                # Artifact enrichment (posture, attestation)
    │   └── README.md
    ├── agents/
    │   ├── critic.py
    │   ├── surface_resolver.py
    │   ├── generator.py
    │   ├── security_compiler.py
    │   ├── executor.py
    │   ├── pytest_runner.py
    │   ├── suite_summary.py           # Categorized rollup for artifacts
    │   └── templates/pytest_api.jinja2
    ├── state/                         # Pydantic models (ProjectState, TestCase, …)
    ├── database/                      # ingest, vector_store, ast_chunker, reranker
    ├── samples/
    │   ├── sample_stories.py          # CLI story registry
    │   └── mentor_requirements/       # Mentor FR/NFR category stories
    ├── tools/sast_scan.py             # Bandit sidecar (POST_CODE)
    ├── utils/                         # llm, payloads, boundaries, placeholders
    ├── phase_bridge/                  # Phase-1 snapshots + drift_report
    ├── shim_data/sentinel.db          # SQLite run/artifact store (gitignored)
    ├── repo_cache/                    # App under test (local only, gitignored)
    ├── tests/                         # Unit tests
    ├── workspace/                     # Generated pytest runs (gitignored)
    └── chroma_data/                   # Vector DB (gitignored)
```

---

## Development

### Lint and test

From `Backend/`:

```bash
ruff check .
pytest
```

CI (`.github/workflows/ci.yml`): **ruff** on `main`, then **pytest** with cached pip/HF models.

### Logging

`SENTINEL_LOG_LEVEL` (e.g. `INFO`, `WARNING`). Pipeline uses `logging` with timestamps in `main.py`.

---

## Known limitations

| Area | Status |
|------|--------|
| **IDOR / two-user fixtures** | `perms` may report `INSUFFICIENT` — path templates need peer task seeding. Design: [`docs/design-notes/idor-path-template-tests.md`](docs/design-notes/idor-path-template-tests.md). |
| **Pinpoint line citations** | Range buckets (`schemas.py:50-86`) are reliable; single-line refs in LLM prose may drift ±few lines. |
| **Heal loop cost** | Retries Generator; cap `max_heal_attempts` and compiler size for demos. |
| **Resilience %** | Excludes skipped/errored adversarial tests from denominator — read `errored` in posture. |
| **Unclassified adversarial tests** | ADV tests with no `attestation_mode` stamp are excluded from resilience % and flagged amber in the UI — fix by ensuring Surface Resolver runs before Generator. |
| **Features absent in app** | `org`, `ratelimit`, `taskshare` often yield honest empty or thin suites — by design. |
| **CLI vs shim artifact enrichment** | `security_posture` and `attestation_mode` are fully populated via the shim path (`run_shim.py`). CLI `main.py` dumps a simpler artifact without shim enrichment. |

---

## Security note

Payloads in `utils/payloads.py` are **canonical test strings** for authorized security evaluation in isolated environments. Do not point Sentinel at production systems without scope and approval.

---

## License / attribution

HPE internship / academic project context. Smart Task Manager sample app is populated locally under `Backend/repo_cache/` (gitignored).
