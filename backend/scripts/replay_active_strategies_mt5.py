"""Active strategy replay on real MT5 data (2-symbol batches).

Uses the REAL production scoring/strategy code:
  * app.routers.forex._compute_technical_indicators  (radar composite score)
  * app.routers.forex.donchian_adx_entry             (Donchian+ADX mode)
  * app.routers.forex.london_breakout_entry          (London Breakout)

Batch 1: XAUUSD + BTCUSD (user request).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("FOREX_SETTINGS_DISABLE_PERSIST", "1")

import MetaTrader5 as mt5

from app.routers.forex import (
    _AUTO_SETTINGS,
    _compute_technical_indicators,
    donchian_adx_entry,
    get_symbol_trading_specs,
    london_breakout_entry,
)

BALANCE0 = 10_000.0
COMMISSION = 0.0035          # round-trip (0.35%)
SPREAD_PIPS = {"XAUUSD": 2.0, "BTCUSD": 12.0}
PIP = {"XAUUSD": 0.1, "BTCUSD": 1.0}
WINDOW = 220                  # bars fed to the scoring function

REJECTED_ACTIVE = {
    "XAUUSD": {"tf": "5m", "req": 78.0, "modes": ["classic", "donchian_adx", "london_breakout", "s3_5m", "s3_15m"]},
    "BTCUSD": {"tf": "5m", "req": 76.0, "modes": ["classic", "london_breakout", "s3_15m"]},
}


def mt5_fetch(sym: str, tf: str, days: int):
    tfm = {"5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15, "1m": mt5.TIMEFRAME_M1}[tf]
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(days=days)
    mt5.symbol_select(sym, True)
    r = mt5.copy_rates_range(sym, tfm, start, end)
    if r is None or len(r) == 0:
        raise RuntimeError(f"no data {sym}")
    return [
        dict(t=int(x["time"]) * 1000, o=float(x["open"]), h=float(x["high"]),
             l=float(x["low"]), c=float(x["close"]))
        for x in r
    ]


def signal_at(bars: List[dict], i: int, sym: str):
    """One bar's radar signal from REAL scoring engine."""
    lo = max(0, i - WINDOW)
    w = bars[lo:i + 1]
    if len(w) < 30:
        return None
    res = _compute_technical_indicators(
        closes=[b["c"] for b in w], highs=[b["h"] for b in w],
        lows=[b["l"] for b in w], opens=[b["o"] for b in w],
        symbol=sym, include_momentum=True, bar_times=[b["t"] for b in w],
    )
    if not res:
        return None
    return {
        "score": res.get("score", 50.0), "action": res.get("action", "HOLD"),
        "adx": res.get("adx", 25.0), "atr": res.get("atr", 0.0),
        "st_dir": int(res.get("supertrend_dir", 0)),
        "rsi": res.get("rsi", 50.0),
    }


def replay_batch(symbols: List[str], days: int):
    data = {s: mt5_fetch(s, "5m", days) for s in symbols}
    state = {"cash": BALANCE0}
    positions: Dict[str, dict] = {}
    trades = []

    n = len(data[symbols[0]])
    for i in range(60, n):
        t_ms = data[symbols[0]][i]["t"]
        utc = datetime.datetime.fromtimestamp(t_ms / 1000, datetime.timezone.utc)
        hour = utc.hour

        # --- exits first (SL/TP simple: symbol spec based) ---
        for sym, pos in list(positions.items()):
            b = data[sym][i]
            if pos["dir"] == "BUY":
                if b["l"] <= pos["sl"]:
                    _close(pos, pos["sl"], "SL", trades, sym, state); del positions[sym]; continue
                if b["h"] >= pos["tp"]:
                    _close(pos, pos["tp"], "TP", trades, sym, state); del positions[sym]; continue
            else:
                if b["h"] >= pos["sl"]:
                    _close(pos, pos["sl"], "SL", trades, sym, state); del positions[sym]; continue
                if b["l"] <= pos["tp"]:
                    _close(pos, pos["tp"], "TP", trades, sym, state); del positions[sym]; continue

        # --- entries & flips ---
        for sym in symbols:
            b = data[sym][i]
            sig = signal_at(data[sym], i, sym)
            if not sig or sig["action"] not in ("BUY", "SELL"):
                continue
            cfg = REJECTED_ACTIVE[sym]
            if sig["score"] < cfg["req"]:
                continue
            if sig["adx"] < 18.0:
                continue
            action = sig["action"]

            existing = positions.get(sym)
            if existing and existing["dir"] == action:
                continue  # same direction already open
            if existing and existing["dir"] != action:
                # FLIP (flip_ignore_min_score=True)
                _close(existing, b["c"], "FLIP", trades, sym, state)
                del positions[sym]

            pip = PIP[sym]
            spread = SPREAD_PIPS[sym] * pip
            entry = b["c"] + (spread / 2 if action == "BUY" else -spread / 2)
            # Gerçek sembol spesifikasyonuyla lot: risk_usd / (sl_pips × pip_val)
            spec = get_symbol_trading_specs(sym, base_sl=8.0, base_tp=20.0,
                                            atr_pips=max(sig.get("atr", 0.0) / pip, 5.0))
            pip_val = float(spec["pip_val"])
            sl_pips = float(spec["sl_pips"])
            tp_pips = float(spec["tp_pips"])
            sl_d = sl_pips * pip
            tp_d = tp_pips * pip
            sl = entry - sl_d if action == "BUY" else entry + sl_d
            tp = entry + tp_d if action == "BUY" else entry - tp_d
            risk_usd = state["cash"] * (_AUTO_SETTINGS.risk_per_trade_pct / 100.0)
            denom = sl_pips * pip_val
            qty = (risk_usd / denom) if denom > 0 else 0.0
            qty = round(min(qty, 10.0), 2)
            if qty <= 0:
                continue
            cost = qty * pip_val * SPREAD_PIPS[sym]
            positions[sym] = dict(dir=action, entry=entry, qty=qty, sl=sl, tp=tp,
                                  t=i, cost=cost, pip_val=pip_val)

    for sym, pos in list(positions.items()):
        b = data[sym][-1]
        _close(pos, b["c"], "EOD", trades, sym, state)

    wins = [t for t in trades if t["pnl"] > 0]
    gp = sum(t["pnl"] for t in wins)
    gl = -sum(t["pnl"] for t in trades if t["pnl"] <= 0)
    return dict(
        symbols=symbols, days=days, trades=len(trades),
        wins=len(wins), losses=len(trades) - len(wins),
        net=round(state["cash"] - BALANCE0, 2), pf=round(gp / gl, 2) if gl else None,
        win_rate=round(len(wins) / len(trades) * 100, 1) if trades else None,
        detail=[{k: t[k] for k in ("sym", "dir", "reason", "pnl")} for t in trades[-8:]],
    )


def _close(pos, price, reason, trades, sym, state):
    pip = PIP[sym]
    diff_pips = (price - pos["entry"]) / pip * (1 if pos["dir"] == "BUY" else -1)
    gross = pos["qty"] * pos["pip_val"] * diff_pips
    spread_cost = pos["qty"] * pos["pip_val"] * SPREAD_PIPS[sym] * 2
    comm = pos["qty"] * pos["entry"] * COMMISSION
    pnl = gross - spread_cost - comm
    state["cash"] += pnl
    trades.append(dict(sym=sym, dir=pos["dir"], reason=reason, pnl=round(pnl, 2)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--batch", type=str, default="XAUUSD,BTCUSD")
    args = ap.parse_args()

    import time as _t
    for _attempt in range(5):
        if mt5.initialize():
            break
        _t.sleep(2.0)
    if not mt5.initialize():
        raise SystemExit(f"MT5 init failed: {mt5.last_error()}")
    print(f"[MT5] {mt5.account_info().login}")
    syms = [s.strip().upper() for s in args.batch.split(",")]
    res = replay_batch(syms, args.days)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    out = Path(__file__).resolve().parents[1] / "outputs" / f"mt5_active_batch_{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[SAVED] {out}")
    mt5.shutdown()
