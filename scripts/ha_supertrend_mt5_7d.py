#!/usr/bin/env python3
"""HA-ST Filtre — BTCUSD ve XAUUSD, 7 gun, MT5 bridge verisi.

Strateji backtest calismadan once kilitlendi. Carpani, periyodu veya
esikleri sonuca bakip degistirmez.

Cekirdek (ha_st_rsi_adx):
  * Heikin Ashi, broker OHLC uzerinden.
  * TradingView ta.supertrend(10, 3) Heikin Ashi mumuna uygulanir.
  * RSI(14) ve ADX(14) gercek mumdadir; HA uzerine ikinci kez yumusatilmaz.
  * Long: ST yukari doner, RSI>50, ADX>=20, +DI>-DI.
  * Short: ST asagi doner, RSI<50, ADX>=20, -DI>+DI.
  * Giris bir sonraki mumun acilisinda. Koruyucu stop, onceki kapanmis
    Supertrend cizgisidir ve gercek high/low ile bakilir.
  * Cikis: ters ST donusu (sonraki acilis), stop, veya pencere sonu.
  * Tek pozisyon. Paper bakiye 10_000 hesap para birimi. Risk islem basina %1.
  * XAUUSD yeni girisleri yalniz 07:00-21:00 UTC (Londra + New York).
  * BTCUSD, broker acik oldugu tum saatler.

Karsilastirmalar (ayni pencerede, ayni maliyet):
  baseline_st_10_3, ha_st_10_3, ha_st_rsi_adx_24s, ha_dual_7_2_10_3.

Veri: calisan MetaTrader 5 terminali (mt5_bridge.py ile ayni oturum).
Emir gonderilmez. copy_rates bid mumdur; maliyet anlik spread snapshot'idir.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import mt5_bridge  # noqa: E402
import MetaTrader5 as mt5  # noqa: E402

PAPER_BALANCE = 10_000.0
RISK_PCT = 0.01
WINDOW_SEC = 7 * 24 * 3600
WARMUP_DAYS = 21
PRIMARY_TF = "15m"
TIMEFRAMES = ("15m", "5m")
SYMBOLS = ("BTCUSD", "XAUUSD")
CORE_NAME = "ha_st_rsi_adx"
RESULT_PATH = os.path.join(SCRIPT_DIR, "ha_supertrend_mt5_7d_result.json")

TF_MAP = {
    "1m": mt5.TIMEFRAME_M1,
    "3m": mt5.TIMEFRAME_M3,
    "5m": mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "1h": mt5.TIMEFRAME_H1,
    "4h": mt5.TIMEFRAME_H4,
}
TF_SEC = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


@dataclass
class Bar:
    t: int
    open: float
    high: float
    low: float
    close: float


@dataclass
class Position:
    side: int
    raw_entry: float
    net_entry: float
    stop: float
    volume: float
    risk_cash: float
    entry_t: int
    entry_i: int


@dataclass
class Trade:
    side: str
    entry_t: int
    exit_t: int
    raw_entry: float
    net_entry: float
    raw_exit: float
    net_exit: float
    volume: float
    gross: float
    net: float
    r_multiple: float
    reason: str


def wilder_rma(values: list[float], period: int) -> list[float | None]:
    """TradingView ta.rma: ilk deger SMA, sonra (prev*(n-1)+x)/n."""
    out: list[float | None] = [None] * len(values)
    seed_at = None
    for i in range(period - 1, len(values)):
        if all(values[j] is not None for j in range(i - period + 1, i + 1)):
            seed_at = i
            break
    if seed_at is None:
        return out
    prev = sum(values[seed_at - period + 1:seed_at + 1]) / period
    out[seed_at] = prev
    for i in range(seed_at + 1, len(values)):
        v = values[i]
        if v is None or prev is None:
            out[i] = None
            continue
        prev = (prev * (period - 1) + v) / period
        out[i] = prev
    return out


def heikin_ashi(bars: list[Bar]) -> list[Bar]:
    ha: list[Bar] = []
    for i, bar in enumerate(bars):
        ha_close = (bar.open + bar.high + bar.low + bar.close) / 4.0
        if i == 0:
            ha_open = (bar.open + bar.close) / 2.0
        else:
            ha_open = (ha[i - 1].open + ha[i - 1].close) / 2.0
        ha_high = max(bar.high, ha_open, ha_close)
        ha_low = min(bar.low, ha_open, ha_close)
        ha.append(Bar(bar.t, ha_open, ha_high, ha_low, ha_close))
    return ha


def supertrend(bars: list[Bar], period: int = 10, factor: float = 3.0) -> tuple[list[float | None], list[int]]:
    """TradingView ta.supertrend. direction -1 = yukari, +1 = asagi."""
    n = len(bars)
    tr: list[float | None] = [None] * n
    for i in range(1, n):
        prev_c = bars[i - 1].close
        tr[i] = max(
            bars[i].high - bars[i].low,
            abs(bars[i].high - prev_c),
            abs(bars[i].low - prev_c),
        )
    atr = wilder_rma(tr, period)
    st: list[float | None] = [None] * n
    direction = [0] * n
    final_lower: list[float | None] = [None] * n
    final_upper: list[float | None] = [None] * n
    for i in range(n):
        if atr[i] is None:
            continue
        hl2 = (bars[i].high + bars[i].low) / 2.0
        lower = hl2 - factor * atr[i]
        upper = hl2 + factor * atr[i]
        if i == 0 or final_lower[i - 1] is None or atr[i - 1] is None:
            final_lower[i] = lower
            final_upper[i] = upper
            direction[i] = -1 if bars[i].close >= hl2 else 1
            st[i] = final_lower[i] if direction[i] == -1 else final_upper[i]
            continue
        prev_close = bars[i - 1].close
        if lower > final_lower[i - 1] or prev_close < final_lower[i - 1]:
            final_lower[i] = lower
        else:
            final_lower[i] = final_lower[i - 1]
        if upper < final_upper[i - 1] or prev_close > final_upper[i - 1]:
            final_upper[i] = upper
        else:
            final_upper[i] = final_upper[i - 1]
        if direction[i - 1] == 1:
            direction[i] = -1 if bars[i].close > final_upper[i] else 1
        else:
            direction[i] = 1 if bars[i].close < final_lower[i] else -1
        st[i] = final_lower[i] if direction[i] == -1 else final_upper[i]
    return st, direction


def rsi_wilder(closes: list[float], period: int = 14) -> list[float | None]:
    n = len(closes)
    gain: list[float | None] = [None] * n
    loss: list[float | None] = [None] * n
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        gain[i] = max(diff, 0.0)
        loss[i] = max(-diff, 0.0)
    avg_g = wilder_rma(gain, period)
    avg_l = wilder_rma(loss, period)
    out: list[float | None] = [None] * n
    for i in range(n):
        if avg_g[i] is None or avg_l[i] is None:
            continue
        if avg_l[i] == 0:
            out[i] = 100.0
        else:
            rs = avg_g[i] / avg_l[i]
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def adx_dmi(bars: list[Bar], period: int = 14) -> tuple[list[float | None], list[float | None], list[float | None]]:
    n = len(bars)
    tr: list[float | None] = [None] * n
    plus_dm: list[float | None] = [None] * n
    minus_dm: list[float | None] = [None] * n
    for i in range(1, n):
        up = bars[i].high - bars[i - 1].high
        down = bars[i - 1].low - bars[i].low
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0
        prev_c = bars[i - 1].close
        tr[i] = max(bars[i].high - bars[i].low, abs(bars[i].high - prev_c), abs(bars[i].low - prev_c))
    atr = wilder_rma(tr, period)
    sm_plus = wilder_rma(plus_dm, period)
    sm_minus = wilder_rma(minus_dm, period)
    plus_di: list[float | None] = [None] * n
    minus_di: list[float | None] = [None] * n
    dx: list[float | None] = [None] * n
    for i in range(n):
        if atr[i] is None or sm_plus[i] is None or sm_minus[i] is None or atr[i] == 0:
            continue
        plus_di[i] = 100.0 * sm_plus[i] / atr[i]
        minus_di[i] = 100.0 * sm_minus[i] / atr[i]
        denom = plus_di[i] + minus_di[i]
        dx[i] = 0.0 if denom == 0 else 100.0 * abs(plus_di[i] - minus_di[i]) / denom
    adx = wilder_rma(dx, period)
    return plus_di, minus_di, adx


def floor_volume(volume: float, vmin: float, vmax: float, step: float) -> float | None:
    if volume <= 0 or step <= 0 or vmin <= 0:
        return None
    steps = math.floor((volume + 1e-12) / step)
    sized = round(steps * step, 8)
    if sized < vmin - 1e-9:
        return None
    max_sized = round(math.floor((vmax + 1e-12) / step) * step, 8)
    return min(sized, max_sized)


def _flip_to(direction: list[int], i: int) -> int:
    """1 = yukari donus, -1 = asagi donus, 0 = donus yok."""
    if i <= 0 or direction[i] == 0 or direction[i - 1] == 0:
        return 0
    if direction[i] == -1 and direction[i - 1] == 1:
        return 1
    if direction[i] == 1 and direction[i - 1] == -1:
        return -1
    return 0


def session_ok(ts: int, symbol: str, use_session: bool) -> bool:
    if not use_session or symbol != "XAUUSD":
        return True
    hour = datetime.fromtimestamp(ts, timezone.utc).hour
    return 7 <= hour < 21


def hour_in_span(ts: int, span: tuple[int, int] | None) -> bool:
    if span is None:
        return True
    start, end = span
    hour = datetime.fromtimestamp(ts, timezone.utc).hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def entry_allowed(
    mode: str,
    side: int,
    i: int,
    rsi: list[float | None],
    adx: list[float | None],
    plus_di: list[float | None],
    minus_di: list[float | None],
) -> bool:
    """Giris filtresi. Modlar backtestten once kilitlendi."""
    if mode == "none":
        return True
    rv, av, pdi, mdi = rsi[i], adx[i], plus_di[i], minus_di[i]
    rsi_ok = rv is not None and ((side == 1 and rv > 50) or (side == -1 and rv < 50))
    def adx_ok(threshold: float) -> bool:
        if av is None or pdi is None or mdi is None or av < threshold:
            return False
        return (side == 1 and pdi > mdi) or (side == -1 and mdi > pdi)
    if mode == "rsi":
        return rsi_ok
    if mode == "adx20":
        return adx_ok(20)
    if mode == "adx25":
        return adx_ok(25)
    if mode == "full20":
        return rsi_ok and adx_ok(20)
    if mode == "full25":
        return rsi_ok and adx_ok(25)
    raise ValueError(f"bilinmeyen filtre: {mode}")


def _filters_ok(
    side: int,
    i: int,
    rsi: list[float | None],
    adx: list[float | None],
    plus_di: list[float | None],
    minus_di: list[float | None],
) -> bool:
    rv, av, pdi, mdi = rsi[i], adx[i], plus_di[i], minus_di[i]
    if rv is None or av is None or pdi is None or mdi is None or av < 20:
        return False
    if side == 1:
        return rv > 50 and pdi > mdi
    return rv < 50 and mdi > pdi


def run_backtest(
    bars: list[Bar],
    *,
    symbol: str,
    variant: str,
    spread: float,
    unit_per_lot: float,
    vmin: float,
    vmax: float,
    vstep: float,
    digits: int,
    window_start: int,
    addon: str = "none",
    entry_filter: str | None = None,
    session_span: tuple[int, int] | None = None,
    bias: list[int] | None = None,
) -> dict:
    raw = bars
    ha = heikin_ashi(bars)
    src = ha if variant != "baseline_st_10_3" else raw
    st, direction = supertrend(src, 10, 3.0)
    fast_st, fast_dir = supertrend(src, 7, 2.0)
    closes = [b.close for b in raw]
    rsi = rsi_wilder(closes, 14)
    plus_di, minus_di, adx = adx_dmi(raw, 14)

    use_filter = variant in ("ha_st_rsi_adx", "ha_st_rsi_adx_24s")
    use_session = variant == "ha_st_rsi_adx"
    dual = variant == "ha_dual_7_2_10_3"
    line = fast_st if dual else st
    sig_dir = fast_dir if dual else direction

    cash = PAPER_BALANCE
    peak = PAPER_BALANCE
    max_dd = 0.0
    pos: Position | None = None
    pending_exit = False
    pending_side = 0
    pending_stop: float | None = None
    trades: list[Trade] = []
    skipped = {"min_lot": 0, "gap": 0, "filter": 0, "session": 0, "no_unit": 0, "addon": 0, "bias": 0}
    exposure_bars = 0
    window_bars = 0
    wick_used = False
    pullback_used = False
    resume_used = 0
    last_resume_i = -999

    def _arm_wick(side: int, i: int) -> None:
        nonlocal pending_side, pending_stop, wick_used
        if addon != "wick_reentry" or wick_used or i >= n - 1 or line[i] is None:
            return
        aligned = (side == 1 and sig_dir[i] == -1) or (side == -1 and sig_dir[i] == 1)
        if not aligned or raw[i].t < window_start:
            return
        if use_session and not session_ok(raw[i].t, symbol, True):
            return
        if use_filter and not _filters_ok(side, i, rsi, adx, plus_di, minus_di):
            return
        pending_side = side
        pending_stop = line[i]
        wick_used = True
        skipped["addon"] += 1

    def mark(i: int) -> None:
        nonlocal peak, max_dd
        unreal = 0.0
        if pos is not None:
            px = raw[i].close
            if pos.side == 1:
                unreal = (px - pos.net_entry) * unit_per_lot * pos.volume
            else:
                unreal = (pos.net_entry - (px + spread)) * unit_per_lot * pos.volume
        equity = cash + unreal
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    def close_pos(i: int, raw_exit: float, net_exit: float, reason: str) -> None:
        nonlocal pos, cash
        assert pos is not None
        gross = pos.side * (raw_exit - pos.raw_entry) * unit_per_lot * pos.volume
        net = pos.side * (net_exit - pos.net_entry) * unit_per_lot * pos.volume
        r_mult = net / pos.risk_cash if pos.risk_cash else 0.0
        trades.append(Trade(
            "BUY" if pos.side == 1 else "SELL",
            pos.entry_t, raw[i].t,
            pos.raw_entry, pos.net_entry, raw_exit, net_exit,
            pos.volume, gross, net, r_mult, reason,
        ))
        cash += net
        pos = None

    def try_open(i: int, side: int, stop: float) -> None:
        nonlocal pos
        bar = raw[i]
        raw_entry = bar.open
        if side == 1:
            net_entry = raw_entry + spread
            if net_entry <= stop:
                skipped["gap"] += 1
                return
            risk_price = net_entry - stop
        else:
            net_entry = raw_entry
            stop_net = stop + spread
            if net_entry >= stop:
                skipped["gap"] += 1
                return
            risk_price = stop_net - net_entry
            stop = stop_net
        if risk_price <= spread:
            skipped["gap"] += 1
            return
        if unit_per_lot <= 0:
            skipped["no_unit"] += 1
            return
        risk_cash = cash * RISK_PCT
        if risk_cash <= 0:
            return
        volume = floor_volume(risk_cash / (risk_price * unit_per_lot), vmin, vmax, vstep)
        if volume is None:
            skipped["min_lot"] += 1
            return
        pos = Position(side, raw_entry, net_entry, stop, volume, risk_cash, bar.t, i)
        if side == 1 and bar.low <= stop:
            raw_exit = bar.open if bar.open < stop else stop
            close_pos(i, raw_exit, raw_exit, "stop")
        elif side == -1 and bar.high + spread >= stop:
            raw_level = stop - spread
            raw_exit = bar.open if bar.open > raw_level else raw_level
            close_pos(i, raw_exit, raw_exit + spread, "stop")

    n = len(raw)
    for i in range(n):
        in_window = raw[i].t >= window_start
        if in_window:
            window_bars += 1
        if in_window and pending_exit and pos is not None:
            if pos.side == 1:
                close_pos(i, raw[i].open, raw[i].open, "flip")
            else:
                close_pos(i, raw[i].open, raw[i].open + spread, "flip")
        pending_exit = False
        if in_window and pos is None and pending_side != 0 and pending_stop is not None:
            try_open(i, pending_side, pending_stop)
        pending_side = 0
        pending_stop = None

        if in_window and pos is not None and i > pos.entry_i:
            if pos.side == 1 and raw[i].low <= pos.stop:
                raw_exit = raw[i].open if raw[i].open < pos.stop else pos.stop
                held_side = pos.side
                close_pos(i, raw_exit, raw_exit, "stop")
                _arm_wick(held_side, i)
            elif pos.side == -1 and raw[i].high >= (pos.stop - spread):
                raw_level = pos.stop - spread
                raw_exit = raw[i].open if raw[i].open > raw_level else raw_level
                held_side = pos.side
                close_pos(i, raw_exit, raw_exit + spread, "stop")
                _arm_wick(held_side, i)

        if in_window and pos is not None:
            exposure_bars += 1
        if in_window:
            mark(i)

        if i >= n - 1 or line[i] is None:
            continue
        flip = _flip_to(sig_dir, i)
        if flip != 0:
            wick_used = False
            pullback_used = False
            resume_used = 0
        entry_flip = flip
        # Cift ST: cikis hizli cizginin donusudur. Giris icin yavas ST de ayni yonde olmali.
        if dual and entry_flip != 0:
            slow_ok = direction[i] == (-1 if entry_flip == 1 else 1)
            if not slow_ok:
                entry_flip = 0
        if pos is not None and flip == -pos.side:
            pending_exit = True
        want = 0
        if entry_flip != 0 and (pos is None or entry_flip == -pos.side):
            want = entry_flip
        if want == 0 or raw[i].t < window_start:
            if pos is not None and line[i] is not None and not pending_exit:
                if pos.side == 1 and sig_dir[i] == -1:
                    pos.stop = max(pos.stop, line[i])
                elif pos.side == -1 and sig_dir[i] == 1:
                    pos.stop = min(pos.stop, line[i] + spread)
            elif (
                pos is None and pending_side == 0 and not pending_exit
                and raw[i].t >= window_start and line[i] is not None and i > 0
                and sig_dir[i] != 0 and sig_dir[i] == sig_dir[i - 1]
            ):
                side = 1 if sig_dir[i] == -1 else -1
                allow = (not use_session or session_ok(raw[i].t, symbol, True)) and (
                    not use_filter or _filters_ok(side, i, rsi, adx, plus_di, minus_di)
                )
                if allow and addon == "pullback" and not pullback_used:
                    touched = (
                        (side == 1 and raw[i].low <= line[i] and raw[i].close > line[i])
                        or (side == -1 and raw[i].high >= line[i] and raw[i].close < line[i])
                    )
                    if touched:
                        pending_side = side
                        pending_stop = line[i]
                        pullback_used = True
                        skipped["addon"] += 1
                if (
                    allow and addon == "ha_resume" and resume_used < 2
                    and i - last_resume_i >= 6 and pending_side == 0
                ):
                    bull = ha[i].close > ha[i].open
                    prev_bull = ha[i - 1].close > ha[i - 1].open
                    resumed = (side == 1 and bull and not prev_bull) or (side == -1 and (not bull) and prev_bull)
                    if resumed:
                        pending_side = side
                        pending_stop = line[i]
                        resume_used += 1
                        last_resume_i = i
                        skipped["addon"] += 1
            continue
        if entry_filter is not None:
            if not hour_in_span(raw[i].t, session_span):
                skipped["session"] += 1
                want = 0
            elif want and not entry_allowed(entry_filter, want, i, rsi, adx, plus_di, minus_di):
                skipped["filter"] += 1
                want = 0
        elif use_session and not session_ok(raw[i].t, symbol, True):
            skipped["session"] += 1
            want = 0
        if entry_filter is None and want and use_filter:
            rv, av = rsi[i], adx[i]
            pdi, mdi = plus_di[i], minus_di[i]
            if addon == "rsi_only":
                ok = rv is not None and ((want == 1 and rv > 50) or (want == -1 and rv < 50))
            elif addon == "adx15":
                ok = (
                    rv is not None and av is not None and pdi is not None and mdi is not None
                    and av >= 15
                    and ((want == 1 and rv > 50 and pdi > mdi) or (want == -1 and rv < 50 and mdi > pdi))
                )
            else:
                ok = (
                    rv is not None and av is not None and pdi is not None and mdi is not None
                    and av >= 20
                    and ((want == 1 and rv > 50 and pdi > mdi) or (want == -1 and rv < 50 and mdi > pdi))
                )
            if not ok:
                skipped["filter"] += 1
                want = 0
        if want and bias is not None and (i >= len(bias) or bias[i] != want):
            skipped["bias"] += 1
            want = 0
        if want and line[i] is not None:
            pending_side = want
            pending_stop = line[i]
        elif pos is not None and line[i] is not None and not pending_exit:
            if pos.side == 1 and sig_dir[i] == -1:
                pos.stop = max(pos.stop, line[i])
            elif pos.side == -1 and sig_dir[i] == 1:
                pos.stop = min(pos.stop, line[i] + spread)

    if pos is not None:
        last = n - 1
        if pos.side == 1:
            close_pos(last, raw[last].close, raw[last].close, "window_end")
        else:
            close_pos(last, raw[last].close, raw[last].close + spread, "window_end")
        mark(last)

    nets = [t.net for t in trades]
    grosses = [t.gross for t in trades]
    wins = [v for v in nets if v > 0]
    losses = [v for v in nets if v < 0]
    gp, gl = sum(wins), abs(sum(losses))
    streak = worst = 0
    for v in nets:
        if v < 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1
    return {
        "variant": variant,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len([v for v in nets if v < 0]),
        "flats": len([v for v in nets if v == 0]),
        "win_rate": (len(wins) / len(trades)) if trades else None,
        "gross_pnl": sum(grosses),
        "net_pnl": sum(nets),
        "ending_equity": cash,
        "profit_factor": (gp / gl) if gl > 0 else (None if gp == 0 else "inf"),
        "expectancy": (sum(nets) / len(trades)) if trades else None,
        "avg_r": (sum(t.r_multiple for t in trades) / len(trades)) if trades else None,
        "max_drawdown": max_dd,
        "max_losing_streak": worst,
        "exposure_bars": exposure_bars,
        "window_bars": window_bars,
        "exposure_pct": (exposure_bars / window_bars) if window_bars else None,
        "exit_reasons": reasons,
        "skipped": skipped,
        "buy_count": sum(1 for t in trades if t.side == "BUY"),
        "sell_count": sum(1 for t in trades if t.side == "SELL"),
        "trade_list": [
            {
                "side": t.side,
                "entry_utc": datetime.fromtimestamp(t.entry_t, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "exit_utc": datetime.fromtimestamp(t.exit_t, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "net": round(t.net, 2),
                "gross": round(t.gross, 2),
                "r": round(t.r_multiple, 3),
                "reason": t.reason,
                "volume": t.volume,
            }
            for t in trades
        ],
    }


def self_check() -> None:
    up: list[Bar] = []
    px = 100.0
    t0 = 1_700_000_000
    for i in range(80):
        px += 1.0
        up.append(Bar(t0 + i * 900, px - 0.4, px + 0.3, px - 0.6, px))
    _st, direction = supertrend(up, 10, 3.0)
    if direction[-1] != -1:
        raise SystemExit(f"self-check: yukselen seride ST yukari degil ({direction[-1]})")
    crash = list(up)
    last = crash[-1].close
    for i in range(15):
        last -= 4.0
        crash.append(Bar(crash[-1].t + 900, last + 0.2, last + 0.4, last - 0.5, last))
    _st2, direction2 = supertrend(crash, 10, 3.0)
    if direction2[-1] != 1:
        raise SystemExit(f"self-check: cokus sonrasi ST asagi donmedi ({direction2[-1]})")
    ha = heikin_ashi(up[:2])
    manual = (up[0].open + up[0].high + up[0].low + up[0].close) / 4.0
    if abs(ha[0].close - manual) > 1e-9:
        raise SystemExit("self-check: Heikin Ashi kapanisi hatali")


def attach_terminal() -> str:
    """Calisan terminalin oturumuna yapis. Yeni login denemez, shutdown cagirmaz."""
    if mt5.initialize():
        return "running-terminal"
    err = mt5.last_error()
    path = r"C:\Program Files\MetaTrader 5\terminal64.exe"
    if mt5.initialize(path=path):
        return path
    err2 = mt5.last_error()
    raise SystemExit(f"MT5 baglantisi kurulamadi. Ilk hata: {err}. Ikinci hata: {err2}.")


def server_offset_s() -> int:
    now = int(time.time())
    best_off, best_gap = 0, 10 ** 9
    fresh = False
    for probe in ("BTCUSD", "XAUUSD", "EURUSD", "GBPUSD"):
        resolved = mt5_bridge.resolve_mt5_symbol(probe)
        tick = mt5.symbol_info_tick(resolved)
        if tick is None or not getattr(tick, "time", None):
            continue
        gap = abs(int(tick.time) - now)
        if gap < best_gap:
            best_gap = gap
            best_off = int(tick.time) - now
            fresh = gap < 6 * 3600
    if not fresh:
        return 0
    return int(round(best_off / 1800.0) * 1800)


def fetch_bars(app_symbol: str, tf: str, offset: int, lookback_days: int | None = None) -> tuple[str, list[Bar]]:
    import datetime as dt
    resolved = mt5_bridge.resolve_mt5_symbol(app_symbol)
    info = mt5.symbol_info(resolved)
    if info is None:
        raise SystemExit(f"{app_symbol} terminalde yok (cozulen ad: {resolved})")
    if not info.visible:
        mt5.symbol_select(resolved, True)
    end_broker = dt.datetime.now() + dt.timedelta(seconds=offset)
    start_broker = end_broker - dt.timedelta(days=lookback_days or (WARMUP_DAYS + 8))
    rates = mt5.copy_rates_range(resolved, TF_MAP[tf], start_broker, end_broker)
    if rates is None or len(rates) == 0:
        raise SystemExit(f"{resolved} {tf} mum yok. last_error={mt5.last_error()}")
    bars = [
        Bar(int(r["time"]) - offset, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
        for r in rates
    ]
    bars.sort(key=lambda b: b.t)
    step = TF_SEC[tf]
    if bars and bars[-1].t + step > time.time():
        bars = bars[:-1]
    return resolved, bars


def symbol_costs(resolved: str) -> dict:
    info = mt5.symbol_info(resolved)
    tick = mt5.symbol_info_tick(resolved)
    if info is None or tick is None:
        raise SystemExit(f"{resolved} sembol/tick bilgisi alinamadi")
    point_spread = float(info.spread) * float(info.point)
    tick_spread = float(tick.ask) - float(tick.bid)
    if tick_spread > 0:
        spread = tick_spread
        spread_source = "tick_ask_bid"
    elif point_spread > 0:
        spread = point_spread
        spread_source = "symbol_spread_points"
    else:
        spread = 0.0
        spread_source = "unknown"
    ref = float(tick.bid) or float(info.bidprice) or 0.0
    unit = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, resolved, 1.0, ref, ref + 1.0)
    unit_source = "order_calc_profit"
    if unit is None or unit <= 0:
        unit = float(info.trade_contract_size)
        unit_source = "trade_contract_size_fallback"
    return {
        "resolved": resolved,
        "digits": int(info.digits),
        "point": float(info.point),
        "spread_price": spread,
        "spread_source": spread_source,
        "symbol_spread_points": int(info.spread),
        "tick_spread": tick_spread,
        "contract_size": float(info.trade_contract_size),
        "volume_min": float(info.volume_min),
        "volume_max": float(info.volume_max),
        "volume_step": float(info.volume_step),
        "unit_per_lot_per_price": float(unit),
        "unit_source": unit_source,
        "currency_profit": str(info.currency_profit),
        "bid": float(tick.bid),
        "ask": float(tick.ask),
        "description": str(info.description),
    }


def gap_report(bars: list[Bar], tf: str) -> dict:
    step = TF_SEC[tf]
    gaps = []
    for i in range(1, len(bars)):
        delta = bars[i].t - bars[i - 1].t
        if delta > step * 1.5:
            gaps.append(delta)
    span = bars[-1].t - bars[0].t if len(bars) > 1 else 0
    expected = int(span / step) + 1 if step else 0
    return {
        "bars": len(bars),
        "first_utc": datetime.fromtimestamp(bars[0].t, timezone.utc).strftime("%Y-%m-%d %H:%M") if bars else None,
        "last_utc": datetime.fromtimestamp(bars[-1].t, timezone.utc).strftime("%Y-%m-%d %H:%M") if bars else None,
        "gap_count": len(gaps),
        "longest_gap_hours": (max(gaps) / 3600.0) if gaps else 0.0,
        "missing_slots_incl_weekends": max(0, expected - len(bars)),
    }


def buy_hold(bars: list[Bar], window_start: int) -> dict | None:
    window = [b for b in bars if b.t >= window_start]
    if len(window) < 2 or window[0].close == 0:
        return None
    ret = window[-1].close / window[0].close - 1.0
    return {
        "first_close": window[0].close,
        "last_close": window[-1].close,
        "return_pct": ret * 100.0,
        "bars": len(window),
    }


def recommend(core_rows: list[dict]) -> str:
    """Kisa pencere paper adayi yapmaz. Net, her iki sembolde ve 2x spreadde ayakta kalmali."""
    if not core_rows:
        return "reject"
    positives = [r for r in core_rows if r["net_pnl"] > 0 and r["stress_2x_spread_net"] > 0]
    if len(positives) < len(core_rows):
        return "reject" if all(r["net_pnl"] <= 0 for r in core_rows) else "continue-testing"
    trades = sum(r["trades"] for r in core_rows)
    if trades < 30:
        return "continue-testing"
    if any((r["profit_factor"] or 0) == "inf" for r in core_rows):
        return "continue-testing"
    if all(isinstance(r["profit_factor"], float) and r["profit_factor"] >= 1.3 for r in core_rows):
        return "continue-testing"
    return "continue-testing"


def main() -> None:
    self_check()
    retrieved = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    attached = attach_terminal()
    acc = mt5.account_info()
    term = mt5.terminal_info()
    offset = server_offset_s()
    account = None
    if acc is not None:
        account = {
            "login": int(acc.login),
            "server": str(acc.server),
            "currency": str(acc.currency),
            "leverage": int(acc.leverage),
            "trade_mode": int(acc.trade_mode),
        }
    variants = (
        "baseline_st_10_3",
        "ha_st_10_3",
        "ha_st_rsi_adx_24s",
        "ha_st_rsi_adx",
        "ha_dual_7_2_10_3",
    )
    report: dict = {
        "retrieved_at": retrieved,
        "attach": attached,
        "terminal_path": str(getattr(term, "path", "")) if term else None,
        "server_utc_offset_sec": offset,
        "account": account,
        "paper_balance": PAPER_BALANCE,
        "risk_pct": RISK_PCT,
        "window_days": 7,
        "core_variant": CORE_NAME,
        "orders_sent": False,
        "commission": "unknown",
        "symbols": {},
    }
    try:
        for app_symbol in SYMBOLS:
            report["symbols"][app_symbol] = {"timeframes": {}}
            resolved_name = None
            costs = None
            for tf in TIMEFRAMES:
                resolved, bars = fetch_bars(app_symbol, tf, offset)
                resolved_name = resolved
                if costs is None:
                    costs = symbol_costs(resolved)
                if not bars:
                    continue
                window_start = bars[-1].t - WINDOW_SEC
                hold = buy_hold(bars, window_start)
                tf_out = {
                    "provenance": gap_report(bars, tf),
                    "window_start_utc": datetime.fromtimestamp(window_start, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "buy_hold": hold,
                    "variants": {},
                }
                for name in variants:
                    base = run_backtest(
                        bars, symbol=app_symbol, variant=name, spread=costs["spread_price"],
                        unit_per_lot=costs["unit_per_lot_per_price"],
                        vmin=costs["volume_min"], vmax=costs["volume_max"], vstep=costs["volume_step"],
                        digits=costs["digits"], window_start=window_start,
                    )
                    stress = run_backtest(
                        bars, symbol=app_symbol, variant=name, spread=costs["spread_price"] * 2.0,
                        unit_per_lot=costs["unit_per_lot_per_price"],
                        vmin=costs["volume_min"], vmax=costs["volume_max"], vstep=costs["volume_step"],
                        digits=costs["digits"], window_start=window_start,
                    )
                    base["stress_2x_spread_net"] = stress["net_pnl"]
                    base["stress_2x_trades"] = stress["trades"]
                    tf_out["variants"][name] = base
                report["symbols"][app_symbol]["resolved"] = resolved_name
                report["symbols"][app_symbol]["costs"] = costs
                report["symbols"][app_symbol]["timeframes"][tf] = tf_out
        core_rows = []
        for app_symbol in SYMBOLS:
            block = report["symbols"][app_symbol]["timeframes"].get(PRIMARY_TF, {})
            core = (block.get("variants") or {}).get(CORE_NAME)
            if core:
                core_rows.append(core)
        report["recommendation"] = recommend(core_rows)
        report["recommendation_basis"] = (
            "7 gun tek penceredir; paper-candidate icin yetmez. "
            "Cekirdek 15m sonucunun isareti ve 2x spread stresi kullanildi."
        )
    finally:
        # Kopru ayni terminali kullaniyor. shutdown() onun IPC bagini dusurur.
        pass

    with open(RESULT_PATH, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        "result": RESULT_PATH,
        "recommendation": report.get("recommendation"),
        "offset_h": offset / 3600.0,
        "account": account,
        "summary": {
            sym: {
                tf: {
                    name: {
                        "trades": v["trades"],
                        "net": round(v["net_pnl"], 2),
                        "gross": round(v["gross_pnl"], 2),
                        "pf": v["profit_factor"],
                        "dd": round(v["max_drawdown"], 2),
                        "win_rate": None if v["win_rate"] is None else round(v["win_rate"], 3),
                        "stress2x": round(v["stress_2x_spread_net"], 2),
                        "exits": v["exit_reasons"],
                    }
                    for name, v in tf_block["variants"].items()
                }
                for tf, tf_block in body["timeframes"].items()
            }
            for sym, body in report["symbols"].items()
        },
    }, ensure_ascii=False, indent=2))


def run_addons() -> None:
    """15dk cekirdek uzerine, pozisyon kapaliyken ek giris denemeleri."""
    self_check()
    attach_terminal()
    offset = server_offset_s()
    addons = ("none", "wick_reentry", "pullback", "ha_resume", "adx15", "rsi_only")
    out: dict = {}
    for app_symbol in SYMBOLS:
        _resolved, bars = fetch_bars(app_symbol, "15m", offset)
        costs = symbol_costs(_resolved)
        window_start = bars[-1].t - WINDOW_SEC
        out[app_symbol] = {}
        for addon in addons:
            result = run_backtest(
                bars, symbol=app_symbol, variant=CORE_NAME, spread=costs["spread_price"],
                unit_per_lot=costs["unit_per_lot_per_price"],
                vmin=costs["volume_min"], vmax=costs["volume_max"], vstep=costs["volume_step"],
                digits=costs["digits"], window_start=window_start, addon=addon,
            )
            out[app_symbol][addon] = {
                "trades": result["trades"],
                "net": round(result["net_pnl"], 2),
                "pf": result["profit_factor"],
                "dd": round(result["max_drawdown"], 2),
                "expectancy": None if result["expectancy"] is None else round(result["expectancy"], 2),
                "addon_signals": result["skipped"]["addon"],
                "buys": result["buy_count"],
                "sells": result["sell_count"],
            }
    print(json.dumps(out, ensure_ascii=False, indent=2))


FX_MENU_SYMBOLS = (
    "BTCUSD", "XAUUSD",
    "EURUSD", "GBPUSD", "USDCAD", "EURCAD", "GBPCAD",
    "EURJPY", "USDJPY", "GBPJPY",
)
# Secim kurali, sonuclar gorulmeden: en az 4 islem, net arti, kar faktoru >= 1.2,
# tepe dusus 1.500 USD'yi asmayacak. Bunlarin icinden en yuksek net.
FX_FILTERS = (
    ("full20_lnny", "full20", (7, 21)),
    ("full20_24s", "full20", None),
    ("adx20_lnny", "adx20", (7, 21)),
    ("rsi_lnny", "rsi", (7, 21)),
    ("st_lnny", "none", (7, 21)),
    ("full25_lnny", "full25", (7, 21)),
    ("adx20_tokyo", "adx20", (0, 16)),
)


def _eligible(row: dict) -> bool:
    pf = row["profit_factor"]
    return (
        row["trades"] >= 4
        and row["net_pnl"] > 0
        and isinstance(pf, float)
        and pf >= 1.2
        and row["max_drawdown"] <= 1500
    )


def run_fx_menu() -> None:
    """Her sembolde ayni HA-ST, farkli giris filtresi. 15dk, 7 gun."""
    self_check()
    attach_terminal()
    offset = server_offset_s()
    report: dict = {
        "offset_h": offset / 3600.0,
        "selection_rule": "trades>=4, net>0, PF>=1.2, maxDD<=1500, sonra en yuksek net",
        "symbols": {},
    }
    for app_symbol in FX_MENU_SYMBOLS:
        try:
            resolved, bars = fetch_bars(app_symbol, "15m", offset)
            costs = symbol_costs(resolved)
        except SystemExit as exc:
            report["symbols"][app_symbol] = {"error": str(exc)}
            print(f"[ATLANDI] {app_symbol}: {exc}", file=sys.stderr)
            continue
        window_start = bars[-1].t - WINDOW_SEC
        hold = buy_hold(bars, window_start)
        cells = {}
        for name, mode, span in FX_FILTERS:
            result = run_backtest(
                bars, symbol=app_symbol, variant=CORE_NAME, spread=costs["spread_price"],
                unit_per_lot=costs["unit_per_lot_per_price"],
                vmin=costs["volume_min"], vmax=costs["volume_max"], vstep=costs["volume_step"],
                digits=costs["digits"], window_start=window_start,
                entry_filter=mode, session_span=span,
            )
            cells[name] = {
                "trades": result["trades"],
                "net": round(result["net_pnl"], 2),
                "pf": result["profit_factor"] if not isinstance(result["profit_factor"], float) else round(result["profit_factor"], 3),
                "dd": round(result["max_drawdown"], 2),
                "expectancy": None if result["expectancy"] is None else round(result["expectancy"], 2),
                "win_rate": None if result["win_rate"] is None else round(result["win_rate"], 3),
                "buys": result["buy_count"],
                "sells": result["sell_count"],
                "eligible": _eligible(result),
            }
        picked = None
        best_net = None
        for name, cell in cells.items():
            if not cell["eligible"]:
                continue
            if best_net is None or cell["net"] > best_net:
                best_net = cell["net"]
                picked = name
        report["symbols"][app_symbol] = {
            "resolved": resolved,
            "spread": costs["spread_price"],
            "unit_per_lot_per_price": costs["unit_per_lot_per_price"],
            "bars": gap_report(bars, "15m"),
            "buy_hold_pct": None if hold is None else round(hold["return_pct"], 2),
            "picked": picked,
            "filters": cells,
        }
    path = os.path.join(SCRIPT_DIR, "ha_supertrend_fx_filters_7d.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    brief = {
        sym: {
            "picked": body.get("picked"),
            "hold_pct": body.get("buy_hold_pct"),
            "spread": body.get("spread"),
            "filters": {
                name: {"n": cell["trades"], "net": cell["net"], "pf": cell["pf"], "dd": cell["dd"]}
                for name, cell in body.get("filters", {}).items()
            },
        }
        for sym, body in report["symbols"].items()
    }
    print(json.dumps({"file": path, "symbols": brief}, ensure_ascii=False, indent=2))


# 7 gunde karli gorulen kilitli kurallar. 14 hafta ici gun bunlari yeniden secmeyecek.
LOCKED_14 = (
    ("BTCUSD", "full20", None),
    ("XAUUSD", "full20", (7, 21)),
    ("EURUSD", "full20", None),
    ("GBPUSD", "full20", None),
)


def weekday_window_start(last_ts: int, weekdays: int) -> int:
    """Son mumun UTC gunu dahil, geriye `weekdays` adet Pazartesi-Cuma sayar."""
    from datetime import timedelta as _td
    day = datetime.fromtimestamp(last_ts, timezone.utc).date()
    left = weekdays
    while True:
        if day.weekday() < 5:
            left -= 1
            if left == 0:
                break
        day -= _td(days=1)
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return int(start.timestamp())


def _trade_ts(entry_utc: str) -> int:
    return int(datetime.strptime(entry_utc, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


def _slice_stats(trades: list[dict], start: int, end: int | None) -> dict:
    chosen = []
    for trade in trades:
        ts = _trade_ts(trade["entry_utc"])
        if ts < start:
            continue
        if end is not None and ts >= end:
            continue
        chosen.append(trade)
    nets = [float(trade["net"]) for trade in chosen]
    wins = [value for value in nets if value > 0]
    losses = [value for value in nets if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trades": len(chosen),
        "net": round(sum(nets), 2),
        "pf": None if not chosen else ("inf" if gross_loss == 0 and gross_profit > 0 else (round(gross_profit / gross_loss, 3) if gross_loss else None)),
        "buys": sum(1 for trade in chosen if trade["side"] == "BUY"),
        "sells": sum(1 for trade in chosen if trade["side"] == "SELL"),
    }


def run_14_weekdays() -> None:
    """Karli bes sembol, kilitli filtre, 14 hafta ici gun."""
    self_check()
    attach_terminal()
    offset = server_offset_s()
    report: dict = {"offset_h": offset / 3600.0, "symbols": {}}
    for app_symbol, mode, span in LOCKED_14:
        resolved, bars = fetch_bars(app_symbol, "15m", offset, lookback_days=55)
        costs = symbol_costs(resolved)
        last_ts = bars[-1].t
        window_start = weekday_window_start(last_ts, 14)
        seen_start = last_ts - WINDOW_SEC
        hold = buy_hold(bars, window_start)
        result = run_backtest(
            bars, symbol=app_symbol, variant=CORE_NAME, spread=costs["spread_price"],
            unit_per_lot=costs["unit_per_lot_per_price"],
            vmin=costs["volume_min"], vmax=costs["volume_max"], vstep=costs["volume_step"],
            digits=costs["digits"], window_start=window_start,
            entry_filter=mode, session_span=span,
        )
        stress = run_backtest(
            bars, symbol=app_symbol, variant=CORE_NAME, spread=costs["spread_price"] * 2.0,
            unit_per_lot=costs["unit_per_lot_per_price"],
            vmin=costs["volume_min"], vmax=costs["volume_max"], vstep=costs["volume_step"],
            digits=costs["digits"], window_start=window_start,
            entry_filter=mode, session_span=span,
        )
        weekdays = []
        for bar in bars:
            if bar.t < window_start:
                continue
            day = datetime.fromtimestamp(bar.t, timezone.utc).date()
            if day.weekday() < 5 and day not in weekdays:
                weekdays.append(day)
        report["symbols"][app_symbol] = {
            "filter": mode,
            "session_utc": None if span is None else f"{span[0]:02d}-{span[1]:02d}",
            "spread": costs["spread_price"],
            "spread_source": costs["spread_source"],
            "window_start_utc": datetime.fromtimestamp(window_start, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "last_utc": datetime.fromtimestamp(last_ts, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "weekdays_with_bars": len(weekdays),
            "buy_hold_pct": None if hold is None else round(hold["return_pct"], 2),
            "all": {
                "trades": result["trades"],
                "net": round(result["net_pnl"], 2),
                "pf": result["profit_factor"] if not isinstance(result["profit_factor"], float) else round(result["profit_factor"], 3),
                "dd": round(result["max_drawdown"], 2),
                "expectancy": None if result["expectancy"] is None else round(result["expectancy"], 2),
                "buys": result["buy_count"],
                "sells": result["sell_count"],
                "stress_2x": round(stress["net_pnl"], 2),
            },
            "earlier_weekdays": _slice_stats(result["trade_list"], window_start, seen_start),
            "selection_7d": _slice_stats(result["trade_list"], seen_start, None),
        }
    path = os.path.join(SCRIPT_DIR, "ha_supertrend_14wd.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, **report}, ensure_ascii=False, indent=2))


def run_60_days() -> None:
    """Kilitli filtreler, son mumdan geriye 60 takvim gunu. Filtre yeniden secilmez."""
    self_check()
    attach_terminal()
    offset = server_offset_s()
    report: dict = {"offset_h": offset / 3600.0, "requested_calendar_days": 60, "symbols": {}}
    for app_symbol, mode, span in LOCKED_14:
        resolved, bars = fetch_bars(app_symbol, "15m", offset, lookback_days=100)
        costs = symbol_costs(resolved)
        last_ts = bars[-1].t
        window_start = last_ts - 60 * 86400
        seen_start = last_ts - WINDOW_SEC
        history_short = bars[0].t > window_start
        hold = buy_hold(bars, window_start)
        result = run_backtest(
            bars, symbol=app_symbol, variant=CORE_NAME, spread=costs["spread_price"],
            unit_per_lot=costs["unit_per_lot_per_price"],
            vmin=costs["volume_min"], vmax=costs["volume_max"], vstep=costs["volume_step"],
            digits=costs["digits"], window_start=window_start,
            entry_filter=mode, session_span=span,
        )
        stress = run_backtest(
            bars, symbol=app_symbol, variant=CORE_NAME, spread=max(costs["spread_price"], 0.0) * 2.0,
            unit_per_lot=costs["unit_per_lot_per_price"],
            vmin=costs["volume_min"], vmax=costs["volume_max"], vstep=costs["volume_step"],
            digits=costs["digits"], window_start=window_start,
            entry_filter=mode, session_span=span,
        )
        in_window = [bar for bar in bars if bar.t >= window_start]
        weekdays = []
        for bar in in_window:
            day = datetime.fromtimestamp(bar.t, timezone.utc).date()
            if day.weekday() < 5 and (not weekdays or weekdays[-1] != day):
                weekdays.append(day)
        first_ts = in_window[0].t if in_window else bars[0].t
        report["symbols"][app_symbol] = {
            "filter": mode,
            "session_utc": None if span is None else f"{span[0]:02d}-{span[1]:02d}",
            "spread": costs["spread_price"],
            "spread_source": costs["spread_source"],
            "history_reaches_window": not history_short,
            "window_start_utc": datetime.fromtimestamp(window_start, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "first_bar_utc": datetime.fromtimestamp(first_ts, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "last_utc": datetime.fromtimestamp(last_ts, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "calendar_days": round((last_ts - first_ts) / 86400, 1),
            "weekdays_with_bars": len(weekdays),
            "buy_hold_pct": None if hold is None else round(hold["return_pct"], 2),
            "all": {
                "trades": result["trades"],
                "net": round(result["net_pnl"], 2),
                "pf": result["profit_factor"] if not isinstance(result["profit_factor"], float) else round(result["profit_factor"], 3),
                "dd": round(result["max_drawdown"], 2),
                "expectancy": None if result["expectancy"] is None else round(result["expectancy"], 2),
                "win_rate": None if result["win_rate"] is None else round(result["win_rate"], 3),
                "buys": result["buy_count"],
                "sells": result["sell_count"],
                "stress_2x": round(stress["net_pnl"], 2),
            },
            "before_selection_week": _slice_stats(result["trade_list"], window_start, seen_start),
            "selection_7d": _slice_stats(result["trade_list"], seen_start, None),
        }
    path = os.path.join(SCRIPT_DIR, "ha_supertrend_60d.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, **report}, ensure_ascii=False, indent=2))


def htf_side(m15: list[Bar], htf: list[Bar], htf_sec: int) -> list[int]:
    """Kapanmis ust zaman HA-ST yonu. +1 alis, -1 satis. Ust mum kapanmadan kullanilmaz."""
    _st, direction = supertrend(heikin_ashi(htf), 10, 3.0)
    out = [0] * len(m15)
    j = 0
    for i, bar in enumerate(m15):
        while j + 1 < len(htf) and htf[j + 1].t + htf_sec <= bar.t:
            j += 1
        if j < len(htf) and htf[j].t + htf_sec <= bar.t and direction[j] != 0:
            out[i] = 1 if direction[j] == -1 else -1
    return out


def merge_bias(parts: list[list[int]]) -> list[int]:
    merged: list[int] = []
    for vals in zip(*parts):
        if any(value == 0 for value in vals) or len(set(vals)) != 1:
            merged.append(0)
        else:
            merged.append(vals[0])
    return merged


# Altin ilaveleri, 60 gun sonucu gorulmeden kilitlendi. Kisa yon dayatmasi yok.
GOLD_60_MENU = (
    ("full20_lnny", "full20", (7, 21), None),
    ("full20_london", "full20", (7, 16), None),
    ("full20_overlap", "full20", (12, 16), None),
    ("full25_overlap", "full25", (12, 16), None),
    ("adx25_overlap", "adx25", (12, 16), None),
    ("h1_full20_lnny", "full20", (7, 21), "h1"),
    ("h4_full20_lnny", "full20", (7, 21), "h4"),
    ("h4_full20_overlap", "full20", (12, 16), "h4"),
    ("dxy_full20_lnny", "full20", (7, 21), "dxy"),
    ("h4_dxy_overlap", "full20", (12, 16), "h4_dxy"),
)


def run_gold_60() -> None:
    """XAUUSD 60 gun. USDJPY yok. Ilaveler ayni pencerede siralanir."""
    self_check()
    attach_terminal()
    offset = server_offset_s()
    bars_15 = fetch_bars("XAUUSD", "15m", offset, lookback_days=100)[1]
    bars_1h = fetch_bars("XAUUSD", "1h", offset, lookback_days=120)[1]
    bars_4h = fetch_bars("XAUUSD", "4h", offset, lookback_days=160)[1]
    costs = symbol_costs("XAUUSD")
    last_ts = bars_15[-1].t
    window_start = last_ts - 60 * 86400
    h1 = htf_side(bars_15, bars_1h, TF_SEC["1h"])
    h4 = htf_side(bars_15, bars_4h, TF_SEC["4h"])
    dxy_note = "yok"
    dxy_bias: list[int] | None = None
    try:
        dxy_resolved, dxy_bars = fetch_bars("DXY", "1h", offset, lookback_days=120)
        raw_dxy = htf_side(bars_15, dxy_bars, TF_SEC["1h"])
        dxy_bias = [-side if side else 0 for side in raw_dxy]
        dxy_note = dxy_resolved
    except SystemExit as exc:
        dxy_note = str(exc)
    biases = {
        "h1": h1,
        "h4": h4,
        "dxy": dxy_bias,
        "h4_dxy": None if dxy_bias is None else merge_bias([h4, dxy_bias]),
    }
    cells = []
    for name, mode, span, key in GOLD_60_MENU:
        if key is not None and biases.get(key) is None:
            cells.append({"name": name, "error": "DXY verisi yok"})
            continue
        result = run_backtest(
            bars_15, symbol="XAUUSD", variant=CORE_NAME, spread=costs["spread_price"],
            unit_per_lot=costs["unit_per_lot_per_price"],
            vmin=costs["volume_min"], vmax=costs["volume_max"], vstep=costs["volume_step"],
            digits=costs["digits"], window_start=window_start,
            entry_filter=mode, session_span=span, bias=None if key is None else biases[key],
        )
        pf = result["profit_factor"]
        pf_out = pf if not isinstance(pf, float) else round(pf, 3)
        eligible = (
            result["trades"] >= 8
            and result["net_pnl"] > 0
            and isinstance(pf, float)
            and pf >= 1.2
            and result["max_drawdown"] <= 1500
        )
        cells.append({
            "name": name,
            "trades": result["trades"],
            "net": round(result["net_pnl"], 2),
            "pf": pf_out,
            "dd": round(result["max_drawdown"], 2),
            "expectancy": None if result["expectancy"] is None else round(result["expectancy"], 2),
            "win_rate": None if result["win_rate"] is None else round(result["win_rate"], 3),
            "buys": result["buy_count"],
            "sells": result["sell_count"],
            "bias_skips": result["skipped"].get("bias", 0),
            "eligible": eligible,
        })
    ranked = sorted(
        [cell for cell in cells if "net" in cell],
        key=lambda cell: cell["net"],
        reverse=True,
    )
    eligible = [cell for cell in ranked if cell["eligible"]]
    winner = eligible[0]["name"] if eligible else None
    report = {
        "symbol": "XAUUSD",
        "usd_jpy": "cikarildi",
        "dxy": dxy_note,
        "spread": costs["spread_price"],
        "window_start_utc": datetime.fromtimestamp(window_start, timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "last_utc": datetime.fromtimestamp(last_ts, timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "selection_rule": "en az 8 islem, net>0, PF>=1.2, dusus<=1500, sonra en yuksek net",
        "winner": winner,
        "ranked": ranked,
    }
    path = os.path.join(SCRIPT_DIR, "ha_supertrend_xau_60_addons.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if "--gold60" in sys.argv:
        run_gold_60()
    elif "--d60" in sys.argv:
        run_60_days()
    elif "--wd14" in sys.argv:
        run_14_weekdays()
    elif "--fx" in sys.argv:
        run_fx_menu()
    elif "--addons" in sys.argv:
        run_addons()
    else:
        main()
