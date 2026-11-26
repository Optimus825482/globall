"""Unit tests for BB_SQUEEZE_H1 (BTCUSD & AUDUSD) strategy."""
from __future__ import annotations

from app import bb_squeeze_h1


def test_bb_squeeze_h1_buy_breakout():
    candles = []
    # 60 bars of wider volatility trending up, then 25 bars of tight squeeze, then breakout up
    px = 50000.0
    for i in range(60):
        step = 300.0 if i % 2 == 0 else -150.0
        o = px
        c = px + step
        candles.append({"open": o, "high": max(o, c) + 120.0, "low": min(o, c) - 120.0, "close": c})
        px = c
    # Tight squeeze (very low std) above EMA200
    for i in range(25):
        o = px
        c = px + (5.0 if i % 2 == 0 else -4.0)
        candles.append({"open": o, "high": max(o, c) + 8.0, "low": min(o, c) - 8.0, "close": c})
        px = c
    # Strong upward breakout out of squeeze
    candles.append({"open": px, "high": px + 500.0, "low": px - 5.0, "close": px + 450.0})

    ev = bb_squeeze_h1.evaluate_bb_squeeze_h1(candles, pip_size=1.0, sl_atr_mult=1.5)
    assert ev["ok"] is True
    assert ev["in_squeeze"] is True
    assert ev["signal"] == "BUY"
    assert ev["tp_pips"] == round(ev["sl_pips"] * 3.0, 1)
