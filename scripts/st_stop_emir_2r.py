#!/usr/bin/env python3
"""Supertrend yonunde, sinyal mumu kirilirsa gir.

Long: yon yukari, ADX en az 20, DI ayni. Alis, mum tepesinin ustu.
Stop, mum dibi. Hedef 2R. Emir 2 bar surer, dolmazsa iptal.
Ayni barda stop da gorulurse once stop. Risk %5. Spread var. Secim yok.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = (
    "XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY",
    "USDCAD", "EURCAD", "GBPCAD", "EURNZD", "GBPNZD", "NZDUSD",
)
RISK = 0.05


def simulate(bars, spread, unit_value, vmin, vmax, vstep, start: int, end: int) -> dict:
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    vol = wk.atr(bars, 14)
    cash = wk.START_CASH
    pos = None
    armed = None
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
        if pos is None and armed is not None and i > armed["i"]:
            if i > armed["i"] + 2:
                armed = None
            else:
                side = armed["side"]
                if side == 1:
                    triggered = bar.high >= armed["entry"]
                    stopped = bar.low <= armed["stop"]
                else:
                    triggered = bar.low <= armed["entry"]
                    stopped = bar.high >= armed["stop"]
                if triggered and stopped:
                    cash -= cash * RISK
                    trades += 1
                    armed = None
                elif triggered:
                    raw = armed["entry"]
                    if side == 1:
                        net = raw + spread
                        stop = armed["stop"]
                        risk_px = net - stop
                        target = net + 2.0 * risk_px
                    else:
                        net = raw
                        stop = armed["stop"]
                        risk_px = stop - net
                        target = net - 2.0 * risk_px
                    if risk_px > spread and cash > 0 and unit_value > 0:
                        volume = eng.floor_volume(cash * RISK / (risk_px * unit_value), vmin, vmax, vstep)
                        if volume is not None:
                            pos = {"side": side, "net": net, "stop": stop, "target": target, "vol": volume, "i": i}
                    armed = None
        if pos is not None and i > pos["i"]:
            side = pos["side"]
            if side == 1:
                stop_hit = bar.low <= pos["stop"]
                tp_hit = bar.high >= pos["target"]
            else:
                stop_hit = bar.high >= pos["stop"]
                tp_hit = bar.low <= pos["target"]
            if stop_hit or tp_hit:
                if side == 1:
                    raw_exit = pos["stop"] if stop_hit else pos["target"]
                    pnl = (raw_exit - pos["net"]) * unit_value * pos["vol"]
                else:
                    raw_exit = pos["stop"] if stop_hit else pos["target"]
                    pnl = (pos["net"] - (raw_exit + spread)) * unit_value * pos["vol"]
                cash += pnl
                trades += 1
                winners += int(pnl > 0)
                pos = None
        if (
            pos is None and armed is None and vol[i] is not None and adx[i] is not None and adx[i] >= 20
            and plus[i] is not None and minus[i] is not None and bar.t < end
        ):
            span = bar.high - bar.low
            if direction[i] == -1 and plus[i] > minus[i] and span > 0 and (bar.close - bar.low) / span >= 0.7:
                risk_px = bar.high - bar.low
                if 0.3 * vol[i] <= risk_px <= 2.0 * vol[i]:
                    armed = {"side": 1, "entry": bar.high, "stop": bar.low, "i": i}
            elif direction[i] == 1 and minus[i] > plus[i] and span > 0 and (bar.high - bar.close) / span >= 0.7:
                risk_px = bar.high - bar.low
                if 0.3 * vol[i] <= risk_px <= 2.0 * vol[i]:
                    armed = {"side": -1, "entry": bar.low, "stop": bar.high, "i": i}
    return {"friday": round(cash, 2), "hit": cash >= wk.TARGET, "trades": trades, "winners": winners}


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    cal = wk.weeks_ending(anchor[-1].t, 8)
    report = {"weeks": [row[2] for row in cal], "symbols": {}, "passed_all_8": []}
    for symbol in SYMBOLS:
        resolved, bars = eng.fetch_bars(symbol, "15m", offset, lookback_days=80)
        costs = eng.symbol_costs(resolved)
        detail = []
        for start, end, label in cal:
            detail.append({
                "week": label,
                **simulate(
                    bars, costs["spread_price"], costs["unit_per_lot_per_price"],
                    costs["volume_min"], costs["volume_max"], costs["volume_step"], start, end,
                ),
            })
        hits = sum(1 for row in detail if row["hit"])
        fridays = [row["friday"] for row in detail]
        trades = sum(row["trades"] for row in detail)
        wins = sum(row["winners"] for row in detail)
        report["symbols"][symbol] = {
            "resolved": resolved,
            "hits": hits,
            "min_friday": round(min(fridays), 2),
            "sum_pnl": round(sum(value - wk.START_CASH for value in fridays), 2),
            "trades": trades,
            "winners": wins,
        }
        if hits == 8:
            report["passed_all_8"].append(symbol)
        rate = wins / trades if trades else 0
        print(
            f"{symbol:8} {hits}/8 min={min(fridays):.0f} pnl={report['symbols'][symbol]['sum_pnl']:.0f} islem={trades} oran={rate:.2f}",
            flush=True,
        )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "st_stop_emir_2r.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
