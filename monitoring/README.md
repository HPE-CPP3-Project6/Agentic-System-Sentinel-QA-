# Sentinel-QA Monitoring (Prometheus + Grafana)

A small, self-contained local monitoring stack (Option A). Only Prometheus and
Grafana run in Docker; the Sentinel-QA shim itself runs on the **host** at
`:8080` and is scraped over `host.docker.internal`. No cloud, no external egress.

## Prerequisites

1. Docker Desktop (or Docker Engine + Compose v2).
2. The Sentinel-QA shim running on the host and exposing `/metrics`:

   ```bash
   cd ../Backend
   ./venv/Scripts/python.exe -m uvicorn shim.app:app --port 8080     # Windows
   # curl http://localhost:8080/metrics   -> should list http_* and sentinel_* series
   ```

## Start / stop

```bash
cd monitoring
docker compose up -d      # start Prometheus + Grafana
docker compose down       # stop (add -v to also wipe stored data)
```

## What you get

| Service    | URL                       | Notes                                   |
|------------|---------------------------|-----------------------------------------|
| Prometheus | http://localhost:9090     | Status → Targets: `sentinel-shim` = UP  |
| Grafana    | http://localhost:3000     | login `admin` / `admin`                 |

The **Sentinel-QA** dashboard is auto-provisioned (Dashboards → Sentinel-QA):
run rate by status, runs-in-progress, run-duration p50/p95, per-node p95,
verdict breakdown, last-run resilience %, LLM latency/throughput, and an
estimated **$/hour** panel (set your blended per-1K-token price via the
`Blended $ / 1K tokens` variable at the top of the dashboard).

## Alerts

Prometheus rules live in [`prometheus/alerts.yml`](prometheus/alerts.yml) and
appear under Prometheus → Alerts:

- **TargetAppDown** — the shim is unreachable for >1m (critical).
- **HighRunFailureRate** — >25% of runs failing over 10m (warning).
- **SlowRun** — p95 run duration >10m (warning).

> These rules only *fire* in Prometheus. To route them to Slack/email/PagerDuty,
> add an Alertmanager service and a `alerting:` block in `prometheus.yml`.

## Verifying alerting works

Stop the shim while the stack is up; within ~1m **TargetAppDown** flips to
`FIRING` in Prometheus → Alerts. Restart the shim and it resolves.
