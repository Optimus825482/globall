#!/usr/bin/env python3
"""Combo3 (M5, XAUUSD) paper donemi kayma/spread raporu.

Kaynak 1: backend GET /api/forex/slippage (canli kayit; SCALPER_API_URL ile)
Kaynak 2: backend/data/live_slippage_log.jsonl (yerel dosya; --file)

Karar esikleri (docs/COMBO3_M5_PAPER_KURULUM.md):
  icra kaymasi medyan <= 1 pip ve p90 <= 2 pip, spread medyan <= 2 pip  -> risk kademeli artirilabilir
  icra kaymasi p90 > 2 pip                                             -> strateji canliya uygun degil

Kullanim:
  python scripts/combo3_slippage_report.py --api https://global.erkanerdem.online --tag CMB3
  python scripts/combo3_slippage_report.py --file backend/data/live_slippage_log.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from app import combo3_m5 as c3  # noqa: E402


def load_api(api: str, tag: str) -> list:
    url = f"{api.rstrip('/')}/api/forex/slippage?limit=5000" + (f"&tag={tag}" if tag else "")
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8")).get("records", [])


def load_file(path: str, tag: str) -> list:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                r = json.loads(line)
                if not tag or str(r.get("strategy_tag") or "").upper() == tag.upper():
                    rows.append(r)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.environ.get("SCALPER_API_URL", ""))
    ap.add_argument("--file", default="")
    ap.add_argument("--tag", default="CMB3")
    args = ap.parse_args()
    if args.file:
        rows = load_file(args.file, args.tag)
    elif args.api:
        rows = load_api(args.api, args.tag)
    else:
        raise SystemExit("--api veya --file ver")
    summ = c3.slippage_summary(rows)
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    s = summ.get(args.tag.upper()) or next(iter(summ.values()), None)
    if not s or s["exec_slip_pips"]["n"] < 20:
        print(f"\nKARAR: yetersiz ornek ({0 if not s else s['exec_slip_pips']['n']} < 20) — olcume devam.")
        return
    ex, sp = s["exec_slip_pips"], s["spread_pips_exec"]
    if ex["p90"] > 2.0:
        print(f"\nKARAR: icra kaymasi p90 {ex['p90']} pip > 2 — strateji bu kaymada kenarini kaybeder (replay: 2 pipte PF 1.09). Risk ARTIRILMAZ.")
    elif ex["median"] <= 1.0 and sp.get("median", 99) <= 2.0:
        print(f"\nKARAR: kayma medyan {ex['median']} / p90 {ex['p90']} pip, spread medyan {sp.get('median')} pip — kademeli risk artisi degerlendirilebilir (once PF >= 1.3 ile 2 hafta).")
    else:
        print(f"\nKARAR: sinirda (medyan {ex['median']}, p90 {ex['p90']}, spread {sp.get('median')}) — olcume devam, risk sabit.")


if __name__ == "__main__":
    main()
