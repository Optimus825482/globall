#!/usr/bin/env python3
"""Rejimin yalnizca trend bacagi. Yatay bant islemleri yok.

Giris ayni: ADX 25 ustu, 15dk yon, EMA21 geri cekilme.
Stop durur. Basabas karda girise cekilir. Hedef eski 2.5 ATR ve bir de 4 ATR.
Risk %5. Her hafta 1000 USD.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import m1_rejim_sweep_60d as rej  # noqa: E402
import rejim_hafta_8w as hafta  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402


def trend_only(signals, tp_scale: float) -> list:
    out = []
    for sig in signals:
        if sig is None or sig[3] <= 0:
            out.append(None)
            continue
        side, sl, tp, be = sig
        out.append((side, sl, tp * tp_scale, be))
    return out


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    cal = wk.weeks_ending(anchor[-1].t, wk.WEEKS)
    report = {"weeks": [label for _s, _e, label in cal], "symbols": {}, "passed_all_8": []}
    for symbol in hafta.SYMBOLS:
        try:
            resolved, bars = rej.fetch(symbol, offset)
            costs = eng.symbol_costs(resolved)
            book = rej.build_signals(symbol, bars, costs["spread_price"])
        except SystemExit as exc:
            print(symbol, exc, flush=True)
            continue
        report["symbols"][symbol] = {}
        for name, scale in (("trend_2_5", 1.0), ("trend_4", 4.0 / 2.5)):
            signals = trend_only(book["rejim"], scale)
            detail = []
            for start, end, label in cal:
                detail.append({
                    "week": label,
                    **hafta.week_cash(
                        bars, signals, costs["spread_price"], costs["unit_per_lot_per_price"],
                        costs["volume_min"], costs["volume_max"], costs["volume_step"],
                        start, end, 0.05,
                    ),
                })
            hits = sum(1 for row in detail if row["hit"])
            fridays = [row["friday"] for row in detail]
            trades = sum(row["trades"] for row in detail)
            wins = sum(row["winners"] for row in detail)
            cell = {
                "hits": hits,
                "min_friday": round(min(fridays), 2),
                "sum_pnl": round(sum(value - wk.START_CASH for value in fridays), 2),
                "trades": trades,
                "winners": wins,
                "detail": detail,
            }
            report["symbols"][symbol][name] = cell
            if hits == wk.WEEKS:
                report["passed_all_8"].append(f"{symbol}|{name}")
            print(
                f"{symbol:8} {name:10} {hits}/8 min={cell['min_friday']:.0f} pnl={cell['sum_pnl']:.0f} islem={trades} kazanc={wins}",
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rejim_trend_bacak.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
