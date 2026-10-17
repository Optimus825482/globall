import json, datetime
data = json.load(open('outputs/forex_replay_all31_merged.json'))
bars = data['AUDCAD']
import sys
sys.path.insert(0, '.')
from scripts.forex_replay_backtest import _aroon_osc_series
aroon = _aroon_osc_series(bars, 14)
for i, b in enumerate(bars):
    dt = datetime.datetime.fromtimestamp(b[0], datetime.timezone.utc)
    if dt.strftime('%Y-%m-%d') == '2026-09-24' and 6 <= dt.hour <= 8:
        print(f"{dt.strftime('%H:%M')} C:{b[4]} aroon:{aroon[i]}")
