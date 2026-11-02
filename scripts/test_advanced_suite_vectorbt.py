"""İleri Düzey Spot Kripto Stratejileri Araştırma ve VectorBT Laboratuvarı.

İncelenen 3 İleri Düzey Mimari:
1. Volume Profile (Hacim Profili) Value Area Modelleri:
   - vp_val_bounce: Fiyatın VAL (Value Area Low - %70 Hacim Alt Sınırı) altına sarkıp içeri dönmesi
   - vp_vah_breakout: Fiyatın VAH (Value Area High) üzerine hacimli kırılımı
2. Keltner & Bollinger Volatilite Sıkışması (TTM Squeeze 2.0):
   - ttm_squeeze_fired: BB(20, 2.0) Keltner(20, 1.5 ATR) içine sıkışıp yukarı patlaması + Momentum
   - ttm_squeeze_pullback: Sıkışma patlaması sonrası EMA20'ye dokunup sekme
3. CVD & Hacim Emme (Order Flow Absorption):
   - cvd_bull_divergence: Fiyat yeni dip yaparken kümülatif hacim deltasının yükselmesi (Akıllı Para Alımı)
   - cvd_absorption_wick: Hacimli barda alıcıların satış baskısını tamamen emmesi (Delta > 0 + Alt Fitil)
4. Referans:
   - __RASTGELE__: Şans faktörü kontrolü

Veri ve Maliyet:
- 40 Aktif Binance Spot USDT Coini
- 1 Saatlik (H1) ve 15 Dakikalık (15m) Periyotlar
- %0.15 Round-Trip Net Komisyon Kesintili (BNB indirimli gerçek spot)
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

# ─── 1. Volume Profile (Hacim Profili) Hesaplayıcı ───────────────────────────
def calculate_rolling_vp(H, L, C, V, window=24, bins=30, va_pct=0.70):
    n = len(C)
    poc_arr = np.full(n, np.nan)
    val_arr = np.full(n, np.nan)
    vah_arr = np.full(n, np.nan)
    
    for i in range(window, n):
        hw = H[i-window:i]
        lw = L[i-window:i]
        cw = C[i-window:i]
        vw = V[i-window:i]
        
        hi = hw.max()
        lo = lw.min()
        if hi <= lo or vw.sum() <= 0:
            continue
            
        price_bins = np.linspace(lo, hi, bins + 1)
        # Mumların tipik fiyatlarını binlere ayır
        typical_p = (hw + lw + cw) / 3.0
        bin_idx = np.digitize(typical_p, price_bins) - 1
        bin_idx = np.clip(bin_idx, 0, bins - 1)
        
        vol_per_bin = np.zeros(bins)
        for b, v_val in zip(bin_idx, vw):
            vol_per_bin[b] += v_val
            
        poc_b = int(np.argmax(vol_per_bin))
        poc_arr[i] = (price_bins[poc_b] + price_bins[poc_b + 1]) / 2.0
        
        target_vol = vol_per_bin.sum() * va_pct
        cur_vol = vol_per_bin[poc_b]
        low_b, high_b = poc_b, poc_b
        
        while cur_vol < target_vol:
            expanded = False
            next_up = high_b + 1
            next_down = low_b - 1
            
            up_vol = vol_per_bin[next_up] if next_up < bins else -1
            down_vol = vol_per_bin[next_down] if next_down >= 0 else -1
            
            if up_vol >= down_vol and up_vol >= 0:
                cur_vol += up_vol
                high_b = next_up
                expanded = True
            elif down_vol >= 0:
                cur_vol += down_vol
                low_b = next_down
                expanded = True
            if not expanded:
                break
                
        val_arr[i] = price_bins[low_b]
        vah_arr[i] = price_bins[high_b + 1]
        
    return poc_arr, val_arr, vah_arr

# ─── 2. TTM Squeeze 2.0 Hesaplayıcı ──────────────────────────────────────────
def calculate_ttm_squeeze(H, L, C, bb_p=20, bb_mult=2.0, kc_p=20, kc_mult=1.5):
    n = len(C)
    squeeze_on = np.zeros(n, dtype=bool)
    squeeze_fired = np.zeros(n, dtype=bool)
    momentum = np.zeros(n)
    
    atr_vals = _atr(H, L, C, kc_p)
    e20 = _ema(C, bb_p)
    
    # Doğrusal regresyon momentumu (20 bar)
    x = np.arange(20, dtype=float)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()
    
    for i in range(max(bb_p, kc_p), n):
        cw = C[i-bb_p+1:i+1]
        mid = cw.mean()
        sd = cw.std()
        upper_bb = mid + bb_mult * sd
        lower_bb = mid - bb_mult * sd
        
        kc_mid = e20[i]
        kc_range = atr_vals[i] * kc_mult
        upper_kc = kc_mid + kc_range
        lower_kc = kc_mid - kc_range
        
        # Sıkışma: Bollinger bantları Keltner kanalının İÇİNDE
        is_in_squeeze = (lower_bb > lower_kc) and (upper_bb < upper_kc)
        squeeze_on[i] = is_in_squeeze
        
        # Sıkışmadan çıkış (Fired): Önceki bar sıkışmadaydı, bu bar açıldı
        if (not is_in_squeeze) and squeeze_on[i-1]:
            squeeze_fired[i] = True
            
        # Momentum: (Close - (Donchian Mid + SMA20)/2) regresyonu
        donch_mid = (H[i-20+1:i+1].max() + L[i-20+1:i+1].min()) / 2.0
        val = cw - (donch_mid + mid) / 2.0
        momentum[i] = ((x - x_mean) * (val - val.mean())).sum() / denom if denom > 0 else 0.0
        
    return squeeze_on, squeeze_fired, momentum

# ─── 3. CVD & Volume Delta Proxy Hesaplayıcı ────────────────────────────────
def calculate_cvd_metrics(H, L, C, V):
    n = len(C)
    # Intrabar Alıcı-Satıcı Hacim Deltası:
    # ((Close - Low) - (High - Close)) / (High - Low) * Volume
    hl = np.maximum(H - L, 1e-9)
    delta_ratio = ((C - L) - (H - C)) / hl
    bar_delta = delta_ratio * V
    cvd = np.cumsum(bar_delta)
    return bar_delta, cvd

# ─── Sinyal Motoru ───────────────────────────────────────────────────────────
def generate_advanced_signals(H, L, C, V):
    H = np.asarray(H, dtype=float)
    L = np.asarray(L, dtype=float)
    C = np.asarray(C, dtype=float)
    V = np.asarray(V, dtype=float)
    n = len(C)
    
    # 1. Volume Profile (24 bar pencere)
    poc, val, vah = calculate_rolling_vp(H, L, C, V, window=24, bins=25)
    
    # 2. TTM Squeeze
    squeeze_on, squeeze_fired, ttm_mom = calculate_ttm_squeeze(H, L, C)
    
    # 3. CVD
    bar_delta, cvd = calculate_cvd_metrics(H, L, C, V)
    
    rsi_vals = _rsi(C, 14)
    e20 = _ema(C, 20)
    e50 = _ema(C, 50)
    
    avg_vol = np.zeros(n)
    for i in range(20, n):
        avg_vol[i] = V[i-20:i].mean()
        
    sig_vp_val = np.zeros(n, dtype=bool)
    sig_vp_vah = np.zeros(n, dtype=bool)
    sig_ttm_fired = np.zeros(n, dtype=bool)
    sig_ttm_pullback = np.zeros(n, dtype=bool)
    sig_cvd_div = np.zeros(n, dtype=bool)
    sig_cvd_absorb = np.zeros(n, dtype=bool)
    
    for i in range(26, n):
        # Model 1A: VP VAL Dip Sekmesi (Fiyat VAL altına iğne attı, içeri kapattı + RSI dip)
        if not np.isnan(val[i]):
            val_bounce = (L[i-1] <= val[i-1]) and (C[i] > val[i])
            if val_bounce and (rsi_vals[i] <= 40.0) and (C[i] > C[i-1]):
                sig_vp_val[i] = True
                
        # Model 1B: VP VAH Hacimli Kırılımı (Fiyat VAH üstüne çıktı + Hacim desteği)
        if not np.isnan(vah[i]):
            vah_break = (C[i] > vah[i]) and (C[i-1] <= vah[i-1])
            if vah_break and (V[i] >= avg_vol[i] * 1.25) and (C[i] > e50[i]):
                sig_vp_vah[i] = True
                
        # Model 2A: TTM Squeeze Fired (Sıkışma patladı + Pozitif Momentum)
        if squeeze_fired[i] and (ttm_mom[i] > 0) and (ttm_mom[i] > ttm_mom[i-1]) and (C[i] > e20[i]):
            sig_ttm_fired[i] = True
            
        # Model 2B: TTM Squeeze Pullback (Momentum pozitifken EMA20'ye dokunup sekme)
        near_e20 = (abs(L[i] - e20[i]) / max(e20[i], 1e-9)) <= 0.008
        if (ttm_mom[i] > 0) and near_e20 and (C[i] > e20[i]) and (not squeeze_on[i]):
            sig_ttm_pullback[i] = True
            
        # Model 3A: CVD Uyumsuzluğu (Fiyat 10 barın en düşüğünü test ederken CVD yükseliyor)
        lowest_10_c = C[i-10:i].min()
        lowest_10_cvd = cvd[i-10:i].min()
        if (C[i] <= lowest_10_c * 1.005) and (cvd[i] > lowest_10_cvd * 1.02) and (C[i] > L[i]):
            sig_cvd_div[i] = True
            
        # Model 3B: CVD Emme İğnesi (Aşağı itilen barda bar_delta pozitif + Uzun alt fitil)
        candle_body = abs(C[i] - (H[i] + L[i]) / 2.0)
        lower_wick = min(C[i], C[i-1]) - L[i]
        if (lower_wick >= candle_body * 1.3) and (bar_delta[i] > 0) and (V[i] >= avg_vol[i] * 1.3) and (rsi_vals[i] <= 36.0):
            sig_cvd_absorb[i] = True

    def shift1(arr):
        z = np.zeros_like(arr, dtype=bool)
        z[1:] = arr[:-1]
        return z

    signals = {
        "vp_val_bounce": shift1(sig_vp_val),
        "vp_vah_breakout": shift1(sig_vp_vah),
        "ttm_squeeze_fired": shift1(sig_ttm_fired),
        "ttm_squeeze_pullback": shift1(sig_ttm_pullback),
        "cvd_bull_divergence": shift1(sig_cvd_div),
        "cvd_absorption_wick": shift1(sig_cvd_absorb),
    }
    
    rnd = np.zeros(n, dtype=bool)
    rnd[::15] = True
    signals["__RASTGELE__"] = shift1(rnd)
    
    for k in signals:
        signals[k][:35] = False
    return signals

# ─── Veri Yükleyici ──────────────────────────────────────────────────────────
async def load_candles(symbols: int, days: int, timeframe: str = "1h", min_vol: float = 10000.0):
    import asyncpg
    url = os.environ.get("DATABASE_URL") or "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"
    conn = await asyncpg.connect(url)
    cutoff = int((time.time() - days * 86400) * 1000)
    
    rank_query = """
        SELECT symbol, AVG(quote_volume) as avg_quote, COUNT(*) as cnt
        FROM historical_candles
        WHERE timeframe = '5m' AND symbol LIKE '%USDT' AND open_time >= $1
        GROUP BY symbol
        HAVING AVG(quote_volume) >= $2 AND COUNT(*) >= 2000
        ORDER BY AVG(quote_volume) DESC
        LIMIT $3
    """
    ranked_rows = await conn.fetch(rank_query, cutoff, min_vol, symbols)
    active_symbols = [r["symbol"] for r in ranked_rows]
    
    data_query = """
        SELECT symbol, open_time, open, high, low, close, volume
        FROM historical_candles
        WHERE timeframe = '5m' AND symbol = ANY($1) AND open_time >= $2
        ORDER BY symbol, open_time ASC
    """
    rows = await conn.fetch(data_query, active_symbols, cutoff)
    await conn.close()
    
    raw = defaultdict(lambda: {"T": [], "O": [], "H": [], "L": [], "C": [], "V": []})
    for r in rows:
        sym = r["symbol"]
        raw[sym]["T"].append(int(r["open_time"]))
        raw[sym]["O"].append(float(r["open"]))
        raw[sym]["H"].append(float(r["high"]))
        raw[sym]["L"].append(float(r["low"]))
        raw[sym]["C"].append(float(r["close"]))
        raw[sym]["V"].append(float(r["volume"]))
        
    freq = "1h" if timeframe == "1h" else "15min"
    resampled = {}
    for sym, d in raw.items():
        if len(d["C"]) < 500:
            continue
        df = pd.DataFrame({
            "open": d["O"], "high": d["H"], "low": d["L"], "close": d["C"], "volume": d["V"]
        }, index=pd.to_datetime(d["T"], unit="ms"))
        res_df = df.resample(freq).agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()
        if len(res_df) < 100:
            continue
        resampled[sym] = {
            "O": res_df["open"].to_numpy(),
            "H": res_df["high"].to_numpy(),
            "L": res_df["low"].to_numpy(),
            "C": res_df["close"].to_numpy(),
            "V": res_df["volume"].to_numpy(),
        }
    return resampled

# ─── Ana Yürütme ─────────────────────────────────────────────────────────────
def run_suite(timeframe="1h", symbols=40, days=45, fee=0.15):
    print("\n" + "=" * 94)
    print(f" === ILERI DUZEY SPOT STRATEJILERI TEST LABORATUVARI ({timeframe.upper()} | {symbols} Aktif Coin) ===")
    print(f" 1. Volume Profile (VAL/VAH)  2. TTM Squeeze 2.0  3. CVD Order Flow Absorption")
    print(f" Maliyet: %{fee} net round-trip komisyon | lookahead=0 (shift=1)")
    print("=" * 94)
    
    t0 = time.time()
    data = asyncio.run(load_candles(symbols, days, timeframe))
    print(f"Yuklenen Aktif Coin: {len(data)} sembol, Toplam {sum(len(d['C']) for d in data.values()):,} bar ({time.time()-t0:.1f}s)")
    
    tp_pct = 3.5 if timeframe == "1h" else 2.2
    sl_pct = 1.8 if timeframe == "1h" else 1.2
    
    agg = defaultdict(lambda: defaultdict(lambda: {"tp_sl": [], "trail": []}))
    for sym, d in data.items():
        H, L, C, V = d["H"], d["L"], d["C"], d["V"]
        sigs = generate_advanced_signals(H, L, C, V)
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
    run_suite("1h", symbols=40, days=45, fee=0.15)
    run_suite("15m", symbols=40, days=45, fee=0.15)
