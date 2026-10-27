#!/usr/bin/env python3
"""Supertrend yasina gore 3R. Secim testten once.

Yas 0: donus bari. 1-3, 4-10, 11-40 ve 40'tan eski ayri ayri denenir.
DI ayni yonde, ADX en az 20. Stop 1.2 ATR. Hedef 3R. Risk %5.
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
BUCKETS = (("yas0", 0, 0), ("yas1_3", 1, 3), ("yas4_10", 4, 10), ("yas11_40", 11, 40), ("yas41", 41, 10**9))


def ages_and_sides(direction) -> tuple[list[int], list[int]]:
    age = 0
    ages = [0] * len(direction)
    sides = [0] * len(direction)
    for i, way in enumerate(direction):
        if i > 0 and way != direction[i - 1] and way in (-1, 1):
            age = 0
        elif i > 0:
            age += 1
        ages[i] = age
        if way == -1:
            sides[i] = 1
        elif way == 1:
            sides[i] = -1
    return ages, sides


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=160)
    cal = wk.weeks_ending(anchor[-1].t, 18)
    train = [row for row in cal if row[2] < TEST_FROM]
    test = [row for row in cal if row[2] >= TEST_FROM][-8:]
    report = {"train": [row[2] for row in train], "test": [row[2] for row in test], "symbols": {}, "passed_all_8": []}
    for tf in ("15m",):
        for symbol in SYMBOLS:
            resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=160)
            costs = eng.symbol_costs(resolved)
            _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
            plus, minus, adx = eng.adx_dmi(bars, 14)
            vol = wk.atr(bars, 14)
            ages, sides = ages_and_sides(direction)
            best = None
            for name, lo, hi in BUCKETS:
                gated = [side if lo <= ages[i] <= hi else 0 for i, side in enumerate(sides)]
                orders = ga.materialize(bars, gated, direction, plus, minus, adx, vol, 20.0, None)
                detail = ga.play(bars, orders, costs, train, 3.0)
                key = ga.rank_of(detail)
                if best is None or key > best[0]:
                    best = (key, name, orders)
            key, name, orders = best
            test_detail = ga.play(bars, orders, costs, test, 3.0)
            te = ga.rank_of(test_detail)
            wins = sum(row["winners"] for row in test_detail)
            trades = sum(row["trades"] for row in test_detail)
            report["symbols"][symbol] = {
                "resolved": resolved,
                "chosen": name,
                "train_hits": key[0],
                "train_min": round(key[1], 2),
                "test_hits": te[0],
                "test_min": round(te[1], 2),
                "test_pnl": round(te[2], 2),
                "test_trades": trades,
                "test_winners": wins,
                "test": test_detail,
            }
            if te[0] == 8:
                report["passed_all_8"].append(symbol)
            rate = wins / trades if trades else 0
            print(
                f"{symbol:8} secim={name:8} egitim {key[0]}/{len(train)} min={key[1]:.0f} | test {te[0]}/8 min={te[1]:.0f} pnl={te[2]:.0f} islem={trades} oran={rate:.2f}",
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "st_yas_3r.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
