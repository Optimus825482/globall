"""
VectorBT Quant Araştırma Laboratuvarı: Oynaklık Rejimi ve Volatilite Genişleme Modelleri
1. Garman-Klass Volatilite Sıkışması ve Hacimli Genişleme (GK-Vol Expansion)
2. Keltner Aşırı Sapma ve Kurumsal Kapitülasyon Sekmesi (Keltner -2.5 ATR Bounce)
3. Volume-Weighted RSI (VW-RSI) Hacim Ağırlıklı Momentum Kırılımı
4. Garman-Klass ve Parkinson Birleşik Oynaklık Patlaması
5. Linda Raschke Volatility Breakout (Inside Bar + ATR Expansion)

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

def _garman_klass_vol(O, H, L, C, period=20):
    """Garman-Klass Volatilite Tahmincisi (OHLC bazlı yüksek verimli volatilite)."""
    n = len(C)
    log_hl = np.log(np.maximum(H / np.maximum(L, 1e-9), 1e-9)) ** 2
    log_co = np.log(np.maximum(C / np.maximum(O, 1e-9), 1e-9)) ** 2
    gk_bar = 0.5 * log_hl - (2.0 * np.log(2.0) - 1.0) * log_co
    gk_vol = np.zeros(n)
    for i in range(period, n):
        gk_vol[i] = np.sqrt(np.maximum(gk_bar[i-period+1:i+1].mean(), 0.0))
    return gk_vol

def _parkinson_vol(H, L, period=20):
    """Parkinson Volatilite Tahmincisi (High-Low aralığı bazlı)."""
    n = len(H)
    log_hl = np.log(np.maximum(H / np.maximum(L, 1e-9), 1e-9)) ** 2
    const = 1.0 / (4.0 * np.log(2.0))
    p_vol = np.zeros(n)
    for i in range(period, n):
        p_vol[i] = np.sqrt(np.maximum(const * log_hl[i-period+1:i+1].mean(), 0.0))
    return p_vol

def _keltner_channels(H, L, C, ema_period=20, atr_period=14, mult=2.2):
    ema = _ema(C, ema_period)
    atr = _atr(H, L, C, atr_period)
    upper = ema + mult * atr
    lower = ema - mult * atr
    return ema, upper, lower

def _vw_rsi(C, V, period=14):
    """Hacim Ağırlıklı RSI (Volume-Weighted RSI)."""
    n = len(C)
    diff = np.diff(C, prepend=C[0])
    vw_change = diff * V
    
    pos = np.where(vw_change > 0, vw_change, 0.0)
    neg = np.where(vw_change < 0, -vw_change, 0.0)
    
    vw_rsi_vals = np.zeros(n)
    pos_roll = pd.Series(pos).rolling(window=period, min_periods=period).mean().values
    neg_roll = pd.Series(neg).rolling(window=period, min_periods=period).mean().values
    
    for i in range(period, n):
        denom = pos_roll[i] + neg_roll[i]
        vw_rsi_vals[i] = 100.0 * (pos_roll[i] / denom) if denom > 0 else 50.0
    return vw_rsi_vals

def generate_vol_signals(O, H, L, C, V):
    n = len(C)
    gk_vol = _garman_klass_vol(O, H, L, C, period=20)
    park_vol = _parkinson_vol(H, L, period=20)
    k_mid, k_up, k_lo = _keltner_channels(H, L, C, 20, 14, mult=2.2)
    vw_rsi_vals = _vw_rsi(C, V, period=14)
    atr_vals = _atr(H, L, C, period=14)
    e50 = _ema(C, 50)
    
    avg_vol = np.zeros(n)
    for i in range(20, n):
        avg_vol[i] = V[i-20:i].mean()
        
    sig_gk_expand = np.zeros(n, dtype=bool)
    sig_keltner_bounce = np.zeros(n, dtype=bool)
    sig_vw_rsi_break = np.zeros(n, dtype=bool)
    sig_inside_bar_break = np.zeros(n, dtype=bool)
    sig_dual_vol_break = np.zeros(n, dtype=bool)
    
    for i in range(30, n):
        # 1. Garman-Klass Volatilite Sıkışması ve Hacimli Genişleme
        # Son 30 barın en düşük %25'lik oynaklık bandında sıkışıp aniden 15-bar tepeyi kırma
        gk_window = gk_vol[i-25:i]
        is_compressed = gk_vol[i-1] <= np.percentile(gk_window, 30) if len(gk_window) else False
        prev_highest_15 = H[i-15:i].max()
        if is_compressed and (C[i] > prev_highest_15) and (V[i] >= avg_vol[i] * 1.35) and (C[i] > e50[i]):
            sig_gk_expand[i] = True
            
        # 2. Keltner Aşırı Sapma ve Kurumsal Kapitülasyon Sekmesi
        # Önceki bar alt Keltner kanalını delmiş, son bar yeşil gövdeyle içeri sıçrıyor + Hacim
        lo_pierced = L[i-1] <= k_lo[i-1]
        bounce_inside = (C[i] > k_lo[i]) and (C[i] > O[i]) and (C[i] > (H[i] + L[i]) / 2.0)
        if lo_pierced and bounce_inside and (V[i-1] >= avg_vol[i-1] * 1.3):
            sig_keltner_bounce[i] = True
            
        # 3. Volume-Weighted RSI (VW-RSI) 50 Seviyesini Hacimle Yukarı Kırma
        if (vw_rsi_vals[i] > 52.0) and (vw_rsi_vals[i-1] <= 52.0) and (C[i] > e50[i]) and (V[i] >= avg_vol[i] * 1.2):
            sig_vw_rsi_break[i] = True
            
        # 4. Linda Raschke Inside Bar Volatilite Kırılımı
        # i-1 barı i-2 barının içinde (Inside Bar), i barı önceki tepeyi hacimle patlatıyor
        inside_bar = (H[i-1] < H[i-2]) and (L[i-1] > L[i-2])
        if inside_bar and (C[i] > H[i-1]) and (C[i] > e50[i]) and (V[i] >= avg_vol[i] * 1.25):
            sig_inside_bar_break[i] = True
            
        # 5. Dual Volatilite (GK + Parkinson) Eşzamanlı Kırılımı
        if (gk_vol[i] > gk_vol[i-1] * 1.2) and (park_vol[i] > park_vol[i-1] * 1.2) and (C[i] > e50[i]) and (C[i] > H[i-10:i].max()):
            sig_dual_vol_break[i] = True

    def shift1(arr):
        z = np.zeros_like(arr, dtype=bool)
        z[1:] = arr[:-1]
        return z

    rnd = np.zeros(n, dtype=bool)
    rnd[::15] = True

    signals = {
        "gk_vol_expansion": shift1(sig_gk_expand),
        "keltner_capitulation_rev": shift1(sig_keltner_bounce),
        "vw_rsi_surge": shift1(sig_vw_rsi_break),
        "inside_bar_break": shift1(sig_inside_bar_break),
        "dual_vol_break": shift1(sig_dual_vol_break),
        "__RASTGELE__": shift1(rnd)
    }
    for k in signals:
        signals[k][:35] = False
    return signals

def run_vol_test():
    print("\n" + "=" * 95)
    print(" === OYNAKLIK REJİMİ & VOLATİLİTE GENİŞLEME MODELLERİ (1H | 40 Aktif Coin) ===")
    print(" 1. Garman-Klass Vol Expansion  2. Keltner Capitulation Rev  3. VW-RSI Surge")
    print(" 4. Inside Bar Breakout         5. Dual Volatilite Kırılımı")
    print(" Maliyet: %0.15 net round-trip komisyon | lookahead=0 (shift=1)")
    print("=" * 95)
    
    t0 = time.time()
    data = asyncio.run(load_candles(symbols=40, days=45, timeframe="1h"))
    print(f"Yuklenen Aktif Coin: {len(data)} sembol, Toplam {sum(len(d['C']) for d in data.values()):,} bar ({time.time()-t0:.1f}s)")
    
    tp_pct, sl_pct, fee = 3.5, 1.8, 0.15
    agg = defaultdict(lambda: defaultdict(lambda: {"tp_sl": None, "trail": None}))
    
    for sym, d in data.items():
        O, H, L, C, V = d["O"], d["H"], d["L"], d["C"], d["V"]
        sigs = generate_vol_signals(O, H, L, C, V)
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
        print(f"{'Strateji':<26} {'Islem (n)':<10} {'WinRate':<9} {'ProfitFac':<10} {'Ort Net%':<10} {'Pozitif Coin':<13} {'Durum'}")
        print("-" * 94)
        
        rows = []
        for name in ["gk_vol_expansion", "keltner_capitulation_rev", "vw_rsi_surge", "inside_bar_break", "dual_vol_break", "__RASTGELE__"]:
            c = combine(name, mode)
            if not c:
                continue
            status = "[KAZANCLI] **" if (c["pf"] >= 1.50 and c["avg"] > 0) else ("[KAZANCLI]" if c["avg"] > 0 else "[ZARAR]")
            rows.append((name, c["n"], c["wr"], c["pf"], c["avg"], f"{c['coins_pos']}/{c['coins_n']}", status))
            
        rows.sort(key=lambda x: x[3], reverse=True)
        for r in rows:
            print(f"{r[0]:<26} {r[1]:<10} %{r[2]:<8.1f} {r[3]:<10.2f} %{r[4]:<9.3f} {r[5]:<13} {r[6]}")

if __name__ == "__main__":
    run_vol_test()
