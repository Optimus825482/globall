#!/usr/bin/env python3
"""Trend bacagi, 30 dakikalik sure cikisi yok.

hedef: 2.5 ATR hedef durur, sure cikisi kalkar.
iz: sabit hedef yok. 1.2 ATR kârda stop girise cekilir, sonra yalnizca
kâr yonunde 1 ATR izler. Stop gevsetilmez, kalkmaz.
Risk %5. Her hafta 1000 USD.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import m1_rejim_sweep_60d as rej  # noqa: E402
import rejim_trend_bacak as bacak  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

RISK = 0.05
SYMBOLS = (
    "XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY",
    "USDCAD", "EURCAD", "GBPCAD", "EURNZD", "GBPNZD", "NZDUSD",
)


def week_hold(bars, signals, spread, unit_value, vmin, vmax, vstep, start, end, mode: str) -> dict:
    cash = wk.START_CASH
    pos = None
    pending = None
    cool = -1
    trades = 0
    winners = 0
    for i, bar in enumerate(bars):
        if bar.t > end and pos is not None:
            if pos["side"] == 1:
                pnl = (bar.open - pos["net"]) * unit_value * pos["vol"]
            else:
                pnl = (pos["net"] - (bar.open + spread)) * unit_value * pos["vol"]
            cash += pnl
            trades += 1
            winners += int(pnl > 0)
            pos = None
            break
        if bar.t > end:
            break
        if bar.t < start:
            continue
        if pos is None and pending is not None and i > cool:
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
            if risk_px > spread * 2 and unit_value > 0 and cash > 0:
                volume = eng.floor_volume(cash * RISK / (risk_px * unit_value), vmin, vmax, vstep)
                if volume is not None:
                    pos = {
                        "side": side, "net": net, "raw": raw, "stop": stop,
                        "target": target, "arm": arm, "be": False, "vol": volume,
                        "i": i, "extreme": raw, "trail": sl,
                    }
        pending = None
        if pos is not None and i > pos["i"]:
            side = pos["side"]
            if side == 1:
                stop_hit = bar.low <= pos["stop"]
                tp_hit = mode == "hedef" and bar.high >= pos["target"]
            else:
                stop_hit = bar.high >= pos["stop"] - spread
                tp_hit = mode == "hedef" and bar.low <= pos["target"]
            if stop_hit:
                if side == 1:
                    raw_exit = bar.open if bar.open < pos["stop"] else pos["stop"]
                    pnl = (raw_exit - pos["net"]) * unit_value * pos["vol"]
                else:
                    level = pos["stop"] - spread
                    raw_exit = bar.open if bar.open > level else level
                    pnl = (pos["net"] - (raw_exit + spread)) * unit_value * pos["vol"]
                cash += pnl
                trades += 1
                winners += int(pnl > 0)
                pos = None
                cool = i + 4
            elif tp_hit:
                raw_exit = pos["target"]
                if side == 1:
                    pnl = (raw_exit - pos["net"]) * unit_value * pos["vol"]
                else:
                    pnl = (pos["net"] - (raw_exit + spread)) * unit_value * pos["vol"]
                cash += pnl
                trades += 1
                winners += int(pnl > 0)
                pos = None
                cool = i + 4
            else:
                if side == 1:
                    pos["extreme"] = max(pos["extreme"], bar.high)
                else:
                    pos["extreme"] = min(pos["extreme"], bar.low)
                if pos["arm"] is not None and not pos["be"]:
                    armed = (side == 1 and bar.high >= pos["arm"]) or (side == -1 and bar.low <= pos["arm"])
                    if armed:
                        pos["be"] = True
                        pos["stop"] = pos["raw"] if side == 1 else pos["raw"] + spread
                if mode == "iz" and pos is not None and pos["be"]:
                    if side == 1:
                        trailed = pos["extreme"] - pos["trail"]
                        if trailed > pos["stop"]:
                            pos["stop"] = trailed
                    else:
                        trailed = pos["extreme"] + pos["trail"]
                        if trailed < pos["stop"]:
                            pos["stop"] = trailed
        if pos is not None or i < cool or i >= len(bars) - 1 or bar.t >= end:
            continue
        if signals[i] is not None:
            pending = signals[i]
    return {
        "friday": round(cash, 2),
        "hit": cash >= wk.TARGET,
        "trades": trades,
        "winners": winners,
    }


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=120)
    cal = wk.weeks_ending(anchor[-1].t, 8)
    report = {"weeks": [label for _s, _e, label in cal], "symbols": {}, "passed_all_8": []}
    loaded = {}
    for symbol in SYMBOLS:
        try:
            resolved, bars = rej.fetch(symbol, offset)
            costs = eng.symbol_costs(resolved)
            book = rej.build_signals(symbol, bars, costs["spread_price"])
            loaded[symbol] = (bars, costs, bacak.trend_only(book["rejim"], 1.0))
        except SystemExit as exc:
            print(symbol, exc, flush=True)
    for mode in ("hedef", "iz"):
        for symbol, (bars, costs, signals) in loaded.items():
            detail = []
            for start, end, label in cal:
                detail.append({
                    "week": label,
                    **week_hold(
                        bars, signals, costs["spread_price"], costs["unit_per_lot_per_price"],
                        costs["volume_min"], costs["volume_max"], costs["volume_step"],
                        start, end, mode,
                    ),
                })
            hits = sum(1 for row in detail if row["hit"])
            fridays = [row["friday"] for row in detail]
            cell = {
                "hits": hits,
                "min_friday": round(min(fridays), 2),
                "sum_pnl": round(sum(value - wk.START_CASH for value in fridays), 2),
                "detail": detail,
            }
            report["symbols"].setdefault(symbol, {})[mode] = cell
            if hits == 8:
                report["passed_all_8"].append(f"{symbol}|{mode}")
            print(
                f"{symbol:8} {mode:5} {hits}/8 min={cell['min_friday']:.0f} pnl={cell['sum_pnl']:.0f}",
                flush=True,
            )
            if symbol == "XAUUSD":
                print(" ", " ".join(f"{row['week'][5:]}:{row['friday']:.0f}" for row in detail), flush=True)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rejim_trend_tutus.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
