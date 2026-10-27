#!/usr/bin/env python3
"""5 dk kesim, 15 ve 30 dk ayni renk.

Yesil histogram al, kirmizi histogram sat.
15 ve 30, 5 dk mumu kapanmadan kapanmis olmali.
Stop 1.2 ATR. Kagit 10000 USD, risk %1.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macd_mtf_onay as mtf  # noqa: E402
import macd_sifir_kesim as tek  # noqa: E402


def confirm(raw: list[int], masks: list[list[int]]) -> list[int]:
    out = [0] * len(raw)
    for i, side in enumerate(raw):
        if side != 0 and all(mask[i] == side for mask in masks):
            out[i] = side
    return out


def main() -> None:
    tek.eng.attach_terminal()
    offset = tek.eng.server_offset_s()
    _name, anchor = tek.eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    last = anchor[-1].t
    report = {
        "rule": "5dk histogram sifir kesimi. 15 ve 30 ayni renkteyse islem.",
        "symbols": {},
    }
    for symbol in tek.SYMBOLS:
        try:
            resolved, bars5 = tek.eng.fetch_bars(symbol, "5m", offset, lookback_days=90)
        except SystemExit as exc:
            print(symbol, exc, flush=True)
            continue
        bars15 = tek.wk.resample(bars5, 900)
        bars30 = tek.wk.resample(bars5, 1800)
        costs = tek.eng.symbol_costs(resolved)
        raw = mtf.zero_cross(bars5)
        masks = (
            mtf.align(bars5, bars15, 900, 300),
            mtf.align(bars5, bars30, 1800, 300),
        )
        sides = confirm(raw, list(masks))
        vol = tek.wk.atr(bars5, 14)
        cells = {}
        for days in tek.WINDOWS:
            start = last - days * 86400
            if bars5[0].t > start:
                cells[str(days)] = {"note": "veri_kisiti"}
                continue
            cells[str(days)] = tek.simulate(
                bars5, sides, vol, costs["spread_price"], costs["unit_per_lot_per_price"],
                costs["volume_min"], costs["volume_max"], costs["volume_step"], start, last,
            )
        report["symbols"][symbol] = {"resolved": resolved, "spread": costs["spread_price"], "cells": cells}
        for days in ("7", "14", "30", "60"):
            row = cells.get(days, {})
            print(
                f"{symbol:8} {days:>2}g islem={row.get('trades')} net={row.get('net')} pf={row.get('pf')} dd={row.get('dd')} oran={row.get('win_rate')}",
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macd_mtf_5_15_30.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
