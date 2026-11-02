"""Multi-Timeframe (MTF) Confluence VectorBT Test Laboratuvarı.

Araştırma Hipotezi:
Tek başına 5m ve 15m barlarda komisyona yenilen göstergeler,
1 Saatlik (1h) Makro Trend (1h EMA200, 1h SuperTrend, 1h ADX) filtresiyle
birleştirildiğinde gürültüden arınarak yüksek kârlılığa ulaşıyor mu?

Modeller:
1. mtf_cluc_h1_trend: 5m/15m Kapitülasyon İğnesi + 1h Fiyat > EMA100
2. mtf_vwap_h1_bull: 5m/15m VWAP Bant Dip + 1h SuperTrend Boğa
3. mtf_kdj_h1_macro: 5m KDJ Saf Dip (J<=12) + 1h EMA50 > EMA200
4. mtf_donchian_pullback: 1h Donchian Yükseliş Trendinde 15m RSI<=35 Geri Çekilmesi
5. benchmark_single_tf: Tek zaman dilimli referans
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
    _ema, _atr, _rsi, _adx, _kdj,
    evaluate_vbt_fixed,
    evaluate_dynamic_trailing,
)

# En aktif 25 Binance Spot USDT coini
ACTIVE_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
    "NEARUSDT", "DOGEUSDT", "AVAXUSDT", "SUIUSDT", "ADAUSDT",
    "ARBUSDT", "AAVEUSDT", "LINKUSDT", "HBARUSDT", "FETUSDT",
    "INJUSDT", "LTCUSDT", "DOTUSDT", "APTUSDT", "OPUSDT",
    "FILUSDT", "NEARUSDT", "DASHUSDT", "CRVUSDT", "ALGOUSDT"
]

async def load_5m_and_build_h1(symbols: list[str], days: int = 45):
    import asyncpg
    url = os.environ.get("DATABASE_URL") or "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"
    conn = await asyncpg.connect(url)
    cutoff = int((time.time() - days * 86400) * 1000)
    
    query = """
        SELECT symbol, open_time, open, high, low, close, volume
        FROM historical_candles
        WHERE timeframe = '5m' AND symbol = ANY($1) AND open_time >= $2
        ORDER BY symbol, open_time ASC
    """
    rows = await conn.fetch(query, symbols, cutoff)
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
        
    paired_data = {}
    for sym, d in raw.items():
        if len(d["C"]) < 1500:
            continue
        df5 = pd.DataFrame({
            "open": d["O"], "high": d["H"], "low": d["L"], "close": d["C"], "volume": d["V"]
        }, index=pd.to_datetime(d["T"], unit="ms"))
        
        # 1H Resample (12 bar)
        df1h = df5.resample("1h").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()
        
        if len(df1h) < 100:
            continue
            
        # 1H İndikatörlerini hesapla (Lookahead önlemek için 1H göstergelerini 1 saat kaydırarak 5m'e map et)
        c1h = df1h["close"].to_numpy()
        h1h = df1h["high"].to_numpy()
        l1h = df1h["low"].to_numpy()
        
        e50_1h = _ema(c1h, 50)
        e100_1h = _ema(c1h, 100)
        e200_1h = _ema(c1h, 200)
        
        # SuperTrend 1H
        atr_1h = _atr(h1h, l1h, c1h, 10)
        hl2_1h = (h1h + l1h) / 2.0
        up_1h = hl2_1h + 3.0 * atr_1h
        dn_1h = hl2_1h - 3.0 * atr_1h
        st_bull_1h = np.ones(len(c1h), dtype=bool)
        for i in range(1, len(c1h)):
            if c1h[i] > up_1h[i-1]:
                st_bull_1h[i] = True
            elif c1h[i] < dn_1h[i-1]:
                st_bull_1h[i] = False
            else:
                st_bull_1h[i] = st_bull_1h[i-1]
                
        df1h["e50"] = e50_1h
        df1h["e100"] = e100_1h
        df1h["e200"] = e200_1h
        df1h["st_bull"] = st_bull_1h
        
        # 1H verisini 1 bar kaydır (i barının kapanışı bilinmeden i+1'e bakılamaz)
        df1h_shifted = df1h[["e50", "e100", "e200", "st_bull"]].shift(1)
        
        # 5m tablosuna geriye doğru forward-fill ile eşleştir
        merged = df5.join(df1h_shifted, how="left").ffill().dropna()
        
        paired_data[sym] = {
            "df": merged,
            "H": merged["high"].to_numpy(),
            "L": merged["low"].to_numpy(),
            "C": merged["close"].to_numpy(),
            "V": merged["volume"].to_numpy(),
            "T": (merged.index.astype("int64") // 10**6).to_numpy(),
            "h1_e50": merged["e50"].to_numpy(),
            "h1_e100": merged["e100"].to_numpy(),
            "h1_e200": merged["e200"].to_numpy(),
            "h1_st_bull": merged["st_bull"].to_numpy(dtype=bool),
        }
    return paired_data

def generate_mtf_signals(d):
    H, L, C, V = d["H"], d["L"], d["C"], d["V"]
    h1_e50 = d["h1_e50"]
    h1_e100 = d["h1_e100"]
    h1_e200 = d["h1_e200"]
    h1_st_bull = d["h1_st_bull"]
    n = len(C)
    
    # 5m İndikatörleri
    rsi5 = _rsi(C, 14)
    e50_5 = _ema(C, 50)
    
    # VWAP 5m
    tp = (H + L + C) / 3.0
    cum_vol_price = np.cumsum(tp * V)
    cum_vol = np.cumsum(V)
    vwap = np.where(cum_vol > 0, cum_vol_price / cum_vol, C)
    diff = C - vwap
    rolling_std = np.zeros(n)
    for i in range(30, n):
        rolling_std[i] = diff[i-30:i].std()
    lower_vwap = vwap - 1.8 * rolling_std
    
    # KDJ 5m
    k, d_kdj, j_arr = _kdj(H, L, C, 9, 3)
    
    avg_vol = np.zeros(n)
    for i in range(20, n):
        avg_vol[i] = V[i-20:i].mean()
        
    sig_cluc_mtf = np.zeros(n, dtype=bool)
    sig_vwap_mtf = np.zeros(n, dtype=bool)
    sig_kdj_mtf = np.zeros(n, dtype=bool)
    sig_donchian_pullback = np.zeros(n, dtype=bool)
    sig_raw_cluc = np.zeros(n, dtype=bool)
    
    for i in range(35, n):
        candle_body = abs(C[i] - (H[i] + L[i]) / 2.0)
        lower_wick = min(C[i], C[i-1]) - L[i]
        wick_rejection = (lower_wick >= candle_body * 1.4) and (L[i] < e50_5[i] * 0.985)
        vol_climax = V[i] >= avg_vol[i] * 1.4 if avg_vol[i] > 0 else False
        oversold = rsi5[i] <= 32.0
        green_candle = C[i] > L[i] + lower_wick * 0.4
        is_cluc = wick_rejection and vol_climax and oversold and green_candle
        
        # 1. Ham Cluc (Referans)
        if is_cluc:
            sig_raw_cluc[i] = True
            
        # 2. MTF Cluc (1h Trend Onaylı: Fiyat > 1h EMA100 ve 1h SuperTrend Boğa)
        h1_macro_bull = (C[i] > h1_e100[i]) and h1_st_bull[i]
        if is_cluc and h1_macro_bull:
            sig_cluc_mtf[i] = True
            
        # 3. MTF VWAP Dip (5m VWAP Alt Bant + 1h SuperTrend Boğa)
        band_bounce = (L[i-1] <= lower_vwap[i-1]) and (C[i] > lower_vwap[i])
        rsi_dip = (rsi5[i-1] <= 35.0) and (rsi5[i] > rsi5[i-1])
        if band_bounce and rsi_dip and h1_macro_bull:
            sig_vwap_mtf[i] = True
            
        # 4. MTF KDJ Dip (J<=12 + 1h EMA50 > EMA200 Altın Kesişim)
        j_dip = (j_arr[i] > d_kdj[i]) and (j_arr[i-1] <= d_kdj[i-1]) and (j_arr[i] <= 12.0)
        h1_golden_cross = (h1_e50[i] >= h1_e200[i] * 0.99)
        if j_dip and h1_golden_cross:
            sig_kdj_mtf[i] = True
            
        # 5. Donchian MTF Pullback (1h Boğa Trendinde 5m RSI<=30 İndirim Yakalama)
        if h1_st_bull[i] and (C[i] > h1_e50[i]) and (rsi5[i] <= 28.0) and (C[i] > C[i-1]):
            sig_donchian_pullback[i] = True

    def shift1(arr):
        z = np.zeros_like(arr, dtype=bool)
        z[1:] = arr[:-1]
        return z

    signals = {
        "raw_cluc_5m": shift1(sig_raw_cluc),
        "mtf_cluc_h1_trend": shift1(sig_cluc_mtf),
        "mtf_vwap_h1_bull": shift1(sig_vwap_mtf),
        "mtf_kdj_h1_golden": shift1(sig_kdj_mtf),
        "mtf_donchian_pullback": shift1(sig_donchian_pullback),
    }
    for k in signals:
        signals[k][:100] = False
    return signals

def run_mtf_test():
    print("\n" + "=" * 90)
    print(" === MULTI-TIMEFRAME (MTF) CONFLUENCE VECTORBT ARASTIRMA LABORATUVARI ===")
    print(" Hipotez: 5m Girisleri 1H Makro Trend Filtresiyle Guclendirme (Net %0.15 Komisyon)")
    print("=" * 90)
    
    t0 = time.time()
    data = asyncio.run(load_5m_and_build_h1(ACTIVE_SYMBOLS, days=45))
    print(f"Yüklenen Veri: {len(data)} aktif coin, toplam {sum(len(d['C']) for d in data.values()):,} 5m bar ({time.time()-t0:.1f}s)")
    
    tp_pct, sl_pct, fee = 1.6, 0.9, 0.15
    agg = defaultdict(lambda: defaultdict(lambda: {"tp_sl": [], "trail": []}))
    
    for sym, d in data.items():
        C, H, L = d["C"], d["H"], d["L"]
        sigs = generate_mtf_signals(d)
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

    for mode, title in [("trail", "Dinamik Takipçi Çıkış"), ("tp_sl", f"Sabit TP/SL (%{tp_pct}/%{sl_pct})")]:
        print(f"\n--- {title} ---")
        print(f"{'Strateji':<26} {'İşlem (n)':<10} {'WinRate':<9} {'ProfitFac':<10} {'Ort Net%':<10} {'Pozitif Coin':<13} {'Durum'}")
        print("-" * 92)
        rows = []
        for name in agg:
            c = combine(name, mode)
            if not c:
                continue
            status = "KAZANÇLI" if (c["avg"] > 0 and c["pf"] >= 1.20) else "ZARAR"
            rows.append((c["avg"], name, c, status))
        for _, name, c, status in sorted(rows, key=lambda r: -r[0]):
            mark = " **" if c["avg"] > 0 else ""
            print(f"{name:<26} {c['n']:<10d} %{c['wr']:<7.1f} {c['pf']:<10.2f} %{c['avg']:<8.3f} {c['coins_pos']}/{c['coins_n']:<10d} [{status}]{mark}")

if __name__ == "__main__":
    run_mtf_test()
