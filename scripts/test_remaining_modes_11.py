#!/usr/bin/env python3
"""Test alternative modes (bb_bandwalk, tokyo_fix, reopen_fade, nr7, donchian_pure)
specifically on the 11 challenging symbols.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import scripts.forex_replay_backtest as frb
from backend.app.routers import forex

TARGET_11 = [
    "EURUSD", "USDJPY", "EURJPY", "CHFJPY", "EURGBP",
    "EURCHF", "GBPCAD", "EURAUD", "AUDCHF", "NZDCHF", "CADCHF"
]

def main():
    forex.ATR_USE_WILDER = True
    cache_path = os.path.join(ROOT, "outputs", "forex_replay_31_m5.json")
    with open(cache_path, encoding="utf-8") as f:
        raw = json.load(f)
    data = {sym: [tuple(b) for b in bars] for sym, bars in raw.items() if sym in TARGET_11}
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
    modes = ["bb_bandwalk", "tokyo_fix", "reopen_fade", "nr7", "donchian_pure"]

    results = {}
    for m in modes:
        frb.TUN_ENTRY_MODE = m
        frb.MODE_DAY_STATE.clear()
        frb.LB_STATE.clear()
        frb._SR_ST_CACHE.clear()
        frb._SR_RSI_CACHE.clear()
        frb._SR_ATR_CACHE.clear()
        frb._SQZ_KC_CACHE.clear()
        frb._HTF_EMA_STATE.clear()
        frb._ADR_CACHE.clear()

        rep = frb.run_replay(data, days=22, add_symbols=set(TARGET_11))
        new_v = rep.get("variants", {}).get("NEW", {})
        per_sym = new_v.get("per_symbol", {})
        results[m] = {
            s: {
                "trades": int(st.get("n", 0)),
                "wins": int(st.get("wins", 0)),
                "win_rate": round(100.0 * st.get("wins", 0) / max(1, st.get("n", 0)), 1),
                "pnl": round(float(st.get("pnl", 0.0)), 2)
            } for s, st in per_sym.items() if st.get("n", 0) > 0
        }

    out_file = os.path.join(ROOT, "outputs", "res_alt_modes_11.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 80)
    print("POZİTİF SONUÇLAR (11 Sembol):")
    print("=" * 80)
    for m, sym_dict in results.items():
        pos = {s: info for s, info in sym_dict.items() if info["pnl"] > 0}
        if pos:
            print(f"\n--- Strateji: {m} ---")
            for s, info in sorted(pos.items(), key=lambda kv: -kv[1]["pnl"]):
                print(f"  {s:8s} n={info['trades']:3d} WR={info['win_rate']:5.1f}% PnL=${info['pnl']:+6.2f}")

if __name__ == "__main__":
    main()
