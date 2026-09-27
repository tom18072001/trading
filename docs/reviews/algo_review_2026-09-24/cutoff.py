import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)


from picks_eval import (MIN_BUY_SCORE, MIN_DV, UNTRENDED_FLOOR, jt_portfolio, load_all,  # noqa: E402
    nw_t, per_trade, perf, production_rank, production_score, topk)  # noqa: E402
p, f, vn = load_all()
elig = (f["dv20"] > MIN_DV) & f["sma50"].notna()
sc = production_score(f).round(2)
rk = production_rank(sc, f["obv_chg20"], elig).round(4)
with_cut = topk(rk.where((sc >= MIN_BUY_SCORE) & elig), 5, tiebreak=sc)
# the alternative keeps the SMA200 gate (score above the -20 floor) and drops only the 2.5 cutoff
no_cut = topk(rk.where((sc > UNTRENDED_FLOOR) & elig), 5, tiebreak=sc)
print("picks below SMA200 in the alternative (must be 0):", int((no_cut & (sc <= -20)).sum().sum()), "of", int(no_cut.sum().sum()))
d0 = with_cut.sum(axis=1)[with_cut.index >= "2023-01-01"]
print("days with 0 picks (cutoff):", int((d0 == 0).sum()), "of", len(d0), "; <5 picks:", int((d0 < 5).sum()))
print("score of names picked without cutoff: quantiles", sc.where(no_cut).stack().quantile([.1,.25,.5,.75,.9]).round(2).to_dict())
for h in (20, 40):
    a = per_trade(with_cut, p, f, vn, h, elig=elig, start="2023-01-01")
    b = per_trade(no_cut, p, f, vn, h, elig=elig, start="2023-01-01")
    for lab, x in (("with cutoff", a), ("SMA200 gate only", b)):
        e = (x.pick - x.base).dropna()
        print(f"h={h} {lab:18s} excess vs NO GATE {e.mean()*100:+.2f}%  NW t {nw_t(e,h):+.2f}  by year",
              (e.groupby(e.index.year).mean()*100).round(2).to_dict(),
              " JT CAGR %.1f%%" % (perf(jt_portfolio((with_cut if lab == 'with cutoff' else no_cut) & elig, p, vn, h), start='2023-01-01')['cagr']*100))
    d = (a.pick - b.pick).dropna()
    print(f"   paired (with - without): {d.mean()*100:+.2f}%/trade NW t {nw_t(d,h):+.2f} by year", (d.groupby(d.index.year).mean()*100).round(2).to_dict())
