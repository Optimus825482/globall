#!/usr/bin/env python3
"""A2 (seans-VWAP-z reversion) adayının dürüstlük testi: gün-gün tutarlılık,
maliyet duyarlılığı ve işlem/yön dağılımı."""
import datetime as dt
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import scalp_strategy_research as S  # noqa: E402

data = json.load(open(os.path.join(ROOT, "outputs", "scalp_cache_32d_5m.json"), encoding="utf-8"))

for sym in ("XAUUSD", "BTCUSD"):
    bars = data[sym]; spec = S.SPECS[sym]
    pip = spec["pip"]
    entries, ctx = S.strat_vwap_reversion(bars, sess_start=(7, 16), z_thr=2.0, adx_max=25.0)
    print(f"\n=== {sym}: A2 VWAP-z2.0 ADX<25 07-16 UTC — {len(entries)} ham sinyal ===")
    # maliyet duyarlılığı
    print("  maliyet duyarlılığı:")
    for spr in (0.0, spec["spread_pips"] / 2, spec["spread_pips"], spec["spread_pips"] * 2):
        tr = S.simulate(entries, ctx["c"], ctx["h"], ctx["l"], ctx["ts"], pip, spr,
                        sl_atr=1.2, tp_mode="rr", atr_series=ctx["atr"], max_hold=24, tp_rr=1.5)
        s = S.trade_stats(tr, f"spread={spr:.1f}pip")
        if s.get("n"):
            print(f"    spread={spr:5.2f}pip → n={s['n']:3d} net={s['net_pips']:+8.1f}pip "
                  f"exp={s['exp_pips']:+6.2f}pip PF={s['pf']:.2f} WR=%{s['wr']}")
    # gün-gün (gerçek spread)
    tr = S.simulate(entries, ctx["c"], ctx["h"], ctx["l"], ctx["ts"], pip, spec["spread_pips"],
                    sl_atr=1.2, tp_mode="rr", atr_series=ctx["atr"], max_hold=24, tp_rr=1.5)
    by_day = {}
    for t in tr:
        d = dt.datetime.utcfromtimestamp(ctx["ts"][t["i"]]).strftime("%m-%d")
        by_day.setdefault(d, []).append(t["pips"])
    days_sorted = sorted(by_day)
    pos = sum(1 for d in days_sorted if sum(by_day[d]) > 0)
    print(f"  gün-gün: {len(days_sorted)} işlem-günü, pozitif {pos} "
          f"({100*pos/max(len(days_sorted),1):.0f}%)")
    row = "   "
    for d in days_sorted:
        row += f" {d}:{sum(by_day[d]):+.0f}"
    print(row)
    # yön dağılımı
    longs = [t for t in tr if t["dir"] == 1]; shorts = [t for t in tr if t["dir"] == -1]
    def bl(lst, nm):
        if not lst:
            print(f"    {nm}: yok"); return
        p = np.array([t["pips"] for t in lst])
        print(f"    {nm}: n={len(p):3d} net={p.sum():+8.1f}pip exp={p.mean():+6.2f} WR=%{100*(p>0).mean():.0f}")
    bl(longs, "LONG "); bl(shorts, "SHORT")
