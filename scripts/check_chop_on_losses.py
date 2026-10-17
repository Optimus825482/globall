import json, datetime
import numpy as np

def compute_chop(highs, lows, closes, period=14):
    n = len(closes)
    if n < period + 1:
        return [50.0] * n
    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
    
    chop = [50.0] * n
    log_p = np.log10(period)
    for i in range(period, n):
        sum_tr = sum(tr[i - period + 1:i + 1])
        max_h = max(highs[i - period + 1:i + 1])
        min_l = min(lows[i - period + 1:i + 1])
        range_hl = max_h - min_l
        if range_hl > 0 and sum_tr > 0:
            c_val = 100.0 * (np.log10(sum_tr / range_hl) / log_p)
            chop[i] = round(float(c_val), 1)
    return chop

data = json.load(open('outputs/forex_replay_all31_merged.json'))
rep1 = json.load(open('outputs/report_opt_week_1.json'))
closed = rep1['variants']['NEW']['closed']

print("Checking CHOP index for Week 1 trades:")
chop_cache = {}
for sym in data:
    bars = data[sym]
    closes = [b[4] for b in bars]
    highs = [b[2] for b in bars]
    lows = [b[3] for b in bars]
    chop_cache[sym] = (compute_chop(highs, lows, closes, 14), [b[0] for b in bars])

high_chop_losses = 0
total_losses = 0
for t in closed:
    if t['pnl_usd'] < 0:
        total_losses += 1
        sym = t['symbol']
        c_ts = t['closed_ts']
        chop_vals, ts_list = chop_cache[sym]
        # find index
        idx = None
        for i, ts in enumerate(ts_list):
            if ts >= c_ts:
                idx = i
                break
        if idx and idx < len(chop_vals):
            c_val = chop_vals[idx]
            dt = datetime.datetime.fromtimestamp(c_ts, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
            is_chop = c_val >= 61.8
            if is_chop:
                high_chop_losses += 1
            print(f"{dt} {sym:7s} pnl:{t['pnl_usd']:6.2f} CHOP:{c_val:4.1f} {'[HIGH CHOP!]' if is_chop else ''}")

print(f"\nTotal losses: {total_losses}, Losses with CHOP >= 61.8: {high_chop_losses} ({100.0*high_chop_losses/total_losses:.1f}%)")
