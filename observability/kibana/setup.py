#!/usr/bin/env python3
"""One-shot Kibana bootstrap (idempotent): data views, saved searches, a dashboard.

Everything is created through Kibana's API with fixed ids, so re-running overwrites rather
than duplicates. Kibana is read-through to the Elasticsearch data streams created by
observability/elasticsearch/setup.py.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

KB = os.environ.get("KIBANA_URL", "http://kibana:5601")
AUTH = "Basic " + base64.b64encode(f"elastic:{os.environ['ELASTIC_PASSWORD']}".encode()).decode()


def call(method, path, body=None):
    req = urllib.request.Request(KB + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": AUTH, "Content-Type": "application/json", "kbn-xsrf": "true"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> {e.code}: {e.read().decode()[:400]}")


for _ in range(60):
    try:
        call("GET", "/api/status")
        break
    except (SystemExit, urllib.error.URLError):
        time.sleep(3)

# --- data views ---------------------------------------------------------------------------
VIEWS = {
    "portal-logs": ("logs-portal-*", "Portal logs"),
    "portal-traces": ("traces-portal-*", "Portal traces (spans)"),
    # Spans and logs share ECS names (trace.id, span.id, service.name), so one view over both
    # lets you paste a trace id and see every log line and span of that request together.
    "portal-correlation": ("logs-portal-*,traces-portal-*", "Portal logs + traces (correlate by trace.id)"),
}
for vid, (pattern, name) in VIEWS.items():
    call("POST", "/api/data_views/data_view", {"override": True, "data_view": {
        "id": vid, "title": pattern, "name": name, "timeFieldName": "@timestamp"}})


# --- saved searches -----------------------------------------------------------------------
def search(sid, title, view, query, columns, sort, description=""):
    src = {"query": {"query": query, "language": "kuery"}, "filter": [],
           "indexRefName": "kibanaSavedObjectMeta.searchSourceJSON.index"}
    call("POST", f"/api/saved_objects/search/{sid}?overwrite=true", {
        "attributes": {"title": title, "description": description, "columns": columns, "sort": sort,
                       "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps(src)}},
        "references": [{"name": "kibanaSavedObjectMeta.searchSourceJSON.index", "type": "index-pattern", "id": view}]})


# NB: severity names are the OTel ones in Elasticsearch: WARN (not WARNING); ERROR and CRITICAL are unchanged.
LOGCOLS = ["service.name", "log.level", "message", "trace.id"]
search("portal-s-errors", "Portal: errors and criticals", "portal-logs",
       "log.level : (ERROR or CRITICAL)", LOGCOLS, [["@timestamp", "desc"]],
       "Start here for Scenarios 2 and 3. Copy a trace.id into the correlation search.")
search("portal-s-warnings", "Portal: warnings", "portal-logs", "log.level : WARN", LOGCOLS, [["@timestamp", "desc"]])
search("portal-s-all-logs", "Portal: all logs", "portal-logs", "*", LOGCOLS, [["@timestamp", "desc"]])
search("portal-s-slow-spans", "Portal: slowest spans", "portal-traces", "duration_ms > 50",
       ["service.name", "span.name", "duration_ms", "trace.id"], [["duration_ms", "desc"]],
       "Scenarios 1 and 4: find the slow operation, then follow its trace.id.")
search("portal-s-correlate", "Portal: follow a trace (edit the id)", "portal-correlation",
       'trace.id : "PASTE-TRACE-ID-HERE"', ["service.name", "message", "span.name", "log.level"], [["@timestamp", "asc"]],
       "Replace the placeholder with a trace.id: shows the request's log lines and spans in time order.")

# --- dashboard ----------------------------------------------------------------------------
PANELS = [("portal-s-errors", 0, 0, 24, 12), ("portal-s-slow-spans", 0, 12, 24, 12), ("portal-s-all-logs", 0, 24, 24, 14)]
call("POST", "/api/saved_objects/dashboard/portal-logs-overview?overwrite=true", {
    "attributes": {
        "title": "Portal: logs and traces overview",
        "description": "Errors, slowest spans and the live log stream. Open a row and copy its trace.id into 'Portal: follow a trace'.",
        "timeRestore": False,
        "optionsJSON": json.dumps({"useMargins": True, "syncColors": False, "syncCursor": True, "syncTooltips": False, "hidePanelTitles": False}),
        "panelsJSON": json.dumps([{
            "version": "8.15.3", "type": "search", "panelIndex": str(i),
            "gridData": {"x": x, "y": y, "w": w, "h": h, "i": str(i)},
            "embeddableConfig": {}, "panelRefName": f"panel_{i}"} for i, (_, x, y, w, h) in enumerate(PANELS)]),
        "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []})}},
    "references": [{"name": f"panel_{i}", "type": "search", "id": sid} for i, (sid, *_r) in enumerate(PANELS)]})
print("kibana bootstrap complete")
