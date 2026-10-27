#!/usr/bin/env python3
"""Kayip sonrasi bekleme ve dar aralik kirilimi. Hedef 3R.

bekle: her kayiptan sonra 12 bar (15 dkda 3 saat) yeni islem yok.
cevir: kayiptan sonra Supertrend yon degistirene kadar yok.
dar: son 7 barin en darinin disina, Supertrend yonunde kapanis.
Stop 1.2 ATR. Risk %5. Spread var. Secim yok.
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


def prepare(bars):
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    vol = wk.atr(bars, 14)
    narrow = [False] * len(bars)
    for i in range(7, len(bars)):
        span = bars[i].high - bars[i].low
        if span <= 0:
            continue
        if all(span <= bars[j].high - bars[j].low for j in range(i - 6, i)):
            narrow[i] = True
    signal = {"bekle": [0] * len(bars), "cevir": [0] * len(bars), "dar": [0] * len(bars)}
    for i, bar in enumerate(bars):
        if vol[i] is None or vol[i] <= 0 or direction[i] not in (-1, 1):
            continue
        side = 1 if direction[i] == -1 else -1
        signal["bekle"][i] = side
        signal["cevir"][i] = side
        if i > 0 and narrow[i - 1]:
            if side == 1 and bar.close > bars[i - 1].high:
                signal["dar"][i] = 1
            elif side == -1 and bar.close < bars[i - 1].low:
                signal["dar"][i] = -1
    return direction, vol, signal


def simulate(bars, direction, vol, sides, mode: str, spread, unit_value, vmin, vmax, vstep, start: int, end: int) -> dict:
    cash = wk.START_CASH
    pos = None
    pending = None
    quiet_until = -1
    need_flip = False
    seen_dir = 0
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
        if direction[i] != seen_dir and direction[i] in (-1, 1):
            if need_flip and seen_dir != 0:
                need_flip = False
            seen_dir = direction[i]
        if bar.t < start:
            continue
        if pos is None and pending is not None and i > quiet_until and not need_flip:
            side, stop_line = pending
            raw = bar.open
            if side == 1:
                net = raw + spread
                stop = stop_line
                risk_px = net - stop
                target = net + 3.0 * risk_px
            else:
                net = raw
                stop = stop_line + spread
                risk_px = stop - net
                target = net - 3.0 * risk_px
            if risk_px > spread and cash > 0 and unit_value > 0:
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
            if stop_hit or tp_hit:
                if side == 1:
                    raw_exit = (bar.open if bar.open < pos["stop"] else pos["stop"]) if stop_hit else pos["target"]
                    pnl = (raw_exit - pos["net"]) * unit_value * pos["vol"]
                else:
                    if stop_hit:
                        level = pos["stop"] - spread
                        raw_exit = bar.open if bar.open > level else level
                    else:
                        raw_exit = pos["target"]
                    pnl = (pos["net"] - (raw_exit + spread)) * unit_value * pos["vol"]
                cash += pnl
                trades += 1
                if pnl > 0:
                    winners += 1
                else:
                    if mode == "bekle":
                        quiet_until = i + 12
                    elif mode == "cevir":
                        need_flip = True
                pos = None
        if pos is None and i > quiet_until and not need_flip and sides[i] in (1, -1) and vol[i] is not None and bar.t < end:
            if sides[i] == 1:
                pending = (1, bar.close - 1.2 * vol[i])
            else:
                pending = (-1, bar.close + 1.2 * vol[i])
    return {"friday": round(cash, 2), "hit": cash >= wk.TARGET, "trades": trades, "winners": winners}


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    cal = wk.weeks_ending(anchor[-1].t, 8)
    report = {"weeks": [row[2] for row in cal], "symbols": {}, "passed_all_8": []}
    modes = ("bekle", "cevir", "dar")
    loaded = {}
    for symbol in SYMBOLS:
        resolved, bars = eng.fetch_bars(symbol, "15m", offset, lookback_days=80)
        loaded[symbol] = (resolved, bars, eng.symbol_costs(resolved), prepare(bars))
    for mode in modes:
        for symbol, (resolved, bars, costs, packed) in loaded.items():
            direction, vol, signal = packed
            detail = []
            for start, end, label in cal:
                detail.append({
                    "week": label,
                    **simulate(
                        bars, direction, vol, signal[mode], mode, costs["spread_price"],
                        costs["unit_per_lot_per_price"], costs["volume_min"], costs["volume_max"],
                        costs["volume_step"], start, end,
                    ),
                })
            hits = sum(1 for row in detail if row["hit"])
            fridays = [row["friday"] for row in detail]
            trades = sum(row["trades"] for row in detail)
            wins = sum(row["winners"] for row in detail)
            name = f"{symbol}|{mode}"
            report["symbols"][name] = {
                "hits": hits,
                "min_friday": round(min(fridays), 2),
                "sum_pnl": round(sum(value - wk.START_CASH for value in fridays), 2),
                "trades": trades,
                "winners": wins,
            }
            if hits == 8:
                report["passed_all_8"].append(name)
            rate = wins / trades if trades else 0
            print(
                f"{name:16} {hits}/8 min={min(fridays):.0f} pnl={report['symbols'][name]['sum_pnl']:.0f} islem={trades} oran={rate:.2f}",
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "st_bekle_dar_3r.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
