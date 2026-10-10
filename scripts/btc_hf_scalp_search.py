#!/usr/bin/env python3
"""YÜKSEK-FREKANS BTCUSD scalping arama — hedef: >=30 işlem/gün VE net>0.

1m barlar. BTCUSD spread 5 pip ($5 = %0.006) gerçek MT5 ölçümü.
Her strateji + parametre grid'i denenir; işlem/gün ve maliyet-sonrası net ölçülür.

Aileler:
  1) BB z-skor fade (1m)          — ortalamaya dönüş
  2) RSI(n) aşırı-uç fade         — ortalamaya dönüş
  3) N-bar kırılım (breakout)     — momentum
  4) EMA çift-kesişim             — trend
  5) VWAP band fade (gün-içi)     — ortalamaya dönüş
  6) Ardışık-mum fade (3-4 aynı yön sonra dönüş)

Kullanım:
    python scripts/btc_hf_scalp_search.py \
        --cache outputs/scalp_cache_btc_30d_1m.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import scalp_strategy_research as S  # noqa: E402

BTC_PIP = 1.0          # BTCUSD pip_size = 1.0
BTC_SPREAD = 5.0       # p95 pips (canlı ölçüm)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["BTCUSD"]


def arrays(bars):
    return (np.array([b[0] for b in bars]), np.array([b[1] for b in bars]),
            np.array([b[2] for b in bars]), np.array([b[3] for b in bars]),
            np.array([b[4] for b in bars]))


# ------------------------------- sinyal üreticiler -------------------------------
def sig_bb_fade(c, period, z_thr):
    n = len(c)
    out = []
    for i in range(period, n):
        seg = c[i - period:i]
        m = seg.mean(); sd = seg.std()
        if sd <= 0:
            continue
        z = (c[i] - m) / sd
        if z <= -z_thr:
            out.append((i, 1))
        elif z >= z_thr:
            out.append((i, -1))
    return out


def sig_rsi_fade(c, period, lo, hi):
    r = S.rsi(c, period)
    out = []
    for i in range(period + 1, len(c)):
        if not np.isfinite(r[i]):
            continue
        if r[i] <= lo:
            out.append((i, 1))
        elif r[i] >= hi:
            out.append((i, -1))
    return out


def sig_nbar_break(c, h, l, k):
    out = []
    for i in range(k, len(c)):
        hi = h[i - k:i].max(); lo = l[i - k:i].min()
        if c[i] > hi:
            out.append((i, 1))
        elif c[i] < lo:
            out.append((i, -1))
    return out


def sig_ema_cross(c, fast, slow):
    f = S.ema(c, fast); s = S.ema(c, slow)
    out = []
    for i in range(slow + 1, len(c)):
        if not (np.isfinite(f[i]) and np.isfinite(s[i])):
            continue
        if f[i - 1] <= s[i - 1] and f[i] > s[i]:
            out.append((i, 1))
        elif f[i - 1] >= s[i - 1] and f[i] < s[i]:
            out.append((i, -1))
    return out


def sig_vwap_fade(ts, h, l, c, z_thr):
    vwap, dev = S.session_vwap(ts, h, l, c)
    sig = S.rolling_sigma(dev, 30)
    out = []
    for i in range(40, len(c)):
        if not (np.isfinite(sig[i]) and sig[i] > 0):
            continue
        z = dev[i] / sig[i]
        if z <= -z_thr:
            out.append((i, 1))
        elif z >= z_thr:
            out.append((i, -1))
    return out


def sig_run_fade(c, run):
    out = []
    for i in range(run + 1, len(c)):
        ups = all(c[i - j] > c[i - j - 1] for j in range(run))
        dns = all(c[i - j] < c[i - j - 1] for j in range(run))
        if ups:
            out.append((i, -1))   # yükseliş sonrası dönüş
        elif dns:
            out.append((i, 1))
    return out


# ------------------------------- simülatör -------------------------------
def sim(entries, c, h, l, sl_ticks, tp_ticks, max_hold):
    """Girişte spread'in yarısı aleyhte; SL/TP fiyat-cinsinden ($). tek pozisyon."""
    half = BTC_SPREAD * BTC_PIP / 2.0
    n = len(c)
    trades = []
    busy = -1
    for (i, dr) in entries:
        if i <= busy:
            continue
        if i + 1 >= n:
            break
        entry = c[i] + dr * half
        sl = entry - dr * sl_ticks
        tp = entry + dr * tp_ticks
        ex = None; ei = None
        end = min(n - 1, i + max_hold)
        for j in range(i + 1, end + 1):
            if dr == 1:
                if l[j] <= sl: ex, ei = sl, j; break
                if h[j] >= tp: ex, ei = tp, j; break
            else:
                if h[j] >= sl: ex, ei = sl, j; break
                if l[j] <= tp: ex, ei = tp, j; break
        if ex is None:
            ei = end; ex = c[end]
        ex -= dr * half
        pips = dr * (ex - entry) / BTC_PIP
        trades.append({"i": i, "ei": ei, "dir": dr, "pips": pips, "bars": ei - i})
        busy = ei
    return trades


def stats(tr, days):
    if not tr:
        return None
    p = np.array([t["pips"] for t in tr])
    wins = p[p > 0]; losses = p[p <= 0]
    pf = wins.sum() / -losses.sum() if len(losses) and losses.sum() < 0 else float("inf")
    eq = np.cumsum(p); dd = (eq - np.maximum.accumulate(eq)).min()
    return {"n": len(p), "per_day": len(p) / days, "net": p.sum(), "exp": p.mean(),
            "wr": 100 * (p > 0).mean(), "pf": pf, "dd": dd,
            "bars": float(np.mean([t["bars"] for t in tr]))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="outputs/scalp_cache_btc_30d_1m.json")
    ap.add_argument("--min-per-day", type=float, default=30.0)
    args = ap.parse_args()
    path = args.cache if os.path.isabs(args.cache) else os.path.join(ROOT, args.cache)
    bars = load(path)
    ts, o, h, l, c = arrays(bars)
    days = len(set(dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d") for t in ts))
    print(f"BTCUSD 1m: {len(c)} bar, {days} gün, {len(c)/days:.0f} bar/gün, "
          f"spread {BTC_SPREAD}pip (${BTC_SPREAD})\n")

    results = []

    def try_strat(name, entries, sl_t, tp_t, mh):
        tr = sim(entries, c, h, l, sl_t, tp_t, mh)
        st = stats(tr, days)
        if st:
            st["name"] = f"{name} SL{sl_t:.0f}/TP{tp_t:.0f}/H{mh}"; results.append(st)

    # --- 1) BB fade ---
    for period in (20, 50):
        for z in (1.5, 2.0, 2.5):
            e = sig_bb_fade(c, period, z)
            for sl, tp in ((40, 40), (30, 60), (60, 60)):
                try_strat(f"BBfade p{period} z{z}", e, sl, tp, 20)

    # --- 2) RSI fade ---
    for period in (2, 3, 7, 14):
        for lo, hi in ((5, 95), (10, 90), (20, 80), (30, 70)):
            e = sig_rsi_fade(c, period, lo, hi)
            for sl, tp in ((40, 40), (30, 60)):
                try_strat(f"RSIfade p{period} {lo}/{hi}", e, sl, tp, 15)

    # --- 3) N-bar breakout ---
    for k in (5, 10, 20, 30):
        e = sig_nbar_break(c, h, l, k)
        for sl, tp in ((40, 40), (30, 45), (50, 50), (30, 90)):
            try_strat(f"BRK k{k}", e, sl, tp, 30)

    # --- 4) EMA cross ---
    for f, s in ((5, 20), (9, 21), (12, 26), (3, 10)):
        e = sig_ema_cross(c, f, s)
        for sl, tp in ((40, 40), (30, 60), (50, 100)):
            try_strat(f"EMA{f}/{s}", e, sl, tp, 30)

    # --- 5) VWAP fade ---
    for z in (1.5, 2.0, 2.5, 3.0):
        e = sig_vwap_fade(ts, h, l, c, z)
        for sl, tp in ((40, 40), (30, 60)):
            try_strat(f"VWAPfade z{z}", e, sl, tp, 20)

    # --- 6) Run fade ---
    for run in (3, 4, 5):
        e = sig_run_fade(c, run)
        for sl, tp in ((40, 40), (30, 60)):
            try_strat(f"RunFade r{run}", e, sl, tp, 15)

    # --- rapor ---
    results.sort(key=lambda r: r["net"], reverse=True)
    print(f"{'strateji':28}{'n':>7}{'/gün':>7}{'netpip':>10}{'exp':>7}{'WR%':>6}{'PF':>5}{'maxDD':>9}{'bar':>5}")
    print("-" * 92)
    for r in results[:40]:
        flag = "✅" if (r["per_day"] >= args.min_per_day and r["net"] > 0) else "  "
        print(f"{flag}{r['name']:28}{r['n']:7d}{r['per_day']:7.1f}{r['net']:10.0f}{r['exp']:7.2f}"
              f"{r['wr']:6.1f}{r['pf']:5.2f}{r['dd']:9.0f}{r['bars']:5.0f}")

    ok = [r for r in results if r["per_day"] >= args.min_per_day and r["net"] > 0]
    print(f"\n=== >= {args.min_per_day:.0f} işlem/gün VE net>0 olan: {len(ok)} / {len(results)} ===")
    for r in ok[:15]:
        print(f"  {r['name']:28} {r['per_day']:.1f}/gün net={r['net']:+.0f}pip PF={r['pf']:.2f} WR=%{r['wr']:.1f} DD={r['dd']:.0f}")
    out = os.path.join(ROOT, "outputs", "btc_hf_scalp_results.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"days": days, "spread": BTC_SPREAD,
                   "results": [{k: (None if isinstance(v, float) and not np.isfinite(v) else v)
                                for k, v in r.items()} for r in results]}, fh, indent=2)
    print(f"\n[CIKTI] → {out}")


if __name__ == "__main__":
    main()
