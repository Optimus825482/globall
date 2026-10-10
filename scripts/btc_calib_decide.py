#!/usr/bin/env python3
"""KARAR TESTİ — overlap-düzeltilmiş, blok-bootstrap, V4-tarzı 'büyük hareket' lift,
önemsiz kapı kıyası ve kesişmeyen OOS penceresi.

Amaç: gözlenen excess gerçek mi, yoksa (a) örtüşen ileri pencerelerin şişirdiği
istatistik mi, (b) basit trend-beta mı, (c) rejim sürüklenmesi mi?
"""
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
feat = C.build_features(C.fetch_klines(data["meta"]["symbol"], "15m", data["meta"]["days"]))
n = feat["n"]
rng = np.random.default_rng(7)

CAND = [
    # (etiket, yön, kapı, horizon_h, ret8, atr, slope, adx)
    ("A_mom8",  "long", "none",       8,  1.2, 0.5, 0.15, 25.0),
    ("B_mom24", "long", "none",      24,  0.5, 0.5, 0.06, 15.0),
    ("C_mom24st","long","supertrend",24,  0.8, 0.5, 0.10, 15.0),
    ("D_mom8lo","long", "none",       8,  1.2, 0.35,0.15, 15.0),
    # referans: ham V4 filtresi BTC eşikleriyle
    ("REF_v4",  "long", "none",       8,  2.0, 0.5, 0.30, 25.0),
    ("REF_ema200only","long","ema200",8,  0.0, 0.0, 0.00, 0.0),   # önemsiz kapı
    ("REF_stonly","long","supertrend",8,  0.0, 0.0, 0.00, 0.0),
]


def nonoverlap_mask(sig, spacing):
    """Zaman sırasında, son alınandan >= spacing bar sonra gelen sinyalleri tut."""
    out = np.zeros(len(sig), dtype=bool)
    last = -10**9
    for i in np.where(sig)[0]:
        if i - last >= spacing:
            out[i] = True
            last = i
    return out


def stats(idx, fwd, direction, cost):
    sign = 1.0 if direction == "long" else -1.0
    r = sign * fwd[idx] - cost
    return r


print("=" * 100)
print("KARAR TESTİ — overlap-düzeltilmiş örneklem, blok-bootstrap, hedef-tabanlı hit-lift")
print("=" * 100)

for (label, direction, gate, hh, r8, atr, sl, adx) in CAND:
    hb = hh * 4
    fwd, mfe, mae = C.forward_stats(feat, hb)
    thr = {"ret8": r8, "atr": atr, "slope": sl, "adx": adx, "di": 20.0}
    sig = C.mask_for(feat, thr, direction, gate)
    valid = ~np.isnan(fwd)
    sig &= valid
    idx_all = np.where(sig)[0]
    if len(idx_all) < 10:
        print(f"{label}: n={len(idx_all)} çok az → atla")
        continue
    px = feat["c"]
    cost = C.cost_scenarios(float(px[-1]), hh)["realistic"]
    sign = 1.0 if direction == "long" else -1.0
    base = sign * fwd[valid]

    # --- (1) örtüşen vs örtüşmeyen ---
    sig_no = nonoverlap_mask(sig, hb)
    idx_no = np.where(sig_no)[0]
    r_all = stats(idx_all, fwd, direction, cost)
    r_no = stats(idx_no, fwd, direction, cost)
    ex_all = r_all.mean() - base.mean()
    ex_no = r_no.mean() - base.mean() if len(r_no) else float("nan")

    # --- (2) blok-bootstrap (örtüşme farkındalıklı) ---
    # sinyal getirilerini bloklar halinde yeniden örnekle (blok=hb)
    def block_boot(x, blk, iters=2000):
        m = len(x)
        if m < blk:
            return np.array([x.mean()])
        nb = int(np.ceil(m / blk))
        starts = rng.integers(0, max(1, m - blk), size=(iters, nb))
        return np.array([np.concatenate([x[s:s + blk] for s in row])[:m].mean() for row in starts])
    boot = block_boot(r_all - base.mean(), hb)
    p_block = 2 * min((boot <= 0).mean(), (boot >= 0).mean())

    # --- (3) V4-tarzı hedef tabanlı hit-lift (büyük hareket) ---
    lines = []
    for thr_move in (0.0, 0.25, 0.5, 1.0):
        tgt = sign * fwd
        base_hit = float((tgt[valid] > thr_move).mean()) * 100
        sig_hit = float((tgt[idx_all] > thr_move).mean()) * 100
        lines.append(f"      >{thr_move:>4.2f}%: sig%={sig_hit:5.1f} base%={base_hit:5.1f} lift={sig_hit/max(base_hit,1e-9):4.2f}x")

    print(f"\n{label}: {direction} gate={gate} H={hh}h thr(r8>={r8},atr>={atr},sl>={sl},adx>={adx}) cost={cost}%")
    print(f"   örtüşen  : n={len(idx_all):4d} net%={r_all.mean():+.3f} base%={base.mean():+.3f} excess%={ex_all:+.3f}")
    print(f"   örtüşmesiz: n={len(idx_no):4d} net%={r_no.mean():+.3f} excess%={ex_no:+.3f}  (>={hb} bar ara)")
    print(f"   blok-bootstrap excess p={p_block:.4f} (blok={hb})")
    print("   hedef-tabanlı hit-lift:")
    print("\n".join(lines))

# --- (5) kesişmeyen OOS: ilk %60 train / son %40 test, VE son %40 tek başına ---
print("\n" + "=" * 100)
print("KESİŞMEYEN OOS: ilk %60 train / son %40 test")
print("=" * 100)
cut = int(n * 0.60)
for (label, direction, gate, hh, r8, atr, sl, adx) in CAND[:5]:
    hb = hh * 4
    fwd, mfe, mae = C.forward_stats(feat, hb)
    thr = {"ret8": r8, "atr": atr, "slope": sl, "adx": adx, "di": 20.0}
    sig = C.mask_for(feat, thr, direction, gate)
    tr = np.zeros(n, dtype=bool); tr[:cut] = True
    te = ~tr
    px = feat["c"]
    cost = C.cost_scenarios(float(px[-1]), hh)["realistic"]
    e_tr = C.eval_mask(feat, fwd, mfe, mae, sig & tr, direction, cost)
    e_te = C.eval_mask(feat, fwd, mfe, mae, sig & te, direction, cost)
    print(f"  {label:12} H={hh:2}h | TRAIN n={e_tr.get('n',0):4d} net%={e_tr.get('sig_avg_net')} ex%={e_tr.get('excess')} "
          f"| TEST n={e_te.get('n',0):4d} net%={e_te.get('sig_avg_net')} ex%={e_te.get('excess')}")

# --- (6) Son 3 ay tek başına (taze rejim) ---
print("\n" + "=" * 100)
print("SON ~3 AY TEK BAŞINA (taze rejim, 2026-07-10 →)")
print("=" * 100)
import datetime as dt  # noqa: E402
cut_ms = dt.datetime(2026, 7, 10).timestamp() * 1000
recent = feat["t"] >= cut_ms
for (label, direction, gate, hh, r8, atr, sl, adx) in CAND[:5]:
    hb = hh * 4
    fwd, mfe, mae = C.forward_stats(feat, hb)
    thr = {"ret8": r8, "atr": atr, "slope": sl, "adx": adx, "di": 20.0}
    sig = C.mask_for(feat, thr, direction, gate)
    cost = C.cost_scenarios(float(feat["c"][-1]), hh)["realistic"]
    e = C.eval_mask(feat, fwd, mfe, mae, sig & recent, direction, cost)
    print(f"  {label:12} H={hh:2}h | n={e.get('n',0):4d} net%={e.get('sig_avg_net')} base%={e.get('base_avg')} "
          f"ex%={e.get('excess')} hit%={e.get('hit')} hitL={e.get('hit_lift')}")
