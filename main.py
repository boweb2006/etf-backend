"""
main.py — ETF Trader FastAPI Backend v2
========================================
Render.com'a deploy edilecek Python API.
"""
from __future__ import annotations

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from data_manager import load_config, save_config, refresh_all, fetch_history, fetch_live_price
from indicators import compute_all
from signal_engine import compute_all_signals

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

import sqlite3

DB_PATH    = "/tmp/etf_data.db"
TMP_CONFIG = "/tmp/etf_config.json"

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def get_config() -> dict:
    try:
        conn = _get_db()
        row  = conn.execute(
            "SELECT value FROM app_config WHERE key='etf_config'"
        ).fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception as e:
        log.error(f"DB config okuma hatasi: {e}")
    cfg = load_config("config.json")
    _save_config(cfg)
    return cfg

def _save_config(cfg: dict):
    try:
        conn = _get_db()
        conn.execute(
            "INSERT OR REPLACE INTO app_config (key, value) VALUES ('etf_config', ?)",
            (json.dumps(cfg, ensure_ascii=False),)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"DB config yazma hatasi: {e}")
        try:
            with open(TMP_CONFIG, "w") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

app = FastAPI(
    title="ETF Trader API",
    description="UCITS ETF Teknik Analiz ve Sinyal Motoru",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# CACHE
# ─────────────────────────────────────────────────────────────
_cache: dict      = {}
_cache_time: dict = {}
CACHE_TTL = 300

def _get_cache(key: str):
    import time
    if key in _cache and time.time() - _cache_time.get(key, 0) < CACHE_TTL:
        return _cache[key]
    return None

def _set_cache(key: str, value):
    import time
    _cache[key]      = value
    _cache_time[key] = time.time()

# ─────────────────────────────────────────────────────────────
# YARDIMCI
# ─────────────────────────────────────────────────────────────
def get_full_analysis(cfg: dict):
    cached = _get_cache("full_analysis")
    if cached:
        return cached
    raw        = refresh_all(cfg)
    indicators = {sym: compute_all(sym, df, cfg["signal_config"])
                  for sym, df in raw.items()}
    signals    = compute_all_signals(indicators, cfg)
    result     = (raw, indicators, signals)
    _set_cache("full_analysis", result)
    return result

def _clean(v):
    """NaN/Inf değerleri None'a çevirir — JSON serialize hatası önler."""
    if v is None:
        return None
    try:
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return v

import math

def format_indicator(ind: dict, sig: dict, live: dict | None = None) -> dict:
    if "error" in ind:
        return {"symbol": ind["symbol"], "error": ind["error"]}

    # ── Fiyat: önce fetch_live_price, yoksa indicators'dan ──
    price    = _clean(ind.get("price"))
    chg_1d   = _clean(ind.get("chg_1d"))
    if live:
        live_price = _clean(live.get("price"))
        if live_price is not None:
            price = live_price
        if live.get("chg_pct") is not None:
            chg_1d = _clean(live["chg_pct"])

    return {
        "symbol": ind["symbol"],
        "price":  price,
        "currency": live.get("currency", "USD") if live else "USD",
        "changes": {
            "d1":   chg_1d,
            "d5":   ind.get("chg_5d"),
            "d21":  ind.get("chg_21d"),
            "d252": ind.get("chg_252d"),
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
            "high":           ind.get("high_52w"),
            "low":            ind.get("low_52w"),
            "dist_from_low":  ind.get("dist_from_low"),
            "dist_from_high": ind.get("dist_from_high"),
            "position_pct":   ind.get("pos_52w"),
        },
        "fibonacci": ind.get("fib_levels"),
        "fib_near":  ind.get("fib_near"),
        "signal": {
            "name":  sig.get("signal_name", "TUT"),
            "score": sig.get("score", 50),
            "icon":  sig.get("icon",  "🟡"),
            "color": sig.get("color", "#ffd740"),
            "breakdown": sig.get("breakdown", {}),
            "details": [
                {"group": d.group, "criterion": d.criterion,
                 "weight": d.weight, "earned": d.earned, "note": d.note}
                for d in sig.get("details", [])
            ],
            "bonuses": [
                {"group": b.group, "criterion": b.criterion,
                 "weight": b.weight, "earned": b.earned}
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
    return {"status": "ok", "service": "ETF Trader API", "version": "2.0.0",
            "time": datetime.now().isoformat()}

@app.get("/api/etf/all")
def get_all_etfs():
    try:
        cfg = get_config()
        _, indicators, signals = get_full_analysis(cfg)
        result = []
        for sym in cfg["etf_list"]:
            ind  = indicators.get(sym, {"symbol": sym, "error": "Veri yok"})
            sig  = signals.get(sym, {"signal_name": "TUT", "score": 50,
                                     "icon": "🟡", "color": "#ffd740"})
            # Her sembol için canlı fiyat çek
            live = fetch_live_price(sym)
            result.append(format_indicator(ind, sig, live))
        result.sort(key=lambda x: x.get("signal", {}).get("score", 50), reverse=True)
        return {"data": result, "count": len(result),
                "updated_at": datetime.now().isoformat()}
    except Exception as e:
        log.error(f"get_all_etfs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/etf/{symbol}")
def get_etf_detail(symbol: str):
    try:
        symbol = symbol.upper()
        cfg    = get_config()
        _, indicators, signals = get_full_analysis(cfg)
        ind = indicators.get(symbol)
        sig = signals.get(symbol)
        if ind is None:
            raise HTTPException(status_code=404, detail=f"{symbol} bulunamadı")
        live = fetch_live_price(symbol)
        return format_indicator(ind, sig or {}, live)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/dividends/{symbol}")
def get_dividends(symbol: str):
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        divs   = ticker.dividends
        if divs.empty:
            return {"symbol": symbol, "dividends": [], "annual_estimate": 0}
        one_year_ago = datetime.now() - timedelta(days=365)
        recent  = divs[divs.index > str(one_year_ago)[:10]]
        annual  = float(recent.sum()) if not recent.empty else 0
        live    = fetch_live_price(symbol)
        price   = live["price"] if live else None
        yield_pct = (annual / price * 100) if price and price > 0 else 0
        history = [
            {"date": str(d)[:10], "amount": float(v)}
            for d, v in divs.tail(20).items()
        ]
        return {
            "symbol":          symbol,
            "dividends":       history,
            "annual_estimate": round(annual, 4),
            "yield_pct":       round(yield_pct, 2),
            "currency":        "GBP" if symbol.endswith(".L") else "USD",
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/api/chart/{symbol}")
def get_chart_data(symbol: str, period: str = "1y"):
    try:
        symbol = symbol.upper()
        period_bars = {"1m": 21, "3m": 63, "6m": 126, "1y": 252,
                       "2y": 504, "5y": 1260}.get(period, 252)
        cfg = get_config()
        df  = fetch_history(symbol, days=period_bars)
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"{symbol} data not found")
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
        ind = compute_all(symbol, df, cfg["signal_config"])
        s   = ind.get("_series", {})

        def to_list(serie, decimals=4):
            if serie is None: return []
            return [{"date": dt.strftime("%Y-%m-%d"), "value": round(float(v), decimals)}
                    for dt, v in serie.dropna().items()]

        return {
            "symbol": symbol, "period": period, "ohlcv": ohlcv,
            "series": {
                "sma50":     to_list(s.get("sma50")),
                "sma200":    to_list(s.get("sma200")),
                "rsi":       to_list(s.get("rsi"),       2),
                "macd_line": to_list(s.get("macd_line"), 6),
                "macd_sig":  to_list(s.get("macd_sig"),  6),
                "macd_hist": to_list(s.get("macd_hist"), 6),
                "bb_upper":  to_list(s.get("bb_upper")),
                "bb_mid":    to_list(s.get("bb_mid")),
                "bb_lower":  to_list(s.get("bb_lower")),
                "stoch_k":   to_list(s.get("stoch_k"),   2),
                "stoch_d":   to_list(s.get("stoch_d"),   2),
            },
            "count": len(ohlcv),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config")
def get_config_endpoint():
    try:
        cfg = get_config()
        return {k: v for k, v in cfg.items() if k != "notification"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ConfigUpdate(BaseModel):
    etf_list:                   Optional[List[str]] = None
    refresh_interval_seconds:   Optional[int]       = None
    signal_config:              Optional[dict]      = None

@app.post("/api/config")
def update_config(update: ConfigUpdate):
    try:
        cfg = get_config()
        if update.etf_list is not None:
            cfg["etf_list"] = [s.upper() for s in update.etf_list]
        if update.refresh_interval_seconds is not None:
            cfg["refresh_interval_seconds"] = update.refresh_interval_seconds
        if update.signal_config is not None:
            cfg["signal_config"].update(update.signal_config)
        _save_config(cfg)
        _cache.clear()
        return {"status": "ok", "config": cfg}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/refresh")
def force_refresh():
    _cache.clear()
    return {"status": "ok", "message": "Cache temizlendi"}

@app.get("/api/debug/{symbol}")
def debug_live_price(symbol: str):
    """fetch_live_price sonucunu doğrudan döner — teşhis için"""
    import math
    try:
        result = fetch_live_price(symbol.upper())
        if result is None:
            return {"symbol": symbol, "live": None, "error": "fetch_live_price None döndü"}
        # NaN kontrolü
        cleaned = {}
        for k, v in result.items():
            try:
                cleaned[k] = None if (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else v
            except Exception:
                cleaned[k] = str(v)
        return {"symbol": symbol, "live": cleaned}
    except Exception as e:
        import traceback
        return {"symbol": symbol, "error": str(e), "trace": traceback.format_exc()}
