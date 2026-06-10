# NBA Lineup Synergy Embeddings — adapted to nba-lakehouse

This adapts the standalone "NBA Lineup Synergy Embeddings" plan to the assets that
already exist in this repo. **Goal is unchanged:** learn low-dimensional player
skill embeddings that model lineup synergy (teammate + matchup interactions) so we
can predict lineups that have rarely/never shared the floor — something RAPM can't
do. Core hypothesis unchanged: stint point-differential = individual effects +
pairwise interaction (dot products of feature-anchored player vectors).

What changes is **plumbing, not the science**: ~40% of Phase 1 is already built,
and the tech stack shifts from "local DuckDB only" to a hybrid that uses our
Databricks lakehouse for governed ingestion and DuckDB/MotherDuck for fast,
quota-free modeling iteration.

---

## 0. How the plan maps onto what we already have

| Plan component | Our existing asset | Status |
|---|---|---|
| Cache-first, resumable HTTP ingestion | `src/nba_warehouse/extract*.py` + `ops.crawl_state` (per-slice checkpoints) | **Reuse** |
| Rate limiting / browser headers | `nba_api` + `API_DELAY_SECONDS`; **backoff is light → harden** | **Adapt** |
| `_fetched_at` / `_source_params` columns | Bronze lineage cols `_ingested_at, _params_json, _param_hash, _run_id` | **Reuse** |
| Endpoint metadata / "one module per source" | `registry.py` (135 endpoints introspected) + `warehouse.py` Bronze sink | **Reuse** |
| nba_api pulls (synergy/tracking/hustle/shots/matchups) | endpoints exist in registry; **not yet crawled** | **New crawl** |
| Box scores, shot charts, player bio, seasons | `fact_player_game`, `fact_shot`, `dim_player`, `dim_season`, `fact_player_season` | **Reuse** |
| dbt staging → features → marts | dbt project (dbt-databricks) + `generate_schema_name` macro | **Reuse/extend** |
| Eval harness + `results` table pattern | `src/nba_warehouse/elo_backtest.py` + offline-cache reports | **Reuse as template** |
| DuckDB local store | **MotherDuck** (you just added `MOTHERDUCK_TOKEN`) | **Adopt** |
| Possession/stint data | `gamerotation` (subs timing) + `fact_play_by_play` (points) — **no pbpstats** | **New (nba_api)** |
| Garbage-time filter inputs | `fact_play_by_play` (period, clock, score) + `fact_player_season` (minutes) | **Reuse** |
| Player-id canonicalization | NBA `person_id` used throughout | **Reuse** |

Net: **Phases 1.1, parts of 1.2, and 3's box/shot inputs are largely done.** The
net-new work is stints (Phase 2), the synergy/tracking/matchup feature crawl
(Phase 3), and the modeling/eval (Phases 4–6).

---

## 1. Tech stack (reconciled)

- **Governed ingestion + source of truth:** Databricks Unity Catalog lakehouse
  (`nba` / `nba_dev`, Bronze→Silver→Gold) — keep as is.
- **Modeling sandbox:** **DuckDB / MotherDuck.** The synergy work is iterative and
  heavy (RAPM ridge, PyTorch, many ablations) — running it against the serverless
  SQL warehouse is slow and hits the **daily free-tier limit** (already a recurring
  blocker; see `reports/*.py` offline-cache fallback). So we **sync the handful of
  Gold tables the model needs into MotherDuck/DuckDB** and iterate there with no
  quota and millisecond queries.
- **Transformation:** keep dbt-databricks for Bronze→Silver→Gold; add a **second
  dbt project `dbt_synergy/` using `dbt-duckdb`** (against MotherDuck/local file)
  for the stint + feature + mart layer the model consumes. Same dbt skills, cheap
  iteration, matches the original plan's DuckDB choice.
- **Modeling:** PyTorch (factorization), scikit-learn (RAPM ridge), numpy/pandas.
- **CLI/config:** extend the existing pattern (argparse entrypoints like
  `run_extract.py`); add `pydantic` settings if config grows. (typer optional.)
- **Testing:** pytest (we already test `registry` and `elo_backtest`); dbt tests
  for the synergy marts.

> Sync mechanism Databricks → DuckDB/MotherDuck: reuse the **raw-cache pattern**
> already in `reports/first4_trend.py` (`_load()` writes `_raw.csv`). Generalize it
> to export each needed Gold table to Parquet once per refresh; the cron
> (`reports/refresh.sh`) drops them and `dbt-duckdb`/MotherDuck reads them. No new
> infra — it's the offline cache we already built, pointed at the modeling tables.

---

## 2. Repo structure (inside nba-lakehouse, not a new repo)

```
nba-lakehouse/
├── src/nba_warehouse/                # EXISTING ingestion framework — extend
│   ├── extract_synergy.py            # NEW: synergy/tracking/hustle/matchup league-season crawls
│   ├── extract_shotchart.py          # NEW: shotchartdetail per player-season (fanout like extract_career)
│   ├── extract_rotation.py           # NEW: gamerotation per game (substitution timing -> stints)
│   └── sync_motherduck.py            # NEW: export Gold tables -> Parquet/MotherDuck (reuses cache pattern)
├── src/nba_synergy/                  # NEW: modeling code (kept separate from ingestion)
│   ├── stints.py                     # stint construction from possessions
│   ├── features.py                   # assemble player-season feature matrix from marts
│   ├── models/baselines.py           # raw +/-, RAPM ridge
│   ├── models/factorization.py       # feature-anchored synergy model (PyTorch)
│   ├── eval.py                        # splits + metrics + results table (mirror elo_backtest)
│   └── cli.py
├── dbt/                              # EXISTING dbt-databricks (Bronze->Silver->Gold)
├── dbt_synergy/                      # NEW dbt-duckdb project: stg -> features -> marts.stints / player_season_features
├── data/                            # duckdb file + parquet exports (gitignored)
└── docs/synergy/PLAN.md             # this file
```

---

## 3. Scope (v1) — unchanged intent, our data window

- **Seasons:** 2017-18 → 2024-25, regular season (tracking/synergy/matchup quality
  consistent here). Our spine already covers these; the new endpoints get crawled
  for this window only.
- **Target:** points per 100 possessions differential at the **stint** grain.
- **Exclusions:** garbage time (rule in Phase 2), <4s-clock possessions; OT kept &
  flagged. We already have period/clock/score in `fact_play_by_play`.

---

## Phase 1 — Ingestion (mostly built; extend)

**1.1 Infra — REUSE.** The cache-first/resumable/lineage requirements are already
satisfied: `ops.crawl_state` gives resume-from-checkpoint per `(endpoint,
param_hash[,season])`; Bronze is the replayable archive; lineage columns exist.
**One hardening task:** add exponential backoff + jitter + dead-letter to the
extractor (today retries are minimal) and a configurable per-endpoint delay.
Optional proxy support already noted in our docs.

**1.2 nba_api pulls — partly done.**
- *Already in Gold:* player bio (`dim_player`/`commonallplayers`), box scores
  (`fact_player_game` via `boxscore*v3`), shot coords (`fact_shot` from PBP),
  seasons.
- *New crawls* (all exist in `registry.py`, just not yet pulled), via
  `extract_synergy.py` (league-season, cheap: ~1 call/season/measure) and
  `extract_shotchart.py` (player-season fanout, reuse `extract_career` batching):
  `synergyplaytypes` (off+def, all play types), `leaguedashptstats` (each
  `pt_measure_type`), `leaguehustlestatsplayer`, `leagueseasonmatchups` /
  `boxscorematchupsv3`, `draftcombinestats`, and `shotchartdetail` per player-season.
- Acceptance unchanged (`--season 2023-24` populates Bronze, resumable, row-count
  sanity vs ~500 players / 1230 games) — our extractor already prints/loads counts.

**1.3 Possession / stint source — NEW (nba_api only; no pbpstats).**
Decision made: **no external dependency.** Verified live that nba_api covers it:
- **`gamerotation`** (`extract_rotation.py`) returns every player's
  `IN_TIME_REAL`/`OUT_TIME_REAL` (tenths of a second from tip-off) for both teams →
  reconstruct the 10 on the floor at any instant → **stint boundaries**. This is
  exactly what pbpstats was recommended for (the substitution-timing swamp), in one
  call per game.
- Points + events come from our existing **`fact_play_by_play`** (`score_home/away`,
  `period`, `clock`, `team_id`, `player_id`).
- **Possessions:** PBP doesn't label them, so v1 **estimates** per stint via the
  standard formula `FGA + 0.44·FTA − OREB + TOV` from events inside the stint
  window (exact event-based possession parsing is a later refinement). The only
  fiddly bit is aligning gamerotation's tenths-from-tip-off to PBP's period+clock
  on a common "seconds elapsed" axis — bounded work.
- **`leaguedashlineups`** (2,000 five-man units/season with OFF/DEF/NET_RATING +
  POSS) is pulled too — used as a **validation target** (compare predicted vs
  actual lineup net ratings) and as a fast teammate-only v1 if needed.
- pbpstats remains an *optional* future swap only if exact possession parsing
  becomes the bottleneck; not part of v1.

---

## Phase 2 — Stint construction (NEW; dbt_synergy)

- `marts.stints` (in `dbt_synergy`, materialized in DuckDB/MotherDuck):
  `stint_id, game_id, season, off_lineup(5 sorted ids), def_lineup(5 sorted ids),
  n_possessions, points_for, points_against, start/end clock, period, is_garbage,
  leverage`. Store both offensive directions consistently.
- **Garbage-time rule (v1):** margin ≥19 in Q4, ≥25 in Q3, or a lineup with 4+
  players outside their team's top-10 season minutes. We have margin/period from
  `fact_play_by_play` and minutes from `fact_player_season` → directly computable.
  Flag, don't drop (`is_garbage`).
- **dbt tests** (we already use dbt tests + cross-fact reconciliations like
  `assert_player_points_match_team_box`): stint possessions reconcile to game
  totals; exactly 10 distinct players; no player on both sides; points tie to final
  score. Lineups stored as **sorted id tuples** (plan pitfall #4).
- Expect ~30–40k stints/season; weight by possessions, never filter short stints.

---

## Phase 3 — Player-season features (extend existing)

- Build `marts.player_season_features` (~80–150 cols) in `dbt_synergy`, sourced
  from the new Bronze (synergy/tracking/hustle/matchups) **plus** our existing Gold
  (`fact_shot` for shot profile, `dim_player` for bio, `fact_player_season` for
  minutes/possession weight).
- Feature groups exactly as the plan (offensive play-type profile, shot profile,
  creation/handling, off-ball, rebounding, defensive role from matchups, bio).
- z-score within season; keep low-minute players (emit `total_possessions` for
  prior strength); impute missing tracking with position-group means + missingness
  flags. (We already z-score and try_cast/impute in staging.)
- Leakage note for the temporal split: recompute from train-period games or
  document the v1 caveat (plan pitfall #6).

---

## Phase 4 — Baselines + eval harness (NEW; mirror elo_backtest)

- `src/nba_synergy/eval.py` reuses the **shape** of `elo_backtest.py`: pure metric
  functions + a `results` table (model, config hash, split, metrics) — every
  experiment reproducible. Persist results to DuckDB/MotherDuck (or `ops` on
  Databricks).
- Baselines: (1) naive (0 / team net rating); (2) **additive RAPM** ridge
  (possession-weighted, CV λ) — the canonical yardstick; (3) RAPM + box prior.
- Splits: (a) random stint holdout; (b) temporal (first 60 games → rest);
  (c) **novel-pairs holdout** (headline test). Metrics: possession-weighted
  RMSE/MAE, predicted-vs-actual lineup net rating corr (≥100 poss), calibration —
  same reliability/calibration tooling we built for Elo.

---

## Phase 5 — Synergy factorization model (NEW; PyTorch)

Model spec unchanged: `ŷ = μ + Σ aᵒ + Σ aᵈ + Σ⟨u(oᵢ),u(oⱼ)⟩ + Σ⟨v(dᵢ),v(dⱼ)⟩ +
Σ⟨w(oᵢ),z(dⱼ)⟩`, k∈{4,8,16}, possession-weighted MSE.
- **Feature anchoring (the crux):** `u(p)=f_u(x_p)+δ_p` with x_p = Phase-3 feature
  vector, shared small net f_u, per-player offset δ_p penalized ∝ 1/√possessions.
  Plus player-masking augmentation. This is what enables generalization to unseen
  combos and beating RAPM on split (c).
- Multi-season: share f_*; δ per player-season; season intercepts. Data (~250k
  stints) fits in memory — train locally/MotherDuck-fed, no Databricks needed.
- Deliverables: beat additive RAPM on split (c); interpretability artifacts
  (NN players in embedding space; top synergy pairs vs actual two-man net ratings;
  "best fifth player" query).

---

## Phase 6 — Validation & honest reporting (reuse report infra)

- Results doc across all three splits + ablations (no anchoring / no interactions /
  no matchup term) + sanity checks (known PnR duos positive; 2024-25 high-minute
  lineups correlate out-of-sample).
- Render as an **offline-capable HTML report** under `reports/` exactly like
  `elo_calibration.py` (reliability/calibration plots, metric cards, results
  table), wired into `reports/refresh.sh`.

## Phase 7 — Product surface (optional, deferred)
- Lineup builder / similarity explorer / synergy leaderboard — defer until Phase 6
  shows a real result. Could reuse the interactive Plotly/HTML patterns from
  `reports/first4_trend.py`.

---

## Dependencies to add (pyproject groups)

- modeling: `torch`, `scikit-learn`, `numpy`, `pandas` (have pandas).
- duckdb path: `duckdb`, `dbt-duckdb`, `duckdb-engine` (for MotherDuck use the
  `md:` connection + `MOTHERDUCK_TOKEN`).
- config/cli: `pydantic` (+ optional `typer`).

---

## Revised milestone order (de-risk first, reuse what exists)

1. **Harden extractor** (backoff/jitter/dead-letter) + crawl one season of the new
   nba_api endpoints (synergy/tracking/hustle/matchups/shotchart) → Bronze. *(reuse)*
2. **Possession/stint source**: `extract_rotation.py` (`gamerotation`) for that
   season → Bronze; build stints from it + `fact_play_by_play`. *(new)*
3. **MotherDuck sync**: export the needed Gold/Bronze tables to MotherDuck/DuckDB
   via the cache pattern; stand up `dbt_synergy` (dbt-duckdb). *(new, small)*
4. **`marts.stints` + dbt tests** (Phase 2). *(new)*
5. **RAPM baseline + eval harness** (Phase 4) — *before* features, to prove the
   stint data is sane (plan's rationale; same reason we built the Elo backtest first).
6. **`player_season_features` mart** (Phase 3). *(extend)*
7. **Factorization model v1** (Phase 5) → ablations + report (Phase 6). *(new)*
8. Scale to all seasons; rerun; publish results report.

---

## Decisions

1. **Possession source — DECIDED: `gamerotation` + `fact_play_by_play`** (nba_api
   only, no pbpstats). Possessions estimated per stint for v1; exact parsing later.
2. **Modeling store:** MotherDuck (cloud DuckDB, shareable) vs. local DuckDB file
   (`data/synergy.duckdb`). Recommend MotherDuck since you've added the token. *(open)*
3. **Synergy feature dbt project:** `dbt-duckdb` (recommended, cheap iteration) vs.
   adding models to the existing dbt-databricks project (governed but quota-bound). *(open)*

Inherited pitfalls still apply verbatim: stats.nba.com hostility (→ our cache +
backoff), possession parsing swamp (→ `gamerotation` removes the substitution-
timing half; estimate possessions for v1), id joins (NBA ids, verify ~100%),
sorted lineup keys, collinearity (→ feature anchoring + masking), leakage on the
temporal split, never filter short stints (possession-weight instead).
