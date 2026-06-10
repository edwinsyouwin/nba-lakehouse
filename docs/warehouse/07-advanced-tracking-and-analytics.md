# 07 — Advanced Tracking & Analytics Expansion

Design for the next data expansion: **player tracking, hustle, play-type (Synergy),
shot quality, lineups, and matchup/defense data**, plus the analytics products they
unlock. Continues the medallion architecture (Bronze → Silver → Gold → marts) and
the conventions in [03 — Data Model](03-data-model.md); extends the roadmap past
Phase 3 (career + roster).

The governing constraint is **API/compute economy**. The dev workspace is on a
free-tier daily compute cap, and per-game fan-outs (box/PBP/shots) are ~13
warehouse round-trips/game — so a full-history game backfill is multi-day and
exhausts quota. **The richest differentiated data is the cheapest to pull**:
season-grain "league dash" endpoints return *every player/team for a season in a
single call*. This doc prioritizes accordingly.

---

## 1. Endpoints to ingest

Grouped by **grain**, because grain drives both cost and modeling.

### A. Season-grain — 1 call per season (priority: do first)

Each call returns all players (or teams) for a season. Tracking data exists from
**2013-14**, Synergy play types from **2015-16**. Pulling 10–12 seasons across this
whole group is on the order of **~150 API calls total** — trivial vs. the
12,808-game detail fan-out.

| Endpoint | Grain | Key params | What it adds |
|---|---|---|---|
| `leaguedashptstats` | player×season, team×season | `player_or_team`, `pt_measure_type` (Drives, Passing, Possessions, CatchShoot, PullUpShot, Defense, SpeedDistance, Rebounding, ElbowTouch, PostTouch, PaintTouch), `per_mode`, `season`, `season_type` | Creation & movement: drives, touches, passes→potential assists, speed/distance, rebound chances |
| `leaguedashptdefend` | player×season | `defense_category` (Overall, 3 Pointers, 2 Pointers, Less Than 6Ft, …) | Opponent FG% defended by distance → rim protection / perimeter D |
| `leaguehustlestatsplayer` / `…team` | player/team×season | `season`, `season_type`, `per_mode` | Deflections, charges drawn, screen assists, contested shots, loose balls, box-outs |
| `synergyplaytypes` | player×season×play_type×{off,def} | `play_type` (Transition, Isolation, PRBallHandler, PRRollman, Postup, Spotup, Handoff, Cut, OffScreen, OffRebound, Misc), `type_grouping`, `player_or_team` | Efficiency (PPP, frequency, percentile) by play type → role & style |
| `leaguedashplayerptshot` / `…teamptshot` | player×season | `season`, shot-tracking dims | Shot quality inputs: defender distance, dribbles, touch time, shot clock buckets |
| `leaguedashplayershotlocations` | player×season×zone | `distance_range` | FGM/FGA by court zone (complements `fact_shot`/`dim_shot_zone`) |
| `leaguedashlineups` | lineup×season | `group_quantity` (2–5) | Lineup ratings (off/def/net, pace) → on/off, lineup optimization |
| `leaguedashplayerclutch` / `…teamclutch` | player/team×season | clutch window params | Clutch splits |
| `leaguedashplayerbiostats` | player×season | `season` | Height/weight/age + draft-adjacent context |
| `leagueseasonmatchups` | defender×offender×season | `def_player_id`/`off_player_id` rollup | Defender-vs-scorer possession totals (larger; player×player) |

### B. Game-grain fan-out — expensive (defer; recent seasons or post-upgrade)

One call **per game** (or per player-game). Same cost profile as the box/PBP backfill.
Gate behind quota; pull only recent/priority seasons until the workspace is upgraded
or moved to the Volume + Auto Loader path.

| Endpoint | Grain | What it adds |
|---|---|---|
| `winprobabilitypbp` | game×event | **Official** win probability per play — benchmark for the Elo model |
| `hustlestatsboxscore` | player×game | Per-game hustle (deflections, contests…) |
| `boxscoreplayertrackv3` | player×game | Per-game tracking box score |
| `boxscorematchupsv3` | matchup×game | Per-game defender↔scorer possessions |
| `shotchartdetail` | player×season (or team×season) | Clean shot events w/ defender — medium cost (≈30 calls/season if pulled team-wise); already partly derivable from `fact_shot` |

### C. Reference / context — cheap, occasional

`drafthistory`, `draftcombinestats`, `draftcombineplayeranthro` (1 call/draft year),
`playerawards` (per player, one-time), `leaguestandingsv3` (snapshot),
`commonplayerinfo` (per player — enriches `dim_player` with position/draft/height).

### Note on absence/injury data (already available)

No forward-looking injury endpoint exists in `nba_api`. Retrospective availability is
already ingested: **`fact_player_game.comment`/`did_play`** (DNP/DND/NWT reasons) and
`boxscoresummaryv2/v3 → InactivePlayers`. These feed the *availability-impact* analysis
in §3 with no new ingestion. (Prospective Out/Questionable status would require scraping
the league's daily PDF Injury Report — out of scope here.)

---

## 2. Medallion design

Extends the existing pattern; **no new architecture**, just new tables following
`stg_ → int_ → dim_/fact_ → mart_` conventions.

### 2.1 Ingestion (Bronze)

- **One generic season-grain extractor** (`extract_tracking.py`), parameterized over
  `(endpoint, measure_type/play_type, player_or_team)` × season. Reuses
  `warehouse.load_result_set` and the `ops.crawl_state` checkpoint (idempotent,
  resumable). Drives the endpoint/param matrix from the existing **registry**.
- **Bronze tables** stay one-per-(endpoint, result set), all-STRING + lineage columns —
  identical to today. E.g. `bronze.leaguedashptstats__LeagueDashPtStats`,
  `bronze.synergyplaytypes__SynergyPlayTypes`.
- **Quota-aware scheduling** (critical):
  - Pull Group A (season-grain) first — full history in ~150 calls.
  - Defer Group B to recent seasons; gate per-day within the free-tier cap, or move
    bulk to the **Volume + Auto Loader** path (far fewer query-statements than per-row
    `INSERT`s — both faster and more quota-efficient).
  - Fix the extractor's retry policy to **fail fast on quota/`BAD_REQUEST`** and only
    retry genuine connection drops.

### 2.2 Conform (Silver — `stg_`)

Typed/conformed, `try_cast` for era-missing fields, one `stg_` per Bronze result set.
Key conformance work:

- Normalize `per_mode` (pick one canonical — e.g. Totals — and derive per-game/per-100
  downstream) so metrics are comparable across endpoints.
- Conform `player_id`, `team_id`, `season_id` to the existing keys.
- Pivot the `pt_measure_type` families and `synergy play_type`/`type_grouping` into tidy
  long rows.

New staging models (illustrative):
`stg_pt_player_tracking`, `stg_pt_player_defend`, `stg_hustle_player`,
`stg_synergy_playtype`, `stg_lineups`, `stg_player_clutch`,
`stg_player_pt_shot`, `stg_player_shot_locations`, `stg_player_bio`,
`stg_player_matchup`.

### 2.3 Build (Intermediate — `int_`)

- `int_player_season__tracking` — join the tracking measure-type families + hustle into
  one wide player-season feature row.
- `int_synergy__player_playtype` — long: player × play_type × {off,def} with PPP,
  frequency, percentile.
- `int_lineup__ratings` — lineup key (sorted 5 player_ids) + ratings.
- `int_player_shotquality` — pt_shot buckets → expected eFG per player.

### 2.4 Gold — facts, dims, marts

**New season-grain facts:**

| Model | Grain | Source |
|---|---|---|
| `fact_player_season_tracking` | player×season×season_type | tracking + hustle + pt_shot (wide) |
| `fact_player_season_synergy` | player×season×play_type×off/def | synergy (long) |
| `fact_lineup_season` | lineup×season | leaguedashlineups |
| `fact_player_matchup_season` | defender×offender×season | leagueseasonmatchups |
| `fact_player_shot_zone_season` | player×season×zone | shot locations |

**Game-grain facts (deferred, recent-first):**
`fact_player_game_tracking`, `fact_player_game_hustle`, `fact_win_probability`
(game×event).

**Dimensions:** seed `dim_play_type`; add `dim_lineup` (surrogate over the sorted
player-id set) if lineups are modeled; enrich `dim_player` (or add `dim_player_bio`)
with position/draft/height/weight. Reuse existing `dim_shot_zone`, `dim_season`,
`dim_team`, `dim_game`.

**Analytics marts (`mart_`):**

| Mart | Built from | Product |
|---|---|---|
| `mart_player_impact` | tracking + lineup on/off + clutch | composite player-value rating (homemade EPM/BPM) |
| `mart_player_style` | synergy + shot zones | role/archetype clustering |
| `mart_shot_quality` | pt_shot expected vs actual eFG | shot-making vs shot-creation |
| `mart_lineup_optimization` | fact_lineup_season | best/worst lineups, fit |
| `mart_defense_rating` | ptdefend + matchups | defender rankings, rim protection |
| `mart_winprob_benchmark` | winprobabilitypbp vs `analytics_team_elo` | model calibration / credibility |
| `mart_availability_impact` | `fact_player_game` (comment/did_play) + team ratings | team on/off **by player availability** |

### 2.5 Serving (DuckDB / MotherDuck)

Heavy modeling stays in Databricks (or local dev); **publish only the slim `mart_`
tables to MotherDuck** (`publish.py`) for the product/serving layer. This keeps the
serving path off the metered warehouse and is the natural home for dashboards, the
player-card API, and the agent/Genie surface.

---

## 3. Analyses & takeaways

What the above unlocks — each maps to a concrete, differentiated (sellable) output.

1. **Player impact / value rating.** Fuse creation (drives, potential assists), hustle
   (deflections, screen assists), lineup on/off net rating, and clutch into a single
   proprietary value metric. → player rankings, *undervalued-player* finder.
2. **Player style archetypes.** Synergy play-type mix + shot zones → cluster into roles
   (3&D wing, rim-runner, iso creator, P&R maestro). → roster-fit & trade analysis.
3. **Shot-quality model.** pt_shot (defender distance, touch time, shot clock) → expected
   eFG per shot; player skill = actual − expected. → "best shot-makers vs creators,"
   a betting-adjacent edge.
4. **Lineup optimization & on/off.** Best/worst lineups, net rating by combination,
   stepping toward RAPM-style impact. → coaching/roster tool.
5. **Defense & matchups.** ptdefend + matchups → defender-vs-scorer, rim protection. →
   defensive rankings, matchup game-planning.
6. **Win-probability benchmark.** Compare the Elo win-prob to the NBA's official
   `winprobabilitypbp` → calibration (Brier score), "our model vs the league's." →
   credibility for the predictions product.
7. **Availability impact.** Using the absence data already in `fact_player_game`, compute
   team net rating *with vs without* each player. → injury/load-management impact, all
   from data on hand (no new ingestion).
8. **Effort/intangibles narratives.** Deflections, charges drawn, screen assists →
   "hustle leaders" stories for content/newsletter.

---

## 4. Suggested sequencing

1. **`extract_tracking` (Group A, season-grain)** — full history in ~150 calls;
   quota-cheap. Land Bronze → `stg_` → `int_player_season__tracking` →
   `fact_player_season_tracking`.
2. **`mart_player_impact` + `mart_player_style`** — first differentiated products off (1).
3. **`mart_availability_impact`** — zero new ingestion; uses existing absence data.
4. **`mart_winprob_benchmark`** — pull `winprobabilitypbp` for *recent* seasons only
   (game-grain, quota-gated) to validate Elo.
5. **Lineups / defense / shot-quality marts** — as quota allows.
6. **Game-grain tracking/hustle/winprob full history** — only after a paid upgrade or the
   Volume + Auto Loader migration.

> **Acceptance (Phase-style):** Group-A Bronze present for ≥10 seasons;
> `fact_player_season_tracking` builds and passes tests (unique player×season×type,
> non-null core metrics); `mart_player_impact` published to MotherDuck and queryable;
> all within the daily compute cap.
