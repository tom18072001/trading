# §19 — Lịch sử test: vì sao từng bài test tồn tại

> Tách khỏi `CLAUDE.md` ngày 2026-09-16 để doctrine trở lại ngân sách context
> (135.718 B nạp lại **mỗi lượt**; ngân sách của `claude/CLAUDE.md` mẹ là 10 KB).
> **Nội dung dưới đây nguyên văn** — không tóm tắt, không sửa số, không sửa ngày.
> `CLAUDE.md` giữ lại: bảng đếm + 2 lệnh chạy, và trỏ về file này.


> 2026-09-16 (2): +7 in `tests/test_picks_ranking.py`, backend **370** — the
> cross-sectional ordering pass (§26.9). One of them was written wrong on
> purpose-adjacent grounds and that is how it earned its keep:
> `test_a_50_50_blend_can_tie_the_best_score_with_the_worst` first asserted
> that a top score must outrank a bottom one whatever the flow, went red,
> and revealed that a 50/50 rank blend ties them exactly. The assertion was
> inverted to pin the real property, and
> `test_flow_cannot_rescue_a_name_the_score_gate_rejects` was added to pin
> the guard that makes the tie safe. The two must be read together.
>
> `test_the_bench_ordering_is_the_shipped_function` asserts on the bench
> factor's SOURCE, which is crude, but a vectorised copy that happens to
> agree on a three-name fixture is exactly the drift 22.11 logged, and an
> output comparison would not catch it.
>
> 2026-09-16: +15 net, backend 363 — the scoring rewrite (§26).
> `tests/test_picks_scoring.py` was rewritten rather than extended: five of its
> tests asserted exact integers produced by the rule that was replaced, so they
> were not coverage of the new one. `tests/test_picks_ranking.py` (+9) pins the
> two things that can regress independently — the bench and the service
> computing the same number, and the tie-break not being dollar volume again.
> `tests/test_picks_universe_service.py` (+2) covers the all-zero `foreign_room`
> guard (§26.5).
>
> **Two of these exist because a negative control caught a test of mine proving
> nothing.** `test_the_bench_and_the_service_agree_row_by_row` was green with
> the ATR penalty *deleted from the bench*, because the fixture's daily sigma
> put every bar under `WIDE_ATR_PCT` — so the term under test was never
> reached. A third, deliberately wild name fixed it, and
> `test_the_fixture_actually_reaches_every_term_it_claims_to_test` now asserts
> the fixture still straddles both the trend gate and the ATR threshold. That
> guard has now earned its place twice: an earlier draft had both fixture names
> drifting into uptrends, so the gate was never blocked either. Same lesson as
> §22.11's open-run test — a fixture that never reaches a branch cannot test it,
> and the suite reports coverage it does not have.
>
> `test_a_negative_score_is_never_offered_as_a_top_buy` came from the first live
> rebuild rather than from reasoning: `_select_top` filtered on `is_valid_buy`
> alone, which is about stop/target geometry, so the page padded itself to five
> with names scoring −0.65 and −0.77. Invisible under the old 0..7 score, which
> could not go negative.

> 2026-08-26: +3 in `tests/test_database_schema.py`, backend **348** — migration
> 12, dropping two tables that never had a writer. The load-bearing one is
> `test_the_drop_survives_a_restart`, and it earns its place by exercising the
> real startup sequence (`create_all` → `run_migrations`, **twice**) rather than
> inspecting `Base.metadata`. That distinction is not academic: the failure it
> guards fired live during this change — the negative control briefly reinstated
> the two ORM classes, `uvicorn --reload` picked the edit up, `init_db()` ran,
> and both tables came back *after* migration 12 had recorded itself as applied.
> A metadata-only assertion would have stayed green through that.
>
> 2026-08-25: +3 in `tests/test_stealth_history.py`, backend **345**. All three
> are on `/api/sectors/stealth`, and none of them could have been written the
> day before: the `/api/stealth/*` routes opened `SessionLocal()` inside the
> handler, so a test could not give them a panel. Taking
> `get_session_dependency` is what turned "assert the Query defaults" into
> "assert the answer".
>
> The load-bearing one is
> `test_both_stealth_endpoints_derive_the_same_events`, and it compares the
> **event list**, not the count — a route that finds the right *number* of the
> wrong runs is the failure worth catching. Negative control: reverting
> `history` to `[]` fails exactly these 3.
>
> 2026-08-24 (13): +14 in `tests/test_stealth_history.py` — `stealth_events()`,
> behind `/api/stealth/history` (§22.11). Backend **342**.
>
> The one carrying the feature is
> `test_a_long_open_run_is_not_scored_even_though_it_could_be`, and it exists
> because its first draft did not work. That draft used a 3-session run at the
> panel edge, which has no forward bars — so `judgeable` was already False and
> the test passed against code with the `still_running` guard **deleted**. A
> negative control caught it: removing the guard left all 13 green. The
> replacement uses a 25-session open run that has 24 forward bars and clears the
> breakout bar, so only `still_running` keeps it unscored, and it goes red
> without it. General lesson, worth more than the test: a guard test whose
> fixture also trips an *earlier* guard measures the earlier one.
>
> `test_the_bench_and_the_endpoint_share_one_breakout_definition` asserts
> `bench._bar_atr_scaled is S.breakout_bar_scaled` — identity, not equal output,
> because two copies that agree today are still two copies.
>
> The fixture pads 60 quiet sessions in front of every panel. Without them
> `breakout_bar_baseline` falls short of its 20 ATR observations and silently
> returns the 0.02 default, so the tests would score against a bar production
> never uses.
>
> 2026-08-24 (12): +11, and one of them found a live production defect.
> `tests/test_report_import.py` (+8) pins that `import generate_report` sends no
> mail, opens no DB and writes no file — the property the §20.3 P3-2 split
> exists for. Three of those are behavioural and one is structural
> (`test_the_work_lives_inside_main_not_at_module_level`), because the first
> three can pass by luck and the last cannot: measured against the pre-split
> file it is 113 module-level statements versus 4, so the `< 40` threshold
> discriminates. `smtplib.SMTP` is replaced with a raising bomb rather than a
> recording mock — a mock lets the import finish and reports afterwards, which
> is exactly the behaviour that shipped for months.
>
> `tests/test_model_artifacts.py` (+3) guards something worse and unrelated to
> the refactor: **running pytest overwrote the production ranker.**
> `RotationRanker.fit()` writes `rotation_ranker.pkl` to
> `config.SAVED_MODELS_DIR` unconditionally, six tests call it with 2-3
> synthetic features, and `models/saved/` is gitignored — so the 17:00 publish
> job died with *"number of features in data (19) is not the same as it was in
> training data (3)"*, `git status` was clean, and no test failed. A silent
> suite that breaks production is the worst shape a defect can take.
> `tests/conftest.py::_models_go_to_a_tmpdir` is autouse for the reason an
> opt-in fixture would fail: the tests that forget to ask are the dangerous
> ones. Verified by negative control — de-autousing it fails 2 of the 3 guards
> (and re-broke the live model, which is the bug reproducing itself).
>
> 2026-08-24 (9): +13. `tests/test_position_track.py` — stop/target on the book
> and the price path since entry (§22.10). The two that carry the feature are
> `test_stop_and_target_survive_the_round_trip` (the defect itself: both numbers
> were destroyed at the mark) and
> `test_hit_stop_is_ever_touched_not_just_today`. Its mirror,
> `test_a_breach_before_entry_is_not_your_breach`, is what stops the fix
> over-firing on the 30-session tail that predates the trade.
> `test_sellable_on_skips_holidays_too` pins the reason `next_trading_day`
> exists at all rather than `setDate(+2)`.
>
> One fixture detail is the test: `_bars()` keys the date as `"time"`, because
> that is what `picks_universe_service` writes and `generate_report.py:164` has
> to rename. A test that used `"date"` would pass against code that never
> matches a real bar.
>
> 2026-08-24 (3): +19. `tests/test_position_close.py` (+17) and two more in
> `test_regime_confidence.py`.
>
> The load-bearing one is `test_a_close_is_not_a_delete`: closing must *leave
> evidence*. Until `close_position()` existed the only verb was
> `remove_position()`, so a sale and a mis-click were the same operation and the
> book could never answer whether the picks made money.
> `test_costs_can_turn_a_small_win_into_a_loss` is the reason the §18.2/10
> figures are imported rather than retyped — a +0.20% gross scalp is a loss net
> of a ~0.40% round trip, and a book that disagrees with the backtest about that
> is worse than no book. `test_a_break_even_book_reports_zero_not_none` guards a
> `sum(...) or None` that would have erased an exactly-flat book, and
> `test_an_old_state_file_without_closed_still_loads` pins the reason this
> needed no migration.
>
> 2026-08-24 (2): +26. `tests/test_regime_confidence.py` (+13) and
> `tests/test_position_edit.py` (+13).
>
> Three of the regime tests guard *wording*, not arithmetic, which is unusual
> enough to justify: `confidence_phrase()` is the only reader-facing sentence
> that says what the number means, and the four strings it replaced said "HMM
> confidence 1.00" for months. `test_the_phrase_hedges_at_the_low_end_not_the_
> high_end` pins the *direction* of the hedge — it first sat above 0.85 on a
> 300-bar measurement that turned out to be a period artefact (§25.2), so
> asserting the direction is what stops that regressing quietly.
>
> **`hmmlearn` was missing from the interpreter that runs pytest**, while
> production runs through `uv run` and resolves `.venv`, where it is installed.
> So every regime test before this date exercised the heuristic fallback while
> the scheduled job ran the HMM — a suite agreeing with itself about a code path
> nobody ships. Installed now; the HMM tests `skipif` rather than silently pass
> when it is absent.
>
> The load-bearing regime test is
> `test_fit_does_not_collapse_on_a_real_length_panel`, which pins the *cause*
> (three of four states at hmmlearn's ceiling covariance) rather than the
> symptom Tom reported (confidence stuck at 1.0) — the symptom is a consequence
> and a future refactor could reproduce it a different way. The fixture is a
> deliberate two-regime path: a single-regime random walk is exactly the input
> that collapsed in production, so it cannot tell a working model from a broken
> one.
>
> On the book: `test_edit_does_not_restamp_the_open_date` is the one carrying
> the feature — it is the whole reason `update_position` exists separately from
> `add_position`. `test_pnl_route_is_not_shadowed_by_the_symbol_route` guards
> FastAPI route ordering: `/positions/pnl` and `/positions/{symbol}` share a
> prefix, and if the literal ever loses you get a position named "pnl".

> 2026-08-23 (late, 6): +14 in `tests/test_stealth_gate.py` — §16.1 after it
> stopped being a conjunction. The load-bearing one is
> `test_four_of_five_fires_where_all_five_cannot`: a panel that clears four
> conditions and never the fifth must produce an event, which the old gate
> could not. `test_unevaluable_condition_does_not_raise_the_bar` guards the
> numerator/denominator symmetry — the bug that let an all-zero `foreign_net`
> column silently ship a 3-condition gate while the doctrine said 5. Two more
> pin the endpoint to the scanner: that `/api/stealth/active`'s Query defaults
> come from `analysis.stealth`'s constants rather than being retyped, and that
> its cond4 ranks ATR instead of comparing a raw 0.006 fraction to 0.5.
>
> The fixture is deterministic on purpose: flat flow gives sd=0 → z is NaN → c1
> is reliably False, and a *ramp* (not a step) is what holds z above +1, since
> a step's z decays to 0 once the 20d mean catches up. An earlier `rng.normal`
> version produced random z-spikes that made the cold case fire intermittently.

> 2026-08-23 (late, 5): +11 in `tests/test_report_runner.py` — the "Gửi báo cáo
> ngay" button. One test carries the feature:
> `test_second_click_does_not_start_a_second_run` — two clicks must send one
> email, and the button being disabled is cosmetic, the backend is the guard.
> The rest pin argv construction (`--no-email`, the date), rejection of a
> malformed `report_date` **before** anything runs, and that a timeout lands in
> the status instead of killing the daemon thread silently. No subprocess is
> spawned: `send_report(runner=…)` takes the runner as a parameter for this.

> 2026-08-23 (late, 4): +13 in `tests/test_backtest_controls.py` — the backtest
> controls the UI can now reach. Two of them are the interesting ones:
> `test_flow_z_is_not_the_same_strategy_as_flow_raw` (a +2.5σ small sector must
> be reachable by `flow_z` and unreachable by `flow_raw`) and
> `test_cross_sectional_z_preserves_raw_order`, which pins the *proof* that the
> old cross-sectional z was an order-preserving affine map. The rest guard the
> benchmark curve, cost-override clamping (a negative fee must not pay the
> trader), the `Literal` strategy validation (422 on a typo, which used to fall
> through to `flow_raw`) and the `trade_log` row shape the TS type claims.

> 2026-08-23 (late): +13 in `tests/test_trading_state.py` — the operator store
> behind the kill-switch, the position book and the watchlist. The guards that
> matter: a corrupt file must not take the API down, the `TRADING_HALT` env
> override must not be clearable from a browser, marking the same pick twice
> must update rather than duplicate, and — the point of the whole feature — a
> flag set from the browser must reach `SectorSignalService.publish()` and make
> it emit all-HOLD.

> 2026-08-23: +6 in `tests/test_picks_universe_service.py` — the disk-snapshot
> round-trip (identity between `by_sector` and `tickers` preserved), cold-cache
> load from disk, the stale-vs-latest-signal-date flag, and the two degrade
> paths (corrupt file, missing file) that must return `None` rather than raise.
> An empty build is not persisted.

> 2026-08-22: +28 in `tests/test_review_20260822.py`, one guard per finding in
> `docs/reviews/CODE_REVIEW_2026-08-22.md`. The 105 figure above also counted ~9 one-line
> placeholder files under `tests/test_api/`, `tests/test_services/` and
> `tests/test_database/` that contain only "Legacy test removed in sector
> redesign" — real backend coverage before this review was ~101.

Backend modules covered:
- `config.py`, `database/models.py` schema (21 pre-existing).
- `services/picks_scoring.py` — 20 tests (NVL-style regression guard, SWING/TPLUS profiles, is_valid_long_pick parametric matrix).
- `services/picks_universe_service.py` — 14 tests (classification priority, cache lifecycle, degraded-mode fallback). vnstock calls mocked.
- `services/trader_agent.py` — 23 tests (JSON parse variants incl. `<think>` stripping, prompt trimming, cache invalidation, provider routing for local/glm/claude, missing-key guard, local connect-error message, timeout guard). No live LLM call — the local transport is faked at `httpx.AsyncClient`.
- `services/insight_refresh.py` — 5 tests (happy path, idempotent start while running, error propagation, stale run_id lookup, worker-thread progress plumbing). Uses an injected fake pipeline; no KBS / Claude / DB.
- `api/routers/insight.py` refresh endpoints — 3 tests via FastAPI `TestClient` (POST returns run_id; polling completes with payload; second click while running returns same run_id + already_running).
- `services/unified_picks.py` — 10 tests (NEW 2026-04-23). Anchors the SecV5 union-merge rule: consensus sort to top with `source=BOTH`; empty ranker → fallback to pure DAILY_INSIGHT (regression guard for the SecV4 silent-ranker bug); input lists not mutated; extra fields flow through; missing-score sort tiebreaker. Pure; no DB / vnstock / Claude dependencies.

Frontend modules covered:
- `pages/DailyInsightPage.tsx` — `fmtNum`, `fmtPct`, `AgentReport`, `PickGroup`, `PickCard` (valid + fallback + news toggle + SELL variant).

Test runners:
- Backend: pytest 9.x, anyio plugin. No network access required (mocked).
- Frontend: vitest 4.x + @testing-library/react + jsdom + @testing-library/jest-dom.

Live integration (not in pytest): `POST /api/insight/refresh` — exercises vnstock KBS + Claude Agent SDK end-to-end; run manually after meaningful changes to those paths. Since 2026-04-20 this endpoint is async: it returns a `run_id` immediately and the UI polls `GET /api/insight/refresh/status` for stage + progress. See `specs/daily-insight.md` §4.5 for the full contract.



