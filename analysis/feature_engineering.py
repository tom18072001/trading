# ============================================
# analysis/feature_engineering.py
# Module tạo features (đặc trưng) cho model
# ============================================
"""
Tạo các đặc trưng kỹ thuật (Technical Indicators) từ dữ liệu OHLCV.
Sử dụng thư viện `ta` (Technical Analysis) và tính toán thủ công.

Danh sách features:
  1. Moving Averages: SMA, EMA
  2. Momentum: RSI, MACD, Stochastic, Williams %R, CCI, MFI
  3. Volatility: Bollinger Bands, ATR
  4. Volume: OBV, VWAP
  5. Trend: ADX
  6. Custom: Returns, Volatility, Price ratios
"""

import numpy as np
import pandas as pd
import ta


def add_moving_averages(df, close_col='close'):
    """
    Thêm các đường trung bình động.

    SMA (Simple Moving Average):
        SMA_n = mean(close[-n:])
        Ý nghĩa: Giá trung bình n phiên gần nhất, làm mượt xu hướng.

    EMA (Exponential Moving Average):
        EMA_t = close_t * k + EMA_(t-1) * (1-k), với k = 2/(n+1)
        Ý nghĩa: Trung bình có trọng số, ưu tiên giá gần nhất hơn.
    """
    for period in [5, 10, 20, 50]:
        df[f'SMA_{period}'] = df[close_col].rolling(window=period).mean()

    df['EMA_12'] = df[close_col].ewm(span=12, adjust=False).mean()
    df['EMA_26'] = df[close_col].ewm(span=26, adjust=False).mean()

    # Tỷ lệ giá so với MA (normalized)
    for period in [5, 20, 50]:
        df[f'price_to_SMA_{period}'] = df[close_col] / df[f'SMA_{period}'] - 1

    return df


def add_rsi(df, close_col='close', period=14):
    """
    RSI (Relative Strength Index) - Chỉ số sức mạnh tương đối.

    Công thức:
        delta = close - close.shift(1)
        gain = mean(delta[delta > 0], period)
        loss = mean(abs(delta[delta < 0]), period)
        RS = gain / loss
        RSI = 100 - 100 / (1 + RS)

    Ý nghĩa:
        RSI > 70: Quá mua (overbought) → tín hiệu bán
        RSI < 30: Quá bán (oversold) → tín hiệu mua
        RSI = 50: Trung tính

    Tham số tuning:
        period: Mặc định 14. Giảm → nhạy hơn (nhiều tín hiệu giả).
                                    Tăng → chậm hơn (ít tín hiệu giả).
    """
    df[f'RSI_{period}'] = ta.momentum.RSIIndicator(
        close=df[close_col], window=period
    ).rsi()
    return df


def add_macd(df, close_col='close'):
    """
    MACD (Moving Average Convergence Divergence).

    Công thức:
        MACD_line = EMA_12 - EMA_26
        Signal_line = EMA_9(MACD_line)
        Histogram = MACD_line - Signal_line

    Ý nghĩa:
        MACD cắt lên Signal → Bullish (mua)
        MACD cắt xuống Signal → Bearish (bán)
        Histogram > 0 và tăng → Xu hướng tăng mạnh

    Tham số tuning:
        fast_period (12), slow_period (26), signal_period (9)
        Giảm fast_period → nhạy hơn với biến động ngắn hạn.
    """
    macd = ta.trend.MACD(close=df[close_col], window_slow=26, window_fast=12, window_sign=9)
    df['MACD'] = macd.macd()
    df['MACD_signal'] = macd.macd_signal()
    df['MACD_hist'] = macd.macd_diff()
    return df


def add_bollinger_bands(df, close_col='close', period=20, std_dev=2):
    """
    Bollinger Bands - Dải Bollinger.

    Công thức:
        Middle Band = SMA_20
        Upper Band = SMA_20 + 2 * std(close, 20)
        Lower Band = SMA_20 - 2 * std(close, 20)
        BB_width = (Upper - Lower) / Middle

    Ý nghĩa:
        Giá chạm Upper → có thể quá mua
        Giá chạm Lower → có thể quá bán
        BB_width co hẹp → thị trường sắp có biến động lớn (squeeze)

    Tham số tuning:
        period: 20 (mặc định). Tăng → dải rộng, ít tín hiệu.
        std_dev: 2 (mặc định). Tăng → dải rộng hơn.
    """
    bb = ta.volatility.BollingerBands(close=df[close_col], window=period, window_dev=std_dev)
    df['BB_upper'] = bb.bollinger_hband()
    df['BB_middle'] = bb.bollinger_mavg()
    df['BB_lower'] = bb.bollinger_lband()
    bb_range = df['BB_upper'] - df['BB_lower']
    df['BB_width'] = bb_range / df['BB_middle'].replace(0, np.nan)
    df['BB_position'] = (df[close_col] - df['BB_lower']) / bb_range.replace(0, np.nan)
    return df


def add_atr(df, high_col='high', low_col='low', close_col='close', period=14):
    """
    ATR (Average True Range) - Biên độ dao động trung bình.

    Công thức:
        TR = max(high - low, abs(high - prev_close), abs(low - prev_close))
        ATR = SMA(TR, period)

    Ý nghĩa:
        ATR cao → biến động mạnh
        ATR thấp → thị trường đi ngang
        Dùng để đặt stop-loss: SL = entry - 2*ATR

    Tham số tuning:
        period: 14 (mặc định). Giảm → nhạy hơn.
    """
    df[f'ATR_{period}'] = ta.volatility.AverageTrueRange(
        high=df[high_col], low=df[low_col], close=df[close_col], window=period
    ).average_true_range()
    # Normalize ATR theo giá
    df[f'ATR_{period}_pct'] = df[f'ATR_{period}'] / df[close_col]
    return df


def add_obv(df, close_col='close', volume_col='volume'):
    """
    OBV (On-Balance Volume) - Khối lượng cân bằng.

    Công thức:
        Nếu close > prev_close: OBV += volume
        Nếu close < prev_close: OBV -= volume
        Nếu close == prev_close: OBV không đổi

    Ý nghĩa:
        OBV tăng + giá tăng → xác nhận xu hướng tăng
        OBV giảm + giá tăng → phân kỳ âm (bearish divergence)
    """
    df['OBV'] = ta.volume.OnBalanceVolumeIndicator(
        close=df[close_col], volume=df[volume_col]
    ).on_balance_volume()
    return df


def add_stochastic(df, high_col='high', low_col='low', close_col='close'):
    """
    Stochastic Oscillator - Chỉ báo ngẫu nhiên.

    Công thức:
        %K = (close - lowest_low_14) / (highest_high_14 - lowest_low_14) * 100
        %D = SMA(%K, 3)

    Ý nghĩa:
        %K > 80: Quá mua → tín hiệu bán
        %K < 20: Quá bán → tín hiệu mua
        %K cắt lên %D: Mua. %K cắt xuống %D: Bán.

    Tham số tuning:
        window (14), smooth_window (3)
    """
    stoch = ta.momentum.StochasticOscillator(
        high=df[high_col], low=df[low_col], close=df[close_col],
        window=14, smooth_window=3
    )
    df['Stoch_K'] = stoch.stoch()
    df['Stoch_D'] = stoch.stoch_signal()
    return df


def add_adx(df, high_col='high', low_col='low', close_col='close', period=14):
    """
    ADX (Average Directional Index) - Chỉ số xu hướng.

    Công thức:
        +DM = high - prev_high (nếu > 0 và > -DM, else 0)
        -DM = prev_low - low (nếu > 0 và > +DM, else 0)
        +DI = 100 * EMA(+DM) / ATR
        -DI = 100 * EMA(-DM) / ATR
        DX = abs(+DI - -DI) / (+DI + -DI) * 100
        ADX = EMA(DX, period)

    Ý nghĩa:
        ADX > 25: Xu hướng mạnh (trending)
        ADX < 20: Thị trường đi ngang (ranging)
        +DI > -DI: Xu hướng tăng. -DI > +DI: Xu hướng giảm.

    Tham số tuning:
        period: 14 (mặc định)
    """
    adx = ta.trend.ADXIndicator(
        high=df[high_col], low=df[low_col], close=df[close_col], window=period
    )
    df[f'ADX_{period}'] = adx.adx()
    df[f'DI_plus_{period}'] = adx.adx_pos()
    df[f'DI_minus_{period}'] = adx.adx_neg()
    return df


def add_cci(df, high_col='high', low_col='low', close_col='close', period=20):
    """
    CCI (Commodity Channel Index).

    Công thức:
        TP = (high + low + close) / 3
        CCI = (TP - SMA(TP, 20)) / (0.015 * MeanDeviation(TP, 20))

    Ý nghĩa:
        CCI > 100: Quá mua
        CCI < -100: Quá bán

    Tham số tuning:
        period: 20, constant: 0.015
    """
    df[f'CCI_{period}'] = ta.trend.CCIIndicator(
        high=df[high_col], low=df[low_col], close=df[close_col], window=period
    ).cci()
    return df


def add_williams_r(df, high_col='high', low_col='low', close_col='close', period=14):
    """
    Williams %R.

    Công thức:
        %R = (highest_high - close) / (highest_high - lowest_low) * -100

    Ý nghĩa:
        %R > -20: Quá mua
        %R < -80: Quá bán
    """
    df['Williams_R'] = ta.momentum.WilliamsRIndicator(
        high=df[high_col], low=df[low_col], close=df[close_col], lbp=period
    ).williams_r()
    return df


def add_mfi(df, high_col='high', low_col='low', close_col='close', volume_col='volume', period=14):
    """
    MFI (Money Flow Index) - RSI kết hợp volume.

    Công thức:
        TP = (high + low + close) / 3
        Money_Flow = TP * volume
        Positive_MF = sum(MF khi TP tăng, period)
        Negative_MF = sum(MF khi TP giảm, period)
        MFR = Positive_MF / Negative_MF
        MFI = 100 - 100 / (1 + MFR)

    Ý nghĩa:
        Giống RSI nhưng có tính đến volume
        MFI > 80: Quá mua. MFI < 20: Quá bán.
    """
    df[f'MFI_{period}'] = ta.volume.MFIIndicator(
        high=df[high_col], low=df[low_col], close=df[close_col],
        volume=df[volume_col], window=period
    ).money_flow_index()
    return df


def add_custom_features(df, close_col='close', volume_col='volume'):
    """
    Tạo các đặc trưng tùy chỉnh bổ sung.

    Bao gồm:
        - Returns: Tỷ suất sinh lợi 1, 3, 5, 10, 20 ngày
        - Volatility: Độ biến động (rolling std)
        - Volume ratios: Tỷ lệ volume so với trung bình
        - Price patterns: Gap, inside bar, ...
        - Lag features: Giá trị trễ
    """
    # --- Returns (tỷ suất sinh lợi) ---
    for n in [1, 3, 5, 10, 20]:
        df[f'return_{n}d'] = df[close_col].pct_change(n)

    # --- Log returns ---
    df['log_return_1d'] = np.log(df[close_col] / df[close_col].shift(1))

    # --- Volatility (rolling) ---
    # Vietnam market has ~248 trading days (more holidays than US)
    for n in [5, 10, 20]:
        df[f'volatility_{n}d'] = df['log_return_1d'].rolling(window=n).std() * np.sqrt(248)

    # --- Volume features ---
    df['volume_SMA_5'] = df[volume_col].rolling(5).mean()
    df['volume_SMA_20'] = df[volume_col].rolling(20).mean()
    df['volume_ratio_5'] = df[volume_col] / df['volume_SMA_5']
    df['volume_ratio_20'] = df[volume_col] / df['volume_SMA_20']

    # --- Price patterns ---
    df['gap_up'] = ((df['open'] - df[close_col].shift(1)) / df[close_col].shift(1)).fillna(0)
    df['high_low_range'] = (df['high'] - df['low']) / df[close_col]
    df['upper_shadow'] = (df['high'] - df[['open', close_col]].max(axis=1)) / df[close_col]
    df['lower_shadow'] = (df[['open', close_col]].min(axis=1) - df['low']) / df[close_col]

    # --- Day of week (đặc trưng thời gian) ---
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'])
        df['day_of_week'] = df['time'].dt.dayofweek
        df['month'] = df['time'].dt.month

    return df


def create_target_variable(df, close_col='close', horizon=5, method='binary'):
    """
    Tạo biến mục tiêu (target) cho model.

    Args:
        df: DataFrame
        close_col: Cột giá đóng cửa
        horizon: Số ngày tới để dự đoán
        method: 'binary' (tăng/giảm) hoặc 'regression' (% thay đổi)

    Returns:
        df với cột target mới

    Binary target:
        1 = giá tăng sau `horizon` ngày
        0 = giá giảm hoặc không đổi

    Regression target:
        % thay đổi giá sau `horizon` ngày
    """
    future_return = df[close_col].shift(-horizon) / df[close_col] - 1

    if method == 'binary':
        df[f'target_{horizon}d'] = (future_return > 0).astype(int)
    elif method == 'regression':
        df[f'target_{horizon}d'] = future_return

    return df


def build_feature_set(df):
    """
    Hàm tổng hợp: Tạo toàn bộ features cho một DataFrame.

    Pipeline:
        1. Moving Averages (SMA, EMA)
        2. RSI
        3. MACD
        4. Bollinger Bands
        5. ATR
        6. OBV
        7. Stochastic
        8. ADX
        9. CCI
        10. Williams %R
        11. MFI
        12. Custom features (returns, volatility, volume ratios)
        13. Target variable

    Returns:
        pd.DataFrame với đầy đủ features + target
    """
    print(f"  [Feature Engineering] Building features for {len(df)} rows...")

    df = add_moving_averages(df)
    df = add_rsi(df)
    df = add_macd(df)
    df = add_bollinger_bands(df)
    df = add_atr(df)
    df = add_obv(df)
    df = add_stochastic(df)
    df = add_adx(df)
    df = add_cci(df)
    df = add_williams_r(df)
    df = add_mfi(df)
    df = add_custom_features(df)

    # Tạo target cho nhiều horizons
    for h in [1, 3, 5, 10, 20]:
        future_return = df['close'].shift(-h) / df['close'] - 1
        # Binary target: 1 = price goes up, 0 = price goes down
        df[f'target_bin_{h}d'] = (future_return > 0).astype(int)
        # Regression target: actual % change
        df[f'target_reg_{h}d'] = future_return

    # Xóa dòng NaN (do rolling window)
    initial_rows = len(df)
    df = df.dropna(subset=[c for c in df.columns if c.startswith('SMA_') or c.startswith('RSI_')])

    print(f"  [Feature Engineering] Done. {initial_rows} -> {len(df)} rows (dropped {initial_rows - len(df)} NaN)")
    return df


# ===== TEST =====
if __name__ == "__main__":
    # Tạo dữ liệu mẫu để test
    np.random.seed(42)
    dates = pd.date_range(start='2023-01-01', periods=500, freq='B')
    close = 50 + np.cumsum(np.random.randn(500) * 0.5)
    test_df = pd.DataFrame({
        'time': dates,
        'open': close + np.random.randn(500) * 0.2,
        'high': close + abs(np.random.randn(500) * 0.5),
        'low': close - abs(np.random.randn(500) * 0.5),
        'close': close,
        'volume': np.random.randint(100000, 1000000, 500)
    })

    result = build_feature_set(test_df)
    print(f"\nFeatures tạo được: {result.shape[1]} cột")
    print(f"Các cột: {list(result.columns)}")
