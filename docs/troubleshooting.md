# Troubleshooting

Most entries below are problems that actually occurred while building this platform.

## Stack won't start
| Symptom | Cause / fix |
|---|---|
| `set POSTGRES_PASSWORD in .env` (or another `...:?set ...`) | `.env` missing or incomplete. Run `make init` (first time) or compare with `.env.example`. |
| `ImproperlyConfigured: DJANGO_SECRET_KEY must be set` | The app deliberately refuses to start without a secret key unless `DEBUG=true`. |
| Elasticsearch exits immediately | `vm.max_map_count` too low (Linux), or not enough RAM. See `deployment.md`. |
| Logstash or Kibana never starts | They wait for `es-setup` to **complete successfully**. Check `docker compose logs es-setup`; fix and `docker compose up es-setup`. |
| Logstash crash: `unauthorized for user [portal_writer]` | The writer role needs the read-only cluster `monitor` privilege; `es-setup` grants it. Re-run `docker compose up --force-recreate es-setup`. |
| `celery-beat` unhealthy / permission denied on the schedule file | The `/var/lib/beat` volume must be owned by the non-root app user (done in the Dockerfile). Recreate with `docker compose down -v` if an old root-owned volume exists. |
| Collector: `'retry' has invalid keys` and similar | Config keys differ between Collector versions. The image is pinned to 0.116.1; check keys against that version. |
| Port already in use | Another stack uses 8000/9090/3000/9200/5601; stop it or change the published ports in `docker-compose.yml`. |

## No data in a backend
1. **Is the destination enabled?** `make routes` shows where each signal goes. A `false` flag in `.env` removes a destination.
2. **Is the Collector receiving?** `docker compose logs -f otel-collector`. For full detail: `DEBUG_EXPORTER_VERBOSITY=detailed docker compose up -d otel-collector`.
3. **Is the app exporting?** `OTEL_EXPORTER_OTLP_ENDPOINT` should be `http://otel-collector:4317`. App logs also go to stdout as JSON (`make logs`).
4. **Telemetry takes ~30 s** to be queryable (SDK batch + Collector batch + Prometheus scrape). Don't judge before then.
5. Prometheus targets: http://127.0.0.1:9090/targets (all three should be UP).

## Wrong or surprising numbers
| Symptom | Cause |
|---|---|
| Counters/histograms jump around or under-count | Several processes exporting with the same resource identity overwrite each other. Each process must have a unique `service.instance.id` (`config/telemetry.py` sets it). |
| Duration percentiles are nonsense (e.g. p95 = 4.75 s for an 0.8 s operation) | Histogram measured in seconds using the SDK's millisecond-sized default buckets. Name it `portal.*.duration` (a View sets second-scale buckets) or add a View. |
| Queue depth is N times too high | Every process reports the same gauge; query with `max`, not `sum`. |
| A Kibana/Grafana query for warnings finds nothing | In Elasticsearch the level is `WARN` (not `WARNING`). `ERROR` and `CRITICAL` are unchanged. |
| `trace.id` query finds logs but no spans | The span normalising ingest pipeline is missing: re-run `es-setup` and roll over the stream (see `signal-compat.md`). |
| Aggregation error: "Fielddata is disabled on [log.level]" | Field mapped as `text`. Templates must declare ECS fields as `keyword`; changing a field **type** requires deleting the data stream: `DELETE _data_stream/<name>`. |

## Elasticsearch/Logstash
- **Telemetry missing after an Elasticsearch outage:** expected for the direct exporter. It logs `Exporting failed. Dropping data.` and does not retry connection failures (Collector 0.116). The Logstash path retries. See `signal-compat.md`.
- **Every log line appears twice in Elasticsearch:** by design (direct stream and `logs-portal-logstash-default`). Query one stream, or disable `EXPORT_LOGSTASH`.
- **Logstash 401 from the Collector:** `LOGSTASH_INPUT_PASSWORD` differs between the two containers; recreate both after changing it.

## App and scenarios
- **`cannot log in as ops-admin`:** run `make demo-user`; faults also need `FAULTS_ENABLED=true`.
- **Edited app code but behaviour unchanged:** the source is baked into the image. `make up` rebuilds.
- **Login returns 429:** per-IP and per-account failure budgets (`LOGIN_FAIL_*`, `LOGIN_IP_THROTTLE_RATE`). Wait a minute, or the window passes (account budget is 15 min).
- **Scenario assertions fail intermittently:** telemetry propagation is ~30 s and some outcomes (e.g. Scenario 6 delivery ratios) vary run to run; thresholds are set to the observed ranges. Re-run before assuming a regression.
- **Leftover fault:** faults auto-expire after 15 min; clear now with `DELETE /api/_faults/` as `ops-admin`.

## Starting over
`docker compose down -v && make up` (deletes all data, including the Collector's on-disk queue and Elasticsearch indices).
