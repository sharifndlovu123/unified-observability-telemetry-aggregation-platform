#!/usr/bin/env python3
"""Renders the Collector's routing config from on/off environment flags.

Why this exists: the Collector can't build a pipeline's exporter list from booleans, and
we want "EXPORT_PROMETHEUS=false" to be all it takes to stop sending there. This runs once
(compose service `otel-config`) before the Collector starts and writes
/generated/routing.yaml containing:
  * the exporter definitions of ENABLED destinations only (from exporters.<name>.yaml), and
  * one pipeline per signal listing only the enabled exporters that handle that signal.
Disabled destinations are never loaded, so e.g. Datadog needs no API key until enabled.

To add a destination: drop exporters.<name>.yaml next to this file, add a row to
DESTINATIONS, add an EXPORT_<NAME> flag in docker-compose.yml. The app is not touched.
"""
import os
import sys
from pathlib import Path

SRC = Path(__file__).parent
OUT = Path(os.environ.get("OUT_FILE", "/generated/routing.yaml"))

# flag name -> (exporter id used in pipelines, signals it receives, default flag value)
DESTINATIONS = {
    "debug": ("debug", ("metrics", "logs", "traces"), "true"),
    "prometheus": ("prometheus", ("metrics",), "true"),
    "elasticsearch": ("elasticsearch", ("logs", "traces"), "true"),
    "logstash": ("otlphttp/logstash", ("logs",), "true"),
}
QUEUE_DIR = Path("/queue")  # persistent exporter queue volume (file_storage extension)
COLLECTOR_UID = 10001       # the contrib image runs as this non-root user
# Receivers and processor chain per signal (order matters: memory_limiter first, batch last).
PIPELINES = {
    "metrics": (["otlp", "hostmetrics"], ["memory_limiter", "resource", "batch"]),
    "logs": (["otlp"], ["memory_limiter", "resource", "batch"]),
    "traces": (["otlp"], ["memory_limiter", "resource", "filter/noise", "batch"]),
}


def flag(name, default):
    return os.environ.get(f"EXPORT_{name.upper()}", default).strip().lower() in ("1", "true", "yes", "on")


def fragment_sections(path):
    """Split a fragment into {top-level key: indented body lines} (e.g. exporters, extensions)."""
    sections, current = {}, None
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            current = line.rstrip(":").strip()
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return sections


def main():
    enabled = {n: d for n, d in DESTINATIONS.items() if flag(n, d[2])}
    merged = {}
    for name in enabled:
        frag = SRC / f"exporters.{name}.yaml"
        if not frag.exists():
            sys.exit(f"EXPORT_{name.upper()} is on but {frag.name} does not exist")
        for section, body in fragment_sections(frag).items():
            merged.setdefault(section, []).extend(body)
    lines = []
    for section, body in merged.items():
        lines += [f"{section}:", *body, ""]
    extension_ids = [l.strip().rstrip(":") for l in merged.get("extensions", []) if l.startswith("  ") and not l.startswith("   ")]
    lines += ["service:", f"  extensions: [{', '.join(['health_check', *extension_ids])}]", "  pipelines:"]
    for signal, (receivers, procs) in PIPELINES.items():
        targets = [d[0] for d in enabled.values() if signal in d[1]] or ["nop"]
        lines += [
            f"    {signal}:",
            f"      receivers: [{', '.join(receivers)}]",
            f"      processors: [{', '.join(procs)}]",
            f"      exporters: [{', '.join(targets)}]",
        ]
        print(f"{signal:8s} -> {', '.join(targets)}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    if QUEUE_DIR.exists():  # named volumes start root-owned; the Collector is not root
        os.chown(QUEUE_DIR, COLLECTOR_UID, COLLECTOR_UID)


if __name__ == "__main__":
    main()
