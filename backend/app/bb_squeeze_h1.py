"""BB_SQUEEZE_H1 (Bollinger Band Squeeze Breakout + EMA200) Strategy for BTCUSD & AUDUSD.

Validated via VectorBT (1-year H1, fee=0.02%, slippage=0.01%):
  - BTCUSD (SL=1.5 ATR, RR=3.0): 115 trades, Full PF 1.29 (+23.21%), OOS PF 2.36 (+21.27%).
  - AUDUSD (SL=2.0 ATR, RR=3.0): 82 trades, Full PF 1.17 (+3.34%), OOS PF 2.60 (+4.85%).

Rules:
  - Timeframe: H1 (1 hour)
  - Squeeze: previous bar BB(20, 2.0) width <= 25th percentile of last 50 bars
  - Breakout BUY: close > upper BB AND close > EMA(200)
  - Breakout SELL: close < lower BB AND close < EMA(200)
  - Risk/Reward: 3.0R (SL = 1.5*ATR for BTCUSD, 2.0*ATR for AUDUSD)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Sequence

import numpy as np

logger = logging.getLogger("scalper.bb_squeeze_h1")

STRATEGY_ID = "BB_SQUEEZE_H1"
STRATEGY_LABEL = "Bollinger Squeeze H1"
SYMBOL_SL_MULT = {"BTCUSD": 1.5, "AUDUSD": 2.0}
RR = 3.0
BB_PERIOD = 20
SQUEEZE_WINDOW = 50
EMA_PERIOD = 200
ATR_PERIOD = 14
COOLDOWN_SEC = 4 * 3600

_LAST_TRIGGER: Dict[str, float] = {}


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def evaluate_bb_squeeze_h1(
    candles: Sequence[Dict[str, Any]],
    *,
    pip_size: float = 1.0,
    sl_atr_mult: float = 1.5,
) -> Dict[str, Any]:
    """Pure signal evaluator for H1 OHLCV candles."""
    highs, lows, closes = [], [], []
    for c in candles or []:
        try:
            h = float(c.get("high", c.get("h", 0.0)))
            l = float(c.get("low", c.get("l", 0.0)))
            cl = float(c.get("close", c.get("c", 0.0)))
        except (TypeError, ValueError):
            continue
        if h > 0 and l > 0 and cl > 0:
            highs.append(h)
            lows.append(l)
            closes.append(cl)

    min_bars = BB_PERIOD + SQUEEZE_WINDOW + 2
    if len(closes) < min_bars or pip_size <= 0:
        return {"ok": False, "signal": "HOLD", "reason": f"yetersiz H1 mum ({len(closes)} < {min_bars})"}

    h_arr = np.asarray(highs, dtype=float)
    l_arr = np.asarray(lows, dtype=float)
    c_arr = np.asarray(closes, dtype=float)

    ema200 = float(_ema(c_arr, min(EMA_PERIOD, len(c_arr)))[-1])

    # Rolling BB(20) width over last SQUEEZE_WINDOW bars (up to previous bar)
    widths = []
    for end_idx in range(len(c_arr) - SQUEEZE_WINDOW - 1, len(c_arr) - 1):
        win = c_arr[end_idx - BB_PERIOD + 1 : end_idx + 1]
        ma = float(np.mean(win))
        sd = float(np.std(win, ddof=1)) if len(win) > 1 else 0.0
        widths.append((4.0 * sd / ma) if ma > 0 else 0.01)

    prev_width = widths[-1]
    q25 = float(np.quantile(widths, 0.25))
    in_squeeze = prev_width <= q25

    cur_win = c_arr[-BB_PERIOD:]
    cur_ma = float(np.mean(cur_win))
    cur_sd = float(np.std(cur_win, ddof=1))
    upper_bb = cur_ma + 2.0 * cur_sd
    lower_bb = cur_ma - 2.0 * cur_sd
    last_close = float(c_arr[-1])

    prev_c = c_arr[:-1]
    tr = np.maximum(h_arr[1:] - l_arr[1:], np.maximum(np.abs(h_arr[1:] - prev_c), np.abs(l_arr[1:] - prev_c)))
    atr = float(np.mean(tr[-ATR_PERIOD:]))
    if atr <= 0:
        return {"ok": False, "signal": "HOLD", "reason": "ATR hesaplanamadı"}

    sl_dist = sl_atr_mult * atr
    tp_dist = RR * sl_dist
    sl_pips = round(sl_dist / pip_size, 1)
    tp_pips = round(tp_dist / pip_size, 1)
    atr_pips = round(atr / pip_size, 1)

    signal = "HOLD"
    reason = "sıkışma kırılımı yok"
    if in_squeeze and last_close > upper_bb and last_close > ema200:
        signal = "BUY"
        reason = f"H1 BB Squeeze yukarı kırılım ({last_close:.4f} > {upper_bb:.4f}) & EMA200 üstü"
    elif in_squeeze and last_close < lower_bb and last_close < ema200:
        signal = "SELL"
        reason = f"H1 BB Squeeze aşağı kırılım ({last_close:.4f} < {lower_bb:.4f}) & EMA200 altı"

    return {
        "ok": True,
        "signal": signal,
        "reason": reason,
        "in_squeeze": in_squeeze,
        "price": round(last_close, 5),
        "upper_bb": round(upper_bb, 5),
        "lower_bb": round(lower_bb, 5),
        "ema200": round(ema200, 5),
        "atr_pips": atr_pips,
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_LABEL,
    }


async def run_bb_squeeze_h1_scan() -> List[Dict[str, Any]]:
    """Scan BTCUSD & AUDUSD on H1 and queue DEMO order on verified squeeze breakout."""
    from app import forex_research
    from app.routers import forex as fx

    results: List[Dict[str, Any]] = []
    now = time.time()
    for sym, sl_mult in SYMBOL_SL_MULT.items():
        if now - _LAST_TRIGGER.get(sym, 0.0) < COOLDOWN_SEC:
            continue
        try:
            bars, _src = await forex_research.run_blocking(forex_research.get_candles, sym, "1h")
            spec = fx.get_symbol_trading_specs(sym)
            pip_size = float(spec.get("pip_size") or (1.0 if "BTC" in sym else 0.0001))
            ev = evaluate_bb_squeeze_h1(bars or [], pip_size=pip_size, sl_atr_mult=sl_mult)
            ev["symbol"] = sym
            results.append(ev)
            if ev.get("signal") in ("BUY", "SELL"):
                res = fx.open_scan_position(
                    sym,
                    ev["signal"],
                    ev["sl_pips"],
                    ev["tp_pips"],
                    ev["atr_pips"],
                    85.0,
                    ev["reason"],
                    1.0,
                )
                if res.get("ok"):
                    pending = (getattr(fx, "_MT5_STATE", None) or {}).get("pending_commands") or []
                    for cmd in reversed(pending):
                        if cmd.get("id") == res.get("cmd_id"):
                            cmd["strategy"] = STRATEGY_ID
                            cmd["strategy_label"] = STRATEGY_LABEL
                            cmd["comment"] = f"BBSQ_H1 {ev['signal']}"
                            break
                    _LAST_TRIGGER[sym] = now
                    logger.info("[BB_SQUEEZE_H1] %s %s emri yazıldı (%s)", sym, ev["signal"], res.get("cmd_id"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[BB_SQUEEZE_H1] tarama hatası (%s): %s", sym, exc)
    return results
