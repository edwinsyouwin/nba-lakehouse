#!/usr/bin/env bash
# Regenerate the reports. Uses the warehouse when the serverless daily quota
# allows (refreshing the raw caches); otherwise falls back to cache. Safe to run
# on a schedule.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
PY=./.venv/bin/python
"$PY" reports/first4_trend.py
"$PY" reports/elo_calibration.py
