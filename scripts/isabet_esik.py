#!/usr/bin/env python3
"""Egitim haftasinda 2R isabet oranini olcer. Esik once kilitli.

Bir dilim egitimde haftada en az 8 islem ve isabet orani en az %60 degilse
teste alinmaz. %5 riskte 2R, bu ikisi yoksa cuma 2000 aritmetik olarak cikmaz.
Stop 1.2 ATR. Test haftasinin sonucu secime girmez.
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
MIN_PER_WEEK = 8
MIN_RATE = 0.60


def hour_of(ts: int) -> int:
    return datetime.fromtimestamp(ts, timezone.utc).hour


def squeeze_sides(bars, vol) -> list[int]:
    sides = [0] * len(bars)
    for i in range(48, len(bars)):
        if vol[i] is None:
            continue
        last = max(bar.high for bar in bars[i - 8:i]) - min(bar.low for bar in bars[i - 8:i])
        wider = False
        for start in range(i - 40, i - 8):
            span = max(bar.high for bar in bars[start:start + 8]) - min(bar.low for bar in bars[start:start + 8])
            if span < last:
                wider = True
                break
        if wider:
            continue
        hh = max(bar.high for bar in bars[i - 8:i])
        ll = min(bar.low for bar in bars[i - 8:i])
        if bars[i].close > hh:
            sides[i] = 1
        elif bars[i].close < ll:
            sides[i] = -1
    return sides


def strong_sides(bars) -> list[int]:
    sides = [0] * len(bars)
    for i, bar in enumerate(bars):
        span = bar.high - bar.low
        if span <= 0:
            continue
        if bar.close > bar.open and (bar.close - bar.low) / span >= 0.7:
            sides[i] = 1
        elif bar.close < bar.open and (bar.high - bar.close) / span >= 0.7:
            sides[i] = -1
    return sides


def mask(bars, base, direction, plus, minus, adx, vol, adx_min: float, session) -> list:
    out = [None] * len(bars)
    for i, side in enumerate(base):
        if side not in (1, -1) or vol[i] is None or vol[i] <= 0:
            continue
        if adx[i] is None or plus[i] is None or minus[i] is None or adx[i] < adx_min:
            continue
        if side == 1 and not (direction[i] == -1 and plus[i] > minus[i]):
            continue
        if side == -1 and not (direction[i] == 1 and minus[i] > plus[i]):
            continue
        if session is not None and not (session[0] <= hour_of(bars[i].t) < session[1]):
            continue
        if side == 1:
            out[i] = (1, bars[i].close - 1.2 * vol[i])
        else:
            out[i] = (-1, bars[i].close + 1.2 * vol[i])
    return out


def slice_stats(detail: list[dict]) -> dict:
    rows = [row for row in detail if row.get("friday") is not None]
    trades = sum(row["trades"] for row in rows)
    wins = sum(row["winners"] for row in rows)
    return {
        "weeks": len(rows),
        "trades": trades,
        "wins": wins,
        "per_week": round(trades / len(rows), 2) if rows else 0,
        "rate": round(wins / trades, 3) if trades else None,
        "hits": sum(1 for row in rows if row["friday"] >= wk.TARGET),
        "min": round(min(row["friday"] for row in rows), 2) if rows else None,
    }


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=160)
    cal = wk.weeks_ending(anchor[-1].t, 18)
    train = [row for row in cal if row[2] < TEST_FROM]
    test = [row for row in cal if row[2] >= TEST_FROM][-wk.WEEKS:]
    report = {
        "rule": "Egitimde haftada >=8 islem ve isabet >=0.60 ise teste alinir",
        "train": [row[2] for row in train],
        "test": [row[2] for row in test],
        "symbols": {},
        "passed_all_8": [],
        "qualified": [],
    }
    for tf in ("15m", "5m"):
        for symbol in SYMBOLS:
            try:
                resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=160)
                costs = eng.symbol_costs(resolved)
            except SystemExit as exc:
                print(symbol, tf, exc, flush=True)
                continue
            _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
            plus, minus, adx = eng.adx_dmi(bars, 14)
            vol = wk.atr(bars, 14)
            bases = {
                "st": [1 if direction[i] == -1 else -1 if direction[i] == 1 else 0 for i in range(len(bars))],
                "squeeze": squeeze_sides(bars, vol),
                "guclu": strong_sides(bars),
            }
            specs = []
            for base_name, sides in bases.items():
                for adx_min, sess_name, session in (
                    (20.0, "tum", None),
                    (25.0, "lnny", (7, 20)),
                    (30.0, "ov", (12, 16)),
                ):
                    orders = mask(bars, sides, direction, plus, minus, adx, vol, adx_min, session)
                    train_detail = ga.play(bars, orders, costs, train, 2.0)
                    stats = slice_stats(train_detail)
                    specs.append((f"{base_name}_adx{int(adx_min)}_{sess_name}", orders, stats, train_detail))
            qualified = [item for item in specs if item[2]["per_week"] >= MIN_PER_WEEK and (item[2]["rate"] or 0) >= MIN_RATE]
            name = f"{symbol}|{tf}"
            best = max(specs, key=lambda item: (item[2]["rate"] or 0, item[2]["per_week"]))
            cell = {
                "resolved": resolved,
                "best_train_slice": best[0],
                "best_train": best[2],
                "qualified": [item[0] for item in qualified],
            }
            if qualified:
                pick = max(qualified, key=lambda item: ga.rank_of(item[3]))
                test_detail = ga.play(bars, pick[1], costs, test, 2.0)
                test_stats = slice_stats(test_detail)
                cell["tested"] = pick[0]
                cell["test"] = test_stats
                cell["test_detail"] = test_detail
                report["qualified"].append(name)
                if test_stats["hits"] == wk.WEEKS:
                    report["passed_all_8"].append(name)
                print(
                    f"{name:16} ADAY {pick[0]} egitim oran={pick[2]['rate']} /hafta={pick[2]['per_week']} | test {test_stats['hits']}/8 min={test_stats['min']}",
                    flush=True,
                )
            else:
                cell["tested"] = None
                print(
                    f"{name:16} esik yok eniyi={best[0]} oran={best[2]['rate']} /hafta={best[2]['per_week']} hit={best[2]['hits']}",
                    flush=True,
                )
            report["symbols"][name] = cell
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "isabet_esik.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        "file": path,
        "qualified": report["qualified"],
        "passed_all_8": report["passed_all_8"],
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
