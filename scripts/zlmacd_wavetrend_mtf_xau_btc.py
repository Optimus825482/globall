#!/usr/bin/env python3
"""Zero-Lag MACD + WaveTrend, coklu zaman dilimi. XAUUSD ve BTCUSD.

Formuller ve kural listesi kosudan once kilitlendi. Kazanan, yalnizca
egitim haftalarinin kapanis bakiyesine gore secilir. Son 4 hafta bir kez
okunur; oradan kural degistirilmez.

Zero-Lag MACD: DEMA(12) - DEMA(26), sinyal EMA(9).
  Canli tarayicidaki _zl_macd_status ile ayni yapi.

WaveTrend (LazyBear): kanal 10, ortalama 21, sinyal SMA 4.
  CI = (hlc3 - EMA) / (0.015 * EMA(|hlc3-EMA|)).
  Asiri satim -60, asiri alim +60.

Hizli WaveTrend: kanal 7, ortalama 1, sinyal SMA 4, esik 45.
  Canli _wavetrend varsayilani. Yalnizca tek zaman dilimi karsilastirmasi.

Giris 15 dk kapanmis mum. 1s ve 4s yalnizca kapanmis bar.
  15 dk bar acilis t, kapanis t+900.
  Ust dilim barinin kapanisi (acilis + dilim) bu kapanistan once olmali.
Giris bir sonraki 15 dk acilisinda. Giris mumunun high/low stop ve hedefe bakar.
Stop 1.2 ATR(14), kalkmaz, gevsetilmez. 1R lehte gorulurse stop girise cekilir.
Hedef 2R. Ayni mumda stop ve hedef birlikteyse stop sayilir.
Ust uste 2 stop: 2 adet 15 dk bar yeni islem yok.
XAUUSD yeni islem 07:00-21:00 UTC. BTCUSD tum saatler.
Risk, haftalik kasanin %2'si. Her hafta 1000, terminal kar para birimi.
Emir gonderilmez. Spread anlik tick; ek komisyon bilinmiyor, sifir yazilmaz.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = ("XAUUSD", "BTCUSD")
ENTRY_TF = "15m"
ENTRY_SEC = 900
HTF = (("1h", 3600), ("4h", 14400))
LOOKBACK_DAYS = 140
TRAIN_WEEKS = 8
TEST_WEEKS = 4
RISK = 0.02
RR = 2.0
STOP_ATR = 1.2
MIN_TRADES_PER_SYMBOL = 4
PAPER_MIN_TRADES = 20
PAPER_MIN_PF = 1.3
WT_OS = -60.0
WT_OB = 60.0
WT_FAST_OS = -45.0
WT_FAST_OB = 45.0
XAU_HOURS = (7, 21)
RULES = (
    "baseline_macd15",
    "zl15",
    "wt10_15",
    "wt7_15",
    "zl15_wt10",
    "zl15_h1",
    "mtf_ikisi",
    "oncu_erken",
)


def ema_on_sparse(values: list[float | None], period: int) -> list[float | None]:
    idx = [i for i, value in enumerate(values) if value is not None]
    compact = wk.ema([values[i] for i in idx], period)
    out: list[float | None] = [None] * len(values)
    for pos, i in enumerate(idx):
        out[i] = compact[pos]
    return out


def dema(values: list[float], period: int) -> list[float | None]:
    first = wk.ema(values, period)
    second = ema_on_sparse(first, period)
    out: list[float | None] = [None] * len(values)
    for i, (a, b) in enumerate(zip(first, second)):
        if a is not None and b is not None:
            out[i] = 2.0 * a - b
    return out


def macd_pair(closes: list[float], fast: int, slow: int, signal: int, zero_lag: bool) -> tuple[list, list]:
    if zero_lag:
        line = [None if a is None or b is None else a - b for a, b in zip(dema(closes, fast), dema(closes, slow))]
    else:
        line = [None if a is None or b is None else a - b for a, b in zip(wk.ema(closes, fast), wk.ema(closes, slow))]
    return line, ema_on_sparse(line, signal)


def wavetrend(bars: list[eng.Bar], channel: int, average: int, signal: int) -> tuple[list, list]:
    ap = [(bar.high + bar.low + bar.close) / 3.0 for bar in bars]
    esa = wk.ema(ap, channel)
    dev_raw: list[float | None] = [None if base is None else abs(price - base) for price, base in zip(ap, esa)]
    dev = ema_on_sparse(dev_raw, channel)
    ci: list[float | None] = [None] * len(bars)
    for i in range(len(bars)):
        if esa[i] is None or dev[i] in (None, 0.0):
            continue
        ci[i] = (ap[i] - esa[i]) / (0.015 * dev[i])
    wt1 = ema_on_sparse(ci, average)
    wt2: list[float | None] = [None] * len(bars)
    for i in range(signal - 1, len(bars)):
        window = wt1[i - signal + 1:i + 1]
        if any(value is None for value in window):
            continue
        wt2[i] = sum(window) / signal
    return wt1, wt2


def cross_up(fast: list, slow: list, i: int) -> bool:
    if i <= 0:
        return False
    a, b, c, d = fast[i - 1], slow[i - 1], fast[i], slow[i]
    return None not in (a, b, c, d) and a <= b and c > d


def cross_down(fast: list, slow: list, i: int) -> bool:
    if i <= 0:
        return False
    a, b, c, d = fast[i - 1], slow[i - 1], fast[i], slow[i]
    return None not in (a, b, c, d) and a >= b and c < d


def side_of(fast: list, slow: list, i: int) -> int:
    if i < 0 or fast[i] is None or slow[i] is None or fast[i] == slow[i]:
        return 0
    return 1 if fast[i] > slow[i] else -1


def align(entry: list[eng.Bar], higher: list[eng.Bar], entry_sec: int, higher_sec: int) -> list[int]:
    """Her giris bari icin kullanilabilir son kapanmis ust bar indeksi."""
    if not higher:
        return [-1] * len(entry)
    out = [-1] * len(entry)
    j = 0
    for i, bar in enumerate(entry):
        limit = bar.t + entry_sec - higher_sec
        while j + 1 < len(higher) and higher[j + 1].t <= limit:
            j += 1
        if higher[j].t <= limit:
            out[i] = j
    return out


def prepare(bars: list[eng.Bar]) -> dict:
    closes = [bar.close for bar in bars]
    macd, macd_sig = macd_pair(closes, 12, 26, 9, False)
    zl, zl_sig = macd_pair(closes, 12, 26, 9, True)
    wt1, wt2 = wavetrend(bars, 10, 21, 4)
    f1, f2 = wavetrend(bars, 7, 1, 4)
    _plus, _minus, adx = eng.adx_dmi(bars, 14)
    return {
        "bars": bars,
        "macd": macd,
        "macd_sig": macd_sig,
        "zl": zl,
        "zl_sig": zl_sig,
        "wt1": wt1,
        "wt2": wt2,
        "f1": f1,
        "f2": f2,
        "atr": wk.atr(bars, 14),
        "adx": adx,
    }


def stop_for(bars: list[eng.Bar], atr: list, i: int, side: int) -> float | None:
    if atr[i] is None or atr[i] <= 0:
        return None
    if side == 1:
        return bars[i].close - STOP_ATR * atr[i]
    return bars[i].close + STOP_ATR * atr[i]


def signals_for(rule: str, entry: dict, h1: dict, h4: dict, map1: list[int], map4: list[int]) -> list:
    bars = entry["bars"]
    out: list[tuple[int, float] | None] = [None] * len(bars)
    for i in range(1, len(bars)):
        side = 0
        j1, j4 = map1[i], map4[i]
        zl_up = cross_up(entry["zl"], entry["zl_sig"], i)
        zl_dn = cross_down(entry["zl"], entry["zl_sig"], i)
        if rule == "baseline_macd15":
            if cross_up(entry["macd"], entry["macd_sig"], i):
                side = 1
            elif cross_down(entry["macd"], entry["macd_sig"], i):
                side = -1
        elif rule == "zl15":
            side = 1 if zl_up else -1 if zl_dn else 0
        elif rule == "wt10_15":
            if cross_up(entry["wt1"], entry["wt2"], i) and entry["wt1"][i] <= WT_OS:
                side = 1
            elif cross_down(entry["wt1"], entry["wt2"], i) and entry["wt1"][i] >= WT_OB:
                side = -1
        elif rule == "wt7_15":
            if cross_up(entry["f1"], entry["f2"], i) and entry["f1"][i] <= WT_FAST_OS:
                side = 1
            elif cross_down(entry["f1"], entry["f2"], i) and entry["f1"][i] >= WT_FAST_OB:
                side = -1
        elif rule == "zl15_wt10":
            if zl_up and side_of(entry["wt1"], entry["wt2"], i) == 1:
                side = 1
            elif zl_dn and side_of(entry["wt1"], entry["wt2"], i) == -1:
                side = -1
        elif rule == "zl15_h1":
            if j1 < 0:
                continue
            h1_zl = side_of(h1["zl"], h1["zl_sig"], j1)
            h1_wt = side_of(h1["wt1"], h1["wt2"], j1)
            if zl_up and h1_zl == 1 and h1_wt == 1:
                side = 1
            elif zl_dn and h1_zl == -1 and h1_wt == -1:
                side = -1
        elif rule == "mtf_ikisi":
            if j1 < 0 or j4 < 0:
                continue
            if side_of(h4["zl"], h4["zl_sig"], j4) == 1 and side_of(h1["zl"], h1["zl_sig"], j1) == 1 and side_of(h1["wt1"], h1["wt2"], j1) == 1 and zl_up:
                wt_ok = side_of(entry["wt1"], entry["wt2"], i) == 1 or (
                    cross_up(entry["wt1"], entry["wt2"], i) and entry["wt1"][i] <= WT_OS
                )
                if wt_ok:
                    side = 1
            elif side_of(h4["zl"], h4["zl_sig"], j4) == -1 and side_of(h1["zl"], h1["zl_sig"], j1) == -1 and side_of(h1["wt1"], h1["wt2"], j1) == -1 and zl_dn:
                wt_ok = side_of(entry["wt1"], entry["wt2"], i) == -1 or (
                    cross_down(entry["wt1"], entry["wt2"], i) and entry["wt1"][i] >= WT_OB
                )
                if wt_ok:
                    side = -1
        elif rule == "oncu_erken":
            if j1 < 0:
                continue
            hist_now = None if entry["zl"][i] is None or entry["zl_sig"][i] is None else entry["zl"][i] - entry["zl_sig"][i]
            hist_prev = None if entry["zl"][i - 1] is None or entry["zl_sig"][i - 1] is None else entry["zl"][i - 1] - entry["zl_sig"][i - 1]
            if hist_now is None or hist_prev is None:
                continue
            if side_of(h1["zl"], h1["zl_sig"], j1) == 1 and cross_up(entry["wt1"], entry["wt2"], i) and entry["wt1"][i] <= WT_OS and hist_now > hist_prev:
                side = 1
            elif side_of(h1["zl"], h1["zl_sig"], j1) == -1 and cross_down(entry["wt1"], entry["wt2"], i) and entry["wt1"][i] >= WT_OB and hist_now < hist_prev:
                side = -1
        if side == 0:
            continue
        level = stop_for(bars, entry["atr"], i, side)
        if level is None:
            continue
        if side == 1 and level >= bars[i].close:
            continue
        if side == -1 and level <= bars[i].close:
            continue
        out[i] = (side, level)
    return out


def simulate(bars, series, spread, unit, vmin, vmax, vstep, start, end, risk, hours, adx=None) -> dict:
    cash = wk.START_CASH
    peak = cash
    max_dd = 0.0
    pos = None
    pending = None
    trades = []
    losses_in_row = 0
    quiet_until = -1
    for i, bar in enumerate(bars):
        if bar.t < start:
            continue
        if bar.t > end:
            if pos is not None:
                _realize(trades, pos, bar.open, "pencere", spread, unit, cash)
                cash += trades[-1]["pnl"]
                pos = None
            break
        hour = datetime.fromtimestamp(bar.t, timezone.utc).hour
        hour_ok = hours is None or hours[0] <= hour < hours[1]
        if pending is not None and pos is None and i > quiet_until and hour_ok:
            pos = _open(pending, bar.open, spread, unit, vmin, vmax, vstep, cash, risk, i, bar.t)
        pending = None
        if pos is not None:
            closed = _manage(bar, pos, spread)
            if closed is not None:
                raw_exit, reason = closed
                _realize(trades, pos, raw_exit, reason, spread, unit, cash)
                cash += trades[-1]["pnl"]
                if reason == "stop":
                    losses_in_row += 1
                    if losses_in_row >= 2:
                        quiet_until = i + 2
                        losses_in_row = 0
                else:
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
        if pos is None and i < len(series) and series[i] is not None and bar.t < end and i > quiet_until:
            pending = (series[i], None if adx is None else adx[i])
    wins = [row["pnl"] for row in trades if row["pnl"] > 0]
    losses = [row["pnl"] for row in trades if row["pnl"] < 0]
    gross_win = sum(wins)
    gross_loss = sum(losses)
    return {
        "friday": round(cash, 2),
        "pnl": round(cash - wk.START_CASH, 2),
        "hit": cash >= wk.TARGET,
        "trades": len(trades),
        "winners": len(wins),
        "dd": round(max_dd, 2),
        "pf": None if not losses or gross_loss == 0 else round(gross_win / abs(gross_loss), 3),
        "expectancy": None if not trades else round(sum(row["pnl"] for row in trades) / len(trades), 4),
        "reasons": _count(row["reason"] for row in trades),
        "log": trades,
    }


def _open(pending, raw: float, spread: float, unit: float, vmin: float, vmax: float, vstep: float, cash: float, risk: float, i: int, entry_t: int):
    order, adx = pending
    side, stop_line = order
    if side == 1:
        net = raw + spread
        stop = stop_line
        risk_px = net - stop
        tp = net + RR * risk_px
    else:
        net = raw
        stop = stop_line + spread
        risk_px = stop - net
        tp = net - spread - RR * risk_px
    if risk_px <= spread or unit <= 0 or cash <= 0:
        return None
    volume = eng.floor_volume(cash * risk / (risk_px * unit), vmin, vmax, vstep)
    if volume is None:
        return None
    return {
        "side": side,
        "net": net,
        "stop": stop,
        "tp": tp,
        "risk_px": risk_px,
        "vol": volume,
        "i": i,
        "entry_t": entry_t,
        "adx": adx,
        "be": False,
    }


def _manage(bar: eng.Bar, pos: dict, spread: float) -> tuple[float, str] | None:
    side = pos["side"]
    if side == 1:
        stop_hit = bar.low <= pos["stop"]
        tp_hit = bar.high >= pos["tp"]
        trigger = pos["net"] + pos["risk_px"]
        be_raw = pos["net"]
        tagged = bar.high >= trigger
        be_touched = bar.low <= be_raw
    else:
        stop_hit = bar.high >= pos["stop"] - spread
        tp_hit = bar.low <= pos["tp"]
        trigger = pos["net"] - spread - pos["risk_px"]
        be_raw = pos["net"] - spread
        tagged = bar.low <= trigger
        be_touched = bar.high >= be_raw
    if stop_hit:
        reason = "basabas" if pos["be"] else "stop"
        if side == 1:
            return (bar.open if bar.open < pos["stop"] else pos["stop"], reason)
        level = pos["stop"] - spread
        return (bar.open if bar.open > level else level, reason)
    if tp_hit:
        if side == 1:
            return (bar.open if bar.open > pos["tp"] else pos["tp"], "hedef")
        return (bar.open if bar.open < pos["tp"] else pos["tp"], "hedef")
    if tagged and be_touched and pos["be"]:
        return (be_raw, "basabas")
    if tagged and not pos["be"]:
        if be_touched:
            return (be_raw, "basabas")
        if side == 1:
            pos["stop"] = max(pos["stop"], pos["net"])
        else:
            pos["stop"] = min(pos["stop"], pos["net"])
        pos["be"] = True
    return None


def _realize(trades: list, pos: dict, raw_exit: float, reason: str, spread: float, unit: float, cash_before: float) -> None:
    if pos["side"] == 1:
        pnl = (raw_exit - pos["net"]) * unit * pos["vol"]
    else:
        pnl = (pos["net"] - (raw_exit + spread)) * unit * pos["vol"]
    risk_cash = pos["risk_px"] * pos["vol"] * unit
    trades.append({
        "side": "al" if pos["side"] == 1 else "sat",
        "entry_t": pos["entry_t"],
        "pnl": round(pnl, 4),
        "reason": reason,
        "r": None if risk_cash == 0 else round(pnl / risk_cash, 3),
        "adx": None if pos["adx"] is None else round(float(pos["adx"]), 2),
        "regime": _regime(pos["adx"]),
        "cash_before": round(cash_before, 2),
    })


def _regime(adx) -> str:
    if adx is None:
        return "bilinmiyor"
    if adx >= 25:
        return "trend"
    if adx < 20:
        return "testere"
    return "ara"


def _count(items) -> dict:
    out: dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return out


def summarize_weeks(rows: list[dict]) -> dict:
    pnls = [row["pnl"] for row in rows]
    trades = sum(row["trades"] for row in rows)
    winners = sum(row["winners"] for row in rows)
    return {
        "weeks": len(rows),
        "sum_pnl": round(sum(pnls), 2),
        "min_friday": min(row["friday"] for row in rows) if rows else None,
        "hits": sum(1 for row in rows if row["hit"]),
        "trades": trades,
        "winners": winners,
        "win_rate": None if trades == 0 else round(winners / trades, 3),
        "max_week_dd": max((row["dd"] for row in rows), default=None),
    }


def choose(train: dict) -> dict:
    best_name = None
    best_score = None
    for name in RULES:
        per_symbol = []
        ok = True
        for symbol in SYMBOLS:
            body = train[symbol][name]
            if body["trades"] < MIN_TRADES_PER_SYMBOL:
                ok = False
                break
            per_symbol.append(body["sum_pnl"])
        if not ok:
            continue
        score = min(per_symbol)
        if best_score is None or score > best_score:
            best_score = score
            best_name = name
    return {
        "rule": best_name,
        "train_min_pnl": best_score,
        "eligible": best_name is not None and best_score is not None and best_score > 0,
    }


def run_rule(pack, costs, hours, rule, weeks, spread_mult: float) -> list[dict]:
    series = pack["signals"][rule]
    rows = []
    for start, end, label in weeks:
        row = simulate(
            pack["entry"]["bars"], series, costs["spread_price"] * spread_mult,
            costs["unit_per_lot_per_price"], costs["volume_min"], costs["volume_max"],
            costs["volume_step"], start, end, RISK, hours, pack["entry"]["adx"],
        )
        rows.append({"week": label, **{key: row[key] for key in ("friday", "pnl", "hit", "trades", "winners", "dd", "pf", "expectancy", "reasons")}})
    return rows


def continuous(pack, costs, hours, rule, start, end, spread_mult: float) -> dict:
    series = pack["signals"][rule]
    row = simulate(
        pack["entry"]["bars"], series, costs["spread_price"] * spread_mult,
        costs["unit_per_lot_per_price"], costs["volume_min"], costs["volume_max"],
        costs["volume_step"], start, end, RISK, hours, pack["entry"]["adx"],
    )
    regimes: dict[str, dict] = {}
    for trade in row["log"]:
        bucket = regimes.setdefault(trade["regime"], {"trades": 0, "pnl": 0.0, "winners": 0})
        bucket["trades"] += 1
        bucket["pnl"] = round(bucket["pnl"] + trade["pnl"], 2)
        bucket["winners"] += int(trade["pnl"] > 0)
    public = {key: row[key] for key in ("friday", "pnl", "trades", "winners", "dd", "pf", "expectancy", "reasons")}
    public["win_rate"] = None if row["trades"] == 0 else round(row["winners"] / row["trades"], 3)
    public["regimes"] = regimes
    public["trades_detail"] = row["log"]
    return public


def recommend(picked: dict, test_books: dict, stress: dict) -> str:
    if not picked["eligible"]:
        return "reject"
    books = [test_books[symbol] for symbol in SYMBOLS]
    trades = sum(book["trades"] for book in books)
    both_positive = all(book["pnl"] > 0 for book in books)
    stress_ok = all(stress[symbol]["pnl"] > 0 for symbol in SYMBOLS)

    def pf_ok(book: dict) -> bool:
        if book["trades"] == 0 or book["pnl"] <= 0:
            return False
        if book["pf"] is None:
            return book["winners"] == book["trades"]
        return book["pf"] >= PAPER_MIN_PF

    if both_positive and trades >= PAPER_MIN_TRADES and all(pf_ok(book) for book in books) and stress_ok:
        return "paper-candidate"
    if both_positive and trades >= 8:
        return "continue-testing"
    return "reject"


def self_check() -> None:
    entry = [eng.Bar(t, 1, 1, 1, 1) for t in range(0, 48 * 900, 900)]
    higher = [eng.Bar(t, 1, 1, 1, 1) for t in range(0, 48 * 900, 3600)]
    idx = align(entry, higher, 900, 3600)
    at_1100 = next(i for i, bar in enumerate(entry) if bar.t == 11 * 3600)
    at_1000 = next(i for i, bar in enumerate(entry) if bar.t == 10 * 3600)
    assert higher[idx[at_1100]].t == 10 * 3600
    assert higher[idx[at_1000]].t == 9 * 3600
    flat = dema([5.0] * 80, 10)
    assert flat[-1] is not None and abs(flat[-1] - 5.0) < 1e-6
    fast = [0, 0, 1, 2]
    slow = [0, 1, 1, 1]
    assert cross_up(fast, slow, 3) and not cross_up(fast, slow, 2)


def main() -> None:
    self_check()
    eng.attach_terminal()
    offset = eng.server_offset_s()
    retrieved = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    anchor_name, anchor = eng.fetch_bars("EURUSD", ENTRY_TF, offset, lookback_days=LOOKBACK_DAYS)
    cal = wk.weeks_ending(anchor[-1].t, TRAIN_WEEKS + TEST_WEEKS)
    train_weeks, test_weeks = cal[:TRAIN_WEEKS], cal[TRAIN_WEEKS:]
    packs = {}
    costs = {}
    coverage = {}
    for symbol in SYMBOLS:
        resolved, bars = eng.fetch_bars(symbol, ENTRY_TF, offset, lookback_days=LOOKBACK_DAYS)
        entry = prepare(bars)
        higher = {}
        maps = {}
        for tf, sec in HTF:
            _name, hbars = eng.fetch_bars(symbol, tf, offset, lookback_days=LOOKBACK_DAYS)
            higher[tf] = prepare(hbars)
            maps[tf] = align(bars, hbars, ENTRY_SEC, sec)
        signals = {
            rule: signals_for(rule, entry, higher["1h"], higher["4h"], maps["1h"], maps["4h"])
            for rule in RULES
        }
        packs[symbol] = {"entry": entry, "signals": signals}
        costs[symbol] = eng.symbol_costs(resolved)
        coverage[symbol] = {
            "resolved": resolved,
            "spread_price": costs[symbol]["spread_price"],
            "spread_source": costs[symbol]["spread_source"],
            "unit": costs[symbol]["unit_per_lot_per_price"],
            "currency_profit": costs[symbol]["currency_profit"],
            "bars_15m": len(bars),
            "first_utc": datetime.fromtimestamp(bars[0].t, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "last_utc": datetime.fromtimestamp(bars[-1].t, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "gaps": eng.gap_report(bars, ENTRY_TF),
            "signal_counts": {rule: sum(item is not None for item in series) for rule, series in signals.items()},
        }
        print(symbol, coverage[symbol]["resolved"], "sinyaller", coverage[symbol]["signal_counts"], flush=True)

    train = {symbol: {} for symbol in SYMBOLS}
    test = {symbol: {} for symbol in SYMBOLS}
    for symbol in SYMBOLS:
        hours = XAU_HOURS if symbol == "XAUUSD" else None
        for rule in RULES:
            train_rows = run_rule(packs[symbol], costs[symbol], hours, rule, train_weeks, 1.0)
            test_rows = run_rule(packs[symbol], costs[symbol], hours, rule, test_weeks, 1.0)
            train[symbol][rule] = {**summarize_weeks(train_rows), "weeks_detail": train_rows}
            test[symbol][rule] = {**summarize_weeks(test_rows), "weeks_detail": test_rows}
            print(
                f"{symbol} {rule} egitim {train[symbol][rule]['sum_pnl']} ({train[symbol][rule]['trades']} islem)"
                f" | test {test[symbol][rule]['sum_pnl']} ({test[symbol][rule]['trades']} islem)",
                flush=True,
            )

    picked = choose(train)
    focus = picked["rule"]
    test_continuous = {}
    stress = {}
    if focus is not None:
        start, end = test_weeks[0][0], test_weeks[-1][1]
        for symbol in SYMBOLS:
            hours = XAU_HOURS if symbol == "XAUUSD" else None
            test_continuous[symbol] = continuous(packs[symbol], costs[symbol], hours, focus, start, end, 1.0)
            stress[symbol] = continuous(packs[symbol], costs[symbol], hours, focus, start, end, 2.0)
            stress[symbol].pop("trades_detail", None)
            print(
                f"secilen {focus} {symbol} test kasa {test_continuous[symbol]['pnl']}"
                f" pf {test_continuous[symbol]['pf']} | cift spread {stress[symbol]['pnl']}",
                flush=True,
            )
    verdict = recommend(picked, test_continuous, stress) if focus is not None else "reject"
    report = {
        "source": "MetaTrader 5 copy_rates, bid mum",
        "retrieved_utc": retrieved,
        "server_offset_s": offset,
        "anchor": anchor_name,
        "entry_tf": ENTRY_TF,
        "higher_tf": [tf for tf, _sec in HTF],
        "risk": RISK,
        "rr": RR,
        "stop_atr": STOP_ATR,
        "start_cash": wk.START_CASH,
        "currency_note": "Her hafta 1000, terminal kar para birimi. Scalper 10000 TL kasasi degil.",
        "commission": None,
        "slippage_beyond_spread": None,
        "train_weeks": [label for _s, _e, label in train_weeks],
        "test_weeks": [label for _s, _e, label in test_weeks],
        "selection": "Sembol basina en az 4 egitim islemi. Skor = iki sembolun egitim pnl minimumu. Skor pozitif degilse kural yok.",
        "picked": picked,
        "recommendation": verdict,
        "coverage": coverage,
        "train": train,
        "test_weekly": test,
        "test_continuous": test_continuous,
        "stress_double_spread": stress,
        "limits": [
            "Komisyon alani yok, sifir kabul edilmedi.",
            "Spread anlik snapshot; gecmis spread bilinmiyor.",
            "Yuksek etkili haber filtresi uygulanmadi.",
            "Emir defteri ve gercek kayma yok.",
            "Ayni mumda stop ve hedef birlikteyse stop.",
            "1R ve basabas ayni mumda birlikteyse basabas.",
        ],
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zlmacd_wavetrend_mtf_xau_btc.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        "file": path,
        "picked": picked,
        "recommendation": verdict,
        "train_min": {rule: min(train[s][rule]["sum_pnl"] for s in SYMBOLS) for rule in RULES},
        "test_sum": None if focus is None else {s: test_continuous[s]["pnl"] for s in SYMBOLS},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
