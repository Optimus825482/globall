#!/usr/bin/env python3
"""1 dakikada Supertrend yonu, hedef 3R. Suzgec yok.

15 ve 5 dakikanin sik hali. Stop 1.2 ATR. Risk %5. Spread var.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genis_arama_holdout as ga  # noqa: E402
import ha_supertrend_mt5_7d as eng  # noqa: E402
import m1_rejim_sweep_60d as rej  # noqa: E402
import st_her_bar_3r as her  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    cal = wk.weeks_ending(anchor[-1].t, 8)
    report = {"weeks": [row[2] for row in cal], "symbols": {}, "passed_all_8": []}
    for symbol in her.SYMBOLS:
        try:
            resolved, bars = rej.fetch(symbol, offset)
            costs = eng.symbol_costs(resolved)
        except SystemExit as exc:
            print(symbol, exc, flush=True)
            continue
        detail = ga.play(bars, her.orders_of(bars), costs, cal, 3.0)
        hits = sum(1 for row in detail if row["hit"])
        fridays = [row["friday"] for row in detail]
        trades = sum(row["trades"] for row in detail)
        wins = sum(row["winners"] for row in detail)
        report["symbols"][symbol] = {
            "resolved": resolved,
            "hits": hits,
            "min_friday": round(min(fridays), 2) if fridays else None,
            "sum_pnl": round(sum(value - wk.START_CASH for value in fridays), 2) if fridays else None,
            "trades": trades,
            "winners": wins,
            "detail": detail,
        }
        if hits == 8:
            report["passed_all_8"].append(symbol)
        rate = wins / trades if trades else 0
        print(
            f"{symbol:8} {hits}/8 min={min(fridays):.0f} pnl={report['symbols'][symbol]['sum_pnl']:.0f} islem={trades} oran={rate:.2f}",
            flush=True,
        )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "st_m1_her_bar_3r.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
