#!/usr/bin/env python3
"""Kalibrasyon JSON'undan adayları kabul kriterlerine göre ele (analiz, karar değil)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "outputs", "btc_momentum_calibration_240d.json")
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)

print(f"meta: {data['meta']}\n")

rows = [r for h, lst in data["results"].items() for r in lst]


def wf_plus(r):
    return sum(1 for w in r["wf"] if (w.get("excess") or -9) > 0), len(r["wf"])


def summarize(label, sel):
    print(f"--- {label}: {len(sel)} aday ---")
    for r in sel[:15]:
        fr, tr, te = r["full"], r["train"], r["test"]
        wp, wt = wf_plus(r)
        print(f"  {r['direction']:5} gate={r['gate']:10} cost={r['cost']:12} H={r['horizon_h']:2}h "
              f"ATR<{r['thr']['atr']:.2f} r8<{r['thr']['ret8']:.1f} sl<{r['thr']['slope']:.2f} adx<{r['thr']['adx']:.0f} | "
              f"n={fr['n']:4d} net%={fr['sig_avg_net']:+.3f} base%={fr['base_avg']:+.3f} "
              f"ex%={fr['excess']:+.3f} retL={fr['ret_lift']} hitL={fr['hit_lift']} hit%={fr['hit']} "
              f"| TR ex={tr.get('excess')} TE ex={te.get('excess')} TE n={te.get('n')} WF+={wp}/{wt}")
    print()


# Kriter 1: hit_lift > 1.2 (briefteki sıkı) VE net>0 VE test ex>0 VE n>=50
strict = [r for r in rows if (r["full"].get("hit_lift") or 0) > 1.2
          and (r["full"].get("sig_avg_net") or -9) > 0
          and (r["test"].get("excess") or -9) > 0
          and r["full"]["n"] >= 50]
strict.sort(key=lambda r: (r["direction"] != "long", -(r["full"]["hit_lift"] or 0)))
summarize("SİKI: hit_lift>1.2 & net>0 & test_ex>0 & n>=50", strict)

# Kriter 2: getiri-lift (brief iskeleti) > 1.2 VE test_ex>0 VE n>=50 VE WF>=4/6
ret_ok = [r for r in rows if (r["full"].get("sig_avg_net") or -9) > 0
          and (r["test"].get("excess") or -9) > 0
          and r["full"]["n"] >= 50 and wf_plus(r)[0] >= 4]
ret_ok.sort(key=lambda r: -(r["full"]["excess"] or 0))
summarize("GETIRI: net>0 & test_ex>0 & n>=50 & WF>=4/6 (excess'e göre)", ret_ok)

# Kriter 3: positive test excess in ANY candidate, sorted by test excess
any_te = [r for r in rows if (r["test"].get("excess") or -9) > 0 and r["full"]["n"] >= 100]
any_te.sort(key=lambda r: -(r["test"]["excess"] or 0))
summarize("TEST-EX pozitif (n>=100), test excess'e göre ilk 12", any_te)

# Yön dağılımı: kaç aday positive?
pos_test = sum(1 for r in rows if (r["test"].get("excess") or -9) > 0)
pos_full = sum(1 for r in rows if (r["full"].get("excess") or -9) > 0)
print(f"Toplam {len(rows)} kombinasyon: tam-pencere excess>0 = {pos_full}, test excess>0 = {pos_test}")
long_rows = [r for r in rows if r["direction"] == "long"]
short_rows = [r for r in rows if r["direction"] == "short"]
print(f"  long excess>0: {sum(1 for r in long_rows if (r['full'].get('excess') or -9)>0)}/{len(long_rows)}"
      f" | test>0: {sum(1 for r in long_rows if (r['test'].get('excess') or -9)>0)}/{len(long_rows)}")
print(f"  short excess>0: {sum(1 for r in short_rows if (r['full'].get('excess') or -9)>0)}/{len(short_rows)}"
      f" | test>0: {sum(1 for r in short_rows if (r['test'].get('excess') or -9)>0)}/{len(short_rows)}")
