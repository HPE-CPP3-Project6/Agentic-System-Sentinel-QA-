from __future__ import annotations

import csv
import io
import json
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from shim.errors import api_error
from shim.pipeline import (
    _artifact_path,
    _next_node_after,
    _resolve_stop,
    _script_path,
    check_chroma_ok,
    check_target_app_ok,
    execute_run,
    load_state,
    save_artifact,
    save_state,
)
from shim.store import Store
from shim.ws_hub import WsHub
from state import ProjectState, SurfaceBinding, TestCase

store = Store()
hub = WsHub()
_queue_depth = 0
_lock = threading.Lock()

app = FastAPI(title="Sentinel-QA API Shim", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StoryCreate(BaseModel):
    title: str
    body: str
    acceptance_criteria: list[str] = Field(min_length=1)


class StoryPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    acceptance_criteria: list[str] | None = None


class RunCreate(BaseModel):
    mode: str = "post_code"
    stop_after: str | None = None


class RunAdvance(BaseModel):
    stop_after: str | None = None


class SurfaceOverrides(BaseModel):
    overrides: dict[str, dict[str, Any]]


class TestCasePatch(BaseModel):
    action: str | None = None
    expected_status_code: int | None = None
    forbidden_response_content: list[str] | None = None


class PatchDecision(BaseModel):
    decision: str


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "http_error", "message": str(exc.detail), "detail": {}}},
    )


def _enqueue(run_id: str) -> None:
    global _queue_depth

    def _worker() -> None:
        global _queue_depth
        with _lock:
            _queue_depth += 1
        try:
            execute_run(store, hub, run_id)
        finally:
            with _lock:
                _queue_depth = max(0, _queue_depth - 1)

    threading.Thread(target=_worker, daemon=True).start()


def _partial_artifact(run_id: str) -> dict[str, Any] | None:
    run = store.get_run(run_id)
    if not run:
        return None
    state = load_state(run)
    if not state:
        return None
    from shim.artifact import state_to_artifact

    return state_to_artifact(state)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "chroma_ok": check_chroma_ok(),
        "target_app_ok": check_target_app_ok(),
        "queue_depth": _queue_depth,
    }


@app.get("/api/stories")
def list_stories() -> dict[str, Any]:
    return {"stories": [s.to_dict() for s in store.list_stories()]}


@app.post("/api/stories", status_code=201)
def create_story(payload: StoryCreate) -> dict[str, Any]:
    story = store.create_story(payload.title, payload.body, payload.acceptance_criteria)
    return {"story": story.to_dict()}


@app.get("/api/stories/{story_id}")
def get_story(story_id: str) -> dict[str, Any]:
    story = store.get_story(story_id)
    if not story:
        raise api_error(404, "not_found", "Story not found")
    return story.to_dict()


@app.patch("/api/stories/{story_id}")
def patch_story(story_id: str, payload: StoryPatch) -> dict[str, Any]:
    if store.story_has_active_run(story_id):
        raise api_error(409, "run_in_progress", "Story has an active run")
    story = store.update_story(
        story_id,
        title=payload.title,
        body=payload.body,
        acceptance_criteria=payload.acceptance_criteria,
    )
    if not story:
        raise api_error(404, "not_found", "Story not found")
    return story.to_dict()


@app.post("/api/stories/bulk", status_code=201)
async def bulk_stories(file: UploadFile = File(...)) -> dict[str, Any]:
    raw = await file.read()
    name = (file.filename or "").lower()
    created = []
    rejected = []

    try:
        if name.endswith(".json"):
            data = json.loads(raw.decode("utf-8"))
            items = data if isinstance(data, list) else data.get("stories", [])
            for i, item in enumerate(items):
                try:
                    story = store.create_story(
                        item["title"],
                        item.get("body", ""),
                        item.get("acceptance_criteria", []),
                    )
                    created.append(story.to_dict())
                except Exception as exc:
                    rejected.append({"row": i + 1, "reason": str(exc)})
        else:
            text = raw.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            for i, row in enumerate(reader, start=2):
                title = (row.get("title") or row.get("Title") or "").strip()
                body = (row.get("body") or row.get("story") or "").strip()
                ac_raw = row.get("acceptance_criteria") or row.get("acs") or ""
                acs = [a.strip() for a in ac_raw.split("|") if a.strip()]
                if not title or not acs:
                    rejected.append({"row": i, "reason": "title and acceptance_criteria required"})
                    continue
                story = store.create_story(title, body, acs)
                created.append(story.to_dict())
    except Exception as exc:
        raise api_error(422, "bulk_parse_failed", str(exc)) from exc

    return {"created": created, "rejected": rejected}


@app.post("/api/stories/{story_id}/runs", status_code=202)
def start_run(story_id: str, payload: RunCreate) -> dict[str, Any]:
    story = store.get_story(story_id)
    if not story:
        raise api_error(404, "not_found", "Story not found")
    if store.story_has_active_run(story_id):
        raise api_error(409, "run_in_progress", "Story already has a queued/running job")
    mode = payload.mode.lower()
    if mode not in ("pre_code", "post_code"):
        raise api_error(422, "validation_failed", "mode must be pre_code or post_code")
    stop = _resolve_stop(payload.stop_after)
    run = store.create_run(story_id, mode, stop, resume_from=None)
    _enqueue(run.run_id)
    return {"run_id": run.run_id, "status": "queued"}


@app.post("/api/runs/{run_id}/advance", status_code=202)
def advance_run(run_id: str, payload: RunAdvance) -> dict[str, Any]:
    run = store.get_run(run_id)
    if not run:
        raise api_error(404, "not_found", "Run not found")
    if run.status != "paused":
        raise api_error(409, "not_paused", "Run is not paused")
    stop = _resolve_stop(payload.stop_after)
    resume = _next_node_after(run.current_phase or "surface_resolver")
    store.update_run(
        run_id,
        status="queued",
        stop_after=stop,
        resume_from=resume,
        error_code=None,
        error_message=None,
    )
    _enqueue(run_id)
    return {"run_id": run_id, "status": "queued"}


def _phase_status(run, phase: str) -> str:
    order = ["critic", "surface_resolver", "generator", "security_compiler", "executor"]
    if phase not in order:
        return "pending"
    if run.status == "completed":
        return "completed"
    if run.status == "failed" and run.current_phase in order:
        failed_idx = order.index(run.current_phase)
        phase_idx = order.index(phase)
        if phase_idx < failed_idx:
            return "completed"
        if phase_idx == failed_idx:
            return "failed"
        return "pending"
    if run.status == "running" and run.current_phase == phase:
        return "running"
    if run.current_phase in order:
        cur_idx = order.index(run.current_phase)
        phase_idx = order.index(phase)
        if phase_idx < cur_idx:
            return "completed"
        if phase_idx == cur_idx and run.status == "paused":
            return "completed"
    return "pending"


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if not run:
        raise api_error(404, "not_found", "Run not found")
    phases = []
    partial = _partial_artifact(run_id)
    for phase in ["critic", "surface_resolver", "generator", "security_compiler", "executor"]:
        phases.append({"phase": phase, "status": _phase_status(run, phase)})
    return {
        "run_id": run.run_id,
        "status": run.status,
        "current_phase": run.current_phase,
        "stop_after": run.stop_after,
        "phases": phases,
        "partial_artifact": partial,
        "error_code": run.error_code,
        "error_message": run.error_message,
    }


@app.get("/api/runs/{run_id}/artifact")
def get_artifact(run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if not run:
        raise api_error(404, "not_found", "Run not found")
    if run.status not in ("paused", "completed"):
        raise api_error(409, "run_not_complete", "Run not paused or complete")
    path = _artifact_path(run)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    partial = _partial_artifact(run_id)
    if partial:
        return partial
    raise api_error(409, "run_not_complete", "Artifact not ready")


@app.get("/api/runs/{run_id}/script")
def get_script(run_id: str, format: str = "py") -> Response:
    run = store.get_run(run_id)
    if not run:
        raise api_error(404, "not_found", "Run not found")
    script = _script_path(run)
    if not script.exists():
        raise api_error(409, "script_not_ready", "Generated script not available yet")
    content = script.read_text(encoding="utf-8")
    if format == "json":
        return JSONResponse({"script": content})
    return PlainTextResponse(content, media_type="text/x-python")


@app.patch("/api/runs/{run_id}/surface-overrides")
def surface_overrides(run_id: str, payload: SurfaceOverrides) -> dict[str, Any]:
    run = store.get_run(run_id)
    if not run:
        raise api_error(404, "not_found", "Run not found")
    if run.status != "paused":
        raise api_error(409, "not_paused", "Overrides only apply to paused runs")
    state = load_state(run)
    if not state:
        raise api_error(409, "not_paused", "Run state missing")
    for req_id, patch in payload.overrides.items():
        existing = (state.surface_map or {}).get(req_id)
        base = existing.model_dump() if existing else {"requirement_id": req_id, "state": "BACKEND_API", "rationale": "", "confidence": "low"}
        base.update(patch)
        if "req_id" in patch and "requirement_id" not in patch:
            base["requirement_id"] = patch.get("req_id", req_id)
        state.surface_map[req_id] = SurfaceBinding.model_validate(base)
    save_state(run, state)
    save_artifact(run, state)
    return {"surface_map": {k: v.model_dump() for k, v in state.surface_map.items()}}


@app.patch("/api/runs/{run_id}/test-cases/{tc_id}")
def patch_test_case(run_id: str, tc_id: str, payload: TestCasePatch) -> dict[str, Any]:
    run = store.get_run(run_id)
    if not run:
        raise api_error(404, "not_found", "Run not found")
    if run.status != "paused":
        raise api_error(409, "not_paused", "Test edits only apply to paused runs")
    state = load_state(run)
    if not state:
        raise api_error(409, "not_paused", "Run state missing")
    tc = next((t for t in state.test_suite if t.test_id == tc_id), None)
    if not tc:
        raise api_error(404, "not_found", "Test case not found")
    if payload.action is not None:
        tc.action = payload.action
    if payload.expected_status_code is not None:
        tc.expected_status_code = payload.expected_status_code
    if payload.forbidden_response_content is not None:
        tc.forbidden_response_content = payload.forbidden_response_content
    save_state(run, state)
    save_artifact(run, state)
    return TestCase.model_validate(tc.model_dump()).model_dump()


@app.post("/api/runs/{run_id}/patches/{patch_id}/decision")
def patch_decision(run_id: str, patch_id: str, payload: PatchDecision) -> dict[str, Any]:
    run = store.get_run(run_id)
    if not run:
        raise api_error(404, "not_found", "Run not found")
    if run.status != "completed":
        raise api_error(409, "run_not_complete", "Patch decisions require a completed run")
    if payload.decision not in ("accept", "reject"):
        raise api_error(422, "validation_failed", "decision must be accept or reject")
    return {"patch_id": patch_id, "decision": payload.decision}


@app.get("/api/stories/{story_id}/runs")
def story_runs(story_id: str) -> dict[str, Any]:
    if not store.get_story(story_id):
        raise api_error(404, "not_found", "Story not found")
    runs = store.list_runs_for_story(story_id)
    return {"runs": [r.to_history_dict() for r in runs]}


@app.get("/api/runs/{run_id}/export")
def export_run(run_id: str, format: str = "pdf") -> Response:
    run = store.get_run(run_id)
    if not run:
        raise api_error(404, "not_found", "Run not found")
    if run.status != "completed":
        raise api_error(409, "run_not_complete", "Export requires completed run")
    raise api_error(503, "export_failed", f"{format} export worker not configured")


@app.websocket("/ws/runs/{run_id}")
async def ws_run(websocket: WebSocket, run_id: str) -> None:
    run = store.get_run(run_id)
    if not run:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    q = hub.subscribe(run_id)
    try:
        while True:
            event = await q.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        hub.unsubscribe(run_id, q)
