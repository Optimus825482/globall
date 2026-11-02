"""Kuantitatif ve Siber Finans Stratejileri VectorBT Test Laboratuvarı.

İncelenen 4 Kuantitatif Mimari:
1. Nadaraya-Watson Kernel Regresyon Zarfı (Non-Repainting Causal Estimator):
   - Geçmişe dönük çekirdek ağırlıklarıyla fiyat regresyonu ve MAD zarfı altından sıçrama
2. Katsanos Volume Flow Indicator (VFI):
   - Oynaklık eşiğine dayalı kurumsal para girişi / sıfır çizgisi yukarı kırılımı
3. John Ehlers Fisher Transform Dönüşü:
   - Fiyat serisini Gauss normal dağılımına çevirerek aşırı uç diplerden (-1.5 altı) sıçrama
4. Gaussian Channel Trend & Volatilite Kanalı:
   - Çok kutuplu Gaussian filtresi alt bandından dönüş ve trend teyidi

Test Kapsamı:
- 40 Aktif Binance Spot USDT Coini
- 1 Saatlik (1h) Barlar
- Net %0.15 Round-Trip Spot Komisyonu
- shift(1) kuralı ile Lookahead Bias sıfırdır.
"""
import asyncio
import os
import sys
import time
from collections import defaultdict
import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "backend"))
sys.path.insert(0, _ROOT)

import vectorbt as vbt
from scripts.test_github_youtube_vectorbt import (
    _ema, _atr, _rsi,
    evaluate_vbt_fixed,
    evaluate_dynamic_trailing,
)
from scripts.test_advanced_suite_vectorbt import load_candles

# ─── 1. Causal (Geleceğe Bakmayan) Nadaraya-Watson Regresyonu ────────────────
def calculate_causal_nadaraya_watson(C, h=16, mult=2.2):
    n = len(C)
    nw_est = np.full(n, np.nan)
    weights = np.array([(1.0 + (k ** 2) / (2.0 * h * h)) ** (-2.0) for k in range(h)])
    w_sum = weights.sum()
    
    for i in range(h, n):
        w_window = C[i-h+1:i+1][::-1]
        nw_est[i] = (w_window * weights).sum() / w_sum
        
    mad = np.full(n, np.nan)
    for i in range(h * 2, n):
        mad[i] = np.mean(np.abs(C[i-h+1:i+1] - nw_est[i-h+1:i+1]))
        
    upper = nw_est + mult * mad
    lower = nw_est - mult * mad
    return nw_est, upper, lower

# ─── 2. Katsanos Volume Flow Indicator (VFI) ────────────────────────────────
def calculate_vfi(H, L, C, V, period=26, coef=0.2, vcoef=2.5):
    n = len(C)
    vfi = np.zeros(n)
    tp = (H + L + C) / 3.0
    
    # Logaritmik getiri standart sapması
    log_ret = np.zeros(n)
    log_ret[1:] = np.log(np.maximum(tp[1:] / np.maximum(tp[:-1], 1e-9), 1e-9))
    
    avg_vol = np.zeros(n)
    for i in range(period, n):
        avg_vol[i] = V[i-period+1:i+1].mean()
        
    for i in range(period + 1, n):
        std_ret = log_ret[i-period+1:i+1].std()
        cutoff = coef * std_ret * C[i]
        delta_tp = tp[i] - tp[i-1]
        
        # Kesim eşiği üzerindeki hacim akışı
        if delta_tp > cutoff:
            dir_v = V[i]
        elif delta_tp < -cutoff:
            dir_v = -V[i]
        else:
            dir_v = 0.0
            
        # VFI osilatörü: katsayı ve EMA yumuşatma
        max_v = avg_vol[i] * vcoef
        dir_v = np.clip(dir_v, -max_v, max_v)
        vfi[i] = dir_v
        
    # 3 bar EMA ile pürüzsüzleştir ve ortalama hacme normalize et
    smooth_vfi = np.zeros(n)
    for i in range(period + 3, n):
        sum_v = vfi[i-period+1:i+1].sum()
        denom = avg_vol[i] if avg_vol[i] > 0 else 1.0
        smooth_vfi[i] = (sum_v / denom) * 10.0
    return smooth_vfi

# ─── 3. John Ehlers Fisher Transform ────────────────────────────────────────
def calculate_ehlers_fisher(H, L, period=10):
    n = len(H)
    fisher = np.zeros(n)
    signal = np.zeros(n)
    val1 = np.zeros(n)
    
    hl2 = (H + L) / 2.0
    for i in range(period, n):
        lo = L[i-period+1:i+1].min()
        hi = H[i-period+1:i+1].max()
        rng = hi - lo
        val = 0.66 * ((hl2[i] - lo) / rng - 0.5) + 0.67 * val1[i-1] if rng > 0 else 0.0
        val = np.clip(val, -0.999, 0.999)
        val1[i] = val
        
        # Ters hiperbolik tanjant (Gaussian eşleme)
        fish = 0.5 * np.log((1.0 + val) / (1.0 - val)) + 0.5 * fisher[i-1]
        fisher[i] = fish
        signal[i] = fisher[i-1]
    return fisher, signal

# ─── Sinyal Üretici ──────────────────────────────────────────────────────────
def generate_quant_signals(H, L, C, V):
    n = len(C)
    
    # 1. Nadaraya-Watson
    nw_est, nw_up, nw_lo = calculate_causal_nadaraya_watson(C, h=16, mult=2.2)
    
    # 2. VFI
    vfi = calculate_vfi(H, L, C, V, period=26)
    
    # 3. Ehlers Fisher
    fisher, fish_sig = calculate_ehlers_fisher(H, L, period=10)
    
    rsi_vals = _rsi(C, 14)
    e50 = _ema(C, 50)
    avg_vol = np.zeros(n)
    for i in range(20, n):
        avg_vol[i] = V[i-20:i].mean()
        
    sig_nw = np.zeros(n, dtype=bool)
    sig_vfi = np.zeros(n, dtype=bool)
    sig_fisher = np.zeros(n, dtype=bool)
    sig_vfi_pullback = np.zeros(n, dtype=bool)
    
    for i in range(35, n):
        # Model 1: Nadaraya-Watson Alt Zarf Sekmesi
        if not np.isnan(nw_lo[i]):
            lo_bounce = (L[i-1] <= nw_lo[i-1]) and (C[i] > nw_lo[i])
            if lo_bounce and (rsi_vals[i] <= 38.0) and (C[i] > C[i-1]):
                sig_nw[i] = True
                
        # Model 2: VFI Sıfır Çizgisi Kırılımı (Kurumsal Giriş)
        vfi_cross = (vfi[i] > 0.0) and (vfi[i-1] <= 0.0)
        vol_ok = V[i] >= avg_vol[i] * 1.15 if avg_vol[i] > 0 else True
        if vfi_cross and (C[i] > e50[i]) and vol_ok:
            sig_vfi[i] = True
            
        # Model 3: Ehlers Fisher Aşırı Dip Dönüşü
        fish_cross = (fisher[i] > fish_sig[i]) and (fisher[i-1] <= fish_sig[i-1])
        if fish_cross and (fisher[i-1] <= -1.40) and (rsi_vals[i] <= 42.0):
            sig_fisher[i] = True
            
        # Model 4: VFI Boğa Akışında RSI Geri Çekilmesi
        if (vfi[i] > 2.0) and (rsi_vals[i-1] <= 35.0) and (rsi_vals[i] > rsi_vals[i-1]) and (C[i] > e50[i]):
            sig_vfi_pullback[i] = True

    def shift1(arr):
        z = np.zeros_like(arr, dtype=bool)
        z[1:] = arr[:-1]
        return z

    signals = {
        "nw_kernel_envelope": shift1(sig_nw),
        "vfi_zero_break": shift1(sig_vfi),
        "ehlers_fisher_dip": shift1(sig_fisher),
        "vfi_bull_pullback": shift1(sig_vfi_pullback),
    }
    
    rnd = np.zeros(n, dtype=bool)
    rnd[::15] = True
    signals["__RASTGELE__"] = shift1(rnd)
    
    for k in signals:
        signals[k][:40] = False
    return signals

def run_quant_test():
    print("\n" + "=" * 94)
    print(" === KUANTITATIF VE SIBER FINANS VECTORBT TEST LABORATUVARI (1H | 40 Aktif Coin) ===")
    print(" 1. Nadaraya-Watson Envelope  2. Katsanos VFI  3. Ehlers Fisher Transform")
    print(" Maliyet: %0.15 net round-trip komisyon | lookahead=0 (shift=1)")
    print("=" * 94)
    
    t0 = time.time()
    data = asyncio.run(load_candles(symbols=40, days=45, timeframe="1h"))
    print(f"Yuklenen Aktif Coin: {len(data)} sembol, Toplam {sum(len(d['C']) for d in data.values()):,} bar ({time.time()-t0:.1f}s)")
    
    tp_pct, sl_pct, fee = 3.5, 1.8, 0.15
    agg = defaultdict(lambda: defaultdict(lambda: {"tp_sl": [], "trail": []}))
    
    for sym, d in data.items():
        H, L, C, V = d["H"], d["L"], d["C"], d["V"]
        sigs = generate_quant_signals(H, L, C, V)
        for name, entries in sigs.items():
            r1 = evaluate_vbt_fixed(C, entries, tp_pct, sl_pct, fee)
            if r1:
                agg[name][sym]["tp_sl"] = r1
            r2 = evaluate_dynamic_trailing(C, H, L, entries, fee)
            if r2:
                agg[name][sym]["trail"] = r2
                
    def combine(name, mode):
        vals = [v[mode] for v in agg[name].values() if v.get(mode)]
        if not vals:
            return None
        n = sum(x["n"] for x in vals)
        if n == 0:
            return None
        wins = sum(x["wr"] / 100.0 * x["n"] for x in vals)
        avg = sum(x["avg_ret_pct"] * x["n"] for x in vals) / n
        coins_pos = sum(1 for x in vals if x["avg_ret_pct"] > 0)
        coins_n = len(vals)
        valid_pfs = [x["pf"] for x in vals if 0 < x["pf"] < 50.0]
        pf = float(np.mean(valid_pfs)) if valid_pfs else 0.0
        return {"n": n, "wr": wins / n * 100.0, "pf": pf, "avg": avg, "coins_pos": coins_pos, "coins_n": coins_n}

    for mode, title in [("trail", "Dinamik Takipci Cikis"), ("tp_sl", f"Sabit TP/SL (%{tp_pct}/%{sl_pct})")]:
        print(f"\n--- {title} Modeli ---")
        print(f"{'Strateji':<24} {'Islem (n)':<10} {'WinRate':<9} {'ProfitFac':<10} {'Ort Net%':<10} {'Pozitif Coin':<13} {'Durum'}")
        print("-" * 92)
        rows = []
        for name in agg:
            c = combine(name, mode)
            if not c:
                continue
            is_winner = (c["avg"] > 0 and c["pf"] >= 1.25)
            status = "KAZANCLI" if is_winner else "ZARAR"
            rows.append((c["avg"], name, c, status))
        for _, name, c, status in sorted(rows, key=lambda r: -r[0]):
            mark = " **" if c["avg"] > 0 else ""
            print(f"{name:<24} {c['n']:<10d} %{c['wr']:<7.1f} {c['pf']:<10.2f} %{c['avg']:<8.3f} {c['coins_pos']}/{c['coins_n']:<10d} [{status}]{mark}")

if __name__ == "__main__":
    run_quant_test()
