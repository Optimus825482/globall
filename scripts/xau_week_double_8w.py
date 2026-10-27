#!/usr/bin/env python3
"""XAUUSD, 8 tam hafta. Her hafta Pazartesi 1000 USD, hedef Cuma >= 2000.

Gostergeler GOSTERGELER.HTML icinden hesaplanabilir olanlar:
HA Supertrend, Stochastic RSI, ADX/DI, EMA kesisimi, Bollinger, Donchian, ATR.
Zaman: 1, 3, 5, 15 dakika. Emir yok.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import stochrsi_hast_adx_60d as combo  # noqa: E402
import xau_m1_gunluk_60d as m1  # noqa: E402

START_CASH = 1000.0
TARGET = 2000.0
WEEKS = 8


def resample(bars: list[eng.Bar], sec: int) -> list[eng.Bar]:
    out: list[eng.Bar] = []
    key = None
    cur: eng.Bar | None = None
    for bar in bars:
        bucket = bar.t // sec * sec
        if bucket != key:
            if cur is not None:
                out.append(cur)
            key = bucket
            cur = eng.Bar(bucket, bar.open, bar.high, bar.low, bar.close)
        else:
            assert cur is not None
            cur = eng.Bar(bucket, cur.open, max(cur.high, bar.high), min(cur.low, bar.low), bar.close)
    if cur is not None:
        out.append(cur)
    return out


def weeks_ending(last_ts: int, count: int = WEEKS) -> list[tuple[int, int, str]]:
    day = datetime.fromtimestamp(last_ts, timezone.utc).date()
    while day.weekday() != 4:
        day -= timedelta(days=1)
    found = []
    for i in range(count):
        friday = day - timedelta(weeks=i)
        monday = friday - timedelta(days=4)
        start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
        end = datetime(friday.year, friday.month, friday.day, 21, 0, tzinfo=timezone.utc)
        found.append((int(start.timestamp()), int(end.timestamp()), f"{monday.isoformat()}"))
    return list(reversed(found))


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def atr(bars: list[eng.Bar], period: int = 14) -> list[float | None]:
    tr: list[float | None] = [None] * len(bars)
    for i in range(1, len(bars)):
        prev = bars[i - 1].close
        tr[i] = max(bars[i].high - bars[i].low, abs(bars[i].high - prev), abs(bars[i].low - prev))
    return eng.wilder_rma(tr, period)


def signals_stoch(bars: list[eng.Bar]) -> list[tuple[int, float] | None]:
    closes = [b.close for b in bars]
    st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    k, d = combo.stoch_rsi(closes)
    out: list[tuple[int, float] | None] = [None] * len(bars)
    for i in range(1, len(bars)):
        if k[i] is None or d[i] is None or k[i - 1] is None or d[i - 1] is None or st[i] is None:
            continue
        up = k[i - 1] <= d[i - 1] and k[i] > d[i] and k[i] < 10 and direction[i] == -1 and st[i] < bars[i].close
        dn = k[i - 1] >= d[i - 1] and k[i] < d[i] and k[i] > 90 and direction[i] == 1 and st[i] > bars[i].close
        if up:
            out[i] = (1, st[i])
        elif dn:
            out[i] = (-1, st[i])
    return out


def signals_ema(bars: list[eng.Bar]) -> list[tuple[int, float] | None]:
    closes = [b.close for b in bars]
    fast, slow = ema(closes, 9), ema(closes, 21)
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    vol = atr(bars, 14)
    out: list[tuple[int, float] | None] = [None] * len(bars)
    for i in range(1, len(bars)):
        if fast[i] is None or slow[i] is None or fast[i - 1] is None or slow[i - 1] is None or vol[i] is None:
            continue
        if fast[i - 1] <= slow[i - 1] and fast[i] > slow[i] and direction[i] == -1:
            out[i] = (1, bars[i].close - vol[i])
        elif fast[i - 1] >= slow[i - 1] and fast[i] < slow[i] and direction[i] == 1:
            out[i] = (-1, bars[i].close + vol[i])
    return out


def signals_bb(bars: list[eng.Bar], spread: float) -> list[tuple[int, float] | None]:
    closes = [b.close for b in bars]
    _p, _m, adx = eng.adx_dmi(bars, 14)
    vol = atr(bars, 14)
    out: list[tuple[int, float] | None] = [None] * len(bars)
    for i in range(20, len(bars)):
        if adx[i] is None or adx[i] > 20 or vol[i] is None:
            continue
        window = closes[i - 19:i + 1]
        mean = sum(window) / 20
        sd = (sum((x - mean) ** 2 for x in window) / 20) ** 0.5
        lower, upper = mean - 2 * sd, mean + 2 * sd
        room = abs(mean - bars[i].close)
        if room < max(0.4 * vol[i], spread * 6):
            continue
        if bars[i].low < lower and bars[i].close > lower and bars[i].close > bars[i].open:
            out[i] = (1, bars[i].close - 0.8 * vol[i])
        elif bars[i].high > upper and bars[i].close < upper and bars[i].close < bars[i].open:
            out[i] = (-1, bars[i].close + 0.8 * vol[i])
    return out


def signals_donchian(bars: list[eng.Bar]) -> list[tuple[int, float] | None]:
    plus, minus, adx = eng.adx_dmi(bars, 14)
    vol = atr(bars, 14)
    out: list[tuple[int, float] | None] = [None] * len(bars)
    for i in range(20, len(bars)):
        if adx[i] is None or adx[i] < 25 or vol[i] is None or plus[i] is None or minus[i] is None:
            continue
        hi = max(b.high for b in bars[i - 20:i])
        lo = min(b.low for b in bars[i - 20:i])
        if bars[i].close > hi and plus[i] > minus[i]:
            out[i] = (1, bars[i].close - 1.5 * vol[i])
        elif bars[i].close < lo and minus[i] > plus[i]:
            out[i] = (-1, bars[i].close + 1.5 * vol[i])
    return out


def signals_atr_trend(bars: list[eng.Bar]) -> list[tuple[int, float] | None]:
    """HA-ST yonunde, ATR ortalamanin ustundeyken kirilim. Stop 1.5 ATR."""
    closes = [b.close for b in bars]
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    vol = atr(bars, 14)
    out: list[tuple[int, float] | None] = [None] * len(bars)
    for i in range(30, len(bars)):
        if vol[i] is None or direction[i] == 0:
            continue
        window = [v for v in vol[i - 20:i] if v is not None]
        if len(window) < 20 or vol[i] < (sum(window) / len(window)) * 1.15:
            continue
        if direction[i] == -1 and closes[i] > max(b.high for b in bars[i - 5:i]):
            out[i] = (1, closes[i] - 1.5 * vol[i])
        elif direction[i] == 1 and closes[i] < min(b.low for b in bars[i - 5:i]):
            out[i] = (-1, closes[i] + 1.5 * vol[i])
    return out


def signals_adx_pull(bars: list[eng.Bar]) -> list[tuple[int, float] | None]:
    """ADX 25+, DI ve HA-ST ayni yon, EMA21 geri cekilme. Stop 1 ATR, mantik genis hedef degil sabit stop."""
    closes = [b.close for b in bars]
    trend = ema(closes, 21)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    vol = atr(bars, 14)
    out: list[tuple[int, float] | None] = [None] * len(bars)
    for i in range(30, len(bars)):
        if None in (trend[i], adx[i], plus[i], minus[i], vol[i]) or adx[i] < 25:
            continue
        if direction[i] == -1 and plus[i] > minus[i] and bars[i].low <= trend[i] and bars[i].close > trend[i]:
            out[i] = (1, closes[i] - vol[i])
        elif direction[i] == 1 and minus[i] > plus[i] and bars[i].high >= trend[i] and bars[i].close < trend[i]:
            out[i] = (-1, closes[i] + vol[i])
    return out


def signals_rsi_st(bars: list[eng.Bar]) -> list[tuple[int, float] | None]:
    closes = [b.close for b in bars]
    rsi = eng.rsi_wilder(closes, 14)
    _st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    vol = atr(bars, 14)
    out: list[tuple[int, float] | None] = [None] * len(bars)
    for i in range(20, len(bars)):
        if rsi[i] is None or rsi[i - 1] is None or vol[i] is None:
            continue
        if rsi[i - 1] < 30 <= rsi[i] and direction[i] == -1:
            out[i] = (1, closes[i] - 1.2 * vol[i])
        elif rsi[i - 1] > 70 >= rsi[i] and direction[i] == 1:
            out[i] = (-1, closes[i] + 1.2 * vol[i])
    return out


def signals_macd_st(bars: list[eng.Bar]) -> list[tuple[int, float] | None]:
    closes = [b.close for b in bars]
    fast, slow = ema(closes, 12), ema(closes, 26)
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
    vol = atr(bars, 14)
    out: list[tuple[int, float] | None] = [None] * len(bars)
    for i in range(30, len(bars)):
        if None in (macd[i], macd[i - 1], sig[i], sig[i - 1], vol[i]):
            continue
        if macd[i - 1] <= sig[i - 1] and macd[i] > sig[i] and direction[i] == -1:
            out[i] = (1, closes[i] - 1.2 * vol[i])
        elif macd[i - 1] >= sig[i - 1] and macd[i] < sig[i] and direction[i] == 1:
            out[i] = (-1, closes[i] + 1.2 * vol[i])
    return out


def signals_keltner(bars: list[eng.Bar]) -> list[tuple[int, float] | None]:
    closes = [b.close for b in bars]
    mid = ema(closes, 20)
    vol = atr(bars, 14)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    out: list[tuple[int, float] | None] = [None] * len(bars)
    for i in range(30, len(bars)):
        if None in (mid[i], vol[i], adx[i], plus[i], minus[i]) or adx[i] < 22:
            continue
        if closes[i] > mid[i] + 1.5 * vol[i] and plus[i] > minus[i]:
            out[i] = (1, mid[i])
        elif closes[i] < mid[i] - 1.5 * vol[i] and minus[i] > plus[i]:
            out[i] = (-1, mid[i])
    return out


def simulate(
    bars: list[eng.Bar],
    signals: list[tuple[int, float] | None],
    spread: float,
    unit: float,
    vmin: float,
    vmax: float,
    vstep: float,
    start: int,
    end: int,
    risk: float,
) -> dict:
    cash = START_CASH
    peak = cash
    max_dd = 0.0
    pos = None
    pending = None
    trades = 0
    winners = 0
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
                if pnl > 0:
                    winners += 1
                pos = None
            break
        if pending is not None and pos is None:
            side, stop_line = pending
            raw = bar.open
            if side == 1:
                net = raw + spread
                stop = stop_line
                risk_px = net - stop
            else:
                net = raw
                stop = stop_line + spread
                risk_px = stop - net
            if risk_px > spread and unit > 0 and cash > 0:
                volume = eng.floor_volume(cash * risk / (risk_px * unit), vmin, vmax, vstep)
                if volume is not None:
                    pos = {"side": side, "net": net, "stop": stop, "vol": volume, "i": i}
        pending = None
        if pos is not None and i > pos["i"]:
            side = pos["side"]
            hit = (side == 1 and bar.low <= pos["stop"]) or (side == -1 and bar.high >= pos["stop"] - spread)
            if hit or bar.t >= end:
                if side == 1:
                    raw_exit = bar.open if hit and bar.open < pos["stop"] else (pos["stop"] if hit else bar.close)
                    pnl = (raw_exit - pos["net"]) * unit * pos["vol"]
                else:
                    level = pos["stop"] - spread
                    raw_exit = bar.open if hit and bar.open > level else (level if hit else bar.close)
                    pnl = (pos["net"] - (raw_exit + spread)) * unit * pos["vol"]
                cash += pnl
                trades += 1
                if pnl > 0:
                    winners += 1
                pos = None
        if pos is not None:
            unreal = (bar.close - pos["net"]) * pos["vol"] * unit if pos["side"] == 1 else (pos["net"] - (bar.close + spread)) * pos["vol"] * unit
            equity = cash + unreal
        else:
            equity = cash
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if pos is None and i < len(signals) and signals[i] is not None and bar.t < end:
            pending = signals[i]
    return {
        "friday": round(cash, 2),
        "hit": cash >= TARGET,
        "trades": trades,
        "winners": winners,
        "dd": round(max_dd, 2),
    }


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _resolved, m1_bars = m1.fetch_m1("XAUUSD", offset)
    costs = eng.symbol_costs(_resolved)
    frames = {
        "1m": m1_bars,
        "3m": resample(m1_bars, 180),
        "5m": resample(m1_bars, 300),
        "15m": resample(m1_bars, 900),
    }
    cal = weeks_ending(m1_bars[-1].t, WEEKS)
    builders = {
        "stoch10_90_hast": signals_stoch,
        "ema9_21_hast": signals_ema,
        "bb_yatay": lambda b: signals_bb(b, costs["spread_price"]),
        "donchian_adx": signals_donchian,
        "atr_kirilim": signals_atr_trend,
        "adx_geri_cekilme": signals_adx_pull,
        "rsi_hast": signals_rsi_st,
        "macd_hast": signals_macd_st,
        "keltner_adx": signals_keltner,
    }
    report = {
        "symbol": "XAUUSD",
        "weeks": [label for _s, _e, label in cal],
        "start_cash": START_CASH,
        "target": TARGET,
        "spread": costs["spread_price"],
        "cells": {},
    }
    for tf, bars in frames.items():
        cache = {name: fn(bars) for name, fn in builders.items()}
        for name, series in cache.items():
            for risk in (0.02, 0.05):
                key = f"{tf}|{name}|risk{int(risk * 100)}"
                week_rows = []
                for start, end, label in cal:
                    week_rows.append({"week": label, **simulate(
                        bars, series, costs["spread_price"], costs["unit_per_lot_per_price"],
                        costs["volume_min"], costs["volume_max"], costs["volume_step"],
                        start, end, risk,
                    )})
                hits = sum(1 for row in week_rows if row["hit"])
                report["cells"][key] = {
                    "hits": hits,
                    "weeks": WEEKS,
                    "min_friday": min(row["friday"] for row in week_rows),
                    "max_friday": max(row["friday"] for row in week_rows),
                    "detail": week_rows,
                }
    passed = [key for key, cell in report["cells"].items() if cell["hits"] == WEEKS]
    report["passed_all_8"] = passed
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xau_week_double_8w.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    ranked = sorted(
        report["cells"].items(),
        key=lambda item: (item[1]["hits"], item[1]["min_friday"]),
        reverse=True,
    )
    report["top"] = [
        {"name": key, "hits": cell["hits"], "min": cell["min_friday"], "max": cell["max_friday"],
         "train_hits": sum(1 for row in cell["detail"][:4] if row["hit"]),
         "test_hits": sum(1 for row in cell["detail"][4:] if row["hit"]),
         "test_min": min(row["friday"] for row in cell["detail"][4:]),
         "fridays": [row["friday"] for row in cell["detail"]]}
        for key, cell in ranked[:8]
    ]
    brief = {row["name"]: {"hits": row["hits"], "min": row["min"], "train": row["train_hits"], "test": row["test_hits"], "test_min": row["test_min"]} for row in report["top"]}
    print(json.dumps({"file": path, "passed_all_8": passed, "weeks": report["weeks"], "top": brief}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
