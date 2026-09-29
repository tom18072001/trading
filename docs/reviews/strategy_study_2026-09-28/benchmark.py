"""Benchmark check (2026-09-29): has the shipped rule met the 20-30%/yr target?

Tom: "so sánh benchmark và kiểm tra đạt target 20%-30%/năm chưa".

The rule as shipped on 2026-09-28: ramom126 over the 75-name basket, top 8,
reviewed every 20 sessions, kept while in the top 16, no market switch.
Benchmarks on the same days: VNINDEX (price index, no dividends), the basket
equal-weighted (daily, no costs) and the rule it replaced (top 5, SMA200 gate
-> blend). Every window here is in-sample except the holdout one; read with
STRATEGY_STUDY_2026-09-28.md §7 (a 2026 basket, 394 variants tried).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

LAB = str(Path(__file__).resolve().parent)
sys.path.insert(0, LAB)
from lab import HOLD_START, SESSIONS, bench, simulate_phases, stats  # noqa: E402
from study import PANEL, UNIV, fam, P, vn  # noqa: E402

import scripts.ticker_alpha_bench as tab  # noqa: E402
tab.PANEL_DB = PANEL
from signals import baseline  # noqa: E402

LO, HI = 0.20, 0.30                     # Tom's target band, per year
el = UNIV["U75"]
START, END = pd.Timestamp("2019-07-01"), P["close"].index[-1]
PH = list(range(0, 20, 2))


def ew_index(e: pd.DataFrame) -> pd.Series:
    """Equal weight over the names eligible at t-1, rebalanced daily, no costs."""
    r = P["close"].pct_change(fill_method=None)
    w = e.shift(1).fillna(False) & r.notna()
    return r.where(w).mean(axis=1).fillna(0.0)


def flag(c: float) -> str:
    return "ĐẠT" if LO <= c <= HI else ("VƯỢT" if c > HI else "chưa")


fr = tab.build_features(tab.load_panel())
old = baseline(fr, el.reindex_like(fr["close"]).fillna(False)).reindex_like(P["close"])

new, *_ = simulate_phases(fam["ramom126"], el, P, K=8, R=20, buffer=8, phases=PH,
                          start=START, end=END)
old_d, *_ = simulate_phases(old, el, P, K=5, R=20, buffer=0, phases=PH, start=START, end=END)
idx = new.index
D = pd.DataFrame({"luật mới": new, "VNINDEX": bench(vn, idx),
                  "rổ 75 mã chia đều": ew_index(el).reindex(idx).fillna(0.0),
                  "luật cũ (top 5)": old_d.reindex(idx).fillna(0.0)})

print(f"=== 1. CAGR theo cửa sổ, đến {END.date()} (luật chạy liên tục từ 2019-07) ===")
wins = [("2019-07", START), ("2020-01", pd.Timestamp("2020-01-01")),
        ("2021-01", pd.Timestamp("2021-01-01")), ("2022-01", pd.Timestamp("2022-01-01")),
        ("2023-01", pd.Timestamp("2023-01-01")), ("2024-01", pd.Timestamp("2024-01-01")),
        ("2025-01", pd.Timestamp("2025-01-01")), ("12 tháng (holdout)", HOLD_START),
        ("2026 YTD", pd.Timestamp("2026-01-01"))]
for label, a in wins:
    x = D[D.index >= a]
    s = {c: stats(x[c]) for c in D.columns}
    yrs = len(x) / SESSIONS
    tot = (1 + x["luật mới"]).prod() - 1
    print(f"từ {label:18s} ({yrs:3.1f} năm)  luật mới {s['luật mới']['cagr']*100:6.1f}%/năm "
          f"[{flag(s['luật mới']['cagr'])}] Sharpe {s['luật mới']['sharpe']:5.2f} "
          f"MaxDD {s['luật mới']['maxdd']*100:6.1f}% | VNINDEX {s['VNINDEX']['cagr']*100:6.1f}% "
          f"| rổ {s['rổ 75 mã chia đều']['cagr']*100:6.1f}% | luật cũ {s['luật cũ (top 5)']['cagr']*100:6.1f}%"
          + (f"  (tổng {tot*100:+.1f}%)" if yrs < 1.05 else ""))

print("\n=== 2. Theo năm (%) ===")
yr = (1 + D).groupby(D.index.year).prod() - 1
yr["hiệu vs VNINDEX"] = yr["luật mới"] - yr["VNINDEX"]
yr["mục tiêu 20-30%"] = [flag(v) for v in yr["luật mới"]]
print(yr.assign(**{c: (yr[c] * 100).round(1) for c in D.columns.tolist() + ["hiệu vs VNINDEX"]})
      .T.to_string())

print("\n=== 3. Mọi cửa sổ 12 tháng cuốn chiếu (252 phiên) ===")
eq = (1 + D).cumprod()
r12 = (eq.shift(-252) / eq - 1).dropna()
for c in ("luật mới", "VNINDEX", "rổ 75 mã chia đều", "luật cũ (top 5)"):
    x = r12[c]
    print(f"{c:18s} n={len(x)}  trung vị {x.median()*100:6.1f}%  P25 {x.quantile(.25)*100:6.1f}%  "
          f"P75 {x.quantile(.75)*100:6.1f}%  ≥20%: {(x >= LO).mean()*100:3.0f}%  "
          f"trong 20-30%: {((x >= LO) & (x <= HI)).mean()*100:3.0f}%  ≥30%: {(x > HI).mean()*100:3.0f}%  "
          f"<0: {(x < 0).mean()*100:3.0f}%")
print(f"luật mới thắng VNINDEX trong {(r12['luật mới'] > r12['VNINDEX']).mean()*100:.0f}% "
      "số cửa sổ 12 tháng")

print("\n=== 4. Mọi cửa sổ 3 năm cuốn chiếu (756 phiên), CAGR ===")
r36 = ((eq.shift(-756) / eq) ** (1 / 3) - 1).dropna()
for c in ("luật mới", "VNINDEX", "rổ 75 mã chia đều"):
    x = r36[c]
    print(f"{c:18s} n={len(x)}  min {x.min()*100:6.1f}%  trung vị {x.median()*100:6.1f}%  "
          f"max {x.max()*100:6.1f}%  ≥20%/năm: {(x >= LO).mean()*100:3.0f}% số cửa sổ")

print("\n=== 5. Nếu bắt đầu từ tiền mặt vào đầu mỗi quý, tới hôm nay ===")
rows = []
for s in pd.date_range("2019-07-01", "2025-07-01", freq="QS"):
    d, cagrs, _, _ = simulate_phases(fam["ramom126"], el, P, K=8, R=20, buffer=8,
                                     phases=[0, 5, 10, 15], start=s, end=END)
    rows.append({"bắt đầu": s.date(), "năm": round(len(d) / SESSIONS, 1),
                 "luật mới %/năm": round(stats(d)["cagr"] * 100, 1),
                 "VNINDEX %/năm": round(stats(bench(vn, d.index))["cagr"] * 100, 1)})
S = pd.DataFrame(rows)
print(S.to_string(index=False))
c = S["luật mới %/năm"]
print(f"CAGR từ {len(S)} ngày bắt đầu: min {c.min():.1f}%, trung vị {c.median():.1f}%, "
      f"max {c.max():.1f}%; ≥20%/năm ở {(c >= 20).mean()*100:.0f}% số ngày bắt đầu; "
      f"thắng VNINDEX ở {(c > S['VNINDEX %/năm']).mean()*100:.0f}%")
