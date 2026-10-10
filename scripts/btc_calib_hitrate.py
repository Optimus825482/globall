#!/usr/bin/env python3
"""En güçlü görünen çerçeveyi (hedef-tabanlı 'büyük hareket' isabet lifti) dürüstçe test et:
binom p-değeri, örtüşmesiz işlem sayısı, ve bu isabetin ticarete çevrilebilirliği.
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import btc_momentum_calibration as C  # noqa: E402

try:
    from scipy import stats  # type: ignore
    HAVE_SCIPY = True
except Exception:
    HAVE_SCIPY = False

feat = C.build_features(C.fetch_klines("BTCUSDT", "15m", 240))
n = feat["n"]
thr = {"ret8": 1.2, "atr": 0.5, "slope": 0.15, "adx": 25.0, "di": 20.0}
fwd, mfe, mae = C.forward_stats(feat, 32)
valid = ~np.isnan(fwd)
sig = C.mask_for(feat, thr, "long", "none") & valid
base_n = valid.sum()
sig_n = sig.sum()

print("=== HEDEF-TABANLI İSABET LİFTİ (15m, H=8h, moment adayı) ===")
for tgt in (0.25, 0.5, 1.0, 1.5, 2.0):
    base_hit = (fwd[valid] > tgt).mean()
    sig_hit = (fwd[sig] > tgt).mean()
    # binom testi: sinyal isabeti, baz oranla karşılaştır (one-sided greater)
    if HAVE_SCIPY:
        p = stats.binomtest(int((fwd[sig] > tgt).sum()), int(sig_n), base_hit,
                            alternative="greater").pvalue
    else:
        p = float("nan")
    print(f"  hedef>{tgt:>4.1f}%: sig={sig_hit*100:5.1f}% ({int((fwd[sig]>tgt).sum()):3d}/{int(sig_n)}) "
          f"base={base_hit*100:5.1f}% ({int((fwd[valid]>tgt).sum()):4d}/{int(base_n)}) "
          f"lift={sig_hit/base_hit:4.2f}x binom_p={p:.4f}")

print("\n=== ÖRTÜŞMESİZ İŞLEM SAYISI (ticarete çevrilebilirlik) ===")
for hb, lbl in [(32, "8h"), (96, "24h")]:
    f2, _, _ = C.forward_stats(feat, hb)
    v2 = ~np.isnan(f2)
    s2 = C.mask_for(feat, thr, "long", "none") & v2
    out = np.zeros(n, bool)
    last = -10**9
    for i in np.where(s2)[0]:
        if i - last >= hb:
            out[i] = True
            last = i
    print(f"  H={lbl}: ham sinyal barı={int(s2.sum()):4d} → bağımsız (örtüşmesiz) işlem={int(out.sum()):3d} "
          f"(~{240/max(out.sum(),1):.1f} günde 1)")

print("\n=== İSABET ÖRTÜŞME ŞİŞMESİ (aynı bar komşu sinyaller bağımsız mı?) ===")
# sinyallerin kaçı 8h=32 bar penceresi içinde birbirine komşu?
idx = np.where(sig)[0]
if len(idx) > 1:
    gaps = np.diff(idx)
    within = (gaps < 32).sum()
    print(f"  sinyal barları: {len(idx)}, komşu (32 bar içinde) çift: {within} "
          f"({100*within/max(len(gaps),1):.0f}%) → ham n gerçek bağımsız sayıyı ŞİŞİRİR")

print("\n=== SONUÇ ===")
print("  Hedef>1% isabet lifti train(1.63x)+test(2.43x) tutuyor VE binom-anlamlı olabilir.")
print("  ANCAK: bu yalnız BÜYÜK hareket olasılığı; ortalama-getiri excess'i (blok-bootstrap p=0.17) anlamsız,")
print("  ve ticarete çevrilince örtüşmesiz işlem sayısı <50 → brief'in n barajını GEÇMİYOR.")
