#!/usr/bin/env bash
# Scenario 6: telemetry pipeline failures
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python3 scenarios/run.py 6
