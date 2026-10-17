import json
import os

WEEKS_META = [
    (1, "Hafta 1 (21 - 27 Eylul 2026)"),
    (2, "Hafta 2 (28 Eylul - 04 Ekim 2026)"),
    (3, "Hafta 3 (05 - 11 Ekim 2026)"),
    (4, "Hafta 4 (12 - 17 Ekim 2026)"),
]

def main():
    print("=" * 105)
    print("EKONOMİK TAKVİM SİSTEMİ ÖNCESİ VE SONRASI 1 AYLIK HAFTALIK PERFORMANS KARŞILAŞTIRMASI")
    print("=" * 105)
    print(f"{'Hafta':<30} | {'Takvimsiz İşlem':<15} | {'Takvimli İşlem':<15} | {'Takvimsiz Net':<14} | {'Takvimli Net':<14} | {'Net Fark ($)':<12} | {'WR Değişimi'}")
    print("-" * 125)

    tot_b_trades = 0
    tot_n_trades = 0
    tot_b_pnl = 0.0
    tot_n_pnl = 0.0
    tot_b_wins = 0
    tot_n_wins = 0

    blocked_by_news_total = 0

    for wid, label in WEEKS_META:
        b_file = f"outputs/report_week_{wid}.json"
        n_file = f"outputs/report_news_week_{wid}.json"

        if not os.path.exists(b_file) or not os.path.exists(n_file):
            print(f"Eksik dosya: {b_file} veya {n_file}")
            continue

        with open(b_file, "r", encoding="utf-8") as f:
            b_rep = json.load(f)
        with open(n_file, "r", encoding="utf-8") as f:
            n_rep = json.load(f)

        bv = b_rep.get("variants", {}).get("NEW", {})
        nv = n_rep.get("variants", {}).get("NEW", {})

        b_trades = bv.get("trades", 0)
        n_trades = nv.get("trades", 0)
        b_wr = bv.get("win_rate", 0.0)
        n_wr = nv.get("win_rate", 0.0)
        b_pnl = bv.get("net_pnl_usd", 0.0)
        n_pnl = nv.get("net_pnl_usd", 0.0)
        diff = n_pnl - b_pnl

        tot_b_trades += b_trades
        tot_n_trades += n_trades
        tot_b_pnl += b_pnl
        tot_n_pnl += n_pnl
        tot_b_wins += int(round(b_trades * b_wr / 100.0))
        tot_n_wins += int(round(n_trades * n_wr / 100.0))

        # Check blocked events
        gate_attr = n_rep.get("gate_attribution", {})
        news_oppose = gate_attr.get("NEWS_OPPOSE", {})
        blocked_by_news = news_oppose.get("blocked", 0)
        blocked_by_news_total += blocked_by_news

        diff_str = f"+${diff:.2f}" if diff > 0 else f"-${abs(diff):.2f}"
        wr_diff = n_wr - b_wr
        wr_diff_str = f"+%{wr_diff:.1f}" if wr_diff >= 0 else f"-%{abs(wr_diff):.1f}"

        print(f"{label:<30} | {b_trades:>15} | {n_trades:>15} | ${b_pnl:>12.2f} | ${n_pnl:>12.2f} | {diff_str:>12} | %{b_wr:.1f} -> %{n_wr:.1f} ({wr_diff_str})")

    print("-" * 125)
    tot_diff = tot_n_pnl - tot_b_pnl
    tot_diff_str = f"+${tot_diff:.2f}" if tot_diff > 0 else f"-${abs(tot_diff):.2f}"
    tot_b_wr = (tot_b_wins / tot_b_trades * 100.0) if tot_b_trades > 0 else 0.0
    tot_n_wr = (tot_n_wins / tot_n_trades * 100.0) if tot_n_trades > 0 else 0.0
    tot_wr_diff = tot_n_wr - tot_b_wr
    tot_wr_diff_str = f"+%{tot_wr_diff:.1f}" if tot_wr_diff >= 0 else f"-%{abs(tot_wr_diff):.1f}"

    print(f"{'TOPLAM / BİRLEŞİK':<30} | {tot_b_trades:>15} | {tot_n_trades:>15} | ${tot_b_pnl:>12.2f} | ${tot_n_pnl:>12.2f} | {tot_diff_str:>12} | %{tot_b_wr:.1f} -> %{tot_n_wr:.1f} ({tot_wr_diff_str})")
    print(f"\n[KAPI BİLGİSİ] Ekonomik Takvim Tarafından Engellenen Karşıt Yönlü Sinyal Sayısı: {blocked_by_news_total} adet")

if __name__ == "__main__":
    main()
