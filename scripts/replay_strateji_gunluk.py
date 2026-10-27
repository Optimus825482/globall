#!/usr/bin/env python3
"""Mevcut replay motoru (forex_replay_backtest.py) + YALNIZ giris stratejisi degisik.

Kullanici istegi (2026-10-27): "su andaki mevcut sistemi replay olarak calistir,
sadece stratejiyi degistirerek; m3-5-15; gunluk 1000 -> 1500 hedefi".

Motorun kapilari, cikis yonetimi (BE/trailing/kismi), risk butcesi (altin %10,
kripto %2 — canli ayar) ve lot tavanlari DOKUNULMADAN kalir. Sadece
`_entry_mode_candidate` bu dosyadaki strateji ile degistirilir (monkeypatch).
Klasik radar kolu kapali (mod secili oldugunda motor kendisi kapatir).

Veri: outputs/replay_cache_xaubtc_{m3,m5,m15}.json (MT5, fx_build_mt5_cache.py).
Gunluk degerlendirme: motor raporundaki kapanan islemlerden gun (UTC) bazinda
P&L; her gun 1000 USD tabanina gore (motor lotu sabit BALANCE ile boyutlar,
gun ici birikim yok). Hedef: gun P&L >= +500 USD.

Kullanim:
  python scripts/replay_strateji_gunluk.py --strategy hma_ao --tf m5
      [--risk-gold 10 --risk-btc 2] [--sl-atr 1.5 --tp-r 2.0]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "backend"), os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import forex_replay_backtest as rp  # noqa: E402
from backend.app.routers import forex  # noqa: E402
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402
import zlmacd_wavetrend_mtf_xau_btc as base  # noqa: E402
import gunluk_tavan_tarama_xau_btc as gt  # noqa: E402

BUILTIN_STRATEGIES = (
    "hma_ao", "vortex_adx", "kama_cci", "stoch_kijun", "tsi_ema50", "fisher_st",
    "cmo_bb", "wpr_ema_trend", "psar_macd", "donch_vortex", "ut_bot", "coral_trend",
    "combo3",   # ut_bot | donch_vortex | vortex_adx (birlesim; ilk ateslenen yon)
    "combo3_onay",  # en az ikisi ayni yonde (ut_bot, donch_vortex, vortex_adx)
)
SL_ATR = 1.5
TP_R = 2.0
PLUGIN_DIR = os.path.join(ROOT, "scripts", "strategies")
SPREAD_DB = os.path.join(ROOT, "outputs", "fx_spread_db_1m.json")
SPREAD_DEFAULT_PIPS = 1.5   # ne tech["spread_pips"] ne de profil varsa
PLUGINS: dict = {}          # ad -> normalize edilmis eklenti tanimi (load_plugins doldurur)
TARGET_USD = 500.0
RUIN_USD = -700.0
WIN_7W = "2026-09-08"
WIN_14W = "2026-07-21"
_SERIES: dict = {}
_BARS: dict = {}


# ------------------------------------------------------------------ seri yardimcilari
def bars_of(sym: str, bars: list) -> list:
    cur = _BARS.get(sym)
    if cur is None or len(cur) != len(bars):
        cur = [eng.Bar(int(b[0]), float(b[1]), float(b[2]), float(b[3]), float(b[4])) for b in bars]
        _BARS[sym] = cur
    return cur


def wma(values: list, n: int) -> list:
    out: list = [None] * len(values)
    den = n * (n + 1) / 2.0
    for i in range(n - 1, len(values)):
        win = values[i - n + 1:i + 1]
        if any(v is None for v in win):
            continue
        out[i] = sum((k + 1) * v for k, v in enumerate(win)) / den
    return out


def hma(values: list, n: int) -> list:
    half = wma(values, max(1, n // 2))
    full = wma(values, n)
    diff = [None if a is None or b is None else 2 * a - b for a, b in zip(half, full)]
    return wma(diff, max(1, int(round(math.sqrt(n)))))


def sma(values: list, n: int) -> list:
    return gt.sma(values, n)


def awesome(b: list) -> list:
    hl2 = [(x.high + x.low) / 2 for x in b]
    f, s = sma(hl2, 5), sma(hl2, 34)
    return [None if a is None or c is None else a - c for a, c in zip(f, s)]


def vortex(b: list, n: int = 14) -> tuple:
    tr, vmp, vmm = [None] * len(b), [None] * len(b), [None] * len(b)
    for i in range(1, len(b)):
        tr[i] = max(b[i].high - b[i].low, abs(b[i].high - b[i - 1].close), abs(b[i].low - b[i - 1].close))
        vmp[i] = abs(b[i].high - b[i - 1].low)
        vmm[i] = abs(b[i].low - b[i - 1].high)
    vip, vim = [None] * len(b), [None] * len(b)
    for i in range(n, len(b)):
        st = sum(tr[i - n + 1:i + 1])
        if st:
            vip[i] = sum(vmp[i - n + 1:i + 1]) / st
            vim[i] = sum(vmm[i - n + 1:i + 1]) / st
    return vip, vim


def kama(values: list, n: int = 10, fast: int = 2, slow: int = 30) -> list:
    out: list = [None] * len(values)
    fs, ss = 2 / (fast + 1), 2 / (slow + 1)
    for i in range(n, len(values)):
        change = abs(values[i] - values[i - n])
        vol = sum(abs(values[k] - values[k - 1]) for k in range(i - n + 1, i + 1))
        er = 0.0 if vol == 0 else change / vol
        sc = (er * (fs - ss) + ss) ** 2
        prev = out[i - 1] if out[i - 1] is not None else values[i - 1]
        out[i] = prev + sc * (values[i] - prev)
    return out


def cci(b: list, n: int = 20) -> list:
    tp = [(x.high + x.low + x.close) / 3 for x in b]
    m = sma(tp, n)
    out: list = [None] * len(b)
    for i in range(n - 1, len(b)):
        if m[i] is None:
            continue
        md = sum(abs(v - m[i]) for v in tp[i - n + 1:i + 1]) / n
        out[i] = 0.0 if md == 0 else (tp[i] - m[i]) / (0.015 * md)
    return out


def stoch(b: list, k: int = 14, sk: int = 3, d: int = 3) -> tuple:
    raw: list = [None] * len(b)
    for i in range(k - 1, len(b)):
        hh = max(x.high for x in b[i - k + 1:i + 1])
        ll = min(x.low for x in b[i - k + 1:i + 1])
        raw[i] = 50.0 if hh == ll else 100.0 * (b[i].close - ll) / (hh - ll)
    kk = sma(raw, sk)
    return kk, sma(kk, d)


def tsi(values: list, long: int = 25, short: int = 13, sig: int = 13) -> tuple:
    m = [None] + [values[i] - values[i - 1] for i in range(1, len(values))]
    am = [None if v is None else abs(v) for v in m]
    num = base.ema_on_sparse(base.ema_on_sparse(m, long), short)
    den = base.ema_on_sparse(base.ema_on_sparse(am, long), short)
    t = [None if a is None or c in (None, 0) else 100.0 * a / c for a, c in zip(num, den)]
    return t, base.ema_on_sparse(t, sig)


def fisher(b: list, n: int = 9) -> tuple:
    hl2 = [(x.high + x.low) / 2 for x in b]
    val, fish = 0.0, 0.0
    out: list = [None] * len(b)
    for i in range(n - 1, len(b)):
        win = hl2[i - n + 1:i + 1]
        hh, ll = max(win), min(win)
        x = 0.0 if hh == ll else (hl2[i] - ll) / (hh - ll) - 0.5
        val = 0.66 * x + 0.67 * val
        val = max(-0.999, min(0.999, val))
        fish = 0.5 * math.log((1 + val) / (1 - val)) + 0.5 * fish
        out[i] = fish
    trig = [None] + out[:-1]
    return out, trig


def cmo(values: list, n: int = 9) -> list:
    out: list = [None] * len(values)
    for i in range(n, len(values)):
        up = sum(max(values[k] - values[k - 1], 0.0) for k in range(i - n + 1, i + 1))
        dn = sum(max(values[k - 1] - values[k], 0.0) for k in range(i - n + 1, i + 1))
        out[i] = 0.0 if up + dn == 0 else 100.0 * (up - dn) / (up + dn)
    return out


def wpr(b: list, n: int = 14) -> list:
    out: list = [None] * len(b)
    for i in range(n - 1, len(b)):
        hh = max(x.high for x in b[i - n + 1:i + 1])
        ll = min(x.low for x in b[i - n + 1:i + 1])
        out[i] = -50.0 if hh == ll else (hh - b[i].close) / (hh - ll) * -100.0
    return out


def ut_bot(b: list, key: float = 1.0, n: int = 10) -> list:
    a = wk.atr(b, n)
    stop: list = [None] * len(b)
    for i in range(1, len(b)):
        if a[i] is None:
            continue
        loss = key * a[i]
        src, prev_src, prev = b[i].close, b[i - 1].close, stop[i - 1]
        if prev is None:
            stop[i] = src - loss
        elif src > prev and prev_src > prev:
            stop[i] = max(prev, src - loss)
        elif src < prev and prev_src < prev:
            stop[i] = min(prev, src + loss)
        elif src > prev:
            stop[i] = src - loss
        else:
            stop[i] = src + loss
    return stop


def coral(values: list, n: int = 21, cd: float = 0.4) -> list:
    di = (n - 1.0) / 2.0 + 1.0
    c1 = 2 / (di + 1)
    c2 = 1 - c1
    c3 = 3 * (cd * cd + cd * cd * cd)
    c4 = -3 * (2 * cd * cd + cd + cd * cd * cd)
    c5 = 3 * cd + 1 + cd * cd * cd + 3 * cd * cd
    i1 = i2 = i3 = i4 = i5 = i6 = values[0]
    out: list = [None] * len(values)
    for i, v in enumerate(values):
        i1 = c1 * v + c2 * i1
        i2 = c1 * i1 + c2 * i2
        i3 = c1 * i2 + c2 * i3
        i4 = c1 * i3 + c2 * i4
        i5 = c1 * i4 + c2 * i5
        i6 = c1 * i5 + c2 * i6
        out[i] = -cd * cd * cd * i6 + c3 * i5 + c4 * i4 + c5 * i3
    return out


# ------------------------------------------------------------------ eklentiler
_PLUGIN_DEFAULTS = {"sl_atr": None, "tp_r": None, "symbols": None, "spread_min_mult": None}


def load_plugins(plugin_dir: str | None = None) -> dict:
    """scripts/strategies/*.py (test_ ile baslayanlar haric) -> PLUGINS.

    Her dosya modul duzeyinde `STRATEGIES = {ad: {series, side, sl_atr, tp_r,
    symbols, spread_min_mult}}` tanimlar. Yerlesik ya da baska eklenti ile ad
    cakismasinda SystemExit. PLUGINS her cagrida bastan kurulur (idempotent)."""
    pdir = PLUGIN_DIR if plugin_dir is None else plugin_dir
    found: dict = {}
    owner: dict = {}
    if os.path.isdir(pdir):
        for fn in sorted(os.listdir(pdir)):
            if not fn.endswith(".py") or fn.startswith("test_"):
                continue
            path = os.path.join(pdir, fn)
            spec = importlib.util.spec_from_file_location("_strat_plugin_" + fn[:-3], path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            defs = getattr(mod, "STRATEGIES", None)
            if not isinstance(defs, dict):
                raise SystemExit(f"eklenti gecersiz (STRATEGIES dict yok): {fn}")
            for name, d in defs.items():
                if name in BUILTIN_STRATEGIES or name in found:
                    other = "yerlesik" if name in BUILTIN_STRATEGIES else owner[name]
                    raise SystemExit(f"eklenti ad cakismasi: {name} ({fn} <-> {other})")
                if not callable(d.get("series")) or not callable(d.get("side")):
                    raise SystemExit(f"eklenti gecersiz (series/side callable degil): {name} ({fn})")
                found[name] = {**_PLUGIN_DEFAULTS, **d}
                owner[name] = fn
    PLUGINS.clear()
    PLUGINS.update(found)
    return PLUGINS


def _load_spread_profile() -> dict:
    """outputs/fx_spread_db_1m.json -> {SYM: avg_pips}; yoksa/bozuksa bos."""
    try:
        with open(SPREAD_DB, encoding="utf-8") as fh:
            raw = json.load(fh).get("symbols", {})
        return {k: float(v["avg_pips"]) for k, v in raw.items() if v.get("avg_pips") is not None}
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return {}


_SPREAD_PROFILE: dict = _load_spread_profile()


def spread_pips_for(sym: str, tech) -> float:
    """tech["spread_pips"] (> 0) -> _SPREAD_PROFILE[sym] -> 1.5."""
    v = (tech or {}).get("spread_pips")
    if v is not None and v > 0:
        return float(v)
    return _SPREAD_PROFILE.get(sym, SPREAD_DEFAULT_PIPS)


load_plugins()
STRATEGIES = BUILTIN_STRATEGIES + tuple(PLUGINS)


def series_for(sym: str, strat: str, bars: list) -> dict:
    cur = _SERIES.get(sym)
    if cur is not None and cur["_n"] == len(bars) and cur["_strat"] == strat:
        return cur
    b = bars_of(sym, bars)
    closes = [x.close for x in b]
    plug = PLUGINS.get(strat)
    if plug is not None:
        s = plug["series"](b, closes)
        if "atr" not in s:
            s["atr"] = wk.atr(b, 14)
        s["_n"], s["_strat"] = len(bars), strat
        _SERIES[sym] = s
        return s
    s: dict = {"atr": wk.atr(b, 14)}
    if strat == "hma_ao":
        s["hma"], s["ao"] = hma(closes, 21), awesome(b)
    elif strat in ("vortex_adx", "donch_vortex"):
        s["vip"], s["vim"] = vortex(b, 14)
        if strat == "donch_vortex":
            s["dc_hi"], s["dc_lo"] = gt.donchian(b, 20)
    elif strat == "kama_cci":
        s["kama"], s["cci"] = kama(closes), cci(b, 20)
    elif strat == "stoch_kijun":
        s["k"], s["d"] = stoch(b)
        _t, s["kijun"], _a, _b2 = gt.ichimoku(b)
    elif strat == "tsi_ema50":
        s["tsi"], s["tsig"] = tsi(closes)
        s["ema50"] = wk.ema(closes, 50)
    elif strat == "fisher_st":
        s["fish"], s["trig"] = fisher(b, 9)
        _st, s["st_dir"] = eng.supertrend(b, 10, 3.0)
    elif strat == "cmo_bb":
        s["cmo"] = cmo(closes, 9)
        _m, s["bb_up"], s["bb_lo"], _w = gt.bollinger(closes)
    elif strat == "wpr_ema_trend":
        s["wpr"] = wpr(b, 14)
        s["ema21"], s["ema50"] = wk.ema(closes, 21), wk.ema(closes, 50)
    elif strat == "psar_macd":
        _sar, s["sar_dir"] = gt.psar(b)
        f, sl = wk.ema(closes, 12), wk.ema(closes, 26)
        macd = [None if a is None or c is None else a - c for a, c in zip(f, sl)]
        sig = base.ema_on_sparse(macd, 9)
        s["hist"] = [None if a is None or c is None else a - c for a, c in zip(macd, sig)]
    elif strat == "ut_bot":
        s["ut"] = ut_bot(b)
    elif strat == "coral_trend":
        s["coral"] = coral(closes, 21)
    elif strat in ("combo3", "combo3_onay"):
        s["ut"] = ut_bot(b)
        s["vip"], s["vim"] = vortex(b, 14)
        s["dc_hi"], s["dc_lo"] = gt.donchian(b, 20)
    else:
        raise ValueError(strat)
    s["_n"], s["_strat"] = len(bars), strat
    _SERIES[sym] = s
    return s


# ------------------------------------------------------------------ stratejiler
def side_for(strat: str, s: dict, b: list, i: int) -> int:
    plug = PLUGINS.get(strat)
    if plug is not None:
        return plug["side"](s, b, i)
    c = b[i].close
    if strat == "hma_ao":
        h, ao = s["hma"], s["ao"]
        if None in (h[i], h[i - 1], ao[i], ao[i - 1]):
            return 0
        if ao[i - 1] <= 0 < ao[i] and h[i] > h[i - 1]:
            return 1
        if ao[i - 1] >= 0 > ao[i] and h[i] < h[i - 1]:
            return -1
        return 0
    if strat == "vortex_adx":
        if base.cross_up(s["vip"], s["vim"], i):
            return 1
        if base.cross_down(s["vip"], s["vim"], i):
            return -1
        return 0
    if strat == "kama_cci":
        k, cc = s["kama"], s["cci"]
        if None in (k[i], k[i - 1], cc[i]):
            return 0
        if b[i - 1].close <= k[i - 1] and c > k[i] and cc[i] > 100:
            return 1
        if b[i - 1].close >= k[i - 1] and c < k[i] and cc[i] < -100:
            return -1
        return 0
    if strat == "stoch_kijun":
        k, d, kj = s["k"], s["d"], s["kijun"]
        if kj[i] is None or None in (k[i], d[i], k[i - 1], d[i - 1]):
            return 0
        if k[i - 1] <= d[i - 1] and k[i] > d[i] and k[i] < 20 and c > kj[i]:
            return 1
        if k[i - 1] >= d[i - 1] and k[i] < d[i] and k[i] > 80 and c < kj[i]:
            return -1
        return 0
    if strat == "tsi_ema50":
        t, g, e = s["tsi"], s["tsig"], s["ema50"]
        if e[i] is None:
            return 0
        if base.cross_up(t, g, i) and t[i] < 0 and c > e[i]:
            return 1
        if base.cross_down(t, g, i) and t[i] > 0 and c < e[i]:
            return -1
        return 0
    if strat == "fisher_st":
        f, t, d = s["fish"], s["trig"], s["st_dir"]
        if base.cross_up(f, t, i) and f[i] < -1.5 and d[i] == -1:
            return 1
        if base.cross_down(f, t, i) and f[i] > 1.5 and d[i] == 1:
            return -1
        return 0
    if strat == "cmo_bb":
        m, up, lo = s["cmo"], s["bb_up"], s["bb_lo"]
        if None in (m[i], up[i], lo[i], lo[i - 1], up[i - 1]):
            return 0
        if m[i] < -50 and b[i - 1].close < lo[i - 1] and c > lo[i]:
            return 1
        if m[i] > 50 and b[i - 1].close > up[i - 1] and c < up[i]:
            return -1
        return 0
    if strat == "wpr_ema_trend":
        w, e21, e50 = s["wpr"], s["ema21"], s["ema50"]
        if None in (w[i], w[i - 1], e21[i], e50[i]):
            return 0
        if w[i - 1] <= -80 < w[i] and e21[i] > e50[i]:
            return 1
        if w[i - 1] >= -20 > w[i] and e21[i] < e50[i]:
            return -1
        return 0
    if strat == "psar_macd":
        d, h = s["sar_dir"], s["hist"]
        if h[i] is None:
            return 0
        if d[i] == 1 and d[i - 1] == -1 and h[i] > 0:
            return 1
        if d[i] == -1 and d[i - 1] == 1 and h[i] < 0:
            return -1
        return 0
    if strat == "donch_vortex":
        hi, lo, vp, vm = s["dc_hi"], s["dc_lo"], s["vip"], s["vim"]
        if None in (hi[i - 1], lo[i - 1], vp[i], vm[i]):
            return 0
        if c > hi[i - 1] and vp[i] > vm[i]:
            return 1
        if c < lo[i - 1] and vm[i] > vp[i]:
            return -1
        return 0
    if strat == "ut_bot":
        u = s["ut"]
        if None in (u[i], u[i - 1]):
            return 0
        if b[i - 1].close <= u[i - 1] and c > u[i]:
            return 1
        if b[i - 1].close >= u[i - 1] and c < u[i]:
            return -1
        return 0
    if strat in ("combo3", "combo3_onay"):
        sides = [side_for("ut_bot", s, b, i), side_for("donch_vortex", s, b, i), side_for("vortex_adx", s, b, i)]
        if strat == "combo3":
            return next((x for x in sides if x), 0)
        if sides.count(1) >= 2:
            return 1
        if sides.count(-1) >= 2:
            return -1
        return 0
    if strat == "coral_trend":
        cr = s["coral"]
        if i < 2 or None in (cr[i], cr[i - 1], cr[i - 2]):
            return 0
        if cr[i] > cr[i - 1] and cr[i - 1] <= cr[i - 2]:
            return 1
        if cr[i] < cr[i - 1] and cr[i - 1] >= cr[i - 2]:
            return -1
        return 0
    raise ValueError(strat)


ACTIVE = {"strategy": "hma_ao", "sl_atr": SL_ATR, "tp_r": TP_R}


def candidate(sym, ts, bars, ci, tech, pip_size):
    """rp._entry_mode_candidate yerine: kapanmis bar ci-1 sinyali, motor sonraki barda acar."""
    if ci < 60 or pip_size <= 0:
        return None
    plug = PLUGINS.get(ACTIVE["strategy"])
    if plug is not None and plug["symbols"] is not None and sym not in plug["symbols"]:
        return None
    s = series_for(sym, ACTIVE["strategy"], bars)
    b = bars_of(sym, bars)
    i = ci - 1
    side = side_for(ACTIVE["strategy"], s, b, i)
    if side == 0:
        return None
    atr = s["atr"][i]
    if atr is None or atr <= 0:
        return None
    sl = ACTIVE["sl_atr"] * atr / pip_size
    if plug is not None and plug["spread_min_mult"] is not None:
        if round(sl, 1) < plug["spread_min_mult"] * spread_pips_for(sym, tech):
            return None
    return {"action": "BUY" if side == 1 else "SELL", "entry_source": ACTIVE["strategy"],
            "exits": {"sl_pips": round(sl, 1), "tp_pips": round(sl * ACTIVE["tp_r"], 1)}}


# ------------------------------------------------------------------ gunluk degerlendirme
def daily_eval(report_path: str) -> dict:
    rep = json.load(open(report_path, encoding="utf-8"))
    new = rep["variants"]["NEW"]
    closed = new.get("closed", [])
    per_day: dict = {}
    per_sym_day: dict = {}
    for t in closed:
        if not t.get("closed_ts"):
            continue
        d = datetime.fromtimestamp(t["closed_ts"], timezone.utc).strftime("%Y-%m-%d")
        per_day[d] = per_day.get(d, 0.0) + t["pnl_usd"]
        per_sym_day.setdefault(t["symbol"], {})
        per_sym_day[t["symbol"]][d] = per_sym_day[t["symbol"]].get(d, 0.0) + t["pnl_usd"]

    def summ(dd: dict, start: str) -> dict:
        vals = [v for d, v in dd.items() if d >= start]
        return {
            "days_with_trades": len(vals),
            "target_days": sum(1 for v in vals if v >= TARGET_USD),
            "ruin_days": sum(1 for v in vals if v <= RUIN_USD),
            "positive_days": sum(1 for v in vals if v > 0),
            "sum": round(sum(vals), 2),
            "mean": None if not vals else round(statistics.mean(vals), 2),
            "median": None if not vals else round(statistics.median(vals), 2),
            "best": None if not vals else round(max(vals), 2),
            "worst": None if not vals else round(min(vals), 2),
        }

    out = {"trades": new["trades"], "win_rate": new["win_rate"], "net": new["net_pnl_usd"], "pf": new["profit_factor"],
           "combined": {"14w": summ(per_day, WIN_14W), "7w": summ(per_day, WIN_7W)},
           "per_symbol": {s: {"14w": summ(dd, WIN_14W), "7w": summ(dd, WIN_7W)} for s, dd in per_sym_day.items()},
           "daily": {d: round(v, 2) for d, v in sorted(per_day.items())}}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True, choices=STRATEGIES)
    ap.add_argument("--tf", required=True, choices=("m1", "m3", "m5", "m15", "m30"))
    ap.add_argument("--symbols", default="XAUUSD,BTCUSD", help="Virgullu sembol listesi (motor --symbols)")
    ap.add_argument("--cache", default="", help="Onbellek dosyasi (bos = outputs/replay_cache_xaubtc_<tf>.json)")
    ap.add_argument("--source", default="cache", choices=("cache", "db"), help="db = PostgreSQL historical_candles (MT5 koprusu/ingest)")
    ap.add_argument("--sl-atr", type=float, default=None, help="bos = eklenti varsayilani, o da yoksa 1.5")
    ap.add_argument("--tp-r", type=float, default=None, help="bos = eklenti varsayilani, o da yoksa 2.0")
    ap.add_argument("--risk-gold", type=float, default=0.0, help="0 = sistem ayari (canli %10)")
    ap.add_argument("--risk-btc", type=float, default=0.0, help="0 = sistem ayari (canli %2)")
    ap.add_argument("--start", default=WIN_14W)
    ap.add_argument("--end", default="2026-10-28")
    ap.add_argument("--tag", default="")
    ap.add_argument("--extra", default="", help="Motora aynen gecirilecek ek argumanlar (bosluklu)")
    args = ap.parse_args()

    plug = PLUGINS.get(args.strategy) or {}
    args.sl_atr = args.sl_atr if args.sl_atr is not None else (plug.get("sl_atr") or SL_ATR)
    args.tp_r = args.tp_r if args.tp_r is not None else (plug.get("tp_r") or TP_R)
    ACTIVE.update({"strategy": args.strategy, "sl_atr": args.sl_atr, "tp_r": args.tp_r})
    rp._entry_mode_candidate = candidate
    if args.risk_gold > 0:
        forex._AUTO_SETTINGS.risk_gold_pct = args.risk_gold
    if args.risk_btc > 0:
        forex._AUTO_SETTINGS.risk_crypto_pct = args.risk_btc
    tag = args.tag or f"{args.strategy}_{args.tf}"
    out_dir = os.path.join(ROOT, "outputs", "replay_strateji")
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, f"rep_{tag}.json")
    cache = args.cache or os.path.join(ROOT, "outputs", f"replay_cache_xaubtc_{args.tf}.json")
    src_args = ["--source", "db"] if args.source == "db" else ["--cache", cache, "--source", "cache"]
    argv = ["forex_replay_backtest.py"] + src_args + ["--days", "130",
            "--symbols", args.symbols, "--balance", "1000", "--entry-mode", "pullback", "--skip-old",
            "--interval", {"m1": "1m", "m3": "3m", "m5": "5m", "m15": "15m", "m30": "30m"}[args.tf],
            "--start", args.start, "--end", args.end, "--out", report_path, "--tag", tag]
    if args.extra:
        argv += args.extra.split()
    sys.argv = argv
    rp.main()
    ev = daily_eval(report_path)
    ev["strategy"], ev["tf"], ev["sl_atr"], ev["tp_r"] = args.strategy, args.tf, args.sl_atr, args.tp_r
    ev["risk_gold"], ev["risk_btc"], ev["extra"] = args.risk_gold or "sistem", args.risk_btc or "sistem", args.extra
    with open(os.path.join(out_dir, f"gun_{tag}.json"), "w", encoding="utf-8") as fh:
        json.dump(ev, fh, ensure_ascii=False, indent=1)
    c14, c7 = ev["combined"]["14w"], ev["combined"]["7w"]
    print(f"[GUNLUK] {tag}: islem {ev['trades']} wr {ev['win_rate']} net {ev['net']} | 14h hedef {c14['target_days']}/{c14['days_with_trades']} "
          f"iflas {c14['ruin_days']} ort {c14['mean']} | 7h hedef {c7['target_days']}/{c7['days_with_trades']} ort {c7['mean']}")


if __name__ == "__main__":
    main()
