#!/usr/bin/env python3
"""Sembol basina kural, egitim haftalarinda secilir. 8 test haftasina bakilmaz.

Egitim: 2026-08-31 oncesi tamamlanmis haftalar.
Test: 31 Ağu 2026'dan sonraki 8 hafta, secim bittikten sonra bir kez.
Stop 1.2 ATR, hedef 2R, risk %5. Stop kalkmaz, martingale yok.
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
RR = 2.0


def hour_of(ts: int) -> int:
    return datetime.fromtimestamp(ts, timezone.utc).hour


def context(bars: list[eng.Bar]) -> dict:
    closes = [bar.close for bar in bars]
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    return {
        "bars": bars,
        "closes": closes,
        "vol": wk.atr(bars, 14),
        "direction": direction,
        "plus": plus,
        "minus": minus,
        "adx": adx,
        "ema9": wk.ema(closes, 9),
        "ema21": wk.ema(closes, 21),
    }


def to_orders(ctx: dict, sides: list[int]) -> list:
    bars, vol = ctx["bars"], ctx["vol"]
    out = [None] * len(bars)
    for i, side in enumerate(sides):
        if side not in (1, -1) or vol[i] is None or vol[i] <= 0:
            continue
        if side == 1:
            out[i] = (1, bars[i].close - 1.2 * vol[i])
        else:
            out[i] = (-1, bars[i].close + 1.2 * vol[i])
    return out


def trend_ok(ctx, i, side, adx_min: float) -> bool:
    adx, plus, minus, direction = ctx["adx"][i], ctx["plus"][i], ctx["minus"][i], ctx["direction"][i]
    if adx is None or plus is None or minus is None or adx < adx_min:
        return False
    if side == 1:
        return direction == -1 and plus > minus
    return direction == 1 and minus > plus


def rule_mom(ctx, mult: float, adx_min: float, hours: tuple[int, int] | None) -> list:
    bars, vol = ctx["bars"], ctx["vol"]
    sides = [0] * len(bars)
    for i in range(4, len(bars)):
        if vol[i] is None or vol[i] <= 0:
            continue
        if hours is not None and not (hours[0] <= hour_of(bars[i].t) < hours[1]):
            continue
        move = bars[i].close - bars[i - 4].close
        side = 1 if move > mult * vol[i] else -1 if move < -mult * vol[i] else 0
        if side and trend_ok(ctx, i, side, adx_min):
            sides[i] = side
    return sides


def rule_three(ctx) -> list:
    closes = ctx["closes"]
    sides = [0] * len(closes)
    for i in range(3, len(closes)):
        if closes[i] > closes[i - 1] > closes[i - 2] and trend_ok(ctx, i, 1, 20):
            sides[i] = 1
        elif closes[i] < closes[i - 1] < closes[i - 2] and trend_ok(ctx, i, -1, 20):
            sides[i] = -1
    return sides


def rule_donchian(ctx) -> list:
    bars = ctx["bars"]
    sides = [0] * len(bars)
    for i in range(20, len(bars)):
        hh = max(bar.high for bar in bars[i - 20:i])
        ll = min(bar.low for bar in bars[i - 20:i])
        if bars[i].close > hh and trend_ok(ctx, i, 1, 20):
            sides[i] = 1
        elif bars[i].close < ll and trend_ok(ctx, i, -1, 20):
            sides[i] = -1
    return sides


def rule_ema(ctx) -> list:
    e9, e21 = ctx["ema9"], ctx["ema21"]
    sides = [0] * len(e9)
    for i in range(1, len(e9)):
        if None in (e9[i], e9[i - 1], e21[i], e21[i - 1]):
            continue
        if e9[i - 1] <= e21[i - 1] and e9[i] > e21[i] and trend_ok(ctx, i, 1, 25):
            sides[i] = 1
        elif e9[i - 1] >= e21[i - 1] and e9[i] < e21[i] and trend_ok(ctx, i, -1, 25):
            sides[i] = -1
    return sides


def rule_pullback(ctx) -> list:
    bars, ema = ctx["bars"], ctx["ema21"]
    sides = [0] * len(bars)
    for i in range(21, len(bars)):
        if ema[i] is None:
            continue
        if bars[i].low <= ema[i] <= bars[i].close and trend_ok(ctx, i, 1, 20):
            sides[i] = 1
        elif bars[i].high >= ema[i] >= bars[i].close and trend_ok(ctx, i, -1, 20):
            sides[i] = -1
    return sides


def rule_strong(ctx) -> list:
    bars = ctx["bars"]
    sides = [0] * len(bars)
    for i in range(20, len(bars)):
        span = bars[i].high - bars[i].low
        if span <= 0:
            continue
        if (bars[i].close - bars[i].low) / span >= 0.75 and bars[i].close > bars[i].open and trend_ok(ctx, i, 1, 25):
            sides[i] = 1
        elif (bars[i].high - bars[i].close) / span >= 0.75 and bars[i].close < bars[i].open and trend_ok(ctx, i, -1, 25):
            sides[i] = -1
    return sides


RULES = {
    "mom_adx20": lambda ctx: rule_mom(ctx, 0.5, 20, None),
    "mom_adx25": lambda ctx: rule_mom(ctx, 0.5, 25, None),
    "mom_adx30": lambda ctx: rule_mom(ctx, 0.8, 30, None),
    "mom_overlap": lambda ctx: rule_mom(ctx, 0.5, 25, (12, 16)),
    "mom_london": lambda ctx: rule_mom(ctx, 0.5, 20, (7, 11)),
    "uc_bar": rule_three,
    "donchian": rule_donchian,
    "ema_kesisim": rule_ema,
    "geri_cekilme": rule_pullback,
    "guclu_kapanis": rule_strong,
}


def play(bars, orders, costs, cal) -> list[dict]:
    detail = []
    for start, end, label in cal:
        if not any(start <= bar.t <= end for bar in bars):
            detail.append({"week": label, "friday": None, "hit": False, "trades": 0, "winners": 0, "dd": None})
            continue
        row = sim.simulate(
            bars, orders, costs["spread_price"], costs["unit_per_lot_per_price"],
            costs["volume_min"], costs["volume_max"], costs["volume_step"],
            start, end, RISK, RR, None,
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
    print("train", [row[2] for row in train], flush=True)
    print("test", [row[2] for row in test], flush=True)
    report = {"train_weeks": [row[2] for row in train], "test_weeks": [row[2] for row in test], "symbols": {}}
    passed = []
    for tf in ("15m", "5m"):
        for symbol in SYMBOLS:
            try:
                resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=160)
                costs = eng.symbol_costs(resolved)
            except SystemExit as exc:
                report["symbols"][f"{symbol}|{tf}"] = {"error": str(exc)}
                print(symbol, tf, exc, flush=True)
                continue
            ctx = context(bars)
            best_name = None
            best_key = None
            best_orders = None
            best_train = None
            for name, builder in RULES.items():
                orders = to_orders(ctx, builder(ctx))
                detail = play(bars, orders, costs, train)
                key = rank_of(detail)
                if best_key is None or key > best_key:
                    best_key = key
                    best_name = name
                    best_orders = orders
                    best_train = detail
            test_detail = play(bars, best_orders, costs, test)
            test_key = rank_of(test_detail)
            cell = {
                "resolved": resolved,
                "chosen": best_name,
                "train_hits": best_key[0],
                "train_min": round(best_key[1], 2),
                "test_hits": test_key[0],
                "test_min": round(test_key[1], 2),
                "test_pnl": round(test_key[2], 2),
                "train": best_train,
                "test": test_detail,
            }
            report["symbols"][f"{symbol}|{tf}"] = cell
            if test_key[0] == len(test) and len(test) == wk.WEEKS:
                passed.append(f"{symbol}|{tf}")
            print(
                f"{symbol:8} {tf:3} secim={best_name:14} egitim {best_key[0]}/{len(train)} min={best_key[1]:.0f} | test {test_key[0]}/{len(test)} min={test_key[1]:.0f} pnl={test_key[2]:.0f}",
                flush=True,
            )
    report["passed_all_8"] = passed
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hafta_holdout_secim.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": passed}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
