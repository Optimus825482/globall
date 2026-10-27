#!/usr/bin/env python3
"""Donchian kirilimi hemen alinmaz. Seviye geri test edilince girilir.

Kural kosudan once kilitli. 20 barlik Donchian kapanis kirilimi, Heikin Ashi
Supertrend ayni yonde, ADX en az 20 ve DI ayni yonde. Sonraki 8 barda fiyat
kirilan seviyeye dokunup tekrar disarida kapanirsa bir sonraki acilista girilir.
Stop 1.2 ATR. Hedef 2R ve 3R ayri ayri. Risk %5. Stop kalkmaz.
Egitim ve test haftalari ikisi de raporlanir. Biri digerini secmek icin kullanilmaz.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import hafta_cift_15m as sim  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = (
    "XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY",
    "USDCAD", "EURCAD", "GBPCAD", "EURNZD", "GBPNZD", "NZDUSD",
)
TEST_FROM = "2026-08-31"
RISK = 0.05


def retest_orders(bars: list[eng.Bar]) -> list:
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    vol = wk.atr(bars, 14)
    out = [None] * len(bars)
    used_until = -1
    for i in range(20, len(bars) - 2):
        if i <= used_until or vol[i] is None or adx[i] is None or adx[i] < 20:
            continue
        hh = max(bar.high for bar in bars[i - 20:i])
        ll = min(bar.low for bar in bars[i - 20:i])
        side = 0
        level = 0.0
        if bars[i].close > hh and direction[i] == -1 and plus[i] is not None and plus[i] > minus[i]:
            side, level = 1, hh
        elif bars[i].close < ll and direction[i] == 1 and minus[i] is not None and minus[i] > plus[i]:
            side, level = -1, ll
        if side == 0:
            continue
        for step in range(1, 9):
            j = i + step
            if j >= len(bars) - 1 or vol[j] is None:
                break
            if side == 1 and bars[j].low <= level and bars[j].close > level:
                out[j] = (1, bars[j].close - 1.2 * vol[j])
                used_until = j
                break
            if side == -1 and bars[j].high >= level and bars[j].close < level:
                out[j] = (-1, bars[j].close + 1.2 * vol[j])
                used_until = j
                break
            if side == 1 and bars[j].close < level - 0.5 * vol[j]:
                break
            if side == -1 and bars[j].close > level + 0.5 * vol[j]:
                break
    return out


def ceiling(orders, bars, cal, rr: float) -> list[dict]:
    rows = []
    gain = 1.0 + RISK * rr
    for start, end, label in cal:
        count = sum(1 for i, bar in enumerate(bars) if start <= bar.t <= end and orders[i] is not None)
        cash = wk.START_CASH
        for _ in range(count):
            cash *= gain
        rows.append({"week": label, "signals": count, "all_win_friday": round(cash, 2)})
    return rows


def play(bars, orders, costs, cal, rr: float) -> list[dict]:
    detail = []
    for start, end, label in cal:
        row = sim.simulate(
            bars, orders, costs["spread_price"], costs["unit_per_lot_per_price"],
            costs["volume_min"], costs["volume_max"], costs["volume_step"],
            start, end, RISK, rr, None,
        )
        detail.append({"week": label, **row})
    return detail


def pack(detail: list[dict]) -> dict:
    rows = [row for row in detail if row.get("friday") is not None]
    fridays = [row["friday"] for row in rows]
    return {
        "hits": sum(1 for row in rows if row["friday"] >= wk.TARGET),
        "n": len(rows),
        "min": min(fridays) if fridays else None,
        "pnl": round(sum(value - wk.START_CASH for value in fridays), 2) if fridays else None,
    }


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=160)
    cal = wk.weeks_ending(anchor[-1].t, 18)
    train = [row for row in cal if row[2] < TEST_FROM]
    test = [row for row in cal if row[2] >= TEST_FROM][-wk.WEEKS:]
    report = {"train": [row[2] for row in train], "test": [row[2] for row in test], "symbols": {}}
    passed = []
    for tf in ("15m", "5m"):
        for symbol in SYMBOLS:
            try:
                resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=160)
                costs = eng.symbol_costs(resolved)
            except SystemExit as exc:
                print(symbol, tf, exc, flush=True)
                continue
            orders = retest_orders(bars)
            for rr in (2.0, 3.0):
                test_rows = play(bars, orders, costs, test, rr)
                train_rows = play(bars, orders, costs, train, rr)
                cap = ceiling(orders, bars, test, rr)
                key = f"{symbol}|{tf}|{int(rr)}R"
                tp, tr = pack(test_rows), pack(train_rows)
                cap_hits = sum(1 for row in cap if row["all_win_friday"] >= wk.TARGET)
                report["symbols"][key] = {
                    "test": tp, "train": tr, "test_detail": test_rows, "ceiling": cap,
                }
                if tp["hits"] == wk.WEEKS:
                    passed.append(key)
                print(
                    f"{key:20} test {tp['hits']}/8 min={tp['min']} pnl={tp['pnl']} | egitim {tr['hits']}/{tr['n']} min={tr['min']} | tavan_hafta {cap_hits}/8",
                    flush=True,
                )
    report["passed_all_8"] = passed
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "retest_hafta.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": passed}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
