"""XAUUSD DONCHIAN_H1(20) + EMA200 Trend Breakout Strategy.

Validated via VectorBT (1-year H1, fee=0.02%, slippage=0.01%):
  - XAUUSD: 133 trades, Win Rate 41.4%, Full PF 1.32 (+36.76%), OOS PF 1.28 (+7.42%).

Rules:
  - Timeframe: H1 (1 hour)
  - Channel: 20-bar Donchian High/Low (excluding current bar)
  - Trend filter: EMA(200) on H1 closes
  - Entry BUY: close > donchian_high_20 AND close > ema200
  - Entry SELL: close < donchian_low_20 AND close < ema200
  - Stop Loss: 2.0 * ATR(14)
  - Take Profit: 2.0 * SL (R:R = 2.0)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

logger = logging.getLogger("scalper.donchian_h1")

STRATEGY_ID = "DONCHIAN_H1"
STRATEGY_LABEL = "Donchian H1(20) Kırılımı"
TARGET_SYMBOLS = ("XAUUSD",)
LOOKBACK = 20
EMA_PERIOD = 200
ATR_PERIOD = 14
SL_ATR_MULT = 2.0
RR = 2.0
COOLDOWN_SEC = 4 * 3600  # Aynı sembolde en az 4 saat bekleme

_LAST_TRIGGER: Dict[str, float] = {}


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def evaluate_donchian_h1(
    candles: Sequence[Dict[str, Any]],
    *,
    pip_size: float = 0.1,
    lookback: int = LOOKBACK,
    ema_period: int = EMA_PERIOD,
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

    min_bars = max(lookback + 2, 30)
    if len(closes) < min_bars or pip_size <= 0:
        return {"ok": False, "signal": "HOLD", "reason": f"yetersiz H1 mum ({len(closes)} < {min_bars})"}

    h_arr = np.asarray(highs, dtype=float)
    l_arr = np.asarray(lows, dtype=float)
    c_arr = np.asarray(closes, dtype=float)

    ema_span = min(ema_period, len(c_arr))
    ema200 = float(_ema(c_arr, ema_span)[-1])

    donch_hi = float(np.max(h_arr[-(lookback + 1) : -1]))
    donch_lo = float(np.min(l_arr[-(lookback + 1) : -1]))
    last_close = float(c_arr[-1])

    # ATR(14)
    prev_c = c_arr[:-1]
    tr = np.maximum(h_arr[1:] - l_arr[1:], np.maximum(np.abs(h_arr[1:] - prev_c), np.abs(l_arr[1:] - prev_c)))
    atr = float(np.mean(tr[-ATR_PERIOD:])) if len(tr) >= ATR_PERIOD else float(np.mean(tr))
    if atr <= 0:
        return {"ok": False, "signal": "HOLD", "reason": "ATR hesaplanamadı"}

    sl_dist = SL_ATR_MULT * atr
    tp_dist = RR * sl_dist
    sl_pips = round(sl_dist / pip_size, 1)
    tp_pips = round(tp_dist / pip_size, 1)
    atr_pips = round(atr / pip_size, 1)

    signal = "HOLD"
    reason = "kırılım yok"
    if last_close > donch_hi and last_close > ema200:
        signal = "BUY"
        reason = f"H1 Donchian({lookback}) yukarı kırılım ({last_close:.2f} > {donch_hi:.2f}) & EMA200 üstü"
    elif last_close < donch_lo and last_close < ema200:
        signal = "SELL"
        reason = f"H1 Donchian({lookback}) aşağı kırılım ({last_close:.2f} < {donch_lo:.2f}) & EMA200 altı"

    return {
        "ok": True,
        "signal": signal,
        "reason": reason,
        "price": round(last_close, 4),
        "donch_hi": round(donch_hi, 4),
        "donch_lo": round(donch_lo, 4),
        "ema200": round(ema200, 4),
        "atr_pips": atr_pips,
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_LABEL,
    }


async def run_donchian_h1_scan() -> List[Dict[str, Any]]:
    """Scan TARGET_SYMBOLS (XAUUSD) on H1 and queue DEMO order on verified breakout."""
    from app import forex_research
    from app.routers import forex as fx

    results: List[Dict[str, Any]] = []
    now = time.time()
    for sym in TARGET_SYMBOLS:
        if now - _LAST_TRIGGER.get(sym, 0.0) < COOLDOWN_SEC:
            continue
        try:
            bars, _src = await forex_research.run_blocking(forex_research.get_candles, sym, "1h")
            spec = fx.get_symbol_trading_specs(sym)
            pip_size = float(spec.get("pip_size") or 0.1)
            ev = evaluate_donchian_h1(bars or [], pip_size=pip_size)
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
                    # Tag command with DONCHIAN_H1 for isolated performance tracking
                    pending = (getattr(fx, "_MT5_STATE", None) or {}).get("pending_commands") or []
                    for cmd in reversed(pending):
                        if cmd.get("id") == res.get("cmd_id"):
                            cmd["strategy"] = STRATEGY_ID
                            cmd["strategy_label"] = STRATEGY_LABEL
                            cmd["comment"] = f"DONCH_H1 {ev['signal']}"
                            break
                    _LAST_TRIGGER[sym] = now
                    logger.info("[DONCHIAN_H1] %s %s emri yazıldı (%s)", sym, ev["signal"], res.get("cmd_id"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DONCHIAN_H1] tarama hatası (%s): %s", sym, exc)
    return results
