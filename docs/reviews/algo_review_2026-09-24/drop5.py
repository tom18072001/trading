"""Does the email's 5-day free-fall guard (ret_5d > -12%) help the gate-only rule?

Added 2026-09-25 with the change that retired it (CLAUDE.md §26.4, doctrine
26.11). Same harness, same base, same sessions as cutoff.py.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))

from picks_eval import (MIN_DV, UNTRENDED_FLOOR, jt_portfolio, load_all,  # noqa: E402
                        nw_t, per_trade, perf, production_rank, production_score, topk)

DROP_5D_PCT = -12.0   # the retired picks_scoring.MAX_5D_DROP_PCT

p, f, vn = load_all()
elig = (f["dv20"] > MIN_DV) & f["sma50"].notna()
sc = production_score(f).round(2)
rk = production_rank(sc, f["obv_chg20"], elig).round(4)
c = p["close"]
ret5 = (c / c.shift(5) - 1.0) * 100
gate = (sc > UNTRENDED_FLOOR) & elig
a_sel = topk(rk.where(gate), 5, tiebreak=sc)
b_sel = topk(rk.where(gate & (ret5 > DROP_5D_PCT)), 5, tiebreak=sc)
diff_days = (a_sel != b_sel).any(axis=1)
print("sessions where the guard changes the list:",
      int(diff_days[diff_days.index >= "2023-01-01"].sum()),
      "of", int((diff_days.index >= "2023-01-01").sum()))
print("gate-only picks with ret5 <= -12%:",
      int((a_sel & (ret5 <= DROP_5D_PCT)).loc["2023":].sum().sum()),
      "of", int(a_sel.loc["2023":].sum().sum()))
for h in (20, 40):
    a = per_trade(a_sel, p, f, vn, h, elig=elig, start="2023-01-01")
    b = per_trade(b_sel, p, f, vn, h, elig=elig, start="2023-01-01")
    d = (b.pick - a.pick).dropna()
    print(f"h={h} guard - no guard: {d.mean()*100:+.3f}%/trade NW t {nw_t(d, h):+.2f} by year",
          (d.groupby(d.index.year).mean() * 100).round(3).to_dict(),
          "| CAGR no guard %.1f%% guard %.1f%%" % (
              perf(jt_portfolio(a_sel & elig, p, vn, h), start="2023-01-01")["cagr"] * 100,
              perf(jt_portfolio(b_sel & elig, p, vn, h), start="2023-01-01")["cagr"] * 100))
