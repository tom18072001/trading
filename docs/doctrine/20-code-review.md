# §20.1-20.2 — Code review 2026-08-22: defect trung tâm và 15 mục đã sửa

> Tách khỏi `CLAUDE.md` ngày 2026-09-16 để doctrine trở lại ngân sách context
> (135.718 B nạp lại **mỗi lượt**; ngân sách của `claude/CLAUDE.md` mẹ là 10 KB).
> **Nội dung dưới đây nguyên văn** — không tóm tắt, không sửa số, không sửa ngày.
> `CLAUDE.md` giữ lại: §20.3 (mục CÒN MỞ) và §20.4, và trỏ về file này.

### 20.1 The central defect

One causal chain ran through most of the P0s and started at one table,
`sector_flow_daily`. The 16:00 EOD job wrote rows **without** `close_idx`. The
only ingest path that writes `close_idx` (`services/fast_ingest.py`, reachable
solely from `POST /api/flow/ingest`) skipped any date that already had a row —
so the scheduler claimed each date first and permanently locked it in a
price-less state. `scripts/backfill_close_idx.py`, `scripts/fix_close_idx.py`
and the `STEALTH_SYNTHETIC_CLOSE` flag all exist only to paper over this.

Because `close_idx` feeds the ML target, stealth condition 5 and the entire
backtest P&L, every number the system surfaced rested on an untrustworthy
daily table.

### 20.2 Fixed in this pass

| Id | Fix | Files |
|---|---|---|
| P0-1 | `rollup_to_daily()` derives each row's date from the bar's own timestamp and refuses to stamp a stale bar as a new session | `services/sector_ingest_service.py` |
| P0-2 | The scheduled path now carries `close_idx` + `return_1d` through; `fast_ingest` upserts instead of skipping, so it can repair damaged dates | `sector_ingest_service.py`, `fast_ingest.py`, migration 11 |
| P0-3 | `SectorAggregate.basket_return` — the split-safe weighted mean of constituent returns. `close_idx` remains a raw price sum and must not be used for returns | `analysis/flow_aggregation.py` |
| P0-4 | Backtest replays published `sector_signals` by default (`strategy="signals"`), with `flow_z` and legacy `flow_raw` baselines for comparison; benchmark is VNINDEX per §11, labelled when it falls back. **Half-true until 2026-08-23** — see §23 | `services/backtest_service.py` |
| P0-6 | Purged/embargoed CV — embargo = horizon + 2 sessions (§18.3/13, was BLOCKER). Metrics replaced with `top1_excess_hit` (vs. median sector), `decile_monotonic` (§18.7) and `ndcg_at_3` | `models/rotation_ranker.py` |
| P1-2 | The mean-flow fallback is flagged `is_degraded` and announced loudly instead of shipping as "ranker-gated" | `rotation_ranker.py`, `sector_signal_service.py` |
| P1-5 | §16.9 ACCUMULATE cap (4) and 30-session auto-exit, §18.4/20 `TRADING_HALT` kill-switch, and `ALLOW_SHORT_SIGNALS` to retire the cash-leg short per §18.2/12 | `config.py`, `services/sector_signal_service.py` |
| P1-5b | **2026-08-23** — the kill-switch stops being env-only. `publish()` ORs `TRADING_HALT` with a runtime flag toggled from `/positions?tab=risk`, read once before the loop so a mid-run toggle cannot split a batch. The env var remains a hard override a browser cannot clear | `services/trading_state.py`, `api/routers/state.py`, `sector_signal_service.py` |
| P1-6 | `utils/clock.py` — one market-local definition of "today". `config.TIMEZONE` was declared and used nowhere | new module + call sites |
| P2-1 | `require_api_key` is wired to every router behind `API_REQUIRE_KEY`; the slowapi limiter is finally attached to the app; the inert `"https://*.ngrok-free.app"` CORS entries are gone | `api/main.py`, `config.py` |
| P3-1 | `AGENTS.md` reduced to a pointer — one source of truth again | `AGENTS.md` |
| P3-3 | `.env.example` regenerated from `config.py` | `.env.example` |
| P3-4 | `rollup_to_daily` no longer loads the whole `sector_flow_ts` table; `_stealth_sectors()` N+1 collapsed to one query | ingest + signal services |
| P3-5 | ruff config in `pyproject.toml`; 666 findings → 30, all of them real | `pyproject.toml` + call sites |

> **2026-08-24 — the "30" above is stale; the baseline is 66.** Measured, not
> re-broken: `F401` 14 · `E402` 11 · `B904` 8 · `B905` 5 · `S608` 5 · `E401` 4
> · `PERF401` 4, then a tail of ones and twos. The 30 was counted before
> several later features landed, and nobody re-measured it — which is the
> failure mode a hardcoded count in a document always has. Treat 66 as the
> number a change must not grow, and re-measure rather than trusting this line.
>
> **65 as of 2026-08-24 (12)** — three `F841` dead locals in
> `generate_report.py` (`sector_prior_dv`, never even written to;
> `sector_stats_map`; `flow_in_secs`) fell out of the `main()` wrap. They were
> not new: ruff analyses function scope properly and module scope barely, so
> moving the body inside a function is what made them visible. That is worth
> knowing before the next count moves — a refactor can raise this number without
> breaking anything, and lower it without fixing anything.

**Defaults chosen to preserve live behaviour:** `API_REQUIRE_KEY=0`,
`ALLOW_SHORT_SIGNALS=1`, `TRADING_HALT=0`. Nothing in the daily email changes
until you flip these. `MAX_ACCUMULATE_SECTORS=4` and the 30-session release
DO change behaviour — they implement §16.9, which was never enforced.


---

## §20.3 — bản gốc, gồm cả 4 mục ĐÃ ĐÓNG

> `CLAUDE.md` §20.3 chỉ giữ 3 mục **còn mở** (P1-3, P2-2, P2-3) và một dòng
> liệt kê các mục đã đóng. Chi tiết từng mục đã đóng — số đo, commit, lý do —
> ở đây.

### 20.3 Still open — needs a decision, not just code

| Id | Question |
|---|---|
| ~~P0-5~~ | **CLOSED 2026-08-23** — `foreign_net` was backfilled by commit `b4d1d90`. Measured: **12,616 / 13,470 rows non-zero**, spanning 2023-03-13 → 2026-08-21; `foreign_hit_20d` spans 0.0 → 1.0 with 2,742 rows clearing the §16.1 0.6 threshold. The three `FEATURE_COLS` entries are no longer constant. **Consequence nobody logged at the time:** `analysis/stealth.py` drops cond2 whenever `foreign_net` is all-zero, so the backfill silently took the stealth gate from 3 evaluable conditions to 5 — a behaviour change that arrived as a side effect of a data change. That asymmetry is now explicit in the code (numerator *and* denominator) and pinned by `test_unevaluable_condition_does_not_raise_the_bar`. |
| ~~P1-1~~ | **CLOSED 2026-08-23**, in the direction of neither number. Doctrine said N=5 / bottom 40%, `analysis/stealth.py` shipped N=3 / bottom 60% — but under a five-way AND **both give zero sectors over 3.5 years**, so the disagreement was never worth what it cost to argue about. §16.1 is a score now; the scanner, `api/routers/stealth.py` and the UI presets read the same two knobs. |
| P1-3 | Breadth over 5 names takes 6 discrete values (§18.1/6, still open). |
| ~~P1-4~~ | **CLOSED 2026-08-24** (§25.3). The published label is the filtered posterior of the last bar — `predict_proba(X[:t+1])[-1]`, which has no future to smooth over — so it no longer changes with hindsight. Found while chasing a different symptom: confidence pinned at 1.0. The back-painting was the *third* defect in that chain; the first was a collapsed fit that made the posterior 1.0 by construction. |
| P2-2 | Two rate-limit buckets in one process: `utils/vnstock_gate` and `picks_universe_service._kbs_throttle`. `/insight/refresh` takes no `job_lock` at all, so a UI refresh overlapping the intraday job runs at 2× the KBS ceiling. |
| P2-3 | The "intraday" job fetches `interval="1D"` and re-downloads 120 days every 15 minutes (~3,750 calls/day against an 18/min gate). Either fetch real 15m bars or admit it is an EOD pipeline and fix §4/§8. |
| ~~P3-2~~ | **CLOSED 2026-08-24.** `import generate_report` is inert: 113 module-level statements → 4, everything else inside `main(argv=None)`. `services/report/` took the genuinely pure pieces — chart builders, the six SQL reads (which now take the cursor as an argument instead of closing over a module global, the actual reason nothing could be tested) and the two formatters. **The HTML weave deliberately did not move**: ~700 lines of `X = build_x()` where each builder reads several others' globals is a rewrite, not an extraction, and the harm was `import` sending mail — which is fixed. `ponytail:` in `services/report/__init__.py` names the trigger for finishing it (a second output format). `/api/state/report/send` still shells out; it no longer has to, and that is its own commit. |

