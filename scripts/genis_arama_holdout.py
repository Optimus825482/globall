#!/usr/bin/env python3
"""Egitim haftasinda genis kombinasyon aranir. Test haftasina bakilmaz.

Adaylar sabit: Supertrend donusu, EMA 9/21, RSI(2), Donchian 20.
Filtre: ADX 20 veya 30, DI ayni yon, Supertrend ayni yon, seans tum gun veya 07-20.
Hedef 2R veya 3R. Stop 1.2 ATR. Risk %5. Her sembol egitimde bir kural secer.
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


def hour_of(ts: int) -> int:
    return datetime.fromtimestamp(ts, timezone.utc).hour


def macd_cross(closes: list[float]) -> list[int]:
    fast, slow = wk.ema(closes, 12), wk.ema(closes, 26)
    macd = [None if a is None or b is None else a - b for a, b in zip(fast, slow)]
    sig: list[float | None] = [None] * len(closes)
    buf: list[float] = []
    prev = None
    k = 2 / 10
    for i, value in enumerate(macd):
        if value is None:
            continue
        if prev is None:
            buf.append(value)
            if len(buf) == 9:
                prev = sum(buf) / 9
                sig[i] = prev
            continue
        prev = value * k + prev * (1 - k)
        sig[i] = prev
    side = [0] * len(closes)
    for i in range(1, len(closes)):
        if None in (macd[i], macd[i - 1], sig[i], sig[i - 1]):
            continue
        if macd[i - 1] <= sig[i - 1] and macd[i] > sig[i]:
            side[i] = 1
        elif macd[i - 1] >= sig[i - 1] and macd[i] < sig[i]:
            side[i] = -1
    return side


def base_sides(bars: list[eng.Bar]) -> dict[str, list[int]]:
    closes = [bar.close for bar in bars]
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    rsi = eng.rsi_wilder(closes, 2)
    ema9, ema21 = wk.ema(closes, 9), wk.ema(closes, 21)
    st = [0] * len(bars)
    ema = [0] * len(bars)
    rsi_side = [0] * len(bars)
    don = [0] * len(bars)
    for i in range(1, len(bars)):
        if direction[i] != direction[i - 1] and direction[i] in (-1, 1):
            st[i] = 1 if direction[i] == -1 else -1
        if None not in (ema9[i], ema9[i - 1], ema21[i], ema21[i - 1]):
            if ema9[i - 1] <= ema21[i - 1] and ema9[i] > ema21[i]:
                ema[i] = 1
            elif ema9[i - 1] >= ema21[i - 1] and ema9[i] < ema21[i]:
                ema[i] = -1
        if rsi[i] is not None and rsi[i - 1] is not None:
            if rsi[i - 1] < 10 <= rsi[i]:
                rsi_side[i] = 1
            elif rsi[i - 1] > 90 >= rsi[i]:
                rsi_side[i] = -1
    for i in range(20, len(bars)):
        hh = max(bar.high for bar in bars[i - 20:i])
        ll = min(bar.low for bar in bars[i - 20:i])
        if bars[i].close > hh:
            don[i] = 1
        elif bars[i].close < ll:
            don[i] = -1
    return {"st": st, "ema": ema, "rsi2": rsi_side, "don": don, "macd": macd_cross(closes)}


def materialize(bars, sides, direction, plus, minus, adx, vol, adx_min: float, session) -> list:
    out = [None] * len(bars)
    for i, side in enumerate(sides):
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
    report = {"train": [row[2] for row in train], "test": [row[2] for row in test], "passed_all_8": []}
    cells = {}
    sessions = (("tum", None), ("lnny", (7, 20)))
    for tf in ("15m", "1h"):
        for symbol in SYMBOLS:
            try:
                resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=160)
                costs = eng.symbol_costs(resolved)
            except SystemExit as exc:
                print(symbol, tf, exc, flush=True)
                continue
            closes = [bar.close for bar in bars]
            _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
            plus, minus, adx = eng.adx_dmi(bars, 14)
            vol = wk.atr(bars, 14)
            bases = base_sides(bars)
            best = None
            for base_name, sides in bases.items():
                for adx_min in (20.0, 30.0):
                    for sess_name, session in sessions:
                        orders = materialize(bars, sides, direction, plus, minus, adx, vol, adx_min, session)
                        if not any(orders):
                            continue
                        for rr in (2.0, 3.0):
                            detail = play(bars, orders, costs, train, rr)
                            key = rank_of(detail)
                            label = f"{base_name}_adx{int(adx_min)}_{sess_name}_{int(rr)}R"
                            if best is None or key > best[0]:
                                best = (key, label, orders, rr)
            if best is None:
                print(f"{symbol}|{tf} sinyal yok", flush=True)
                continue
            key, label, orders, rr = best
            test_detail = play(bars, orders, costs, test, rr)
            test_key = rank_of(test_detail)
            name = f"{symbol}|{tf}"
            cells[name] = {
                "resolved": resolved,
                "chosen": label,
                "train_hits": key[0],
                "train_weeks": len(train),
                "train_min": round(key[1], 2),
                "test_hits": test_key[0],
                "test_min": round(test_key[1], 2),
                "test_pnl": round(test_key[2], 2),
                "test": test_detail,
            }
            if test_key[0] == wk.WEEKS:
                report["passed_all_8"].append(name)
            print(
                f"{name:16} secim={label:28} egitim {key[0]}/{len(train)} min={key[1]:.0f} | test {test_key[0]}/8 min={test_key[1]:.0f} pnl={test_key[2]:.0f}",
                flush=True,
            )
    report["symbols"] = cells
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "genis_arama_holdout.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
