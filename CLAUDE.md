# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Phases 1-5, 7 and 8 done (docs in `docs/`; acceptance check `make verify`; `make init` creates `.env`): Django app, Postgres, Redis, Celery worker/beat, full OTel instrumentation (metrics, JSON logs with trace IDs, traces incl. Celery propagation), an `otel-collector` with flag-driven routing, Prometheus with alert rules, Grafana (provisioned dashboards + alert rules), and the Elastic stack (Elasticsearch, Logstash, Kibana). Datadog is deliberately postponed (user decision); do not build it unless asked. `spec.md` and `TECHNICAL_SPEC.md` are git-ignored local planning docs (may be absent on a fresh clone); they define scope and design decisions.

## Commands (also `make init`, `make verify`, `make scenario N=..`)

All via the Makefile: `make up` (build + start, waits on healthchecks), `make down`, `make logs`, `make demo-user`, `make test`, `make load`. Requires a `.env` copied from `.env.example` (`POSTGRES_PASSWORD` is mandatory).
Single test: `docker compose exec -T django pytest -q tests/test_api.py::test_asset_crud_and_cache`.
Model changes: generate migrations with the source mounted so the file lands on the host: `docker compose run --rm --no-deps -v "$PWD/app:/app" django python manage.py makemigrations portal`.
Gotchas: `redis`/`kombu`/`celery` pins in `app/requirements.txt` are interdependent; the django service must be in `DJANGO_ALLOWED_HOSTS` because the app calls its own `/stub/rates/` as the simulated external API.

## What is being built

A self-hosted (Docker Compose) reference implementation of centralised observability: a Django "Operations Management Portal" emits metrics, logs and traces via the OpenTelemetry SDK over OTLP (gRPC/HTTP) to a single OpenTelemetry Collector, which fans out to multiple backends. Guiding principle: **instrument once, collect centrally, distribute wherever required.**

## Architecture (big picture)

```
Django + Celery (OTel SDK) --OTLP--> otel-collector --+--> Prometheus  (metrics)
                                                      +--> Elasticsearch (logs, traces) <-- Logstash / Kibana
                                                      +--> Datadog (metrics/logs/traces, OPTIONAL)
                                                      +--> debug exporter
                                       Grafana reads from Prometheus + Elasticsearch
```

Planned compose services: django, postgres, redis, celery-worker, celery-beat, otel-collector, prometheus, grafana, elasticsearch, logstash, kibana, datadog-agent (optional).

## Design constraints to preserve

- **The app must be provider-agnostic.** No Prometheus/Elastic/Datadog-specific code or credentials in the Django app; adding or removing a backend must be a Collector-config-only change (spec scenario 5).
- **Independent Collector pipelines** for metrics, logs and traces; exporters individually enable/disable-able via configuration. Keep Collector config modular and documented.
- **Not every backend gets every signal:** Prometheus = metrics only; Elasticsearch = logs (and traces where supported); Datadog = all three; Grafana only visualises (it stores nothing); Kibana is the Elasticsearch-native UI.
- **Datadog is optional.** The stack must work fully locally without a Datadog account, and the app must keep running if Datadog is disabled or unreachable. Same for telemetry in general: Collector outages must not break business functionality (scenario 6).
- **Logs** are structured JSON including timestamp, severity, service name, environment, message, trace ID and span ID (needed for log↔trace correlation), and are shipped through the Collector.
- **Traces** should span HTTP → Django → PostgreSQL / Redis / Celery task → background job → PostgreSQL, with correct parent-child relationships (trace context must propagate into Celery).
- Collector needs memory limiting, batching, and exporter retry/queue config. Caveat: the Elasticsearch exporter does NOT retry on connection failure (it drops); only the Logstash path is durable (see `docs/signal-compat.md`, Scenario 6).
- Security: all credentials via environment variables (never committed), pinned image versions (no `latest`), healthchecks and persistent volumes on stateful services, restricted container networking, monitoring UIs not publicly exposed, no sensitive data in telemetry.
- Keep application code and observability infrastructure in logically separate top-level directories.
- Document signal-conversion/compatibility limitations between exporters and destinations, and demo-vs-production limitations.

## Deliverables beyond code

Grafana dashboards (at minimum: Application Performance, Infrastructure Health, Background Processing), Prometheus alert rules, Kibana views, and reproducible docs for six operational scenarios (latency degradation, app errors, Celery failure, slow DB, adding a new provider, Collector failure). Out of scope: Kubernetes, HA Collector clusters, Terraform, SIEM.

## Collector routing

Destinations are `EXPORT_<NAME>=true|false` flags (default on). `otel-config` (a one-shot container running `observability/otel-collector/render_config.py`) writes `routing.yaml` with only the enabled exporters' definitions and one pipeline per signal; the Collector loads `base.yaml` + that file. After changing flags or any `exporters.*.yaml`: `make collector-reload`. `make routes` shows the result. New destination = `exporters.<name>.yaml` + a row in `DESTINATIONS` + a flag in `docker-compose.yml`. Prometheus metric names are normalised OTel names (e.g. `portal_celery_tasks_total`, `http_server_duration_milliseconds_*`); latency is in ms.

## Scenarios and fault injection

`app/faults/` holds runtime toggles (Redis-backed, TTL 15 min, `FAULTS_ENABLED`-gated, staff-only API at `/api/_faults/`). `scenarios/run.py <1-6|all>` (via `make scenario N=..`) applies a fault, drives load (`scenarios/load/loadgen.py`, importable) and asserts the outcome in Prometheus/Elasticsearch; it exits non-zero on failure. Users come from `make demo-user` (`demo`, `ops-admin`). Measure exactly where you can (e.g. server spans vs requests actually sent, `work order created` logs vs work orders created) rather than estimating rates; thresholds must tolerate run-to-run variance (see Scenario 6). A destination fragment declares its routing in a `# routing:` header and is enabled with `EXPORT_<NAME>=true` or `EXPORT_EXTRA=<name>`.

## Elastic stack

`es-setup` and `kibana-setup` are idempotent one-shot containers (`observability/elasticsearch/setup.py`, `observability/kibana/setup.py`): users/roles, ILM, data-stream templates with keyword mappings, the span-normalising ingest pipeline, and Kibana data views/searches/dashboard. Logstash/Kibana wait for `es-setup` to *complete successfully*, so any non-zero exit there stalls the stack: keep it safe to re-run on a fresh and a populated cluster. Roles: `portal_writer` (Collector, Logstash) and `portal_reader` (Grafana) both need the read-only cluster `monitor` privilege for health checks. In Elasticsearch severity is `WARN` (not `WARNING`); `trace.id` is the shared correlation key. Changing a field *type* needs the data streams deleted (see `docs/signal-compat.md`). Collector queue volume `/queue` is chowned to uid 10001 by `otel-config`.

## Grafana

Fully file-provisioned (`observability/grafana/provisioning` + `dashboards/*.json`, `allowUiUpdates: false`): never click-edit, change the JSON and `docker compose restart grafana`. The dashboard JSON was generated from a script and is now the source of truth; keep new panels on the same style (datasource uid `prometheus`, `$__rate_interval`, `service` variable). Verify new panels by running their expr against Prometheus (`:9090`); a wrong metric name just yields an empty panel. Infra panels use Collector `hostmetrics` (Docker host view, not per-container). Ratio/"failures" stat queries use `or vector(0)` so healthy systems show 0, not "No data".

## Telemetry gotchas (learned the hard way)

- **Every OS process needs a unique `service.instance.id`** (set in `telemetry.py`). gunicorn/Celery run several; with an identical resource their cumulative counters/histograms overwrite each other in the Collector and under-count. Gauges that every process reports identically (queue depth) must be queried with `max`, not `sum`.
- **Histograms measured in seconds need explicit buckets**: the SDK default boundaries (0, 5, 10, 25 ...) are for milliseconds, so seconds-valued data all lands in the first bucket and percentiles are nonsense. `telemetry.py` has a View for `portal.*.duration`; new second-valued histograms must match that name pattern or get their own view.
- **Don't claim resilience you haven't measured against what was sent.** The Elasticsearch exporter looked retried and queued but drops data when Elasticsearch is unreachable (Scenario 6).
- App source is baked into the image (no bind mount): **rebuild (`make up`) after editing app code or tests** before running `make test`.
- `setup_telemetry()` runs per process: in `config/wsgi.py` for gunicorn workers, and via Celery's `worker_process_init` / `beat_init` (the SDK starts threads, so never init in the prefork parent).
- Don't mutate `LogRecord`s in a logging Filter to add fields (e.g. `trace_id=None`): the OTLP handler turns them into attributes, warns, that warning is logged, and it recurses. JSON enrichment lives in `ContextJsonFormatter`; the OTLP handler excludes `opentelemetry*` loggers.
- Metric names/attributes in `app/portal/metrics.py` are the contract for future dashboards and alerts; keep attribute cardinality low.

