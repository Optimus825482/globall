#!/usr/bin/env python3
"""XAUUSD 1 dakika, 60 gun. Gunde 15 karli kapanis hedefi.

Kurallar sonuc gorulmeden kilitlendi. 15dk Supertrend ailesi degil.
Emir gonderilmez. Paper 10.000 USD, islem basina risk %1.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402

SESSION = (7, 20)
WINDOW_SEC = 60 * 86400


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def atr(bars: list[eng.Bar], period: int = 14) -> list[float | None]:
    tr: list[float | None] = [None] * len(bars)
    for i in range(1, len(bars)):
        prev = bars[i - 1].close
        tr[i] = max(bars[i].high - bars[i].low, abs(bars[i].high - prev), abs(bars[i].low - prev))
    return eng.wilder_rma(tr, period)


def bollinger(closes: list[float], period: int = 20, mult: float = 2.0):
    n = len(closes)
    mid: list[float | None] = [None] * n
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        mean = sum(window) / period
        var = sum((value - mean) ** 2 for value in window) / period
        sd = var ** 0.5
        mid[i] = mean
        upper[i] = mean + mult * sd
        lower[i] = mean - mult * sd
    return mid, upper, lower


def _signals_burst(bars, spread: float, fast: bool) -> list[int]:
    closes = [bar.close for bar in bars]
    ha = eng.heikin_ashi(bars)
    trend = ema(closes, 21)
    rsi = eng.rsi_wilder(closes, 7)
    vol = atr(bars, 14)
    gate = 4.0 if fast else 8.0
    rsi_long = 52.0 if fast else 55.0
    rsi_short = 48.0 if fast else 45.0
    out = [0] * len(bars)
    for i in range(len(bars)):
        if not eng.hour_in_span(bars[i].t, SESSION):
            continue
        if trend[i] is None or rsi[i] is None or vol[i] is None:
            continue
        if vol[i] < spread * gate:
            continue
        bull = ha[i].close > ha[i].open and closes[i] > trend[i] and rsi_long < rsi[i] < 80
        bear = ha[i].close < ha[i].open and closes[i] < trend[i] and 20 < rsi[i] < rsi_short
        if bull:
            out[i] = 1
        elif bear:
            out[i] = -1
    return out


def _signals_revert(bars, spread: float) -> list[int]:
    closes = [bar.close for bar in bars]
    mid, upper, lower = bollinger(closes, 20, 2.0)
    vol = atr(bars, 14)
    out = [0] * len(bars)
    for i in range(len(bars)):
        if not eng.hour_in_span(bars[i].t, SESSION):
            continue
        if lower[i] is None or upper[i] is None or vol[i] is None or vol[i] < spread * 4:
            continue
        if bars[i].low < lower[i] and bars[i].close > lower[i] and bars[i].close > bars[i].open:
            out[i] = 1
        elif bars[i].high > upper[i] and bars[i].close < upper[i] and bars[i].close < bars[i].open:
            out[i] = -1
    return out


def run_scalp(
    bars: list[eng.Bar],
    signals: list[int],
    *,
    spread: float,
    unit: float,
    vmin: float,
    vmax: float,
    vstep: float,
    window_start: int,
    sl_mult: float,
    tp_mult: float,
    time_stop: int,
    cooldown: int,
    vol: list[float | None],
) -> dict:
    cash = eng.PAPER_BALANCE
    peak = cash
    max_dd = 0.0
    pos = None
    pending = 0
    pending_stop = 0.0
    pending_tp = 0.0
    cool_until = -1
    trades = []

    def mark(i: int) -> None:
        nonlocal peak, max_dd
        unreal = 0.0
        if pos is not None:
            px = bars[i].close
            if pos["side"] == 1:
                unreal = (px - pos["net_entry"]) * unit * pos["volume"]
            else:
                unreal = (pos["net_entry"] - (px + spread)) * unit * pos["volume"]
        equity = cash + unreal
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    def close(i: int, raw_exit: float, net_exit: float, reason: str) -> None:
        nonlocal pos, cash, cool_until
        gross = pos["side"] * (raw_exit - pos["raw_entry"]) * unit * pos["volume"]
        net = pos["side"] * (net_exit - pos["net_entry"]) * unit * pos["volume"]
        trades.append({
            "side": "BUY" if pos["side"] == 1 else "SELL",
            "entry_t": pos["entry_t"],
            "exit_t": bars[i].t,
            "net": net,
            "gross": gross,
            "reason": reason,
        })
        cash += net
        pos = None
        cool_until = i + cooldown

    n = len(bars)
    for i in range(n):
        in_window = bars[i].t >= window_start
        if in_window and pos is None and pending != 0:
            raw_entry = bars[i].open
            side = pending
            if side == 1:
                net_entry = raw_entry + spread
                risk_price = net_entry - pending_stop
                stop = pending_stop
                target = pending_tp
            else:
                net_entry = raw_entry
                stop = pending_stop + spread
                target = pending_tp - spread
                risk_price = stop - net_entry
            if risk_price > spread and unit > 0 and cash > 0:
                volume = eng.floor_volume(cash * eng.RISK_PCT / (risk_price * unit), vmin, vmax, vstep)
                if volume is not None:
                    pos = {
                        "side": side,
                        "raw_entry": raw_entry,
                        "net_entry": net_entry,
                        "stop": stop,
                        "target": target,
                        "volume": volume,
                        "entry_t": bars[i].t,
                        "entry_i": i,
                    }
        pending = 0

        if in_window and pos is not None:
            side = pos["side"]
            hit_stop = (side == 1 and bars[i].low <= pos["stop"]) or (side == -1 and bars[i].high >= pos["stop"] - spread)
            hit_tp = (side == 1 and bars[i].high >= pos["target"]) or (side == -1 and bars[i].low <= pos["target"])
            if hit_stop:
                if side == 1:
                    raw_exit = bars[i].open if bars[i].open < pos["stop"] else pos["stop"]
                    close(i, raw_exit, raw_exit, "stop")
                else:
                    raw_level = pos["stop"] - spread
                    raw_exit = bars[i].open if bars[i].open > raw_level else raw_level
                    close(i, raw_exit, raw_exit + spread, "stop")
            elif hit_tp:
                if side == 1:
                    raw_exit = bars[i].open if bars[i].open > pos["target"] else pos["target"]
                    close(i, raw_exit, raw_exit, "tp")
                else:
                    raw_level = pos["target"]
                    raw_exit = bars[i].open if bars[i].open < raw_level else raw_level
                    close(i, raw_exit, raw_exit + spread, "tp")
            elif i - pos["entry_i"] >= time_stop:
                if side == 1:
                    close(i, bars[i].close, bars[i].close, "time")
                else:
                    close(i, bars[i].close, bars[i].close + spread, "time")

        if in_window:
            mark(i)
        if i >= n - 1 or not in_window or pos is not None or i < cool_until:
            continue
        side = signals[i]
        if side == 0 or vol[i] is None:
            continue
        dist_sl = vol[i] * sl_mult
        dist_tp = vol[i] * tp_mult
        if side == 1:
            pending_stop = bars[i].close - dist_sl
            pending_tp = bars[i].close + dist_tp
        else:
            pending_stop = bars[i].close + dist_sl
            pending_tp = bars[i].close - dist_tp
        pending = side

    if pos is not None:
        last = n - 1
        if pos["side"] == 1:
            close(last, bars[last].close, bars[last].close, "window_end")
        else:
            close(last, bars[last].close, bars[last].close + spread, "window_end")

    winners_by_day: dict[str, int] = defaultdict(int)
    trades_by_day: dict[str, int] = defaultdict(int)
    for trade in trades:
        if datetime.fromtimestamp(trade["exit_t"], timezone.utc).weekday() >= 5:
            continue
        day = datetime.fromtimestamp(trade["exit_t"], timezone.utc).strftime("%Y-%m-%d")
        trades_by_day[day] += 1
        if trade["net"] > 0:
            winners_by_day[day] += 1
    weekdays = []
    seen = set()
    for bar in bars:
        if bar.t < window_start:
            continue
        day = datetime.fromtimestamp(bar.t, timezone.utc)
        if day.weekday() >= 5:
            continue
        key = day.strftime("%Y-%m-%d")
        if key not in seen:
            seen.add(key)
            weekdays.append(key)
    winner_counts = [winners_by_day[day] for day in weekdays]
    nets = [trade["net"] for trade in trades]
    wins = [value for value in nets if value > 0]
    losses = [value for value in nets if value < 0]
    gp, gl = sum(wins), abs(sum(losses))
    days_hit = sum(1 for value in winner_counts if value >= 15)
    return {
        "trades": len(trades),
        "winners": len(wins),
        "win_rate": round(len(wins) / len(trades), 3) if trades else None,
        "net": round(sum(nets), 2),
        "pf": None if not trades else ("inf" if gl == 0 and gp > 0 else (round(gp / gl, 3) if gl else None)),
        "dd": round(max_dd, 2),
        "expectancy": round(sum(nets) / len(trades), 2) if trades else None,
        "avg_winners_per_weekday": round(sum(winner_counts) / len(weekdays), 2) if weekdays else None,
        "max_winners_in_one_weekday": max(winner_counts) if winner_counts else 0,
        "weekdays": len(weekdays),
        "weekdays_with_15_winners": days_hit,
        "reasons": {
            "tp": sum(1 for trade in trades if trade["reason"] == "tp"),
            "stop": sum(1 for trade in trades if trade["reason"] == "stop"),
            "time": sum(1 for trade in trades if trade["reason"] == "time"),
        },
    }


def fetch_m1(app_symbol: str, offset: int, count: int = 99000) -> tuple[str, list[eng.Bar]]:
    resolved = eng.mt5_bridge.resolve_mt5_symbol(app_symbol)
    info = eng.mt5.symbol_info(resolved)
    if info is None:
        raise SystemExit(f"{app_symbol} terminalde yok")
    if not info.visible:
        eng.mt5.symbol_select(resolved, True)
    rates = eng.mt5.copy_rates_from_pos(resolved, eng.mt5.TIMEFRAME_M1, 0, count)
    if rates is None or len(rates) == 0:
        raise SystemExit(f"{resolved} 1m mum yok. last_error={eng.mt5.last_error()}")
    bars = [
        eng.Bar(int(row["time"]) - offset, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]))
        for row in rates
    ]
    bars.sort(key=lambda bar: bar.t)
    if bars and bars[-1].t + 60 > eng.time.time():
        bars = bars[:-1]
    return resolved, bars


def main() -> None:
    eng.self_check()
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _resolved, bars = fetch_m1("XAUUSD", offset)
    costs = eng.symbol_costs(_resolved)
    last_ts = bars[-1].t
    window_start = last_ts - WINDOW_SEC
    spread = costs["spread_price"]
    vol = atr(bars, 14)
    specs = {
        "burst": (_signals_burst(bars, spread, False), 0.9, 1.1, 12, 8),
        "burst_hizli": (_signals_burst(bars, spread, True), 0.55, 0.65, 6, 2),
        "bant_donus": (_signals_revert(bars, spread), 0.7, 0.8, 10, 3),
    }
    out = {
        "symbol": "XAUUSD",
        "timeframe": "1m",
        "session_utc": "07-20",
        "spread": spread,
        "spread_source": costs["spread_source"],
        "window_start_utc": datetime.fromtimestamp(window_start, timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "last_utc": datetime.fromtimestamp(last_ts, timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "calendar_days": round((last_ts - max(window_start, bars[0].t)) / 86400, 1),
        "target": "hafta ici gunde en az 15 karli kapanis",
        "strategies": {},
    }
    for name, (signals, sl, tp, hold, cool) in specs.items():
        out["strategies"][name] = run_scalp(
            bars, signals, spread=spread, unit=costs["unit_per_lot_per_price"],
            vmin=costs["volume_min"], vmax=costs["volume_max"], vstep=costs["volume_step"],
            window_start=window_start, sl_mult=sl, tp_mult=tp, time_stop=hold, cooldown=cool, vol=vol,
        )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xau_m1_gunluk_60d.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, **out}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
