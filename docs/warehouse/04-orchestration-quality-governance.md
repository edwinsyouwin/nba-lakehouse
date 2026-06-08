# 04 — Orchestration, Quality & Governance

## 1. Orchestration — one Lakeflow Job, all serverless

The daily pipeline is a single **Lakeflow Job** that chains the whole flow. The dbt
step uses the **native `dbt` task type**, executing on the **serverless SQL
warehouse**, authenticated as the job's **service principal** (no token in
`profiles.yml`).

```
nba-daily-refresh  (cron: 09:00 ET)
  extract_and_land ──▶ bronze_autoloader ──▶ dbt_silver_gold ──▶ refresh_dashboard
   (Python task,        (Lakeflow            (native dbt task,     (AI/BI dashboard
    serverless           pipeline,            serverless SQL:       refresh)
    job compute)         Auto Loader)         deps→run→test)
```

DAB definition (the orchestration backbone):

```yaml
# resources/nba_daily_job.yml
resources:
  jobs:
    nba_daily:
      name: nba-daily-refresh
      schedule:
        quartz_cron_expression: "0 0 13 * * ?"   # 09:00 ET == 13:00 UTC
        timezone_id: America/New_York
      email_notifications:
        on_failure: ["edwin.t.lee@gmail.com"]
      tasks:
        - task_key: extract_and_land
          spark_python_task:
            python_file: ../src/nba_warehouse/run_extract.py
            parameters: ["--mode", "daily"]
          environment_key: serverless

        - task_key: bronze_autoloader
          depends_on: [{ task_key: extract_and_land }]
          pipeline_task: { pipeline_id: ${resources.pipelines.nba_bronze.id} }

        - task_key: dbt_silver_gold
          depends_on: [{ task_key: bronze_autoloader }]
          dbt_task:
            project_directory: ../dbt
            catalog: nba
            schema: silver
            warehouse_id: ${var.serverless_warehouse_id}
            commands:
              - "dbt deps"
              - "dbt snapshot --target ${bundle.target}"
              - "dbt build    --target ${bundle.target}"   # run + test together
          environment_key: serverless

        - task_key: refresh_dashboard
          depends_on: [{ task_key: dbt_silver_gold }]
          # dashboard refresh task

      environments:
        - environment_key: serverless
          spec: { client: "1" }
```

### Why `dbt build`
`dbt build` runs models, snapshots, seeds, and **tests in DAG order**, so a failed
test on `dim_player` stops dependent facts from publishing — the pipeline **fails
closed**. That single command is the quality gate.

### Backfill is a separate job
Backfilling decades of games is expensive and heavily throttled, so it must not
share the daily job's schedule or rate budget.

```
nba-backfill (manually/parametrized triggered)
  extract_backfill(--mode backfill --seasons 1996-97..2024-25 --groups boxscore,pbp,shots)
    ──▶ bronze_autoloader ──▶ dbt build --full-refresh
```

- Parametrized by season range + endpoint groups; chunked per season so failures
  are isolated and resumable via `ops.crawl_state`.
- Runs with a larger rate budget / optional proxy pool (see [02 §5](02-source-and-ingestion.md)).
- After backfill completes, the daily job takes over the delta.

## 2. Data quality

Two enforcement points, each owning what it's best at:

**Bronze (structural, in the Lakeflow pipeline)** — `@expect` assertions:
- lineage columns non-null, payload parseable, `_rescued_data` monitored.
- Drops/quarantines malformed records; logs schema-evolution events.

**Silver/Gold (semantic, in dbt)** — the primary quality layer, run by `dbt build`:

| Test type | Examples |
|---|---|
| `unique` / `not_null` | every dim PK; `(game_id, player_id)` on `fact_player_game` |
| `relationships` | every fact FK resolves to its dim (no orphan games/players/teams) |
| `accepted_values` | season types, shot zones, event types |
| `dbt_expectations` | `0 ≤ *_pct ≤ 1`; `points ≥ 0`; per-season row-count within expected band; **source freshness** (Bronze updated within 24h) |
| **singular** | team points = Σ player points per game; lineup stints sum to 48 min/game; shots in `fact_shot` ≈ FGA in box score |

Severity: structural tests are `error` (fail the run); plausibility/freshness can
be `warn` with alerting, so a minor API hiccup doesn't block the whole warehouse.

**Lakehouse Monitoring** on key Gold tables tracks drift/volume over time
(row counts, null rates, distribution shifts) and surfaces anomalies on a dashboard.

## 3. Governance (Unity Catalog)

- **Single `nba` catalog**, schema = layer. Drop/rebuild is one statement.
- **Least-privilege grants** (managed in DAB / `grants.sql`):
  - Analysts / BI / Genie / MCP service principal → `SELECT` on `nba.gold` only.
  - Data engineers → full on `nba`.
  - Bronze/ops restricted to the pipeline service principals.
- **Lineage**: Unity Catalog captures table/column lineage across the Auto Loader
  pipeline and dbt automatically; **dbt docs** adds a model-level DAG + descriptions
  published as a static site (see [05](05-analytics-and-showcase.md)).
- **Tags & docs**: tag PII-sensitivity (none expected — public sports data),
  freshness tier, and ownership; descriptions flow from dbt model YAML into UC
  comments via persist_docs.
- **No PII**: data is public; still, we keep the principle explicit so the project
  demonstrates governance discipline.
- **Service principals**: the daily job, backfill job, and dbt task run as a
  dedicated SP, not a user — auditable and rotation-friendly.

## 4. CI/CD

Reuse the repo's existing **CircleCI** + **pre-commit**, extended for the warehouse:

| Stage | Action |
|---|---|
| **pre-commit** | `sqlfluff` lint (dbt dialect), `dbt parse`, yaml/format checks |
| **CI (PR)** | `databricks bundle validate`; `dbt deps`; `dbt build --target ci` against an **ephemeral `nba_ci` catalog** seeded with a small Bronze sample → runs all models + tests; `pytest` for `nba_warehouse` (registry, rate limiter, crawler unit tests) |
| **CD (merge to main)** | `databricks bundle deploy --target prod` (jobs, pipeline, dbt project, dashboards); optionally `dbt docs generate` + publish |

The `nba_ci` target gives true model+test coverage on every PR without touching
prod data — the headline reproducibility story for the case study.

## 5. Observability & ops control plane
- `ops.crawl_state` — per-(endpoint, params, season) capture status → resumability.
- `ops.run_log` — per-call metrics, errors, dead-letters, rate-limit events.
- `ops.endpoint_registry` — generated catalog of the API surface (queryable docs).
- dbt artifacts (`run_results.json`, `manifest.json`) optionally loaded to
  `ops.dbt_run_results` for historical test/runtime trend dashboards.
- Failure alerts via job `email_notifications` (+ optional webhook to Slack).

Next: **[05 — Analytics & Showcase](05-analytics-and-showcase.md)**.
