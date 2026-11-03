#!/usr/bin/env python3
"""Mixed-traffic load generator for the portal API (stdlib only; also imported by scenarios).

CLI: python3 scenarios/load/loadgen.py [--base URL] [--rps 5] [--duration 60]
         [--user demo] [--password demo-pass] [--weight list=6 --weight report=3]

Operations: list get create update workorder wolist report external missing.
`--weight op=N` changes how often an operation is picked (default 1; get is 2). Scenarios use it
to concentrate traffic on the endpoint a fault affects. A small share of 404s (`missing`)
is deliberate so error metrics are never empty.
"""
import argparse
import json
import random
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

DEFAULT_WEIGHTS = {"list": 1, "get": 2, "create": 1, "update": 1, "workorder": 1, "wolist": 1,
                   "report": 1, "external": 1, "missing": 1}


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def csrf(self):
        return next((c.value for c in self.jar if c.name == "csrftoken"), "")

    def call(self, method, path, data=None):
        """Returns (status, json-or-None). status 0 = connection failure."""
        body = None
        headers = {"X-CSRFToken": self.csrf()}
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        try:
            with self.op.open(req, timeout=15) as r:
                raw = r.read()
                try:
                    return r.status, (json.loads(raw) if raw else None)
                except ValueError:
                    return r.status, None
        except urllib.error.HTTPError as e:
            return e.code, None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            return 0, None

    def login(self, user, password):
        self.call("GET", "/admin/login/")  # sets the CSRF cookie
        status, _ = self.call("POST", "/api/auth/login", {"username": user, "password": password})
        return status == 200


def drive(client, duration, rps=5, weights=None, quiet=False):
    """Send mixed traffic for `duration` seconds.
    Returns {"status": {code: n}, "latency": [s...], "workorders_created": n}."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    names, wts = list(w), list(w.values())
    ids, counts, latency, workorders = [], {}, [], 0
    end = time.time() + duration
    while time.time() < end:
        op = random.choices(names, wts)[0]
        started = time.perf_counter()
        if op == "list":
            s, _ = client.call("GET", "/api/assets/")
        elif op == "get" and ids:
            s, _ = client.call("GET", f"/api/assets/{random.choice(ids)}/")
        elif op == "update" and ids:
            s, _ = client.call("PATCH", f"/api/assets/{random.choice(ids)}/", {"owner": f"team-{random.randint(1, 5)}"})
        elif op == "workorder" and ids:
            s, _ = client.call("POST", "/api/workorders/", {"asset": random.choice(ids), "title": "loadgen"})
            workorders += s == 201  # each emits exactly one "work order created" log line
        elif op == "wolist":
            s, _ = client.call("GET", "/api/workorders/")
        elif op == "report":
            s, _ = client.call("POST", "/api/reports/")
        elif op == "external":
            s, _ = client.call("GET", "/api/external/rates/")
        elif op == "missing":
            s, _ = client.call("GET", "/api/assets/999999999/")
        else:  # create (also the fallback until some assets exist)
            s, body = client.call("POST", "/api/assets/", {"name": f"lg-{random.randint(1, 99999)}"})
            if s == 201 and body:
                ids.append(body["id"])
        latency.append(time.perf_counter() - started)
        counts[s] = counts.get(s, 0) + 1
        time.sleep(random.expovariate(rps))
    if not quiet:
        print("status counts:", dict(sorted(counts.items())))
    return {"status": counts, "latency": latency, "workorders_created": workorders}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--rps", type=float, default=5)
    p.add_argument("--duration", type=float, default=60)
    p.add_argument("--user", default="demo")
    p.add_argument("--password", default="demo-pass")
    p.add_argument("--weight", action="append", default=[], metavar="OP=N")
    a = p.parse_args()
    c = Client(a.base)
    if not c.login(a.user, a.password):
        raise SystemExit("login failed; create the users first: make demo-user")
    drive(c, a.duration, a.rps, {k: float(v) for k, v in (x.split("=") for x in a.weight)})


if __name__ == "__main__":
    main()
