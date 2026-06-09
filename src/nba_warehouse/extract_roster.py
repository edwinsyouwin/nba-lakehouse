"""Roster + coaching staff extractor — per team-season fan-out.

For each (team_id, season):
  * commonteamroster [CommonTeamRoster] -> bronze.commonteamroster__CommonTeamRoster
  * commonteamroster [Coaches]          -> bronze.commonteamroster__Coaches

CommonTeamRoster returns two result sets from a single call, so one API request
(and one checkpoint per team-season) populates both Bronze tables. The roster
result set is richer than commonallplayers (jersey #, position, height/weight,
college, age, experience, how-acquired); the Coaches result set carries the head
coach + assistant coaches for that team-season.

Note (data quality): the NBA Stats Coaches feed is uneven across seasons — some
team-seasons return only a trainer row, others omit the head coach entirely. We
land it as-is; Silver models flag head vs. assistant via COACH_TYPE/IS_ASSISTANT.

Team ids come from gold.dim_team (so the spine must already be loaded). Politeness
and idempotency mirror extract_detail: a global delay between calls and an
ops.crawl_state checkpoint so re-runs skip already-captured slices.
"""

from __future__ import annotations

import time
import uuid

from nba_api.stats.endpoints import commonteamroster

from . import warehouse as wh

API_DELAY_SECONDS = 0.8
ENDPOINT = "commonteamroster"

# result set name -> dataframe index
RESULT_SETS = {
    "CommonTeamRoster": 0,
    "Coaches": 1,
}


def team_ids(cur) -> list[int]:
    cur.execute("SELECT DISTINCT team_id FROM gold.dim_team ORDER BY team_id")
    return [r[0] for r in cur.fetchall()]


def run(*, seasons: list[str], teams: list[int] | None = None,
        run_id: str | None = None, force: bool = False) -> dict:
    run_id = run_id or uuid.uuid4().hex[:12]
    summary: dict[str, int] = {}

    with wh.connection() as conn:
        cur = conn.cursor()
        wh.ensure_ops_tables(cur)

        tids = teams or team_ids(cur)
        slices = [(t, s) for s in seasons for t in tids]
        total = len(slices)
        summary["team_seasons"] = total

        for i, (tid, season) in enumerate(slices, 1):
            params = {"team_id": tid, "season": season}
            ph = wh.param_hash(params)
            if not force and wh.is_done(cur, ENDPOINT, ph):
                summary[f"{ENDPOINT}:skipped"] = summary.get(f"{ENDPOINT}:skipped", 0) + 1
                continue

            time.sleep(API_DELAY_SECONDS)
            dfs = commonteamroster.CommonTeamRoster(
                team_id=tid, season=season, timeout=60
            ).get_data_frames()

            captured = 0
            for result_set, df_idx in RESULT_SETS.items():
                n = wh.load_result_set(
                    cur,
                    endpoint=ENDPOINT,
                    result_set=result_set,
                    df=dfs[df_idx],
                    params=params,
                    run_id=run_id,
                )
                summary[result_set] = summary.get(result_set, 0) + n
                captured += n

            wh.mark_state(cur, ENDPOINT, ph, season, captured, "done")
            if i % 30 == 0 or i == total:
                print(f"[roster] {i}/{total} team-seasons", flush=True)

    return summary
