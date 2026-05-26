#!/usr/bin/env bash
# Sentinel-QA cloud entrypoint (Phase 1 — sidecar MVP).
#
# Lifecycle inside the container:
#   1. Boot the target app (uvicorn) in the background, bound to 127.0.0.1
#   2. Wait for /health, register a test user, capture the JWT  (setup_target.py)
#   3. Index the target source into Chroma so the Generator can ground tests
#   4. Run the full Sentinel-QA pipeline (main.py)
#   5. Publish artifacts to GCS                                  (publish_results.py)
#   6. Stop uvicorn, exit with the pipeline's status code
#
# Exit code is the PIPELINE's exit code — publish failures are visible in logs
# but do not mask the actual run outcome (the run still happened; the upload
# failed, which is observable and recoverable).
#
# Env contract (Cloud Run Job sets these; defaults are sidecar-MVP-friendly):
#   SENTINEL_APP_DIR            default: /app           (Backend/ inside image)
#   TARGET_APP_DIR              default: /app/repo_cache (Smart Task Manager src)
#   TARGET_PORT                 default: 8000
#   SENTINEL_BASE_URL           default: http://127.0.0.1:${TARGET_PORT}
#   SENTINEL_STORY_KEY          default: taskshare
#   SENTINEL_MODE               default: post_code
#   SENTINEL_RUN_ID             default: cloud-<UTC>   (override with commit SHA in CI)
#   SENTINEL_SKIP_INGEST        default: 0             (set to 1 when Chroma is cached)
#   SENTINEL_GCS_BUCKET         optional               (empty → publish runs dry-run)
#   CONTAINER_LOG               default: /tmp/container.log
#
#   Vertex AI auth: the Cloud Run Job's service account picks up ADC automatically.
#                   No GOOGLE_APPLICATION_CREDENTIALS needed in production.

set -euo pipefail

# --------------------------------------------------------------------------- #
# Defaults                                                                     #
# --------------------------------------------------------------------------- #
SENTINEL_APP_DIR="${SENTINEL_APP_DIR:-/app}"
TARGET_APP_DIR="${TARGET_APP_DIR:-/app/repo_cache}"
TARGET_PORT="${TARGET_PORT:-8000}"
export SENTINEL_BASE_URL="${SENTINEL_BASE_URL:-http://127.0.0.1:${TARGET_PORT}}"
export SENTINEL_STORY_KEY="${SENTINEL_STORY_KEY:-taskshare}"
export SENTINEL_MODE="${SENTINEL_MODE:-post_code}"
export SENTINEL_RUN_ID="${SENTINEL_RUN_ID:-cloud-$(date -u +%Y%m%dT%H%M%SZ)}"
SENTINEL_SKIP_INGEST="${SENTINEL_SKIP_INGEST:-0}"
CONTAINER_LOG="${CONTAINER_LOG:-/tmp/container.log}"

# Mirror every line to the container log file so publish_results.py can upload it.
# tee runs in a subshell; the script's stdout/stderr are redirected through it.
mkdir -p "$(dirname "$CONTAINER_LOG")"
exec > >(tee -a "$CONTAINER_LOG") 2>&1

# --------------------------------------------------------------------------- #
# Cleanup — always stop the background uvicorn on exit                         #
# --------------------------------------------------------------------------- #
UVICORN_PID=""
cleanup() {
    local code=$?
    echo "=== [entrypoint] cleanup (in-flight exit code: $code) ==="
    if [[ -n "$UVICORN_PID" ]] && kill -0 "$UVICORN_PID" 2>/dev/null; then
        echo "[entrypoint] stopping uvicorn (pid=$UVICORN_PID)"
        kill -TERM "$UVICORN_PID" 2>/dev/null || true
        # Give uvicorn 5s to flush before SIGKILL
        for _ in 1 2 3 4 5; do
            kill -0 "$UVICORN_PID" 2>/dev/null || break
            sleep 1
        done
        kill -KILL "$UVICORN_PID" 2>/dev/null || true
        wait "$UVICORN_PID" 2>/dev/null || true
    fi
    echo "=== [entrypoint] done (rc=$code) ==="
}
trap cleanup EXIT

# --------------------------------------------------------------------------- #
# Banner                                                                       #
# --------------------------------------------------------------------------- #
echo "=================================================================="
echo "Sentinel-QA cloud entrypoint"
echo "  run_id     : $SENTINEL_RUN_ID"
echo "  story      : $SENTINEL_STORY_KEY"
echo "  mode       : $SENTINEL_MODE"
echo "  target     : $TARGET_APP_DIR (port $TARGET_PORT)"
echo "  sentinel   : $SENTINEL_APP_DIR"
echo "  base_url   : $SENTINEL_BASE_URL"
echo "  bucket     : ${SENTINEL_GCS_BUCKET:-<unset → dry-run>}"
echo "  log        : $CONTAINER_LOG"
echo "=================================================================="

# --------------------------------------------------------------------------- #
# 1. Boot target app                                                           #
# --------------------------------------------------------------------------- #
echo
echo "=== [1/5] booting target app (uvicorn) ==="
if [[ ! -d "$TARGET_APP_DIR" ]]; then
    echo "FATAL: TARGET_APP_DIR=$TARGET_APP_DIR does not exist"
    exit 10
fi

# Force-rotate the target's JWT signing key per container run.
# repo_cache/config.py ships a hardcoded default SECRET_KEY ("CHANGE_ME_..."),
# which Pydantic-settings would otherwise pick up — meaning every run of the
# sidecar would issue JWTs signed with a key that's literally checked into
# every clone of this repo. Generating a fresh 128-char hex secret here
# means each container has a unique signing key the second uvicorn starts,
# and the SQLite DB is ephemeral anyway so JWT continuity across runs is
# not a feature.
if [[ -z "${SECRET_KEY:-}" ]]; then
    export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(64))')"
    echo "[entrypoint] generated fresh SECRET_KEY (128 hex chars) for this run"
else
    echo "[entrypoint] SECRET_KEY supplied via env — using it (NOT generating)"
fi

( cd "$TARGET_APP_DIR" && \
    python -m uvicorn main:app \
        --host 127.0.0.1 --port "$TARGET_PORT" \
        --log-level warning ) &
UVICORN_PID=$!
echo "[entrypoint] uvicorn started (pid=$UVICORN_PID)"

# --------------------------------------------------------------------------- #
# 2. Bootstrap test identity                                                   #
# --------------------------------------------------------------------------- #
echo
echo "=== [2/5] waiting for target + provisioning test identity ==="
cd "$SENTINEL_APP_DIR"

# CONTRACT: setup_target.py emits "SENTINEL_TEST_BEARER_TOKEN=<jwt>" as last stdout line.
# pipefail propagates a non-zero exit from setup_target.py up to here.
if ! JWT_LINE="$(python -m cloud.setup_target | tail -n 1)"; then
    echo "FATAL: setup_target.py exited non-zero — check stderr above for cause"
    exit 11
fi
if [[ "$JWT_LINE" != SENTINEL_TEST_BEARER_TOKEN=* ]]; then
    echo "FATAL: setup_target.py last line was not the JWT export pair"
    echo "       got: $JWT_LINE"
    exit 12
fi
export "$JWT_LINE"
echo "[entrypoint] JWT exported (token chars: $((${#JWT_LINE} - 31)))"

# --------------------------------------------------------------------------- #
# 3. Index target source into Chroma                                           #
# --------------------------------------------------------------------------- #
echo
echo "=== [3/5] indexing target source into Chroma ==="
if [[ "$SENTINEL_SKIP_INGEST" == "1" ]]; then
    echo "[entrypoint] SENTINEL_SKIP_INGEST=1 → reusing prior Chroma index"
else
    python -m database.ingest "$TARGET_APP_DIR" --reset
fi

# --------------------------------------------------------------------------- #
# 4. Run the Sentinel-QA pipeline                                              #
# --------------------------------------------------------------------------- #
echo
echo "=== [4/5] running Sentinel-QA pipeline (mode=$SENTINEL_MODE story=$SENTINEL_STORY_KEY) ==="
PIPELINE_RC=0
python main.py --mode "$SENTINEL_MODE" "$SENTINEL_STORY_KEY" || PIPELINE_RC=$?
echo "[entrypoint] pipeline exit code: $PIPELINE_RC"

# --------------------------------------------------------------------------- #
# 5. Publish artifacts                                                         #
# --------------------------------------------------------------------------- #
echo
echo "=== [5/5] publishing artifacts to GCS ==="
# Force a flush so container.log captures everything up to this moment.
sync || true
PUBLISH_RC=0
python -m cloud.publish_results --container-logs "$CONTAINER_LOG" || PUBLISH_RC=$?
echo "[entrypoint] publish exit code: $PUBLISH_RC"
if [[ "$PUBLISH_RC" -ne 0 ]]; then
    echo "[entrypoint] WARNING: publish failed (rc=$PUBLISH_RC). Pipeline run is unaffected."
fi

# Pipeline rc is the authoritative outcome; publish failures are observable
# but do not mask the actual demo result.
exit "$PIPELINE_RC"
