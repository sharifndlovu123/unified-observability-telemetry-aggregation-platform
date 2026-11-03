# Scenario 6: telemetry pipeline failures

**Run:** `make scenario N=6`

**What it does:** Stops the Collector (Part A), then Elasticsearch (Part B), under load.

## Expected outcome (checked automatically)
- **Part A, Collector down (100 s):** the app serves every request with unchanged latency. The SDK buffers and retries, so most (observed 69% to 97%, varies per run) of the outage's spans arrive after recovery; what overflows its bounded buffer is dropped.
- **Part B, Elasticsearch down (40 s):** the direct Elasticsearch exporter **drops** what it cannot deliver (observed 5% to 51% of traces stored), while the Logstash path delivers **100%** of the same logs. Resilience belongs to each exporter.

## Where to look
- **Grafana** → Infrastructure Health → *Received by Collector*, *Export failures*.
- **Prometheus** → alerts `CollectorDown`, `CollectorExportFailures`.
- **Kibana** → compare document counts across the outage windows.

## Think about
Which layer buffers in each failure, how much, and what is dropped? Why did the two log paths behave differently, and which would you trust for audit logs?
