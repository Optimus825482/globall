#!/usr/bin/env python3
"""Zero-Lag MACD + WaveTrend coklu zaman dilimi TARAMASI. XAUUSD ve BTCUSD.

Formuller TradingView acik kaynak kodundan birebir alindi (2026-10-27):

Zero Lag MACD Enhanced 1.2 (albert.callisto, Glaz tabanli):
  zlFast = 2*EMA(close,12) - EMA(EMA(close,12),12)
  zlSlow = 2*EMA(close,26) - EMA(EMA(close,26),26)
  ZLMACD = zlFast - zlSlow
  sinyal = 2*EMA(ZLMACD,9) - EMA(EMA(ZLMACD,9),9)   <- sinyal de zero-lag
  hist   = ZLMACD - sinyal
  Not: depodaki eski script ve canli tarayici sinyali duz EMA(9) ile aliyor.

WaveTrend [LazyBear]:
  ap = hlc3; esa = EMA(ap,10); d = EMA(|ap-esa|,10)
  ci = (ap-esa)/(0.015*d); wt1 = EMA(ci,21); wt2 = SMA(wt1,4)
  Bantlar +60/+53 asiri alim, -60/-53 asiri satim.
  LazyBear: asiri satim altinda wt1 wt2'yi yukari keserse AL, asiri alim
  ustunde asagi keserse SAT.

Tarama: giris dilimi 5m, 15m, 30m, 1h. Her giris dilimi icin iki ust dilim.
Kural listesi ve cikis modelleri kosudan once kilitlendi (RULES, EXITS).
Secim yalnizca egitim haftalarinin (ilk 8) kapanis bakiyesine gore.
Son 4 hafta bir kez okunur.

Giris: kapanmis mum sinyali, bir sonraki mum acilisinda. Ust dilim yalnizca
kapanmis bar. Stop 1.2 ATR(14). 1R lehte gorulurse stop girise.
Cikis modeli "2r": hedef 2R. Cikis modeli "wt_ters": hedef 4R tavan, ters
WaveTrend kesisiminde bir sonraki acilista cikis.
Ust uste 2 stop -> 2 bar bekleme. XAUUSD 07:00-21:00 UTC, BTCUSD tum saatler.
Risk haftalik kasanin %2'si. Her hafta 1000, terminal kar para birimi.
Emir gonderilmez.
"""
from __future__ import annotations

import bisect
import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402
import zlmacd_wavetrend_mtf_xau_btc as base  # noqa: E402
import MetaTrader5 as mt5  # noqa: E402

eng.TF_MAP.setdefault("30m", mt5.TIMEFRAME_M30)
eng.TF_MAP.setdefault("1d", mt5.TIMEFRAME_D1)
eng.TF_SEC.setdefault("30m", 1800)
eng.TF_SEC.setdefault("1d", 86400)

SYMBOLS = ("XAUUSD", "BTCUSD")
ENTRY_TFS = ("5m", "15m", "30m", "1h")
HTF_OF = {"5m": ("30m", "4h"), "15m": ("1h", "4h"), "30m": ("4h", "1d"), "1h": ("4h", "1d")}
LOOKBACK = {"5m": 140, "15m": 140, "30m": 200, "1h": 240, "4h": 400, "1d": 600}
TRAIN_WEEKS = 8
TEST_WEEKS = 4
RISK = 0.02
STOP_ATR = 1.2
RR_FIXED = 2.0
RR_CAP = 4.0
MIN_TRAIN_TRADES = 12
PAPER_MIN_TRADES = 20
PAPER_MIN_PF = 1.3
XAU_HOURS = (7, 21)
WT_OB1, WT_OS1 = 60.0, -60.0
WT_OB2, WT_OS2 = 53.0, -53.0
RULES = (
    "zl_kesim",            # ZL-MACD sinyal kesisimi
    "zl_trend",            # kesisim sifirin dogru tarafinda
    "zl_erken",            # kesisim sifirin ters tarafinda (donus)
    "wt_60",               # WT bolge kesisimi +-60
    "wt_53",               # WT bolge kesisimi +-53
    "wt_53_hist",          # WT 53 + ZL hist ayni yonde buyuyor
    "zl_kesim_wt_yon",     # ZL kesisim + WT1 WT2 ayni taraf
    "ust1_zl_wt53",        # ust1 ZL yonu + giris WT 53
    "ust1_zl_wt_geri",     # ust1 ZL yonu + WT sifir altinda/ustunde kesisim (geri cekilme)
    "ust12_zl_kesim",      # ust1 ve ust2 ZL yonu + giris ZL kesisim
    "ust1_zlwt_zl_kesim",  # ust1 ZL ve WT yonu + giris ZL kesisim
    "ust12_wt_geri",       # ust1 ve ust2 ZL yonu + WT geri cekilme kesisimi
)
EXITS = ("2r", "wt_ters")
OUT_NAME = "zlwt_tarama_xau_btc.json"


# ---------------------------------------------------------------- gostergeler
def ema_sparse(values: list, period: int) -> list:
    return base.ema_on_sparse(values, period)


def zero_lag_ema(values: list, period: int) -> list:
    ma1 = ema_sparse(values, period)
    ma2 = ema_sparse(ma1, period)
    return [None if a is None or b is None else 2.0 * a - b for a, b in zip(ma1, ma2)]


def zl_macd_tv(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list, list, list]:
    """TradingView Zero Lag MACD Enhanced 1.2, useEma=true, useOldAlgo=false."""
    zf = zero_lag_ema(closes, fast)
    zs = zero_lag_ema(closes, slow)
    macd = [None if a is None or b is None else a - b for a, b in zip(zf, zs)]
    sig = zero_lag_ema(macd, signal)
    hist = [None if a is None or b is None else a - b for a, b in zip(macd, sig)]
    return macd, sig, hist


def wavetrend_tv(bars: list[eng.Bar], n1: int = 10, n2: int = 21, sig: int = 4) -> tuple[list, list]:
    """TradingView WaveTrend [LazyBear] birebir."""
    ap = [(b.high + b.low + b.close) / 3.0 for b in bars]
    esa = ema_sparse(ap, n1)
    dev_in = [None if e is None else abs(a - e) for a, e in zip(ap, esa)]
    d = ema_sparse(dev_in, n1)
    ci = [None if e is None or dv is None or dv == 0 else (a - e) / (0.015 * dv) for a, e, dv in zip(ap, esa, d)]
    wt1 = ema_sparse(ci, n2)
    wt2: list = [None] * len(bars)
    for i in range(sig - 1, len(bars)):
        win = wt1[i - sig + 1:i + 1]
        if any(v is None for v in win):
            continue
        wt2[i] = sum(win) / sig
    return wt1, wt2


def prepare(bars: list[eng.Bar]) -> dict:
    closes = [b.close for b in bars]
    macd, sig, hist = zl_macd_tv(closes)
    wt1, wt2 = wavetrend_tv(bars)
    _p, _m, adx = eng.adx_dmi(bars, 14)
    return {"bars": bars, "zl": macd, "zl_sig": sig, "hist": hist, "wt1": wt1, "wt2": wt2, "atr": wk.atr(bars, 14), "adx": adx}


# ---------------------------------------------------------------- sinyaller
def wt_zone_cross(p: dict, i: int, level: float) -> int:
    w1, w2 = p["wt1"], p["wt2"]
    if base.cross_up(w1, w2, i) and min(w1[i], w1[i - 1]) <= -level:
        return 1
    if base.cross_down(w1, w2, i) and max(w1[i], w1[i - 1]) >= level:
        return -1
    return 0


def wt_pullback_cross(p: dict, i: int) -> int:
    w1, w2 = p["wt1"], p["wt2"]
    if base.cross_up(w1, w2, i) and w1[i - 1] < 0:
        return 1
    if base.cross_down(w1, w2, i) and w1[i - 1] > 0:
        return -1
    return 0


def hist_dir(p: dict, i: int) -> int:
    h = p["hist"]
    if h[i] is None or h[i - 1] is None:
        return 0
    return 1 if h[i] > h[i - 1] else -1 if h[i] < h[i - 1] else 0


def rule_side(rule: str, e: dict, h1: dict, h2: dict, j1: int, j2: int, i: int) -> int:
    zl_up = base.cross_up(e["zl"], e["zl_sig"], i)
    zl_dn = base.cross_down(e["zl"], e["zl_sig"], i)
    zl_cross = 1 if zl_up else -1 if zl_dn else 0
    zl_val = e["zl"][i]
    s1 = base.side_of(h1["zl"], h1["zl_sig"], j1) if j1 >= 0 else 0
    s2 = base.side_of(h2["zl"], h2["zl_sig"], j2) if j2 >= 0 else 0
    w1 = base.side_of(h1["wt1"], h1["wt2"], j1) if j1 >= 0 else 0
    if rule == "zl_kesim":
        return zl_cross
    if rule == "zl_trend":
        if zl_cross and zl_val is not None and (zl_val > 0) == (zl_cross == 1):
            return zl_cross
        return 0
    if rule == "zl_erken":
        if zl_cross and zl_val is not None and (zl_val < 0) == (zl_cross == 1):
            return zl_cross
        return 0
    if rule == "wt_60":
        return wt_zone_cross(e, i, WT_OB1)
    if rule == "wt_53":
        return wt_zone_cross(e, i, WT_OB2)
    if rule == "wt_53_hist":
        z = wt_zone_cross(e, i, WT_OB2)
        return z if z and hist_dir(e, i) == z else 0
    if rule == "zl_kesim_wt_yon":
        return zl_cross if zl_cross and base.side_of(e["wt1"], e["wt2"], i) == zl_cross else 0
    if rule == "ust1_zl_wt53":
        z = wt_zone_cross(e, i, WT_OB2)
        return z if z and s1 == z else 0
    if rule == "ust1_zl_wt_geri":
        z = wt_pullback_cross(e, i)
        return z if z and s1 == z else 0
    if rule == "ust12_zl_kesim":
        return zl_cross if zl_cross and s1 == zl_cross and s2 == zl_cross else 0
    if rule == "ust1_zlwt_zl_kesim":
        return zl_cross if zl_cross and s1 == zl_cross and w1 == zl_cross else 0
    if rule == "ust12_wt_geri":
        z = wt_pullback_cross(e, i)
        return z if z and s1 == z and s2 == z else 0
    raise ValueError(rule)


def build_signals(rule: str, e: dict, h1: dict, h2: dict, m1: list[int], m2: list[int]) -> list:
    bars = e["bars"]
    out: list = [None] * len(bars)
    for i in range(1, len(bars)):
        side = rule_side(rule, e, h1, h2, m1[i], m2[i], i)
        if side == 0:
            continue
        atr = e["atr"][i]
        if atr is None or atr <= 0:
            continue
        level = bars[i].close - STOP_ATR * atr if side == 1 else bars[i].close + STOP_ATR * atr
        out[i] = (side, level)
    return out


def wt_cross_series(e: dict) -> list[int]:
    out = [0] * len(e["bars"])
    for i in range(1, len(out)):
        if base.cross_up(e["wt1"], e["wt2"], i):
            out[i] = 1
        elif base.cross_down(e["wt1"], e["wt2"], i):
            out[i] = -1
    return out


# ---------------------------------------------------------------- simulasyon
def _open(order, raw, spread, unit, vmin, vmax, vstep, cash, rr, i, t):
    side, stop_line = order
    if side == 1:
        net, stop = raw + spread, stop_line
        risk_px = net - stop
        tp = net + rr * risk_px
    else:
        net, stop = raw, stop_line + spread
        risk_px = stop - net
        tp = net - spread - rr * risk_px
    if risk_px <= spread or unit <= 0 or cash <= 0:
        return None
    vol = eng.floor_volume(cash * RISK / (risk_px * unit), vmin, vmax, vstep)
    if vol is None:
        return None
    return {"side": side, "net": net, "stop": stop, "tp": tp, "risk_px": risk_px, "vol": vol, "i": i, "entry_t": t, "adx": None, "be": False}


def simulate(bars, series, wt_x, exit_mode, spread, unit, vmin, vmax, vstep, start, end, hours) -> dict:
    cash = wk.START_CASH
    peak, max_dd = cash, 0.0
    pos = pending = None
    pending_exit = False
    trades: list = []
    losses_in_row, quiet_until = 0, -1
    rr = RR_FIXED if exit_mode == "2r" else RR_CAP
    times = [b.t for b in bars]
    i0 = bisect.bisect_left(times, start)
    for i in range(i0, len(bars)):
        bar = bars[i]
        if bar.t > end:
            if pos is not None:
                base._realize(trades, pos, bar.open, "pencere", spread, unit, cash)
                cash += trades[-1]["pnl"]
                pos = None
            break
        hour = datetime.fromtimestamp(bar.t, timezone.utc).hour
        hour_ok = hours is None or hours[0] <= hour < hours[1]
        if pos is not None and pending_exit:
            base._realize(trades, pos, bar.open, "ters_wt", spread, unit, cash)
            cash += trades[-1]["pnl"]
            pos = None
            losses_in_row = 0
        pending_exit = False
        if pending is not None and pos is None and i > quiet_until and hour_ok:
            pos = _open(pending, bar.open, spread, unit, vmin, vmax, vstep, cash, rr, i, bar.t)
        pending = None
        if pos is not None:
            closed = base._manage(bar, pos, spread)
            if closed is not None:
                raw_exit, reason = closed
                base._realize(trades, pos, raw_exit, reason, spread, unit, cash)
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
            equity = cash + ((bar.close - pos["net"]) if pos["side"] == 1 else (pos["net"] - (bar.close + spread))) * pos["vol"] * unit
            if exit_mode == "wt_ters" and wt_x[i] == -pos["side"] and i > pos["i"]:
                pending_exit = True
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if pos is None and series[i] is not None and bar.t < end and i > quiet_until:
            pending = series[i]
    wins = [r["pnl"] for r in trades if r["pnl"] > 0]
    losses = [r["pnl"] for r in trades if r["pnl"] < 0]
    gl = sum(losses)
    return {
        "friday": round(cash, 2), "pnl": round(cash - wk.START_CASH, 2), "hit": cash >= wk.TARGET,
        "trades": len(trades), "winners": len(wins), "dd": round(max_dd, 2),
        "pf": None if not losses or gl == 0 else round(sum(wins) / abs(gl), 3),
        "expectancy": None if not trades else round(sum(r["pnl"] for r in trades) / len(trades), 4),
        "reasons": base._count(r["reason"] for r in trades), "log": trades,
    }


def run_weeks(pack, cfg, costs, hours, weeks, spread_mult=1.0) -> list[dict]:
    series = pack["signals"][cfg["tf"]][cfg["rule"]]
    e = pack["entry"][cfg["tf"]]
    rows = []
    for start, end, label in weeks:
        r = simulate(e["bars"], series, pack["wt_x"][cfg["tf"]], cfg["exit"], costs["spread_price"] * spread_mult,
                     costs["unit_per_lot_per_price"], costs["volume_min"], costs["volume_max"], costs["volume_step"], start, end, hours)
        rows.append({"week": label, **{k: r[k] for k in ("friday", "pnl", "hit", "trades", "winners", "dd", "pf", "expectancy", "reasons")}})
    return rows


def run_continuous(pack, cfg, costs, hours, start, end, spread_mult=1.0) -> dict:
    series = pack["signals"][cfg["tf"]][cfg["rule"]]
    e = pack["entry"][cfg["tf"]]
    r = simulate(e["bars"], series, pack["wt_x"][cfg["tf"]], cfg["exit"], costs["spread_price"] * spread_mult,
                 costs["unit_per_lot_per_price"], costs["volume_min"], costs["volume_max"], costs["volume_step"], start, end, hours)
    out = {k: r[k] for k in ("friday", "pnl", "trades", "winners", "dd", "pf", "expectancy", "reasons")}
    out["win_rate"] = None if r["trades"] == 0 else round(r["winners"] / r["trades"], 3)
    out["trades_detail"] = r["log"]
    return out


# ---------------------------------------------------------------- secim
def cfg_name(cfg: dict) -> str:
    return f"{cfg['tf']}|{cfg['rule']}|{cfg['exit']}"


def choose_per_symbol(table: dict) -> dict | None:
    best = None
    for name, row in table.items():
        if row["train"]["trades"] < MIN_TRAIN_TRADES:
            continue
        if best is None or row["train"]["sum_pnl"] > best[1]:
            best = (name, row["train"]["sum_pnl"])
    if best is None or best[1] <= 0:
        return None
    return {"name": best[0], "train_pnl": best[1]}


def choose_joint(tables: dict) -> dict | None:
    best = None
    for name in tables[SYMBOLS[0]]:
        ok = all(tables[s][name]["train"]["trades"] >= MIN_TRAIN_TRADES for s in SYMBOLS)
        if not ok:
            continue
        score = min(tables[s][name]["train"]["sum_pnl"] for s in SYMBOLS)
        if best is None or score > best[1]:
            best = (name, score)
    if best is None or best[1] <= 0:
        return None
    return {"name": best[0], "train_min_pnl": best[1]}


def parse_cfg(name: str) -> dict:
    tf, rule, ex = name.split("|")
    return {"tf": tf, "rule": rule, "exit": ex}


def verdict(test_books: list[dict], stress: list[dict], total_trades: int) -> str:
    def pf_ok(b):
        if b["trades"] == 0 or b["pnl"] <= 0:
            return False
        return b["winners"] == b["trades"] if b["pf"] is None else b["pf"] >= PAPER_MIN_PF
    if all(b["pnl"] > 0 for b in test_books) and total_trades >= PAPER_MIN_TRADES and all(pf_ok(b) for b in test_books) and all(s["pnl"] > 0 for s in stress):
        return "paper-candidate"
    if all(b["pnl"] > 0 for b in test_books) and total_trades >= 8:
        return "continue-testing"
    return "reject"


# ---------------------------------------------------------------- anlik tarama
def snapshot(e: dict) -> dict:
    i = len(e["bars"]) - 1
    w1, w2 = e["wt1"][i], e["wt2"][i]
    zone = None
    if w1 is not None:
        zone = "asiri_satim" if w1 <= WT_OS2 else "asiri_alim" if w1 >= WT_OB2 else "orta"
    zl_side = base.side_of(e["zl"], e["zl_sig"], i)
    return {
        "bar_open_utc": datetime.fromtimestamp(e["bars"][i].t, timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "close": e["bars"][i].close,
        "zl": None if e["zl"][i] is None else round(e["zl"][i], 5),
        "zl_sig": None if e["zl_sig"][i] is None else round(e["zl_sig"][i], 5),
        "zl_yon": "yukari" if zl_side == 1 else "asagi" if zl_side == -1 else "yok",
        "zl_kesim_bu_bar": "al" if base.cross_up(e["zl"], e["zl_sig"], i) else "sat" if base.cross_down(e["zl"], e["zl_sig"], i) else None,
        "wt1": None if w1 is None else round(w1, 2),
        "wt2": None if w2 is None else round(w2, 2),
        "wt_bolge": zone,
        "wt_kesim_bu_bar": "al" if base.cross_up(e["wt1"], e["wt2"], i) else "sat" if base.cross_down(e["wt1"], e["wt2"], i) else None,
    }


# ---------------------------------------------------------------- self check
def self_check() -> None:
    ramp = [float(i) for i in range(1, 400)]
    zl = zero_lag_ema(ramp, 12)
    assert abs(zl[-1] - ramp[-1]) < 0.05, zl[-1]          # zero-lag dogrusal rampada gecikmesiz
    plain = wk.ema(ramp, 12)
    assert ramp[-1] - plain[-1] > 5.0                        # duz EMA ~5.5 geride
    _macd, _sig, hist = zl_macd_tv(ramp)
    assert hist[-1] is not None and abs(hist[-1]) < 1e-6     # sabit egimde macd = sinyal
    bars = []
    for i in range(600):
        c = 100 + 10 * math.sin(i / 16.0)
        bars.append(eng.Bar(i * 60, c, c + 0.5, c - 0.5, c))
    w1, _w2 = wavetrend_tv(bars)
    vals = [v for v in w1 if v is not None]
    assert max(vals) > 60 and min(vals) < -60
    e = {"wt1": [-70, -64, -58], "wt2": [-60, -63, -60]}
    assert wt_zone_cross(e, 2, 60.0) == 1
    assert wt_zone_cross({"wt1": [-40, -44, -38], "wt2": [-40, -43, -40]}, 2, 60.0) == 0


def main() -> None:
    self_check()
    eng.attach_terminal()
    offset = eng.server_offset_s()
    retrieved = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _n, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=140)
    cal = wk.weeks_ending(anchor[-1].t, TRAIN_WEEKS + TEST_WEEKS)
    train_weeks, test_weeks = cal[:TRAIN_WEEKS], cal[TRAIN_WEEKS:]
    t_start, t_end = test_weeks[0][0], test_weeks[-1][1]

    packs, costs, coverage, now_scan = {}, {}, {}, {}
    need_tfs = sorted({tf for tf in ENTRY_TFS} | {h for pair in HTF_OF.values() for h in pair}, key=lambda t: eng.TF_SEC[t])
    for symbol in SYMBOLS:
        prepared, raw = {}, {}
        resolved = None
        for tf in need_tfs:
            resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=LOOKBACK[tf])
            raw[tf] = bars
            prepared[tf] = prepare(bars)
        costs[symbol] = eng.symbol_costs(resolved)
        signals, wt_x = {}, {}
        for tf in ENTRY_TFS:
            h1n, h2n = HTF_OF[tf]
            m1 = base.align(raw[tf], raw[h1n], eng.TF_SEC[tf], eng.TF_SEC[h1n])
            m2 = base.align(raw[tf], raw[h2n], eng.TF_SEC[tf], eng.TF_SEC[h2n])
            signals[tf] = {rule: build_signals(rule, prepared[tf], prepared[h1n], prepared[h2n], m1, m2) for rule in RULES}
            wt_x[tf] = wt_cross_series(prepared[tf])
        packs[symbol] = {"entry": prepared, "signals": signals, "wt_x": wt_x}
        coverage[symbol] = {
            "resolved": resolved, "spread_price": costs[symbol]["spread_price"], "spread_source": costs[symbol]["spread_source"],
            "unit": costs[symbol]["unit_per_lot_per_price"], "currency_profit": costs[symbol]["currency_profit"],
            "bars": {tf: len(raw[tf]) for tf in need_tfs},
            "first_utc": {tf: datetime.fromtimestamp(raw[tf][0].t, timezone.utc).strftime("%Y-%m-%d %H:%M") for tf in need_tfs},
            "gaps_15m": eng.gap_report(raw["15m"], "15m"),
            "signal_counts": {tf: {r: sum(x is not None for x in s) for r, s in signals[tf].items()} for tf in ENTRY_TFS},
        }
        now_scan[symbol] = {tf: snapshot(prepared[tf]) for tf in need_tfs}
        print(symbol, resolved, {tf: len(raw[tf]) for tf in need_tfs}, flush=True)

    tables = {s: {} for s in SYMBOLS}
    for symbol in SYMBOLS:
        hours = XAU_HOURS if symbol == "XAUUSD" else None
        for tf in ENTRY_TFS:
            for rule in RULES:
                for ex in EXITS:
                    cfg = {"tf": tf, "rule": rule, "exit": ex}
                    tr = run_weeks(packs[symbol], cfg, costs[symbol], hours, train_weeks)
                    te = run_weeks(packs[symbol], cfg, costs[symbol], hours, test_weeks)
                    tables[symbol][cfg_name(cfg)] = {
                        "train": base.summarize_weeks(tr), "test": base.summarize_weeks(te),
                        "train_weeks": tr, "test_weeks": te,
                    }
            print(symbol, tf, "bitti", flush=True)

    # Egitim siralamasi (ilk 10) ve bunlarin test sonucu: secim yanliligi gostergesi
    leaderboard = {}
    for symbol in SYMBOLS:
        rows = [(n, r) for n, r in tables[symbol].items() if r["train"]["trades"] >= MIN_TRAIN_TRADES]
        rows.sort(key=lambda x: x[1]["train"]["sum_pnl"], reverse=True)
        leaderboard[symbol] = [
            {"config": n, "train_pnl": r["train"]["sum_pnl"], "train_trades": r["train"]["trades"], "train_win": r["train"]["win_rate"],
             "test_pnl": r["test"]["sum_pnl"], "test_trades": r["test"]["trades"], "test_win": r["test"]["win_rate"]}
            for n, r in rows[:10]
        ]
        top = rows[:10]
        leaderboard[symbol + "_ozet"] = {
            "egitim_pozitif_config": sum(1 for _n, r in rows if r["train"]["sum_pnl"] > 0),
            "toplam_config": len(rows),
            "ilk10_testte_pozitif": sum(1 for _n, r in top if r["test"]["sum_pnl"] > 0),
        }

    picked = {s: choose_per_symbol(tables[s]) for s in SYMBOLS}
    joint = choose_joint(tables)
    final = {}
    for symbol in SYMBOLS:
        hours = XAU_HOURS if symbol == "XAUUSD" else None
        pick = picked[symbol]
        if pick is None:
            final[symbol] = {"picked": None, "verdict": "reject"}
            continue
        cfg = parse_cfg(pick["name"])
        cont = run_continuous(packs[symbol], cfg, costs[symbol], hours, t_start, t_end)
        stress = run_continuous(packs[symbol], cfg, costs[symbol], hours, t_start, t_end, 2.0)
        stress.pop("trades_detail")
        final[symbol] = {
            "picked": pick, "config": cfg,
            "train": tables[symbol][pick["name"]]["train"],
            "test_weekly": tables[symbol][pick["name"]]["test"],
            "test_continuous": cont, "stress_double_spread": stress,
            "verdict": verdict([cont], [stress], cont["trades"]),
        }
        print(f"{symbol} secilen {pick['name']} egitim {pick['train_pnl']} | test {cont['pnl']} pf {cont['pf']} ({cont['trades']} islem) | cift spread {stress['pnl']} -> {final[symbol]['verdict']}", flush=True)

    joint_out = None
    if joint is not None:
        cfg = parse_cfg(joint["name"])
        books, stresses = {}, {}
        for symbol in SYMBOLS:
            hours = XAU_HOURS if symbol == "XAUUSD" else None
            books[symbol] = run_continuous(packs[symbol], cfg, costs[symbol], hours, t_start, t_end)
            stresses[symbol] = run_continuous(packs[symbol], cfg, costs[symbol], hours, t_start, t_end, 2.0)
            stresses[symbol].pop("trades_detail")
        joint_out = {
            "picked": joint, "config": cfg,
            "train": {s: tables[s][joint["name"]]["train"] for s in SYMBOLS},
            "test_continuous": books, "stress_double_spread": stresses,
            "verdict": verdict(list(books.values()), list(stresses.values()), sum(b["trades"] for b in books.values())),
        }
        print("ortak", joint["name"], {s: books[s]["pnl"] for s in SYMBOLS}, joint_out["verdict"], flush=True)

    report = {
        "source": "MetaTrader 5 copy_rates, bid mum", "retrieved_utc": retrieved, "server_offset_s": offset,
        "formulas": {
            "zl_macd": "TV Zero Lag MACD Enhanced 1.2: ZLEMA(12)-ZLEMA(26), sinyal ZLEMA(9) (2*EMA-EMA(EMA)), useEma=true, useOldAlgo=false",
            "wavetrend": "TV WaveTrend [LazyBear]: hlc3, esa EMA10, d EMA10, ci/(0.015d), wt1 EMA21, wt2 SMA4, bant 60/53",
            "sources": [
                "https://www.tradingview.com/script/kfFN7M7u/",
                "https://www.tradingview.com/script/2KE8wTuF-Indicator-WaveTrend-Oscillator-WT/",
            ],
        },
        "entry_tfs": ENTRY_TFS, "htf_of": HTF_OF, "rules": RULES, "exits": EXITS,
        "risk": RISK, "stop_atr": STOP_ATR, "rr_fixed": RR_FIXED, "rr_cap": RR_CAP, "start_cash": wk.START_CASH,
        "train_weeks": [l for _s, _e, l in train_weeks], "test_weeks": [l for _s, _e, l in test_weeks],
        "selection": f"Sembol basina: egitim >= {MIN_TRAIN_TRADES} islem, en yuksek egitim pnl. Ortak: iki sembol egitim pnl minimumu. Pozitif degilse secim yok.",
        "config_count_per_symbol": len(ENTRY_TFS) * len(RULES) * len(EXITS),
        "coverage": coverage,
        "now_scan": now_scan,
        "leaderboard": leaderboard,
        "per_symbol": final,
        "joint": joint_out,
        "all_configs": {s: {n: {"train": r["train"], "test": r["test"]} for n, r in tables[s].items()} for s in SYMBOLS},
        "limits": [
            "96 konfigurasyon tarandi; egitim en iyisi secim yanliligi tasir, test bu yuzden ayri.",
            "Komisyon alani yok, sifir kabul edilmedi. Spread anlik snapshot.",
            "Haber filtresi yok. Emir defteri ve gercek kayma yok.",
            "Ayni mumda stop ve hedef birlikteyse stop.",
            "1d barlari broker gunu; align yalnizca kapanmis bar kullanir.",
        ],
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUT_NAME)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "per_symbol": {s: {"picked": final[s].get("picked"), "verdict": final[s]["verdict"]} for s in SYMBOLS},
                      "joint": None if joint_out is None else {"picked": joint_out["picked"], "verdict": joint_out["verdict"]},
                      "ozet": {s: leaderboard[s + "_ozet"] for s in SYMBOLS}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
