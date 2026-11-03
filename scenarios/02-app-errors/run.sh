#!/usr/bin/env bash
# Scenario 2: application errors
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python3 scenarios/run.py 2
