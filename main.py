"""
main.py — ETF Trader FastAPI Backend
=====================================
Railway.app'e deploy edilecek Python API.
Flutter uygulaması bu API üzerinden veri alır.

Endpoints:
  GET /                    → Health check
  GET /api/etf/all         → Tüm ETF'ler özet + sinyaller
  GET /api/etf/{symbol}    → Tek ETF detaylı analiz
  GET /api/config          → Mevcut config
  POST /api/config         → Config güncelle
  GET /api/chart/{symbol}  → Grafik verisi (OHLCV + göstergeler)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from data_manager  import load_config, save_config, refresh_all, fetch_history
from indicators    import compute_all
from signal_engine import compute_all_signals

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(
    title="ETF Trader API",
    description="UCITS ETF Teknik Analiz ve Sinyal Motoru",
    version="1.0.0"
)

# CORS — Flutter uygulamasının erişebilmesi için
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# CACHE (basit in-memory, 5 dakika TTL)
# ─────────────────────────────────────────────────────────────
_cache: dict = {}
_cache_time: dict = {}
CACHE_TTL = 300  # saniye


def _get_cache(key: str):
    import time
    if key in _cache and time.time() - _cache_time.get(key, 0) < CACHE_TTL:
        return _cache[key]
    return None


def _set_cache(key: str, value):
    import time
    _cache[key] = value
    _cache_time[key] = time.time()


# ─────────────────────────────────────────────────────────────
# YARDIMCI
# ─────────────────────────────────────────────────────────────

def get_full_analysis(cfg: dict) -> tuple[dict, dict, dict]:
    """Veri çek → göstergeler → sinyaller."""
    cached = _get_cache("full_analysis")
    if cached:
        return cached

    raw        = refresh_all(cfg)
    indicators = {sym: compute_all(sym, df, cfg["signal_config"])
                  for sym, df in raw.items()}
    signals    = compute_all_signals(indicators, cfg)

    result = (raw, indicators, signals)
    _set_cache("full_analysis", result)
    return result


def format_indicator(ind: dict, sig: dict) -> dict:
    """Tek ETF için API response dict'i oluşturur."""
    if "error" in ind:
        return {"symbol": ind["symbol"], "error": ind["error"]}

    return {
        "symbol":       ind["symbol"],
        "price":        ind.get("price"),
        "currency":     "GBp",  # Londra borsası
        "changes": {
            "d1":  ind.get("chg_1d"),
            "d5":  ind.get("chg_5d"),
            "d21": ind.get("chg_21d"),
            "d252":ind.get("chg_252d"),
        },
        "indicators": {
            "rsi":          ind.get("rsi"),
            "macd":         ind.get("macd"),
            "macd_signal":  ind.get("macd_signal"),
            "macd_hist":    ind.get("macd_hist"),
            "macd_bull":    ind.get("macd_bull"),
            "stoch_k":      ind.get("stoch_k"),
            "stoch_d":      ind.get("stoch_d"),
            "sma50":        ind.get("sma50"),
            "sma200":       ind.get("sma200"),
            "golden_cross": ind.get("golden_cross"),
            "bb_upper":     ind.get("bb_upper"),
            "bb_mid":       ind.get("bb_mid"),
            "bb_lower":     ind.get("bb_lower"),
            "bb_pos":       ind.get("bb_pos"),
            "atr":          ind.get("atr"),
            "atr_rising":   ind.get("atr_rising"),
            "slope_20":     ind.get("slope_20"),
        },
        "volume": {
            "current": ind.get("vol_now"),
            "average": ind.get("vol_avg"),
            "ratio":   ind.get("vol_ratio"),
            "spike":   ind.get("vol_spike"),
        },
        "range_52w": {
            "high":          ind.get("high_52w"),
            "low":           ind.get("low_52w"),
            "dist_from_low": ind.get("dist_from_low"),
            "dist_from_high":ind.get("dist_from_high"),
            "position_pct":  ind.get("pos_52w"),
        },
        "fibonacci": ind.get("fib_levels"),
        "fib_near":  ind.get("fib_near"),
        "signal": {
            "name":      sig.get("signal_name", "TUT"),
            "score":     sig.get("score", 50),
            "icon":      sig.get("icon", "🟡"),
            "color":     sig.get("color", "#ffd740"),
            "breakdown": sig.get("breakdown", {}),
            "details": [
                {
                    "group":    d.group,
                    "criterion":d.criterion,
                    "weight":   d.weight,
                    "earned":   d.earned,
                    "note":     d.note,
                }
                for d in sig.get("details", [])
            ],
            "bonuses": [
                {
                    "group":    b.group,
                    "criterion":b.criterion,
                    "weight":   b.weight,
                    "earned":   b.earned,
                }
                for b in sig.get("bonuses", [])
            ],
        },
        "last_updated": datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "ETF Trader API",
        "version": "1.0.0",
        "time": datetime.now().isoformat(),
    }


@app.get("/api/etf/all")
def get_all_etfs():
    """Tüm ETF'ler için özet liste — ana ekran için."""
    try:
        cfg = load_config()
        _, indicators, signals = get_full_analysis(cfg)

        result = []
        for sym in cfg["etf_list"]:
            ind = indicators.get(sym, {"symbol": sym, "error": "Veri yok"})
            sig = signals.get(sym, {"signal_name": "TUT", "score": 50,
                                     "icon": "🟡", "color": "#ffd740"})
            result.append(format_indicator(ind, sig))

        # Skora göre sırala (yüksekten düşüğe)
        result.sort(key=lambda x: x.get("signal", {}).get("score", 50), reverse=True)

        return {
            "data": result,
            "count": len(result),
            "updated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        log.error(f"get_all_etfs hatası: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/etf/{symbol}")
def get_etf_detail(symbol: str):
    """Tek ETF detaylı analiz — detay ekranı için."""
    try:
        symbol = symbol.upper()
        cfg    = load_config()
        _, indicators, signals = get_full_analysis(cfg)

        ind = indicators.get(symbol)
        sig = signals.get(symbol)

        if ind is None:
            raise HTTPException(status_code=404, detail=f"{symbol} bulunamadı")

        return format_indicator(ind, sig or {})

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"get_etf_detail hatası: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chart/{symbol}")
def get_chart_data(symbol: str, period: str = "1y"):
    """
    Grafik için OHLCV + gösterge serisi döner.
    period: 1m, 3m, 6m, 1y, 2y, 5y
    """
    try:
        symbol = symbol.upper()
        period_bars = {
            "1m": 21, "3m": 63, "6m": 126,
            "1y": 252, "2y": 504, "5y": 1260
        }.get(period, 252)

        cfg = load_config()
        df  = fetch_history(symbol, days=period_bars)

        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"{symbol} verisi bulunamadı")

        # OHLCV → liste
        ohlcv = []
        for dt, row in df.iterrows():
            ohlcv.append({
                "date":   dt.strftime("%Y-%m-%d"),
                "open":   round(float(row["open"]),  4),
                "high":   round(float(row["high"]),  4),
                "low":    round(float(row["low"]),   4),
                "close":  round(float(row["close"]), 4),
                "volume": int(row["volume"]),
            })

        # Göstergeler (seriler)
        ind = compute_all(symbol, df, cfg["signal_config"])
        s   = ind.get("_series", {})

        def series_to_list(serie, decimals=4):
            if serie is None:
                return []
            return [
                {"date": dt.strftime("%Y-%m-%d"), "value": round(float(v), decimals)}
                for dt, v in serie.dropna().items()
            ]

        return {
            "symbol": symbol,
            "period": period,
            "ohlcv":  ohlcv,
            "series": {
                "sma50":     series_to_list(s.get("sma50")),
                "sma200":    series_to_list(s.get("sma200")),
                "rsi":       series_to_list(s.get("rsi"), 2),
                "macd_line": series_to_list(s.get("macd_line"), 6),
                "macd_sig":  series_to_list(s.get("macd_sig"), 6),
                "macd_hist": series_to_list(s.get("macd_hist"), 6),
                "bb_upper":  series_to_list(s.get("bb_upper")),
                "bb_mid":    series_to_list(s.get("bb_mid")),
                "bb_lower":  series_to_list(s.get("bb_lower")),
                "stoch_k":   series_to_list(s.get("stoch_k"), 2),
                "stoch_d":   series_to_list(s.get("stoch_d"), 2),
            },
            "count": len(ohlcv),
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"get_chart_data hatası: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/config")
def get_config():
    """Mevcut config'i döner."""
    try:
        cfg = load_config()
        cfg_safe = {k: v for k, v in cfg.items() if k != "notification"}
        return cfg_safe
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ConfigUpdate(BaseModel):
    etf_list: Optional[list[str]] = None
    refresh_interval_seconds: Optional[int] = None
    signal_config: Optional[dict] = None


@app.post("/api/config")
def update_config(update: ConfigUpdate):
    """Config'i günceller."""
    try:
        cfg = load_config()
        if update.etf_list:
            cfg["etf_list"] = [s.upper() for s in update.etf_list]
        if update.refresh_interval_seconds:
            cfg["refresh_interval_seconds"] = update.refresh_interval_seconds
        if update.signal_config:
            cfg["signal_config"].update(update.signal_config)
        save_config(cfg)
        _cache.clear()  # Cache'i temizle
        return {"status": "ok", "config": cfg}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/refresh")
def force_refresh():
    """Cache'i temizleyip veriyi yeniden çeker."""
    _cache.clear()
    return {"status": "ok", "message": "Cache temizlendi"}
