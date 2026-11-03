#!/usr/bin/env python3
"""One-shot Elasticsearch bootstrap (idempotent). Runs after ES is healthy.

Creates: the kibana_system password, a 7-day retention (ILM) policy, data-stream index
templates for logs-portal-* / traces-portal-*, and two least-privilege users:
  portal_writer  append-only on those streams + read-only cluster `monitor` (Collector, Logstash)
  grafana_reader read-only on logs-*/traces-* + cluster `monitor` for its health check (Grafana)
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

ES = os.environ.get("ES_URL", "http://elasticsearch:9200")
AUTH = "Basic " + base64.b64encode(f"elastic:{os.environ['ELASTIC_PASSWORD']}".encode()).decode()


def call(method, path, body=None):
    req = urllib.request.Request(ES + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": AUTH, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> {e.code}: {e.read().decode()[:300]}")


for _ in range(60):
    try:
        call("GET", "/_cluster/health")
        break
    except SystemExit:
        time.sleep(2)

call("POST", "/_security/user/kibana_system/_password", {"password": os.environ["KIBANA_SYSTEM_PASSWORD"]})

# Demo retention: roll over daily, delete after 7 days. (Not a production archival policy.)
call("PUT", "/_ilm/policy/portal-retention", {"policy": {"phases": {
    "hot": {"actions": {"rollover": {"max_age": "1d", "max_primary_shard_size": "1gb"}}},
    "delete": {"min_age": "7d", "actions": {"delete": {}}}}}})

# trace.id / span.id are interpolated into links (Grafana -> Kibana) and queries, so only
# well-formed hex IDs are allowed to exist; anything else is removed at ingest.
def drop_unless_hex(field, length):
    parts = field.split(".")
    path = "ctx." + "?.".join(parts)
    return {"remove": {"field": field, "ignore_missing": True, "ignore_failure": True,
                       "if": f"{path} != null && !(({path} instanceof String) && {path}.length() == {length} && {path} ==~ /[0-9a-f]+/)"}}


ID_CHECKS = [drop_unless_hex("trace.id", 32), drop_unless_hex("span.id", 16)]
call("PUT", "/_ingest/pipeline/portal-logs-validate", {
    "description": "Drop malformed trace/span ids from log documents", "processors": ID_CHECKS})

# The Collector's ES exporter writes logs with ECS names (trace.id) but spans in its own
# schema (TraceId, Resource.service.name, Duration in microseconds). This pipeline copies
# span fields to the ECS names so ONE query (trace.id:<id>) matches both logs and spans.
copy = lambda src, dst: {"set": {"field": dst, "copy_from": src, "ignore_empty_value": True, "ignore_failure": True}}
call("PUT", "/_ingest/pipeline/portal-traces-normalise", {
    "description": "Align span field names with ECS log fields for log<->trace correlation",
    "processors": [
        copy("TraceId", "trace.id"), copy("SpanId", "span.id"), copy("ParentSpanId", "span.parent_id"),
        copy("Name", "span.name"), copy("Resource.service.name", "service.name"),
        copy("Resource.deployment.environment", "service.environment"),
        *ID_CHECKS,
        {"script": {"lang": "painless", "ignore_failure": True,
                    "source": "if (ctx.Duration != null) { ctx.duration_ms = ctx.Duration / 1000.0; }"}},
    ]})

# Without explicit types the exporter's fields are dynamically mapped as analysed `text`,
# which cannot be aggregated (log volume by level) and tokenises IDs. Declare the shared
# ECS fields as keyword so filters/terms/aggregations are exact on every stream.
kw = {"type": "keyword"}
MAPPINGS = {"properties": {
    "log": {"properties": {"level": kw}},
    "service": {"properties": {"name": kw, "environment": kw}},
    "trace": {"properties": {"id": kw}},
    "span": {"properties": {"id": kw, "parent_id": kw, "name": kw}},
    "duration_ms": {"type": "double"},
}}

for kind in ("logs", "traces"):
    settings = {"index.lifecycle.name": "portal-retention", "number_of_replicas": 0}
    settings["index.default_pipeline"] = "portal-traces-normalise" if kind == "traces" else "portal-logs-validate"
    call("PUT", f"/_index_template/{kind}-portal", {
        "index_patterns": [f"{kind}-portal-*"],
        "data_stream": {},
        "priority": 500,  # beats Elastic's built-in logs-*-* template (priority 100)
        "template": {"settings": settings, "mappings": MAPPINGS},
    })

# Template changes only affect NEW backing indices, so roll existing streams over to pick
# them up. (Old backing indices keep their old mapping until ILM deletes them; if you change a
# field TYPE during development, delete the data stream: DELETE _data_stream/<name>.)
for stream in ("logs-portal-default", "logs-portal-logstash-default", "traces-portal-default"):
    try:
        call("GET", f"/_data_stream/{stream}")   # fails (404) when the stream doesn't exist yet
    except SystemExit:
        continue
    call("POST", f"/{stream}/_rollover")

# `monitor` is read-only cluster info; Logstash refuses to start without it (health check).
call("PUT", "/_security/role/portal_writer", {"cluster": ["monitor"], "indices": [{
    "names": ["logs-portal-*", "traces-portal-*"],
    "privileges": ["create_doc", "create_index", "auto_configure", "view_index_metadata"]}]})
call("PUT", "/_security/user/portal_writer", {"password": os.environ["ES_WRITER_PASSWORD"], "roles": ["portal_writer"]})
call("PUT", "/_security/role/portal_reader", {"cluster": ["monitor"], "indices": [{
    "names": ["logs-*", "traces-*"], "privileges": ["read", "view_index_metadata"]}]})
call("PUT", "/_security/user/grafana_reader", {"password": os.environ["ES_READER_PASSWORD"], "roles": ["portal_reader"]})
print("elasticsearch bootstrap complete")
