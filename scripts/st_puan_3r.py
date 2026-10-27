#!/usr/bin/env python3
"""Supertrend yonunde puan. Esik yalnizca testten onceki haftalarda.

Puan, bar kapaninca belli olan seylerden gelir.
ADX, DI, trend yasi, govde, ters fitil, cizgiye uzaklik, saat, ATR genislemesi.
Stop 1.2 ATR. Hedef 3R. Risk %5. Spread var.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genis_arama_holdout as ga  # noqa: E402
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = ga.SYMBOLS
TEST_FROM = "2026-08-31"
THRESHOLDS = (4, 5, 6, 7)


def hour_of(ts: int) -> int:
    return datetime.fromtimestamp(ts, timezone.utc).hour


def scores(bars) -> tuple[list[int], list[int]]:
    st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    vol = wk.atr(bars, 14)
    side = [0] * len(bars)
    score = [0] * len(bars)
    age = 0
    atr_sum = 0.0
    for i, bar in enumerate(bars):
        if i > 0 and direction[i] != direction[i - 1] and direction[i] in (-1, 1):
            age = 0
        elif i > 0:
            age += 1
        if vol[i] is not None:
            atr_sum += vol[i]
        if i >= 20 and vol[i - 20] is not None:
            atr_sum -= vol[i - 20]
        if direction[i] not in (-1, 1) or vol[i] is None or vol[i] <= 0 or st[i] is None:
            continue
        if adx[i] is None or plus[i] is None or minus[i] is None:
            continue
        way = 1 if direction[i] == -1 else -1
        points = 0
        if adx[i] >= 25:
            points += 1
        if adx[i] >= 35:
            points += 1
        if way == 1 and plus[i] - minus[i] >= 10:
            points += 1
        if way == -1 and minus[i] - plus[i] >= 10:
            points += 1
        if 4 <= age <= 20:
            points += 1
        body = (bar.close - bar.open) * way
        if body >= 0.5 * vol[i]:
            points += 1
        wick = (bar.open - bar.low) if way == 1 else (bar.high - bar.open)
        if wick <= 0.2 * vol[i]:
            points += 1
        gap = (bar.close - st[i]) * way
        if 0.2 * vol[i] <= gap <= 1.5 * vol[i]:
            points += 1
        if 12 <= hour_of(bar.t) < 16:
            points += 1
        if i >= 20 and atr_sum > 0 and vol[i] >= atr_sum / 20:
            points += 1
        side[i] = way
        score[i] = points
    return side, score


def orders_at(bars, side, score, vol, minimum: int) -> list:
    out = [None] * len(bars)
    for i, bar in enumerate(bars):
        if side[i] == 0 or score[i] < minimum or vol[i] is None or vol[i] <= 0:
            continue
        if side[i] == 1:
            out[i] = (1, bar.close - 1.2 * vol[i])
        else:
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
        vol = wk.atr(bars, 14)
        side, score = scores(bars)
        best = None
        for minimum in THRESHOLDS:
            orders = orders_at(bars, side, score, vol, minimum)
            detail = ga.play(bars, orders, costs, train, 3.0)
            key = ga.rank_of(detail)
            if best is None or key > best[0]:
                best = (key, minimum, orders)
        key, minimum, orders = best
        test_detail = ga.play(bars, orders, costs, test, 3.0)
        te = ga.rank_of(test_detail)
        trades = sum(row["trades"] for row in test_detail)
        wins = sum(row["winners"] for row in test_detail)
        report["symbols"][symbol] = {
            "resolved": resolved,
            "threshold": minimum,
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
            f"{symbol:8} esik={minimum} egitim {key[0]}/{len(train)} min={key[1]:.0f} | test {te[0]}/8 min={te[1]:.0f} pnl={te[2]:.0f} islem={trades} oran={rate:.2f}",
            flush=True,
        )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "st_puan_3r.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
