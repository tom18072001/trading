"""PicksUniverseService — dynamic per-ticker universe for report + insight.

Builds ONE validated snapshot per trading day, cached in memory. Both the
email report (generate_report.py) and the Daily Insight API
(api/routers/insight.py) consume this service as the single source of truth
for per-ticker BUY/ACCUMULATE picks. Per CLAUDE.md §2 the legacy
`_legacy_stock_prices` + `_legacy_stock_features` tables are NOT read.

Pipeline (see specs/picks_universe.md for details):
  1. Discovery    — vnstock Listing().all_symbols(), HOSE-only.
  2. Classify     — sector_constituents override → ICB_TO_SECTOR → VN keyword.
  3. Capability1  — batch price_board → reject foreign_room ≤ 0.
  4. Capability2  — parallel OHLCV fetch (70 sessions), reject if
                    history < MIN_HISTORY_SESSIONS or dv_20d < MIN_DV_20D_VND.
  5. Indicators   — analysis.feature_engineering.build_feature_set.
  6. Score        — services.picks_scoring.score_ticker.
  7. Stop/Target  — services.picks_scoring.compute_stop_target_rr (SWING).
  8. Group        — by sector_code, sorted desc by score.

Freshness contract — is_valid == True iff:
  - as_of == latest SectorSignal.date, and signal ≤ 2 calendar days old
  - ohlcv_fail_pct < UNIVERSE_OHLCV_FAIL_PCT_MAX
  - capability_pass_count ≥ 50
  - every BUY/ACCUMULATE sector has ≥ 1 ticker with is_valid_buy=True
"""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable

import pandas as pd

from config import (
    DATA_SOURCE,
    ICB_TO_SECTOR,
    MIN_DV_20D_VND,
    MIN_FOREIGN_ROOM_PCT,
    MIN_HISTORY_SESSIONS,
    SECTORS,
    UNIVERSE_BUILD_WORKERS,
    UNIVERSE_MIN_PASS,
    UNIVERSE_OHLCV_FAIL_PCT_MAX,
    UNIVERSE_PICKS_FLOOR,
)
from database.connection import SessionLocal
from database.models import SectorConstituent, SectorSignal
from services.picks_scoring import (
    PickProfile,
    compute_stop_target_rr,
    is_valid_long_pick,
    score_ticker,
)

log = logging.getLogger(__name__)


# =====================================================================
#  Dataclasses
# =====================================================================

@dataclass
class TickerRow:
    symbol: str
    sector_code: str
    close: float
    ret_5d: float | None = None
    ret_20d: float | None = None
    atr_pct: float | None = None      # percent units (2.5 == 2.5%)
    rsi_14: float | None = None
    macd_hist: float | None = None
    bb_upper: float | None = None
    bb_lower: float | None = None
    price_to_sma_20: float | None = None
    price_to_sma_50: float | None = None
    volume_ratio_20: float | None = None
    adx_14: float | None = None
    bb_position: float | None = None
    volatility_20d: float | None = None
    dv_20d: float = 0.0
    foreign_room_pct: float | None = None
    score: int = 0
    stop: float | None = None
    target: float | None = None
    rr: float | None = None
    is_valid_buy: bool = False
    reject_reason: str | None = None
    # Last ~30 sessions of OHLCV for mini-chart rendering in email report.
    # Kept intentionally compact (list of dicts) to avoid pandas in callers.
    daily_prices: list[dict[str, Any]] = field(default_factory=list)

    def as_picks_dict(self) -> dict[str, Any]:
        """Compatibility projection consumed by generate_report.py's
        rendering code (which expects `sym`, `sector`, `close`, etc.)."""
        return {
            "sym": self.symbol,
            "sector": SECTORS.get(self.sector_code, self.sector_code),
            "sector_code": self.sector_code,
            "close": self.close,
            "ret_5d": self.ret_5d or 0.0,
            "dv": self.dv_20d,
            "dv_recent": self.dv_20d,
            "score": self.score,
            "rsi": self.rsi_14,
            "macd_h": self.macd_hist,
            "adx": self.adx_14,
            "vr20": self.volume_ratio_20,
            "atr_pct": self.atr_pct,
            "vol20": self.volatility_20d,
            "r20": self.ret_20d,
            "bb_pos": self.bb_position,
            "bb_upper": self.bb_upper,
            "bb_lower": self.bb_lower,
            "sma20": (1 + (self.price_to_sma_20 or 0)),
            "notes": "",
        }


@dataclass
class FreshnessReport:
    as_of: date
    built_at: datetime
    universe_size: int = 0
    capability_pass_count: int = 0
    capability_fail_count: int = 0
    ohlcv_fail_pct: float = 0.0
    # Split of capability_fail_count: true source/fetch failures vs legitimate
    # quality rejects (short history, thin liquidity). Only the former drives
    # the DEGRADED gate — a stock correctly excluded for <5B/day turnover is a
    # healthy filter, not a data outage. (2026-06-19 fix)
    ohlcv_fetch_fail_count: int = 0
    quality_reject_count: int = 0
    sectors_with_picks: set[str] = field(default_factory=set)
    sectors_missing_picks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "built_at": self.built_at.isoformat() if self.built_at else None,
            "universe_size": self.universe_size,
            "capability_pass_count": self.capability_pass_count,
            "capability_fail_count": self.capability_fail_count,
            "ohlcv_fail_pct": round(self.ohlcv_fail_pct, 3),
            "ohlcv_fetch_fail_count": self.ohlcv_fetch_fail_count,
            "quality_reject_count": self.quality_reject_count,
            "sectors_with_picks": sorted(self.sectors_with_picks),
            "sectors_missing_picks": self.sectors_missing_picks,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class PickEntry:
    """A single long or short pick with reasoning for OpenClaw/frontend."""
    symbol: str
    sector_code: str
    sector_name: str
    action: str              # BUY | SELL
    close: float
    stop: float | None
    target: float | None
    rr: float | None
    score: int
    atr_pct: float | None
    upside_pct: float | None
    downside_pct: float | None
    foreign_room_pct: float | None
    dv_20d: float
    technical_bits: list[str]  # ["RSI 58", "MACD+", "above SMA20", "Vol 1.4x"]
    thesis: str                # 1-line VN rationale
    news: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "sector_code": self.sector_code,
            "sector_name": self.sector_name,
            "action": self.action,
            "close": self.close,
            "stop": self.stop,
            "target": self.target,
            "rr": self.rr,
            "score": self.score,
            "atr_pct": self.atr_pct,
            "upside_pct": self.upside_pct,
            "downside_pct": self.downside_pct,
            "foreign_room_pct": self.foreign_room_pct,
            "dv_20d": self.dv_20d,
            "technical_bits": self.technical_bits,
            "thesis": self.thesis,
            "news": self.news,
        }


@dataclass
class UniverseSnapshot:
    as_of: date
    built_at: datetime
    tickers: dict[str, TickerRow]
    by_sector: dict[str, list[TickerRow]]
    freshness: FreshnessReport
    is_valid: bool = False
    # Top-N BUY/SELL picks with news + thesis. Empty when is_valid=False or
    # when no sector has a BUY/SELL signal from the ranker.
    top_buys: list[PickEntry] = field(default_factory=list)
    top_sells: list[PickEntry] = field(default_factory=list)


# =====================================================================
#  Helpers
# =====================================================================

_VN_KEYWORD_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ngân hàng", re.I), "BANK"),
    (re.compile(r"chứng khoán", re.I), "BROK"),
    (re.compile(r"bảo hiểm", re.I), "INSUR"),
    (re.compile(r"bất động sản|địa ốc|nhà đất", re.I), "REAL"),
    (re.compile(r"thép|tôn\b|vật liệu xây", re.I), "STEEL"),
    (re.compile(r"dầu khí|xăng dầu|khí đốt", re.I), "OIL"),
    (re.compile(r"điện lực|năng lượng|nhiệt điện|thủy điện", re.I), "POWER"),
    (re.compile(r"công nghệ|phần mềm|viễn thông|FPT|điện tử", re.I), "TECH"),
    (re.compile(r"hàng không|logistic|vận tải|cảng|sân bay", re.I), "LOGIS"),
    (re.compile(r"bán lẻ|siêu thị|thương mại điện", re.I), "RETAIL"),
    (re.compile(r"thực phẩm|đồ uống|sữa|bia|rượu", re.I), "FOOD"),
    (re.compile(r"hóa chất|phân bón|hoá chất", re.I), "CHEM"),
    (re.compile(r"dệt may|may mặc|sợi|dệt", re.I), "TEXT"),
    (re.compile(r"cao su|nhựa|săm lốp", re.I), "RUBBER"),
    (re.compile(r"thủy sản|thuỷ sản|thuỷ hải sản|cá tra|tôm", re.I), "FISH"),
]


def _technical_bits(r: "TickerRow") -> list[str]:
    """Compose human-readable technical tags for a pick (used in thesis +
    frontend tag chips)."""
    bits: list[str] = []
    if r.price_to_sma_20 is not None:
        bits.append("above SMA20" if r.price_to_sma_20 > 0 else "below SMA20")
    if r.price_to_sma_50 is not None:
        bits.append("above SMA50" if r.price_to_sma_50 > 0 else "below SMA50")
    if r.rsi_14 is not None:
        if r.rsi_14 > 70:
            bits.append(f"RSI {r.rsi_14:.0f} OB")
        elif r.rsi_14 < 30:
            bits.append(f"RSI {r.rsi_14:.0f} OS")
        else:
            bits.append(f"RSI {r.rsi_14:.0f}")
    if r.macd_hist is not None:
        bits.append("MACD+" if r.macd_hist > 0 else "MACD-")
    if r.adx_14 is not None and r.adx_14 > 20:
        bits.append(f"ADX {r.adx_14:.0f}")
    if r.volume_ratio_20 is not None:
        if r.volume_ratio_20 > 1.3 or r.volume_ratio_20 < 0.7:
            bits.append(f"Vol {r.volume_ratio_20:.1f}x")
    if r.atr_pct is not None:
        bits.append(f"ATR% {r.atr_pct:.1f}")
    return bits


def _compose_thesis(r: "TickerRow", action: str) -> str:
    """One-line VN rationale. Caller enriches with news bullets separately."""
    bits = _technical_bits(r)
    tag = ", ".join(bits[:4]) if bits else "clean technicals"
    if action == "BUY":
        rr_txt = f", R:R {r.rr:.1f}" if r.rr else ""
        return (f"Composite score {r.score}. {tag}{rr_txt}. "
                f"T+ swing: mua {r.close:.1f}, stop {r.stop:.1f}, target {r.target:.1f}.")
    # SELL
    return (f"Composite score {r.score}. {tag}. "
            f"Đề xuất thoát / tránh: giá {r.close:.1f}, stop-out nếu thủng {r.stop:.1f}.")


def _latest_signal_date() -> date | None:
    """SectorSignal.date is stored as VARCHAR(20) 'YYYY-MM-DD' — coerce to date."""
    sess = SessionLocal()
    try:
        row = sess.query(SectorSignal.date).order_by(SectorSignal.date.desc()).first()
        if row is None or row[0] is None:
            return None
        val = row[0]
        if isinstance(val, date):
            return val
        try:
            return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    finally:
        sess.close()


def _load_constituent_override() -> dict[str, str]:
    """Return {symbol: sector_code} for every active row in sector_constituents."""
    sess = SessionLocal()
    try:
        out: dict[str, str] = {}
        for r in sess.query(SectorConstituent).filter(SectorConstituent.active.is_(True)).all():
            out[r.symbol] = r.sector_code
        return out
    finally:
        sess.close()


def _classify_sector(
    symbol: str,
    organ_name: str,
    icb: str | None,
    overrides: dict[str, str],
) -> str | None:
    """Priority: override → ICB → VN keyword. Returns sector_code or None."""
    if symbol in overrides:
        return overrides[symbol]
    if icb:
        # ICB codes can be 4-digit supersector or 8-digit subsector; take prefix
        code4 = icb[:4]
        if code4 in ICB_TO_SECTOR:
            return ICB_TO_SECTOR[code4]
    name = organ_name or ""
    for rx, sec in _VN_KEYWORD_RULES:
        if rx.search(name):
            return sec
    return None


def _pick_first_col(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _fetch_price_board_chunk(symbols: list[str]) -> pd.DataFrame:
    """Batch price_board for up to ~50 symbols. Returns empty DataFrame on
    failure (caller handles fallback per-symbol)."""
    _kbs_throttle()
    try:
        from utils.vn_api import price_board
        df = price_board(symbols)
        if df is None or df.empty:
            return pd.DataFrame()
        # Flatten multi-level columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["_".join(str(x) for x in c if x).lower() for c in df.columns]
        df.columns = [str(c).lower() for c in df.columns]
        return df
    except BaseException as e:
        log.warning("[picks-universe] price_board chunk failed: %s", e)
        return pd.DataFrame()


# --- Rate limiter ------------------------------------------------------------
# KBS guest tier: 20 req/min. Token-bucket-lite — we cap to 18 calls/60s to
# leave headroom for price_board chunks. Thread-safe via a single deque of
# timestamps protected by a lock.
import collections as _collections
_KBS_CALL_WINDOW: _collections.deque[float] = _collections.deque()
_KBS_LOCK = threading.Lock()
_KBS_MAX_PER_MIN = 18
_KBS_WINDOW_SEC = 60.0


def _kbs_throttle() -> None:
    """Block just long enough to keep < 18 calls in any 60-second window."""
    with _KBS_LOCK:
        now = time.monotonic()
        # evict timestamps older than the window
        while _KBS_CALL_WINDOW and (now - _KBS_CALL_WINDOW[0]) > _KBS_WINDOW_SEC:
            _KBS_CALL_WINDOW.popleft()
        if len(_KBS_CALL_WINDOW) >= _KBS_MAX_PER_MIN:
            sleep_for = _KBS_WINDOW_SEC - (now - _KBS_CALL_WINDOW[0]) + 0.2
            if sleep_for > 0:
                log.debug("[picks-universe] KBS rate-limit sleep %.1fs", sleep_for)
                # release lock during sleep so other threads don't stack
                _KBS_LOCK.release()
                try:
                    time.sleep(sleep_for)
                finally:
                    _KBS_LOCK.acquire()
                now = time.monotonic()
                while _KBS_CALL_WINDOW and (now - _KBS_CALL_WINDOW[0]) > _KBS_WINDOW_SEC:
                    _KBS_CALL_WINDOW.popleft()
        _KBS_CALL_WINDOW.append(time.monotonic())


def _fetch_ohlcv(symbol: str, start: str, end: str, retries: int = 1) -> pd.DataFrame:
    """Wrapper over data.data_fetcher.get_stock_history. Returns empty df on failure.

    Single-source (vnstock/KBS) is flaky under load — a transient timeout on
    one worker shouldn't permanently drop a liquid name and inflate
    ohlcv_fail_pct. Retry once (with the KBS throttle between attempts) before
    giving up. (2026-06-19 fix — §18.4/17 robustness)
    """
    from data.data_fetcher import get_stock_history
    last_err: BaseException | None = None
    for attempt in range(retries + 1):
        _kbs_throttle()
        try:
            df = get_stock_history(symbol, start_date=start, end_date=end, source=DATA_SOURCE, interval="1D")
            if df is None or df.empty:
                last_err = None
                continue  # retry — empty can be a transient KBS hiccup
            # Normalize column names
            df.columns = [str(c).lower() for c in df.columns]
            if "time" in df.columns:
                df = df.sort_values("time").reset_index(drop=True)
            return df
        except BaseException as e:
            last_err = e
            log.debug("[picks-universe] OHLCV fail %s (attempt %d): %s", symbol, attempt + 1, e)
    if last_err is not None:
        log.debug("[picks-universe] OHLCV gave up %s: %s", symbol, last_err)
    return pd.DataFrame()


def _last(series: pd.Series) -> float | None:
    if series is None or len(series) == 0:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


def _build_ticker_row(symbol: str, sector_code: str, ohlcv: pd.DataFrame,
                     foreign_room_pct: float | None, dv_20d: float) -> TickerRow | None:
    """Run feature engineering + scoring for a single ticker. Returns None if
    indicator computation failed (insufficient data post-dropna)."""
    try:
        from analysis.feature_engineering import (
            add_adx, add_atr, add_bollinger_bands, add_custom_features,
            add_macd, add_moving_averages, add_rsi,
        )
    except Exception as e:  # pragma: no cover
        log.error("[picks-universe] feature_engineering import failed: %s", e)
        return None

    df = ohlcv.copy()
    try:
        df = add_moving_averages(df)
        df = add_rsi(df)
        df = add_macd(df)
        df = add_bollinger_bands(df)
        df = add_atr(df)
        df = add_adx(df)
        df = add_custom_features(df)
    except Exception as e:
        log.debug("[picks-universe] indicator fail %s: %s", symbol, e)
        return None

    if df.empty:
        return None

    close = _last(df["close"]) if "close" in df.columns else None
    if not close or close <= 0:
        return None

    row = TickerRow(
        symbol=symbol,
        sector_code=sector_code,
        close=close,
        ret_5d=_last(df.get("return_5d", pd.Series(dtype=float))),
        ret_20d=_last(df.get("return_20d", pd.Series(dtype=float))),
        atr_pct=(_last(df.get("ATR_14_pct", pd.Series(dtype=float))) or 0) * 100,
        rsi_14=_last(df.get("RSI_14", pd.Series(dtype=float))),
        macd_hist=_last(df.get("MACD_hist", pd.Series(dtype=float))),
        bb_upper=_last(df.get("BB_upper", pd.Series(dtype=float))),
        bb_lower=_last(df.get("BB_lower", pd.Series(dtype=float))),
        price_to_sma_20=_last(df.get("price_to_SMA_20", pd.Series(dtype=float))),
        price_to_sma_50=_last(df.get("price_to_SMA_50", pd.Series(dtype=float))),
        volume_ratio_20=_last(df.get("volume_ratio_20", pd.Series(dtype=float))),
        adx_14=_last(df.get("ADX_14", pd.Series(dtype=float))),
        bb_position=_last(df.get("BB_position", pd.Series(dtype=float))),
        volatility_20d=_last(df.get("volatility_20d", pd.Series(dtype=float))),
        dv_20d=dv_20d,
        foreign_room_pct=foreign_room_pct,
    )

    # Normalize ret_5d/ret_20d to percent units for downstream code that
    # expects e.g. `+2.58%`. pct_change returns fractions — multiply.
    if row.ret_5d is not None:
        row.ret_5d *= 100
    if row.ret_20d is not None:
        row.ret_20d *= 100

    # Composite score
    row.score = score_ticker({
        "rsi_14": row.rsi_14,
        "macd_hist": row.macd_hist,
        "price_to_sma_20": row.price_to_sma_20,
        "price_to_sma_50": row.price_to_sma_50,
        "adx_14": row.adx_14,
        "volume_ratio_20": row.volume_ratio_20,
    })

    # Stop / target / RR — default to SWING profile; callers needing TPLUS
    # recompute via compute_stop_target_rr() directly.
    stop, target, rr, err = compute_stop_target_rr({
        "close": row.close,
        "atr_pct": row.atr_pct,
        "bb_upper": row.bb_upper,
        "bb_lower": row.bb_lower,
    }, PickProfile.SWING)
    row.stop, row.target, row.rr = stop, target, rr

    ok, reason = is_valid_long_pick(row.close, target, stop)
    row.is_valid_buy = ok
    row.reject_reason = reason

    # Stash compact OHLCV tail for mini-chart rendering (kept < 30 rows)
    if {"time", "open", "close", "volume"}.issubset(df.columns):
        tail = df.tail(30)[["time", "open", "close", "volume"]].to_dict("records")
        # Normalize time to ISO string for JSON-safety
        for rec in tail:
            t = rec.get("time")
            rec["time"] = t.isoformat() if hasattr(t, "isoformat") else str(t)
            rec["open"] = float(rec.get("open") or 0)
            rec["close"] = float(rec.get("close") or 0)
            rec["volume"] = float(rec.get("volume") or 0)
        row.daily_prices = tail

    return row


# =====================================================================
#  Service
# =====================================================================

class PicksUniverseService:
    def __init__(self) -> None:
        self._cache: UniverseSnapshot | None = None
        self._lock = threading.RLock()

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None
            log.info("[picks-universe] cache invalidated")

    def peek(self) -> UniverseSnapshot | None:
        """Return the cached snapshot WITHOUT ever building (non-blocking).

        Read-path endpoints (/api/insight/daily) must use this instead of
        get_snapshot(): a cold cache there used to trigger the full KBS
        fan-out synchronously inside the request, hanging the page for
        2-10 min (observed 2026-07-19). Cold cache -> caller serves a
        stale/empty payload and the async /refresh runner does the build.
        """
        with self._lock:
            return self._cache

    def get_snapshot(self, force: bool = False,
                     on_progress: "Callable[[int, int, str], None] | None" = None
                     ) -> UniverseSnapshot:
        """Return the cached snapshot or rebuild it.

        `on_progress(done, total, note)` — optional callback fired once per
        completed OHLCV future during the (slow) Stage D fan-out. Used by the
        async /api/insight/refresh runner to stream stage % back to the UI.
        Called from the ThreadPoolExecutor callback thread, so implementations
        must be thread-safe. Never raises out of the caller: a callback error
        is swallowed so a buggy UI hook can't kill the build.
        """
        with self._lock:
            latest = _latest_signal_date()
            if (
                not force
                and self._cache is not None
                and self._cache.as_of == latest
            ):
                return self._cache
            try:
                snap = self._build(latest, on_progress=on_progress)
                # Anti-blank-page guard (2026-06-19, §18.4/17): a forced rebuild
                # that comes back empty — vnstock Listing/discovery returned
                # nothing, or every OHLCV fetch failed in a source outage —
                # must NOT overwrite a good prior snapshot. Otherwise the UI's
                # /refresh wipes its picks to a blank page while /daily (cached)
                # still had them. Keep the last good cache, flagged stale.
                if (
                    not snap.tickers
                    and self._cache is not None
                    and self._cache.tickers
                ):
                    log.warning(
                        "[picks-universe] rebuild empty (%s) — keeping last good "
                        "snapshot (%d tickers, as_of=%s)",
                        "; ".join(snap.freshness.errors) or "0 tickers",
                        len(self._cache.tickers), self._cache.as_of,
                    )
                    self._cache.is_valid = False
                    self._cache.freshness.errors.append(
                        "rebuild returned empty — serving last good snapshot "
                        f"(as_of {self._cache.as_of})"
                    )
                    return self._cache
                self._cache = snap
                return snap
            except BaseException as e:
                log.exception("[picks-universe] build failed: %s", e)
                if self._cache is not None:
                    # surface a stale snapshot with an added error note
                    self._cache.freshness.errors.append(f"build failed: {e}")
                    self._cache.is_valid = False
                    return self._cache
                # no prior cache — synthesize an empty invalid snapshot
                fr = FreshnessReport(
                    as_of=latest or date.today(),
                    built_at=datetime.now(),
                    errors=[f"build failed: {e}"],
                )
                return UniverseSnapshot(
                    as_of=fr.as_of, built_at=fr.built_at,
                    tickers={}, by_sector={c: [] for c in SECTORS},
                    freshness=fr, is_valid=False,
                )

    # ---------- build pipeline ----------

    def _build(self, as_of: date | None,
               on_progress: "Callable[[int, int, str], None] | None" = None
               ) -> UniverseSnapshot:
        t0 = time.monotonic()
        as_of_eff = as_of or date.today()
        fr = FreshnessReport(as_of=as_of_eff, built_at=datetime.now())
        log.info("[picks-universe] build start as_of=%s", as_of_eff)

        def _safe_progress(done: int, total: int, note: str = "") -> None:
            if on_progress is None:
                return
            try:
                on_progress(done, total, note)
            except BaseException as cb_err:  # pragma: no cover
                log.debug("[picks-universe] progress cb error: %s", cb_err)

        # --- Stage A: discovery ---
        syms_df = self._discover_hose()
        if syms_df.empty:
            fr.errors.append("Listing unavailable or returned empty")
            return UniverseSnapshot(
                as_of=as_of_eff, built_at=fr.built_at,
                tickers={}, by_sector={c: [] for c in SECTORS},
                freshness=fr, is_valid=False,
            )
        fr.universe_size = len(syms_df)
        log.info("[picks-universe] stage A: %d constituent symbols", fr.universe_size)

        # --- Stage B: sector_code already pinned by _discover_hose() ---
        # The constituent path bypasses ICB/keyword classification — each row
        # carries a `sector_code_hint` from PROXY_BASKETS or sector_constituents.
        classified: list[tuple[str, str, str]] = [
            (str(r["symbol"]).upper().strip(), str(r["sector_code_hint"]), "")
            for _, r in syms_df.iterrows()
            if r.get("symbol") and r.get("sector_code_hint")
        ]
        log.info("[picks-universe] stage B: %d pre-classified", len(classified))

        # --- Stage C: capability filter pass 1 (foreign_room) ---
        syms_all = [s for s, _, _ in classified]
        room_by_sym = self._fetch_foreign_room(syms_all)
        cap1_pass = [(s, sec) for (s, sec, _) in classified
                     if (room_by_sym.get(s) is None or room_by_sym.get(s, 0) > MIN_FOREIGN_ROOM_PCT)]
        # room=None means we couldn't verify — keep it rather than drop (foreign_net
        # signal may be weaker but universe presence is OK). This mirrors the
        # degraded-mode philosophy of Stage B.
        log.info("[picks-universe] stage C1: %d pass foreign_room filter", len(cap1_pass))

        # --- Stage D: capability filter pass 2 + OHLCV (parallel) ---
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=110)).strftime("%Y-%m-%d")  # ~70 bd
        tickers: dict[str, TickerRow] = {}
        fetch_failed = 0     # true source/fetch failures (empty df / exception)
        quality_reject = 0   # legitimate filters (short history, thin liquidity)
        attempted = len(cap1_pass)

        def _process_one(sym_sec: tuple[str, str]) -> tuple[TickerRow | None, str]:
            """Returns (row, reason). reason ∈ {ok, fetch_fail, short_history,
            no_cols, low_liquidity, indicator_fail}. Only `fetch_fail` counts as
            a data-source failure; the rest are healthy quality filters."""
            sym, sec = sym_sec
            df = _fetch_ohlcv(sym, start, end)
            if df.empty:
                return None, "fetch_fail"
            if len(df) < MIN_HISTORY_SESSIONS:
                return None, "short_history"
            if "close" not in df.columns or "volume" not in df.columns:
                return None, "no_cols"
            # KBS returns close in THOUSAND VND units (e.g. HPG close=27.95 == 27,950 VND/share).
            # Normalize to full VND so MIN_DV_20D_VND in config is a realistic
            # threshold. VCI previously returned the same convention; if a
            # future source returns raw VND (close ≥ 1000 typical), the *1000
            # coefficient here would need switching — gate per-source if that
            # happens.
            dv = (df["close"] * 1000 * df["volume"]).tail(20).mean()
            if pd.isna(dv) or dv < MIN_DV_20D_VND:
                return None, "low_liquidity"
            row = _build_ticker_row(sym, sec, df, room_by_sym.get(sym), float(dv))
            return (row, "ok") if row is not None else (None, "indicator_fail")

        total_futures = len(cap1_pass)
        _safe_progress(0, total_futures, "bắt đầu fetch OHLCV")
        with ThreadPoolExecutor(max_workers=UNIVERSE_BUILD_WORKERS) as pool:
            futures = {pool.submit(_process_one, ss): ss for ss in cap1_pass}
            completed = 0
            for fut in as_completed(futures, timeout=max(240, 20 * len(futures) // max(UNIVERSE_BUILD_WORKERS, 1))):
                sym, sec = futures[fut]
                try:
                    row, reason = fut.result(timeout=30)
                except BaseException as e:
                    log.debug("[picks-universe] ohlcv future fail %s: %s", sym, e)
                    fetch_failed += 1
                    completed += 1
                    _safe_progress(completed, total_futures, f"{sym} fail")
                    continue
                completed += 1
                if row is None:
                    if reason == "fetch_fail":
                        fetch_failed += 1
                    else:
                        quality_reject += 1
                    _safe_progress(completed, total_futures, f"{sym} {reason}")
                    continue
                tickers[sym] = row
                _safe_progress(completed, total_futures, sym)

        fr.capability_pass_count = len(tickers)
        fr.capability_fail_count = attempted - len(tickers)
        fr.ohlcv_fetch_fail_count = fetch_failed
        fr.quality_reject_count = quality_reject
        # ohlcv_fail_pct now reflects ONLY true source failures — a thinly-traded
        # name correctly filtered for liquidity no longer trips the DEGRADED gate.
        fr.ohlcv_fail_pct = (fetch_failed / attempted) if attempted else 0.0
        log.info("[picks-universe] stage D: %d pass, %d fetch_fail, %d quality_reject "
                 "(ohlcv_fail_pct=%.2f)",
                 len(tickers), fetch_failed, quality_reject, fr.ohlcv_fail_pct)

        # --- Stage E-H: already done inline in _build_ticker_row. Group by sector. ---
        by_sector: dict[str, list[TickerRow]] = {c: [] for c in SECTORS}
        for row in tickers.values():
            by_sector.setdefault(row.sector_code, []).append(row)
        for code in by_sector:
            by_sector[code].sort(key=lambda r: (r.score, r.dv_20d), reverse=True)

        # --- Freshness evaluation ---
        if fr.ohlcv_fail_pct >= UNIVERSE_OHLCV_FAIL_PCT_MAX:
            fr.errors.append(f"ohlcv_fail_pct {fr.ohlcv_fail_pct:.2%} ≥ {UNIVERSE_OHLCV_FAIL_PCT_MAX:.0%}")
        if fr.capability_pass_count < UNIVERSE_MIN_PASS:
            fr.errors.append(f"capability_pass_count {fr.capability_pass_count} < {UNIVERSE_MIN_PASS}")
        # Sector-level BUY coverage
        buy_sectors = self._buy_accumulate_sectors(as_of_eff)
        for sec in buy_sectors:
            picks = [r for r in by_sector.get(sec, []) if r.is_valid_buy]
            if picks:
                fr.sectors_with_picks.add(sec)
            else:
                fr.sectors_missing_picks.append(sec)
        if fr.sectors_missing_picks:
            fr.errors.append(f"sectors_missing_picks: {fr.sectors_missing_picks}")
        # as_of freshness (≤ 2 calendar days)
        if as_of is None:
            fr.errors.append("no SectorSignal row — ranker has not run")
        elif (date.today() - as_of).days > 2:
            fr.warnings.append(f"signal date {as_of} is {((date.today() - as_of).days)} days old")

        is_valid = not fr.errors

        # --- Top-5 BUY / Top-5 SELL selection with news enrichment ---
        # Relaxed gate (2026-06-18): build top picks whenever the universe is
        # large enough to trust selection (≥ UNIVERSE_PICKS_FLOOR tickers), even
        # if is_valid=False due to *soft* degradation (ohlcv_fail_pct ≥ max,
        # stale signal, a BUY sector missing picks). is_valid still drives the
        # STALE banner so the user is warned; this only stops the page from
        # collapsing to the legacy 1-pick fallback on a degraded data day.
        top_buys: list[PickEntry] = []
        top_sells: list[PickEntry] = []
        can_pick = len(tickers) >= UNIVERSE_PICKS_FLOOR
        if can_pick:
            top_buys = self._select_top(tickers, by_sector, action="BUY", n=5, as_of=as_of_eff)
            top_sells = self._select_top(tickers, by_sector, action="SELL", n=5, as_of=as_of_eff)

        dur = time.monotonic() - t0
        log.info("[picks-universe] build done: %d tickers in %.1fs, is_valid=%s, top_buys=%d, top_sells=%d",
                 len(tickers), dur, is_valid, len(top_buys), len(top_sells))
        return UniverseSnapshot(
            as_of=as_of_eff, built_at=fr.built_at,
            tickers=tickers, by_sector=by_sector,
            freshness=fr, is_valid=is_valid,
            top_buys=top_buys, top_sells=top_sells,
        )

    def _select_top(self, tickers: dict[str, TickerRow],
                    by_sector: dict[str, list[TickerRow]],
                    action: str, n: int, as_of: date) -> list["PickEntry"]:
        """Pick top-N BUY (highest score in BUY/ACCUMULATE sectors, is_valid_buy)
        or top-N SELL (lowest score in SELL sectors, or weakest momentum in
        any sector when no SELL sector exists).
        """
        action_up = action.upper()
        target_sectors = self._sectors_with_action(
            as_of,
            ("BUY", "ACCUMULATE") if action_up == "BUY" else ("SELL",),
        )

        candidates: list[TickerRow] = []
        for sec in target_sectors:
            candidates.extend(by_sector.get(sec, []))
        # If no SELL sector today, fall back to weakest scored tickers
        # across the whole universe — lets the report still surface risk.
        if not candidates and action_up == "SELL":
            candidates = list(tickers.values())

        # BUY path: require is_valid_buy; sort by (score, dv_20d) desc.
        # SELL path: pick weakest (score asc); is_valid_buy irrelevant.
        if action_up == "BUY":
            filtered = [r for r in candidates if r.is_valid_buy]
            filtered.sort(key=lambda r: (r.score, r.dv_20d), reverse=True)
            # Top-up (2026-06-18): when the ranker flags few BUY/ACCUMULATE
            # sectors, the BUY list starves (e.g. only 1 sector → 1-3 picks).
            # Back-fill with the best-scored is_valid_buy tickers from the WHOLE
            # universe so the user still sees a full shortlist. These passed all
            # capability + validity gates; they're "next-best" ideas, not BUY-
            # flagged sectors — the thesis text carries the metrics.
            if len(filtered) < n:
                seen = {r.symbol for r in filtered}
                extra = [
                    r for r in tickers.values()
                    if r.is_valid_buy and r.symbol not in seen
                ]
                extra.sort(key=lambda r: (r.score, r.dv_20d), reverse=True)
                filtered.extend(extra)
        else:
            filtered = list(candidates)
            # Prefer: negative MACD, RSI < 50, score low
            filtered.sort(key=lambda r: (r.score, -(r.dv_20d or 0)))
        chosen = filtered[:n]

        from services.picks_news import fetch_news

        out: list[PickEntry] = []
        for r in chosen:
            pct_up = ((r.target - r.close) / r.close * 100) if (r.target and r.close) else None
            pct_dn = ((r.close - r.stop) / r.close * 100) if (r.stop and r.close) else None
            tech_bits = _technical_bits(r)
            thesis = _compose_thesis(r, action_up)
            news: list[dict[str, Any]] = []
            try:
                news = [n.to_dict() for n in fetch_news(r.symbol, max_items=3)]
            except BaseException as e:
                log.debug("[picks-universe] news fetch %s failed: %s", r.symbol, e)
            out.append(PickEntry(
                symbol=r.symbol,
                sector_code=r.sector_code,
                sector_name=SECTORS.get(r.sector_code, r.sector_code),
                action=action_up,
                close=r.close,
                stop=r.stop,
                target=r.target if action_up == "BUY" else None,
                rr=r.rr if action_up == "BUY" else None,
                score=r.score,
                atr_pct=r.atr_pct,
                upside_pct=round(pct_up, 2) if pct_up is not None else None,
                downside_pct=round(pct_dn, 2) if pct_dn is not None else None,
                foreign_room_pct=r.foreign_room_pct,
                dv_20d=r.dv_20d,
                technical_bits=tech_bits,
                thesis=thesis,
                news=news,
            ))
        return out

    def _sectors_with_action(self, as_of: date,
                             actions: tuple[str, ...]) -> set[str]:
        as_of_str = as_of.isoformat() if isinstance(as_of, date) else str(as_of)
        sess = SessionLocal()
        try:
            rows = (
                sess.query(SectorSignal)
                .filter(SectorSignal.date == as_of_str)
                .filter(SectorSignal.action.in_(actions))
                .all()
            )
            return {r.sector_code for r in rows}
        finally:
            sess.close()

    # ---------- stage helpers ----------

    def _discover_hose(self) -> pd.DataFrame:
        """Return the per-sector constituent universe as a DataFrame with
        columns `symbol`, `sector_code` pre-assigned.

        2026-04-18: scope narrowed from "all HOSE" (~500 symbols) to
        "constituents of 15 PROXY_BASKETS" (~75 symbols). Rationale:
        - KBS free tier caps at 20 req/min — 500-symbol scan took 25+ min.
        - Sector-level aggregates are owned by sector_ingest_service (DB);
          the picks layer only needs per-ticker OHLCV for BUY/SELL selection.
        - User doctrine (2026-04-18): sectors persisted, per-ticker picks
          are cache-only and serve Daily Insight via OpenClaw.

        Classification via PROXY_BASKETS makes the Stage B sector-classify
        step a no-op (sector_code is already pinned), so the ICB_TO_SECTOR +
        VN-keyword classifier is skipped entirely on this path.

        Override path: rows in `sector_constituents(active=1)` can still
        REPLACE a PROXY_BASKETS entry — they are merged on top.
        """
        from config import PROXY_BASKETS

        rows: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Primary: PROXY_BASKETS (top-5 per sector, market-cap-ordered).
        for sector_code, syms in PROXY_BASKETS.items():
            for sym in syms:
                sym_u = sym.upper().strip()
                if sym_u in seen:
                    continue
                rows.append({"symbol": sym_u, "sector_code_hint": sector_code,
                             "organ_name": "", "industry_code": None})
                seen.add(sym_u)

        # Overrides: sector_constituents table — useful when PROXY_BASKETS
        # goes stale without a code release.
        overrides = _load_constituent_override()
        for sym, sec in overrides.items():
            sym_u = sym.upper().strip()
            if sym_u in seen:
                # same symbol overridden to a different sector? rewrite.
                for r in rows:
                    if r["symbol"] == sym_u:
                        r["sector_code_hint"] = sec
                continue
            rows.append({"symbol": sym_u, "sector_code_hint": sec,
                         "organ_name": "", "industry_code": None})
            seen.add(sym_u)

        return pd.DataFrame(rows)

    def _fetch_foreign_room(self, symbols: list[str]) -> dict[str, float | None]:
        """Batch price_board for foreign_room. Returns {sym: pct or None}."""
        out: dict[str, float | None] = {}
        if not symbols:
            return out
        chunk_size = 50
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i + chunk_size]
            df = _fetch_price_board_chunk(chunk)
            if df.empty:
                for s in chunk:
                    out[s] = None
                continue
            sym_col = _pick_first_col(df, ("symbol", "ticker", "code", "listing_symbol"))
            # KBS exposes `foreign_room` as raw shares (not %). Treat any
            # positive value as "room available"; the capability filter only
            # needs strictly > 0, not a true percentage.
            room_col = _pick_first_col(df, (
                "foreign_room_percent", "foreign_room_pct", "foreign_room",
                "room_outstanding", "foreign_available_pct",
            ))
            if sym_col is None:
                for s in chunk:
                    out[s] = None
                continue
            for _, r in df.iterrows():
                s = str(r[sym_col]).upper().strip()
                if room_col and not pd.isna(r.get(room_col)):
                    try:
                        val = float(r[room_col])
                        out[s] = val
                    except (TypeError, ValueError):
                        out[s] = None
                else:
                    out[s] = None
            # ensure every chunk member has an entry
            for s in chunk:
                out.setdefault(s, None)
        return out

    def _buy_accumulate_sectors(self, as_of: date) -> set[str]:
        """SectorSignal.date is VARCHAR — compare as ISO string."""
        as_of_str = as_of.isoformat() if isinstance(as_of, date) else str(as_of)
        sess = SessionLocal()
        try:
            rows = (
                sess.query(SectorSignal)
                .filter(SectorSignal.date == as_of_str)
                .filter(SectorSignal.action.in_(("BUY", "ACCUMULATE")))
                .all()
            )
            return {r.sector_code for r in rows}
        finally:
            sess.close()


# ---------- module-level accessor ----------

_SERVICE: PicksUniverseService | None = None
_SERVICE_LOCK = threading.Lock()


def get_picks_universe() -> PicksUniverseService:
    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = PicksUniverseService()
    return _SERVICE


__all__ = [
    "PicksUniverseService",
    "UniverseSnapshot",
    "TickerRow",
    "FreshnessReport",
    "get_picks_universe",
]
