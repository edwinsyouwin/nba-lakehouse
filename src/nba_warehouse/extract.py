"""Phase 1 extractor — the reference + game spine.

Crawls (in dependency order):
  1. static teams                              -> bronze.static_teams__Teams
  2. commonallplayers (all players, once)      -> bronze.commonallplayers__CommonAllPlayers
  3. leaguegamelog(season, season_type)        -> bronze.leaguegamelog__LeagueGameLog
     for each requested season and season type (one row per team per game).

Players are pulled once (season-independent) so player_id stays unique across a
multi-season backfill. Game logs are pulled per season/type.

Politeness: a global delay between API calls; each slice is checkpointed in
ops.crawl_state so re-runs skip already-captured slices (idempotent).
"""

from __future__ import annotations

import time
import uuid

import pandas as pd
from nba_api.stats.endpoints import commonallplayers, leaguegamelog
from nba_api.stats.static import teams as static_teams

from . import warehouse as wh

API_DELAY_SECONDS = 0.8
SEASON_TYPES = ["Regular Season", "Playoffs"]


def _teams_df() -> pd.DataFrame:
    df = pd.DataFrame(static_teams.get_teams())
    df.columns = [c.upper() for c in df.columns]
    return df


def run(seasons: list[str], *, run_id: str | None = None, force: bool = False) -> dict:
    """Extract the spine for one or more seasons. Returns a summary dict."""
    run_id = run_id or uuid.uuid4().hex[:12]
    summary: dict[str, int] = {}

    with wh.connection() as conn:
        cur = conn.cursor()
        wh.ensure_ops_tables(cur)

        def capture(endpoint, result_set, df, params, season_label, key=None):
            ph = wh.param_hash(params)
            label = key or endpoint
            if not force and wh.is_done(cur, endpoint, ph):
                summary[f"{label}:skipped"] = len(df)
                return
            n = wh.load_result_set(
                cur,
                endpoint=endpoint,
                result_set=result_set,
                df=df,
                params=params,
                run_id=run_id,
                replace=force,
            )
            wh.mark_state(cur, endpoint, ph, season_label, n, "done")
            summary[label] = summary.get(label, 0) + n

        # 1. static teams (no API call)
        capture("static_teams", "Teams", _teams_df(), {"source": "nba_api.static"}, "ALL")

        # 2. all players, once (season-independent slice)
        time.sleep(API_DELAY_SECONDS)
        cap = commonallplayers.CommonAllPlayers(
            is_only_current_season=0, league_id="00", season="2024-25", timeout=60
        )
        capture(
            "commonallplayers",
            "CommonAllPlayers",
            cap.get_data_frames()[0],
            {"is_only_current_season": 0, "league_id": "00"},  # no season -> one slice
            "ALL",
        )

        # 3. team-game rows per season / season type
        for season in seasons:
            for season_type in SEASON_TYPES:
                time.sleep(API_DELAY_SECONDS)
                gl = leaguegamelog.LeagueGameLog(
                    season=season,
                    season_type_all_star=season_type,
                    league_id="00",
                    timeout=60,
                )
                capture(
                    "leaguegamelog",
                    "LeagueGameLog",
                    gl.get_data_frames()[0],
                    {"season": season, "season_type": season_type, "league_id": "00"},
                    season,
                    key=f"leaguegamelog:{season}:{season_type}",
                )

    return summary
