#!/usr/bin/env python3
"""Iki olcu. Biri tavan, biri kural.

Tavan: Supertrend yonu, 3R, spread dahil, kaybeden bar acilmaz.
Kural: ayni yon, govde en az 0.8 ATR, ters fitil en cok 0.25 ATR,
ADX en az 20, DI ayni yon. Stop 1.2 ATR. Hedef 3R. Risk %5.
Kural test haftasina gore secilmedi.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genis_arama_holdout as ga  # noqa: E402
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = ga.SYMBOLS
TEST_FROM = "2026-08-31"
RR = 3.0
RISK = 0.05


def ceiling(bars, direction, vol, spread: float, start: int, end: int) -> dict:
    cash = wk.START_CASH
    trades = 0
    i = 20
    while i < len(bars) - 1:
        if bars[i + 1].t > end:
            break
        if bars[i].t < start or vol[i] is None or vol[i] <= 0 or direction[i] not in (-1, 1):
            i += 1
            continue
        side = 1 if direction[i] == -1 else -1
        entry = bars[i + 1].open + (spread if side == 1 else 0.0)
        risk_px = 1.2 * vol[i]
        if side == -1:
            risk_px += spread
        target = entry + side * RR * (1.2 * vol[i])
        stop = entry - side * (1.2 * vol[i])
        hit_j = None
        for j in range(i + 1, len(bars)):
            if bars[j].t > end:
                break
            if side == 1:
                if bars[j].low <= stop:
                    break
                if bars[j].high >= target:
                    hit_j = j
                    break
            else:
                if bars[j].high >= stop:
                    break
                if bars[j].low <= target:
                    hit_j = j
                    break
        if hit_j is None:
            i += 1
            continue
        cash *= 1.0 + RISK * RR
        trades += 1
        i = hit_j + 1
    return {"friday": round(cash, 2), "hit": cash >= wk.TARGET, "trades": trades}


def impulse_orders(bars) -> list:
    st_dir_src = eng.heikin_ashi(bars)
    _st, direction = eng.supertrend(st_dir_src, 10, 3.0)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    vol = wk.atr(bars, 14)
    out = [None] * len(bars)
    for i, bar in enumerate(bars):
        if vol[i] is None or vol[i] <= 0 or adx[i] is None or adx[i] < 20:
            continue
        if plus[i] is None or minus[i] is None or direction[i] not in (-1, 1):
            continue
        body = bar.close - bar.open
        if direction[i] == -1 and plus[i] > minus[i] and body >= 0.8 * vol[i] and (bar.open - bar.low) <= 0.25 * vol[i]:
            out[i] = (1, bar.close - 1.2 * vol[i])
        elif direction[i] == 1 and minus[i] > plus[i] and -body >= 0.8 * vol[i] and (bar.high - bar.open) <= 0.25 * vol[i]:
            out[i] = (-1, bar.close + 1.2 * vol[i])
    return out


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    cal = wk.weeks_ending(anchor[-1].t, 8)
    report = {"weeks": [row[2] for row in cal], "symbols": {}, "ceiling_all_8": [], "rule_all_8": []}
    for symbol in SYMBOLS:
        resolved, bars = eng.fetch_bars(symbol, "15m", offset, lookback_days=80)
        costs = eng.symbol_costs(resolved)
        _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
        vol = wk.atr(bars, 14)
        cap = []
        for start, end, label in cal:
            cap.append({"week": label, **ceiling(bars, direction, vol, costs["spread_price"], start, end)})
        orders = impulse_orders(bars)
        rule = ga.play(bars, orders, costs, cal, RR)
        cap_hits = sum(1 for row in cap if row["hit"])
        rule_hits = sum(1 for row in rule if row["hit"])
        report["symbols"][symbol] = {
            "spread": costs["spread_price"],
            "ceiling_hits": cap_hits,
            "ceiling_min": round(min(row["friday"] for row in cap), 2),
            "rule_hits": rule_hits,
            "rule_min": round(min(row["friday"] for row in rule), 2),
            "rule_pnl": round(sum(row["friday"] - wk.START_CASH for row in rule), 2),
            "rule_trades": sum(row["trades"] for row in rule),
            "rule_wins": sum(row["winners"] for row in rule),
            "ceiling": cap,
            "rule": rule,
        }
        if cap_hits == 8:
            report["ceiling_all_8"].append(symbol)
        if rule_hits == 8:
            report["rule_all_8"].append(symbol)
        print(
            f"{symbol:8} tavan {cap_hits}/8 min={report['symbols'][symbol]['ceiling_min']:.0f} | kural {rule_hits}/8 min={report['symbols'][symbol]['rule_min']:.0f} pnl={report['symbols'][symbol]['rule_pnl']:.0f} islem={report['symbols'][symbol]['rule_trades']}",
            flush=True,
        )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "st_3r_spread_impuls.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        "file": path,
        "ceiling_all_8": report["ceiling_all_8"],
        "rule_all_8": report["rule_all_8"],
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
