"""nba_warehouse — extraction framework that turns the NBA Stats API (via nba_api)
into a governed Databricks lakehouse.

This package depends on ``nba_api`` as the source-of-truth for endpoint contracts;
``registry`` introspects it so Bronze tables and dbt sources never drift from the
upstream API definitions.
"""

__version__ = "0.1.0"
