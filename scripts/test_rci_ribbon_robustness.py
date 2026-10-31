"""
RCI ŞERİDİ HİZASI (5m) — KOMŞULUK IZGARASI + GERÇEK WALK-FORWARD (IS 1000 → OOS 500)
====================================================================================
v4'ün en güçlü adayı (PF 1.38, H2 +28.1, 14/18 coin) PF 1.5 eşiğini aşabiliyor mu?
Kural: komşuluk geniş çapta pozitifse (plato) VE bireysel bir konfigürasyon IS'te
tüm 5 sert kriteri geçip OOS'ta (son 500 bar, seçimde kullanılmadı) Net>0 + PF≥1.2
+ ≥10 işlem yapıyorsa terfi. Tek tük parlayan noktalar (lone spike) RED.
"""
import sys
import math

import pandas as pd

from test_indicator_combos_lab import (
    simulate_conservative, calc_ema, calc_chop, ALL_SYMBOLS, fetch_klines_range,
)
from test_indicator_combos_lab_v3 import calc_rci

sys.stdout.reconfigure(encoding="utf-8")


def rci_ribbon_signals(df, r1=9, r2=26, r3=52, ema_n=50, r1_min=None):
    close = df["close"]
    a, b, c = calc_rci(close, r1), calc_rci(close, r2), calc_rci(close, r3)
    aligned = (a > b) & (b > c) & (a > a.shift(1)) & (b > b.shift(1)) & (c > c.shift(1))
    sig = aligned & (close > calc_ema(close, ema_n))
    if r1_min is not None:
        sig = sig & (a > r1_min)
    return sig.fillna(False)


def evaluate(data, params, tp, sl, oos=False):
    agg = {"trades": 0, "wins": 0, "gg": 0.0, "gl": 0.0, "net": 0.0, "cp": 0, "c": 0, "h1": 0.0, "h2": 0.0}
    for sym, df in data.items():
        sigs = rci_ribbon_signals(df, **params)
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
    print("=" * 105)
    print("  🔬 RCI ŞERİDİ HİZASI (5m) — KOMŞULUK IZGARASI + WALK-FORWARD (IS 1000 → OOS 500)")
    print("=" * 105)
    data = {}
    for sym in ALL_SYMBOLS:
        try:
            data[sym] = fetch_klines_range(sym, interval="5m", total=1500)
        except Exception as e:
            print(f"⚠️ {sym}: {e}")
    print(f"Veri: {len(data)} coin x {min(len(d) for d in data.values())} bar\n")

    TP, SL = 1.5, 0.9
    grid = [
        ("baz 9/26/52 EMA50", dict(r1=9, r2=26, r3=52, ema_n=50)),
        ("8/21/42 EMA50", dict(r1=8, r2=21, r3=42, ema_n=50)),
        ("10/26/52 EMA50", dict(r1=10, r2=26, r3=52, ema_n=50)),
        ("9/21/52 EMA50", dict(r1=9, r2=21, r3=52, ema_n=50)),
        ("13/26/52 EMA50", dict(r1=13, r2=26, r3=52, ema_n=50)),
        ("9/26/52 EMA100", dict(r1=9, r2=26, r3=52, ema_n=100)),
        ("9/26/52 EMA200", dict(r1=9, r2=26, r3=52, ema_n=200)),
        ("9/26/52 EMA50 + RCI9>10", dict(r1=9, r2=26, r3=52, ema_n=50, r1_min=10)),
        ("9/26/52 EMA50 + RCI9>20", dict(r1=9, r2=26, r3=52, ema_n=50, r1_min=20)),
        ("8/21/42 EMA100", dict(r1=8, r2=21, r3=42, ema_n=100)),
        ("10/26/52 EMA100", dict(r1=10, r2=26, r3=52, ema_n=100)),
    ]

    print(f"{'Konfigürasyon':<28} {'İşlm':>5} {'WR%':>6} {'PF':>6} {'Net%':>8} {'+Coin':>6} | {'OOS İşlm':>8} {'OOS PF':>7} {'OOS Net%':>9}")
    print("-" * 105)
    passing = []
    nets = []
    for label, params in grid:
        r = evaluate(data, params, TP, SL, oos=False)
        nets.append(r["net"])
        oos_txt = "—"
        gates = [r["trades"] >= 20, r["wr"] >= 55.0, r["pf"] >= 1.5, r["net"] > 0, r["cp"] >= 3]
        if sum(gates) >= 3 and r["net"] > 0:
            o = evaluate(data, params, TP, SL, oos=True)
            oos_txt = f"{o['trades']:>8} {o['pf']:>7.2f} {o['net']:>+9.2f}"
            if all(gates):
                passing.append((label, params, r, o))
        flags = "".join("✅" if v else "❌" for v in gates)
        print(f"{label:<28} {r['trades']:>5} {r['wr']:>6.1f} {r['pf']:>6.2f} {r['net']:>+8.2f} {r['cp']:>3}/{r['c']:<2} | {oos_txt}  {flags}")

    pos = sum(1 for n in nets if n > 0)
    print(f"\n📊 Komşuluk: {len(nets)} konfigürasyondan {pos} tanesi IS'te net pozitif.")

    if not passing:
        print("❌ KARAR: Hiçbir konfigürasyon IS'te 5 kriterin tamamını geçemedi → TERFİ YOK, "
              "RCI Şeridi 'izleme' havuzunda kalır (PF eşiğinin hemen altında, H2 güçlü).")
        return
    # Lone-spike koruması: terfi için komşuluk platosu şartı
    broad = pos >= len(nets) * 0.6
    for label, params, r, o in passing:
        if broad and o["net"] > 0 and o["pf"] >= 1.2 and o["trades"] >= 10:
            print(f"🎉 TERFİ ADAYI: {label} | IS PF {r['pf']:.2f} WR {r['wr']:.1f}% | "
                  f"OOS PF {o['pf']:.2f} Net {o['net']:+.2f}% ({o['trades']} işlem)")
        else:
            print(f"🟡 {label}: 5 kriteri geçti ama plato şartı ({'yok' if not broad else 'OOS zayıf'}) → TERFİ YOK")

if __name__ == "__main__":
    main()
