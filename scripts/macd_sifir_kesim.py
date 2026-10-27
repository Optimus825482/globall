#!/usr/bin/env python3
"""MACD sifir cizgisi kurali. Altin, BTC ve doviz.

Al: MACD, sinyal cizgisini yukari keser ve kesim sifirin altindadir.
Sat: MACD, sinyal cizgisini asagi keser ve kesim sifirin ustundedir.
MACD 12, 26, 9. Giris sonraki acilis. Stop 1.2 ATR.
Ters sinyalde de cikis. Ayni mumda stop once.
Kagit 10000 USD, risk %1. Spread anlik.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import m1_rejim_sweep_60d as rej  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = (
    "XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY",
    "USDCAD", "EURCAD", "GBPCAD", "EURNZD", "GBPNZD", "NZDUSD",
)
WINDOWS = (7, 14, 30, 60)
START_CASH = 10000.0
RISK = 0.01


def macd_hist(closes: list[float]) -> tuple[list[float | None], list[float | None]]:
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
    return macd, sig


def signals_of(bars) -> list[int]:
    closes = [bar.close for bar in bars]
    macd, sig = macd_hist(closes)
    out = [0] * len(bars)
    for i in range(1, len(bars)):
        if None in (macd[i], macd[i - 1], sig[i], sig[i - 1]):
            continue
        if macd[i - 1] <= sig[i - 1] and macd[i] > sig[i] and macd[i] < 0 and sig[i] < 0:
            out[i] = 1
        elif macd[i - 1] >= sig[i - 1] and macd[i] < sig[i] and macd[i] > 0 and sig[i] > 0:
            out[i] = -1
    return out


def simulate(bars, sides, vol, spread, unit_value, vmin, vmax, vstep, start: int, end: int) -> dict:
    cash = START_CASH
    peak = cash
    max_dd = 0.0
    pos = None
    pending = None
    trades = 0
    winners = 0
    buys = 0
    sells = 0
    gross_win = 0.0
    gross_loss = 0.0
    for i, bar in enumerate(bars):
        if bar.t > end and pos is not None:
            pnl = (bar.open - pos["net"]) * unit_value * pos["vol"] if pos["side"] == 1 else (pos["net"] - (bar.open + spread)) * unit_value * pos["vol"]
            cash += pnl
            trades += 1
            winners += int(pnl > 0)
            if pnl > 0:
                gross_win += pnl
            else:
                gross_loss += -pnl
            pos = None
            break
        if bar.t > end:
            break
        if bar.t < start:
            continue
        if pos is None and pending is not None:
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
            if risk_px > spread and cash > 0 and unit_value > 0:
                volume = eng.floor_volume(cash * RISK / (risk_px * unit_value), vmin, vmax, vstep)
                if volume is not None:
                    pos = {"side": side, "net": net, "stop": stop, "vol": volume, "i": i}
                    if side == 1:
                        buys += 1
                    else:
                        sells += 1
        pending = None
        if pos is not None and i > pos["i"]:
            side = pos["side"]
            stop_hit = (side == 1 and bar.low <= pos["stop"]) or (side == -1 and bar.high >= pos["stop"] - spread)
            if stop_hit:
                if side == 1:
                    raw_exit = bar.open if bar.open < pos["stop"] else pos["stop"]
                    pnl = (raw_exit - pos["net"]) * unit_value * pos["vol"]
                else:
                    level = pos["stop"] - spread
                    raw_exit = bar.open if bar.open > level else level
                    pnl = (pos["net"] - (raw_exit + spread)) * unit_value * pos["vol"]
                cash += pnl
                trades += 1
                winners += int(pnl > 0)
                if pnl > 0:
                    gross_win += pnl
                else:
                    gross_loss += -pnl
                pos = None
        if pos is not None:
            unreal = (bar.close - pos["net"]) * pos["vol"] * unit_value if pos["side"] == 1 else (pos["net"] - (bar.close + spread)) * pos["vol"] * unit_value
            equity = cash + unreal
        else:
            equity = cash
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if pos is None and sides[i] in (1, -1) and vol[i] is not None and vol[i] > 0 and bar.t < end:
            if sides[i] == 1:
                pending = (1, bar.close - 1.2 * vol[i])
            else:
                pending = (-1, bar.close + 1.2 * vol[i])
        elif pos is not None and sides[i] == -pos["side"]:
            if pos["side"] == 1:
                pnl = (bar.close - pos["net"]) * unit_value * pos["vol"]
            else:
                pnl = (pos["net"] - (bar.close + spread)) * unit_value * pos["vol"]
            cash += pnl
            trades += 1
            winners += int(pnl > 0)
            if pnl > 0:
                gross_win += pnl
            else:
                gross_loss += -pnl
            pos = None
            if vol[i] is not None and vol[i] > 0 and bar.t < end:
                if sides[i] == 1:
                    pending = (1, bar.close - 1.2 * vol[i])
                else:
                    pending = (-1, bar.close + 1.2 * vol[i])
    pf = None if trades == 0 else ("inf" if gross_loss == 0 and gross_win > 0 else (round(gross_win / gross_loss, 3) if gross_loss else None))
    return {
        "trades": trades,
        "winners": winners,
        "buys": buys,
        "sells": sells,
        "net": round(cash - START_CASH, 2),
        "pf": pf,
        "dd": round(max_dd, 2),
        "win_rate": round(winners / trades, 3) if trades else None,
    }


def load_frames(symbol: str, offset: int) -> dict:
    frames = {}
    resolved, m1 = rej.fetch(symbol, offset)
    m1_eng = [eng.Bar(bar.t, bar.open, bar.high, bar.low, bar.close) for bar in m1]
    frames["1m"] = m1_eng
    frames["3m"] = wk.resample(m1_eng, 180)
    for tf, sec in (("5m", 300), ("15m", 900)):
        try:
            _name, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=80)
            frames[tf] = bars
        except SystemExit:
            frames[tf] = wk.resample(m1_eng, sec)
    return resolved, frames


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    last = anchor[-1].t
    report = {"rule": "MACD 12/26/9 sifir altinda yukari kesim=al, sifir ustunde asagi kesim=sat", "symbols": {}}
    for symbol in SYMBOLS:
        try:
            resolved, frames = load_frames(symbol, offset)
            costs = eng.symbol_costs(resolved)
        except SystemExit as exc:
            print(symbol, exc, flush=True)
            continue
        report["symbols"][symbol] = {"resolved": resolved, "spread": costs["spread_price"], "frames": {}}
        for tf, bars in frames.items():
            if len(bars) < 40:
                continue
            sides = signals_of(bars)
            vol = wk.atr(bars, 14)
            cells = {}
            for days in WINDOWS:
                start = last - days * 86400
                if bars[0].t > start:
                    cells[str(days)] = {"note": "veri_kisiti", "first": datetime.fromtimestamp(bars[0].t, timezone.utc).strftime("%Y-%m-%d %H:%M")}
                    continue
                cells[str(days)] = simulate(
                    bars, sides, vol, costs["spread_price"], costs["unit_per_lot_per_price"],
                    costs["volume_min"], costs["volume_max"], costs["volume_step"], start, last,
                )
            report["symbols"][symbol]["frames"][tf] = cells
            row7 = cells.get("7", {})
            print(
                f"{symbol:8} {tf:4} 7g islem={row7.get('trades')} net={row7.get('net')} pf={row7.get('pf')} oran={row7.get('win_rate')}",
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macd_sifir_kesim.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
