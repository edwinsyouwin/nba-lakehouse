"""Entrypoint for the extractor. Usage:

    python -m nba_warehouse.run_extract --season 2023-24
    python -m nba_warehouse.run_extract --season 2023-24 --force

Modes beyond the Phase 1 spine (daily / full backfill) are added in later phases.
"""

from __future__ import annotations

import argparse
import json

from . import extract


def main() -> None:
    p = argparse.ArgumentParser(description="NBA lakehouse extractor")
    p.add_argument("--season", required=True, help="e.g. 2023-24")
    p.add_argument("--force", action="store_true", help="re-pull even if checkpointed")
    args = p.parse_args()

    summary = extract.run(args.season, force=args.force)
    print(json.dumps({"season": args.season, "loaded": summary}, indent=2))


if __name__ == "__main__":
    main()
