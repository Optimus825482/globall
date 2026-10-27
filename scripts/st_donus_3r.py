#!/usr/bin/env python3
"""Supertrend donusu, hedef 3R. Secim testten onceki haftalarda.

Spread var. Stop 1.2 ATR. Risk %5. Martingale yok.
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


def flip_sides(direction) -> list[int]:
    out = [0] * len(direction)
    for i in range(1, len(direction)):
        if direction[i] != direction[i - 1] and direction[i] in (-1, 1):
            out[i] = 1 if direction[i] == -1 else -1
    return out


def fresh_sides(direction, closes) -> list[int]:
    out = [0] * len(direction)
    for i in range(2, len(direction)):
        if direction[i] == -1 and closes[i] > closes[i - 1] > closes[i - 2]:
            out[i] = 1
        elif direction[i] == 1 and closes[i] < closes[i - 1] < closes[i - 2]:
            out[i] = -1
    return out


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=160)
    cal = wk.weeks_ending(anchor[-1].t, 18)
    train = [row for row in cal if row[2] < TEST_FROM]
    test = [row for row in cal if row[2] >= TEST_FROM][-8:]
    report = {"train": [row[2] for row in train], "test": [row[2] for row in test], "symbols": {}, "passed_all_8": []}
    for tf in ("15m", "5m"):
        for symbol in SYMBOLS:
            resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=160)
            costs = eng.symbol_costs(resolved)
            closes = [bar.close for bar in bars]
            _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
            plus, minus, adx = eng.adx_dmi(bars, 14)
            vol = wk.atr(bars, 14)
            bases = {
                "donus20": (flip_sides(direction), 20.0),
                "donus30": (flip_sides(direction), 30.0),
                "taze20": (fresh_sides(direction, closes), 20.0),
                "taze30": (fresh_sides(direction, closes), 30.0),
            }
            best = None
            for name, (sides, adx_min) in bases.items():
                orders = ga.materialize(bars, sides, direction, plus, minus, adx, vol, adx_min, None)
                detail = ga.play(bars, orders, costs, train, 3.0)
                key = ga.rank_of(detail)
                if best is None or key > best[0]:
                    best = (key, name, orders, detail)
            key, name, orders, _train_detail = best
            test_detail = ga.play(bars, orders, costs, test, 3.0)
            te = ga.rank_of(test_detail)
            label = f"{symbol}|{tf}"
            report["symbols"][label] = {
                "resolved": resolved,
                "chosen": name,
                "train_hits": key[0],
                "train_min": round(key[1], 2),
                "test_hits": te[0],
                "test_min": round(te[1], 2),
                "test_pnl": round(te[2], 2),
                "test": test_detail,
            }
            if te[0] == 8:
                report["passed_all_8"].append(label)
            print(
                f"{label:16} secim={name:8} egitim {key[0]}/{len(train)} min={key[1]:.0f} | test {te[0]}/8 min={te[1]:.0f} pnl={te[2]:.0f}",
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "st_donus_3r.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
