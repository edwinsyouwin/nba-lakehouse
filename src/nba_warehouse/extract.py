"""Phase 1 extractor — the reference + game spine for a single season.

Crawls (in dependency order):
  1. static teams                          -> bronze.static_teams
  2. commonallplayers(season)              -> bronze.commonallplayers__CommonAllPlayers
  3. leaguegamelog(season, season_type)    -> bronze.leaguegamelog__LeagueGameLog
     (one row per team per game = the grain of fact_team_game)

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
SEASON_TYPES = {"Regular Season": "leaguegamelog"}


def _teams_df() -> pd.DataFrame:
    df = pd.DataFrame(static_teams.get_teams())
    df.columns = [c.upper() for c in df.columns]
    return df


def run(season: str, *, run_id: str | None = None, force: bool = False) -> dict:
    """Extract the spine for one season. Returns a summary dict."""
    run_id = run_id or uuid.uuid4().hex[:12]
    summary: dict[str, int] = {}

    with wh.connection() as conn:
        cur = conn.cursor()
        wh.ensure_ops_tables(cur)

        def capture(endpoint, result_set, df, params, season_label):
            ph = wh.param_hash(params)
            if not force and wh.is_done(cur, endpoint, ph):
                summary[f"{endpoint}:skipped"] = len(df)
                return
            n = wh.load_result_set(
                cur,
                endpoint=endpoint,
                result_set=result_set,
                df=df,
                params=params,
                run_id=run_id,
            )
            wh.mark_state(cur, endpoint, ph, season_label, n, "done")
            summary[endpoint] = n

        # 1. static teams (no API call, no season)
        capture("static_teams", "Teams", _teams_df(), {"source": "nba_api.static"}, "ALL")

        # 2. players active in the season
        time.sleep(API_DELAY_SECONDS)
        cap = commonallplayers.CommonAllPlayers(
            is_only_current_season=1, league_id="00", season=season, timeout=60
        )
        capture(
            "commonallplayers",
            "CommonAllPlayers",
            cap.get_data_frames()[0],
            {"season": season, "is_only_current_season": 1, "league_id": "00"},
            season,
        )

        # 3. team-game rows for the season
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
            )

        cur.close()

    return summary
