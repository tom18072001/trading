"""Running the tests must not overwrite the production ranker.

Found 2026-08-24, and it had already fired: `models/saved/rotation_ranker.json`
on disk read `{"feature_names": ["f1", "f2", "all_null"]}` — a synthetic panel
from `test_review_20260822.py`, not the 19 real features. The next scheduled
publish died with:

    LightGBMError: The number of features in data (19) is not the same as it
    was in training data (3).

`RotationRanker.fit()` writes to `config.SAVED_MODELS_DIR` unconditionally, six
tests call it, and `models/saved/` is gitignored — so nothing showed in `git
status`, no test failed, and the damage only surfaced when the 17:00 job ran.
A silent test suite that breaks production is the worst shape a defect can take.

`tests/conftest.py::_models_go_to_a_tmpdir` repoints the module global for the
whole session. These tests are what keeps it repointed.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import models.rotation_ranker as rr

REPO = Path(__file__).resolve().parents[1]


def _panel(n_dates: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    base = datetime(2025, 1, 1)
    return pd.DataFrame([
        {"date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
         "sector_code": s, "f1": rng.normal(), "f2": rng.normal(),
         "target": rng.normal() * 0.02}
        for i in range(n_dates)
        for s in ("BANK", "FISH", "TECH", "STEEL")
    ])


def test_the_saved_models_dir_is_redirected_during_tests():
    """The fixture is autouse, so this must hold without asking for it."""
    from config import SAVED_MODELS_DIR as LIVE

    assert rr.SAVED_MODELS_DIR != LIVE, (
        "fit() would write to the live model directory — see "
        "conftest::_models_go_to_a_tmpdir"
    )
    assert not Path(rr.SAVED_MODELS_DIR).is_relative_to(REPO / "models")


def test_fitting_writes_inside_the_tmpdir_not_the_repo():
    """The end-to-end version: fit, then look where the bytes landed."""
    result = rr.RotationRanker().fit(_panel(), ["f1", "f2"])

    written = Path(result.model_path)
    assert written.is_relative_to(Path(rr.SAVED_MODELS_DIR))
    assert written.exists()

    sidecar = Path(rr.SAVED_MODELS_DIR) / "rotation_ranker.json"
    assert json.loads(sidecar.read_text())["feature_names"] == ["f1", "f2"]


def test_the_live_ranker_still_has_real_features():
    """A direct guard on the artefact that broke.

    Skipped when the file is absent — a clean clone has no trained model
    (`models/saved/*.pkl` is gitignored) and that is not a failure. Present but
    2-feature is.
    """
    import pytest

    from config import SAVED_MODELS_DIR as LIVE

    live = Path(LIVE) / "rotation_ranker.json"
    if not live.exists():
        pytest.skip("no trained ranker on this machine — run main.py --train")

    names = json.loads(live.read_text())["feature_names"]
    assert set(names) != {"f1", "f2"}, "the test panel overwrote the live model"
    assert len(names) > 5, f"only {len(names)} features — this is a test artefact"
