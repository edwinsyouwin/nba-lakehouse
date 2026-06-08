# 02 — Source Inventory & Ingestion (→ Bronze)

## 1. The `nba_api` surface

The upstream client is our source-of-truth catalog of the NBA Stats API.

| Area | Location in repo | What it gives us |
|---|---|---|
| **Stats endpoints** | `src/nba_api/stats/endpoints/` (140 modules) | The bulk of the warehouse: box scores, play-by-play, shots, dashboards, league/team/player splits, draft, tracking. Each declares `endpoint`, `expected_data` (named result sets → column lists), and its parameter set. |
| **Live endpoints** | `src/nba_api/live/nba/endpoints/` (scoreboard, boxscore, playbyplay, odds) | Low-latency in-game data for today's slate. |
| **Static data** | `src/nba_api/stats/static/` (players, teams) | Offline reference lists — the seed of the crawl, no API call needed. |

### Each endpoint is a self-describing contract

```python
class PlayerCareerStats(Endpoint):
    endpoint = "playercareerstats"
    expected_data = {
        "CareerTotalsAllStarSeason": ["PLAYER_ID","LEAGUE_ID","Team_ID","GP", ...],
        "CareerTotalsCollegeSeason":  ["PLAYER_ID","LEAGUE_ID","ORGANIZATION_ID", ...],
        "CareerTotalsPostSeason":     ["PLAYER_ID","LEAGUE_ID","Team_ID","GP", ...],
        ...
    }
```

**Key design lever:** every `(endpoint, result_set)` pair is a candidate Bronze
table with a *known* column list. We don't hand-write 140 schemas — we **derive**
them programmatically from `expected_data`. This is the backbone of the
`nba_warehouse.registry` module (see §4) and, downstream, of dbt `sources.yml`.

> Counting note: ~140 endpoints × multiple result sets each ⇒ on the order of
> **400–600 distinct Bronze tables** at full breadth. We do *not* model all of
> them to Gold — only the analytics spine. The rest live in Bronze as a complete,
> queryable raw archive.

## 2. Endpoint taxonomy (how we group ~140 endpoints)

Grouping drives crawl ordering, scheduling cadence, and Gold modeling priority.

| Group | Example endpoints | Grain | Cadence | Gold priority |
|---|---|---|---|---|
| **Reference** | static `players`/`teams`, `commonallplayers`, `commonteamyears`, `teamdetails`, `franchisehistory` | entity | rarely | dims (P1) |
| **Schedule/Games** | `scheduleleaguev2`, `leaguegamefinder`, `leaguegamelog`, `scoreboardv3` | game / team-game | daily | `dim_game`, `fact_team_game` (P1) |
| **Box scores** | `boxscoretraditionalv3`, `…advancedv3`, `…scoringv3`, `…usagev3`, `…fourfactorsv3`, `…hustlev2`, `…playertrackv3`, `…matchupsv3` | player-game / team-game | daily | `fact_player_game`, `fact_team_game` (P2) |
| **Play-by-play** | `playbyplayv3`, live `playbyplay`, `winprobabilitypbp`, `gamerotation` | event / stint | daily | `fact_play_by_play`, `fact_lineup_stint` (P2) |
| **Shots** | `shotchartdetail`, `shotchartleaguewide`, `shotchartlineupdetail` | shot attempt | daily | `fact_shot` (P2) |
| **Player splits/dashboards** | `playercareerstats`, `playerprofilev2`, `playerdashboardby*`, `playerdashpt*`, `playergamelogs` | player-season / split | weekly | `fact_player_season`, marts (P3) |
| **Team splits/dashboards** | `teamdashboardby*`, `teamdashpt*`, `teamyearbyyearstats`, `teamplayeronoff*` | team-season / split | weekly | `fact_team_season`, marts (P3) |
| **League leaders/aggregates** | `leaguedashplayerstats`, `leaguedashteamstats`, `leagueleaders`, `leaguedashlineups`, `leaguedashptstats` | league-season agg | weekly | marts (P3) |
| **Draft & combine** | `drafthistory`, `draftcombinestats`, `draftcombine*`, `draftboard` | pick / prospect | yearly | `fact_draft_pick`, `dim_prospect` (P3) |
| **Standings/misc** | `leaguestandingsv3`, `playoffpicture`, `iststandings`, `playerawards` | team-season / award | daily-ish | marts (P3) |
| **Video/asset** | `videodetailsasset`, `videoevents*`, `videostatus` | event-media | on demand | not modeled; Bronze only |

## 3. The dependency / crawl DAG

Most detail endpoints require IDs produced by upstream ones. The crawler walks this
DAG; it is the single most important piece of ingestion logic.

```
 static teams ─┐
 static players┼─▶ seasons[] (config: 1946→current, by season_type)
               │
               ├─▶ commonallplayers(season)               ── player_ids active that season
               │
               └─▶ leaguegamefinder / scheduleleaguev2(season)
                        │  ── game_ids, team_ids, dates
                        ▼
          ┌─────────────┴───────────────────────────────┐
          ▼              ▼                ▼               ▼
   boxscore*v3(game_id)  playbyplayv3(  shotchartdetail(  gamerotation(
                          game_id)       player/team/      game_id)
                                         season)
          │
          ▼
   per-player / per-team season dashboards (player_id, team_id, season)
```

**Crawl ordering rules**

1. **Seeds are free:** static `players`/`teams` need no API call — load them first.
2. **Discover before detail:** resolve the game list for a season *before* pulling
   per-game box scores/PBP/shots.
3. **Fan-out is bounded by config:** season range, season types (Regular/Playoffs/
   Preseason/All-Star/Play-In), and a per-group enable flag live in
   `config/`, so a run's scope is explicit and reproducible.
4. **State-checked:** each unit of work is keyed in `ops.crawl_state`; already-done
   slices are skipped on re-run.

## 4. The extraction framework (`src/nba_warehouse/`)

Built **on top of** `nba_api` so endpoint contracts are never duplicated.

### `registry.py` — derive metadata from the client
- Import every module in `nba_api.stats.endpoints`, read `endpoint`,
  `expected_data`, and the parameter signature.
- Emit a machine-readable registry: for each endpoint → its result sets, columns,
  required/optional params, taxonomy group, and crawl cadence.
- This registry generates **both** the Bronze table list **and** dbt
  `sources.yml`, so the API contract, Bronze, and staging models stay in lockstep.
- Persisted to `nba.ops.endpoint_registry` for queryable documentation.

### `extract.py` — the dependency-aware crawler
- Walks the DAG in §3; resolves parent IDs from already-landed data.
- **Rate limiting** (see §5) and **retry with exponential backoff + jitter**.
- Writes **two** things per successful call:
  1. the raw JSON response (audit), and
  2. one record per result-set row, tagged with lineage columns.
- Marks `ops.crawl_state` on success; emits run metrics to `ops.run_log`.

### `landing.py` — raw-response capture → UC Volume
- Lands newline-delimited JSON to
  `/Volumes/nba/ops/landing/<endpoint>/<result_set>/<ingest_date>/<param_hash>.json`.
- Each record carries **lineage metadata** injected at landing time:
  `_endpoint`, `_result_set`, `_params_json`, `_param_hash`, `_source_url`,
  `_ingested_at`, `_run_id`, `_api_version`.
- Partition-by-date folders keep Auto Loader's file discovery cheap.

### `run_extract.py` — job entrypoint
- Modes: `--mode daily` (yesterday's games + live), `--mode backfill --seasons …`,
  `--mode reference` (refresh dims sources). Invoked by the Lakeflow Job.

## 5. Rate limiting & resilience (the make-or-break of this source)

`stats.nba.com` throttles aggressively and returns 429s / silent timeouts under load.

- **Politeness:** single logical crawler with a global **token-bucket** (~1 request
  / 0.6–1.0s, tunable per endpoint group). Concurrency is *capped by the bucket*,
  not by cores — more workers don't help and get you blocked.
- **Headers:** send the browser-like headers `nba_api` already sets (Referer,
  User-Agent, etc.); keep a persistent session.
- **Retries:** exponential backoff with jitter on 429/5xx/timeout; cap attempts,
  then dead-letter to `ops.run_log` (status=`failed`) and continue — one bad
  `game_id` must not sink the run.
- **Resumability:** `ops.crawl_state` means a killed run resumes where it stopped.
- **Optional proxy pool:** `nba_api` supports a `proxy` arg; for large backfills,
  rotate a residential proxy pool from config. Used only for backfill, never
  needed for the small daily delta.
- **Backfill vs daily:** backfill is the expensive, throttled, multi-day job
  (decades × games × per-game endpoints); daily is a tiny delta (~5–15 games).
  They are **separate jobs** with separate rate budgets (see [04](04-orchestration-quality-governance.md)).

## 6. Bronze design (Auto Loader)

A thin **Lakeflow Declarative Pipeline** turns landed JSON into Delta streaming
tables — one Bronze table per `(endpoint, result_set)`.

- **Auto Loader** (`cloudFiles`) reads the Volume incrementally with schema
  inference and a `_rescued_data` column to capture any unexpected fields (this is
  how we survive the API's schema drift without breaking ingestion).
- Bronze is **append-only and untyped-friendly**: columns land as strings/variant
  as delivered; *no business logic here*. Typing/renaming happens in dbt staging.
- Lineage metadata columns from landing are preserved.
- **Two flavors of Bronze table:**
  - `nba.bronze.<endpoint>__<result_set>` — the exploded rows (the working tables).
  - `nba.bronze._raw_api_responses` — the full raw payloads, for replay/audit.
- **Light Bronze expectations** (DLT `@expect`) only assert structural invariants
  (e.g. lineage columns non-null, parseable JSON). Semantic quality is dbt's job.
- **Schema-drift handling:** new columns appear automatically via Auto Loader
  schema evolution; the pipeline logs evolution events so we notice when the API
  changes shape.

**Output of this layer:** a complete, replayable, incrementally-updated raw archive
of the entire NBA Stats API in `nba.bronze.*`, ready for dbt to model.
Next: **[03 — Data Model](03-data-model.md)**.
