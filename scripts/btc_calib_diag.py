#!/usr/bin/env python3
"""Adayların gerçekten kararlı mı, yoksa rejim/beta mı olduğunu teşhis et.

Kritik ayrım:
  - 'her yarıda pozitif excess' (kararlı edge) vs
  - 'train negatif / test pozitif' (rejim sürüklenmesi = sahte edge)
Ayrıca aylık pencere kırılımı ve baz-oran drift'i gösterir.
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import btc_momentum_calibration as C  # noqa: E402

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "outputs", "btc_momentum_calibration_240d.json")
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)

rows = [r for h, lst in data["results"].items() for r in lst]


def wf_pos(r):
    return sum(1 for w in r["wf"] if (w.get("excess") or -9) > 0)


# --- 1) Her iki yarıda da pozitif olanlar (kararlılık testi) ---
both = [r for r in rows
        if (r["train"].get("excess") or -9) > 0 and (r["test"].get("excess") or -9) > 0
        and (r["full"].get("sig_avg_net") or -9) > 0 and r["full"]["n"] >= 50]
both.sort(key=lambda r: -(min(r["train"]["excess"], r["test"]["excess"])))
print(f"=== HER İKİ YARIDA da pozitif excess (n>=50, net>0): {len(both)} aday ===")
for r in both[:15]:
    fr, tr, te = r["full"], r["train"], r["test"]
    print(f"  {r['direction']:5} {r['gate']:10} {r['cost']:12} H={r['horizon_h']:2}h "
          f"ATR>={r['thr']['atr']:.2f} r8>={r['thr']['ret8']:.1f} sl>={r['thr']['slope']:.2f} adx>={r['thr']['adx']:.0f} | "
          f"n={fr['n']:4d} net={fr['sig_avg_net']:+.3f} ex={fr['excess']:+.3f} "
          f"hitL={fr['hit_lift']} | TR ex={tr['excess']:+.3f} TE ex={te['excess']:+.3f} WF+={wf_pos(r)}/6")
print()

# --- 2) Yarı-bazlı baz getiri (beta/rejim hipotezi) ---
r0 = rows[0]
days = data["meta"]["days"]
print("=== BAZ GETİRİ DRIFT (uzun/H=24h, trend rejimi) ===")
for r in rows:
    if r["direction"] == "long" and r["horizon_h"] == 24 and r["gate"] == "none" and r["cost"] == "realistic":
        print(f"  baz: tam={r['full']['base_avg']:+.3f}%  TR={r['train']['base_avg']:+.3f}%  TE={r['test']['base_avg']:+.3f}%")
        break
for r in rows:
    if r["direction"] == "long" and r["horizon_h"] == 8 and r["gate"] == "none" and r["cost"] == "realistic":
        print(f"  baz: tam={r['full']['base_avg']:+.3f}%  TR={r['train']['base_avg']:+.3f}%  TE={r['test']['base_avg']:+.3f}% (H=8h)")
        break

# --- 3) Aylık pencere kırılımı: en iyi 'her iki yarı' adayı için ---
print("\n=== AYLIK KIRILIM (yerinden yeniden hesapla, en iyi kararlı aday) ===")
if both:
    best = both[0]
    print("aday:", best["direction"], best["gate"], best["horizon_h"], "h",
          best["thr"], "cost", best["cost"], "cost_pct", best["cost_pct"])
    sym = data["meta"]["symbol"]
    bars = C.fetch_klines(sym, "15m", days)
    feat = C.build_features(bars)
    hb = best["horizon_h"] * 4
    fwd, mfe, mae = C.forward_stats(feat, hb)
    sig = C.mask_for(feat, best["thr"], best["direction"], best["gate"])
    n = feat["n"]
    # aylık sınırlar (UTC)
    import datetime as dt
    months = {}
    for i in range(n):
        m = dt.datetime.utcfromtimestamp(feat["t"][i] / 1000).strftime("%Y-%m")
        months.setdefault(m, []).append(i)
    print(f"  {'ay':8} {'n_sig':>6} {'n_bar':>7} {'sig_net%':>9} {'base%':>8} {'excess%':>8} {'hit%':>6} {'base_hit%':>9}")
    for m in sorted(months):
        idx = np.array(months[m])
        wm = np.zeros(n, dtype=bool)
        wm[idx] = True
        e = C.eval_mask(feat, fwd, mfe, mae, sig & wm, best["direction"], best["cost_pct"])
        if not e.get("n"):
            continue
        print(f"  {m:8} {e['n']:6d} {len(idx):7d} {e['sig_avg_net']:+9.3f} {e['base_avg']:+8.3f} "
              f"{e['excess']:+8.3f} {e['hit']:6.1f} {e['base_hit']:9.1f}")
