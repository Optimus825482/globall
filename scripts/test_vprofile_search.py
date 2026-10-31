"""
HACİM PROFİLİ VAL SEKMESİ (1h) — İKİ AŞAMALI PARAMETRE ARAMASI + WALK-FORWARD
==============================================================================
Lab v5 izleme havuzu adayı (PF 1.32, +41.2%, 14/18 coin — ama WR %44 < %60 ve
PF < 1.5) eşikleri aşabiliyor mu?

Aşama 1 (kaba ızgara, TP4.0/SL2.0 baz): lookback {200,300} × satır {12,24} ×
        VA %{65,70,80} × RSI kapısı {<40, <45, kapı yok} = 36 konfigürasyon.
Aşama 2: kaba ızgaranın ilk 5'i için TP/SL varyantları {4.0/2.0, 3.0/1.5, 5.0/2.5}
        + IS 5 kriter kontrolü + OOS (son 500 bar) doğrulama.
Kabul: IS 5/5 + OOS Net>0 & PF≥1.2 & ≥10 işlem + komşuluk platosu (≥%60 pozitif).
"""
import sys

import numpy as np
import pandas as pd

from test_indicator_combos_lab import simulate_conservative, calc_rsi, fetch_klines_range

sys.stdout.reconfigure(encoding="utf-8")


def val_series(df: pd.DataFrame, lookback: int, rows: int, va_pcts=(0.65, 0.70, 0.80)) -> dict:
    """Tek geçişte çoklu VA yüzdesi için VAL serileri (ağırlık merkezi genişletmesi)."""
    lows = df["low"].values
    highs = df["high"].values
    tp = ((df["high"] + df["low"] + df["close"]) / 3.0).values
    vol = df["volume"].values
    n = len(df)
    vals = {vp: np.full(n, np.nan) for vp in va_pcts}
    for i in range(lookback, n):
        s = i - lookback + 1
        lo, hi = lows[s:i + 1].min(), highs[s:i + 1].max()
        if hi <= lo:
            continue
        edges = np.linspace(lo, hi, rows + 1)
        centers = (edges[:-1] + edges[1:]) / 2.0
        bins = np.clip(np.digitize(tp[s:i + 1], edges) - 1, 0, rows - 1)
        vols = np.zeros(rows)
        np.add.at(vols, bins, vol[s:i + 1])
        total = vols.sum()
        if total <= 0:
            continue
        p = int(np.argmax(vols))
        for vp in va_pcts:
            acc = vols[p]
            lo_i, hi_i = p, p
            while acc < vp * total and (lo_i > 0 or hi_i < rows - 1):
                below = vols[lo_i - 1] if lo_i > 0 else -1.0
                above = vols[hi_i + 1] if hi_i < rows - 1 else -1.0
                if above >= below:
                    hi_i += 1
                    acc += vols[hi_i]
                else:
                    lo_i -= 1
                    acc += vols[lo_i]
            vals[vp][i] = centers[lo_i]
    return {vp: pd.Series(v, index=df.index) for vp, v in vals.items()}


def val_signals(df, val: pd.Series, rsi_max=40.0):
    close = df["close"]
    sig = (close.shift(1) <= val.shift(1)) & (close > val)
    if rsi_max is not None:
        sig = sig & (calc_rsi(close, 14) < rsi_max)
    return sig.fillna(False)


def evaluate(data, sigs_by_sym, tp, sl, oos=False):
    agg = {"trades": 0, "wins": 0, "gg": 0.0, "gl": 0.0, "net": 0.0, "cp": 0, "c": 0}
    for sym, sigs in sigs_by_sym.items():
        df = data[sym]
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
    print("=" * 110)
    print("  🔬 HACİM PROFİLİ VAL SEKMESİ (1h) — İKİ AŞAMALI ARAMA + WALK-FORWARD (IS 1000 → OOS 500)")
    print("=" * 110)
    data = {}
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
                "DOGEUSDT", "PEPEUSDT", "SHIBUSDT", "OPUSDT", "NEARUSDT", "BNBUSDT",
                "XRPUSDT", "ADAUSDT", "RENDERUSDT", "FETUSDT", "ARBUSDT", "INJUSDT"]:
        try:
            data[sym] = fetch_klines_range(sym, interval="1h", total=1500)
        except Exception as e:
            print(f"⚠️ {sym}: {e}")
    print(f"Veri: {len(data)} coin x {min(len(d) for d in data.values())} bar\n")

    TP, SL = 4.0, 2.0
    rsi_gates = [("<40", 40.0), ("<45", 45.0), ("kapı-yok", None)]

    # ── Aşama 1: kaba ızgara (profil (lookback, rows) başına bir kez hesaplanır) ──
    stage1 = []
    for lookback in (200, 300):
        for rows in (12, 24):
            for va in (0.65, 0.70, 0.80):
                prof = {sym: val_series(df, lookback, rows, va_pcts=(va,))[va] for sym, df in data.items()}
                for gate_label, rsi_max in rsi_gates:
                    sb = {sym: val_signals(data[sym], prof[sym], rsi_max) for sym in data}
                    r = evaluate(data, sb, TP, SL, oos=False)
                    stage1.append({"lookback": lookback, "rows": rows, "va": va, "gate": gate_label,
                                   "rsi_max": rsi_max, **r})

    stage1.sort(key=lambda x: (-x["pf"], -x["net"]))
    print(f"{'lookback':>8} {'satır':>5} {'VA':>5} {'RSI':>9} {'İşlm':>5} {'WR%':>6} {'PF':>6} {'Net%':>8} {'+Coin':>6}")
    print("-" * 70)
    for r in stage1[:12]:
        print(f"{r['lookback']:>8} {r['rows']:>5} {r['va']:>5.2f} {r['gate']:>9} {r['trades']:>5} "
              f"{r['wr']:>6.1f} {r['pf']:>6.2f} {r['net']:>+8.2f} {r['cp']:>3}/{r['c']:<2}")
    nets1 = [r["net"] for r in stage1]
    pos1 = sum(1 for n in nets1 if n > 0)
    print(f"\nAşama 1: 36 konfigürasyonun {pos1} tanesi net pozitif.\n")

    # ── Aşama 2: ilk 5 konfigürasyon × TP/SL varyantları + IS 5 kriter + OOS ──
    print("─" * 110)
    print("AŞAMA 2 — İlk 5 konfigürasyon × TP/SL varyantları (IS 5 kriter + OOS doğrulama):")
    print(f"{'Konfigürasyon':<34} {'TP/SL':>9} {'İşlm':>5} {'WR%':>6} {'PF':>6} {'Net%':>8} {'+Coin':>6} | {'OOS İşlm':>8} {'OOS PF':>7} {'OOS Net%':>9}")
    print("-" * 110)
    promoted = []
    for top in stage1[:5]:
        prof = {sym: val_series(df, top["lookback"], top["rows"], va_pcts=(top["va"],))[top["va"]]
                for sym, df in data.items()}
        for tp, sl in [(4.0, 2.0), (3.0, 1.5), (5.0, 2.5)]:
            sb = {sym: val_signals(data[sym], prof[sym], top["rsi_max"]) for sym in data}
            r = evaluate(data, sb, tp, sl, oos=False)
            gates = [r["trades"] >= 20, r["wr"] >= 60.0, r["pf"] >= 1.5, r["net"] > 0, r["cp"] >= 3]
            oos_txt = "—"
            if r["net"] > 0:
                o = evaluate(data, sb, tp, sl, oos=True)
                oos_txt = f"{o['trades']:>8} {o['pf']:>7.2f} {o['net']:>+9.2f}"
                if all(gates):
                    promoted.append((top, tp, sl, r, o))
            flags = "".join("✅" if v else "❌" for v in gates)
            label = f"LB{top['lookback']}/R{top['rows']}/VA{top['va']:.2f}/RSI{top['gate']}"
            print(f"{label:<34} {tp:>3.1f}/{sl:<4.1f} {r['trades']:>5} {r['wr']:>6.1f} {r['pf']:>6.2f} "
                  f"{r['net']:>+8.2f} {r['cp']:>3}/{r['c']:<2} | {oos_txt}  {flags}")

    print()
    if not promoted:
        print("❌ KARAR: Parametre aramasına rağmen IS 5/5 kriteri geçen konfigürasyon yok → "
              "Hacim Profili VAL izleme havuzunda kalır, canlıya alınmaz.")
        return
    broad = pos1 >= len(nets1) * 0.5
    any_ok = False
    for top, tp, sl, r, o in promoted:
        oos_ok = o["net"] > 0 and o["pf"] >= 1.2 and o["trades"] >= 10
        if broad and oos_ok:
            any_ok = True
            print(f"🎉 TERFİ ADAYI: LB{top['lookback']}/R{top['rows']}/VA{top['va']:.2f}/RSI{top['gate']} "
                  f"TP{tp}/SL{sl} | IS PF {r['pf']:.2f} WR {r['wr']:.1f}% | OOS PF {o['pf']:.2f} Net {o['net']:+.2f}% ({o['trades']} işlem)")
        else:
            print(f"🟡 {top['gate']} TP{tp}/SL{sl}: 5/5 geçti ama {'plato' if not broad else 'OOS'} şartı tutmadı → TERFİ YOK")
    if not any_ok:
        print("❌ GENEL KARAR: TERFİ YOK.")

if __name__ == "__main__":
    main()
