# Scenario 1: application performance degradation

**Run:** `make scenario N=1`

**What it does:** `slow_endpoint` (1500 ms) on `GET /api/assets/`, applied inside a span named `simulated.slow_operation`.

## Expected outcome (checked automatically)
- p95 latency of `GET /api/assets/` jumps from ~10 ms to over 1 s.
- A `simulated.slow_operation` span of ~1500 ms exists, and its `trace.id` also finds a WARN log line ("fault injected: slow endpoint").

## Where to look
- **Grafana** → Application Performance → *p95 latency by route* and *Latency percentiles*; the *Active fault injections* banner turns red.
- **Kibana** → *Portal: slowest spans* (sorted by `duration_ms`); copy the `trace.id` into *Portal: follow a trace*.
- **Prometheus** → `histogram_quantile(0.95, sum by (le) (rate(http_server_duration_milliseconds_bucket{http_target="api/assets/$",http_method="GET"}[1m])))`
- **Datadog**: postponed.

## Think about
Which tool tells you *that* it is slow, and which tells you *where*? (Metrics say that; the trace says where.)
