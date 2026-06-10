#!/usr/bin/env bash
# Regenerate reports/first4_trend.html. Uses the warehouse when the serverless
# daily quota allows (refreshing reports/_raw.csv); otherwise falls back to cache.
# Safe to run on a schedule.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
exec ./.venv/bin/python reports/first4_trend.py
