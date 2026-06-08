# 01 — Architecture & Platform Design

## 1. Why a medallion lakehouse

The NBA Stats API is a sprawling, semi-documented, rate-limited REST surface that
returns denormalized "report" tables (one endpoint can return 5–10 differently
shaped result sets). The data is:

- **Heterogeneous** — 140 endpoints, hundreds of distinct result-set schemas.
- **Volatile at the edges** — column sets change between API versions (note the
  v2/v3 box-score duplication in the client); historical rows get corrected.
- **Dependency-heavy** — most detail endpoints need IDs discovered from other
  endpoints (you need a `game_id` before you can pull its play-by-play).

A **medallion architecture** (Bronze → Silver → Gold) is the right fit because it
separates *faithful capture* from *interpretation*:

- **Bronze** preserves exactly what the API returned, so we can replay and audit
  without re-hitting a throttled, sometimes-changing source.
- **Silver** absorbs schema drift and enforces types/keys once, centrally.
- **Gold** presents a stable, documented dimensional model that downstream
  analytics and ML depend on — insulated from API churn.

## 2. The hybrid split: Auto Loader for Bronze, dbt for Silver→Gold

A deliberate tool boundary, chosen so each tool does what it is best at:

| Layer | Owner | Why |
|---|---|---|
| **Extraction** | `nba_warehouse` Python (extends `nba_api`) | Only Python can crawl a dependency graph against a throttled REST API with retries/backoff. |
| **Bronze** | **Auto Loader** streaming tables (thin Lakeflow pipeline) | Native, serverless, exactly-once incremental file ingest with schema inference + rescue column. dbt does not ingest files. |
| **Silver → Gold** | **dbt Core** on the serverless SQL warehouse | SQL-first dimensional modeling, a `ref()`/`source()` DAG, `dbt test`, `dbt snapshot` (SCD2), and a published docs/lineage site — the highest-signal, most reviewable layer. |
| **Orchestration** | **Lakeflow Job** (native `dbt` task) | One schedule chains crawl → Bronze → `dbt run`/`dbt test` → dashboard; runs fully serverless. |

The rule we follow: **one owner per layer.** dbt never tries to ingest files, and
the Bronze pipeline never models business logic. The handoff is the `nba.bronze.*`
tables, which dbt reads via `sources.yml`.

### Where dbt runs (and why it's still serverless)

dbt Core (the OSS CLI) connects through the `dbt-databricks` adapter to a SQL
warehouse's `http_path`. We point it at the **Serverless SQL Warehouse**, so all
model SQL executes on serverless. In production the dbt CLI itself runs inside a
**native dbt task in a Lakeflow Job** on **serverless job compute**, authenticated
as the job's **service principal** (no token in `profiles.yml`). Result:
end-to-end serverless, zero clusters. (SQL models only — dbt *Python* models would
need a cluster, which we don't use here.)

## 3. Unity Catalog namespace

A single dedicated catalog keeps the project self-contained, governable, and easy
to drop/rebuild.

```
Catalog:  nba
├── Schema: bronze      -- raw, as-ingested (1 table per endpoint result set) + raw payload audit
├── Schema: silver      -- dbt: typed/renamed staging + intermediate + SCD2 snapshots
├── Schema: gold        -- dbt: star schema (dim_*, fact_*) and analytics marts (mart_*)
├── Schema: feature     -- ML feature tables (point-in-time correct)
├── Schema: ml          -- registered models, inference outputs
├── Schema: ops         -- pipeline control: crawl_state, watermarks, run_log
└── Volume: nba.ops.landing   -- raw JSON responses land here for Auto Loader
```

Mapping to dbt: the dbt project writes the `silver` and `gold` schemas. By dbt
convention we set `catalog: nba` and use **custom schemas per folder** —
`staging`/`intermediate` materialize into `silver`, `marts` into `gold` — via a
`generate_schema_name` macro so dbt's default `<target>_<schema>` prefixing is
overridden to clean schema names.

Rationale:

- **One catalog, schema = layer.** Clean lineage, simple grants (read `gold`, deny
  `bronze` to analysts), and `DROP CATALOG nba CASCADE` rebuilds from scratch.
- **`ops` schema as the control plane.** Crawl checkpoints and watermarks live *in
  the lakehouse* as Delta tables — queryable, versioned, recoverable.
- **`feature`/`ml` separated** so ML artifacts have their own access model and the
  analytics Gold layer stays BI-focused.

> Environments: prefix the catalog per target — `nba_dev`, `nba_prod` — selected by
> the DAB target **and** the dbt `--target`. Same code, isolated data.

## 4. Storage & physical design

- **Delta Lake** everywhere (ACID, time travel, schema evolution, `MERGE`).
- **Liquid clustering** instead of partitioning. In dbt, set on models via
  `cluster_by` config (e.g. `fact_player_game` on `(game_date, team_id)`,
  `fact_play_by_play` on `(game_id)`). Liquid clustering avoids the small-files and
  skew problems Hive partitioning causes with uneven NBA data (a 1950s season has
  a fraction of a modern season's rows).
- **Predictive Optimization** is already `ENABLE` on the metastore — let Databricks
  manage `OPTIMIZE`/`VACUUM`.
- **Auto Loader** ingests landed JSON incrementally with schema inference +
  `_rescued_data`, so new/late files are picked up exactly once into Bronze.

## 5. Compute strategy (serverless-first)

Your workspace is serverless-only today, which is ideal — no cluster fleet to manage.

| Workload | Compute |
|---|---|
| Extraction (API crawl) | Serverless job compute running the `nba_warehouse` Python task. Network-bound; concurrency is governed by the rate limiter, not cores. |
| Bronze ingest | **Serverless Lakeflow pipeline** (Auto Loader streaming tables). |
| Silver→Gold (dbt) | **Serverless SQL Warehouse** via the native dbt task. |
| Ad-hoc SQL / dashboards / Genie / MCP | The same Serverless SQL Warehouse. |
| ML training | Serverless job compute + MLflow. |

## 6. Technology choices & trade-offs

| Decision | Choice | Why / alternative considered |
|---|---|---|
| Silver→Gold engine | **dbt Core** | Ubiquitous, SQL-first, `ref()` DAG, tests, and a `dbt docs` lineage site — the most reviewable artifact for a DE portfolio. Alternative (all-DLT) is simpler operationally and has native SCD2/streaming, but shows a single Databricks-specific tool. |
| Bronze ingest | **Auto Loader (thin Lakeflow pipeline)** | Native exactly-once incremental file ingest dbt can't do. Alternative (plain Spark `readStream`) works but loses DLT's lineage/observability. |
| Ingestion landing | **JSON files in a UC Volume + Auto Loader** | Decouples the fragile API crawl from transformation; gives a replayable raw archive. Alternative (write Delta directly from the extractor) couples crawl reliability to table writes and loses the raw audit trail. |
| Modeling style | **Kimball star schema** in Gold | Best for BI/Genie/exec consumption and for demonstrating modeling. Wide marts are added *on top* for ML/feature needs. |
| Slowly-changing entities | **dbt snapshots (SCD2)** for players & teams | Player team/position and team name/city change over time; `dbt snapshot` captures history as a first-class, version-controlled model. |
| dbt execution | **Serverless SQL Warehouse via native dbt task** | Fully serverless, identity-based auth, scheduled in Lakeflow Jobs. Alternative (dbt Cloud) is a separate paid scheduler outside the workspace. |
| IaC | **Databricks Asset Bundles** | One `databricks.yml` deploys catalog objects, the Bronze pipeline, the dbt job, and dashboards across dev/prod. Alternative (Terraform) is heavier. |

## 7. Idempotency & replay (cross-cutting principle)

Every layer is designed to be safely re-runnable:

- **Extraction** records each successful pull in `ops.crawl_state` keyed by
  `(endpoint, param_hash, season)` so re-runs skip already-captured slices and
  resume after failures.
- **Bronze** is append-only from Auto Loader; the raw payload archive
  (`bronze._raw_api_responses`) means any Silver/Gold model can be fully rebuilt
  from disk without touching the API.
- **Silver/Gold (dbt)** use `incremental` models with `merge` (keyed on natural
  keys) and `snapshot` for SCD2, so `dbt build` is convergent — reprocessing the
  same Bronze data yields the same result. `dbt build --full-refresh` rebuilds from
  Bronze when contracts change.

This is what makes a flaky, throttled source safe to build a warehouse on — and is
the single most important design property to highlight in the case study.
