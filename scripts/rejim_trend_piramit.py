#!/usr/bin/env python3
"""Trend bacagina, kâr 1.2 ATR gorunce ayni yuzdeyle ikinci birim.

Ikinci birimin stopu ilk giristir. Hedef ilk islemin hedefidir.
Ilk stop kalkmaz, karda girise cekilir. Risk her birimde %5.
Martingale yok. Her hafta 1000 USD.
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


def pnl_of(unit, exit_raw: float, spread: float, unit_value: float) -> float:
    if unit["side"] == 1:
        return (exit_raw - unit["net"]) * unit_value * unit["vol"]
    return (unit["net"] - (exit_raw + spread)) * unit_value * unit["vol"]


def week_pyramid(bars, signals, spread, unit_value, vmin, vmax, vstep, start, end) -> dict:
    cash = wk.START_CASH
    units = []
    pending = None
    cool = -1
    trades = 0
    winners = 0
    added = False
    born = None
    for i, bar in enumerate(bars):
        if bar.t > end:
            for unit in units:
                cash += pnl_of(unit, bar.open, spread, unit_value)
                trades += 1
                winners += int(pnl_of(unit, bar.open, spread, unit_value) > 0)
            units = []
            break
        if bar.t < start:
            continue
        if not units and pending is not None and i > cool:
            side, sl, tp, be = pending
            raw = bar.open
            if side == 1:
                net = raw + spread
                risk_px = net - (raw - sl)
                stop, target = raw - sl, raw + tp
                arm = raw + be if be else None
            else:
                net = raw
                stop = raw + sl + spread
                target = raw - tp
                risk_px = stop - net
                arm = raw - be if be else None
            if risk_px > spread * 2 and unit_value > 0 and cash > 0:
                volume = eng.floor_volume(cash * RISK / (risk_px * unit_value), vmin, vmax, vstep)
                if volume is not None:
                    units = [{
                        "side": side, "net": net, "raw": raw, "stop": stop,
                        "target": target, "vol": volume, "arm": arm, "be": False,
                    }]
                    added = False
                    born = i
        pending = None
        if units and born is not None and i > born:
            side = units[0]["side"]
            primary = units[0]
            if side == 1:
                stop_hit = any(bar.low <= unit["stop"] for unit in units)
            else:
                stop_hit = any(bar.high >= unit["stop"] - spread for unit in units)
            tp_hit = (side == 1 and bar.high >= primary["target"]) or (side == -1 and bar.low <= primary["target"])
            if stop_hit or tp_hit or i - born >= 30:
                if stop_hit:
                    for unit in units:
                        if side == 1:
                            raw_exit = bar.open if bar.open < unit["stop"] else unit["stop"]
                        else:
                            level = unit["stop"] - spread
                            raw_exit = bar.open if bar.open > level else level
                        gain = pnl_of(unit, raw_exit, spread, unit_value)
                        cash += gain
                        trades += 1
                        winners += int(gain > 0)
                elif tp_hit:
                    for unit in units:
                        raw_exit = primary["target"]
                        gain = pnl_of(unit, raw_exit, spread, unit_value)
                        cash += gain
                        trades += 1
                        winners += int(gain > 0)
                else:
                    for unit in units:
                        gain = pnl_of(unit, bar.close, spread, unit_value)
                        cash += gain
                        trades += 1
                        winners += int(gain > 0)
                units = []
                cool = i + 4
            elif primary["arm"] is not None and not added:
                armed = (side == 1 and bar.high >= primary["arm"]) or (side == -1 and bar.low <= primary["arm"])
                if armed:
                    primary["be"] = True
                    primary["stop"] = primary["raw"] if side == 1 else primary["raw"] + spread
                    if side == 1:
                        raw_add = primary["arm"]
                        net_add = raw_add + spread
                        stop_add = primary["raw"]
                        risk_px = net_add - stop_add
                        target_add = primary["target"]
                    else:
                        raw_add = primary["arm"]
                        net_add = raw_add
                        stop_add = primary["raw"] + spread
                        risk_px = stop_add - net_add
                        target_add = primary["target"]
                    if risk_px > spread * 2 and cash > 0 and target_add != raw_add:
                        volume = eng.floor_volume(cash * RISK / (risk_px * unit_value), vmin, vmax, vstep)
                        if volume is not None:
                            units.append({
                                "side": side, "net": net_add, "raw": raw_add, "stop": stop_add,
                                "target": target_add, "vol": volume, "arm": None, "be": True,
                            })
                    added = True
        if units or i < cool or i >= len(bars) - 1 or bar.t >= end:
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
    cal = wk.weeks_ending(anchor[-1].t, 14)
    report = {"weeks": [label for _s, _e, label in cal], "symbols": {}, "passed_all_8": []}
    test_labels = set(report["weeks"][-8:])
    for symbol in (
        "XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY",
        "USDCAD", "EURCAD", "GBPCAD", "EURNZD", "GBPNZD", "NZDUSD",
    ):
        try:
            resolved, bars = rej.fetch(symbol, offset)
            costs = eng.symbol_costs(resolved)
            book = rej.build_signals(symbol, bars, costs["spread_price"])
        except SystemExit as exc:
            print(symbol, exc, flush=True)
            continue
        signals = bacak.trend_only(book["rejim"], 1.0)
        detail = []
        for start, end, label in cal:
            if bars[0].t > start:
                continue
            detail.append({
                "week": label,
                "in_test": label in test_labels,
                **week_pyramid(
                    bars, signals, costs["spread_price"], costs["unit_per_lot_per_price"],
                    costs["volume_min"], costs["volume_max"], costs["volume_step"], start, end,
                ),
            })
        test_rows = [row for row in detail if row["in_test"]]
        hits = sum(1 for row in test_rows if row["hit"])
        fridays = [row["friday"] for row in test_rows]
        cell = {
            "hits": hits,
            "min_friday": round(min(fridays), 2) if fridays else None,
            "sum_pnl": round(sum(row["friday"] - wk.START_CASH for row in test_rows), 2) if test_rows else None,
            "detail": detail,
        }
        report["symbols"][symbol] = cell
        if hits == 8 and len(test_rows) == 8:
            report["passed_all_8"].append(symbol)
        print(
            f"{symbol:8} test {hits}/{len(test_rows)} min={cell['min_friday']} pnl={cell['sum_pnl']}",
            flush=True,
        )
        if symbol == "XAUUSD":
            for row in detail:
                mark = "T" if row["in_test"] else "E"
                print(f"  {mark} {row['week']} {row['friday']:.0f} islem={row['trades']} kazanc={row['winners']}", flush=True)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rejim_trend_piramit.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
