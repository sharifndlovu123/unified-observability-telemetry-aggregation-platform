#!/usr/bin/env bash
# Scenario 5: adding a monitoring destination
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python3 scenarios/run.py 5
