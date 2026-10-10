#!/usr/bin/env python3
"""Yeni scalping stratejisi araştırması — 5m bar replays (XAUUSD + BTCUSD).

Araştırma bulgusu (2026-10-10): ORB altın/kriptoda ÇÜRÜK; en tekrarlanabilir
5m edge'leri (a) session-VWAP z-skor ortalamaya dönüş (ADX rejim kapısıyla) ve
(b) zaman-dilimi volatilite-koni momentum (Noise Area). Bu harness ikisini de
gerçek spread maliyetiyle bar-bar simüle eder.

Maliyetler (MT5 p95 ölçümü): XAUUSD 1.1 pip, BTCUSD 5.0 pip — round-trip.
Kural: girişte spread'in YARISI kadar olumsuz kayma uygulanır (mid→bid/ask).

Bar formatı giriş: {SYMBOL: [[ts, o, h, l, c], ...]}

Kullanım:
    python scripts/scalp_strategy_research.py --cache outputs/scalp_cache_3d_5m.json --label "3 GÜN"
    python scripts/scalp_strategy_research.py --cache outputs/scalp_cache_32d_5m.json --label "32 GÜN"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# sembol → (pip_size, spread_pips_p95)
SPECS = {
    "XAUUSD": {"pip": 0.1, "spread_pips": 1.1},
    "BTCUSD": {"pip": 1.0, "spread_pips": 5.0},
}


# ----------------------------- göstergeler -----------------------------
def ema(vals, period):
    out = np.full(len(vals), np.nan)
    if len(vals) < period:
        return out
    cur = float(np.mean(vals[:period]))
    out[period - 1] = cur
    a = 2.0 / (period + 1)
    for i in range(period, len(vals)):
        cur = a * float(vals[i]) + (1 - a) * cur
        out[i] = cur
    return out


def atr(h, l, c, period=14):
    n = len(c)
    tr = np.full(n, np.nan)
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    # Wilder
    out[period] = np.nanmean(tr[1:period + 1])
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def rsi(c, period=14):
    n = len(c)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    d = np.diff(c)
    g = np.where(d > 0, d, 0.0); ls = np.where(d < 0, -d, 0.0)
    ag = float(np.mean(g[:period])); al = float(np.mean(ls[:period]))
    out[period] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(period, len(d)):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + ls[i]) / period
        out[i + 1] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def adx(h, l, c, period=14):
    n = len(c)
    out = np.full(n, np.nan)
    if n < 2 * period + 2:
        return out
    tr = np.full(n - 1, np.nan)
    tr[:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    up = h[1:] - h[:-1]; dn = l[:-1] - l[1:]
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    def wilder(v, p):
        o = np.full(len(v), np.nan)
        if len(v) < p:
            return o
        o[p - 1] = np.mean(v[:p])
        for i in range(p, len(v)):
            o[i] = (o[i - 1] * (p - 1) + v[i]) / p
        return o
    trw = wilder(tr, period); pw = wilder(plus, period); mw = wilder(minus, period)
    dx = np.full(len(trw), np.nan)
    for k in range(len(trw)):
        if np.isnan(trw[k]) or trw[k] == 0:
            continue
        p = 100 * pw[k] / trw[k]; m = 100 * mw[k] / trw[k]
        dx[k] = 100 * abs(p - m) / (p + m) if (p + m) else 0.0
    dxv = dx[~np.isnan(dx)]
    adxw = wilder(dxv, period)
    for j in range(len(adxw)):
        out[1 + (period - 1) + j] = adxw[j]
    return out


# ----------------------------- yardımcılar -----------------------------
def day_key(ts):
    return dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")


def session_vwap(ts_arr, h, l, c, v=None):
    """Her gün UTC 00:00'da sıfırlanan kümülatif tipik-fiyat VWAP + sapma serisi."""
    n = len(c)
    vwap = np.full(n, np.nan)
    typ = (h + l + c) / 3.0
    vol = v if v is not None else np.ones(n)
    cur_day = None; cum_pv = 0.0; cum_v = 0.0
    for i in range(n):
        d = day_key(ts_arr[i])
        if d != cur_day:
            cur_day = d; cum_pv = 0.0; cum_v = 0.0
        cum_pv += typ[i] * vol[i]; cum_v += vol[i]
        if cum_v > 0:
            vwap[i] = cum_pv / cum_v
    dev = c - vwap
    return vwap, dev


def rolling_sigma(dev, period=20):
    n = len(dev)
    out = np.full(n, np.nan)
    for i in range(period - 1, n):
        s = dev[i - period + 1:i + 1]
        if np.any(np.isnan(s)):
            continue
        out[i] = float(np.std(s))
    return out


# ----------------------------- simülatör -----------------------------
def simulate(entries, c, h, l, ts, pip, spread_pips, sl_atr, tp_mode, atr_series,
             max_hold, one_position=True, tp_rr=2.0):
    """entries: liste (i, dir) — dir +1 long / -1 short. Bar-i kapanışından girer."""
    half_spread_price = (spread_pips * pip) / 2.0
    n = len(c)
    trades = []
    busy_until = -1
    for (i, dr) in entries:
        if one_position and i <= busy_until:
            continue
        a = atr_series[i]
        if not np.isfinite(a) or a <= 0:
            continue
        entry = c[i] + dr * half_spread_price          # girişte spread'in yarısı aleyhte
        sl = entry - dr * sl_atr * a
        if tp_mode == "vwap":
            tp = None  # dışarıdan verilir
        else:
            tp = entry + dr * tp_rr * sl_atr * a
        exit_price = None; exit_i = None
        end = min(n - 1, i + max_hold)
        for j in range(i + 1, end + 1):
            if dr == 1:
                if l[j] <= sl:
                    exit_price = sl; exit_i = j; break
                if tp is not None and h[j] >= tp:
                    exit_price = tp; exit_i = j; break
            else:
                if h[j] >= sl:
                    exit_price = sl; exit_i = j; break
                if tp is not None and l[j] <= tp:
                    exit_price = tp; exit_i = j; break
        if exit_price is None:
            exit_i = end
            exit_price = c[end]
        # çıkışta da spread'in yarısı aleyhte
        exit_price = exit_price - dr * half_spread_price
        gross_pips = dr * (exit_price - entry) / pip
        trades.append({"i": i, "exit_i": exit_i, "dir": dr, "pips": gross_pips,
                       "bars": exit_i - i})
        busy_until = exit_i
    return trades


def trade_stats(trades, label, capital_usd=10000.0, usd_per_pip_per_lot=10.0, lot=0.1):
    """pips → USD: XAUUSD 0.1 lot için ~$1/pip; burada nötr raporlama."""
    if not trades:
        return {"label": label, "n": 0}
    p = np.array([t["pips"] for t in trades])
    wins = p[p > 0]; losses = p[p <= 0]
    gross_win = wins.sum() if len(wins) else 0.0
    gross_loss = -losses.sum() if len(losses) else 0.0
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    equity = np.cumsum(p)
    dd = equity - np.maximum.accumulate(equity)
    return {"label": label, "n": len(p), "wr": round(100 * len(wins) / len(p), 1),
            "net_pips": round(float(p.sum()), 1), "exp_pips": round(float(p.mean()), 2),
            "pf": round(pf, 2), "maxdd_pips": round(float(dd.min()), 1),
            "avg_bars": round(float(np.mean([t["bars"] for t in trades])), 1)}


def print_stats(s, n_bars=0, days=0):
    if not s or s.get("n", 0) == 0:
        print(f"  {s.get('label','?'):34} → İŞLEM YOK")
        return
    print(f"  {s['label']:34} n={s['n']:3d} WR=%{s['wr']:5.1f} net={s['net_pips']:+8.1f}pip "
          f"exp={s['exp_pips']:+6.2f}pip PF={s['pf']:4.2f} maxDD={s['maxdd_pips']:+7.1f}pip "
          f"~{s['avg_bars']:.0f}bar")


# ----------------------------- stratejiler -----------------------------
def strat_vwap_reversion(bars, sess_start=None, z_thr=2.0, adx_max=25.0, sl_atr=1.2):
    """Session-VWAP z-skor ortalamaya dönüş (rejim: ADX<eşik)."""
    ts = np.array([b[0] for b in bars]); o = np.array([b[1] for b in bars])
    h = np.array([b[2] for b in bars]); l = np.array([b[3] for b in bars])
    c = np.array([b[4] for b in bars])
    vwap, dev = session_vwap(ts, h, l, c)
    sigma = rolling_sigma(dev, 20)
    atr_s = atr(h, l, c, 14)
    adx_s = adx(h, l, c, 14)
    entries = []
    n = len(c)
    for i in range(40, n):
        if not (np.isfinite(sigma[i]) and sigma[i] > 0 and np.isfinite(adx_s[i])):
            continue
        if adx_s[i] >= adx_max:
            continue
        z = dev[i] / sigma[i]
        hh = dt.datetime.utcfromtimestamp(ts[i]).hour
        # seans filtresi (verilmişse)
        if sess_start is not None and not (sess_start[0] <= hh < sess_start[1]):
            continue
        # geri dönüş mumu: z aşırı + mum VWAP'a doğru kapanıyor
        if z <= -z_thr and c[i] > o[i]:
            entries.append((i, 1))
        elif z >= z_thr and c[i] < o[i]:
            entries.append((i, -1))
    return entries, {"h": h, "l": l, "c": c, "ts": ts, "atr": atr_s, "vwap": vwap}


def strat_noise_area(bars, vm=1.5, lookback_days=14, adx_max=100.0):
    """Zarattini Noise-Area intraday momentum — 30dk işaretlerde, VWAP teyitli."""
    ts = np.array([b[0] for b in bars]); o = np.array([b[1] for b in bars])
    h = np.array([b[2] for b in bars]); l = np.array([b[3] for b in bars])
    c = np.array([b[4] for b in bars])
    n = len(c)
    # gün açılışları
    days = {}
    for i in range(n):
        days.setdefault(day_key(ts[i]), []).append(i)
    day_list = sorted(days)
    # her gün için: bucket → |open→o saat| ortalaması (son lookback gün)
    entries = []
    vwap, _ = session_vwap(ts, h, l, c)
    for di, d in enumerate(day_list):
        idx = days[d]
        if di < 1:
            continue
        ref_idx = idx[0]
        day_open = o[ref_idx]
        prev_close = c[days[day_list[di - 1]][-1]]
        base_hi = max(day_open, prev_close); base_lo = min(day_open, prev_close)
        # sigma_bar: son lookback günün günlük aralık ortalaması / bar sayısı
        hist = []
        for k in range(max(0, di - lookback_days), di):
            j = days[day_list[k]]
            hist.append((h[j].max() - l[j].min()) / day_open)
        sb = float(np.mean(hist)) if hist else 0.004
        ub = base_hi * (1 + sb * vm); lb = base_lo * (1 - sb * vm)
        for pos, i in enumerate(idx):
            minute = dt.datetime.utcfromtimestamp(ts[i]).minute
            if minute not in (0, 30):
                continue
            if not np.isfinite(vwap[i]):
                continue
            if c[i] > ub and c[i] > vwap[i]:
                entries.append((i, 1))
            elif c[i] < lb and c[i] < vwap[i]:
                entries.append((i, -1))
    atr_s = atr(h, l, c, 14)
    return entries, {"h": h, "l": l, "c": c, "ts": ts, "atr": atr_s, "vwap": vwap}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--symbols", default="XAUUSD,BTCUSD")
    args = ap.parse_args()

    path = args.cache if os.path.isabs(args.cache) else os.path.join(ROOT, args.cache)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    print("=" * 108)
    print(f"YENİ SCALPING STRATEJİ ARAŞTIRMASI — {args.label}  ({os.path.basename(path)})")
    print("=" * 108)

    for sym in args.symbols.split(","):
        sym = sym.strip()
        bars = data.get(sym)
        if not bars:
            print(f"\n### {sym}: veri yok")
            continue
        spec = SPECS[sym]
        pip = spec["pip"]; spr = spec["spread_pips"]
        ts = np.array([b[0] for b in bars])
        d0 = dt.datetime.utcfromtimestamp(ts[0]); d1 = dt.datetime.utcfromtimestamp(ts[-1])
        span_days = (ts[-1] - ts[0]) / 86400.0
        c_arr = np.array([b[4] for b in bars])
        print(f"\n### {sym}  {len(bars)} bar  {d0:%Y-%m-%d %H:%M}→{d1:%Y-%m-%d %H:%M} UTC "
              f"(~{span_days:.1f} gün)  fiyat {c_arr[0]:.2f}→{c_arr[-1]:.2f} "
              f"({(c_arr[-1]/c_arr[0]-1)*100:+.2f}%)")
        print(f"    maliyet: {spr} pip spread (round-trip), giriş/çıkışta yarımşar uygulanır")

        # --- A) VWAP reversion (tam gün / seans) ---
        for tag, sess in (("A1 VWAP-z(2.0) ADX<25 tüm-gün", None),
                          ("A2 VWAP-z(2.0) ADX<25 07-16 UTC", (7, 16)),
                          ("A3 VWAP-z(2.5) ADX<20 tüm-gün", None)):
            zt = 2.5 if "2.5" in tag else 2.0
            am = 20.0 if "ADX<20" in tag else 25.0
            entries, ctx = strat_vwap_reversion(bars, sess_start=sess, z_thr=zt, adx_max=am)
            tr = simulate(entries, ctx["c"], ctx["h"], ctx["l"], ctx["ts"], pip, spr,
                          sl_atr=1.2, tp_mode="rr", atr_series=ctx["atr"], max_hold=24, tp_rr=1.5)
            print_stats(trade_stats(tr, tag), len(bars), span_days)

        # --- B) Noise-area momentum ---
        for tag, vm in (("B1 NoiseArea VM1.5", 1.5), ("B2 NoiseArea VM2.0", 2.0)):
            entries, ctx = strat_noise_area(bars, vm=vm)
            tr = simulate(entries, ctx["c"], ctx["h"], ctx["l"], ctx["ts"], pip, spr,
                          sl_atr=1.5, tp_mode="rr", atr_series=ctx["atr"], max_hold=48, tp_rr=2.0)
            print_stats(trade_stats(tr, tag), len(bars), span_days)

        # --- C) referans: her yönde rastgele değil, basit EMA-trend (kıyas) ---
        ctxc = {"h": np.array([b[2] for b in bars]), "l": np.array([b[3] for b in bars]),
                "c": c_arr, "ts": ts}
        ema50 = ema(c_arr, 50); ema200 = ema(c_arr, 200)
        atr_s = atr(ctxc["h"], ctxc["l"], ctxc["c"], 14)
        ent = []
        for i in range(200, len(c_arr)):
            if np.isfinite(ema50[i]) and np.isfinite(ema200[i]):
                if c_arr[i] > ema200[i] and ema50[i] > ema200[i]:
                    ent.append((i, 1))
                elif c_arr[i] < ema200[i] and ema50[i] < ema200[i]:
                    ent.append((i, -1))
        tr = simulate(ent, ctxc["c"], ctxc["h"], ctxc["l"], ts, pip, spr, sl_atr=1.5,
                      tp_mode="rr", atr_series=atr_s, max_hold=48, tp_rr=2.0)
        print_stats(trade_stats(tr, "C0 referans EMA50/200 trend"), len(bars), span_days)


if __name__ == "__main__":
    main()
