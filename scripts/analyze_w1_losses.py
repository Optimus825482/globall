import json
import datetime

with open('outputs/report_opt_week_1.json', 'r') as f:
    d = json.load(f)

closed = d['variants']['NEW']['closed']
print('Total closed trades in Week 1:', len(closed))
loss_trades = [t for t in closed if t['pnl_usd'] < 0]
print(f'Total losing trades: {len(loss_trades)}')
for t in loss_trades:
    dt = datetime.datetime.fromtimestamp(t['closed_ts'], datetime.timezone.utc)
    print(f"{dt.strftime('%Y-%m-%d %H:%M')} {t['symbol']:7s} {t['direction']:4s} pnl:{t['pnl_usd']:6.2f} reason:{t['reason']}")
