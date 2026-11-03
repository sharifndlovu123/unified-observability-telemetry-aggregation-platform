#!/usr/bin/env bash
# Scenario 1: application performance degradation
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python3 scenarios/run.py 1
