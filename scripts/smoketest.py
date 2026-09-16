"""Smoketest — does this install actually work, right now, on this machine?

`pytest` answers a different question. Every test fakes vnstock, fakes the LLM,
and (since 2026-08-24) redirects `SAVED_MODELS_DIR` to a tmpdir — deliberately,
so the suite is fast and offline. The consequence is that a green suite says
nothing about the artefacts production reads:

  - the ranker that pytest used to overwrite with a 3-feature test panel, which
    killed the 17:00 publish while `git status` stayed clean and 342 tests
    stayed green (CLAUDE.md §19, tests/conftest.py::_models_go_to_a_tmpdir);
  - the picks snapshot, whose absence blanked the homepage after every restart
    for months (§22.6);
  - `/api/stealth/history`, which returned a hardcoded `{"rows": []}` and was
    indistinguishable from the truth until §16.1 started firing (§22.11).

Every check below is one of those: real DB, real artefacts on disk, real
routers. What it is NOT is a test of correctness — it asks whether the wiring
is intact, not whether the numbers are right.

Run:  uv run python scripts/smoketest.py
      uv run python scripts/smoketest.py --with-report   # also renders the PDF
Exit: 0 all pass · 1 something is broken

No network: the API is exercised in-process through FastAPI's TestClient, so
nothing binds a port and no scheduled job is disturbed. `--with-report` is the
exception — it shells out to `generate_report.py --no-email`, which does reach
vnstock, takes minutes, and is off by default for that reason.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from config import DATABASE_PATH, SAVED_MODELS_DIR  # noqa: E402
from scripts.check_freshness import DEFAULT_MAX_GAP, latest_flow_date  # noqa: E402
from utils.clock import today  # noqa: E402

# ── checks ──────────────────────────────────────────────────────────────────
# Each returns (ok: bool, detail: str). A check that raises is a failure with
# the exception as its detail — a smoketest that crashes on check 3 and never
# reports checks 4-9 is worth less than one that finishes.


def check_db_fresh() -> tuple[bool, str]:
    """The pipeline is running, and `sector_flow_daily` proves it.

    Same threshold as the scheduled sentinel, imported rather than retyped —
    two definitions of "stale" would drift and only one would be in the log.
    """
    latest = latest_flow_date(DATABASE_PATH)
    if latest is None:
        return False, "sector_flow_daily is empty"
    gap = (today() - latest).days
    return gap <= DEFAULT_MAX_GAP, f"latest={latest} gap={gap}d (max {DEFAULT_MAX_GAP})"


def check_ranker_artifact() -> tuple[bool, str]:
    """The live ranker is a real model, not a test panel.

    This is the defect that shipped: `fit()` writes unconditionally,
    `models/saved/` is gitignored, so a test run replaced 19 real features with
    `["f1", "f2", "all_null"]` and nothing anywhere said so until the job died.
    """
    sidecar = Path(SAVED_MODELS_DIR) / "rotation_ranker.json"
    if not sidecar.exists():
        return False, f"no trained ranker at {sidecar} — run `main.py --train`"
    names = json.loads(sidecar.read_text(encoding="utf-8")).get("feature_names", [])
    ok = len(names) > 5 and set(names) != {"f1", "f2"}
    return ok, f"{len(names)} features"


def check_picks_snapshot() -> tuple[bool, str]:
    """Daily Insight survives a cold start (§22.6).

    Read through the service's own loader, not `json.load`, so a snapshot this
    passes on is one the homepage can actually deserialise.
    """
    from services.picks_universe_service import PicksUniverseService

    snap = PicksUniverseService()._load_from_disk()
    if snap is None:
        return False, "no readable snapshot — homepage will be blank on restart"
    return bool(snap.tickers), f"{len(snap.tickers)} tickers, built {snap.built_at}"


def _client():
    from fastapi.testclient import TestClient

    from api.main import app

    return TestClient(app)


def check_api_routes(client) -> tuple[bool, str]:
    """Every route the five nav pages call answers 200."""
    routes = [
        "/api/state",
        "/api/flow/freshness",
        "/api/insight/daily",
        "/api/sectors/ranking",
        "/api/sectors/regime",
        "/api/sectors/risk/exposure",
        "/api/sectors/handoff",
        "/api/stealth/active",
        "/api/stealth/history",
    ]
    bad = []
    for r in routes:
        try:
            code = client.get(r).status_code
        except Exception as e:  # noqa: BLE001 — one dead route must not hide the rest
            bad.append(f"{r}→{type(e).__name__}")
            continue
        if code != 200:
            bad.append(f"{r}→{code}")
    return not bad, f"{len(routes) - len(bad)}/{len(routes)} ok" + (f" · {', '.join(bad)}" if bad else "")


def check_stealth_history_not_stub(client) -> tuple[bool, str]:
    """`/api/stealth/history` returns events, not the hardcoded empty list.

    A 200 with `{"rows": []}` is exactly what the stub returned for months, so
    the route check above cannot see this one. §16.1 currently produces ~21
    events over the panel; zero means either the stub is back or the gate has
    stopped firing, and both are worth a red line.
    """
    body = client.get("/api/stealth/history").json()
    n = body.get("summary", {}).get("events", 0)
    return n > 0, f"{n} events, {body.get('summary', {}).get('scored', 0)} scored"


def check_report_import_is_inert() -> tuple[bool, str]:
    """`import generate_report` sends no mail (§20.3 P3-2).

    Pinned by tests too, but those run with `smtplib.SMTP` replaced. Here the
    real module is imported into a real process — if the work ever moves back
    to module level, this is where it sends a live email and the check that
    notices is the one that ran it.
    """
    import generate_report

    return callable(getattr(generate_report, "main", None)), "main() present, import inert"


def check_report_renders() -> tuple[bool, str]:
    """`generate_report.py --no-email` produces today's HTML+PDF.

    Subprocess, not import: the script is driven by `sys.argv` and calling
    `main()` in-process would leave its module state in this one.
    """
    proc = subprocess.run(
        [sys.executable, str(REPO / "generate_report.py"), "--no-email"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    if proc.returncode != 0:
        return False, f"exit {proc.returncode}: {proc.stderr.strip()[-200:]}"
    stamp = today().isoformat()
    made = [p.name for p in (REPO / "report").glob(f"daily_report_{stamp}.*")]
    return len(made) >= 2, f"wrote {', '.join(sorted(made)) or 'nothing'}"


# ── runner ──────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--with-report", action="store_true",
                    help="also render the daily report (slow, reaches vnstock)")
    args = ap.parse_args(argv)

    client = _client()
    checks = [
        ("db fresh", check_db_fresh),
        ("ranker artifact", check_ranker_artifact),
        ("picks snapshot", check_picks_snapshot),
        ("api routes", lambda: check_api_routes(client)),
        ("stealth history", lambda: check_stealth_history_not_stub(client)),
        ("report import inert", check_report_import_is_inert),
    ]
    if args.with_report:
        checks.append(("report renders", check_report_renders))

    failed = 0
    for name, fn in checks:
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001 — report every check, not just the ones before the crash
            ok, detail = False, f"{type(e).__name__}: {e}"
        failed += not ok
        print(f"[smoke] {'ok  ' if ok else 'FAIL'} {name:<22} {detail}")

    print(f"[smoke] {len(checks) - failed}/{len(checks)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
