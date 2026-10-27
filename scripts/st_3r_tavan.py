#!/usr/bin/env python3
"""Supertrend yonunde 3R tavan. Kaybeden bar baslanmaz.

Strateji degildir. Heikin Ashi Supertrend yonu bellidir. O yonde
1.2 ATR stop ve 3R hedef, stop yemeden doluyorsa islem alinir.
Risk %5. Her hafta 1000 USD.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = (
    "XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY",
    "USDCAD", "EURCAD", "GBPCAD", "EURNZD", "GBPNZD", "NZDUSD",
)
RISK = 0.05
RR = 3.0


def friday_of(bars, direction, vol, start: int, end: int) -> dict:
    cash = wk.START_CASH
    trades = 0
    i = 20
    while i < len(bars) - 1:
        if bars[i + 1].t > end:
            break
        if bars[i].t < start or vol[i] is None or vol[i] <= 0 or direction[i] not in (-1, 1):
            i += 1
            continue
        side = 1 if direction[i] == -1 else -1
        entry = bars[i + 1].open
        risk_px = 1.2 * vol[i]
        target = entry + side * RR * risk_px
        stop = entry - side * risk_px
        hit_j = None
        for j in range(i + 1, len(bars)):
            if bars[j].t > end:
                break
            if side == 1:
                if bars[j].low <= stop:
                    break
                if bars[j].high >= target:
                    hit_j = j
                    break
            else:
                if bars[j].high >= stop:
                    break
                if bars[j].low <= target:
                    hit_j = j
                    break
        if hit_j is None:
            i += 1
            continue
        cash *= 1.0 + RISK * RR
        trades += 1
        i = hit_j + 1
    return {"friday": round(cash, 2), "hit": cash >= wk.TARGET, "trades": trades}


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    cal = wk.weeks_ending(anchor[-1].t, 8)
    report = {"note": "ST yonu, yalnizca 3R kazananlar, strateji degil", "symbols": {}, "passed_all_8": []}
    for tf in ("15m", "5m"):
        for symbol in SYMBOLS:
            _resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=80)
            _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
            vol = wk.atr(bars, 14)
            detail = []
            for start, end, label in cal:
                detail.append({"week": label, **friday_of(bars, direction, vol, start, end)})
            hits = sum(1 for row in detail if row["hit"])
            fridays = [row["friday"] for row in detail]
            name = f"{symbol}|{tf}"
            report["symbols"][name] = {"hits": hits, "min_friday": round(min(fridays), 2), "detail": detail}
            if hits == 8:
                report["passed_all_8"].append(name)
            print(
                f"{name:16} {hits}/8 min={min(fridays):.0f} " + " ".join(f"{row['week'][5:]}:{row['friday']:.0f}/{row['trades']}" for row in detail),
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "st_3r_tavan.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
