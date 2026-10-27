#!/usr/bin/env python3
"""Karli cikan 5 sembol. Ayni kilitli kural, her hafta yeniden 1000 USD.

Secim onceki 8 haftalik kosunun sonucuna gore yapildi. Bu replay ayni haftalari
yeniden oynatir; yeni bir pencere degildir.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import macd_hast_3m_multi as multi  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = ("EURUSD", "USDJPY", "EURJPY", "GBPJPY", "USDCAD")


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = multi.load_m3("EURUSD", offset)
    cal = wk.weeks_ending(anchor[-1].t, wk.WEEKS)
    symbols = {}
    for symbol in SYMBOLS:
        resolved, bars = multi.load_m3(symbol, offset)
        costs = eng.symbol_costs(resolved)
        series = wk.signals_macd_st(bars)
        detail = []
        for start, end, label in cal:
            row = wk.simulate(
                bars, series, costs["spread_price"], costs["unit_per_lot_per_price"],
                costs["volume_min"], costs["volume_max"], costs["volume_step"],
                start, end, multi.RISK,
            )
            detail.append({"week": label, **row})
        fridays = [row["friday"] for row in detail]
        symbols[symbol] = {
            "resolved": resolved,
            "spread": costs["spread_price"],
            "last_utc": datetime.fromtimestamp(bars[-1].t, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "hits": sum(1 for row in detail if row["hit"]),
            "min_friday": min(fridays),
            "max_friday": max(fridays),
            "sum_pnl": round(sum(value - wk.START_CASH for value in fridays), 2),
            "detail": detail,
        }
    combined = []
    for _s, _e, label in cal:
        book = []
        for body in symbols.values():
            row = next(item for item in body["detail"] if item["week"] == label)
            book.append(row["friday"])
        combined.append({
            "week": label,
            "sum_friday": round(sum(book), 2),
            "sum_start": wk.START_CASH * len(SYMBOLS),
            "sum_pnl": round(sum(book) - wk.START_CASH * len(SYMBOLS), 2),
            "books_at_target": sum(1 for value in book if value >= wk.TARGET),
        })
    report = {
        "rule": "3m MACD + HA Supertrend, risk %5, her hafta 1000 USD",
        "symbols_kept": list(SYMBOLS),
        "symbols_removed": ["BTCUSD", "GBPUSD", "EURCAD", "GBPCAD", "EURNZD", "GBPNZD", "NZDUSD"],
        "weeks": [label for _s, _e, label in cal],
        "symbols": symbols,
        "combined": combined,
        "eight_week_pnl": round(sum(row["sum_pnl"] for row in combined), 2),
        "weeks_combined_positive": sum(1 for row in combined if row["sum_pnl"] > 0),
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macd_hast_3m_karli.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        "file": path,
        "eight_week_pnl": report["eight_week_pnl"],
        "weeks_combined_positive": report["weeks_combined_positive"],
        "combined": combined,
        "symbols": {s: {"hits": b["hits"], "min": b["min_friday"], "pnl": b["sum_pnl"]} for s, b in symbols.items()},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
