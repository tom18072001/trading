# CLAUDE.md — Sector Money-Flow Redesign (Approved Plan)

> Status: **APPROVED** — 2026-04-08
> Supersedes: legacy 170-symbol prediction system
> Owner: Tom (anhchitruong18@gmail.com)
> Rule: every future modification MUST append an entry to `MODIFICATION_LOG.md`.
> Đọc file này thế nào: giữ **luật đang có hiệu lực**. Chứng cứ — phép đo có
> ngày tháng, hậu kiểm, lịch sử test — nằm ở `docs/doctrine/`, một file một mục.
> Mọi số hiệu mục (§16.1, §22.11, §25.9 …) vẫn giải được ở đây; mục nào đã
> chuyển thì có dòng trỏ. Tách ngày 2026-09-16: 135.718 B → xem cuối file.

## 1. Mission
Pivot the VN Trading system from per-symbol prediction to **sector-level money-flow tracking and rotation prediction** across the 15 inherited VN sectors. Goal: fewer, higher-signal records; slower, more persistent edge; lower compute.

## 2. Inheritance Rules (from legacy)
- KEEP: Python/FastAPI/SQLAlchemy/SQLite(WAL), migrations, service-layer pattern, router pattern, backtest engine skeleton, risk math, scheduler heartbeat (Asia/Ho_Chi_Minh), vnstock integration.
- REMOVE: 170-symbol universe, `stock_prices`, `stock_features`, `trade_setups`, `predictions`, symbol screener, T+3 scanner, symbol pages in frontend, per-symbol ML.
- REPLACE: primary key `symbol` → `sector_code` everywhere.
- **Per-ticker picks (2026-04-17 onward):** `generate_report.py` and `api/routers/insight.py` read per-ticker BUY/ACCUMULATE picks exclusively from `services.picks_universe_service.PicksUniverseService` (dynamic HOSE universe from vnstock Listing). They no longer read `_legacy_stocks`, `_legacy_stock_prices`, or `_legacy_stock_features`. These three tables stay in the DB during a 2-week shadow window then drop in migration 10.
- **Email report (2026-04-23 onward):** `generate_report.py` is the **sole** daily email generator. **Since 2026-09-25 its BUY list is `snapshot.top_buys` verbatim** — one buy rule (`picks_universe_service.long_shortlist`: SMA200 gate → rank blend) shared with Daily Insight and the 17:30 bulletin; the ranker no longer gates or adds buys (no out-of-sample edge, review 2026-09-24 §4.2). The AVOID list still unifies `snapshot.top_sells` with the ranker's SELL sectors into one de-duped list, each entry tagged with its source (`BOTH` / `DAILY_INSIGHT` / `RANKER`). The HTML/PDF gains an Expert Trader Memo section at the top; the email body is plain text (buy symbols + reasons + Dashboard + news links). Recipients come from `REPORT_EMAIL_TO` in the local `.env` — **no list is committed and there is no fallback in code** (removed 2026-08-24 when the repo went public; a source file is the wrong place to publish an inbox). Empty means the HTML/PDF are written and no mail is sent. `scripts/jobs/job_sector_signal_publish.bat` calls `generate_report.py`.
- **One report generator, no versioned copies.** `generate_report.py` is the only
  daily-report generator in the repo. Every earlier numbered copy is gone:
  SecV2 on 2026-04-20, SecV3 + SecV4 on 2026-06-18 (they were kept only as
  manual rollback paths and had drifted into duplicate-but-divergent helpers),
  and SecV5 was renamed to `generate_report.py` on 2026-08-22 (§21 — version
  numbers do not belong in names). If a stale Task Scheduler entry still points
  at one of them, run `scripts/pause_legacy_email_task.ps1` (elevated
  PowerShell) to evict it, then `scripts/cleanup_scheduled_tasks.ps1` to
  re-register the 8 canonical jobs.

## 3. The 15 Sectors (inherited from legacy SECTOR_MAP)
Ngân hàng, Chứng khoán, Bất động sản, Thép & VLXD, Bán lẻ, Thực phẩm, Dầu khí, Điện & NL, Công nghệ, Hàng không & Logistics, Bảo hiểm, Hóa chất & Phân bón, Dệt may, Cao su & Nhựa, Thủy sản.

Each sector defined by a **proxy basket of top 5 constituents by market cap**, used only to compute sector aggregates. Raw constituent OHLCV is fetched transiently and discarded after aggregation (rolling 60-day window retained).

## 4. Money-Flow Metrics per Sector per Interval
Net Dollar Flow, Up/Down Volume Ratio, **Foreign Net Buy** (vnstock foreign flow — killer VN signal), Breadth (% above SMA20/SMA50), Relative Strength vs VNINDEX (5/20/60d), ATR% (sector aggregate), Cross-sector correlation (rolling 20d). Shared macro anchors: VNINDEX, USD/VND, Brent, US10Y, Gold.

Record-count impact vs legacy: **~98% reduction** (15 sectors × ~12 features vs 170 symbols × 40 features).

## 5. New Database Schema
- `sectors (sector_code PK, name, description)`
- `sector_constituents (sector_code FK, symbol, weight, active)` — reference only
- `sector_flow_ts (sector_code, time, net_dollar_flow, up_vol, down_vol, foreign_net, breadth_sma20, breadth_sma50, rs_vnindex_5d, rs_vnindex_20d, atr_pct, UQ(sector_code,time))`
- `sector_flow_daily` — daily rollups
- `macro_anchors (time, vnindex, usdvnd, brent, us10y, gold)`
- `sector_regime (date, regime_label, confidence)`
- `sector_signals (date, sector_code, score, rank, action, model_run_id)`
- Retained: `model_runs`, `backtest_runs`, `dashboard_layouts`.

## 6. New Service Layer
`sector_ingest_service`, `macro_service`, `flow_feature_service`, `rotation_model_service`, `sector_signal_service`, `picks_universe_service` (2026-04-18), `trader_agent` (2026-04-18). Retrofit: `backtest_service`, `risk_service`. Delete: `trade_service`, symbol parts of `ml_service` and `data_service`, legacy `openclaw/` agent (retired 2026-04-18, replaced by `trader_agent`).

## 7. New API Routers
`/api/sectors/flow`, `/api/sectors/ranking`, `/api/sectors/regime`, `/api/sectors/backtest`, `/api/sectors/risk`, retrofitted `/api/agent/briefing`. Remove: `/api/stocks/*`, `/api/trade/*`, symbol `/api/ml/*`.

## 8. Scheduled Jobs (Asia/Ho_Chi_Minh)
| Job | Cron | Purpose |
|---|---|---|
| sector_intraday_flow | */15 9-15 * * 1-5 | Proxy OHLCV + foreign flow → `sector_flow_ts` |
| sector_eod_rollup | 0 16 * * 1-5 | Daily rollup |
| macro_ingest | 0 * * * * | Macro anchors hourly |
| regime_classify | 30 16 * * 1-5 | HMM regime label |
| rotation_train | 0 2 * * * | Nightly LightGBM ranker retrain |
| rotation_predict | 45 16 * * 1-5 | Next-day sector ranking |
| sector_signal_publish | 0 17 * * 1-5 | Write signals + Gmail briefing |
| sector_risk_sentinel | */30 9-15 * * 1-5 | Stop-loss alerts on held sectors |
| daily_watch | 30 17 * * 1-5 | **(2026-09-16)** Module `daily_watch/`: báo cáo sổ + đề xuất mua + đề xuất bán (cửa sổ 20-40 phiên + range tham chiếu, **không stop-loss**) → `report/watch_<date>.md` + kho `data/watch/<date>.json`. Theo dõi cả mã đang nắm **ngoài universe**. Không gửi email. Skill `.claude/skills/theo-doi-hang-ngay/` đọc output, **không** tự phân tích lại |

> **2026-09-16 — task thứ 9, và một chi tiết đáng biết về 8 task cũ.** Trigger
> của cả 8 job trên được đăng ký là `-Daily`, dù cột Cron ghi `1-5`; nên chúng
> **có** chạy cuối tuần, vô hại vì không có phiên mới. `daily_watch` đăng ký
> `-Weekly Mon..Fri` thật, vì Tom yêu cầu T2-T6 rõ ràng. Nó cũng là job duy nhất
> chạy ở `RunLevel = Limited` — nó chỉ chạy python và ghi file, không cần đặc
> quyền, và ở mức đó **đăng ký được mà không cần shell admin**
> (`scripts/cleanup_scheduled_tasks.ps1` nay nhận `RunLevel` theo từng job).

## 9. Data Sources
Primary: **vnstock** (proxy OHLCV, foreign flow, VNINDEX). Macro: FRED (US10Y), stooq (Brent, Gold), SBV/exchangerate.host (USD/VND). Optional: HOSE order-book deltas, ETFs FUEVFVND/E1VFVND.

## 10. Models
- **Regime classifier:** Gaussian HMM on macro + VNINDEX returns → {risk_on, risk_off, rotation, chop}
- **Sector ranker:** LightGBM lambdarank, target = forward 5d sector return
- **Persistence filter:** flow sign held ≥3 sessions
- **Sizing:** vol-targeted, max 3 long / 2 short

## 11. Backtest Targets
Benchmark VNINDEX B&H. Sharpe > 1.0, MaxDD < 15%, top-rank hit-rate > 55%.

## 12. Frontend
Replace 9 symbol pages with 5 sector pages: Flow Dashboard, Rotation Ranking, Regime Monitor, Sector Backtest, Risk.

> **2026-08-23 — reconciled with what actually shipped.** Four of the five
> pages above (Ranking, Regime, Backtest, Risk) had been *built and working*
> for months but had no `<Route>`, so the only way to reach them was to edit
> the source. They are wired now, lazily, under a second nav group
> ("Ra quyết định"), giving nine nav items.
>
> Twelve page components were deleted rather than wired: nine were one-line
> stubs, and `FlowPage`, `BriefingPage` and `AccumulationPage` were superseded
> (by FlowMonitorPage, by the in-page trader agent, and by StealthWatchPage
> respectively — and `/accumulation` would have rendered permanently empty
> since `accumulation_age` is zero on every row).
>
> **Later the same day those nine merged back to five — see §22.9 for the
> current nav.** The name `FlowPage.tsx` was reused for the merged
> Money Flow Monitor + Sector Detail page; it is not the deleted one.

## 13. Migration Order (execution sequence)
1. Freeze legacy tables with `_legacy_` prefix.
2. Migration 8: add new schema.
3. Build `sector_ingest_service` + `macro_service` + 2 schedulers.
4. Backfill 5y `sector_flow_daily` from vnstock.
5. Build `flow_feature_service` + `rotation_model_service` + train v0.
6. Retrofit backtest + risk services.
7. Rewrite briefing + Gmail template. **[2026-04-18 SUPERSEDED]** OpenClaw removed; replaced by in-process `services.trader_agent.TraderAgent` via `claude_agent_sdk` (see `specs/trader_agent.md`).
8. Replace frontend pages.
8.5. **Introduce `PicksUniverseService`** — consolidate per-ticker picks under one dynamic HOSE universe; retire `_legacy_stock_*` reads from the report generator (then SecV3, now `generate_report.py`) and `api/routers/insight.py` (see `specs/picks_universe.md`, 2026-04-17).
9. Shadow-run 2 weeks.
10. Drop `_legacy_` tables + delete symbol code.

## 14. Decided Defaults (chosen in absence of user override)
- Proxy basket size: **top 5 by market cap** per sector.
- Backfill depth: **5 years** (or max vnstock available).
- Execution universe: **top-3 constituents basket** (ETF liquidity in VN is thin).
- OpenClaw agent Trung: **retired 2026-04-18** — replaced by `services.trader_agent.TraderAgent` ("Minh"). **2026-07-20: default provider is now `local`** — plain HTTP to an OpenAI-compatible `/chat/completions` endpoint, no `claude_agent_sdk`. **2026-08-23: `local` names the transport, not where the model runs.** It points at 9Router (`LOCAL_BASE_URL` default `http://localhost:20128/v1`, dashboard `http://localhost:20128/dashboard`), a local router fronting hosted Claude models; `LOCAL_MODEL` default `claude-opus-5`. The previous Ollama defaults (`:11434`, `qwen3:8b`) were dropped — Ollama was never running on this box, so the agent had been failing on every run. Alternatives via `AGENT_PROVIDER`: `glm` (Z.ai Anthropic-compatible endpoint, model `glm-5.2`, needs `GLM_API_KEY`) or `claude` (Claude Code subscription). The SDK is imported lazily, so a local-only install does not need it. Invoked from `POST /api/insight/refresh`. Output rendered inline on the Daily Insight page.
- Frontend: **feature flag** during shadow run, hard-cut after.

Change any of these by editing this file and logging in `MODIFICATION_LOG.md`.

## 15. Modification Protocol
Every code or schema change must:
1. Append entry in `MODIFICATION_LOG.md` with date, files touched, reason, summary.
2. Update `ARCHITECTURE.md` if layer/contract/schema changes.
3. Update this `CLAUDE.md` if strategy/defaults change.

## 16. Early Money-Flow Detection (Tom's Edge Doctrine) — APPROVED 2026-04-09

> **Thesis:** In the VN market, public news/analyst coverage lags real money movement by **~1 month**. By the time a sector is "on the news", smart money has already accumulated. The system's job is therefore **not** to predict next-day return — it is to **detect stealth accumulation 2-4 weeks before the breakout**, so Tom can buy "at the root" (gốc) or at worst "high on the branch" (cành cao), never at the canopy (ngọn).

### 16.1 What "early" means, formally

> **AMENDED 2026-08-23 — the gate is a score, not a conjunction.** The five
> conditions below stand; requiring *all five at once* does not, because it was
> measured to be arithmetically unreachable.
>
> Over the full 13,470-row panel (2023-03 → 2026-08), individual pass rates are
> c1 17.5% · c2 20.4% · c3 34.7% · c4 52.1% · c5 47.7%. All five held
> simultaneously on **0.3%** of rows (42), and the **longest consecutive
> all-five run across 15 sectors in 3.5 years was 2 sessions** — against a
> requirement of 3 in code and 5 in this document. So `accumulation_age` was 0
> on every row ever written, and §22.1's "§16 has never fired" was right about
> the symptom and wrong about the cause: the gate was over-specified, not
> data-starved.
>
> **The rule now:** a sector is in stealth accumulation when it meets
> **≥ `STEALTH_MIN_CONDITIONS` of the 5** (default **4**) for ≥
> `STEALTH_MIN_SESSIONS` sessions (default **3**). The conditions are
> deliberately **unweighted** — §16 gives no basis to rank them, and an invented
> weight vector is a number nobody could defend. A condition that *cannot be
> evaluated* is dropped from **both** the numerator and the denominator, so
> missing data never silently raises the bar.
>
> Result on the live panel: **23 events across 11 sectors**, 53 rows with
> `accumulation_age > 0` (max 7) — the first non-zero values in the system's
> history. **It does not yet meet §16.11** — see the honest numbers there.
>
> This retires the doctrine-vs-code conflict logged as §20.3 P1-1, in the
> direction of neither number: both gave zero. `analysis/stealth.py`,
> `api/routers/stealth.py` and `frontend/src/lib/stealthPresets.ts` now read the
> same two knobs. `RETURN_BOTTOM_FRAC` is back to the doctrine **0.40**.

A sector is in **stealth accumulation** when ≥ 4 of these hold for ≥ 3 sessions (was: ALL, for ≥ N=5):
1. **Rolling 20d net dollar flow z-score > +1.0** (flow regime shift vs own history)
2. **Foreign net buy positive on ≥ 60% of sessions in the last 20d** (smart-money persistence)
3. **Breadth SMA20 rising** (diffusion — more constituents joining, not one whale)
4. **ATR% below 20d median** (quiet tape — no euphoria yet)
5. **Price return (close_idx) in bottom 40% of its 60d range** (still cheap, not extended)

When the score clears the bar, emit a new `ACCUMULATE` action — this is the "gốc" (root) buy. The existing `BUY` action stays but is downgraded to "cành cao" (late-cycle) confirmation.

### 16.2 New leading features (add to FEATURE_COLS)
- `flow_z20` — 20d rolling z-score of `net_dollar_flow` per sector
- `flow_z60` — 60d version (slower, macro flow regime)
- `foreign_streak` — number of consecutive sessions of positive `foreign_net` (cap 20)
- `foreign_hit_20d` — fraction of last 20 sessions with `foreign_net > 0`
- `stealth_score` — composite: `(flow_z20) × (breadth_sma20 rising) × (1 / (1 + atr_rank_20d))`
- `flow_price_divergence` — `flow_z20 − return_20d_zscore` (positive = flow leading price)
- `flow_leadtime_proxy` — lag (in days) between flow z crossing +1 and price return turning positive; stored per crossing event
- `conditions_met` — how many of the 5 §16.1 conditions hold today (0-5)
- `accumulation_age` — consecutive sessions the §16.1 score has cleared the bar (0 if not active)

### 16.3 New signal actions
Extend `SectorSignal.action` enum:
- `ACCUMULATE` — stealth phase (§16.1). Position size = **full target weight**, early entry, widest stop.
- `BUY` — momentum confirmation (flow AND price both rising). Smaller size-add, tighter stop.
- `TRIM` — price extended (return_20d > 90th pctile) while flow_z20 rolling over. Cut half.
- `SELL` — flow z20 flips negative AND price still high. Full exit.
- `HOLD` — default.

### 16.4-16.8 Target, job, backtest metric, cột DB, frontend

Ranker target đổi sang `fwd_20d_sector_return` + classifier head thứ hai
(§16.4); 3 job `stealth_scanner` / `lead_time_audit` / `flow_regime_report`
(§16.5); entry-timing attribution — median entry lag ≥ 10 phiên, root-capture
≤ 0.85 (§16.6); 6 cột thêm vào `sector_flow_daily` + bảng
`sector_accumulation_events` (§16.7); halo `flow_z20` + trang `/accumulation`
(§16.8).

> **Hai mục đã bị thực tế vượt qua, đừng dựng lại:**
> `sector_accumulation_events` **đã drop ở migration 12** (2026-08-26) vì chưa
> từng có writer — run stealth suy ra từ `accumulation_age`, xem §22.11.
> Trang `/accumulation` **đã xoá** (§12) vì `accumulation_age` khi đó bằng 0 ở
> mọi dòng; thay bằng Stealth Watch trong nav "Luân chuyển" (§22.9).

→ Nguyên văn: [`docs/doctrine/16-stealth-measurements.md`](docs/doctrine/16-stealth-measurements.md)

### 16.9 Execution rules (risk-adjusted for early entry)
Because early entries mean wider stops and more time at risk:
- `ACCUMULATE` position: 1.5× normal vol-target, stop = 2.5 × ATR20 (wide).
- Maximum concurrent `ACCUMULATE` positions = 4 (vs 3 for BUY).
- If a sector spends > 30 sessions in stealth without breaking out, auto-exit with no loss/gain ("dry powder reclaimed").

### 16.10 Implementation order (append to §13)

Bước 11-18. → [`docs/doctrine/16-stealth-measurements.md`](docs/doctrine/16-stealth-measurements.md)

### 16.11 Success criterion

Ba tiêu chí gốc: ≥ 60% tín hiệu `ACCUMULATE` đi trước breakout ≥ 10 phiên;
median root-capture ≤ 0.85; false-positive ≤ 30%.

**Cả ba là cần, không đủ — và tiêu chí lead-time không sống sót §16.15.** Dưới
một bar breakout đúng đơn vị, base rate không lọc đã đạt 74% ở ≥10d: tiêu chí
đó thoả mãn được bằng nhiễu. **Chỉ biên độ so với NO GATE mới có nghĩa**
(§16.12).

→ Toàn bộ phép đo: [`docs/doctrine/16-stealth-measurements.md`](docs/doctrine/16-stealth-measurements.md)

### 16.12 The base rate — and why §16.11's criteria are not sufficient

**Luật, áp dụng cho mọi phép đo từ nay:** mọi bench phải in dòng **NO GATE**
(chấm toàn bộ panel, không lọc), và một biến thể **không thắng base rate thì
không phải tín hiệu**, bất kể con số tuyệt đối đẹp đến đâu. So sánh phải
**trong từng năm**, không gộp — gộp là thứ đã che được một 2026 ngang mức ngẫu
nhiên.

**NO GATE nghĩa là gì (2026-09-25):** mọi mã đủ thanh khoản, **mọi phiên** có
≥ 30 mã như thế — một base chung cho mọi luật. **Cấm** so factor có cổng với base
cũng có cổng (xoá luôn phần đóng góp của chính cái cổng), và **cấm** bỏ phiên theo
bề rộng cross-section của chính factor (đúng các phiên thị trường yếu mà
production vẫn ra danh sách). Hai lựa chọn đó cùng nhau đã lật năm 2023 của picks
(review 2026-09-24 §1). Lợi suất h phiên đo mỗi ngày chồng nhau: t là Newey-West
lag h. "Vượt VNINDEX" là danh mục staggered so với index **cùng ngày** — không
phải quy năm số học so với một hằng số.

→ Bảng đo: [`docs/doctrine/16-stealth-measurements.md`](docs/doctrine/16-stealth-measurements.md)

### 16.13 The 2026 collapse is mostly the market

Không phải dữ liệu, không phải right-censoring. 2026 **giảm và biến động cao
hơn** hai năm trước (median fwd-40d −7,6%, vol 0,42 vs 0,21-0,29) — nhưng gate
sập nhanh hơn thị trường, nên regime giải thích mức, không giải thích phần hụt.

→ [`docs/doctrine/16-stealth-measurements.md`](docs/doctrine/16-stealth-measurements.md)

### 16.14 What this means for §16 as a whole

> **Cảnh báo vận hành, còn hiệu lực.** Tính đến 2026-08-24 cổng §16.1 **không
> có edge đo được**: 20 lần bắn trong 3,5 năm, breakout *ít* hơn, *muộn* hơn và
> vào lệnh *tệ* hơn một sector-day lấy ngẫu nhiên từ cùng panel.
>
> Hệ quả: **không luật sizing nào ở §16.9 được tin trên cổng hiện tại** — 1,5×
> vol target, stop 2,5×ATR, 4 vị thế đồng thời. Coi output `ACCUMULATE` sống là
> **watchlist, không phải lệnh**, cho tới khi một biến thể thắng NO GATE trong
> từng năm.
>
> Điều này **không** bác thesis §16 (dòng tiền VN đi trước tin ~1 tháng) — nó
> bác **bản hiện thực này** của thesis. Ứng viên duy nhất từng thắng base rate
> là `foreign_streak` (tính bền của mua ròng nước ngoài), đúng thứ §18.5/21 dự
> đoán trên cơ sở khác.

→ [`docs/doctrine/16-stealth-measurements.md`](docs/doctrine/16-stealth-measurements.md)

### 16.15 The breakout bar was 1.15%, not 8%

Nghi ngờ ban đầu (2×ATR co giãn theo tape) **sai**; lỗi thật là **đơn vị** —
`atr_pct` là biên độ *ngày* (median 0,57%) nên bar ~1,15%, áp lên max 40 phiên
thì **83% sector-day "breakout"**. Đó là phép thử còn sống, không phải phép thử
breakout. `atr_scaled = 2 × median ATR × √40 ≈ 7,2%` giữ đúng ý "hai nhịp
thường" mà nhất quán với horizon.

**Chỉ là bench đo, không ship vào scanner** — `analysis/stealth.py` không dùng
định nghĩa breakout nào.

→ [`docs/doctrine/16-stealth-measurements.md`](docs/doctrine/16-stealth-measurements.md)

## 18. Trader-Lens System Review — APPROVED 2026-04-09

> Reviewer stance: "if I had to trade this book tomorrow with my own money, what would break or bleed me?" Findings are grouped by severity. Items marked **[BLOCKER]** must ship before live paper-trade; **[EDGE]** items are alpha improvements; **[HYGIENE]** items are robustness.

### 18.1 Signal quality gaps

| # | finding | trạng thái |
|---|---|---|
| 1 | **[BLOCKER]** Survivorship + constituent drift — rổ top-5 tĩnh vẽ lại lịch sử. Dựng lại rổ hằng tháng theo market cap tại thời điểm, đóng dấu `constituent_asof` | mở |
| 2 | **[BLOCKER]** Nhiễu foreign-flow ngày ETF rebalance → `etf_rebalance_mask`, `foreign_net_clean` | mở |
| 3 | **[EDGE]** Flow z-score cần điều kiện theo regime → `flow_z20_by_regime` | mở |
| 4 | **[EDGE]** Thiếu proxy phái sinh → `vn30f1m_basis`, `vn30f1m_oi_chg_5d` (vnstock có sẵn) | mở |
| 5 | **[EDGE]** Thiếu proxy dư nợ margin → `broker_margin_total_mom` | mở |
| 6 | **[EDGE]** Breadth tính trên rổ 5 mã — quá hẹp để gọi là breadth | mở, = §20.3 P1-3 |

### 18.2 Execution & risk realism

| # | finding | trạng thái |
|---|---|---|
| 7 | **[BLOCKER]** Chưa mô hình hoá thanh toán T+2 → `settlement_lag=2` | **bỏ 2026-09-25** — Tom: *"bỏ T+2, chỉ sử dụng 4 tuần và 8 tuần"*. Ở khung ≥ 20 phiên T+2 không bao giờ là ràng buộc; backtest tái cơ cấu theo `config.HOLD_SESSIONS` thay vì mỗi phiên |
| 8 | **[BLOCKER]** Chưa kiểm room ngoại (FOL) — `foreign_net` về 0 vì hết room chứ không phải vì hết niềm tin. Room median < 3% → hạ trọng số signal 0,5× | mở |
| 9 | **[BLOCKER]** Slippage + biên giá ±7% HOSE; bỏ fill khi rổ chạm trần/sàn | **đóng ở backtest** (§23) |
| 10 | **[BLOCKER]** Thiếu dòng thuế + phí: `fee_bps=15`/chiều + `sell_tax_bps=10` | **đóng ở backtest** (§23) |
| 11 | **[EDGE]** Vol-targeting dùng ATR ngành — phải dùng đóng góp biên vào vol **danh mục** (bank + broker + realty VN chạy cùng nhau) | mở |
| 12 | **[EDGE]** Trần "3 long / 2 short" tuỳ tiện; **short cash ở VN là bất khả** — chỉ qua VN30F1M | `ALLOW_SHORT_SIGNALS` (§20.2 P1-5) |

### 18.3 Model & validation

| # | finding | trạng thái |
|---|---|---|
| 13 | **[BLOCKER]** Thiếu walk-forward với fold purged/embargoed (López de Prado, embargo = horizon + 2) | **đóng 2026-08-22** (§20.2 P0-6) |
| 14 | **[EDGE]** Một target 20d là hẹp → ensemble `fwd_10d` 0,4 + `fwd_20d` 0,4 + `fwd_40d` 0,2 | mở |
| 15 | **[EDGE]** Ngưỡng §16.1 cố định — phải là **quantile 2 năm của chính ngành đó** (bank ATR thấp kinh niên, năng lượng cao kinh niên) | mở |
| 16 | **[HYGIENE]** Không có giám sát drift của ranker | mở |

### 18.4 Data & ops

| # | finding | trạng thái |
|---|---|---|
| 17 | **[BLOCKER]** Rủi ro một nguồn vnstock — hỏng một ngày là cả pipeline chết im. Cần scraper dự phòng + circuit-breaker + cảnh báo lớn | mở |
| 18 | **[HYGIENE]** WAL trên ổ mạng dễ vỡ → DB phải ở đĩa cục bộ, chặn ở startup | mở |
| 19 | **[HYGIENE]** Thiếu kỷ luật "as of" → thêm `source_ts` tách khỏi `ingested_ts` | mở |
| 20 | **[HYGIENE]** Không có kill-switch toàn cục | **đóng** (§20.2 P1-5, §22.10) |

### 18.5 Stealth doctrine sharpening (§16 delta)

| # | finding | trạng thái |
|---|---|---|
| 21 | **[EDGE]** "Foreign net ≥ 60% của 20d" quá thô — một lệnh khối ngày 1 thoả được hit-rate trong khi dòng tiền chết 19 ngày. Cần **cả** `foreign_hit_20d ≥ 0,6` **và** `foreign_net_z20 ≥ +0,5` | mở — và §16.11 đo được rằng **tính bền** mới là phần dẫn trước |
| 22 | **[EDGE]** Thiếu "distribution guard" để huỷ sớm một stealth event | mở |
| 23 | **[EDGE]** Tín hiệu "buổi sáng của tổ chức" → `morning_share = morning_flow / daily_flow` | mở |
| 24 | **[EDGE]** Lead-time audit phải phân tầng theo regime | mở |

→ Nguyên văn 24 finding: [`docs/doctrine/18-trader-review.md`](docs/doctrine/18-trader-review.md)

### 18.6 Priority queue (append to §13 + §16.10)
Ship order, blockers first:
- P0: §18.1/1–2, §18.2/7–10, §18.3/13, §18.4/17 — before any live paper trade.
  > **2026-08-23:** §18.2/9, 10 are **closed in the backtest engine** —
  > slippage, fee, sell tax and the ±7% band are modelled and now reported on
  > every run (§23). They stay open in `risk_service`, which sizes positions
  > with no cost model. §18.3/13 closed 2026-08-22 (§20.2 P0-6). §18.2/7 (T+2)
  > was closed the same way and **removed 2026-09-25** with the T+ mode.
- P1: §18.1/3–6, §18.2/11–12, §18.3/14–15, §18.5/21–22 — before shadow-run metrics matter.
- P2: remaining HYGIENE + EDGE.

### 18.7 Success re-definition
Current §16.11 targets are necessary but not sufficient. Add:
- **Net-of-cost Sharpe ≥ 0.8** (after fees, taxes, slippage, price-band misses, on a 20- or 40-session book).
- **Max adverse excursion on ACCUMULATE entries ≤ 6%** — if early entries routinely bleed more than that before working, the "root" claim is false.
- **Decile monotonicity** of the ranker: mean forward 20d return must be monotone across score deciles on out-of-sample data. Non-monotone = model is guessing. **Đọc kèm Q5−Q1 với t Newey-West** (2026-09-25): năm con số trung bình nhiễu rất dễ đổi thứ tự — ensemble ML chỉ đơn điệu ở 4/8 lần chạy, không năm nào đơn điệu (review 2026-09-24 §9).

### 18.8 Doctrine
Any future change MUST (a) log a `MODIFICATION_LOG.md` entry referencing the §18 item number it resolves, and (b) update the relevant spec file under `specs/`. Closing a §18 item requires evidence (backtest diff, unit test, or data proof) — not just code.

## 19. Testing

Counts below are re-measured, not dated — §22.7 removed a fixed "as of" stamp
from `ARCHITECTURE.md` for the reason it applies here too: a date in a living
document ages without anyone noticing, and a stale count reads as a fact.
Run the two commands rather than trusting the numbers.

| Suite | Count | Command |
|---|---|---|
| Backend (pytest) | 371 | `uv run pytest tests/` |
| Frontend (vitest) | 13 | `cd frontend && npm test` |
| **Total** | **384** | — |
> Vì sao từng bài test tồn tại — và 4 lần negative control bắt được test vô
> dụng của chính tôi — ở [`docs/doctrine/19-testing-history.md`](docs/doctrine/19-testing-history.md).
> Đọc nó trước khi xoá hoặc viết lại một bài test trông có vẻ thừa.

Smoketest (thứ pytest cấu trúc không thấy được): `uv run python scripts/smoketest.py`.

## 20. Code Review — 2026-08-22

Full findings: **`docs/reviews/CODE_REVIEW_2026-08-22.md`** (22 findings: 6 P0, 6 P1, 4 P2, 6 P3).

### 20.1-20.2 Defect trung tâm, và 15 mục đã sửa

Một chuỗi nhân quả chạy qua phần lớn P0 và bắt đầu ở **một bảng**: job EOD 16:00
ghi `sector_flow_daily` **thiếu `close_idx`**, mà `close_idx` nuôi target ML,
điều kiện 5 của §16.1 và toàn bộ P&L backtest. Đã sửa, cùng 14 mục khác.

→ Chuỗi nhân quả + bảng 15 mục: [`docs/doctrine/20-code-review.md`](docs/doctrine/20-code-review.md)
→ 22 finding đầy đủ: [`docs/reviews/CODE_REVIEW_2026-08-22.md`](docs/reviews/CODE_REVIEW_2026-08-22.md)

**Mặc định chọn để giữ nguyên hành vi sống:** `API_REQUIRE_KEY=0`,
`ALLOW_SHORT_SIGNALS=1`, `TRADING_HALT=0`. `MAX_ACCUMULATE_SECTORS=4` và luật
giải phóng sau 30 phiên **có** đổi hành vi — chúng hiện thực §16.9, thứ chưa
từng được thi hành.

**Baseline ruff: 65.** Đo lại, đừng tin dòng này — một lần refactor có thể làm
số này tăng mà không hỏng gì, hoặc giảm mà không sửa gì (§20.2).

### 20.3 Còn mở — cần một quyết định, không chỉ code

| Id | Câu hỏi |
|---|---|
| P1-3 | Breadth trên 5 mã chỉ nhận 9 giá trị rời rạc (§18.1/6, còn mở). |
| P2-2 | Hai bucket rate-limit trong một process: `utils/vnstock_gate` và `picks_universe_service._kbs_throttle`. `/insight/refresh` **không lấy `job_lock`**, nên một lần refresh từ UI chồng lên job intraday sẽ chạy ở 2× trần KBS. |
| P2-3 | Job "intraday" fetch `interval="1D"` và tải lại 120 ngày mỗi 15 phút (~3.750 call/ngày trên gate 18/phút). Hoặc fetch bar 15m thật, hoặc thừa nhận đây là pipeline EOD và sửa §4/§8. |

**Đã đóng** (chi tiết ở [`docs/doctrine/20-code-review.md`](docs/doctrine/20-code-review.md)):
P0-5 backfill `foreign_net` (2026-08-23) · P1-1 cổng §16.1 thành điểm
(2026-08-23) · P1-4 filtered posterior, hết back-paint (2026-08-24, §25.3) ·
P3-2 `import generate_report` thành trơ, 113 → 4 câu lệnh module-level
(2026-08-24).

### 20.4 Doctrine drift to close

`docs/reviews/CODE_REVIEW_2026-08-22.md` carries a "plan vs. code" table of ten places where
this document describes a system different from the one running. Per §18.8,
each needs either a code change or a doctrine amendment — not silence.


## 21. Naming — no version suffixes (2026-08-22)

Tom's directive: version numbers do not belong in names. A file called
`generate_secv5.py` tells you there were four before it and nothing about what
it does, and it forces a rename every time it changes.

| was | now |
|---|---|
| `generate_secv5.py` | `generate_report.py` |
| `report/report_template_secv5.html` | `report/report_template.html` |
| `report/secv5_<date>.{html,pdf}` | `report/daily_report_<date>.{html,pdf}` |
| `scripts/register_secv5_task.ps1` | `scripts/register_report_task.ps1` |
| `scripts/pause_secv3_secv4_email.ps1` | `scripts/pause_legacy_email_task.ps1` |
| model_name `rotation_ranker_v0` | `rotation_ranker` |
| `models/saved/rotation_ranker_v0.pkl` | `rotation_ranker.pkl` |
| model_version `hmm_v0` | `hmm` |
| env `SECV3_DB_PATH` | `REPORT_DB_PATH` (old name still honoured) |

Dates are NOT versions and were left alone: `MODIFICATION_LOG.md`,
`docs/reviews/CODE_REVIEW_2026-08-22.md` and the dated post-mortems keep their names,
because a dated record is supposed to say when it was written.

**Consequence to know about:** renaming `model_name` orphans the 74 existing
`model_runs` rows from the active-model lookup. That is intentional -- every
one of them was a degraded mean-flow fallback (see section 20 / P0-8), so
none was worth keeping. The next `--train` writes the first real one.



## 22. Frontend flow audit — 2026-08-23

→ Nguyên văn §22.1-22.11: [`docs/doctrine/22-frontend-audit.md`](docs/doctrine/22-frontend-audit.md)

### 22.7 Bốn tài liệu chia việc — đọc trước khi viết vào file nào

| file | trả lời | hình dạng |
|---|---|---|
| `CLAUDE.md` | hệ thống **phải** thế nào | doctrine, sửa tại chỗ |
| `docs/doctrine/` | **vì sao** luật đó có — phép đo, hậu kiểm | một file một mục §, nguyên văn |
| `ARCHITECTURE.md` | contract hiện **là** gì | lớp + changelog có ngày |
| `MODIFICATION_LOG.md` | cái gì **đã đổi**, và vì sao | append-only, một entry một lần sửa |
| `docs/PATCHES.md` | plan nào **đang chạy**, plan nào **xong** | hai bảng, một dòng một plan |

Tài liệu cũ thì **xoá, không lưu trữ** — một doc sai được archive vẫn là một doc
sai sẽ có người đọc. `GLOSSARY_VI.md` là file nguy hiểm nhất khi sai: nó viết
cho người **không** đọc code.

### 22.8 Một design system, một bộ từ vựng hành động

`frontend/src/lib/actions.tsx` là nguồn duy nhất, và nó tách hai thứ từng bị gộp:

| component | nghĩa | nguồn | trạng thái |
|---|---|---|---|
| `ActionBadge` | làm gì với tiền | `sector_signal_service.py` (§16.3) | ACCUMULATE · BUY · TRIM · SELL · HOLD |
| `FlowBadge` | tape đang làm gì | `api/routers/flow.py`, chỉ từ `flow_z` | HOT · COOL · NEUTRAL |

`FlowBadge` cố ý styling phẳng hơn: tape HOT là một **quan sát**, không phải
lệnh, và không được đọc ra như BUY. **TRIM được render nhưng chưa bao giờ phát**
— signal service không có đường tới nó, nên §16.3 thực tế còn 4 trạng thái.

### 22.9 Nav 5 mục, tab nằm trong URL

Daily Insight · Dòng tiền · Luân chuyển · Rủi ro & Vị thế · Nghiên cứu.
Tab ở `?tab=` với `replace: true` — trang gộp phải giữ được deep link của route
cũ, và đổi tab không được chồng history. Mọi path trước khi gộp đều redirect.

### 22.10 Operator state — kill-switch, sổ vị thế, watchlist

`services/trading_state.py` = **một file JSON** (`data/trading_state.json`,
gitignored), 5 khoá: halt · capital · positions · closed · watchlist, sau
`/api/state/*`. **Cố ý không phải bảng:** process scheduler không có HTTP client
nên phải đọc cờ halt thẳng từ đĩa.

- **Halt có hai nguồn, OR lại.** `TRADING_HALT` là override cứng mà browser
  không xoá được; cờ runtime là thứ UI bật. `publish()` đọc **một lần trước
  vòng lặp**, nên bật giữa chừng không thể publish nửa batch.
- **Bán ≠ xoá.** `close_position()` để lại chứng cứ; `remove_position()` vẫn
  xoá, dành cho lúc bấm nhầm. P&L realised **net** chi phí §18.2/10 (≈0,40%
  vòng), import từ `config.py` chứ không gõ lại.
- **`hit_stop` là "đã từng chạm kể từ lúc vào lệnh"**, không phải "giá đóng hôm
  nay xuyên mức". T+ đếm **phiên**, không đếm ngày (`utils/clock.next_trading_day`).

### 22.11 Lịch sử stealth suy ra từ `accumulation_age`

**Không** đọc `sector_accumulation_events` — bảng đó chưa từng có writer và đã
drop ở migration 12. Một sự thật nằm ở hai chỗ là hai sự thật sẽ lệch nhau.
`classification` **nullable**: run đang chạy hoặc chưa đủ `BREAKOUT_WINDOW` phiên
là *chưa chấm được*, không phải trượt.

`BREAKOUT_WINDOW`, `BREAKOUT_ATR_MULT` và hai hàm bar sống ở `analysis/stealth.py`
— bench và endpoint là caller của **cùng một** định nghĩa, và test assert
*identity* chứ không phải output bằng nhau.

> **Trang phải in §16.14 cạnh con số**: base rate không lọc là 43% breakout /
> 74% ở ≥10d, nên 40%/75% **không** phải bằng chứng cổng chạy được.

## 23. Backtest controls — và `flow_z` chính là `flow_raw` — 2026-08-23

→ Nguyên văn: [`docs/doctrine/23-backtest-controls.md`](docs/doctrine/23-backtest-controls.md)

- **Chi phí đã mô hình hoá trong backtest engine**: phí mỗi chiều, thuế bán
  0,1%, slippage `max(0,3%, 0,5×ATR%)`, biên ±7% HOSE. **§18.2/9, 10 đóng ở
  backtest**, còn mở ở `risk_service` — nơi sizing vị thế **không có** cost model.
  T+2 (§18.2/7) **bỏ 2026-09-25**: danh mục tái cơ cấu mỗi 20 hoặc 40 phiên
  (`config.HOLD_SESSIONS`), khớp ở phiên **sau** phiên công bố tín hiệu.
  Đừng viết lại caveat "chưa mô hình hoá": một caveat sai dạy người đọc chiết
  khấu một con số vốn đã net.
- **`flow_z` xếp hạng trên `flow_z20`** (z của ngành so với *chính lịch sử 20d
  của nó*). Bản cross-sectional cũ là ánh xạ affine dương → **giữ nguyên thứ tự
  raw VND**, tức `flow_z` và `flow_raw` từng là một chiến lược.
- **§23.5 đóng về cấu trúc 2026-09-25:** 45% ma sát trên 844 lệnh/năm là
  turnover của việc tái cơ cấu **mỗi phiên**. Nay chỉ tái cơ cấu mỗi 20 hoặc 40
  phiên: `flow_z` 2024-01→2026-09 còn 163 lệnh ở khung 20 và 81 ở khung 40 (đo
  trên bản DB 2026-09-24, trước khi sửa dữ liệu ngành — §4 review 2026-09-24).

## 24. Filter, preset và giá của tranh cãi P1-1 — 2026-08-23

→ Nguyên văn: [`docs/doctrine/24-filters-presets.md`](docs/doctrine/24-filters-presets.md)

- **§24.1** — `lib/filters.tsx` là nguồn duy nhất cho search / lọc action / sort / CSV.
  State nằm trong **URL**, không trong component — một view đã chỉnh là thứ gửi
  được cho người khác, và F5 không được xoá nó. **Lọc trước, sort sau.**
  **CSV mang BOM UTF-8**, nếu không Excel locale VN mở "Ngân hàng" thành mojibake.
- **§24.2** — preset stealth **Chặt / Vừa / Rộng** mở mặc định ở **Vừa** (≥4/5, N=3 — thứ
  đang chạy). Chặt (5/5, N=5) giữ lại **để nhìn thấy nó trả về 0**.
- **§24.3** — `POST /api/state/report/send` chạy `generate_report.py` bằng **subprocess**,
  và guard double-click nằm ở **backend**, không phải ở nút bị disable: nút
  disable là gợi ý, hai email là sự thật.

## 25. Regime confidence — model sập báo cáo sự chắc chắn — 2026-08-24

→ Nguyên văn: [`docs/doctrine/25-regime-confidence.md`](docs/doctrine/25-regime-confidence.md)

- **Số 1,00 là model sập, không phải model tự tin**: 3/4 state chạm trần
  covariance vì feature chưa chuẩn hoá. `fit()` nay **từ chối** một fit sập
  (>1 state rỗng) và rơi về heuristic thay vì publish số 1,0 của nó.
### 25.2 Công thức — `confidence` nghĩa là gì

- **`confidence` = P(nhãn này còn giữ sau `CONF_HORIZON` = 5 phiên)**, không
  phải state posterior. Đây là định nghĩa phải nói ra mỗi khi hiển thị —
  `analysis.regime.confidence_phrase()` là **renderer duy nhất**, và nó sống
  cạnh công thức chứ không ở report generator: ai đổi ý nghĩa con số thì sở hữu
  luôn câu chữ mô tả nó.
- **Hedge ở đầu THẤP, không phải đầu cao** (<0,55). Đo trên 300 bar thì ngược
  lại — đó là artefact giai đoạn, và bài học tổng quát hơn con số: **một đường
  calibration khớp trên lát gần nhất của chuỗi phi dừng chỉ đo lát đó.**
- **Không calibrator nào được ship**: isotonic và Platt đều thua raw ở Brier
  walk-forward. Một lớp fit mà thua out-of-sample là một lớp fit tốn tiền.
- **`CONF_HORIZON`=5** vì là horizon dài nhất **dương ở cả ba** giai đoạn, không
  phải vì tối ưu — gộp lại thì H=13 thắng, và đó chính là cái bẫy §16.12.
- **Đoạn gần đây sập là do tape, không do model** — chia theo tercile vol: AUC
  0,827 / 0,790 / 0,694, đơn điệu, và lịch chỉ là proxy cho vol.
- **§25.10 còn mở:** `CONF_HORIZON` theo vol (đo rồi, chưa ship); đo lại khi
  panel dài thêm.

## 26. Picks theo mã xếp hạng ngược — 2026-09-16

→ Nguyên văn §26.1-26.10: [`docs/doctrine/26-ticker-picks.md`](docs/doctrine/26-ticker-picks.md)

### 26.4 Công thức đang ship

`services/picks_scoring.py::score_ticker` trả float ~−9..+7, `UNTRENDED_FLOOR`
= −20 cho mã không xác nhận được uptrend:

```
score = −1
      + (50 − RSI(2)) / 10                 quá bán — Connors
      + clip(−ret_1d / ATR, −2, +2)        nhịp giảm đo bằng ATR của CHÍNH mã đó
      + 2   nếu trên SMA50
      − 1.5 nếu ATR% > 3.5
      sàn −20 trừ khi trên SMA200
```

- **Một luật mua cho mọi bề mặt — `long_shortlist` (2026-09-25):** cổng SMA200
  (`score > UNTRENDED_FLOOR`) → thứ tự blend → top-5. Daily Insight, email 17:00
  và bản tin 17:30 cùng gọi nó; **không** lọc theo tín hiệu ngành. Danh sách
  chỉ rỗng khi không mã nào trên SMA200 — phần vốn đó mua ETF chỉ số.
- **`MIN_BUY_SCORE` 2,5 đã bỏ làm cổng** (Tom: *"bỏ ngay, giữ cổng SMA200"*). Nó
  đặt theo phân vị 78 của điểm, chưa từng đo lợi nhuận; đo rồi thì tốn
  −0,39%/lệnh ở 20 phiên, −0,44% ở 40 (t −1,5…−1,6, in-sample). Hằng số còn lại
  **chỉ** để `daily_watch` ghi danh sách luật cũ vào kho (`shortlist_with_cutoff`)
  — `daily_watch/audit.py` chấm hai luật ngoài mẫu. `MAX_5D_DROP_PCT` (−12%, chỉ
  email) cũng bỏ: đo ra ±0,01%/lệnh.
- **Tie-break theo symbol, không theo dollar volume**: `dv_20d` không trung tính
  mà **có hại** (−0,06% → −0,15%) — trong mỗi bậc điểm nó luôn trả về mã to
  nhất, chậm nhất. Thanh khoản thuộc về bộ lọc cứng ở thượng nguồn.
- **Thứ tự do tầng cross-sectional quyết**: `blended_rank_scores` (blend rank
  50/50 giữa score và OBV trend) chạy một lần mỗi build, ghi `TickerRow.rank_score`.
  **Cổng SMA200 quyết định được vào hay không; blend quyết định thứ tự.** Bản cộng
  OBV theo từng dòng thua rõ — cộng giá trị thô để dispersion một ngày quyết
  định số hạng đó át hay biến mất.
- Bench **import** hệ số chứ không gõ lại (§22.11).

### 26.6 Phần không phải bài toán thuật toán

> **ĐÍNH CHÍNH 2026-09-16 — con số 0,70% dưới đây sai, đúng là 1,00%.**
> §26.6 lấy "15bps slippage mỗi chiều", nhưng §18.2/9 quy định slippage là
> `max(0,3%, 0,5×ATR%)` và `config.BACKTEST_SLIPPAGE_MIN_PCT = 0.003` thi hành
> đúng điều đó — **0,30%/chiều, không phải 0,15%**. Hai bench đã implement hai
> số khác nhau suốt thời gian qua: `ticker_alpha_bench.py` lấy từ config
> (**1,00%/vòng**), `ticker_ranker_experiment.py` gõ tay `0.0015`
> (**0,70%/vòng**). Nay cả hai import `analysis/bench.py` — một định nghĩa.
>
> | khung | 0,70% (số cũ, sai) | **1,00% (đúng)** |
> |---|---|---|
> | T+3 | 58,8%/năm | **84,0%/năm** |
> | T+10 | 17,6% | **25,2%** |
> | T+20 (4 tuần) | 8,8% | **12,6%** |
> | T+40 (8 tuần) | 4,4% | **6,3%** |
> | T+60 | 2,9% | **4,2%** |
>
> **Mọi con số `excess` không đổi** — excess là hiệu hai lợi suất gộp nên chi phí
> triệt tiêu. Chỉ cột **net/lệnh và quy năm** sai, và sai đúng bằng 0,30%/lệnh.
> §26.9's "vẫn không thắng index" vì thế **mạnh lên chứ không yếu đi**.
>
> Và 1,00% **vẫn là phía nhẹ**: §26.9 kiểm bằng web rằng phí thật VPS là
> 0,2%/chiều chứ không phải 0,15% như config.

Ở 0,70%/vòng (`BACKTEST_FEE_BPS`×2 + `BACKTEST_SELL_TAX_BPS` + 15bps slippage
mỗi chiều), chi phí xoay vòng mỗi năm: **T+3 → 58,8%** · T+10 17,6% · T+20 8,8%
· T+60 2,9%. Universe đủ điều kiện trả **+12,5%/năm**.

> **Nói thẳng: xoay vòng T+3 không thể có lãi trên universe này ở mức phí này,
> bằng bảng xếp hạng nào cũng vậy.** Rule tốt nhất đo được đáng +0,21%/lệnh —
> không phải suýt trượt, mà lệch **hai bậc độ lớn**. Cách dùng trung thực của
> danh sách hằng ngày là **shortlist 3-4 tuần**.

### 26.9 Khung thời gian đáng giá gấp mười lần thuật toán

> **ĐÍNH CHÍNH 2026-09-25 — thước đo dưới đây phóng đại edge; đọc khối này
> trước.** Bench cũ so factor có cổng SMA200 với base cũng có cổng và bỏ các
> phiên factor có dưới 30 mã; t coi cửa sổ chồng nhau là độc lập; "vượt VNINDEX"
> so quy năm số học với hằng số 15,7%. Chấm lại đúng (base NO GATE mọi phiên,
> NW t, danh mục staggered cùng ngày — `ticker_alpha_bench.py` nay làm đúng thế):
> - **"1/41 sống sót" bị rút:** không luật nào dương đủ 4 năm, kể cả `X_prop_obv`.
> - **Luật đang ship** (cổng SMA200 → blend, `X_shipped_rule`): excess +0,69%/lệnh
>   (NW t 1,55) ở 20 phiên, +1,01% (t 1,91) ở 40; danh mục **7,2% / 11,7%/năm**,
>   Sharpe 0,44 / 0,65, so với **VNINDEX 17,5%, Sharpe 0,98** cùng kỳ 2023-01 →
>   2026-09. Số 5,9% / 11,7% cũ là quy năm số học của luật có ngưỡng 2,5 (danh
>   mục thật của nó: 2,7% / 9,3%).
> - **"Trên 40 phiên không factor nào sống sót" bị rút:** danh mục đi ngang sau
>   ~40 phiên (60: 10,6%, 120: 10,9%) — giữ lâu hơn không thêm gì đo được, và đó là
>   lý do 40 là mặc định (Tom 2026-09-25: chỉ dùng khung 4 và 8 tuần).
> → Bảng đầy đủ: `docs/reviews/ALGO_REVIEW_2026-09-24.md` §1-§3.

Base rate **không xếp hạng**, quy năm: T+3 **−40,6%** · T+10 −4,9% · T+15
**+1,3%** (hoà phí) · T+20 +4,7% · T+40 +10,2%.

> **Tần suất giao dịch là thuế thuần và là số hạng lớn nhất trong cả hệ thống.**
> T+3 → 4 tuần đáng ~**+45 điểm %/năm** trước mọi kỹ năng xếp hạng; rule tốt
> nhất đáng +0,5-0,8 điểm %/lệnh.

**Vẫn không thắng index.** Cấu hình tốt nhất đo được ≈ +14,4%/năm với 5 mã tập
trung, so với **VNINDEX +15,7% CAGR, Sharpe 0,91, MaxDD −18,1%**. Cái đo được là
+13 điểm %/năm **so với thứ chạy hôm trước**, không phải lý do chọn cổ phiếu
thay vì index.

> **ĐO LẠI 2026-09-16 dưới chi phí đúng (§26.6) — khoảng cách rộng hơn.** Mọi
> con số quy năm ở mục này tính ở 0,70%/vòng; ở 1,00% thì trừ đi 3,8 điểm %/năm
> tại khung 20 phiên. Thứ tự đang ship (`X_prop_obv`), đo trên panel
> 2022-01→2026-09, 789 lát ngày:
>
> | | §26.9 ghi (0,70%) | **đo lại (1,00%)** |
> |---|---|---|
> | excess/lệnh | +0,49% | **+0,49%** (không đổi — chi phí triệt tiêu) |
> | net/lệnh | +0,77% | **+0,47%** |
> | quy năm | +10,1% | **+5,9%** |
>
> **Nó vẫn là thứ duy nhất sống sót.** Chấm cả 41 factor trong bench theo hai
> tiêu chí bắt buộc (§16.12 từng năm + §18.7 đơn điệu): **1/41 qua**, và đó là
> `X_prop_obv`. Kết quả này đến từ tiêu chí, không từ việc tôi chọn.
>
> **Bài học của bộ khung, đọc ở đúng một dòng:** `Y_shipped_plus_small` quy năm
> **+7,5%** — cao hơn — nhưng **âm 2025 (−0,80)** nên trượt. Xếp theo tiền thì
> chọn nhầm; hai tiêu chí bắt buộc là thứ chặn lại. Đây chính là điều §16.12
> nói, nay được thi hành tự động thay vì phải nhớ.

- **Book sim là nhiễu, và đó là phát hiện, không phải lời than.** Cùng một rule,
  quét khung giữ 15/20/25/30/40/60 cho +25,9 / −17,1 / +78,8 / +127,2 / +170,2 /
  −30,7 — đổi dấu hai lần. **Mọi kết luận lấy từ bench cross-sectional**
  (789-1.126 lát ngày, chia theo năm). **Đừng chọn rule từ book sim.**
- **Vào lệnh ở giá mở phiên sau bỏ mất drift qua đêm** — 0,145 điểm % mỗi lệnh,
  như nhau ở mọi khung từ 2 đến 20 phiên, tức ~1/5 toàn bộ chi phí vòng. Đo
  được, **cố ý chưa làm** (cần chấm trước phiên ATC 14:45).

### 26.10 Stop đang tốn nhiều hơn phần nó bảo vệ

Ở khung 4 tuần, 3.542 lệnh: **mọi** hình học có stop đều lỗ; chỉ bản **không
stop** có lãi (+0,72%/lệnh vs −0,14% của SWING 2.5/1.8 đang ship). 40% chạm
target, **44% chạm stop** — stop nổ ngang tần suất target là đang kết thúc luận
điểm chứ không bảo vệ nó.

Một lệnh đơn tệ hơn 3 lần khi bỏ stop (−47% vs −15%), **nhưng ở book 5 mã thì
vừa lời hơn vừa drawdown thấp hơn** (+36,2% / −18,8% vs −5,2% / −21,5%): số
lượng vị thế đã chặn đuôi rồi.

> **QUYẾT ĐỊNH ĐẢO LẠI, CÙNG NGÀY — Tom bỏ stop.** *"bỏ stop nhưng phải đưa
> khuyến nghị range bán (range có thể thay đổi theo thời gian nếu bạn cảm thấy
> nó vẫn có sóng lên)."* Đây là quyết định đang có hiệu lực; đoạn bên dưới giữ
> lại vì nó ghi lý lẽ của lần quyết đầu, và cả hai lần đều là quyết định của
> Tom chứ không phải của phép đo.
>
> **Đã ship:** `is_valid_long_pick` và sàn R:R giữ nguyên (chúng là bộ lọc
> *sàng lọc*, không phải lệnh bán), nhưng **sổ vị thế không còn stop và không
> còn cảnh báo stop**. Thay bằng `daily_watch/sell_range.py`: một **cửa sổ thời
> gian** (luật) và một **range giá trượt lên** (tham chiếu).
>
> **Range bán trượt cũng được đo, và nó cũng thua.** Câu hỏi tự nhiên là liệu
> một băng neo ở *đỉnh* có tốt hơn một stop neo ở *giá vào* không.
> `scripts/tplus_strategy_bench.py --trail` chấm 7 hình học, chi phí 1,00%/vòng,
> khung 40 phiên. **Đo lại 2026-09-25** sau khi sửa hai lỗi nhìn trước của bench
> (đỉnh cập nhật bằng giá đóng trước khi so giá thấp cùng phiên; phiên mở dưới
> băng vẫn khớp ở băng — review 2026-09-24 §3.2); cột "bản lỗi" là số cũ:
>
> | hình học thoát | luật cũ, bản lỗi | luật cũ, sửa | **luật ship, sửa** |
> |---|---|---|---|
> | **KHÔNG stop, giữ hết khung** | +1,77 | +1,77 | **+2,23** |
> | range nhả 3,5×ATR | +1,07 | +1,14 | +1,54 |
> | chỉ gãy trend thì bán | +0,87 | +0,88 | +1,21 |
> | range nhả 2,5×ATR | +0,18 | +0,87 | +1,26 |
> | range nhả 1,5×ATR | −1,29 | +0,45 | +0,70 |
>
> **Giữ hết khung vẫn thắng, và càng chặt càng thấp — nhưng cái giá của băng nhỏ
> hơn 2-3 lần con số cũ.** Cùng chiều ở khung 20. Như một danh mục thật,
> `give_back` 3,5×ATR tốn ~0,7 điểm %/năm nếu tiền bán ra đặt vào index. Kết luận
> tổng quát vẫn đứng: **một luật thoát bằng mức giá, dù neo ở đâu, vẫn tốn tiền**
> — ít hơn đã tưởng.
>
> Nên `sell_range.py` tách bạch hai thứ và chỉ gọi **một** trong hai là luật:
> `sell_from`/`sell_by` (giữ 20-40 phiên — **luật đo được**) và
> `band_lo`/`band_hi` (±1×ATR quanh đỉnh — **tham chiếu, không phải luật**).
> `give_back` 3,5×ATR dưới đỉnh là mức **ít tốn nhất** trong các băng đo được,
> không phải mức tốt; nó được báo như một tin về *luận điểm* ("sóng lên đã kết
> thúc"), không phải một lệnh bán.

<details><summary>Lý lẽ của lần quyết đầu, cùng ngày — Tom giữ stop (đã đảo)</summary>

> **QUYẾT ĐỊNH 2026-09-16 — Tom giữ stop.** *"tôi vẫn nghĩ cần stoploss."*
> Câu hỏi đóng lại: `is_valid_long_pick` giữ nguyên yêu cầu `stop < entry`, sàn
> R:R giữ nguyên, thẻ Daily Insight giữ thang stop→target, sổ vị thế giữ
> `hit_stop`. **Không đổi dòng code nào.**
>
> Đây là một lựa chọn hợp lệ trên chứng cứ chứ không phải bỏ qua chứng cứ:
> backtest **không nhìn thấy** margin call, gap-down theo tin, hay ngày Tom
> không ngồi trước màn hình — ba thứ mà stop tồn tại để chặn, và không thứ nào
> xuất hiện trong bảng trên. Bảng đo tail per-trade (−47% khi bỏ stop vs −15%
> khi giữ) là phần chứng cứ đứng về phía quyết định này.
>
> **Cái giá được chấp nhận có ý thức: ~0,86 điểm %/lệnh**, lớn hơn toàn bộ cải
> tiến thuật toán §26.9. Nó không biến mất vì đã quyết; nó chuyển từ "defect
> chưa biết" sang "chi phí đã biết", và đó là lý do con số này phải nằm lại đây.
>
> **Việc còn mở, và giờ mới là việc đáng làm:** đã chốt giữ stop thì câu hỏi
> không còn là *có hay không* mà là **hình học nào rẻ nhất**. Mới đo 4 hình học
> cố định; chưa đo trailing stop, stop theo thời gian, stop chỉ kích hoạt sau
> khi lãi, hay stop theo ATR động. Một trong số đó có thể lấy lại phần lớn
> 0,86pp mà vẫn chặn được đuôi.
>
> *(Việc đó đã làm, cùng ngày, và câu trả lời là **không cái nào** — xem bảng ở
> trên. Đó là lý do quyết định bị đảo.)*

</details>

## 27. Tách file — 2026-09-16

`CLAUDE.md` được khai là CACHED và *"DO NOT modify mid-session"*, nhưng đã tới
**135.718 B ≈ 33.400 token nạp lại mỗi lượt** — gấp 13 lần ngân sách 10 KB mà
`claude/CLAUDE.md` mẹ đặt ra — và **72% là hậu kiểm có ngày tháng**, không phải
luật đang có hiệu lực. Hậu quả đo được trong transcript: `4b2f418e` hết context
**5 lần trong một ngày**, `9245140a` 3 lần.

Nguyên tắc cắt: **giữ thứ một agent phải tuân mỗi lượt; chuyển thứ chỉ giải
thích vì sao luật đó có.** Mọi heading §NN ở lại, nên mọi tham chiếu (§16.1 bị
trỏ 104 lần, §18.2 99 lần, §22.11 23 lần) vẫn giải được.

| file | chứa | nguyên văn từ |
|---|---|---|
| [`16-stealth-measurements.md`](docs/doctrine/16-stealth-measurements.md) | kế hoạch §16.4-16.8/16.10 + toàn bộ phép đo §16.11-16.15 | §16 |
| [`18-trader-review.md`](docs/doctrine/18-trader-review.md) | 24 finding | §18.1-18.5 |
| [`19-testing-history.md`](docs/doctrine/19-testing-history.md) | vì sao từng bài test tồn tại | §19 |
| [`20-code-review.md`](docs/doctrine/20-code-review.md) | defect trung tâm + 15 mục đã sửa | §20.1-20.2 |
| [`22-frontend-audit.md`](docs/doctrine/22-frontend-audit.md) | audit frontend | §22 |
| [`23-backtest-controls.md`](docs/doctrine/23-backtest-controls.md) | backtest controls | §23 |
| [`24-filters-presets.md`](docs/doctrine/24-filters-presets.md) | filter + preset | §24 |
| [`25-regime-confidence.md`](docs/doctrine/25-regime-confidence.md) | regime confidence | §25 |
| [`26-ticker-picks.md`](docs/doctrine/26-ticker-picks.md) | picks theo mã | §26 |

**Luật từ nay:** một phép đo mới ghi vào `docs/doctrine/`; `CLAUDE.md` chỉ nhận
**kết luận** của nó, và chỉ khi kết luận đó đổi một luật. Nếu một mục ở đây dài
quá ~15 dòng thì phần thừa thuộc về `docs/doctrine/`.

### 27.1 Bảng tra mục con đã chuyển

Mọi `§NN.M` dưới đây **không còn thân bài ở file này**; kết luận đang có hiệu lực
đã gộp vào mục cha ở trên, nguyên văn ở file bên phải.

| § | nội dung | file |
|---|---|---|
| 16.4-16.8, 16.10 | target 20d + classifier head · 3 job stealth · entry-timing attribution · cột DB · halo + trang `/accumulation` · thứ tự dựng 11-18 | `16-stealth-measurements.md` |
| 16.11 | ba tiêu chí thành công, và vì sao tiêu chí lead-time không sống sót | `16-stealth-measurements.md` |
| 16.12 | base rate — gate thua cả việc không lọc | `16-stealth-measurements.md` |
| 16.13 | 2026 sập chủ yếu là do thị trường | `16-stealth-measurements.md` |
| 16.14 | §16 nói chung: không có edge đo được | `16-stealth-measurements.md` |
| 16.15 | bar breakout là 1,15% chứ không phải 8% — lỗi đơn vị | `16-stealth-measurements.md` |
| 20.1 | defect trung tâm: `sector_flow_daily` thiếu `close_idx` | `20-code-review.md` |
| 20.2 | 15 mục đã sửa trong lượt review | `20-code-review.md` |
| 22.1 | 4 luồng không render gì — 2 trong số đó chẩn đoán sai | `22-frontend-audit.md` |
| 22.2 | client gọi route đã xoá 4 tháng (`/api/agent/*`) | `22-frontend-audit.md` |
| 22.3 | hiệu năng: `lookback` 400 ở **client** ghi đè default backend | `22-frontend-audit.md` |
| 22.4 | dev server bind mọi adapter → `host: 'localhost'`, `npm run dev:lan` | `22-frontend-audit.md` |
| 22.5 | suite vitest đỏ trong khi §19 ghi là xanh | `22-frontend-audit.md` |
| 22.6 | trang chủ rỗng sau mỗi lần restart — snapshot chỉ nằm trong RAM | `22-frontend-audit.md` |
| 23.1-23.4 | 5 thứ service đã làm mà UI không với tới; `flow_z` = `flow_raw` | `23-backtest-controls.md` |
| 24.1, 24.5 | một bộ từ vựng filter; phần chưa làm | `24-filters-presets.md` |
| 25.1 | ba defect chồng nhau: feature chưa chuẩn hoá → 3/4 state sập | `25-regime-confidence.md` |
| 25.3 | filtered chứ không smoothed — đóng §20.3 P1-4 | `25-regime-confidence.md` |
| 25.4 | nhánh heuristic cũng đang nói dối (4 số hardcode) | `25-regime-confidence.md` |
| 25.5 | một đính chính của tôi, và defect hẹp hơn nằm dưới nó | `25-regime-confidence.md` |
| 25.6 | câu chữ: "HMM confidence 0.65" → "~65% khả năng giữ 5 phiên tới" | `25-regime-confidence.md` |
| 25.7 | `CONF_HORIZON` được suy ra, và đáp án gộp bị bác | `25-regime-confidence.md` |
| 25.8 | *(không tồn tại — §25.7 nhảy thẳng sang §25.9)* | — |
| 25.9 | đoạn gần đây sập: là tape, không phải model; lịch là proxy cho vol | `25-regime-confidence.md` |
| 26.1 | không có gì trong repo trả lời được câu hỏi của Tom | `26-ticker-picks.md` |
| 26.2 | xếp hạng tệ hơn ngẫu nhiên: −42,9% trong khi VNINDEX +71,3% | `26-ticker-picks.md` |
| 26.3 | picks không chậm — thẻ lệnh chưa từng ghi khung thời gian | `26-ticker-picks.md` |
| 26.5 | feed foreign-room quét sạch universe, 0 ticker | `26-ticker-picks.md` |
| 26.7 | vào lệnh ở giá mở phiên sau bỏ mất drift qua đêm | `26-ticker-picks.md` |
| 26.8 | phần còn mở của §26 | `26-ticker-picks.md` |

`§25.10`, `§23.5`, `§24.2-24.4`, `§22.7-22.11`, `§26.4`, `§26.6`, `§26.9`,
`§26.10` **vẫn có thân bài ở file này** — chúng chứa luật đang thi hành.
