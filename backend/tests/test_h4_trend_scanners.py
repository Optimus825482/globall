"""Unit tests for EURUSD ICHIMOKU_H4 and XAUUSD CHANDELIER_H4 strategies."""
from __future__ import annotations

from app import h4_trend_scanners as h4


def test_ichimoku_h4_returns_valid_structure():
    candles = []
    px = 1.0800
    for i in range(90):
        px += 0.0005 if i < 70 else (-0.0006 if i < 82 else 0.0025)
        candles.append({"open": px - 0.0003, "high": px + 0.0008, "low": px - 0.0008, "close": px})
    ev = h4.evaluate_ichimoku_h4(candles, pip_size=0.0001)
    assert ev["ok"] is True
    assert ev["strategy"] == "ICHIMOKU_H4"
    assert ev["sl_pips"] > 0 and abs(ev["tp_pips"] - ev["sl_pips"] * 3.0) <= 0.3


def test_chandelier_h4_buy_breakout():
    candles = []
    px = 3000.0
    for _ in range(40):
        px += 3.0
        candles.append({"open": px - 2.0, "high": px + 3.0, "low": px - 3.0, "close": px})
    # Pullback then sharp upward break above Chandelier short line
    for _ in range(8):
        px -= 5.0
        candles.append({"open": px + 4.0, "high": px + 5.0, "low": px - 4.0, "close": px})
    candles.append({"open": px, "high": px + 60.0, "low": px - 2.0, "close": px + 55.0})

    ev = h4.evaluate_chandelier_h4(candles, pip_size=0.1)
    assert ev["ok"] is True
    assert ev["strategy"] == "CHANDELIER_H4"
    assert ev["signal"] == "BUY"
    assert abs(ev["tp_pips"] - ev["sl_pips"] * 3.0) <= 0.3
