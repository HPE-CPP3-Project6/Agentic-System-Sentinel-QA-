# Sentinel-QA API Shim

FastAPI service that wraps the LangGraph pipeline for the React frontend.

## Run

From `Backend/` (with venv active and deps installed):

```bash
pip install fastapi uvicorn python-multipart
python run_shim.py
```

`run_shim.py` enables reload for **shim source only** (`Backend/shim/`). Pipeline output under `Backend/workspace/` does not trigger a restart.

Shim listens on **http://localhost:8080** (target app under test stays on `:8000`).

## Frontend

```bash
cd ../frontend
# .env: VITE_USE_MSW=false
npm run dev
```

Vite proxies `/api` and `/ws` → `:8080`.

## Endpoints

See [`sentinel-qa-architecture.md`](../sentinel-qa-architecture.md) §D–§E.

## Storage

- SQLite: `Backend/shim_data/sentinel.db`
- Run workspaces: `Backend/workspace/runs/<run_id>/`

## Staged pipeline

| Step | API call | `stop_after` |
|------|----------|--------------|
| Resolve surface | `POST /api/stories/{id}/runs` | `surface_resolver` |
| Generate tests | `POST /api/runs/{id}/advance` | `compiler` |
| Execute | `POST /api/runs/{id}/advance` | `null` |

Overrides and scenario edits apply while run `status=paused`.
