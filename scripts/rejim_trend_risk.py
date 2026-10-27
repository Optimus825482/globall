#!/usr/bin/env python3
"""Trend bacagi. Risk yuzdesi yalnizca testten onceki haftalarda secilir.

Aday yuzdeler sabit: 5, 8, 10, 12, 15, 20, 25, 30.
Secim, onceki haftalarin en kotu cumasini yukselten yuzdedir.
O yuzde test haftalarina bir kez uygulanir. Stop durur. Martingale yok.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import m1_rejim_sweep_60d as rej  # noqa: E402
import rejim_hafta_8w as hafta  # noqa: E402
import rejim_trend_bacak as bacak  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

RISKS = (0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30)
SYMBOLS = hafta.SYMBOLS


def run_weeks(bars, signals, costs, cal, risk: float) -> list[dict]:
    detail = []
    for start, end, label in cal:
        if bars[0].t > start:
            continue
        detail.append({
            "week": label,
            **hafta.week_cash(
                bars, signals, costs["spread_price"], costs["unit_per_lot_per_price"],
                costs["volume_min"], costs["volume_max"], costs["volume_step"],
                start, end, risk,
            ),
        })
    return detail


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=120)
    cal = wk.weeks_ending(anchor[-1].t, 14)
    test = cal[-8:]
    prior = cal[:-8]
    report = {
        "prior": [row[2] for row in prior],
        "test": [row[2] for row in test],
        "symbols": {},
        "passed_all_8": [],
    }
    for symbol in SYMBOLS:
        try:
            resolved, bars = rej.fetch(symbol, offset)
            costs = eng.symbol_costs(resolved)
            book = rej.build_signals(symbol, bars, costs["spread_price"])
        except SystemExit as exc:
            print(symbol, exc, flush=True)
            continue
        signals = bacak.trend_only(book["rejim"], 1.0)
        by_risk = {}
        best = None
        for risk in RISKS:
            detail = run_weeks(bars, signals, costs, cal, risk)
            prior_rows = [row for row in detail if row["week"] < test[0][2]]
            test_rows = [row for row in detail if row["week"] >= test[0][2]]
            prior_min = min((row["friday"] for row in prior_rows), default=None)
            test_min = min((row["friday"] for row in test_rows), default=None)
            test_hits = sum(1 for row in test_rows if row["hit"])
            prior_hits = sum(1 for row in prior_rows if row["hit"])
            by_risk[f"{int(risk * 100)}"] = {
                "prior_hits": prior_hits,
                "prior_n": len(prior_rows),
                "prior_min": None if prior_min is None else round(prior_min, 2),
                "test_hits": test_hits,
                "test_min": None if test_min is None else round(test_min, 2),
                "test": test_rows,
            }
            if prior_rows and (best is None or prior_min > best[0]):
                best = (prior_min, risk, test_hits, test_min, test_rows)
        chosen = best[1] if best else 0.05
        cell = by_risk[f"{int(chosen * 100)}"]
        report["symbols"][symbol] = {"chosen_risk": chosen, "risks": by_risk}
        if cell["test_hits"] == 8 and cell["prior_hits"] == cell["prior_n"] and cell["prior_n"] > 0:
            report["passed_all_8"].append(symbol)
        print(
            f"{symbol:8} secilen %{int(chosen * 100):02d} onceki {cell['prior_hits']}/{cell['prior_n']} min={cell['prior_min']} | test {cell['test_hits']}/8 min={cell['test_min']}",
            flush=True,
        )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rejim_trend_risk.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
