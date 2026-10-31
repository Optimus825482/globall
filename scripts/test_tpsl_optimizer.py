"""
TP/SL KADEME OPTİMİZATÖRÜ — KAZANAN STRATEJİLER İÇİN WALK-FORWARD
==================================================================
Kapsam: BB-KC Sıkışma Kırılımı, LinReg Eğim Dönüşü (canlı şampiyonlar) +
Aroon, Ichimoku (yeniden test havuzu) × 5m/15m/1h × TP/SL ızgarası.

Metot (overfit korumalı):
 1. IS (ilk 1000 bar): ızgarada en iyi TP/SL seçilir — şartlar: ≥20 işlem,
    Net>0, ≥3 coin pozitif; sıralama PF'ye göre.
 2. Komşu stabilite: seçilen noktanın 4 ortogonal komşusundan ≥3'ü Net>0 olmalı
    (tek noktalık tepe = overfit işareti → elenir).
 3. OOS (son 500 bar, hiç seçimde kullanılmadı): Net>0, PF≥1.2, ≥10 işlem şart.
 4. Mevcut canlı kademe (5m 1.5/0.9, 15m 2.2/1.2, 1h 4.0/2.0) da IS'de
    değerlendirilir; override ancak mevcut kademeden anlamlı derecede iyiyse
    veya mevcut TF hiç geçemiyorsa önerilir.
N beyanı: ızgara denemeleri loglanır (çoklu-test E[max] uyarısıyla).
"""
import sys
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from test_indicator_combos_lab import (
    simulate_conservative, ALL_SYMBOLS, COMMISSION_PCT, generate_signals_v2, fetch_klines_range,
)
from test_indicator_combos_lab_v3 import generate_signals_v3

sys.stdout.reconfigure(encoding="utf-8")

STRATEGIES = {
    "BB_KC_SQUEEZE_BREAK": ("BB-KC Sıkışma Kırılımı", "v2"),
    "LINREG_SLOPE_TURN_VOL": ("LinReg Eğim Dönüşü + Hacim", "v3"),
    "AROON_POWER_EMA50":   ("Aroon Up>70/Down<30 + EMA50", "v3"),
    "ICHIMOKU_TK_CLOUD":   ("Ichimoku TK Kesişim + Bulut Üstü", "v3"),
}

# Izgara: TF ölçeğine göre ölçeklenen TP × SL
GRID = {
    "5m":  {"tp": [1.0, 1.5, 2.0, 2.5, 3.0], "sl": [0.6, 0.9, 1.2, 1.5]},
    "15m": {"tp": [1.5, 2.2, 3.0, 4.0, 5.0], "sl": [0.9, 1.2, 1.8, 2.4]},
    "1h":  {"tp": [2.0, 3.0, 4.0, 5.0, 6.0, 8.0], "sl": [1.2, 2.0, 2.5, 3.5]},
}
LIVE_DEFAULT = {"5m": (1.5, 0.9), "15m": (2.2, 1.2), "1h": (4.0, 2.0)}

def eval_grid(df_by_sym, sig_by_sym, tf, tp, sl, oos: bool):
    """Verilen TP/SL'yi IS (ilk 1000) veya OOS (son 500) diliminde toplu değerlendirir."""
    agg = {"trades": 0, "wins": 0, "gg": 0.0, "gl": 0.0, "net": 0.0, "cp": 0, "c": 0}
    for sym, sigs in sig_by_sym.items():
        df = df_by_sym[sym]
        if oos:
            sub = df.iloc[1000:].reset_index(drop=True)
            sg = sigs.iloc[1000:].reset_index(drop=True)
        else:
            sub = df.iloc[:1000].reset_index(drop=True)
            sg = sigs.iloc[:1000].reset_index(drop=True)
        r = simulate_conservative(sub, sg, tp, sl)
        if r["trades"]:
            agg["trades"] += r["trades"]; agg["wins"] += r["wins"]
            agg["gg"] += r["gross_gain"]; agg["gl"] += r["gross_loss"]
            agg["net"] += r["net_total"]; agg["c"] += 1
            agg["cp"] += 1 if r["net_total"] > 0 else 0
    wr = 100.0 * agg["wins"] / agg["trades"] if agg["trades"] else 0.0
    pf = agg["gg"] / agg["gl"] if agg["gl"] > 0 else 99.9
    return {"tp": tp, "sl": sl, "trades": agg["trades"], "wr": round(wr, 1),
            "pf": round(pf, 2), "net": round(agg["net"], 2),
            "coins_pos": agg["cp"], "coins": agg["c"]}


def run_optimizer():
    n_grid = sum(len(g["tp"]) * len(g["sl"]) for g in GRID.values())
    n_configs = n_grid * len(STRATEGIES) * len(GRID)
    print("=" * 105)
    print("  🎯 TP/SL KADEME OPTİMİZATÖRÜ — WALK-FORWARD (IS 1000 bar → OOS 500 bar)")
    print("=" * 105)
    print(f"Stratejiler: {len(STRATEGIES)} | TF: {list(GRID)} | Izgara: {n_grid}/TF | "
          f"Toplam deneme N={n_configs}, E[max]≈√(2·lnN)={math.sqrt(2 * math.log(max(2, n_configs))):.2f}")

    recommendations = []
    for tf in GRID:
        print(f"\n{'=' * 105}\n▶ TF {tf} — veri çekiliyor (1500 bar/coin)...")
        data = {}
        for sym in ALL_SYMBOLS:
            try:
                data[sym] = fetch_klines_range(sym, interval=tf, total=1500)
            except Exception as e:
                print(f"   ⚠️ {sym}: {e}")
        print(f"   Veri hazır: {len(data)} coin")

        for code, (label, ver) in STRATEGIES.items():
            df_by_sym = {s: d for s, d in data.items() if len(d) >= 1000}
            sig_by_sym = {}
            for sym, df in df_by_sym.items():
                sigs = generate_signals_v2(df, code) if ver == "v2" else generate_signals_v3(df, code)
                if int(sigs.sum()) >= 1:
                    sig_by_sym[sym] = sigs
            if not sig_by_sym:
                continue

            results = []
            for tp in GRID[tf]["tp"]:
                for sl in GRID[tf]["sl"]:
                    results.append(eval_grid(df_by_sym, sig_by_sym, tf, tp, sl, oos=False))

            # IS seçim: sert şartlar + PF sıralaması
            eligible = [r for r in results if r["trades"] >= 20 and r["net"] > 0 and r["coins_pos"] >= 3]
            live_r = next((r for r in results if r["tp"] == LIVE_DEFAULT[tf][0] and r["sl"] == LIVE_DEFAULT[tf][1]), None)

            def neighbors(r):
                tps, sls = GRID[tf]["tp"], GRID[tf]["sl"]
                ti, si = tps.index(r["tp"]), sls.index(r["sl"])
                out = []
                for dt, ds in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    ni, ns = ti + dt, si + ds
                    if 0 <= ni < len(tps) and 0 <= ns < len(sls):
                        out.append(next(x for x in results if x["tp"] == tps[ni] and x["sl"] == sls[ns]))
                return out

            chosen, verdict = None, "RED (IS şartları tutmadı)"
            if eligible:
                best = sorted(eligible, key=lambda r: (-r["pf"], -r["net"]))[0]
                nb = neighbors(best)
                nb_pos = sum(1 for x in nb if x["net"] > 0)
                if len(nb) >= 2 and nb_pos < max(2, len(nb) - 1):
                    verdict = f"RED (komşu stabilite: {nb_pos}/{len(nb)} pozitif)"
                else:
                    oos = eval_grid(df_by_sym, sig_by_sym, tf, best["tp"], best["sl"], oos=True)
                    oos_ok = oos["net"] > 0 and oos["pf"] >= 1.2 and oos["trades"] >= 10
                    better_than_live = (live_r is None or not (live_r["trades"] >= 20 and live_r["net"] > 0 and live_r["coins_pos"] >= 3)
                                        or best["pf"] > live_r["pf"] * 1.10 or best["net"] > live_r["net"] * 1.25)
                    if not oos_ok:
                        verdict = f"RED (OOS başarısız: Net {oos['net']:+.2f}%, PF {oos['pf']:.2f}, {oos['trades']} işlem)"
                    elif not better_than_live:
                        verdict = f"MEVCUT KADEME YETERLİ (canlı {LIVE_DEFAULT[tf][0]}/{LIVE_DEFAULT[tf][1]}: PF {live_r['pf']:.2f})"
                        chosen = {"tf": tf, "code": code, "keep_live": True, "is": best, "oos": oos}
                    else:
                        verdict = "🎉 OVERRIDE ÖNERİSİ"
                        chosen = {"tf": tf, "code": code, "keep_live": False,
                                  "tp": best["tp"], "sl": best["sl"], "is": best, "oos": oos}
                        recommendations.append(chosen)

                live_txt = f" | canlı kademe: PF {live_r['pf']:.2f}, Net {live_r['net']:+.2f}%, WR {live_r['wr']:.1f}%" if live_r else ""
                print(f"\n  [{label} @ {tf}]")
                print(f"    IS en iyi: TP %{best['tp']}/SL %{best['sl']} → {best['trades']} işlem, WR {best['wr']:.1f}%, "
                      f"PF {best['pf']:.2f}, Net {best['net']:+.2f}%, {best['coins_pos']}/{best['coins']} coin{live_txt}")
                print(f"    → {verdict}")
            else:
                print(f"\n  [{label} @ {tf}] IS'te ≥20 işlem + Net>0 + ≥3 coin şartını sağlayan TP/SL yok → RED")

    print("\n" + "=" * 105)
    print("  📋 SONUÇ ÖZETİ")
    print("=" * 105)
    if not recommendations:
        print("Önerilen TP/SL override yok — mevcut kademeler veya strateji-TF eşleşmesi yeterli.")
    else:
        for r in recommendations:
            if r.get("keep_live"):
                print(f"  ✔ {r['code']} @ {r['tf']}: mevcut kademe korunuyor (OOS Net {r['oos']['net']:+.2f}%)")
            else:
                print(f"  🎯 {r['code']} @ {r['tf']}: TP %{r['tp']} / SL %{r['sl']} "
                      f"(IS PF {r['is']['pf']:.2f}, OOS PF {r['oos']['pf']:.2f}, OOS Net {r['oos']['net']:+.2f}%)")

    out_file = Path("outputs/spot_tpsl_optimizer.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"meta": {"n_configs": n_configs, "grid": GRID, "live_default": LIVE_DEFAULT},
                   "recommendations": recommendations}, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n💾 Log: {out_file}")
    return recommendations

if __name__ == "__main__":
    run_optimizer()
