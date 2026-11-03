#!/usr/bin/env bash
# Scenario 3: background processing failure
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python3 scenarios/run.py 3
