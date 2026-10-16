#!/usr/bin/env python3
"""Test additional modes (pullback, orb_filtered, squeeze_exp, squeeze, london_sign)
specifically on the 7 remaining symbols:
EURGBP, EURCHF, GBPCAD, EURAUD, AUDCHF, NZDCHF, CADCHF.
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

TARGET_7 = [
    "EURGBP", "EURCHF", "GBPCAD", "EURAUD", "AUDCHF", "NZDCHF", "CADCHF"
]

def main():
    forex.ATR_USE_WILDER = True
    cache_path = os.path.join(ROOT, "outputs", "forex_replay_31_m5.json")
    with open(cache_path, encoding="utf-8") as f:
        raw = json.load(f)
    data = {sym: [tuple(b) for b in bars] for sym, bars in raw.items() if sym in TARGET_7}
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
    modes = ["pullback", "orb_filtered", "squeeze_exp", "squeeze", "london_sign"]

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

        print(f"\n--- Testing mode: {m} on 7 symbols ---")
        rep = frb.run_replay(data, days=22, add_symbols=set(TARGET_7))
        new_v = rep.get("variants", {}).get("NEW", {})
        per_sym = new_v.get("per_symbol", {})
        results[m] = {
            s: {
                "trades": int(st.get("n", 0)),
                "wins": int(st.get("wins", 0)),
                "win_rate": round(100.0 * int(st.get("wins", 0)) / max(1, int(st.get("n", 0))), 1),
                "pnl": round(float(st.get("pnl", 0.0)), 2),
            }
            for s, st in per_sym.items()
        }
        for s, st in results[m].items():
            if st["pnl"] > 0:
                print(f"  >>> POSITIVE: {s} {m} PnL: +${st['pnl']:.2f} ({st['win_rate']}%, {st['trades']} trades)")

    out_file = os.path.join(ROOT, "outputs", "res_last_7_additional_modes.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 80)
    print(f"{'SEMBOL':10s} {'STRATEJİ':20s} {'İŞLEM':>6s} {'WIN %':>8s} {'NET PnL ($)':>12s}")
    print("-" * 80)
    for m, sym_dict in results.items():
        for sym, st in sym_dict.items():
            if st["trades"] > 0:
                pnl_str = f"+{st['pnl']:.2f}" if st['pnl'] > 0 else f"{st['pnl']:.2f}"
                print(f"{sym:10s} {m:20s} {st['trades']:>6d} {st['win_rate']:>7.1f}% {pnl_str:>12s}")

if __name__ == "__main__":
    main()
