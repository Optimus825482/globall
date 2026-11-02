"""
VectorBT Quant Araştırma Laboratuvarı: Frontier Alpha Modelleri
1. Chande Momentum Oscillator (CMO) İvme Kırılımı
2. Alan Hull Sıfır-Gecikmeli HMA Trend İvmesi + Pivot
3. Cumulative Flow / Delta Imbalance Alıcı Baskısı (Buy Flow Dominance)
4. McGinley Dynamic Otomatik Hızlanan Destek Sekmesi
5. Linda Raschke Holy Grail (ADX>=25 + EMA20 Pullback Sekmesi)

Tüm testler Binance Spot aktif 40 coin üzerinde, %0.15 net maliyet ve shift(1) kuralıyla çalışır.
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

def _wma(arr, period):
    weights = np.arange(1, period + 1)
    res = np.zeros(len(arr))
    for i in range(period - 1, len(arr)):
        res[i] = np.dot(arr[i-period+1:i+1], weights) / weights.sum()
    return res

def _hma(arr, period=21):
    half_period = int(period / 2)
    sqrt_period = int(np.sqrt(period))
    wma_half = _wma(arr, half_period)
    wma_full = _wma(arr, period)
    diff = 2 * wma_half - wma_full
    return _wma(diff, sqrt_period)

def _cmo(C, period=14):
    n = len(C)
    diff = np.diff(C, prepend=C[0])
    gains = np.where(diff > 0, diff, 0.0)
    losses = np.where(diff < 0, -diff, 0.0)
    cmo_vals = np.zeros(n)
    for i in range(period, n):
        sum_g = np.sum(gains[i-period+1:i+1])
        sum_l = np.sum(losses[i-period+1:i+1])
        denom = sum_g + sum_l
        cmo_vals[i] = 100.0 * (sum_g - sum_l) / denom if denom > 0 else 0.0
    return cmo_vals

def _mcginley_dynamic(C, period=14):
    n = len(C)
    md = np.zeros(n)
    md[0] = C[0]
    k = 0.6 * period
    for i in range(1, n):
        ratio = C[i] / md[i-1] if md[i-1] > 0 else 1.0
        md[i] = md[i-1] + (C[i] - md[i-1]) / (k * (ratio ** 4))
    return md

def _adx(H, L, C, period=14):
    n = len(C)
    up_move = np.zeros(n)
    down_move = np.zeros(n)
    for i in range(1, n):
        up_move[i] = H[i] - H[i-1]
        down_move[i] = L[i-1] - L[i]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = np.zeros(n)
    tr[0] = H[0] - L[0]
    for i in range(1, n):
        tr[i] = max(H[i] - L[i], abs(H[i] - C[i-1]), abs(L[i] - C[i-1]))
    smooth_tr = _ema(tr, period)
    smooth_plus = _ema(plus_dm, period)
    smooth_minus = _ema(minus_dm, period)
    denom = np.maximum(smooth_tr, 1e-9)
    plus_di = 100.0 * (smooth_plus / denom)
    minus_di = 100.0 * (smooth_minus / denom)
    di_sum = np.maximum(plus_di + minus_di, 1e-9)
    dx = 100.0 * (np.abs(plus_di - minus_di) / di_sum)
    return _ema(dx, period)

def generate_frontier_signals(H, L, C, V):
    n = len(C)
    cmo = _cmo(C, 14)
    hma21 = _hma(C, 21)
    md = _mcginley_dynamic(C, 14)
    adx_vals = _adx(H, L, C, 14)
    e20 = _ema(C, 20)
    e50 = _ema(C, 50)
    
    avg_vol = np.zeros(n)
    for i in range(20, n):
        avg_vol[i] = V[i-20:i].mean()
        
    sig_cmo = np.zeros(n, dtype=bool)
    sig_hma = np.zeros(n, dtype=bool)
    sig_flow = np.zeros(n, dtype=bool)
    sig_mcginley = np.zeros(n, dtype=bool)
    sig_holy_grail = np.zeros(n, dtype=bool)
    
    for i in range(25, n):
        # 1. Chande Momentum Oscillator (CMO): Sıfır çizgisini yukarı kesiş + Hacim + EMA50 üstü
        if (cmo[i] > 15.0) and (cmo[i-1] <= 15.0) and (C[i] > e50[i]) and (V[i] >= avg_vol[i] * 1.25):
            sig_cmo[i] = True
            
        # 2. Hull HMA21 Konkav-Yukarı Dönüş + Donchian 10 Tepe Kırılımı
        hma_turning_up = (hma21[i] > hma21[i-1]) and (hma21[i-1] <= hma21[i-2])
        highest_10 = H[i-10:i].max()
        if hma_turning_up and (C[i] > highest_10) and (C[i] > e50[i]):
            sig_hma[i] = True
            
        # 3. Buy Flow Dominance (Bar Delta Oranı >= %70 alıcı baskısı + Yerel Kırılım)
        bar_range = H[i] - L[i]
        if bar_range > 0:
            buy_ratio = (C[i] - L[i]) / bar_range
            prev_highest_7 = H[i-7:i].max()
            if (buy_ratio >= 0.70) and (C[i] > prev_highest_7) and (V[i] >= avg_vol[i] * 1.30):
                sig_flow[i] = True
                
        # 4. McGinley Dynamic Destek Sekmesi: Düşük bar MD altına sarkıp yeşil barla üstüne sıçrıyor
        if (L[i-1] <= md[i-1]) and (C[i] > md[i]) and (C[i] > C[i-1]) and (C[i] > e50[i]):
            sig_mcginley[i] = True
            
        # 5. Linda Raschke Holy Grail: ADX >= 25 (sağlam trend) + EMA20 test edilip önceki tepe geçiliyor
        if (adx_vals[i] >= 25.0) and (L[i-1] <= e20[i-1]) and (C[i] > e20[i]) and (C[i] > H[i-1]):
            sig_holy_grail[i] = True

    def shift1(arr):
        z = np.zeros_like(arr, dtype=bool)
        z[1:] = arr[:-1]
        return z

    rnd = np.zeros(n, dtype=bool)
    rnd[::15] = True

    signals = {
        "cmo_accel_break": shift1(sig_cmo),
        "hma_concave_break": shift1(sig_hma),
        "buy_flow_dominance": shift1(sig_flow),
        "mcginley_rebound": shift1(sig_mcginley),
        "holy_grail_adx25": shift1(sig_holy_grail),
        "__RASTGELE__": shift1(rnd)
    }
    for k in signals:
        signals[k][:35] = False
    return signals

def run_frontier_test():
    print("\n" + "=" * 95)
    print(" === FRONTIER QUANT ALPHA MODELLERI VECTORBT TESTİ (1H | 40 Aktif Coin) ===")
    print(" 1. Chande Momentum (CMO)  2. Zero-Lag HMA  3. Buy Flow Dominance")
    print(" 4. McGinley Dynamic       5. Linda Raschke Holy Grail (ADX>=25)")
    print(" Maliyet: %0.15 net round-trip komisyon | lookahead=0 (shift=1)")
    print("=" * 95)
    
    t0 = time.time()
    data = asyncio.run(load_candles(symbols=40, days=45, timeframe="1h"))
    print(f"Yuklenen Aktif Coin: {len(data)} sembol, Toplam {sum(len(d['C']) for d in data.values()):,} bar ({time.time()-t0:.1f}s)")
    
    tp_pct, sl_pct, fee = 3.5, 1.8, 0.15
    agg = defaultdict(lambda: defaultdict(lambda: {"tp_sl": None, "trail": None}))
    
    for sym, d in data.items():
        H, L, C, V = d["H"], d["L"], d["C"], d["V"]
        sigs = generate_frontier_signals(H, L, C, V)
        for name, entries in sigs.items():
            if not np.any(entries):
                continue
            r1 = evaluate_vbt_fixed(C, entries, tp_pct=tp_pct, sl_pct=sl_pct, fee_pct=fee)
            if r1:
                agg[name][sym]["tp_sl"] = r1
            r2 = evaluate_dynamic_trailing(C, H, L, entries, fee_pct=fee)
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

    for mode, title in [("trail", "Dinamik Takipci Cikis Modeli"), ("tp_sl", f"Sabit TP/SL (%{tp_pct}/%{sl_pct}) Modeli")]:
        print(f"\n--- {title} ---")
        print(f"{'Strateji':<24} {'Islem (n)':<10} {'WinRate':<9} {'ProfitFac':<10} {'Ort Net%':<10} {'Pozitif Coin':<13} {'Durum'}")
        print("-" * 92)
        
        rows = []
        for name in ["cmo_accel_break", "hma_concave_break", "buy_flow_dominance", "mcginley_rebound", "holy_grail_adx25", "__RASTGELE__"]:
            c = combine(name, mode)
            if not c:
                continue
            status = "[KAZANCLI] **" if (c["pf"] >= 1.50 and c["avg"] > 0) else ("[KAZANCLI]" if c["avg"] > 0 else "[ZARAR]")
            rows.append((name, c["n"], c["wr"], c["pf"], c["avg"], f"{c['coins_pos']}/{c['coins_n']}", status))
            
        rows.sort(key=lambda x: x[3], reverse=True)
        for r in rows:
            print(f"{r[0]:<24} {r[1]:<10} %{r[2]:<8.1f} {r[3]:<10.2f} %{r[4]:<9.3f} {r[5]:<13} {r[6]}")

if __name__ == "__main__":
    run_frontier_test()
