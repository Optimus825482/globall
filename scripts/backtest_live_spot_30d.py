"""
30 Günlük Geriye Dönük Backtest Laboratuvarı: Canlıdaki 15 Spot Stratejisi
Tarih: Son 30 Gün (Son 720 Saatlik Mumlar)
Kapsam: Binance Spot'ta Aktif Hacimli Coinler
Komisyon: %0.15 Net Round-Trip Spot Komisyonu
Lookahead Bias: 0 (shift(1) ile barlar kapanmadan emir girilmez)
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

from scripts.test_github_youtube_vectorbt import (
    _ema, _atr, _rsi,
    evaluate_vbt_fixed,
    evaluate_dynamic_trailing,
)
from scripts.test_advanced_suite_vectorbt import (
    load_candles,
    calculate_rolling_vp,
    calculate_ttm_squeeze,
    calculate_cvd_metrics,
)
from scripts.test_quant_cybernetics_vectorbt import (
    calculate_vfi,
    calculate_causal_nadaraya_watson,
)
from scripts.test_alpha_factors_vectorbt import (
    calculate_kaufman_er,
    calculate_multi_factor_alpha,
)
from scripts.test_frontier_suite_vectorbt import (
    _cmo,
)
from scripts.test_vol_regime_suite_vectorbt import (
    _garman_klass_vol,
    _parkinson_vol,
)

def _kdj(highs, lows, closes, n=9, m1=3, m2=3):
    length = len(closes)
    k_vals = np.zeros(length)
    d_vals = np.zeros(length)
    j_vals = np.zeros(length)
    k_prev, d_prev = 50.0, 50.0
    for i in range(length):
        start = max(0, i - n + 1)
        hn = highs[start:i+1].max()
        ln = lows[start:i+1].min()
        rsv = ((closes[i] - ln) / (hn - ln) * 100.0) if hn != ln else 50.0
        k = (k_prev * (m1 - 1) + rsv) / m1
        d = (d_prev * (m2 - 1) + k) / m2
        j = 3.0 * k - 2.0 * d
        k_vals[i], d_vals[i], j_vals[i] = k, d, j
        k_prev, d_prev = k, d
    return k_vals, d_vals, j_vals

def _vwap(C, H, L, V, period=48):
    typical = (H + L + C) / 3.0
    n = len(C)
    vwap = np.zeros(n)
    lower_band = np.zeros(n)
    for i in range(period, n):
        tw = typical[i-period+1:i+1]
        vw = V[i-period+1:i+1]
        v_sum = vw.sum()
        if v_sum > 0:
            vwap_val = np.sum(tw * vw) / v_sum
            dev = np.sqrt(np.sum(vw * ((tw - vwap_val) ** 2)) / v_sum)
            vwap[i] = vwap_val
            lower_band[i] = vwap_val - 1.8 * dev
    return vwap, lower_band

def generate_all_15_signals(O, H, L, C, V):
    n = len(C)
    
    # 1. dual_vol_break
    gk_vol = _garman_klass_vol(O, H, L, C, period=20)
    park_vol = _parkinson_vol(H, L, period=20)
    
    # 2. gk_vol_expansion
    # gk_vol hesaplandı
    
    # 3. buy_flow_dominance
    bar_range = H - L
    buy_ratio = np.where(bar_range > 0, (C - L) / np.maximum(bar_range, 1e-9), 0.5)
    
    # 4. cmo_accel_break
    cmo_vals = _cmo(C, 14)
    
    # 5. kaufman_er_trend
    er_vals = calculate_kaufman_er(C, 14)
    
    # 6. multi_factor_alpha
    alpha_vals = calculate_multi_factor_alpha(H, L, C, V, 20)
    
    # 7. vp_vah_breakout
    poc_arr, val_arr, vah_arr = calculate_rolling_vp(H, L, C, V, window=24)
    
    # 8. vfi_zero_break
    vfi_vals = calculate_vfi(H, L, C, V, 130)
    
    # 9. nw_kernel_envelope
    nw_mid, nw_up, nw_lo = calculate_causal_nadaraya_watson(C, h=16, mult=2.2)
    
    # 10. cluc_wick_bounce
    body = np.abs(C - O)
    lower_wick = np.minimum(O, C) - L
    rsi_vals = _rsi(C, 14)
    
    # 11. cvd_absorption_wick
    bar_delta, cvd_vals = calculate_cvd_metrics(H, L, C, V)
    
    # 12. turtle_donchian
    # donchian 20 + ADX 14
    
    # 13. ttm_squeeze_fired
    in_sqz, fired, hist = calculate_ttm_squeeze(H, L, C)
    
    # 14. vwap_mean_rev
    vwap_val, vwap_lower = _vwap(C, H, L, V, period=48)
    
    # 15. kdj_pure_dip
    k_vals, d_vals, j_vals = _kdj(H, L, C, 9, 3, 3)
    
    # Ortak göstergeler
    e50 = _ema(C, 50)
    avg_vol = np.zeros(n)
    for i in range(20, n):
        avg_vol[i] = V[i-20:i].mean()
        
    sig = {k: np.zeros(n, dtype=bool) for k in [
        "dual_vol_break", "gk_vol_expansion", "buy_flow_dominance", "cmo_accel_break",
        "kaufman_er_trend", "multi_factor_alpha", "vp_vah_breakout", "vfi_zero_break",
        "nw_kernel_envelope", "cluc_wick_bounce", "cvd_absorption_wick", "turtle_donchian",
        "ttm_squeeze_fired", "vwap_mean_rev", "kdj_pure_dip"
    ]}
    
    for i in range(35, n):
        # 1. dual_vol_break
        if (gk_vol[i] > gk_vol[i-1] * 1.20) and (park_vol[i] > park_vol[i-1] * 1.20) and (C[i] > H[i-10:i].max()) and (C[i] > e50[i]):
            sig["dual_vol_break"][i] = True
            
        # 2. gk_vol_expansion
        gk_win = gk_vol[i-25:i]
        if len(gk_win) and (gk_vol[i-1] <= np.percentile(gk_win, 30)) and (C[i] > H[i-15:i].max()) and (V[i] >= avg_vol[i] * 1.35) and (C[i] > e50[i]):
            sig["gk_vol_expansion"][i] = True
            
        # 3. buy_flow_dominance
        if (buy_ratio[i] >= 0.70) and (C[i] > H[i-7:i].max()) and (V[i] >= avg_vol[i] * 1.30):
            sig["buy_flow_dominance"][i] = True
            
        # 4. cmo_accel_break
        if (cmo_vals[i] > 15.0) and (cmo_vals[i-1] <= 15.0) and (C[i] > e50[i]) and (V[i] >= avg_vol[i] * 1.25):
            sig["cmo_accel_break"][i] = True
            
        # 5. kaufman_er_trend
        if (er_vals[i] >= 0.42) and (C[i] > H[i-14:i].max()) and (C[i-1] <= H[i-14:i].max()) and (V[i] >= avg_vol[i] * 1.2):
            sig["kaufman_er_trend"][i] = True
            
        # 6. multi_factor_alpha
        if (alpha_vals[i] >= 1.80) and (C[i] > e50[i]) and (rsi_vals[i] <= 65.0):
            sig["multi_factor_alpha"][i] = True
            
        # 7. vp_vah_breakout
        if not np.isnan(vah_arr[i-1]) and (C[i] > vah_arr[i-1]) and (C[i-1] <= vah_arr[i-1]) and (V[i] >= avg_vol[i] * 1.2):
            sig["vp_vah_breakout"][i] = True
            
        # 8. vfi_zero_break
        if (vfi_vals[i] > 0.0) and (vfi_vals[i-1] <= 0.0) and (C[i] > e50[i]) and (V[i] >= avg_vol[i] * 1.15):
            sig["vfi_zero_break"][i] = True
            
        # 9. nw_kernel_envelope
        if (L[i-1] <= nw_lo[i-1]) and (C[i] > nw_lo[i]) and (rsi_vals[i] <= 42.0) and (C[i] > C[i-1]):
            sig["nw_kernel_envelope"][i] = True
            
        # 10. cluc_wick_bounce
        if (lower_wick[i-1] >= body[i-1] * 1.4) and (V[i-1] >= avg_vol[i-1] * 1.4) and (rsi_vals[i-1] <= 32.0) and (C[i] > C[i-1]):
            sig["cluc_wick_bounce"][i] = True
            
        # 11. cvd_absorption_wick
        delta_pos = (cvd_vals[i-1] > cvd_vals[i-2])
        if delta_pos and (lower_wick[i-1] >= body[i-1] * 1.2) and (V[i-1] >= avg_vol[i-1] * 1.3) and (C[i] > C[i-1]):
            sig["cvd_absorption_wick"][i] = True
            
        # 12. turtle_donchian
        highest_20 = H[i-20:i].max()
        if (C[i] > highest_20) and (C[i-1] <= highest_20) and (V[i] >= avg_vol[i] * 1.25) and (C[i] > e50[i]):
            sig["turtle_donchian"][i] = True
            
        # 13. ttm_squeeze_fired
        if fired[i] and (hist[i] > 0) and (hist[i] > hist[i-1]):
            sig["ttm_squeeze_fired"][i] = True
            
        # 14. vwap_mean_rev
        if (L[i-1] <= vwap_lower[i-1]) and (C[i] > vwap_lower[i]) and (rsi_vals[i] <= 35.0):
            sig["vwap_mean_rev"][i] = True
            
        # 15. kdj_pure_dip
        if (j_vals[i-1] <= 12.0) and (j_vals[i] > d_vals[i]) and (j_vals[i-1] <= d_vals[i-1]):
            sig["kdj_pure_dip"][i] = True

    def shift1(arr):
        z = np.zeros_like(arr, dtype=bool)
        z[1:] = arr[:-1]
        return z

    res = {k: shift1(v) for k, v in sig.items()}
    rnd = np.zeros(n, dtype=bool)
    rnd[::15] = True
    res["__RASTGELE__"] = shift1(rnd)
    for k in res:
        res[k][:45] = False
    return res

def run_30d_backtest():
    print("\n" + "=" * 102)
    print(" === 30 GÜNLÜK GERİYE DÖNÜK SPOT VECTORBT BACKTESTİ (15 CANLI STRATEJİ) ===")
    print(" Periyot: Son 30 Gün (H1 Barlar) | 40 Aktif Likit Binance Spot Coini")
    print(" Net Komisyon: %0.15 Round-Trip Spot | Lookahead Bias: 0 (shift=1)")
    print("=" * 102)
    
    t0 = time.time()
    # Son tam 30 gün verisi çek
    data = asyncio.run(load_candles(symbols=40, days=30, timeframe="1h"))
    total_bars = sum(len(d["C"]) for d in data.values())
    print(f"Yüklenen Aktif Coin: {len(data)} sembol, Toplam {total_bars:,} bar ({time.time()-t0:.1f}s)")
    
    fee = 0.15
    agg = defaultdict(lambda: defaultdict(lambda: {"trail": None, "tpsl": None}))
    
    for sym, d in data.items():
        O, H, L, C, V = d["O"], d["H"], d["L"], d["C"], d["V"]
        signals = generate_all_15_signals(O, H, L, C, V)
        for name, entries in signals.items():
            if not np.any(entries):
                continue
            r_trail = evaluate_dynamic_trailing(C, H, L, entries, fee_pct=fee)
            if r_trail:
                agg[name][sym]["trail"] = r_trail
            r_tpsl = evaluate_vbt_fixed(C, entries, tp_pct=3.5, sl_pct=1.8, fee_pct=fee)
            if r_tpsl:
                agg[name][sym]["tpsl"] = r_tpsl

    def combine_metrics(name, mode):
        vals = [v[mode] for v in agg[name].values() if v.get(mode)]
        if not vals:
            return None
        n = sum(x["n"] for x in vals)
        if n == 0:
            return None
        wins = sum(x["wr"] / 100.0 * x["n"] for x in vals)
        avg_ret = sum(x["avg_ret_pct"] * x["n"] for x in vals) / n
        sum_ret = sum(x["sum_ret_pct"] for x in vals)
        coins_pos = sum(1 for x in vals if x["avg_ret_pct"] > 0)
        coins_tot = len(vals)
        valid_pfs = [x["pf"] for x in vals if 0 < x["pf"] < 50.0]
        pf = float(np.mean(valid_pfs)) if valid_pfs else 0.0
        return {
            "n": n,
            "wr": wins / n * 100.0,
            "pf": pf,
            "avg_ret": avg_ret,
            "sum_ret": sum_ret,
            "coins_pos": coins_pos,
            "coins_tot": coins_tot
        }

    for mode, title in [("trail", "Dinamik Takipci Cikis Modeli (ATR Trailing)"), ("tpsl", "Sabit TP/SL (%3.5 / %1.8) Modeli")]:
        print(f"\n" + "-" * 102)
        print(f"--- MODEL: {title} ---")
        print(f"{'Strateji Kodu':<25} {'Islem (n)':<10} {'WinRate':<9} {'ProfitFac':<10} {'Ort Net%':<10} {'Kum. Net%':<11} {'Pozitif Coin':<13} {'Durum'}")
        print("-" * 102)
        
        rows = []
        for name in agg:
            m = combine_metrics(name, mode)
            if not m:
                continue
            is_winner = (m["pf"] >= 1.50 and m["avg_ret"] > 0)
            status = "[KAZANCLI] **" if is_winner else ("[POZITIF]" if m["avg_ret"] > 0 else "[ZARAR]")
            if name == "__RASTGELE__":
                status = "[REFERANS]"
            rows.append((name, m["n"], m["wr"], m["pf"], m["avg_ret"], m["sum_ret"], f"{m['coins_pos']}/{m['coins_tot']}", status))
            
        rows.sort(key=lambda x: x[3], reverse=True)
        for r in rows:
            print(f"{r[0]:<25} {r[1]:<10} %{r[2]:<8.1f} {r[3]:<10.2f} %{r[4]:<9.3f} %{r[5]:<10.1f} {r[6]:<13} {r[7]}")

if __name__ == "__main__":
    run_30d_backtest()
