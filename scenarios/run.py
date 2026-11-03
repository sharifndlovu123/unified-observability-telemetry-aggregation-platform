#!/usr/bin/env python3
"""Operational scenarios (spec section 8). Usage: python3 scenarios/run.py <1-6|all>

Each scenario: measure a baseline, inject one fault, drive load, then check that the fault is
visible where an operator would look (Prometheus, Elasticsearch, alerts) and that it was
removed afterwards. Exits non-zero if any expectation is not met. Narrative and "where to
look in the UI" notes are in scenarios/0N-*/README.md.
"""
import shutil
import sys
import time
from pathlib import Path

import lib
from lib import Report, ROOT

LOGS, TRACES = "logs-portal-default", "traces-portal-default"
BASELINE_S, FAULT_S = 45, 75


# ------------------------------------------------------------------------------ 1
def scenario_1():
    r, o, u = Report("Scenario 1: application performance degradation"), lib.ops(), lib.user()
    target, delay = "api/assets/$", 1500
    try:
        lib.phase("baseline", u, BASELINE_S, {"list": 6})
        lib.propagate()
        base = lib.p95_ms(target)
        t0 = lib.now_iso()
        lib.set_fault(o, "slow_endpoint", delay_ms=delay)
        lib.phase("fault", u, FAULT_S, {"list": 6})
        lib.propagate()
        t1 = lib.now_iso()
        slow = lib.p95_ms(target)
    finally:
        lib.clear_faults(o)
    r.check("Prometheus: p95 latency of GET /api/assets/ rose sharply", base is not None and slow is not None and slow > max(delay * 0.8, base * 5),
            f"baseline {base and round(base)} ms -> fault {slow and round(slow)} ms")
    spans = lib.es(TRACES, {"size": 1, "sort": [{"duration_ms": "desc"}], "query": {"bool": {"filter": [
        {"term": {"span.name": "simulated.slow_operation"}}, lib.window(t0, t1)]}}})["hits"]["hits"]
    r.check("Elasticsearch: trace shows a 'simulated.slow_operation' span of the injected length", bool(spans) and spans[0]["_source"]["duration_ms"] >= delay * 0.9,
            f"{spans[0]['_source']['duration_ms']:.0f} ms" if spans else "no span found")
    if spans:
        tid = spans[0]["_source"]["trace"]["id"]
        logs = lib.es_count(LOGS, {"bool": {"filter": [{"term": {"trace.id": tid}}, {"term": {"log.level": "WARN"}}]}})
        r.check("Elasticsearch: the slow request's trace.id also finds its WARN log line (log <-> trace correlation)", logs >= 1, f"trace {tid[:8]}..., {logs} log line(s)")
    r.check("Faults were cleared afterwards", o.call("GET", "/api/_faults/")[1] == {}, "no active faults")
    r.info("Grafana: Application Performance -> 'p95 latency by route'. Datadog comparison is postponed.")
    return r.finish()


# ------------------------------------------------------------------------------ 2
def scenario_2():
    r, o, u = Report("Scenario 2: application errors"), lib.ops(), lib.user()
    try:
        t0 = lib.now_iso()
        lib.set_fault(o, "http_500", rate=0.6)
        res = lib.phase("fault", u, 150, {"get": 10})
        lib.propagate()
        t1 = lib.now_iso()
        ratio = lib.prom('sum(rate(http_server_duration_milliseconds_count{http_status_code=~"5.."}[90s])) / sum(rate(http_server_duration_milliseconds_count[90s]))')
        states = lib.alert_states("HighErrorRate")
    finally:
        lib.clear_faults(o)
    served_500 = res["status"].get(500, 0)
    r.check("Clients really received HTTP 500s", served_500 > 0, f"{served_500} responses")
    r.check("Prometheus: 5xx ratio is above the 5% alert threshold", ratio is not None and ratio > 0.05, f"{ratio and round(ratio * 100, 1)}%")
    r.check("Prometheus alert HighErrorRate is pending or firing", bool(states), ", ".join(sorted(states)) or "not triggered")
    errs = lib.es_count(LOGS, {"bool": {"filter": [{"term": {"log.level": "ERROR"}}, {"term": {"service.name": "portal-django"}}, lib.window(t0, t1)]}})
    r.check("Elasticsearch: ERROR logs recorded by the web service", errs > 0, f"{errs} log lines")
    bad = lib.es_count(TRACES, {"bool": {"filter": [{"term": {"service.name": "portal-django"}}, {"term": {"TraceStatus": 2}}, lib.window(t0, t1)]}})
    r.check("Elasticsearch: exception traces (spans with ERROR status)", bad > 0, f"{bad} spans")
    r.info("Grafana: Application Performance -> '5xx error rate' tile; Kibana: 'Portal: errors and criticals'.")
    return r.finish()


# ------------------------------------------------------------------------------ 3
def scenario_3():
    r, o, u = Report("Scenario 3: background processing failure"), lib.ops(), lib.user()
    try:
        t0 = lib.now_iso()
        lib.set_fault(o, "celery_fail", rate=0.6)
        lib.phase("fault", u, 150, {"report": 8})
        lib.propagate()
        t1 = lib.now_iso()
        failures = lib.prom('sum(increase(portal_celery_tasks_total{outcome="failure"}[4m]))')
        states = lib.alert_states("CeleryTaskFailures")
    finally:
        lib.clear_faults(o)
    r.check("Prometheus: failed Celery tasks counted", failures is not None and failures > 0, f"{failures and round(failures)} failures in 4m")
    r.check("Prometheus alert CeleryTaskFailures is pending or firing", bool(states), ", ".join(sorted(states)) or "not triggered")
    hits = lib.es(LOGS, {"size": 1, "query": {"bool": {"filter": [
        {"term": {"service.name": "portal-celery-worker"}}, {"term": {"log.level": "ERROR"}}, {"exists": {"field": "trace.id"}}, lib.window(t0, t1)]}}})["hits"]["hits"]
    r.check("Elasticsearch: ERROR log from the worker, carrying a trace.id", bool(hits), hits[0]["_source"]["message"][:70] if hits else "none")
    if hits:
        tid = hits[0]["_source"]["trace"]["id"]
        agg = lib.es(TRACES, {"size": 0, "query": {"term": {"trace.id": tid}}, "aggs": {"s": {"terms": {"field": "service.name"}}}})
        services = {b["key"] for b in agg["aggregations"]["s"]["buckets"]}
        r.check("The failed task's trace spans BOTH the web request and the worker", {"portal-django", "portal-celery-worker"} <= services, ", ".join(sorted(services)))
    r.info("Grafana: Background Processing dashboard -> 'Failures by task' and 'Task success ratio'.")
    return r.finish()


# ------------------------------------------------------------------------------ 4
def scenario_4():
    r, o, u = Report("Scenario 4: database performance"), lib.ops(), lib.user()
    target, delay = "api/workorders/$", 800
    try:
        lib.phase("baseline", u, BASELINE_S, {"wolist": 6})
        lib.propagate()
        base_req = lib.p95_ms(target)
        t0 = lib.now_iso()
        lib.set_fault(o, "slow_db", delay_ms=delay)
        lib.phase("fault", u, FAULT_S, {"wolist": 6})
        lib.propagate()
        t1 = lib.now_iso()
        req = lib.p95_ms(target)
        db = lib.prom('histogram_quantile(0.95, sum by (le) (rate(portal_db_query_duration_seconds_bucket{operation="SELECT"}[90s])))')
    finally:
        lib.clear_faults(o)
    r.check("Prometheus: DB query duration p95 reflects the slow query", db is not None and delay / 1000 * 0.8 <= db <= delay / 1000 * 2, f"{db and round(db * 1000)} ms (injected {delay} ms)")
    r.check("Prometheus: request latency of GET /api/workorders/ rose with it", req is not None and base_req is not None and req > max(delay * 0.8, base_req * 5),
            f"baseline {base_req and round(base_req)} ms -> {req and round(req)} ms")
    spans = lib.es(TRACES, {"size": 1, "sort": [{"duration_ms": "desc"}], "query": {"bool": {"filter": [
        {"match": {"Attributes.db.statement": "pg_sleep"}}, lib.window(t0, t1)]}}})["hits"]["hits"]
    r.check("Elasticsearch: a database span for 'pg_sleep' of the injected length", bool(spans) and spans[0]["_source"]["duration_ms"] >= delay * 0.9,
            f"{spans[0]['_source']['duration_ms']:.0f} ms" if spans else "none")
    if spans:
        tid = spans[0]["_source"]["trace"]["id"]
        logs = lib.es_count(LOGS, {"term": {"trace.id": tid}})
        r.check("Elasticsearch: correlated log lines found by the same trace.id", logs >= 1, f"{logs} log line(s)")
    r.info("Kibana: 'Portal: slowest spans'. Grafana: Application Performance -> 'DB query duration p95 by operation'.")
    return r.finish()


# ------------------------------------------------------------------------------ 5
def scenario_5():
    r, u = Report("Scenario 5: adding a monitoring destination"), lib.user()
    template = ROOT / "scenarios/05-add-provider/exporters.file.yaml"
    installed = ROOT / "observability/otel-collector/exporters.file.yaml"
    out_file = "new-destination.jsonl"
    count = lambda: int(lib.subprocess.run(["docker", "run", "--rm", "-v", "uotap_otelcol-queue:/q:ro", "python:3.12-slim", "sh", "-c",
                                            f"wc -l < /q/{out_file} 2>/dev/null || echo 0"], capture_output=True, text=True).stdout.strip() or 0)
    app_before = lib.tree_hash(ROOT / "app")
    routes = lambda: lib.compose("logs", "otel-config", "--no-log-prefix", "--tail", "5").stdout
    try:
        r.check("Before: the new destination is not in the routing", "file" not in routes().replace("otlphttp", ""))
        shutil.copy(template, installed)
        print("  added observability/otel-collector/exporters.file.yaml (a new destination: one file)")
        lib.compose("up", "-d", "--force-recreate", "otel-config", "otel-collector", env={"EXPORT_EXTRA": "file"})
        time.sleep(8)
        routing = routes()
        r.check("After reload: the routing lists the new destination for all three signals", routing.count("file") >= 3, "metrics/logs/traces -> ..., file")
        before = count()
        lib.phase("traffic", u, 25)
        lib.wait(20, "Collector flushing to the new destination")
        after = count()
        r.check("The new destination is receiving telemetry", after > before, f"{before} -> {after} records")
        prom_ok = lib.prom("up{job='otel-collector-metrics'}")
        r.check("Existing destinations kept working (Prometheus still scraping)", prom_ok == 1.0)
    finally:
        installed.unlink(missing_ok=True)
        lib.compose("up", "-d", "--force-recreate", "otel-config", "otel-collector")
        lib.subprocess.run(["docker", "run", "--rm", "-v", "uotap_otelcol-queue:/q", "python:3.12-slim", "rm", "-f", f"/q/{out_file}"], capture_output=True)
        print("  cleanup: fragment removed, routing restored")
    r.check("The application source did not change at all", lib.tree_hash(ROOT / "app") == app_before, "app/ hash identical before and after")
    return r.finish()


# ------------------------------------------------------------------------------ 6
def server_spans(t0, t1):
    """Server-side request spans stored for a time window. Each HTTP request makes exactly one,
    so (stored / requests sent) is an exact delivery ratio with no rate estimation."""
    return lib.es_count(TRACES, {"bool": {
        "filter": [{"term": {"service.name": "portal-django"}}, {"match_phrase": {"Kind": "SPAN_KIND_SERVER"}}, lib.window(t0, t1)],
        # the app calls its own /stub/rates/ as the "external API": real server spans, but not client requests
        "must_not": [{"match_phrase": {"Name": "stub/rates"}}]}})


def wo_logs(index, t0, t1):
    """'work order created' is logged exactly once per successful work-order POST."""
    return lib.es_count(index, {"bool": {"filter": [{"match_phrase": {"message": "work order created"}}, lib.window(t0, t1)]}})


def timed_phase(label, client, seconds, rps):
    t0 = lib.now_iso()
    res = lib.phase(label, client, seconds, rps=rps)
    return res, t0, lib.now_iso(), sum(res["status"].values())


def scenario_6():
    r, u = Report("Scenario 6: telemetry pipeline failures"), lib.user()
    OUTAGE_A, RPS = 100, 8

    print("\n-- Part A: the Collector is down (app -> Collector link broken)")
    _, t0, t1, sent = timed_phase("control, Collector up", u, 25, RPS)
    lib.wait(25, "control telemetry landing")
    control = server_spans(t0, t1) / sent
    r.check("Control: with everything healthy, nearly every request has its span stored", control >= 0.9, f"{control:.0%}")

    lib.compose("stop", "otel-collector")
    out, t0, t1, sent = timed_phase("Collector DOWN", u, OUTAGE_A, RPS)
    lib.compose("start", "otel-collector")
    lib.wait(10, "Collector restarting")
    lib.phase("Collector back", u, 20, rps=RPS)
    lib.propagate()
    errors = sum(n for s_, n in out["status"].items() if s_ == 0 or s_ >= 500)
    r.check("The application served every request while the Collector was down", errors == 0, f"statuses {dict(sorted(out['status'].items()))}")
    lat = sorted(out["latency"])[int(len(out["latency"]) * 0.95) - 1]
    r.check("Request latency was unaffected by the failing exports (p95 < 1s)", lat < 1.0, f"p95 {lat * 1000:.0f} ms")
    kept = server_spans(t0, t1) / sent
    r.check("The SDK buffered and retried: a substantial share of the outage's spans was delivered after recovery", kept >= 0.4,
            f"{kept:.0%} stored vs {control:.0%} when healthy, after a {OUTAGE_A}s outage at ~{sent / OUTAGE_A:.0f} req/s")
    r.info("Delivery is best-effort and varies run to run (observed 69%-97%): the SDK keeps a bounded buffer (2048 spans per process, 2 web workers) and retries; what overflows or times out is dropped.")
    r.check("Telemetry resumed after the Collector came back", lib.es_count(TRACES, {"range": {"@timestamp": {"gte": "now-30s"}}}) > 0)

    print("\n-- Part B: Elasticsearch is down (Collector -> backend link broken)")
    lib.compose("stop", "elasticsearch")
    out, t0, t1, sent = timed_phase("Elasticsearch DOWN", u, 40, RPS)
    lib.compose("start", "elasticsearch")
    healthy = lib.wait_healthy("elasticsearch")
    lib.wait(90, "exporters retrying / draining their queues")
    r.check("Elasticsearch recovered", healthy)
    kept = server_spans(t0, t1) / sent if healthy else 0
    r.check("FINDING: traces written by the Elasticsearch exporter have a large gap (it drops batches it cannot deliver; no retry on connection failure in this Collector version)",
            kept < 0.8, f"{kept:.0%} of requests have a stored span (observed 5%-50% across runs)")
    made = out["workorders_created"]
    direct = wo_logs("logs-portal-default", t0, t1) / max(made, 1)
    via_ls = wo_logs("logs-portal-logstash-default", t0, t1) / max(made, 1)
    r.info(f"'work order created' logs for {made} work orders: direct exporter {direct:.0%}, via Logstash {via_ls:.0%}")
    r.check("The Logstash path (standard retrying exporter + Logstash's own queue) lost nothing", via_ls >= 0.9, f"{via_ls:.0%}")
    r.check("...and delivered clearly more than the direct exporter over the same window", via_ls >= direct + 0.05, f"{via_ls:.0%} vs {direct:.0%}")
    r.info("Lesson: resilience belongs to each exporter. Check whether the exporter you use retries on connection failure, and test it.")
    return r.finish()


SCENARIOS = {"1": scenario_1, "2": scenario_2, "3": scenario_3, "4": scenario_4, "5": scenario_5, "6": scenario_6}

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "all":
        codes = [fn() for fn in SCENARIOS.values()]
        sys.exit(1 if any(codes) else 0)
    if arg not in SCENARIOS:
        sys.exit(__doc__)
    sys.exit(SCENARIOS[arg]())
