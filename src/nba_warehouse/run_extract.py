"""Entrypoint for the extractor. Usage:

    python -m nba_warehouse.run_extract --season 2023-24
    python -m nba_warehouse.run_extract --seasons 2015-16:2024-25
    python -m nba_warehouse.run_extract --season 2023-24 --season 2022-23
    python -m nba_warehouse.run_extract --seasons 2015-16:2024-25 --force
"""

from __future__ import annotations

import argparse
import json

from . import extract


def _season_label(start_year: int) -> str:
    return f"{start_year}-{str((start_year + 1) % 100).zfill(2)}"


def _expand_range(spec: str) -> list[str]:
    """'2015-16:2024-25' -> ['2015-16', ..., '2024-25']."""
    start, end = spec.split(":")
    start_year = int(start.split("-")[0])
    end_year = int(end.split("-")[0])
    return [_season_label(y) for y in range(start_year, end_year + 1)]


def main() -> None:
    p = argparse.ArgumentParser(description="NBA lakehouse extractor")
    p.add_argument("--season", action="append", default=[], help="e.g. 2023-24 (repeatable)")
    p.add_argument("--seasons", help="inclusive range, e.g. 2015-16:2024-25")
    p.add_argument("--force", action="store_true", help="re-pull even if checkpointed")
    args = p.parse_args()

    seasons: list[str] = list(args.season)
    if args.seasons:
        seasons += _expand_range(args.seasons)
    if not seasons:
        p.error("provide --season and/or --seasons")
    seasons = sorted(set(seasons))

    summary = extract.run(seasons, force=args.force)
    print(json.dumps({"seasons": seasons, "loaded": summary}, indent=2))


if __name__ == "__main__":
    main()
