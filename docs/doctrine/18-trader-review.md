# §18.1-18.5 — Trader-Lens System Review: 24 finding

> Tách khỏi `CLAUDE.md` ngày 2026-09-16 để doctrine trở lại ngân sách context
> (135.718 B nạp lại **mỗi lượt**; ngân sách của `claude/CLAUDE.md` mẹ là 10 KB).
> **Nội dung dưới đây nguyên văn** — không tóm tắt, không sửa số, không sửa ngày.
> `CLAUDE.md` giữ lại: §18.6 (hàng đợi ưu tiên, gọi tên từng finding theo số), §18.7, §18.8, và trỏ về file này.

### 18.1 Signal quality gaps
1. **[BLOCKER] Survivorship + constituent drift.** `sector_constituents` is a static top-5 by market cap. In VN, banks and brokers rotate in/out of the top-5 yearly (e.g., VIX, SHS replaced names in 2024). A frozen basket back-paints history. **Fix:** rebuild the basket monthly from point-in-time market cap and stamp `constituent_asof` on every `sector_flow_ts` row. Backtest MUST read the basket valid on each historical date.
2. **[BLOCKER] Foreign-flow noise on ETF rebalance days.** FUEVFVND and E1VFVND monthly rebalances spike `foreign_net` on names like HPG, VHM, VIC without reflecting real directional conviction. **Fix:** add an `etf_rebalance_mask` feature; zero out `foreign_net` contribution for constituents on known index review windows (HOSE quarterly, ETF monthly). Expose as `foreign_net_clean`.
3. **[EDGE] Flow z-score needs regime conditioning.** A +1.0 z20 in `risk_off` means something very different than in `risk_on`. **Fix:** compute `flow_z20_by_regime` — z-score relative to the distribution in the same HMM regime label. Stealth trigger §16.1 should use the regime-conditioned z.
4. **[EDGE] No put/call or derivatives proxy.** VN30F1M open interest and basis (futures − spot) lead the cash index by 1-3 sessions on turns. **Fix:** add `vn30f1m_basis`, `vn30f1m_oi_chg_5d` to macro_anchors; feed into ranker. Cheap win — vnstock exposes it.
5. **[EDGE] Missing margin-debt proxy.** SSI/VND/HCM publish monthly margin balances — leading indicator for broker sector and for systemic leverage. **Fix:** add `broker_margin_total_mom` as a macro anchor (manual CSV refresh monthly until scraped).
6. **[EDGE] Breadth is computed on the 5-stock basket — too narrow to be "breadth".** Breadth SMA20/50 of 5 names is almost binary. **Fix:** compute breadth on the *full sector population* (all listed tickers mapped to sector), while keeping flow on the weighted top-5 basket. Two different tools.

### 18.2 Execution & risk realism
7. **[BLOCKER] T+2.5 settlement not modeled.** VN HOSE is T+2 cash, ~T+2.5 effective. Backtest must lock capital for 2-3 sessions after a buy. Current `SectorBacktestService` assumes instantaneous recycling → overstated Sharpe. **Fix:** add `settlement_lag=2` to the backtest cash engine.
8. **[BLOCKER] No foreign ownership room (FOL) check.** Banks, retail, airports routinely hit FOL and become un-buyable by foreigners — distorts `foreign_net` (it goes to zero not because of conviction but because of cap). **Fix:** pull `foreign_room_pct` per constituent; if median room < 3%, downweight `foreign_net` signal to 0.5× for that sector.
9. **[BLOCKER] Slippage + price-band realism.** VN has ±7% daily price bands (HOSE), ±10% (HNX), ±15% (UPCoM). In strong rotations, sectors gap to ceiling with no fills. **Fix:** backtest must (a) add a `ceiling_floor_hit` flag, (b) skip fills when basket median touched ±7% of prior close, (c) apply slippage = max(0.3%, 0.5 × ATR%). No slippage = fantasy Sharpe.
10. **[BLOCKER] Tax + fee line missing.** VN: 0.1% sell tax on proceeds, 0.15–0.35% broker fee round-trip. On a 20d holding period with 60%+ turnover, this is ~60-80 bps/trade of drag. **Fix:** hardcode `fee_bps=15` per side + `sell_tax_bps=10` in backtest config, expose in risk service too.
11. **[EDGE] Vol-targeting uses sector ATR — should use portfolio vol.** Sizing each position on its own ATR ignores cross-sector correlation (banks + brokers + realty move together in VN). **Fix:** size against portfolio marginal contribution to vol using the rolling 20d correlation matrix you already compute.
12. **[EDGE] Max 3 long / 2 short cap is arbitrary.** 15 sectors × high pairwise correlation → effective independent bets ≈ 3-4. Shorting in VN cash market is impossible (only VN30 futures). **Fix:** either restrict shorts to "reduce long" (cash flat) or model shorts exclusively through VN30F1M hedging. Delete the "2 short" concept from cash leg.

### 18.3 Model & validation
13. **[BLOCKER] No walk-forward with purged/embargoed folds.** Standard CV leaks across 5-20d forward targets. **Fix:** adopt López de Prado purged k-fold with embargo = max(target horizon) + 2 on ranker training.
14. **[EDGE] Single 20d target loses nuance.** Add an ensemble target: weighted blend of `fwd_10d` (0.4) + `fwd_20d` (0.4) + `fwd_40d` (0.2). Prevents the model from overfitting a single horizon.
15. **[EDGE] Stealth §16.1 uses fixed thresholds — should be sector-specific quantiles.** Banks normally run low ATR%; energy is chronically volatile. A global "ATR% < 20d median" is unfair across sectors. **Fix:** every §16.1 cut is evaluated against the **sector's own 2y empirical quantile**, not a cross-sector number.
16. **[HYGIENE] No model drift monitor.** Ranker may silently degrade. **Fix:** nightly job logs ranker top-3 hit-rate on the last 20 sessions; Gmail alert if < baseline − 1σ for 5 consecutive days.

### 18.4 Data & ops
17. **[BLOCKER] Single-source vnstock risk.** If vnstock breaks for a day, the whole pipeline fails silently (ingest just catches). **Fix:** add a secondary HOSE scraper (cafef or ssi-iBoard) as fallback; circuit-breaker + loud Gmail alert on 2 consecutive miss.
18. **[HYGIENE] SQLite for intraday 15m flow will contend.** 15 sectors × 26 intraday bars × 252 days ≈ 100k/yr — fine. But WAL on a network mount is fragile. **Fix:** document that DB must live on a local disk; add a startup check that rejects network paths.
19. **[HYGIENE] No "as of" timestamp discipline.** A flow row should always carry `source_ts` (when the data was observed) + `ingested_ts`. Currently only one timestamp. Required for proper point-in-time backtesting. **Fix:** add `source_ts` column to `sector_flow_ts`.
20. **[HYGIENE] No kill-switch.** If risk sentinel fires repeatedly, there is no global "pause all new ACCUMULATE entries" flag. **Fix:** add `config.trading_halt` bool read at the top of `sector_signal_service.publish()`.

### 18.5 Stealth doctrine sharpening (§16 delta)
21. **[EDGE] "Foreign net ≥ 60% of last 20d" is too coarse.** A single huge block trade on day 1 can satisfy the hit-rate while flow dies for 19 days. **Fix:** require BOTH `foreign_hit_20d ≥ 0.6` AND `foreign_net_z20 ≥ +0.5`. Two independent checks.
22. **[EDGE] Add a "distribution guard" to kill stealth early.** If during stealth window any single session sees `up_vol / down_vol < 0.5` AND `foreign_net < 0`, invalidate the event (smart money is leaving). Currently stealth only resolves on price breakout or 30-day timeout — too slow.
23. **[EDGE] Track "institutional mornings" signal.** VN institutions trade disproportionately in the 09:15–10:30 window; retail dominates afternoons. Intraday 15m flow should compute `morning_share = morning_flow / daily_flow`. Rising `morning_share` during accumulation = high-conviction institutional buying. Add to `stealth_score`.
24. **[EDGE] Lead-time audit must be regime-stratified.** Average lead-time is meaningless across bull/bear. `lead_time_audit` job must bucket by HMM regime on the event start date.

