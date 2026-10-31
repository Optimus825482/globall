"""
ZAMAN-ÇAPALI RVOL SPIKE (5m) — KOMŞULUK IZGARASI + GERÇEK WALK-FORWARD (IS 1000 → OOS 500)
===========================================================================================
v5'in tek tam adayı (WR %63.0, PF 2.30, 13/17 coin, split-half sağlam) overfit kontrolü:
 - RVOL eşiği: {1.5, 2.0, 2.5, 3.0}
 - Saat-of-gün geçmiş minimum: {5, 10, 20} bar
 - EMA kesişim penceresi: {20 (baz), 50}
 - TP/SL: baz 1.5/0.9 + (1.2/0.9), (2.0/1.2)
Kabul: baz IS'te 5/5 kriter + OOS Net>0 & PF≥1.2 & ≥10 işlem + komşuluk platosu.
"""
import sys
import math

import numpy as np
import pandas as pd

from test_indicator_combos_lab import (
    simulate_conservative, calc_ema, ALL_SYMBOLS, fetch_klines_range,
)

sys.stdout.reconfigure(encoding="utf-8")


def calc_rvol_tod(df: pd.DataFrame, min_hist=10) -> pd.Series:
    hour = df["time"].dt.floor("1h")
    hist = df.groupby(hour)["volume"].transform(lambda s: s.shift(1).expanding(min_periods=min_hist).mean())
    return df["volume"] / hist.replace(0, np.nan)


def rvol_signals(df, thr=2.0, min_hist=10, ema_n=20):
    close = df["close"]
    rvol = calc_rvol_tod(df, min_hist)
    ema = calc_ema(close, ema_n)
    return ((rvol > thr) & (close > ema) & (close.shift(1) <= ema.shift(1))).fillna(False)


def evaluate(data, params, tp, sl, oos=False):
    agg = {"trades": 0, "wins": 0, "gg": 0.0, "gl": 0.0, "net": 0.0, "cp": 0, "c": 0}
    for sym, df in data.items():
        sigs = rvol_signals(df, **params)
        sl_df, sl_sig = (df.iloc[1000:].reset_index(drop=True), sigs.iloc[1000:].reset_index(drop=True)) if oos \
            else (df.iloc[:1000].reset_index(drop=True), sigs.iloc[:1000].reset_index(drop=True))
        r = simulate_conservative(sl_df, sl_sig, tp, sl)
        if r["trades"]:
            agg["trades"] += r["trades"]; agg["wins"] += r["wins"]
            agg["gg"] += r["gross_gain"]; agg["gl"] += r["gross_loss"]
            agg["net"] += r["net_total"]; agg["c"] += 1
            agg["cp"] += 1 if r["net_total"] > 0 else 0
    wr = 100.0 * agg["wins"] / agg["trades"] if agg["trades"] else 0.0
    pf = agg["gg"] / agg["gl"] if agg["gl"] > 0 else 99.9
    return {"trades": agg["trades"], "wr": round(wr, 1), "pf": round(pf, 2),
            "net": round(agg["net"], 2), "cp": agg["cp"], "c": agg["c"]}


def main():
    print("=" * 108)
    print("  🔬 ZAMAN-ÇAPALI RVOL SPIKE (5m) — KOMŞULUK IZGARASI + WALK-FORWARD (IS 1000 → OOS 500)")
    print("=" * 108)
    data = {}
    for sym in ALL_SYMBOLS:
        try:
            data[sym] = fetch_klines_range(sym, interval="5m", total=1500)
        except Exception as e:
            print(f"⚠️ {sym}: {e}")
    print(f"Veri: {len(data)} coin x {min(len(d) for d in data.values())} bar\n")

    grid = [
        ("baz RVOL>2.0 m10 EMA20", dict(thr=2.0, min_hist=10, ema_n=20), (1.5, 0.9)),
        ("RVOL>1.5", dict(thr=1.5, min_hist=10, ema_n=20), (1.5, 0.9)),
        ("RVOL>2.5", dict(thr=2.5, min_hist=10, ema_n=20), (1.5, 0.9)),
        ("RVOL>3.0", dict(thr=3.0, min_hist=10, ema_n=20), (1.5, 0.9)),
        ("m5 (geçmiş pencere)", dict(thr=2.0, min_hist=5, ema_n=20), (1.5, 0.9)),
        ("m20 (geçmiş pencere)", dict(thr=2.0, min_hist=20, ema_n=20), (1.5, 0.9)),
        ("EMA50 kesişim", dict(thr=2.0, min_hist=10, ema_n=50), (1.5, 0.9)),
        ("TP1.2/SL0.9", dict(thr=2.0, min_hist=10, ema_n=20), (1.2, 0.9)),
        ("TP2.0/SL1.2", dict(thr=2.0, min_hist=10, ema_n=20), (2.0, 1.2)),
    ]

    print(f"{'Konfigürasyon':<24} {'İşlm':>5} {'WR%':>6} {'PF':>6} {'Net%':>8} {'+Coin':>6} | {'OOS İşlm':>8} {'OOS PF':>7} {'OOS Net%':>9}")
    print("-" * 108)
    base = None
    passing = []
    nets = []
    for label, params, (tp, sl) in grid:
        r = evaluate(data, params, tp, sl, oos=False)
        nets.append(r["net"])
        gates = [r["trades"] >= 20, r["wr"] >= 55.0, r["pf"] >= 1.5, r["net"] > 0, r["cp"] >= 3]
        oos_txt = "—"
        if r["net"] > 0:
            o = evaluate(data, params, tp, sl, oos=True)
            oos_txt = f"{o['trades']:>8} {o['pf']:>7.2f} {o['net']:>+9.2f}"
            if all(gates) and label.startswith("baz"):
                base = (label, params, r, o)
            if all(gates):
                passing.append((label, params, r, o))
        flags = "".join("✅" if v else "❌" for v in gates)
        print(f"{label:<24} {r['trades']:>5} {r['wr']:>6.1f} {r['pf']:>6.2f} {r['net']:>+8.2f} {r['cp']:>3}/{r['c']:<2} | {oos_txt}  {flags}")

    pos = sum(1 for n in nets if n > 0)
    strong = sum(1 for l, p, r, o in grid and []) if False else sum(1 for n in nets if n > 0)
    print(f"\n📊 Komşuluk: {len(nets)} konfigürasyonun {pos} tanesi IS'te net pozitif.")

    if base:
        label, params, r, o = base
        broad = pos >= len(nets) * 0.6
        oos_ok = o["net"] > 0 and o["pf"] >= 1.2 and o["trades"] >= 10
        if broad and oos_ok:
            print(f"🎉 KARAR: TERFİ GÜVENLİ — {label} | IS PF {r['pf']:.2f} WR {r['wr']:.1f}% | "
                  f"OOS PF {o['pf']:.2f}, Net {o['net']:+.2f}% ({o['trades']} işlem)")
        else:
            print(f"🟡 KARAR: Baz 5/5 geçti ama {'komşuluk platosu zayıf' if not broad else 'OOS doğrulanamadı'} "
                  f"(broad={broad}, OOS Net {o['net']:+.2f}%, PF {o['pf']:.2f}) → düşük skorla veya izleme.")
    else:
        print("❌ KARAR: Baz konfigürasyon IS'te 5 kriteri geçemedi → TERFİ YOK.")

if __name__ == "__main__":
    main()
