"""
indicators.py
=============
Tüm teknik göstergeleri hesaplayan modül.
RSI, MACD, Stokastik, Bollinger, ATR, SMA, regresyon eğimi, Fibonacci vb.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────
# TEMEL YARDIMCILAR
# ─────────────────────────────────────────────────────────────

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


# ─────────────────────────────────────────────────────────────
# RSI
# ─────────────────────────────────────────────────────────────

def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1/period, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ─────────────────────────────────────────────────────────────
# MACD
# ─────────────────────────────────────────────────────────────

def macd(s: pd.Series, fast=12, slow=26, signal=9):
    """Returns (macd_line, signal_line, histogram)"""
    fast_ema   = ema(s, fast)
    slow_ema   = ema(s, slow)
    macd_line  = fast_ema - slow_ema
    signal_line= ema(macd_line, signal)
    histogram  = macd_line - signal_line
    return macd_line, signal_line, histogram


# ─────────────────────────────────────────────────────────────
# STOKASTİK
# ─────────────────────────────────────────────────────────────

def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k_period=14, d_period=3) -> tuple[pd.Series, pd.Series]:
    """Stochastic %K ve %D döner."""
    lowest_low   = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    k_smooth = k.rolling(d_period).mean()   # Fast %K → %K (smoothed)
    d = k_smooth.rolling(d_period).mean()   # %D
    return k_smooth, d


# ─────────────────────────────────────────────────────────────
# BOLLİNGER BANTLARI
# ─────────────────────────────────────────────────────────────

def bollinger(s: pd.Series, period=20, std_dev=2.0):
    """Returns (upper, middle, lower)"""
    mid   = sma(s, period)
    sigma = s.rolling(period).std()
    return mid + std_dev * sigma, mid, mid - std_dev * sigma


# ─────────────────────────────────────────────────────────────
# ATR
# ─────────────────────────────────────────────────────────────

def atr(high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


# ─────────────────────────────────────────────────────────────
# LİNEER REGRESYON EĞİMİ
# ─────────────────────────────────────────────────────────────

def linreg_slope(s: pd.Series, window: int = 20) -> float | None:
    """Son N bardaki normalize edilmiş lineer regresyon eğimini döner."""
    try:
        vals = s.dropna().iloc[-window:]
        if len(vals) < window:
            return None
        x = np.arange(len(vals))
        slope, _ = np.polyfit(x, vals.values, 1)
        # Normalize: fiyat bazında yüzde eğim
        return float(slope / vals.mean() * 100)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# FİBONACCİ SEVİYELERİ
# ─────────────────────────────────────────────────────────────

def fibonacci_levels(high_52w: float, low_52w: float) -> dict[str, float]:
    """52 haftalık range üzerinden Fibonacci retracement seviyeleri hesaplar."""
    rng = high_52w - low_52w
    return {
        "0.236": low_52w + 0.236 * rng,
        "0.382": low_52w + 0.382 * rng,
        "0.500": low_52w + 0.500 * rng,
        "0.618": low_52w + 0.618 * rng,
        "0.786": low_52w + 0.786 * rng,
    }


def fib_proximity(price: float, levels: dict[str, float], threshold_pct: float = 2.0) -> bool:
    """Fiyat herhangi bir Fibonacci seviyesine threshold_pct yakınlıkta mı?"""
    for lvl in [levels.get("0.618"), levels.get("0.786")]:
        if lvl and abs(price - lvl) / lvl * 100 <= threshold_pct:
            return True
    return False


# ─────────────────────────────────────────────────────────────
# ANA HESAPLAMA FONKSİYONU
# ─────────────────────────────────────────────────────────────

def compute_all(symbol: str, df: pd.DataFrame, cfg: dict) -> dict:
    """
    Bir ETF için tüm teknik göstergeleri hesaplar.

    Args:
        symbol: Ticker sembolü
        df    : OHLCV DataFrame (index=tarih)
        cfg   : config["signal_config"]

    Returns:
        Tüm göstergeleri içeren flat dict
    """
    if df is None or len(df) < 30:
        return {"symbol": symbol, "error": "Yetersiz veri"}

    c = df["close"]
    h = df["high"]
    lo = df["low"]
    v  = df["volume"]

    # ── SMA ─────────────────────────────────────────────────
    sma50  = sma(c, 50)
    sma200 = sma(c, 200)
    sma50_val  = _last(sma50)
    sma200_val = _last(sma200)

    # ── RSI ──────────────────────────────────────────────────
    rsi_s = rsi(c, 14)
    rsi_val = _last(rsi_s)
    rsi_prev3 = rsi_s.dropna().iloc[-4:-1].tolist() if len(rsi_s.dropna()) >= 4 else []
    rsi_rising_bars = sum(1 for i in range(1, len(rsi_prev3))
                          if rsi_prev3[i] > rsi_prev3[i-1]) if len(rsi_prev3) >= 2 else 0

    # RSI dip dönüşü: oversold bölgeden son 2 günde yükseliş
    rsi_reversal = False
    if rsi_val and len(rsi_s.dropna()) >= 3:
        last3_rsi = rsi_s.dropna().iloc[-3:].tolist()
        rsi_reversal = (last3_rsi[0] < cfg["rsi_oversold"]
                        and last3_rsi[1] < cfg["rsi_oversold"]
                        and last3_rsi[2] > last3_rsi[1] > last3_rsi[0])

    # ── MACD ─────────────────────────────────────────────────
    macd_line, macd_sig, macd_hist = macd(c)
    macd_val      = _last(macd_line)
    macd_sig_val  = _last(macd_sig)
    macd_hist_val = _last(macd_hist)

    # ── STOKASTİK ────────────────────────────────────────────
    stoch_k, stoch_d = stochastic(h, lo, c)
    stoch_k_val = _last(stoch_k)
    stoch_d_val = _last(stoch_d)

    # ── BOLLİNGER ────────────────────────────────────────────
    bb_period = cfg.get("bb_period", 20)
    bb_std    = cfg.get("bb_std", 2.0)
    bb_upper, bb_mid, bb_lower = bollinger(c, bb_period, bb_std)
    bb_upper_val = _last(bb_upper)
    bb_mid_val   = _last(bb_mid)
    bb_lower_val = _last(bb_lower)
    price_now    = _last(c)

    # Fiyatın bant içi pozisyonu (0=alt, 1=üst)
    bb_pos = None
    if bb_upper_val and bb_lower_val and (bb_upper_val - bb_lower_val) > 0:
        bb_pos = (price_now - bb_lower_val) / (bb_upper_val - bb_lower_val)

    # ── ATR ──────────────────────────────────────────────────
    atr_s = atr(h, lo, c, 14)
    atr_val = _last(atr_s)
    atr_rising = False
    if len(atr_s.dropna()) >= 6:
        atr5 = atr_s.dropna().iloc[-6:-1]
        atr_rising = float(atr5.iloc[-1]) > float(atr5.iloc[0])

    # ── HACİM ────────────────────────────────────────────────
    vol_ma_period = cfg.get("volume_ma_period", 20)
    vol_spike_thr = cfg.get("volume_spike_threshold", 1.5)
    vol_ma  = v.rolling(vol_ma_period).mean()
    vol_now = _last(v)
    vol_avg = _last(vol_ma)
    vol_ratio = vol_now / vol_avg if vol_avg and vol_avg > 0 else None
    vol_spike = vol_ratio >= vol_spike_thr if vol_ratio else False

    # Hacim azalırken fiyat sabit / yükseliyor (sıkışma tespiti)
    squeeze = False
    if len(v) >= 5 and len(c) >= 5:
        vol_trend  = float(v.iloc[-1]) < float(v.iloc[-5])
        price_trend= float(c.iloc[-1]) >= float(c.iloc[-5]) * 0.99
        squeeze = vol_trend and price_trend

    # ── REGRESYON EĞİMİ ─────────────────────────────────────
    slope_val = linreg_slope(c, 20)

    # ── 52 HAFTALIK ──────────────────────────────────────────
    w52 = df.tail(252)
    high_52w = float(w52["high"].max())
    low_52w  = float(w52["low"].min())
    dist_from_low_pct  = (price_now - low_52w)  / low_52w  * 100 if low_52w  else None
    dist_from_high_pct = (price_now - high_52w) / high_52w * 100 if high_52w else None
    pos_52w_pct = (price_now - low_52w) / (high_52w - low_52w) * 100 \
                  if (high_52w - low_52w) > 0 else None

    # ── FİBONACCİ ────────────────────────────────────────────
    fib_levels = fibonacci_levels(high_52w, low_52w)
    fib_near   = fib_proximity(price_now, fib_levels, threshold_pct=2.0) \
                 if cfg.get("use_fibonacci_levels", True) else False

    # ── SON 20 BAR MİNİMUM SAPMA ────────────────────────────
    recent_min = float(c.tail(20).min())
    deviation_from_min = (price_now - recent_min) / recent_min * 100 if recent_min else None

    # ── 200 SMA DOKUNUŞ TESPITI ──────────────────────────────
    touched_200sma = False
    if sma200_val and len(c) >= 5:
        for i in range(-5, -1):
            try:
                p = float(c.iloc[i])
                s200 = float(sma200.iloc[i])
                if abs(p - s200) / s200 * 100 < 1.5:
                    touched_200sma = True
                    break
            except Exception:
                pass

    # ── DÖNEMSEL DEĞİŞİMLER ─────────────────────────────────
    def pct_change(n):
        try:
            n = min(n, len(c) - 1)
            old = float(c.iloc[-(n+1)])
            return round((price_now - old) / old * 100, 2) if old else None
        except Exception:
            return None

    return {
        "symbol": symbol,
        "price":  price_now,

        # Dönemsel değişimler
        "chg_1d":  pct_change(1),
        "chg_5d":  pct_change(5),
        "chg_21d": pct_change(21),
        "chg_252d":pct_change(252),

        # SMA
        "sma50":  sma50_val,
        "sma200": sma200_val,
        "golden_cross": (sma50_val and sma200_val and sma50_val > sma200_val),

        # RSI
        "rsi":            rsi_val,
        "rsi_rising_bars":rsi_rising_bars,
        "rsi_reversal":   rsi_reversal,

        # MACD
        "macd":       macd_val,
        "macd_signal":macd_sig_val,
        "macd_hist":  macd_hist_val,
        "macd_bull":  (macd_val is not None and macd_sig_val is not None
                       and macd_val > macd_sig_val),

        # Stokastik
        "stoch_k": stoch_k_val,
        "stoch_d": stoch_d_val,

        # Bollinger
        "bb_upper": bb_upper_val,
        "bb_mid":   bb_mid_val,
        "bb_lower": bb_lower_val,
        "bb_pos":   bb_pos,  # 0=alt bant, 1=üst bant

        # ATR
        "atr":        atr_val,
        "atr_rising": atr_rising,

        # Hacim
        "vol_now":   vol_now,
        "vol_avg":   vol_avg,
        "vol_ratio": vol_ratio,
        "vol_spike": vol_spike,
        "squeeze":   squeeze,

        # Regresyon eğimi
        "slope_20": slope_val,

        # 52 Haftalık
        "high_52w":         high_52w,
        "low_52w":          low_52w,
        "dist_from_low":    dist_from_low_pct,
        "dist_from_high":   dist_from_high_pct,
        "pos_52w":          pos_52w_pct,

        # Fibonacci
        "fib_levels": fib_levels,
        "fib_near":   fib_near,

        # Yapısal
        "deviation_from_min": deviation_from_min,
        "touched_200sma":     touched_200sma,

        # Ham seriler (grafik için)
        "_series": {
            "close":     c,
            "sma50":     sma50,
            "sma200":    sma200,
            "rsi":       rsi_s,
            "macd_line": macd_line,
            "macd_sig":  macd_sig,
            "macd_hist": macd_hist,
            "bb_upper":  bb_upper,
            "bb_mid":    bb_mid,
            "bb_lower":  bb_lower,
            "stoch_k":   stoch_k,
            "stoch_d":   stoch_d,
            "atr":       atr_s,
            "volume":    v,
            "open":      df["open"],
            "high":      df["high"],
            "low":       df["low"],
        },
    }


def _last(s: pd.Series) -> float | None:
    """Serinin son geçerli değerini döner."""
    try:
        val = s.dropna().iloc[-1]
        return float(val) if not np.isnan(val) else None
    except Exception:
        return None
