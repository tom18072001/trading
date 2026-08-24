# ============================================
# services/backtest_service.py — Sector Rotation Backtest (VN-realistic)
# ============================================
# Replaces the legacy per-symbol T+3 backtester. Simulates a LONG-ONLY sector
# rotation basket on `sector_flow_daily`, with the VN frictions from
# CLAUDE.md §18.2 that the old toy model ignored (and that were inflating Sharpe):
#   §18.2/7  T+2 cash settlement — proceeds are locked for `settlement_lag`
#            sessions, so capital cannot be instantly recycled.
#   §18.2/9  Slippage = max(0.3%, 0.5×ATR%) per fill, AND a ±7% HOSE price-band:
#            a sector that gapped to ceiling/floor that day cannot be filled.
#   §18.2/10 Broker fee per side + a sell tax on proceeds (per-trade, not a flat
#            daily constant).
#   §18.2/12 VN cash market cannot short — the long/short toy was deleted; this
#            is long-only. (Shorts, if ever modelled, belong in a VN30F1M hedge.)
# Plus §16.6 entry-timing attribution: median root-capture ratio across closed
# trades (entry price / peak price during the hold; ≤0.85 = bought near the root).

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from config import (
    BACKTEST_FEE_BPS, BACKTEST_INITIAL_CAPITAL, BACKTEST_LONG_ONLY,
    BACKTEST_PRICE_BAND_PCT, BACKTEST_SELL_TAX_BPS, BACKTEST_SETTLEMENT_LAG,
    BACKTEST_SLIPPAGE_ATR_MULT, BACKTEST_SLIPPAGE_MIN_PCT,
    MAX_ACCUMULATE_SECTORS, MAX_LONG_SECTORS,
)
from database.models import BacktestRun, MacroAnchor, SectorFlowDaily, SectorSignal

# Actions that open or hold a long position (CLAUDE.md §16.3).
LONG_ACTIONS = ("ACCUMULATE", "BUY")


@dataclass
class BacktestResult:
    name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    total_trades: int
    win_rate: float
    benchmark_return_pct: float
    equity_curve: list[dict]
    trade_log: list[dict]
    # --- §18.2 / §16.6 realism diagnostics ---
    long_only: bool = True
    settlement_lag: int = BACKTEST_SETTLEMENT_LAG
    fee_bps: float = BACKTEST_FEE_BPS
    sell_tax_bps: float = BACKTEST_SELL_TAX_BPS
    total_cost_pct: float = 0.0          # cumulative friction as % of initial capital
    ceiling_floor_skips: int = 0         # entries skipped due to ±7% band
    root_capture_ratio: float | None = None  # median entry/peak across closed trades
    # --- what was actually simulated (review 2026-08-22, P0-4) ---
    strategy_source: str = "signals"     # "signals" | "flow_z" | "flow_raw"
    benchmark_source: str = "vnindex"    # "vnindex" | "sector_mean"
    signal_dates_covered: int = 0        # days that had published signals


@dataclass
class _Position:
    value: float            # current marked-to-market value (VND)
    can_sell_idx: int       # first day-index at which T+2 allows a sale
    entry_close: float      # sector close_idx at entry (for root-capture)
    peak_close: float       # running max close_idx during the hold


class SectorBacktestService:
    def __init__(self, session: Session):
        self.session = session

    def _load_panel(self, start: str, end: str) -> pd.DataFrame:
        rows = (
            self.session.query(SectorFlowDaily)
            .filter(SectorFlowDaily.date >= start, SectorFlowDaily.date <= end)
            .order_by(SectorFlowDaily.date, SectorFlowDaily.sector_code)
            .all()
        )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([{
            "date": r.date, "sector_code": r.sector_code,
            "close_idx": r.close_idx, "return_1d": r.return_1d,
            "net_dollar_flow": r.net_dollar_flow, "atr_pct": r.atr_pct,
            "flow_z20": r.flow_z20,
        } for r in rows])

    def _load_signals(self, start: str, end: str) -> dict[str, list[str]]:
        """{date: [sector_code, ...]} of published long signals, best rank first.

        Review 2026-08-22, P0-4. The backtest used to rank by raw
        `net_dollar_flow` and never look at `sector_signals` at all -- so every
        success criterion in CLAUDE.md §16.11 / §18.7 was being measured
        against a strategy nobody trades.
        """
        rows = (
            self.session.query(SectorSignal)
            .filter(SectorSignal.date >= start, SectorSignal.date <= end,
                    SectorSignal.action.in_(LONG_ACTIONS))
            .order_by(SectorSignal.date, SectorSignal.rank)
            .all()
        )
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r.date, []).append(r.sector_code)
        return out

    def _load_benchmark(self, start: str, end: str) -> tuple[pd.Series, str]:
        """VNINDEX daily returns (CLAUDE.md §11), or a flagged fallback.

        The previous benchmark was the equal-weighted mean of all 15 sector
        `return_1d` values, which is not VNINDEX buy-and-hold and quietly
        flattered any strategy that tilted toward the larger sectors.
        """
        rows = (
            self.session.query(MacroAnchor)
            .filter(MacroAnchor.vnindex.isnot(None))
            .order_by(MacroAnchor.time)
            .all()
        )
        if rows:
            df = pd.DataFrame([
                {"date": pd.Timestamp(r.time).strftime("%Y-%m-%d"),
                 "vnindex": float(r.vnindex)}
                for r in rows
            ])
            daily = df.groupby("date")["vnindex"].last()
            daily = daily[(daily.index >= start) & (daily.index <= end)]
            if len(daily) > 5:
                return daily.pct_change().fillna(0.0), "vnindex"
        return pd.Series(dtype=float), "sector_mean"

    @staticmethod
    def _cross_sectional_z(group: pd.DataFrame, col: str) -> pd.Series:
        """Z-score within the day.

        Raw `net_dollar_flow` is un-normalised VND, so ranking 15 sectors by it
        is structurally "rank by sector size" -- BANK/REAL/STEEL win nearly
        every day and the result is a near-static portfolio dressed up as
        rotation (review 2026-08-22, P0-4).

        NOTE (2026-08-23): this does NOT fix that, and the "flow_z" strategy no
        longer uses it. `(v - mean) / sd` is a positive affine map applied
        within the same day the rows are then sorted in, and a positive affine
        map preserves order -- so ranking by this z and ranking by raw VND are
        the *identical permutation*, every day. Measured on 2026-04-09→08-23,
        both produced -25.06% and the same 330 trades. Kept only because
        `_persist` and the P0-4 tests refer to it.
        """
        v = pd.to_numeric(group[col], errors="coerce")
        sd = v.std(ddof=0)
        if not sd or pd.isna(sd) or sd == 0:
            return pd.Series(0.0, index=group.index)
        return (v - v.mean()) / sd

    @staticmethod
    def _slippage(atr_pct: float | None) -> float:
        a = float(atr_pct) if atr_pct is not None and not pd.isna(atr_pct) else 0.0
        return max(BACKTEST_SLIPPAGE_MIN_PCT, BACKTEST_SLIPPAGE_ATR_MULT * a)

    def run(
        self,
        name: str,
        start_date: str,
        end_date: str,
        initial_capital: float = BACKTEST_INITIAL_CAPITAL,
        strategy: str = "signals",
        fee_bps: float | None = None,
        sell_tax_bps: float | None = None,
        settlement_lag: int | None = None,
    ) -> BacktestResult:
        """`strategy` selects what is being simulated:

        "signals"  -- replay the ACCUMULATE/BUY signals this system actually
                      published (default). Falls back to "flow_z" when the
                      range has no published signals.
        "flow_z"   -- baseline: top-N by cross-sectional z-score of flow.
        "flow_raw" -- the pre-2026-08-22 behaviour, kept only so the two can
                      be compared. It ranks by un-normalised VND and is
                      effectively "hold the largest sectors".

        `fee_bps` / `sell_tax_bps` / `settlement_lag` override the §18.2/7,10
        config defaults for one run. They exist so a trader can price their own
        broker instead of the 15/10/T+2 assumption -- the defaults are still
        what the scheduled jobs use. Slippage and the ±7% band stay fixed:
        they are market structure, not a negotiated rate.
        """
        panel = self._load_panel(start_date, end_date)
        if panel.empty:
            raise RuntimeError("no sector_flow_daily data in range")

        signals_by_date: dict[str, list[str]] = {}
        if strategy == "signals":
            signals_by_date = self._load_signals(start_date, end_date)
            if not signals_by_date:
                print("[backtest] no published signals in range — "
                      "falling back to the flow_z baseline")
                strategy = "flow_z"
        max_positions = (MAX_LONG_SECTORS + MAX_ACCUMULATE_SECTORS
                         if strategy == "signals" else MAX_LONG_SECTORS)

        fee_bps = BACKTEST_FEE_BPS if fee_bps is None else max(0.0, float(fee_bps))
        sell_tax_bps = (BACKTEST_SELL_TAX_BPS if sell_tax_bps is None
                        else max(0.0, float(sell_tax_bps)))
        lag = int(BACKTEST_SETTLEMENT_LAG if settlement_lag is None else settlement_lag)
        lag = max(0, lag)
        fee = fee_bps / 10_000.0
        sell_tax = sell_tax_bps / 10_000.0

        dates = sorted(panel["date"].unique())
        by_date = {d: g.reset_index(drop=True) for d, g in panel.groupby("date")}

        cash = float(initial_capital)
        positions: dict[str, _Position] = {}
        pending: list[tuple[int, float]] = []   # (settle_idx, amount)
        equity_curve: list[dict] = []
        trades: list[dict] = []
        ret_history: list[float] = []
        wins = closed = 0
        total_cost = 0.0
        ceiling_skips = 0
        root_caps: list[float] = []
        prev_equity = float(initial_capital)

        for t, date in enumerate(dates):
            group = by_date[date]

            # 1) Release settled sale proceeds
            still_pending = []
            for settle_idx, amt in pending:
                if settle_idx <= t:
                    cash += amt
                else:
                    still_pending.append((settle_idx, amt))
            pending = still_pending

            # 2) Mark held positions to market on today's return
            ret_by = dict(zip(group["sector_code"], group["return_1d"]))
            close_by = dict(zip(group["sector_code"], group["close_idx"]))
            for code, pos in positions.items():
                r = ret_by.get(code)
                if r is not None and not pd.isna(r):
                    pos.value *= (1.0 + float(r))
                c = close_by.get(code)
                if c is not None and not pd.isna(c):
                    pos.peak_close = max(pos.peak_close, float(c))

            # 3) Target set, excluding price-band gap days
            if strategy == "signals":
                wanted = signals_by_date.get(date, [])
                ranked = (group.set_index("sector_code")
                               .reindex([c for c in wanted if c in set(group["sector_code"])])
                               .reset_index())
            elif strategy == "flow_z":
                # `flow_z20` is the per-sector z of its OWN 20d flow history --
                # "is this sector unusually bought for itself", which is what
                # §16.2 means by flow z and what makes a small sector reachable.
                # The old cross-sectional z here could not do that: see the note
                # on _cross_sectional_z. Sectors with no z yet sort last rather
                # than ahead of a genuine +2σ.
                g = group.copy()
                g["_z"] = pd.to_numeric(g["flow_z20"], errors="coerce")
                ranked = g.sort_values("_z", ascending=False, na_position="last")
            else:  # flow_raw — legacy behaviour, size-biased
                ranked = group.sort_values("net_dollar_flow", ascending=False)

            target: list[str] = []
            for _, row in ranked.iterrows():
                if len(target) >= max_positions:
                    break
                code = row["sector_code"]
                r1d = row["return_1d"]
                gapped = (r1d is not None and not pd.isna(r1d)
                          and abs(float(r1d)) >= BACKTEST_PRICE_BAND_PCT)
                if gapped and code not in positions:
                    ceiling_skips += 1   # can't get filled at ceiling/floor
                    continue
                target.append(code)
            target_set = set(target)

            # 4) SELL held sectors no longer in target (respecting T+2)
            for code in list(positions.keys()):
                if code in target_set:
                    continue
                pos = positions[code]
                if t < pos.can_sell_idx:
                    continue   # not yet settled — cannot sell
                proceeds = pos.value
                slip = self._slippage(_atr(group, code))
                cost = proceeds * (fee + sell_tax + slip)
                total_cost += cost
                net = proceeds - cost
                pending.append((t + lag, net))
                closed += 1
                c = close_by.get(code, pos.peak_close)
                if pos.peak_close > 0 and pos.entry_close > 0:
                    root_caps.append(pos.entry_close / pos.peak_close)
                # win = exited above entry close
                if c and pos.entry_close and c > pos.entry_close:
                    wins += 1
                trades.append({"date": date, "sector": code, "side": "SELL",
                               "proceeds": round(proceeds, 2), "cost": round(cost, 2)})
                del positions[code]

            # 5) BUY new target sectors with available settled cash
            buys = [c for c in target if c not in positions]
            if buys and cash > 0:
                alloc_each = cash / len(buys)
                for code in buys:
                    if cash <= 0:
                        break
                    alloc = min(alloc_each, cash)
                    slip = self._slippage(_atr(group, code))
                    cost = alloc * (fee + slip)
                    total_cost += cost
                    cash -= alloc
                    positions[code] = _Position(
                        value=alloc - cost,
                        can_sell_idx=t + lag,
                        entry_close=float(close_by.get(code) or 0.0),
                        peak_close=float(close_by.get(code) or 0.0),
                    )
                    trades.append({"date": date, "sector": code, "side": "BUY",
                                   "alloc": round(alloc, 2), "cost": round(cost, 2)})

            # 6) Equity = settled cash + unsettled proceeds + position MTM
            equity = cash + sum(a for _, a in pending) + sum(p.value for p in positions.values())
            equity_curve.append({"date": date, "equity": equity})
            ret_history.append(equity / prev_equity - 1.0 if prev_equity else 0.0)
            prev_equity = equity

        ret_arr = np.asarray(ret_history)
        sharpe = float(np.sqrt(252) * ret_arr.mean() / ret_arr.std()) if ret_arr.std() > 0 else 0.0
        eq_series = pd.Series([p["equity"] for p in equity_curve])
        peak = eq_series.cummax()
        max_dd = float(((eq_series - peak) / peak).min()) if not eq_series.empty else 0.0
        final_equity = float(eq_series.iloc[-1]) if not eq_series.empty else float(initial_capital)
        total_ret = (final_equity / initial_capital - 1) * 100

        bench_ret, bench_source = self._load_benchmark(start_date, end_date)
        if bench_ret.empty:
            bench_ret = panel.groupby("date")["return_1d"].mean().fillna(0)
        bench_total = float((1 + bench_ret).prod() - 1) * 100

        # Benchmark as a *curve*, not just a scalar. Only the total was returned
        # before, so the chart had one line and "did it beat VNINDEX" was a
        # subtraction the reader had to do in their head -- and it hid *when*
        # the strategy lost, which is the whole point of looking at a chart.
        # Rebased to the same initial capital so both lines share one axis.
        bench_equity = (1.0 + bench_ret).cumprod() * initial_capital
        for point in equity_curve:
            b = bench_equity.get(point["date"])
            point["benchmark"] = (None if b is None or pd.isna(b) else float(b))

        result = BacktestResult(
            name=name, start_date=start_date, end_date=end_date,
            initial_capital=initial_capital, final_capital=final_equity,
            total_return_pct=total_ret, sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd * 100, total_trades=len(trades),
            win_rate=(wins / closed) if closed else 0.0,
            benchmark_return_pct=bench_total,
            equity_curve=equity_curve, trade_log=trades,
            long_only=BACKTEST_LONG_ONLY, settlement_lag=lag,
            fee_bps=fee_bps, sell_tax_bps=sell_tax_bps,
            total_cost_pct=(total_cost / initial_capital) * 100 if initial_capital else 0.0,
            ceiling_floor_skips=ceiling_skips,
            root_capture_ratio=(float(np.median(root_caps)) if root_caps else None),
            strategy_source=strategy,
            benchmark_source=bench_source,
            signal_dates_covered=len(signals_by_date),
        )
        self._persist(result)
        return result

    def _persist(self, r: BacktestResult) -> None:
        run = BacktestRun(
            name=r.name, strategy=f"rotation_long_only:{r.strategy_source}",
            start_date=r.start_date, end_date=r.end_date,
            initial_capital=r.initial_capital, final_capital=r.final_capital,
            total_trades=r.total_trades, win_rate=r.win_rate,
            sharpe_ratio=r.sharpe_ratio, max_drawdown_pct=r.max_drawdown_pct,
            total_return_pct=r.total_return_pct, benchmark_return_pct=r.benchmark_return_pct,
            params=json.dumps({
                "max_long": MAX_LONG_SECTORS, "long_only": r.long_only,
                "settlement_lag": r.settlement_lag, "fee_bps": r.fee_bps,
                "sell_tax_bps": r.sell_tax_bps,
                "slippage_min_pct": BACKTEST_SLIPPAGE_MIN_PCT,
                "slippage_atr_mult": BACKTEST_SLIPPAGE_ATR_MULT,
                "price_band_pct": BACKTEST_PRICE_BAND_PCT,
                "total_cost_pct": r.total_cost_pct,
                "ceiling_floor_skips": r.ceiling_floor_skips,
                "root_capture_ratio": r.root_capture_ratio,
                "strategy_source": r.strategy_source,
                "benchmark_source": r.benchmark_source,
                "signal_dates_covered": r.signal_dates_covered,
            }),
            equity_curve=json.dumps(r.equity_curve),
            trade_log=json.dumps(r.trade_log[:500]),
        )
        self.session.add(run)
        self.session.commit()


def _atr(group: pd.DataFrame, code: str) -> float | None:
    """ATR% for a sector on the given day's group, or None."""
    sub = group.loc[group["sector_code"] == code, "atr_pct"]
    if sub.empty:
        return None
    v = sub.iloc[0]
    return None if pd.isna(v) else float(v)


# Backwards-compat alias
BacktestService = SectorBacktestService
