from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

from agents import (
    critic_node,
    executor_node,
    generator_node,
    needs_healing,
    security_compiler_node,
    surface_resolver_node,
)
from bootstrap import configure_caches
from config import get_settings
from database.vector_store import DEFAULT_PERSIST_DIR
from metrics import (
    NODE_DURATION,
    RESILIENCE_PCT,
    RUN_DURATION,
    RUN_FAILURES_TOTAL,
    RUNS_IN_PROGRESS,
    RUNS_TOTAL,
    VERDICTS_TOTAL,
)
from obs import set_run_id
from phase_bridge import generate_drift_report, load_phase1, save_phase1
from shim.artifact import state_to_artifact
from shim.store import RunRow, Store, StoryRow
from shim.ws_hub import WsHub
from state import ProjectState

configure_caches()

NODE_ORDER = ["critic", "surface_resolver", "generator", "security_compiler", "executor"]
NODE_FUNCS: dict[str, Callable[[ProjectState], ProjectState]] = {
    "critic": critic_node,
    "surface_resolver": surface_resolver_node,
    "generator": generator_node,
    "security_compiler": security_compiler_node,
    "executor": executor_node,
}

# API stop_after "compiler" maps to security_compiler node
STOP_AFTER_ALIASES = {"compiler": "security_compiler"}


def _coerce_state(state: ProjectState | dict) -> ProjectState:
    if isinstance(state, ProjectState):
        return state
    return ProjectState.model_validate(state)


def _resolve_stop(stop_after: str | None) -> str | None:
    if not stop_after:
        return None
    return STOP_AFTER_ALIASES.get(stop_after, stop_after)


def _initial_state(story: StoryRow, mode: str) -> ProjectState:
    state = ProjectState(
        user_story=story.body,
        story_title=story.title,
        story_id=story.id,
        acceptance_criteria=list(story.acceptance_criteria),
        module="api",
        pipeline_mode=mode.upper(),
    )
    max_heal = get_settings().sentinel_max_heal
    if max_heal is not None:
        try:
            state.max_heal_attempts = max(0, int(max_heal))
        except ValueError:
            pass
    return state


def _state_path(run: RunRow) -> Path:
    return Path(run.workspace_dir) / "state.json"


def _artifact_path(run: RunRow) -> Path:
    return Path(run.workspace_dir) / "artifact.json"


def _script_path(run: RunRow) -> Path:
    ws = Path(run.workspace_dir)
    candidates = list(ws.glob("test_sentinel_api_generated.py"))
    if candidates:
        return candidates[0]
    state = load_state(run)
    if state:
        generated = state.metadata.get("security_compiler_generated_files") or []
        for raw in reversed(generated):
            path = Path(str(raw))
            if path.is_file():
                return path
        compiler_dir = state.metadata.get("security_compiler_run_dir")
        if compiler_dir:
            path = Path(str(compiler_dir)) / "test_sentinel_api_generated.py"
            if path.is_file():
                return path
    return ws / "test_sentinel_api_generated.py"


def load_state(run: RunRow) -> ProjectState | None:
    path = _state_path(run)
    if not path.exists():
        return None
    try:
        return ProjectState.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError, ValueError):
        # Transient: worker mid-write / os.replace window. The next poll
        # (1.5s) will read the committed file. Degrade to "no partial yet"
        # rather than 500 the status endpoint.
        return None


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + os.replace so a concurrent reader (e.g. a 1.5s
    status poll calling load_state) never sees a half-written file. Without
    this, the worker thread writing state.json mid-poll caused intermittent
    json.JSONDecodeError → 500 on GET /api/runs/{id}, which read as a UI
    'integration broke mid-run' glitch."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save_state(run: RunRow, state: ProjectState) -> None:
    _atomic_write(_state_path(run), state.model_dump_json(indent=2))


def save_artifact(run: RunRow, state: ProjectState) -> Path:
    payload = state_to_artifact(state)
    path = _artifact_path(run)
    _atomic_write(path, json.dumps(payload, indent=2, default=str))
    return path


def _nodes_from_resume(resume_from: str | None) -> list[str]:
    if not resume_from:
        return list(NODE_ORDER)
    if resume_from not in NODE_ORDER:
        return list(NODE_ORDER)
    idx = NODE_ORDER.index(resume_from)
    return NODE_ORDER[idx:]


def _next_node_after(stop_after: str) -> str:
    stop = _resolve_stop(stop_after) or stop_after
    idx = NODE_ORDER.index(stop)
    return NODE_ORDER[idx + 1]


def _run_executor_with_heal(state: ProjectState, hub: WsHub, run_id: str) -> ProjectState:
    while True:
        hub.emit(run_id, "phase_started", phase="executor", index=5, total=5)
        t0 = time.time()
        state = _coerce_state(executor_node(state))
        NODE_DURATION.labels(node="executor").observe(time.time() - t0)
        hub.emit(
            run_id,
            "phase_completed",
            phase="executor",
            duration_ms=int((time.time() - t0) * 1000),
        )
        stdout_tail = state.metadata.get("executor_pytest_stdout_tail") or ""
        for line in stdout_tail.splitlines()[-200:]:
            if line.strip():
                hub.emit(run_id, "pytest_stdout", stream="stdout", line=line)
        for log in state.logs[-50:]:
            hub.emit(
                run_id,
                "verdict_decided",
                test_id=log.test_id,
                status=log.status,
                verdict=getattr(log, "verdict", "n/a"),
                verdict_confidence=getattr(log, "verdict_confidence", "low"),
                duration_ms=log.duration_ms,
                exploit_target=log.exploit_target,
            )
        if needs_healing(state) == "heal" and state.heal_attempts < state.max_heal_attempts:
            hub.emit(
                run_id,
                "heal_cycle_started",
                attempt=state.heal_attempts,
                failing_test_ids=[l.test_id for l in state.logs if l.status == "failed"][:10],
            )
            for phase in ("generator", "security_compiler"):
                hub.emit(run_id, "phase_started", phase=phase, index=NODE_ORDER.index(phase) + 1, total=5)
                t1 = time.time()
                state = _coerce_state(NODE_FUNCS[phase](state))
                NODE_DURATION.labels(node=phase).observe(time.time() - t1)
                hub.emit(
                    run_id,
                    "phase_completed",
                    phase=phase,
                    duration_ms=int((time.time() - t1) * 1000),
                )
            hub.emit(run_id, "heal_cycle_completed", attempt=state.heal_attempts, patches_proposed=len(state.suggested_patches))
            continue
        break
    return state


def _finalize_post_code(state: ProjectState) -> ProjectState:
    try:
        phase1 = load_phase1(state.story_id or "unknown")
        if phase1:
            drift = generate_drift_report(phase1, state)
            state.metadata["drift_report"] = drift
        else:
            seed_path = save_phase1(state)
            state.metadata["drift_report"] = {
                "skipped": "seeded from POST_CODE; rerun for drift",
                "seeded_snapshot_path": seed_path,
            }
    except Exception as exc:
        state.metadata["phase_bridge_error"] = f"{type(exc).__name__}: {exc}"

    if get_settings().sentinel_sast:
        try:
            from tools.sast_scan import run_sast_scan

            target_root = Path(__file__).resolve().parent.parent / "repo_cache"
            state.metadata["sast_summary"] = run_sast_scan(target_root)
        except Exception as exc:
            state.metadata["sast_summary"] = {"tool": "bandit", "ran": False, "reason": str(exc)}
    return state


def _finalize_pre_code(state: ProjectState) -> ProjectState:
    try:
        path = save_phase1(state)
        state.metadata["phase_bridge_saved_to"] = path
    except Exception as exc:
        state.metadata["phase_bridge_error"] = f"{type(exc).__name__}: {exc}"
    return state


def _classify_run_error(exc: Exception) -> str:
    """Map a pipeline exception to a stable error code for the UI.

    Previously every failure was stamped "phase_bridge_error", which made an
    LLM auth failure, a Chroma failure, and a real phase-bridge failure look
    identical in the frontend.
    """
    try:
        from utils import LLMInvocationError

        if isinstance(exc, LLMInvocationError):
            return "llm_error"
    except ImportError:
        pass
    name = type(exc).__name__
    text = str(exc).lower()
    if "credential" in text or "permission" in text or "403" in text or "auth" in text:
        return "llm_auth_error"
    if "chroma" in text or "chroma" in name.lower():
        return "index_error"
    if isinstance(exc, (OSError, json.JSONDecodeError)):
        return "io_error"
    return "pipeline_error"


def execute_run(store: Store, hub: WsHub, run_id: str) -> None:
    set_run_id(run_id)  # correlation id for every log line from this worker thread
    run = store.get_run(run_id)
    if not run:
        return
    story = store.get_story(run.story_id)
    if not story:
        store.update_run(run_id, status="failed", error_code="not_found", error_message="Story missing")
        return

    store.update_run(run_id, status="running")
    RUNS_IN_PROGRESS.inc()
    run_t0 = time.time()
    try:
        state = load_state(run) or _initial_state(story, run.mode)
        stop = _resolve_stop(run.stop_after)
        nodes = _nodes_from_resume(run.resume_from)

        for i, phase in enumerate(nodes):
            if phase == "executor":
                if stop and stop != "executor":
                    break
                state = _run_executor_with_heal(state, hub, run_id)
                break

            hub.emit(run_id, "phase_started", phase=phase, index=i + 1, total=len(NODE_ORDER))
            store.update_run(run_id, current_phase=phase)
            t0 = time.time()
            state = _coerce_state(NODE_FUNCS[phase](state))
            summary = {}
            if phase == "surface_resolver" and state.surface_map:
                for binding in state.surface_map.values():
                    key = binding.state
                    summary[key] = summary.get(key, 0) + 1
            NODE_DURATION.labels(node=phase).observe(time.time() - t0)
            hub.emit(
                run_id,
                "phase_completed",
                phase=phase,
                duration_ms=int((time.time() - t0) * 1000),
                summary=summary or None,
            )
            save_state(run, state)

            if stop and phase == stop:
                store.update_run(run_id, status="paused", current_phase=phase)
                hub.emit(run_id, "run_paused", stopped_after=phase)
                return

        if run.mode.lower() == "pre_code":
            state = _finalize_pre_code(state)
        else:
            state = _finalize_post_code(state)

        artifact = save_artifact(run, state)
        save_state(run, state)
        art = state_to_artifact(state)
        posture = state.metadata.get("security_posture") or {}
        final_phase = (
            "security_compiler" if run.mode.lower() == "pre_code" else "executor"
        )
        store.update_run(
            run_id,
            status="completed",
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            artifact_path=str(artifact),
            suite_quality=art.get("coverage_quality") or art.get("suite_quality"),
            run_validity=art.get("run_validity"),
            resilience_pct=posture.get("resilience_pct"),
            current_phase=final_phase,
            # Workspace files are gitignored and die with the folder; the DB
            # copy keeps completed reports readable after a re-clone.
            artifact_json=json.dumps(art, default=str),
        )
        hub.emit(
            run_id,
            "run_completed",
            pipeline_mode=run.mode,
            run_validity=art.get("run_validity", "OK"),
            suite_quality=art.get("coverage_quality") or art.get("suite_quality"),
            resilience_pct=posture.get("resilience_pct"),
        )
        RUNS_TOTAL.labels(mode=run.mode, status="completed").inc()
        RUN_DURATION.labels(mode=run.mode).observe(time.time() - run_t0)
        if posture.get("resilience_pct") is not None:
            RESILIENCE_PCT.set(posture["resilience_pct"])
        for log in state.logs:
            VERDICTS_TOTAL.labels(verdict=getattr(log, "verdict", "n/a") or "n/a").inc()
    except Exception as exc:
        code = _classify_run_error(exc)
        message = f"{type(exc).__name__}: {exc}"
        store.update_run(
            run_id,
            status="failed",
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error_code=code,
            error_message=message,
        )
        hub.emit(
            run_id,
            "run_failed",
            code=code,
            phase=run.current_phase or "critic",
            message=message,
        )
        RUNS_TOTAL.labels(mode=run.mode, status="failed").inc()
        RUN_FAILURES_TOTAL.labels(error_code=code).inc()
    finally:
        RUNS_IN_PROGRESS.dec()


def check_chroma_ok() -> bool:
    """Lightweight check — avoid loading embedding models on /health."""
    try:
        p = Path(DEFAULT_PERSIST_DIR)
        return p.is_dir() and any(p.iterdir())
    except Exception:
        return False


def check_target_app_ok() -> bool:
    import httpx

    base = get_settings().sentinel_base_url.rstrip("/")
    try:
        r = httpx.get(f"{base}/health", timeout=3.0)
        return r.status_code < 500
    except Exception:
        return False
