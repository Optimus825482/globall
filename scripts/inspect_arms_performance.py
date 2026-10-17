import json

total_arms = {}
for w in (1, 2, 3, 4):
    rep = json.load(open(f'outputs/report_opt_week_{w}.json'))
    nv = rep['variants']['NEW']
    closed = nv['closed']
    arm_stats = {}
    for t in closed:
        arm = t.get('entry_source', 'classic')
        st = arm_stats.setdefault(arm, {'n': 0, 'wins': 0, 'pnl': 0.0})
        st['n'] += 1
        if t['pnl_usd'] >= 0:
            st['wins'] += 1
        st['pnl'] = round(st['pnl'] + t['pnl_usd'], 2)
        
        tot = total_arms.setdefault(arm, {'n': 0, 'wins': 0, 'pnl': 0.0})
        tot['n'] += 1
        if t['pnl_usd'] >= 0:
            tot['wins'] += 1
        tot['pnl'] = round(tot['pnl'] + t['pnl_usd'], 2)
        
    print(f"=== Week {w} Arms ===")
    for arm, s in sorted(arm_stats.items()):
        wr = round(100.0 * s['wins'] / s['n'], 1) if s['n'] else 0.0
        print(f"  {arm:18s} n:{s['n']:3d} wr:%{wr:4.1f} pnl:${s['pnl']:7.2f}")

print("\n=== TOTAL 4-WEEK COMBINED ARMS ===")
for arm, s in sorted(total_arms.items(), key=lambda x: -x[1]['pnl']):
    wr = round(100.0 * s['wins'] / s['n'], 1) if s['n'] else 0.0
    print(f"  {arm:18s} n:{s['n']:3d} wr:%{wr:4.1f} pnl:${s['pnl']:7.2f}")
