# §25 — Regime confidence: model sập báo cáo sự chắc chắn

> Tách khỏi `CLAUDE.md` ngày 2026-09-16 để doctrine trở lại ngân sách context
> (135.718 B nạp lại **mỗi lượt**; ngân sách của `claude/CLAUDE.md` mẹ là 10 KB).
> **Nội dung dưới đây nguyên văn** — không tóm tắt, không sửa số, không sửa ngày.
> `CLAUDE.md` giữ lại: định nghĩa confidence đang dùng, hướng hedge, và §25.10 còn mở, và trỏ về file này.

## 25. Regime confidence — a collapsed model reporting certainty — 2026-08-24

Tom: *"do tin cay cua thi truong luon la 100% la sai"*. Correct, and the
reported symptom was the **third** defect in the chain, not the first.

### 25.1 What was actually wrong

| # | defect | consequence |
|---|---|---|
| 1 | features fed **raw** to a diagonal Gaussian HMM | 3 of 4 states blew up to hmmlearn's ceiling covariance (1000); all 111 bars landed in the survivor |
| 2 | **180 days** of history (~111 bars) for a 40-parameter model | fitted inside a single regime — a regime model that has never seen a regime change |
| 3 | `confidence` = the **state posterior** | answers "which state is this bar in", not "is this call worth acting on" |

Defect 1 is why the number was 1.0: **with one live state the posterior is 1.0
by construction.** The model was not confident, it was degenerate. Feature
scales differ ~6× (5d return sd 0.028 vs 20d vol sd 0.005) and diagonal
Gaussian EM is not scale-invariant — the wide column dominates the likelihood,
the narrow states never win an observation, their covariances run to the
ceiling. Standardising gives occupancy `[154 177 470 251]`, max covariance 2.7.

History is now 1500 days (~1050 bars, back to 2022). `fit()` **refuses** a
collapsed fit (>1 empty state) and falls back rather than publishing its 1.0.

### 25.2 The formula

Even with 1 and 2 fixed, the state posterior sits at ~0.95 — a Gaussian HMM is
near-certain which state a bar is in whenever the states separate at all. That
is a property of the fit, not a reason to size a position. Meanwhile the label
flipped 26 times in 260 sessions.

`confidence` now means **P(this label still holds in `CONF_HORIZON` = 5
sessions)** — the filtered posterior propagated through the transition matrix,
summed over every state sharing the label.

| | value |
|---|---|
| range over 300 sessions | 0.46 – 0.91 (was: 0.9999998 on nearly every row) |
| mean predicted | 0.69 |
| mean realised (label actually held) | 0.60 |
| live 2026-08-24 | `risk_on 0.6472` |

Calibration by bucket: `[0.55,0.70)` predicted 0.64 / actual 0.63,
`[0.70,0.85)` 0.81 / 0.79 — good in the middle. **The top bucket is
overconfident: 0.90 predicted, 0.70 actual.** Read >0.85 as "likely", not
"certain". Isotonic calibration would fix it and needs more than 300 sessions
to fit honestly.

> **2026-08-24 (3) — that last paragraph was measured on too short a window and
> is wrong.** Re-run over the full 900 walk-forward bars
> (`scripts/regime_horizon_experiment.py`), the top bucket is fine — 0.895
> predicted vs **0.906** realised, n=406 — and the *bottom* is the biased end:
> below 0.55 it predicts 0.487 against a realised **0.370**. That gap widens the
> nearer you get to today (+0.012 early, +0.110 mid, +0.243 late), which is what
> the 300-bar window was actually seeing: it put the whole degrading stretch
> under a magnifying glass and read a **period**-specific miss as a **level**-
> specific one. The lesson generalises past this number: a calibration curve
> fitted on the most recent slice of a non-stationary series measures the slice.
>
> Direction matters more than size here. A low reading **overstates** survival,
> so "50%" means less than half — a reader who trusts it sizes on a call that
> holds ~37% of the time. The hedge in `confidence_phrase()` moved accordingly:
> it fires below 0.55 and points downward. The high end carries none.
>
> **And no calibrator ships.** Isotonic and Platt were both fitted walk-forward
> (train on the past, score the next 100 bars) against raw: raw wins the mean
> Brier — 0.1464 vs 0.1540 isotonic, 0.1479 Platt — and each method wins some
> folds. A calibrator that loses out of sample is a fitted layer that costs
> money. The mitigation stays a sentence, on purpose.

### 25.3 Filtered, not smoothed — this closes §20.3 P1-4

P1-4: *"Regime labels are back-painted — Viterbi re-decodes the whole history
each run, so yesterday's label can change. Use the filtered posterior for the
last bar."*

`predict_proba` over the whole panel is forward-backward, so it re-decodes
history with hindsight. The last bar of a **prefix** has no future to smooth
over, so `predict_proba(X[:t+1])[-1]` *is* the filtered posterior — using
public API only (hmmlearn 0.3.3 has no `_do_forward_pass`).

### 25.4 The heuristic fallback was lying too

It returned hardcoded 0.6 / 0.6 / 0.5 / 0.5 — four made-up numbers wearing the
same field name as a measured one. It now reports the share of the last 10
sessions carrying the same label: the same question the HMM path answers,
measured directly, so the two are comparable.

This matters more than it looks: **`hmmlearn` was absent from the interpreter
running pytest** while production resolves `.venv` through `uv run`, where it is
installed. Every regime test before 2026-08-24 exercised the fallback while the
scheduled job ran the HMM.

### 25.5 A correction, and the narrower defect underneath it

Mid-investigation this session I claimed `config.DATA_SOURCE = KBS` answers
"VNINDEX" with ~1.79 and that this poisoned the classifier. **Both halves were
wrong.** Measured: KBS returns 1784.24 and VCI 1784.29 for the same day *when
given a date range*. And `classify_regime` overwrites `macro_df` with
`fetch_vnindex_daily()` before use, so `macro_anchors.vnindex` never reached the
classifier at all.

The real defect is narrower and still worth fixing. `MacroService._fetch_vnindex`
asked for `today..today`; one bad read on 2026-04-16 returned 1.82; and
`ingest_now`'s carry-forward — which **cannot distinguish a missing value from a
wrong one** — copied it into the next 613 of 623 rows. Fixed with a 10-day
window plus `VNINDEX_MIN_PLAUSIBLE = 200.0`, so a bad read returns None and
carry-forward keeps the last *good* value. The 613 existing rows are left as-is
and marked `ponytail:`: nothing reads that column, so a backfill would be
tidying, not repair.

### 25.6 The wording — closed 2026-08-24 (late)

The four stance strings in `generate_report.py` plus the banner and the plain
-text body rendered `"HMM confidence {:.2f}"`. After the rewrite they printed
0.65 instead of 1.00, which is the intended change and also the dangerous one:
the word "confidence" invites a reader to size on it, and the number is no
longer a confidence. It is P(this label survives 5 sessions).

`analysis.regime.confidence_phrase()` is the one renderer now — six call sites
across the banner, the memo and the email body:

```
was:  Tape đang risk-on (HMM confidence 0.65)
now:  Tape đang risk-on (~65% khả năng giữ 5 phiên tới)
```

**It lives in `analysis/regime.py`, not in the report generator**, and that
placement is the point: the sentence is a property of the formula, so whoever
changes what the number means owns the words describing it. It is also the only
way it could be tested — `generate_report.py` is 1,629 module-level lines that
send mail on `import` (§20.3 P3-2).

~~Above 0.85 the phrase appends a hedge.~~ **Below 0.55** — see §25.2's
correction. The direction is pinned by
`test_the_phrase_hedges_at_the_low_end_not_the_high_end`, which asserts the
*side* rather than the boundary, so putting it back on the high end fails a test
instead of shipping.

### 25.7 `CONF_HORIZON` — derived 2026-08-24 (3), and the pooled answer rejected

It was an assertion for months. `scripts/regime_horizon_experiment.py` walks the
filtered posterior over 900 bars and scores every horizon by Brier skill against
a base-rate forecast.

Pooled, skill rises to a flat plateau at H=8-13 (+0.207…+0.212) and **H=13
wins**. Split in thirds it does not:

| H | early | mid | late (2025-06 → 2026-08) |
|---|---|---|---|
| 5 | +0.223 | +0.229 | **+0.060** |
| 8 | +0.262 | +0.224 | −0.003 |
| 13 | +0.172 | +0.297 | −0.020 |
| 20 | +0.161 | +0.298 | **−0.166** (AUC 0.510 — a coin) |

The entire H≥8 advantage comes from the middle stretch. **5 is the only horizon
positive in all three thirds**, so it stays — not because it is optimal, but
because it is the longest horizon that has not been shown to break. Same
methodological point as §16.12: pooling let one strong stretch mask a recent one
that matches random.

AUC is ~0.80 across H=1-13 and carries no opinion — it ranks, it does not
calibrate, which is why skill is the deciding metric here.

### 25.9 The late-third degradation — diagnosed 2026-08-24 (4)

§25.8 flagged it as the highest-value open question: the horizon sweep here and
the §16.1 stealth gate (§16.13) both fall apart over the same recent stretch,
and *"a defect common to two unrelated models is more likely the tape or the
data than either model."* `scripts/late_period_diagnosis.py` runs the four
checks. Result: **it is the tape, and the calendar was a proxy for it.**

**Not data.** Every 2026 quarter carries 15 sectors, ~0 missing `close_idx`,
96-100% non-zero `foreign_net`. Coverage matches the years that work. The one
thin quarter in the panel is 2023Q1 (36% missing closes), at the opposite end.

**Not a stale transition matrix.** `transmat_` is fitted once over the whole
panel, so it encodes average persistence — a plausible reason the late third
overpredicts survival by +9.3pt (0.695 predicted vs 0.602 realised). Testing it
by re-estimating transitions on a trailing window, emissions untouched:

| window | late bias | late Brier | late AUC | Brier, all 900 |
|---|---|---|---|---|
| whole panel (shipped) | **+0.093** | 0.2266 | **0.678** | **0.1607** |
| 250 bars | −0.045 | 0.2196 | 0.665 | 0.1916 |
| 500 bars | **+0.018** | 0.2289 | 0.637 | 0.1887 |
| 120 bars | −0.103 | 0.2615 | 0.583 | 0.2118 |

A trailing window fixes the *bias* and costs *discrimination* and overall Brier.
So the late failure is not miscalibration that a fresher matrix repairs — it is
**lost discrimination**: late AUC 0.673 against 0.816/0.828 earlier. Nothing
ships from this check; it is recorded so nobody re-runs it hoping.

**It is volatility.** Bucketing all 900 bars by 20d VNINDEX vol, ignoring date:

| vol tercile | n | base rate | AUC | share of rows in the late third |
|---|---|---|---|---|
| low | 298 | 0.836 | **0.827** | 0.12 |
| mid | 298 | 0.735 | 0.790 | 0.46 |
| high | 299 | 0.592 | **0.694** | 0.42 |

Monotone, and the high-vol bucket is spread across periods rather than being a
relabelling of "late". Crossed both ways, low-vol *late* bars still score 0.699
while high-vol *early* bars score 0.619 — vol tracks the failure, the calendar
does not. 2026 is simply where the high-vol bars concentrate (§16.13's amended
table: ann vol 0.42 vs 0.21-0.29).

**What this means, stated so it is not over-read.** A regime model is least
certain when regimes are least stable, which is not a defect — it is the
model reporting a harder problem. The honest response is to let confidence fall
in choppy tape, which it does. But it means:

- **`CONF_HORIZON` is not one number.** 5 is the longest horizon positive in all
  three thirds *pooled across vol*; in the high-vol bucket even 5 is marginal.
  A vol-conditioned horizon is the obvious next experiment and is **not** shipped
  — it needs its own walk-forward, and §25.2 is the standing warning about
  fitting a layer on a recent slice.
- **§16's story is different from this one.** The stealth gate's 2026 collapse
  shares a cause *class* (the tape) but not the mechanism: §16.13's breakout
  test is pinned to 2×ATR, so a rising ATR raises the bar exactly when the moves
  it must clear are shrinking. That is a definition that moves with what it
  measures — a real defect in the metric, worth fixing on its own terms, and it
  is not fixed by anything here.

### 25.10 Open
- **A vol-conditioned `CONF_HORIZON`** (§25.9). Measured as needed, not shipped.
- ~~**§16.13's 2×ATR breakout definition scales with the tape it measures.**~~
  **Measured 2026-08-24 (5) — the suspicion was wrong and the real defect is
  worse. See §16.15.**
- `CONF_HORIZON` should be re-measured when the panel grows; 900 bars split
  three ways is 300 per cell, and §25.9 now wants it split by vol as well.

### 25.11 The calibration was in sample — 2026-09-25

Review 2026-09-24 §4.1/7 replayed the label the way it is published — refit
weekly on the history available that day, filtered posterior, VNINDEX from the
price panel — instead of scoring one fit over the whole panel, which is what
§25.2-25.9 measured:

- "holds 5 sessions" read **0.69-0.85**; the label held **0.28-0.58**;
- Brier skill against the base rate: **−0.94 / −0.42 / −0.24 / −0.05** by year —
  negative every year;
- the label changed **33.8 times per 250 sessions**; the worst 10% of refits
  re-labelled 93% of history;
- after a `risk_on` day VNINDEX's next 20 sessions were **1.55% worse** than
  after other days (t −1.7) — long `risk_on` / short `risk_off` loses.

So the §25.2 finding "the high end needs no hedge" holds only in sample.
Shipped: `confidence_phrase()` ends every reading with "chưa kiểm chứng ngoài
mẫu" (the low-end hedge stays — it points the right way), the label is on the
`analysis/verification.py` list, and every surface that printed a regime
instruction ("size full weight", "no new BUYs", "Tư thế tấn công") prints the
note instead. `classify_regime()` no longer falls back to the hourly
`macro_anchors` rows: 2026-09-22's `risk_off 0.9961` was fitted on 1.82s.

Scripts and numbers: `docs/reviews/ALGO_REVIEW_2026-09-24.md` §4,
`docs/reviews/algo_review_2026-09-24/`.

