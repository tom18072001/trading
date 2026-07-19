# ============================================
# analysis/flow_handoff.py — sector rotation matrix
# ============================================
# "Handoff" score: flow leaving sector A while entering sector B.
# Pure function. Takes a wide panel of flow_z20 by (date, sector_code),
# returns a long DataFrame of (date, from_sector, to_sector, handoff_score).

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_handoff(
    flow_z_panel: pd.DataFrame,
    window: int = 5,
    top_k: int = 5,
) -> pd.DataFrame:
    """
    flow_z_panel: index=date, columns=sector_code, values=flow_z20
    handoff[A→B] = max(0, -ΔzA_window) * max(0, +ΔzB_window)
    Only the strongest `top_k` handoffs per date are returned.
    """
    if flow_z_panel.empty:
        return pd.DataFrame(columns=["date", "from_sector", "to_sector", "handoff_score"])

    delta = flow_z_panel.diff(window)
    rows: list[dict] = []
    for date, row in delta.iterrows():
        leaving = (-row).clip(lower=0)   # positive where flow dropped
        entering = row.clip(lower=0)     # positive where flow rose
        if leaving.sum() == 0 or entering.sum() == 0:
            continue
        # Outer product — handoff strength matrix
        mat = np.outer(leaving.values, entering.values)
        sectors = list(flow_z_panel.columns)
        pairs = []
        for i, a in enumerate(sectors):
            for j, b in enumerate(sectors):
                if i == j:
                    continue
                score = float(mat[i, j])
                if score > 0:
                    pairs.append((a, b, score))
        pairs.sort(key=lambda x: x[2], reverse=True)
        for a, b, s in pairs[:top_k]:
            rows.append({
                "date": str(date)[:10],
                "from_sector": a,
                "to_sector": b,
                "handoff_score": s,
            })
    return pd.DataFrame(rows)
