import os
import sys
import time
import json
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from vectorbt_optimizer import (
    load_candles_from_cache,
    optimize_smc_sweep_vbt,
    optimize_fisher_vbt,
    optimize_kdj_vbt,
    optimize_hybrid_crypto_vbt,
    optimize_kombo_vbt,
)

COINS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT",
    "DOGEUSDT", "XRPUSDT", "LINKUSDT", "NEARUSDT", "SUIUSDT"
]

STRATEGIES = [
    ("hybrid", optimize_hybrid_crypto_vbt),
    ("smc_sweep", optimize_smc_sweep_vbt),
    ("fisher", optimize_fisher_vbt),
    ("kdj", optimize_kdj_vbt),
    ("kombo", optimize_kombo_vbt),
]

all_results = []

for tf, cache_file in [("15m", "outputs/crypto_cache_15m.json"), ("5m", "outputs/crypto_cache_5m.json")]:
    print(f"\n================================================================================")
    print(f"       [{tf.upper()}] 10 KRIPTO VARLIK ÇOKLU-GÖSTERGE VEKTÖRÜZE BENCHMARK       ")
    print(f"================================================================================")
    
    for coin in COINS:
        try:
            df = load_candles_from_cache(cache_file, coin)
        except Exception as exc:
            continue
            
        for s_name, s_func in STRATEGIES:
            try:
                res = s_func(df, top_n=1)
                top = res.get("top_results", [])
                if not top:
                    continue
                best = top[0]
                p_str = " | ".join(f"{k}:{v}" for k, v in best["parameters"].items())
                row = {
                    "tf": tf,
                    "coin": coin,
                    "strategy": s_name.upper(),
                    "total_return": best["total_return_pct"],
                    "sharpe": best["sharpe_ratio"],
                    "max_dd": best["max_drawdown_pct"],
                    "win_rate": best["win_rate_pct"],
                    "trades": best["trade_count"],
                    "best_params": p_str,
                }
                all_results.append(row)
                if best["sharpe_ratio"] > 1.0:
                    print(f"  🔥 [{tf}] {coin:<8} | {s_name.upper():<10} -> Kâr: +%{best['total_return_pct']:<5} | Sharpe: {best['sharpe_ratio']:<6} | WR: %{best['win_rate_pct']:<5} | İşlem: {best['trade_count']}")
            except Exception as exc:
                pass

# Save full results
with open("outputs/crypto_10_coins_full_benchmark.json", "w", encoding="utf-8") as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)

print("\n\n==========================================================================================")
print("                    🏆 10 KRİPTO VARLIKTA EN YÜKSEK SHARPE KAZANANLARI                    ")
print("==========================================================================================")
header = f"{'TF':<5} {'Coin':<9} {'Strateji':<10} {'Toplam Kâr':<12} {'Sharpe':<8} {'MaxDD':<8} {'İsabet':<8} {'İşlem':<6} {'En İyi Parametreler'}"
print(header)
print("-" * 115)

# Sort by Sharpe
winners = [r for r in all_results if r["sharpe"] > 0]
winners.sort(key=lambda x: (x["sharpe"], x["total_return"]), reverse=True)

for w in winners[:20]:
    tf = w["tf"]
    c = w["coin"].replace("USDT", "")
    s = w["strategy"]
    k = w["total_return"]
    sh = w["sharpe"]
    dd = w["max_dd"]
    wr = w["win_rate"]
    t = w["trades"]
    p = w["best_params"]
    print(f"{tf:<5} {c:<9} {s:<10} %{k:<11} {sh:<8} %{dd:<7} %{wr:<7} {t:<6} {p[:45]}")

print("\nRapor kaydedildi: outputs/crypto_10_coins_full_benchmark.json")
