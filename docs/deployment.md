# Deployment

## Requirements
- Docker with Compose v2 (tested with Docker 29 / Compose 5), Python 3 on the host (for `make init`, load generator and scenarios; standard library only).
- About **8 GB RAM free** (Elasticsearch has a 1 GB heap, Logstash 512 MB, Kibana is heavy to start). Tested on a 16-core / 30 GB machine.
- Linux hosts: Elasticsearch needs `vm.max_map_count >= 262144` (`sysctl vm.max_map_count`; raise with `sudo sysctl -w vm.max_map_count=262144`).
- Free ports on `127.0.0.1`: 8000 (app), 9090 (Prometheus), 3000 (Grafana), 9200 (Elasticsearch), 5601 (Kibana).

## First run
```bash
git clone <repo> && cd <repo>
make init         # writes .env with random secrets (mode 600); refuses to overwrite an existing .env
make up           # builds the app image and starts everything; waits for healthchecks (first run pulls ~4 GB of images)
make demo-user    # creates 'demo' (load) and 'ops-admin' (staff; fault control)
make verify       # ~1.5 min: checks the spec's acceptance criteria against the running stack
make load         # 60 s of mixed traffic (optional; Celery Beat also generates baseline activity)
```
Startup takes a few minutes: Elasticsearch must be healthy, then `es-setup` (users, retention, templates) completes, then Logstash and Kibana start, then `kibana-setup` creates the saved objects. The one-shot containers (`otel-config`, `es-setup`, `kibana-setup`) show `Exited (0)` when done; that is normal.

## What's where
| URL | What | Login |
|---|---|---|
| http://127.0.0.1:8000/healthz, `/readyz`, `/api/...` | The Django API | `demo` / `demo-pass` (session login at `POST /api/auth/login`) |
| http://127.0.0.1:3000 | Grafana (folder "Observability Platform") | `admin` / `GF_SECURITY_ADMIN_PASSWORD` in `.env` |
| http://127.0.0.1:5601 | Kibana ("Portal: logs and traces overview") | `elastic` / `ELASTIC_PASSWORD` in `.env` |
| http://127.0.0.1:9090 | Prometheus (Alerts page shows rule state) | none |
| http://127.0.0.1:9200 | Elasticsearch API | `elastic` / `ELASTIC_PASSWORD` |

## Everyday commands
| Command | Does |
|---|---|
| `make up` / `make down` | Start (rebuilding the app image) / stop, keeping data |
| `make logs` | Follow all container logs |
| `make test` | pytest inside the django container |
| `make collector-reload` | Re-render routing after changing `EXPORT_*` flags or an `exporters.*.yaml` |
| `make routes` | Show where each signal currently goes |
| `make scenario N=1` / `make scenarios` | Run one / all operational scenarios |
| `docker compose down -v` | Stop **and delete all data** (volumes) |

The app's source is baked into the image: **after editing app code, run `make up`** before `make test`.

## Configuration
Everything is environment-driven via `.env` (template: `.env.example`, which documents each variable). Notable ones:
- `EXPORT_DEBUG`, `EXPORT_PROMETHEUS`, `EXPORT_ELASTICSEARCH`, `EXPORT_LOGSTASH`: which destinations receive telemetry (default all on). `EXPORT_EXTRA=<name>[,<name>]` enables additional fragments.
- `FAULTS_ENABLED`: allows the demo fault API (needed for scenarios). Set `false` for anything but a demo.
- `LOG_LEVEL` (default `INFO`), `DEBUG_EXPORTER_VERBOSITY` (`basic|normal|detailed`; `detailed` prints full spans in the Collector log).
- Image versions are pinned in `docker-compose.yml`; the Elastic stack components must stay on the same version.

## Adding a destination
1. Create `observability/otel-collector/exporters.<name>.yaml` whose first line is `# routing: exporter=<id> signals=<metrics,logs,traces> default=false`, followed by its `exporters:` (and `extensions:`) definitions.
2. Enable it: `EXPORT_<NAME>=true` in `.env` (or `EXPORT_EXTRA=<name>`), then `make collector-reload`.
3. Nothing in `app/` changes. `make scenario N=5` demonstrates exactly this and asserts it.

## Backups and upgrades
Not covered: this is a demonstration environment (see `limitations.md`). Persistent data lives in named volumes (`pgdata`, `redisdata`, `esdata`, `promdata`, `grafanadata`, `otelcol-queue`); Elasticsearch data is deleted by ILM after 7 days.
