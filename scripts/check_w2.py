import json

def check():
    b = json.load(open("outputs/report_week_2.json", encoding="utf-8"))["variants"]["NEW"]["per_symbol"]
    n = json.load(open("outputs/report_news_week_2.json", encoding="utf-8"))["variants"]["NEW"]["per_symbol"]
    all_syms = sorted(set(list(b.keys()) + list(n.keys())))
    print(f"{'Sembol':<10} | {'Base PnL':<10} | {'News PnL':<10} | {'Fark ($)':<10}")
    print("-" * 50)
    for s in all_syms:
        bp = b.get(s, {}).get("pnl", 0.0)
        np = n.get(s, {}).get("pnl", 0.0)
        diff = np - bp
        if abs(diff) > 20:
            print(f"{s:<10} | ${bp:>8.2f} | ${np:>8.2f} | ${diff:>8.2f}")

if __name__ == "__main__":
    check()
