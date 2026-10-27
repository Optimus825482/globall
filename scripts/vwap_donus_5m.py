#!/usr/bin/env python3
"""Gunluk VWAP'tan 1.5 ATR sapinca geri donus. Trend zayifken.

VWAP, tipik fiyatın o gun 00:00 UTC'den birikmis ortalamasi. Hacim yok.
Giris 07-16 UTC. ADX 25'in altinda. Stop 1 ATR. Hedef 1 ATR, VWAP yonunde.
Risk %5. Spread var. Secim yok.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = (
    "XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY",
    "USDCAD", "EURCAD", "GBPCAD", "EURNZD", "GBPNZD", "NZDUSD",
)
RISK = 0.05


def day_key(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def hour_of(ts: int) -> int:
    return datetime.fromtimestamp(ts, timezone.utc).hour


def simulate(bars, spread, unit_value, vmin, vmax, vstep, start: int, end: int) -> dict:
    vol = wk.atr(bars, 14)
    _p, _m, adx = eng.adx_dmi(bars, 14)
    cash = wk.START_CASH
    pos = None
    pending = None
    trades = 0
    winners = 0
    vwap_sum = 0.0
    vwap_n = 0
    current_day = None
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
        day = day_key(bar.t)
        if day != current_day:
            current_day = day
            vwap_sum = 0.0
            vwap_n = 0
        typical = (bar.high + bar.low + bar.close) / 3.0
        vwap_sum += typical
        vwap_n += 1
        vwap = vwap_sum / vwap_n
        if bar.t < start:
            continue
        if pos is None and pending is not None:
            side, stop_line = pending
            raw = bar.open
            if side == 1:
                net = raw + spread
                stop = stop_line
                risk_px = net - stop
                target = net + risk_px
            else:
                net = raw
                stop = stop_line + spread
                risk_px = stop - net
                target = net - risk_px
            if risk_px > spread and unit_value > 0 and cash > 0:
                volume = eng.floor_volume(cash * RISK / (risk_px * unit_value), vmin, vmax, vstep)
                if volume is not None:
                    pos = {"side": side, "net": net, "stop": stop, "target": target, "vol": volume, "i": i}
        pending = None
        if pos is not None and i > pos["i"]:
            side = pos["side"]
            if side == 1:
                stop_hit = bar.low <= pos["stop"]
                tp_hit = bar.high >= pos["target"]
            else:
                stop_hit = bar.high >= pos["stop"] - spread
                tp_hit = bar.low <= pos["target"]
            hour = hour_of(bar.t)
            session_done = hour >= 16
            if stop_hit or tp_hit or session_done:
                if side == 1:
                    if stop_hit:
                        raw_exit = bar.open if bar.open < pos["stop"] else pos["stop"]
                    elif tp_hit:
                        raw_exit = pos["target"]
                    else:
                        raw_exit = bar.close
                    pnl = (raw_exit - pos["net"]) * unit_value * pos["vol"]
                else:
                    if stop_hit:
                        level = pos["stop"] - spread
                        raw_exit = bar.open if bar.open > level else level
                    elif tp_hit:
                        raw_exit = pos["target"]
                    else:
                        raw_exit = bar.close
                    pnl = (pos["net"] - (raw_exit + spread)) * unit_value * pos["vol"]
                cash += pnl
                trades += 1
                winners += int(pnl > 0)
                pos = None
        if pos is None and vol[i] is not None and vol[i] > 0 and adx[i] is not None and adx[i] < 25:
            hour = hour_of(bar.t)
            if 7 <= hour < 16 and vwap_n >= 6:
                stretch = bar.close - vwap
                if stretch <= -1.5 * vol[i] and bar.close > bar.open:
                    pending = (1, bar.close - vol[i])
                elif stretch >= 1.5 * vol[i] and bar.close < bar.open:
                    pending = (-1, bar.close + vol[i])
    return {
        "friday": round(cash, 2),
        "hit": cash >= wk.TARGET,
        "trades": trades,
        "winners": winners,
    }


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "5m", offset, lookback_days=80)
    cal = wk.weeks_ending(anchor[-1].t, 8)
    report = {"weeks": [row[2] for row in cal], "symbols": {}, "passed_all_8": []}
    for symbol in SYMBOLS:
        resolved, bars = eng.fetch_bars(symbol, "5m", offset, lookback_days=80)
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
            "detail": detail,
        }
        if hits == 8:
            report["passed_all_8"].append(symbol)
        rate = wins / trades if trades else 0
        print(
            f"{symbol:8} {hits}/8 min={min(fridays):.0f} pnl={report['symbols'][symbol]['sum_pnl']:.0f} islem={trades} oran={rate:.2f}",
            flush=True,
        )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vwap_donus_5m.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
