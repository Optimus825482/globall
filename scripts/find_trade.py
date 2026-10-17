import json, datetime
rep = json.load(open('outputs/report_opt_week_1.json'))
data = json.load(open('outputs/forex_replay_all31_merged.json'))
bars = data['AUDCAD']

for t in rep['variants']['NEW']['closed']:
    dt = datetime.datetime.fromtimestamp(t['closed_ts'], datetime.timezone.utc)
    if dt.strftime('%Y-%m-%d') == '2026-09-24':
        print(dt.strftime('%H:%M'), t)
