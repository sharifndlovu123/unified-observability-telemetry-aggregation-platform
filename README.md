# Unified Observability & Telemetry Aggregation Platform

A hands-on learning project: one instrumented Django app, one OpenTelemetry Collector, many observability backends (Prometheus, Grafana, ELK, optional Datadog).

**Core idea: instrument once, collect centrally, distribute wherever required.**

## Architecture: App → Collector → Data

OpenTelemetry (OTel) splits observability into three independent parts. Each can change without touching the others.

```
┌──────────────────────┐      ┌───────────────────────┐      ┌─────────────────────────┐
│ 1. APP               │      │ 2. COLLECTOR          │      │ 3. DATA (backends)      │
│ produces telemetry   │ OTLP │ receives, processes,  │      │ stores & visualises     │
│                      │─────▶│ routes                │─────▶│                         │
│ Django · Celery      │ gRPC │                       │      │ Prometheus  (metrics)   │
│ + OTel SDK           │      │ otel-collector        │      │ Elasticsearch (logs,    │
│                      │      │                       │      │   traces) + Kibana      │
└──────────────────────┘      └───────────────────────┘      │ Datadog (all, optional) │
                                                             │ Grafana (reads the rest)│
                                                             └─────────────────────────┘
   knows ONE address            knows ALL destinations         knows nothing about the app
```

### 1. The app: produces telemetry (vendor-neutral)

`app/` is a Django "Operations Management Portal" plus Celery worker and beat. Three containers, three `service.name`s (`portal-django`, `portal-celery-worker`, `portal-celery-beat`).

The OTel SDK (`app/config/telemetry.py`) emits the three **signals**:

| Signal | What it answers | How it's produced here |
|---|---|---|
| **Metrics** | *How much / how fast, in aggregate?* | Auto: HTTP server/client duration, active requests. Custom (`app/portal/metrics.py`): cache hit/miss, Celery task outcomes and duration, DB query duration, queue depth, uptime. |
| **Logs** | *What happened, exactly?* | JSON to stdout **and** OTLP. Every line carries `trace_id` / `span_id`. Sensitive keys (password, token, ...) are redacted. |
| **Traces** | *Where did this one request spend its time?* | Auto-instrumented Django, PostgreSQL, Redis and `requests`. Trace context is propagated through the Celery queue, so one trace follows a request from the API into the background worker. |

The app's only telemetry configuration is `OTEL_EXPORTER_OTLP_ENDPOINT` (the Collector's address). It contains **no** Prometheus, Elastic or Datadog code. If the Collector is down, the SDK drops data in bounded buffers and requests keep working.

### 2. The collector: the gateway in the middle

`observability/otel-collector/` runs the OpenTelemetry Collector, the only thing the app talks to. Everything is a pipeline of **receivers → processors → exporters**, one independent pipeline per signal:

- **Receivers**: accept OTLP on `:4317` (gRPC) / `:4318` (HTTP).
- **Processors** (order matters): `memory_limiter` (first; protects the Collector) → `resource` (stamps `deployment.environment` on everything) → `batch` (last; fewer, bigger writes).
- **Exporters**: where data goes. Adding or removing a backend is a Collector config change, with **zero app changes**.

Files: `base.yaml` (receivers/processors/exporters definitions) and `pipelines.yaml` (which signal uses what), merged at startup with repeated `--config` flags.

### 3. The data: backends that store and show it

Not every backend gets every signal; each gets what it's good at:

| Signal | Prometheus | Elasticsearch | Datadog (optional) |
|---|---|---|---|
| Metrics | ✅ | – | ✅ |
| Logs | – | ✅ | ✅ |
| Traces | – | ✅ | ✅ |

Grafana stores nothing: it queries Prometheus and Elasticsearch. Kibana is Elasticsearch's own UI. Trace IDs in logs let you jump from a log line to its trace.

### Where this build is today

| Part | Status |
|---|---|
| App + Postgres + Redis + Celery | ✅ built |
| App instrumentation (metrics, logs, traces) | ✅ built, verified end-to-end |
| Collector | ✅ running, **debug exporter only** (prints what it receives) |
| Prometheus / Grafana / ELK / Datadog | ⏳ later phases |

See what the Collector receives: `docker compose logs -f otel-collector`.
Full span detail: `DEBUG_EXPORTER_VERBOSITY=detailed docker compose up -d otel-collector`.

## Repository layout
- `app/` – Django demo application (no backend-specific code)
- `observability/` – Collector, Prometheus, Grafana, Elastic, Datadog config (only the Collector so far)
- `scenarios/` – load generator and (later) reproducible failure demos
- `docs/` – architecture, deployment, troubleshooting, limitations

## Getting started
```
cp .env.example .env    # set POSTGRES_PASSWORD, DJANGO_SECRET_KEY and other secrets
make up                 # build and start everything, waits for healthchecks
make demo-user          # user "demo" / "demo-pass"
make test               # pytest inside the django container
make load               # 60s of mixed API traffic (generates telemetry)
```
API on http://127.0.0.1:8000 (`/healthz`, `/readyz`, `/api/assets/`, `/api/workorders/`, `/api/reports/`, `/api/external/rates/`).
Celery Beat emits baseline activity (heartbeat, synthetic load, stale sweep, one log record per severity) even with no traffic.

## Docs
- [`CLAUDE.md`](CLAUDE.md) – guidance for Claude Code
- Local planning docs (`spec.md`, `TECHNICAL_SPEC.md`) are git-ignored.
