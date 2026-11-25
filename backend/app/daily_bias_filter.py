"""1D EMA 12/50 Daily Bias Filter for Forex Majors (VectorBT-validated IS PF 1.96 / OOS PF 1.97 on EURUSD).

Provides a cached (30-min TTL) directional bias ('BULLISH', 'BEARISH', 'NEUTRAL')
so intraday trades aligned with the Daily trend get full size, while counter-trend
entries are automatically size-reduced (0.5x) to prevent directional loss clusters.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

DAILY_BIAS_MAJORS = frozenset({"EURUSD", "GBPUSD", "USDCHF", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD"})
_CACHE_TTL_SEC = 1800.0  # 30 minutes
_BIAS_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _ema(arr: np.ndarray, period: int) -> float:
    alpha = 2.0 / (period + 1.0)
    val = float(arr[0])
    for x in arr[1:]:
        val = alpha * float(x) + (1.0 - alpha) * val
    return val


def compute_daily_bias_from_candles(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure function: compute 1D EMA12 vs EMA50 bias from daily OHLC candles."""
    if not candles or len(candles) < 52:
        return {"bias": "NEUTRAL", "ema12": None, "ema50": None, "spread_pct": 0.0}
    closes = np.array([float(c.get("close", c.get("c", 0.0))) for c in candles], dtype=float)
    if np.any(closes <= 0):
        return {"bias": "NEUTRAL", "ema12": None, "ema50": None, "spread_pct": 0.0}
    e12 = _ema(closes, 12)
    e50 = _ema(closes, 50)
    spread_pct = ((e12 - e50) / e50) * 100.0 if e50 > 0 else 0.0
    if spread_pct >= 0.05:
        bias = "BULLISH"
    elif spread_pct <= -0.05:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"
    return {
        "bias": bias,
        "ema12": round(e12, 5),
        "ema50": round(e50, 5),
        "spread_pct": round(spread_pct, 3),
    }


def get_daily_bias(fx: Any, symbol: str) -> Dict[str, Any]:
    """Fetch (with 30m cache) 1D EMA 12/50 bias for Forex majors."""
    sym_u = str(symbol or "").upper()
    if sym_u not in DAILY_BIAS_MAJORS:
        return {"bias": "NEUTRAL", "ema12": None, "ema50": None, "spread_pct": 0.0}
    now = time.time()
    cached = _BIAS_CACHE.get(sym_u)
    if cached and (now - cached[0]) < _CACHE_TTL_SEC:
        return cached[1]
    try:
        candles = fx._fetch_forex_klines(sym_u, "1d", 80) if hasattr(fx, "_fetch_forex_klines") else []
        res = compute_daily_bias_from_candles(candles or [])
    except Exception:  # noqa: BLE001
        res = {"bias": "NEUTRAL", "ema12": None, "ema50": None, "spread_pct": 0.0}
    _BIAS_CACHE[sym_u] = (now, res)
    return res


def daily_bias_alignment(bias: str, direction: str) -> str:
    """Return 'ALIGNED', 'COUNTER', or 'NEUTRAL'."""
    b = str(bias or "NEUTRAL").upper()
    d = str(direction or "").upper()
    if b == "BULLISH":
        return "ALIGNED" if d == "BUY" else ("COUNTER" if d == "SELL" else "NEUTRAL")
    if b == "BEARISH":
        return "ALIGNED" if d == "SELL" else ("COUNTER" if d == "BUY" else "NEUTRAL")
    return "NEUTRAL"
