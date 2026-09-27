# §22 — Audit frontend 2026-08-23

> Tách khỏi `CLAUDE.md` ngày 2026-09-16 để doctrine trở lại ngân sách context
> (135.718 B nạp lại **mỗi lượt**; ngân sách của `claude/CLAUDE.md` mẹ là 10 KB).
> **Nội dung dưới đây nguyên văn** — không tóm tắt, không sửa số, không sửa ngày.
> `CLAUDE.md` giữ lại: kết luận đang có hiệu lực của §22.1-22.11, và trỏ về file này.

## 22. Frontend flow audit — 2026-08-23

Every route and every endpoint behind it was exercised against the running
server. Full numbers in the **Sector Flow Bench** artifact.

### 22.1 Flows that render nothing
These return HTTP 200 with an empty collection, so the page draws an empty
state. They are not broken code — they are correct code with no data:

| surface | endpoint | why it is empty |
|---|---|---|
| Stealth Watch | `/api/stealth/active` | `accumulation_age` is 0 on all 13k rows; §16 has never fired — **cause corrected 2026-08-23**: not missing data, an unreachable AND gate (§16.1). 53 rows are non-zero now. |
| ~~Stealth Watch history~~ | ~~`/api/stealth/history`~~ | **Misdiagnosed, fixed 2026-08-24** — it was not empty *data*, it was a hardcoded `return {"rows": []}`, the same defect as Flow Pulse below. Now derives runs from `sector_flow_daily.accumulation_age`: **21 events, 20 scored, 40% hit, median lead 21 sessions**. See §22.11. |
| Rotation Map | `/api/rotation/pairs` | ~~no pair clears the 1.5 threshold~~ — **wrong, corrected below** |
| Flow Pulse | `/api/pulse/exposure` | ~~no positions are tracked~~ — **wrong, corrected below** |

Fixing Stealth Watch means fixing §16 (see §20.3), not the UI — which is what
§16.1's 2026-08-23 amendment did. The other two
rows were **misdiagnosed**; both were fixed on 2026-08-23:

- **Rotation Map** was not threshold-limited, it was structurally empty.
  `rotation.py` builds `pairs` as the cartesian product of
  `delta < -threshold*sigma` × `delta > +threshold*sigma`, and a live probe
  returned 10 nodes **all on the target side**. The product is therefore empty
  at *every* threshold — lowering it widens both sets from the same one-sided
  `delta`. The page now reads `/api/sectors/handoff`, which computes the same
  thing correctly (`max(0, -Δz_A) * max(0, +Δz_B)`; the independent clip per
  side is what keeps both sides non-empty) and had 270 rows and no consumer.
  `/api/rotation/*` stays mounted, unread.
- **Flow Pulse** exposure was not "no positions" — `api/routers/pulse.py`
  returns a hardcoded `{"rows": []}` while the real implementation sits in
  `sectors_risk.py`. The client now calls `/api/sectors/risk/exposure`.

### 22.2 Client code pointing at deleted routes
`agentApi.briefing()` and `agentApi.stoplossAlerts()` called `/api/agent/*`,
which was removed from the backend on 2026-04-18 when OpenClaw was replaced by
`services.trader_agent`. Both returned 404 for four months. Removed, along with
`BriefingPage`, which was their only caller.

### 22.3 Performance
- `flowApi.series` and `flowApi.sector` hard-coded `lookback = 400` in the
  **client**, so lowering the backend default to 120 changed nothing until the
  client changed too. Now 120 both ends: **2.8 s / 1.0 MB → 1.3 s / 303 KB**.
  > **2026-08-23: this was only two-thirds true.** The client *default* and
  > `SectorDetailPage` were changed, but `FlowMonitorPage.tsx` passed an
  > explicit `400` that overrode the default, so the route users actually open
  > still shipped 1.0 MB. Fixed now — measured 1,000,870 B / 2.72 s →
  > 304,682 B / 1.61 s. The lesson: changing a default proves nothing until you
  > grep the call sites.
- Wiring the four pages eagerly took the main bundle from 372 kB to 732 kB,
  because `BacktestPage` imports recharts. They are `React.lazy` now: main
  bundle 376 kB, recharts in a 346 kB chunk that only loads when you open
  Backtest.

### 22.4 Dev server bound to every adapter
`vite.config.ts` had `host: true`, which binds 0.0.0.0 and advertises every
network adapter — including `172.20.16.1`, the Hyper-V vEthernet switch WSL and
Docker Desktop create, which nothing outside the machine can reach. Now
`host: 'localhost'`; use `npm run dev:lan` when you want it on the LAN. That is
also the safer default while `API_REQUIRE_KEY=0`: the Vite proxy fronts the
trading API, so putting the dev server on the LAN puts the API there too.

### 22.5 The frontend test suite was red, and §19 said it was green
8 of the 13 vitest tests failed with `TypeError: React.act is not a function`.
React 19.2 ships `act` only in its development build, and Vitest runs with
`NODE_ENV=test`, so Vite resolved React's production entry and
`@testing-library/react` fell back to the removed `react-dom/test-utils.act`.
Fixed in `vitest.config.ts` by asking the resolver for the `development`
condition. **13/13 pass now** — the count in §19 is finally true.

### 22.6 The homepage was empty after every restart — 2026-08-23
The defect the audit above missed, because it only shows up on a cold process.
`PicksUniverseService` kept its snapshot **only in memory**, so a backend
restart blanked Daily Insight until a human clicked Refresh. `/api/insight/daily`
deliberately does a cache-only `.peek()` (a cold `get_snapshot()` would hang the
endpoint for 2–10 minutes behind the 18 req/min KBS throttle), so the endpoint
was correct and the cache was the gap — it was the only stage of the daily
pipeline with no durable store. It now persists to
`data/snapshots/picks_universe.json` and reloads on a cold cache. The file is a
cache, not a source of truth: corrupt, missing or stale degrades to the existing
empty-state banner and never raises; a stale one is loaded anyway and flagged
through `freshness.errors`. See `MODIFICATION_LOG.md` 2026-08-23 (evening) A1.

### 22.7 Docs layout — 2026-08-23
Seven outdated documents were **deleted**, not archived (Tom's call: an archived
wrong doc is still a wrong doc someone will read). `README.md`'s email command
had been running a file deleted on 2026-06-18. What survives:

```
README.md · CLAUDE.md · ARCHITECTURE.md · MODIFICATION_LOG.md · AGENTS.md   ← root, entry points
docs/PATCHES.md         ← plan lifecycle: what is running, what is done (2026-08-24)
specs/                  ← one topic per file, referenced from 5 .py docstrings; untouched
docs/reference/         ← ALGORITHM.md, GLOSSARY_VI.md
docs/reviews/           ← the dated reviews (§21: dated records keep their names)
```

**No Python file moved.** `scripts/jobs/*.bat` invoke `main.py` from the repo
root under Task Scheduler, and `MODIFICATION_LOG.md` 2026-07-19 already records
one path move that left shortcuts pointing at a dead directory.

> **2026-08-24 (10) — the four documents now divide cleanly.** Tom asked for
> "một file update patch chung" and for the repo to say **what the current plan
> is**, which nothing did: a finished plan left a `MODIFICATION_LOG.md` entry
> and a `CLAUDE.md` section, and an *unfinished* one left nothing at all. So
> "what are we doing now" was only answerable by reading a plan file outside the
> repo, in `~/.claude/plans/`, which no reviewer or agent would ever find.
>
> | file | answers | shape |
> |---|---|---|
> | `CLAUDE.md` | what the system **must** be | doctrine, amended in place |
> | `ARCHITECTURE.md` | what the contracts **are** | layers + dated changelog |
> | `MODIFICATION_LOG.md` | what **changed**, and why | append-only, one entry per change |
> | `docs/PATCHES.md` | which plan is **running**, which is **done** | two tables, one line per plan |
>
> `PATCHES.md` deliberately holds **one line per plan** and points elsewhere for
> the reasoning. A patch index that grows into a second changelog is a second
> changelog, and two changelogs disagree — which is the exact failure §21 logged
> for versioned filenames and §20.4 logged for plan-vs-code drift.
>
> **The audit that came with it found the retired docs were mostly not retired.**
> Of 23 stale-looking matches, 19 are dated changelog entries in
> `ARCHITECTURE.md` / `CLAUDE.md` / `ALGORITHM.md` recording that OpenClaw *was*
> retired and the 170-symbol system *was* replaced — §21 protects those, and
> rewriting them would erase the record that the change happened. The genuinely
> wrong content was concentrated elsewhere and is fixed: two specs describing
> things that never shipped or shipped differently (`SPEC_INTRADAY_VNSTOCK.md`,
> `REDESIGN_PHASE15.md`), one spec carrying Ollama defaults dropped a day
> earlier (`trader_agent.md`), one spec naming an endpoint that was never built
> (`daily-insight.md` §4.4 `send-gmail`), and `GLOSSARY_VI.md`.
>
> **`GLOSSARY_VI.md` was the dangerous one**, because it is the file written for
> the person who is not reading the code. It still taught the 5/5 stealth gate
> (unreachable — §16.1), still defined `confidence` as "how sure the model is"
> (it is P(label survives 5 sessions) — §25.2), described the kill-switch as
> firing *automatically* after three sentinel hits (it is manual — §22.10), and
> said T+2.5 in calendar days (it is 2 *sessions*, holiday-aware). Every one of
> those would have led a reader to act. Corrected, each pointing at the section
> that governs it.


### 22.8 One design system, one action vocabulary — 2026-08-23
The four "Ra quyết định" pages were wired on 2026-08-23 (§12) but had never
been through the redesign, so they still shipped raw Tailwind while the five
"Theo dõi" pages used the `@theme` tokens. They are on the tokens now — class
swaps only, no new design.

The bigger fix is vocabulary. Three pages spoke three alphabets, and none was
the five-state enum §16.3 defines. `frontend/src/lib/actions.tsx` is now the
single source, and it separates two things that were being conflated:

| component | means | source | states |
|---|---|---|---|
| `ActionBadge` | what to do with money | `sector_signal_service.py` (§16.3) | ACCUMULATE · BUY · TRIM · SELL · HOLD |
| `FlowBadge` | what the tape is doing | `api/routers/flow.py:176`, from `flow_z` alone | HOT · COOL · NEUTRAL |

`FlowBadge` is styled flatter on purpose: a HOT tape is an observation, not an
instruction, and it must never read like a BUY. **TRIM is rendered but never
emitted** — the signal service has no path to it, so §16.3 is still four states
in practice. That is a doctrine-vs-code gap of the same family as P1-1.

### 22.9 Nav merged 9 → 5 — 2026-08-23
Nine nav doors for 15 sectors was more navigation than data, and every merge
below removes a context switch rather than a page. Nothing was deleted: every
pre-merge path redirects, including `/flow/:code`.

| nav | contains | why together |
|---|---|---|
| Daily Insight | (unchanged) | the screen you open every morning |
| Dòng tiền | Money Flow Monitor + Sector Detail | clicking a sector used to leave the page and drop your interval, `flow_z_hot` and chart selection |
| Luân chuyển | Stealth Watch + Rotation Map | one question, two phases — §16.1 accumulation (early) vs. the handoff that already happened |
| Rủi ro & Vị thế | Risk + Flow Pulse | also removes the last way the two exposure panels of §22.1/A4 could disagree |
| Nghiên cứu | Xếp hạng + Regime + Backtest | none of the three is a daily job |

Tabs live in the URL (`?tab=`, `components/Tabs.tsx`) with `replace: true` —
a merged page must keep the deep links its old routes had, and switching tabs
must not stack history entries.

`SectorDetailPage` was the last page still on raw Tailwind (37 `slate-*` hits
plus 20 hardcoded SVG hexes); it was tokenised in the same pass, so §22.8's
claim now holds for the whole app.

Daily Insight also gained a sticky jump bar: the buy/sell list — the thing
people open the page for — sat below the gauge, the spectrum and Minh's memo,
about two laptop screens down.

Bundle: main **376.43 → 371.12 kB**. `PositionsPage` (12.7 kB) and
`ResearchPage` (1.05 kB) are lazy, and recharts stays in its own 346 kB chunk
that only loads when you select the Backtest tab.

### 22.10 Operator state — kill-switch, book, watchlist — 2026-08-23

Everything on every page was model output. The app knew what it thought and
nothing about what Tom did, which showed up in four places at once:

| symptom | cause |
|---|---|
| stopping the 17:00 publish meant editing `.env` and restarting | §18.4/20's kill-switch was an env var |
| "Vị thế đang mở" on the Risk page was not your book | `current_exposure()` equal-weights today's BUY/SELL signals — model suggestions wearing a book's name |
| the "Vốn 50-500tr" slider reset to 100tr on every F5 | it only split weights; nothing stored it |
| eight of nine routes never said how old the data was | `FlowMonitorPage` was the only page fetching `/flow/freshness` |

`services/trading_state.py` is one JSON file (`data/trading_state.json`,
gitignored) with four keys — halt, capital, positions, watchlist — behind
`/api/state/*`. **Not a table on purpose:** three keys do not justify migration
12, and the scheduler process has no HTTP client, so it must read the halt flag
directly off disk. If a second machine or a second trader ever appears this
becomes a table and the read path becomes a query; the API shape above it does
not have to change.

The halt has **two sources, OR'd**. `TRADING_HALT` stays a hard override a
browser cannot clear; the runtime flag is what the UI toggles. `halt_env` and
`halt_effective` are returned so that asymmetry is visible rather than
surprising — the toggle disables itself, with a title saying why, when the env
var is the one holding the halt. `publish()` reads the answer **once before the
loop**, so toggling mid-run cannot publish half a batch.

The banner is app-wide and un-dismissable. A halt you can only see on the page
where you set it is a halt you will forget about, and forgetting it means
trading picks the 17:00 job has already stopped publishing. Below it sits a
data-age bar on the same principle: quiet when fresh, warn-coloured with the
session gap when behind.

`lib/tradingState.ts` is a `useSyncExternalStore` module store, not Context —
Layout would otherwise own state it never reads, and one object does not justify
a state library. Marking a pick is idempotent on `(symbol, side)` and drops the
symbol from the watchlist: you cannot be watching something you have bought.

The book stores no exit price, so there is no P&L yet. That is the next thing to
add if performance attribution is wanted — it is a deliberate stop, not an
oversight.

> **2026-08-24 — half of that is now done.** The book was a list, not a control:
> you could mark a pick but not correct the price, and the price it stamped is
> the *previous close*, which is almost never your fill. `PATCH
> /api/state/positions/{symbol}` edits entry price and quantity in place, and
> `GET /api/state/positions/pnl` marks the book against the picks snapshot.
>
> `update_position` is deliberately **not** `add_position`: that one restamps
> `opened_at` to today and drops the symbol from the watchlist, both wrong when
> you are fixing a typo. `None` means "leave this field alone", so clearing one
> takes an explicit negative — the alternative silently wipes `qty` on every
> price edit.
>
> The response carries `priced` and `count` separately, because a P&L over 1 of
> 3 rows is not the book's P&L, and the header says so when they differ.
> Unrealised only: **still no exit price**, so realised attribution remains the
> next thing to add.

> **2026-08-24 (3) — and now it is added, which finishes the book.**
> `POST /api/state/positions/{symbol}/close` moves a row from `positions` to a
> new `closed` list with realised P&L; `GET /api/state/positions/realised`
> totals it. The UI gets an "Đã bán" button that asks for the fill price, and a
> closed-trades panel that hides itself when empty.
>
> **The distinction that makes this worth a second verb:** `DELETE` still
> deletes. "I mis-clicked" and "I sold at 28" were the same operation before
> today, and both destroyed the row — so the app was structurally incapable of
> answering the one question a book exists to answer. The ✕ is still there,
> smaller, for the mis-click.
>
> Realised P&L is **net of the §18.2/10 costs**, imported from `config.py`
> (`BACKTEST_FEE_BPS` × 2 + `BACKTEST_SELL_TAX_BPS`, ≈0.40% round trip) rather
> than retyped. A book quoting a gross number the backtest would call a loss is
> worse than no book, and at these levels the costs routinely decide whether a
> small win is a win — a +0.20% gross scalp books at −0.20%.
> `pnl_pct` is computed even without `qty`, because cost-in-percent is
> size-independent; `pnl_vnd` is not, and stays null rather than being invented.
>
> `closed` is a key, not migration 12 — `_read()` merges `_DEFAULT`, so every
> state file written before today loads unchanged. Still no partial exits: a
> close takes the whole position (`ponytail:` in the source names the upgrade).

> **2026-08-24 (9) — the book can now follow a trade, not only record one.**
> Tom: *"chưa có view để … tiếp tục theo dõi các ngày sau đó."* The data existed
> at every layer and was destroyed at exactly one line.
> `picks_scoring.compute_stop_target_rr` computes a stop and a target,
> `PickEntry` carries them, the Daily Insight card renders them and draws a
> stop→target ladder — and the "Đã vào lệnh" button sent `entry_price` alone,
> into a `trading_state` row with no field to receive them. **So the book could
> not answer the one question worth asking the day after a buy: is this trade
> still valid.** `stop` / `target` / `thesis` are stored now, and editable in
> place on the same `NumCell` the entry price uses.
>
> `GET /positions/pnl` gained `path`, `hit_stop`, `hit_target`,
> `dist_to_*_pct`, `sessions_held`, `sellable_on`. **No new endpoint on
> purpose:** `/pnl` already read the book, already called `.peek()`, already
> looped the positions, and `MyBookPanel` already called it — a second route is
> two route-ordering tests and two places to drift. **No new data source
> either:** the price path is `TickerRow.daily_prices`, 30 sessions the
> snapshot already carries and already persists.
>
> Two definitions that are load-bearing rather than incidental:
> - **`hit_stop` is "ever touched since entry"**, not "today's close is
>   through the level". A stop breached on Tuesday and recovered by Friday is
>   still a breach, and a book that forgets that tells you the trade is fine.
> - **T+ counts sessions.** `tPlusDays()` used `setDate(+i)`, so a Thursday buy
>   claimed a Sunday settlement; it is also T+**2** now, not T+3, matching
>   `BACKTEST_SETTLEMENT_LAG` and §18.2/7. The book row takes the
>   holiday-aware date from the new `utils/clock.next_trading_day`.
>
> Not migration 12 — but `_DEFAULT` merges at the *top level only*, so rows
> written before today omitted the key entirely and shipped a shape the TS
> `Position` type forbids. `_POSITION_DEFAULT` is merged per row in `_read()`.
>
> The sparkline is hand-rolled SVG: recharts sits in a 362 kB chunk that only
> loads on the Backtest tab (§22.3), and a 64×22 polyline must not drag it onto
> every page — the built chunk list is unchanged.
>
> **Deliberately not built** (Tom picked two of four): stop/target *alerts* and
> a full T+ calendar panel. Both fields are computed already, so the UI is
> cheap when wanted. `path` is closes only — `daily_prices` has no high/low — so
> an intraday wick through a stop that closed back above does not register.

### 22.11 The stealth history was a stub, not an empty table — 2026-08-24

`/api/stealth/history` returned a hardcoded `{"rows": []}` from the day it was
written. §22.1 filed it under "correct code with no data", which was wrong in
the same way the Flow Pulse row in that table was wrong — and for a worse
reason: **the stub was indistinguishable from the truth for months**, because
the §16.1 AND gate genuinely produced zero events. The moment §16.1 became a
score and 53 rows carried `accumulation_age > 0`, the endpoint kept saying zero
and nothing in the app could notice.

**Derived from `sector_flow_daily.accumulation_age`, not from
`sector_accumulation_events`.** That table has existed since migration 9 with no
writer in four months, so reading it returns the same empty list by a longer
route. More to the point, the column *already* encodes every run — it is what
the scanner writes and what the Stealth Watch badge renders — so writing the
table too would create a second representation of one fact, and two
representations disagree.

`analysis.stealth.stealth_events()` turns the column into one record per
maximal run of `accumulation_age > 0`, scored forward over `BREAKOUT_WINDOW`:

| classification | meaning |
|---|---|
| `hit` | price cleared the bar inside the window |
| `false_positive` | the run ended and price never did |
| `dry_powder_timeout` | reached §16.9's 30-session max age without breaking out |
| `null` | still open, or too close to the panel edge to judge |

**The null case is the design.** An event whose forward window has not elapsed
has not failed, and classifying it as one would understate the gate on every
refresh, forever. `summary.scored` therefore excludes it, so the hit rate is not
diluted by events that have not had their chance.

`BREAKOUT_WINDOW`, `BREAKOUT_ATR_MULT` and the two bar functions **moved out of
`scripts/stealth_leadtime_experiment.py` into `analysis/stealth.py`** — the
bench and the endpoint are now the second caller of each other's definition, and
a breakout bar living in two files is two bars that drift. The drift would be
invisible: the bench would keep reporting a number the page had stopped using.
`test_the_bench_and_the_endpoint_share_one_breakout_definition` asserts
*identity*, not equality of output. The extraction was verified
behaviour-preserving by re-running the bench and matching §16.15's recorded
table byte-for-byte.

Live: **21 events, 20 scored, hit_rate 0.40, median lead 21 sessions, 75% at
≥10d** — exactly the bench's shipped-gate row, which is what the shared
definition buys. One event (STEEL, 2026-08-11→13) is open and correctly
unscored.

**The page renders §16.14 next to the numbers**, in warn colour: the
unconditional base rate is 43% breakout / 74% at ≥10d, so 40%/75% is *not*
evidence the gate works. Without that line a reader takes a respectable-looking
hit rate as a reason to buy. `ACCUMULATE` is still a watchlist.

> **A negative control caught a test that proved nothing.** The first
> `test_an_open_run_is_not_scored_as_a_failure` used a 3-session run at the
> panel edge — which has no forward bars, so `judgeable` was already False and
> the test passed with the `still_running` guard deleted. Deleting the guard
> left all 13 tests green. Replaced by
> `test_a_long_open_run_is_not_scored_even_though_it_could_be`: a 25-session
> open run has 24 forward bars of its own, clears the bar, and only
> `still_running` keeps it unscored. That one goes red without the guard. A test
> that passes against the broken code is worse than no test — it reports
> coverage it does not have.

> **The same defect had a second host — closed 2026-08-25.**
> `api/routers/sectors_flow.py` built its `history` key from
> `SectorAccumulationEvent`, so `/api/sectors/stealth` reported **0 events**
> from the same panel `/api/stealth/history` read 21 from. Two endpoints, one
> question, opposite answers, and no way to tell which was lying. Both now call
> `stealth_events(panel_from_rows(...))`; live they agree on the first 20.
>
> **Why it survived the §22.11 fix:** both `/api/stealth/*` routes opened
> `SessionLocal()` directly instead of taking `get_session_dependency`, so no
> test could hand them a panel — the endpoints were **structurally untestable**,
> and the only assertions possible were on constants. They take the dependency
> now, which is what let `test_both_stealth_endpoints_derive_the_same_events`
> exist at all. A route that cannot be given data cannot be shown to be wrong.
>
> `panel_from_rows()` in `analysis/stealth.py` is the shared ORM→dict step. It
> is one function rather than two literals because the six columns are the
> contract: a caller that omits `atr_pct` gets a `0.0` default and silently
> scores against the fallback bar instead of the sector's own — the wrong number
> with no error.

