#!/usr/bin/env python3
"""Supertrend yonunde her boslukta 3R. Suzgec yok.

Tavanin kaybedenleri de alan halidir. Stop 1.2 ATR. Risk %5.
Spread var. Secim yok.
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


def orders_of(bars) -> list:
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    vol = wk.atr(bars, 14)
    out = [None] * len(bars)
    for i, bar in enumerate(bars):
        if vol[i] is None or vol[i] <= 0 or direction[i] not in (-1, 1):
            continue
        if direction[i] == -1:
            out[i] = (1, bar.close - 1.2 * vol[i])
        else:
            out[i] = (-1, bar.close + 1.2 * vol[i])
    return out


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    cal = wk.weeks_ending(anchor[-1].t, 8)
    report = {"weeks": [row[2] for row in cal], "symbols": {}, "passed_all_8": []}
    for tf in ("15m", "5m"):
        for symbol in SYMBOLS:
            resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=80)
            costs = eng.symbol_costs(resolved)
            detail = ga.play(bars, orders_of(bars), costs, cal, 3.0)
            hits = sum(1 for row in detail if row["hit"])
            fridays = [row["friday"] for row in detail]
            trades = sum(row["trades"] for row in detail)
            wins = sum(row["winners"] for row in detail)
            name = f"{symbol}|{tf}"
            report["symbols"][name] = {
                "resolved": resolved,
                "hits": hits,
                "min_friday": round(min(fridays), 2),
                "sum_pnl": round(sum(value - wk.START_CASH for value in fridays), 2),
                "trades": trades,
                "winners": wins,
                "detail": detail,
            }
            if hits == 8:
                report["passed_all_8"].append(name)
            print(
                f"{name:16} {hits}/8 min={min(fridays):.0f} pnl={report['symbols'][name]['sum_pnl']:.0f} islem={trades} oran={wins / trades if trades else 0:.2f}",
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "st_her_bar_3r.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
