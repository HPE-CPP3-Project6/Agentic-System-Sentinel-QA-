# Sentinel-QA Cloud Run — Phase 1 Runbook

Manual operations to stand up the Phase-1 sidecar Cloud Run Job and run one end-to-end demo. Phase 2 (Cloud Build trigger on commit) replaces the manual `gcloud run jobs execute` step.

---

## What you get after this runbook

A Cloud Run Job named `sentinel-qa-runner` that, on each invocation:
1. Spins up the Phase-1 sidecar container (Sentinel + Smart Task Manager)
2. Runs the full Critic → Generator → Security+Compiler → Executor pipeline
3. Uploads `exec-demo.json`, the generated pytest file, and `container.log` to `gs://<bucket>/runs/<run-id>/`
4. Emits the front-door URI `gs://<bucket>/runs/<run-id>/index.json` to Cloud Logging

One run takes ~7–12 minutes and costs ~$0.10–0.30 (Vertex dominates).

---

## Conventions

Replace these placeholders in every command:

| Placeholder | Example | Notes |
|---|---|---|
| `${PROJECT_ID}` | `hpe-sentinel-qa-prod` | Your GCP project |
| `${REGION}` | `us-central1` | **Use the same region as Vertex AI** (default `us-central1`) |
| `${REPO_NAME}` | `sentinel` | Artifact Registry repository |
| `${IMAGE}` | `sentinel-qa` | Image name within the repo |
| `${TAG}` | `v1` or commit SHA | Image tag |
| `${BUCKET_NAME}` | `${PROJECT_ID}-sentinel-runs` | Globally unique GCS bucket |
| `${SA_NAME}` | `sentinel-qa-runner` | Service-account local name |
| `${SA_EMAIL}` | derived | `${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com` |

---

## Step 0 — Local prerequisites (one-time, ~10 min)

```bash
# 1. Install gcloud (if not already): https://cloud.google.com/sdk/docs/install
gcloud --version

# 2. Authenticate
gcloud auth login
gcloud auth application-default login

# 3. Pin defaults so the rest of the runbook doesn't need --project/--region flags
gcloud config set project ${PROJECT_ID}
gcloud config set run/region ${REGION}
gcloud config set artifacts/location ${REGION}

# 4. Local Docker (needed to build + push the image once)
docker --version
```

---

## Step 1 — Enable APIs (one-time, ~2 min)

```bash
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    aiplatform.googleapis.com \
    storage.googleapis.com \
    secretmanager.googleapis.com \
    logging.googleapis.com \
    iamcredentials.googleapis.com
```

---

## Step 2 — Service account + IAM (one-time, ~3 min)

The Job runs as a dedicated SA with minimum privilege.

```bash
# Create the SA
gcloud iam service-accounts create ${SA_NAME} \
    --display-name="Sentinel-QA Cloud Run Job runner"

export SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Grant exactly what the Job needs
for ROLE in \
    roles/aiplatform.user \
    roles/storage.objectAdmin \
    roles/artifactregistry.reader \
    roles/secretmanager.secretAccessor \
    roles/logging.logWriter
do
    gcloud projects add-iam-policy-binding ${PROJECT_ID} \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="${ROLE}"
done
```

**Why each role:**
| Role | Used by |
|---|---|
| `aiplatform.user` | Vertex AI / Gemini calls from Critic, Generator, Healer |
| `storage.objectAdmin` | `publish_results.py` writes artifacts to GCS |
| `artifactregistry.reader` | Cloud Run pulls the container image |
| `secretmanager.secretAccessor` | Phase-3 readiness (Bearer tokens, GitHub PAT) |
| `logging.logWriter` | Structured logs from inside the container |

---

## Step 3 — Artifact Registry + GCS bucket (one-time, ~2 min)

```bash
# Artifact Registry — holds the container image
gcloud artifacts repositories create ${REPO_NAME} \
    --repository-format=docker \
    --location=${REGION} \
    --description="Sentinel-QA images"

# GCS bucket — holds run artifacts
gcloud storage buckets create gs://${BUCKET_NAME} \
    --location=${REGION} \
    --uniform-bucket-level-access \
    --public-access-prevention

# Lifecycle: auto-delete runs older than 30 days (cost hygiene)
cat > /tmp/lifecycle.json <<EOF
{
  "rule": [{
    "action": {"type": "Delete"},
    "condition": {"age": 30, "matchesPrefix": ["runs/"]}
  }]
}
EOF
gcloud storage buckets update gs://${BUCKET_NAME} \
    --lifecycle-file=/tmp/lifecycle.json
```

---

## Step 4 — Build and push the image (one-time + on every code change, ~8 min)

```bash
# Authenticate Docker to Artifact Registry
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# Build from REPO ROOT (Dockerfile expects this context)
cd "/path/to/HPE Project"

export FULL_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE}:${TAG}"
docker build -f Backend/Dockerfile -t "${FULL_IMAGE}" .

# Push
docker push "${FULL_IMAGE}"
```

**Phase 2 swap:** This step gets replaced by a Cloud Build trigger watching the GitHub repo — `gcloud builds submit` runs automatically on push.

---

## Step 5 — Create the Cloud Run Job (one-time, ~2 min)

```bash
gcloud run jobs create sentinel-qa-runner \
    --image="${FULL_IMAGE}" \
    --region=${REGION} \
    --service-account="${SA_EMAIL}" \
    --cpu=2 \
    --memory=4Gi \
    --task-timeout=1800s \
    --max-retries=0 \
    --set-env-vars="\
VERTEX_AI_PROJECT_ID=${PROJECT_ID},\
VERTEX_AI_LOCATION=${REGION},\
SENTINEL_LLM_MODEL=gemini-2.5-flash,\
SENTINEL_GCS_BUCKET=${BUCKET_NAME},\
SENTINEL_STORY_KEY=taskshare,\
SENTINEL_MODE=post_code,\
SENTINEL_RAG_MODE=standard"
```

**Resource sizing rationale:**
- **2 vCPU / 4 GiB:** Jina embeddings need ~2 GiB headroom; Gemini calls are I/O-bound, 1 extra vCPU keeps pytest subprocess fluid
- **30 min timeout:** generous — typical run is 7–12 min; healing on a stuck target could push toward 20
- **0 retries:** failed runs are observable; auto-retry burns Vertex tokens on the same broken state

---

## Step 6 — Execute one run

```bash
# Default: runs the 'taskshare' story in POST_CODE mode
gcloud run jobs execute sentinel-qa-runner --region=${REGION} --wait

# Override per-run (different story / different mode)
gcloud run jobs execute sentinel-qa-runner \
    --region=${REGION} \
    --update-env-vars="SENTINEL_STORY_KEY=login,SENTINEL_MODE=post_code,SENTINEL_RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)" \
    --wait

# Tail the live execution logs
gcloud run jobs executions list \
    --job=sentinel-qa-runner --region=${REGION} --limit=1
# (grab EXECUTION_NAME from the output)
gcloud logging read \
    "resource.type=cloud_run_job AND resource.labels.job_name=sentinel-qa-runner" \
    --limit=200 --format='value(textPayload)'
```

---

## Step 7 — Read the artifact

```bash
# The entrypoint's last log line is the index URI; or list directly:
gcloud storage ls gs://${BUCKET_NAME}/runs/

# Read the headline metrics for a specific run
gcloud storage cat gs://${BUCKET_NAME}/runs/<RUN_ID>/index.json | jq .headline
# {
#   "story_id": "...",
#   "patches_proposed": 2,                  ← the demo metric
#   "security_posture": { ... },
#   "logs_summary": { ... }
# }

# Download the full bundle locally
gcloud storage cp -r gs://${BUCKET_NAME}/runs/<RUN_ID> ./local-inspect/
```

---

## Cost guardrails — enable on day one

```bash
# Vertex AI budget alert at 50 / 80 / 100% of monthly cap
# (set via Console: Billing → Budgets & alerts → Create budget)
#   Scope: project=${PROJECT_ID}, services=Vertex AI API
#   Threshold rules: 50%, 80%, 100%
#   Notification: email + Pub/Sub

# Cloud Run per-job timeout already capped at 1800s in Step 5 (--task-timeout)
# Sentinel's max_heal_attempts is 2 (state default) — caps Vertex spend per run

# Optional: container-level memory cap (kills runaway runs)
# Already set via --memory=4Gi above
```

**Single-run cost ceiling math:**
- Gemini 2.5 Flash @ ~$0.075 / 1M input tokens, ~$0.30 / 1M output
- Heaviest run observed: ~150K input + ~80K output across 4 nodes + 2 heal cycles
- Cost ceiling: **≤ $0.05** per pipeline run for LLM
- Add Cloud Run Job compute (~$0.02 / 12 min @ 2 vCPU) → **~$0.07 / run worst-case**

---

## Common issues

| Symptom | Cause | Fix |
|---|---|---|
| `Permission denied on Vertex AI` | SA missing `roles/aiplatform.user` | Re-run Step 2 IAM bindings |
| `404 Artifact Registry pull failed` | Wrong region in image URI | Match `--region` between push and Cloud Run Job |
| Job exits with code 11 (`setup_target.py did not emit JWT`) | Target uvicorn never reached `/health`; usually `repo_cache` import error | `gcloud logging read` for the uvicorn stderr lines (banner shows lifecycle step) |
| `403 on /register` | Target app changed and rejects unknown email | Override `SENTINEL_TEST_USER_EMAIL` env to a known account |
| Vertex `429 ResourceExhausted` | Quota limit | `gcloud alpha services quota update`; or use `--region` with more headroom |
| `index.json` missing | Pipeline succeeded but publish failed | Check container log lines after `=== [5/5] publishing` — usually a bucket-permission issue |
| Image is huge (>5 GB) | `.dockerignore` not picked up | Build from repo root, NOT from `Backend/` |

---

## Phase 2 hooks (do not run yet — future)

- Cloud Build trigger watching the Smart Task Manager repo (replaces Step 4 + Step 6)
- Per-PR Cloud Run revision tags (replaces single-Job-for-all model)
- GitHub status check posted from a final entrypoint step (`gh pr comment` or REST)
- Workload Identity Federation for GitHub Actions → kills the last residual `gcloud auth`

---

## Tear-down (if you need to start over)

```bash
gcloud run jobs delete sentinel-qa-runner --region=${REGION} --quiet
gcloud artifacts repositories delete ${REPO_NAME} --location=${REGION} --quiet
gcloud storage rm -r gs://${BUCKET_NAME}
gcloud iam service-accounts delete ${SA_EMAIL} --quiet
```

(Project + APIs you can leave enabled; they cost nothing while idle.)
