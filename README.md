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

Files in `observability/otel-collector/`:
- `base.yaml`: receivers, processors, self-metrics, health check.
- `exporters.<name>.yaml`: one file per destination (`debug`, `prometheus`; more later).
- `render_config.py`: run once by the `otel-config` container; reads the `EXPORT_*` flags below and writes the Collector's routing (`exporters:` + one pipeline per signal) containing **only the enabled destinations**.

#### Turning destinations on and off

Every available destination is **on by default**, so `make up` shows the whole platform working at once. To stop sending to one, flip its flag in `.env` and reload; nothing else changes and the app is never touched:

```
EXPORT_PROMETHEUS=false   # in .env
make collector-reload     # re-renders routing, restarts only the Collector
make routes               # shows where each signal now goes
```

| Flag | Receives | Default |
|---|---|---|
| `EXPORT_DEBUG` | all signals (printed in the Collector log) | on |
| `EXPORT_PROMETHEUS` | metrics (scrape endpoint `:8889`) | on |
| `EXPORT_ELASTICSEARCH` / `EXPORT_DATADOG` | logs, traces / all | later phases |

A signal with every destination off still gets a valid (no-op) pipeline. To add a destination: add `exporters.<name>.yaml`, one row in `render_config.py`, one flag in `docker-compose.yml`.

### 3. The data: backends that store and show it

Not every backend gets every signal; each gets what it's good at:

| Signal | Prometheus | Elasticsearch | Datadog (optional) |
|---|---|---|---|
| Metrics | ✅ | – | ✅ |
| Logs | – | ✅ | ✅ |
| Traces | – | ✅ | ✅ |

Grafana stores nothing: it queries Prometheus and Elasticsearch. Kibana is Elasticsearch's own UI. Trace IDs in logs let you jump from a log line to its trace.

### Dashboards (Grafana → "Observability Platform" folder)
- **Application Performance**: request rate, 5xx rate, p50/p95/p99 latency, slowest routes, DB query time, cache hit ratio, external API calls.
- **Background Processing**: Celery queue depth, success ratio, failures, duration by task.
- **Infrastructure Health**: host CPU/memory/load/network (Collector `hostmetrics`; this is the Docker *host*, not per-container usage) plus the telemetry pipeline's own health: what the Collector receives, what each exporter sends, export failures.

Dashboards are files (`observability/grafana/dashboards/*.json`) and read-only in the UI; change the JSON, not the screen.

### Where this build is today

| Part | Status |
|---|---|
| App + Postgres + Redis + Celery | ✅ built |
| App instrumentation (metrics, logs, traces) | ✅ built, verified end-to-end |
| Collector | ✅ flag-driven routing, self-metrics, health endpoint |
| Prometheus | ✅ scraping the Collector; 6 alert rules (`observability/prometheus/rules`) at http://127.0.0.1:9090 |
| Grafana | ✅ http://127.0.0.1:3000 (user `admin`, password = `GF_SECURITY_ADMIN_PASSWORD` in `.env`). Prometheus data source, 3 dashboards, 2 alert rules, all provisioned from `observability/grafana/` |
| ELK / Datadog | ⏳ later phases (logs and traces currently go to the debug exporter only; Grafana's log/trace drill-down arrives with Elasticsearch) |

See what the Collector receives: `docker compose logs -f otel-collector`.
Full span detail: `DEBUG_EXPORTER_VERBOSITY=detailed docker compose up -d otel-collector`.

## Repository layout
- `app/` – Django demo application (no backend-specific code)
- `observability/` – Collector, Prometheus and Grafana config (Elastic, Datadog to come)
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
