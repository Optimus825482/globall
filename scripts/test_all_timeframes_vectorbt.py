"""Tüm Zaman Dilimleri (M1, M3, M5, M15, M30, M45, H1) İçin VectorBT Test Betiği.

Aktif ve yüksek hacimli Binance Spot USDT coinleri üzerinde:
- M1 ve M3: Binance Public API üzerinden en son 1.000'er bar
- M5, M15, M30, M45, H1: PostgreSQL historical_candles tablosundaki gerçek veriler ve resample
- Tüm testlerde net %0.15 round-trip komisyon düşülür.
- shift=1 kuralı ile lookahead bias sıfırdır.
"""
import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict
import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "backend"))
sys.path.insert(0, _ROOT)

import vectorbt as vbt
from scripts.test_github_youtube_vectorbt import (
    generate_all_signals,
    evaluate_vbt_fixed,
    evaluate_dynamic_trailing,
)

# En aktif, en likit ve yüksek hacimli ana coin listesi
ACTIVE_CORE_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
    "NEARUSDT", "DOGEUSDT", "AVAXUSDT", "SUIUSDT", "ADAUSDT",
    "ARBUSDT", "AAVEUSDT", "LINKUSDT", "HBARUSDT", "FETUSDT",
    "INJUSDT", "LTCUSDT", "DOTUSDT", "APTUSDT", "OPUSDT"
]

# Zaman dilimi TP/SL oranları
TF_CONFIG = {
    "1m":  {"tp": 0.8, "sl": 0.5, "freq": "1min", "label": "M1 (1 Dakika)"},
    "3m":  {"tp": 1.1, "sl": 0.7, "freq": "3min", "label": "M3 (3 Dakika)"},
    "5m":  {"tp": 1.5, "sl": 0.9, "freq": "5min", "label": "M5 (5 Dakika)"},
    "15m": {"tp": 2.2, "sl": 1.2, "freq": "15min", "label": "M15 (15 Dakika)"},
    "30m": {"tp": 2.8, "sl": 1.5, "freq": "30min", "label": "M30 (30 Dakika)"},
    "45m": {"tp": 3.2, "sl": 1.6, "freq": "45min", "label": "M45 (45 Dakika)"},
    "1h":  {"tp": 3.5, "sl": 1.8, "freq": "1h",    "label": "H1 (1 Saat)"},
}

def fetch_binance_klines_sync(symbol: str, interval: str, limit: int = 1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode())
            return {
                "T": [int(k[0]) for k in raw],
                "O": [float(k[1]) for k in raw],
                "H": [float(k[2]) for k in raw],
                "L": [float(k[3]) for k in raw],
                "C": [float(k[4]) for k in raw],
                "V": [float(k[5]) for k in raw],
            }
    except Exception as e:
        return None

async def load_candles_for_tf(timeframe: str, symbols: list[str], days: int = 45):
    # M1 ve M3: Doğrudan Binance Public API'den taze 1000 bar çek
    if timeframe in {"1m", "3m"}:
        print(f"[{timeframe.upper()}] Binance API'den {len(symbols)} aktif coin için taze 1.000 bar çekiliyor...")
        data = {}
        for sym in symbols:
            k = fetch_binance_klines_sync(sym, timeframe, limit=1000)
            if k and len(k["C"]) >= 200:
                data[sym] = k
        return data

    # M5, M15, M30, M45, H1: PostgreSQL'den 5m mumlarını çekip resample et
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
    
    raw_data = defaultdict(lambda: {"T": [], "O": [], "H": [], "L": [], "C": [], "V": []})
    for r in rows:
        sym = r["symbol"]
        raw_data[sym]["T"].append(int(r["open_time"]))
        raw_data[sym]["O"].append(float(r["open"]))
        raw_data[sym]["H"].append(float(r["high"]))
        raw_data[sym]["L"].append(float(r["low"]))
        raw_data[sym]["C"].append(float(r["close"]))
        raw_data[sym]["V"].append(float(r["volume"]))
        
    if timeframe == "5m":
        return {s: d for s, d in raw_data.items() if len(d["C"]) >= 500}
        
    resample_freq = TF_CONFIG[timeframe]["freq"]
    resampled_data = {}
    for sym, d in raw_data.items():
        if len(d["C"]) < 500:
            continue
        df = pd.DataFrame({
            "open": d["O"], "high": d["H"], "low": d["L"], "close": d["C"], "volume": d["V"]
        }, index=pd.to_datetime(d["T"], unit="ms"))
        
        agg_rules = {
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }
        res_df = df.resample(resample_freq).agg(agg_rules).dropna()
        if len(res_df) < 100:
            continue
        resampled_data[sym] = {
            "T": (res_df.index.astype("int64") // 10**6).tolist(),
            "H": res_df["high"].tolist(),
            "L": res_df["low"].tolist(),
            "C": res_df["close"].tolist(),
            "V": res_df["volume"].tolist(),
        }
    return resampled_data

def evaluate_timeframe(timeframe: str, symbols: list[str], days: int = 45, fee: float = 0.15):
    cfg = TF_CONFIG[timeframe]
    tp_pct = cfg["tp"]
    sl_pct = cfg["sl"]
    
    data = asyncio.run(load_candles_for_tf(timeframe, symbols, days))
    if not data:
        print(f"[{timeframe}] Veri yüklenemedi!")
        return None
        
    total_bars = sum(len(d["C"]) for d in data.values())
    print(f"\n==========================================================================================")
    print(f" {cfg['label']} TESTİ ({len(data)} Aktif Coin | Toplam {total_bars:,} Bar | TP %{tp_pct} / SL %{sl_pct})")
    print(f" Komisyon: %{fee} round-trip net kesintili")
    print(f"==========================================================================================")
    
    agg = defaultdict(lambda: defaultdict(lambda: {"tp_sl": [], "trail": []}))
    for sym, d in data.items():
        C = np.asarray(d["C"])
        H = np.asarray(d["H"])
        L = np.asarray(d["L"])
        V = np.asarray(d["V"])
        T = np.asarray(d["T"])
        sigs = generate_all_signals(H, L, C, V, T)
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
        return {
            "n": n, "wr": wins / n * 100.0, "pf": pf, "avg": avg,
            "coins_pos": coins_pos, "coins_n": coins_n
        }

    # Sonuç Tablosu
    results = {}
    for mode, title in [("trail", "Dinamik Takipçi"), ("tp_sl", f"Sabit TP/SL (%{tp_pct}/%{sl_pct})")]:
        print(f"\n--- {title} Modeli ---")
        print(f"{'Strateji':<22} {'İşlem (n)':<10} {'WinRate':<9} {'ProfitFac':<10} {'Ort Net%':<10} {'Pozitif Coin':<13} {'Durum'}")
        print("-" * 88)
        rows = []
        for name in agg:
            c = combine(name, mode)
            if not c:
                continue
            is_win = (c["avg"] > 0 and c["pf"] >= 1.20)
            status = "KAZANÇLI" if is_win else "ZARAR"
            rows.append((c["avg"], name, c, status))
            
        for _, name, c, status in sorted(rows, key=lambda r: -r[0]):
            mark = " **" if c["avg"] > 0 else ""
            print(f"{name:<22} {c['n']:<10d} %{c['wr']:<7.1f} {c['pf']:<10.2f} %{c['avg']:<8.3f} {c['coins_pos']}/{c['coins_n']:<10d} [{status}]{mark}")
            results.setdefault(mode, {})[name] = c
    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=45)
    parser.add_argument("--fee", type=float, default=0.15)
    args = parser.parse_args()
    
    timeframes = ["1m", "3m", "5m", "15m", "30m", "45m", "1h"]
    all_summary = {}
    
    print("\n" + "=" * 90)
    print(" === TUM ZAMAN DILIMLERI ICIN (M1, M3, M5, M15, M30, M45, H1) VECTORBT TEST LABORATUVARI ===")
    print(f" Hedef: {len(ACTIVE_CORE_SYMBOLS)} Aktif Coin | Maliyet: %{args.fee} net round-trip")
    print("=" * 90)
    
    for tf in timeframes:
        t0 = time.time()
        res = evaluate_timeframe(tf, ACTIVE_CORE_SYMBOLS, args.days, args.fee)
        all_summary[tf] = res
        print(f"[{tf.upper()}] Tamamlandı ({time.time()-t0:.1f}s)")
        
    print("\n" + "=" * 90)
    print(" TÜM ZAMAN DİLİMLERİ İÇİN GENEL ÖZET KARŞILAŞTIRMASI")
    print("=" * 90)
    print(f"{'Zaman Dilimi':<14} {'En İyi Strateji':<22} {'Model':<16} {'WinRate':<9} {'ProfitFac':<10} {'Ort Net%'}")
    print("-" * 88)
    for tf, res in all_summary.items():
        if not res:
            continue
        best_name = None
        best_mode = None
        best_avg = -999.0
        best_data = None
        for mode in ["trail", "tp_sl"]:
            for name, c in res.get(mode, {}).items():
                if name == "__RASTGELE__":
                    continue
                if c["avg"] > best_avg:
                    best_avg = c["avg"]
                    best_name = name
                    best_mode = mode
                    best_data = c
        if best_name and best_data:
            mode_lbl = "Takipçi" if best_mode == "trail" else "Sabit TP/SL"
            print(f"{tf.upper():<14} {best_name:<22} {mode_lbl:<16} %{best_data['wr']:<7.1f} {best_data['pf']:<10.2f} %{best_data['avg']:<8.3f}")

if __name__ == "__main__":
    main()
