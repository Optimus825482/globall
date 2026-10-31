#!/usr/bin/env python3
"""VectorBT Destekli Ultra-Hızlı Çoklu-Parametre Strateji Optimizasyon Motoru.

Kullanım:
    python scripts/vectorbt_optimizer.py --symbol XAUUSD --cache outputs/forex_replay_21d.json
    python scripts/vectorbt_optimizer.py --symbol BTCUSD --cache outputs/forex_replay_21d.json --top 5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import vectorbt as vbt


def load_candles_from_cache(cache_path: str, symbol: str) -> pd.DataFrame:
    """Replay önbelleğinden veya JSON dosyasından barları yükler ve DataFrame yapar."""
    if not os.path.exists(cache_path):
        raise FileNotFoundError(f"Önbellek dosyası bulunamadı: {cache_path}")

    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if symbol not in data:
        available = list(data.keys())[:15]
        raise ValueError(f"Sembol '{symbol}' önbellekte yok. Mevcut semboller: {available}")

    raw_bars = data[symbol]
    if not raw_bars:
        raise ValueError(f"'{symbol}' için bar verisi boş.")

    cols = ["timestamp", "open", "high", "low", "close"]
    if len(raw_bars[0]) >= 6:
        cols.append("volume")
        records = [b[:6] for b in raw_bars]
    else:
        records = [b[:5] for b in raw_bars]

    df = pd.DataFrame(records, columns=cols)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df.set_index("datetime").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df


def optimize_ema_crossover_vbt(
    df: pd.DataFrame,
    windows: list[int] | None = None,
    tp_sl_pairs: list[tuple[float, float]] | None = None,
    fees: float = 0.0002,
    top_n: int = 10,
) -> dict:
    """VectorBT ile EMA kombinasyonları ve TP/SL ızgarasını vektörize simüle eder."""
    windows = windows or [5, 8, 9, 13, 15, 21, 34, 50, 55, 89]
    tp_sl_pairs = tp_sl_pairs or [
        (0.010, 0.008),
        (0.015, 0.010),
        (0.020, 0.012),
        (0.025, 0.015),
        (0.030, 0.015),
    ]

    close = df["close"]
    # windows arasından ikili kombinasyonlar sayısı: C(N, 2)
    n_combs = len(windows) * (len(windows) - 1) // 2
    total_combinations = n_combs * len(tp_sl_pairs)

    print(f"\n[VectorBT] Vektörize Optimizasyon Başlıyor...")
    print(f"Toplam Parametre Kombinasyonu: {total_combinations:,}")
    print(f"Veri Boyutu: {len(df):,} bar ({df.index[0]} -> {df.index[-1]})")

    start_time = time.time()

    # Tüm ikili EMA kombinasyonlarını vektörel hesapla
    fast_ma, slow_ma = vbt.MA.run_combs(close, windows, r=2, ewm=True)
    entries = fast_ma.ma_crossed_above(slow_ma)
    exits = fast_ma.ma_crossed_below(slow_ma)

    all_results = []

    # Her TP/SL çifti için vektörel portföyü test et
    for tp, sl in tp_sl_pairs:
        pf = vbt.Portfolio.from_signals(
            close=close,
            entries=entries,
            exits=exits,
            tp_stop=tp,
            sl_stop=sl,
            fees=fees,
            freq="15m" if len(df) > 500 else "1m",
        )

        total_ret = pf.total_return()
        sharpe = pf.sharpe_ratio()
        max_dd = pf.max_drawdown()
        win_rate = pf.trades.win_rate()
        trades = pf.trades.count()

        fast_idx = total_ret.index.names.index("ma_1_window") if "ma_1_window" in total_ret.index.names else 0
        slow_idx = total_ret.index.names.index("ma_2_window") if "ma_2_window" in total_ret.index.names else 1

        for col_idx in total_ret.index:
            if isinstance(col_idx, tuple):
                w_fast = col_idx[fast_idx]
                w_slow = col_idx[slow_idx]
            else:
                w_fast = col_idx
                w_slow = col_idx
            t_count = int(trades[col_idx])
            s_val = float(sharpe[col_idx])
            if np.isnan(s_val):
                s_val = 0.0

            all_results.append({
                "parameters": {
                    "fast_ema": int(w_fast),
                    "slow_ema": int(w_slow),
                    "tp_pct": round(tp * 100, 2),
                    "sl_pct": round(sl * 100, 2),
                },
                "total_return_pct": round(float(total_ret[col_idx]) * 100, 2),
                "sharpe_ratio": round(s_val, 3),
                "max_drawdown_pct": round(float(max_dd[col_idx]) * 100, 2),
                "win_rate_pct": round(float(win_rate[col_idx]) * 100, 2),
                "trade_count": t_count,
            })

    elapsed = time.time() - start_time
    print(f"[VectorBT] Simülasyon Tamamlandı! Süre: {elapsed:.2f} saniye ({total_combinations / max(elapsed, 0.001):,.0f} test/sn)")

    # En az 5 işlem yapmış olanları Sharpe'a göre sırala
    valid_results = [r for r in all_results if r["trade_count"] >= 5]
    if not valid_results:
        valid_results = all_results

    valid_results.sort(key=lambda x: (x["sharpe_ratio"], x["total_return_pct"]), reverse=True)
    top_results = valid_results[:top_n]

    return {
        "status": "success",
        "elapsed_sec": round(elapsed, 3),
        "total_combinations": total_combinations,
        "bars_evaluated": len(df),
        "top_results": top_results,
    }


def main():
    parser = argparse.ArgumentParser(description="VectorBT Ultra-Hızlı Strateji Optimizatörü")
    parser.add_argument("--symbol", default="XAUUSD", help="Analiz edilecek sembol (ör: XAUUSD, BTCUSD)")
    parser.add_argument("--cache", default="outputs/forex_replay_21d.json", help="Bar verisi JSON önbellek yolu")
    parser.add_argument("--top", type=int, default=5, help="Raporlanacak en iyi sonuç sayısı")
    parser.add_argument("--out", default=None, help="Sonuç JSON kayıt dosyası (opsiyonel)")
    args = parser.parse_args()

    print(f"=== VectorBT Optimizasyon Motoru ===")
    print(f"Hedef Sembol: {args.symbol}")
    print(f"Kaynak Veri:  {args.cache}")

    df = load_candles_from_cache(args.cache, args.symbol)
    res = optimize_ema_crossover_vbt(df, top_n=args.top)

    print("\n--- EN İYİ PARAMETRE KOMBİNASYONLARI (Sharpe Sıralı) ---")
    header = f"{'Sıra':<5} {'Parametreler':<38} {'Toplam Kâr':<12} {'Sharpe':<8} {'MaxDD':<8} {'İsabet':<8} {'İşlem':<6}"
    print(header)
    print("-" * len(header))
    for i, item in enumerate(res["top_results"], 1):
        p = item["parameters"]
        param_str = f"Fast:{p.get('fast_ema')}|Slow:{p.get('slow_ema')}|TP:%{p.get('tp_pct')}|SL:%{p.get('sl_pct')}"
        print(f"#{i:<4} {param_str:<38} %{item['total_return_pct']:<11} {item['sharpe_ratio']:<8} %{item['max_drawdown_pct']:<7} %{item['win_rate_pct']:<7} {item['trade_count']:<6}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)
        print(f"\nSonuçlar kaydedildi: {args.out}")


if __name__ == "__main__":
    main()
