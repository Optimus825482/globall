#!/usr/bin/env python3
"""Kilitli kural: 3dk MACD kesimi + Heikin Ashi Supertrend, risk %5.

XAUUSD aramasinda en yuksek hafta skoru buydu. Parametre degismez.
Her sembol ayri. Her hafta Pazartesi 1000 USD, hedef Cuma 2000.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = (
    "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY",
    "USDCAD", "EURCAD", "GBPCAD", "EURNZD", "GBPNZD", "NZDUSD",
)
RISK = 0.05


def load_m3(symbol: str, offset: int) -> tuple[str, list]:
    try:
        return eng.fetch_bars(symbol, "3m", offset, lookback_days=140)
    except SystemExit:
        resolved, bars = wk.m1.fetch_m1(symbol, offset)
        return resolved, wk.resample(bars, 180)


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    anchor_name, anchor = load_m3("EURUSD", offset)
    cal = wk.weeks_ending(anchor[-1].t, wk.WEEKS)
    report = {
        "rule": "3m MACD kesimi + HA Supertrend, stop 1.2 ATR, risk %5",
        "anchor": anchor_name,
        "weeks": [label for _s, _e, label in cal],
        "start_cash": wk.START_CASH,
        "target": wk.TARGET,
        "symbols": {},
    }
    for symbol in SYMBOLS:
        try:
            resolved, bars = load_m3(symbol, offset)
            costs = eng.symbol_costs(resolved)
        except SystemExit as exc:
            report["symbols"][symbol] = {"error": str(exc)}
            continue
        if not bars:
            report["symbols"][symbol] = {"error": "mum yok"}
            continue
        series = wk.signals_macd_st(bars)
        detail = []
        for start, end, label in cal:
            covered = any(start <= bar.t <= end for bar in bars)
            if not covered:
                detail.append({"week": label, "friday": None, "hit": False, "trades": 0, "winners": 0, "dd": None, "note": "veri_yok"})
                continue
            row = wk.simulate(
                bars, series, costs["spread_price"], costs["unit_per_lot_per_price"],
                costs["volume_min"], costs["volume_max"], costs["volume_step"],
                start, end, RISK,
            )
            detail.append({"week": label, **row})
        scored = [row for row in detail if row.get("friday") is not None]
        hits = sum(1 for row in scored if row.get("hit"))
        fridays = [row["friday"] for row in scored]
        report["symbols"][symbol] = {
            "resolved": resolved,
            "spread": costs["spread_price"],
            "first_utc": datetime.fromtimestamp(bars[0].t, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "last_utc": datetime.fromtimestamp(bars[-1].t, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "weeks_with_data": len(scored),
            "hits": hits,
            "min_friday": min(fridays) if fridays else None,
            "max_friday": max(fridays) if fridays else None,
            "avg_friday": round(sum(fridays) / len(fridays), 2) if fridays else None,
            "sum_pnl": round(sum(value - wk.START_CASH for value in fridays), 2) if fridays else None,
            "detail": detail,
        }
    combined = []
    for _start, _end, label in cal:
        book = []
        for body in report["symbols"].values():
            if "detail" not in body:
                continue
            row = next(item for item in body["detail"] if item["week"] == label)
            if row.get("friday") is not None:
                book.append(row["friday"])
        combined.append({
            "week": label,
            "symbols": len(book),
            "sum_friday": round(sum(book), 2) if book else None,
            "sum_start": round(wk.START_CASH * len(book), 2) if book else None,
            "sum_pnl": round(sum(book) - wk.START_CASH * len(book), 2) if book else None,
        })
    report["combined_separate_books"] = combined
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macd_hast_3m_multi.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    brief = {
        symbol: {
            "hits": body.get("hits"),
            "weeks": body.get("weeks_with_data"),
            "min": body.get("min_friday"),
            "max": body.get("max_friday"),
            "avg": body.get("avg_friday"),
            "pnl": body.get("sum_pnl"),
            "error": body.get("error"),
            "last": body.get("last_utc"),
        }
        for symbol, body in report["symbols"].items()
    }
    print(json.dumps({"file": path, "weeks": report["weeks"], "symbols": brief, "combined": combined}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
