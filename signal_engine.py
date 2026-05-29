"""
signal_engine.py
================
Çok faktörlü ağırlıklı skor tabanlı sinyal üretme motoru.
Spec'e birebir uygun A/B/C/D/E faktör grupları ile.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# SINYAL TANIMLAMALARI
# ─────────────────────────────────────────────────────────────

SIGNAL_MAP = [
    (75, 100, "GÜÇLÜ AL",  "🟢", "#00c853"),
    (60,  74, "AL",         "🔵", "#40c4ff"),
    (45,  59, "TUT",        "🟡", "#ffd740"),
    (30,  44, "SAT",        "🟠", "#ff9100"),
    ( 0,  29, "GÜÇLÜ SAT", "🔴", "#ff5252"),
]


def score_to_signal(score: float) -> tuple[str, str, str]:
    """Skoru sinyal adı, simge, renge dönüştürür."""
    for lo, hi, name, icon, color in SIGNAL_MAP:
        if lo <= score <= hi:
            return name, icon, color
    return "TUT", "🟡", "#ffd740"


# ─────────────────────────────────────────────────────────────
# SKOR HESAPLAMA
# ─────────────────────────────────────────────────────────────

@dataclass
class ScoreDetail:
    """Skor kırılımını tutan yapı."""
    group: str
    criterion: str
    weight: float
    earned: float
    note: str = ""


def compute_score(ind: dict, cfg: dict) -> dict:
    """
    Spec'e göre 0-100 arası AL skoru hesaplar.

    Args:
        ind : indicators.compute_all() çıktısı
        cfg : config["signal_config"]

    Returns:
        {score, signal_name, icon, color, details, bonuses, breakdown}
    """
    if "error" in ind:
        return {
            "score": 50, "signal_name": "TUT", "icon": "🟡",
            "color": "#ffd740", "details": [], "bonuses": [],
            "breakdown": {}, "total_weight": 0,
        }

    details: list[ScoreDetail] = []
    bonuses: list[ScoreDetail] = []
    rsi_cfg  = cfg.get("rsi_oversold", 30)
    rsi_ob   = cfg.get("rsi_overbought", 70)

    price   = ind.get("price") or 0
    sma50   = ind.get("sma50")
    sma200  = ind.get("sma200")
    rsi_val = ind.get("rsi")
    stoch_k = ind.get("stoch_k")
    bb_pos  = ind.get("bb_pos")         # 0=alt, 1=üst
    slope   = ind.get("slope_20")
    dist_low= ind.get("dist_from_low")  # %
    dev_min = ind.get("deviation_from_min")

    # ══════════════════════════════════════════════════════════
    # A. TREND FAKTÖRLERİ — %35
    # ══════════════════════════════════════════════════════════

    # A1. Fiyat > SMA200  (+12)
    a1 = 0.0
    if sma200 and price:
        a1 = 12.0 if price > sma200 else 0.0
    details.append(ScoreDetail("A-Trend", "Fiyat > SMA-200", 12, a1,
                               f"Fiyat={'✓' if a1 else '✗'} ({price:.2f} vs {sma200:.2f})" if sma200 else "N/A"))

    # A2. Fiyat > SMA50  (+10)
    a2 = 0.0
    if sma50 and price:
        a2 = 10.0 if price > sma50 else 0.0
    details.append(ScoreDetail("A-Trend", "Fiyat > SMA-50", 10, a2,
                               f"{'✓' if a2 else '✗'} ({price:.2f} vs {sma50:.2f})" if sma50 else "N/A"))

    # A3. Altın Kesişim: SMA50 > SMA200  (+8)
    a3 = 0.0
    if sma50 and sma200:
        a3 = 8.0 if sma50 > sma200 else 0.0
    details.append(ScoreDetail("A-Trend", "Altın Kesişim (SMA50>SMA200)", 8, a3,
                               "✓ Altın Kesişim" if a3 else "✗"))

    # A4. Pozitif regresyon eğimi  (+5)
    a4 = 0.0
    if slope is not None:
        a4 = 5.0 if slope > 0 else 0.0
    details.append(ScoreDetail("A-Trend", "20 Bar Regresyon Eğimi Pozitif", 5, a4,
                               f"Eğim={slope:.3f}%" if slope is not None else "N/A"))

    # ══════════════════════════════════════════════════════════
    # B. MOMENTUM FAKTÖRLERİ — %30
    # ══════════════════════════════════════════════════════════

    # B1. RSI Lineer Ölçek  (+12)
    b1 = 0.0
    if rsi_val is not None:
        if rsi_val <= rsi_cfg:
            b1 = 12.0
        elif rsi_val >= rsi_ob:
            b1 = 0.0
        else:
            # Lineer: 30→12, 70→0
            b1 = 12.0 * (rsi_ob - rsi_val) / (rsi_ob - rsi_cfg)
    details.append(ScoreDetail("B-Momentum", f"RSI (14) = {rsi_val:.1f}" if rsi_val else "RSI", 12, b1,
                               f"RSI={rsi_val:.1f} → +{b1:.1f}" if rsi_val else "N/A"))

    # B2. MACD > Sinyal  (+8)
    b2 = 8.0 if ind.get("macd_bull") else 0.0
    details.append(ScoreDetail("B-Momentum", "MACD > Sinyal Çizgisi", 8, b2,
                               "✓ Boğa" if b2 else "✗ Ayı"))

    # B3. Stokastik %K ≤ 20  (+5)
    b3 = 0.0
    if stoch_k is not None:
        if stoch_k <= 20:
            b3 = 5.0
        elif stoch_k >= 80:
            b3 = 0.0
        else:
            b3 = 5.0 * (80 - stoch_k) / 60
    details.append(ScoreDetail("B-Momentum", f"Stokastik %K = {stoch_k:.1f}" if stoch_k else "Stoch %K", 5, b3,
                               f"%K={stoch_k:.1f} → +{b3:.2f}" if stoch_k else "N/A"))

    # B4. Son 3 barda RSI yükselişi  (+5, her bar +1.67)
    b4 = min(5.0, (ind.get("rsi_rising_bars") or 0) * 1.67)
    details.append(ScoreDetail("B-Momentum", "Son 3 Barda RSI Yükselişi", 5, b4,
                               f"{ind.get('rsi_rising_bars',0)} bar yükseliyor"))

    # ══════════════════════════════════════════════════════════
    # C. VOLATİLİTE VE HACİM — %15
    # ══════════════════════════════════════════════════════════

    # C1. Bollinger Alt Bant Yakınlığı  (+6)
    c1 = 0.0
    if bb_pos is not None:
        if bb_pos <= 0.2:       # Alt banda çok yakın
            c1 = 6.0
        elif bb_pos <= 0.5:     # Orta bant altı
            c1 = 3.0
        elif bb_pos <= 0.65:    # Orta bant üzeri
            c1 = 1.5
    details.append(ScoreDetail("C-Volatilite", "Bollinger Alt Bant Yakınlığı", 6, c1,
                               f"BB Poz={bb_pos:.2f}" if bb_pos is not None else "N/A"))

    # C2. Hacim Spike  (+5)
    c2 = 5.0 if ind.get("vol_spike") else 0.0
    vol_ratio = ind.get("vol_ratio")
    details.append(ScoreDetail("C-Volatilite", "Hacim > 1.5× Ortalama", 5, c2,
                               f"Oran={vol_ratio:.2f}×" if vol_ratio else "N/A"))

    # C3. ATR Artıyor  (+4)
    c3 = 4.0 if ind.get("atr_rising") else 0.0
    details.append(ScoreDetail("C-Volatilite", "ATR Son 5 Barda Artıyor", 4, c3,
                               "✓ Volatilite artıyor" if c3 else "✗"))

    # ══════════════════════════════════════════════════════════
    # D. DESTEK / DİRENÇ — %12
    # ══════════════════════════════════════════════════════════

    # D1. 52 Hafta Düşüğüne Uzaklık  (+6)
    d1 = 0.0
    if dist_low is not None:
        if dist_low <= 5:
            d1 = 6.0
        elif dist_low <= 10:
            d1 = 4.0
        elif dist_low <= 20:
            d1 = 2.0
    details.append(ScoreDetail("D-Yapısal", "52H Düşüğüne Uzaklık", 6, d1,
                               f"%{dist_low:.1f} yukarıda" if dist_low is not None else "N/A"))

    # D2. Fibonacci 0.618/0.786 Yakınlığı  (+3)
    d2 = 3.0 if ind.get("fib_near") else 0.0
    details.append(ScoreDetail("D-Yapısal", "Fibonacci 0.618/0.786 Yakın", 3, d2,
                               "✓ Fibonacci desteği" if d2 else "✗"))

    # D3. Son 20 Bar Minimumdan Sapma < %10  (+3)
    d3 = 0.0
    if dev_min is not None and dev_min < 10:
        d3 = 3.0
    details.append(ScoreDetail("D-Yapısal", "20 Bar Minimum Yakınlığı (<10%)", 3, d3,
                               f"Sapma=%{dev_min:.1f}" if dev_min is not None else "N/A"))

    # ══════════════════════════════════════════════════════════
    # TOPLAM (Maks 100 - bonus hariç)
    # ══════════════════════════════════════════════════════════
    base_score = a1+a2+a3+a4 + b1+b2+b3+b4 + c1+c2+c3 + d1+d2+d3

    # ══════════════════════════════════════════════════════════
    # E. BONUS PUANLAR (Maks +8)
    # ══════════════════════════════════════════════════════════

    e1 = 3.0 if ind.get("rsi_reversal") else 0.0
    bonuses.append(ScoreDetail("E-Bonus", "RSI Oversold Dönüşü (+3)", 3, e1,
                               "✓ RSI dip dönüşü" if e1 else ""))

    e2 = 3.0 if ind.get("touched_200sma") else 0.0
    bonuses.append(ScoreDetail("E-Bonus", "SMA-200'e Dokunuş & Tepki (+3)", 3, e2,
                               "✓ SMA-200 desteği" if e2 else ""))

    e3 = 2.0 if ind.get("squeeze") else 0.0
    bonuses.append(ScoreDetail("E-Bonus", "Hacim Sıkışması (+2)", 2, e3,
                               "✓ Sıkışma var" if e3 else ""))

    bonus_total = min(8.0, e1 + e2 + e3)

    # ══════════════════════════════════════════════════════════
    # FİNAL SKOR
    # ══════════════════════════════════════════════════════════
    final_score = round(min(100.0, base_score + bonus_total), 1)
    signal_name, icon, color = score_to_signal(final_score)

    # Grup bazında kırılım
    breakdown = {
        "A-Trend (35)":        round(a1+a2+a3+a4, 1),
        "B-Momentum (30)":     round(b1+b2+b3+b4, 1),
        "C-Volatilite (15)":   round(c1+c2+c3, 1),
        "D-Yapısal (12)":      round(d1+d2+d3, 1),
        "E-Bonus (max 8)":     round(bonus_total, 1),
    }

    # Terminal bildirim (GÜÇLÜ AL / GÜÇLÜ SAT)
    if signal_name in ("GÜÇLÜ AL", "GÜÇLÜ SAT"):
        _terminal_alert(ind["symbol"], signal_name, final_score, icon)

    return {
        "score":       final_score,
        "signal_name": signal_name,
        "icon":        icon,
        "color":       color,
        "details":     details,
        "bonuses":     bonuses,
        "breakdown":   breakdown,
    }


def _terminal_alert(symbol: str, signal: str, score: float, icon: str):
    """GÜÇLÜ sinyal durumunda terminal'e renkli uyarı basar."""
    GREEN = "\033[1;92m"
    RED   = "\033[1;91m"
    RESET = "\033[0m"
    clr   = GREEN if "AL" in signal else RED
    print(f"\n{'█'*55}")
    print(f"{clr}  {icon}  {symbol}  —  {signal}  —  SKOR: {score}/100{RESET}")
    print(f"{'█'*55}\n")

    # ── Opsiyonel: Telegram Bildirimi ───────────────────────
    # import requests
    # BOT_TOKEN = "YOUR_BOT_TOKEN"
    # CHAT_ID   = "YOUR_CHAT_ID"
    # msg = f"{icon} {symbol} — {signal}\nSkor: {score}/100"
    # requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    #              params={"chat_id": CHAT_ID, "text": msg})


# ─────────────────────────────────────────────────────────────
# TOPLU SİNYAL HESAPLAMA
# ─────────────────────────────────────────────────────────────

def compute_all_signals(indicators_dict: dict[str, dict], cfg: dict) -> dict[str, dict]:
    """Tüm ETF'ler için skor hesaplar."""
    return {
        sym: compute_score(ind, cfg["signal_config"])
        for sym, ind in indicators_dict.items()
    }
