#!/usr/bin/env python3
"""4h derinlemesine + briefteki KABUL kriterlerinin otomatik değerlendirmesi."""
import datetime as dt
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import btc_momentum_calibration as C  # noqa: E402

rng = np.random.default_rng(3)
feat = C.build_features(C.fetch_klines("BTCUSDT", "4h", 240))
n = feat["n"]
print(f"4h: {n} bar, {dt.datetime.utcfromtimestamp(feat['t'][0]/1000):%Y-%m-%d} → "
      f"{dt.datetime.utcfromtimestamp(feat['t'][-1]/1000):%Y-%m-%d}, son ${feat['c'][-1]:,.0f}")
print(f"4h medyan ATR%={np.nanmedian(feat['atr_pct']):.3f}") 


def nonoverlap(sig, spacing):
    out = np.zeros(len(sig), dtype=bool)
    last = -10**9
    for i in np.where(sig)[0]:
        if i - last >= spacing:
            out[i] = True
            last = i
    return out


def block_boot(sig, r, base_mean, block, iters=3000):
    m = len(r)
    nb = int(np.ceil(m / block))
    ms = []
    for _ in range(iters):
        starts = rng.integers(0, m - block + 1, size=nb)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:m]
        ss = sig[idx]
        if ss.sum() < 5:
            continue
        ms.append(r[idx][ss].mean() - base_mean)
    return np.array(ms)


print("\n=== 4h: gate=none, H=24h (6 bar), r8>=0.3 atr>=0.25 sl>=0.05 adx>=15 ===")
thr = {"ret8": 0.3, "atr": 0.25, "slope": 0.05, "adx": 15.0, "di": 20.0}
for hb in (2, 6):
    fwd, mfe, mae = C.forward_stats(feat, hb)
    valid = ~np.isnan(fwd)
    sig = C.mask_for(feat, thr, "long", "none") & valid
    cost = C.cost_scenarios(float(feat["c"][-1]), hb * 4)["realistic"]
    r = fwd
    bm = r[valid].mean()
    idx = np.where(sig)[0]
    net = r[idx].mean() - cost
    sig_no = nonoverlap(sig, hb)
    idx_no = np.where(sig_no)[0]
    boot = block_boot(sig, r, bm, block=max(hb, 6))
    print(f" H={hb*4:2}h: n={len(idx):4d} net%={net:+.3f} base%={bm:+.3f} ex%={net-bm:+.3f} | "
          f"bağımsız n={len(idx_no):3d} net%={r[idx_no].mean()-cost:+.3f} | "
          f"blokboot p={2*min((boot<=0).mean(),(boot>=0).mean()):.3f} "
          f"CI=[{np.percentile(boot,2.5):+.3f},{np.percentile(boot,97.5):+.3f}] | "
          f"alwaysL net%={r[valid].mean()-cost:+.3f}")

print("\n=== 4h ÇEYREK KARARLILIK ===")
fwd, mfe, mae = C.forward_stats(feat, 6)
sig = C.mask_for(feat, thr, "long", "none")
for a, b in [(0, .25), (.25, .5), (.5, .75), (.75, 1.0)]:
    ia, ib = int(n * a), int(n * b)
    wm = np.zeros(n, dtype=bool)
    wm[ia:ib] = True
    e = C.eval_mask(feat, fwd, mfe, mae, sig & wm, "long", 0.0072)
    d0 = dt.datetime.utcfromtimestamp(feat["t"][ia] / 1000).strftime("%y-%m-%d")
    d1 = dt.datetime.utcfromtimestamp(feat["t"][ib - 1] / 1000).strftime("%y-%m-%d")
    if not e.get("n"):
        print(f"  {d0}→{d1}: sinyal yok")
    else:
        print(f"  {d0}→{d1}: n={e['n']:4d} net%={e['sig_avg_net']:+.3f} base%={e['base_avg']:+.3f} "
              f"ex%={e['excess']:+.3f} hit%={e['hit']}")

print("\n=== BRIEF HEDEF-METRİĞİ: 'büyük hareket' isabet lifti, TRAIN/TEST ===")
# V4 ruhu: sonraki gün içi >= X% hareket isabeti
for tag, hb, tgt in [("15m H=8h", 32, 0.5), ("15m H=8h", 32, 1.0), ("4h H=24h", 6, 2.0)]:
    f = feat if tag.startswith("4h") else C.build_features(C.fetch_klines("BTCUSDT", "15m", 240))
    fwd, mfe, mae = C.forward_stats(f, hb)
    valid = ~np.isnan(fwd)
    thr2 = {"ret8": 1.2, "atr": 0.5, "slope": 0.15, "adx": 25.0, "di": 20.0} if not tag.startswith("4h") else thr
    s = C.mask_for(f, thr2, "long", "none") & valid
    nn = f["n"]
    half = nn // 2
    tr = np.zeros(nn, bool); tr[:half] = True
    te = ~tr
    for name, sel in (("ALL", s), ("TRAIN", s & tr), ("TEST", s & te)):
        if sel.sum() == 0:
            continue
        bh = (fwd[valid] > tgt).mean() * 100
        sh = (fwd[sel] > tgt).mean() * 100
        print(f"  {tag} hedef>{tgt}% [{name:5}] n={sel.sum():4d} sig_hit={sh:5.1f}% base={bh:5.1f}% lift={sh/bh:4.2f}x")

print("\n=== KABUL KRİTERLERİ ÖZETİ ===")
crit = [
    ("hit-lift > 1.2x", "haftalık/aylık lift ~1.0-1.3x (küçük hedefte ~1.0 → GEÇMEZ; >1% hedefte 1.4x)"),
    ("test'te de tutuyor", "yarı-bazlı EVET ama çeyrek/aylık HAYIR (2/4 çeyrek negatif)"),
    ("n >= 50-100", "gevşek eşikte 50-78 bağımsız; sıkı eşikte 13-40 → SINIRDA/GEÇMEZ"),
    ("net > 0", "geniş TP'de pozitif; sıkı TP/stop'ta NEGATİF → kırılgan"),
    ("istatistiksel anlamlılık", "blok-bootstrap p=0.17-0.27 → ANLAMSIZ"),
]
for c, v in crit:
    print(f"  • {c:28} {v}")
