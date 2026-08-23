# ============================================
# data/data_fetcher.py
# Module keo du lieu tu vnstock API
# ============================================
"""
Su dung thu vien vnstock (v3.x) de lay du lieu thi truong chung khoan Viet Nam.
Nguon du lieu: TCBS, VCI (Vietcap Securities), SSI

Cac chuc nang:
  - Lay danh sach ma co phieu theo san (HOSE, HNX, UPCOM)
  - Lay du lieu lich su gia OHLCV
  - Lay thong tin cong ty & nganh
  - Lay bang gia realtime
  - Lay chi so tai chinh co ban
"""

import time
import logging
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from config import DATA_SOURCE, START_DATE, END_DATE
try:
    from config import SECTOR_MAP
except ImportError:
    SECTOR_MAP = {}  # removed in sector money-flow redesign

logger = logging.getLogger(__name__)

# Max retries for API calls
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds
RATE_LIMIT_DELAY = 0.5  # seconds between API calls
API_TIMEOUT = 30  # seconds per API call


def _safe_log(msg: str):
    """Log message safely, handling encoding issues on Windows."""
    try:
        logger.info(msg)
    except Exception:
        pass
    try:
        print(msg)
    except (UnicodeEncodeError, UnicodeDecodeError):
        # Fallback: strip non-ASCII chars for Windows cp1252 console
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _call_with_retry(fn, description: str = "API call", timeout: int = None):
    """
    Call fn() with retry logic, exponential backoff, and per-call timeout.
    Returns the result or raises the last exception.
    Reuses a single-thread executor to avoid overhead of creating one per call.
    """
    timeout = timeout or API_TIMEOUT
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(fn)
                return future.result(timeout=timeout)
        except FuturesTimeoutError:
            last_error = TimeoutError(f"{description} timed out after {timeout}s")
            _safe_log(f"  [TIMEOUT] {description} attempt {attempt}/{MAX_RETRIES} "
                      f"exceeded {timeout}s")
        except Exception as e:
            last_error = e
            err_name = type(e).__name__
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                _safe_log(f"  [RETRY] {description} attempt {attempt}/{MAX_RETRIES} "
                          f"failed ({err_name}), retrying in {delay:.0f}s...")
            else:
                _safe_log(f"  [ERROR] {description} failed after {MAX_RETRIES} attempts: {err_name}: {e}")
        if attempt < MAX_RETRIES:
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            time.sleep(delay)
    raise last_error


def get_all_symbols():
    """
    Lay toan bo danh sach ma co phieu tren 3 san: HOSE, HNX, UPCOM.

    Returns:
        pd.DataFrame: Bang danh sach ma CK voi cac cot [ticker, organ_name, ...]
    """
    from utils.vn_api import listing as vn_listing

    def _fetch():
        return vn_listing().all_symbols()

    df = _call_with_retry(_fetch, "get_all_symbols")
    _safe_log(f"[INFO] Total symbols: {len(df)}")
    return df


def get_stock_history(symbol, start_date=START_DATE, end_date=END_DATE, source=DATA_SOURCE, interval='1D'):
    """
    Lay du lieu lich su gia (OHLCV) cua mot ma co phieu.

    Args:
        symbol (str): Ma co phieu (VD: 'VCB', 'FPT')
        start_date (str): Ngay bat dau (YYYY-MM-DD)
        end_date (str): Ngay ket thuc (YYYY-MM-DD)
        source (str): Nguon du lieu ('VCI', 'TCBS')

    Returns:
        pd.DataFrame: Bang du lieu OHLCV
            - time: Ngay giao dich
            - open, high, low, close: Gia OHLC
            - volume: Khoi luong giao dich
    """
    from utils.vn_api import quote_history

    def _fetch():
        return quote_history(symbol, start_date, end_date,
                             interval=interval, source=source)

    try:
        df = _call_with_retry(_fetch, f"history({symbol})")

        if df is not None and not df.empty:
            # Normalize column names
            df.columns = [c.lower().strip() for c in df.columns]
            df['symbol'] = symbol
            _safe_log(f"  [OK] {symbol}: {len(df)} rows ({start_date} -> {end_date})")
            return df
        else:
            _safe_log(f"  [WARN] {symbol}: no data returned")
            return pd.DataFrame()
    except Exception as e:
        _safe_log(f"  [ERROR] {symbol}: {type(e).__name__}: {e}")
        return pd.DataFrame()


def get_intraday_history(symbol, interval='1H', days_back=7, source=DATA_SOURCE):
    """Fetch intraday OHLCV data for a symbol."""
    from datetime import datetime, timedelta
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    return get_stock_history(symbol, start_date=start, end_date=end, source=source, interval=interval)


def is_market_open():
    """Check if Vietnam stock market is currently open (UTC+7)."""
    from config import MARKET_OPEN, MARKET_CLOSE, MARKET_BREAK_START, MARKET_BREAK_END
    now = datetime.now()  # Assumes server is in UTC+7
    current_time = now.strftime("%H:%M")
    if now.weekday() >= 5:  # Weekend
        return False
    if current_time < MARKET_OPEN or current_time >= MARKET_CLOSE:
        return False
    if MARKET_BREAK_START <= current_time < MARKET_BREAK_END:
        return False
    return True


def get_company_overview(symbol, source=DATA_SOURCE):
    """
    Lay thong tin tong quan cong ty: nganh, san, von hoa...

    Args:
        symbol (str): Ma co phieu

    Returns:
        pd.DataFrame: Thong tin tong quan
    """
    from utils.vn_api import company_news

    def _fetch():
        return company_news(symbol, source=source).overview()

    try:
        return _call_with_retry(_fetch, f"overview({symbol})")
    except Exception as e:
        _safe_log(f"  [ERROR] Overview {symbol}: {type(e).__name__}: {e}")
        return pd.DataFrame()


def fetch_sector_data(sector_name, symbols=None, start_date=START_DATE, end_date=END_DATE):
    """
    Lay du lieu lich su cho toan bo co phieu trong mot nhom nganh.

    Args:
        sector_name (str): Ten nhom nganh (VD: 'Ngan hang', 'Bat dong san')
        symbols (list): Danh sach ma CK. Neu None, lay tu SECTOR_MAP
        start_date (str): Ngay bat dau
        end_date (str): Ngay ket thuc

    Returns:
        pd.DataFrame: Du lieu gop tat ca ma CK trong nganh, co cot 'sector'
    """
    if symbols is None:
        symbols = SECTOR_MAP.get(sector_name, [])

    if not symbols:
        _safe_log(f"[WARN] No symbols found for sector: {sector_name}")
        return pd.DataFrame()

    _safe_log(f"\n{'='*50}")
    _safe_log(f"[FETCH] Sector: {sector_name} ({len(symbols)} symbols)")
    _safe_log(f"{'='*50}")

    all_data = []
    failed = []
    for sym in symbols:
        df = get_stock_history(sym, start_date, end_date)
        if not df.empty:
            df['sector'] = sector_name
            all_data.append(df)
        else:
            failed.append(sym)
        time.sleep(RATE_LIMIT_DELAY)

    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        _safe_log(f"[DONE] {sector_name}: {len(combined)} rows, "
                  f"{len(all_data)}/{len(symbols)} symbols OK"
                  f"{f', failed: {failed}' if failed else ''}")
        return combined

    _safe_log(f"[WARN] {sector_name}: all symbols failed")
    return pd.DataFrame()


def fetch_all_sectors(start_date=START_DATE, end_date=END_DATE):
    """
    Lay du lieu cho TAT CA cac nhom nganh da cau hinh.

    Args:
        start_date (str): Ngay bat dau
        end_date (str): Ngay ket thuc
        save (bool): Luu file CSV

    Returns:
        pd.DataFrame: Du lieu toan thi truong
    """
    all_data = []
    for sector_name in SECTOR_MAP:
        try:
            df = fetch_sector_data(sector_name, start_date=start_date, end_date=end_date)
            if not df.empty:
                all_data.append(df)
        except Exception as e:
            _safe_log(f"[ERROR] Sector {sector_name} failed: {type(e).__name__}: {e}")
            continue

    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        _safe_log(f"\n[DONE] Fetched all sectors: {len(combined)} rows")
        return combined
    return pd.DataFrame()


def fetch_single_stock_full(symbol, start_date=START_DATE, end_date=END_DATE):
    """
    Lay day du du lieu cho mot ma: gia + thong tin cong ty.

    Returns:
        dict: {'history': DataFrame, 'overview': DataFrame}
    """
    history = get_stock_history(symbol, start_date, end_date)
    overview = get_company_overview(symbol)
    return {"history": history, "overview": overview}


def get_price_board(symbols):
    """
    Lay bang gia realtime cho danh sach ma.

    Args:
        symbols (list): Danh sach ma CK

    Returns:
        pd.DataFrame: Bang gia
    """
    from utils.vn_api import price_board

    def _fetch():
        return price_board(symbols)

    try:
        return _call_with_retry(_fetch, "price_board")
    except Exception as e:
        _safe_log(f"[ERROR] Price board: {type(e).__name__}: {e}")
        return pd.DataFrame()


# ===== TEST =====
if __name__ == "__main__":
    print("=" * 60)
    print("  VN STOCK DATA FETCHER - Test Run")
    print("=" * 60)

    # Test 1: Get symbol list
    print("\n[TEST 1] Get all symbols...")
    try:
        symbols_df = get_all_symbols()
        print(symbols_df.head())
    except Exception as e:
        print(f"  Error: {e}")

    # Test 2: Get history for 1 symbol
    print("\n[TEST 2] Get FPT history...")
    df = get_stock_history("FPT", start_date="2025-01-01")
    if not df.empty:
        print(df.tail())

    # Test 3: Get sector data
    print("\n[TEST 3] Get banking sector (top 5)...")
    bank_data = fetch_sector_data("Ngan hang", symbols=["VCB", "BID", "CTG", "TCB", "MBB"],
                                  start_date="2025-01-01")
    if not bank_data.empty:
        print(f"  Total: {len(bank_data)} rows")
        print(bank_data.groupby('symbol').size())
