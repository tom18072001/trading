"""Score the picks this system actually emailed, against the base rate.

Tom, 2026-09-16: "cac ma co phieu ban suggest ... thuc te ket qua cham hon nhieu
so voi T+3" -- the suggested tickers move far slower than a T+3 hold needs.

Nothing in the repo could answer that. PicksUniverseService keeps one snapshot,
the position book only holds what Tom marked by hand, and no table records what
went out in the mail. `report/daily_report_<date>.html` is the only durable
record, so `extract_past_picks.py` reads it back and this scores it.

Three comparisons, because a raw return number means nothing on its own:
  1. the picks,
  2. the EQUAL-WEIGHT ELIGIBLE UNIVERSE on the same dates (the base rate -- if
     the picks do not beat this, the ranking is worse than a coin),
  3. VNINDEX over the same window, as the benchmark 11 mandates.

Entry is the NEXT session's open: the report is generated at 17:00, after the
close it quotes, so its `entry` price is not purchasable.

HISTORICAL. This script answered the 2026-09-16 T+3 question and its short
windows (T+1..T+15) are that diagnosis; they are kept so the numbers quoted in
CLAUDE.md §26.3 stay reproducible. The T+ mode itself was removed on 2026-09-25
(Tom: "chỉ sử dụng 4 tuần và 8 tuần"). The live audit of what the system
recommends is `daily_watch/audit.py`, on the 20/40-session horizons.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PANEL_DB = ROOT / "data" / "price_panel.db"
PICKS_CSV = ROOT / "data" / "past_picks.csv"

# Trước 2026-09-16 đây là phí+thuế thôi, KHÔNG slippage — nên cột "net%" của
# script này là 0,40%/vòng trong khi ticker_alpha_bench chấm 1,00%. Một cột tên
# là "net" mà thiếu hơn nửa chi phí thì tệ hơn là không có cột đó.
from analysis.bench import TOTAL_COST as ROUND_TRIP  # noqa: E402
HORIZONS = (1, 2, 3, 5, 10, 15)


def load_prices():
    con = sqlite3.connect(PANEL_DB)
    df = pd.read_sql("SELECT symbol,time,open,high,low,close,volume FROM prices "
                     "WHERE close>0", con, parse_dates=["time"])
    con.close()
    return {c: df.pivot(index="time", columns="symbol", values=c).sort_index()
            for c in ("open", "high", "low", "close", "volume")}


def vnindex() -> pd.Series:
    con = sqlite3.connect(ROOT / "vnstock_market.db")
    df = pd.read_sql("SELECT time, vnindex FROM macro_anchors WHERE vnindex > 200 "
                     "ORDER BY time", con, parse_dates=["time"])
    con.close()
    if df.empty:
        return pd.Series(dtype=float)
    s = df.set_index("time")["vnindex"]
    s.index = s.index.normalize()
    return s[~s.index.duplicated(keep="last")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-dv", type=float, default=5e6)
    args = ap.parse_args()

    if not PICKS_CSV.exists():
        print("run scripts/extract_past_picks.py first", file=sys.stderr)
        return 1
    picks = pd.read_csv(PICKS_CSV, parse_dates=["date"])
    p = load_prices()
    c, o = p["close"], p["open"]
    dv20 = (c * p["volume"]).rolling(20).mean()
    sessions = c.index

    def nth_session_after(d, n):
        i = sessions.searchsorted(d, side="right")   # first session strictly after d
        j = i + n - 1
        return sessions[j] if 0 <= j < len(sessions) else None

    rows = []
    for _, r in picks.iterrows():
        d, sym = r["date"], r["symbol"]
        e_day = nth_session_after(d, 1)
        if e_day is None or sym not in c.columns:
            continue
        entry = o.at[e_day, sym]
        if not np.isfinite(entry) or entry <= 0:
            continue
        rec = {"date": d, "symbol": sym, "src": r["source"], "score": r["score"],
               "report_close": r["entry"], "entry_open": entry,
               "target": r["target"], "stop": r["stop"]}
        # A report date is not always a trading session (2026-08-22 is a
        # Saturday -- the job ran, the market did not). Take the last session
        # at or before it, which is the tape the report was actually built on.
        k = sessions.searchsorted(d, side="right") - 1
        if k < 0:
            continue
        elig = dv20.iloc[k].dropna()
        elig = elig[elig > args.min_dv].index
        for h in HORIZONS:
            x_day = nth_session_after(d, 1 + h)
            if x_day is None:
                rec[f"r{h}"] = np.nan
                rec[f"b{h}"] = np.nan
                continue
            rec[f"r{h}"] = c.at[x_day, sym] / entry - 1
            uni = c.loc[x_day, elig] / o.loc[e_day, elig] - 1
            rec[f"b{h}"] = uni.replace([np.inf, -np.inf], np.nan).mean()
        # Did it ever reach target / stop? Use whatever window exists -- most
        # picks are younger than 15 sessions, and requiring a full window drops
        # 95% of the sample. `window` records how much forward tape was judged.
        i_e = sessions.searchsorted(e_day)
        i_x = min(i_e + 15, len(sessions) - 1)
        win = p["high"].iloc[i_e:i_x + 1][sym]
        wlo = p["low"].iloc[i_e:i_x + 1][sym]
        tgt, stp = r["target"], r["stop"]
        rec["window"] = i_x - i_e + 1
        if np.isfinite(tgt):
            hits = np.where(win.values >= tgt)[0]
            rec["hit_target"] = bool(len(hits))
            rec["days_to_target"] = int(hits[0]) + 1 if len(hits) else None
        if np.isfinite(stp):
            st = np.where(wlo.values <= stp)[0]
            rec["hit_stop"] = bool(len(st))
            rec["days_to_stop"] = int(st[0]) + 1 if len(st) else None
        # Best exit available inside a T+3 hold vs inside 10 sessions -- the
        # gap between them IS the horizon mismatch.
        rec["maxgain_3"] = float(win.values[:4].max() / entry - 1) if rec["window"] >= 4 else np.nan
        rec["maxgain_10"] = float(win.values[:11].max() / entry - 1) if rec["window"] >= 11 else np.nan
        rows.append(rec)

    d = pd.DataFrame(rows)
    if d.empty:
        print("no picks could be priced", file=sys.stderr)
        return 1

    print(f"{len(d)} picks, {d['symbol'].nunique()} symbols, "
          f"{d['date'].nunique()} report dates "
          f"({d['date'].min().date()} .. {d['date'].max().date()})")
    print("entry = next session OPEN (report is written after the close it quotes)")
    print(f"cost: {ROUND_TRIP*100:.2f}% round trip (phí + thuế + slippage)\n")

    print(f"{'hold':>6s} {'picks%':>8s} {'BASE%':>8s} {'excess%':>9s} "
          f"{'net%':>8s} {'win':>6s} {'base win':>9s} {'n':>5s}")
    print("-" * 66)
    for h in HORIZONS:
        col, bcol = f"r{h}", f"b{h}"
        m = d[col].notna() & d[bcol].notna()
        if not m.any():
            continue
        pk, bs = d.loc[m, col].mean(), d.loc[m, bcol].mean()
        flag = "  <- T+3 exit" if h == 3 else ""
        print(f"T+{h:<4d} {pk*100:>8.2f} {bs*100:>8.2f} {(pk-bs)*100:>+9.2f} "
              f"{pk*100-ROUND_TRIP*100:>8.2f} {(d.loc[m,col]>0).mean():>6.2f} "
              f"{(d.loc[m,bcol]>0).mean():>9.2f} {int(m.sum()):>5d}{flag}")

    vni = vnindex()
    if not vni.empty:
        segs = []
        for _, r in d.iterrows():
            e = nth_session_after(r["date"], 1)
            x = nth_session_after(r["date"], 4)
            if e is None or x is None:
                continue
            a = vni.asof(e)
            b = vni.asof(x)
            if np.isfinite(a) and np.isfinite(b) and a > 0:
                segs.append(b / a - 1)
        if segs:
            print(f"\nVNINDEX over the same T+3 windows: {np.mean(segs)*100:+.2f}%")

    print(f"\n--- target / stop reality check "
          f"(median forward window judged: {d['window'].median():.0f} sessions) ---")
    ht = d["hit_target"].dropna()
    hs = d["hit_stop"].dropna()
    if len(ht):
        print(f"ever reached the printed TARGET: {ht.mean()*100:>3.0f}%  "
              f"({int(ht.sum())}/{len(ht)})")
        dtt = d["days_to_target"].dropna()
        if len(dtt):
            print(f"  median sessions to target, when reached: {dtt.median():.0f}")
            print(f"  reached by T+3: {int((dtt <= 3).sum())}/{len(ht)} = "
                  f"{(dtt<=3).sum()/len(ht)*100:.0f}%")
    if len(hs):
        print(f"ever touched the printed STOP:   {hs.mean()*100:>3.0f}%  "
              f"({int(hs.sum())}/{len(hs)})")
        dts = d["days_to_stop"].dropna()
        if len(dts):
            print(f"  median sessions to stop, when touched:   {dts.median():.0f}")
            print(f"  touched by T+3: {int((dts <= 3).sum())}/{len(hs)} = "
                  f"{(dts<=3).sum()/len(hs)*100:.0f}%")
    g3, g10 = d["maxgain_3"].dropna(), d["maxgain_10"].dropna()
    if len(g3) and len(g10):
        print("\nbest exit available (high) inside the hold -- the horizon gap:")
        print(f"  within T+3 : median {g3.median()*100:>+5.2f}%   "
              f"share >= +2% (the MIN_UPSIDE the card promises): {(g3>=0.02).mean()*100:.0f}%")
        print(f"  within T+10: median {g10.median()*100:>+5.2f}%   "
              f"share >= +2%: {(g10>=0.02).mean()*100:.0f}%")

    print("\n--- by source tag ---")
    for src, g in d.groupby("src"):
        m = g["r3"].notna()
        if m.sum() < 3:
            continue
        print(f"{src:>14s}  n={int(m.sum()):>3d}  T+3 {g.loc[m,'r3'].mean()*100:>+6.2f}%  "
              f"excess {(g.loc[m,'r3'].mean()-g.loc[m,'b3'].mean())*100:>+6.2f}%")

    print("\n--- by shipped score (the number the ranking sorts on) ---")
    for sc, g in d.groupby("score"):
        m = g["r3"].notna()
        if m.sum() < 3:
            continue
        print(f"score {int(sc):>+3d}  n={int(m.sum()):>3d}  T+3 {g.loc[m,'r3'].mean()*100:>+6.2f}%  "
              f"excess {(g.loc[m,'r3'].mean()-g.loc[m,'b3'].mean())*100:>+6.2f}%")

    out = ROOT / "data" / "past_picks_scored.csv"
    d.to_csv(out, index=False)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
