# Scenario 2: application errors

**Run:** `make scenario N=2`

**What it does:** `http_500` (60%) on `GET /api/assets/<id>/`, raising a controlled `SimulatedError`.

## Expected outcome (checked automatically)
- Clients receive HTTP 500s; the 5xx ratio exceeds the 5% alert threshold.
- Prometheus alert `HighErrorRate` becomes *pending* (fires after 2 minutes sustained).
- ERROR logs and spans with ERROR status exist for `portal-django`.

## Where to look
- **Grafana** → *5xx error rate* tile (red) and *Responses by status code*; follow its link to Kibana errors.
- **Prometheus** → Alerts page (`HighErrorRate`).
- **Kibana** → *Portal: errors and criticals*.

## Think about
Open an error log, copy its `trace.id`, and read the exception on the matching failed span.
