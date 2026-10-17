import json, datetime
data = json.load(open('outputs/forex_replay_all31_merged.json'))
bars = data['AUDCAD']

import sys
sys.path.insert(0, '.')
from backend.app.routers import forex

for i in range(len(bars)):
    dt = datetime.datetime.fromtimestamp(bars[i][0], datetime.timezone.utc)
    if dt.strftime('%Y-%m-%d %H:%M') == '2026-09-24 07:15':
        w = bars[i-50:i+1]
        closes = [b[4] for b in w]
        highs = [b[2] for b in w]
        lows = [b[3] for b in w]
        opens = [b[1] for b in w]
        tech = forex._compute_technical_indicators(closes, highs, lows, opens, 'AUDCAD')
        print("AUDCAD tech at 07:15:")
        for k in ['score', 'action', 'trend', 'rsi', 'macd', 'supertrend_dir', 'adx', 'ema21', 'ema50', 'ema200']:
            print(f"  {k}: {tech.get(k)}")
        break
