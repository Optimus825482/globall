#!/usr/bin/env python3
"""NİHAİ KARAR TESTİ.

Doğru overlap düzeltmesi: zaman-bloklı bootstrap (tam seride, sinyal bayraklarıyla).
Kıyas tabanları: (a) baz bar getirisi, (b) HER ZAMAN LONG, (c) trend-içinde rastgele giriş.
Ayrıca örtüşmeyen (bağımsız) işlem simülasyonu ve 1h teyidi.
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import btc_momentum_calibration as C  # noqa: E402

feat = C.build_features(C.fetch_klines("BTCUSDT", "15m", 240))
n = feat["n"]
rng = np.random.default_rng(11)

CAND = [
    ("A_mom8",   "none",       8,  1.2, 0.5,  0.15, 25.0),
    ("B_mom24",  "none",      24,  0.5, 0.5,  0.06, 15.0),
    ("C_mom24st","supertrend",24,  0.8, 0.5,  0.10, 15.0),
    ("D_mom8lo", "none",       8,  1.2, 0.35, 0.15, 15.0),
    ("E_mom8s",  "supertrend", 8,  1.2, 0.5,  0.15, 25.0),
]


def nonoverlap(sig, spacing):
    out = np.zeros(len(sig), dtype=bool)
    last = -10**9
    for i in np.where(sig)[0]:
        if i - last >= spacing:
            out[i] = True
            last = i
    return out


def time_block_bootstrap(sig, r, base_mean, block, iters=3000):
    """r: tüm barların yön-getirisi (uzun perspektifi). Sinyal bayrağıyla birlikte
    ZAMAN bloklarını (uzunluk=block) yeniden örnekle → sinyal-ortalaması dağılımı."""
    m = len(r)
    nblocks = int(np.ceil(m / block))
    means = np.empty(iters)
    for it in range(iters):
        starts = rng.integers(0, m - block + 1, size=nblocks)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:m]
        ss = sig[idx]
        if ss.sum() < 5:
            means[it] = np.nan
            continue
        means[it] = r[idx][ss].mean() - base_mean
    means = means[~np.isnan(means)]
    return means


def evaluate(label, gate, hh, r8, atr, sl, adx, verbose=True):
    hb = hh * 4
    fwd, mfe, mae = C.forward_stats(feat, hb)
    thr = {"ret8": r8, "atr": atr, "slope": sl, "adx": adx, "di": 20.0}
    sig = C.mask_for(feat, thr, "long", gate) & ~np.isnan(fwd)
    valid = ~np.isnan(fwd)
    cost = C.cost_scenarios(float(feat["c"][-1]), hh)["realistic"]
    r = fwd.copy()  # long
    base_mean = r[valid].mean()
    idx = np.where(sig)[0]
    r_sig = r[idx] - cost

    # (1) örtüşmeyen işlemler
    sig_no = nonoverlap(sig, hb)
    idx_no = np.where(sig_no)[0]
    r_no = r[idx_no] - cost

    # (2) zaman-bloklı bootstrap
    means = time_block_bootstrap(sig, r - 0.0, base_mean, block=max(hb, 8), iters=2000)
    ci = (np.percentile(means, 2.5), np.percentile(means, 97.5))
    p_two = 2 * min((means <= 0).mean(), (means >= 0).mean())

    # (3) her zaman long
    always_long = r[valid].mean() - cost

    # (4) trend-içinde rastgele: ema200 üstündeki barlardan aynı sayıda rastgele
    ema_ok = valid & (feat["c"] > feat["ema200"])
    ema_idx = np.where(ema_ok)[0]
    rand = []
    for _ in range(2000):
        pick = rng.choice(ema_idx, size=min(len(idx), len(ema_idx)), replace=False)
        rand.append(r[pick].mean() - cost)
    rand = np.array(rand)

    if verbose:
        print(f"\n{label} gate={gate} H={hh}h (r8>={r8} atr>={atr} sl>={sl} adx>={adx}) cost={cost}%")
        print(f"  ham sinyal : n={len(idx):4d} net%={r_sig.mean():+.3f} base%={base_mean:+.3f} excess%={r_sig.mean()-base_mean:+.3f}")
        print(f"  bağımsız   : n={len(idx_no):4d} net%={r_no.mean():+.3f} (>= {hb} bar ara) → ~1 işlem / {240/max(len(idx_no),1):.1f} gün")
        print(f"  blok-boot  : excess %95CI=[{ci[0]:+.3f},{ci[1]:+.3f}] p={p_two:.4f} (blok={max(hb,8)})")
        print(f"  her zaman L: net%={always_long:+.3f}  | trend-içi rastgele: ort%={rand.mean():+.3f} "
              f"p95%={np.percentile(rand,95):+.3f} → sinyal yüzdelik={(rand < r_sig.mean()).mean()*100:.1f}%")
    return {"label": label, "hh": hh, "gate": gate,
            "n": len(idx), "n_indep": len(idx_no),
            "net": r_sig.mean(), "base": base_mean, "excess": r_sig.mean() - base_mean,
            "ci": ci, "p": p_two, "always_long": always_long,
            "rand_mean": rand.mean(), "rand_pctile": (rand < r_sig.mean()).mean() * 100}


print("=" * 96)
print("NİHAİ KARAR TESTİ — 15m, 240 gün BTCUSDT")
print("=" * 96)
results = [evaluate(*c) for c in CAND]

print("\n" + "=" * 96)
print("ÖZET TABLO")
print("=" * 96)
print(f"{'aday':12}{'n':>5}{'n_bag':>7}{'net%':>9}{'excess%':>9}{'p':>8}{'alwaysL%':>10}{'rand%ile':>10}")
for r in results:
    print(f"{r['label']:12}{r['n']:5d}{r['n_indep']:7d}{r['net']:+9.3f}{r['excess']:+9.3f}{r['p']:8.3f}"
          f"{r['always_long']:+10.3f}{r['rand_pctile']:10.1f}")

# 1h teyidi
print("\n" + "=" * 96)
print("1h TEYİDİ (aynı mantık, 1h barlar, ATR/slope eşikleri ölçeklenmez — ham karşılaştırma)")
print("=" * 96)
feat1h = C.build_features(C.fetch_klines("BTCUSDT", "1h", 240))
for gate, r8, atr, sl, adx, hh in [("none", 1.0, 0.5, 0.3, 20.0, 8), ("supertrend", 1.0, 0.5, 0.3, 20.0, 8)]:
    hb = hh * 1
    fwd, mfe, mae = C.forward_stats(feat1h, hb)
    thr = {"ret8": r8, "atr": atr, "slope": sl, "adx": adx, "di": 20.0}
    sig = C.mask_for(feat1h, thr, "long", gate) & ~np.isnan(fwd)
    valid = ~np.isnan(fwd)
    base = fwd[valid].mean()
    idx = np.where(sig)[0]
    cost = C.cost_scenarios(float(feat1h["c"][-1]), hh)["realistic"]
    net = fwd[idx].mean() - cost
    print(f"  1h {gate:10} H={hh}h n={len(idx):4d} net%={net:+.3f} base%={base:+.3f} excess%={net-base:+.3f}")
