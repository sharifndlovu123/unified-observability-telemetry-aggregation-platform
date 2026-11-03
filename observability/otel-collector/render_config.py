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

# destination -> (exporter name, signals it receives, default flag value)
DESTINATIONS = {
    "debug": ("debug", ("metrics", "logs", "traces"), "true"),
    "prometheus": ("prometheus", ("metrics",), "true"),
}
# Processor chain per signal (order matters: memory_limiter first, batch last).
PROCESSORS = {
    "metrics": ["memory_limiter", "resource", "batch"],
    "logs": ["memory_limiter", "resource", "batch"],
    "traces": ["memory_limiter", "resource", "filter/noise", "batch"],
}


def flag(name, default):
    return os.environ.get(f"EXPORT_{name.upper()}", default).strip().lower() in ("1", "true", "yes", "on")


def main():
    enabled = {n: d for n, d in DESTINATIONS.items() if flag(n, d[2])}
    lines = ["exporters:"]
    for name in enabled:
        frag = SRC / f"exporters.{name}.yaml"
        if not frag.exists():
            sys.exit(f"EXPORT_{name.upper()} is on but {frag.name} does not exist")
        body = frag.read_text().splitlines()
        start = next(i for i, l in enumerate(body) if l.strip() == "exporters:")
        lines += [l for l in body[start + 1:] if l.strip()]
    lines += ["", "service:", "  pipelines:"]
    for signal, procs in PROCESSORS.items():
        targets = [d[0] for d in enabled.values() if signal in d[1]] or ["nop"]
        lines += [
            f"    {signal}:",
            "      receivers: [otlp]",
            f"      processors: [{', '.join(procs)}]",
            f"      exporters: [{', '.join(targets)}]",
        ]
        print(f"{signal:8s} -> {', '.join(targets)}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
