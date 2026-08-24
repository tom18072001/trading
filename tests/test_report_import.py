"""`import generate_report` must do nothing.

Until 2026-08-24 it did everything: read the DB, call the LLM, render ~15
matplotlib figures, write an HTML and a PDF, and **send the email** — all at
module level, driven by `sys.argv`. That is why it had zero tests (§20.3 P3-2)
and why `/api/state/report/send` shells out to a subprocess (§24.3).

These tests pin the property, not the refactor. Any future change that moves
work back to module scope fails here rather than in Tom's inbox.
"""
from __future__ import annotations

import ast
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPORT_PY = ROOT / "generate_report.py"


def test_importing_the_report_sends_no_mail(monkeypatch):
    """The one that matters: import must not reach SMTP.

    `smtplib.SMTP` is replaced with a bomb rather than a recording mock — a
    mock lets the import finish and reports afterwards, which is exactly the
    behaviour that shipped for months. This fails loudly at the moment of the
    call.
    """
    import smtplib

    def _bomb(*a, **kw):  # noqa: ANN002, ANN003
        raise AssertionError("import generate_report attempted to send mail")

    monkeypatch.setattr(smtplib, "SMTP", _bomb)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _bomb)

    sys.modules.pop("generate_report", None)
    mod = importlib.import_module("generate_report")
    assert callable(mod.main)


def test_importing_the_report_opens_no_database(monkeypatch):
    """Import must not touch the DB either.

    Separate from the mail test on purpose: the DB open is the *first* thing
    the old module body did, so a regression would trip this one and never
    reach SMTP. Two symptoms of the same defect, two failure messages.
    """
    def _bomb(*a, **kw):  # noqa: ANN002, ANN003
        raise AssertionError("import generate_report attempted to open the DB")

    monkeypatch.setattr(sqlite3, "connect", _bomb)

    sys.modules.pop("generate_report", None)
    importlib.import_module("generate_report")


def test_importing_the_report_writes_no_files(tmp_path, monkeypatch):
    """No HTML, no PDF, no chart PNG as a side effect of import."""
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("generate_report", None)
    importlib.import_module("generate_report")
    assert list(tmp_path.iterdir()) == []


def test_the_work_lives_inside_main_not_at_module_level():
    """Structural, so it cannot be satisfied by luck.

    The three tests above pass if the module happens to guard its side effects;
    this one asserts the body is genuinely inside a function. Counting
    module-level statements is crude but it is the property being defended: the
    file was 1,640 lines of them.
    """
    tree = ast.parse(REPORT_PY.read_text(encoding="utf-8"))
    executable = [
        n for n in tree.body
        if not isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                              ast.AsyncFunctionDef, ast.ClassDef, ast.Expr))
    ]
    # What legitimately remains: constants, the try/except stdout reconfigure,
    # and the `if __name__` guard. A body that grows past this is the old shape
    # coming back.
    assert len(executable) < 40, (
        f"{len(executable)} module-level statements — the report body belongs "
        "in main()"
    )
    assert any(
        isinstance(n, ast.If)
        and isinstance(n.test, ast.Compare)
        and getattr(n.test.left, "id", None) == "__name__"
        for n in tree.body
    ), "missing `if __name__ == '__main__'` guard"


@pytest.mark.parametrize("mod", [
    "services.report.format",
    "services.report.charts",
    "services.report.data",
])
def test_the_extracted_pieces_import_clean(mod):
    """Each extracted module must stand alone.

    `charts` in particular sets the Agg backend at import; if that ever moves
    into a caller the daily job dies headless under Task Scheduler.
    """
    importlib.import_module(mod)


def test_charts_pins_the_headless_backend():
    import matplotlib

    importlib.import_module("services.report.charts")
    assert matplotlib.get_backend().lower() == "agg"
