#!/usr/bin/env python3
"""Smoke test of the spec's acceptance criteria against the RUNNING stack (about 1.5 minutes).
Run after `make up` and `make demo-user`. Exits non-zero if any criterion fails."""
import json
import time
import urllib.request
import base64
import os

import lib
from lib import Report

LOGS, TRACES, LSLOGS = "logs-portal-default", "traces-portal-default", "logs-portal-logstash-default"


def http_json(url, user=None, password=None):
    req = urllib.request.Request(url)
    if user:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode())
    return json.load(urllib.request.urlopen(req, timeout=20))


def main():
    r = Report("Acceptance criteria (spec section 11)")
    ps = [json.loads(l) for l in lib.compose("ps", "-a", "--format", "json").stdout.splitlines() if l.strip()]
    bad = [p["Service"] for p in ps if p["State"] == "running" and p.get("Health") not in ("healthy", "") or
           p["State"] == "exited" and p["ExitCode"] != 0]
    r.check("The entire environment is deployed through Docker Compose and healthy", ps and not bad, f"{len(ps)} containers" + (f", problems: {bad}" if bad else ""))

    lib.phase("traffic", lib.user(), 25)
    lib.propagate()

    metrics = lib.prom("sum(http_server_duration_milliseconds_count)")
    n_logs, n_spans = lib.es_count(LOGS, {"match_all": {}}), lib.es_count(TRACES, {"match_all": {}})
    r.check("The Django application produces metrics, logs and traces", bool(metrics) and n_logs > 0 and n_spans > 0, f"{metrics and int(metrics)} requests counted, {n_logs} logs, {n_spans} spans")

    out = lib.compose("exec", "-T", "django", "python", "-c",
                      "import socket\nfor h,p in [('prometheus',9090),('elasticsearch',9200),('grafana',3000),('logstash',8080)]:\n"
                      "    try:\n        socket.setdefaulttimeout(2); socket.create_connection((h,p)); print('REACHED',h)\n    except OSError: pass", check=False).stdout
    r.check("All telemetry goes through the Collector (the app cannot reach any backend directly)", "REACHED" not in out, out.strip() or "app is on telemetry-net and app-net only")

    routing = lib.compose("logs", "otel-config", "--no-log-prefix", "--tail", "8").stdout
    r.check("The Collector has independent pipelines for all three signals", all(f"{sig} " in routing for sig in ("metrics", "logs", "traces")), routing.strip().replace("\n", " | "))

    r.check("Prometheus receives and stores application metrics", lib.prom('sum(portal_cache_operations_total)') is not None and metrics > 0)

    gp = os.environ["GF_SECURITY_ADMIN_PASSWORD"]
    health = [http_json(f"http://127.0.0.1:3000/api/datasources/uid/{u}/health", "admin", gp).get("status") for u in ("prometheus", "elasticsearch-logs", "elasticsearch-traces")]
    dashes = {d["title"] for d in http_json("http://127.0.0.1:3000/api/search?type=dash-db", "admin", gp)}
    r.check("Grafana displays data from its configured data sources, with the three dashboards", health == ["OK"] * 3 and {"Application Performance", "Infrastructure Health", "Background Processing"} <= dashes, f"datasources {health}, dashboards {len(dashes)}")
    rules = http_json("http://127.0.0.1:3000/api/v1/provisioning/alert-rules", "admin", gp)
    r.check("Grafana alert rules and Prometheus alert rules are provisioned", len(rules) >= 2 and len(http_json("http://127.0.0.1:9090/api/v1/rules")["data"]["groups"]) >= 2, f"{len(rules)} Grafana rules")

    structured = lib.es_count(LOGS, {"bool": {"filter": [{"exists": {"field": "trace.id"}}, {"exists": {"field": "service.name"}}, {"exists": {"field": "log.level"}}]}})
    r.check("Elasticsearch receives and indexes structured logs", structured > 0, f"{structured} logs with trace.id, service.name, log.level")

    tok = base64.b64encode(f"elastic:{os.environ['ELASTIC_PASSWORD']}".encode()).decode()
    kb = urllib.request.Request("http://127.0.0.1:5601/api/saved_objects/_find?type=search&type=dashboard&type=index-pattern&per_page=50", headers={"Authorization": "Basic " + tok, "kbn-xsrf": "true"})
    kinds = [o["type"] for o in json.load(urllib.request.urlopen(kb, timeout=20))["saved_objects"]]
    r.check("Kibana can search and visualise application logs (data views, saved searches, dashboard)", kinds.count("index-pattern") >= 3 and kinds.count("search") >= 4 and "dashboard" in kinds, f"{kinds.count('index-pattern')} data views, {kinds.count('search')} searches")

    hit = lib.es(LOGS, {"size": 1, "query": {"bool": {"filter": [{"exists": {"field": "trace.id"}}, {"range": {"@timestamp": {"gte": "now-2m"}}}]}}})["hits"]["hits"]
    tid = hit[0]["_source"]["trace"]["id"] if hit else ""
    joined = lib.es_count(f"{TRACES}", {"term": {"trace.id": tid}}) if tid else 0
    r.check("Trace IDs correlate application logs and traces", joined > 0, f"trace {tid[:8]}...: 1+ log line and {joined} spans share it")

    r.check("Multiple destinations receive telemetry simultaneously (Prometheus, Elasticsearch direct, Elasticsearch via Logstash)",
            bool(metrics) and n_logs > 0 and lib.es_count(LSLOGS, {"match_all": {}}) > 0, f"logs: {n_logs} direct, {lib.es_count(LSLOGS, {'match_all': {}})} via Logstash")

    lib.compose("up", "-d", "--force-recreate", "otel-config", "otel-collector", env={"EXPORT_PROMETHEUS": "false"})
    time.sleep(6)
    off = lib.compose("logs", "otel-config", "--no-log-prefix", "--tail", "4").stdout
    lib.compose("up", "-d", "--force-recreate", "otel-config", "otel-collector")
    time.sleep(6)
    on = lib.compose("logs", "otel-config", "--no-log-prefix", "--tail", "4").stdout
    metrics_line = lambda t: next((l for l in t.splitlines() if l.startswith("metrics")), "")
    r.check("Individual exporters can be enabled or disabled through configuration", "prometheus" not in metrics_line(off) and "prometheus" in metrics_line(on), "EXPORT_PROMETHEUS=false removed it, default restored it")

    r.info("A new destination can be added without modifying application code: run `make scenario N=5` (asserts app/ is byte-identical).")
    r.info("The operational scenarios are documented and reproducible: `make scenarios`.")
    r.info("Datadog receives the configured telemetry: SKIPPED, Datadog is postponed by decision.")
    return r.finish()


if __name__ == "__main__":
    raise SystemExit(main())
