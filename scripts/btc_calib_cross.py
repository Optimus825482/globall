#!/usr/bin/env python3
"""Adım 7 önizleme: aynı kalibrasyon iskeletini başka varlıklara uygula.
Binance'te mevcut proxy'ler: PAXGUSDT (altın), EURUSDT (EUR/USD). 4h + 15m."""
import datetime as dt
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import btc_momentum_calibration as C  # noqa: E402

rng = np.random.default_rng(5)


def nonoverlap(sig, spacing):
    out = np.zeros(len(sig), dtype=bool)
    last = -10**9
    for i in np.where(sig)[0]:
        if i - last >= spacing:
            out[i] = True
            last = i
    return out


def block_boot(sig, r, bm, block, iters=2000):
    m = len(r)
    nb = int(np.ceil(m / block))
    ms = []
    for _ in range(iters):
        starts = rng.integers(0, m - block + 1, size=nb)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:m]
        ss = sig[idx]
        if ss.sum() < 5:
            continue
        ms.append(r[idx][ss].mean() - bm)
    return np.array(ms)


def run(symbol, interval, days, hb, r8, atr, sl, adx, gate="none"):
    try:
        bars = C.fetch_klines(symbol, interval, days)
    except Exception as e:
        print(f"  {symbol} {interval}: veri yok ({e})")
        return
    feat = C.build_features(bars)
    n = feat["n"]
    med_atr = np.nanmedian(feat["atr_pct"])
    fwd, mfe, mae = C.forward_stats(feat, hb)
    valid = ~np.isnan(fwd)
    thr = {"ret8": r8, "atr": atr, "slope": sl, "adx": adx, "di": 20.0}
    sig = C.mask_for(feat, thr, "long", gate) & valid
    cost = C.cost_scenarios(float(feat["c"][-1]), hb * (15 if interval == "15m" else 240) // 60)["realistic"]
    bm = fwd[valid].mean()
    idx = np.where(sig)[0]
    if len(idx) < 10:
        print(f"  {symbol:9} {interval:4} {n:5d} bar: sinyal={len(idx)} (az) medATR%={med_atr:.2f}")
        return
    net = fwd[idx].mean() - cost
    sig_no = nonoverlap(sig, hb)
    boot = block_boot(sig, fwd, bm, block=max(hb, 6))
    p = 2 * min((boot <= 0).mean(), (boot >= 0).mean()) if len(boot) else float("nan")
    # çeyrek
    qs = []
    for a, b in [(0, .25), (.25, .5), (.5, .75), (.75, 1.0)]:
        ia, ib = int(n * a), int(n * b)
        wm = np.zeros(n, bool); wm[ia:ib] = True
        e = C.eval_mask(feat, fwd, mfe, mae, sig & wm, "long", cost)
        qs.append(e.get("excess") if e.get("n") else None)
    qpos = sum(1 for q in qs if q is not None and q > 0)
    print(f"  {symbol:9} {interval:4} {n:5d} bar medATR%={med_atr:4.2f} | n={len(idx):4d} net%={net:+.3f} "
          f"base%={bm:+.3f} ex%={net-bm:+.3f} | bağ.n={len(np.where(sig_no)[0]):3d} | "
          f"blokboot p={p:.3f} | çeyrek+={qpos}/4")


print("=== ADIM 7 ÖNİZLEME — farklı varlıklar, aynı iskelet ===")
print("4h, H=24h, r8>=0.3 atr>=0.25 sl>=0.05 adx>=15:")
for sym in ("BTCUSDT", "PAXGUSDT", "EURUSDT", "ETHUSDT"):
    run(sym, "4h", 240, 6, 0.3, 0.25, 0.05, 15.0)
print("\n15m, H=8h, r8>=1.2 atr>=0.5 sl>=0.15 adx>=25:")
for sym in ("BTCUSDT", "PAXGUSDT", "EURUSDT", "ETHUSDT"):
    run(sym, "15m", 120, 32, 1.2, 0.5, 0.15, 25.0)
