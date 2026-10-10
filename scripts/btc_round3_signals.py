#!/usr/bin/env python3
"""3. TUR: YÖN-BAĞIMSIZ + REJİM-KOŞULLU + FUNDING sinyalleri (BTCUSD).

2. turda klasik yön stratejilerinin brüt edge'i yoktu. Bu tur literatürün
işaret ettiği farklı kaynakları test eder:
  R1) Volatilite-rejim koşullu MOMENTUM (yalnız yüksek-vol seanslarda devam)
  R2) Volatilite-rejim koşullu REVERSION (yalnız düşük-vol seanslarda dönüş)
  R3) Saat-bazlı seans drift (belirli UTC saatleri long/short) — walk-forward
  R4) Funding-z kontraryen (Binance perp funding aşırı-uç → fade)
  R5) Güniçi TSMOM (ilk 30dk → son 30dk, vol-koşullu)
  R6) Volatilite kırılımı (range-expansion) — sıkışma sonrası yön

Kullanım:
    python scripts/btc_round3_signals.py --interval 1m --days 30
    python scripts/btc_round3_signals.py --interval 5m --days 30
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import scalp_strategy_research as S  # noqa: E402

BTC_PIP = 1.0
BTC_SPREAD = 5.0


def load_bars(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["BTCUSD"]


def arrs(bars):
    return (np.array([b[0] for b in bars]), np.array([b[1] for b in bars]),
            np.array([b[2] for b in bars]), np.array([b[3] for b in bars]),
            np.array([b[4] for b in bars]))


def sim(entries, c, h, l, sl_ticks, tp_ticks, max_hold, spread=BTC_SPREAD):
    """Sabit-$ SL/TP, tek pozisyon, giriş/çıkışta yarım spread."""
    half = spread * BTC_PIP / 2.0
    n = len(c); trades = []; busy = -1
    for (i, dr) in entries:
        if i <= busy or i + 1 >= n:
            continue
        entry = c[i] + dr * half
        sl = entry - dr * sl_ticks; tp = entry + dr * tp_ticks
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
        trades.append({"i": i, "ei": ei, "dir": dr,
                       "pips": dr * (ex - entry) / BTC_PIP, "bars": ei - i})
        busy = ei
    return trades


def stats(tr, days):
    if not tr:
        return None
    p = np.array([t["pips"] for t in tr])
    w = p[p > 0]; ls = p[p <= 0]
    pf = w.sum() / -ls.sum() if len(ls) and ls.sum() < 0 else float("inf")
    dd = (np.cumsum(p) - np.maximum.accumulate(np.cumsum(p))).min()
    return {"n": len(p), "per_day": len(p) / days, "net": p.sum(), "exp": p.mean(),
            "wr": 100 * (p > 0).mean(), "pf": pf, "dd": dd,
            "bars": float(np.mean([t["bars"] for t in tr]))}


def nonoverlap(entries, spacing):
    out = []; last = -10**9
    for (i, dr) in entries:
        if i - last >= spacing:
            out.append((i, dr)); last = i
    return out


# ---------------- R1/R2: rejim-koşullu momentum/reversion ----------------
def regime_mom_rev(ts, o, h, l, c, fast, slow, vol_lookback, vol_pct, mode, sl_t, tp_t, spacing, max_hold):
    """mode='mom': yüksek-vol (vol>=pct) + EMA kesişim yönünde
       mode='rev': düşük-vol (vol< pct) + EMA'dan sapma → ortalamaya dön."""
    f = S.ema(c, fast); s = S.ema(c, slow)
    ret = np.zeros(len(c))
    ret[1:] = np.log(c[1:] / c[:-1])
    rv = np.full(len(c), np.nan)
    for i in range(vol_lookback, len(c)):
        rv[i] = np.std(ret[i - vol_lookback:i])
    ent = []
    for i in range(slow + 1, len(c)):
        if not (np.isfinite(f[i]) and np.isfinite(s[i]) and np.isfinite(rv[i])):
            continue
        thr = np.nanpercentile(rv[max(slow, vol_lookback):i + 1], vol_pct) if i > vol_lookback + 50 else np.nan
        if not np.isfinite(thr):
            continue
        high_vol = rv[i] >= thr
        if mode == "mom":
            if not high_vol:
                continue
            if f[i - 1] <= s[i - 1] and f[i] > s[i]: ent.append((i, 1))
            elif f[i - 1] >= s[i - 1] and f[i] < s[i]: ent.append((i, -1))
        else:  # rev
            if high_vol:
                continue
            dev = (c[i] - f[i]) / f[i]
            if dev <= -0.001 and c[i] > o[i]: ent.append((i, 1))
            elif dev >= 0.001 and c[i] < o[i]: ent.append((i, -1))
    return nonoverlap(ent, spacing)


# ---------------- R3: saat-bazlı seans (walk-forward) ----------------
def hour_sessions(ts, c, hours, min_move_bp=0.0):
    """Verilen UTC saatlerinde gir, bir sonraki saatte çık. Yön: son 60dk hareketi."""
    ent = []; n = len(c)
    for i in range(60, n):
        hh = dt.datetime.utcfromtimestamp(ts[i]).hour
        mm = dt.datetime.utcfromtimestamp(ts[i]).minute
        if hh in hours and mm == 0:
            mv = (c[i] / c[i - 60] - 1) * 1e4
            if abs(mv) >= min_move_bp:
                ent.append((i, 1 if mv > 0 else -1))
    return ent


# ---------------- R4: funding-z kontraryen ----------------
def fetch_funding(days=60):
    out = []; end = int(time.time() * 1000); start = end - days * 86400000
    cur = start
    while cur < end:
        url = (f"https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT"
               f"&startTime={cur}&endTime={cur + 90 * 86400000}&limit=1000")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            ch = json.loads(r.read().decode())
        if not ch:
            break
        out += ch
        cur = ch[-1]["fundingTime"] + 1
        if len(ch) < 1000:
            break
        time.sleep(0.1)
    return sorted({int(x["fundingTime"]): float(x["fundingRate"]) for x in out}.items())


def funding_signal(ts, c, funding, z_thr, hold_bars):
    """Funding aşırı pozitif (long kalabalık) → short; aşırı negatif → long."""
    if len(funding) < 30:
        return []
    ft = np.array([x[0] for x in funding]); fr = np.array([x[1] for x in funding])
    z = np.full(len(fr), np.nan)
    for i in range(20, len(fr)):
        seg = fr[i - 20:i]
        sd = seg.std()
        z[i] = (fr[i] - seg.mean()) / sd if sd > 0 else 0
    # her funding zamanını en yakın bara eşle
    ent = []
    for i in range(1, len(ft)):
        if not np.isfinite(z[i]):
            continue
        # bu funding zamanına en yakın bar indeksi
        bi = int(np.searchsorted(ts, ft[i] // 1000))
        if bi >= len(c):
            continue
        if z[i] >= z_thr:
            ent.append((bi, -1))
        elif z[i] <= -z_thr:
            ent.append((bi, 1))
    return ent


# ---------------- R5: güniçi TSMOM ----------------
def intraday_tsmom(ts, c, vol_filter=False, hour_open=17, half=30):
    """17:00 EST=22:00 UTC açılış bazlı: ilk 30dk getirisi → son 30dk yönü."""
    days = {}
    for i in range(len(ts)):
        days.setdefault(S.day_key(ts[i]), []).append(i)
    dl = sorted(days)
    ent = []
    for di in range(1, len(dl)):
        idx = days[dl[di]]
        if len(idx) < 12:
            continue
        t30 = idx[-6]
        prev_close = c[days[dl[di - 1]][-1]]
        if c[t30] > prev_close:
            ent.append((t30, 1))
        elif c[t30] < prev_close:
            ent.append((t30, -1))
    return ent


# ---------------- R6: range-expansion breakout ----------------
def range_expansion(ts, o, h, l, c, squeeze_len, expand_mult, sl_t, tp_t, max_hold):
    """N barın aralığı daraldıysa ve bu bar aralığı büyükse → yön kırılımı."""
    n = len(c); ent = []
    for i in range(squeeze_len + 1, n):
        rng = h[i] - l[i]
        prev = (h[i - squeeze_len:i] - l[i - squeeze_len:i])
        avg = prev.mean()
        if avg <= 0:
            continue
        if rng >= expand_mult * avg:
            if c[i] > o[i]:
                ent.append((i, 1))
            elif c[i] < o[i]:
                ent.append((i, -1))
    return ent


def report(name, tr, days):
    st = stats(tr, days)
    if not st:
        print(f"  {name:34} → işlem yok")
        return None
    print(f"  {name:34} n={st['n']:5d} /gün={st['per_day']:6.1f} net={st['net']:+9.0f}pip "
          f"exp={st['exp']:+6.2f} WR=%{st['wr']:4.1f} PF={st['pf']:5.2f} DD={st['dd']:+8.0f} bar={st['bars']:.1f}")
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="")
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    if args.cache:
        path = args.cache if os.path.isabs(args.cache) else os.path.join(ROOT, args.cache)
    else:
        path = os.path.join(ROOT, "outputs", f"scalp_cache_btc_{args.days}d_{args.interval}.json")
    bars = load_bars(path)
    ts, o, h, l, c = arrs(bars)
    days = len(set(dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d") for t in ts))
    print(f"3. TUR SİNYALLER — BTCUSD {args.interval}, {len(c)} bar, {days} gün, "
          f"spread {BTC_SPREAD}pip\n")

    print("[R1] Volatilite-rejim koşullu MOMENTUM (yalnız yüksek-vol):")
    for fast, slow in ((9, 21), (12, 26)):
        for pct in (70, 85):
            for sl, tp in ((40, 40), (30, 60)):
                spacing = {"1m": 30, "5m": 6}[args.interval]
                ent = regime_mom_rev(ts, o, h, l, c, fast, slow, 100, pct, "mom", sl, tp, spacing, 60)
                tr = sim(ent, c, h, l, sl, tp, 60)
                report(f"mom EMA{fast}/{slow} vol>{pct}pct SL{sl}/TP{tp}", tr, days)

    print("\n[R2] Volatilite-rejim koşullu REVERSION (yalnız düşük-vol):")
    for pct in (30, 50):
        for sl, tp in ((40, 40), (30, 60)):
            spacing = {"1m": 15, "5m": 3}[args.interval]
            ent = regime_mom_rev(ts, o, h, l, c, 20, 50, 100, pct, "rev", sl, tp, spacing, 30)
            tr = sim(ent, c, h, l, sl, tp, 30)
            report(f"rev dev0.1% vol<{pct}pct SL{sl}/TP{tp}", tr, days)

    print("\n[R3] Saat-seans drift (son 60dk yönü, belirli UTC saatleri):")
    for hours in ([8], [13], [8, 13], [0, 4, 8, 9, 11, 12, 13, 16]):
        ent = hour_sessions(ts, c, set(hours))
        for sl, tp, mh in ((40, 40, 60), (60, 60, 60)):
            tr = sim(ent, c, h, l, sl, tp, mh)
            report(f"seans {hours} SL{sl}/TP{tp}", tr, days)

    print("\n[R4] Funding-z kontraryen (Binance perp):")
    try:
        fund = fetch_funding(args.days + 10)
        print(f"  (funding: {len(fund)} nokta)")
        for z in (1.5, 2.0):
            for mh in (60, 480):
                ent = funding_signal(ts, c, fund, z, mh)
                tr = sim(ent, c, h, l, 200, 200, mh)
                report(f"fundZ {z} hold{mh}bar", tr, days)
    except Exception as e:
        print("  funding HATA:", e)

    print("\n[R5] Güniçi TSMOM (ilk30dk→son30dk):")
    ent = intraday_tsmom(ts, c)
    tr = sim(ent, c, h, l, 60, 60, 60)
    report("TSMOM son30dk", tr, days)

    print("\n[R6] Range-expansion breakout:")
    for sq in (10, 20):
        for mult in (2.0, 3.0):
            ent = range_expansion(ts, o, h, l, c, sq, mult, 40, 40, 30)
            tr = sim(ent, c, h, l, 40, 40, 30)
            report(f"rangeexp sq{sq} x{mult}", tr, days)


if __name__ == "__main__":
    main()
