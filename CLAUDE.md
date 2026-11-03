# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Phases 1-2 done: Django app, Postgres, Redis, Celery worker/beat, full OTel instrumentation (metrics, JSON logs with trace IDs, traces incl. Celery propagation), and an `otel-collector` whose only exporter is `debug`. Prometheus/Grafana/ELK/Datadog are not built yet. `spec.md` and `TECHNICAL_SPEC.md` are git-ignored local planning docs (may be absent on a fresh clone); they define scope and design decisions.

## Commands

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
- Collector needs memory limiting, batching, and exporter retry/queue config.
- Security: all credentials via environment variables (never committed), pinned image versions (no `latest`), healthchecks and persistent volumes on stateful services, restricted container networking, monitoring UIs not publicly exposed, no sensitive data in telemetry.
- Keep application code and observability infrastructure in logically separate top-level directories.
- Document signal-conversion/compatibility limitations between exporters and destinations, and demo-vs-production limitations.

## Deliverables beyond code

Grafana dashboards (at minimum: Application Performance, Infrastructure Health, Background Processing), Prometheus alert rules, Kibana views, and reproducible docs for six operational scenarios (latency degradation, app errors, Celery failure, slow DB, adding a new provider, Collector failure). Out of scope: Kubernetes, HA Collector clusters, Terraform, SIEM.

## Telemetry gotchas (learned the hard way)

- App source is baked into the image (no bind mount): **rebuild (`make up`) after editing app code or tests** before running `make test`.
- `setup_telemetry()` runs per process: in `config/wsgi.py` for gunicorn workers, and via Celery's `worker_process_init` / `beat_init` (the SDK starts threads, so never init in the prefork parent).
- Don't mutate `LogRecord`s in a logging Filter to add fields (e.g. `trace_id=None`): the OTLP handler turns them into attributes, warns, that warning is logged, and it recurses. JSON enrichment lives in `ContextJsonFormatter`; the OTLP handler excludes `opentelemetry*` loggers.
- Metric names/attributes in `app/portal/metrics.py` are the contract for future dashboards and alerts; keep attribute cardinality low.

