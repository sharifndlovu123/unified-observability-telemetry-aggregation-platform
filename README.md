# Unified Observability & Telemetry Aggregation Platform

A hands-on learning project: one instrumented Django app, one OpenTelemetry Collector, many observability backends (Prometheus, Grafana, ELK, optional Datadog).

**Core idea:** instrument once, collect centrally, distribute wherever required.

## Docs
- [`spec.md`](spec.md) – requirements and acceptance criteria
- [`TECHNICAL_SPEC.md`](TECHNICAL_SPEC.md) – design decisions, config contracts, verification plan
- [`CLAUDE.md`](CLAUDE.md) – guidance for Claude Code

## Status
Phase 1 done: Django app + Postgres + Redis + Celery worker/beat under Docker Compose (no telemetry yet).
Next: Phase 2 (OpenTelemetry instrumentation). Phases are described in `TECHNICAL_SPEC.md` §12.

## Layout
- `app/` – Django demo application (no backend-specific code)
- `observability/` – Collector, Prometheus, Grafana, Elastic, Datadog config (empty so far)
- `scenarios/` – load generator and (later) reproducible failure demos
- `docs/` – architecture, deployment, troubleshooting, limitations

## Getting started
```
cp .env.example .env    # set POSTGRES_PASSWORD and other secrets
make up                 # build and start everything, waits for healthchecks
make demo-user          # user "demo" / "demo-pass"
make test               # pytest inside the django container
make load               # 60s of mixed API traffic
```
API on http://127.0.0.1:8000 (`/healthz`, `/readyz`, `/api/assets/`, `/api/workorders/`, `/api/reports/`, `/api/external/rates/`).
Celery Beat emits baseline activity (heartbeat, synthetic load, stale sweep) even with no traffic.
