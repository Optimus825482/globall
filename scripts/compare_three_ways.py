import json
import os

WEEKS_META = [
    (1, "Hafta 1 (21 - 27 Eylul)"),
    (2, "Hafta 2 (28 Eylul - 04 Ekim)"),
    (3, "Hafta 3 (05 - 11 Ekim)"),
    (4, "Hafta 4 (12 - 17 Ekim)"),
]

def main():
    print("=" * 115)
    print("3 MODELİN 1 AYLIK HAFTALIK PERFORMANS KARŞILAŞTIRMASI (Her Pazartesi $1,000 Reset)")
    print("=" * 115)
    print(f"{'Hafta':<28} | {'1. MODEL (Takvimsiz)':<20} | {'2. MODEL (+10 Bump)':<20} | {'3. MODEL (Optimize Kalkan)':<24} | {'Net Fark (3 vs 1)'}")
    print("-" * 115)

    tot_1_pnl = 0.0
    tot_2_pnl = 0.0
    tot_3_pnl = 0.0
    tot_1_trades = 0
    tot_2_trades = 0
    tot_3_trades = 0

    for wid, label in WEEKS_META:
        f1 = f"outputs/report_week_{wid}.json"
        f2 = f"outputs/report_news_week_{wid}.json"
        f3 = f"outputs/report_opt_week_{wid}.json"

        p1, t1, w1 = 0.0, 0, 0.0
        p2, t2, w2 = 0.0, 0, 0.0
        p3, t3, w3 = 0.0, 0, 0.0

        if os.path.exists(f1):
            v1 = json.load(open(f1, "r", encoding="utf-8")).get("variants", {}).get("NEW", {})
            p1, t1, w1 = v1.get("net_pnl_usd", 0.0), v1.get("trades", 0), v1.get("win_rate", 0.0)
        if os.path.exists(f2):
            v2 = json.load(open(f2, "r", encoding="utf-8")).get("variants", {}).get("NEW", {})
            p2, t2, w2 = v2.get("net_pnl_usd", 0.0), v2.get("trades", 0), v2.get("win_rate", 0.0)
        if os.path.exists(f3):
            v3 = json.load(open(f3, "r", encoding="utf-8")).get("variants", {}).get("NEW", {})
            p3, t3, w3 = v3.get("net_pnl_usd", 0.0), v3.get("trades", 0), v3.get("win_rate", 0.0)

        tot_1_pnl += p1
        tot_2_pnl += p2
        tot_3_pnl += p3
        tot_1_trades += t1
        tot_2_trades += t2
        tot_3_trades += t3

        diff_3_vs_1 = p3 - p1
        d_str = f"+${diff_3_vs_1:.2f}" if diff_3_vs_1 > 0 else f"-${abs(diff_3_vs_1):.2f}"

        col1 = f"${p1:>9.2f} (%{w1:.1f})"
        col2 = f"${p2:>9.2f} (%{w2:.1f})"
        col3 = f"${p3:>9.2f} (%{w3:.1f})"

        print(f"{label:<28} | {col1:<20} | {col2:<20} | {col3:<24} | {d_str}")

    print("-" * 115)
    tot_diff = tot_3_pnl - tot_1_pnl
    tot_d_str = f"+${tot_diff:.2f}" if tot_diff > 0 else f"-${abs(tot_diff):.2f}"
    print(f"{'TOPLAM / BİRLEŞİK':<28} | ${tot_1_pnl:>9.2f} ({tot_1_trades} t)   | ${tot_2_pnl:>9.2f} ({tot_2_trades} t)   | ${tot_3_pnl:>9.2f} ({tot_3_trades} t)          | {tot_d_str}")

if __name__ == "__main__":
    main()
