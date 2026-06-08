# nba-lakehouse

A modern, governed **data warehouse on the Databricks Lakehouse** that ingests the
**complete NBA Stats API surface**, models it dimensionally, and powers real
sports-analytics products — dashboards, a natural-language Genie space, ML models,
and an agent-ready (MCP) data interface.

Built on the excellent [`nba_api`](https://github.com/swar/nba_api) client (MIT),
used here as a dependency for its endpoint contracts — this project does not modify it.

> **Status:** design complete, implementation in progress. Start with the
> **[design & roadmap docs](docs/warehouse/README.md)**.

---

## Architecture (hybrid, serverless-first)

```
        NBA Stats API (140 stats + 4 live endpoints)
                       │
   nba_warehouse (Python, built on nba_api)        ← dependency-aware, rate-limited crawler
                       │  raw JSON → UC Volume
                       ▼
        Auto Loader ──▶ BRONZE  (raw, 1 table / endpoint result set)
                       │
            dbt Core ──▶ SILVER (typed, conformed, SCD2 snapshots)
        (serverless    │
         SQL whse)     ▼
                       GOLD   (Kimball star schema + analytics marts)
                       │
   AI/BI Dashboards · Genie (NL→SQL) · MLflow · UC-functions MCP (agents)
```

| Concern | Choice |
|---|---|
| Storage / format | Delta Lake + Unity Catalog (catalog `nba`, schema = medallion layer), liquid clustering |
| Extraction | Python (`src/nba_warehouse/`, extends `nba_api`) → JSON in a UC Volume |
| Bronze | **Auto Loader** streaming tables (thin Lakeflow pipeline) |
| Silver → Gold | **dbt Core** via `dbt-databricks` on the **serverless SQL warehouse** |
| SCD2 | dbt snapshots (players, teams) |
| Orchestration | one **Lakeflow Job** with a native **dbt task**, scheduled daily |
| Quality gate | `dbt build` (models + tests, fails closed) + Bronze expectations |
| IaC / CI-CD | **Databricks Asset Bundles**; CI runs `dbt build` on an ephemeral catalog |

Full rationale and trade-offs: **[docs/warehouse/01-architecture.md](docs/warehouse/01-architecture.md)**.

---

## Documentation

| Doc | Covers |
|---|---|
| [Overview](docs/warehouse/README.md) | Goals, architecture, repo layout, phase summary |
| [01 — Architecture](docs/warehouse/01-architecture.md) | Medallion design, hybrid Auto Loader + dbt split, Unity Catalog layout, trade-offs |
| [02 — Source & Ingestion](docs/warehouse/02-source-and-ingestion.md) | API surface, endpoint taxonomy, crawl DAG, rate-limit strategy, Bronze |
| [03 — Data Model](docs/warehouse/03-data-model.md) | dbt project, Silver staging/snapshots, Gold star schema |
| [04 — Orchestration, Quality & Governance](docs/warehouse/04-orchestration-quality-governance.md) | Lakeflow Job + dbt task, tests, Unity Catalog, CI/CD |
| [05 — Analytics & Showcase](docs/warehouse/05-analytics-and-showcase.md) | Dashboards, Genie, MCP, ML, dbt docs |
| [06 — Roadmap](docs/warehouse/06-roadmap.md) | Phased build plan with acceptance criteria |

---

## Planned repo layout

```
nba-lakehouse/
├── src/nba_warehouse/      # extraction framework built on nba_api (registry, crawler, landing)
├── pipelines/bronze/       # Lakeflow pipeline: Auto Loader → Bronze streaming tables
├── dbt/                    # dbt Core project (owns Silver → Gold)
├── resources/              # DAB job/pipeline/dashboard definitions
├── databricks.yml          # Databricks Asset Bundle root
└── docs/warehouse/         # design & roadmap (this is what's here today)
```

## Quickstart (target state)

```bash
poetry install
databricks bundle deploy --target dev      # creates catalog objects, pipeline, job
poetry run python -m nba_warehouse.run_extract --mode reference
cd dbt && dbt deps && dbt build --target dev
```

---

## Credits & license

- Built on [`nba_api`](https://github.com/swar/nba_api) by Swar Patel & contributors (MIT).
- This project is licensed under the MIT License — see [LICENSE](LICENSE).
- Data is sourced from the public NBA Stats API; this project is not affiliated with the NBA.
