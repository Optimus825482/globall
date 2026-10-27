#!/usr/bin/env python3
"""Major kirilir, cift henuz kirilmadiysa cifte girilir.

Kural kosudan once kilitli. Surucu son 6 M5 barin tepesini veya dibini kapatir
ve Heikin Ashi Supertrend ayni yondedir. Cift kendi 6 barlik seviyesini henuz
kirmadiysa bir sonraki acilista girilir. Stop 1.2 ATR, hedef 2R, risk %5.
Altin EURUSD ile ayni yon. USD ciftleri EURUSD'nin tersi. BTC, EURUSD ve
GBPUSD kendi kirilimina girer.
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
LOOK = 6
# (surucu, yon carpani). None ise sembol kendi kirilimina girer.
LINKS = {
    "EURJPY": ("EURUSD", 1),
    "EURCAD": ("EURUSD", 1),
    "EURNZD": ("EURUSD", 1),
    "GBPJPY": ("GBPUSD", 1),
    "GBPCAD": ("GBPUSD", 1),
    "GBPNZD": ("GBPUSD", 1),
    "XAUUSD": ("EURUSD", 1),
    "USDJPY": ("EURUSD", -1),
    "USDCAD": ("EURUSD", -1),
    "NZDUSD": ("EURUSD", 1),
    "EURUSD": None,
    "GBPUSD": None,
    "BTCUSD": None,
}


def broke(bars, i: int, side: int) -> bool:
    if i < LOOK:
        return False
    if side == 1:
        level = max(bar.high for bar in bars[i - LOOK:i])
        return bars[i].close > level
    level = min(bar.low for bar in bars[i - LOOK:i])
    return bars[i].close < level


def st_map(bars) -> dict[int, int]:
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    return {bar.t: direction[i] for i, bar in enumerate(bars)}


def orders_for(symbol: str, books: dict, directions: dict, vols: dict) -> list:
    bars = books[symbol]
    out = [None] * len(bars)
    link = LINKS[symbol]
    vol = vols[symbol]
    for i, bar in enumerate(bars):
        if i < LOOK or vol[i] is None or vol[i] <= 0:
            continue
        if link is None:
            direction = directions[symbol].get(bar.t, 0)
            side = 1 if direction == -1 else -1 if direction == 1 else 0
            if side == 0 or not broke(bars, i, side):
                continue
        else:
            driver_name, sign = link
            driver = books[driver_name]
            d_st = directions[driver_name].get(bar.t, 0)
            d_index = {b.t: k for k, b in enumerate(driver)} if False else None
            if not hasattr(orders_for, "_idx"):
                pass
            side_driver = 1 if d_st == -1 else -1 if d_st == 1 else 0
            if side_driver == 0:
                continue
            d_i = orders_for.idx[driver_name].get(bar.t)
            if d_i is None or not broke(driver, d_i, side_driver):
                continue
            side = side_driver * sign
            if broke(bars, i, side):
                continue
        if side == 1:
            out[i] = (1, bar.close - 1.2 * vol[i])
        else:
            out[i] = (-1, bar.close + 1.2 * vol[i])
    return out


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "5m", offset, lookback_days=160)
    cal = wk.weeks_ending(anchor[-1].t, 18)
    train = [row for row in cal if row[2] < TEST_FROM]
    test = [row for row in cal if row[2] >= TEST_FROM][-wk.WEEKS:]
    books = {}
    directions = {}
    vols = {}
    costs = {}
    for symbol in SYMBOLS:
        resolved, bars = eng.fetch_bars(symbol, "5m", offset, lookback_days=160)
        books[symbol] = bars
        directions[symbol] = st_map(bars)
        vols[symbol] = wk.atr(bars, 14)
        costs[symbol] = eng.symbol_costs(resolved)
    orders_for.idx = {name: {bar.t: i for i, bar in enumerate(bars)} for name, bars in books.items()}
    report = {"train": [row[2] for row in train], "test": [row[2] for row in test], "symbols": {}, "passed_all_8": []}
    for symbol in SYMBOLS:
        orders = orders_for(symbol, books, directions, vols)
        train_detail = ga.play(books[symbol], orders, costs[symbol], train, 2.0)
        test_detail = ga.play(books[symbol], orders, costs[symbol], test, 2.0)
        tr, te = ga.rank_of(train_detail), ga.rank_of(test_detail)
        trades = sum(row["trades"] for row in test_detail)
        wins = sum(row["winners"] for row in test_detail)
        report["symbols"][symbol] = {
            "train_hits": tr[0],
            "train_min": round(tr[1], 2),
            "test_hits": te[0],
            "test_min": round(te[1], 2),
            "test_pnl": round(te[2], 2),
            "test_trades": trades,
            "test_winners": wins,
            "test": test_detail,
        }
        if te[0] == wk.WEEKS:
            report["passed_all_8"].append(symbol)
        rate = wins / trades if trades else 0
        print(
            f"{symbol:8} egitim {tr[0]}/{len(train)} min={tr[1]:.0f} | test {te[0]}/8 min={te[1]:.0f} pnl={te[2]:.0f} islem={trades} oran={rate:.2f}",
            flush=True,
        )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "oncu_cift.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
