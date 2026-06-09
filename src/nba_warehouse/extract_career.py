"""Phase 3 extractor — per-player career fan-out (playercareerstats).

For each player, playercareerstats returns SeasonTotalsRegularSeason: one row per
player per season per team (traded players get a row per team). This is the source
grain for fact_player_season and the player<->team<->season relationship.

Performance: the API calls are the floor (~0.8s/player politeness), but the writes
are batched — rows and checkpoints for many players are bulk-inserted every
BATCH_PLAYERS instead of per player — so warehouse round-trips drop ~100x. Player
list comes from bronze.commonallplayers; each player is checkpointed in
ops.crawl_state, so the run is resumable.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

from nba_api.stats.endpoints import playercareerstats

from . import warehouse as wh

API_DELAY_SECONDS = 0.8
BATCH_PLAYERS = 150
ENDPOINT = "playercareerstats"
RESULT_SET = "SeasonTotalsRegularSeason"
TABLE = f"{ENDPOINT}__{RESULT_SET}"


def player_ids(cur, min_to_year: int) -> list[int]:
    cur.execute(
        "SELECT DISTINCT cast(PERSON_ID as bigint) "
        "FROM bronze.`commonallplayers__CommonAllPlayers` "
        f"WHERE try_cast(TO_YEAR as int) >= {int(min_to_year)} ORDER BY 1"
    )
    return [r[0] for r in cur.fetchall()]


def _done_hashes(cur) -> set[str]:
    # 'empty' = the API has no playercareerstats data for this player (returns {});
    # treat it as resolved so it is not retried on every run.
    cur.execute(
        f"SELECT param_hash FROM ops.crawl_state WHERE endpoint = '{ENDPOINT}' "
        "AND status IN ('done', 'empty')"
    )
    return {r[0] for r in cur.fetchall()}


def _flush(cur, rows: list[dict], source_cols: list[str], checkpoints: list[tuple]) -> None:
    """Bulk-insert buffered bronze rows and crawl_state checkpoints."""
    if rows:
        wh.ensure_table(cur, TABLE, source_cols)
        all_cols = source_cols + wh.LINEAGE_COLS
        col_list = ", ".join(f"`{c}`" for c in all_cols)
        for i in range(0, len(rows), 500):
            chunk = rows[i : i + 500]
            values = [
                "(" + ", ".join(wh._sql_literal(r.get(c)) for c in all_cols) + ")"
                for r in chunk
            ]
            cur.execute(f"INSERT INTO bronze.`{TABLE}` ({col_list}) VALUES {', '.join(values)}")
    if checkpoints:
        vals = [
            f"('{ENDPOINT}', {wh._sql_literal(ph)}, 'ALL', {cnt}, '{status}', current_timestamp())"
            for ph, cnt, status in checkpoints
        ]
        cur.execute(
            "INSERT INTO ops.crawl_state (endpoint, param_hash, season, result_count, status, updated_at) "
            f"VALUES {', '.join(vals)}"
        )


def run(*, min_to_year: int = 1980, run_id: str | None = None) -> dict:
    run_id = run_id or uuid.uuid4().hex[:12]
    summary = {"players": 0, "rows": 0, "skipped": 0, "empty": 0, "failed": 0}

    with wh.connection() as conn:
        cur = conn.cursor()
        wh.ensure_ops_tables(cur)
        ids = player_ids(cur, min_to_year)
        done = _done_hashes(cur)
        total = len(ids)
        summary["players"] = total

        buf_rows: list[dict] = []
        buf_ckpt: list[tuple] = []
        source_cols: list[str] = []
        processed = 0

        for i, pid in enumerate(ids, 1):
            params = {"player_id": pid}
            ph = wh.param_hash(params)
            if ph in done:
                summary["skipped"] += 1
                continue
            time.sleep(API_DELAY_SECONDS)
            try:
                df = playercareerstats.PlayerCareerStats(player_id=pid, timeout=60).get_data_frames()[0]
            except KeyError:
                # API returned an empty body ({}) for this player — no career data.
                buf_ckpt.append((ph, 0, "empty"))
                summary["empty"] += 1
                continue
            except Exception as e:
                buf_ckpt.append((ph, 0, f"failed:{type(e).__name__}"))
                summary["failed"] += 1
                continue

            if not source_cols and len(df.columns):
                source_cols = [str(c) for c in df.columns]
            ingested_at = datetime.now(timezone.utc).isoformat()
            params_json = json.dumps(params, sort_keys=True, default=str)
            for rec in df.to_dict("records"):
                rec.update({
                    "_endpoint": ENDPOINT, "_result_set": RESULT_SET,
                    "_params_json": params_json, "_param_hash": ph,
                    "_ingested_at": ingested_at, "_run_id": run_id,
                })
                buf_rows.append(rec)
            buf_ckpt.append((ph, len(df), "done"))
            summary["rows"] += len(df)
            processed += 1

            if processed % BATCH_PLAYERS == 0:
                _flush(cur, buf_rows, source_cols, buf_ckpt)
                buf_rows, buf_ckpt = [], []
                print(f"[career] {i}/{total} players seen, {summary['rows']} rows", flush=True)

        _flush(cur, buf_rows, source_cols, buf_ckpt)
        print(f"[career] DONE {total}/{total} players, {summary['rows']} rows", flush=True)

    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
