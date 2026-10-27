#!/usr/bin/env python3
"""Uc yukselen dip veya uc dusen tepe. Hedef 3R.

Long: dipler yukseliyor, kapanis bir oncekinden yuksek, Supertrend yukari,
ADX en az 20, DI ayni yon. Short tersi.
Stop 1.2 ATR. Risk %5. Spread var. Secim yok.
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


def orders_of(bars) -> list:
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    vol = wk.atr(bars, 14)
    out = [None] * len(bars)
    for i in range(2, len(bars)):
        if vol[i] is None or vol[i] <= 0 or adx[i] is None or adx[i] < 20:
            continue
        if plus[i] is None or minus[i] is None or direction[i] not in (-1, 1):
            continue
        higher_lows = bars[i].low > bars[i - 1].low > bars[i - 2].low and bars[i].close > bars[i - 1].close
        lower_highs = bars[i].high < bars[i - 1].high < bars[i - 2].high and bars[i].close < bars[i - 1].close
        if direction[i] == -1 and plus[i] > minus[i] and higher_lows:
            out[i] = (1, bars[i].close - 1.2 * vol[i])
        elif direction[i] == 1 and minus[i] > plus[i] and lower_highs:
            out[i] = (-1, bars[i].close + 1.2 * vol[i])
    return out


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    cal = wk.weeks_ending(anchor[-1].t, 8)
    report = {"weeks": [row[2] for row in cal], "symbols": {}, "passed_all_8": []}
    for symbol in SYMBOLS:
        resolved, bars = eng.fetch_bars(symbol, "15m", offset, lookback_days=80)
        costs = eng.symbol_costs(resolved)
        detail = ga.play(bars, orders_of(bars), costs, cal, 3.0)
        hits = sum(1 for row in detail if row["hit"])
        fridays = [row["friday"] for row in detail]
        trades = sum(row["trades"] for row in detail)
        wins = sum(row["winners"] for row in detail)
        report["symbols"][symbol] = {
            "resolved": resolved,
            "hits": hits,
            "min_friday": round(min(fridays), 2),
            "sum_pnl": round(sum(value - wk.START_CASH for value in fridays), 2),
            "trades": trades,
            "winners": wins,
        }
        if hits == 8:
            report["passed_all_8"].append(symbol)
        rate = wins / trades if trades else 0
        print(
            f"{symbol:8} {hits}/8 min={min(fridays):.0f} pnl={report['symbols'][symbol]['sum_pnl']:.0f} islem={trades} oran={rate:.2f}",
            flush=True,
        )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "st_dip_3r.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
