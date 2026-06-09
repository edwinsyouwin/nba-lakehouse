"""Phase 2 extractor — per-game detail fan-out.

For each game_id:
  * boxscoretraditionalv3 [PlayerStats]  -> bronze.boxscoretraditionalv3__PlayerStats
  * boxscoreadvancedv3    [PlayerStats]  -> bronze.boxscoreadvancedv3__PlayerStats
  * playbyplayv3          [PlayByPlay]   -> bronze.playbyplayv3__PlayByPlay
    (PBP carries shot coordinates, so fact_shot derives from it — no separate
     shot-chart call needed.)

This is the same fan-out the daily/backfill jobs use; here we run it for a bounded
set of game_ids (e.g. the most recent N games) to keep the demo slice fast.
"""

from __future__ import annotations

import time
import uuid

from nba_api.stats.endpoints import (
    boxscoreadvancedv3,
    boxscoretraditionalv3,
    playbyplayv3,
)

from . import warehouse as wh

API_DELAY_SECONDS = 0.8

# endpoint -> (nba_api class, result_set name, dataframe index)
DETAIL_ENDPOINTS = {
    "boxscoretraditionalv3": (boxscoretraditionalv3.BoxScoreTraditionalV3, "PlayerStats", 0),
    "boxscoreadvancedv3": (boxscoreadvancedv3.BoxScoreAdvancedV3, "PlayerStats", 0),
    "playbyplayv3": (playbyplayv3.PlayByPlayV3, "PlayByPlay", 0),
}


def recent_game_ids(cur, limit: int) -> list[str]:
    cur.execute(f"SELECT game_id FROM gold.dim_game ORDER BY game_date DESC LIMIT {int(limit)}")
    return [r[0] for r in cur.fetchall()]


def run(*, game_ids: list[str] | None = None, recent: int | None = None,
        run_id: str | None = None, force: bool = False) -> dict:
    run_id = run_id or uuid.uuid4().hex[:12]
    summary: dict[str, int] = {}

    with wh.connection() as conn:
        cur = conn.cursor()
        wh.ensure_ops_tables(cur)

        ids = list(game_ids or [])
        if recent:
            ids += recent_game_ids(cur, recent)
        ids = sorted(set(ids))
        summary["games"] = len(ids)

        for gid in ids:
            for endpoint, (klass, result_set, df_idx) in DETAIL_ENDPOINTS.items():
                params = {"game_id": gid}
                ph = wh.param_hash(params)
                if not force and wh.is_done(cur, endpoint, ph):
                    summary[f"{endpoint}:skipped"] = summary.get(f"{endpoint}:skipped", 0) + 1
                    continue
                time.sleep(API_DELAY_SECONDS)
                df = klass(game_id=gid, timeout=60).get_data_frames()[df_idx]
                n = wh.load_result_set(
                    cur,
                    endpoint=endpoint,
                    result_set=result_set,
                    df=df,
                    params=params,
                    run_id=run_id,
                )
                wh.mark_state(cur, endpoint, ph, gid, n, "done")
                summary[endpoint] = summary.get(endpoint, 0) + n

    return summary
