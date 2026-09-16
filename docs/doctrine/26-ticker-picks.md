# §26 — Điểm chấm mã xếp hạng ngược, và khung thời gian đáng giá gấp mười lần

> Tách khỏi `CLAUDE.md` ngày 2026-09-16 để doctrine trở lại ngân sách context
> (135.718 B nạp lại **mỗi lượt**; ngân sách của `claude/CLAUDE.md` mẹ là 10 KB).
> **Nội dung dưới đây nguyên văn** — không tóm tắt, không sửa số, không sửa ngày.
> **CẢNH BÁO TRƯỚC KHI ĐỌC SỐ:** mọi figure "net/lệnh" và "quy năm" trong file
> này tính ở **0,70%/vòng**, và con số đó **sai** — đúng là **1,00%** (§18.2/9 +
> `config.BACKTEST_SLIPPAGE_MIN_PCT`). Xem đính chính ở `CLAUDE.md` §26.6.
> Các con số **excess** không bị ảnh hưởng.
>
> `CLAUDE.md` giữ lại: công thức đang ship, số học chi phí, và §26.8/§26.10 còn mở, và trỏ về file này.

## 26. The per-ticker picks ranked backwards — 2026-09-16

Tom: *"thuật toán chưa tốt … các mã cổ phiếu bạn suggest nhưng thực tế kết quả
chậm hơn nhiều so với T+3."* Both halves turned out to be true, for two
different reasons, and the second one is not an algorithm problem at all.

### 26.1 Nothing in the repo could answer the question

There is no record of what this system recommended. `PicksUniverseService` keeps
**one** snapshot (today's), the position book holds only what Tom marked by
hand, and no table stores a pick. The only durable trace is
`report/daily_report_<date>.html`, so `scripts/extract_past_picks.py` reads the
archive back: **174 BUY picks, 45 symbols, 17 report dates, 2026-07-23 →
2026-09-14**.

Scoring them needed a per-ticker price panel, which also did not exist —
`_legacy_stock_prices` stops at 2026-04-08 and the snapshot carries 30 sessions.
`scripts/build_price_panel.py` builds and caches one: **143 HOSE names ×
1,168 sessions, 2022-01 → 2026-09**, plus `^VNINDEX` so the benchmark shares the
panel's calendar. It is incremental, so the 18 req/min gate is paid once.

> **Panel breadth is load-bearing and nearly ruined the first pass.** Seeded
> from the legacy table alone the panel was **21 names wide before 2025** — the
> fetcher only chased each symbol's missing *tail*, never its missing *head*.
> Every 2023-24 number computed on that panel was "top 5 of 21", a quarter of
> the market. `min_names=30` in the bench now refuses such a cross-section
> outright.

### 26.2 The ranking was worse than random

`scripts/ticker_alpha_bench.py` is the ticker-level twin of
`stealth_leadtime_experiment.py` and carries §16.12's discipline: every run
prints the **base rate** (equal-weight eligible universe, same entry and exit),
splits **by year**, costs come from `config`, entry is the **next session's
open** (the report is written after the close it quotes), and no horizon shorter
than `BACKTEST_SETTLEMENT_LAG` is allowed.

| rule, exit +3 sessions | excess vs base | quintiles | IC (t) |
|---|---|---|---|
| shipped score | **−0.06%** | **not monotone** — Q5 (−0.06) below Q4 (+0.17) | +0.002 (0.4) |
| shipped score, `(score, dv_20d)` — *as actually ranked* | **−0.15%** | worse | +0.002 (0.3) |
| new score (§26.4) | **+0.21%** | monotone, −0.14 → +0.20 | +0.053 (7.9) |

By calendar year the shipped score is **negative in four of five**
(2023 −0.16, 2024 −0.15, 2025 −0.02, 2026 −0.48). Run as a book — 5 positions,
20-session hold, T+2, fees + 15bps slippage per side — it returns **−42.9%**
over 2023-01 → 2026-09 while VNINDEX returns **+71.3%**.

**Why it ranked backwards.** The score counted trend-continuation conditions:
above SMA20, above SMA50, MACD > 0, ADX > 20, RSI(14) in 50-70, volume surge.
That is a description of a stock that has **already run** — §16's "ngọn", the
canopy this system was explicitly built not to buy — and at a 2-20 session
horizon Vietnamese cross-sectional returns are dominated by short-horizon **mean
reversion**. The score was the right family for the wrong holding period.

**The dollar-volume tie-break was not neutral, it was harmful.** Inside every
score bucket it handed back the largest and slowest name on the board, and it
took the excess from −0.06% to −0.15%. Ties now break on the **symbol**:
arbitrary but stable, and not a second unmeasured factor smuggled into the
ranking. Liquidity stays where a liquidity requirement belongs — a hard filter
upstream.

### 26.3 The picks were not slow; the card never said how long

`scripts/audit_past_picks.py`, over the 174 real picks, entry at the next open:

| hold | picks | base rate | excess | net of fees |
|---|---|---|---|---|
| T+2 | −0.51% | −0.68% | +0.17 | −0.91% |
| **T+3** | **−0.43%** | −0.86% | +0.43 | **−0.83%** |
| T+10 | −0.61% | −1.46% | +0.85 | −1.01% |

Note what that table does *not* say: over this particular two-month stretch the
picks **beat** the base rate at every horizon. n=174 across 17 dates is far too
small to call that an edge — the four-year bench above says the opposite — but
it does mean the losses were mostly the market, not the selection.

The decisive numbers are these:

| within the 15 sessions after entry | share | median sessions |
|---|---|---|
| reached the printed TARGET | 15% | 7 |
| reached it **inside T+3** | **4%** | — |
| touched the printed STOP | 50% | 4 |
| touched it **inside T+3** | **24%** | — |

`PickProfile.SWING` is a 2.5×ATR target and a 1.8×ATR stop — at a typical VN
ATR of ~2% that is a **+5% target, three to four weeks out**. Closing it on a
T+3 clock turns a 15%-vs-50% race into a **4%-vs-24%** one. The picks were not
slower than T+3; the trade printed on the card was never a T+3 trade, and the
card never said so. `PROFILE_HORIZON_SESSIONS` and `horizon_note()` now say it,
and the sentence lives beside the ATR multipliers so whoever changes the target
distance owns the words describing it (§25.6's placement argument).

**`TPLUS` is not the fix and is not the default.** Measured over the panel, its
1.0×ATR stop is touched by noise on **31-42%** of three-session holds against
11-12% for SWING's 1.8×ATR. A tighter stop on a short clock is a worse lottery,
not a shorter one.

### 26.4 What shipped

`services/picks_scoring.py::score_ticker` returns a float, ~−9..+7, with an
`UNTRENDED_FLOOR` of −20 for names whose uptrend cannot be confirmed:

```
score = −1
      + (50 − RSI(2)) / 10                 oversold — Connors
      + clip(−ret_1d / ATR, −2, +2)        today's move in the stock's OWN ATRs
      + 2   if above SMA50
      − 1.5 if ATR% > 3.5
      floored to −20 unless above SMA200
```

Three terms survived measurement. `oversold` is the single strongest factor in
the bench (IC +0.037, t = 7.3). `pullback` is self-normalising, so a 2% drop in
a quiet bank and a 2% drop in a wild broker are not the same event — no
cross-section needed, which is what lets a per-row function do the job. The
trend gate matters because un-gated mean reversion buys falling knives; it was
worse in every table.

**The ATR penalty is the term that carries 2026** — without it the score is
−0.11% that year, with it +0.29%. That matches §25.9's finding that high
volatility, not the calendar, is where these models degrade.

Also shipped: the OHLCV lookback goes **110 → 400 calendar days** (~70 → ~270
sessions), because SMA200 needs 200 bars and the gate needs SMA200. Same *one*
call per symbol, so it costs nothing against the KBS budget.
`generate_report.py`'s parallel shortlist logic moves onto the same constants:
`MIN_BUY_SCORE` (the measured 78th percentile of gated scores, replacing a
literal `>= 3` on a scale that no longer exists) and `MAX_5D_DROP_PCT = −12`,
which replaces `ret_5d > −1` — a momentum filter that excluded exactly the
pullbacks the new score exists to find, while the genuinely toxic tail
(free-falling names, down on news) stays excluded an order of magnitude lower.

The bench **imports** the coefficients rather than retyping them, and
`test_the_bench_and_the_service_agree_row_by_row` pins the two implementations
to the same number on real panel rows — §22.11's lesson about a definition
living in two files.

**`MIN_BUY_SCORE` is also enforced in `_select_top`, and the shortlist is now
allowed to be short.** Found on the first live rebuild: that method filtered on
`is_valid_buy` alone, which only says the stop and target are geometrically
sane, so the page padded itself to five with names scoring −0.65 and −0.77 —
"overbought inside an uptrend", the exact shape this rewrite demotes. It was
invisible under the old score, which could not go negative. Measured over the
panel at 108 eligible names a day, **median 10** names clear the bar, 95% of
days have at least one and 73% have five; in 2026 it is median 7. The
production universe is ~55 names, so expect roughly half that, and expect thin
days when the tape is overbought — 2026-09-16 admitted exactly one. A short
list on such a day is the answer, not a bug.

### 26.5 The foreign-room feed emptied the universe, live

Found while rebuilding the snapshot, unrelated to the rewrite and worse than it:
the KBS price board returned `foreign_room = 0` for **every** name — VCB, FPT,
HPG, SSI, DCM included, with `foreign_buy_volume` and `foreign_sell_volume`
zero too. The capability filter is `room > MIN_FOREIGN_ROOM_PCT` with that
constant at `0.0`, so every blue chip on HOSE read as foreign-full, stage C1
passed **0 of 75**, and the build finished with 0 tickers.

This is §25.5's asymmetry again: *a zero that means "missing" and a zero that
means "none left" are the same number.* The only defence is to judge the
**column**, not the cell — one full name among normal ones is ordinary, every
name full at once is a dead feed. An all-zero block is now `None`
("could not verify"), which the filter already keeps.

### 26.6 The part that is not an algorithm problem

At `BACKTEST_FEE_BPS`×2 + `BACKTEST_SELL_TAX_BPS` + 15bps slippage per side =
**0.70% per round trip**, the annual cost of rotating is:

| hold | rebalances/yr | cost drag/yr |
|---|---|---|
| **T+3** | 84 | **58.8%** |
| T+10 | 25 | 17.6% |
| T+20 | 13 | 8.8% |
| T+60 | 4 | 2.9% |

The equal-weight eligible universe returned **+12.5%/yr** over 2023-2026. A T+3
rotation therefore has to generate **58.8%/yr of gross alpha to break even**.
The best ranking rule measured here is worth **+0.21% per trade**. It is not a
near miss; it is off by two orders of magnitude, and it is the same arithmetic
§23.5 logged at sector level ("45% friction on 844 trades a year").

**Stated plainly: T+3 rotation cannot be made profitable on this universe at
these costs, by this ranking or any other.** The scoring rewrite is worth
shipping because a ranking that is worse than random is worth fixing whatever
the horizon — but it does not make short-horizon churn viable, and nothing in
§26 should be read as saying it does. The honest use of the daily list is a
**3-4 week** shortlist.

And one more line that no rule here clears: over 2023-01 → 2026-09 **VNINDEX
buy-and-hold returned +71.3%, CAGR 15.7%, Sharpe 0.91, MaxDD −18.1%.** The best
rule measured (`rsi2_oversold_uptrend`, 20-session hold) reaches +75.4% total
but at Sharpe 0.70 and MaxDD −40.8%, with +101.5% of it in 2025 alone. No
variant beat the index risk-adjusted.

### 26.7 Entering at the next open forfeits the drift

Measured across the panel, equal-weight over eligible names, 2023-01 → now:

| leg | per session | annualised |
|---|---|---|
| overnight (close → next open) | **+0.149%** | **+37.6%** |
| intraday (open → close) | −0.086% | −21.6% |
| total | +0.057% | +14.3% |

This is the Lou/Polk/Skouras overnight-vs-intraday decomposition, and it is
stark here. The operational consequence is exact and horizon-independent: an
entry at the next open instead of the same session's close costs **0.145
percentage points**, identical at every hold from 2 to 20 sessions — about a
fifth of the whole round-trip cost, given away by the 17:00 schedule.

**Not acted on, deliberately.** Capturing it means scoring before the 14:45 ATC
auction, which is a different pipeline with different freshness guarantees, and
~28% of the panel's opens equal the previous close exactly, so the tradeable
share of that 0.145pp is unproven. It is recorded because it is larger than the
ranking edge and nobody had measured it.

### 26.8 Open
- **Nothing beats the index.** Until some rule does, risk-adjusted, the daily
  list is a shortlist for a discretionary reader, not a system to follow.
- **The book simulation is too noisy to choose rules** at 5 positions and
  100-200 trades over 3.7 years: the same rule swings from −49% to +56% between
  a 10- and a 20-session hold. The cross-sectional bench (1,114 days × ~90
  names) is the deciding instrument; the book sim is a sanity check on
  mechanics, not an oracle. Do not pick a rule from it.
- **No factor is positive in all five years at T+3.** The uptrend + oversold
  family works 2023-2025 and fades in 2026 — the same year §16.13 and §25.9
  already attribute to the tape.
- `MIN_BUY_SCORE` is a percentile of the current panel. It should be
  re-measured when the universe changes, and it is not a probability.

### 26.9 The horizon is worth ten times the algorithm — 2026-09-16 (2)

Tom, after reading §26.6: *"cho phép thay đổi dự báo mua 2-4 tuần nếu benchmark
test cho thấy profit lợi hơn … cái tôi cần là profit."* Web access was granted
for the same question. Both halves are answered here.

**Web search and WebFetch are unavailable in this session** — both route through
a model this account cannot reach. The built-in browser does not, so the reading
below was done through it. Two claims were checked because each could have
overturned §26.6, and one secondary source turned out to be wrong:

| claim | verdict |
|---|---|
| settlement lets you sell on T+2 | **confirmed.** VNDIRECT's own HSX/HNX pages: shares credited *before 13:00 on T+2*, and the afternoon session opens at 13:00. `BACKTEST_SETTLEMENT_LAG = 2` is right, and §22.10's 2026-08-24 correction from T+3 was right. A widely-syndicated advisory page claiming "sellable only from T+3 morning" cites Thông tư 120/2020, which predates the 2022 move to T+2. |
| the fee stack is 0.15%/side | **optimistic but in range.** VPS online is 0.2% under 100tr, falling to 0.15% above 2 tỷ, plus the 0.1% sell tax. So §26.6's 0.70% round trip is at the *cheap* end of reality, which makes its conclusion conservative rather than overstated. |

#### The one number that matters

Base rate — no ranking at all, equal-weight eligible universe, entry at the next
open, 0.70% round trip:

| hold | net per trade | rebalances/yr | **annualised** |
|---|---|---|---|
| 3 sessions | −0.62% | 84 | **−40.6%** |
| 10 | −0.20% | 25 | −4.9% |
| **15** | **+0.08%** | 17 | **+1.3%** ← costs break even here |
| 20 | +0.36% | 13 | +4.7% |
| 40 | +1.56% | 6 | +10.2% |
| 120 | +7.16% | 2 | +15.6% |

**Trading frequency is a pure tax and it is the largest term in the whole
system.** Moving from T+3 to a four-week hold is worth roughly **+45 percentage
points a year** before any ranking skill at all. The best ranking rule measured
in this entire investigation is worth **+0.5 to +0.8pp per trade**. The horizon
is not one lever among several; it is an order of magnitude larger than the
algorithm, and it was the thing nobody had measured.

#### What the literature bought, and what it did not

The one genuinely new idea came from *Factors and anomalies in the Vietnamese
stock market* (Pacific-Basin Finance Journal 82, 2023), whose Fama-MacBeth table
puts **ln(ME) at −0.11, p<0.01** — a strong size effect on HOSE/HNX, with EP
significant, BM and beta not. That is a hypothesis, not evidence, so it was
tested here rather than adopted: a size tilt *does* help pooled (+0.40% excess at
+20) but **fails 2025 (−0.64)**, so it does not clear §16.12's within-year bar
and is not shipped. The paper's real contribution was pointing at the family;
the term that survived testing was a different one.

#### What shipped: a cross-sectional ordering pass

`score_ticker` answers "is this name worth owning" from one row. It cannot
answer "which of the worthy ones first", because the term that most improves the
order — **on-balance-volume trend**, 20d OBV change over the name's own 20d
average volume — only works once it is ranked against the day's cross-section.

| ordering, exit +20 | excess | IC (t) | quintiles | by year |
|---|---|---|---|---|
| score alone (§26.4) | +0.13% | 2.6 | not monotone | 3 of 4 + |
| score + OBV **added per row** | +0.23% | 3.0 | not monotone | 3 of 4 + |
| score + OBV **blended by rank** | **+0.49%** | **4.4** | **monotone** | **4 of 4 +** |

At +40 the same ordering gives +0.77% excess, IC t = 3.6, monotone
(+1.60 / +1.78 / +2.17 / +2.34 / +2.56), positive in all four years.

The per-row form was tried first because it would have needed no new stage, and
it is measurably worse: adding a raw value lets one day's dispersion decide
whether the term dominates or vanishes. `blended_rank_scores` runs once per
build over the whole universe (`PicksUniverseService` Stage E) and writes
`TickerRow.rank_score`, which `_rank_key` now reads. The displayed score is
unchanged, so `MIN_BUY_SCORE` keeps its meaning: the score decides *admission*,
the blend decides *order*.

**A surprising property, pinned by test.** With 50/50 weights the best score
paired with the worst flow **ties** the worst score paired with the best flow.
That is safe only because admission runs first — `_select_top` drops everything
under `MIN_BUY_SCORE` before the ordering is consulted. The first draft of
`test_a_50_50_blend_can_tie_the_best_score_with_the_worst` asserted the
opposite, failed, and that is how the property was found;
`test_flow_cannot_rescue_a_name_the_score_gate_rejects` now pins the dependency
the tie relies on. Reading either test alone would mislead.

#### Expected return, honestly

Combining the measured base rate with the measured edge, at top-5:

| hold | net/trade | **annualised** | of which base | of which ranking |
|---|---|---|---|---|
| 10 sessions | +0.16% | +4.1% | −5.9% | +10.0% |
| 15 | +0.50% | +8.7% | +0.5% | +8.2% |
| **20 — 4 weeks** | +0.77% | **+10.1%** | +3.6% | +6.6% |
| 30 | +1.41% | +12.5% | +7.5% | +5.0% |
| **40 — 8 weeks** | +2.16% | **+14.4%** | +9.1% | +5.3% |
| 60 | +2.69% | +11.8% | +9.9% | +1.9% |

**VNINDEX buy-and-hold over the same window: +15.7% CAGR, Sharpe 0.91, MaxDD
−18.1%.** So the best configuration measured still does not beat holding the
index, and it carries five-name concentration on top. The ranking generates
genuine alpha — +5 to +10pp/yr over its own base rate — but a rotating book
starts 4-9pp/yr behind buy-and-hold on costs alone, and the alpha roughly pays
that back rather than exceeding it.

What the change **is** worth is measured against the system as it stood
yesterday: the old ordering scored −0.56% excess at +20 and the new one +0.49%,
a swing of **+1.05pp per trade, about +13pp a year** at a four-week cadence.
That is the honest claim: this is a large improvement to a losing ranking, not a
demonstration that the ranking beats the index.

#### The book simulation was noise, and saying so is the finding

`picks_portfolio_sim.py` made the 40-session hold look spectacular — +170%
total, CAGR 30.9%. A sweep of the holding period on the *same rule* killed it:

| hold | 15 | **20** | 25 | 30 | 40 | **60** |
|---|---|---|---|---|---|---|
| total | +25.9% | **−17.1%** | +78.8% | +127.2% | +170.2% | **−30.7%** |
| Sharpe | 0.35 | −0.09 | 0.67 | 1.03 | 0.86 | −0.31 |

The sign flips twice and neighbouring holds differ by 96 percentage points. A
real edge does not do that; ~100 trades over 3.7 years is dominated by which
specific names happened to be held. §26.8 had already logged this and it was
worth re-confirming rather than believing the +170%. **Every number in this
section comes from the cross-sectional bench** (789-1,126 daily cross-sections
with within-year splits), never from the book sim.

#### Open
- **Still nothing beats the index.** The recommendation stands: the daily list
  is a shortlist for a reader who has decided to pick stocks, not a case for
  picking stocks over an index position.
- **The size effect is unresolved, not rejected.** It is significant in the
  literature and pooled here, and fails one year out of four. A longer panel
  would settle it; 3.7 years does not.
- ~~**The SWING target distance was not re-derived for the longer horizon.**~~
  **Measured — see §26.10. The target was not the problem; the STOP was.**
  `MIN_BUY_SCORE` is still not re-derived for the longer horizon.

### 26.10 The stop is costing more than it protects — measured, not shipped

Found while checking whether the SWING geometry still makes sense at the longer
horizon (§26.9's third open item). It does not, and the reason is not the target
distance — it is the stop.

Over 3,542 trades, 2023-01 → 2026-09, four-week hold, top-5 by the new ordering:

| geometry | mean/trade | excess vs own control | by year 23/24/25/26 |
|---|---|---|---|
| SWING 2.5/1.8 (**shipped**) | **−0.14%** | +0.26 | +0.17 / +0.92 / −0.07 / +0.02 |
| TPLUS 2.0/1.0 | −0.30% | +0.20 | +0.39 / +0.41 / −0.05 / +0.06 |
| tight 1.0/1.0 | −0.47% | +0.18 | all + |
| wide-stop 2.0/3.0 | −0.14% | +0.12 | −0.04 / +0.74 / +0.05 / −0.37 |
| **no stop, time exit** | **+0.72%** | **+0.33** | −0.41 / +0.67 / +0.64 / +0.58 |

**Every stopped variant loses money; only the unstopped one makes any.** The
mechanism is in the exit counts: at the shipped 2.5/1.8 over twenty sessions,
40% of trades reach the target and **44% touch the stop**. A stop that fires as
often as the target is not protecting the thesis, it is ending it — the same
noise-versus-signal failure §26.3 measured at three sessions, arriving at four
weeks too.

#### The tail is the other half, and it does not say what it looks like it says

A mean cannot see why stops exist. So:

| geometry | mean | p5 | p1 | worst trade | share < −20% |
|---|---|---|---|---|---|
| SWING 2.5/1.8 | −0.14% | −9.1% | −11.5% | **−15.3%** | 0.0% |
| no stop | +0.72% | −14.2% | −22.5% | **−47.1%** | 1.6% |

Per trade, removing the stop makes the worst case **three times worse**. That is
real and it is the argument for keeping one.

But the book does not hold one trade:

| geometry | total return | max drawdown |
|---|---|---|
| SWING 2.5/1.8 | **−5.2%** | −21.5% |
| no stop | **+36.2%** | **−18.8%** |

*(equal-weight, five names at a time, approximated as the mean of overlapping
trades with a twentieth of the book turning over daily — it uses all 3,542
trades rather than the ~150 the full book sim produces, which is why it is
quoted here and §26.9's sim is not.)*

**At five positions the no-stop book earns more AND draws down less.** A −47%
single name is −9.4% of the book; the stop's cost is paid on every trade. The
job the stop was doing — bounding the tail — is already being done by position
count, and doing it a second time with a stop costs about **0.86 percentage
points per trade**, which is larger than the entire ranking improvement in
§26.9.

#### Not shipped, and that is a decision for Tom, not a measurement

Removing the printed stop is not a parameter change. `is_valid_long_pick`
requires `stop < entry`, the whole R:R floor is built on it, the Daily Insight
card draws a stop→target ladder, and the position book tracks `hit_stop`. More
to the point, a backtest cannot see the reasons a live trader wants a stop:
margin, a gap-down on news, or simply not watching the screen that day. The
measurement says the stop costs money on this sample at this horizon with five
positions. It does not say stops are useless, and nothing here should be read
that way.

What it does justify is putting the question to Tom with a number attached
rather than leaving the geometry unexamined because it has always been there.
