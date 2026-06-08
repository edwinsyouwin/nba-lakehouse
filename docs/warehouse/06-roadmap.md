# 06 — Implementation Roadmap

The ordered, checkable build plan. Each phase has **deliverables** and
**acceptance criteria** (what must be true to call it done). Tools are locked:
**Auto Loader → Bronze**, **dbt Core (serverless SQL) → Silver/Gold**, **Lakeflow
Job** orchestration, **DAB** for IaC.

---

## Phase 0 — Foundations
*Goal: a deployable, empty platform skeleton.*

**Steps**
1. Create Unity Catalog objects: catalog `nba`; schemas `bronze`, `silver`, `gold`,
   `feature`, `ml`, `ops`; volume `nba.ops.landing`. (Mirror as `nba_dev`.)
2. Initialize the **DAB** (`databricks.yml`) with `dev` + `prod` targets and the
   serverless warehouse id as a variable.
3. Scaffold `src/nba_warehouse/` (package, deps via Poetry — repo already uses it).
4. Scaffold the **dbt project** (`dbt/`): `dbt_project.yml`, `profiles` template,
   `packages.yml` (dbt_utils, dbt_expectations), `generate_schema_name` macro.
5. Wire **auth**: a service principal + secret scope for the jobs; dbt task uses
   identity auth (no token in repo).
6. CI: extend CircleCI with `bundle validate`, `dbt parse`, `sqlfluff`.

**Acceptance**
- `databricks bundle validate` passes; `databricks bundle deploy --target dev`
  creates the (empty) job/pipeline.
- `dbt debug` connects to the serverless warehouse and sees catalog `nba_dev`.

---

## Phase 1 — Reference & game spine
*Goal: end-to-end thin slice — one season flows API → Gold.*

**Steps**
1. `registry.py`: derive endpoint/result-set/column/param metadata from `nba_api`;
   persist to `ops.endpoint_registry`; generate dbt `_sources.yml`.
2. Extractor v1: seed static teams/players; crawl `commonallplayers`,
   `scheduleleaguev2`/`leaguegamefinder` for **one season**; land JSON to the Volume
   with lineage columns + `ops.crawl_state`.
3. Bronze pipeline: Auto Loader streaming tables for the reference + games result
   sets; `_raw_api_responses` archive.
4. dbt: `stg_*` for those Bronze tables; `snap_team`/`snap_player`;
   `int_games__deduped`.
5. dbt Gold: `dim_date`, `dim_season`, `dim_team`, `dim_player`, `dim_game`,
   `fact_team_game`.

**Acceptance**
- For the chosen season, `fact_team_game` row count = 2 × games; every FK passes
  `relationships`; `dbt build` green.
- Re-running extract + `dbt build` changes nothing (idempotent).

---

## Phase 2 — Game detail (the analytics core)
*Goal: box scores, play-by-play, shots modeled to Gold.*

**Steps**
1. Extend the crawler with per-`game_id` fan-out: `boxscore*v3` (traditional,
   advanced, scoring, usage, four-factors, hustle, player-track, matchups),
   `playbyplayv3`, `shotchartdetail`, `gamerotation`.
2. Bronze tables for all the above.
3. dbt `int_player_game__unified` (join box-score variants); `int_shots__enriched`.
4. dbt Gold facts: `fact_player_game`, `fact_play_by_play`, `fact_shot`,
   `fact_lineup_stint` + `bridge_lineup_player`; dims `dim_arena`, `dim_official`,
   `dim_shot_zone`, `dim_play_type`.
5. Singular reconciliation tests (team pts = Σ player pts; shots ≈ FGA).

**Acceptance**
- For the season: `fact_player_game` ≈ 30 rows/game; reconciliation tests pass;
  `fact_shot` row count within tolerance of box-score FGA.
- Incremental run of one new game day adds only that day's rows.

---

## Phase 3 — Breadth (all 140 endpoints)
*Goal: complete raw coverage + the splits/dashboard facts.*

**Steps**
1. Registry-driven Bronze: auto-generate an Auto Loader table for **every**
   `(endpoint, result_set)` not yet landed — full API archive in `nba.bronze`.
2. Crawl remaining groups per config cadence: player/team dashboards & tracking,
   league aggregates, draft/combine, standings, awards.
3. dbt staging for the high-value remainder; Gold `fact_player_season`,
   `fact_team_season`, `fact_player_tracking`, `fact_draft_pick`, `fact_standings`,
   `dim_prospect`.
4. Document coverage: which result sets are Bronze-only vs modeled (in dbt docs).

**Acceptance**
- Every endpoint result set has a Bronze table (count vs registry = 100%).
- Bronze-only vs Gold-modeled coverage is reported, no silent gaps.

---

## Phase 4 — Incremental, backfill & ops
*Goal: it runs itself, reliably, over all history.*

**Steps**
1. Finalize the **daily** Lakeflow Job (crawl `--mode daily` → Bronze →
   `dbt snapshot` + `dbt build` → dashboard refresh), scheduled 09:00 ET.
2. Build the **backfill** job (parametrized seasons/groups, chunked, larger rate
   budget, optional proxy pool); backfill modern era (1996-97→present for
   pbp/shots; full history for box/games where available).
3. Convert append-grain facts to `incremental`/`merge`; verify daily delta cost.
4. Quality: full `dbt_expectations` + freshness; severities tuned; Lakehouse
   Monitoring on key Gold tables; failure alerts.
5. CI hardening: `dbt build --target ci` on ephemeral `nba_ci` with sampled Bronze.

**Acceptance**
- Daily job runs unattended for a week; yesterday's games in Gold by 9am ET.
- Backfill completes and resumes correctly after an induced failure.
- A deliberately bad row fails `dbt build` and blocks publish (fails closed).

---

## Phase 5 — Analytics products & showcase
*Goal: the visible payoff.*

**Steps**
1. Build `mart_*` tables and the **AI/BI dashboards** ([05](05-analytics-and-showcase.md) §1).
2. Create the **Genie space** on `nba.gold` with curated tables + examples.
3. Publish **UC functions** (`nba.ai`) and re-point the **MCP server**; record an
   agent demo. Optionally add Genie/Vector-Search MCP servers.
4. Ship ≥1 **ML model** (game outcome or player projection) via MLflow + feature
   tables; register in UC Models.
5. Generate + publish **dbt docs**; write the **case study** and update the repo
   README with the architecture diagram and artifact links.

**Acceptance**
- Dashboards, Genie, MCP agent demo, ML model, and dbt docs all live and linked.
- A fresh clone reproduces the platform: `databricks bundle deploy` + backfill +
  `dbt build` yields populated Gold.

---

## Suggested sequencing & effort
| Phase | Rough effort | Can start once… |
|---|---|---|
| 0 | 0.5–1 day | now |
| 1 | 2–3 days | Phase 0 |
| 2 | 3–5 days | Phase 1 |
| 3 | 3–5 days | Phase 2 (registry from P1 reused) |
| 4 | 3–4 days | Phase 2 (backfill needs the core facts) |
| 5 | 3–5 days | Phase 4 (stable Gold) |

> Build the **thin vertical slice (Phases 0–1) first** — one season all the way to a
> dashboard — before widening. It de-risks every later decision and gives you a
> demoable result early.

---

## Immediate next actions (concrete)
1. Create the `nba` catalog + schemas + volume (I can run this now via the UC API).
2. Commit this `docs/warehouse/` set on a branch.
3. Scaffold `databricks.yml` + `dbt/` + `src/nba_warehouse/` skeletons.
4. Implement `registry.py` and prove it lists all endpoints/result sets.

See the [overview](README.md) for the full index.
