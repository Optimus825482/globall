"""TSMOM (Time-Series Momentum) testi — GitHub araştırmasının tek kurtulanı.

Kaynak: yongzhe2160cs/trading-engine
  "TSMOM on BTC/ETH/SOL, rebalanced DAILY. Book HAC p=0.008, Sharpe 1.15,
   maxDD -19%. Holdout 12 ay: +6.1% vs buy&hold -35%."
  "Anahtar bulgu: rebalansı saatlikten GÜNLÜĞE çekmek Sharpe'ı ikiye katladı.
   Yüksek devirli stratejiler 1h kriptoda maliyet tarafından yutuluyor."

Kural:
  sinyal_t = sign(getiri_t)  burada getiri = 30 günlük (720 × 1h) bakış
  pozisyon = sinyal × (vol_hedef / gerçekleşen_vol)
  rebalans = GÜNLÜK

Bizim verimizde 5m bar var; günlük bakış için her 288 barı bir güne topluyoruz.
Bu, canlı spot_monitor'ün 5 dakikalık döngüsünden TEMELDEN farklı: giriş/çıkış
günde bir kez, komisyon yükü ~288 kat azalıyor.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "backend"))
sys.path.insert(0, _ROOT)

BARS_PER_DAY = 288          # 5m × 288 = 1 gün
FEE_ROUND_TRIP_PCT = 0.15   # tek gidiş-dönüş


def daily_ohlc(T, H, L, C):
    """5m barları UTC günlerine toplar."""
    days, cur_day = [], None
    bucket = {"o": None, "h": -np.inf, "l": np.inf, "c": None, "t": None}
    for i in range(len(C)):
        d = T[i] // 86_400_000
        if cur_day is None:
            cur_day = d
            bucket = {"o": C[i], "h": H[i], "l": L[i], "c": C[i], "t": T[i]}
        elif d != cur_day:
            days.append(dict(bucket))
            cur_day = d
            bucket = {"o": C[i], "h": H[i], "l": L[i], "c": C[i], "t": T[i]}
        else:
            bucket["h"] = max(bucket["h"], H[i])
            bucket["l"] = min(bucket["l"], L[i])
            bucket["c"] = C[i]
    if bucket["o"] is not None:
        days.append(dict(bucket))
    return days


def tsmom_returns(days, lookback_days=30, vol_win=30, vol_target=0.20,
                  fee_pct=FEE_ROUND_TRIP_PCT, long_only=True):
    """Günlük TSMOM. Dönüş: (günlük net getiri dizisi, işlem sayısı, pozisyonlar)."""
    C = np.array([d["c"] for d in days], dtype=float)
    n = len(C)
    if n < max(lookback_days, vol_win) + 5:
        return None, 0, np.array([])

    rets = np.diff(C) / C[:-1]          # geçmiş günlük getiri (n-1 eleman)
    pos = np.zeros(n)
    trades = 0
    prev_pos = 0.0
    net = np.zeros(n)

    for t in range(n - 1):
        # Sinyal: t-1'e KADAR olan veri (ileri bakış yok)
        if t < max(lookback_days, vol_win):
            continue
        past = C[max(0, t - lookback_days):t + 1]
        sig = 1.0 if past[-1] > past[0] else -1.0
        if long_only and sig < 0:
            sig = 0.0                     # spot: short yok
        # Vol hedefleme: son vol_win günün gerçekleşen volatilitesi
        recent = rets[max(0, t - vol_win):t]
        if len(recent) < 5:
            continue
        rv = float(np.std(recent)) * np.sqrt(365.0)
        if rv <= 1e-9:
            continue
        lev = min(1.0, vol_target / rv)   # kaldıraç yok, yalnız küçültme
        pos[t] = sig * lev
        if abs(pos[t] - prev_pos) > 1e-6:
            trades += 1
            prev_pos = pos[t]

    # Getiri: t günü pozisyonu, t+1 getirisini alır
    for t in range(n - 1):
        gross = pos[t] * rets[t]
        turn = abs(pos[t] - (pos[t - 1] if t > 0 else 0.0))
        net[t + 1] = gross - turn * fee_pct / 100.0
    return net[1:], trades, pos


def buy_and_hold_returns(days):
    C = np.array([d["c"] for d in days], dtype=float)
    if len(C) < 2:
        return None
    return np.diff(C) / C[:-1]


def stats(r, base=None):
    if r is None or len(r) == 0:
        return None
    r = np.asarray(r, dtype=float)
    n = len(r)
    ann_ret = float(np.mean(r)) * 365
    ann_vol = float(np.std(r, ddof=1)) * np.sqrt(365.0) if n > 1 else 0.0
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    eq = np.cumprod(1 + r)
    peak = np.maximum.accumulate(eq)
    dd = (eq / peak - 1.0)
    out = {
        "n_days": n,
        "total_pct": float((eq[-1] - 1) * 100),
        "ann_ret_pct": ann_ret * 100,
        "ann_vol_pct": ann_vol * 100,
        "sharpe": sharpe,
        "max_dd_pct": float(dd.min() * 100),
        "win_day_pct": float((r > 0).mean() * 100),
    }
    return out


async def _load(symbols, days_back):
    import asyncpg
    url = os.environ.get("DATABASE_URL") or "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"
    conn = await asyncpg.connect(url)
    cutoff = int((__import__("time").time() - days_back * 86400) * 1000)
    rows = await conn.fetch(
        """SELECT symbol, open_time, high, low, close
             FROM historical_candles
            WHERE timeframe='5m' AND symbol = ANY($1) AND open_time >= $2
            ORDER BY symbol, open_time ASC""", symbols, cutoff)
    await conn.close()
    data = {}
    for r in rows:
        d = data.setdefault(r["symbol"], {"T": [], "H": [], "L": [], "C": []})
        d["T"].append(int(r["open_time"]))
        d["H"].append(float(r["high"]))
        d["L"].append(float(r["low"]))
        d["C"].append(float(r["close"]))
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--lookback", type=int, default=30)
    ap.add_argument("--fee", type=float, default=FEE_ROUND_TRIP_PCT)
    ap.add_argument("--long-only", action="store_true", default=True)
    args = ap.parse_args()

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
               "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "DOTUSDT"]
    data = asyncio.run(_load(symbols, args.days))

    print("=" * 88)
    print(f"TSMOM -- GUNLUK -- {args.days} gun, bakis {args.lookback} gun, maliyet %{args.fee}")
    print("=" * 88)
    print("%-10s %6s %9s %9s %8s %9s %8s %7s" % (
        "sembol", "gun", "toplam%", "yil_get%", "Sharpe", "maxDD%", "WR_gun%", "islem"))
    print("-" * 88)

    port = []
    all_stats = []
    for sym, d in data.items():
        days = daily_ohlc(d["T"], d["H"], d["L"], d["C"])
        r, trades, pos = tsmom_returns(days, args.lookback, fee_pct=args.fee)
        s = stats(r)
        if not s:
            continue
        s["symbol"] = sym
        s["trades"] = trades
        all_stats.append(s)
        if len(port) == 0:
            port = list(r)
        elif len(r) == len(port):
            port = [a + b for a, b in zip(port, r)]

        print("%-10s %6d %+8.2f %+8.2f %8.2f %+8.2f %7.1f %7d" % (
            sym, s["n_days"], s["total_pct"], s["ann_ret_pct"],
            s["sharpe"], s["max_dd_pct"], s["win_day_pct"], trades))

    print("-" * 88)
    if all_stats:
        avg_sharpe = np.mean([s["sharpe"] for s in all_stats])
        pos_count = sum(1 for s in all_stats if s["total_pct"] > 0)
        print("PORTFOY ORTALAMASI: Sharpe %.2f | pozitif sembol %d/%d" % (
            avg_sharpe, pos_count, len(all_stats)))

    if port:
        ps = stats(np.array(port) / max(1, len(all_stats)))
        print("\nPORTFOY (esit agirlikli sepet):")
        print("  toplam      : %+.2f%%" % ps["total_pct"])
        print("  yillik getiri: %+.2f%%" % ps["ann_ret_pct"])
        print("  Sharpe      : %.2f" % ps["sharpe"])
        print("  maxDD       : %+.2f%%" % ps["max_dd_pct"])
        print("  kazanan gun : %.1f%%" % ps["win_day_pct"])

    # Buy & hold referansı
    print()
    print("BUY & HOLD REFERANSI:")
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        if sym not in data:
            continue
        days = daily_ohlc(data[sym]["T"], data[sym]["H"], data[sym]["L"], data[sym]["C"])
        bh = stats(buy_and_hold_returns(days))
        if bh:
            print("  %-10s toplam %+8.2f%%  Sharpe %5.2f  maxDD %+7.2f%%" % (
                sym, bh["total_pct"], bh["sharpe"], bh["max_dd_pct"]))


if __name__ == "__main__":
    main()
