"""Unit tests for XAUUSD DONCHIAN_H1(20) + EMA200 strategy."""
from __future__ import annotations

from app import donchian_h1


def test_donchian_h1_buy_and_sell_signals():
    # Build 210 uptrending H1 bars followed by a clear breakout above 20-bar high
    candles = []
    px = 3000.0
    for i in range(210):
        o = px
        c = px + 0.5
        candles.append({"open": o, "high": c + 1.0, "low": o - 1.0, "close": c})
        px = c
    # Breakout bar
    candles.append({"open": px, "high": px + 15.0, "low": px - 1.0, "close": px + 12.0})

    ev = donchian_h1.evaluate_donchian_h1(candles, pip_size=0.1)
    assert ev["ok"] is True
    assert ev["signal"] == "BUY"
    assert ev["sl_pips"] > 0 and ev["tp_pips"] == round(ev["sl_pips"] * 2.0, 1)

    # Downtrend breakout
    down = []
    px = 3500.0
    for i in range(210):
        o = px
        c = px - 0.5
        down.append({"open": o, "high": o + 1.0, "low": c - 1.0, "close": c})
        px = c
    down.append({"open": px, "high": px + 1.0, "low": px - 15.0, "close": px - 12.0})
    ev_s = donchian_h1.evaluate_donchian_h1(down, pip_size=0.1)
    assert ev_s["ok"] is True and ev_s["signal"] == "SELL"
