#!/usr/bin/env python3
"""Run a single strategy mode on all 31 symbols from cache and save per-symbol results."""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import scripts.forex_replay_backtest as frb
from backend.app.routers import forex

ALL_31_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDCHF", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD",
    "BTCUSD", "XAUUSD", "EURJPY", "AUDCAD", "CHFJPY", "EURGBP", "EURCHF",
    "EURCAD", "GBPCHF", "GBPJPY", "CADJPY", "NAS100", "US30", "GBPAUD",
    "GBPCAD", "GBPNZD", "EURAUD", "EURNZD", "AUDNZD", "AUDJPY", "AUDCHF",
    "NZDCHF", "CADCHF", "NZDJPY"
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    forex.ATR_USE_WILDER = True
    cache_path = os.path.join(ROOT, "outputs", "forex_replay_31_m5.json")
    with open(cache_path, encoding="utf-8") as f:
        raw = json.load(f)
    data = {sym: [tuple(b) for b in bars] for sym, bars in raw.items()}
    frb.REPLAY_PIP_VAL_OVERRIDE = frb._compute_pip_val_overrides(data)
    if frb.REPLAY_PIP_VAL_OVERRIDE:
        _orig_specs = forex.get_symbol_trading_specs
        def _specs_with_override(sym, **kw):
            s = dict(_orig_specs(sym, **kw))
            ov = frb.REPLAY_PIP_VAL_OVERRIDE.get(str(sym).upper())
            if ov:
                s["pip_val"] = ov
            return s
        forex.get_symbol_trading_specs = _specs_with_override

    frb.TUN_SKIP_OLD = True
    frb.TUN_ENTRY_MODE = args.mode
    frb.MODE_DAY_STATE.clear()
    frb.LB_STATE.clear()
    frb._SR_ST_CACHE.clear()
    frb._SR_RSI_CACHE.clear()
    frb._SR_ATR_CACHE.clear()
    frb._SQZ_KC_CACHE.clear()
    frb._HTF_EMA_STATE.clear()
    frb._ADR_CACHE.clear()

    t0 = time.time()
    rep = frb.run_replay(data, days=22, add_symbols=set(ALL_31_SYMBOLS))
    elapsed = time.time() - t0

    new_v = rep.get("variants", {}).get("NEW", {})
    per_sym = new_v.get("per_symbol", {})

    results = {}
    for sym, st in per_sym.items():
        n = int(st.get("n", 0))
        wins = int(st.get("wins", 0))
        pnl = float(st.get("pnl", 0.0))
        wr = (wins / n * 100.0) if n > 0 else 0.0
        results[sym] = {
            "trades": n,
            "wins": wins,
            "win_rate": round(wr, 1),
            "pnl": round(pnl, 2),
        }

    out_data = {
        "mode": args.mode,
        "elapsed": round(elapsed, 1),
        "total_trades": new_v.get("trades", 0),
        "win_rate": new_v.get("win_rate", 0),
        "net_pnl": new_v.get("net_pnl_usd", 0),
        "per_symbol": results
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2)
    print(f"[OK] Mode {args.mode} completed in {elapsed:.1f}s -> {args.out}")

if __name__ == "__main__":
    main()
