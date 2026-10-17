import json
import os
import sys
import datetime
from typing import Dict, Any, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from app.routers import forex

# Load the merged 31 symbols dataset
cache_file = "outputs/forex_replay_all31_merged.json"
with open(cache_file, "r") as f:
    data = json.load(f)

print(f"Loaded {len(data)} symbols from {cache_file}")

# Cost pips per symbol
REAL_SPREADS = {
    "EURUSD": 0.8, "GBPUSD": 1.1, "USDJPY": 0.9, "USDCHF": 1.2, "AUDUSD": 1.0,
    "USDCAD": 1.2, "NZDUSD": 1.5, "AUDCAD": 2.0, "EURJPY": 1.8, "GBPJPY": 2.2,
    "CHFJPY": 2.5, "EURGBP": 1.4, "EURCHF": 1.8, "EURCAD": 2.0, "GBPCHF": 2.5,
    "CADJPY": 2.0, "GBPAUD": 3.0, "GBPCAD": 2.8, "GBPNZD": 3.8, "EURAUD": 2.5,
    "EURNZD": 3.5, "AUDNZD": 2.8, "AUDJPY": 2.0, "AUDCHF": 2.2, "NZDCHF": 2.5,
    "CADCHF": 2.2, "NZDJPY": 2.4, "XAUUSD": 1.2, "US30": 1.5, "NAS100": 1.5, "BTCUSD": 15.0
}

def get_cost_pips(sym: str, pip_val: float) -> float:
    spread = REAL_SPREADS.get(sym, 2.0)
    is_fx = len(sym) == 6 and sym[:3].isalpha() and sym[3:].isalpha()
    comm_pips = (7.0 / pip_val) if (is_fx and pip_val > 0) else 0.0
    return spread + comm_pips

print("\n--- SAMPLE COST & DYNAMIC LEVELS ---")
for test_sym in ["EURUSD", "AUDCAD", "GBPNZD", "NZDJPY", "XAUUSD", "US30", "BTCUSD"]:
    spec = forex.get_symbol_trading_specs(test_sym)
    cost = get_cost_pips(test_sym, spec["pip_val"])
    # 5M approx ATR
    sample_atr = 15.0 if "XAU" in test_sym else (25.0 if "30" in test_sym else (8.0 if "CAD" in test_sym else (12.0 if "NZD" in test_sym else 5.0)))
    dyn_sl = max(spec["sl_pips"], sample_atr * 1.8, cost * 4.0)
    dyn_tp = round(dyn_sl * 1.8, 1)
    be_trig = max(cost * 2.5, dyn_sl * 0.45)
    be_lock = cost + 1.0
    print(f"{test_sym:8s} | Cost: {cost:4.1f}p | Old SL: {spec['sl_pips']:4.1f}p -> New Dyn SL: {dyn_sl:4.1f}p | New TP: {dyn_tp:4.1f}p | BE Trig: {be_trig:4.1f}p | BE Lock: {be_lock:4.1f}p")
