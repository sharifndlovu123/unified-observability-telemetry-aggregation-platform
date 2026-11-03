# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

The repository is **pre-implementation**: it contains only `spec.md` (the project specification). There is no source code, build system, test suite, or git history yet, so there are no build/lint/test commands to document. When scaffolding begins, add the real commands here (Docker Compose up/down, running Django tests, single-test invocation, etc.) rather than guessing. Treat `spec.md` as the source of truth for scope and acceptance criteria (section 11).

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
