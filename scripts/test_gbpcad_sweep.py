import json, os, sys
ROOT = r'd:\PROJELLER\globall'
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'backend'))
import scripts.forex_replay_backtest as frb
from backend.app.routers import forex

forex.ATR_USE_WILDER = True
with open('outputs/forex_replay_31_m5.json', encoding='utf-8') as f:
    raw = json.load(f)

# Save the real base function once
_real_orig_specs = forex.get_symbol_trading_specs

remaining = ['EURAUD', 'EURGBP', 'AUDCHF', 'CADCHF', 'NZDCHF']

for sym in remaining:
    data = {sym: [tuple(b) for b in raw[sym]]}
    frb.REPLAY_PIP_VAL_OVERRIDE = frb._compute_pip_val_overrides(data)
    
    def _sp(s, **kw):
        spec = dict(_real_orig_specs(s, **kw))
        if s in frb.REPLAY_PIP_VAL_OVERRIDE:
            spec['pip_val'] = frb.REPLAY_PIP_VAL_OVERRIDE[s]
        return spec
    forex.get_symbol_trading_specs = _sp

    frb.TUN_SKIP_OLD = True
    frb.TUN_ENTRY_MODE = 'london_breakout'

    print(f"\n=== Testing {sym} London Breakout Sweep ===")
    best_pnl = -999999.0
    best_line = None
    for frac in [0.35, 0.4, 0.5]:
        for tp_r in [1.2, 1.5, 2.0, 2.5]:
            frb.TUN_LB_SL_BOX_FRAC = frac
            frb.TUN_LB_TP_R = tp_r
            frb.LB_STATE.clear()
            frb.MODE_DAY_STATE.clear()
            rep = frb.run_replay(data, days=22, add_symbols={sym})
            v = rep['variants']['NEW']['per_symbol'][sym]
            n = v['n']
            w = v['wins']
            pnl = v['pnl']
            wr = 100.0 * w / max(1, n)
            pnl_str = f"+{pnl:.2f}" if pnl > 0 else f"{pnl:.2f}"
            line = f"frac={frac} tp_r={tp_r} -> trades={n} win_rate={wr:.1f}% PnL: ${pnl_str}"
            if pnl > best_pnl:
                best_pnl = pnl
                best_line = line
            if pnl > 0:
                print(f"  >>> POSITIVE: {line}")
    print(f"  BEST for {sym}: {best_line}")
