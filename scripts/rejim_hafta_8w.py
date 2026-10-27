#!/usr/bin/env python3
"""Kilitli 1dk rejim ailesi, haftalik 1000 USD.

Kurallar m1_rejim_sweep_60d icinden oldugu gibi alinir.
Risk sabit. Stop durur. Basabas yalnizca karda stopu girise ceker.
Her sembol, her strateji, her risk ayri raporlanir. Secim yok.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import m1_rejim_sweep_60d as rej  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = (
    "XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY",
    "USDCAD", "EURCAD", "GBPCAD", "EURNZD", "GBPNZD", "NZDUSD",
)
RISKS = (0.02, 0.05)


def week_cash(bars, signals, spread, unit, vmin, vmax, vstep, start, end, risk: float) -> dict:
    cash = wk.START_CASH
    pos = None
    pending = None
    cool = -1
    trades = 0
    winners = 0
    for i, bar in enumerate(bars):
        if bar.t > end:
            if pos is not None:
                if pos["side"] == 1:
                    pnl = (bar.open - pos["net"]) * unit * pos["vol"]
                else:
                    pnl = (pos["net"] - (bar.open + spread)) * unit * pos["vol"]
                cash += pnl
                trades += 1
                winners += int(pnl > 0)
                pos = None
            break
        if bar.t < start:
            continue
        if pos is None and pending is not None:
            side, sl, tp, be = pending
            raw = bar.open
            if side == 1:
                net = raw + spread
                risk_px = net - (raw - sl)
                stop, target = raw - sl, raw + tp
                arm = raw + be if be else None
            else:
                net = raw
                stop, target = raw + sl + spread, raw - tp
                risk_px = stop - net
                arm = raw - be if be else None
            if risk_px > spread * 2 and unit > 0 and cash > 0:
                volume = eng.floor_volume(cash * risk / (risk_px * unit), vmin, vmax, vstep)
                if volume is not None:
                    pos = {
                        "side": side, "net": net, "raw": raw, "stop": stop,
                        "target": target, "arm": arm, "be": False, "vol": volume, "i": i,
                    }
        pending = None
        if pos is not None and i > pos["i"]:
            side = pos["side"]
            if side == 1:
                stop_hit = bar.low <= pos["stop"]
            else:
                stop_hit = bar.high >= pos["stop"] - spread
            tp_hit = (side == 1 and bar.high >= pos["target"]) or (side == -1 and bar.low <= pos["target"])
            if stop_hit:
                if side == 1:
                    raw_exit = bar.open if bar.open < pos["stop"] else pos["stop"]
                    pnl = (raw_exit - pos["net"]) * unit * pos["vol"]
                else:
                    level = pos["stop"] - spread
                    raw_exit = bar.open if bar.open > level else level
                    pnl = (pos["net"] - (raw_exit + spread)) * unit * pos["vol"]
                cash += pnl
                trades += 1
                winners += int(pnl > 0)
                pos = None
                cool = i + 4
            elif tp_hit:
                if side == 1:
                    raw_exit = bar.open if bar.open > pos["target"] else pos["target"]
                    pnl = (raw_exit - pos["net"]) * unit * pos["vol"]
                else:
                    raw_exit = bar.open if bar.open < pos["target"] else pos["target"]
                    pnl = (pos["net"] - (raw_exit + spread)) * unit * pos["vol"]
                cash += pnl
                trades += 1
                winners += int(pnl > 0)
                pos = None
                cool = i + 4
            elif i - pos["i"] >= 30:
                if side == 1:
                    pnl = (bar.close - pos["net"]) * unit * pos["vol"]
                else:
                    pnl = (pos["net"] - (bar.close + spread)) * unit * pos["vol"]
                cash += pnl
                trades += 1
                winners += int(pnl > 0)
                pos = None
                cool = i + 4
            elif pos["arm"] is not None and not pos["be"]:
                if (side == 1 and bar.high >= pos["arm"]) or (side == -1 and bar.low <= pos["arm"]):
                    pos["be"] = True
                    pos["stop"] = pos["raw"] if side == 1 else pos["raw"] + spread
        if i >= len(bars) - 1 or pos is not None or i < cool or bar.t >= end:
            continue
        sig = signals[i]
        if sig is not None:
            pending = sig
    return {
        "friday": round(cash, 2),
        "hit": cash >= wk.TARGET,
        "trades": trades,
        "winners": winners,
    }


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    cal = wk.weeks_ending(anchor[-1].t, wk.WEEKS)
    report = {"weeks": [label for _s, _e, label in cal], "risks": list(RISKS), "symbols": {}}
    passed = []
    for symbol in SYMBOLS:
        try:
            resolved, bars = rej.fetch(symbol, offset)
            costs = eng.symbol_costs(resolved)
            book = rej.build_signals(symbol, bars, costs["spread_price"])
        except SystemExit as exc:
            report["symbols"][symbol] = {"error": str(exc)}
            print(symbol, exc, flush=True)
            continue
        first = bars[0].t
        report["symbols"][symbol] = {"first_utc": first, "modes": {}}
        for name, signals in book.items():
            for risk in RISKS:
                detail = []
                for start, end, label in cal:
                    if bars[-1].t < start or first > end:
                        detail.append({"week": label, "friday": None, "hit": False, "trades": 0, "winners": 0, "note": "veri_yok"})
                        continue
                    detail.append({
                        "week": label,
                        **week_cash(
                            bars, signals, costs["spread_price"], costs["unit_per_lot_per_price"],
                            costs["volume_min"], costs["volume_max"], costs["volume_step"],
                            start, end, risk,
                        ),
                    })
                scored = [row for row in detail if row.get("friday") is not None]
                hits = sum(1 for row in scored if row["hit"])
                fridays = [row["friday"] for row in scored]
                key = f"{name}|{int(risk * 100)}"
                cell = {
                    "hits": hits,
                    "weeks": len(scored),
                    "min_friday": min(fridays) if fridays else None,
                    "sum_pnl": round(sum(value - wk.START_CASH for value in fridays), 2) if fridays else None,
                    "detail": detail,
                }
                report["symbols"][symbol]["modes"][key] = cell
                if hits == wk.WEEKS and len(scored) == wk.WEEKS:
                    passed.append(f"{symbol}|{key}")
                print(
                    f"{symbol:8} {key:16} {hits}/{len(scored)} min={cell['min_friday']} pnl={cell['sum_pnl']}",
                    flush=True,
                )
    report["passed_all_8"] = passed
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rejim_hafta_8w.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": passed}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
