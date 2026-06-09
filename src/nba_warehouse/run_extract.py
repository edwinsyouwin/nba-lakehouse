"""Entrypoint for the extractor. Usage:

    python -m nba_warehouse.run_extract --season 2023-24
    python -m nba_warehouse.run_extract --seasons 2015-16:2024-25
    python -m nba_warehouse.run_extract --season 2023-24 --season 2022-23
    python -m nba_warehouse.run_extract --seasons 2015-16:2024-25 --force
"""

from __future__ import annotations

import argparse
import json

from . import extract, extract_detail, extract_roster


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
    p.add_argument("--detail-recent", type=int, help="fan out per-game detail for the N most recent games")
    p.add_argument("--detail-game", action="append", default=[], help="game_id for detail fan-out (repeatable)")
    p.add_argument("--detail-season", action="append", default=[], help="backfill all games' detail for a season, e.g. 2015-16 (repeatable)")
    p.add_argument("--detail-seasons", help="inclusive season range for detail, e.g. 2015-16:2024-25")
    p.add_argument("--roster-season", action="append", default=[], help="pull team roster + coaches for a season, e.g. 2023-24 (repeatable)")
    p.add_argument("--roster-seasons", help="inclusive season range for roster + coaches, e.g. 2015-16:2024-25")
    p.add_argument("--force", action="store_true", help="re-pull even if checkpointed")
    args = p.parse_args()

    out: dict = {}

    seasons: list[str] = list(args.season)
    if args.seasons:
        seasons += _expand_range(args.seasons)
    if seasons:
        seasons = sorted(set(seasons))
        out["spine"] = {"seasons": seasons, "loaded": extract.run(seasons, force=args.force)}

    detail_seasons: list[str] = list(args.detail_season)
    if args.detail_seasons:
        detail_seasons += _expand_range(args.detail_seasons)

    if args.detail_recent or args.detail_game or detail_seasons:
        out["detail"] = extract_detail.run(
            game_ids=args.detail_game or None,
            recent=args.detail_recent,
            seasons=sorted(set(detail_seasons)) or None,
            force=args.force,
        )

    roster_seasons: list[str] = list(args.roster_season)
    if args.roster_seasons:
        roster_seasons += _expand_range(args.roster_seasons)

    if roster_seasons:
        out["roster"] = extract_roster.run(seasons=sorted(set(roster_seasons)), force=args.force)

    if not out:
        p.error(
            "provide --season/--seasons and/or --detail-recent/--detail-game/"
            "--detail-season and/or --roster-season/--roster-seasons"
        )

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
