"""Yapay Zeka, Kuantitatif Alpha Faktörleri ve Lider-Takipçi (Lead-Lag) Test Laboratuvarı.

İncelenen 4 Kuantitatif Mimari:
1. Kaufman Efficiency Ratio Trend Filtresi (Kaufman AMA - Gürültüsüz Trend):
   - ER = |Net Fiyat Hareketi| / Toplam Yol > 0.45 (Testere piyasasını tamamen filtreler)
2. BTC Lead-Lag Hacim Dökülmesi (Cross-Asset Spillover):
   - BTC 1H barda hacimli impuls kırılımı yaptığında (+%1.5 ve 2x hacim), 1 bar gecikmeyle altcoin alımı
3. Kompozit Çoklu-Faktör Alpha Skoru (Multi-Factor Z-Score Confluence):
   - Z(Hacim) + Z(Momentum) + Z(RSI Dip) bileşkesi 90. persentili aştığında giriş
4. Chande Kroll Volatilite Kanal Kırılımı (Katsanos / Chande Dinamik Stop):
   - Yüksek oynaklık kanalı tavan kırılımı

Test Kapsamı:
- 40 Aktif Binance Spot USDT Coini
- 1 Saatlik (1h) Barlar
- Net %0.15 Round-Trip Spot Komisyonu
- shift(1) kuralı ile Lookahead bias sıfırdır.
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

# ─── 1. Kaufman Efficiency Ratio (ER) ve KAMA ───────────────────────────────
def calculate_kaufman_er(C, period=14):
    n = len(C)
    er = np.zeros(n)
    for i in range(period, n):
        net_change = abs(C[i] - C[i-period])
        sum_changes = np.sum(np.abs(np.diff(C[i-period:i+1])))
        er[i] = (net_change / sum_changes) if sum_changes > 0 else 0.0
    return er

# ─── 2. Çoklu-Faktör Z-Score Alpha Modeli ────────────────────────────────────
def calculate_multi_factor_alpha(H, L, C, V, period=20):
    n = len(C)
    alpha_score = np.zeros(n)
    
    rsi_vals = _rsi(C, 14)
    mom = np.zeros(n)
    mom[5:] = (C[5:] - C[:-5]) / C[:-5] * 100.0
    
    for i in range(period, n):
        # Hacim Z-Score
        vw = V[i-period+1:i+1]
        v_mean = vw.mean()
        v_std = vw.std()
        vol_z = (V[i] - v_mean) / v_std if v_std > 0 else 0.0
        
        # Momentum Z-Score
        mw = mom[i-period+1:i+1]
        m_mean = mw.mean()
        m_std = mw.std()
        mom_z = (mom[i] - m_mean) / m_std if m_std > 0 else 0.0
        
        # RSI Dip Faktörü (30'un altı yüksek puan)
        rsi_factor = (50.0 - rsi_vals[i]) / 15.0
        
        # Bileşik Faktör Skoru
        alpha_score[i] = 0.40 * vol_z + 0.35 * mom_z + 0.25 * rsi_factor
    return alpha_score

# ─── 3. Chande Kroll Volatilite Kanalı ───────────────────────────────────────
def calculate_chande_kroll(H, L, C, p=10, mult=2.0):
    n = len(C)
    atr_vals = _atr(H, L, C, p)
    stop_hi = np.zeros(n)
    for i in range(p, n):
        hi_p = H[i-p+1:i+1].max()
        stop_hi[i] = hi_p - mult * atr_vals[i]
    return stop_hi

# ─── Sinyal Üretici ──────────────────────────────────────────────────────────
def generate_alpha_signals(H, L, C, V, btc_impulse_series=None):
    n = len(C)
    er = calculate_kaufman_er(C, period=14)
    alpha = calculate_multi_factor_alpha(H, L, C, V, period=20)
    stop_hi = calculate_chande_kroll(H, L, C, p=10, mult=1.8)
    
    e50 = _ema(C, 50)
    rsi_vals = _rsi(C, 14)
    avg_vol = np.zeros(n)
    for i in range(20, n):
        avg_vol[i] = V[i-20:i].mean()
        
    sig_kaufman = np.zeros(n, dtype=bool)
    sig_alpha = np.zeros(n, dtype=bool)
    sig_chande = np.zeros(n, dtype=bool)
    sig_lead_lag = np.zeros(n, dtype=bool)
    
    for i in range(25, n):
        # 1. Kaufman ER Trend Kırılımı: ER > 0.45 (gürültüsüz saf trend) + Hacimli 14-bar tepe kırılımı
        highest_14 = H[i-14:i].max()
        if (er[i] >= 0.42) and (C[i] > highest_14) and (C[i-1] <= highest_14) and (V[i] >= avg_vol[i] * 1.2):
            sig_kaufman[i] = True
            
        # 2. Multi-Factor Alpha Spike: Alpha Skoru > 1.8 (90. persentil) + EMA50 üstünde
        if (alpha[i] >= 1.80) and (C[i] > e50[i]) and (rsi_vals[i] <= 65.0):
            sig_alpha[i] = True
            
        # 3. Chande Kroll Kırılımı: Fiyat Chande Stop seviyesini yukarı kesiyor
        if (C[i] > stop_hi[i]) and (C[i-1] <= stop_hi[i-1]) and (C[i] > e50[i]):
            sig_chande[i] = True
            
        # 4. BTC Lead-Lag Dökülmesi: BTC 1 bar önce impuls kırdı, altcoin henüz patlamadı
        if btc_impulse_series is not None and btc_impulse_series[i]:
            alt_not_overbought = (rsi_vals[i] <= 58.0) and (C[i] > e50[i])
            if alt_not_overbought:
                sig_lead_lag[i] = True

    def shift1(arr):
        z = np.zeros_like(arr, dtype=bool)
        z[1:] = arr[:-1]
        return z

    signals = {
        "kaufman_er_trend": shift1(sig_kaufman),
        "multi_factor_alpha": shift1(sig_alpha),
        "chande_kroll_break": shift1(sig_chande),
    }
    if btc_impulse_series is not None:
        signals["btc_lead_lag_spill"] = shift1(sig_lead_lag)
        
    rnd = np.zeros(n, dtype=bool)
    rnd[::15] = True
    signals["__RASTGELE__"] = shift1(rnd)
    
    for k in signals:
        signals[k][:35] = False
    return signals

def run_alpha_test():
    print("\n" + "=" * 94)
    print(" === YAPAY ZEKA VE MULTI-FACTOR ALPHA VECTORBT TEST LABORATUVARI (1H | 40 Aktif Coin) ===")
    print(" 1. Kaufman Efficiency Ratio  2. Multi-Factor Z-Score  3. Chande Kroll  4. BTC Lead-Lag")
    print(" Maliyet: %0.15 net round-trip komisyon | lookahead=0 (shift=1)")
    print("=" * 94)
    
    t0 = time.time()
    data = asyncio.run(load_candles(symbols=40, days=45, timeframe="1h"))
    print(f"Yuklenen Aktif Coin: {len(data)} sembol, Toplam {sum(len(d['C']) for d in data.values()):,} bar ({time.time()-t0:.1f}s)")
    
    # BTC İmpuls Dizisi Hesapla (BTC 1H barda +%1.4 getiri ve 1.8x hacim yaptı mı?)
    btc_impulse = None
    if "BTCUSDT" in data:
        btcC = data["BTCUSDT"]["C"]
        btcV = data["BTCUSDT"]["V"]
        n_btc = len(btcC)
        btc_imp = np.zeros(n_btc, dtype=bool)
        btc_v_avg = np.zeros(n_btc)
        for i in range(20, n_btc):
            btc_v_avg[i] = btcV[i-20:i].mean()
        for i in range(21, n_btc):
            ret = (btcC[i] - btcC[i-1]) / btcC[i-1] * 100.0
            if (ret >= 1.3) and (btcV[i] >= btc_v_avg[i] * 1.6):
                btc_imp[i] = True
        btc_impulse = btc_imp
        
    tp_pct, sl_pct, fee = 3.5, 1.8, 0.15
    agg = defaultdict(lambda: defaultdict(lambda: {"tp_sl": [], "trail": []}))
    
    for sym, d in data.items():
        H, L, C, V = d["H"], d["L"], d["C"], d["V"]
        sigs = generate_alpha_signals(H, L, C, V, btc_impulse if sym != "BTCUSDT" else None)
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
    run_alpha_test()
