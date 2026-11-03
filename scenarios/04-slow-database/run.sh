#!/usr/bin/env bash
# Scenario 4: database performance
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python3 scenarios/run.py 4
