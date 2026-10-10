#!/usr/bin/env python3
"""Kararlılık + anlamlılık testi: (1) veri boşluğu, (2) istatistiksel anlamlılık,
(3) rastgele-sinyal kontrolü, (4) pencere-yerel baz ile düzeltilmiş walk-forward.
"""
import datetime as dt
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import btc_momentum_calibration as C  # noqa: E402

path = os.path.join(ROOT, "outputs", "btc_momentum_calibration_240d.json")
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
days = data["meta"]["days"]
sym = data["meta"]["symbol"]

bars = C.fetch_klines(sym, "15m", days)
feat = C.build_features(bars)
n = feat["n"]
t = feat["t"]

# --- 1) Veri boşluğu ---
gaps = []
for i in range(1, n):
    d = (t[i] - t[i - 1]) / 60000.0
    if d > 16:  # >16 dk = eksik bar
        gaps.append((dt.datetime.utcfromtimestamp(t[i - 1] / 1000), d))
print(f"=== VERİ: {n} bar, {dt.datetime.utcfromtimestamp(t[0]/1000):%Y-%m-%d} → "
      f"{dt.datetime.utcfromtimestamp(t[-1]/1000):%Y-%m-%d} ===")
print(f"  16dk'dan büyük boşluk sayısı: {len(gaps)}; toplam eksik ~{sum(int(g[1]//15)-1 for g in gaps)} bar")
for g in gaps[:8]:
    print(f"    {g[0]:%Y-%m-%d %H:%M} sonrası {g[1]:.0f} dk boşluk")

rows = [r for h, lst in data["results"].items() for r in lst]


def corrected_wf(feat, fwd, mfe, mae, sig, direction, cost, k=6):
    """Pencere-YEREL baz: sinyal ortalaması - aynı pencerenin baz ortalaması."""
    n = feat["n"]
    out = []
    for j in range(k):
        a, b = int(n * j / k), int(n * (j + 1) / k)
        wm = np.zeros(n, dtype=bool)
        wm[a:b] = True
        base_m = wm & ~np.isnan(fwd)
        if base_m.sum() == 0:
            out.append(None)
            continue
        sign = 1.0 if direction == "long" else -1.0
        base_local = float((sign * fwd[base_m]).mean())
        idx = np.where(sig & base_m)[0]
        if len(idx) < 5:
            out.append(None)
            continue
        sig_local = float((sign * fwd[idx]).mean()) - cost
        out.append({"n": len(idx), "excess_local": round(sig_local - base_local, 3),
                    "sig_net": round(sig_local, 3), "base": round(base_local, 3)})
    return out


# en iyi "her iki yarı" adayı
both = [r for r in rows if (r["train"].get("excess") or -9) > 0 and (r["test"].get("excess") or -9) > 0
        and (r["full"].get("sig_avg_net") or -9) > 0 and r["full"]["n"] >= 50]
both.sort(key=lambda r: -(min(r["train"]["excess"], r["test"]["excess"])))

print("\n=== PENCERE-YEREL BAZ ile DÜZELTİLMİŞ WALK-FORWARD (ilk 6 aday) ===")
for r in both[:6]:
    hb = r["horizon_h"] * 4
    fwd, mfe, mae = C.forward_stats(feat, hb)
    sig = C.mask_for(feat, r["thr"], r["direction"], r["gate"])
    wf = corrected_wf(feat, fwd, mfe, mae, sig, r["direction"], r["cost_pct"])
    pos = sum(1 for w in wf if w and w["excess_local"] > 0)
    print(f"  {r['direction']} {r['gate']} H={r['horizon_h']}h ATR>={r['thr']['atr']} "
          f"r8>={r['thr']['ret8']} sl>={r['thr']['slope']} adx>={r['thr']['adx']} | WF-yerel +{pos}/6")
    for j, w in enumerate(wf):
        if w:
            print(f"      p{j+1}: n={w['n']:3d} sig_net={w['sig_net']:+.3f} base={w['base']:+.3f} ex={w['excess_local']:+.3f}")

# --- 2) Anlamlılık: en iyi aday için bootstrap ---
print("\n=== ANLAMLILIK (bootstrap 4000, en iyi kararlı adaylar) ===")
rng = np.random.default_rng(42)
for r in both[:5]:
    hb = r["horizon_h"] * 4
    fwd, mfe, mae = C.forward_stats(feat, hb)
    sig = C.mask_for(feat, r["thr"], r["direction"], r["gate"])
    sign = 1.0 if r["direction"] == "long" else -1.0
    base_m = ~np.isnan(fwd)
    base_local = sign * fwd[base_m]
    idx = np.where(sig & base_m)[0]
    x = sign * fwd[idx] - r["cost_pct"] - base_local.mean()
    obs = float(x.mean())
    boots = np.array([x[rng.integers(0, len(x), len(x))].mean() for _ in range(4000)])
    p_two = 2 * min((boots <= 0).mean(), (boots >= 0).mean())
    print(f"  {r['direction']} {r['gate']} H={r['horizon_h']}h n={len(x):4d} excess={obs:+.3f}% "
          f"%95CI=[{np.percentile(boots,2.5):+.3f},{np.percentile(boots,97.5):+.3f}] p={p_two:.4f}")

# --- 3) Rastgele sinyal kontrolü (aynı n ve aynı uzunluk, 2000 kez) ---
print("\n=== RASTGELE SİNYAL KONTROLÜ (en iyi aday, aynı n) ===")
for r in both[:3]:
    hb = r["horizon_h"] * 4
    fwd, mfe, mae = C.forward_stats(feat, hb)
    sign = 1.0 if r["direction"] == "long" else -1.0
    base_m = np.isnan(fwd)
    valid = np.where(~base_m)[0]
    valid = valid[valid >= 210]
    sig = C.mask_for(feat, r["thr"], r["direction"], r["gate"])
    k = int((sig & ~base_m).sum())
    base_local = sign * fwd[valid]
    rand_means = []
    for _ in range(2000):
        pick = rng.choice(valid, size=k, replace=False)
        rand_means.append(float((sign * fwd[pick] - r["cost_pct"] - base_local.mean()).mean()))
    rand_means = np.array(rand_means)
    real_ex = float((sign * fwd[sig & ~base_m] - r["cost_pct"] - base_local.mean()).mean())
    pct = (rand_means < real_ex).mean()
    print(f"  {r['direction']} {r['gate']} H={r['horizon_h']}h k={k} gerçek_ex={real_ex:+.3f}% "
          f"rastgele ort={rand_means.mean():+.3f}% p95={np.percentile(rand_means,95):+.3f} "
          f"→ yüzdelik={pct*100:.1f}%")
