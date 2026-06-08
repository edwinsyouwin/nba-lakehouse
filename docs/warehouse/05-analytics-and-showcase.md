# 05 — Analytics Use Cases & Showcase

The warehouse is the means; these products are what a reviewer (or a real user)
actually sees. Each is built on Gold and is a distinct portfolio artifact.

## 1. Analytics marts → BI dashboards

Built on the Gold star schema, surfaced via **AI/BI Dashboards** on the serverless
SQL warehouse.

| Dashboard | Backing marts | What it shows |
|---|---|---|
| **Team performance** | `mart_team_four_factors`, `fact_team_game`, `dim_season` | Off/def rating, four factors, pace, W-L trends, home/away splits |
| **Player explorer** | `mart_player_game_rollup`, `fact_player_game` | Rolling 5/10/season splits, usage vs efficiency, per-36/per-100 |
| **Shot charts** | `mart_shot_zone_efficiency`, `fact_shot` | Hex/zone make% vs league baseline, expected points, player vs team |
| **Lineup lab** | `mart_lineup_performance`, `fact_lineup_stint`, `bridge_lineup_player` | Net rating per 5-man unit with minutes thresholds |
| **Season pulse** | `fact_standings`, `playoffpicture`, `iststandings` | Live standings, playoff/play-in picture, streaks |

## 2. Natural-language access — Genie space

A **Genie space** scoped to `nba.gold` lets non-technical users ask questions in
plain English ("which lineups had the best net rating in the 2024 playoffs with
500+ possessions?") and get governed SQL answers.

- Curate the space with the core facts/dims + `mart_*`, rich column descriptions
  (sourced from dbt model YAML → UC comments), and a few example questions.
- Same governance: Genie respects the `SELECT`-on-`gold` grants.

## 3. Agentic access — the MCP layer

The **`databricks-uc-functions` MCP server** already connected in this Claude Code
session becomes a programmable analytics interface once we publish **UC functions**
in `nba.gold` (or a dedicated `nba.ai` schema):

- Author SQL UDFs/table functions like `top_scorers(season, n)`,
  `player_shot_profile(player_id, season)`, `team_four_factors(team_id, season)`.
- Re-point the MCP server from `main/default` to `nba/ai`:
  ```
  claude mcp remove databricks-uc-functions
  claude mcp add --transport http databricks-uc-functions \
    https://dbc-16b7e00d-e6b0.cloud.databricks.com/api/2.0/mcp/functions/nba/ai \
    --header "Authorization: Bearer <token>"
  ```
- Optionally add the **Genie MCP** (`/api/2.0/mcp/genie/<space-id>`) and **Vector
  Search MCP** so an agent can do NL analytics + semantic player/play search.
- Demo: an agent answers "build me a scouting report on player X this season" by
  calling these functions — a strong, modern showcase of the lakehouse as an
  agent-ready data product.

## 4. Machine learning use cases

Feature tables in `nba.feature` (point-in-time correct, derived from Gold facts),
trained with **MLflow**, registered in **Unity Catalog Models**.

| Model | Target | Features (point-in-time) | Serving |
|---|---|---|---|
| **Game outcome** | home win prob | team rolling four factors, rest days, travel, H2H | batch + dashboard |
| **Player game projection** | pts/reb/ast | rolling player splits, opponent defense, usage, minutes trend | nightly batch |
| **Win-probability replay** | in-game win prob | `fact_play_by_play` state | compare vs API `winprobabilitypbp` as a label sanity check |
| **Player similarity** | embedding/NN | season stat vectors, shot profiles | Vector Search index |
| **Shot make probability** | xFG% | distance, zone, defender (tracking), clock | feeds `mart_shot_zone_efficiency` |

Point-in-time correctness (no leakage) is the key DE/MLE signal here — features are
built from `fact_*` filtered to data available *before* each game.

## 5. dbt docs site
`dbt docs generate` produces a browsable lineage graph + column-level documentation
for the entire Silver→Gold model. Published (e.g. as a static site / Databricks
workspace artifact) it's one of the most compelling single artifacts for a DE
portfolio — it shows modeling discipline at a glance.

## 6. Presenting it as a portfolio piece

A suggested narrative for the case study / repo README:

1. **The problem** — a complete, governed NBA warehouse from a flaky, throttled,
   140-endpoint public API.
2. **The architecture** — the hybrid medallion (Auto Loader + dbt), with the
   diagram from the [overview](README.md).
3. **The hard parts** — dependency-aware crawling, rate-limit resilience,
   idempotent replay, schema-drift survival, box-score variant unification.
4. **Engineering rigor** — registry-generated contracts, `dbt build` quality gate,
   CI on an ephemeral catalog, full IaC via DAB.
5. **The payoff** — dashboards, Genie, an ML model, dbt docs, and an MCP agent demo.
6. **Reproducibility** — "clone → `databricks bundle deploy` → `dbt build`."

Artifacts to capture: the architecture diagram, a dbt docs screenshot, a dashboard
GIF, a Genie Q&A, an agent/MCP transcript, and the CI run. Link them from the repo
README and (optionally) a short blog post.

Next: **[06 — Roadmap](06-roadmap.md)**.
