# Scenario 4: database performance

**Run:** `make scenario N=4`

**What it does:** `slow_db` (800 ms) on `GET /api/workorders/`, running `SELECT pg_sleep(...)`.

## Expected outcome (checked automatically)
- DB query duration p95 (`portal_db_query_duration_seconds`) rises to ~0.8 s and request latency for `GET /api/workorders/` rises with it.
- A database span containing `pg_sleep` of ~800 ms exists, and its `trace.id` finds correlated log lines.

## Where to look
- **Grafana** → Application Performance → *DB query duration p95 by operation*.
- **Kibana** → *Portal: slowest spans*; the span's `Attributes.db.statement` shows the query.

## Think about
Compare with Scenario 1: both make a request slow. What in the trace distinguishes app time from database time?
