"""Databricks SQL-warehouse helpers and the Bronze sink.

The documented target ingestion path is land-to-Volume + Auto Loader (see
docs/warehouse/02-source-and-ingestion.md). That path needs a token with Volume /
workspace scope. Until that is in place, this module provides a SQL-warehouse
Bronze sink that works with a SQL-only token: it creates one Bronze table per
endpoint result set (all source columns as STRING, plus lineage columns) and loads
rows idempotently. dbt Silver->Gold is identical regardless of which sink filled
Bronze.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone

import pandas as pd
from databricks import sql

# Lineage columns added to every Bronze row.
LINEAGE_COLS = [
    "_endpoint",
    "_result_set",
    "_params_json",
    "_param_hash",
    "_ingested_at",
    "_run_id",
]


def _cfg() -> dict[str, str]:
    host = os.environ["DATABRICKS_HOST"].replace("https://", "").rstrip("/")
    return {
        "server_hostname": host,
        "http_path": os.environ["DATABRICKS_HTTP_PATH"],
        "access_token": os.environ["DATABRICKS_TOKEN"],
        "catalog": os.environ.get("DATABRICKS_CATALOG", "nba_dev"),
    }


@contextmanager
def connection():
    cfg = _cfg()
    conn = sql.connect(
        server_hostname=cfg["server_hostname"],
        http_path=cfg["http_path"],
        access_token=cfg["access_token"],
        catalog=cfg["catalog"],
        schema="bronze",
    )
    try:
        yield conn
    finally:
        conn.close()


def exec_sql(cur, statement: str):
    cur.execute(statement)


def param_hash(params: dict) -> str:
    blob = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def _sql_literal(v) -> str:
    """Render a value as a SQL STRING literal (everything in Bronze is STRING)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "NULL"
    s = str(v).replace("\\", "\\\\").replace("'", "''")
    return f"'{s}'"


def ensure_table(cur, table: str, source_cols: list[str]) -> None:
    cols = [f"`{c}` STRING" for c in source_cols] + [f"`{c}` STRING" for c in LINEAGE_COLS]
    exec_sql(cur, f"CREATE TABLE IF NOT EXISTS bronze.`{table}` ({', '.join(cols)})")


def load_result_set(
    cur,
    *,
    endpoint: str,
    result_set: str,
    df: pd.DataFrame,
    params: dict,
    run_id: str,
    chunk_size: int = 500,
) -> int:
    """Idempotently load one result-set DataFrame into bronze.<endpoint>__<result_set>.

    Idempotency: delete any rows previously landed for this (endpoint, param_hash)
    slice, then insert. Re-running yields identical Bronze content.
    """
    table = f"{endpoint}__{result_set}"
    source_cols = [str(c) for c in df.columns]
    ensure_table(cur, table, source_cols)

    ph = param_hash(params)
    ingested_at = datetime.now(timezone.utc).isoformat()
    params_json = json.dumps(params, sort_keys=True, default=str)

    exec_sql(
        cur,
        f"DELETE FROM bronze.`{table}` WHERE _endpoint = {_sql_literal(endpoint)} "
        f"AND _param_hash = {_sql_literal(ph)}",
    )
    if df.empty:
        return 0

    all_cols = source_cols + LINEAGE_COLS
    col_list = ", ".join(f"`{c}`" for c in all_cols)
    lineage_vals = [endpoint, result_set, params_json, ph, ingested_at, run_id]

    rows = df.to_dict("records")
    inserted = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        values = []
        for r in chunk:
            cells = [_sql_literal(r.get(c)) for c in source_cols] + [
                _sql_literal(v) for v in lineage_vals
            ]
            values.append(f"({', '.join(cells)})")
        exec_sql(
            cur,
            f"INSERT INTO bronze.`{table}` ({col_list}) VALUES {', '.join(values)}",
        )
        inserted += len(chunk)
    return inserted


def ensure_ops_tables(cur) -> None:
    exec_sql(
        cur,
        "CREATE TABLE IF NOT EXISTS ops.crawl_state ("
        "endpoint STRING, param_hash STRING, season STRING, "
        "result_count INT, status STRING, updated_at TIMESTAMP)",
    )


def is_done(cur, endpoint: str, ph: str) -> bool:
    cur.execute(
        f"SELECT status FROM ops.crawl_state WHERE endpoint = {_sql_literal(endpoint)} "
        f"AND param_hash = {_sql_literal(ph)} AND status = 'done' LIMIT 1"
    )
    return cur.fetchone() is not None


def mark_state(cur, endpoint: str, ph: str, season: str, count: int, status: str) -> None:
    exec_sql(
        cur,
        f"DELETE FROM ops.crawl_state WHERE endpoint = {_sql_literal(endpoint)} "
        f"AND param_hash = {_sql_literal(ph)}",
    )
    exec_sql(
        cur,
        "INSERT INTO ops.crawl_state (endpoint, param_hash, season, result_count, status, updated_at) "
        f"VALUES ({_sql_literal(endpoint)}, {_sql_literal(ph)}, {_sql_literal(season)}, "
        f"{int(count)}, {_sql_literal(status)}, current_timestamp())",
    )
