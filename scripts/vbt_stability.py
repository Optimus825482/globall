#!/usr/bin/env python3
"""PARAMETRE KOMŞULUĞU KARARLILIĞI (2026-11-10)

NEDEN: bir ızgarada "en iyi hücre" şanslı olabilir (55 kombinasyon taradık). Sağlamlık
kontrolü: seçilen parametrenin **komşuları** da OOS'ta pozitif mi? Tek hücre pozitif,
komşuları negatifse o kenar büyük olasılıkla gürültüdür.

Kullanim:
    .venv-vbt/Scripts/python.exe scripts/vbt_stability.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vbt_sweep as S  # noqa: E402  (aynı venv, aynı strateji tanımları)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: (sembol, tf, strateji, parametre adı, değerler)
CASES = [
    ("XAUUSD", "1h", S.sig_donchian, "n", [10, 15, 20, 25, 30, 40]),
    ("USDJPY", "1h", S.sig_donchian, "n", [10, 15, 20, 25, 30, 40]),
    ("US30", "1d", S.sig_mom, "n", [5, 10, 15, 20, 30]),
    ("NAS100", "1h", S.sig_mom, "n", [10, 15, 20, 30, 50]),
]
MA_CASES = [("NAS100", "1h", [(f, s) for f in (5, 10, 20) for s in (100, 150, 200)])]


def main() -> int:
    print("KOMŞU KARARLILIĞI — OOS Sharpe (ilk %70 IS, son %30 OOS)\n")
    ok = 0
    for sym, tf, fn, pname, vals in CASES:
        df = S.load(sym, tf)
        if df is None:
            continue
        cut = int(len(df) * 0.70)
        tr, te = df.iloc[:cut], df.iloc[cut:]
        cost = S.COST.get(sym, 0.0001)
        print(f"{sym} {tf} · {fn.__name__} · {pname} →")
        line = []
        for v in vals:
            try:
                en, ex = fn(tr, **{pname: v})
                r_tr = S.run_one(tr["close"], en, ex, tf, cost, 1.0)
                en, ex = fn(te, **{pname: v})
                r_te = S.run_one(te["close"], en, ex, tf, cost, 1.0)
            except Exception:  # noqa: BLE001
                continue
            if not r_tr or not r_te:
                continue
            line.append((v, round(r_tr["sharpe"], 2), round(r_te["sharpe"], 2), r_te["trades"]))
        pos = sum(1 for *_, x in [(a, b, c, d) for a, b, c, d in line] for _ in [0])  # noqa: F841
        for v, is_s, oos_s, n in line:
            flag = "✅" if oos_s > 0.3 else ("·" if oos_s > -0.2 else "❌")
            print(f"   {pname}={v:<4} IS {is_s:>5.2f} → OOS {oos_s:>5.2f}  işlem {n:>4} {flag}")
        good = sum(1 for _, _, o, _ in line if o > 0.3)
        print(f"   → komşuların {good}/{len(line)} tanesi OOS Sharpe>0.3 "
              f"{'KARARLI' if good >= max(2, len(line) // 2) else 'KIRILGAN'}\n")
        if good >= max(2, len(line) // 2):
            ok += 1

    for sym, tf, grid in MA_CASES:
        df = S.load(sym, tf)
        if df is None:
            continue
        cut = int(len(df) * 0.70)
        tr, te = df.iloc[:cut], df.iloc[cut:]
        cost = S.COST.get(sym, 0.0001)
        print(f"{sym} {tf} · EMA kesişimi → OOS Sharpe ızgarası (satır fast, kolon slow)")
        rows = {}
        for f, s in grid:
            en, ex = S.sig_ma_cross(te, fast=f, slow=s)
            r = S.run_one(te["close"], en, ex, tf, cost, 1.0)
            rows.setdefault(f, {})[s] = (round(r["sharpe"], 2), r["trades"]) if r else (None, 0)
        print("   fast\\slow " + "".join(f"{s:>12}" for s in (100, 150, 200)))
        for f, d in rows.items():
            print(f"   {f:>9} " + "".join(
                f"{(d.get(s, (None, 0))[0] if d.get(s, (None, 0))[0] is not None else float('nan')):>9.2f}"
                f"({d.get(s, (0, 0))[1]:>4})" for s in (100, 150, 200)))
        print()
    print(f"kararlı vaka: {ok}/{len(CASES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
