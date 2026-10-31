"""
LINREG EĞİM DÖNÜŞÜ + VOL OSC (5m) — PARAMETRE SAĞLAMLIK + 1500 BAR DOĞRULAMA
============================================================================
v3 turunun tek tam-adayının overfit kontrolü:
 - LinReg eğim penceresi {10, 14, 20}
 - Volume Oscillator {5/10, 10/20}, eşik {>0, >5}
 - Trend filtresi {EMA50, EMA200}
 - TP/SL varyantları (baz parametrelerle): 1.5/0.9, 1.2/0.9, 1.8/1.0, 2.0/1.2
 - 1500 bar pencere (orijinal 1000 + 500 yeni bar), split-half 750/750
Kabul: komşuların çoğunluğu net pozitif + baz konfigürasyonda H2 pozitif → terfi.
"""
import sys
import math

from test_advanced_spot_strategies import fetch_binance_klines
from test_indicator_combos_lab import (
    simulate_conservative, calc_ema, calc_rsi, calc_chop, ALL_SYMBOLS,
)
from test_indicator_combos_lab_v3 import calc_linreg_slope, calc_vol_osc

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")


def linreg_signals(df, slope_n=14, vo_fast=5, vo_slow=10, vo_thr=0.0, ema_n=50):
    close = df["close"]
    slope = calc_linreg_slope(close, slope_n)
    vo = calc_vol_osc(df, vo_fast, vo_slow)
    return ((slope.shift(1) <= 0.0) & (slope > 0.0) & (vo > vo_thr) &
            (close > calc_ema(close, ema_n))).fillna(False)


def main():
    print("=" * 105)
    print("  🔬 LINREG EĞİM DÖNÜŞÜ + VOL OSC — PARAMETRE SAĞLAMLIK + 1500 BAR DOĞRULAMA (5m)")
    print("=" * 105)
    data = {}
    for sym in ALL_SYMBOLS:
        try:
            data[sym] = fetch_binance_klines(sym, interval="5m", limit=1500)
        except Exception as e:
            print(f"⚠️ {sym}: {e}")
    print(f"Veri: {len(data)} coin x 1500 bar\n")

    results = []

    def evaluate(label, params, tp, sl):
        agg = {"trades": 0, "wins": 0, "gg": 0.0, "gl": 0.0, "net": 0.0,
               "cp": 0, "c": 0, "h1": 0.0, "h2": 0.0}
        for sym, df in data.items():
            sigs = linreg_signals(df, **params)
            full = simulate_conservative(df, sigs, tp, sl)
            h1 = simulate_conservative(df.iloc[:750].reset_index(drop=True), sigs.iloc[:750].reset_index(drop=True), tp, sl)
            h2 = simulate_conservative(df.iloc[750:].reset_index(drop=True), sigs.iloc[750:].reset_index(drop=True), tp, sl)
            if full["trades"]:
                agg["trades"] += full["trades"]; agg["wins"] += full["wins"]
                agg["gg"] += full["gross_gain"]; agg["gl"] += full["gross_loss"]
                agg["net"] += full["net_total"]; agg["c"] += 1
                agg["cp"] += 1 if full["net_total"] > 0 else 0
            agg["h1"] += h1["net_total"]; agg["h2"] += h2["net_total"]
        wr = 100.0 * agg["wins"] / agg["trades"] if agg["trades"] else 0.0
        pf = agg["gg"] / agg["gl"] if agg["gl"] > 0 else 99.9
        results.append((label, agg["trades"], wr, pf, agg["net"], agg["cp"], agg["c"], agg["h1"], agg["h2"]))

    base = dict(slope_n=14, vo_fast=5, vo_slow=10, vo_thr=0.0, ema_n=50)
    for tp, sl in [(1.5, 0.9), (1.2, 0.9), (1.8, 1.0), (2.0, 1.2)]:
        evaluate(f"TP{tp}/SL{sl} (baz: n14, VO5/10>0, EMA50)", base, tp, sl)
    for slope_n in (10, 20):
        evaluate(f"slope_n={slope_n}", {**base, "slope_n": slope_n}, 1.5, 0.9)
    for vf, vs in [(10, 20)]:
        evaluate(f"VO {vf}/{vs}", {**base, "vo_fast": vf, "vo_slow": vs}, 1.5, 0.9)
    evaluate("VO eşik >5", {**base, "vo_thr": 5.0}, 1.5, 0.9)
    evaluate("EMA200 filtresi", {**base, "ema_n": 200}, 1.5, 0.9)
    for slope_n, ema_n in [(10, 200), (20, 200)]:
        evaluate(f"slope_n={slope_n} + EMA{ema_n}", {**base, "slope_n": slope_n, "ema_n": ema_n}, 1.5, 0.9)
    for vf, vs in [(10, 20)]:
        for ema_n in (200,):
            evaluate(f"VO {vf}/{vs} + EMA{ema_n}", {**base, "vo_fast": vf, "vo_slow": vs, "ema_n": ema_n}, 1.5, 0.9)

    tpsl = [r for r in results if r[0].startswith("TP")]
    grid = [r for r in results if not r[0].startswith("TP")]
    grid.sort(key=lambda r: -r[4])

    print(f"{'Konfigürasyon':<38} {'İşlm':>5} {'WR%':>6} {'PF':>6} {'Net%':>8} {'+Coin':>6} {'H1':>8} {'H2':>8}")
    print("-" * 105)
    print("--- TP/SL duyarlılığı ---")
    for r in tpsl:
        print(f"{r[0]:<38} {r[1]:>5} {r[2]:>6.1f} {r[3]:>6.2f} {r[4]:>+8.2f} {r[5]:>3}/{r[6]:<2} {r[7]:>+8.2f} {r[8]:>+8.2f}")
    print("--- Parametre komşuluğu (TP1.5/SL0.9) ---")
    for r in grid:
        v = "✅" if (r[4] > 0 and r[3] >= 1.4 and r[5] >= 8) else ("🟡" if r[4] > 0 else "❌")
        print(f"{v} {r[0]:<36} {r[1]:>5} {r[2]:>6.1f} {r[3]:>6.2f} {r[4]:>+8.2f} {r[5]:>3}/{r[6]:<2} {r[7]:>+8.2f} {r[8]:>+8.2f}")

    pos = sum(1 for r in grid if r[4] > 0)
    strong = sum(1 for r in grid if r[4] > 0 and r[3] >= 1.4)
    base_r = tpsl[0]
    print(f"\n📊 Komşuluk özeti: {len(grid)} komşudan {pos} net pozitif, {strong} PF≥1.4.")
    print(f"   Baz (1500 bar): Net {base_r[4]:+.2f}%, H1 {base_r[7]:+.2f} / H2 {base_r[8]:+.2f}")
    if pos >= len(grid) * 0.6 and base_r[8] > 0 and base_r[4] > 0:
        print("✅ KARAR: Etki komşulukta tutarlı + uzun pencerede H2 pozitif → TERFİ GÜVENLİ.")
    elif pos >= len(grid) * 0.6:
        print("🟡 KARAR: Komşuluk tutarlı ama güncel yarı (H2) zayıf → DÜŞÜK SKORLA terfi + yakından izleme.")
    else:
        print("❌ KARAR: Komşuluk tutarsız → TERFİ ETME, YENİDEN TEST havuzuna al.")

if __name__ == "__main__":
    main()
