# Operational scenarios
Each scenario injects one controlled fault, drives load, then **checks the outcome automatically** in Prometheus and Elasticsearch (exit code non-zero if an expectation is not met).
Prerequisites: stack running (`make up`), users created (`make demo-user`), `FAULTS_ENABLED=true`. Run one with `make scenario N=1` (or `bash scenarios/01-slow-endpoint/run.sh`), all with `make scenarios`. Each takes about 3 to 6 minutes because telemetry needs ~30s to reach the backends. Faults auto-expire after 15 minutes and are cleared when a scenario ends.
| # | Scenario | Fault |
|---|---|---|
| 1 | [application performance degradation](01-slow-endpoint/README.md) | `slow_endpoint` (1500 ms) |
| 2 | [application errors](02-app-errors/README.md) | `http_500` (60%) |
| 3 | [background processing failure](03-celery-failure/README.md) | `celery_fail` (60%) in the `generate_report` task |
| 4 | [database performance](04-slow-database/README.md) | `slow_db` (800 ms) |
| 5 | [adding a monitoring destination](05-add-provider/README.md) | No fault. Drops `exporters.file.yaml` (a stand-in new provider) into the Collector config and enables it with `EXPORT_EXTRA=file`. |
| 6 | [telemetry pipeline failures](06-collector-failure/README.md) | Stops the Collector (Part A) |
