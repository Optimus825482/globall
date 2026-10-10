#!/usr/bin/env python3
"""İKİNCİ TUR strateji araştırması — 5m bar replays (XAUUSD + BTCUSD).

Birinci turda A2 (VWAP-z reversion) öne çıkmıştı. Burada FARKLI aileleri test eder:
  1) Intraday Momentum (son 30dk)  — Baltussen/Gao JFE: T-30dk getirisi son 30dk'yı öngörür
  2) BTC seans anomalisi (21:00-23:00 UTC hold) — Quantpedia/Vojtko
  3) RSI-2 aşırı-uç ortalamaya dönüş (Connors) + trend filtresi
  4) Squeeze breakout (Bollinger daralma → genişleme, Keltner teyidi)
  5) ORB (opening range breakout) — literatürde altın/kripto için FALSİFİYE, kontrol amaçlı
  6) VWAP trend-devam (fiyat VWAP üstü + geri çekilme sonrası teyit)

Maliyet: XAUUSD 1.1 pip, BTCUSD 5.0 pip (round-trip), yarımşar uygulanır.

Kullanım:
    python scripts/scalp_strategy_round2.py --cache outputs/scalp_cache_5d_pazt_cuma.json --label "5 GUN"
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

SPECS = S.SPECS


def minute_of_day(ts):
    d = dt.datetime.utcfromtimestamp(ts)
    return d.hour * 60 + d.minute


def pips_between(a, b, pip):
    return (b - a) / pip


# -------------------- 1) INTRADAY MOMENTUM (son 30 dakika) --------------------
def strat_intraday_momentum(bars, sl_atr=1.5, tp_rr=1.0):
    """T-30dk'ya kadarki gün-içi getiri (rROD) yönünde son 30dk pozisyon."""
    ts = np.array([b[0] for b in bars]); c = np.array([b[4] for b in bars])
    h = np.array([b[2] for b in bars]); l = np.array([b[3] for b in bars])
    n = len(c)
    days = {}
    for i in range(n):
        days.setdefault(S.day_key(ts[i]), []).append(i)
    day_list = sorted(days)
    atr_s = S.atr(h, l, c, 14)
    entries = []
    for di in range(1, len(day_list)):
        idx = days[day_list[di]]
        prev_close = c[days[day_list[di - 1]][-1]]
        # gün içinde son 30 dk = son 6 bar; ondan önceki bar T-30
        if len(idx) < 12:
            continue
        t30 = idx[-6]           # son 6 barın ilki (30 dk)
        if c[t30] > prev_close:      # rROD > 0
            entries.append((t30, 1))
        elif c[t30] < prev_close:
            entries.append((t30, -1))
    return entries, {"c": c, "h": h, "l": l, "ts": ts, "atr": atr_s}


# -------------------- 2) BTC SEANS ANOMALISI (21:00-23:00 UTC) --------------------
def strat_session_hold(bars, start_h, end_h, trend_ma=200):
    """Her gün start_h UTC'de gir, end_h'de çık (trend MA üstünde long, altında short)."""
    ts = np.array([b[0] for b in bars]); c = np.array([b[4] for b in bars])
    h = np.array([b[2] for b in bars]); l = np.array([b[3] for b in bars])
    n = len(c)
    ma = S.ema(c, trend_ma)
    atr_s = S.atr(h, l, c, 14)
    entries = []
    for i in range(trend_ma, n):
        if not np.isfinite(ma[i]):
            continue
        d = dt.datetime.utcfromtimestamp(ts[i])
        if d.hour != start_h or d.minute != 0:
            continue
        entries.append((i, 1 if c[i] > ma[i] else -1))
    return entries, {"c": c, "h": h, "l": l, "ts": ts, "atr": atr_s}


# -------------------- 3) RSI-2 ORTALAMAYA DÖNÜŞ (Connors) --------------------
def strat_rsi2(bars, rsi_buy=5.0, rsi_sell=95.0, trend_ma=200):
    """RSI(2) <= rsi_buy & trend üstü → long; RSI(2) >= rsi_sell & trend altı → short."""
    ts = np.array([b[0] for b in bars]); c = np.array([b[4] for b in bars])
    h = np.array([b[2] for b in bars]); l = np.array([b[3] for b in bars])
    r2 = S.rsi(c, 2); ma = S.ema(c, trend_ma); atr_s = S.atr(h, l, c, 14)
    n = len(c)
    entries = []
    for i in range(trend_ma, n):
        if not (np.isfinite(r2[i]) and np.isfinite(ma[i])):
            continue
        if r2[i] <= rsi_buy and c[i] > ma[i]:
            entries.append((i, 1))
        elif r2[i] >= rsi_sell and c[i] < ma[i]:
            entries.append((i, -1))
    return entries, {"c": c, "h": h, "l": l, "ts": ts, "atr": atr_s}


# -------------------- 4) SQUEEZE BREAKOUT --------------------
def strat_squeeze(bars, bb_period=20, kc_mult=1.5, lookback=100):
    """Bollinger daralması (20g persentil altı) sonrası kırılım yönünde gir."""
    ts = np.array([b[0] for b in bars]); c = np.array([b[4] for b in bars])
    h = np.array([b[2] for b in bars]); l = np.array([b[3] for b in bars])
    atr_s = S.atr(h, l, c, 14)
    n = len(c)
    bbw = np.full(n, np.nan); up = np.full(n, np.nan); dn = np.full(n, np.nan)
    for i in range(bb_period - 1, n):
        seg = c[i - bb_period + 1:i + 1]; m = seg.mean(); sd = seg.std()
        if m:
            bbw[i] = 2 * 2.0 * sd / m * 100
            up[i] = m + 2.0 * sd; dn[i] = m - 2.0 * sd
    entries = []
    for i in range(max(bb_period, lookback), n):
        if not (np.isfinite(bbw[i]) and np.isfinite(atr_s[i])):
            continue
        hist = bbw[i - lookback:i]
        hist = hist[np.isfinite(hist)]
        if len(hist) < 20:
            continue
        thr = np.percentile(hist, 20)
        if bbw[i - 1] <= thr:                    # dünkü bar sıkışıktı
            if c[i] > up[i]:
                entries.append((i, 1))
            elif c[i] < dn[i]:
                entries.append((i, -1))
    return entries, {"c": c, "h": h, "l": l, "ts": ts, "atr": atr_s}


# -------------------- 5) ORB (opening range breakout) — kontrol --------------------
def strat_orb(bars, or_minutes=30, sl_atr=1.0, tp_rr=1.0):
    """Seans açılışında ilk or_minutes aralığını kır → o yönde gir (gün içi)."""
    ts = np.array([b[0] for b in bars]); c = np.array([b[4] for b in bars])
    h = np.array([b[2] for b in bars]); l = np.array([b[3] for b in bars])
    o = np.array([b[1] for b in bars])
    atr_s = S.atr(h, l, c, 14)
    n = len(c)
    days = {}
    for i in range(n):
        days.setdefault(S.day_key(ts[i]), []).append(i)
    entries = []
    for d, idx in days.items():
        if len(idx) < or_minutes // 5 + 6:
            continue
        or_idx = idx[:or_minutes // 5]
        orh = h[or_idx].max(); orl = l[or_idx].min()
        for i in idx[or_minutes // 5:]:
            if h[i] > orh:
                entries.append((i, 1)); break
            if l[i] < orl:
                entries.append((i, -1)); break
    return entries, {"c": c, "h": h, "l": l, "ts": ts, "atr": atr_s}


# -------------------- 6) VWAP TREND-DEVAM --------------------
def strat_vwap_trend(bars, ema_len=50):
    """Fiyat > EMA50 > EMA200 (ya da tersi) VE fiyat VWAP'ın doğru tarafında → devam."""
    ts = np.array([b[0] for b in bars]); c = np.array([b[4] for b in bars])
    h = np.array([b[2] for b in bars]); l = np.array([b[3] for b in bars])
    vwap, _ = S.session_vwap(ts, h, l, c)
    e50 = S.ema(c, ema_len); e200 = S.ema(c, 200); atr_s = S.atr(h, l, c, 14)
    n = len(c)
    entries = []
    for i in range(201, n):
        if not (np.isfinite(vwap[i]) and np.isfinite(e50[i]) and np.isfinite(e200[i])):
            continue
        if c[i] > vwap[i] and e50[i] > e200[i] and c[i] > e50[i]:
            entries.append((i, 1))
        elif c[i] < vwap[i] and e50[i] < e200[i] and c[i] < e50[i]:
            entries.append((i, -1))
    return entries, {"c": c, "h": h, "l": l, "ts": ts, "atr": atr_s}


def run(bars, pip, spr, tag, mk, sl_atr, tp_rr, max_hold):
    entries, ctx = mk(bars)
    tr = S.simulate(entries, ctx["c"], ctx["h"], ctx["l"], ctx["ts"], pip, spr,
                    sl_atr=sl_atr, tp_mode="rr", atr_series=ctx["atr"],
                    max_hold=max_hold, tp_rr=tp_rr)
    return tr, ctx


def day_report(tr, ts, label):
    by = {}
    for t in tr:
        d = dt.datetime.utcfromtimestamp(ts[t["i"]]).strftime("%a %m-%d")
        by.setdefault(d, []).append(t["pips"])
    if not tr:
        print(f"    {label:34} → işlem yok")
        return
    p = np.array([t["pips"] for t in tr])
    st = S.trade_stats(tr, label)
    line = f"    {label:34} n={len(p):3d} net={p.sum():+8.1f}pip exp={p.mean():+6.2f} PF={st['pf']:.2f} "
    line += " | " + " ".join(f"{d.split()[0]}:{sum(v):+.0f}" for d, v in sorted(by.items()))
    print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--symbols", default="XAUUSD,BTCUSD")
    args = ap.parse_args()
    path = args.cache if os.path.isabs(args.cache) else os.path.join(ROOT, args.cache)
    data = json.load(open(path, encoding="utf-8"))

    print("=" * 112)
    print(f"2. TUR STRATEJİ ARAŞTIRMASI — {args.label}  ({os.path.basename(path)})")
    print("=" * 112)

    for sym in args.symbols.split(","):
        sym = sym.strip()
        bars = data.get(sym)
        if not bars:
            continue
        pip = SPECS[sym]["pip"]; spr = SPECS[sym]["spread_pips"]
        ts0 = bars[0][0]; ts1 = bars[-1][0]
        print(f"\n### {sym}  {len(bars)} bar  "
              f"{dt.datetime.utcfromtimestamp(ts0):%m-%d %H:%M}→{dt.datetime.utcfromtimestamp(ts1):%m-%d %H:%M} UTC")
        tr, ctx = run(bars, pip, spr, "intraday-mom", strat_intraday_momentum, 1.5, 1.0, 8)
        day_report(tr, ctx["ts"], "1) Intraday-mom son30dk")
        for sh, eh in [(21, 23), (7, 10), (13, 16)]:
            tr, ctx = run(bars, pip, spr, f"seans{sh}", lambda b, a=sh, c=eh: strat_session_hold(b, a, c), 1.5, 1.0, 40)
            day_report(tr, ctx["ts"], f"2) seans-hold {sh:02d}-{eh:02d} UTC")
        tr, ctx = run(bars, pip, spr, "rsi2", strat_rsi2, 1.5, 1.5, 24)
        day_report(tr, ctx["ts"], "3) RSI-2 MR + trend filt.")
        tr, ctx = run(bars, pip, spr, "squeeze", strat_squeeze, 1.5, 2.0, 48)
        day_report(tr, ctx["ts"], "4) Squeeze breakout")
        tr, ctx = run(bars, pip, spr, "orb", strat_orb, 1.0, 1.0, 60)
        day_report(tr, ctx["ts"], "5) ORB (kontrol)")
        tr, ctx = run(bars, pip, spr, "vwaPTrend", strat_vwap_trend, 1.5, 2.0, 48)
        day_report(tr, ctx["ts"], "6) VWAP trend-devam")


if __name__ == "__main__":
    main()
