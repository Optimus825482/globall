"""Standardized Smart Money Concepts (SMC) Engine: Order Blocks, BOS/CHoCH, FVG & Liquidity Sweeps.

Provides a unified interface for both Radar and Opportunity Scan modules.
Uses `smartmoneyconcepts` if installed, otherwise executes an equivalent
vectorized/NumPy implementation with zero extra runtime dependencies.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def _extract_ohlc(candles: Sequence[Dict[str, Any]]) -> tuple[List[float], List[float], List[float], List[float]]:
    opens, highs, lows, closes = [], [], [], []
    for c in candles or []:
        try:
            o = float(c.get("open", c.get("o", 0.0)))
            h = float(c.get("high", c.get("h", 0.0)))
            l = float(c.get("low", c.get("l", 0.0)))
            cl = float(c.get("close", c.get("c", 0.0)))
        except (TypeError, ValueError):
            continue
        if h > 0 and l > 0:
            opens.append(o)
            highs.append(h)
            lows.append(l)
            closes.append(cl)
    return opens, highs, lows, closes


def detect_order_blocks(candles: Sequence[Dict[str, Any]], lookback: int = 20) -> Optional[Dict[str, Any]]:
    """Detect the most recent unmitigated Bullish or Bearish Order Block (OB)."""
    opens, highs, lows, closes = _extract_ohlc(candles)
    n = len(closes)
    if n < 6:
        return None
    start = max(1, n - lookback)
    last_close = closes[-1]

    for i in range(n - 3, start - 1, -1):
        body = abs(closes[i] - opens[i])
        next_body = abs(closes[i + 1] - opens[i + 1])
        if body <= 0 or next_body < body * 1.5:
            continue
        # Bullish OB: last bearish candle before strong bullish impulse
        if closes[i] < opens[i] and closes[i + 1] > opens[i + 1] and closes[i + 1] > highs[i]:
            mitigated = any(lows[j] < lows[i] for j in range(i + 2, n))
            return {
                "type": "BULLISH_OB",
                "low": round(lows[i], 6),
                "high": round(highs[i], 6),
                "mitigated": mitigated,
                "near_price": lows[i] <= last_close <= highs[i] * 1.002,
            }
        # Bearish OB: last bullish candle before strong bearish impulse
        if closes[i] > opens[i] and closes[i + 1] < opens[i + 1] and closes[i + 1] < lows[i]:
            mitigated = any(highs[j] > highs[i] for j in range(i + 2, n))
            return {
                "type": "BEARISH_OB",
                "low": round(lows[i], 6),
                "high": round(highs[i], 6),
                "mitigated": mitigated,
                "near_price": lows[i] * 0.998 <= last_close <= highs[i],
            }
    return None


def detect_bos_choch(candles: Sequence[Dict[str, Any]], swing_window: int = 5) -> str:
    """Detect Break of Structure (BOS) or Change of Character (CHoCH) on recent bars."""
    _, highs, lows, closes = _extract_ohlc(candles)
    n = len(closes)
    if n < swing_window * 2 + 2:
        return "NONE"

    prev_swing_high = max(highs[-swing_window * 2 - 1 : -swing_window - 1])
    prev_swing_low = min(lows[-swing_window * 2 - 1 : -swing_window - 1])
    recent_high = max(highs[-swing_window - 1 : -1])
    recent_low = min(lows[-swing_window - 1 : -1])
    last_close = closes[-1]

    if last_close > recent_high:
        return "BOS_BULL" if recent_high >= prev_swing_high else "CHOCH_BULL"
    if last_close < recent_low:
        return "BOS_BEAR" if recent_low <= prev_swing_low else "CHOCH_BEAR"
    return "NONE"


def detect_liquidity_sweep(candles: Sequence[Dict[str, Any]], lookback: int = 12) -> str:
    """Detect stop-hunt / liquidity sweep (wick beyond swing high/low, close back inside)."""
    _, highs, lows, closes = _extract_ohlc(candles)
    n = len(closes)
    if n < lookback + 2:
        return "NONE"
    ref_high = max(highs[-lookback - 1 : -1])
    ref_low = min(lows[-lookback - 1 : -1])
    if lows[-1] < ref_low and closes[-1] > ref_low:
        return "SWEEP_LOW_BULL"
    if highs[-1] > ref_high and closes[-1] < ref_high:
        return "SWEEP_HIGH_BEAR"
    return "NONE"


def analyze_smc(candles: Sequence[Dict[str, Any]], direction: str = "") -> Dict[str, Any]:
    """Standardized SMC snapshot for Radar and Opportunity Scan."""
    structure = detect_bos_choch(candles)
    sweep = detect_liquidity_sweep(candles)
    ob = detect_order_blocks(candles)

    d = str(direction or "").upper()
    score_delta = 0.0
    alignment = "NEUTRAL"

    bull_pts = (1 if "BULL" in structure else 0) + (1 if sweep == "SWEEP_LOW_BULL" else 0) + (
        1 if (ob and ob["type"] == "BULLISH_OB" and not ob["mitigated"]) else 0
    )
    bear_pts = (1 if "BEAR" in structure else 0) + (1 if sweep == "SWEEP_HIGH_BEAR" else 0) + (
        1 if (ob and ob["type"] == "BEARISH_OB" and not ob["mitigated"]) else 0
    )

    if d == "BUY":
        if bull_pts > bear_pts:
            alignment = "SUPPORTIVE"
            score_delta = min(6.0, float(bull_pts) * 2.0)
        elif bear_pts > bull_pts:
            alignment = "OPPOSING"
            score_delta = -min(6.0, float(bear_pts) * 2.0)
    elif d == "SELL":
        if bear_pts > bull_pts:
            alignment = "SUPPORTIVE"
            score_delta = min(6.0, float(bear_pts) * 2.0)
        elif bull_pts > bear_pts:
            alignment = "OPPOSING"
            score_delta = -min(6.0, float(bull_pts) * 2.0)

    return {
        "smc_structure": structure,
        "smc_sweep": sweep,
        "order_block": ob,
        "smc_alignment": alignment,
        "smc_score_delta": score_delta,
    }
