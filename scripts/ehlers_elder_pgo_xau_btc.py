#!/usr/bin/env python3
"""Ehlers anlik trend, Elder itki ve PGO. Altin ve BTC.

Formuller kosudan once kilitlendi.

Ehlers: TradingView everget / cheatcountry Pine. Kaynak hl2, alpha 0.07.
Trigger = 2*ITrend - ITrend[2]. Trigger cizginin ustune cikinca long,
altina inince short.

Elder: StockCharts. EMA(13) egimi ve MACD(12,26,9) histogram egimi.
Ikisi de yukari yesil, ikisi de asagi kirmizi, ayrilik mavi.
Yesilde long, kirmizida short, mavide flat.

PGO: LuxAlgo / Johnson. (kapanis - SMA(89)) / EMA(true range, 89).
Kirilim: +3 ustu long, -3 alti short.
Donus: -3 ustune kesiste long, +3 altina kesiste short, sifirda cikis.

Stop 1.2 ATR, kalkmaz. Risk %5. Her hafta 1000 USD. Cikis bir sonraki acilis.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = ("XAUUSD", "BTCUSD")
TFS = ("15m", "1h")
RISK = 0.05
PGO_LEN = 89
PGO_BAND = 3.0


def ema_valid(values: list[float | None], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    buf: list[float] = []
    prev = None
    k = 2 / (period + 1)
    for i, value in enumerate(values):
        if value is None:
            continue
        if prev is None:
            buf.append(value)
            if len(buf) == period:
                prev = sum(buf) / period
                out[i] = prev
            continue
        prev = value * k + prev * (1 - k)
        out[i] = prev
    return out


def ehlers_state(bars: list[eng.Bar], alpha: float = 0.07) -> list[int]:
    src = [(bar.high + bar.low) / 2.0 for bar in bars]
    it: list[float | None] = [None] * len(src)
    for i in range(len(src)):
        if i < 2:
            continue
        if i < 7:
            it[i] = (src[i] + 2.0 * src[i - 1] + src[i - 2]) / 4.0
            continue
        a2 = alpha * alpha
        it[i] = (
            (alpha - a2 / 4.0) * src[i]
            + (0.5 * a2) * src[i - 1]
            - (alpha - 0.75 * a2) * src[i - 2]
            + 2.0 * (1.0 - alpha) * it[i - 1]
            - ((1.0 - alpha) ** 2) * it[i - 2]
        )
    state = [0] * len(src)
    for i in range(2, len(src)):
        if it[i] is None or it[i - 2] is None:
            continue
        trigger = 2.0 * it[i] - it[i - 2]
        if trigger > it[i]:
            state[i] = 1
        elif trigger < it[i]:
            state[i] = -1
    return state


def macd_hist(closes: list[float]) -> list[float | None]:
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
    return [None if a is None or b is None else a - b for a, b in zip(macd, sig)]


def elder_state(bars: list[eng.Bar]) -> list[int]:
    closes = [bar.close for bar in bars]
    ema13 = wk.ema(closes, 13)
    hist = macd_hist(closes)
    state = [0] * len(bars)
    for i in range(1, len(bars)):
        if None in (ema13[i], ema13[i - 1], hist[i], hist[i - 1]):
            continue
        up = ema13[i] > ema13[i - 1] and hist[i] > hist[i - 1]
        down = ema13[i] < ema13[i - 1] and hist[i] < hist[i - 1]
        if up:
            state[i] = 1
        elif down:
            state[i] = -1
    return state


def pgo_line(bars: list[eng.Bar], length: int = PGO_LEN) -> list[float | None]:
    closes = [bar.close for bar in bars]
    sma: list[float | None] = [None] * len(bars)
    for i in range(length - 1, len(bars)):
        sma[i] = sum(closes[i - length + 1:i + 1]) / length
    tr: list[float | None] = [None] * len(bars)
    for i in range(1, len(bars)):
        prev = bars[i - 1].close
        tr[i] = max(bars[i].high - bars[i].low, abs(bars[i].high - prev), abs(bars[i].low - prev))
    smooth = ema_valid(tr, length)
    out: list[float | None] = [None] * len(bars)
    for i in range(len(bars)):
        if sma[i] is None or smooth[i] is None or smooth[i] == 0:
            continue
        out[i] = (closes[i] - sma[i]) / smooth[i]
    return out


def pgo_break_state(line: list[float | None]) -> list[int]:
    state = [0] * len(line)
    for i, value in enumerate(line):
        if value is None:
            continue
        if value > PGO_BAND:
            state[i] = 1
        elif value < -PGO_BAND:
            state[i] = -1
    return state


def pgo_revert_state(line: list[float | None]) -> list[int]:
    state = [0] * len(line)
    side = 0
    for i in range(1, len(line)):
        prev, cur = line[i - 1], line[i]
        if prev is None or cur is None:
            state[i] = side
            continue
        if prev <= -PGO_BAND < cur:
            side = 1
        elif prev >= PGO_BAND > cur:
            side = -1
        elif side == 1 and prev < 0.0 <= cur:
            side = 0
        elif side == -1 and prev > 0.0 >= cur:
            side = 0
        state[i] = side
    return state


def simulate(bars, state, spread, unit, vmin, vmax, vstep, start, end) -> dict:
    vol = wk.atr(bars, 14)
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
                pnl = (bar.open - pos["net"]) * unit * pos["vol"] if pos["side"] == 1 else (pos["net"] - (bar.open + spread)) * unit * pos["vol"]
                cash += pnl
                trades += 1
                winners += int(pnl > 0)
                pos = None
            break
        if pending is not None:
            if pos is not None and pos["side"] != pending:
                pnl = (bar.open - pos["net"]) * unit * pos["vol"] if pos["side"] == 1 else (pos["net"] - (bar.open + spread)) * unit * pos["vol"]
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
            if pos is None and pending in (1, -1) and i > quiet_until:
                raw = bar.open
                atr = vol[i - 1] if i > 0 else None
                if atr is not None and atr > 0:
                    if pending == 1:
                        net = raw + spread
                        stop = bars[i - 1].close - 1.2 * atr
                        risk_px = net - stop
                    else:
                        net = raw
                        stop = bars[i - 1].close + 1.2 * atr + spread
                        risk_px = stop - net
                    if risk_px > spread and unit > 0 and cash > 0:
                        volume = eng.floor_volume(cash * RISK / (risk_px * unit), vmin, vmax, vstep)
                        if volume is not None:
                            pos = {"side": pending, "net": net, "stop": stop, "vol": volume, "i": i}
        pending = None
        if pos is not None and i > pos["i"]:
            side = pos["side"]
            hit = (side == 1 and bar.low <= pos["stop"]) or (side == -1 and bar.high >= pos["stop"] - spread)
            if hit:
                if side == 1:
                    raw_exit = bar.open if bar.open < pos["stop"] else pos["stop"]
                    pnl = (raw_exit - pos["net"]) * unit * pos["vol"]
                else:
                    level = pos["stop"] - spread
                    raw_exit = bar.open if bar.open > level else level
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
            unreal = (bar.close - pos["net"]) * pos["vol"] * unit if pos["side"] == 1 else (pos["net"] - (bar.close + spread)) * pos["vol"] * unit
            equity = cash + unreal
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if i > quiet_until and i + 1 < len(bars) and bars[i + 1].t <= end:
            want = state[i]
            if pos is None:
                if want in (1, -1):
                    pending = want
            elif want != pos["side"]:
                pending = want if want in (1, -1) else 0
    return {
        "friday": round(cash, 2),
        "hit": cash >= wk.TARGET,
        "trades": trades,
        "winners": winners,
        "dd": round(max_dd, 2),
    }


def build_state(name: str, bars: list[eng.Bar]) -> list[int]:
    if name == "ehlers":
        return ehlers_state(bars)
    if name == "elder":
        return elder_state(bars)
    line = pgo_line(bars)
    if name == "pgo_kirilim":
        return pgo_break_state(line)
    return pgo_revert_state(line)


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=140)
    cal = wk.weeks_ending(anchor[-1].t, wk.WEEKS)
    names = ("ehlers", "elder", "pgo_kirilim", "pgo_donus")
    report = {"weeks": [label for _s, _e, label in cal], "symbols": {}}
    for symbol in SYMBOLS:
        report["symbols"][symbol] = {}
        for tf in TFS:
            resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=140)
            costs = eng.symbol_costs(resolved)
            for name in names:
                state = build_state(name, bars)
                detail = []
                for start, end, label in cal:
                    detail.append({
                        "week": label,
                        **simulate(
                            bars, state, costs["spread_price"], costs["unit_per_lot_per_price"],
                            costs["volume_min"], costs["volume_max"], costs["volume_step"],
                            start, end,
                        ),
                    })
                fridays = [row["friday"] for row in detail]
                key = f"{tf}|{name}"
                cell = {
                    "hits": sum(1 for row in detail if row["hit"]),
                    "min_friday": min(fridays),
                    "sum_pnl": round(sum(value - wk.START_CASH for value in fridays), 2),
                    "detail": detail,
                }
                report["symbols"][symbol][key] = cell
                print(
                    f"{symbol:6} {key:16} {cell['hits']}/8 min={cell['min_friday']:.0f} pnl={cell['sum_pnl']:.0f}",
                    flush=True,
                )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ehlers_elder_pgo_xau_btc.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path}, ensure_ascii=False))


if __name__ == "__main__":
    main()
