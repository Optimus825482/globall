#!/usr/bin/env python3
"""15dk MACD + HA Supertrend + ADX 25. Hedef 2R veya 3R. Stop durur.

Kurallar kosudan once kilitlendi. Sembol basina ayar aranmadi.
Her hafta 1000 USD. Ust uste 2 stop olursa 30 dk yeni islem yok.
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
    "XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY",
    "USDCAD", "EURCAD", "GBPCAD", "EURNZD", "GBPNZD", "NZDUSD",
)
MODES = (
    {"name": "2R_5", "rr": 2.0, "risk": 0.05, "hours": None},
    {"name": "3R_5", "rr": 3.0, "risk": 0.05, "hours": None},
    {"name": "2R_5_ov", "rr": 2.0, "risk": 0.05, "hours": (12, 16)},
    {"name": "2R_2", "rr": 2.0, "risk": 0.02, "hours": None},
)


def signals(bars: list[eng.Bar]) -> list[tuple[int, float] | None]:
    closes = [b.close for b in bars]
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
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    vol = wk.atr(bars, 14)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    out: list[tuple[int, float] | None] = [None] * len(bars)
    for i in range(30, len(bars)):
        if None in (macd[i], macd[i - 1], sig[i], sig[i - 1], vol[i], adx[i], plus[i], minus[i]):
            continue
        if adx[i] < 25:
            continue
        if macd[i - 1] <= sig[i - 1] and macd[i] > sig[i] and direction[i] == -1 and plus[i] > minus[i]:
            out[i] = (1, closes[i] - 1.2 * vol[i])
        elif macd[i - 1] >= sig[i - 1] and macd[i] < sig[i] and direction[i] == 1 and minus[i] > plus[i]:
            out[i] = (-1, closes[i] + 1.2 * vol[i])
    return out


def simulate(bars, series, spread, unit, vmin, vmax, vstep, start, end, risk, rr, hours) -> dict:
    cash = wk.START_CASH
    peak = cash
    max_dd = 0.0
    pos = None
    pending = None
    trades = 0
    winners = 0
    losses_in_row = 0
    quiet_until = -1
    for i, bar in enumerate(bars):
        if bar.t < start:
            continue
        if bar.t > end:
            if pos is not None:
                if pos["side"] == 1:
                    pnl = (bar.open - pos["net"]) * unit * pos["vol"]
                else:
                    pnl = (pos["net"] - (bar.open + spread)) * unit * pos["vol"]
                cash += pnl
                trades += 1
                winners += int(pnl > 0)
                pos = None
            break
        if pending is not None and pos is None and i > quiet_until:
            side, stop_line = pending
            raw = bar.open
            if side == 1:
                net = raw + spread
                stop = stop_line
                risk_px = net - stop
                tp = net + rr * risk_px
            else:
                net = raw
                stop = stop_line + spread
                risk_px = stop - net
                tp = net - spread - rr * risk_px
            if risk_px > spread and unit > 0 and cash > 0:
                volume = eng.floor_volume(cash * risk / (risk_px * unit), vmin, vmax, vstep)
                if volume is not None:
                    pos = {"side": side, "net": net, "stop": stop, "tp": tp, "vol": volume, "i": i}
        pending = None
        if pos is not None and i > pos["i"]:
            side = pos["side"]
            if side == 1:
                stop_hit = bar.low <= pos["stop"]
                tp_hit = bar.high >= pos["tp"]
            else:
                stop_hit = bar.high >= pos["stop"] - spread
                tp_hit = bar.low <= pos["tp"]
            if stop_hit or tp_hit or bar.t >= end:
                if side == 1:
                    if stop_hit:
                        raw_exit = bar.open if bar.open < pos["stop"] else pos["stop"]
                    elif tp_hit:
                        raw_exit = pos["tp"]
                    else:
                        raw_exit = bar.close
                    pnl = (raw_exit - pos["net"]) * unit * pos["vol"]
                else:
                    if stop_hit:
                        level = pos["stop"] - spread
                        raw_exit = bar.open if bar.open > level else level
                    elif tp_hit:
                        raw_exit = pos["tp"]
                    else:
                        raw_exit = bar.close
                    pnl = (pos["net"] - (raw_exit + spread)) * unit * pos["vol"]
                cash += pnl
                trades += 1
                if pnl > 0:
                    winners += 1
                    losses_in_row = 0
                else:
                    losses_in_row += 1
                    if losses_in_row >= 2:
                        quiet_until = i + 2
                        losses_in_row = 0
                pos = None
        equity = cash
        if pos is not None:
            if pos["side"] == 1:
                equity = cash + (bar.close - pos["net"]) * pos["vol"] * unit
            else:
                equity = cash + (pos["net"] - (bar.close + spread)) * pos["vol"] * unit
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        hour = datetime.fromtimestamp(bar.t, timezone.utc).hour
        hour_ok = hours is None or hours[0] <= hour < hours[1]
        if pos is None and hour_ok and i < len(series) and series[i] is not None and bar.t < end and i > quiet_until:
            pending = series[i]
    return {
        "friday": round(cash, 2),
        "hit": cash >= wk.TARGET,
        "trades": trades,
        "winners": winners,
        "dd": round(max_dd, 2),
    }


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=140)
    cal = wk.weeks_ending(anchor[-1].t, wk.WEEKS)
    report = {"modes": {}, "weeks": [label for _s, _e, label in cal]}
    loaded = {}
    for symbol in SYMBOLS:
        try:
            resolved, bars = eng.fetch_bars(symbol, "15m", offset, lookback_days=140)
            loaded[symbol] = (resolved, bars, eng.symbol_costs(resolved), signals(bars))
        except SystemExit as exc:
            loaded[symbol] = exc
    for mode in MODES:
        symbols = {}
        for symbol in SYMBOLS:
            item = loaded[symbol]
            if isinstance(item, SystemExit):
                symbols[symbol] = {"error": str(item)}
                continue
            resolved, bars, costs, series = item
            detail = []
            for start, end, label in cal:
                detail.append({
                    "week": label,
                    **simulate(
                        bars, series, costs["spread_price"], costs["unit_per_lot_per_price"],
                        costs["volume_min"], costs["volume_max"], costs["volume_step"],
                        start, end, mode["risk"], mode["rr"], mode["hours"],
                    ),
                })
            fridays = [row["friday"] for row in detail]
            symbols[symbol] = {
                "spread": costs["spread_price"],
                "hits": sum(1 for row in detail if row["hit"]),
                "min_friday": min(fridays),
                "sum_pnl": round(sum(v - wk.START_CASH for v in fridays), 2),
                "detail": detail,
            }
        passed = [s for s, body in symbols.items() if body.get("hits") == wk.WEEKS]
        report["modes"][mode["name"]] = {"passed_all_8": passed, "symbols": symbols}
        print(mode["name"], "8/8:", passed or "yok", flush=True)
        for symbol, body in symbols.items():
            if "hits" not in body:
                print(" ", symbol, body.get("error"), flush=True)
                continue
            print(f"  {symbol:8} {body['hits']}/8 min={body['min_friday']:.0f} pnl={body['sum_pnl']:.0f}", flush=True)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hafta_cift_15m.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed": {k: v["passed_all_8"] for k, v in report["modes"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
