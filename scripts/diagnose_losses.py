import json
import sys
from collections import Counter, defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def main():
    reasons = Counter()
    by_sym_reason = defaultdict(Counter)
    by_sym_pnl = defaultdict(lambda: defaultdict(float))
    
    # Also check avg win vs avg loss per symbol
    sym_wins = defaultdict(list)
    sym_losses = defaultdict(list)

    for wid in range(1, 5):
        closed = json.load(open(f"outputs/report_opt_week_{wid}.json", encoding="utf-8"))["variants"]["NEW"]["closed"]
        for c in closed:
            r = f"{c['reason']}_trail={c.get('trail', False)}"
            reasons[r] += 1
            sym = c["symbol"]
            by_sym_reason[sym][r] += 1
            by_sym_pnl[sym][r] += c["pnl_usd"]
            if c["pnl_usd"] >= 0:
                sym_wins[sym].append(c["pnl_usd"])
            else:
                sym_losses[sym].append(c["pnl_usd"])

    print("=== GENEL ÇIKIŞ NEDENLERİ ===")
    for k, v in reasons.most_common():
        tot_p = sum(by_sym_pnl[s][k] for s in by_sym_pnl)
        print(f"  {k:<25}: {v:>5} işlem | Toplam PnL: ${tot_p:>10.2f} | Ort: ${tot_p/v:>7.2f}")

    print("\n=== SEMBOL BAZLI KAZANÇ / KAYIP ASİMETRİSİ ===")
    print(f"{'Sembol':<10} | {'W/L':<9} | {'WR%':<6} | {'Ort Kazanç':<11} | {'Ort Kayıp':<11} | {'R:R Gerçek':<10} | {'Net PnL'}")
    print("-" * 80)
    all_syms = sorted(set(list(sym_wins.keys()) + list(sym_losses.keys())),
                      key=lambda s: sum(sym_wins[s]) + sum(sym_losses[s]))
    for s in all_syms:
        w = sym_wins[s]
        l = sym_losses[s]
        n = len(w) + len(l)
        wr = len(w) / n * 100 if n else 0
        avg_w = sum(w) / len(w) if w else 0
        avg_l = sum(l) / len(l) if l else 0
        rr = abs(avg_w / avg_l) if avg_l != 0 else 0
        net = sum(w) + sum(l)
        print(f"{s:<10} | {len(w):>3}/{len(l):<4} | %{wr:>4.1f} | +${avg_w:>8.2f} | -${abs(avg_l):>8.2f} | {rr:>9.2f}x | ${net:>9.2f}")

    print("\n=== GÜNLÜK DETAYLI PERFORMANS VE NEGATİF GÜNLERİN SEMBOL DAĞILIMI ===")
    import datetime
    for wid in range(1, 5):
        rep = json.load(open(f"outputs/report_opt_week_{wid}.json", encoding="utf-8"))["variants"]["NEW"]
        ds = rep.get("daily_stats", {})
        closed = rep.get("closed", [])
        by_day_sym = defaultdict(lambda: defaultdict(float))
        by_day_sym_n = defaultdict(lambda: defaultdict(int))
        for c in closed:
            if c.get("closed_ts"):
                d = datetime.datetime.fromtimestamp(c["closed_ts"], datetime.timezone.utc).strftime("%Y-%m-%d")
                by_day_sym[d][c["symbol"]] += c["pnl_usd"]
                by_day_sym_n[d][c["symbol"]] += 1
        print(f"\n--- HAFTA {wid} (Net: ${rep.get('net_pnl_usd', 0):+.2f}) ---")
        for d, st in sorted(ds.items()):
            syms_sorted = sorted(by_day_sym[d].items(), key=lambda x: x[1])
            worst_str = ", ".join(f"{k}:{v:+.1f}$({by_day_sym_n[d][k]})" for k, v in syms_sorted[:4])
            best_str = ", ".join(f"{k}:{v:+.1f}$({by_day_sym_n[d][k]})" for k, v in syms_sorted[-2:])
            status = "✅" if st["pnl"] >= 0 else "❌"
            print(f"  {status} {d} | İşlem: {st['trades']:>3} | WR: %{st['win_rate']:>4.1f} | PnL: ${st['pnl']:>+8.2f} | En Kötü: [{worst_str}] | En İyi: [{best_str}]")

    print("\n=== SAAT BAZLI PERFORMANS (UTC) ===")
    by_hour = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
    for wid in range(1, 5):
        closed = json.load(open(f"outputs/report_opt_week_{wid}.json", encoding="utf-8"))["variants"]["NEW"]["closed"]
        for c in closed:
            if c.get("closed_ts"):
                h = datetime.datetime.fromtimestamp(c["closed_ts"], datetime.timezone.utc).hour
                by_hour[h]["n"] += 1
                if c["pnl_usd"] >= 0:
                    by_hour[h]["w"] += 1
                by_hour[h]["pnl"] += c["pnl_usd"]
    for h in sorted(by_hour.keys()):
        st = by_hour[h]
        wr = st["w"] / st["n"] * 100 if st["n"] else 0
        print(f"  UTC {h:02d}:00 | İşlem: {st['n']:>4} | WR: %{wr:>4.1f} | Net PnL: ${st['pnl']:>+9.2f}")

    print("\n=== GÜN İÇİ ZİRVE (PEAK) vs GÜN SONU (CLOSE) PnL ANALİZİ ===")
    for wid in range(1, 5):
        closed = json.load(open(f"outputs/report_opt_week_{wid}.json", encoding="utf-8"))["variants"]["NEW"]["closed"]
        by_day_trades = defaultdict(list)
        for c in closed:
            if c.get("closed_ts"):
                d = datetime.datetime.fromtimestamp(c["closed_ts"], datetime.timezone.utc).strftime("%Y-%m-%d")
                by_day_trades[d].append(c)
        for d in sorted(by_day_trades.keys()):
            trades = sorted(by_day_trades[d], key=lambda x: x["closed_ts"])
            running = 0.0
            peak = 0.0
            trough = 0.0
            first_green_ts = None
            for t in trades:
                running += t["pnl_usd"]
                if running > peak:
                    peak = running
                if running < trough:
                    trough = running
                if running >= 15.0 and first_green_ts is None:
                    first_green_ts = datetime.datetime.fromtimestamp(t["closed_ts"], datetime.timezone.utc).strftime("%H:%M")
            print(f"  W{wid} {d} | Sonuç: ${running:>+8.2f} | Gün İçi Zirve: ${peak:>+8.2f} | Dip: ${trough:>+8.2f} | İlk +$15: {str(first_green_ts):<6} | İşlem: {len(trades)}")
            if peak <= 15.0:
                for t in trades[:12]:
                    hm = datetime.datetime.fromtimestamp(t["closed_ts"], datetime.timezone.utc).strftime("%H:%M")
                    print(f"      -> {hm} {t['symbol']:<8} {t['direction']:<4} lot={t['lots']} pnl=${t['pnl_usd']:+7.2f} reason={t['reason']} trail={t.get('trail')}")

if __name__ == "__main__":
    main()


