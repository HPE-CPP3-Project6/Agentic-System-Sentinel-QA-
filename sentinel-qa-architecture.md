# Sentinel-QA — Frontend & API Architecture

Single-tenant internal tool. SPA + thin FastAPI shim over the existing LangGraph CLI.

---

## A. Executive Summary

We are building a React SPA backed by a thin, stateless FastAPI service that wraps the existing CLI pipeline by invoking it as a subprocess and streaming its progress. The frontend's job is to drive the five-agent pipeline through a staged golden path (Resolve Surface → Generate → Execute → Report) and render the single `ProjectState` artifact so an HPE reviewer understands the release decision in seconds. The architecture is deliberately conservative: the CLI is untouched, the API holds no business logic it doesn't have to, and the SPA matches the React+Vite stack of the apps the pipeline tests. It is HPE-credible because the two screens reviewers will scrutinize map cleanly onto tools they already trust — the **Surface Map** is a modern requirement→test→result traceability matrix (the ALM/Quality Center mental model), and the **Security Posture** dashboard groups verdicts into OWASP buckets with severity ranking and drill-down (the Fortify mental model), without cloning either's dated UI.

## B. Tech Stack

| Layer | Choice | Justification (2 sentences) |
|---|---|---|
| Framework | **React 18 + Vite** | Matches the target apps under test, so reviewers see one stack. Vite's lazy chunking keeps the initial bundle under the 500 KB budget. |
| Language | **TypeScript** | `ProjectState` is ~40 fields with discriminated unions (`suite_quality`, `threat_class`, `defense_kind`); TS turns the artifact contract into compile-time guarantees and catches schema drift before it reaches a reviewer. The pipeline's own enums are the strongest argument for typing. |
| Server state | **TanStack Query** | Stories, runs, artifacts, and history are all server-owned async resources with caching, polling, and invalidation needs — exactly Query's job. |
| Client state | **Zustand** | The genuine client state (theme, active run id, WS connection status, high-frequency live-log buffer, surface-override drafts) is small and ephemeral; Zustand carries it without RTK's reducer/middleware ceremony. Chosen over Redux Toolkit because there is no complex shared mutation graph to justify the boilerplate. |
| UI | **shadcn/ui + Tailwind** | Copy-in components give a Linear-class, non-generic aesthetic we fully own, with no Material-UI "existing-HPE-tool" vibe. |
| Charts | **Recharts** | Declarative composition ships the standard pie/bar/sparkline set fast; Visx's low-level control is unnecessary for this fixed chart vocabulary. |
| Code highlight | **Shiki** | TextMate grammars + VS Code themes render the generated pytest identically to the engineer's own editor, which matters for trust; it's async, so we lazy-load it on the Scripts surface. |
| WebSocket | **Native WebSocket API** | One long-lived connection per run; no rooms, fallbacks, or multiplexing that would justify Socket.io. |
| Build | **Vite** | Same as framework rationale; route-level `React.lazy` for Scripts (Shiki), Reports (Recharts), and export keeps the entry bundle lean. |

## C. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser — React SPA (Vite, SPA, no SSR)                           │
│  TanStack Query (REST)            Zustand (UI + live buffers)       │
└───────────┬──────────────────────────────┬────────────────────────┘
            │ HTTPS REST                     │ WSS  /ws/runs/{id}
            ▼                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  FastAPI shim  (thin, stateless logic; owns a RunRegistry + queue) │
│   • /api/stories, /api/runs   • WS broadcaster   • export workers  │
└───────────┬───────────────────────────────┬───────────────────────┘
            │ subprocess + stdout pipe        │ reads
            ▼                                 ▼
┌───────────────────────────┐      ┌──────────────────────────────┐
│ LangGraph CLI              │ ───▶ │ pytest workspace             │
│ python main.py --mode ...  │      │ test_sentinel_api_*.py        │
│ Critic→Surface→Gen→        │      │ ProjectState JSON → outputs/  │
│ Compiler→Executor(+Healer) │      └───────────────┬──────────────┘
└───────────────────────────┘                       │ HTTP test calls
                                                      ▼
                                          ┌────────────────────────┐
                                          │ Target app under test   │
                                          │ (live FastAPI) + Chroma │
                                          └────────────────────────┘
```

The shim writes story payloads and override files to a per-run workspace dir, spawns the CLI with `--mode`/`--stop-after` flags, tails stdout to parse phase + pytest events into the WS stream, and serves the finished `outputs/*.json` as the artifact. State persistence is a single SQLite file (stories, runs, history) — adequate for single-tenant.

## D. HTTP API Contract

Base `/api`. Errors use `{ "error": { "code": "...", "message": "...", "detail": {} } }` with the codes in Section J. All 4xx/5xx share that shape.

| Method | Path | Request body | Success response | Errors |
|---|---|---|---|---|
| POST | `/stories` | `{title, body, acceptance_criteria[]}` | `201 {story}` | `422 validation_failed` |
| GET | `/stories` | — | `200 {stories[]}` | — |
| GET | `/stories/{id}` | — | `200 {story}` | `404 not_found` |
| POST | `/stories/bulk` | `multipart` CSV/JSON | `201 {created[], rejected[]}` | `422 bulk_parse_failed` |
| PATCH | `/stories/{id}` | partial story | `200 {story}` | `404`, `422`, `409 run_in_progress` |
| POST | `/stories/{id}/runs` | `{mode:"pre_code"\|"post_code", stop_after:"surface_resolver"\|"compiler"\|null}` | `202 {run_id, status:"queued"}` | `404`, `409 run_in_progress` |
| POST | `/runs/{run_id}/advance` | `{stop_after:"compiler"\|null}` | `202 {run_id, status:"queued"}` | `404`, `409 not_paused` |
| GET | `/runs/{run_id}` | — | `200 {run_id, status, current_phase, phases[], partial_artifact}` | `404` |
| GET | `/runs/{run_id}/artifact` | — | `200 {ProjectState}` | `404`, `409 run_not_complete` |
| GET | `/runs/{run_id}/script` | `?format=py\|json` | `200` (py: `text/x-python`) | `404`, `409 script_not_ready` |
| PATCH | `/runs/{run_id}/surface-overrides` | `{overrides:{REQ-ID:{state?,threat_class?,defense_kind?,backend_endpoints?}}}` | `200 {surface_map}` | `404`, `409 not_paused`, `422` |
| PATCH | `/runs/{run_id}/test-cases/{tc_id}` | `{action?,expected_status_code?,forbidden_response_content?}` | `200 {test_case}` | `404`, `409 not_paused` |
| POST | `/runs/{run_id}/patches/{patch_id}/decision` | `{decision:"accept"\|"reject"}` | `200 {patch}` | `404`, `409 run_not_complete` |
| GET | `/stories/{id}/runs` | — | `200 {runs[{run_id, started_at, suite_quality, resilience_pct}]}` | `404` |
| GET | `/runs/{run_id}/export` | `?format=pdf\|xlsx` | `200` (binary) | `404`, `409`, `503 export_failed` |
| WS | `/ws/runs/{run_id}` | — | event stream (Section E) | close `4404` unknown run |
| GET | `/health` | — | `200 {chroma_ok, target_app_ok, queue_depth}` | — |

**Refinements over Section 3.** Added `stop_after` + `POST /advance` so one run object spans the staged golden path (Resolve → Generate → Execute) instead of three disconnected runs — overrides and scenario edits are applied to a *paused* run, then resumed. Added `PATCH /test-cases/{tc_id}` for the required inline scenario edit, `POST /patches/{id}/decision` for the Healer accept/reject step, and `/health` to drive the Chroma/target-app error banners pre-flight.

## E. WebSocket Event Protocol

One connection per run. Every event shares an envelope; `seq` is monotonic per run so a client can resume after reconnect via `?after_seq=N`.

```jsonc
// envelope: { type, run_id, seq, ts, ...payload }

{ "type":"phase_started","run_id":"r_8f","seq":12,"ts":"2026-05-29T10:01:02Z",
  "phase":"surface_resolver","index":2,"total":5 }

{ "type":"phase_completed","run_id":"r_8f","seq":40,"ts":"...",
  "phase":"surface_resolver","duration_ms":18044,
  "summary":{"BACKEND_API":2,"NOT_IMPLEMENTED":3} }

{ "type":"pytest_stdout","run_id":"r_8f","seq":91,"ts":"...",
  "stream":"stdout","line":"tests/test_..._generated.py::TC-REQ-001-01 PASSED" }

{ "type":"verdict_decided","run_id":"r_8f","seq":104,"ts":"...",
  "test_id":"TC-REQ-001-01","status":"passed","verdict":"resilient",
  "verdict_confidence":"high","duration_ms":142,"exploit_target":"A04:2021" }

{ "type":"heal_cycle_started","run_id":"r_8f","seq":150,"ts":"...",
  "attempt":1,"failing_test_ids":["TC-REQ-003-02"] }

{ "type":"heal_cycle_completed","run_id":"r_8f","seq":171,"ts":"...",
  "attempt":1,"patches_proposed":1,"retriggered_generator":true }

{ "type":"run_paused","run_id":"r_8f","seq":42,"ts":"...",
  "stopped_after":"surface_resolver" }   // staged-path checkpoint

{ "type":"run_completed","run_id":"r_8f","seq":230,"ts":"...",
  "suite_quality":"ATTESTABLE","resilience_pct":100.0 }

{ "type":"run_failed","run_id":"r_8f","seq":58,"ts":"...",
  "code":"pytest_timeout","phase":"executor","message":"..." }
```

The SPA reduces `verdict_decided` events into the early-results table live, buffers `pytest_stdout` into the console, and on `run_completed` invalidates the run's TanStack Query so the full artifact is fetched once over REST (the WS never carries the 40-field artifact).

## F. Frontend Component Tree

```
App
├─ QueryClientProvider
├─ ThemeProvider (dark default)
└─ AppShell
   ├─ Sidebar  (Stories | Scenarios | Scripts | Results | Reports | SurfaceMap)
   ├─ Topbar   (RunStatusPill, ThemeToggle, CommandPalette ⌘K)
   └─ <Routes>
      ├─ StoriesPage
      │   ├─ StoryList
      │   ├─ StoryEditor (RichTextBody, ACList, FormatValidator)
      │   └─ BulkUploadDropzone (CSV/JSON/text)
      ├─ SurfaceMapPage  ★ differentiator
      │   ├─ ResolveSurfaceButton
      │   ├─ SurfaceMapGrid → SurfaceBindingCard[]
      │   │     (StateBadge, ThreatClassTag, DefenseKindTag,
      │   │      GroundingRefs, OverrideButton)
      │   └─ SurfaceOverrideModal
      ├─ ScenariosPage
      │   ├─ GenerateTestsButton
      │   ├─ ScenarioTable (sortable, expandable rows)
      │   └─ ScenarioRowEditor (inline action/status/forbidden_content)
      ├─ ScriptsPage
      │   └─ CodePanel (Shiki) + DownloadPy + CopyButton
      ├─ ResultsPage  (live execution)
      │   ├─ ExecuteButton
      │   ├─ PhaseTracker (5 agents, elapsed-time chips)
      │   ├─ LiveLog (monospace, auto-scroll, pause-on-hover, collapse-per-phase)
      │   ├─ EarlyResultsTable (status+verdict+confidence+duration)
      │   └─ PatchInbox (accept/reject)
      └─ ReportsPage
          ├─ PostureDashboard (SuiteQualityBadge, ResilienceGauge,
          │    PostureCards, OwaspGroupedBar, DriftSparkline)
          ├─ RunHistoryTable
          └─ ExportMenu (PDF / Excel)
```

## G. State-Management Map

| Entity | Lives in | Mutated by |
|---|---|---|
| Story | TanStack Query cache (`['story',id]`) | StoryEditor, BulkUpload mutations → invalidate `['stories']` |
| Run status + phases | Query (`['run',id]`); polling fallback if WS drops | Server; WS `phase_*`/`run_*` events patch the cached object |
| Live log buffer | Zustand (transient, ring-buffered) | WS `pytest_stdout` reducer; cleared on run change |
| Early verdicts | Zustand (transient) until `run_completed` | WS `verdict_decided`; replaced by artifact on completion |
| Full Artifact (ProjectState) | Query (`['run',id,'artifact']`) | Fetched once on `run_completed`; never mutated client-side |
| SurfaceBinding override draft | Zustand (`overrideDraft`) | OverrideModal; committed via PATCH → invalidates `['run',id]` |
| Scenario edits | Zustand draft → PATCH `/test-cases` | ScenarioRowEditor; invalidates run |
| Patch decisions | Optimistic in Query; POST `/decision` | PatchInbox |
| Theme, WS connection state, active run id | Zustand (UI slice) | Topbar, WS hook |
| Active tab, selected scenario, filters | URL search params (router) | Navigation; shareable/back-button-safe |

Principle: anything a reviewer might bookmark or share lives in the URL; anything server-owned lives in Query; only ephemeral, high-frequency, or in-flight-draft data lives in Zustand.

## H. Key Screen Wireframes

**(i) Story editor + bulk upload**
```
┌ Stories ────────────────────────────────────────────────┐
│ Title  [ Task Search                                  ]   │
│ Story  ┌───────────────────────────────────────────┐    │
│        │ As a user I want to search tasks…          │    │
│        └───────────────────────────────────────────┘    │
│ Acceptance Criteria (1 / line)                            │
│        ┌───────────────────────────────────────────┐    │
│        │ Given … When … Then …                      │    │
│        └───────────────────────────────────────────┘    │
│ ┌ drag-drop CSV / JSON / text ─────────────────────┐    │
│ │   ⤓  Drop files or click to upload                │    │
│ └───────────────────────────────────────────────────┘   │
│ ✓ 3 ACs · ✓ title set            [ Resolve Surface → ]   │
└──────────────────────────────────────────────────────────┘
```

**(ii) Surface Map — the differentiator (traceability matrix)**
```
┌ Surface Map · SEARCH-001 ──────────── [ Re-resolve ]  ────┐
│ ┌ REQ-001 ───────────────── BACKEND_API ───────────────┐  │
│ │ "no length limit on email"                            │  │
│ │ threat: DEFENSIVE_INVERTED   defense: INPUT_REJECTION │  │
│ │ assert: POST /register → 422 when email>255; no trace │  │
│ │ bind:  POST /register  routers/auth_router.py:27      │  │
│ │ grounding: auth_router.py:27-58   conf: ● high        │  │
│ │                                  [ Override binding ] │  │
│ └───────────────────────────────────────────────────────┘ │
│ ┌ REQ-002 ───────────── NOT_IMPLEMENTED ── ⚠ gap ───────┐  │
│ │ no backend surface found · excluded from suite        │  │
│ │                                  [ Override binding ] │  │
│ └───────────────────────────────────────────────────────┘ │
│ Bindings: BACKEND_API 2 · NOT_IMPLEMENTED 3   [ Generate→]│
└──────────────────────────────────────────────────────────┘
```

**(iii) Live execution view**
```
┌ Results · run r_8f ───────────────────────────────────────┐
│ Critic✓2s ─ Surface✓18s ─ Generator✓9s ─ Compiler✓3s ─ ▶Executor │
│ ┌ console ─ pytest ─────────────────── [pause] [collapse]┐│
│ │ TC-REQ-001-01 PASSED                                   ││
│ │ TC-REQ-003-02 FAILED  → heal attempt 1…                ││
│ │ ▌                                          (auto-scroll)││
│ └────────────────────────────────────────────────────────┘│
│ Test            Status   Verdict     Conf   ms             │
│ TC-REQ-001-01   passed   resilient   high   142            │
│ TC-REQ-003-02   failed   vulnerable  high   88   [patch?]  │
└──────────────────────────────────────────────────────────┘
```

**(iv) Post-run summary dashboard**
```
┌ Reports · SEARCH-001 / r_8f ──────────────────────────────┐
│ ┌ Quality Gate ┐ ┌ Resilience ┐ ┌ Coverage ──────────────┐│
│ │ ● ATTESTABLE │ │   ◔ 100%   │ │ 9 tests · 0 off-target ││
│ │   Trusted    │ │  gauge     │ │ 8 attempted · 8 resil. ││
│ └──────────────┘ └────────────┘ └────────────────────────┘│
│ OWASP by exploit target          Resilience (recent runs) │
│ A01 ▇▇▇  A03 ▇▇▇▇▇  A04 ▇▇       ╱‾‾╲__╱‾   ▁▂▅▇▇         │
│ [ Export PDF ]  [ Export Excel ]                          │
└──────────────────────────────────────────────────────────┘
```

**(v) Surface Map override modal (operational hot-patch)**
```
┌ Override REQ-002 ─────────────────────────── ✕ ───┐
│ State        [ NOT_IMPLEMENTED ▾ ] → [ BACKEND_API ▾ ]│
│ Threat class [ NON_FUNCTIONAL ▾ ] → [ DEFENSIVE_NORMAL ▾ ]│
│ Defense kind [ — ▾ ]              → [ INPUT_REJECTION ▾ ] │
│ Endpoint     method [POST▾] path [ /tasks/search   ]   │
│ ⚠ Override applies to this paused run only; re-run    │
│   to regenerate tests against the new binding.         │
│              [ Cancel ]            [ Apply & continue ]│
└────────────────────────────────────────────────────────┘
```

## I. suite_quality Badge Language

Traffic-light + SonarQube "quality gate" vocabulary. Color, label, sub-copy:

| Enum | Color | Badge label | Sub-copy |
|---|---|---|---|
| `ATTESTABLE` | green | **Trusted** | Suite ran with meaningful coverage. |
| `INSUFFICIENT` | amber | **Caution** | Coverage below floor; metrics may mislead. |
| `PROXY_HEAVY` | amber | **Degraded** | Over 30% of tests landed off-target; bindings are suspect. |
| `NO_RISKS_PREDICTED` | grey-amber | **Review** | Critic predicted no OWASP exposure; nothing to attest. |
| `ALL_SKIPPED` | grey | **Inconclusive** | Every test skipped; nothing executed. |
| `NO_TESTS_GENERATED` | red | **Blocked** | Generator produced no tests; pipeline cannot attest. |

Only `ATTESTABLE` reads as a passed gate; everything else is explicitly *not* a green light, which is the release-gate honesty HPE reviewers expect.

## J. Error-State Catalog

| Code | Cause | UI treatment |
|---|---|---|
| `chroma_empty` | RAG index missing/empty at resolve time | Blocking banner on Surface Map: "No code index — Surface Resolver cannot ground requirements." Link to re-index; `/health` shows it pre-flight. |
| `target_app_unreachable` | Live app down at execute | Block Execute button; topbar pill turns red with retry. |
| `llm_rate_limited` | Provider 429 | Toast + auto-retry-with-backoff indicator on PhaseTracker; phase chip shows "retrying". |
| `llm_invocation_failed` | Non-retryable LLM error | `run_failed` event → PhaseTracker marks phase red, inline cause, "Restart from phase". |
| `pytest_timeout` | Executor exceeded wall clock | LiveLog freezes with red footer; partial verdicts kept; suite_quality forced `INSUFFICIENT`. |
| `pytest_crash` | Non-zero collection error / import failure | Console shows captured traceback in a collapsed red group; offer raw-log download. |
| `phase_bridge_error` | Malformed handoff between agents | Generic "Pipeline internal error at <phase>"; surface run_id + seq for backend triage. |
| `surface_map_empty` | Resolver bound nothing | Empty-state card on Surface Map: "No surfaces resolved — every REQ is NOT_IMPLEMENTED or NEEDS_CLARIFICATION." Suggest override before generating. |
| `bulk_parse_failed` | Bad CSV/JSON upload | Per-row rejection list inline in the dropzone; accepted rows still created. |
| `export_failed` | PDF/XLSX worker error | Non-blocking toast; other exports still available. |

## K. Extensibility Notes (Optional 6–8)

The run model and the artifact renderer are the stable core; the optional features bolt on around them.

**(6) Projects / versioning.** Add a `projects` table and nest existing routes under `/api/projects/{pid}/stories`; the SPA gains a project switcher in the Topbar. Stories already key everything, so the Surface Map, Scenario, and Reports surfaces are unchanged. Run history already exists per story, so story versioning is a `version` column plus a diff view — no renderer changes.

**(7) Collaboration / RBAC.** Insert auth middleware that attaches a role claim (mentor/student/tester) to the request; gate mutating endpoints server-side and hide their buttons client-side via a `useRole` hook. Comments are an additive `/api/runs/{id}/comments` resource rendered in a sidebar; notifications reuse the existing WS connection with a new `notification` event type.

**(8) CI/CD integrations.** Add an inbound `POST /api/webhooks/{provider}` receiver that creates a run, and an outbound post-run hook (fired on `run_completed`) that pushes `suggested_patches` to a repo or posts the quality gate to Jenkins/GitHub Actions. Both are pipeline-adjacent and touch neither the SPA core nor the artifact schema.

Because every feature extends the existing `Story → Run → Artifact` spine rather than reshaping it, none requires re-architecting the SPA, the state map, or the API's core run lifecycle.
