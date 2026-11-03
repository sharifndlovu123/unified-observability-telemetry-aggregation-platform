#!/usr/bin/env python3
"""Renders the Collector's routing config from on/off environment flags.

Why this exists: the Collector can't build a pipeline's exporter list from booleans, and
we want "EXPORT_PROMETHEUS=false" to be all it takes to stop sending there. This runs once
(compose service `otel-config`) before the Collector starts and writes
/generated/routing.yaml containing:
  * the exporter (and extension) definitions of ENABLED destinations only, and
  * one pipeline per signal listing only the enabled exporters that handle that signal.
Disabled destinations are never loaded, so e.g. a destination needing an API key costs nothing
until it is enabled.

Destinations are DISCOVERED, not hard-coded: every exporters.<name>.yaml next to this file is
one, and its first lines declare how it is routed:
    # routing: exporter=<id used in pipelines> signals=<csv of metrics,logs,traces> default=<true|false>
Enabled when EXPORT_<NAME> is truthy (falling back to `default`) or <name> is listed in
EXPORT_EXTRA. To add a destination: drop in exporters.<name>.yaml. No Python and no app change.
"""
import os
import re
import sys
from pathlib import Path

SRC = Path(__file__).parent
OUT = Path(os.environ.get("OUT_FILE", "/generated/routing.yaml"))

SIGNALS = ("metrics", "logs", "traces")
QUEUE_DIR = Path("/queue")  # persistent exporter queue volume (file_storage extension)
COLLECTOR_UID = 10001       # the contrib image runs as this non-root user
# Receivers and processor chain per signal (order matters: memory_limiter first, batch last).
PIPELINES = {
    "metrics": (["otlp", "hostmetrics"], ["memory_limiter", "resource", "batch"]),
    "logs": (["otlp"], ["memory_limiter", "resource", "batch"]),
    "traces": (["otlp"], ["memory_limiter", "resource", "filter/noise", "batch"]),
}


def truthy(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def discover():
    """{name: (exporter id, signals, default)} read from each fragment's `# routing:` header."""
    found = {}
    for frag in sorted(SRC.glob("exporters.*.yaml")):
        name = frag.name.split(".")[1]
        m = re.search(r"^# routing:\s*(.+)$", frag.read_text(), re.M)
        if not m:
            sys.exit(f"{frag.name} has no '# routing: exporter=... signals=... default=...' header")
        meta = dict(kv.split("=", 1) for kv in m.group(1).split())
        signals = tuple(meta["signals"].split(","))
        if not set(signals) <= set(SIGNALS):
            sys.exit(f"{frag.name}: unknown signal in {signals}")
        found[name] = (meta["exporter"], signals, meta.get("default", "false"))
    return found


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
    extra = {x.strip() for x in os.environ.get("EXPORT_EXTRA", "").split(",") if x.strip()}
    enabled = {
        n: d for n, d in discover().items()
        if truthy(os.environ.get(f"EXPORT_{n.upper()}", d[2])) or n in extra
    }
    merged = {}
    for name in enabled:
        frag = SRC / f"exporters.{name}.yaml"
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
