"""Forex & Commodities Market Engine Router.

Provides:
- Major/Minor FX pairs and Commodities metadata
- Global market session states (Sydney, Tokyo, London, New York)
- Live ticker data, spreads, bid/ask prices
- Forex technical radar signals (RSI, MACD, Trend conviction)
- Lot size, Pip value, and Margin requirement calculators
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import csv
import datetime
import io
import json
import logging
import math
import random
import time
import urllib.request
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/forex", tags=["forex"])

# Standard Forex & Commodities Universe
FOREX_SYMBOLS = [
    # Majors
    {
        "symbol": "EURUSD",
        "display": "EUR/USD",
        "name": "Euro / US Dollar",
        "category": "major",
        "base": "EUR",
        "quote": "USD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:EURUSD",
        "default_price": 1.08542,
    },
    {
        "symbol": "GBPUSD",
        "display": "GBP/USD",
        "name": "British Pound / US Dollar",
        "category": "major",
        "base": "GBP",
        "quote": "USD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:GBPUSD",
        "default_price": 1.29650,
    },
    {
        "symbol": "USDJPY",
        "display": "USD/JPY",
        "name": "US Dollar / Japanese Yen",
        "category": "major",
        "base": "USD",
        "quote": "JPY",
        "pip_size": 0.01,
        "digits": 3,
        "tv_symbol": "FX:USDJPY",
        "default_price": 152.450,
    },
    {
        "symbol": "USDCHF",
        "display": "USD/CHF",
        "name": "US Dollar / Swiss Franc",
        "category": "major",
        "base": "USD",
        "quote": "CHF",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:USDCHF",
        "default_price": 0.88420,
    },
    {
        "symbol": "AUDUSD",
        "display": "AUD/USD",
        "name": "Australian Dollar / US Dollar",
        "category": "major",
        "base": "AUD",
        "quote": "USD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:AUDUSD",
        "default_price": 0.65820,
    },
    {
        "symbol": "USDCAD",
        "display": "USD/CAD",
        "name": "US Dollar / Canadian Dollar",
        "category": "major",
        "base": "USD",
        "quote": "CAD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:USDCAD",
        "default_price": 1.38950,
    },
    {
        "symbol": "NZDUSD",
        "display": "NZD/USD",
        "name": "New Zealand Dollar / US Dollar",
        "category": "major",
        "base": "NZD",
        "quote": "USD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:NZDUSD",
        "default_price": 0.59750,
    },
    # Commodities / Precious Metals
    {
        "symbol": "XAUUSD",
        "display": "XAU/USD",
        "name": "Gold / US Dollar",
        "category": "commodity",
        "base": "XAU",
        "quote": "USD",
        "pip_size": 0.1,
        "digits": 2,
        "tv_symbol": "OANDA:XAUUSD",
        "default_price": 2735.60,
    },
    {
        "symbol": "XAGUSD",
        "display": "XAG/USD",
        "name": "Silver / US Dollar",
        "category": "commodity",
        "base": "XAG",
        "quote": "USD",
        "pip_size": 0.01,
        "digits": 3,
        "tv_symbol": "OANDA:XAGUSD",
        "default_price": 33.850,
    },
    {
        "symbol": "USOIL",
        "display": "WTI Oil",
        "name": "Crude Oil (WTI)",
        "category": "commodity",
        "base": "OIL",
        "quote": "USD",
        "pip_size": 0.01,
        "digits": 2,
        "tv_symbol": "TVC:USOIL",
        "default_price": 71.40,
    },
    # Indices
    {
        "symbol": "SPX500",
        "display": "S&P 500",
        "name": "S&P 500 Index",
        "category": "index",
        "base": "SPX",
        "quote": "USD",
        "pip_size": 0.1,
        "digits": 2,
        "tv_symbol": "FOREXCOM:SPXUSD",
        "default_price": 5830.20,
    },
    {
        "symbol": "NAS100",
        "display": "Nasdaq 100",
        "name": "US Tech 100 Index",
        "category": "index",
        "base": "NDX",
        "quote": "USD",
        "pip_size": 0.1,
        "digits": 2,
        "tv_symbol": "FOREXCOM:NSXUSD",
        "default_price": 20420.50,
    },
    # Crypto
    {
        "symbol": "BTCUSD",
        "display": "BTC/USD",
        "name": "Bitcoin / US Dollar",
        "category": "crypto",
        "base": "BTC",
        "quote": "USD",
        "pip_size": 1.0,
        "digits": 2,
        "tv_symbol": "BINANCE:BTCUSDT",
        "default_price": 66500.0,
    },
]

# In-memory realistic price and tick cache
_TICK_CACHE: Dict[str, Dict[str, Any]] = {}
_LAST_CACHE_TIME = 0.0


def _get_market_sessions() -> List[Dict[str, Any]]:
    """Determine which global forex trading sessions are currently active (UTC)."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    current_hour = now_utc.hour + now_utc.minute / 60.0
    weekday = now_utc.weekday()  # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday

    # Forex weekend market close check (Friday 21:00 UTC to Sunday 21:00 UTC)
    is_weekend = (weekday == 4 and current_hour >= 21) or (weekday == 5) or (weekday == 6 and current_hour < 21)

    sessions_def = [
        {"name": "Sydney", "flag": "🇦🇺", "open_utc": 21, "close_utc": 6, "city": "Sydney"},
        {"name": "Tokyo", "flag": "🇯🇵", "open_utc": 0, "close_utc": 9, "city": "Tokyo"},
        {"name": "London", "flag": "🇬🇧", "open_utc": 7, "close_utc": 16, "city": "London"},
        {"name": "New York", "flag": "🇺🇸", "open_utc": 12, "close_utc": 21, "city": "New York"},
    ]

    result = []
    for s in sessions_def:
        open_h = s["open_utc"]
        close_h = s["close_utc"]
        if open_h < close_h:
            is_active = open_h <= current_hour < close_h
        else:
            is_active = current_hour >= open_h or current_hour < close_h

        if is_weekend:
            is_active = False

        result.append({
            "name": s["name"],
            "flag": s["flag"],
            "city": s["city"],
            "active": is_active,
            "hours_utc": f"{s['open_utc']:02d}:00 - {s['close_utc']:02d}:00 UTC",
        })

    return result


_LAST_LIVE_FETCH_TIME = 0.0
_LIVE_PRICES_CACHE: Dict[str, float] = {}

# Hard Risk Constants (Strict ceilings enforced under all conditions)
HARD_MAX_FOREX_LOT = 0.05
HARD_MAX_GOLD_LOT = 0.02
HARD_MIN_GOLD_COOLDOWN_SEC = 60.0
HARD_MIN_BREAKEVEN_PIPS = 14.0

# Technical Analysis & Indicator Cache
_TECHNICAL_CACHE: Dict[str, Dict[str, Any]] = {}
_LAST_TECH_FETCH_TIME = 0.0
_LAST_GOLD_EXIT_TIME = 0.0
_LAST_CLOSED_DEAL_IDS: set = set()

YAHOO_SYMBOL_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
    "NZDUSD": "NZDUSD=X",
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F",
    "USOIL": "CL=F",
    "SPX500": "^GSPC",
    "NAS100": "^NDX",
    "BTCUSD": "BTC-USD",
}


def get_usd_bias(symbol: str, direction: str) -> str:
    """Determine if an order has USD_LONG, USD_SHORT, or USD_NEUTRAL exposure.
    Resilient to broker suffixes (.raw, .ecn, +, -, #) and non-standard commodity tickers.
    - Pairs with USD as Base (USDJPY, USDCAD, USDCHF): BUY -> USD_LONG, SELL -> USD_SHORT
    - Pairs with USD as Quote (EURUSD, GBPUSD, AUDUSD, NZDUSD, XAUUSD, XAGUSD, USOIL, SPX500, NAS100):
      BUY -> USD_SHORT, SELL -> USD_LONG
    """
    s = str(symbol).upper().replace("/", "").strip()
    clean_sym = s.split(".")[0].split("+")[0].split("-")[0].replace("#", "").strip()
    d = str(direction).upper()

    if clean_sym.startswith("USD"):
        return "USD_LONG" if d == "BUY" else "USD_SHORT"
    elif clean_sym.endswith("USD") or clean_sym in ("USOIL", "OIL", "WTI", "XAUUSD", "XAGUSD", "SPX500", "NAS100"):
        return "USD_SHORT" if d == "BUY" else "USD_LONG"
    return "USD_NEUTRAL"


def get_symbol_trading_specs(
    symbol: str,
    base_sl: float = 12.0,
    base_tp: float = 22.0,
    base_be: float = 10.0,
    base_trail: float = 16.0,
    atr_pips: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Her parite ve emtia için doğru pip büyüklüğünü (pip_size),
    volatilite çarpanını (mult), basamak sayısını (digits) ve lot başına 1 pip dolar değerini döner.

    Özellikle Ons Altın (XAUUSD) için:
    - MT5 ve uluslararası piyasalarda 1 pip = 0.10 USD (10 point / 10 cent) kabul edilir.
    - Altın'ın yüksek oynaklığı nedeniyle en az 3.0x volatilite tamponu (min 36 pip / $3.60 USD koruma)
      ve dinamik ATR(14) volatilite tamponu uygulanır. Volatilite arttığında SL dinamik olarak genişler.
    - Erken başabaş (breakeven) stop kilitlenmesini engellemek için altın BE eşiği en az 25 pip ($2.50) olmalıdır.
    - Standart paritelerde de erken boğulmayı engellemek için BE eşiği en az 10.0 pip olmalıdır.
    """
    s = str(symbol).upper().replace("/", "").strip()
    clean_sym = s.split(".")[0].split("+")[0].split("-")[0].replace("#", "").strip()
    base_be_floored = max(HARD_MIN_BREAKEVEN_PIPS, base_be)

    if "XAU" in clean_sym or "GOLD" in clean_sym:
        pip_size = 0.10          # 1 pip = 0.10 USD (10 cent / 10 point)
        mult = 3.0               # 3.0x taban volatilite nefes alma çarpanı
        digits = 2
        pip_val = 10.0           # 1 lot (100 oz) * 0.10 USD = $10.0
        base_sl_pips = round(base_sl * mult, 1)  # 12.0 * 3.0 = 36.0 pips ($3.60)
        base_tp_pips = round(base_tp * mult, 1)  # 22.0 * 3.0 = 66.0 pips ($6.60)

        # Dinamik ATR volatilite tamponu: ATR genişlediğinde SL ve TP dinamik genişletilir
        if atr_pips is not None and atr_pips > 0:
            eff_sl_pips = max(base_sl_pips, round(atr_pips * 1.5, 1))
        else:
            eff_sl_pips = base_sl_pips

        eff_tp_pips = max(base_tp_pips, round(eff_sl_pips * 1.83, 1))
        eff_be_pips = max(25.0, round(eff_sl_pips * 0.7, 1))
        eff_trail_pips = max(40.0, round(eff_sl_pips * 1.2, 1))

    elif "XAG" in clean_sym or "SILVER" in clean_sym:
        pip_size = 0.01          # 1 pip = 0.01 USD
        mult = 2.0
        digits = 3
        pip_val = 50.0           # 1 lot (5000 oz) * 0.01 USD = $50.0
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(20.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    elif "USOIL" in clean_sym or "OIL" in clean_sym or "WTI" in clean_sym:
        pip_size = 0.01          # 1 pip = 0.01 USD (1 cent)
        mult = 2.0
        digits = 2
        pip_val = 10.0           # 1 lot (1000 varil) * 0.01 USD = $10.0
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(20.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    elif "JPY" in clean_sym:
        pip_size = 0.01          # 1 pip = 0.01 JPY (10 point)
        mult = 1.0
        digits = 3
        pip_val = 6.60
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(HARD_MIN_BREAKEVEN_PIPS, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    elif "BTC" in clean_sym:
        pip_size = 1.0           # 1 pip = $1.00
        mult = 5.0
        digits = 2
        pip_val = 1.0
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(40.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    else:
        # Standart Forex (EURUSD, GBPUSD, AUDUSD, NZDUSD, USDCAD, USDCHF)
        pip_size = 0.0001        # 1 pip = 0.0001 (10 point)
        mult = 1.0
        digits = 5
        pip_val = 10.0
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(HARD_MIN_BREAKEVEN_PIPS, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    return {
        "pip_size": pip_size,
        "digits": digits,
        "pip_val": pip_val,
        "mult": mult,
        "sl_pips": eff_sl_pips,
        "tp_pips": eff_tp_pips,
        "be_pips": eff_be_pips,
        "trail_pips": eff_trail_pips,
    }


def _resample_5m_to_15m(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
) -> Tuple[List[float], List[float], List[float], List[float]]:
    """Resample 5-minute candles into 15-minute candles for multi-timeframe analysis."""
    n = len(closes)
    rem = n % 3
    o15, h15, l15, c15 = [], [], [], []
    for i in range(rem, n, 3):
        chunk_o = opens[i:i + 3]
        chunk_h = highs[i:i + 3]
        chunk_l = lows[i:i + 3]
        chunk_c = closes[i:i + 3]
        if chunk_c:
            o15.append(chunk_o[0])
            h15.append(max(chunk_h))
            l15.append(min(chunk_l))
            c15.append(chunk_c[-1])
    return o15, h15, l15, c15


def _compute_technical_indicators(
    closes: List[float],
    highs: List[float],
    lows: List[float],
    opens: List[float],
    symbol: str,
) -> Optional[Dict[str, Any]]:
    """Calculates Multi-Timeframe (15M HTF Trend + 5M LTF Execution) indicators, RSI(14), MACD, ATR, and composite score."""
    if len(closes) < 15:
        return None
    c = np.asarray(closes, dtype=float)
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)

    def _calc_ema(series: np.ndarray, period: int) -> np.ndarray:
        alpha = 2.0 / (period + 1)
        res = [float(series[0])]
        for val in series[1:]:
            res.append(alpha * float(val) + (1.0 - alpha) * res[-1])
        return np.array(res, dtype=float)

    # 1. 5M LTF EMAs
    ema9_series = _calc_ema(c, 9)
    ema21_series = _calc_ema(c, 21)
    ema50_series = _calc_ema(c, min(len(c), 50))

    ema9 = float(ema9_series[-1])
    ema21 = float(ema21_series[-1])
    ema50 = float(ema50_series[-1])
    last_price = float(c[-1])

    # 2. 15M HTF Trend Filter (Resampled from 5M bars)
    o15, h15, l15, c15 = _resample_5m_to_15m(opens, highs, lows, closes)
    if len(c15) >= 15:
        c15_arr = np.asarray(c15, dtype=float)
        ema_fast_15m = float(_calc_ema(c15_arr, 10)[-1])
        ema_slow_15m = float(_calc_ema(c15_arr, min(len(c15_arr), 25))[-1])
        if ema_fast_15m > ema_slow_15m and last_price >= ema_slow_15m * 0.998:
            htf_trend = "BULLISH"
        elif ema_fast_15m < ema_slow_15m and last_price <= ema_slow_15m * 1.002:
            htf_trend = "BEARISH"
        else:
            htf_trend = "NEUTRAL"
    else:
        # Fallback to 5M EMA21 vs EMA50 if not enough 15M bars
        htf_trend = "BULLISH" if ema21 > ema50 else ("BEARISH" if ema21 < ema50 else "NEUTRAL")

    # 3. Wilder-smoothed RSI 14 (5M)
    deltas = np.diff(c)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    period = 14
    if len(deltas) >= period:
        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * 13.0 + float(gains[i])) / 14.0
            avg_loss = (avg_loss * 13.0 + float(losses[i])) / 14.0
        rs = avg_gain / avg_loss if avg_loss != 0 else 100.0
        rsi = float(100.0 - (100.0 / (1.0 + rs)))
    else:
        rsi = 50.0

    # 4. MACD (12, 26, 9)
    fast = _calc_ema(c, 12)
    slow = _calc_ema(c, 26)
    macd_line = fast - slow
    signal_line = _calc_ema(macd_line, 9)
    hist = float(macd_line[-1] - signal_line[-1])

    # 5. ATR 14
    if len(h) >= 15:
        tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
        atr = float(np.mean(tr[-14:]))
    else:
        atr = float(np.mean(h - l)) if len(h) > 0 else 0.001

    first_open = float(opens[0]) if opens else float(c[0])
    change_pct = round(((last_price - first_open) / first_open) * 100.0, 2) if first_open > 0 else 0.0

    # 6. Multi-Timeframe Scoring & Trend Synthesis
    bullish_pts = 0
    bearish_pts = 0

    # (a) HTF 15M Trend Filter (30 Pts) - Trend direction gate
    if htf_trend == "BULLISH":
        bullish_pts += 30
    elif htf_trend == "BEARISH":
        bearish_pts += 30
    else:
        bullish_pts += 10
        bearish_pts += 10

    # (b) LTF 5M EMA Alignment (25 Pts)
    if last_price > ema9 > ema21 > ema50:
        bullish_pts += 25
    elif last_price < ema9 < ema21 < ema50:
        bearish_pts += 25
    elif ema9 > ema21:
        bullish_pts += 15
    elif ema9 < ema21:
        bearish_pts += 15

    # (c) RSI Pullback & Momentum (25 Pts)
    # Healthy pullback zone (sweet spot for scalper entry without chasing extremes)
    if 40.0 <= rsi <= 60.0:
        if htf_trend == "BULLISH":
            bullish_pts += 25
        elif htf_trend == "BEARISH":
            bearish_pts += 25
        else:
            bullish_pts += 12
            bearish_pts += 12
    elif 30.0 <= rsi < 40.0:
        # Oversold bounce opportunity
        bullish_pts += 20
    elif 60.0 < rsi <= 70.0:
        # Overbought pullback opportunity
        bearish_pts += 20
    elif rsi > 72.0:
        # Chasing extreme high - penalize bullish
        bullish_pts -= 15
        bearish_pts += 15
    elif rsi < 28.0:
        # Chasing extreme low - penalize bearish
        bearish_pts -= 15
        bullish_pts += 15

    # (d) MACD Histogram Momentum (20 Pts)
    if hist > 0:
        bullish_pts += 20
    else:
        bearish_pts += 20

    # MTF Alignment Verdict
    ltf_bullish = (ema9 > ema21 and last_price >= ema21 * 0.999)
    ltf_bearish = (ema9 < ema21 and last_price <= ema21 * 1.001)

    if (htf_trend == "BULLISH" or htf_trend == "NEUTRAL") and ltf_bullish and bullish_pts >= bearish_pts:
        trend = "BULLISH"
        action = "BUY" if rsi <= 78.0 else "HOLD"
        score = round(min(96.0, max(60.0, 50.0 + (bullish_pts * 0.46))), 1)
        macd_verdict = f"AL (MTF Boğa Uyumu | 15M: {htf_trend} + 5M Momentum)"
    elif (htf_trend == "BEARISH" or htf_trend == "NEUTRAL") and ltf_bearish and bearish_pts >= bullish_pts:
        trend = "BEARISH"
        action = "SELL" if rsi >= 22.0 else "HOLD"
        score = round(min(96.0, max(60.0, 50.0 + (bearish_pts * 0.46))), 1)
        macd_verdict = f"SAT (MTF Ayı Uyumu | 15M: {htf_trend} + 5M Momentum)"
    else:
        # Choppy, conflicting timeframes, or indecisive market
        trend = "NEUTRAL"
        action = "HOLD"
        score = round(max(50.0, min(58.0, 50.0 + abs(bullish_pts - bearish_pts) * 0.1)), 1)
        macd_verdict = f"NÖTR (MTF Uyumsuzluğu | 15M: {htf_trend}, 5M: {'Boğa' if ltf_bullish else 'Ayı'} - Beklemede)"

    return {
        "price": last_price,
        "high": float(np.max(h)),
        "low": float(np.min(l)),
        "change_pct": change_pct,
        "ema9": ema9,
        "ema21": ema21,
        "ema50": ema50,
        "rsi": round(rsi, 1),
        "macd_hist": round(hist, 6),
        "macd_verdict": macd_verdict,
        "atr": atr,
        "trend": trend,
        "action": action,
        "score": score,
        "htf_trend": htf_trend,
        "updated_at": time.time(),
    }


def _sync_fetch_candles_for_symbol(fx_sym: str, yf_sym: str) -> Optional[Dict[str, Any]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_sym}?interval=5m&range=2d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data["chart"]["result"][0]
            quote = result["indicators"]["quote"][0]
            opens = [o for o in quote.get("open", []) if o is not None]
            highs = [h for h in quote.get("high", []) if h is not None]
            lows = [l for l in quote.get("low", []) if l is not None]
            closes = [c for c in quote.get("close", []) if c is not None]
            if len(closes) >= 15:
                return _compute_technical_indicators(closes, highs, lows, opens, fx_sym)
    except Exception:
        pass
    return None


def _sync_fetch_all_technical_data() -> Dict[str, Dict[str, Any]]:
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        future_map = {
            executor.submit(_sync_fetch_candles_for_symbol, fx, yf): fx
            for fx, yf in YAHOO_SYMBOL_MAP.items()
        }
        for fut in concurrent.futures.as_completed(future_map, timeout=6.0):
            fx = future_map[fut]
            try:
                tech = fut.result()
                if tech:
                    results[fx] = tech
            except Exception:
                pass
    return results


def _sync_fetch_live_rates() -> Dict[str, float]:
    """Fetch real-world live FX rates from ECB/Frankfurter and fallback feeds."""
    rates_map: Dict[str, float] = {}
    try:
        req = urllib.request.Request(
            "https://api.frankfurter.app/latest?from=USD",
            headers={"User-Agent": "ScalperGlobal-Forex/1.0"},
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            r = data.get("rates", {})
            if "EUR" in r and r["EUR"] > 0:
                rates_map["EURUSD"] = round(1.0 / float(r["EUR"]), 5)
            if "GBP" in r and r["GBP"] > 0:
                rates_map["GBPUSD"] = round(1.0 / float(r["GBP"]), 5)
            if "JPY" in r and r["JPY"] > 0:
                rates_map["USDJPY"] = round(float(r["JPY"]), 3)
            if "CHF" in r and r["CHF"] > 0:
                rates_map["USDCHF"] = round(float(r["CHF"]), 5)
            if "AUD" in r and r["AUD"] > 0:
                rates_map["AUDUSD"] = round(1.0 / float(r["AUD"]), 5)
            if "CAD" in r and r["CAD"] > 0:
                rates_map["USDCAD"] = round(float(r["CAD"]), 5)
            if "NZD" in r and r["NZD"] > 0:
                rates_map["NZDUSD"] = round(1.0 / float(r["NZD"]), 5)
    except Exception:
        pass
    return rates_map


async def _refresh_live_rates_if_needed():
    """Update live prices and technical indicators cache asynchronously."""
    global _LAST_LIVE_FETCH_TIME, _LIVE_PRICES_CACHE, _TECHNICAL_CACHE, _LAST_TECH_FETCH_TIME
    now = time.time()

    # 1. Update Technical Indicators from Yahoo Finance candles every 15s
    if now - _LAST_TECH_FETCH_TIME > 15.0 or not _TECHNICAL_CACHE:
        _LAST_TECH_FETCH_TIME = now
        try:
            fresh_tech = await asyncio.to_thread(_sync_fetch_all_technical_data)
            if fresh_tech:
                _TECHNICAL_CACHE.update(fresh_tech)
                for sym, tech in fresh_tech.items():
                    _LIVE_PRICES_CACHE[sym] = tech["price"]
        except Exception:
            pass

    # 2. Update ECB Frankfurter rates every 20s as robust fallback
    if now - _LAST_LIVE_FETCH_TIME > 20.0 or not _LIVE_PRICES_CACHE:
        _LAST_LIVE_FETCH_TIME = now
        try:
            fresh_fx = await asyncio.to_thread(_sync_fetch_live_rates)
            if fresh_fx:
                for sym, p in fresh_fx.items():
                    if sym not in _LIVE_PRICES_CACHE:
                        _LIVE_PRICES_CACHE[sym] = p
        except Exception:
            pass


async def _generate_realistic_ticks() -> Dict[str, Dict[str, Any]]:
    """Maintain live bid/ask/spread rates grounded in real live market technical indicators."""
    global _LAST_CACHE_TIME, _TICK_CACHE
    await _refresh_live_rates_if_needed()
    now = time.time()

    for item in FOREX_SYMBOLS:
        sym = item["symbol"]
        pip = item["pip_size"]
        digits = item["digits"]

        tech = _TECHNICAL_CACHE.get(sym)
        live_p = _LIVE_PRICES_CACHE.get(sym) or (tech["price"] if tech else item["default_price"])

        spread_pips = 1.2 if item["category"] == "major" else (2.5 if item["category"] == "commodity" else (12.0 if item["category"] == "crypto" else 3.0))
        spread_val = spread_pips * pip

        bid_p = round(live_p - spread_val / 2.0, digits)
        ask_p = round(live_p + spread_val / 2.0, digits)

        if tech:
            score = tech["score"]
            trend = tech["trend"]
            action = tech.get("action", "BUY" if trend == "BULLISH" else ("SELL" if trend == "BEARISH" else "HOLD"))
            rsi = tech["rsi"]
            macd_verdict = tech["macd_verdict"]
            change_pct = tech["change_pct"]
            high_p = round(max(tech["high"], ask_p), digits)
            low_p = round(min(tech["low"], bid_p), digits)
            atr_val = tech["atr"]
        else:
            score = 50.0
            trend = "NEUTRAL"
            action = "HOLD"
            rsi = 50.0
            macd_verdict = "NÖTR (Veri Bekleniyor)"
            change_pct = 0.0
            high_p = round(live_p * 1.002, digits)
            low_p = round(live_p * 0.998, digits)
            atr_val = 15.0 * pip

        _TICK_CACHE[sym] = {
            "symbol": sym,
            "display": item["display"],
            "name": item["name"],
            "category": item["category"],
            "tv_symbol": item["tv_symbol"],
            "bid": bid_p,
            "ask": ask_p,
            "spread_pips": spread_pips,
            "change_pct": change_pct,
            "high": high_p,
            "low": low_p,
            "digits": digits,
            "pip_size": pip,
            "score": score,
            "trend": trend,
            "action": action,
            "rsi": rsi,
            "macd_verdict": macd_verdict,
            "atr": atr_val,
            "volatility": "HIGH" if ("XAU" in sym or "GOLD" in sym) else "NORMAL",
            "updated_at": now,
        }

    return _TICK_CACHE


class LotCalculatorRequest(BaseModel):
    account_balance: float = Field(10000.0, ge=1.0, description="Account balance in USD")
    risk_percentage: float = Field(1.0, ge=0.1, le=10.0, description="Risk per trade in percentage")
    stop_loss_pips: float = Field(25.0, ge=1.0, description="Stop loss distance in pips")
    symbol: str = Field("EURUSD", description="Forex pair")


@router.get("/symbols")
async def list_forex_symbols():
    """Return all configured forex pairs and commodities."""
    return {"symbols": FOREX_SYMBOLS}


@router.get("/sessions")
async def get_market_sessions():
    """Return active global forex trading sessions."""
    sessions = _get_market_sessions()
    active_count = sum(1 for s in sessions if s["active"])
    return {
        "sessions": sessions,
        "active_sessions_count": active_count,
        "is_overlap": active_count >= 2,
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@router.get("/tickers")
async def get_forex_tickers(category: Optional[str] = None):
    """Return live tickers with bid/ask, spreads and daily changes."""
    ticks = await _generate_realistic_ticks()
    results = list(ticks.values())
    if category:
        results = [t for t in results if t["category"] == category]
    return {
        "tickers": results,
        "sessions": _get_market_sessions(),
        "timestamp": time.time(),
    }


@router.get("/radar")
async def get_forex_radar():
    """Return high-probability forex momentum and breakout opportunities based on real indicators."""
    ticks = await _generate_realistic_ticks()
    candidates = []

    for sym, t in ticks.items():
        score = t.get("score", 45.0)
        trend = t.get("trend", "NEUTRAL")
        action = t.get("action", "BUY" if trend == "BULLISH" else ("SELL" if trend == "BEARISH" else "HOLD"))
        spread = t.get("spread_pips", 1.5)
        atr_pips = round(t.get("atr", 0.001) / t["pip_size"], 1) if t.get("pip_size", 0) > 0 else 15.0

        spec = get_symbol_trading_specs(
            sym,
            base_sl=_AUTO_SETTINGS.sl_pips,
            base_tp=_AUTO_SETTINGS.tp_pips,
            atr_pips=atr_pips,
        )

        candidates.append({
            "symbol": sym,
            "display": t["display"],
            "name": t["name"],
            "category": t["category"],
            "price": t["ask"],
            "bid": t["bid"],
            "ask": t["ask"],
            "spread_pips": spread,
            "score": score,
            "trend": trend,
            "action": action,
            "rsi_15m": t.get("rsi", 50.0),
            "macd_verdict": t.get("macd_verdict", "NÖTR (Beklemede)"),
            "pip_target": spec["tp_pips"],
            "stop_loss_pips": spec["sl_pips"],
            "risk_reward": f"1:{round(spec['tp_pips'] / spec['sl_pips'], 2)}" if spec["sl_pips"] > 0 else "1:1.83",
            "atr_pips": atr_pips,
            "tv_symbol": t["tv_symbol"],
        })

    # Sort by score descending
    candidates.sort(key=lambda x: x["score"], reverse=True)

    return {
        "candidates": candidates,
        "sessions": _get_market_sessions(),
        "total": len(candidates),
        "updated_at": time.time(),
    }


@router.post("/calculate-lot")
async def calculate_lot_size(req: LotCalculatorRequest):
    """Calculate standard, mini, and micro lot sizes based on capital risk with hard ceilings."""
    risk_amount_usd = req.account_balance * (req.risk_percentage / 100.0)

    spec = get_symbol_trading_specs(req.symbol, base_sl=req.stop_loss_pips)
    pip_val_standard_lot = spec["pip_val"]
    eff_sl_pips = spec["sl_pips"]

    total_risk_per_standard_lot = eff_sl_pips * pip_val_standard_lot
    recommended_lots = risk_amount_usd / total_risk_per_standard_lot if total_risk_per_standard_lot > 0 else 0.0

    standard_lots = round(recommended_lots, 2)
    mini_lots = round(recommended_lots * 10, 2)
    micro_lots = round(recommended_lots * 100, 2)

    # Sert lot tavanı koruması (asla aşılamaz)
    is_gold = ("XAU" in req.symbol.upper() or "GOLD" in req.symbol.upper() or "BTC" in req.symbol.upper())
    lot_ceiling = min(HARD_MAX_GOLD_LOT, _AUTO_SETTINGS.max_gold_lot) if is_gold else min(HARD_MAX_FOREX_LOT, _AUTO_SETTINGS.max_forex_lot)
    safe_lots = round(max(0.01, min(standard_lots, lot_ceiling)), 2)

    return {
        "symbol": req.symbol,
        "account_balance": req.account_balance,
        "risk_percentage": req.risk_percentage,
        "risk_amount_usd": round(risk_amount_usd, 2),
        "stop_loss_pips": eff_sl_pips,
        "standard_lots": standard_lots,
        "safe_capped_lots": safe_lots,
        "mini_lots": mini_lots,
        "micro_lots": micro_lots,
        "units": int(safe_lots * 100_000),
    }


# ============================================================================
# OTONOM FOREX PAPER TRADE SCALPING MOTORU (M1 / M5 Dynamic Exit & Risk Engine)
# ============================================================================

class ForexAutoPaperSettings(BaseModel):
    enabled: bool = False
    balance: float = Field(10000.0, ge=100.0, description="Demo bakiye (USD)")
    risk_per_trade_pct: float = Field(1.0, ge=0.1, le=5.0, description="İşlem başına sermaye riski (%)")
    max_open_positions: int = Field(3, ge=1, le=10, description="Aynı anda maksimum açık işlem")
    min_score: float = Field(70.0, ge=50.0, le=98.0, description="Minimum sinyal radar skoru")
    tp_pips: float = Field(26.0, ge=18.0, le=80.0, description="Kâr al mesafesi (pip)")
    sl_pips: float = Field(12.0, ge=10.0, le=30.0, description="Zarar durdur mesafesi (pip)")
    breakeven_pips: float = Field(14.0, ge=8.0, le=35.0, description="Başabaş kilit tetik mesafesi (varsayılan: 14.0 pip, min uygulanan: 14.0 pip)")
    trailing_stop_pips: float = Field(20.0, ge=14.0, le=50.0, description="İz süren stop mesafesi (pip)")
    session_filter: bool = Field(False, description="Seans filtresi (False: Asya ve tüm seanslarda kesintisiz işlem açılır)")
    max_spread_pips: float = Field(3.0, ge=0.5, le=10.0, description="Maksimum izin verilen spread (pip)")
    max_forex_lot: float = Field(0.05, ge=0.01, le=HARD_MAX_FOREX_LOT, description="Maksimum Forex lot tavanı (Sert tavan: 0.05)")
    max_gold_lot: float = Field(0.02, ge=0.01, le=HARD_MAX_GOLD_LOT, description="Maksimum Altın (XAUUSD) ve Kripto lot tavanı (Sert tavan: 0.02)")
    gold_cooldown_sec: float = Field(60.0, ge=HARD_MIN_GOLD_COOLDOWN_SEC, le=900.0, description="Altın (XAUUSD) kapanış sonrası soğuma süresi (min 60 sn)")
    usd_correlation_guard: bool = Field(False, description="USD yönlü kümelenmeyi engelleyen kalkan (Varsayılan: False - Tüm pariteler bağımsız çalışır)")
    allowed_symbols: List[str] = Field(
        default=["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDCAD", "AUDUSD", "BTCUSD"],
        description="İşleme izin verilen pariteler",
    )


class ClosePositionRequest(BaseModel):
    id: str


class ToggleAutoPaperRequest(BaseModel):
    enabled: bool


# Engine In-Memory State
_AUTO_PAPER_LOCK = asyncio.Lock()
_AUTO_PAPER_TASK: Optional[asyncio.Task] = None
_LAST_SESSION_BLOCK_LOG_TIME = 0.0
_LAST_SCAN_PULSE_TIME = 0.0
_LAST_CANDIDATE_LOG_TIME: Dict[str, float] = {}
_LAST_SYMBOL_ENTRY_TIME: Dict[str, float] = {}

_AUTO_SETTINGS = ForexAutoPaperSettings()

# IC Markets MT5 Durumu (Global Köprü Paylaşımı)
_MT5_STATE: Dict[str, Any] = {
    "connected": False,
    "last_ping": 0.0,
    "auto_trade": True,
    "account": {
        "login": 53077151,
        "name": "ERKAN ERDEM",
        "server": "ICMarketsSC-Demo",
        "balance": 1000.0,
        "equity": 1000.0,
        "margin": 0.0,
        "free_margin": 1000.0,
        "leverage": 5000,
        "currency": "USD",
    },
    "open_positions": [],
    "closed_deals": [],
    "pending_commands": [],
}

_AUTO_STATE: Dict[str, Any] = {
    "enabled": False,
    "balance": 10000.0,
    "initial_balance": 10000.0,
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "realized_pnl_usd": 0.0,
    "realized_pnl_pips": 0.0,
    "open_positions": [],
    "closed_trades": [],
    "decision_logs": [],
    "last_scan_time": 0.0,
    "last_status": "Durduruldu",
}


def _log_auto_decision(category: str, message: str, symbol: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
    """Kayıt defterine otonom karar gerekçesi ekler (şeffaf izleme)."""
    # Mükerrer ardışık logları engelle
    if _AUTO_STATE["decision_logs"]:
        if _AUTO_STATE["decision_logs"][0].get("message") == message:
            return

    log_item = {
        "id": f"LOG-{int(time.time() * 1000) % 1000000}",
        "time": datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC"),
        "category": category,
        "symbol": symbol,
        "message": message,
        "metadata": metadata or {},
    }
    _AUTO_STATE["decision_logs"].insert(0, log_item)
    if len(_AUTO_STATE["decision_logs"]) > 120:
        _AUTO_STATE["decision_logs"] = _AUTO_STATE["decision_logs"][:120]


async def _close_position_internal(pos_id: str, reason: str, exit_price: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Açık pozisyonu kapatır ve muhasebeleştirir."""
    async with _AUTO_PAPER_LOCK:
        open_list = _AUTO_STATE["open_positions"]
        target = None
        for p in open_list:
            if p["id"] == pos_id:
                target = p
                break
        if not target:
            return None

        open_list.remove(target)

        pip_size = target["pip_size"]
        cur_p = exit_price if exit_price is not None else target["current_price"]
        direction = target["direction"]

        # Final PnL hesaplama
        if direction == "BUY":
            pnl_pips = (cur_p - target["entry_price"]) / pip_size
        else:
            pnl_pips = (target["entry_price"] - cur_p) / pip_size

        pip_usd_val = 6.60 if "JPY" in target["symbol"] else 10.0
        pnl_usd = round(pnl_pips * target["lots"] * pip_usd_val, 2)
        pnl_pips = round(pnl_pips, 1)

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_time = time.time()
        open_ts = target.get("opened_at_ts", now_time)
        dur_sec = max(1, int(now_time - open_ts))
        dur_human = f"{dur_sec // 60} dk {dur_sec % 60} sn" if dur_sec >= 60 else f"{dur_sec} sn"

        reason_titles = {
            "TP_HIT": "🎯 Kâr Al (TP)",
            "SL_HIT": "🛑 Zarar Kes (SL)",
            "BE_HIT": "🛡️ Başabaş (BE)",
            "TRAILING_HIT": "📈 İz Süren (Trailing)",
            "MANUAL": "✋ Manuel Kapatma",
            "REVERSAL_FLIP": "🔄 Trend Dönüşü (Flip Reversal)",
        }
        human_reason = reason_titles.get(reason, reason)
        bal_after = round(_AUTO_STATE["balance"] + pnl_usd, 2)

        closed_item = {
            **target,
            "exit_price": cur_p,
            "exit_time": now_utc.strftime("%H:%M:%S UTC"),
            "exit_time_iso": now_utc.isoformat(),
            "closed_at_ts": now_time,
            "duration_sec": dur_sec,
            "duration_human": dur_human,
            "exit_reason": reason,
            "exit_reason_title": human_reason,
            "pnl_usd": pnl_usd,
            "pnl_pips": pnl_pips,
            "balance_after": bal_after,
            "outcome": "WIN" if pnl_usd >= 0 else "LOSS",
        }

        _AUTO_STATE["balance"] = bal_after
        _AUTO_STATE["realized_pnl_usd"] = round(_AUTO_STATE["realized_pnl_usd"] + pnl_usd, 2)
        _AUTO_STATE["realized_pnl_pips"] = round(_AUTO_STATE["realized_pnl_pips"] + pnl_pips, 1)
        _AUTO_STATE["total_trades"] += 1
        if pnl_usd >= 0:
            _AUTO_STATE["wins"] += 1
        else:
            _AUTO_STATE["losses"] += 1

        _AUTO_STATE["closed_trades"].insert(0, closed_item)
        if len(_AUTO_STATE["closed_trades"]) > 1000:
            _AUTO_STATE["closed_trades"] = _AUTO_STATE["closed_trades"][:1000]

        _log_auto_decision(
            "EXIT",
            f"{target.get('display', target.get('symbol', ''))} {human_reason} ile kapandı: ${pnl_usd:+.2f} ({pnl_pips:+.1f} pip)",
            symbol=target["symbol"],
            metadata={"pnl_usd": pnl_usd, "pnl_pips": pnl_pips, "reason": reason},
        )

        # Altın pozisyonu kapandığında 180 saniye soğuma sayacını başlat
        sym_closed = target.get("symbol", "").upper()
        if "XAU" in sym_closed or "GOLD" in sym_closed:
            global _LAST_GOLD_EXIT_TIME
            _LAST_GOLD_EXIT_TIME = time.time()

        # MT5 Köprüsü bağlıysa ve otomatik iletim aktifse, MT5'teki açık pozisyonu da otomatik kapat
        if _MT5_STATE.get("connected") and _MT5_STATE.get("auto_trade"):
            sym_target = target["symbol"].upper()
            for mpos in list(_MT5_STATE.get("open_positions", [])):
                if mpos.get("symbol", "").upper() == sym_target:
                    t_id = mpos.get("ticket")
                    if t_id:
                        already_closing = any(c.get("ticket") == t_id for c in _MT5_STATE.get("pending_commands", []))
                        if not already_closing:
                            _MT5_STATE["pending_commands"].append({
                                "id": f"CMD-CLOSE-{t_id}",
                                "action": "CLOSE_ORDER",
                                "ticket": t_id,
                            })
                            _log_auto_decision(
                                "EXIT",
                                f"🛑 [MT5 Senkron Kapatma]: {target['display']} Bilet #{t_id} kapatma emri iletildi ({human_reason})",
                                symbol=target["symbol"],
                            )

        return closed_item


async def _forex_auto_paper_loop():
    """Arka plan otonom forex scalper izleme ve işlem açma döngüsü."""
    global _LAST_SESSION_BLOCK_LOG_TIME, _LAST_SCAN_PULSE_TIME
    logger.info("Forex Otonom Scalper Döngüsü Başlatıldı.")
    _AUTO_STATE["last_status"] = "Çalışıyor (Canlı Piyasa Taranıyor)"

    while _AUTO_STATE["enabled"]:
        try:
            await asyncio.sleep(1.5)
            ticks = await _generate_realistic_ticks()
            sessions = _get_market_sessions()
            now_ts = time.time()
            _AUTO_STATE["last_scan_time"] = now_ts

            # ---------------------------------------------------------------
            # 1. AÇIK POZİSYONLARI GÜNCELLE & SL/TP/TRAILING/BE DENETLE
            # ---------------------------------------------------------------
            positions_to_close = []
            async with _AUTO_PAPER_LOCK:
                for pos in _AUTO_STATE["open_positions"]:
                    sym = pos["symbol"]
                    t = ticks.get(sym)
                    if not t:
                        continue

                    pip_size = pos["pip_size"]
                    digits = pos["digits"]
                    direction = pos["direction"]
                    entry_p = pos["entry_price"]

                    # Alış pozisyonu Bid fiyatından, Satış pozisyonu Ask fiyatından kapatılır
                    cur_p = t["bid"] if direction == "BUY" else t["ask"]
                    pos["current_price"] = cur_p

                    # PnL hesapla
                    if direction == "BUY":
                        pnl_pips = (cur_p - entry_p) / pip_size
                    else:
                        pnl_pips = (entry_p - cur_p) / pip_size

                    pip_usd_val = 6.60 if "JPY" in sym else 10.0
                    pos["pnl_pips"] = round(pnl_pips, 1)
                    pos["pnl_usd"] = round(pnl_pips * pos["lots"] * pip_usd_val, 2)

                    spec = get_symbol_trading_specs(
                        sym,
                        base_be=_AUTO_SETTINGS.breakeven_pips,
                        base_trail=_AUTO_SETTINGS.trailing_stop_pips,
                    )
                    eff_be_pips = spec["be_pips"]
                    eff_trail_pips = spec["trail_pips"]

                    # (a) BAŞABAŞ (BREAKEVEN) DENETİMİ
                    if pnl_pips >= eff_be_pips and not pos["breakeven_activated"]:
                        buffer_pips = 5.0 if ("XAU" in sym or "GOLD" in sym) else (15.0 if "BTC" in sym else 3.0)
                        be_sl = round(entry_p + (buffer_pips * pip_size if direction == "BUY" else -buffer_pips * pip_size), digits)
                        pos["sl_price"] = be_sl
                        pos["breakeven_activated"] = True
                        _log_auto_decision(
                            "PROTECT",
                            f"{pos['display']} Başabaş (BE) kilitlendi: Kâr +{pnl_pips:.1f} pip. Stop seviyesi {be_sl} yapıldı.",
                            symbol=sym,
                        )
                        # MT5 açık biletlerinde de Stop Loss'u başabaş seviyesine çek
                        if _MT5_STATE.get("connected") and _MT5_STATE.get("auto_trade"):
                            for mpos in _MT5_STATE.get("open_positions", []):
                                if mpos.get("symbol", "").upper() == sym.upper():
                                    t_id = mpos.get("ticket")
                                    if t_id:
                                        _MT5_STATE["pending_commands"].append({
                                            "id": f"CMD-MODIFY-{t_id}-BE",
                                            "action": "MODIFY_SLTP",
                                            "ticket": t_id,
                                            "sl": be_sl,
                                            "tp": mpos.get("tp_price", 0.0),
                                        })
                                        _log_auto_decision("PROTECT", f"🛡️ [MT5] {sym} Bilet #{t_id} Başabaş Stopu {be_sl} olarak kilitlendi.", symbol=sym)

                    # (b) İZ SÜREN STOP (TRAILING STOP) DENETİMİ
                    if pnl_pips >= eff_trail_pips:
                        trail_dist = eff_trail_pips * pip_size
                        updated_trail = False
                        if direction == "BUY":
                            cand_sl = round(cur_p - trail_dist, digits)
                            if cand_sl > pos["sl_price"]:
                                pos["sl_price"] = cand_sl
                                pos["trailing_activated"] = True
                                updated_trail = True
                        else:
                            cand_sl = round(cur_p + trail_dist, digits)
                            if cand_sl < pos["sl_price"]:
                                pos["sl_price"] = cand_sl
                                pos["trailing_activated"] = True
                                updated_trail = True

                        # MT5 açık biletinde de Stop Loss seviyesini dinamik olarak yukarı sür
                        if updated_trail and _MT5_STATE.get("connected") and _MT5_STATE.get("auto_trade"):
                            for mpos in _MT5_STATE.get("open_positions", []):
                                if mpos.get("symbol", "").upper() == sym.upper():
                                    t_id = mpos.get("ticket")
                                    if t_id:
                                        _MT5_STATE["pending_commands"].append({
                                            "id": f"CMD-MODIFY-{t_id}-TR",
                                            "action": "MODIFY_SLTP",
                                            "ticket": t_id,
                                            "sl": pos["sl_price"],
                                            "tp": mpos.get("tp_price", 0.0),
                                        })

                    # (c) KÂR AL (TAKE PROFIT) KONTROLÜ
                    if direction == "BUY" and cur_p >= pos["tp_price"]:
                        positions_to_close.append((pos["id"], "TP_HIT", cur_p))
                    elif direction == "SELL" and cur_p <= pos["tp_price"]:
                        positions_to_close.append((pos["id"], "TP_HIT", cur_p))

                    # (d) ZARAR DURDUR (STOP LOSS) KONTROLÜ
                    elif direction == "BUY" and cur_p <= pos["sl_price"]:
                        reason = "BE_HIT" if pos["breakeven_activated"] and pos["pnl_pips"] >= 0 else "SL_HIT"
                        positions_to_close.append((pos["id"], reason, cur_p))
                    elif direction == "SELL" and cur_p >= pos["sl_price"]:
                        reason = "BE_HIT" if pos["breakeven_activated"] and pos["pnl_pips"] >= 0 else "SL_HIT"
                        positions_to_close.append((pos["id"], reason, cur_p))

            # Pozisyonları kapat
            for pid, rsn, p_exit in positions_to_close:
                await _close_position_internal(pid, rsn, p_exit)

            # ---------------------------------------------------------------
            # 2. YENİ İŞLEM FIRSATLARI DEĞERLENDİRME & GİRİŞ (IC MARKETS MT5)
            # ---------------------------------------------------------------
            active_count = len(_MT5_STATE.get("open_positions", [])) if _MT5_STATE.get("connected") else len(_AUTO_STATE.get("open_positions", []))
            if active_count >= _AUTO_SETTINGS.max_open_positions:
                if now_ts - _LAST_SCAN_PULSE_TIME > 30.0:
                    _LAST_SCAN_PULSE_TIME = now_ts
                    _log_auto_decision(
                        "GATE",
                        f"Maksimum açık pozisyon limitine ulaşıldı ({active_count}/{_AUTO_SETTINGS.max_open_positions}). Yeni emir beklemede.",
                    )
                continue

            # Seans Filtresi Kontrolü
            active_names = [s["name"] for s in sessions if s["active"]]
            any_session_active = len(active_names) > 0
            if _AUTO_SETTINGS.session_filter and not any_session_active:
                if now_ts - _LAST_SESSION_BLOCK_LOG_TIME > 120:
                    _LAST_SESSION_BLOCK_LOG_TIME = now_ts
                    _log_auto_decision(
                        "GATE",
                        "Hafta sonu Forex piyasası kapalı. Yeni seans açılışı bekleniyor.",
                    )
                continue

            # Radar Sinyallerini Al
            radar_res = await get_forex_radar()
            candidates = radar_res.get("candidates", [])

            # Periyodik Canlı Tarama Özeti (Her 15 saniyede bir Decision Stream'e düşer)
            if now_ts - _LAST_SCAN_PULSE_TIME > 15.0 and candidates:
                _LAST_SCAN_PULSE_TIME = now_ts
                active_str = ", ".join(active_names) if active_names else "24/5 Açık"
                top_3 = ", ".join([f"{c['display']} (Skor:{c['score']:.0f} {c['action']})" for c in candidates[:3]])
                _log_auto_decision(
                    "SCAN",
                    f"🔍 Radar Taraması: {len(candidates)} parite analiz edildi. [Öncü: {top_3}] (Seanslar: {active_str})",
                )

            mt5_active_syms = {p.get("symbol", "").upper() for p in _MT5_STATE.get("open_positions", [])}
            auto_active_syms = {p.get("symbol", "").upper() for p in _AUTO_STATE.get("open_positions", [])}
            pending_mt5_syms = {c.get("symbol", "").upper() for c in _MT5_STATE.get("pending_commands", []) if c.get("action") == "OPEN_ORDER"}
            all_active_syms = mt5_active_syms | auto_active_syms | pending_mt5_syms

            for cand in candidates:
                sym = cand["symbol"].upper()
                if sym not in _AUTO_SETTINGS.allowed_symbols:
                    continue

                # 1. Zaten açık pozisyon veya bekleyen MT5 emri var mı? (Anti-Duplicate & Position Reversal/Flip)
                new_action = cand.get("action", "")  # "BUY" or "SELL"
                if new_action not in ("BUY", "SELL"):
                    continue

                if sym in all_active_syms:
                    existing_dirs = set()
                    matching_auto = [p for p in _AUTO_STATE.get("open_positions", []) if p.get("symbol", "").upper() == sym]
                    matching_mt5 = [p for p in _MT5_STATE.get("open_positions", []) if p.get("symbol", "").upper() == sym]
                    matching_pending = [c for c in _MT5_STATE.get("pending_commands", []) if c.get("action") == "OPEN_ORDER" and c.get("symbol", "").upper() == sym]

                    for p in matching_auto:
                        existing_dirs.add(p.get("direction", "").upper())
                    for p in matching_mt5:
                        existing_dirs.add(p.get("direction", "").upper())
                    for c in matching_pending:
                        existing_dirs.add(c.get("direction", "").upper())

                    # (a) Aynı yönlü pozisyon zaten açıksa (örn: BUY açıkken tekrar BUY) -> Mükerrer açma, pas geç
                    if new_action in existing_dirs:
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_open", 0) > 40.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_open"] = now_ts
                            _log_auto_decision(
                                "SCAN",
                                f"[{cand['display']}] Tarandı: Skor {cand['score']:.1f} ({new_action}) fakat aynı yönlü pozisyon zaten açık/beklemede. Yeni giriş pas geçildi.",
                                symbol=sym,
                            )
                        continue

                    # (b) ZIT yönlü pozisyon varsa (örn: BUY açıkken SELL sinyali geldiyse veya tersi):
                    # Ve sinyal yeterince güçlüyse (skor >= min_score ve spread uygunsa)
                    if cand.get("score", 0.0) >= _AUTO_SETTINGS.min_score and cand.get("spread_pips", 99.0) <= _AUTO_SETTINGS.max_spread_pips:
                        old_dir_str = "/".join(existing_dirs) if existing_dirs else "TERS"
                        _log_auto_decision(
                            "REVERSAL",
                            f"🔄 [{cand['display']}] TREND DÖNÜŞÜ (FLIP): Açık {old_dir_str} pozisyonu kapatılıyor -> Yeni {new_action} açılıyor! (Skor: {cand['score']:.1f})",
                            symbol=sym,
                        )
                        # Önce açık auto-paper pozisyonunu kapat
                        for ap in matching_auto:
                            t_sym = ticks.get(sym)
                            exit_p = (t_sym["bid"] if ap.get("direction") == "BUY" else t_sym["ask"]) if t_sym else None
                            await _close_position_internal(ap["id"], "REVERSAL_FLIP", exit_p)

                        # MT5 açık pozisyonu varsa kapatma komutu ilet
                        for mp in matching_mt5:
                            t_id = mp.get("ticket")
                            if t_id:
                                _MT5_STATE["pending_commands"].append({
                                    "id": f"CMD-CLOSE-{t_id}-FLIP",
                                    "action": "CLOSE_ORDER",
                                    "ticket": t_id,
                                })

                        # Eski yöndeki bekleyen emirler varsa temizle
                        _MT5_STATE["pending_commands"] = [
                            c for c in _MT5_STATE.get("pending_commands", [])
                            if not (c.get("action") == "OPEN_ORDER" and c.get("symbol", "").upper() == sym and c.get("direction") != new_action)
                        ]

                        # Anında ters yöne geçebilmek için sembol soğumasını sıfırla
                        _LAST_SYMBOL_ENTRY_TIME[sym] = 0.0
                        if "XAU" in sym or "GOLD" in sym:
                            _LAST_GOLD_EXIT_TIME = 0.0

                        # Döngü devam eder ve aşağıda yeni new_action (BUY/SELL) emrini açar!
                    else:
                        # Zıt yönlü ama skor eşiğini henüz aşmamışsa mevcut işlemi bozma
                        continue

                is_gold = ("XAU" in sym or "GOLD" in sym)

                # 2. Ons Altın (XAUUSD) Özel Soğuma Koruması (Kapanıştan sonra en az 180 sn bekleme kuralı)
                if is_gold:
                    time_since_gold_exit = now_ts - _LAST_GOLD_EXIT_TIME
                    if time_since_gold_exit < _AUTO_SETTINGS.gold_cooldown_sec:
                        remaining_cd = int(_AUTO_SETTINGS.gold_cooldown_sec - time_since_gold_exit)
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_gold_cd", 0) > 30.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_gold_cd"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}] Ons Altın Soğuma Kalkanı: Kapanıştan sonra {remaining_cd} sn bekleniyor (min {_AUTO_SETTINGS.gold_cooldown_sec:.0f} sn kuralı).",
                                symbol=sym,
                            )
                        continue

                # 3. Sembol Soğuma Süresi
                sym_cd = _AUTO_SETTINGS.gold_cooldown_sec if is_gold else 60.0
                if now_ts - _LAST_SYMBOL_ENTRY_TIME.get(sym, 0) < sym_cd:
                    continue

                # 4. USD Korelasyon Kalkanı (Anti-Clustering Koruması)
                direction = cand.get("action", "")  # BUY or SELL
                if direction not in ("BUY", "SELL"):
                    continue
                cand_usd_bias = get_usd_bias(sym, direction)

                if _AUTO_SETTINGS.usd_correlation_guard and cand_usd_bias != "USD_NEUTRAL":
                    active_usd_biases = []
                    all_active_positions = list(_MT5_STATE.get("open_positions", [])) + list(_AUTO_STATE.get("open_positions", []))
                    for p in all_active_positions:
                        b = get_usd_bias(p.get("symbol", ""), p.get("direction", "BUY"))
                        if b != "USD_NEUTRAL":
                            active_usd_biases.append((p.get("symbol", ""), b))
                    for c in _MT5_STATE.get("pending_commands", []):
                        if c.get("action") == "OPEN_ORDER":
                            b = get_usd_bias(c.get("symbol", ""), c.get("direction", "BUY"))
                            if b != "USD_NEUTRAL":
                                active_usd_biases.append((c.get("symbol", ""), b))

                    conflicting = [item for item in active_usd_biases if item[1] == cand_usd_bias]
                    if conflicting:
                        conf_sym = conflicting[0][0]
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_usd_corr", 0) > 30.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_usd_corr"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}] USD Korelasyon Kalkanı: Zaten {cand_usd_bias} yönlü açık pozisyon var ({conf_sym}). Aynı yönlü yeni USD riski engellendi.",
                                symbol=sym,
                            )
                        continue

                # 5. Spread Filtresi
                effective_max_spread = 20.0 if "BTC" in sym else _AUTO_SETTINGS.max_spread_pips
                if cand["spread_pips"] > effective_max_spread:
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_spread", 0) > 25.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_spread"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}] Tarandı: Spread engeli ({cand['spread_pips']:.1f}p > {effective_max_spread:.1f}p limit). İşlem engellendi.",
                            symbol=sym,
                        )
                    continue

                # 6. Skor Eşiği
                if cand["score"] < _AUTO_SETTINGS.min_score:
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_score", 0) > 25.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_score"] = now_ts
                        _log_auto_decision(
                            "SCAN",
                            f"[{cand['display']}] Tarandı: Skor yetersiz ({cand['score']:.1f} < {_AUTO_SETTINGS.min_score:.0f} eşik) | Yön: {cand['action']} | Spread: {cand['spread_pips']:.1f}p | Beklemede.",
                            symbol=sym,
                        )
                    continue

                # 7. Dinamik Lot & Sert Lot Tavanı (Hard Lot Cap)
                t = ticks.get(sym)
                if not t:
                    continue

                atr_pips = round(t.get("atr", 0.001) / t["pip_size"], 1) if t.get("pip_size", 0) > 0 else 15.0
                spec = get_symbol_trading_specs(
                    sym,
                    base_sl=_AUTO_SETTINGS.sl_pips,
                    base_tp=_AUTO_SETTINGS.tp_pips,
                    base_be=_AUTO_SETTINGS.breakeven_pips,
                    base_trail=_AUTO_SETTINGS.trailing_stop_pips,
                    atr_pips=atr_pips,
                )
                sl_pips = spec["sl_pips"]
                tp_pips = spec["tp_pips"]
                pip_val = spec["pip_val"]

                active_bal = float(_MT5_STATE.get("account", {}).get("balance", _AUTO_STATE["balance"])) if _MT5_STATE.get("connected") else float(_AUTO_STATE["balance"])
                risk_usd = active_bal * (_AUTO_SETTINGS.risk_per_trade_pct / 100.0)
                raw_calc_lots = round(risk_usd / (sl_pips * pip_val), 2)

                # SERT LOT TAVANI (Asla aşılamaz: Forex max 0.05 lot, Ons Altın/BTC max 0.02 lot)
                is_gold_or_crypto = is_gold or ("BTC" in sym)
                lot_ceiling = min(HARD_MAX_GOLD_LOT, _AUTO_SETTINGS.max_gold_lot) if is_gold_or_crypto else min(HARD_MAX_FOREX_LOT, _AUTO_SETTINGS.max_forex_lot)
                mt5_lots = max(0.01, min(raw_calc_lots, lot_ceiling))
                mt5_lots = round(mt5_lots, 2)

                entry_p = t["ask"] if direction == "BUY" else t["bid"]

                # IC Markets MT5 bağlıysa doğrudan MT5 emir kuyruğuna ekle
                if _MT5_STATE.get("connected") and _MT5_STATE.get("auto_trade"):
                    cmd_id = f"CMD-{int(time.time() * 1000) % 1000000}"
                    _MT5_STATE["pending_commands"].append({
                        "id": cmd_id,
                        "action": "OPEN_ORDER",
                        "symbol": sym,
                        "direction": direction,
                        "lots": mt5_lots,
                        "sl_pips": sl_pips,
                        "tp_pips": tp_pips,
                        "comment": f"Scalper MT5 {cand['score']:.0f}",
                    })
                else:
                    # MT5 bağlı değilse Paper Engine sanal pozisyon havuzuna ekle
                    sl_dist = sl_pips * spec["pip_size"]
                    tp_dist = tp_pips * spec["pip_size"]
                    pos_item = {
                        "id": f"FX-{int(time.time() * 1000) % 1000000}",
                        "symbol": sym,
                        "display": cand["display"],
                        "direction": direction,
                        "lots": mt5_lots,
                        "entry_price": entry_p,
                        "current_price": entry_p,
                        "sl_price": round(entry_p - sl_dist if direction == "BUY" else entry_p + sl_dist, spec["digits"]),
                        "tp_price": round(entry_p + tp_dist if direction == "BUY" else entry_p - tp_dist, spec["digits"]),
                        "initial_sl_price": round(entry_p - sl_dist if direction == "BUY" else entry_p + sl_dist, spec["digits"]),
                        "breakeven_activated": False,
                        "trailing_activated": False,
                        "opened_at_ts": now_ts,
                        "open_time": datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC"),
                        "pnl_usd": 0.0,
                        "pnl_pips": 0.0,
                        "pip_size": spec["pip_size"],
                        "digits": spec["digits"],
                        "score": cand["score"],
                        "strategy": "M1_M5_RADAR_SCALPER",
                    }
                    async with _AUTO_PAPER_LOCK:
                        _AUTO_STATE["open_positions"].append(pos_item)

                _LAST_SYMBOL_ENTRY_TIME[sym] = now_ts

                _log_auto_decision(
                    "ENTRY",
                    f"⚡ [İŞLEM AÇILDI]: {mt5_lots} Lot {direction} {sym} @ {entry_p} | TP: +{tp_pips}p | SL: -{sl_pips}p | Risk: ${risk_usd:.2f} (Skor: {cand['score']:.0f} | Lot Tavanı: {lot_ceiling})",
                    symbol=sym,
                    metadata={"lots": mt5_lots, "direction": direction, "score": cand["score"], "lot_ceiling": lot_ceiling},
                )

                # Döngü başına en fazla 1 işlem aç (ani yığılmayı önle)
                break

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Forex otonom döngü hatası: %s", exc)
            await asyncio.sleep(3.0)

    _AUTO_STATE["last_status"] = "Durduruldu"
    logger.info("Forex Otonom Scalper Döngüsü Durduruldu.")


@router.get("/auto-paper/status")
async def get_forex_auto_paper_status():
    """IC Markets MT5 Otonom Scalper sistem durumu, canlı MT5 pozisyonları ve hesap metrikleri."""
    is_mt5_conn = _MT5_STATE.get("connected", False)
    mt5_acc = _MT5_STATE.get("account", {})

    if is_mt5_conn:
        balance = float(mt5_acc.get("balance", 1000.0))
        active_positions_source = _MT5_STATE.get("open_positions", [])
        closed_deals_source = _MT5_STATE.get("closed_deals", [])
    else:
        balance = float(_AUTO_STATE.get("balance", 10000.0))
        active_positions_source = _AUTO_STATE.get("open_positions", [])
        closed_deals_source = _AUTO_STATE.get("closed_trades", [])

    # Pozisyonları ve Kapanan İşlemleri Güvenli Formatla Normalize Et
    normalized_positions = []
    for p in active_positions_source:
        pnl = float(p.get("pnl_usd", p.get("profit", 0.0)))
        normalized_positions.append({
            **p,
            "pnl_usd": round(pnl, 2),
            "pnl_pips": float(p.get("pnl_pips", 0.0)),
        })

    normalized_deals = []
    for d in closed_deals_source:
        pnl = float(d.get("profit", d.get("pnl_usd", 0.0)))
        t_id = d.get("ticket") or d.get("id") or 0
        normalized_deals.append({
            "id": d.get("id") or f"MT5-{t_id}",
            "ticket": t_id,
            "symbol": d.get("symbol", ""),
            "display": d.get("display", d.get("symbol", "")),
            "direction": d.get("direction", "BUY"),
            "lots": float(d.get("lots", 0.01)),
            "entry_price": d.get("price", d.get("entry_price", 0.0)),
            "exit_price": d.get("price", d.get("exit_price", 0.0)),
            "open_time": d.get("open_time", d.get("time", "")),
            "exit_time": d.get("exit_time", d.get("time", "")),
            "exit_reason": d.get("exit_reason", "MT5 Kapanış"),
            "exit_reason_title": d.get("exit_reason_title", "IC Markets MT5"),
            "pnl_usd": round(pnl, 2),
            "pnl_pips": float(d.get("pnl_pips", 0.0)),
            "outcome": "WIN" if pnl >= 0 else "LOSS",
        })

    open_pnl_usd = round(sum(p["pnl_usd"] for p in normalized_positions), 2)
    equity = float(mt5_acc.get("equity", round(balance + open_pnl_usd, 2))) if is_mt5_conn else round(balance + open_pnl_usd, 2)

    # Realized PnL ve Kazanma Oranı
    wins = sum(1 for d in normalized_deals if d["pnl_usd"] > 0)
    losses = sum(1 for d in normalized_deals if d["pnl_usd"] < 0)
    total_trades = len(normalized_deals)
    realized_usd = round(sum(d["pnl_usd"] for d in normalized_deals), 2) if is_mt5_conn else _AUTO_STATE["realized_pnl_usd"]
    win_rate = round((wins / total_trades * 100.0), 1) if total_trades > 0 else 0.0

    return {
        "status": _AUTO_STATE["last_status"],
        "enabled": _AUTO_STATE["enabled"],
        "balance": balance,
        "equity": equity,
        "open_pnl_usd": open_pnl_usd,
        "open_pnl_pips": 0.0,
        "realized_pnl_usd": realized_usd,
        "realized_pnl_pips": 0.0,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "settings": _AUTO_SETTINGS.model_dump(),
        "open_positions": normalized_positions,
        "closed_trades": normalized_deals,
        "decision_logs": _AUTO_STATE["decision_logs"][:60],
        "sessions": _get_market_sessions(),
        "last_scan_time": _AUTO_STATE["last_scan_time"],
        "mt5_account": mt5_acc,
        "mt5_connected": is_mt5_conn,
    }


@router.post("/auto-paper/toggle")
async def toggle_forex_auto_paper(req: ToggleAutoPaperRequest):
    """Otonom scalper'ı başlatır veya durdurur."""
    global _AUTO_PAPER_TASK
    _AUTO_STATE["enabled"] = req.enabled
    _AUTO_SETTINGS.enabled = req.enabled
    _MT5_STATE["auto_trade"] = req.enabled

    if req.enabled:
        if _AUTO_PAPER_TASK is None or _AUTO_PAPER_TASK.done():
            _AUTO_PAPER_TASK = asyncio.create_task(_forex_auto_paper_loop())
            _log_auto_decision("SYSTEM", "IC Markets MT5 Otonom Scalper kullanıcı tarafından ETKİNLEŞTİRİLDİ.")
    else:
        if _AUTO_PAPER_TASK and not _AUTO_PAPER_TASK.done():
            _AUTO_PAPER_TASK.cancel()
            _AUTO_PAPER_TASK = None
        _AUTO_STATE["last_status"] = "Durduruldu"
        _log_auto_decision("SYSTEM", "IC Markets MT5 Otonom Scalper kullanıcı tarafından DURDURULDU.")

    return {
        "enabled": _AUTO_STATE["enabled"],
        "status": _AUTO_STATE["last_status"],
        "message": "Otonom Forex Scalper durumu güncellendi.",
    }


@router.post("/auto-paper/settings")
async def update_forex_auto_paper_settings(new_settings: ForexAutoPaperSettings):
    """Otonom scalper risk ve filtre parametrelerini günceller."""
    global _AUTO_SETTINGS
    # Çalışma durumunu koru (motorun durdurulup başlatılması toggle endpoint'iyle yönetilir)
    new_settings.enabled = _AUTO_STATE["enabled"]
    _AUTO_SETTINGS = new_settings

    _log_auto_decision(
        "SYSTEM",
        f"Parametreler güncellendi: Risk: %{new_settings.risk_per_trade_pct}, SL: {new_settings.sl_pips}p, TP: {new_settings.tp_pips}p, BE: {new_settings.breakeven_pips}p, Trailing: {new_settings.trailing_stop_pips}p, Min Skor: {new_settings.min_score}",
    )
    return {"status": "ok", "settings": _AUTO_SETTINGS.model_dump()}


@router.post("/auto-paper/close-position")
async def close_forex_position_manually(req: ClosePositionRequest):
    """Belirli bir açık pozisyonu veya MT5 biletini kapatır."""
    ticket = None
    try:
        raw = req.id.replace("#", "").replace("FX-", "").replace("CMD-CLOSE-", "").strip()
        if raw.isdigit():
            ticket = int(raw)
    except Exception:
        pass

    if ticket:
        cmd_id = f"CMD-CLOSE-{ticket}"
        _MT5_STATE["pending_commands"].append({
            "id": cmd_id,
            "action": "CLOSE_ORDER",
            "ticket": ticket,
        })
        _log_auto_decision("EXIT", f"🛑 [IC Markets MT5] Bilet #{ticket} kapatma emri iletildi.")
        return {"status": "closed", "ticket": ticket}

    res = await _close_position_internal(req.id, "MANUAL")
    if not res:
        raise HTTPException(status_code=404, detail="Pozisyon bulunamadı veya zaten kapalı.")
    return {"status": "closed", "position": res}


@router.post("/auto-paper/reset")
async def reset_forex_auto_paper():
    """IC Markets MT5 Scalper günlüklerini sıfırlar."""
    async with _AUTO_PAPER_LOCK:
        _AUTO_STATE["decision_logs"] = []
        _AUTO_STATE["closed_trades"] = []
        _AUTO_STATE["realized_pnl_usd"] = 0.0
        _AUTO_STATE["realized_pnl_pips"] = 0.0
        _AUTO_STATE["wins"] = 0
        _AUTO_STATE["losses"] = 0
        _AUTO_STATE["total_trades"] = 0
        _AUTO_STATE["balance"] = 10000.0

    _log_auto_decision("SYSTEM", "IC Markets MT5 Scalper günlükleri ve karar akışı sıfırlandı.")
    bal = float(_MT5_STATE.get("account", {}).get("balance", 1000.0)) if _MT5_STATE.get("connected") else float(_AUTO_STATE["balance"])
    return {"status": "reset", "balance": bal}


@router.get("/auto-paper/trades")
async def get_forex_trades_report(
    symbol: Optional[str] = None,
    outcome: Optional[str] = None,
    reason: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 500,
):
    """Forex Otonom Scalper ayrıntılı işlem raporları, filtreleme ve performans analitiği."""
    # MT5 Deals önceliklidir; yoksa auto_state geçmişi kullanılır
    all_closed = list(_MT5_STATE.get("closed_deals", [])) or list(_AUTO_STATE.get("closed_trades", []))
    filtered = all_closed

    if symbol and symbol != "ALL":
        filtered = [t for t in filtered if t.get("symbol") == symbol or t.get("display") == symbol]

    if outcome and outcome != "ALL":
        outcome_upper = str(outcome).upper()
        filtered = [t for t in filtered if str(t.get("outcome", "")).upper() == outcome_upper]

    if reason and reason != "ALL":
        filtered = [t for t in filtered if reason.lower() in str(t.get("exit_reason", "")).lower() or reason.lower() in str(t.get("exit_reason_title", "")).lower()]

    if search:
        s_low = search.lower()
        filtered = [
            t for t in filtered
            if s_low in str(t.get("id", "")).lower()
            or s_low in str(t.get("ticket", "")).lower()
            or s_low in str(t.get("symbol", "")).lower()
            or s_low in str(t.get("display", "")).lower()
            or s_low in str(t.get("exit_reason", "")).lower()
        ]

    # Performans Analitiği (Tüm Kapanan İşlemler Üzerinden)
    total_trades = len(all_closed)
    wins = [t for t in all_closed if float(t.get("pnl_usd", t.get("profit", 0.0))) >= 0]
    losses = [t for t in all_closed if float(t.get("pnl_usd", t.get("profit", 0.0))) < 0]

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = round((win_count / total_trades * 100.0), 1) if total_trades > 0 else 0.0

    gross_profit = round(sum(float(t.get("pnl_usd", t.get("profit", 0.0))) for t in wins), 2)
    gross_loss = round(abs(sum(float(t.get("pnl_usd", t.get("profit", 0.0))) for t in losses)), 2)

    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 2)
    elif gross_profit > 0:
        profit_factor = 999.0
    else:
        profit_factor = 0.0

    total_pnl_usd = round(sum(float(t.get("pnl_usd", t.get("profit", 0.0))) for t in all_closed), 2)
    total_pnl_pips = round(sum(float(t.get("pnl_pips", 0.0)) for t in all_closed), 1)
    total_lots = round(sum(float(t.get("lots", 0.0)) for t in all_closed), 2)

    avg_trade_usd = round(total_pnl_usd / total_trades, 2) if total_trades > 0 else 0.0
    avg_win_usd = round(gross_profit / win_count, 2) if win_count > 0 else 0.0
    avg_loss_usd = round(gross_loss / loss_count, 2) if loss_count > 0 else 0.0

    max_win_usd = max([float(t.get("pnl_usd", t.get("profit", 0.0))) for t in wins], default=0.0)
    max_loss_usd = min([float(t.get("pnl_usd", t.get("profit", 0.0))) for t in losses], default=0.0)

    # Açık Pozisyonlar (MT5 veya Auto)
    open_positions = list(_MT5_STATE.get("open_positions", [])) or list(_AUTO_STATE.get("open_positions", []))
    open_pnl_usd = round(sum(float(p.get("pnl_usd", p.get("profit", 0.0))) for p in open_positions), 2)
    acc_bal = float(_MT5_STATE.get("account", {}).get("balance", _AUTO_STATE["balance"]))
    acc_eq = float(_MT5_STATE.get("account", {}).get("equity", round(acc_bal + open_pnl_usd, 2)))

    return {
        "kpi": {
            "total_trades": total_trades,
            "wins": win_count,
            "losses": loss_count,
            "win_rate": win_rate,
            "total_pnl_usd": total_pnl_usd,
            "total_pnl_pips": total_pnl_pips,
            "gross_profit_usd": gross_profit,
            "gross_loss_usd": gross_loss,
            "profit_factor": profit_factor,
            "avg_trade_usd": avg_trade_usd,
            "avg_win_usd": avg_win_usd,
            "avg_loss_usd": avg_loss_usd,
            "max_win_usd": max_win_usd,
            "max_loss_usd": max_loss_usd,
            "total_lots": total_lots,
            "balance": acc_bal,
            "equity": acc_eq,
            "open_positions_count": len(open_positions),
            "open_pnl_usd": open_pnl_usd,
        },
        "trades": filtered[:limit],
        "total_filtered": len(filtered),
        "open_positions": open_positions,
    }


@router.get("/auto-paper/export-csv")
async def export_forex_trades_csv(
    symbol: Optional[str] = None,
    outcome: Optional[str] = None,
):
    """Forex scalper işlem geçmişini Excel uyumlu UTF-8 CSV olarak dışa aktarır."""
    trades = list(_MT5_STATE.get("closed_deals", [])) or list(_AUTO_STATE.get("closed_trades", []))
    if symbol and symbol != "ALL":
        trades = [t for t in trades if t.get("symbol") == symbol or t.get("display") == symbol]
    if outcome and outcome != "ALL":
        trades = [t for t in trades if str(t.get("outcome", "")).upper() == str(outcome).upper()]

    output = io.StringIO()
    # UTF-8 BOM yaz (Excel'in Türkçe karakterleri düzgün açması için)
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')

    # Başlık Satırı
    writer.writerow([
        "Bilet No",
        "Parite",
        "Sembol",
        "İşlem Yönü",
        "Lot",
        "Radar Skoru",
        "Giriş Fiyatı",
        "Açılış Zamanı (UTC)",
        "Çıkış Fiyatı",
        "Kapanış Zamanı (UTC)",
        "İşlem Süresi",
        "Çıkış Nedeni",
        "Zarar Durdur (SL)",
        "Kâr Al (TP)",
        "Kâr/Zarar (Pip)",
        "Net Getiri (USD)",
        "Bakiye Sonrası (USD)",
        "Sonuç",
    ])

    for tr in trades:
        pnl = float(tr.get("pnl_usd", tr.get("profit", 0.0)))
        pips = float(tr.get("pnl_pips", 0.0))
        t_id = tr.get("id") or (f"#{tr['ticket']}" if tr.get("ticket") else "-")
        writer.writerow([
            t_id,
            tr.get("display", tr.get("symbol", "")),
            tr.get("symbol", ""),
            tr.get("direction", ""),
            tr.get("lots", 0.0),
            tr.get("score", "-"),
            tr.get("entry_price", "-"),
            tr.get("open_time", "-"),
            tr.get("exit_price", "-"),
            tr.get("exit_time", "-"),
            tr.get("duration_human", f"{tr.get('duration_sec', 0)} sn" if tr.get("duration_sec") else "-"),
            tr.get("exit_reason_title", tr.get("exit_reason", "IC Markets MT5")),
            tr.get("sl_price", "-"),
            tr.get("tp_price", "-"),
            f"{pips:+.1f}",
            f"{pnl:+.2f}",
            tr.get("balance_after", "-"),
            "KAZANÇ (WIN)" if pnl >= 0 else "KAYIP (LOSS)",
        ])

    csv_data = output.getvalue().encode("utf-8-sig")
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"forex_scalper_raporu_{now_str}.csv"

    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/csv; charset=utf-8",
        },
    )


# ============================================================================
# IC MARKETS META-TRADER 5 (MT5) BRIDGE HUB & REST API
# ============================================================================


class MT5SyncRequest(BaseModel):
    account: Dict[str, Any] = Field(default_factory=dict)
    positions: List[Dict[str, Any]] = Field(default_factory=list)
    deals: List[Dict[str, Any]] = Field(default_factory=list)
    ticks: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    version: str = "1.0.0"


class MT5ManualOrderRequest(BaseModel):
    symbol: str = "EURUSD"
    direction: str = "BUY"
    lots: float = Field(0.01, ge=0.01, le=10.0)
    sl_pips: Optional[float] = 15.0
    tp_pips: Optional[float] = 25.0
    comment: Optional[str] = "Scalper Manual"


class MT5CloseRequest(BaseModel):
    ticket: int


class MT5ToggleAutoRequest(BaseModel):
    auto_trade: bool


@router.post("/mt5/sync")
async def sync_mt5_bridge(req: MT5SyncRequest):
    """Windows MT5 köprüsünden gelen canlı veriyi alır ve bekleyen emirleri iletir."""
    now_ts = time.time()
    _MT5_STATE["connected"] = True
    _MT5_STATE["last_ping"] = now_ts

    if req.account:
        _MT5_STATE["account"].update(req.account)
    _MT5_STATE["open_positions"] = req.positions

    # MT5 canlı tick fiyatlarını entegre et
    if req.ticks:
        for sym_code, tick_dict in req.ticks.items():
            live_val = tick_dict.get("ask") or tick_dict.get("last") or tick_dict.get("bid")
            if live_val and live_val > 0:
                _LIVE_PRICES_CACHE[sym_code.upper()] = float(live_val)

    if req.deals:
        _MT5_STATE["closed_deals"] = req.deals
        is_first_sync = len(_LAST_CLOSED_DEAL_IDS) == 0
        for d in req.deals:
            deal_id = d.get("ticket") or d.get("id")
            if deal_id and deal_id not in _LAST_CLOSED_DEAL_IDS:
                _LAST_CLOSED_DEAL_IDS.add(deal_id)
                d_sym = str(d.get("symbol", "")).upper()
                if "XAU" in d_sym or "GOLD" in d_sym:
                    deal_time = float(d.get("time", 0)) if isinstance(d.get("time"), (int, float)) else 0.0
                    # İlk senkronizasyonda eski geçmiş deals için false cooldown başlatma; sadece son 180s içinde kapananlar için başlat
                    if not is_first_sync or (deal_time > 0 and (now_ts - deal_time < _AUTO_SETTINGS.gold_cooldown_sec)):
                        global _LAST_GOLD_EXIT_TIME
                        _LAST_GOLD_EXIT_TIME = now_ts

    # Bekleyen emirleri al ve boşalt
    commands = list(_MT5_STATE["pending_commands"])
    _MT5_STATE["pending_commands"].clear()

    return {
        "status": "ok",
        "server_time": now_ts,
        "auto_trade": _MT5_STATE["auto_trade"],
        "commands": commands,
        "settings": {
            "breakeven_pips": _AUTO_SETTINGS.breakeven_pips,
            "trailing_stop_pips": _AUTO_SETTINGS.trailing_stop_pips,
            "sl_pips": _AUTO_SETTINGS.sl_pips,
            "tp_pips": _AUTO_SETTINGS.tp_pips,
            "max_open_positions": _AUTO_SETTINGS.max_open_positions,
            "max_forex_lot": _AUTO_SETTINGS.max_forex_lot,
            "max_gold_lot": _AUTO_SETTINGS.max_gold_lot,
            "gold_cooldown_sec": _AUTO_SETTINGS.gold_cooldown_sec,
            "usd_correlation_guard": _AUTO_SETTINGS.usd_correlation_guard,
        },
    }


@router.get("/mt5/status")
async def get_mt5_bridge_status():
    """IC Markets MT5 köprüsü bağlantı durumunu ve canlı hesap verisini döner."""
    now_ts = time.time()
    # 10 saniye boyunca köprüden ping gelmezse çevrimdışı say
    is_alive = _MT5_STATE["connected"] and (now_ts - _MT5_STATE["last_ping"] < 10.0)
    _MT5_STATE["connected"] = is_alive

    enriched_positions = []
    for p in _MT5_STATE.get("open_positions", []):
        pos = dict(p)
        prot = pos.get("protection")
        if not prot or prot == "NORMAL":
            if pos.get("trailing_activated"):
                prot = "TRAILING"
            elif pos.get("breakeven_activated"):
                prot = "BREAKEVEN"
            else:
                dir_ = pos.get("direction", "BUY")
                entry_p = float(pos.get("entry_price", 0.0))
                sl_p = float(pos.get("sl_price", 0.0))
                if sl_p > 0 and entry_p > 0:
                    if dir_ == "BUY":
                        if sl_p > entry_p + 0.0006:
                            prot = "TRAILING"
                        elif sl_p >= entry_p - 0.0001:
                            prot = "BREAKEVEN"
                    else:
                        if sl_p < entry_p - 0.0006:
                            prot = "TRAILING"
                        elif sl_p <= entry_p + 0.0001:
                            prot = "BREAKEVEN"
        prot = prot or "NORMAL"
        pos["protection"] = prot
        pos["protection_label"] = (
            "İz Süren Stop (Trailing)" if prot == "TRAILING"
            else ("Başabaş (BE)" if prot == "BREAKEVEN" else "Sabit SL")
        )
        pos["breakeven_activated"] = prot in ("BREAKEVEN", "TRAILING")
        pos["trailing_activated"] = prot == "TRAILING"
        enriched_positions.append(pos)

    return {
        "connected": is_alive,
        "last_ping_seconds_ago": round(now_ts - _MT5_STATE["last_ping"], 1) if _MT5_STATE["last_ping"] > 0 else None,
        "auto_trade": _MT5_STATE["auto_trade"],
        "account": _MT5_STATE["account"],
        "open_positions": enriched_positions,
        "closed_deals": _MT5_STATE["closed_deals"][:50],
        "pending_commands_count": len(_MT5_STATE["pending_commands"]),
    }


@router.post("/mt5/order")
async def send_mt5_order(req: MT5ManualOrderRequest):
    """MT5 köprüsüne yeni bir piyasa emri iletir."""
    is_gold = ("XAU" in req.symbol.upper() or "GOLD" in req.symbol.upper() or "BTC" in req.symbol.upper())
    lot_cap = min(HARD_MAX_GOLD_LOT, _AUTO_SETTINGS.max_gold_lot) if is_gold else min(HARD_MAX_FOREX_LOT, _AUTO_SETTINGS.max_forex_lot)
    actual_lots = round(max(0.01, min(req.lots, lot_cap)), 2)

    cmd_id = f"CMD-{int(time.time() * 1000) % 1000000}"
    cmd = {
        "id": cmd_id,
        "action": "OPEN_ORDER",
        "symbol": req.symbol.upper(),
        "direction": req.direction.upper(),
        "lots": actual_lots,
        "sl_pips": req.sl_pips,
        "tp_pips": req.tp_pips,
        "comment": req.comment or "Scalper Agent",
    }
    _MT5_STATE["pending_commands"].append(cmd)
    _log_auto_decision("ENTRY", f"🚀 [MT5 Manuel Emir Kuyruğa Alındı]: {actual_lots} Lot {req.direction} {req.symbol} (Limit: {lot_cap})", symbol=req.symbol)
    return {"status": "queued", "command": cmd}


@router.post("/mt5/close")
async def close_mt5_position(req: MT5CloseRequest):
    """MT5 köprüsüne belirli bir açık bileti kapatma emri iletir."""
    cmd_id = f"CMD-CLOSE-{req.ticket}"
    cmd = {
        "id": cmd_id,
        "action": "CLOSE_ORDER",
        "ticket": req.ticket,
    }
    _MT5_STATE["pending_commands"].append(cmd)
    _log_auto_decision("EXIT", f"🛑 [MT5 Kapatma Kuyruğa Alındı]: Bilet #{req.ticket}")
    return {"status": "queued", "ticket": req.ticket}


@router.post("/mt5/close-all")
async def close_all_mt5_positions():
    """Tüm açık MT5 pozisyonlarını tek seferde kapatma emri kuyruğa alır."""
    cmd_id = f"CMD-CLOSE-ALL-{int(time.time()*1000)%10000}"
    cmd = {
        "id": cmd_id,
        "action": "CLOSE_ALL",
    }
    _MT5_STATE["pending_commands"].append(cmd)
    _log_auto_decision("EXIT", "🛑 [MT5 Toplu Kapatma Kuyruğa Alındı]: Tüm açık MT5 pozisyonları kapatılıyor")
    return {"status": "queued", "command_id": cmd_id}


@router.post("/mt5/toggle-auto")
async def toggle_mt5_auto_trading(req: MT5ToggleAutoRequest):
    """Sinyallerin doğrudan MT5'e otomatik iletilmesini açar veya kapatır."""
    _MT5_STATE["auto_trade"] = req.auto_trade
    state_str = "ETKİNLEŞTİRİLDİ" if req.auto_trade else "DURDURULDU"
    _log_auto_decision("SYSTEM", f"⚡ IC Markets MT5 Otomatik Emir İletimi: {state_str}")
    return {"status": "ok", "auto_trade": _MT5_STATE["auto_trade"]}
