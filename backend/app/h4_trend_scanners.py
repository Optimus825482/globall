"""H4 Trend Scanners validated via 2-year VectorBT + OOS:
  1. EURUSD ICHIMOKU_H4 (SL=2.0 ATR, RR=3.0): 37 trades, Full PF 1.59 (+8.58%, DD -5.83%), OOS PF 1.35.
  2. XAUUSD CHANDELIER_H4 (SL=2.0 ATR, RR=3.0): 62 trades, Full PF 1.56 (+47.15%), OOS PF 2.69 (+27.28%).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Sequence

import numpy as np

logger = logging.getLogger("scalper.h4_trend_scanners")

ICHIMOKU_ID = "ICHIMOKU_H4"
ICHIMOKU_LABEL = "Ichimoku Bulut (H4)"
CHANDELIER_ID = "CHANDELIER_H4"
CHANDELIER_LABEL = "Chandelier Kırılımı (H4)"

COOLDOWN_SEC = 8 * 3600
_LAST_TRIGGER: Dict[str, float] = {}


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def _extract_hlc(candles: Sequence[Dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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
    return np.asarray(highs, dtype=float), np.asarray(lows, dtype=float), np.asarray(closes, dtype=float)


def _atr_series(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
    tr = np.empty_like(c)
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return _ema(tr, period)


def evaluate_ichimoku_h4(candles: Sequence[Dict[str, Any]], *, pip_size: float = 0.0001) -> Dict[str, Any]:
    """Tenkan(9)/Kijun(26) cross above/below Kumo Cloud (shifted 26)."""
    h, l, c = _extract_hlc(candles)
    if len(c) < 80 or pip_size <= 0:
        return {"ok": False, "signal": "HOLD", "reason": f"yetersiz H4 mum ({len(c)} < 80)"}

    n = len(c)
    tenkan_now = (np.max(h[-9:]) + np.min(l[-9:])) / 2.0
    tenkan_prev = (np.max(h[-10:-1]) + np.min(l[-10:-1])) / 2.0
    kijun_now = (np.max(h[-26:]) + np.min(l[-26:])) / 2.0
    kijun_prev = (np.max(h[-27:-1]) + np.min(l[-27:-1])) / 2.0

    # Cloud at current bar uses values computed 26 bars ago
    idx = n - 26
    t26 = (np.max(h[idx - 9 : idx]) + np.min(l[idx - 9 : idx])) / 2.0
    k26 = (np.max(h[idx - 26 : idx]) + np.min(l[idx - 26 : idx])) / 2.0
    span_a = (t26 + k26) / 2.0
    span_b = (np.max(h[idx - 52 : idx]) + np.min(l[idx - 52 : idx])) / 2.0
    cloud_top = max(span_a, span_b)
    cloud_bot = min(span_a, span_b)

    atr = float(_atr_series(h, l, c, 14)[-1])
    if atr <= 0:
        return {"ok": False, "signal": "HOLD", "reason": "ATR hesaplanamadı"}

    sl_dist = 2.0 * atr
    tp_dist = 3.0 * sl_dist
    last_c = float(c[-1])

    signal = "HOLD"
    reason = "Ichimoku kesişimi yok"
    if tenkan_now > kijun_now and tenkan_prev <= kijun_prev and last_c > cloud_top:
        signal = "BUY"
        reason = f"H4 Ichimoku Tenkan>Kijun & bulut üstü ({last_c:.5f} > {cloud_top:.5f})"
    elif tenkan_now < kijun_now and tenkan_prev >= kijun_prev and last_c < cloud_bot:
        signal = "SELL"
        reason = f"H4 Ichimoku Tenkan<Kijun & bulut altı ({last_c:.5f} < {cloud_bot:.5f})"

    return {
        "ok": True,
        "signal": signal,
        "reason": reason,
        "price": round(last_c, 5),
        "atr_pips": round(atr / pip_size, 1),
        "sl_pips": round(sl_dist / pip_size, 1),
        "tp_pips": round(tp_dist / pip_size, 1),
        "strategy": ICHIMOKU_ID,
        "strategy_label": ICHIMOKU_LABEL,
    }


def evaluate_chandelier_h4(candles: Sequence[Dict[str, Any]], *, pip_size: float = 0.1) -> Dict[str, Any]:
    """22-bar Chandelier Exit (3.0 ATR) flip aligned with EMA(100)."""
    h, l, c = _extract_hlc(candles)
    if len(c) < 35 or pip_size <= 0:
        return {"ok": False, "signal": "HOLD", "reason": f"yetersiz H4 mum ({len(c)} < 35)"}

    ema100 = float(_ema(c, min(100, len(c)))[-1])
    atr_arr = _atr_series(h, l, c, 14)
    atr_now = float(atr_arr[-1])
    if atr_now <= 0:
        return {"ok": False, "signal": "HOLD", "reason": "ATR hesaplanamadı"}

    ch_long_prev = float(np.max(h[-23:-1])) - 3.0 * float(atr_arr[-2])
    ch_long_prev2 = float(np.max(h[-24:-2])) - 3.0 * float(atr_arr[-3])
    ch_short_prev = float(np.min(l[-23:-1])) + 3.0 * float(atr_arr[-2])
    ch_short_prev2 = float(np.min(l[-24:-2])) + 3.0 * float(atr_arr[-3])

    last_c, prev_c = float(c[-1]), float(c[-2])
    sl_dist = 2.0 * atr_now
    tp_dist = 3.0 * sl_dist

    signal = "HOLD"
    reason = "Chandelier kırılımı yok"
    if last_c > ch_short_prev and prev_c <= ch_short_prev2 and last_c > ema100:
        signal = "BUY"
        reason = f"H4 Chandelier yukarı kırılım ({last_c:.2f} > {ch_short_prev:.2f}) & EMA100 üstü"
    elif last_c < ch_long_prev and prev_c >= ch_long_prev2 and last_c < ema100:
        signal = "SELL"
        reason = f"H4 Chandelier aşağı kırılım ({last_c:.2f} < {ch_long_prev:.2f}) & EMA100 altı"

    return {
        "ok": True,
        "signal": signal,
        "reason": reason,
        "price": round(last_c, 4),
        "atr_pips": round(atr_now / pip_size, 1),
        "sl_pips": round(sl_dist / pip_size, 1),
        "tp_pips": round(tp_dist / pip_size, 1),
        "strategy": CHANDELIER_ID,
        "strategy_label": CHANDELIER_LABEL,
    }


async def run_h4_trend_scans() -> List[Dict[str, Any]]:
    """Run EURUSD ICHIMOKU_H4 and XAUUSD CHANDELIER_H4 on H4 candles."""
    from app import forex_research
    from app.routers import forex as fx

    tasks = [
        ("EURUSD", ICHIMOKU_ID, ICHIMOKU_LABEL, evaluate_ichimoku_h4, 0.0001),
        ("XAUUSD", CHANDELIER_ID, CHANDELIER_LABEL, evaluate_chandelier_h4, 0.1),
    ]
    results: List[Dict[str, Any]] = []
    now = time.time()

    for sym, strat_id, strat_lbl, fn, default_pip in tasks:
        key = f"{sym}:{strat_id}"
        if now - _LAST_TRIGGER.get(key, 0.0) < COOLDOWN_SEC:
            continue
        try:
            bars, _src = await forex_research.run_blocking(forex_research.get_candles, sym, "4h")
            spec = fx.get_symbol_trading_specs(sym)
            pip_size = float(spec.get("pip_size") or default_pip)
            ev = fn(bars or [], pip_size=pip_size)
            ev["symbol"] = sym
            results.append(ev)
            if ev.get("signal") in ("BUY", "SELL"):
                res = fx.open_scan_position(
                    sym, ev["signal"], ev["sl_pips"], ev["tp_pips"], ev["atr_pips"], 88.0, ev["reason"], 1.0
                )
                if res.get("ok"):
                    pending = (getattr(fx, "_MT5_STATE", None) or {}).get("pending_commands") or []
                    for cmd in reversed(pending):
                        if cmd.get("id") == res.get("cmd_id"):
                            cmd["strategy"] = strat_id
                            cmd["strategy_label"] = strat_lbl
                            cmd["comment"] = f"{strat_id} {ev['signal']}"
                            break
                    _LAST_TRIGGER[key] = now
                    logger.info("[%s] %s %s emri yazıldı (%s)", strat_id, sym, ev["signal"], res.get("cmd_id"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] tarama hatası (%s): %s", strat_id, sym, exc)
    return results
