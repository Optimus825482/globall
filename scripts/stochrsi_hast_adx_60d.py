#!/usr/bin/env python3
"""HA Supertrend + normal mumda Stochastic RSI kesimi + ADX.

Alis: K, D'yi 20 altinda yukari keser, HA-ST yukari, ADX>=20 ve +DI>-DI.
Satis: K, D'yi 80 ustunde asagi keser, HA-ST asagi, ADX>=20 ve -DI>+DI.
Giris sonraki acilis. Stop, Heikin Ashi Supertrend cizgisi.
60 takvim gunu, paper 10_000 USD, risk %1. Emir yok.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_m1_gunluk_60d as m1  # noqa: E402


def sma_none(values: list[float | None], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        chunk = values[i - period + 1:i + 1]
        if all(value is not None for value in chunk):
            out[i] = sum(chunk) / period  # type: ignore[arg-type]
    return out


def stoch_rsi(closes: list[float]) -> tuple[list[float | None], list[float | None]]:
    rsi = eng.rsi_wilder(closes, 14)
    raw: list[float | None] = [None] * len(closes)
    for i in range(14, len(closes)):
        window = rsi[i - 13:i + 1]
        if any(value is None for value in window):
            continue
        lo, hi = min(window), max(window)  # type: ignore[type-var]
        raw[i] = 0.0 if hi == lo else (rsi[i] - lo) / (hi - lo) * 100.0
    k = sma_none(raw, 3)
    d = sma_none(k, 3)
    return k, d


def run(
    bars: list[eng.Bar],
    spread: float,
    unit: float,
    vmin: float,
    vmax: float,
    vstep: float,
    window_start: int,
    low_zone: float = 20,
    high_zone: float = 80,
    use_adx: bool = True,
) -> dict:
    closes = [bar.close for bar in bars]
    st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    k, d = stoch_rsi(closes)
    plus_di, minus_di, adx = eng.adx_dmi(bars, 14)
    cash = eng.PAPER_BALANCE
    peak = cash
    max_dd = 0.0
    pos = None
    pending_side = 0
    pending_stop = 0.0
    pending_exit = False
    trades = []
    blocked = {"st": 0, "adx": 0}

    def mark(i: int) -> None:
        nonlocal peak, max_dd
        unreal = 0.0
        if pos is not None:
            px = bars[i].close
            if pos["side"] == 1:
                unreal = (px - pos["net"]) * unit * pos["vol"]
            else:
                unreal = (pos["net"] - (px + spread)) * unit * pos["vol"]
        equity = cash + unreal
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    def shut(i: int, raw_exit: float, net_exit: float, reason: str) -> None:
        nonlocal pos, cash
        net = pos["side"] * (net_exit - pos["net"]) * unit * pos["vol"]
        trades.append({"net": net, "exit_t": bars[i].t, "reason": reason, "side": pos["side"]})
        cash += net
        pos = None

    for i, bar in enumerate(bars):
        if bar.t >= window_start and pending_exit and pos is not None:
            if pos["side"] == 1:
                shut(i, bar.open, bar.open, "st_flip")
            else:
                shut(i, bar.open, bar.open + spread, "st_flip")
        pending_exit = False
        if bar.t >= window_start and pos is None and pending_side != 0:
            side, stop_line = pending_side, pending_stop
            raw = bar.open
            if side == 1:
                net = raw + spread
                risk = net - stop_line
                stop = stop_line
            else:
                net = raw
                stop = stop_line + spread
                risk = stop - net
            if risk > spread and unit > 0 and cash > 0:
                volume = eng.floor_volume(cash * eng.RISK_PCT / (risk * unit), vmin, vmax, vstep)
                if volume is not None:
                    pos = {"side": side, "net": net, "stop": stop, "vol": volume, "i": i}
        pending_side = 0
        if bar.t >= window_start and pos is not None and i > pos["i"]:
            side = pos["side"]
            if side == 1 and bar.low <= pos["stop"]:
                raw_exit = bar.open if bar.open < pos["stop"] else pos["stop"]
                shut(i, raw_exit, raw_exit, "stop")
            elif side == -1 and bar.high >= pos["stop"] - spread:
                level = pos["stop"] - spread
                raw_exit = bar.open if bar.open > level else level
                shut(i, raw_exit, raw_exit + spread, "stop")
            elif (side == 1 and direction[i] == 1) or (side == -1 and direction[i] == -1):
                pending_exit = True
        if bar.t >= window_start:
            mark(i)
        if i == 0 or i >= len(bars) - 1 or k[i] is None or d[i] is None or k[i - 1] is None or d[i - 1] is None or st[i] is None:
            continue
        if bar.t < window_start or pos is not None or pending_exit:
            continue
        cross_up = k[i - 1] <= d[i - 1] and k[i] > d[i] and k[i] < low_zone
        cross_dn = k[i - 1] >= d[i - 1] and k[i] < d[i] and k[i] > high_zone
        want = 1 if cross_up else -1 if cross_dn else 0
        if want == 0:
            continue
        st_ok = (want == 1 and direction[i] == -1) or (want == -1 and direction[i] == 1)
        adx_ok = (
            adx[i] is not None and plus_di[i] is not None and minus_di[i] is not None and adx[i] >= 20
            and ((want == 1 and plus_di[i] > minus_di[i]) or (want == -1 and minus_di[i] > plus_di[i]))
        )
        if not st_ok:
            blocked["st"] += 1
            continue
        if use_adx and not adx_ok:
            blocked["adx"] += 1
            continue
        line = st[i]
        if want == 1 and line >= bar.close:
            continue
        if want == -1 and line <= bar.close:
            continue
        pending_side = want
        pending_stop = line

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
    days, seen = [], set()
    winners_day: dict[str, int] = defaultdict(int)
    trades_day: dict[str, int] = defaultdict(int)
    for bar in bars:
        if bar.t < window_start or datetime.fromtimestamp(bar.t, timezone.utc).weekday() >= 5:
            continue
        key = datetime.fromtimestamp(bar.t, timezone.utc).strftime("%Y-%m-%d")
        if key not in seen:
            seen.add(key)
            days.append(key)
    reasons: dict[str, int] = defaultdict(int)
    for t in trades:
        reasons[t["reason"]] += 1
        if datetime.fromtimestamp(t["exit_t"], timezone.utc).weekday() >= 5:
            continue
        key = datetime.fromtimestamp(t["exit_t"], timezone.utc).strftime("%Y-%m-%d")
        trades_day[key] += 1
        if t["net"] > 0:
            winners_day[key] += 1
    return {
        "trades": len(trades),
        "winners": len(wins),
        "buys": sum(1 for t in trades if t["side"] == 1),
        "sells": sum(1 for t in trades if t["side"] == -1),
        "net": round(sum(nets), 2),
        "pf": None if not trades else ("inf" if gl == 0 and gp > 0 else (round(gp / gl, 3) if gl else None)),
        "dd": round(max_dd, 2),
        "win_rate": round(len(wins) / len(trades), 3) if trades else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "avg_trades_per_weekday": round(sum(trades_day[d] for d in days) / len(days), 2) if days else None,
        "avg_winners_per_weekday": round(sum(winners_day[d] for d in days) / len(days), 2) if days else None,
        "reasons": dict(reasons),
        "blocked": blocked,
        "weekdays": len(days),
    }


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    rows = []
    for symbol in ("XAUUSD", "BTCUSD"):
        for tf in ("15m", "5m", "3m", "1m"):
            if tf == "1m":
                resolved, bars = m1.fetch_m1(symbol, offset)
                costs = eng.symbol_costs(resolved)
            else:
                resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=100)
                costs = eng.symbol_costs(resolved)
            last = bars[-1].t
            stats = run(
                bars, costs["spread_price"], costs["unit_per_lot_per_price"],
                costs["volume_min"], costs["volume_max"], costs["volume_step"],                 last - 60 * 86400,
                low_zone=10, high_zone=90, use_adx=False,
            )
            rows.append({
                "symbol": symbol,
                "tf": tf,
                "spread": round(costs["spread_price"], 4),
                "from": datetime.fromtimestamp(last - 60 * 86400, timezone.utc).strftime("%Y-%m-%d"),
                "to": datetime.fromtimestamp(last, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "stoch_low": 10,
                "stoch_high": 90,
                **stats,
            })
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stochrsi_hast_10_90_noadx.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
