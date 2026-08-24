"""Import-direction guard for `services/`.

Tom's ask: *"làm microservice để khi cập nhật các tính năng và thay đổi không bị
biến dạng các phần còn lại"* — change one feature without deforming the rest, and
make it easier for an AI agent to edit.

We did **not** split into processes (one trader, one machine, one SQLite; §18.4/18
already flags multi-writer WAL as a risk, and 8 Task Scheduler jobs invoke
`main.py` from the repo root). What actually causes "fix here, break there" is
not the process count — it is an import graph nobody can see. So the boundary is
enforced here instead, at the only place a violation is cheap to catch.

The layering below is **descriptive, then binding**: it was read off the graph
that already existed (measured 2026-08-24 — 17 modules, max depth 2, and only
one violation, which was a cycle). It is written down so the next edit cannot
quietly add a second one.

Why an AST walk rather than importing the modules and inspecting them: importing
`services.*` pulls in SQLAlchemy, vnstock and a live DB engine, and
`generate_report.py` sends mail as a side effect of import (§20.3 P3-2). A test
that has to boot the world to check a static property will eventually be deleted
for being slow. This reads source text and touches nothing.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVICES = REPO / "services"

#: Which layer each service module belongs to. Every `services/*.py` must appear
#: here — a new module with no layer fails `test_every_service_has_a_layer`,
#: which is the point: choosing a layer is a design decision, and the default
#: should be "state one", not "silently belong to none".
LAYER: dict[str, str] = {
    # ingest — talks to the outside world (vnstock, FRED, stooq). Depends on
    # nothing else in services/, so a data-source change stays local.
    "sector_ingest_service": "ingest",
    "fast_ingest": "ingest",
    "macro_service": "ingest",
    "foreign_flow": "ingest",
    # features — turns rows into features. Reads ingest output from the DB.
    "flow_feature_service": "features",
    "flow": "features",  # package: services/flow/aggregation.py
    # decide — models, scoring, signals, picks. The layer that has opinions.
    "rotation_model_service": "decide",
    "sector_signal_service": "decide",
    "picks_universe_service": "decide",
    "picks_scoring": "decide",
    "picks_news": "decide",
    "unified_picks": "decide",
    "backtest_service": "decide",
    # book — what the operator actually did. Deliberately depends on nothing:
    # the kill-switch must be readable by the scheduler process, which has no
    # HTTP client and must not drag the model layer in to read one bool (§22.10).
    "trading_state": "book",
    "risk_service": "book",
    # report / agent — the two output surfaces.
    "report_runner": "report",
    "trader_agent": "agent",
    "insight_refresh": "agent",
}

#: What each layer may import *from services*. Anything outside services/
#: (config, database, analysis, utils, models) is unrestricted — those are
#: shared leaves, not layers, and gating them would be cargo-culting.
ALLOWED: dict[str, set[str]] = {
    "ingest": set(),
    "features": {"ingest"},
    "decide": {"ingest", "features", "decide"},
    "book": set(),
    "report": {"decide", "book"},
    "agent": {"decide", "agent"},
}

#: Packages above services/ in the stack. A module under services/ importing one
#: of these is an upward arrow, i.e. a cycle waiting to happen. It caught a real
#: one on 2026-08-24: `insight_refresh` did `from api.routers.insight import
#: insight_daily` inside a function, and `api.routers.insight` imports
#: `insight_refresh` — quiet only because both ends were lazy. Fixed by the
#: router pushing its builder down via `set_payload_builder()`.
UPWARD = {"api", "main", "generate_report"}


def _modules() -> list[tuple[str, pathlib.Path]]:
    """(module name, file) for every unit under services/. A package counts as
    one unit — `services/flow/` is one boundary, not one per file."""
    out: list[tuple[str, pathlib.Path]] = []
    for p in sorted(SERVICES.glob("*.py")):
        if p.name != "__init__.py":
            out.append((p.stem, p))
    for d in sorted(SERVICES.iterdir()):
        if d.is_dir() and (d / "__init__.py").exists():
            for p in sorted(d.rglob("*.py")):
                out.append((d.name, p))
    return out


def _imports(path: pathlib.Path) -> list[tuple[str, int]]:
    """(dotted module, lineno) for every import in a file, lazy ones included.

    Function-local imports count. Both defects this file exists to catch — the
    api cycle and the dead `services.data_service` reference — were invisible at
    module level; deferring an import hides a dependency from the reader without
    removing it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[str, int]] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            # Relative imports stay inside their own package by construction.
            if n.level == 0 and n.module:
                out.append((n.module, n.lineno))
        elif isinstance(n, ast.Import):
            out.extend((a.name, n.lineno) for a in n.names)
    return out


def _service_dep(mod: str) -> str | None:
    """`services.picks_news` -> `picks_news`; anything else -> None."""
    parts = mod.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "services" else None


def test_every_service_has_a_layer():
    """A new module must declare where it lives. Failing here is not a bug —
    it is the test asking you to make the call you were about to skip."""
    missing = sorted({name for name, _ in _modules()} - set(LAYER))
    assert not missing, (
        f"services modules with no layer in LAYER: {missing}. "
        "Add them to tests/test_module_boundaries.py::LAYER."
    )


def test_layer_table_has_no_ghosts():
    """The reverse: a module listed here that no longer exists. Left unchecked,
    the table slowly becomes a description of a repo that used to be."""
    real = {name for name, _ in _modules()}
    ghosts = sorted(set(LAYER) - real)
    assert not ghosts, f"LAYER names modules that do not exist: {ghosts}"


@pytest.mark.parametrize("name,path", _modules(), ids=lambda v: getattr(v, "name", str(v)))
def test_no_service_imports_upward(name: str, path: pathlib.Path):
    """services/ must not import api/, main or generate_report."""
    bad = [
        (m, ln) for m, ln in _imports(path)
        if m.split(".")[0] in UPWARD
    ]
    assert not bad, (
        f"{path.relative_to(REPO)} imports upward: {bad}. "
        "Invert the dependency — have the caller inject what it needs "
        "(see insight_refresh.set_payload_builder)."
    )


@pytest.mark.parametrize("name,path", _modules(), ids=lambda v: getattr(v, "name", str(v)))
def test_service_imports_respect_the_layering(name: str, path: pathlib.Path):
    layer = LAYER.get(name)
    if layer is None:
        pytest.skip("covered by test_every_service_has_a_layer")
    allowed = ALLOWED[layer]
    bad = []
    for mod, ln in _imports(path):
        dep = _service_dep(mod)
        if dep is None or dep == name:
            continue
        dep_layer = LAYER.get(dep)
        if dep_layer is None:
            bad.append(f"{mod}:{ln} (unknown module — deleted?)")
        elif dep_layer not in allowed:
            bad.append(f"{mod}:{ln} ({layer} -> {dep_layer} not allowed)")
    assert not bad, f"{path.relative_to(REPO)}: {bad}"


def test_every_service_import_in_the_repo_resolves():
    """`from services.X import ...` where X does not exist.

    Caught `scripts/seed_data.py` importing `services.data_service`, deleted
    2026-04-22 (`ARCHITECTURE.md` Phase 16). It sat broken for four months
    because nothing runs it, which is exactly how a stale import survives —
    ruff's F401 only sees unused imports, not unresolvable ones.
    """
    real = {name for name, _ in _modules()}
    bad: list[str] = []
    for d in ("api", "scripts", "services", "analysis", "models", "utils"):
        for p in (REPO / d).rglob("*.py"):
            for mod, ln in _imports(p):
                dep = _service_dep(mod)
                if dep is not None and dep not in real:
                    bad.append(f"{p.relative_to(REPO)}:{ln} -> {mod}")
    for p in REPO.glob("*.py"):
        for mod, ln in _imports(p):
            dep = _service_dep(mod)
            if dep is not None and dep not in real:
                bad.append(f"{p.name}:{ln} -> {mod}")
    assert not bad, f"imports of non-existent services modules: {bad}"


def test_the_book_layer_stays_dependency_free():
    """Named separately from the generic layer test because it is the one whose
    *reason* is operational rather than tidiness.

    `trading_state` holds the kill-switch, and the scheduler reads it straight
    off disk with no HTTP client (§22.10). If it ever grows a dependency on the
    model layer, stopping the 17:00 publish starts requiring the model layer to
    import cleanly — which is precisely the situation you are in when you want
    to stop it.
    """
    for name, path in _modules():
        if LAYER.get(name) != "book":
            continue
        deps = {d for d in (_service_dep(m) for m, _ in _imports(path)) if d and d != name}
        assert not deps, f"{path.relative_to(REPO)} must not depend on services: {deps}"
