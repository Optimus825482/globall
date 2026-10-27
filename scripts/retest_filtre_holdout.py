#!/usr/bin/env python3
"""Geri test sinyaline egitim haftasinda filtre secilir. Test haftasina bakilmaz.

Aday filtreler kosudan once sabit. Her sembol, egitimde en cok 2000 gosteren
filtreyi alir. Beraberlikte en yuksek dip cuma. Secilen filtre testte bir kez kosar.
Stop 1.2 ATR. Risk %5. Martingale yok.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

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


def h1_closed_dir(bars: list[eng.Bar]) -> dict[int, int]:
    h1 = wk.resample(bars, 3600)
    _st, direction = eng.supertrend(eng.heikin_ashi(h1), 10, 3.0)
    return {bar.t: direction[i] for i, bar in enumerate(h1)}


def events(bars: list[eng.Bar]) -> list[dict | None]:
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    vol = wk.atr(bars, 14)
    h1 = h1_closed_dir(bars)
    out: list[dict | None] = [None] * len(bars)
    used_until = -1
    for i in range(20, len(bars) - 2):
        if i <= used_until or vol[i] is None or adx[i] is None or adx[i] < 20:
            continue
        if plus[i] is None or minus[i] is None:
            continue
        hh = max(bar.high for bar in bars[i - 20:i])
        ll = min(bar.low for bar in bars[i - 20:i])
        side = 0
        level = 0.0
        if bars[i].close > hh and direction[i] == -1 and plus[i] > minus[i]:
            side, level = 1, hh
        elif bars[i].close < ll and direction[i] == 1 and minus[i] > plus[i]:
            side, level = -1, ll
        if side == 0:
            continue
        for step in range(1, 9):
            j = i + step
            if j >= len(bars) - 1 or vol[j] is None or adx[j] is None:
                break
            touched = (side == 1 and bars[j].low <= level and bars[j].close > level) or (
                side == -1 and bars[j].high >= level and bars[j].close < level
            )
            if not touched:
                if side == 1 and bars[j].close < level - 0.5 * vol[j]:
                    break
                if side == -1 and bars[j].close > level + 0.5 * vol[j]:
                    break
                continue
            span = bars[j].high - bars[j].low
            strong = span > 0 and (
                (side == 1 and bars[j].close > bars[j].open and (bars[j].close - bars[j].low) / span >= 0.6)
                or (side == -1 and bars[j].close < bars[j].open and (bars[j].high - bars[j].close) / span >= 0.6)
            )
            bucket = bars[j].t // 3600 * 3600 - 3600
            out[j] = {
                "side": side,
                "stop": bars[j].close - 1.2 * vol[j] if side == 1 else bars[j].close + 1.2 * vol[j],
                "step": step,
                "adx": adx[j],
                "strong": strong,
                "hour": datetime.fromtimestamp(bars[j].t, timezone.utc).hour,
                "h1": h1.get(bucket, 0),
            }
            used_until = j
            break
    return out


def orders_from(evts: list[dict | None], pred) -> list:
    out = [None] * len(evts)
    for i, ev in enumerate(evts):
        if ev is not None and pred(ev):
            out[i] = (ev["side"], ev["stop"])
    return out


def h1_ok(ev: dict) -> bool:
    if ev["side"] == 1:
        return ev["h1"] == -1
    return ev["h1"] == 1


FILTERS = (
    ("ham", lambda ev: True),
    ("adx30", lambda ev: ev["adx"] >= 30),
    ("hizli", lambda ev: ev["step"] <= 3),
    ("guclu", lambda ev: ev["strong"]),
    ("overlap", lambda ev: 12 <= ev["hour"] < 16),
    ("siki", lambda ev: ev["adx"] >= 25 and ev["step"] <= 3 and ev["strong"]),
    ("h1", lambda ev: ev["adx"] >= 25 and h1_ok(ev)),
)


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


def rank_of(detail: list[dict]) -> tuple:
    rows = [row for row in detail if row.get("friday") is not None]
    if not rows:
        return (0, 0.0, 0.0)
    hits = sum(1 for row in rows if row["friday"] >= wk.TARGET)
    return (hits, min(row["friday"] for row in rows), sum(row["friday"] - wk.START_CASH for row in rows))


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
            evts = events(bars)
            best = None
            for name, pred in FILTERS:
                base = orders_from(evts, pred)
                for rr in (2.0, 3.0):
                    detail = play(bars, base, costs, train, rr)
                    key = rank_of(detail)
                    if best is None or key > best[0]:
                        best = (key, f"{name}_{int(rr)}R", base, rr, detail)
            assert best is not None
            key, label, base, rr, train_detail = best
            test_detail = play(bars, base, costs, test, rr)
            test_key = rank_of(test_detail)
            cell_name = f"{symbol}|{tf}"
            report["symbols"][cell_name] = {
                "chosen": label,
                "train_hits": key[0],
                "train_min": round(key[1], 2),
                "test_hits": test_key[0],
                "test_min": round(test_key[1], 2),
                "test_pnl": round(test_key[2], 2),
                "test": test_detail,
            }
            if test_key[0] == wk.WEEKS:
                passed.append(cell_name)
            print(
                f"{cell_name:16} secim={label:12} egitim {key[0]}/{len(train)} min={key[1]:.0f} | test {test_key[0]}/8 min={test_key[1]:.0f} pnl={test_key[2]:.0f}",
                flush=True,
            )
    report["passed_all_8"] = passed
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "retest_filtre_holdout.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": passed}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
