"""
Kripto Varlıklar İçin Çoklu Strateji Tarama ve Karşılaştırma Matrisi
10 Farklı VectorBT Stratejisini Kripto Varlıklar üzerinde test eder ve en yüksek Sharpe/Kâr oranlarını raporlar.
"""
import sys
import json
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.vectorbt_optimizer import (
    load_candles_from_cache,
    optimize_btc_master_vbt,
    optimize_smc_sweep_vbt,
    optimize_kdj_vbt,
    optimize_supertrend_vbt,
    optimize_stochrsi_vbt,
    optimize_tv_ultimate_vbt,
    optimize_squeeze_vbt,
    optimize_hybrid_crypto_vbt,
    optimize_fvg_vbt,
    optimize_fisher_vbt,
    optimize_kombo_vbt,
)

STRATEGIES = [
    ("SMC_SWEEP", optimize_smc_sweep_vbt),
    ("KDJ", optimize_kdj_vbt),
    ("BTC_MASTER", optimize_btc_master_vbt),
    ("SUPERTREND", optimize_supertrend_vbt),
    ("STOCHRSI", optimize_stochrsi_vbt),
    ("TV_ULTIMATE", optimize_tv_ultimate_vbt),
    ("SQUEEZE", optimize_squeeze_vbt),
    ("HYBRID", optimize_hybrid_crypto_vbt),
    ("FVG", optimize_fvg_vbt),
    ("FISHER", optimize_fisher_vbt),
]

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOGEUSDT", "NEARUSDT"]
CACHE_PATH = "outputs/crypto_cache_5m.json"

print("==========================================================================")
print("     KRİPTO VARLIKLAR ÇOKLU STRATEJİ VE PERFORMANS TEST MATRİSİ           ")
print("==========================================================================")
print(f"Kaynak Veri: {CACHE_PATH}")
print(f"Test Edilen Semboller: {', '.join(SYMBOLS)}")
print(f"Test Edilen Strateji Sayısı: {len(STRATEGIES)}")
print("--------------------------------------------------------------------------\n")

all_top_picks = []

for sym in SYMBOLS:
    print(f"\n🔍 [TARAMA] {sym} Analiz Ediliyor...")
    try:
        df = load_candles_from_cache(CACHE_PATH, sym)
    except Exception as exc:
        print(f"  ❌ {sym} veri yükleme hatası: {exc}")
        continue

    sym_best = []
    for strat_name, opt_func in STRATEGIES:
        try:
            t0 = time.time()
            res = opt_func(df, top_n=1)
            dur = time.time() - t0
            top_res = res.get("top_results", [])
            if top_res:
                b = top_res[0]
                p_str = " | ".join(f"{k}:{v}" for k, v in b["parameters"].items())
                item = {
                    "symbol": sym,
                    "strategy": strat_name,
                    "return_pct": b["total_return_pct"],
                    "sharpe": b["sharpe_ratio"],
                    "max_dd": b["max_drawdown_pct"],
                    "win_rate": b["win_rate_pct"],
                    "trades": b["trade_count"],
                    "params": p_str,
                }
                sym_best.append(item)
                all_top_picks.append(item)
        except Exception as exc:
            pass

    # Sort this symbol's strategies by Sharpe ratio descending
    sym_best.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"  🏆 {sym} İÇİN EN İYİ 3 STRATEJİ:")
    for rank, it in enumerate(sym_best[:3], 1):
        sign = "+" if it["return_pct"] >= 0 else ""
        print(f"    #{rank} {it['strategy']:<14} | Kâr: %{sign}{it['return_pct']:.2f} | Sharpe: {it['sharpe']:<6.3f} | WinRate: %{it['win_rate']} | İşlem: {it['trades']}")
        print(f"       -> Parametreler: {it['params']}")

# Final Global Leaderboard
print("\n" + "=" * 95)
print("             GENEL KRİPTO LİDERLİK TABLOSU (TÜM STRATEJİLER VE COINLER - SHARPE SIRALI)")
print("=" * 95)
all_top_picks.sort(key=lambda x: x["sharpe"], reverse=True)

header = f"{'Sıra':<4} {'Sembol':<9} {'Strateji':<14} {'Toplam Kâr':<12} {'Sharpe':<8} {'MaxDD':<8} {'İsabet':<8} {'İşlem':<6}"
print(header)
print("-" * len(header))
for idx, it in enumerate(all_top_picks[:15], 1):
    sign = "+" if it["return_pct"] >= 0 else ""
    print(f"#{idx:<3} {it['symbol']:<9} {it['strategy']:<14} %{sign}{it['return_pct']:<10.2f} {it['sharpe']:<8.3f} %{it['max_dd']:<7.2f} %{it['win_rate']:<7.1f} {it['trades']:<6}")

# Save results to JSON
out_path = Path("outputs/crypto_multi_strategy_matrix.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(all_top_picks, f, indent=2, ensure_ascii=False)
print(f"\nTüm detaylı sonuçlar {out_path} dosyasına kaydedildi!")
