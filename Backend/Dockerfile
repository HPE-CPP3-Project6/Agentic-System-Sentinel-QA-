# syntax=docker/dockerfile:1.7
#
# Sentinel-QA — Phase 1 sidecar image.
# Bundles Sentinel-QA + the Smart Task Manager (target app) + uvicorn so a
# single Cloud Run Job invocation can boot the target, run the full pipeline,
# and upload artifacts — see cloud/entrypoint.sh for the lifecycle.
#
# Build (from REPO ROOT, not from Backend/):
#     docker build -f Backend/Dockerfile -t sentinel-qa:local .
#
# Smoke locally:
#     docker run --rm \
#         -e VERTEX_AI_PROJECT_ID=<your-project> \
#         -e VERTEX_AI_LOCATION=us-central1 \
#         -e SENTINEL_PUBLISH_DRY_RUN=1 \
#         -v ~/.config/gcloud:/home/sentinel/.config/gcloud:ro \
#         sentinel-qa:local
#
# Push to Artifact Registry (Phase 1 manual; Phase 2 via Cloud Build):
#     docker tag sentinel-qa:local <REGION>-docker.pkg.dev/<PROJECT>/sentinel/sentinel-qa:<sha>
#     docker push <REGION>-docker.pkg.dev/<PROJECT>/sentinel/sentinel-qa:<sha>

ARG PYTHON_VERSION=3.11

# =========================================================================== #
# Stage 1 — builder                                                            #
#   Install all Python deps (Sentinel + target) and pre-download the Jina      #
#   embedding model so cold-start does not pay the ~600 MB pull.               #
# =========================================================================== #
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Build tooling for the few wheels that compile from source on slim-bookworm
# (mostly C extensions in cryptography / bcrypt / ML deps).
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ git curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# --- Sentinel-QA deps (heavy: torch, transformers, chromadb, vertex) ------- #
COPY Backend/requirements.txt /tmp/sentinel-reqs.txt
RUN pip install -r /tmp/sentinel-reqs.txt

# --- Target app deps (FastAPI + SQLAlchemy + JWT + bcrypt) ----------------- #
# Installed AFTER Sentinel so target's strict pins (pydantic==2.11.3, etc.)
# win the resolver — Sentinel is compatible with those exact versions.
COPY Backend/repo_cache/requirements.txt /tmp/target-reqs.txt
RUN pip install -r /tmp/target-reqs.txt

# --- Pre-download Jina code embeddings model ------------------------------- #
# The four cache env vars match bootstrap.configure_caches() exactly so the
# runtime stage inherits the same paths and re-uses these baked files.
ENV CHROMA_HOME=/var/cache/sentinel \
    HF_HOME=/var/cache/sentinel \
    ONNXRUNTIME_CACHE_DIR=/var/cache/sentinel \
    SENTENCE_TRANSFORMERS_HOME=/var/cache/sentinel
RUN mkdir -p "$HF_HOME" && \
    python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('jinaai/jina-embeddings-v2-base-code', trust_remote_code=True)"

# =========================================================================== #
# Stage 2 — runtime                                                            #
#   Lean image: deps + cached model from builder, plus the application code.  #
# =========================================================================== #
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Container-fixed locations (entrypoint.sh respects these)
    SENTINEL_APP_DIR=/app/Backend \
    TARGET_APP_DIR=/app/Backend/repo_cache \
    CONTAINER_LOG=/tmp/container.log \
    # Cache env vars must match bootstrap.configure_caches keys exactly.
    # bootstrap uses os.environ.setdefault — preset values win, baked cache is reused.
    CHROMA_HOME=/var/cache/sentinel \
    HF_HOME=/var/cache/sentinel \
    ONNXRUNTIME_CACHE_DIR=/var/cache/sentinel \
    SENTENCE_TRANSFORMERS_HOME=/var/cache/sentinel \
    # Python finds Sentinel's top-level packages (agents/, state/, etc.)
    PYTHONPATH=/app/Backend

# Runtime-only OS libs:
#   git        — GitPython (used by github_sync)
#   libgomp1   — OpenMP runtime for torch / transformers numerics
#   curl       — useful for container debugging; tiny
#   ca-certs   — TLS to Vertex AI / GCS / HF
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates libgomp1 && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --uid 1000 --shell /bin/bash sentinel

# --- Copy installed Python deps from builder ------------------------------- #
# Hardcoded python3.11 path matches the PYTHON_VERSION ARG default. If you
# bump that ARG, also bump this path.
COPY --from=builder /usr/local/lib/python3.11/site-packages \
                    /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# --- Copy pre-downloaded model cache --------------------------------------- #
COPY --from=builder /var/cache/sentinel /var/cache/sentinel

# --- Copy application source (Sentinel + target) --------------------------- #
# .dockerignore excludes venv/, __pycache__, .git, outputs/, workspace/runs,
# chroma_models_cache, so the COPY stays tight.
COPY --chown=sentinel:sentinel Backend/ /app/Backend/

# --- Prepare writable runtime dirs ----------------------------------------- #
RUN mkdir -p /app/outputs /app/Backend/workspace /var/cache/sentinel && \
    touch "$CONTAINER_LOG" && \
    chown -R sentinel:sentinel /app /var/cache/sentinel "$CONTAINER_LOG" && \
    chmod +x /app/Backend/cloud/entrypoint.sh

WORKDIR /app/Backend
USER sentinel

# Cloud Run Jobs ignore EXPOSE but it documents the sidecar contract.
EXPOSE 8000

# entrypoint runs the full lifecycle and exits with the pipeline's status.
ENTRYPOINT ["/app/Backend/cloud/entrypoint.sh"]
