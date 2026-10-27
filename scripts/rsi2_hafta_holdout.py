#!/usr/bin/env python3
"""RSI(2) donusu. Hedef 1R ve 1.5R. Egitimde secilir, testte bir kez kosar.

Long: RSI(2) 10 altindan 10 ustune cikar. EMA(200) istege bagli, kapanis ustunde.
Short: RSI(2) 90 ustunden 90 altina iner. Stop 1 ATR. Risk %5. Stop kalkmaz.
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


def rsi_orders(bars: list[eng.Bar], use_ema: bool) -> list:
    closes = [bar.close for bar in bars]
    rsi = eng.rsi_wilder(closes, 2)
    ema = wk.ema(closes, 200) if use_ema else [0.0] * len(bars)
    vol = wk.atr(bars, 14)
    out = [None] * len(bars)
    for i in range(1, len(bars)):
        if rsi[i] is None or rsi[i - 1] is None or vol[i] is None or vol[i] <= 0:
            continue
        if use_ema and ema[i] is None:
            continue
        if rsi[i - 1] < 10 <= rsi[i] and (not use_ema or closes[i] > ema[i]):
            out[i] = (1, closes[i] - vol[i])
        elif rsi[i - 1] > 90 >= rsi[i] and (not use_ema or closes[i] < ema[i]):
            out[i] = (-1, closes[i] + vol[i])
    return out


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
    menus = (("ema", True), ("serbest", False))
    for tf in ("15m", "5m"):
        for symbol in SYMBOLS:
            try:
                resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=160)
                costs = eng.symbol_costs(resolved)
            except SystemExit as exc:
                print(symbol, tf, exc, flush=True)
                continue
            built = {name: rsi_orders(bars, use_ema) for name, use_ema in menus}
            best = None
            for name, orders in built.items():
                for rr in (1.0, 1.5):
                    detail = play(bars, orders, costs, train, rr)
                    key = rank_of(detail)
                    label = f"{name}_{rr:g}R"
                    if best is None or key > best[0]:
                        best = (key, label, orders, rr, detail)
            assert best is not None
            key, label, orders, rr, _train_detail = best
            test_detail = play(bars, orders, costs, test, rr)
            test_key = rank_of(test_detail)
            name = f"{symbol}|{tf}"
            wins = sum(row["winners"] for row in test_detail)
            trades = sum(row["trades"] for row in test_detail)
            report["symbols"][name] = {
                "chosen": label,
                "train_hits": key[0],
                "train_min": round(key[1], 2),
                "test_hits": test_key[0],
                "test_min": round(test_key[1], 2),
                "test_pnl": round(test_key[2], 2),
                "test_trades": trades,
                "test_winners": wins,
                "test": test_detail,
            }
            if test_key[0] == wk.WEEKS:
                passed.append(name)
            print(
                f"{name:16} secim={label:12} egitim {key[0]}/{len(train)} min={key[1]:.0f} | test {test_key[0]}/8 min={test_key[1]:.0f} pnl={test_key[2]:.0f} islem={trades} kazanc={wins}",
                flush=True,
            )
    report["passed_all_8"] = passed
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rsi2_hafta_holdout.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": passed}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
