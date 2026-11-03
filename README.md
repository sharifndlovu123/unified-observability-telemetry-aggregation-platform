# Unified Observability & Telemetry Aggregation Platform

A hands-on learning project: one instrumented Django app, one OpenTelemetry Collector, many observability backends (Prometheus, Grafana, ELK, optional Datadog).

**Core idea:** instrument once, collect centrally, distribute wherever required.

## Docs
- [`spec.md`](spec.md) – requirements and acceptance criteria
- [`TECHNICAL_SPEC.md`](TECHNICAL_SPEC.md) – design decisions, config contracts, verification plan
- [`CLAUDE.md`](CLAUDE.md) – guidance for Claude Code

## Status
Pre-implementation. Build order follows the phases in `TECHNICAL_SPEC.md` §12.

## Layout
- `app/` – Django demo application (no backend-specific code)
- `observability/` – Collector, Prometheus, Grafana, Elastic, Datadog config
- `scenarios/` – reproducible failure/observability demos
- `docs/` – architecture, deployment, troubleshooting, limitations

## Getting started
```
cp .env.example .env   # then edit secrets
```
Compose stack is not built yet.
