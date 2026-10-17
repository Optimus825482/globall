import os
import sys
import json
import datetime
import subprocess
from typing import Dict, Any, List

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

WEEKS = [
    {
        "week_id": 1,
        "name": "Hafta 1 (21 Eyl - 27 Eyl)",
        "start": "2026-09-21",
        "end": "2026-09-28",
        "desc": "21-27 Eylul (Hafta sonu 26-27 Eyl BTCUSD)",
    },
    {
        "week_id": 2,
        "name": "Hafta 2 (28 Eyl - 04 Eki)",
        "start": "2026-09-28",
        "end": "2026-10-05",
        "desc": "28 Eyl - 04 Eki (Hafta sonu 03-04 Eki BTCUSD)",
    },
    {
        "week_id": 3,
        "name": "Hafta 3 (05 Eki - 11 Eki)",
        "start": "2026-10-05",
        "end": "2026-10-12",
        "desc": "05 Eki - 11 Eki (Hafta sonu 10-11 Eki BTCUSD)",
    },
    {
        "week_id": 4,
        "name": "Hafta 4 (12 Eki - 17 Eki)",
        "start": "2026-10-12",
        "end": "2026-10-17",
        "desc": "12 Eki - 17 Eki (Hafta sonu 17 Eki BTCUSD guncel)",
    },
]

def run_week(w: Dict[str, Any]) -> Dict[str, Any]:
    out_file = os.path.join(ROOT, "outputs", f"report_week_{w['week_id']}.json")
    cmd = [
        sys.executable,
        os.path.join(ROOT, "scripts", "forex_replay_backtest.py"),
        "--cache", os.path.join(ROOT, "outputs", "forex_replay_all31_merged.json"),
        "--start", w["start"],
        "--end", w["end"],
        "--all-symbols",
        "--combined",
        "--skip-old",
        "--st-filter",
        "--spec-atr",
        "--max-open", "6",
        "--cost-aware-exits",
        "--crypto-sl-mult", "1.5",
        "--be-trigger-atr-crypto", "0.50",
        "--no-tp-crypto",
        "--balance", "1000",
        "--htf-align",
        "--no-be",
        "--out", out_file,
    ]
    print(f"\n=======================================================")
    print(f"Koşuluyor: {w['name']} [{w['start']} -> {w['end']}]")
    print(f"Komut: {' '.join(cmd)}")
    print(f"=======================================================")
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print(f"HATA ({w['name']}):\n{p.stderr}")
        return {}
    
    if os.path.exists(out_file):
        with open(out_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def main():
    all_results = {}
    weekly_summaries = []
    
    for w in WEEKS:
        rep = run_week(w)
        all_results[f"week_{w['week_id']}"] = {
            "info": w,
            "report": rep
        }
        
        new_v = rep.get("variants", {}).get("NEW", {})
        trades = new_v.get("trades", 0)
        wr = new_v.get("win_rate", 0.0)
        net_pnl = new_v.get("net_pnl_usd", 0.0)
        end_eq = 1000.0 + net_pnl
        weekly_summaries.append({
            "week_id": w["week_id"],
            "name": w["name"],
            "trades": trades,
            "win_rate": wr,
            "net_pnl": net_pnl,
            "start_balance": 1000.0,
            "end_balance": end_eq,
            "max_dd": new_v.get("max_drawdown_usd", 0.0),
            "daily_stats": new_v.get("daily_stats", {}),
            "per_symbol": new_v.get("per_symbol", {}),
            "closed": new_v.get("closed", [])
        })

    # Save aggregated results
    summary_path = os.path.join(ROOT, "outputs", "monthly_weekly_backtest_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(weekly_summaries, f, ensure_ascii=False, indent=2)
        
    print("\n" + "=" * 80)
    print("1 AYLIK GERİYE DÖNÜK HAFTALIK ÖZET (HER HAFTA 1000$ İLE SIFIRDAN)")
    print("=" * 80)
    print(f"{'Hafta':30s} | {'İşlem':6s} | {'Kazanma %':9s} | {'Net PnL ($)':12s} | {'Bitiş Kasa ($)':14s}")
    print("-" * 80)
    total_trades = 0
    total_net = 0.0
    for ws in weekly_summaries:
        total_trades += ws["trades"]
        total_net += ws["net_pnl"]
        print(f"{ws['name']:30s} | {ws['trades']:6d} | %{ws['win_rate']:7.1f} | ${ws['net_pnl']:>+10.2f} | ${ws['end_balance']:>12.2f}")
    print("-" * 80)
    print(f"{'TOPLAM / BİRLEŞİK':30s} | {total_trades:6d} | {'-':>8s} | ${total_net:>+10.2f} | -")
    print(f"\nRapor kaydedildi: {summary_path}")

if __name__ == "__main__":
    main()
