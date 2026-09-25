import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)


import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from picks_eval import (MIN_BUY_SCORE, MIN_DV, jt_portfolio, load_all, per_trade, perf,  # noqa: E402
    production_rank, production_score, topk)  # noqa: E402
p, f, vn = load_all()
elig = (f["dv20"] > MIN_DV) & f["sma50"].notna()
# 1. selecting everything must give exactly zero excess vs NO GATE
df = per_trade(elig, p, f, vn, 20, elig=elig, start="2023-01-01")
print("control 1  (select all)  excess vs NO GATE:", float((df.pick - df.base).abs().max()))
# 2. random 5 per day, 20 seeds -> excess ~ 0, J-T CAGR ~ NO GATE
ex, cg = [], []
rng = np.random.default_rng(1)
for s in range(20):
    noise = pd.DataFrame(rng.random(elig.shape), index=elig.index, columns=elig.columns)
    sel = topk(noise.where(elig), 5)
    d = per_trade(sel, p, f, vn, 40, elig=elig, start="2023-01-01").dropna(subset=["pick"])
    ex.append((d.pick - d.base).mean() * 100)
    if s < 6:
        cg.append(perf(jt_portfolio(sel & elig, p, vn, 40), start="2023-01-01")["cagr"] * 100)
print(f"control 2  (random top-5, 20 seeds, h=40) excess vs NO GATE: mean {np.mean(ex):+.3f}%  sd {np.std(ex):.3f}%  range [{min(ex):+.2f}, {max(ex):+.2f}]")
print(f"           J-T CAGR over 6 seeds: {np.round(cg,1)}  (NO GATE all-liquid h=40 was 7.0%)")
# 3. the shipped rule's excess (+0.64%/trade at h=40) against the random distribution
sc = production_score(f); rk = production_rank(sc, f["obv_chg20"], elig)
ship = topk(rk.where((sc >= MIN_BUY_SCORE) & elig), 5, tiebreak=sc)
d = per_trade(ship, p, f, vn, 40, elig=elig, start="2023-01-01").dropna(subset=["pick"])
se = (d.pick - d.base).mean() * 100
print(f"           shipped h=40 excess {se:+.2f}% sits at z = {(se - np.mean(ex)) / np.std(ex):.2f} of the random-seed spread (seed spread only, not sampling error)")
