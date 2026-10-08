#!/usr/bin/env python3
"""Uçlü portfolio kombinasyonunun L30 doğrulaması (tek seferlik koşucu).

Kombine (H24+L15 onaylı):
  1. XAU S3 5m  S_stflip (BE'li)   — L15 +127.55 PF 1.83
  2. XAU S3 15m S_tp2    (BE'li)   — L15 +60.35  PF 2.78
  3. FX  S4 5m  B_opp    (BE'li)   — L15 +34.91  PF 1.38
Çıktı: outputs/str_h24/ (L30 etiketli) + özet tablo.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "camp", os.path.join(ROOT, "scripts", "fx_str_h48_campaign.py"))
camp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(camp)

JOBS = [
    ("XAU", "S3", "PURE", "5m", "S_stflip", "L30"),
    ("XAU", "S3", "PURE", "15m", "S_tp2", "L30"),
    ("FX", "S4", "PURE", "5m", "B_opp", "L30"),
]


def run_one(job):
    grp, strat, mode, tf, cfg, wname = job
    cmd, out_path = camp.build_cmd(strat, mode, tf, cfg, grp, wname)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    m = camp.parse_metrics(out_path)
    m.update({"grp": grp, "strat": strat, "tf": tf, "cfg": cfg, "window": wname,
              "elapsed_s": round(time.time() - t0, 1)})
    if m.get("error"):
        m["log_tail"] = ((proc.stdout or "") + (proc.stderr or ""))[-800:]
    print(f"[{wname} {grp} {strat} {tf} {cfg}] net={m.get('net')} n={m.get('trades')} "
          f"wr={m.get('wr')} pf={m.get('pf')} dd={m.get('dd')} ({m['elapsed_s']}s)"
          + (f" ERR={m['error']}" if m.get("error") else ""), flush=True)
    return m


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print(f"[PLAN] portföy-3 kombinasyonu L30 — {len(JOBS)} koşum, workers={workers}", flush=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(run_one, JOBS):
            results.append(r)
    out = os.path.join(camp.OUTDIR, "_summary_portfolio3_l30.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"\n=== PORTFÖY-3 L30 (2026-09-07 → 2026-10-07) ===")
    print(f"{'GRP':4s}{'STR':4s}{'CFG':12s}{'TF':4s}{'n':>5s}{'WR%':>7s}{'NET$':>10s}{'PF':>6s}{'DD$':>8s}")
    print("-" * 60)
    tot = 0.0
    for r in sorted(results, key=lambda x: (x["grp"], x["strat"])):
        if r.get("error"):
            print(f"{r['grp']:4s}{r['strat']:4s}{r['cfg']:12s}{r['tf']:4s}  HATA: {r['error']}")
            continue
        tot += r["net"]
        print(f"{r['grp']:4s}{r['strat']:4s}{r['cfg']:12s}{r['tf']:4s}{r['trades']:>5}"
              f"{r['wr']:>7.1f}{r['net']:>+10.2f}{r['pf']:>6.2f}{r['dd']:>8.2f}")
    print(f"TOPLAM NET: {tot:+.2f} USD")


if __name__ == "__main__":
    main()
