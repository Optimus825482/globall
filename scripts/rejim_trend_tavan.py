#!/usr/bin/env python3
"""Trend girislerinin tavani. Kaybeden islem bastan atilir.

Bu kural canliya alinmaz. Islem acilmadan sonucu bilinir. Amac: ayni
girisler, yalnizca kazananlar kalsaydi cuma 2000 oluyor mu.
Stop, hedef ve 30 dk kurali gercek kosuyla ayni. Risk %5.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import m1_rejim_sweep_60d as rej  # noqa: E402
import rejim_hafta_8w as hafta  # noqa: E402
import rejim_trend_bacak as bacak  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

RISK = 0.05


def shadow_win(bars, i: int, side: int, stop: float, target: float, arm: float | None, spread: float, end: int) -> bool:
    be = False
    stop_now = stop
    last = min(len(bars), i + 31)
    for j in range(i + 1, last):
        bar = bars[j]
        if bar.t > end:
            break
        if side == 1:
            if bar.low <= stop_now:
                return False
            if bar.high >= target:
                return True
        else:
            if bar.high >= stop_now - spread:
                return False
            if bar.low <= target:
                return True
        if arm is not None and not be:
            if (side == 1 and bar.high >= arm) or (side == -1 and bar.low <= arm):
                be = True
                stop_now = bars[i].open if side == 1 else bars[i].open + spread
    return False


def week_oracle(bars, signals, spread, unit_value, vmin, vmax, vstep, start, end) -> dict:
    cash = wk.START_CASH
    pos = None
    pending = None
    trades = 0
    winners = 0
    skipped = 0
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
            if shadow_win(bars, i, side, stop, target, arm, spread, end) and risk_px > spread * 2 and cash > 0:
                volume = eng.floor_volume(cash * RISK / (risk_px * unit_value), vmin, vmax, vstep)
                if volume is not None:
                    pos = {"side": side, "net": net, "raw": raw, "stop": stop, "target": target, "arm": arm, "be": False, "vol": volume, "i": i}
            else:
                skipped += 1
        pending = None
        if pos is not None and i > pos["i"]:
            side = pos["side"]
            if side == 1:
                stop_hit = bar.low <= pos["stop"]
                tp_hit = bar.high >= pos["target"]
            else:
                stop_hit = bar.high >= pos["stop"] - spread
                tp_hit = bar.low <= pos["target"]
            if stop_hit or tp_hit or i - pos["i"] >= 30:
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
            elif pos["arm"] is not None and not pos["be"]:
                if (side == 1 and bar.high >= pos["arm"]) or (side == -1 and bar.low <= pos["arm"]):
                    pos["be"] = True
                    pos["stop"] = pos["raw"] if side == 1 else pos["raw"] + spread
        if pos is not None or i >= len(bars) - 1 or bar.t >= end:
            continue
        if signals[i] is not None:
            pending = signals[i]
    return {
        "friday": round(cash, 2),
        "hit": cash >= wk.TARGET,
        "trades": trades,
        "winners": winners,
        "skipped": skipped,
    }


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    cal = wk.weeks_ending(anchor[-1].t, 8)
    report = {"note": "kaybedenler bastan atildi, strateji degil", "symbols": {}, "passed_all_8": []}
    for symbol in hafta.SYMBOLS:
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
            detail.append({
                "week": label,
                **week_oracle(
                    bars, signals, costs["spread_price"], costs["unit_per_lot_per_price"],
                    costs["volume_min"], costs["volume_max"], costs["volume_step"], start, end,
                ),
            })
        hits = sum(1 for row in detail if row["hit"])
        fridays = [row["friday"] for row in detail]
        report["symbols"][symbol] = {
            "hits": hits,
            "min_friday": round(min(fridays), 2),
            "detail": detail,
        }
        if hits == 8:
            report["passed_all_8"].append(symbol)
        print(
            f"{symbol:8} {hits}/8 min={min(fridays):.0f} " + " ".join(f"{row['week'][5:]}:{row['friday']:.0f}" for row in detail),
            flush=True,
        )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rejim_trend_tavan.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
