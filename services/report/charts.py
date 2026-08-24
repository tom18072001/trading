"""Matplotlib figures for the daily report, as base64 PNGs.

Extracted verbatim from `generate_report.py` (§20.3 P3-2). The palette and
rcParams came with them — they were module-level globals the chart functions
closed over, so they belong to the charts, not to the report.

`matplotlib.use("Agg")` is set at import. That is not optional here: the daily
job runs headless under Task Scheduler, and the interactive backend would try
to open a window and fail.
"""
from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import numpy as np  # noqa: E402

from services.report.format import fmtM  # noqa: E402

__all__ = [
    "fig_to_base64",
    "make_sector_flow_chart",
    "make_sector_aggregate_chart",
    "make_correlation_heatmap",
    "make_mini_chart",
]

# ---------- Palette ----------
# Matches the report template's dark theme. Changing a colour here changes the
# charts only — the HTML cards get theirs from the template's CSS.
DARK_BG, CARD_BG, GRID_CLR, TEXT_CLR = "#0f172a", "#1e293b", "#334155", "#e2e8f0"
GREEN, RED, BLUE, YELLOW = "#22c55e", "#ef4444", "#38bdf8", "#eab308"

plt.rcParams.update({
    "figure.facecolor": DARK_BG, "axes.facecolor": CARD_BG,
    "axes.edgecolor": GRID_CLR, "axes.labelcolor": TEXT_CLR,
    "xtick.color": TEXT_CLR, "ytick.color": TEXT_CLR,
    "text.color": TEXT_CLR, "grid.color": GRID_CLR, "grid.alpha": 0.3,
    "font.size": 9, "font.family": "sans-serif",
})


def fig_to_base64(fig, dpi: int = 150) -> str:
    """Render and close. Closing matters — the daily run draws ~15 figures and
    matplotlib keeps every un-closed one alive for the life of the process."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def make_sector_flow_chart(stats: list[dict]) -> str:
    fig, ax = plt.subplots(figsize=(10, max(4, len(stats) * 0.4)))
    sectors = [s["sector"] for s in reversed(stats)]
    deltas = [s["flow_delta"] for s in reversed(stats)]
    colors = [GREEN if d >= 0 else RED for d in deltas]
    bars = ax.barh(sectors, deltas, color=colors, height=0.6)
    ax.set_xlabel("Flow Delta (VND/day)")
    ax.set_title("Sector Money Flow Delta — Recent vs Prior", fontsize=13, fontweight="bold", pad=10)
    ax.axvline(0, color=GRID_CLR, linewidth=0.8)
    ax.grid(axis="x", alpha=0.2)
    max_abs = max((abs(d) for d in deltas), default=1) or 1
    for bar, val in zip(bars, deltas, strict=True):
        ax.text(bar.get_width() + (max_abs * 0.02 * (1 if val >= 0 else -1)),
                bar.get_y() + bar.get_height() / 2, fmtM(val),
                ha="left" if val >= 0 else "right", va="center", fontsize=8, color=TEXT_CLR)
    fig.tight_layout()
    return fig_to_base64(fig)


def make_sector_aggregate_chart(sector_stats: list[dict]) -> str:
    stats_sorted = sorted(sector_stats, key=lambda x: x["avg_ret_5d"])
    sectors = [s["sector"] for s in stats_sorted]
    rets = [s["avg_ret_5d"] for s in stats_sorted]
    colors = [GREEN if r >= 0 else RED for r in rets]
    fig, ax = plt.subplots(figsize=(10, max(4, len(sectors) * 0.4)))
    bars = ax.barh(sectors, rets, color=colors, height=0.6)
    ax.set_xlabel("Average 5-Day Return (%)")
    ax.set_title("Sector Aggregate Performance — Avg 5d Return", fontsize=13, fontweight="bold", pad=10)
    ax.axvline(0, color=GRID_CLR, linewidth=0.8)
    ax.grid(axis="x", alpha=0.2)
    max_abs = max((abs(r) for r in rets), default=1) or 1
    for bar, val in zip(bars, rets, strict=True):
        offset = max_abs * 0.02 * (1 if val >= 0 else -1)
        ax.text(bar.get_width() + offset, bar.get_y() + bar.get_height() / 2, f"{val:+.2f}%",
                ha="left" if val >= 0 else "right", va="center", fontsize=8, color=TEXT_CLR)
    fig.tight_layout()
    return fig_to_base64(fig)


def make_correlation_heatmap(sector_daily_flow: dict, all_dates_sorted: list) -> str:
    sectors = sorted(sector_daily_flow.keys())
    if len(sectors) < 2:
        return ""
    matrix = [[sector_daily_flow[sec].get(d, 0.0) for sec in sectors] for d in all_dates_sorted]
    arr = np.array(matrix)
    n = arr.shape[1]
    corr = np.nan_to_num(np.corrcoef(arr.T), nan=0.0)
    fig, ax = plt.subplots(figsize=(max(6, n * 0.55), max(5, n * 0.45)))
    im = ax.imshow(corr, cmap="RdYlGn", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    short = [s[:18] for s in sectors]
    ax.set_xticklabels(short, rotation=45, ha="right", fontsize=7)
    ax.set_yticklabels(short, fontsize=7)
    for i in range(n):
        for j in range(n):
            val = corr[i, j]
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=6, color=("#000" if abs(val) < 0.5 else "#fff"))
    ax.set_title("Sector Money Flow Correlation", fontsize=12, fontweight="bold", pad=10)
    fig.colorbar(im, ax=ax, shrink=0.8, label="Correlation")
    fig.tight_layout()
    return fig_to_base64(fig, dpi=130)


def make_mini_chart(sym: str, daily_prices: list[dict]) -> str | None:
    """Price + volume sparkline for one ticker. None when there is too little
    history to draw a line anyone should read."""
    if len(daily_prices) < 3:
        return None
    dates_labels = [p["date"][-5:] for p in daily_prices]
    closes = [p["close"] for p in daily_prices]
    volumes = [p["volume"] for p in daily_prices]
    x = range(len(closes))
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(3.2, 2.2),
                                   gridspec_kw={"height_ratios": [2.5, 1]}, sharex=True)
    color = GREEN if closes[-1] >= closes[0] else RED
    ax1.plot(x, closes, color=color, linewidth=1.5)
    ax1.fill_between(x, closes, alpha=0.15, color=color)
    ax1.set_ylabel("Price", fontsize=7)
    ax1.tick_params(labelsize=6)
    ax1.grid(alpha=0.15)
    vol_colors = [GREEN if dp["close"] >= dp["open"] else RED for dp in daily_prices]
    ax2.bar(x, volumes, color=vol_colors, width=0.6, alpha=0.7)
    ax2.set_ylabel("Vol", fontsize=7)
    ax2.tick_params(labelsize=6)
    ax2.set_xticks(x)
    ax2.set_xticklabels(dates_labels, rotation=30, fontsize=5)
    ax2.grid(alpha=0.15)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: f"{v/1e6:.0f}M" if v >= 1e6 else f"{v/1e3:.0f}K"))
    fig.suptitle(sym, fontsize=10, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig_to_base64(fig, dpi=110)
