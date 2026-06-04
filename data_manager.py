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


def fetch_live_price(symbol: str, retries: int = 3) -> dict | None:
    """
    Anlık fiyat bilgisini çeker.
    yf.download() kullanır — hem US hem LSE sembolleri için güvenilir.
    auto_adjust=False → ham kapanış fiyatı, temettü/split etkisi yok.
    """
    for attempt in range(1, retries + 1):
        try:
            t = yf.Ticker(symbol)

            # ── Yöntem 1: 5 günlük download, auto_adjust=False ──
            # En güvenilir yöntem — LSE dahil tüm borsa sembolleri için çalışır
            df = yf.download(
                symbol,
                period="5d",
                interval="1d",
                auto_adjust=False,
                progress=False,
                timeout=12,
            )

            if df is not None and not df.empty:
                # MultiIndex olabilir, düzelt
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df.columns = [c.lower() for c in df.columns]

                price = float(df["close"].iloc[-1])
                prev  = float(df["close"].iloc[-2]) if len(df) >= 2 else price
                chg     = price - prev
                chg_pct = chg / prev * 100 if prev else 0

                fi = t.fast_info
                currency = "USD"
                try:
                    currency = getattr(fi, "currency", "USD") or "USD"
                except Exception:
                    pass

                return {
                    "symbol":   symbol,
                    "price":    round(price, 4),
                    "change":   round(chg, 4),
                    "chg_pct":  round(chg_pct, 2),
                    "currency": currency,
                    "ts":       datetime.now().strftime("%H:%M:%S"),
                }

        except Exception as e:
            log.error(f"{symbol} canlı fiyat hatası (deneme {attempt}): {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
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
