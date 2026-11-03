# Limitations of this demonstration environment

This is a learning platform, not a production deployment. Compared with one:

| Area | Here | A production deployment would |
|---|---|---|
| Elasticsearch | Single node, 1 GB heap, 0 replicas, security on but no TLS | Run a multi-node cluster with replicas, snapshots and TLS |
| Collector | One instance, no HA | Run several behind a load balancer; consider an agent/gateway split |
| Delivery guarantees | The direct Elasticsearch exporter **drops data** when Elasticsearch is unreachable; the SDK buffer is bounded (2048 spans/process) | Put a durable queue (e.g. Kafka) between the Collector and storage, or use an exporter version verified to retry |
| Retention | 7 days via ILM; no archival | Define retention per signal and compliance need, with archival tiers |
| Alerting | Prometheus and Grafana rules visible in their UIs; no Alertmanager, no notification channels | Route alerts to paging/chat, with silences and escalation |
| Security | Local-only ports, per-service least-privilege Elasticsearch users, secrets from `.env`, no TLS between containers, demo credentials (`demo-pass`, `ops-pass`) | TLS everywhere, a secrets manager, SSO, network policies, no demo users |
| Fault injection | A Redis-backed API behind `FAULTS_ENABLED`; staff-only and auto-expiring | Not present at all |
| Login protection | Per-IP and per-account failure budgets | Add step-up challenges (CAPTCHA/MFA); the per-account budget can lock a user out for its window |
| Infrastructure metrics | Collector `hostmetrics` shows the **Docker host**, not per-container usage | cAdvisor / kubelet / Docker stats receiver for per-workload metrics |
| Traces in Elasticsearch | Plain documents searched in Kibana Discover; **not** Elastic APM | Use an APM-compatible ingest path (Elastic APM/EDOT) or a trace backend (Tempo/Jaeger) with a waterfall UI |
| Logstash | Included as a second log path; duplicates data on purpose | Usually only one path; Logstash earns its place for parsing/enrichment or buffering |
| Scale | Tens of requests/second | Needs sampling, capacity planning and cardinality controls |
| Datadog | **Not built** (postponed). The platform is designed so it is one more exporter fragment | Optional SaaS destination, needs an account and API key |
| Versions | Collector 0.116.1 and Elastic 8.15.3 pinned; newer Collectors rename config keys and metrics | Plan and test upgrades |

Explicitly out of scope (from the original specification): Kubernetes, HA Collector clusters, multi-region monitoring, large-scale ingestion, Terraform provisioning, SIEM.
