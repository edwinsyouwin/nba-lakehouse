# NBA Lakehouse — Project Overview

> Turning the [`nba_api`](../../README.md) Python client into a modern, governed
> data warehouse on the Databricks Lakehouse that contains **all data the NBA
> Stats API exposes**, and powers real sports-analytics use cases.

This folder documents the full design and the ordered steps to build it. It is
written to be read top-to-bottom by a reviewer evaluating data-engineering
craft, and to be executed phase-by-phase by whoever builds it.

**Locked architecture:** a **hybrid** stack — native **Auto Loader** lands raw API
data in **Bronze**, and **dbt Core** (running on the **serverless SQL warehouse**)
owns the **Silver → Gold** dimensional modeling. Everything is orchestrated by a
single **Lakeflow Job** and deployed from code via **Databricks Asset Bundles**.

---

## 1. Goal & success criteria

**Goal:** ingest the complete NBA Stats API surface into a Unity Catalog–governed
medallion lakehouse, model it dimensionally with dbt, and ship analytics products
(dashboards, a natural-language Genie space, and at least one ML model) on top.

**Done looks like:**

| Dimension | Target |
|---|---|
| **Coverage** | Every `nba_api` stats endpoint result set has a Bronze table; the analytics "core spine" (games, box scores, play-by-play, shots, rosters) is modeled through Gold. |
| **Freshness** | Yesterday's games land in Gold by 9am ET daily, automatically. |
| **Quality** | Every dbt model has tests; the daily job fails closed when `dbt test` or Bronze expectations fail. |
| **Governance** | All data in a dedicated `nba` catalog, lineage captured (incl. dbt docs), least-privilege grants, PII-free. |
| **Reproducibility** | Entire platform deploys from code via Databricks Asset Bundles — `databricks bundle deploy` from zero. |
| **Showcase** | ≥1 AI/BI dashboard, a Genie space, an ML model, a published dbt docs site, and a written case study. |

---

## 2. Architecture at a glance

```
                          NBA Stats API  (stats.nba.com / live)
                                   │   140 stats + 4 live endpoints
                                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  EXTRACTION FRAMEWORK  (nba_warehouse package, built on nba_api)   │
   │  endpoint registry · dependency-aware crawler · rate-limit/retry   │
   │  · raw-response capture · landing to a UC Volume (JSON)            │
   └──────────────────────────────────────────────────────────────────┘
                                   ▼   Auto Loader (native, serverless)
   ┌───────────────┐               ┌───────────────┐               ┌───────────────┐
   │   BRONZE      │     dbt       │    SILVER     │      dbt       │     GOLD      │
   │ raw, as-is    │  ──────────▶  │ typed, clean, │   ─────────▶   │ star schema,  │
   │ 1 tbl / result│   (Core, on   │ conformed,    │   (Core, on    │ marts, feature│
   │ set + payload │  serverless   │ deduped, SCD2 │   serverless   │ tables        │
   │ Auto Loader   │   SQL whse)   │ (snapshots)   │    SQL whse)   │               │
   └───────────────┘               └───────────────┘               └───────────────┘
     nba.bronze                       nba.silver                     nba.gold / nba.feature
        ▲                                                                   │
        │ Lakeflow Job (one schedule): crawl → land → Bronze → dbt run/test → dashboard
        └───────────────────────────────────────────────────────────────────┘
                                   ▼
        AI/BI Dashboards   ·   Genie Space (NL → SQL)   ·   ML (MLflow)   ·   MCP (agents)
```

**Stack** (serverless-first, matching your current workspace):

- **Storage / format:** Delta Lake tables in **Unity Catalog**, liquid clustering (not Hive partitioning).
- **Ingestion:** custom Python extractor (extends `nba_api`) → JSON in a **UC Volume** → **Auto Loader** streaming tables = **Bronze**.
- **Transformation (Silver → Gold):** **dbt Core** with the `dbt-databricks` adapter, executing on the **serverless SQL warehouse**. SCD2 via **dbt snapshots**; quality via **dbt tests**.
- **Orchestration:** one **Lakeflow Job** with a native **dbt task**, scheduled daily, plus a separate backfill job.
- **IaC / CI-CD:** **Databricks Asset Bundles (DAB)**; reuse the repo's existing CircleCI + pre-commit. CI runs `dbt build` against a dev target.
- **Serving:** **AI/BI Dashboards + Genie**, **MLflow / Unity Catalog Models**, **dbt docs** site, and the **UC-functions MCP server** already wired into this session for agentic querying.

See **[01-architecture.md](01-architecture.md)** for the full rationale and the Unity Catalog layout.

---

## 3. Document index

| Doc | Covers |
|---|---|
| [01-architecture.md](01-architecture.md) | Lakehouse & medallion design, the hybrid Auto Loader + dbt split, Unity Catalog namespace, infra, technology choices and trade-offs |
| [02-source-and-ingestion.md](02-source-and-ingestion.md) | The `nba_api` surface, endpoint taxonomy, the dependency/crawl DAG, rate-limit strategy, the extraction framework, Bronze (Auto Loader) |
| [03-data-model.md](03-data-model.md) | dbt project layout; Silver staging/cleansing + snapshots (SCD2); the Gold dimensional (star-schema) model with fact/dim definitions |
| [04-orchestration-quality-governance.md](04-orchestration-quality-governance.md) | The Lakeflow Job + native dbt task, scheduling, backfill, dbt tests, Unity Catalog governance, lineage, monitoring, CI/CD |
| [05-analytics-and-showcase.md](05-analytics-and-showcase.md) | Dashboards, Genie, ML use cases, the MCP agent layer, dbt docs, and how to present it as a portfolio piece |
| [06-roadmap.md](06-roadmap.md) | The ordered, phased build plan with milestones, deliverables, and acceptance criteria |

---

## 4. Phased roadmap (summary)

The detailed, checkable version is in **[06-roadmap.md](06-roadmap.md)**.

| Phase | Theme | Outcome |
|---|---|---|
| **0** | Foundations | UC `nba` catalog + schemas + volume, DAB skeleton, dbt project + `profiles`, serverless warehouse wired, secrets |
| **1** | Reference & spine | Static teams/players, seasons, games ingested Bronze→Gold; first dims & `fact_team_game` via dbt |
| **2** | Game detail | Box scores (all variants), play-by-play, shots → Silver staging + Gold facts in dbt |
| **3** | Breadth | Remaining 140 endpoints auto-registered to Bronze; player/team dashboards & tracking staged in dbt |
| **4** | Incremental & ops | Daily Lakeflow Job (crawl→Bronze→dbt), backfill job, dbt tests, Lakehouse Monitoring, alerts |
| **5** | Analytics products | Dashboards, Genie space, ML model, dbt docs site, MCP-driven agent demo, case study |

---

## 5. Repo layout

The project **depends on** `nba_api` (pinned in `pyproject.toml`) rather than
vendoring or forking it — the client stays the trusted source-of-truth for
endpoint contracts, imported at runtime by the registry.

```
nba-lakehouse/
│                            # nba_api: a pip/Poetry dependency (not vendored)
├── src/nba_warehouse/          # extraction framework built on nba_api
│   ├── registry.py             #   auto-derive endpoint/result-set/param metadata from nba_api
│   ├── extract.py              #   dependency-aware, rate-limited crawler
│   ├── landing.py              #   raw-response capture → UC Volume
│   ├── run_extract.py          #   job entrypoint
│   └── config/                 #   endpoint priorities, season ranges, params
├── pipelines/
│   └── bronze/                 # NEW — Lakeflow pipeline: Auto Loader → Bronze streaming tables
├── dbt/                        # NEW — dbt Core project (owns Silver → Gold)
│   ├── dbt_project.yml
│   ├── models/
│   │   ├── staging/            #   stg_* : 1:1 typed/renamed views over Bronze
│   │   ├── intermediate/       #   int_* : reusable joins/derivations
│   │   └── marts/
│   │       ├── core/           #   dim_*, fact_*  (the star schema)
│   │       └── analytics/      #   mart_* : use-case aggregates
│   ├── snapshots/              #   SCD2 for players/teams
│   ├── tests/                  #   generic + singular data tests
│   ├── macros/
│   └── seeds/                  #   small static lookups (season types, shot zones)
├── resources/                  # NEW — DAB job/pipeline/dashboard definitions
├── databricks.yml              # NEW — Databricks Asset Bundle root
└── docs/warehouse/             # this folder
```

> dbt and the Lakehouse share **one source of truth for table contracts**: the
> `nba_warehouse.registry` is generated from `nba_api`'s `expected_data`, and dbt
> `sources.yml` is generated from the same registry — so Bronze, staging models,
> and tests never drift from the upstream API definitions. See [03](03-data-model.md).

---

## 6. Current environment (verified)

- Workspace `dbc-16b7e00d-e6b0.cloud.databricks.com` (AWS, us-east-2), serverless metastore.
- Catalogs: `main`, `workspace`, `system`. Owner: `edwin.t.lee@gmail.com`.
- Compute: 1 serverless SQL warehouse (`Serverless Starter Warehouse`, 2X-Small) — this is the dbt execution target. No all-purpose clusters or pipelines yet — a clean slate.
- An **MCP server** (`databricks-uc-functions`, scoped to `main.default`) is already connected in this Claude Code session; it will be re-pointed at the `nba` catalog once it exists (see [05](05-analytics-and-showcase.md)).
