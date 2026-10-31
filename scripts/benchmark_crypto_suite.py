import os
import sys
import time
import json
import pandas as pd
import numpy as np

# Ensure scripts dir is in path to import vectorbt_optimizer functions
sys.path.insert(0, os.path.dirname(__file__))
from vectorbt_optimizer import (
    load_candles_from_cache,
    optimize_smc_sweep_vbt,
    optimize_kombo_vbt,
    optimize_fisher_vbt,
    optimize_kdj_vbt,
    optimize_stc_vbt,
    optimize_supertrend_vbt,
)

CACHE_PATH = "outputs/crypto_candles_cache.json"
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]
STRATEGIES = [
    ("smc_sweep", optimize_smc_sweep_vbt),
    ("kombo", optimize_kombo_vbt),
    ("fisher", optimize_fisher_vbt),
    ("kdj", optimize_kdj_vbt),
    ("stc", optimize_stc_vbt),
]

summary_rows = []

print("================================================================================")
print("       KRIPTO VARLIK ÇOKLU-STRATEJİ & GÖSTERGE VEKTÖRÜZE BENCHMARK MOTORU       ")
print("================================================================================")
print(f"Hedef Coinler: {', '.join(COINS)}")
print(f"Veri Kaynağı:  {CACHE_PATH} (15m Barlar)\n")

for coin in COINS:
    print(f"\n>>> [{coin}] Analiz Ediliyor...")
    try:
        df = load_candles_from_cache(CACHE_PATH, coin)
    except Exception as exc:
        print(f"Hata: {coin} yuklenemedi: {exc}")
        continue

    best_for_coin = None

    for strat_name, strat_func in STRATEGIES:
        try:
            res = strat_func(df, top_n=3)
            top_results = res.get("top_results", [])
            if not top_results:
                continue
            best = top_results[0]
            param_str = " | ".join(f"{k}:{v}" for k, v in best["parameters"].items())
            
            row = {
                "coin": coin,
                "strategy": strat_name.upper(),
                "display_name": res.get("strategy", strat_name),
                "total_return": best["total_return_pct"],
                "sharpe": best["sharpe_ratio"],
                "max_dd": best["max_drawdown_pct"],
                "win_rate": best["win_rate_pct"],
                "trade_count": best["trade_count"],
                "best_params": param_str,
            }
            summary_rows.append(row)
            
            print(f"  {strat_name.upper():<12} -> Kâr: %{row['total_return']:<6} | Sharpe: {row['sharpe']:<6} | MaxDD: %{row['max_dd']:<6} | İsabet: %{row['win_rate']:<5} | İşlem: {row['trade_count']}")
        except Exception as exc:
            print(f"  {strat_name.upper()} calistirilirken hata: {exc}")

# Save results
out_report = "outputs/crypto_multi_coin_benchmark.json"
with open(out_report, "w", encoding="utf-8") as f:
    json.dump(summary_rows, f, indent=2, ensure_ascii=False)

print("\n" + "=" * 90)
print(f"{'Coin':<10} {'Strateji':<14} {'Toplam Kâr':<12} {'Sharpe':<8} {'MaxDD':<8} {'İsabet':<8} {'İşlem':<6}")
print("-" * 90)
summary_rows.sort(key=lambda x: (x["sharpe"], x["total_return"]), reverse=True)
for r in summary_rows:
    print(f"{r['coin']:<10} {r['strategy']:<14} %{r['total_return']:<11} {r['sharpe']:<8} %{r['max_dd']:<7} %{r['win_rate']:<7} {r['trade_count']:<6}")

print("\nBenchmark tamamlandı! Sonuçlar outputs/crypto_multi_coin_benchmark.json dosyasına yazıldı.")
