#!/usr/bin/env python3
"""XAUUSD ve BTCUSD icin uc ayri 1dk ailesi. 60 gun ve son 20 gun ayri hesap.

Kabul: her sembolde, hem 60 gunde hem son 20 gunde,
hafta ici ortalama >= 15 kazanc, net > 0, kar faktoru >= 1.15.
Kurallar kosudan once kilitlendi. Emir yok.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402

WINDOW_60 = 60 * 86400
WINDOW_20 = 20 * 86400


class Bar:
    def __init__(self, t: int, o: float, h: float, l: float, c: float, v: float) -> None:
        self.t, self.open, self.high, self.low, self.close, self.v = t, o, h, l, c, v


def fetch(symbol: str, offset: int, count: int = 99000) -> tuple[str, list[Bar]]:
    resolved = eng.mt5_bridge.resolve_mt5_symbol(symbol)
    info = eng.mt5.symbol_info(resolved)
    if info is None:
        raise SystemExit(f"{symbol} yok")
    if not info.visible:
        eng.mt5.symbol_select(resolved, True)
    rates = eng.mt5.copy_rates_from_pos(resolved, eng.mt5.TIMEFRAME_M1, 0, count)
    if rates is None or len(rates) == 0:
        raise SystemExit(f"{resolved} 1m yok {eng.mt5.last_error()}")
    bars = [
        Bar(int(r["time"]) - offset, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r["tick_volume"]))
        for r in rates
    ]
    bars.sort(key=lambda b: b.t)
    if bars and bars[-1].t + 60 > eng.time.time():
        bars = bars[:-1]
    return resolved, bars


def to_engine(bars: list[Bar]) -> list[eng.Bar]:
    return [eng.Bar(b.t, b.open, b.high, b.low, b.close) for b in bars]


def resample_15(bars: list[Bar]) -> list[eng.Bar]:
    out: list[eng.Bar] = []
    key = None
    cur: eng.Bar | None = None
    for bar in bars:
        bucket = bar.t // 900 * 900
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


def map_closed(bars: list[Bar], htf: list[eng.Bar], values: list, htf_sec: int = 900) -> list:
    out = [None] * len(bars)
    j = 0
    for i, bar in enumerate(bars):
        while j + 1 < len(htf) and htf[j + 1].t + htf_sec <= bar.t:
            j += 1
        if j < len(htf) and htf[j].t + htf_sec <= bar.t:
            out[i] = values[j]
    return out


def session_ok(ts: int, symbol: str) -> bool:
    if symbol == "BTCUSD":
        return True
    return eng.hour_in_span(ts, (7, 20))


def build_signals(symbol: str, bars: list[Bar], spread: float) -> dict[str, list[tuple[int, float, float, float] | None]]:
    n = len(bars)
    closes = [b.close for b in bars]
    eng_bars = to_engine(bars)
    m15 = resample_15(bars)
    _pdi, _mdi, adx15 = eng.adx_dmi(m15, 14)
    htf = eng.htf_side(eng_bars, m15, 900)
    adx = map_closed(bars, m15, adx15)
    # Onceki kapanmis 15dk tepesi ve dibi
    prior_high = map_closed(bars, m15, [b.high for b in m15])
    prior_low = map_closed(bars, m15, [b.low for b in m15])
    ema21 = []
    k = 2 / 22
    prev = None
    sma = 0.0
    for i, px in enumerate(closes):
        if i < 20:
            sma += px
            ema21.append(None)
            continue
        if i == 20:
            prev = (sma + px) / 21
            ema21.append(prev)
            continue
        prev = px * k + prev * (1 - k)
        ema21.append(prev)
    vol_sma = [None] * n
    run = 0.0
    for i, bar in enumerate(bars):
        run += bar.v
        if i >= 20:
            run -= bars[i - 20].v
            vol_sma[i] = run / 20
    atr = [None] * n
    trs: list[float | None] = [None] * n
    for i in range(1, n):
        trs[i] = max(bars[i].high - bars[i].low, abs(bars[i].high - closes[i - 1]), abs(bars[i].low - closes[i - 1]))
    atr = eng.wilder_rma(trs, 14)
    ha = eng.heikin_ashi(eng_bars)
    mid, upper, lower = [], [], []
    for i in range(n):
        if i < 19:
            mid.append(None)
            upper.append(None)
            lower.append(None)
            continue
        window = closes[i - 19:i + 1]
        mean = sum(window) / 20
        var = sum((x - mean) ** 2 for x in window) / 20
        sd = var ** 0.5
        mid.append(mean)
        upper.append(mean + 2 * sd)
        lower.append(mean - 2 * sd)

    rejim: list[tuple[int, float, float, float] | None] = [None] * n
    sweep: list[tuple[int, float, float, float] | None] = [None] * n
    trend_be: list[tuple[int, float, float, float] | None] = [None] * n
    for i in range(21, n):
        if not session_ok(bars[i].t, symbol) or atr[i] is None or atr[i] <= 0:
            continue
        a = atr[i]
        side_htf = htf[i]
        adx_now = adx[i]
        # Rejim: trend geri cekilme, genis hedef, tik hacmi ortalamanin ustunde
        if (
            adx_now is not None and adx_now >= 25 and side_htf in (1, -1)
            and ema21[i] is not None and vol_sma[i] and bars[i].v > vol_sma[i]
            and a * 2.5 >= spread * 8
        ):
            if side_htf == 1 and bars[i - 1].close > ema21[i] and bars[i].low <= ema21[i] and bars[i].close > ema21[i] and ha[i].close > ha[i].open:
                rejim[i] = (1, a * 1.0, a * 2.5, a * 1.2)
            elif side_htf == -1 and bars[i - 1].close < ema21[i] and bars[i].high >= ema21[i] and bars[i].close < ema21[i] and ha[i].close < ha[i].open:
                rejim[i] = (-1, a * 1.0, a * 2.5, a * 1.2)
        # Rejim: yatayda banda donus, hedef orta cizgi
        if rejim[i] is None and adx_now is not None and adx_now <= 18 and lower[i] is not None and upper[i] is not None and mid[i] is not None:
            room = abs(mid[i] - bars[i].close)
            if room >= max(0.5 * a, spread * 8):
                if bars[i].low < lower[i] and bars[i].close > lower[i] and bars[i].close > bars[i].open:
                    rejim[i] = (1, 0.7 * a, min(room, 1.5 * a), 0.0)
                elif bars[i].high > upper[i] and bars[i].close < upper[i] and bars[i].close < bars[i].open:
                    rejim[i] = (-1, 0.7 * a, min(room, 1.5 * a), 0.0)
        # Supurme: onceki 15dk disina fitil, iceri kapanis, sadece yataya yakin ADX
        if adx_now is not None and adx_now <= 22 and prior_low[i] is not None and prior_high[i] is not None and a * 1.8 >= spread * 8:
            if bars[i].low < prior_low[i] and bars[i].close > prior_low[i] and bars[i].close > bars[i].open:
                sl = max(bars[i].close - bars[i].low + 0.1 * a, 0.4 * a)
                sweep[i] = (1, sl, 1.8 * a, 0.0)
            elif bars[i].high > prior_high[i] and bars[i].close < prior_high[i] and bars[i].close < bars[i].open:
                sl = max(bars[i].high - bars[i].close + 0.1 * a, 0.4 * a)
                sweep[i] = (-1, sl, 1.8 * a, 0.0)
        # Trend + basabas: 15dk yon, HA renk, genis hedef
        if side_htf in (1, -1) and ema21[i] is not None and a * 2.5 >= spread * 8:
            if side_htf == 1 and ha[i].close > ha[i].open and closes[i] > ema21[i] and ha[i - 1].close <= ha[i - 1].open:
                trend_be[i] = (1, 1.2 * a, 2.5 * a, 1.2 * a)
            elif side_htf == -1 and ha[i].close < ha[i].open and closes[i] < ema21[i] and ha[i - 1].close >= ha[i - 1].open:
                trend_be[i] = (-1, 1.2 * a, 2.5 * a, 1.2 * a)
    return {"rejim": rejim, "supurme": sweep, "trend_basabas": trend_be}


def run(bars: list[Bar], signals: list, spread: float, unit: float, vmin: float, vmax: float, vstep: float, window_start: int) -> dict:
    cash = eng.PAPER_BALANCE
    peak = cash
    max_dd = 0.0
    pos = None
    pending = None
    cool = -1
    trades = []

    def mark(i: int) -> None:
        nonlocal peak, max_dd
        unreal = 0.0
        if pos is not None:
            px = bars[i].close
            if pos["side"] == 1:
                unreal = (px - pos["net"]) * unit * pos["vol"]
            else:
                unreal = (pos["net"] - (px + spread)) * unit * pos["vol"]
        eq = cash + unreal
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)

    def shut(i: int, raw_exit: float, net_exit: float, reason: str) -> None:
        nonlocal pos, cash, cool
        net = pos["side"] * (net_exit - pos["net"]) * unit * pos["vol"]
        trades.append({
            "net": net,
            "exit_t": bars[i].t,
            "reason": reason,
            "side": pos["side"],
            "leg": pos["leg"],
            "hold_min": i - pos["i"],
        })
        cash += net
        pos = None
        cool = i + 4

    for i, bar in enumerate(bars):
        if bar.t >= window_start and pos is None and pending is not None:
            side, sl, tp, be = pending
            raw = bar.open
            if side == 1:
                net = raw + spread
                risk = net - (raw - sl)
                stop, target = raw - sl, raw + tp
                arm = raw + be if be else None
            else:
                net = raw
                stop, target = raw + sl + spread, raw - tp
                risk = stop - net
                arm = raw - be if be else None
            if risk > spread * 2 and unit > 0 and cash > 0:
                volume = eng.floor_volume(cash * eng.RISK_PCT / (risk * unit), vmin, vmax, vstep)
                if volume is not None:
                    pos = {"side": side, "net": net, "raw": raw, "stop": stop, "target": target, "arm": arm, "be": False, "vol": volume, "i": i, "leg": "trend" if be else "yatay"}
        pending = None
        if bar.t >= window_start and pos is not None:
            side = pos["side"]
            stop_hit = (side == 1 and bar.low <= pos["stop"]) or (side == -1 and bar.high >= (pos["stop"] - spread if pos["be"] else pos["stop"] - spread))
            # short stop is already the ask price
            if side == -1:
                stop_hit = bar.high >= pos["stop"] - spread
            tp_hit = (side == 1 and bar.high >= pos["target"]) or (side == -1 and bar.low <= pos["target"])
            if stop_hit:
                if side == 1:
                    raw_exit = bar.open if bar.open < pos["stop"] else pos["stop"]
                    shut(i, raw_exit, raw_exit, "stop")
                else:
                    level = pos["stop"] - spread
                    raw_exit = bar.open if bar.open > level else level
                    shut(i, raw_exit, raw_exit + spread, "stop")
            elif tp_hit:
                if side == 1:
                    raw_exit = bar.open if bar.open > pos["target"] else pos["target"]
                    shut(i, raw_exit, raw_exit, "tp")
                else:
                    raw_exit = bar.open if bar.open < pos["target"] else pos["target"]
                    shut(i, raw_exit, raw_exit + spread, "tp")
            elif i - pos["i"] >= 30:
                if side == 1:
                    shut(i, bar.close, bar.close, "time")
                else:
                    shut(i, bar.close, bar.close + spread, "time")
            elif pos["arm"] is not None and not pos["be"]:
                if (side == 1 and bar.high >= pos["arm"]) or (side == -1 and bar.low <= pos["arm"]):
                    pos["be"] = True
                    pos["stop"] = pos["raw"] if side == 1 else pos["raw"] + spread
        if bar.t >= window_start:
            mark(i)
        if i >= len(bars) - 1 or bar.t < window_start or pos is not None or i < cool:
            continue
        sig = signals[i]
        if sig is not None:
            pending = sig
    if pos is not None:
        last = len(bars) - 1
        if pos["side"] == 1:
            shut(last, bars[last].close, bars[last].close, "end")
        else:
            shut(last, bars[last].close, bars[last].close + spread, "end")
    nets = [t["net"] for t in trades]
    wins = [v for v in nets if v > 0]
    losses = [v for v in nets if v < 0]
    gp, gl = sum(wins), abs(sum(losses))
    by_day: dict[str, int] = defaultdict(int)
    days = []
    seen = set()
    for bar in bars:
        if bar.t < window_start or datetime.fromtimestamp(bar.t, timezone.utc).weekday() >= 5:
            continue
        key = datetime.fromtimestamp(bar.t, timezone.utc).strftime("%Y-%m-%d")
        if key not in seen:
            seen.add(key)
            days.append(key)
    for t in trades:
        if datetime.fromtimestamp(t["exit_t"], timezone.utc).weekday() >= 5:
            continue
        key = datetime.fromtimestamp(t["exit_t"], timezone.utc).strftime("%Y-%m-%d")
        if t["net"] > 0:
            by_day[key] += 1
    counts = [by_day[d] for d in days]
    trades_by_day: dict[str, int] = defaultdict(int)
    net_by_day: dict[str, float] = defaultdict(float)
    for t in trades:
        if datetime.fromtimestamp(t["exit_t"], timezone.utc).weekday() >= 5:
            continue
        key = datetime.fromtimestamp(t["exit_t"], timezone.utc).strftime("%Y-%m-%d")
        trades_by_day[key] += 1
        net_by_day[key] += t["net"]
    per_day = [trades_by_day[d] for d in days]
    day_nets = [net_by_day[d] for d in days]
    reasons: dict[str, int] = defaultdict(int)
    legs: dict[str, dict] = defaultdict(lambda: {"n": 0, "win": 0, "net": 0.0})
    for t in trades:
        reasons[t["reason"]] += 1
        bucket = legs[t["leg"]]
        bucket["n"] += 1
        bucket["net"] += t["net"]
        if t["net"] > 0:
            bucket["win"] += 1
    holds = sorted(t["hold_min"] for t in trades) or [0]
    reason_net: dict[str, float] = defaultdict(float)
    for t in trades:
        reason_net[t["reason"]] += t["net"]
    ordered_days = sorted(per_day)
    mid = ordered_days[len(ordered_days) // 2] if ordered_days else 0
    return {
        "trades": len(trades),
        "winners": len(wins),
        "net": round(sum(nets), 2),
        "pf": None if not trades else ("inf" if gl == 0 and gp > 0 else (round(gp / gl, 3) if gl else None)),
        "dd": round(max_dd, 2),
        "avg_winners_per_weekday": round(sum(counts) / len(days), 2) if days else None,
        "weekdays_with_15": sum(1 for c in counts if c >= 15),
        "weekdays": len(days),
        "avg_trades_per_weekday": round(sum(per_day) / len(days), 2) if days else None,
        "median_trades_per_weekday": mid,
        "max_trades_per_weekday": max(per_day) if per_day else 0,
        "min_trades_per_weekday": min(per_day) if per_day else 0,
        "green_days": sum(1 for value in day_nets if value > 0),
        "red_days": sum(1 for value in day_nets if value < 0),
        "reasons": dict(reasons),
        "reason_net": {key: round(value, 2) for key, value in reason_net.items()},
        "legs": {key: {"n": value["n"], "win": value["win"], "net": round(value["net"], 2)} for key, value in legs.items()},
        "median_hold_min": holds[len(holds) // 2],
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "buys": sum(1 for t in trades if t["side"] == 1),
        "sells": sum(1 for t in trades if t["side"] == -1),
    }


def passes(row: dict) -> bool:
    pf = row["pf"]
    avg = row["avg_winners_per_weekday"] or 0
    return row["net"] > 0 and isinstance(pf, float) and pf >= 1.15 and avg >= 15 and row["dd"] <= 2500


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    report: dict = {"rule": "60g ve son 20g birlikte: net>0, PF>=1.15, kazanc/gun>=15, dusus<=2500", "symbols": {}}
    for symbol in ("XAUUSD", "BTCUSD"):
        resolved, bars = fetch(symbol, offset)
        costs = eng.symbol_costs(resolved)
        last = bars[-1].t
        sigs = build_signals(symbol, bars, costs["spread_price"])
        cells = {}
        for name, series in sigs.items():
            full = run(bars, series, costs["spread_price"], costs["unit_per_lot_per_price"], costs["volume_min"], costs["volume_max"], costs["volume_step"], last - WINDOW_60)
            late = run(bars, series, costs["spread_price"], costs["unit_per_lot_per_price"], costs["volume_min"], costs["volume_max"], costs["volume_step"], last - WINDOW_20)
            cells[name] = {"d60": full, "d20": late, "pass": passes(full) and passes(late)}
        report["symbols"][symbol] = {
            "spread": costs["spread_price"],
            "first_utc": datetime.fromtimestamp(bars[0].t, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "last_utc": datetime.fromtimestamp(last, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "strategies": cells,
        }
    adopted = {
        symbol: [name for name, cell in body["strategies"].items() if cell["pass"]]
        for symbol, body in report["symbols"].items()
    }
    report["adopted"] = adopted
    report["result"] = "bulundu" if all(adopted.values()) else "hedef_tutmadi"
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "m1_rejim_sweep_60d.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "result": report["result"], "adopted": adopted, "symbols": report["symbols"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
