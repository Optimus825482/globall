#!/usr/bin/env python3
"""Her test haftasinin kurali, yalnizca onceki 4 haftadan secilir.

O haftanin fiyatina bakilmaz. Adaylar sabit. Stop 1.2 ATR veya RSI'de 1 ATR.
Risk %5. Martingale yok.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genis_arama_holdout as ga  # noqa: E402
import ha_supertrend_mt5_7d as eng  # noqa: E402
import retest_hafta as rt  # noqa: E402
import rsi2_hafta_holdout as rsi  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = ga.SYMBOLS
TEST_FROM = "2026-08-31"
LOOK = 4


def catalog(bars) -> list[tuple[str, list, float]]:
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    vol = wk.atr(bars, 14)
    bases = ga.base_sides(bars)
    book = []
    for base_name, sides in bases.items():
        orders = ga.materialize(bars, sides, direction, plus, minus, adx, vol, 20.0, None)
        book.append((f"{base_name}_2R", orders, 2.0))
        book.append((f"{base_name}_3R", orders, 3.0))
    book.append(("retest_2R", rt.retest_orders(bars), 2.0))
    book.append(("rsi_ema_1.5R", rsi.rsi_orders(bars, True), 1.5))
    return book


def score(detail: list[dict]) -> tuple:
    rows = [row for row in detail if row.get("friday") is not None]
    if not rows:
        return (-10**9, 0.0)
    return (sum(row["friday"] - wk.START_CASH for row in rows), min(row["friday"] for row in rows))


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=160)
    cal = wk.weeks_ending(anchor[-1].t, 18)
    test_idx = [i for i, row in enumerate(cal) if row[2] >= TEST_FROM]
    report = {"test_weeks": [cal[i][2] for i in test_idx], "symbols": {}, "passed_all_8": []}
    for tf in ("15m", "5m"):
        for symbol in SYMBOLS:
            try:
                resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=160)
                costs = eng.symbol_costs(resolved)
            except SystemExit as exc:
                print(symbol, tf, exc, flush=True)
                continue
            book = catalog(bars)
            detail = []
            for idx in test_idx:
                past = cal[idx - LOOK:idx]
                best_name = None
                best_key = None
                best_orders = None
                best_rr = None
                for name, orders, rr in book:
                    key = score(ga.play(bars, orders, costs, past, rr))
                    if best_key is None or key > best_key:
                        best_key = key
                        best_name = name
                        best_orders = orders
                        best_rr = rr
                row = ga.play(bars, best_orders, costs, [cal[idx]], best_rr)[0]
                detail.append({"week": cal[idx][2], "rule": best_name, "lookback_pnl": round(best_key[0], 2), **row})
            hits = sum(1 for row in detail if row["friday"] >= wk.TARGET)
            fridays = [row["friday"] for row in detail]
            name = f"{symbol}|{tf}"
            report["symbols"][name] = {
                "resolved": resolved,
                "hits": hits,
                "min_friday": round(min(fridays), 2),
                "sum_pnl": round(sum(value - wk.START_CASH for value in fridays), 2),
                "detail": detail,
            }
            if hits == len(test_idx):
                report["passed_all_8"].append(name)
            print(
                f"{name:16} {hits}/{len(test_idx)} min={min(fridays):.0f} pnl={report['symbols'][name]['sum_pnl']:.0f} son={detail[-1]['rule']}",
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "walkforward_hafta.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
