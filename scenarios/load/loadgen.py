#!/usr/bin/env python3
"""Mixed-traffic load generator for the portal API (stdlib only).

Usage: python3 scenarios/load/loadgen.py [--base URL] [--rps 5] [--duration 60]
                                         [--user demo] [--password demo-pass]
Exercises CRUD, cache reads (hits and misses), async reports, the external
API call, plus a small share of 404s so error logs/metrics exist even
before fault injection is added.
"""
import argparse
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def csrf(self):
        return next((c.value for c in self.jar if c.name == "csrftoken"), "")

    def call(self, method, path, data=None):
        body = None
        headers = {"X-CSRFToken": self.csrf()}
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        try:
            with self.op.open(req, timeout=10) as r:
                raw = r.read()
                try:
                    return r.status, (json.loads(raw) if raw else None)
                except ValueError:
                    return r.status, None
        except urllib.error.HTTPError as e:
            return e.code, None
        except urllib.error.URLError:
            return 0, None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--rps", type=float, default=5)
    p.add_argument("--duration", type=float, default=60)
    p.add_argument("--user", default="demo")
    p.add_argument("--password", default="demo-pass")
    a = p.parse_args()

    c = Client(a.base)
    c.call("GET", "/readyz")  # sets csrf cookie
    c.call("GET", "/admin/login/")
    status, _ = c.call("POST", "/api/auth/login", {"username": a.user, "password": a.password})
    if status != 200:
        raise SystemExit(f"login failed ({status}); create the user first (see README)")

    ids, counts = [], {}
    ops = ["list", "get", "get", "create", "update", "workorder", "report", "external", "missing"]
    end = time.time() + a.duration
    while time.time() < end:
        op = random.choice(ops)
        if op == "list":
            s, _ = c.call("GET", "/api/assets/")
        elif op == "get" and ids:
            s, _ = c.call("GET", f"/api/assets/{random.choice(ids)}/")
        elif op == "update" and ids:
            s, _ = c.call("PATCH", f"/api/assets/{random.choice(ids)}/", {"owner": f"team-{random.randint(1, 5)}"})
        elif op == "workorder" and ids:
            s, _ = c.call("POST", "/api/workorders/", {"asset": random.choice(ids), "title": "loadgen"})
        elif op == "report":
            s, _ = c.call("POST", "/api/reports/")
        elif op == "external":
            s, _ = c.call("GET", "/api/external/rates/")
        elif op == "missing":
            s, _ = c.call("GET", "/api/assets/999999999/")
        else:
            s, body = c.call("POST", "/api/assets/", {"name": f"lg-{random.randint(1, 99999)}"})
            if s == 201 and body:
                ids.append(body["id"])
        counts[s] = counts.get(s, 0) + 1
        time.sleep(random.expovariate(a.rps))
    print("status counts:", dict(sorted(counts.items())))


if __name__ == "__main__":
    main()
