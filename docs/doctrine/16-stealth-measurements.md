# §16.4-16.8, §16.10-16.15 — Stealth: kế hoạch đã dựng và toàn bộ phép đo

> Tách khỏi `CLAUDE.md` ngày 2026-09-16 để doctrine trở lại ngân sách context
> (135.718 B nạp lại **mỗi lượt**; ngân sách của `claude/CLAUDE.md` mẹ là 10 KB).
> **Nội dung dưới đây nguyên văn** — không tóm tắt, không sửa số, không sửa ngày.
> `CLAUDE.md` giữ lại: §16.1 (cổng), §16.2 (feature), §16.3 (action), §16.9 (sizing) và kết luận của §16.11-16.15, và trỏ về file này.

### 16.4 New target / training change
- **Replace** `fwd_5d_sector_return` with `fwd_20d_sector_return` as the primary ranker target. 5d rewards noise chasing; 20d rewards real rotations.
- Add a **second ranker head**: classifier for "did this sector enter breakout within next 15 sessions?" (`1` if `fwd_15d_max_return > 2 × atr_pct`). Two-stage: ranker sorts by expected return, classifier filters noise.
- Training window: rolling 2y, monthly retrain (not nightly — flow regimes change slowly).

### 16.5 New scheduler jobs
| Job | Cron | Purpose |
|---|---|---|
| stealth_scanner | 0 17 * * 1-5 | Evaluate §16.1 conditions per sector, emit `ACCUMULATE` signals when they flip. |
| lead_time_audit | 0 3 * * 1 | Weekly: for each past breakout, measure how many days earlier `flow_z20` crossed +1; store in `flow_leadtime_proxy`. Use as model diagnostic. |
| flow_regime_report | 30 17 * * 5 | Friday EOD: export a "sector flow heatmap" (z20 grid) to Gmail via `trader_agent` + `generate_report.py`. |

### 16.6 Backtest extension
Add an **entry-timing attribution** report to `SectorBacktestService`:
- For each closed trade, compute `entry_lag_days` = days between `ACCUMULATE` trigger and eventual price breakout.
- Metric: **median entry lag** (target: ≥ 10 trading days — meaning Tom bought at least 2 weeks before the move).
- Metric: **"root capture ratio"** — (price at entry) / (price at trade peak). Target: ≤ 0.85 (you bought in the bottom 15% of the move).

### 16.7 New database fields
- `sector_flow_daily`: add `flow_z20`, `flow_z60`, `foreign_streak`, `foreign_hit_20d`, `stealth_score`, `flow_price_divergence`.
- New table `sector_accumulation_events (id, sector_code, start_date, end_date, peak_return_pct, lead_days_to_price, resolved)` — one row per stealth event, closed when the sector either breaks out or the stealth conditions invalidate.

### 16.8 Frontend surface
- **Flow Dashboard:** add a `flow_z20` column with a green halo when ≥ +1.0 for ≥ 5 sessions (visual stealth badge).
- **New page `/accumulation`:** live list of sectors currently in stealth phase, with `accumulation_age`, `stealth_score`, and the estimated `days_until_breakout` (historical median lead time).
- **Ranking page:** new `ACCUMULATE` badge (deeper green than BUY) with a "root/branch/canopy" label per sector.

### 16.10 Implementation order (append to §13)
11. Add §16.2 features to `flow_feature_service`, backfill over existing 2.2y panel.
12. Add `StealthDetector` in `analysis/stealth.py` implementing §16.1.
13. Add `ACCUMULATE` path + new sizing rules to `sector_signal_service` and `risk_service`.
14. Add `sector_accumulation_events` table + migration 9.
15. Switch ranker target to 20d + add classifier head in `models/rotation_ranker.py`.
16. Add three new scheduler jobs (§16.5).
17. Extend backtest metrics (§16.6) — validate against 2023-2025 VN rotations (bank rally Q4'23, steel run Q2'24, broker breakout Q1'25 as ground-truth cases).
18. Ship `/accumulation` frontend page + Flow Dashboard halo.

### 16.11 Success criterion
The system is considered successful on this axis if, in out-of-sample backtest across 2024-2026:
- **≥ 60% of `ACCUMULATE` signals** precede a price breakout by **≥ 10 trading days**.
- **Median root-capture ratio ≤ 0.85**.
- **False-positive rate ≤ 30%** (stealth signals that dissolve without a breakout).

Anything worse than this means the thesis is still lagging — go back to features.

> **First actual measurement — 2026-08-23. The gate fires and FAILS this
> section.** Now that §16.1 can fire at all, the 23 events it produces over the
> full panel were scored against the three criteria above:
>
> | criterion | target | measured (≥4/5, N=3) |
> |---|---|---|
> | breakout within 40d | — | 74% (17/23) |
> | lead time ≥ 10 trading days | ≥ 60% | **24%** — median lead **3 days** |
> | median root-capture ratio | ≤ 0.85 | **0.910** |
> | false positives | ≤ 30% | 26% |
>
> Tightening does not rescue it: ≥4/5 with N=5 gives 12 events, 92% breakout,
> 36% at ≥10d lead, root capture 0.913. Loosening is worse: ≥3/5 N=5 gives 130
> events, 79% breakout, 17% at ≥10d, 0.944.
>
> Read plainly: the gate now identifies sectors that **are about to move**
> (74-92% breakout is a real hit rate) but it identifies them **~3 days early,
> not ~2 weeks**, and it enters at 91% of the eventual peak. That is a momentum
> confirmation signal — §16.3's `BUY`, "cành cao" — wearing the `ACCUMULATE`
> label. **The "gốc" claim is not yet earned**, and no ACCUMULATE sizing rule
> (§16.9: 1.5× vol target, 2.5×ATR stop) should be trusted on it until the lead
> time is fixed.
>
> The conditions are the suspects, not the aggregation: c1 (`flow_z20 > 1`) is
> a *contemporaneous* flow spike, so it tends to fire with the move rather than
> ahead of it. The leading candidates in §16.2 that would actually buy lead time
> — `flow_price_divergence`, `foreign_streak`, `flow_leadtime_proxy` — are
> computed and stored but are in **no** condition. That is the next experiment.

> **The experiment was run — 2026-08-24 — and the suspect above was wrong.**
> `scripts/stealth_leadtime_experiment.py` scores candidate condition sets over
> the full panel. Every variant containing `flow_price_divergence` made lead
> time **worse** (median 3 → 2-3 days, ≥10d share 20% → 4-17%) while inflating
> the event count 20 → 38-77. It fires more often, not earlier.
>
> What moved was the condition §16.11 did not name: replacing **cond2's 20d hit
> *rate*** with **`foreign_streak ≥ 3`** — consecutive sessions of net foreign
> buying.
>
> | | events | breakout | ≥10d lead | med lead | med RC |
> |---|---|---|---|---|---|
> | shipped §16.1 | 20 | 75% | 20% | 3 | 0.940 |
> | cond2 → `foreign_streak ≥ 3` | 16 | 88% | **50%** | **8** | 0.924 |
>
> This is §18.5/21's argument arriving from the other direction: a hit rate is
> satisfiable by one block trade plus 19 quiet days, and one block trade is not
> accumulation. **Persistence is the part that leads.**
>
> **Not shipped, on purpose.** n=16 over 3.5 years, and the year split puts the
> entire effect before 2026: 2023-25 run 50-67% at ≥10d with median lead 10-14,
> while 2026's three events are 0% / median 3 — the same collapse the shipped
> gate shows in 2026 (0% at ≥10d on six events). Tightening to `streak ≥ 8`
> gives 100% at ≥10d on n=2, which is not a result. Root capture stays ~0.92
> against the 0.85 target either way, so no variant here earns the "gốc" claim.
>
> **The real question this surfaced:** both gates degrade sharply in 2026. A
> defect common to two different condition sets is more likely data or regime
> than condition choice — that is the next thing to look at, ahead of any
> further condition tuning.

### 16.12 The base rate — and why §16.11's criteria are not sufficient

> **2026-08-24, chasing the 2026 collapse.** Adding the missing row to
> `scripts/stealth_leadtime_experiment.py` — score **every** row in the panel,
> i.e. no gate at all — produced the most important number in this section:
>
> | | events | breakout | ≥10d lead | med lead | med RC |
> |---|---|---|---|---|---|
> | **NO GATE (base rate)** | 13,033 | **83%** | **23%** | **4** | **0.944** |
> | shipped §16.1 | 20 | 75% | 20% | 3 | 0.940 |
> | cond2 → `foreign_streak ≥ 3` | 16 | 88% | 50% | 8 | 0.924 |
>
> **The shipped gate is worse than not filtering at all.** Lower breakout rate,
> fewer early signals, shorter lead. Of the six variants only
> `foreign_streak` beats the base rate on any axis.
>
> **Every number in this section and §16.11 uses the old 1.15% bar — see
> §16.15.** Re-measured under a horizon-consistent one, the base rate is 43%
> breakout / 74% at ≥10d, and the shipped gate still fails to beat it. The
> ranking of the variants does not change; the absolute levels do.
>
> **§16.11's three criteria cannot detect this**, which is the doctrine defect.
> They are absolute thresholds ("≥60% at ≥10d", "RC ≤ 0.85", "FP ≤ 30%"), so a
> gate posting a respectable-sounding 75% breakout reads as *underperforming a
> target* when it is in fact **selecting worse-than-random sector-days**. Every
> §16.11 measurement from here on is reported against the NO GATE row, and a
> variant that does not beat it is not a signal regardless of its absolute
> numbers. The bench prints the row on every run.
>
> **Amend §16.11's success criteria accordingly:** each of the three targets is
> now *necessary but not sufficient* — a candidate must also beat the
> unconditional base rate on breakout share and ≥10d share, **within each
> year**, not pooled. Pooling is what let `foreign_streak`'s pre-2026 strength
> mask a 2026 that matches random.

### 16.13 The 2026 collapse is mostly the market

> **Same investigation, 2026-08-24.** Ruled out first, cheaply:
> - **Not data.** 2026 rows are 99% non-zero `foreign_net`, 100% `close_idx`
>   and `atr_pct`, 15 sectors, 156 sessions — coverage matches 2024-25.
>   `breadth_sma20` has **zero NULLs** in 2024-26 (245 in 2023 only); its
>   apparent "76% coverage" was a miscount on my part — a legitimate `0.0` is
>   not a missing value. Its zero *rate* does rise, 14/15/16% in 2023-25 →
>   **24%** in 2026, which is not a gap but the flat tape below showing up in
>   breadth: on a quarter of 2026 sector-days no constituent was above its
>   SMA20. (Breadth takes 9 distinct values over 5 names — §20.3 P1-3.)
> - **Not right-censoring.** Only 1 of 7 shipped-gate events in 2026 has fewer
>   than 40 forward sessions, so "a long lead is unobservable near the panel
>   edge" does not explain it.
>
> What did explain most of it is the tape itself. The **unconditional** base
> rate falls in lockstep:
>
> | year | base breakout | med fwd-40d max | gate breakout | gate ≥10d |
> |---|---|---|---|---|
> | 2023 | 88% | +7.1% | 80% | 25% |
> | 2024 | 84% | +5.4% | 100% | 25% |
> | 2025 | 86% | +7.9% | 80% | 25% |
> | **2026** | **68%** | **+3.2%** | **50%** | **0%** |
>
> 2026 is a flatter tape: half the forward move, and a breakout definition
> pinned to 2×ATR catches far less of it. **But the gate degrades faster than
> the market** — 50% vs a 68% base rate, 0% vs 18% at ≥10d. So regime explains
> the level, not the shortfall. Both remain open; the tape is the larger term.

> **"Flatter" was the wrong word — 2026-08-24 (4).** Measured directly
> (`scripts/late_period_diagnosis.py`, check 2), 2026 is not flat, it is
> **down, and more volatile than the two years before it**:
>
> | year | med fwd-40d | med fwd-40d **max** | % of fwd-40d positive | ann vol |
> |---|---|---|---|---|
> | 2023 | +3.9% | +7.1% | 70% | 0.89 |
> | 2024 | +1.4% | +5.4% | 58% | 0.21 |
> | 2025 | +3.6% | +7.9% | 63% | 0.29 |
> | **2026** | **−7.6%** | **+2.9%** | **17%** | **0.42** |
>
> The `med fwd-40d max` column is what §16.13 was reading, and taken alone it
> does look like a quiet tape. It is not: only the *max* compressed. The median
> forward move went negative and vol went **up**. That distinction matters for
> what to do next — a quiet tape argues for a more sensitive gate, a falling
> one argues that a long-only breakout definition has little to find, which is
> a different problem with a different fix.
>
> The 2×ATR breakout bar also moves with the tape it is measuring: ATR rose,
> so the bar rose, while the moves it must clear shrank. A breakout definition
> that gets harder exactly when the market gets choppier will show a collapse
> in any year like this one, independent of the gate.

### 16.14 What this means for §16 as a whole

> Stated plainly, so no later reader has to re-derive it: **as of 2026-08-24
> the §16.1 gate has no measurable edge.** It fires 20 times in 3.5 years and
> those 20 sector-days break out *less* often, *later*, and at a *worse* entry
> than a sector-day drawn at random from the same panel.
>
> This does not falsify §16's thesis — that VN money flow leads public
> coverage by ~1 month. It falsifies **this implementation** of it. The one
> result pointing back at the thesis is `foreign_streak`: persistence of net
> foreign buying is the only tested condition that beat the base rate
> (88% vs 83% breakout, 50% vs 23% at ≥10d, median lead 8 vs 4), and §18.5/21
> predicted exactly that on different grounds.
>
> **Operational consequence, effective now:** no `ACCUMULATE` sizing rule from
> §16.9 — 1.5× vol target, 2.5×ATR stop, 4 concurrent — should be trusted on
> the current gate. §16.11's warning said the "gốc" claim was *not yet earned*;
> the base rate says the signal is not yet a signal. Treat live `ACCUMULATE`
> output as a watchlist, not an instruction, until a variant beats NO GATE
> within-year.

### 16.15 The breakout bar was 1.15%, not 8% — 2026-08-24 (5)

> **2026-09-25 — the premise below is 5× off.** The "median daily ATR 0.57%"
> this section is built on came from `analysis/flow_aggregation.py`, which
> multiplied each constituent's ATR by `w = 1/n` and then divided the sum by n
> again. The basket's real daily ATR is ~2.7%; with it, `atr_scaled` ≈ 35% and
> is never reached. The unit argument (a daily ATR against a 40-session max)
> still stands; every number in the tables below must be re-measured after
> `scripts/repair_sector_data.py` recomputes `atr_pct` (review 2026-09-24
> §4.1/3, fixed the same day).

§25.10 suspected §16.4's `2 × atr_pct` of **scaling with the tape it measures**:
ATR rises in choppy markets, so the bar would rise exactly when the moves
clearing it shrink. `scripts/stealth_leadtime_experiment.py --breakout` now
scores four definitions so that could be tested rather than assumed.

**The suspicion was wrong.** Sector ATR barely moves across years — median
0.58 / 0.53 / 0.57 / 0.67% in 2023-26 — so `atr_now` (today's reading) and
`atr_baseline` (the sector's trailing 2y median, no feedback) produce
near-identical tables. The feedback is real in direction and negligible in size.

**The actual defect is units.** `atr_pct` is a **daily** range, median 0.57%, so
the bar is ~**1.15%**. Asking whether a **40-session forward maximum** ever
exceeded 1.15% is not a breakout test — it is a liveness test, and **83% of all
sector-days pass it**. Every §16.11 and §16.12 breakout number recorded so far
was measured against that.

`atr_scaled` = `2 × median ATR × √40` ≈ **7.2%** keeps §16.4's "two normal
moves" intent while being horizon-consistent (a random walk's expected maximum
grows with √n), stays sector-relative, and takes the trailing median so it has
no feedback.

| | events | breakout | ≥10d lead | med lead | med RC |
|---|---|---|---|---|---|
| NO GATE, old bar | 13,033 | 83% | 23% | 4 | 0.944 |
| **NO GATE, `atr_scaled`** | 13,048 | **43%** | **74%** | **17** | 0.944 |
| shipped §16.1, `atr_scaled` | 20 | 40% | 75% | 21 | 0.940 |
| cond2 → `foreign_streak ≥ 3` | 16 | **62%** | **90%** | **34** | 0.924 |

**§16.11's lead-time criterion does not survive this.** Under a real bar the
unconditional base rate already clears "≥10d on ≥60%" — 74%, median lead 17
sessions — which is not the system detecting anything, it is what "40 sessions
to move 7%" mechanically implies. The criterion was satisfiable by noise and was
never the right test. **Only the margin over NO GATE means anything**, which is
what §16.12 already said and this makes unavoidable.

What survives the change, unchanged: the shipped gate is still no better than no
gate (40% vs 43%), `foreign_streak` is still the only variant clearly ahead on
every axis, and **every variant still collapses in 2026** under every definition
(shipped 0% at ≥10d on n=6; `foreign_streak` 33% breakout / 0% at ≥10d on n=3).
So §25.9's "it is the tape" conclusion stands and §16.14's "no measurable edge"
verdict stands. The bar being wrong was a second, independent defect.

**Not shipped into the scanner.** `analysis/stealth.py` does not use a breakout
definition — this is a measurement bench only, and no live signal changes.
Root capture is untouched at ~0.94 either way, so no variant has earned the
"gốc" claim.

