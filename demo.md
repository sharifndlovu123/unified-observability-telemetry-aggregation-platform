# Demo: a full run-through

A guided tour of the whole platform, about 30 to 40 minutes. You start the stack, generate traffic, watch one request travel through metrics, logs and traces, break something on purpose, then change where telemetry goes without touching the app.

Needs Docker with Compose v2 and about 8 GB of free RAM. The first `make up` pulls roughly 4 GB of images.

## 0. Start

```
make init         # first run only: writes .env with random secrets
make up           # builds and starts everything, waits for healthchecks
make demo-user    # creates users: demo (load) and ops-admin (staff, fault control)
```

Passwords for the UIs are in `.env`:

| UI | URL | Login |
|---|---|---|
| API | http://127.0.0.1:8000 | `demo` / `ops-admin` (see `make demo-user` output) |
| Grafana | http://127.0.0.1:3000 | `admin` / `GF_SECURITY_ADMIN_PASSWORD` |
| Prometheus | http://127.0.0.1:9090 | none |
| Kibana | http://127.0.0.1:5601 | `elastic` / `ELASTIC_PASSWORD` |

Telemetry takes about 30 seconds to reach the backends, so wait a minute before judging an empty panel.

## 1. Check that it works (about 2 minutes)

```
make test         # 22 tests pass inside the django container
make verify       # checks the spec's acceptance criteria against the live stack (~1.5 min)
```

`make verify` is the quick "is everything wired correctly" answer. If it fails, see [`docs/troubleshooting.md`](docs/troubleshooting.md).

## 2. Generate traffic

```
make load         # 60 s of mixed API traffic
```

Celery Beat also emits baseline activity (heartbeat, synthetic load, one log per severity), so dashboards are never completely empty.

## 3. See the three signals

**Metrics (Grafana).** Open the *Observability Platform* folder:
- *Application Performance*: request rate, 5xx rate, p50/p95/p99 latency, slowest routes, cache hit ratio.
- *Background Processing*: queue depth, task success ratio, duration by task.
- *Infrastructure Health*: host CPU/memory plus the telemetry pipeline's own health (what the Collector receives and exports).

**Logs and traces (Kibana).** Open the dashboard *Portal: logs and traces overview*. Copy a `trace.id` from an error, then paste it into the saved search *Portal: follow a trace*. You see that single request's log lines and spans together, in time order. This works because every log line and span carries the same `trace.id`.

**The Collector itself.**
```
docker compose logs -f otel-collector      # what it receives
make routes                                # where each signal goes right now
```

## 4. Break something on purpose

Each scenario injects a fault (auto-expires after 15 minutes), drives load, then checks automatically that the effect shows up in Prometheus and Elasticsearch. Run one while Grafana is open on *Application Performance*; a red **Active fault injections** banner appears while a fault is on.

```
make scenario N=1     # slow endpoint (latency degradation)
make scenario N=2     # application errors
make scenario N=3     # Celery task failure
make scenario N=4     # slow database
make scenario N=5     # add a new destination (no app change)
make scenario N=6     # Collector / pipeline failure
make scenarios        # all six
```

Each takes about 3 to 6 minutes and exits non-zero if the expected effect is not visible. What to look at in the UI for each: [`scenarios/README.md`](scenarios/README.md).

## 5. Change routing without touching the app

This is the core idea: the app only knows the Collector.

1. In `.env`, set `EXPORT_PROMETHEUS=false`.
2. Reload:
   ```
   make collector-reload
   make routes
   ```
3. Generate traffic (`make load`). New metrics stop reaching Prometheus and the Grafana panels flatten, while logs and traces in Kibana keep flowing. The app and its containers were never restarted.
4. Set it back to `true` and `make collector-reload`.

Scenario 5 does the same by adding a brand new destination from a single YAML file.

## 6. Know the limits

- The direct Elasticsearch exporter **drops** data while Elasticsearch is unreachable. The Logstash path (`EXPORT_LOGSTASH`) retries and is the durable one. Scenario 6 measures this. See [`docs/signal-compat.md`](docs/signal-compat.md).
- Infrastructure panels show the Docker host, not per-container usage.
- Datadog is not built yet (postponed).

More: [`docs/limitations.md`](docs/limitations.md).

## 7. Stop

```
make down                  # stop containers, keep data volumes
docker compose down -v     # stop and delete all data (start from empty)
```
