"""Derive a machine-readable registry of the NBA Stats API from the ``nba_api``
client. This is the single source of truth that drives:

  * the list of Bronze tables (one per endpoint result set), and
  * dbt ``sources.yml`` generation,

so the API contract, Bronze, and dbt staging models never drift apart.

The registry is built purely by introspecting ``nba_api`` — no network calls.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass, field, asdict
from typing import Any

# nba_api is a declared dependency (see pyproject.toml).
import nba_api.stats.endpoints as stats_endpoints
from nba_api.stats.endpoints._base import Endpoint


@dataclass(frozen=True)
class ResultSet:
    """One named result set returned by an endpoint -> one Bronze table."""

    name: str
    columns: tuple[str, ...]

    @property
    def bronze_table(self) -> str:
        # nba.bronze.<endpoint>__<ResultSet>
        return f"{{endpoint}}__{self.name}"


@dataclass(frozen=True)
class EndpointSpec:
    """Everything we need to know about one stats endpoint."""

    name: str           # e.g. "playercareerstats"
    class_name: str     # e.g. "PlayerCareerStats"
    module: str         # dotted module path
    parameters: tuple[str, ...]          # kwargs accepted by __init__
    required_parameters: tuple[str, ...]  # kwargs with no default
    result_sets: tuple[ResultSet, ...]

    def bronze_tables(self) -> list[str]:
        return [f"{self.name}__{rs.name}" for rs in self.result_sets]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["bronze_tables"] = self.bronze_tables()
        return d


# Endpoint base classes / helpers that should never be treated as endpoints.
_EXCLUDED = {"Endpoint"}


def _iter_endpoint_classes():
    """Yield concrete Endpoint subclasses defined in nba_api.stats.endpoints."""
    for mod_info in pkgutil.iter_modules(stats_endpoints.__path__):
        if mod_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{stats_endpoints.__name__}.{mod_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Endpoint)
                and obj is not Endpoint
                and obj.__name__ not in _EXCLUDED
                and getattr(obj, "expected_data", None)
                and obj.__module__ == module.__name__  # defined here, not imported
            ):
                yield module.__name__, obj


def _params(cls) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (all_params, required_params) from the endpoint __init__ signature."""
    sig = inspect.signature(cls.__init__)
    all_params, required = [], []
    for pname, p in sig.parameters.items():
        if pname in ("self", "args", "kwargs") or p.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        # nba_api passes these for transport, not API query params:
        if pname in ("proxy", "headers", "timeout", "get_request"):
            continue
        all_params.append(pname)
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    return tuple(all_params), tuple(required)


def build_registry() -> list[EndpointSpec]:
    """Introspect nba_api and return one EndpointSpec per stats endpoint."""
    specs: list[EndpointSpec] = []
    for module_name, cls in _iter_endpoint_classes():
        expected = cls.expected_data or {}
        result_sets = tuple(
            ResultSet(name=rs_name, columns=tuple(cols))
            for rs_name, cols in expected.items()
        )
        all_params, required = _params(cls)
        specs.append(
            EndpointSpec(
                name=getattr(cls, "endpoint", cls.__name__.lower()),
                class_name=cls.__name__,
                module=module_name,
                parameters=all_params,
                required_parameters=required,
                result_sets=result_sets,
            )
        )
    specs.sort(key=lambda s: s.name)
    return specs


def registry_summary() -> dict[str, int]:
    specs = build_registry()
    return {
        "endpoints": len(specs),
        "result_sets": sum(len(s.result_sets) for s in specs),
        "bronze_tables": sum(len(s.bronze_tables()) for s in specs),
    }


if __name__ == "__main__":
    import json

    summary = registry_summary()
    print(json.dumps(summary, indent=2))
    for spec in build_registry():
        print(f"{spec.name:40s} {len(spec.result_sets):2d} result set(s)")
