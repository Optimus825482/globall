"""XAUUSD MACD_CROSS_H4 (H4 MACD Histogram Zero-Cross + EMA100) Trend Strategy.

Validated via VectorBT (2-year H4, fee=0.02%, slippage=0.01%):
  - All 6 SL/RR combinations passed OOS (PF 1.37..1.63, OOS PF 1.52..2.17).
  - Selected config (SL=2.0 ATR, RR=2.0): 61 trades, 50.8% WR, Full PF 1.58 (+43.82%), OOS PF 2.17 (+19.95%).

Rules:
  - Timeframe: H4 (4 hours)
  - Entry BUY: MACD(12,26,9) histogram crosses above 0 AND close > EMA(100)
  - Entry SELL: MACD(12,26,9) histogram crosses below 0 AND close < EMA(100)
  - Stop Loss: 2.0 * ATR(14), Take Profit: 2.0 * SL (R:R = 2.0)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Sequence

import numpy as np

logger = logging.getLogger("scalper.macd_cross_h4")

STRATEGY_ID = "MACD_CROSS_H4"
STRATEGY_LABEL = "MACD Sıfır Geçişi (H4)"
TARGET_SYMBOLS = ("XAUUSD",)
EMA_PERIOD = 100
ATR_PERIOD = 14
SL_ATR_MULT = 2.0
RR = 2.0
COOLDOWN_SEC = 8 * 3600  # H4 stratejisi: en az 8 saat bekleme

_LAST_TRIGGER: Dict[str, float] = {}


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def evaluate_macd_cross_h4(
    candles: Sequence[Dict[str, Any]],
    *,
    pip_size: float = 0.1,
) -> Dict[str, Any]:
    """Pure signal evaluator for H4 OHLCV candles."""
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

    if len(closes) < 40 or pip_size <= 0:
        return {"ok": False, "signal": "HOLD", "reason": f"yetersiz H4 mum ({len(closes)} < 40)"}

    h_arr = np.asarray(highs, dtype=float)
    l_arr = np.asarray(lows, dtype=float)
    c_arr = np.asarray(closes, dtype=float)

    ema100 = float(_ema(c_arr, min(EMA_PERIOD, len(c_arr)))[-1])
    macd = _ema(c_arr, 12) - _ema(c_arr, 26)
    sig = _ema(macd, 9)
    hist = macd - sig

    prev_c = c_arr[:-1]
    tr = np.maximum(h_arr[1:] - l_arr[1:], np.maximum(np.abs(h_arr[1:] - prev_c), np.abs(l_arr[1:] - prev_c)))
    atr = float(np.mean(tr[-ATR_PERIOD:]))
    if atr <= 0:
        return {"ok": False, "signal": "HOLD", "reason": "ATR hesaplanamadı"}

    sl_dist = SL_ATR_MULT * atr
    tp_dist = RR * sl_dist
    sl_pips = round(sl_dist / pip_size, 1)
    tp_pips = round(tp_dist / pip_size, 1)
    atr_pips = round(atr / pip_size, 1)

    last_close = float(c_arr[-1])
    h_now, h_prev = float(hist[-1]), float(hist[-2])

    signal = "HOLD"
    reason = "MACD sıfır geçişi yok"
    if h_now > 0.0 and h_prev <= 0.0 and last_close > ema100:
        signal = "BUY"
        reason = f"H4 MACD sıfır üstüne geçti ({h_now:+.3f}) & EMA100 üstü ({last_close:.2f} > {ema100:.2f})"
    elif h_now < 0.0 and h_prev >= 0.0 and last_close < ema100:
        signal = "SELL"
        reason = f"H4 MACD sıfır altına geçti ({h_now:+.3f}) & EMA100 altı ({last_close:.2f} < {ema100:.2f})"

    return {
        "ok": True,
        "signal": signal,
        "reason": reason,
        "price": round(last_close, 4),
        "ema100": round(ema100, 4),
        "macd_hist": round(h_now, 5),
        "atr_pips": atr_pips,
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_LABEL,
    }


async def run_macd_cross_h4_scan() -> List[Dict[str, Any]]:
    """Scan TARGET_SYMBOLS (XAUUSD) on H4 and queue DEMO order on verified MACD cross."""
    from app import forex_research
    from app.routers import forex as fx

    results: List[Dict[str, Any]] = []
    now = time.time()
    for sym in TARGET_SYMBOLS:
        if now - _LAST_TRIGGER.get(sym, 0.0) < COOLDOWN_SEC:
            continue
        try:
            bars, _src = await forex_research.run_blocking(forex_research.get_candles, sym, "4h")
            spec = fx.get_symbol_trading_specs(sym)
            pip_size = float(spec.get("pip_size") or 0.1)
            ev = evaluate_macd_cross_h4(bars or [], pip_size=pip_size)
            ev["symbol"] = sym
            results.append(ev)
            if ev.get("signal") in ("BUY", "SELL"):
                res = fx.open_scan_position(
                    sym,
                    ev["signal"],
                    ev["sl_pips"],
                    ev["tp_pips"],
                    ev["atr_pips"],
                    88.0,
                    ev["reason"],
                    1.0,
                )
                if res.get("ok"):
                    pending = (getattr(fx, "_MT5_STATE", None) or {}).get("pending_commands") or []
                    for cmd in reversed(pending):
                        if cmd.get("id") == res.get("cmd_id"):
                            cmd["strategy"] = STRATEGY_ID
                            cmd["strategy_label"] = STRATEGY_LABEL
                            cmd["comment"] = f"MACD_H4 {ev['signal']}"
                            break
                    _LAST_TRIGGER[sym] = now
                    logger.info("[MACD_CROSS_H4] %s %s emri yazıldı (%s)", sym, ev["signal"], res.get("cmd_id"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[MACD_CROSS_H4] tarama hatası (%s): %s", sym, exc)
    return results
