"""Team Elo power ratings — one row per team per game (pre/post game).

The Elo algorithm and tunables are ported verbatim from the original dbt Python
model (dbt/models/marts/analytics/analytics_team_elo.py). dbt Python models
require Python-capable compute, which this serverless-SQL-only workspace does not
have, so the computation runs here (works anywhere) and materializes
gold.analytics_team_elo. dbt governs the result as a tested source. Swap back to a
native dbt Python model once a Python cluster is available — the math is identical.

This is proprietary derived IP: Elo is our model computed from public game results.
"""

from __future__ import annotations

import math

import pandas as pd

from . import warehouse as wh

# --- model parameters (the proprietary knobs) -----------------------------
BASE = 1500.0        # rating every team starts at
K = 20.0             # update speed
HOME_ADV = 100.0     # home-court bump, in Elo points, applied to expectation
REGRESS = 0.25       # fraction pulled back toward BASE at each season boundary

TABLE = "gold.analytics_team_elo"

_SCHEMA = [
    ("team_game_sk", "STRING"), ("game_id", "STRING"), ("game_date", "DATE"),
    ("season_key", "STRING"), ("team_id", "BIGINT"), ("opponent_team_id", "BIGINT"),
    ("is_home", "BOOLEAN"), ("elo_pre", "DOUBLE"), ("opp_elo_pre", "DOUBLE"),
    ("win_expected", "DOUBLE"), ("won", "INT"), ("margin", "INT"),
    ("elo_change", "DOUBLE"), ("elo_post", "DOUBLE"),
]


def _expected(r_team: float, r_opp: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((r_opp - r_team) / 400.0))


def _mov_multiplier(margin: int, elo_diff: float) -> float:
    return math.log(abs(margin) + 1.0) * (2.2 / (abs(elo_diff) * 0.001 + 2.2))


def compute(f: pd.DataFrame) -> pd.DataFrame:
    opp_pts = f[["game_id", "team_id", "points"]].rename(
        columns={"team_id": "opponent_team_id", "points": "opp_points"}
    )
    g = f.merge(opp_pts, on=["game_id", "opponent_team_id"], how="left")
    g = g.sort_values(["game_date", "game_id", "team_id"]).reset_index(drop=True)

    ratings: dict[int, float] = {}
    last_year: dict[int, object] = {}  # regress only across season *years*, not RS->PO
    rows = []

    for game_id, grp in g.groupby("game_id", sort=False):
        if len(grp) != 2:
            continue
        a, b = grp.iloc[0], grp.iloc[1]
        pre = {}
        for side in (a, b):
            tid = int(side["team_id"])
            r = ratings.get(tid, BASE)
            # Regular Season and Playoffs share a season_start_year, so a team is
            # not regressed between its last RS game and its first playoff game.
            if last_year.get(tid) not in (None, side["season_start_year"]):
                r = BASE + (1.0 - REGRESS) * (r - BASE)
            pre[tid] = r
            last_year[tid] = side["season_start_year"]
        for side, other in ((a, b), (b, a)):
            tid, oid = int(side["team_id"]), int(other["team_id"])
            r_team, r_opp = pre[tid], pre[oid]
            adv = HOME_ADV if bool(side["is_home"]) else 0.0
            exp = _expected(r_team + adv, r_opp + (HOME_ADV - adv))
            won = int(side["win_flag"]) if pd.notna(side["win_flag"]) else None
            margin = int(side["points"] - side["opp_points"])
            mult = _mov_multiplier(margin, (r_team + adv) - r_opp)
            change = K * mult * ((won if won is not None else exp) - exp)
            post = r_team + change
            ratings[tid] = post
            rows.append({
                "team_game_sk": side["team_game_sk"], "game_id": game_id,
                "game_date": side["game_date"], "season_key": side["season_key"],
                "team_id": tid, "opponent_team_id": oid, "is_home": bool(side["is_home"]),
                "elo_pre": round(r_team, 2), "opp_elo_pre": round(r_opp, 2),
                "win_expected": round(exp, 4), "won": won, "margin": margin,
                "elo_change": round(change, 2), "elo_post": round(post, 2),
            })
    return pd.DataFrame(rows)


def _lit(v, sqltype: str) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "NULL"
    if sqltype in ("DOUBLE", "BIGINT", "INT"):
        return str(v)
    if sqltype == "BOOLEAN":
        return "true" if v else "false"
    return "'" + str(v).replace("'", "''") + "'"  # STRING / DATE


def run(chunk_size: int = 500) -> int:
    with wh.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT f.team_game_sk, f.game_id, f.game_date, f.season_key, "
            "s.season_start_year, f.team_id, f.opponent_team_id, f.is_home, "
            "f.points, f.win_flag "
            "FROM gold.fact_team_game f JOIN gold.dim_season s USING (season_key)"
        )
        cols = [d[0] for d in cur.description]
        f = pd.DataFrame(cur.fetchall(), columns=cols)

        out = compute(f)

        col_defs = ", ".join(f"`{c}` {t}" for c, t in _SCHEMA)
        cur.execute(f"CREATE OR REPLACE TABLE {TABLE} ({col_defs})")
        names = ", ".join(f"`{c}`" for c, _ in _SCHEMA)
        recs = out.to_dict("records")
        for i in range(0, len(recs), chunk_size):
            vals = []
            for r in recs[i : i + chunk_size]:
                vals.append("(" + ", ".join(_lit(r[c], t) for c, t in _SCHEMA) + ")")
            cur.execute(f"INSERT INTO {TABLE} ({names}) VALUES {', '.join(vals)}")
        return len(recs)


if __name__ == "__main__":
    print(f"wrote {run()} rows to {TABLE}")
