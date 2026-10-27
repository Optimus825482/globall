#!/usr/bin/env python3
"""Kaufman verim orani + Supertrend, hedef 3R.

Verim = net hareket / gidilen yol. Son 10 bar.
Esik 0.35, 0.50 veya 0.65. Secim testten onceki haftalarda.
Stop 1.2 ATR. Risk %5. Spread var. ADX en az 20, DI ayni yon.
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
THRESHOLDS = (0.35, 0.50, 0.65)


def efficiency(closes: list[float], i: int, length: int = 10) -> float:
    net = abs(closes[i] - closes[i - length])
    path = 0.0
    for j in range(i - length + 1, i + 1):
        path += abs(closes[j] - closes[j - 1])
    if path <= 0:
        return 0.0
    return net / path


def orders_at(bars, minimum: float) -> list:
    closes = [bar.close for bar in bars]
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    vol = wk.atr(bars, 14)
    out = [None] * len(bars)
    for i, bar in enumerate(bars):
        if i < 10 or vol[i] is None or vol[i] <= 0 or direction[i] not in (-1, 1):
            continue
        if adx[i] is None or plus[i] is None or minus[i] is None or adx[i] < 20:
            continue
        if efficiency(closes, i) < minimum:
            continue
        if direction[i] == -1 and plus[i] > minus[i]:
            out[i] = (1, bar.close - 1.2 * vol[i])
        elif direction[i] == 1 and minus[i] > plus[i]:
            out[i] = (-1, bar.close + 1.2 * vol[i])
    return out


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=160)
    cal = wk.weeks_ending(anchor[-1].t, 18)
    train = [row for row in cal if row[2] < TEST_FROM]
    test = [row for row in cal if row[2] >= TEST_FROM][-8:]
    report = {"train": [row[2] for row in train], "test": [row[2] for row in test], "symbols": {}, "passed_all_8": []}
    for symbol in SYMBOLS:
        resolved, bars = eng.fetch_bars(symbol, "15m", offset, lookback_days=160)
        costs = eng.symbol_costs(resolved)
        best = None
        chosen_orders = None
        for minimum in THRESHOLDS:
            orders = orders_at(bars, minimum)
            detail = ga.play(bars, orders, costs, train, 3.0)
            key = ga.rank_of(detail)
            if best is None or key > best[0]:
                best = (key, minimum)
                chosen_orders = orders
        test_detail = ga.play(bars, chosen_orders, costs, test, 3.0)
        te = ga.rank_of(test_detail)
        trades = sum(row["trades"] for row in test_detail)
        wins = sum(row["winners"] for row in test_detail)
        report["symbols"][symbol] = {
            "resolved": resolved,
            "threshold": best[1],
            "train_hits": best[0][0],
            "train_min": round(best[0][1], 2),
            "test_hits": te[0],
            "test_min": round(te[1], 2),
            "test_pnl": round(te[2], 2),
            "test_trades": trades,
            "test_winners": wins,
        }
        if te[0] == 8:
            report["passed_all_8"].append(symbol)
        rate = wins / trades if trades else 0
        print(
            f"{symbol:8} esik={best[1]:.2f} egitim {best[0][0]}/{len(train)} min={best[0][1]:.0f} | test {te[0]}/8 min={te[1]:.0f} pnl={te[2]:.0f} islem={trades} oran={rate:.2f}",
            flush=True,
        )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "st_verim_3r.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
