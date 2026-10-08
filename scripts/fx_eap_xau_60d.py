#!/usr/bin/env python3
"""XAUUSD — 60 GUN, OPTIMAL RR ayarlariyla replay (2026-10-08).

Optimal bulunan ayar (48 saat RR supurmesi):
    SL = 1.5 x ATR(14) ; TP = 2.0 x ATR(14)   -> 48h +$32.60 / PF 2.28 / WR %86.7 / n=15

Bu kosum ayni kolu 60 GUNE uzatip (2026-08-08 -> 2026-10-07) saglamlik test eder:
  - O (optimal)      : sl1.5 / tp2.0
  - O_trail          : sl1.5 / chandelier trail 2.0 (48h'de en yuksek net)
  - komsu_tp1.5      : sl1.5 / tp1.5   (daha yakin TP)
  - komsu_sl1.0      : sl1.0 / tp2.0   (daha dar SL, 48h'de en dusuk DD)
Ayrica 60 gunun ilk/ikinci yarisi da kosulur (oturmusluk kontrolu).

Izole: --symbols XAUUSD. PURE mod (spec birebir kapi seti). Gercek p95 spread.

Kullanim:
    python -m scripts.fx_eap_xau_60d
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
OUTDIR = os.path.join(ROOT, "outputs", "eap_xau_60d")

SYM = "XAUUSD"
TFS = {"5m": CACHE5, "15m": CACHE15}

# Pencereler: 60 gun + iki yaris (oturmusluk) + 48h referans
WINDOWS = {
    "D60":  ("2026-08-08", "2026-10-07"),   # 60 gun (veri basi 07-29 → tam kapsanir)
    "D60a": ("2026-08-08", "2026-09-17"),   # 1. yari (~40 giris gunu)
    "D60b": ("2026-09-17", "2026-10-07"),   # 2. yari
    "H48":  ("2026-10-05", "2026-10-07"),   # 48h referans (karsilastirma)
}

CONFIGS = {
    "O_tp2":       (["--eap-sl-atr", "1.5", "--eap-tp-atr", "2.0"], "OPTIMAL: SL 1.5 / TP 2.0"),
    "O_trail2":    (["--eap-sl-atr", "1.5", "--eap-tp-atr", "0", "--mode-tp-atr", "0",
                     "--chandelier", "2.0"], "SL 1.5 / chandelier trail 2.0"),
    "K_tp1.5":     (["--eap-sl-atr", "1.5", "--eap-tp-atr", "1.5"], "komsu: SL 1.5 / TP 1.5"),
    "K_sl1.0":     (["--eap-sl-atr", "1.0", "--eap-tp-atr", "2.0"], "komsu: SL 1.0 / TP 2.0"),
}


def build_cmd(tf, window, code, extra):
    start, end = WINDOWS[window]
    out_path = os.path.join(OUTDIR, f"{code}__{tf}__{window}.json")
    cmd = [PY, REPLAY, "--entry-mode", "ema_adx_pullback", "--tag", f"{code}|{tf}|{window}",
           "--out", out_path, "--skip-old", "--cache", TFS[tf],
           "--symbols", SYM, "--add-symbols", SYM,
           "--max-open", "99", "--spread-profile", SPREAD,
           "--start", start, "--end", end,
           "--no-ev-guard", "--major-hours", "", "--major-min-atr", "0"]  # PURE
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
    ps = v.get("per_symbol") or {}
    x = ps.get(SYM, {})
    return {
        "trades": v.get("trades"), "wr": v.get("win_rate"),
        "net": round(v.get("net_pnl_usd", 0.0), 2), "pf": v.get("profit_factor"),
        "dd": round(v.get("max_drawdown_usd", 0.0), 2),
        "avg": round(v.get("avg_pnl_usd", 0.0), 3),
        "wins": x.get("wins"), "n_xau": x.get("n"),
        "exits": {k: v2.get("n") for k, v2 in (v.get("exit_reasons") or {}).items()},
        "daily": v.get("daily_pnl") or {},
        "bars": d.get("bars"), "days": d.get("days"),
    }


def run_one(job):
    tf, window, code, extra = job
    cmd, out_path = build_cmd(tf, window, code, extra)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    m = parse_metrics(out_path)
    m.update({"tf": tf, "window": window, "code": code, "elapsed_s": round(time.time() - t0, 1)})
    if m.get("error"):
        m["log_tail"] = ((proc.stdout or "") + (proc.stderr or ""))[-600:]
    print(f"[{code} {tf} {window}] net={m.get('net')} n={m.get('trades')} wr={m.get('wr')} "
          f"pf={m.get('pf')} dd={m.get('dd')} ({m['elapsed_s']}s)"
          + (f" ERR={m['error']}" if m.get("error") else ""), flush=True)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)

    jobs = [(tf, w, code, args_list)
            for w in WINDOWS for tf in TFS for code, (args_list, _desc) in CONFIGS.items()]
    print(f"[PLAN] XAUUSD {len(jobs)} kosum (pc x tf x konfig)", flush=True)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(run_one, jobs):
            results.append(r)

    with open(os.path.join(OUTDIR, "_summary_xau60.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    for w in WINDOWS:
        rows = [r for r in results if r["window"] == w and not r.get("error")]
        if not rows:
            continue
        print(f"\n=== XAUUSD · {w} ({WINDOWS[w][0]} → {WINDOWS[w][1]}) ===")
        print(f"{'KONFIG':12s}{'TF':4s}{'n':>5s}{'WR%':>7s}{'NET$':>10s}{'PF':>7s}{'DD$':>8s}"
              f"{'SL/BE/TP/TRAIL':>18s}")
        print("-" * 71)
        for r in sorted(rows, key=lambda x: (x["tf"], -x["net"])):
            ex = r["exits"]
            exs = f"{ex.get('SL',0)}/{ex.get('BE',0)}/{ex.get('TP',0)}/{ex.get('TRAIL',0)}"
            print(f"{r['code']:12s}{r['tf']:4s}{r['trades']:>5}{r['wr']:>7.1f}{r['net']:>+10.2f}"
                  f"{r['pf']:>7.2f}{r['dd']:>8.2f}{exs:>18s}")

    errs = [r for r in results if r.get("error")]
    if errs:
        print(f"\n[HATA] {len(errs)} kosum")
        for e in errs:
            print(f"  {e['code']} {e['tf']} {e['window']}: {e['error']}")


if __name__ == "__main__":
    main()
