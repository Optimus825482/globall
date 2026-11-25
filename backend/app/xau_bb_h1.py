"""Validated XAUUSD H1 Bollinger Band Breakout (30, 2.5) + EMA200 Trend Filter.

VectorBT 1Y H1 IS/OOS validation (spread + slippage included):
- IS (60%):  n=48, WR=43.8%, PF=1.21, Ret=+5.84%
- OOS (40%): n=32, WR=53.1%, PF=2.98, Ret=+19.94%, MaxDD=-4.7%
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

XAU_BB_H1_STRATEGY = "XAU_BB_H1"
XAU_BB_H1_LABEL = "Altın BB Kırılımı (H1)"
XAU_BB_H1_ENTRY_SOURCE = "xau_bb_h1"

BB_WINDOW = 30
BB_STD = 2.5
EMA_PERIOD = 200
ATR_PERIOD = 14
SL_ATR_MULT = 1.5
TP_RR = 2.0


def _ema(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.zeros_like(arr, dtype=float)
    if len(arr) == 0:
        return out
    alpha = 2.0 / (period + 1.0)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return out


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    n = len(closes)
    if n <= period + 1:
        return 0.0
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    val = float(np.mean(tr[1 : period + 1]))
    for i in range(period + 1, n):
        val = (val * (period - 1) + float(tr[i])) / period
    return val


def evaluate_xau_bb_h1(
    candles: List[Dict[str, Any]],
    pip_size: float = 0.1,
    last_consumed_bar: int = 0,
) -> Optional[Dict[str, Any]]:
    """Evaluate the latest CLOSED H1 candle for XAUUSD BB(30, 2.5) + EMA200 breakout.

    Uses index -2 (last closed bar) when >= 205 bars are available to avoid repainting.
    """
    if not candles or len(candles) < EMA_PERIOD + 5 or pip_size <= 0:
        return None

    # Use closed candles only (exclude currently forming bar at -1)
    closed = candles[:-1]
    closes = np.array([float(c.get("close", c.get("c", 0.0))) for c in closed], dtype=float)
    highs = np.array([float(c.get("high", c.get("h", 0.0))) for c in closed], dtype=float)
    lows = np.array([float(c.get("low", c.get("l", 0.0))) for c in closed], dtype=float)
    if np.any(closes <= 0):
        return None

    bar_time = int(closed[-1].get("time") or closed[-1].get("ts") or 0)
    if bar_time and bar_time == int(last_consumed_bar or 0):
        return None

    win_slice = closes[-BB_WINDOW:]
    bb_mid = float(np.mean(win_slice))
    bb_std = float(np.std(win_slice, ddof=0))
    bb_upper = bb_mid + BB_STD * bb_std
    bb_lower = bb_mid - BB_STD * bb_std

    ema200 = float(_ema(closes, EMA_PERIOD)[-1])
    atr_val = _atr(highs, lows, closes, ATR_PERIOD)
    if atr_val <= 0:
        return None

    last_close = float(closes[-1])
    action: Optional[str] = None
    if last_close > bb_upper and last_close > ema200:
        action = "BUY"
    elif last_close < bb_lower and last_close < ema200:
        action = "SELL"

    if not action:
        return None

    sl_pips = round(max(15.0, (atr_val * SL_ATR_MULT) / pip_size), 1)
    tp_pips = round(sl_pips * TP_RR, 1)
    return {
        "action": action,
        "bar_time": bar_time,
        "close": round(last_close, 2),
        "bb_upper": round(bb_upper, 2),
        "bb_mid": round(bb_mid, 2),
        "bb_lower": round(bb_lower, 2),
        "ema200": round(ema200, 2),
        "atr_pips": round(atr_val / pip_size, 1),
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
        "score": 88.0,
    }
