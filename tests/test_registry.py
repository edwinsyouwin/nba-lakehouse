"""Tests for the endpoint registry derived from nba_api."""

from nba_warehouse.registry import build_registry, registry_summary


def test_registry_is_non_trivial():
    specs = build_registry()
    # nba_api ships well over 100 stats endpoints.
    assert len(specs) >= 100


def test_every_endpoint_has_result_sets():
    for spec in build_registry():
        assert spec.result_sets, f"{spec.name} has no result sets"
        for rs in spec.result_sets:
            assert rs.name
            # NB: a few nba_api result sets declare zero columns (e.g.
            # defensehub.DefenseHubStat10). That's valid — Auto Loader infers the
            # schema at ingest — so we only require a name here.


def test_bronze_table_naming_is_unique():
    tables = [t for s in build_registry() for t in s.bronze_tables()]
    assert len(tables) == len(set(tables)), "duplicate bronze table names"


def test_summary_counts_are_consistent():
    summary = registry_summary()
    assert summary["result_sets"] == summary["bronze_tables"]
    assert summary["endpoints"] >= 100
