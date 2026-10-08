#!/usr/bin/env python3
"""XAUUSD — TEMMUZ 1-15 2026 replay (MT5 gecmisiyle). Optimal RR + komsu kollar.

Veri: Yahoo 60-gun sinirini astigi icin MT5'ten cekildi (scripts/fx_build_mt5_cache.py):
    outputs/replay_cache_jul_mt5.json      (5m)
    outputs/replay_cache_jul_mt5_m15.json  (15m)

Optimal RR (48h supurmesi + 60g dogrulamasi): SL 1.5 x ATR / TP 2.0 x ATR
Komsu kollar: TP1.5 (60g'de 15m'de en iyi) · SL1.0 · chandelier trail 2.0

Pencereler:
    J15   : 2026-07-01 -> 2026-07-16 (kullanicinin istedigi: Temmuz ilk 15 gun)
    J15warm: ayni ama ısınma 06-15'ten (EMA/ADX için bar birikimi zaten cache'te)

Kapsam: XAUUSD izole + (kontrol) 12 FX + BTC geniş kapsam.

Kullanim:
    python -m scripts.fx_eap_jul15
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
CACHE5 = os.path.join(ROOT, "outputs", "replay_cache_jul_mt5.json")
CACHE15 = os.path.join(ROOT, "outputs", "replay_cache_jul_mt5_m15.json")
SPREAD = "outputs/fx_spread_p95.json"
OUTDIR = os.path.join(ROOT, "outputs", "eap_jul15")

TFS = {"5m": CACHE5, "15m": CACHE15}
START, END = "2026-07-01", "2026-07-16"   # Temmuz ilk 15 gun (dahil degil 16 → 1-15 dahil)

CONFIGS = {
    "O_tp2":    (["--eap-sl-atr", "1.5", "--eap-tp-atr", "2.0"], "OPTIMAL: SL1.5/TP2.0"),
    "K_tp1.5":  (["--eap-sl-atr", "1.5", "--eap-tp-atr", "1.5"], "komsu: SL1.5/TP1.5"),
    "K_sl1.0":  (["--eap-sl-atr", "1.0", "--eap-tp-atr", "2.0"], "komsu: SL1.0/TP2.0"),
    "O_trail2": (["--eap-sl-atr", "1.5", "--eap-tp-atr", "0", "--mode-tp-atr", "0",
                  "--chandelier", "2.0"], "SL1.5 / trail2.0"),
}

ALL_SYMS = ("EURUSD,GBPUSD,USDJPY,USDCHF,USDCAD,NZDUSD,EURJPY,GBPJPY,"
            "EURCHF,GBPCHF,EURNZD,GBPNZD,XAUUSD,BTCUSD")


def build_cmd(scope, tf, code, args_list):
    out_path = os.path.join(OUTDIR, f"{scope}__{code}__{tf}__J15.json")
    cmd = [PY, REPLAY, "--entry-mode", "ema_adx_pullback", "--tag", f"{scope}|{code}|{tf}",
           "--out", out_path, "--skip-old", "--cache", TFS[tf],
           "--max-open", "99", "--spread-profile", SPREAD,
           "--start", START, "--end", END,
           "--no-ev-guard", "--major-hours", "", "--major-min-atr", "0"]  # PURE
    if scope == "XAU":
        cmd += ["--symbols", "XAUUSD", "--add-symbols", "XAUUSD"]
    else:
        cmd += ["--add-symbols", ALL_SYMS]
    if tf == "15m":
        cmd += ["--interval", "15m"]
    cmd += list(args_list)
    return cmd, out_path


def parse_metrics(out_path, scope):
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
    x = ps.get("XAUUSD", {})
    m = {
        "trades": v.get("trades"), "wr": v.get("win_rate"),
        "net": round(v.get("net_pnl_usd", 0.0), 2), "pf": v.get("profit_factor"),
        "dd": round(v.get("max_drawdown_usd", 0.0), 2),
        "avg": round(v.get("avg_pnl_usd", 0.0), 3),
        "xau_net": round(x.get("pnl", 0.0), 2), "xau_n": x.get("n"), "xau_wins": x.get("wins"),
        "btc_net": round(ps.get("BTCUSD", {}).get("pnl", 0.0), 2),
        "exits": {k: v2.get("n") for k, v2 in (v.get("exit_reasons") or {}).items()},
        "daily": v.get("daily_pnl") or {},
        "bars": d.get("bars"),
    }
    if scope != "XAU":
        m["per_symbol"] = {s: round(y["pnl"], 2) for s, y in sorted(ps.items(), key=lambda kv: -kv[1]["pnl"])}
    return m


def run_one(job):
    scope, tf, code, args_list = job
    cmd, out_path = build_cmd(scope, tf, code, args_list)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    m = parse_metrics(out_path, scope)
    m.update({"scope": scope, "tf": tf, "code": code, "elapsed_s": round(time.time() - t0, 1)})
    if m.get("error"):
        m["log_tail"] = ((proc.stdout or "") + (proc.stderr or ""))[-800:]
    print(f"[{scope} {code} {tf}] net={m.get('net')} n={m.get('trades')} wr={m.get('wr')} "
          f"pf={m.get('pf')} dd={m.get('dd')} xau={m.get('xau_net')}(n{m.get('xau_n')}) "
          f"({m['elapsed_s']}s)" + (f" ERR={m['error']}" if m.get("error") else ""), flush=True)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)

    jobs = [(scope, tf, code, al) for scope in ("XAU", "ALL") for tf in TFS
            for code, (al, _d) in CONFIGS.items()]
    print(f"[PLAN] Temmuz 1-15 (2026-07-01 → 07-16): {len(jobs)} kosum", flush=True)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(run_one, jobs):
            results.append(r)

    with open(os.path.join(OUTDIR, "_summary_jul15.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    for scope in ("XAU", "ALL"):
        for tf in TFS:
            rows = [r for r in results if r["scope"] == scope and r["tf"] == tf and not r.get("error")]
            if not rows:
                continue
            print(f"\n=== {'XAUUSD izole' if scope=='XAU' else 'GENIS (12FX+XAU+BTC)'} · {tf} · Tem 1-15 ===")
            print(f"{'KONFIG':12s}{'n':>5s}{'WR%':>7s}{'NET$':>10s}{'PF':>7s}{'DD$':>8s}"
                  f"{'XAU$(n)':>13s}{'SL/BE/TP/TRAIL':>17s}")
            print("-" * 79)
            for r in sorted(rows, key=lambda x: -x["net"]):
                ex = r["exits"]
                exs = f"{ex.get('SL',0)}/{ex.get('BE',0)}/{ex.get('TP',0)}/{ex.get('TRAIL',0)}"
                print(f"{r['code']:12s}{r['trades']:>5}{r['wr']:>7.1f}{r['net']:>+10.2f}"
                      f"{r['pf']:>7.2f}{r['dd']:>8.2f}{r['xau_net']:>+9.2f}({r['xau_n']:>2}){exs:>17s}")

    errs = [r for r in results if r.get("error")]
    if errs:
        print(f"\n[HATA] {len(errs)} kosum")
        for e in errs:
            print(f"  {e['scope']} {e['code']} {e['tf']}: {e['error']} :: {e.get('log_tail','')[:200]}")


if __name__ == "__main__":
    main()
