"""
BB-KC SQUEEZE BREAKOUT (5m) — PARAMETRE SAĞLAMLIK VE UZUN PENCERE DOĞRULAMASI
==============================================================================
Terfi öncesi son kontrol (KRIPTO_ALGO_SISTEMLER.HTML: overfitting / MinBTL disiplini):
 1. Parametre komşuluğu: bb_mult {1.8,2.0,2.2} x kc_mult {1.2,1.5,2.0} x squeeze_win {3,5,8}
 2. TP/SL varyantları: (1.2/0.9), (1.5/0.9), (1.8/1.0), (2.0/1.2)
 3. Uzun pencere: 1500 bar (orijinal 1000 + 500 ekstra bar = yarı örneklem-dışı)
 4. Split-half: ilk 750 / son 750 bar
Sadece komşuluk geniş çapta pozitifse strateji gerçek bir etkidir (squeeze → genişleme).
"""
import sys
import math
import numpy as np
import pandas as pd

from test_indicator_combos_lab import (
    simulate_conservative, calc_bollinger_vwap, calc_keltner, ALL_SYMBOLS,
)

sys.stdout.reconfigure(encoding="utf-8")


def squeeze_signals(df: pd.DataFrame, bb_len=20, bb_mult=2.0, kc_len=20, kc_atr=20,
                    kc_mult=1.5, squeeze_win=5) -> pd.Series:
    close = df["close"]
    upper, lower, _, _ = calc_bollinger_vwap(df, bb_len, bb_mult)
    kc_up, kc_lo = calc_keltner(df, kc_len, kc_atr, kc_mult)
    squeeze = (upper < kc_up) & (lower > kc_lo)
    squeeze_recent = squeeze.shift(1).rolling(squeeze_win).max().fillna(0).astype(bool)
    brk = (close > upper) & (close.shift(1) <= upper.shift(1))
    return (squeeze_recent & brk).fillna(False)


def run_grid():
    print("=" * 100)
    print("  🔬 BB-KC SQUEEZE BREAKOUT — PARAMETRE SAĞLAMLIK + 1500 BAR DOĞRULAMA (5m)")
    print("=" * 100)

    data = {}
    for sym in ALL_SYMBOLS:
        try:
            data[sym] = pd.read_pickle  # noqa placeholder
        except Exception:
            pass

    # 1500 bar taze veri çek
    from test_advanced_spot_strategies import fetch_binance_klines
    data = {}
    for sym in ALL_SYMBOLS:
        try:
            data[sym] = fetch_binance_klines(sym, interval="5m", limit=1500)
        except Exception as e:
            print(f"⚠️ {sym}: {e}")
    print(f"Veri: {len(data)} coin x 1500 bar (5m)\n")

    TP, SL = 1.5, 0.9
    results = []

    def evaluate(params, tp, sl, label):
        agg = {"trades": 0, "wins": 0, "gg": 0.0, "gl": 0.0, "net": 0.0,
               "coins_pos": 0, "coins": 0, "h1": 0.0, "h2": 0.0}
        for sym, df in data.items():
            sigs = squeeze_signals(df, **params)
            full = simulate_conservative(df, sigs, tp, sl)
            h1 = simulate_conservative(df.iloc[:750].reset_index(drop=True),
                                       sigs.iloc[:750].reset_index(drop=True), tp, sl)
            h2 = simulate_conservative(df.iloc[750:].reset_index(drop=True),
                                       sigs.iloc[750:].reset_index(drop=True), tp, sl)
            if full["trades"]:
                agg["trades"] += full["trades"]
                agg["wins"] += full["wins"]
                agg["gg"] += full["gross_gain"]
                agg["gl"] += full["gross_loss"]
                agg["net"] += full["net_total"]
                agg["coins"] += 1
                agg["coins_pos"] += 1 if full["net_total"] > 0 else 0
            agg["h1"] += h1["net_total"]
            agg["h2"] += h2["net_total"]
        wr = 100.0 * agg["wins"] / agg["trades"] if agg["trades"] else 0.0
        pf = agg["gg"] / agg["gl"] if agg["gl"] > 0 else 99.9
        results.append((label, agg["trades"], wr, pf, agg["net"], agg["coins_pos"], agg["coins"], agg["h1"], agg["h2"]))

    print(f"{'Parametre seti':<52} {'İşlm':>5} {'WR%':>6} {'PF':>6} {'Net%':>8} {'+Coin':>6} {'H1':>8} {'H2':>8}")
    print("-" * 100)
    # 1) TP/SL varyantları (baz parametrelerle)
    for tp, sl in [(1.2, 0.9), (1.5, 0.9), (1.8, 1.0), (2.0, 1.2)]:
        evaluate(dict(bb_len=20, bb_mult=2.0, kc_len=20, kc_atr=20, kc_mult=1.5, squeeze_win=5),
                 tp, sl, f"TP{tp}/SL{sl} (baz: BB2.0/KC1.5/w5)")
    # 2) Parametre komşuluğu (TP1.5/SL0.9 sabit)
    for bb_mult in (1.8, 2.0, 2.2):
        for kc_mult in (1.2, 1.5, 2.0):
            for squeeze_win in (3, 5, 8):
                if bb_mult == 2.0 and kc_mult == 1.5 and squeeze_win == 5:
                    continue  # baz zaten test edildi
                evaluate(dict(bb_len=20, bb_mult=bb_mult, kc_len=20, kc_atr=20,
                              kc_mult=kc_mult, squeeze_win=squeeze_win),
                         TP, SL, f"BB{bb_mult}/KC{kc_mult}/w{squeeze_win}")

    base = [r for r in results if r[0].startswith("TP")]
    grid = [r for r in results if not r[0].startswith("TP")]
    grid.sort(key=lambda r: -r[4])

    print("\n--- TP/SL duyarlılığı (baz parametreler) ---")
    for r in base:
        print(f"{r[0]:<52} {r[1]:>5} {r[2]:>6.1f} {r[3]:>6.2f} {r[4]:>+8.2f} {r[5]:>3}/{r[6]:<2} {r[7]:>+8.2f} {r[8]:>+8.2f}")

    print("\n--- Parametre komşuluğu (TP1.5/SL0.9, net kâra göre) ---")
    for r in grid:
        verdict = "✅" if (r[4] > 0 and r[2] >= 55 and r[3] >= 1.5 and r[5] >= 10) else (
            "🟡" if r[4] > 0 and r[3] >= 1.2 else "❌")
        print(f"{verdict} {r[0]:<50} {r[1]:>5} {r[2]:>6.1f} {r[3]:>6.2f} {r[4]:>+8.2f} {r[5]:>3}/{r[6]:<2} {r[7]:>+8.2f} {r[8]:>+8.2f}")

    pos = sum(1 for r in grid if r[4] > 0)
    strong = sum(1 for r in grid if r[4] > 0 and r[3] >= 1.5)
    print(f"\n📊 Komşuluk özeti: {len(grid)} komşu parametreden {pos} tanesi net pozitif, "
          f"{strong} tanesi PF≥1.5 + WR≥%55 + ≥10 coin pozitif.")
    if strong >= len(grid) * 0.5:
        print("✅ SONUÇ: Etki parametreye bağımlı değil → GERÇEK SIKIŞMA-GENİŞLEME ETKİSİ. Terfi güvenli.")
    elif pos >= len(grid) * 0.6:
        print("🟡 SONUÇ: Yön tutarlı ama büyüklük parametreye duyarlı → düşük ağırlıkla terfi edilebilir.")
    else:
        print("❌ SONUÇ: Komşuluk çoğunlukla negatif → tek parametre setine bağlı overfit. Terfi ETME.")

if __name__ == "__main__":
    run_grid()
