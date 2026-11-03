"""Shared helpers for the operational scenarios: talk to the app, Prometheus and Elasticsearch,
and report pass/fail against explicit expectations."""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scenarios" / "load"))
import loadgen  # noqa: E402

APP, PROM, ES = "http://127.0.0.1:8000", "http://127.0.0.1:9090", "http://127.0.0.1:9200"
# Telemetry takes a while to be queryable: SDK batch (5-10s) + Collector batch (5s) + Prometheus scrape (15s).
PROPAGATION_SECONDS = 30


def load_env():
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()


def now_iso(offset=0):
    return datetime.fromtimestamp(time.time() + offset, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def prom(query):
    """First value of an instant query, or None when there is no data."""
    url = PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
    result = json.load(urllib.request.urlopen(url, timeout=20))["data"]["result"]
    return float(result[0]["value"][1]) if result else None


def prom_series(query):
    url = PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
    return json.load(urllib.request.urlopen(url, timeout=20))["data"]["result"]


def es(index, body, path="_search"):
    token = base64.b64encode(f"elastic:{os.environ['ELASTIC_PASSWORD']}".encode()).decode()
    req = urllib.request.Request(f"{ES}/{index}/{path}", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def es_count(index, query):
    return es(index, {"query": query}, "_count")["count"]


def window(start, end):
    return {"range": {"@timestamp": {"gte": start, "lte": end}}}


def p95_ms(target, method="GET", span="90s"):
    return prom(f'histogram_quantile(0.95, sum by (le) (rate(http_server_duration_milliseconds_bucket'
                f'{{http_target="{target}",http_method="{method}"}}[{span}])))')


def wait(seconds, why):
    print(f"  ... waiting {seconds}s ({why})", flush=True)
    time.sleep(seconds)


def propagate():
    wait(PROPAGATION_SECONDS, "telemetry propagating SDK -> Collector -> Prometheus/Elasticsearch")


def ops():
    c = loadgen.Client(APP)
    if not c.login("ops-admin", os.environ.get("DEMO_OPS_PASSWORD", "ops-pass")):
        sys.exit("cannot log in as ops-admin; run: make demo-user (and set FAULTS_ENABLED=true)")
    return c


def user():
    c = loadgen.Client(APP)
    if not c.login("demo", os.environ.get("DEMO_USER_PASSWORD", "demo-pass")):
        sys.exit("cannot log in as demo; run: make demo-user")
    return c


def set_fault(ops_client, name, **params):
    status, body = ops_client.call("POST", "/api/_faults/", {"fault": name, **params})
    if status != 200:
        sys.exit(f"could not set fault {name}: HTTP {status} (is FAULTS_ENABLED=true?)")
    print(f"  fault ON : {name} {params}", flush=True)


def clear_faults(ops_client):
    ops_client.call("DELETE", "/api/_faults/")
    print("  faults cleared", flush=True)


def phase(label, client, seconds, weights=None, rps=6):
    print(f"[{label}] {seconds}s of traffic", flush=True)
    return loadgen.drive(client, seconds, rps, weights)


def alert_states(name, timeout=90):
    """Poll Prometheus until the alert is pending/firing (or timeout). Returns the state seen."""
    deadline = time.time() + timeout
    while True:
        states = {s["metric"]["alertstate"] for s in prom_series(f'ALERTS{{alertname="{name}"}}')}
        if states or time.time() > deadline:
            return states
        time.sleep(5)


def tree_hash(path):
    h = hashlib.sha256()
    for f in sorted(p for p in Path(path).rglob("*") if p.is_file() and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts):
        h.update(str(f.relative_to(path)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def compose(*args, env=None, check=True):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, env={**os.environ, **(env or {})},
                          capture_output=True, text=True, check=check)


def wait_healthy(service, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = compose("ps", service, "--format", "{{.Health}}", check=False).stdout.strip()
        if out == "healthy":
            return True
        time.sleep(3)
    return False


class Report:
    def __init__(self, title):
        self.title, self.failed = title, 0
        print(f"\n=== {title} ===", flush=True)

    def check(self, description, ok, detail=""):
        self.failed += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}  {description}" + (f"   [{detail}]" if detail else ""), flush=True)

    def info(self, text):
        print(f"  info  {text}", flush=True)

    def finish(self):
        print(f"=== {self.title}: {'ALL EXPECTATIONS MET' if not self.failed else str(self.failed) + ' EXPECTATION(S) NOT MET'} ===\n")
        return 1 if self.failed else 0
