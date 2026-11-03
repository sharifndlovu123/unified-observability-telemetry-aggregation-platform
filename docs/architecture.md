# Architecture

One principle: **instrument once, collect centrally, distribute wherever required.** The application emits standard OpenTelemetry (OTLP) and knows a single address. Everything else is the Collector's business.

## Components and networks

```mermaid
flowchart TB
  subgraph appnet["app-net (business traffic)"]
    pg[("PostgreSQL")]
    rd[("Redis<br/>cache db0, broker db1")]
  end
  subgraph apps["App containers (one image)"]
    web["django<br/>gunicorn x2"]
    wk["celery-worker x4"]
    bt["celery-beat"]
  end
  subgraph tnet["telemetry-net (OTLP only)"]
    col["otel-collector<br/>:4317 gRPC / :4318 HTTP"]
  end
  subgraph bnet["backend-net (Collector to backends, and UIs)"]
    prom[("Prometheus :9090")]
    es[("Elasticsearch :9200")]
    ls["Logstash :8080 (auth)"]
    kib["Kibana :5601"]
    graf["Grafana :3000"]
  end
  web & wk & bt --- pg & rd
  web & wk & bt -- OTLP --> col
  col -- scrape endpoint --> prom
  col --> es
  col --> ls --> es
  prom --> graf
  es --> graf & kib
```

- The app containers sit on `app-net` and `telemetry-net` only. They cannot reach Prometheus, Elasticsearch, Logstash or Grafana (`make verify` proves it).
- The Collector is the only bridge between the app side and the backend side.
- PostgreSQL and Redis are not on any telemetry network. All published ports bind to `127.0.0.1`.

## What flows where

| Signal | Producer | Collector pipeline | Destinations |
|---|---|---|---|
| Metrics | OTel SDK (auto + `portal.*` custom), plus Collector `hostmetrics` | `otlp, hostmetrics` → `memory_limiter, resource, batch` | Prometheus (scrape of `:8889`), debug |
| Logs | Python logging via OTLP handler | `otlp` → `memory_limiter, resource, batch` | Elasticsearch (direct), Logstash → Elasticsearch, debug |
| Traces | Auto-instrumented Django, psycopg, Redis, requests, Celery | `otlp` → `memory_limiter, resource, filter/noise, batch` | Elasticsearch, debug |

Grafana stores nothing: it queries Prometheus (metrics) and Elasticsearch (logs, traces). Kibana is Elasticsearch's own UI.

## One request across the system

```mermaid
sequenceDiagram
  participant C as Client
  participant D as django (portal-django)
  participant Q as Redis (broker)
  participant W as celery-worker
  participant O as otel-collector
  participant E as Elasticsearch
  C->>D: POST /api/reports/
  Note over D: server span, trace.id = T
  D->>D: INSERT report (db span)
  D->>Q: apply_async (producer span, trace context in message headers)
  D-->>C: 202 Accepted
  Q->>W: task message
  Note over W: run span, SAME trace.id = T
  W->>W: SELECT/UPDATE (db spans), GET /stub/rates (client span)
  D->>O: spans, logs (trace_id = T)
  W->>O: spans, logs (trace_id = T)
  O->>E: documents with trace.id = T
  Note over E: one query on trace.id finds the request's spans AND log lines
```

## Collector configuration

```mermaid
flowchart LR
  env[".env flags<br/>EXPORT_PROMETHEUS=true ..."] --> cfg["otel-config<br/>(one-shot render_config.py)"]
  frag["exporters.*.yaml<br/>each declares '# routing:'"] --> cfg
  cfg --> routing["routing.yaml<br/>enabled exporters + one pipeline per signal"]
  base["base.yaml<br/>receivers, processors, extensions"] --> col["otel-collector"]
  routing --> col
```

A destination is a file. `render_config.py` discovers `exporters.<name>.yaml`, reads its `# routing: exporter=<id> signals=<csv> default=<bool>` header, and includes it when `EXPORT_<NAME>` is true (or the name is in `EXPORT_EXTRA`). Disabled destinations are never loaded, so one that needs credentials costs nothing until enabled. After changing flags or fragments: `make collector-reload`.

## Design decisions worth knowing

| Decision | Why |
|---|---|
| Prometheus **scrapes** the Collector (`prometheus` exporter) rather than receiving remote-write | Simple, standard, and gives Prometheus its own `up` signal for the Collector |
| Spans are normalised in an Elasticsearch **ingest pipeline** | The Collector writes logs in ECS names (`trace.id`) but spans in its own schema (`TraceId`); one pipeline lets a single `trace.id` query match both |
| IDs are **validated as hex at ingest**, failing closed | `trace.id` is placed into links and queries |
| `service.instance.id` is unique **per OS process** | Several gunicorn/Celery processes sharing one identity overwrite each other's cumulative counters |
| Seconds-valued histograms get **explicit second-scale buckets** | SDK default buckets are millisecond-sized; percentiles would be meaningless |
| Logstash is a **second log path**, not the only one | Shows the "L" in ELK, and (measured) it is the durable path to Elasticsearch |
| Everything in Grafana/Kibana/Elasticsearch is **provisioned from files** | Reproducible; no click-ops state |
| Demo faults are Redis toggles with a **TTL**, staff-only, behind `FAULTS_ENABLED` | Scenarios need no redeploy; a forgotten fault expires |
