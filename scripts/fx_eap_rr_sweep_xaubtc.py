#!/usr/bin/env python3
"""XAUUSD ve BTCUSD icin AYRI AYRI RR (SL/TP x ATR) optimizasyonu — 48 saat.

Kullanici istegi (2026-10-08): altin ve BTC'yi izole kos, RR sinirini (SL/TP
oranini) optimize et, YALNIZ 48 saatlik pencere.

Izole kapsam: --symbols ile TEK sembol islenir (varsayilan allowed'daki
XAU/BTC/GBPJPY/EURJPY icinden). Boylece XAU sonucu BTC'den, kroslardan etkilenmez.

Grid: SL {1.0, 1.5, 2.0} x TP {1.5, 2.0, 2.5, 3.0, 4.0} (sabit-TP, RR 0.75-4.0)
      + sabit-TP yok + chandelier trailing {1.5, 2.0, 2.5} (trend-takip kolu)

Iki zaman dilimi: 5m ve 15m (15m ana kampanyada belirgin sekilde daha iyiydi).

Kullanim:
    python -m scripts.fx_eap_rr_sweep_xaubtc
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
REPLAY = os.path.join(ROOT, "scripts", "forex_replay_backtest.py")
CACHE5 = os.path.join(ROOT, "outputs", "replay_cache_60d_fxwide.json")
CACHE15 = os.path.join(ROOT, "outputs", "replay_cache_60d_fxwide_m15.json")
SPREAD = "outputs/fx_spread_p95.json"
OUTDIR = os.path.join(ROOT, "outputs", "eap_rr_xaubtc")

# 48 saat (kullanici istegi; veri sonu 10-07 07:58)
START, END = "2026-10-05", "2026-10-07"

SYMBOLS = ["XAUUSD", "BTCUSD"]
TFS = {"5m": CACHE5, "15m": CACHE15}

# (kod, ekstra argumanlar)
SL_GRID = [1.0, 1.5, 2.0]
TP_GRID = [1.5, 2.0, 2.5, 3.0, 4.0]
TRAIL_GRID = [1.5, 2.0, 2.5]


def configs():
    out = []
    for sl in SL_GRID:
        for tp in TP_GRID:
            out.append((f"sl{sl}_tp{tp}", ["--eap-sl-atr", str(sl), "--eap-tp-atr", str(tp)]))
    for ch in TRAIL_GRID:
        out.append((f"sl1.5_trail{ch}",
                    ["--eap-sl-atr", "1.5", "--eap-tp-atr", "0", "--mode-tp-atr", "0",
                     "--chandelier", str(ch)]))
    return out


def build_cmd(sym, tf, code, extra):
    out_path = os.path.join(OUTDIR, f"{sym}__{code}__{tf}__H48.json")
    cmd = [PY, REPLAY, "--entry-mode", "ema_adx_pullback", "--tag", f"{sym}|{code}|{tf}",
           "--out", out_path, "--skip-old", "--cache", TFS[tf],
           "--symbols", sym, "--add-symbols", sym,
           "--max-open", "99", "--spread-profile", SPREAD,
           "--start", START, "--end", END,
           "--no-ev-guard", "--major-hours", "", "--major-min-atr", "0"]  # PURE: spec birebir
    if tf == "15m":
        cmd += ["--interval", "15m"]
    cmd += list(extra)
    return cmd, out_path


def parse_metrics(out_path):
    if not os.path.exists(out_path):
        return {"error": "no_json"}
    try:
        with open(out_path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return {"error": f"json:{e}"}
    v = (d.get("variants") or {}).get("NEW")
    if not v:
        return {"error": "no_new"}
    return {
        "trades": v.get("trades"), "wr": v.get("win_rate"),
        "net": round(v.get("net_pnl_usd", 0.0), 2), "pf": v.get("profit_factor"),
        "dd": round(v.get("max_drawdown_usd", 0.0), 2),
        "exits": {k: v2.get("n") for k, v2 in (v.get("exit_reasons") or {}).items()},
        "daily": v.get("daily_pnl") or {},
    }


def run_one(job):
    sym, tf, code, extra = job
    cmd, out_path = build_cmd(sym, tf, code, extra)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    m = parse_metrics(out_path)
    m.update({"sym": sym, "tf": tf, "code": code, "elapsed_s": round(time.time() - t0, 1)})
    if m.get("error"):
        m["log_tail"] = ((proc.stdout or "") + (proc.stderr or ""))[-600:]
    print(f"[{sym} {code} {tf}] net={m.get('net')} n={m.get('trades')} wr={m.get('wr')} "
          f"pf={m.get('pf')} dd={m.get('dd')} ({m['elapsed_s']}s)"
          + (f" ERR={m['error']}" if m.get("error") else ""), flush=True)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)

    cfgs = configs()
    jobs = [(s, tf, code, extra) for s in SYMBOLS for tf in TFS for code, extra in cfgs]
    print(f"[PLAN] {len(jobs)} kosum ({len(SYMBOLS)} sembol x {len(TFS)} tf x {len(cfgs)} konfig) — 48 SAAT", flush=True)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(run_one, jobs):
            results.append(r)

    with open(os.path.join(OUTDIR, "_summary_rr.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    for sym in SYMBOLS:
        for tf in TFS:
            rows = [r for r in results if r["sym"] == sym and r["tf"] == tf and not r.get("error")]
            if not rows:
                continue
            print(f"\n=== {sym} · {tf} · 48h ===")
            print(f"{'KONFIG':16s}{'n':>5s}{'WR%':>7s}{'NET$':>10s}{'PF':>7s}{'DD$':>8s}{'SL/BE/TP/TRAIL':>24s}")
            print("-" * 77)
            for r in sorted(rows, key=lambda x: -x["net"]):
                ex = r["exits"]
                exs = f"{ex.get('SL',0)}/{ex.get('BE',0)}/{ex.get('TP',0)}/{ex.get('TRAIL',0)}"
                print(f"{r['code']:16s}{r['trades']:>5}{r['wr']:>7.1f}{r['net']:>+10.2f}"
                      f"{r['pf']:>7.2f}{r['dd']:>8.2f}{exs:>24s}")

    errs = [r for r in results if r.get("error")]
    if errs:
        print(f"\n[HATA] {len(errs)} kosum")
        for e in errs:
            print(f"  {e['sym']} {e['code']} {e['tf']}: {e['error']}")


if __name__ == "__main__":
    main()
