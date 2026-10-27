#!/usr/bin/env python3
"""Yutan mum ve inside-bar kirilimi. Egitimde secilir, testte bir kez kosar.

Yutan long: kapanis onceki tepenin ustunde, acilis onceki kapanisin altinda.
Inside: onceki mum anne barin icinde, bu mum anne tepesini veya dibini kirar.
Supertrend ve ADX 20 ayni yonde. Stop 1.2 ATR. Hedef 2R veya 3R. Risk %5.
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


def gate(direction, plus, minus, adx, i: int, side: int) -> bool:
    if adx[i] is None or plus[i] is None or minus[i] is None or adx[i] < 20:
        return False
    if side == 1:
        return direction[i] == -1 and plus[i] > minus[i]
    return direction[i] == 1 and minus[i] > plus[i]


def orders_of(bars, kind: str) -> list:
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    vol = wk.atr(bars, 14)
    out = [None] * len(bars)
    start = 3 if kind == "inside" else 2
    for i in range(start, len(bars)):
        if vol[i] is None or vol[i] <= 0:
            continue
        side = 0
        if kind == "yutan":
            prev = bars[i - 1]
            if bars[i].close > prev.high and bars[i].open < prev.close and bars[i].close > bars[i].open:
                side = 1
            elif bars[i].close < prev.low and bars[i].open > prev.close and bars[i].close < bars[i].open:
                side = -1
        else:
            mother, inside = bars[i - 2], bars[i - 1]
            if inside.high > mother.high or inside.low < mother.low:
                continue
            if bars[i].close > mother.high:
                side = 1
            elif bars[i].close < mother.low:
                side = -1
        if side == 0 or not gate(direction, plus, minus, adx, i, side):
            continue
        if side == 1:
            out[i] = (1, bars[i].close - 1.2 * vol[i])
        else:
            out[i] = (-1, bars[i].close + 1.2 * vol[i])
    return out


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=160)
    cal = wk.weeks_ending(anchor[-1].t, 18)
    train = [row for row in cal if row[2] < TEST_FROM]
    test = [row for row in cal if row[2] >= TEST_FROM][-wk.WEEKS:]
    report = {"train": [row[2] for row in train], "test": [row[2] for row in test], "symbols": {}, "passed_all_8": []}
    for tf in ("15m", "5m"):
        for symbol in SYMBOLS:
            try:
                resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=160)
                costs = eng.symbol_costs(resolved)
            except SystemExit as exc:
                print(symbol, tf, exc, flush=True)
                continue
            built = {kind: orders_of(bars, kind) for kind in ("yutan", "inside")}
            best = None
            for kind, orders in built.items():
                for rr in (2.0, 3.0):
                    detail = ga.play(bars, orders, costs, train, rr)
                    key = ga.rank_of(detail)
                    label = f"{kind}_{int(rr)}R"
                    if best is None or key > best[0]:
                        best = (key, label, orders, rr)
            key, label, orders, rr = best
            test_detail = ga.play(bars, orders, costs, test, rr)
            test_key = ga.rank_of(test_detail)
            trades = sum(row["trades"] for row in test_detail)
            wins = sum(row["winners"] for row in test_detail)
            name = f"{symbol}|{tf}"
            report["symbols"][name] = {
                "resolved": resolved,
                "chosen": label,
                "train_hits": key[0],
                "train_min": round(key[1], 2),
                "test_hits": test_key[0],
                "test_min": round(test_key[1], 2),
                "test_pnl": round(test_key[2], 2),
                "test_trades": trades,
                "test_winners": wins,
                "test": test_detail,
            }
            if test_key[0] == wk.WEEKS:
                report["passed_all_8"].append(name)
            rate = (wins / trades) if trades else 0
            print(
                f"{name:16} secim={label:12} egitim {key[0]}/{len(train)} min={key[1]:.0f} | test {test_key[0]}/8 min={test_key[1]:.0f} pnl={test_key[2]:.0f} islem={trades} oran={rate:.2f}",
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pa_mum_holdout.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
