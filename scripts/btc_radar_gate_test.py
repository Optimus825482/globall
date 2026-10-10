#!/usr/bin/env python3
"""V4 radar/velocity geçitlerinin BTCUSDT'de ampirik olarak ateşleyip ateşlemediğini ölçer.

Velocity 1m barlarda çalışır. Geçitleri (1m ölçeği):
  atr_pct >= 0.25 (veya breakout)  ·  bb_width >= 2.5%  ·  RSI>=60 veya <=35
  ·  struct_ok: slope(%/bar*10)>=0.20 VEYA aroon_up>=50
  ·  tükenmişlik yok (MFI<90/>10, RSI<80)  ·  üst-fitil tuzağı yok
Hedef: 5dk'da +%2 (velocity 5m profili).
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import btc_momentum_calibration as C  # noqa: E402


def struct_slope(closes, n=20):
    """V4 _velocity_struct_slope: slope/mean*100*10 (%/bar×10)."""
    if len(closes) < n:
        return None
    xs = list(range(n)); ys = list(closes[-n:])
    mx = sum(xs) / n; my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return (num / den if den else 0) / my * 100 * 10 if my else None


def aroon_up(highs, n=25):
    if len(highs) < n + 1:
        return None
    seg = highs[-n - 1:]
    return 100.0 * (n - (len(seg) - 1 - int(np.argmax(seg)))) / n


def bb_width(closes, period=20, mult=2.0):
    if len(closes) < period:
        return None
    seg = np.asarray(closes[-period:])
    m = seg.mean()
    return (2 * mult * seg.std()) / m * 100 if m else None


def scan(symbol, interval, days):
    bars = C.fetch_klines(symbol, interval, days)
    n = len(bars)
    c = np.array([b[4] for b in bars]); h = np.array([b[2] for b in bars])
    l = np.array([b[3] for b in bars]); o = np.array([b[1] for b in bars])
    v = np.array([b[5] for b in bars])
    print(f"\n=== {symbol} {interval} — {n} bar "
          f"({len(bars)} adet) ===")
    atr = C.atr_pct_series(h, l, c, 14)
    rsi = C.rsi_series(c, 14)
    mfi = C.mfi_series(h, l, c, v, 14)
    hits = {"atr": 0, "bb": 0, "rsi_mod": 0, "struct": 0, "notr_struct": 0, "passes": 0}
    valid = 0
    for i in range(30, n):
        a = atr[i]; bwi = bb_width(c[:i + 1]); r = rsi[i]; m = mfi[i]
        sl = struct_slope(c[:i + 1]); au = aroon_up(h[:i + 1])
        if not (np.isfinite(a) and bwi and np.isfinite(r)):
            continue
        valid += 1
        ret3 = (c[i] / c[i - 3] - 1) * 100 if c[i - 3] else 0
        ret5 = (c[i] / c[i - 5] - 1) * 100 if c[i - 5] else 0
        short_atr = C.atr_pct_series(h[:i + 1], l[:i + 1], c[:i + 1], 3)
        satr = short_atr[i] if np.isfinite(short_atr[i]) else 0
        is_breakout = ret3 >= 1.0 or ret5 >= 1.8 or satr >= 0.45
        atr_ok = a >= 0.25 or (is_breakout and a >= 0.25)
        bb_ok = bwi >= 2.5
        mode = "trend" if r >= 60 else ("vdon" if r <= 35 else "notr")
        rsi_mod_ok = mode != "notr"
        struct_ok = (sl is not None and sl >= 0.20) or (au is not None and au >= 50)
        exhausted = (m is not None and (m >= 90 or m <= 10)) or r >= 80
        if atr_ok: hits["atr"] += 1
        if bb_ok: hits["bb"] += 1
        if rsi_mod_ok: hits["rsi_mod"] += 1
        if struct_ok: hits["struct"] += 1
        if mode == "notr" and struct_ok: hits["notr_struct"] += 1
        if atr_ok and bb_ok and rsi_mod_ok and struct_ok and not exhausted:
            hits["passes"] += 1
    for k, val in hits.items():
        print(f"  {k:12}: {val:5d} / {valid} = {100*val/max(valid,1):5.2f}%")
    # hedef ulaşılabilirliği: 5dk sonra >= +2%
    if interval == "1m":
        fwd = np.array([(c[i + 5] / c[i] - 1) * 100 if i + 5 < n else np.nan for i in range(n)])
        v2 = np.isfinite(fwd)
        print(f"  5dk'da >=+2% hareket oranı: {100*(fwd[v2] >= 2.0).mean():.3f}% (baz)")
        print(f"  1m medyan ATR%={np.nanmedian(atr):.3f}, medyan BB%="
              f"{np.nanmedian([bb_width(c[:i+1]) or np.nan for i in range(20, n)]):.3f}")


print("V4 VELOCITY/RADAR GEÇİTLERİ — BTCUSDT ampirik ateşleme testi")
scan("BTCUSDT", "1m", 5)
scan("BTCUSDT", "5m", 20)

# karşılaştırma: bir altcoin (velocity'nin asıl hedefi)
print("\n" + "=" * 70)
print("KIYAS: altcoin (velocity'nin kalibre olduğu rejim)")
scan("DOGEUSDT", "1m", 5)
scan("SOLUSDT", "1m", 5)
