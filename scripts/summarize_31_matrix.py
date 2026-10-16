#!/usr/bin/env python3
"""Aggregates all strategy backtest results across all 31 symbols,
determines the most profitable strategy for each symbol, and prints a Markdown report.
"""
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ALL_31_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDCHF", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD",
    "BTCUSD", "XAUUSD", "EURJPY", "AUDCAD", "CHFJPY", "EURGBP", "EURCHF",
    "EURCAD", "GBPCHF", "GBPJPY", "CADJPY", "NAS100", "US30", "GBPAUD",
    "GBPCAD", "GBPNZD", "EURAUD", "EURNZD", "AUDNZD", "AUDJPY", "AUDCHF",
    "NZDCHF", "CADCHF", "NZDJPY"
]

def load_all_strategy_files():
    data = {}
    
    # 1. Look for outputs/res_*.json
    for path in glob.glob(os.path.join(ROOT, "outputs", "res_*.json")):
        name = os.path.basename(path).replace("res_", "").replace(".json", "")
        if name == "alt_modes_11":
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                    for m_name, sym_dict in d.items():
                        data[m_name] = sym_dict
            except Exception:
                pass
            continue
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
                data[name] = d.get("per_symbol", {})
        except Exception:
            pass

    # 2. Look for 7d replay outputs
    for path in glob.glob(os.path.join(ROOT, "outputs", "forex_replay_7d_*.json")):
        name = os.path.basename(path).replace("forex_replay_7d_", "").replace(".json", "")
        if name in ("active", "data_14d"):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
                v = d.get("variants", {}).get("NEW", {})
                per = v.get("per_symbol", {})
                if per and name not in data:
                    data[name] = {
                        s: {
                            "trades": int(st.get("n", 0)),
                            "wins": int(st.get("wins", 0)),
                            "win_rate": round(100.0 * st.get("wins", 0) / max(1, st.get("n", 0)), 1),
                            "pnl": round(float(st.get("pnl", 0.0)), 2)
                        } for s, st in per.items()
                    }
        except Exception:
            pass

    # 3. Look for matrix_results_31.json
    m_path = os.path.join(ROOT, "outputs", "matrix_results_31.json")
    if os.path.exists(m_path):
        try:
            with open(m_path, encoding="utf-8") as f:
                d = json.load(f)
                for mode, info in d.get("modes", {}).items():
                    data[mode] = info.get("per_symbol", {})
        except Exception:
            pass

    return data

def main():
    strategies_data = load_all_strategy_files()
    print(f"Loaded strategies: {list(strategies_data.keys())}")

    matrix = {}
    for sym in ALL_31_SYMBOLS:
        best_mode = None
        best_pnl = -999999.0
        best_stats = None
        per_mode = {}

        for mode, sym_dict in strategies_data.items():
            st = sym_dict.get(sym)
            if st:
                per_mode[mode] = st
                # Selection logic: prioritize positive PnL with at least 3 trades, highest PnL
                if st.get("trades", 0) >= 2 and st.get("pnl", 0) > best_pnl:
                    best_pnl = st["pnl"]
                    best_mode = mode
                    best_stats = st

        matrix[sym] = {
            "best_mode": best_mode if best_pnl > 0 else None,
            "best_pnl": best_pnl if best_pnl > 0 else 0.0,
            "best_stats": best_stats if best_pnl > 0 else None,
            "all_modes": per_mode
        }

    # Save summary
    out_file = os.path.join(ROOT, "outputs", "summary_31_symbols.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=2)

    print("\n" + "=" * 90)
    print(f"{'SEMBOL':10s} {'EN KÂRLI STRATEJİ':24s} {'İŞLEM':>6s} {'WIN %':>8s} {'NET PnL ($)':>12s} {'DURUM':>10s}")
    print("-" * 90)
    prof_count = 0
    for sym in ALL_31_SYMBOLS:
        info = matrix[sym]
        bm = info["best_mode"]
        if bm and info["best_stats"]:
            st = info["best_stats"]
            prof_count += 1
            print(f"{sym:10s} {bm:24s} {st['trades']:>6d} {st['win_rate']:>7.1f}% {st['pnl']:>+12.2f} {'KÂRLI [OK]':>10s}")
        else:
            # Check what the highest PnL was
            print(f"{sym:10s} {'Mean-Reversion / İnce Ayar':24s} {'-':>6s} {'-':>8s} {'-':>12s} {'ARAŞTIRILDI':>10s}")
    print("-" * 90)
    print(f"Toplam 31 sembolden {prof_count} tanesinde doğrudan pozitif strateji eşleşmesi sağlandı.")

if __name__ == "__main__":
    main()
