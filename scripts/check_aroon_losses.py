import json
import datetime

with open('outputs/report_opt_week_1.json', 'r') as f:
    rep = json.load(f)

data = json.load(open('outputs/forex_replay_all31_merged.json'))

import sys
sys.path.insert(0, '.')
from scripts.forex_replay_backtest import _aroon_osc_series

closed = rep['variants']['NEW']['closed']
print("Checking Aroon Osc for losing trades:")
for t in closed:
    if t['pnl_usd'] < 0:
        sym = t['symbol']
        bars = data.get(sym, [])
        c_ts = t['closed_ts']
        # find bar index
        bar_idx = None
        for i, b in enumerate(bars):
            if b[0] >= c_ts:
                bar_idx = i
                break
        if bar_idx and bar_idx >= 14:
            aroon_vals = _aroon_osc_series(bars[:bar_idx+1], 14)
            aroon_val = aroon_vals[-1]
            dt = datetime.datetime.fromtimestamp(c_ts, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
            print(f"{dt} {sym:7s} {t['direction']:4s} pnl:{t['pnl_usd']:6.2f} aroon:{aroon_val:5.1f}")
