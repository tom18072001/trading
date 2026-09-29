"""The buy rule (2026-09-28) and the layer on top of it: what to buy, at what
price, and what history says happens over 4 and 8 weeks.

Tom, 2026-09-28: *"7,2%/năm và 11,7%/năm ... thấp hơn VNINDEX (17,5%/năm) —
như thế này thì không ổn, tôi cần bạn tối ưu hơn, mức kỳ vọng của tôi là
20-30% năm"* and *"tạo layer nữa dựa vào phân tích: gợi ý nên mua gì, accept
range, expect lên bao nhiêu trong các chu kỳ 4 tuần 8 tuần"*.

The study is `docs/reviews/STRATEGY_STUDY_2026-09-28.md` (harness in
`docs/reviews/strategy_study_2026-09-28/`). In one paragraph:

  * The rule it replaces (SMA200 gate -> blend of a 1-3 day oversold score and
    OBV) is a short-horizon signal held for 4-8 weeks: 2019-07..2026-09 it made
    4.6%/yr as a top-5 book, below VNINDEX (8.9%) and the equal-weight basket.
  * Of ~20 signal families, 6-month momentum divided by its own volatility
    ("risk-adjusted momentum") was the strongest and the steadiest: top 8 of
    the 75-name basket, reviewed every 4 weeks, a holding kept while it still
    ranks in the top 16 -- 31%/yr 2019-07..2026-09, ahead of VNINDEX in 7 of 8
    calendar years, but -31% in 2022 and max drawdown -47%.
  * Those are in-sample numbers on a basket chosen in 2026 (survivors): read
    them as optimistic. The pre-registered holdout (the last 12 months, with a
    market-timing switch chosen on the earlier years) LOST 21.5% while VNINDEX
    made 5.9%; the switch was dropped, the rule without it made -3% (started
    fresh on 2025-09-16) to +16% (running since 2019) over that year.
  * 2022-01..2026-09 alone: 14.3%/yr vs VNINDEX 3.7%. That -- the index plus
    roughly 10 points a year, with big swings -- is the honest expectation.

Everything this module prints is a measured distribution, not a forecast.
"""
from __future__ import annotations

import math
from typing import Any

# ============================== the rule =====================================

MOM_LOOKBACK = 126      # sessions, ~6 months
MOM_SKIP = 5            # the latest week is left out: 1-5 day moves mean-revert
BUY_TOP_K = 8           # names to hold -- equal weight
KEEP_TOP = 16           # a holding stays while it ranks within this
REVIEW_SESSIONS = 20    # the book is reviewed every 4 weeks (sessions)


def risk_adjusted_momentum(closes: list[float] | Any) -> tuple[float | None, float | None,
                                                              float | None]:
    """(score, 6-month return, daily volatility over the same 126 sessions).

    score = (close[t-5] / close[t-126] - 1) / std(daily return, last 126).
    `closes` is oldest -> newest, adjusted (the snapshot's OHLCV). Needs 127
    closes; fewer -> (None, None, None): a name without 6 months of history is
    not ranked, it is not ranked last.
    """
    c = [float(x) for x in closes if x is not None and float(x) == float(x)]
    if len(c) < MOM_LOOKBACK + 1:
        return None, None, None
    base, recent = c[-(MOM_LOOKBACK + 1)], c[-(MOM_SKIP + 1)]
    if base <= 0 or recent <= 0:
        return None, None, None
    mom = recent / base - 1.0
    rets = [c[i] / c[i - 1] - 1.0 for i in range(len(c) - MOM_LOOKBACK, len(c)) if c[i - 1] > 0]
    if len(rets) < 2:
        return None, mom, None
    mu = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
    if sd <= 0:
        return None, mom, None
    return mom / sd, mom, sd


def daily_vol(closes: list[float] | Any, n: int = 63) -> float | None:
    """Standard deviation of the last `n` daily returns (fraction per session)."""
    c = [float(x) for x in closes if x is not None and float(x) == float(x)]
    if len(c) < n + 1:
        return None
    rets = [c[i] / c[i - 1] - 1.0 for i in range(len(c) - n, len(c)) if c[i - 1] > 0]
    if len(rets) < 2:
        return None
    mu = sum(rets) / len(rets)
    return math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))


# ======================= buying a few names, on your own days =================
# Tom, 2026-09-29: *"bạn khuyến nghị mã nào nên mua hằng ngày (có các priority,
# con nào khả năng lên cao) · tôi báo bạn mua con nào giá thế nào · khi bán tôi
# báo · bạn cập nhật những con tôi đang hold và đề xuất dựa vào giá mua, có nên
# bán hay không"*. He buys a few names from the daily list on his own days, not a
# synchronised 8-name book. Measured in docs/reviews/WORKFLOW_STUDY_2026-09-29.md
# (harness `docs/reviews/workflow_study_2026-09-29/`), DEV 2019-07..2025-09,
# hypotheses and adoption rules written down before any result was read.

#: Sessions of momentum history kept per name -- enough to date a top-8 run.
MOM_HISTORY = 11

#: Priority A = in the top 8 on each of the last 11 sessions (a run > 10).
#: Pre-registered as P3 in priority.py. Per new pick, A minus B (newer names):
#: DEV +1.6% over 4 weeks (Newey-West t 2.2), +2.0% over 8; holdout year +2.5% /
#: +3.4%, the same sign. Not a strong effect: 2025 alone went the other way,
#: and it overlaps with the other trend-strength measures (rank, the last week's
#: move, distance to the 52-week high), none significant on its own once the
#: others are in. Read it as "steady trends first", not as a second rule.
ESTABLISHED = 11
PRIORITY_EDGE = {20: 0.016, 40: 0.020}

#: Mean excess over the average basket name per new pick, after the 1% round
#: trip, by momentum rank at the signal (DEV). Descriptive: inside the top 8 the
#: order helps a little (ranks 1-4 minus 5-8: +0.9% / +1.7%, t 1.3 / 1.5, 3 of 6
#: years); below rank 16 the shortfall is clear -- the reason a holding is sold
#: there and kept above it.
RANK_EDGE = {  # (lo, hi): (4 weeks, 8 weeks)
    (1, 2): (0.015, 0.029), (3, 4): (0.001, 0.016), (5, 8): (-0.001, 0.006),
    (9, 16): (-0.006, -0.004), (17, 24): (-0.011, -0.011), (25, 32): (-0.011, -0.010),
    (33, None): (-0.015, -0.020),
}

#: Sell rules counted from each position's own entry, 8-slot book, DEV CAGR
#: (exits.py). Pre-registered bar: +1 point a year, Sharpe not lower, not worse
#: in 4 of 6 years. Nothing beat the shipped rule on that bar:
EXIT_STUDY = {
    "review_20_keep_16": 0.330,      # shipped: review at sessions 20, 40, 60 ... from entry
    "rank_check_daily": 0.306,       # sell the first day out of the top 16
    "hard_cap_40": 0.265,            # sell at session 40 whatever the rank
    "take_profit_20": 0.251,         # sell at +20% over the entry price
    "take_profit_30": 0.277,
    "cut_loss_10": 0.354,            # +2.4 points, but worse in 3 of 6 years -> not adopted
    "cut_loss_15": 0.325,
}


def momentum_history(closes: list[float] | Any, n: int = MOM_HISTORY) -> list[float | None]:
    """The score on each of the last `n` sessions, oldest -> newest (last = today)."""
    c = [float(x) for x in closes if x is not None and float(x) == float(x)]
    out: list[float | None] = []
    for k in range(n - 1, -1, -1):
        s, _m, _v = risk_adjusted_momentum(c[:len(c) - k] if k else c)
        out.append(round(s, 4) if s is not None else None)
    return out


def top_runs(histories: dict[str, list[float | None]],
             k: int = BUY_TOP_K) -> dict[str, int | None]:
    """Consecutive sessions each name has been in the top `k`, up to today.

    `histories` maps symbol -> `momentum_history`, last element = today. The
    cross-section on a past day is today's universe: a name that joined or left
    it since is a small error, not a new rule. A name with no history at all (a
    snapshot built before 2026-09-29) gets None -- unknown, not "new".
    """
    n = max((len(h) for h in histories.values()), default=0)
    hist = {s: [None] * (n - len(h)) + list(h) for s, h in histories.items()}
    runs: dict[str, int | None] = {s: (0 if h else None) for s, h in histories.items()}
    alive = {s for s, h in histories.items() if h}
    for d in range(n - 1, -1, -1):
        day = {s: h[d] for s, h in hist.items() if h[d] is not None}
        alive &= set(sorted(day, key=lambda s: (-day[s], s))[:k])
        if not alive:
            break
        for s in alive:
            runs[s] += 1
    return runs


def priority(run: int | None) -> str | None:
    """"A" (steady: in the top 8 for > 10 sessions), "B" (newer), None (unknown)."""
    if run is None:
        return None
    return "A" if run >= ESTABLISHED else "B"


def prioritise(picks: list[Any]) -> list[Any]:
    """Stable re-order of an already-chosen buy list: A before B, rank inside each.

    The SET is the rule's (the top names by momentum); this only orders it for
    someone buying a few of them. Works on dicts and on objects.
    """
    def g(p, key):
        return p.get(key) if isinstance(p, dict) else getattr(p, key, None)
    order = {"A": 0, "B": 1, None: 1}
    return sorted(picks, key=lambda p: (order.get(g(p, "priority"), 1),
                                        g(p, "rank") if g(p, "rank") is not None else 10**6))


def rank_edge(rank: int | None) -> tuple[float, float] | None:
    """RANK_EDGE row for a rank, or None."""
    if rank is None:
        return None
    for (lo, hi), v in RANK_EDGE.items():
        if rank >= lo and (hi is None or rank <= hi):
            return v
    return None


def equivalent_rank(score: float | None, universe_scores: list[float]) -> int | None:
    """Where a name outside the basket would sit in today's momentum order.

    For holdings the buy filter left out (liquidity, room, basket). The same
    score, placed among the ranked names: 1 + how many score higher.
    """
    if score is None:
        return None
    return 1 + sum(1 for s in universe_scores if s is not None and s > score)


# ============================== the layer ====================================
# Measured by docs/reviews/strategy_study_2026-09-28/layer.py over every day
# 2019-07-01 .. 2026-08: each name in the top 8 at close t, bought at the open
# of t+1, sold at the close of t+20 / t+40, 1.0% round trip (analysis.bench).
# Overlapping windows: ~14,000 pick-days per horizon, far fewer independent
# ones -- percentiles are fine, a t-stat on these counts would not be.

ROUND_TRIP = 0.010

#: Paying above the signal close costs the pick its edge one for one. The
#: measured edge over an average liquid name is ~1% per 4 weeks before costs
#: (~2% per 8 weeks): at +1% the 4-week edge is gone (-0.9% vs the basket
#: after costs), the 8-week one nearly (+0.1%). Hence the top of the range.
ENTRY_PREMIUM_MAX = 0.01

#: The bottom of the range is not a stop and not a "too cheap": a pick bought
#: after an overnight drop of >= 2% did BETTER (+3.0% vs the basket over 4
#: weeks, n=717). It is two days of normal noise for that name; below it,
#: wait for the next session's list -- a name still in it is still a buy.
LOW_BAND_SIGMAS = 2.0

#: Standardised outcome z = gross return / (daily vol x sqrt(h)), by horizon
#: and by where VNINDEX stood against its 200-session average at the signal.
#: A name's range = z x its own vol x sqrt(h) - costs. Checked: 47-52% of
#: picks landed inside their own predicted P25-P75 in every volatility tercile.
Z = {
    (20, None):  {"q10": -1.138, "q25": -0.509, "q50": 0.107, "q75": 0.829, "q90": 1.672,
                  "win": 0.504, "n": 14284},
    (40, None):  {"q10": -1.100, "q25": -0.473, "q50": 0.133, "q75": 0.911, "q90": 1.885,
                  "win": 0.530, "n": 14133},
    (20, True):  {"q10": -1.123, "q25": -0.539, "q50": 0.087, "q75": 0.932, "q90": 1.829,
                  "win": 0.496, "n": 9548},
    (20, False): {"q10": -1.181, "q25": -0.444, "q50": 0.136, "q75": 0.673, "q90": 1.347,
                  "win": 0.521, "n": 4736},
    (40, True):  {"q10": -1.043, "q25": -0.487, "q50": 0.170, "q75": 1.044, "q90": 2.083,
                  "win": 0.539, "n": 9512},
    (40, False): {"q10": -1.329, "q25": -0.439, "q50": 0.082, "q75": 0.667, "q90": 1.432,
                  "win": 0.511, "n": 4621},
}

#: Mean excess over the average liquid name in the basket, per pick, BEFORE
#: costs -- the whole reason to pick at all. Below the 200-day average it is
#: a third of what it is above (and after costs, about nothing).
EDGE = {(20, None): 0.0107, (20, True): 0.0123, (20, False): 0.0075,
        (40, None): 0.0211, (40, True): 0.0276, (40, False): 0.0076}

#: The whole book (8 names, reviewed every 20 sessions), every 20/40-session
#: window 2019-07..2026-09, after costs. Diversified, so tighter than a pick.
BOOK = {
    20: {"q25": -0.023, "q50": 0.027, "q75": 0.091, "mean": 0.026, "win": 0.64, "beat_vn": 0.60},
    40: {"q25": -0.026, "q50": 0.039, "q75": 0.146, "mean": 0.052, "win": 0.64, "beat_vn": 0.63},
}

#: Headline numbers for the bulletin -- same study, same caveats.
RECORD = {
    "window": "2019-07 → 2026-09",
    "cagr": 0.310, "sharpe": 1.10, "maxdd": -0.475, "worst_year": ("2022", -0.306),
    "vnindex_cagr": 0.089,
    "since_2022_cagr": 0.143, "since_2022_vnindex": 0.037,
    "last_12m": (-0.03, 0.165), "last_12m_vnindex": 0.059,
}


def accept_range(close: float, vol_d: float | None) -> tuple[float | None, float | None]:
    """(low, high) around the signal close. See ENTRY_PREMIUM_MAX / LOW_BAND_SIGMAS."""
    if not close or close <= 0:
        return None, None
    hi = close * (1.0 + ENTRY_PREMIUM_MAX)
    lo = close * (1.0 - LOW_BAND_SIGMAS * vol_d) if vol_d else None
    return (round(lo, 2) if lo else None), round(hi, 2)


def outlook(vol_d: float | None, market_up: bool | None, horizon: int) -> dict[str, float] | None:
    """This name's measured outcome band over `horizon` sessions, after costs.

    `market_up`: VNINDEX above its 200-session average at the signal; None
    (unknown) uses the table pooled over both.
    """
    if not vol_d or vol_d <= 0 or horizon not in (20, 40):
        return None
    z = Z[(horizon, None if market_up is None else bool(market_up))]
    s = vol_d * math.sqrt(horizon)
    return {"p10": z["q10"] * s - ROUND_TRIP, "p25": z["q25"] * s - ROUND_TRIP,
            "median": z["q50"] * s - ROUND_TRIP, "p75": z["q75"] * s - ROUND_TRIP,
            "p90": z["q90"] * s - ROUND_TRIP, "win": z["win"]}


def annotate(close: float, vol_d: float | None, market_up: bool | None) -> dict[str, Any]:
    """Everything the surfaces print for one pick, as plain numbers."""
    lo, hi = accept_range(close, vol_d)
    return {"accept_lo": lo, "accept_hi": hi,
            "outlook_4w": outlook(vol_d, market_up, 20),
            "outlook_8w": outlook(vol_d, market_up, 40)}


def market_state(vnindex_closes: list[float] | Any) -> dict[str, Any]:
    """VNINDEX against its 200-session average, from a daily close series.

    Context, not a switch: the study's market-timing switch lost 21.5% in the
    holdout year (whipsaws in 03/2026 and 07/2026) and was dropped. What the
    data does say is that new picks bought below the average earned a third of
    the edge (EDGE) -- worth knowing before opening a position.
    """
    c = [float(x) for x in vnindex_closes if x is not None and float(x) == float(x)]
    if len(c) < 200:
        return {"up": None, "vnindex": c[-1] if c else None, "sma200": None, "gap": None}
    sma = sum(c[-200:]) / 200
    return {"up": c[-1] > sma, "vnindex": c[-1], "sma200": sma, "gap": c[-1] / sma - 1.0}


# ============================== sentences ====================================
# The same three sentences on every surface (bulletin, email, Daily Insight),
# written once here -- two copies of a caveat drift apart (§22.11).

def _p(v: float, nd: int = 1) -> str:
    return f"{v * 100:+.{nd}f}%"


def market_sentence(mk: dict[str, Any] | None) -> str:
    """One VN sentence on VNINDEX vs its SMA200 and what that did to the edge."""
    mk = mk or {}
    if mk.get("up") is None:
        return ("Thị trường: chưa lấy được VNINDEX ngày — kỳ vọng dưới đây dùng phân phối "
                "gộp cả hai trạng thái.")
    where = "trên" if mk["up"] else "dưới"
    base = (f"Thị trường: VNINDEX {mk['vnindex']:,.1f} {where} trung bình 200 phiên "
            f"{mk['sma200']:,.1f} ({mk['gap'] * 100:+.1f}%).")
    if mk["up"]:
        return base
    return (base + " Lịch sử: mã mới mua khi VNINDEX dưới trung bình 200 phiên chỉ có khoảng "
            f"1/3 lợi thế (8 tuần: {_p(EDGE[(40, False)])} so với mặt bằng, trước phí; khi "
            f"trên: {_p(EDGE[(40, True)])}). Không phải lệnh đứng ngoài — công tắc thời điểm "
            "đã thua trong năm kiểm tra — nhưng là lý do để mở vị thế mới chậm hơn.")


def book_sentence() -> str:
    """The whole book's measured 4/8-week windows."""
    b20, b40 = BOOK[20], BOOK[40]
    return (f"Cả rổ {BUY_TOP_K} mã, chia đều, xem lại mỗi 4 tuần (2019-07 → 2026-09, sau phí): "
            f"4 tuần trung vị {_p(b20['q50'])}, một nửa số lần trong {_p(b20['q25'])} … "
            f"{_p(b20['q75'])}, lãi {b20['win'] * 100:.0f}% số lần; 8 tuần trung vị "
            f"{_p(b40['q50'])} ({_p(b40['q25'])} … {_p(b40['q75'])}), lãi "
            f"{b40['win'] * 100:.0f}% số lần.")


def pick_sentences(p: dict[str, Any]) -> tuple[str, str]:
    """(accept range, 4/8-week outlook) for one annotated pick."""
    lo, hi = p.get("accept_lo"), p.get("accept_hi")
    rng = (f"vùng mua {lo:,.2f}–{hi:,.2f}" if lo is not None and hi is not None
           else f"mua không quá {hi:,.2f}" if hi is not None else "")
    parts = []
    for key, label in (("outlook_4w", "4 tuần"), ("outlook_8w", "8 tuần")):
        o = p.get(key)
        if o:
            parts.append(f"{label}: trung vị {_p(o['median'])} (một nửa số lần {_p(o['p25'])} … "
                         f"{_p(o['p75'])}, lãi {o['win'] * 100:.0f}%)")
    return rng, "; ".join(parts)


def priority_sentence() -> str:
    """How to read the priority column -- the measured size and its limits."""
    return (f"Ưu tiên A = đã nằm trong top {BUY_TOP_K} liên tục ≥ {ESTABLISHED} phiên (xu hướng "
            f"bền); B = mới vào. Mua ít mã thì lấy A trước, trong mỗi nhóm theo hạng. Đo "
            f"2019-2025: mỗi mã A hơn mã B trung bình {_p(PRIORITY_EDGE[20])} sau 4 tuần, "
            f"{_p(PRIORITY_EDGE[40])} sau 8 tuần; 12 tháng gần nhất cùng chiều. Chênh lệch nhỏ và "
            "không năm nào cũng đúng (2025 ngược lại). Tỷ lệ lãi của từng mã chỉ khoảng 55%, "
            "nên cầm vài mã luôn an toàn hơn dồn vào một mã.")


def sell_rule_sentence() -> str:
    """The per-position sell rule and what was measured against it."""
    e = EXIT_STUDY
    base = e["review_20_keep_16"]
    return (f"Luật bán, tính từ ngày anh mua từng mã: xem lại ở phiên thứ {REVIEW_SESSIONS}, "
            f"{2 * REVIEW_SESSIONS}, {3 * REVIEW_SESSIONS}… Đến kỳ mà mã nằm ngoài top {KEEP_TOP} thì "
            f"bán ATO phiên kế; còn trong top {KEEP_TOP} thì giữ tới kỳ sau, không giới hạn số "
            f"phiên. Giá mua không quyết định bán. Đo 2019-2025 trên cùng rổ ({base * 100:.0f}%/năm "
            f"với luật này): chốt lời khi lãi +20% còn {e['take_profit_20'] * 100:.0f}%/năm, +30% "
            f"còn {e['take_profit_30'] * 100:.0f}%; bán cứng ở phiên 40 còn "
            f"{e['hard_cap_40'] * 100:.0f}%; kiểm hạng mỗi ngày còn "
            f"{e['rank_check_daily'] * 100:.0f}%. Cắt lỗ −10% được "
            f"{e['cut_loss_10'] * 100:.0f}% nhưng tệ hơn ở 3/6 năm và mức −15% không giúp, nên "
            "không đưa vào luật.")


def rule_sentence() -> str:
    """What the rule is and what its record honestly means."""
    r = RECORD
    return (f"Luật mua (từ 2026-09-28): xếp 75 mã rổ ngành theo lãi 6 tháng chia biến động, "
            f"mua {BUY_TOP_K} mã đầu chia đều; xem lại mỗi 4 tuần, giữ mã còn trong top "
            f"{KEEP_TOP}. Lịch sử {r['window']}: {r['cagr'] * 100:.0f}%/năm (VNINDEX "
            f"{r['vnindex_cagr'] * 100:.1f}%), năm tệ nhất {r['worst_year'][0]} "
            f"{r['worst_year'][1] * 100:.0f}% — số lạc quan (rổ chọn năm 2026); kỳ vọng trung "
            "thực là VNINDEX cộng khoảng 10 điểm %/năm, dao động lớn.")
