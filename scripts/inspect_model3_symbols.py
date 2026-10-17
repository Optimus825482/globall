import json
from collections import defaultdict

def main():
    agg = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0, "gw": 0.0, "gl": 0.0})
    for wid in range(1, 5):
        f = f"outputs/report_opt_week_{wid}.json"
        d = json.load(open(f, "r", encoding="utf-8"))["variants"]["NEW"]["per_symbol"]
        for sym, rec in d.items():
            agg[sym]["trades"] += rec.get("n", 0)
            agg[sym]["wins"] += rec.get("wins", 0)
            agg[sym]["pnl"] += rec.get("pnl", 0.0)
            agg[sym]["gw"] += rec.get("gw", 0.0)
            agg[sym]["gl"] += rec.get("gl", 0.0)

    sorted_syms = sorted(agg.items(), key=lambda x: x[1]["pnl"], reverse=True)
    print("=" * 75)
    print("MODEL 3 (OPTİMİZE TAKVİM KALKANI) 1 AYLIK SEMBOL PERFORMANS SIRALAMASI")
    print("=" * 75)
    print(f"{'Sembol':<12} | {'İşlem':<6} | {'Win %':<8} | {'Brüt Kâr':<10} | {'Brüt Zarar':<12} | {'Net PnL ($)'}")
    print("-" * 75)
    for s, r in sorted_syms:
        wr = (r["wins"] / r["trades"] * 100.0) if r["trades"] > 0 else 0.0
        print(f"{s:<12} | {r['trades']:>6} | %{wr:>6.1f} | ${r['gw']:>8.2f} | -${r['gl']:>9.2f} | ${r['pnl']:>10.2f}")

if __name__ == "__main__":
    main()
