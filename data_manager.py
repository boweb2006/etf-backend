"""
data_manager.py
===============
SQLite veri katmanı + yfinance veri çekme modülü.
3 kez yeniden deneme mekanizması ile hata toleranslı.
"""
from __future__ import annotations

import sqlite3
import json
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import yfinance as yf

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
def load_config(path: str = "config.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg: dict, path: str = "config.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ─────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────
def get_connection(db_path: str) -> sqlite3.Connection:
    import os
    if not os.path.isabs(db_path):
        tmp_path = os.path.join("/tmp", db_path)
        try:
            conn = sqlite3.connect(tmp_path)
            db_path = tmp_path
        except Exception:
            pass
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            symbol  TEXT NOT NULL,
            date    TEXT NOT NULL,
            open    REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY (symbol, date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_log (
            symbol TEXT PRIMARY KEY,
            last_fetch TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def save_ohlcv(conn: sqlite3.Connection, symbol: str, df: pd.DataFrame):
    cur = conn.cursor()
    for dt, row in df.iterrows():
        date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
        cur.execute("""
            INSERT OR REPLACE INTO ohlcv (symbol, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol, date_str,
            _safe(row.get("open") or row.get("Open")),
            _safe(row.get("high") or row.get("High")),
            _safe(row.get("low")  or row.get("Low")),
            _safe(row.get("close") or row.get("Close")),
            int(row.get("volume") or row.get("Volume") or 0),
        ))
    cur.execute(
        "INSERT OR REPLACE INTO fetch_log (symbol, last_fetch) VALUES (?, ?)",
        (symbol, datetime.now().isoformat())
    )
    conn.commit()

def load_ohlcv(conn: sqlite3.Connection, symbol: str, days: int = 1260) -> pd.DataFrame | None:
    df = pd.read_sql_query(
        "SELECT * FROM ohlcv WHERE symbol=? ORDER BY date DESC LIMIT ?",
        conn, params=(symbol, days)
    )
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df

def _safe(v) -> float | None:
    try:
        return round(float(v), 6) if v is not None and not (isinstance(v, float) and np.isnan(v)) else None
    except Exception:
        return None

# ─────────────────────────────────────────────────────────────
# yFINANCE VERİ ÇEKME — 3 DENEME
# ─────────────────────────────────────────────────────────────
def fetch_history(symbol: str, days: int = 1260, retries: int = 3) -> pd.DataFrame | None:
    end   = datetime.now()
    start = end - timedelta(days=int(days * 1.6))
    for attempt in range(1, retries + 1):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                auto_adjust=True,
                timeout=12,
            )
            if df.empty:
                log.warning(f"{symbol}: Boş yanıt (deneme {attempt})")
            else:
                df.index   = pd.to_datetime(df.index).tz_localize(None)
                df.columns = [c.lower() for c in df.columns]
                df = df[["open", "high", "low", "close", "volume"]].tail(days)
                log.info(f"{symbol}: {len(df)} bar çekildi.")
                return df
        except Exception as e:
            log.error(f"{symbol} hata (deneme {attempt}): {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
    return None


# ─────────────────────────────────────────────────────────────
# TWELVE DATA — CANLI FİYAT
# ─────────────────────────────────────────────────────────────
def _td_symbol(symbol: str):
    if symbol.endswith(".L"):
        return symbol[:-2], "LSE"
    return symbol, None

def fetch_live_price_twelvedata(symbol: str, api_key: str, retries: int = 3) -> dict | None:
    import requests, math
    for attempt in range(1, retries + 1):
        try:
            sym, exchange = _td_symbol(symbol)
            params = {"symbol": sym, "apikey": api_key}
            if exchange:
                params["exchange"] = exchange
            r = requests.get("https://api.twelvedata.com/quote",
                             params=params, timeout=12)
            r.raise_for_status()
            data = r.json()
            if data.get("status") == "error":
                raise ValueError(data.get("message", "TD hata"))
            price    = float(data.get("close") or data.get("price") or 0)
            prev     = float(data.get("previous_close") or price)
            currency = data.get("currency", "USD")
            if price == 0 or math.isnan(price):
                raise ValueError("Fiyat sifir veya NaN")
            chg     = price - prev
            chg_pct = chg / prev * 100 if prev else 0
            return {
                "symbol":   symbol,
                "price":    round(price, 4),
                "change":   round(chg, 4),
                "chg_pct":  round(chg_pct, 2),
                "currency": currency,
                "ts":       datetime.now().strftime("%H:%M:%S"),
                "source":   "twelvedata",
            }
        except Exception as e:
            log.error(f"TD {symbol} hata (deneme {attempt}): {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
    return None


def fetch_live_price(symbol: str, retries: int = 3) -> dict | None:
    """
    Anlık fiyat bilgisini çeker.
    Yahoo Finance v8 JSON API kullanır — intraday dahil güncel veri döner.
    """
    import requests, math

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    for attempt in range(1, retries + 1):
        try:
            # Yöntem 1: Yahoo Finance v8 — 1m interval, regularMarketPrice
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                   f"?interval=1m&range=1d&includePrePost=false")
            r   = requests.get(url, headers=headers, timeout=12)
            r.raise_for_status()
            data = r.json()

            result = data.get("chart", {}).get("result", [])
            if not result:
                raise ValueError("Bos sonuc")

            meta     = result[0].get("meta", {})
            price    = meta.get("regularMarketPrice") or meta.get("previousClose")
            prev     = meta.get("previousClose") or price
            currency = meta.get("currency", "USD")

            if price is None or (isinstance(price, float) and math.isnan(price)):
                raise ValueError("Fiyat None veya NaN")

            chg     = (price - prev) if prev else 0
            chg_pct = chg / prev * 100 if prev else 0

            return {
                "symbol":   symbol,
                "price":    round(float(price), 4),
                "change":   round(float(chg), 4),
                "chg_pct":  round(float(chg_pct), 2),
                "currency": currency,
                "ts":       datetime.now().strftime("%H:%M:%S"),
            }

        except Exception as e:
            log.error(f"{symbol} canli fiyat hatasi v8 (deneme {attempt}): {e}")

        # Yöntem 2: yfinance 1h interval — gunun en son saatlik kapanis
        try:
            t = yf.Ticker(symbol)
            h = t.history(period="2d", interval="1h").dropna()
            if not h.empty:
                price = float(h["Close"].iloc[-1])
                # Onceki gun kapanisi icin 1d veri
                h1d = t.history(period="5d", interval="1d").dropna()
                prev = float(h1d["Close"].iloc[-2]) if len(h1d) >= 2 else price
                chg  = price - prev
                fi   = t.fast_info
                currency = "USD"
                try:
                    currency = getattr(fi, "currency", "USD") or "USD"
                except Exception:
                    pass
                return {
                    "symbol":   symbol,
                    "price":    round(price, 4),
                    "change":   round(chg, 4),
                    "chg_pct":  round(chg / prev * 100 if prev else 0, 2),
                    "currency": currency,
                    "ts":       datetime.now().strftime("%H:%M:%S"),
                }
        except Exception as e:
            log.error(f"{symbol} canli fiyat hatasi 1h (deneme {attempt}): {e}")

        if attempt < retries:
            time.sleep(2 ** attempt)

    # Fallback: yfinance 1d son kapalis
    try:
        t = yf.Ticker(symbol)
        h = t.history(period="5d", interval="1d").dropna()
        if not h.empty:
            price = float(h["Close"].iloc[-1])
            prev  = float(h["Close"].iloc[-2]) if len(h) >= 2 else price
            chg   = price - prev
            return {
                "symbol":   symbol,
                "price":    round(price, 4),
                "change":   round(chg, 4),
                "chg_pct":  round(chg / prev * 100 if prev else 0, 2),
                "currency": "USD",
                "ts":       datetime.now().strftime("%H:%M:%S"),
            }
    except Exception as e:
        log.error(f"{symbol} fallback hatasi: {e}")

    return None


# ─────────────────────────────────────────────────────────────
# TOPLU GÜNCELLEME
# ─────────────────────────────────────────────────────────────
def refresh_all(cfg: dict) -> dict[str, pd.DataFrame]:
    db  = get_connection(cfg["database_path"])
    out = {}
    for sym in cfg["etf_list"]:
        df = fetch_history(sym, days=1260)
        if df is not None:
            save_ohlcv(db, sym, df)
            out[sym] = df
        else:
            df_db = load_ohlcv(db, sym, days=1260)
            if df_db is not None:
                out[sym] = df_db
                log.warning(f"{sym}: DB'den okundu.")
    db.close()
    return out
