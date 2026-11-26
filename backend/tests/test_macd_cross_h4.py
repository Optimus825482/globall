"""Unit tests for XAUUSD MACD_CROSS_H4 strategy."""
from __future__ import annotations

from app import macd_cross_h4


def test_macd_cross_h4_buy_signal():
    # Uptrend above EMA100, brief pullback (hist <= 0), then fresh upward impulse (hist > 0)
    candles = []
    px = 2800.0
    for _ in range(80):
        px += 4.0
        candles.append({"open": px - 3.0, "high": px + 3.0, "low": px - 4.0, "close": px})
    # Pullback to turn MACD histogram slightly negative while staying above EMA100
    for _ in range(12):
        px -= 2.5
        candles.append({"open": px + 2.0, "high": px + 3.0, "low": px - 2.0, "close": px})
    # Push up until histogram crosses above 0
    crossed = False
    for _ in range(15):
        px += 12.0
        candles.append({"open": px - 10.0, "high": px + 4.0, "low": px - 11.0, "close": px})
        ev = macd_cross_h4.evaluate_macd_cross_h4(candles, pip_size=0.1)
        if ev["signal"] == "BUY":
            crossed = True
            assert abs(ev["tp_pips"] - ev["sl_pips"] * 2.0) <= 0.2
            break
    assert crossed is True
