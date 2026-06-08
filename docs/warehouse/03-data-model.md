# 03 — Data Model (dbt: Silver → Gold)

dbt Core owns everything from Bronze onward. This doc covers the dbt project
layout, the Silver layer (staging, intermediate, SCD2 snapshots), and the Gold
dimensional model.

## 1. dbt project layout

```
dbt/
├── dbt_project.yml
├── packages.yml                # dbt_utils, dbt_expectations, audit_helper
├── models/
│   ├── staging/                # stg_<endpoint>__<result_set>  → schema: silver
│   │   ├── _sources.yml        #   GENERATED from nba_warehouse.registry (Bronze tables)
│   │   ├── _stg_models.yml     #   tests + descriptions
│   │   └── stg_*.sql           #   1:1 view per Bronze table: rename→snake, cast types, basic clean
│   ├── intermediate/           # int_*  → schema: silver (ephemeral/views)
│   │   └── int_*.sql           #   reusable joins/derivations (e.g. int_games__deduped)
│   └── marts/
│       ├── core/               # dim_*, fact_*  → schema: gold
│       └── analytics/          # mart_*         → schema: gold
├── snapshots/                  # SCD2: snap_player, snap_team  → schema: silver
├── seeds/                      # season_types.csv, shot_zones.csv, lineup_pos.csv
├── macros/                     # generate_schema_name, surrogate keys, helpers
└── tests/                      # singular data tests
```

`dbt_project.yml` materializations (defaults, overridable per model):

```yaml
models:
  nba:
    staging:      { +materialized: view,        +schema: silver }
    intermediate: { +materialized: ephemeral,   +schema: silver }
    marts:
      core:       { +materialized: table,        +schema: gold }
      analytics:  { +materialized: table,        +schema: gold }
```

A `generate_schema_name` macro overrides dbt's default `<target>_<schema>` naming
so models land in clean `silver`/`gold` schemas inside the `nba` (or `nba_dev`)
catalog, selected by `--target`.

## 2. Silver layer

### 2.1 Staging (`stg_*`) — one model per Bronze result set
- **1:1 with Bronze.** Mechanical, no business logic: snake_case rename, cast
  strings→typed (ints, decimals, dates, `MIN` "34:21" → seconds), trim, null
  normalization, drop `_rescued_data` after asserting it's empty.
- Materialized as **views** (cheap, always current with Bronze).
- `_sources.yml` and base column tests are **generated from the registry**, so when
  the API adds a column, regeneration flows it through automatically.

```sql
-- models/staging/stg_boxscore_traditional__player_stats.sql
with src as (select * from {{ source('bronze','boxscoretraditionalv3__PlayerStats') }})
select
    cast(gameId      as string)  as game_id,
    cast(teamId      as bigint)  as team_id,
    cast(personId    as bigint)  as player_id,
    {{ minutes_to_seconds('minutes') }} as seconds_played,
    cast(points      as int)     as points,
    cast(assists     as int)     as assists,
    cast(reboundsTotal as int)   as rebounds,
    -- …
    _ingested_at, _run_id
from src
```

### 2.2 Intermediate (`int_*`) — reusable derivations
- Cross-source joins and dedup that multiple marts share.
- Examples: `int_games__deduped` (reconcile `leaguegamefinder` vs `scheduleleaguev2`
  vs box-score summary into one canonical game row), `int_player_game__unified`
  (join the box-score variants — traditional/advanced/scoring/usage — on
  `game_id+player_id` into one wide row), `int_shots__enriched` (attach zone/period).
- Mostly **ephemeral** (inlined CTEs) unless reused enough to warrant a view.

### 2.3 SCD2 via dbt snapshots
Entity attributes change over time and we want as-of-date history.

- `snap_player` — bio/team/position/jersey from `commonplayerinfo` /
  `commonallplayers`; `check` strategy on the mutable columns.
- `snap_team` — name/city/arena/conference/division from `teamdetails` /
  `commonteamyears`.

```sql
-- snapshots/snap_team.sql
{% snapshot snap_team %}
{{ config(target_schema='silver', unique_key='team_id',
          strategy='check', check_cols=['team_name','team_city','arena','conference','division']) }}
select team_id, team_name, team_city, arena, conference, division, _ingested_at
from {{ ref('stg_team_details__team_info') }}
{% endsnapshot %}
```

These snapshots feed the SCD2 Gold dimensions, giving `valid_from`/`valid_to`/
`is_current` for free.

## 3. Gold — dimensional (star) model

Kimball star schema optimized for BI, Genie, and ML feature derivation. Surrogate
keys via `dbt_utils.generate_surrogate_key`; natural keys retained for lineage.

### 3.1 Dimensions

| Dimension | Grain | Type | Source (silver) |
|---|---|---|---|
| `dim_date` | one day | static | generated (calendar 1946→+1yr) |
| `dim_season` | season × season_type | static | seed + game span |
| `dim_team` | team version | **SCD2** | `snap_team` |
| `dim_player` | player version | **SCD2** | `snap_player` |
| `dim_arena` | arena | SCD1 | `stg_*` team details / box summary |
| `dim_official` | referee | SCD1 | box score summary officials |
| `dim_game` | one game | SCD1 (mostly immutable) | `int_games__deduped` |
| `dim_play_type` | synergy play type | static | seed / `synergyplaytypes` |
| `dim_shot_zone` | shot zone/range | static | seed |
| `dim_prospect` | draft prospect | SCD1 | combine + draft history |

### 3.2 Facts

| Fact | Grain | Key dims | Source |
|---|---|---|---|
| `fact_team_game` | team × game | game, team, date, season, arena | box score team stats + summary |
| `fact_player_game` | player × game | game, player, team, date, season | `int_player_game__unified` (all box variants) |
| `fact_play_by_play` | event × game | game, team, player, period | `playbyplayv3` (+ win-prob) |
| `fact_shot` | shot attempt | game, player, team, shot_zone, date | `shotchartdetail` |
| `fact_lineup_stint` | 5-man stint × game | game, team | `gamerotation` (+ bridge_lineup_player) |
| `fact_player_season` | player × season × type | player, team, season | `playercareerstats` / `leaguedashplayerstats` |
| `fact_team_season` | team × season × type | team, season | `teamyearbyyearstats` / `leaguedashteamstats` |
| `fact_player_tracking` | player × season × tracking-type | player, team, season | `playerdashpt*` / `leaguedashptstats` |
| `fact_draft_pick` | pick | player, team, season | `drafthistory` (+ combine) |
| `fact_standings` | team × season × date | team, season, date | `leaguestandingsv3` |

Bridge: `bridge_lineup_player` (lineup_sk → 5× player_sk) resolves the
many-to-many between `fact_lineup_stint` and `dim_player`.

### 3.3 Why "unify the box-score variants" in intermediate
The API splits one logical player-game across `boxscoretraditionalv3`,
`…advancedv3`, `…scoringv3`, `…usagev3`, `…fourfactorsv3`, `…hustlev2`,
`…playertrackv3`. `int_player_game__unified` joins them on `game_id+player_id` so
`fact_player_game` is one wide, analysis-ready row instead of seven tables a user
must join. The v2 endpoints are treated as historical fallback where v3 has no
coverage (handled with `coalesce` in the intermediate model).

## 4. Analytics marts (`mart_*`, Gold)
Use-case-shaped, denormalized tables on top of the star schema (detailed in
[05](05-analytics-and-showcase.md)). Examples:
- `mart_player_game_rollup` — rolling 5/10/season per-player splits for dashboards.
- `mart_team_four_factors` — team efficiency (eFG%, TOV%, ORB%, FT rate) per game/season.
- `mart_shot_zone_efficiency` — make% and expected points by player × zone.
- `mart_lineup_performance` — net rating per lineup, min-played thresholds.

## 5. Incremental strategy in dbt
- **Append-grain facts** (`fact_play_by_play`, `fact_shot`, `fact_player_game`,
  `fact_team_game`): `materialized='incremental'`, `incremental_strategy='merge'`,
  `unique_key` = natural key, filtered on `_ingested_at > max(...)` (or game_date)
  so the daily run only processes new games.
- **Small dims / season facts**: full table rebuilds (cheap).
- **`dbt build --full-refresh`** rebuilds any model from Bronze when a contract
  changes — the replayable Bronze archive makes this safe and free of API calls.

```sql
{{ config(materialized='incremental', incremental_strategy='merge',
          unique_key=['game_id','player_id'], cluster_by=['game_date','team_id']) }}
select * from {{ ref('int_player_game__unified') }}
{% if is_incremental() %}
  where game_date > (select coalesce(max(game_date),'1900-01-01') from {{ this }})
{% endif %}
```

## 6. Testing the model (preview — see [04](04-orchestration-quality-governance.md))
- **Generic tests**: `unique`, `not_null`, `relationships` (every fact FK resolves
  to its dim), `accepted_values` (season types, shot zones).
- **`dbt_expectations`**: ranges (`0 ≤ fg_pct ≤ 1`), row-count plausibility, freshness.
- **Singular tests**: e.g. "a team's points in `fact_team_game` equals the sum of
  its players' points in `fact_player_game`" — a strong cross-fact reconciliation
  that catches join/dedup bugs.

Next: **[04 — Orchestration, Quality & Governance](04-orchestration-quality-governance.md)**.
