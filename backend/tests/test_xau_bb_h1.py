"""Unit tests for validated XAUUSD H1 BB(30, 2.5) + EMA200 breakout strategy."""
from app.xau_bb_h1 import evaluate_xau_bb_h1


def _make_candles(prices):
    out = []
    for i, p in enumerate(prices):
        out.append({
            "time": 1700000000 + i * 3600,
            "open": p - 0.5,
            "high": p + 2.0,
            "low": p - 2.0,
            "close": p,
        })
    return out


def test_xau_bb_h1_buy_breakout_and_bar_dedup():
    # Uptrend above EMA200, flat consolidation, then sharp upside breakout on closed bar (-2)
    prices = [3000.0 + i * 0.5 for i in range(210)]
    prices.append(3200.0)  # closed bar (-2): well above BB(30, 2.5) upper & EMA200
    prices.append(3205.0)  # forming bar (-1)
    candles = _make_candles(prices)

    dec = evaluate_xau_bb_h1(candles, pip_size=0.1, last_consumed_bar=0)
    assert dec is not None
    assert dec["action"] == "BUY"
    assert dec["tp_pips"] == round(dec["sl_pips"] * 2.0, 1)

    # Same bar must not fire twice
    assert evaluate_xau_bb_h1(candles, pip_size=0.1, last_consumed_bar=dec["bar_time"]) is None


def test_xau_bb_h1_sell_breakout():
    # Downtrend below EMA200, then sharp downside breakout on closed bar (-2)
    prices = [3500.0 - i * 0.5 for i in range(210)]
    prices.append(3250.0)  # closed bar (-2): well below BB(30, 2.5) lower & EMA200
    prices.append(3248.0)  # forming bar (-1)
    candles = _make_candles(prices)

    dec = evaluate_xau_bb_h1(candles, pip_size=0.1, last_consumed_bar=0)
    assert dec is not None
    assert dec["action"] == "SELL"


def test_xau_bb_h1_blocks_counter_trend_breakout():
    # Strong downtrend (EMA200 high), small upward spike still below EMA200 -> must NOT BUY
    prices = [4000.0 - i * 2.0 for i in range(210)]
    prices.append(3620.0)  # above BB upper of last 30 bars, but still below EMA200
    prices.append(3621.0)
    candles = _make_candles(prices)

    dec = evaluate_xau_bb_h1(candles, pip_size=0.1, last_consumed_bar=0)
    assert dec is None
