# Signal conversion and compatibility notes

Where a signal changes shape on its way from the app to a backend. All of these were hit (and fixed or worked around) while building the platform.

## Metrics → Prometheus
- OTel names are normalised: `portal.celery.tasks` → `portal_celery_tasks_total` (dots → underscores, `_total` for counters, unit suffix such as `_seconds`).
- Django emits HTTP server duration twice (`http_server_duration_*` and `http_server_duration_milliseconds_*`). Dashboards and alerts use the `_milliseconds` form; latency is in **ms**, app-defined durations are in **seconds**.
- Resource attributes become labels only because the exporter has `resource_to_telemetry_conversion` on (`service_name`, `deployment_environment`).
- `http_target` holds the Django route *template* (e.g. `api/assets/(?P<pk>[^/.]+)/$`), not the raw URL, so cardinality stays bounded.

## Logs → Elasticsearch
- Severity names differ between the stdout JSON logs (`WARNING`) and Elasticsearch (`WARN`). `ERROR` and `CRITICAL` are the same in both. Queries against Elasticsearch must use `WARN`.
- The exporter does not define field types. Without the templates in `observability/elasticsearch/setup.py` the ECS fields become analysed `text` (no aggregations, tokenised IDs). They are declared `keyword` there.
- If you change a field **type**, delete the data streams (`DELETE _data_stream/logs-portal-default` etc.); rollover only affects new backing indices.

## Traces → Elasticsearch
- The `ecs` mapping mode writes **logs** with ECS names (`trace.id`, `service.name`) but **spans** in the exporter's own schema (`TraceId`, `SpanId`, `Resource.service.name`, `Duration` in microseconds). An ingest pipeline (`portal-traces-normalise`) copies them to `trace.id`, `span.id`, `span.name`, `service.name` and adds `duration_ms`, so one `trace.id` query matches both.
- This is plain Elasticsearch documents, **not Elastic APM**: Kibana's APM UI will not show these traces. Use the saved searches, or Discover on the `portal-correlation` data view.
- Span attributes include `db.statement` (SQL with `%s` placeholders, not bound values). Check this before pointing the app at real data.

## Logs → Logstash
- Logstash has no native OTLP input, so the Collector sends OTLP **as JSON over HTTP** and the pipeline flattens `resourceLogs → scopeLogs → logRecords` into one event each. It writes to its own stream (`logs-portal-logstash-default`), so every log line appears twice in Elasticsearch on purpose; this path exists to demonstrate Logstash, not because the data needs it.

## Host metrics
- The Collector's `hostmetrics` receiver reports the **Docker host**, not individual containers. Per-container CPU/memory would need cAdvisor or the Docker stats receiver.

## Delivery guarantees
- App → Collector: the SDK buffers in memory and drops when full (bounded, lossy) so the app never blocks.
- Collector → Elasticsearch: retries with backoff plus an on-disk queue (`file_storage`), so it survives destination outages and Collector restarts. Verified with a ~40s Elasticsearch outage: all telemetry from the outage window arrived afterwards.
- Collector → Prometheus is pull-based; a Collector outage is a gap in the series.

## Identifier safety
- `trace.id` / `span.id` end up in links (Grafana → Kibana) and queries. Elasticsearch ingest pipelines (`portal-logs-validate`, `portal-traces-normalise`) remove any value that is not well-formed hex (32 / 16 chars), for both log paths and for spans. The Grafana link also percent-encodes the value.
