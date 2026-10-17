import json
import os
import datetime
from collections import defaultdict

DAY_NAMES_TR = {
    0: "Pazartesi",
    1: "Salı",
    2: "Çarşamba",
    3: "Perşembe",
    4: "Cuma",
    5: "Cumartesi (Kripto)",
    6: "Pazar (Kripto)"
}

def get_category(sym):
    s = sym.upper()
    if s in ["XAUUSD", "GOLD"]:
        return "Altın"
    if s in ["US30", "USTEC", "NAS100", "NDX1.ETR", "DXCM.NAS", "JCDX.PAR", "GDX.NYSE", "GDXJ.NYSE"]:
        return "Endeks / ETF"
    if s in ["BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "XRPUSD", "DOGUSD", "ADAUSD", "LTCUSD", "BCHUSD", "DOTUSD", "LNKUSD", "UNIUSD", "AVXUSD", "XLMUSD", "XTZUSD", "KSMUSD", "POLUSD", "DATAUSD"]:
        return "Kripto"
    return "Forex"

import sys
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--news", action="store_true", help="Ekonomik takvimli raporlari analiz et")
    args = parser.parse_args()

    prefix = "report_news_week_" if args.news else "report_week_"
    title_suffix = " [EKONOMIK TAKVIM ETKISI]" if args.news else ""

    weeks = [
        {"id": 1, "label": f"Hafta 1 (21 - 27 Eylul 2026){title_suffix}", "file": f"outputs/{prefix}1.json", "start": "2026-09-21", "end": "2026-09-27"},
        {"id": 2, "label": f"Hafta 2 (28 Eylul - 04 Ekim 2026){title_suffix}", "file": f"outputs/{prefix}2.json", "start": "2026-09-28", "end": "2026-10-04"},
        {"id": 3, "label": f"Hafta 3 (05 - 11 Ekim 2026){title_suffix}", "file": f"outputs/{prefix}3.json", "start": "2026-10-05", "end": "2026-10-11"},
        {"id": 4, "label": f"Hafta 4 (12 - 17 Ekim 2026){title_suffix}", "file": f"outputs/{prefix}4.json", "start": "2026-10-12", "end": "2026-10-17"},
    ]

    all_data = []
    for w in weeks:
        if not os.path.exists(w["file"]):
            print(f"Eksik dosya: {w['file']}")
            continue
        with open(w["file"], "r", encoding="utf-8") as f:
            d = json.load(f)
            v = d.get("variants", {}).get("NEW", {})
            all_data.append((w, v))

    if len(all_data) < len(weeks):
        print(f"Henuz tum haftalar hazir degil ({len(all_data)}/{len(weeks)} hazir).")
        return

    print("=" * 80)
    print("1. HAFTALIK GENEL PERFORMANS OZETI (Her Pazartesi $1,000 Reset)")
    print("=" * 80)
    print(f"{'Hafta':<32} | {'Baslangic':<9} | {'Bitis':<9} | {'Net PnL':<10} | {'Getiri %':<8} | {'Islem':<5} | {'Win Rate':<8} | {'PF':<5} | {'Max DD':<9}")
    print("-" * 105)

    tot_trades = 0
    tot_pnl = 0.0
    tot_gw = 0.0
    tot_gl = 0.0
    tot_wins = 0

    weekly_summary_list = []

    for w, v in all_data:
        trades = v.get("trades", 0)
        wr = v.get("win_rate", 0.0)
        net_pnl = v.get("net_pnl_usd", 0.0)
        pf = v.get("profit_factor", 0.0)
        max_dd = v.get("max_drawdown_usd", 0.0)
        b_start = v.get("equity_start", 1000.0)
        b_end = v.get("balance", b_start + net_pnl)
        ret_pct = ((b_end - b_start) / b_start) * 100.0

        wins = int(round(trades * wr / 100.0))
        tot_trades += trades
        tot_wins += wins
        tot_pnl += net_pnl

        weekly_summary_list.append({
            "label": w["label"],
            "b_start": b_start,
            "b_end": b_end,
            "net_pnl": net_pnl,
            "ret_pct": ret_pct,
            "trades": trades,
            "wr": wr,
            "pf": pf,
            "max_dd": max_dd
        })

        print(f"{w['label']:<32} | ${b_start:<8.2f} | ${b_end:<8.2f} | ${net_pnl:<9.2f} | %{ret_pct:<7.1f} | {trades:<5} | %{wr:<7.1f} | {pf:<5.2f} | ${max_dd:<8.2f}")

    print("-" * 105)
    overall_wr = (tot_wins / tot_trades * 100.0) if tot_trades > 0 else 0.0
    print(f"{'TOPLAM / ORTALAMA':<32} | $1,000.00 | ----------- | ${tot_pnl:<9.2f} | -------  | {tot_trades:<5} | %{overall_wr:<7.1f} | ----- | --------")
    print("\n")

    # 2. GÜNLÜK ÖZET (Gün Gün, Hafta Sonu Kriptolar Ayrı)
    print("=" * 80)
    print("2. GÜN BAZINDA PERFORMANS ÖZETİ (Pazartesi -> Pazar)")
    print("=" * 80)
    print(f"{'Tarih':<10} | {'Gün':<18} | {'Hafta':<7} | {'İşlem':<5} | {'W/L':<7} | {'Win %':<6} | {'Brüt Kâr':<9} | {'Brüt Zarar':<10} | {'Net PnL':<10}")
    print("-" * 95)

    daily_rows = []
    for w, v in all_data:
        closed = v.get("closed", [])
        # group by date
        by_day = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "gw": 0.0, "gl": 0.0, "pnl": 0.0, "symbols": defaultdict(int)})
        for t in closed:
            ts = t.get("closed_ts", 0)
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            d_str = dt.strftime("%Y-%m-%d")
            pnl = t.get("pnl_usd", 0.0)
            sym = t.get("symbol", "")
            d_rec = by_day[d_str]
            d_rec["trades"] += 1
            d_rec["pnl"] += pnl
            d_rec["symbols"][sym] += 1
            if pnl > 0:
                d_rec["wins"] += 1
                d_rec["gw"] += pnl
            else:
                d_rec["losses"] += 1
                d_rec["gl"] += abs(pnl)

        for d_str in sorted(by_day.keys()):
            d_rec = by_day[d_str]
            dt = datetime.datetime.strptime(d_str, "%Y-%m-%d")
            weekday = dt.weekday()
            day_name = DAY_NAMES_TR.get(weekday, dt.strftime("%A"))
            wr = (d_rec["wins"] / d_rec["trades"] * 100.0) if d_rec["trades"] > 0 else 0.0
            daily_rows.append({
                "date": d_str,
                "day_name": day_name,
                "week": f"Hafta {w['id']}",
                "trades": d_rec["trades"],
                "wl": f"{d_rec['wins']}/{d_rec['losses']}",
                "wr": wr,
                "gw": d_rec["gw"],
                "gl": d_rec["gl"],
                "pnl": d_rec["pnl"]
            })
            print(f"{d_str:<10} | {day_name:<18} | Hafta {w['id']:<1} | {d_rec['trades']:<5} | {d_rec['wins']}/{d_rec['losses']:<5} | %{wr:<5.1f} | ${d_rec['gw']:<8.2f} | -${d_rec['gl']:<8.2f} | ${d_rec['pnl']:<9.2f}")

    print("\n")

    # 3. SEMBOL BAZINDA ÖZET
    print("=" * 80)
    print("3. SEMBOL BAZINDA KÜMÜLATİF PERFORMANS DAĞILIMI (Tüm Ay)")
    print("=" * 80)
    print(f"{'Sembol':<12} | {'Kategori':<12} | {'İşlem':<5} | {'W/L':<7} | {'Win %':<6} | {'Brüt Kâr':<9} | {'Brüt Zarar':<10} | {'Net PnL':<10}")
    print("-" * 85)

    symbol_agg = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "gw": 0.0, "gl": 0.0, "pnl": 0.0})
    for w, v in all_data:
        closed = v.get("closed", [])
        for t in closed:
            sym = t.get("symbol", "")
            pnl = t.get("pnl_usd", 0.0)
            rec = symbol_agg[sym]
            rec["trades"] += 1
            rec["pnl"] += pnl
            if pnl > 0:
                rec["wins"] += 1
                rec["gw"] += pnl
            else:
                rec["losses"] += 1
                rec["gl"] += abs(pnl)

    sorted_syms = sorted(symbol_agg.items(), key=lambda x: x[1]["pnl"], reverse=True)
    for sym, rec in sorted_syms:
        cat = get_category(sym)
        wr = (rec["wins"] / rec["trades"] * 100.0) if rec["trades"] > 0 else 0.0
        print(f"{sym:<12} | {cat:<12} | {rec['trades']:<5} | {rec['wins']}/{rec['losses']:<5} | %{wr:<5.1f} | ${rec['gw']:<8.2f} | -${rec['gl']:<8.2f} | ${rec['pnl']:<9.2f}")

    print("\n")

    # 4. HAFTA x SEMBOL x GÜN KIRILIMI
    print("=" * 80)
    print("4. HAFTA x SEMBOL x GÜN DETAYLI KIRILIM MATRİSİ")
    print("=" * 80)

    # Save all structured results to a final json
    output_summary = {
        "weeks": weekly_summary_list,
        "daily": daily_rows,
        "symbols": [{
            "symbol": sym,
            "category": get_category(sym),
            "trades": rec["trades"],
            "wins": rec["wins"],
            "losses": rec["losses"],
            "win_rate": round((rec["wins"] / rec["trades"] * 100.0), 1) if rec["trades"] > 0 else 0,
            "gw": round(rec["gw"], 2),
            "gl": round(rec["gl"], 2),
            "net_pnl": round(rec["pnl"], 2)
        } for sym, rec in sorted_syms],
        "total_pnl": round(tot_pnl, 2),
        "total_trades": tot_trades,
        "overall_win_rate": round(overall_wr, 1)
    }

    with open("outputs/monthly_detailed_analysis.json", "w", encoding="utf-8") as f:
        json.dump(output_summary, f, indent=2, ensure_ascii=False)
    print("Detayli analiz kaydedildi: outputs/monthly_detailed_analysis.json")

if __name__ == "__main__":
    main()
