import json, datetime
rep = json.load(open('outputs/report_opt_week_1.json'))
print("Trades on 2026-09-24:")
for t in rep['variants']['NEW']['closed']:
    dt = datetime.datetime.fromtimestamp(t['closed_ts'], datetime.timezone.utc)
    if dt.strftime('%Y-%m-%d') == '2026-09-24':
        print(f"{dt.strftime('%H:%M')} {t['symbol']:7s} {t['direction']:4s} lots:{t['lots']:4.2f} pnl:{t['pnl_usd']:6.2f} {t['reason']} {t.get('entry_source')}")
