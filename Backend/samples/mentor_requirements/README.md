# Mentor requirement stories (FR / NFR)

User stories derived from the mentor **Smart Task Manager** requirements document.
Each file is one **category** — run it through Sentinel-QA independently to measure
coverage per FR/NFR section.

## Prerequisites

```powershell
cd Backend
# Target app + Chroma index (repo_cache is local-only, not in git)
python -m database.ingest repo_cache --reset
# Uvicorn on :8000, .env with SENTINEL_BASE_URL and SENTINEL_TEST_BEARER_TOKEN
```

## Run one category

```powershell
python main.py --mode post_code req-fr-filter
python main.py --mode post_code req-nfr-security
```

Artifacts land in `outputs/exec-demo-<key>-post_code-<timestamp>.json`.

## Functional requirements (11 stories)

| CLI key | Story ID | Section |
|---------|----------|---------|
| `req-fr-user-mgmt` | REQ-FR-01 | §1.1 User Management (FR 1–5) |
| `req-fr-task-create` | REQ-FR-02 | §1.2 Task Creation (FR 6–10) |
| `req-fr-task-validate` | REQ-FR-03 | §1.3 Task Validation (FR 11–15) |
| `req-fr-task-view` | REQ-FR-04 | §1.4 Task Viewing (FR 16–18) |
| `req-fr-task-edit` | REQ-FR-05 | §1.5 Task Editing (FR 19–23) |
| `req-fr-task-complete` | REQ-FR-06 | §1.6 Task Completion (FR 24–26) |
| `req-fr-task-delete` | REQ-FR-07 | §1.7 Task Deletion (FR 27–29) |
| `req-fr-filter` | REQ-FR-08 | §1.8 Filtering (FR 30–34) |
| `req-fr-sort` | REQ-FR-09 | §1.9 Sorting (FR 35–38) |
| `req-fr-search` | REQ-FR-10 | §1.10 Search (FR 39–41) |
| `req-fr-persist` | REQ-FR-11 | §1.11 Persistence (FR 42–44) |

## Non-functional requirements (8 stories)

| CLI key | Story ID | Section |
|---------|----------|---------|
| `req-nfr-usability` | REQ-NFR-01 | §2.1 Usability (NFR 1–3) |
| `req-nfr-performance` | REQ-NFR-02 | §2.2 Performance (NFR 4–5) |
| `req-nfr-reliability` | REQ-NFR-03 | §2.3 Reliability (NFR 6–7) |
| `req-nfr-security` | REQ-NFR-04 | §2.4 Security (NFR 8–10) |
| `req-nfr-maintainability` | REQ-NFR-05 | §2.5 Maintainability (NFR 11–13) |
| `req-nfr-portability` | REQ-NFR-06 | §2.6 Portability (NFR 14–15) |
| `req-nfr-compatibility` | REQ-NFR-07 | §2.7 Compatibility (NFR 16–17) |
| `req-nfr-constraints` | REQ-NFR-08 | §2.8 Constraints (NFR 18–20) |

## Batch all functional categories (PowerShell)

```powershell
@(
  "req-fr-user-mgmt","req-fr-task-create","req-fr-task-validate",
  "req-fr-task-view","req-fr-task-edit","req-fr-task-complete",
  "req-fr-task-delete","req-fr-filter","req-fr-sort",
  "req-fr-search","req-fr-persist"
) | ForEach-Object { python main.py --mode post_code $_ }
```

## Expectations

- **API-heavy categories** (`req-fr-filter`, `req-fr-task-validate`, `req-nfr-security`) usually produce the richest pytest suites.
- **UI / perf / docs categories** often yield honest `coverage_gaps` — that is correct behavior, not failure.
- Overlap with legacy demo keys (`lifecycle`, `login`, `search`, `validation`) is intentional; mentor keys align 1:1 with the assignment FR/NFR table.

## File layout

```
mentor_requirements/
  fr_*.py          # one file per functional section
  nfr_*.py         # one file per non-functional section
  registry.py      # CLI key → story registry
  README.md        # this file
```

Edit acceptance criteria in the matching `fr_*.py` / `nfr_*.py` file, not in `registry.py`.
