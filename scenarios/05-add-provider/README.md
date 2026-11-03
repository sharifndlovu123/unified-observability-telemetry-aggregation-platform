# Scenario 5: adding a monitoring destination

**Run:** `make scenario N=5`

**What it does:** No fault. Drops `exporters.file.yaml` (a stand-in new provider) into the Collector config and enables it with `EXPORT_EXTRA=file`.

## Expected outcome (checked automatically)
- The routing lists `file` for metrics, logs and traces; `new-destination.jsonl` receives records.
- Existing destinations keep working.
- The hash of the `app/` directory is **identical before and after**: the application was not touched.

## Where to look
- `docker compose logs otel-config` shows the new routing.
- **Grafana** → Infrastructure Health → *Sent by exporter*: a new exporter line appears.

## Think about
What would adding a real provider (Datadog, Loki, Tempo) change compared with this file?
