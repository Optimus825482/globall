#!/usr/bin/env python3
"""ORB + cikis mimarisi ve JPY kolu ek pencere dogrulamasi (2026-10-08 takip isi).

Job A : ORB kolu, arastirmanin onerdigi cikis mimarisiyle (sabit TP kapali -> chandelier
        trailing / 10R hedef / H1 EMA200 kapisi / seans sonu flat) yeniden kosulur.
Job B : JPY kolu (jp_da_h1, jp_dp_h1, jp_da_tp4, jp_classic) daha once HIC gorulmemis
        pencerelerde kosulur (2026-07-16 -> 2026-08-01).
Wave c: motorun ORB kutusu >=20 bar sarti nedeniyle 1 saatlik kutu (07-08) 0 islem
        uretiyordu; 07-09 (2 saat) kutusu ile Londra acilis varyanti tekrar kosulur.

Sonuc: outputs/fxsweep2/ altinda JSON + liderlik tablosu.
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
CACHE60 = os.path.join(ROOT, "outputs", "replay_cache_60d_fxwide.json")
SPREAD = "outputs/fx_spread_p95.json"
OUTDIR = os.path.join(ROOT, "outputs", "fxsweep2")

FX12 = "EURUSD,GBPUSD,USDJPY,USDCHF,USDCAD,NZDUSD,EURJPY,GBPJPY,EURCHF,GBPCHF,EURNZD,GBPNZD"
JPY2 = "GBPJPY,EURJPY"
EXCL = "XAUUSD,BTCUSD,US30,NAS100"

WINDOWS = {
    "PX":  ("2026-08-10", "2026-08-31"),
    "XV":  ("2026-08-10", "2026-09-07"),
    "U1":  ("2026-07-16", "2026-07-24"),
    "U2":  ("2026-07-24", "2026-08-01"),
    "U3":  ("2026-07-16", "2026-08-01"),
    "L30": ("2026-09-07", "2026-10-07"),
}

ORB_CONFIGS = [
    ("A1_orb_trail25",    ["--chandelier", "2.5", "--mode-tp-atr", "0"],
     "ORB NY overlap (kutu 07-13) + chandelier 2.5 (sabit TP YOK)"),
    ("A2_orb_trail25_h1", ["--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate"],
     "A1 + H1 EMA200 trend kapisi"),
    ("A3_orb_ldn1h_sign", ["--orb-box-start", "7", "--orb-box-end", "8", "--orb-entry-start", "8",
                           "--orb-entry-end", "16", "--chandelier", "2.5", "--mode-tp-atr", "0",
                           "--htf-ema200-gate"],
     "Londra 07-08 kutusu -> 08-16 devam (kutu<20 bar => motor 0 islem uretir)"),
    ("A4_orb_10R",        ["--orb-tp-r", "10"], "Zarattini tarzi 10R sabit hedef (trail yok)"),
    ("A5_orb_ldn_flat16", ["--orb-box-start", "7", "--orb-box-end", "8", "--orb-entry-start", "8",
                           "--orb-entry-end", "16", "--chandelier", "2.5", "--mode-tp-atr", "0",
                           "--htf-ema200-gate", "--flat-16"],
     "A3 + 16:00 UTC zorla kapanis (kutu<20 bar => 0 islem)"),
    ("A6_orb_width_trail",["--orb-min-atr", "0.25", "--orb-max-atr", "1.5",
                           "--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate"],
     "A2 + kutu/ATR genislik filtresi [0.25-1.5] (6 saatlik kutu icin cok dar => 0 islem)"),
    # --- wave c: duzeltilmis varyantlar ---
    ("C1_orb_ldn2h_sign", ["--orb-box-start", "7", "--orb-box-end", "9", "--orb-entry-start", "9",
                           "--orb-entry-end", "16", "--chandelier", "2.5", "--mode-tp-atr", "0",
                           "--htf-ema200-gate"],
     "Londra 07-09 kutusu (24 bar) -> 09-16 devam, trail + H1 kapi"),
    ("C2_orb_ldn2h_flat16",["--orb-box-start", "7", "--orb-box-end", "9", "--orb-entry-start", "9",
                            "--orb-entry-end", "16", "--chandelier", "2.5", "--mode-tp-atr", "0",
                            "--htf-ema200-gate", "--flat-16"],
     "C1 + 16:00 UTC zorla kapanis"),
    ("C3_orb_width_1_4",  ["--orb-min-atr", "1.0", "--orb-max-atr", "4.0",
                           "--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate"],
     "A2 + kutu/ATR genislik filtresi [1.0-4.0] (6 saatlik kutu icin gercekci bant)"),
]

JPY_CONFIGS = [
    ("B1_jp_da_h1",  "donchian_adx",  ["--htf-ema200-gate"], "Donchian+ADX + H1 EMA200 kapisi (JPY)"),
    ("B2_jp_dp_h1",  "donchian_pure", ["--chandelier", "2.5", "--htf-ema200-gate"], "Donchian saf + chand2.5 + H1 kapi (JPY)"),
    ("B3_jp_da_tp4", "donchian_adx",  [], "Donchian+ADX TP4xATR, kapi YOK (kontrol)"),
    ("B4_jp_classic","classic",       [], "klasik motor (JPY, kontrol)"),
]

WAVE_MAP = {
    "a":          [("orb", w) for w in ["U1", "U2", "U3"]],
    "b":          [("jpy", w) for w in ["U1", "U2", "U3"]],
    "orb_unseen": [("orb", w) for w in ["U1", "U2", "U3"]],
    "orb_seen":   [("orb", w) for w in ["PX", "XV"]],
    "d":          [("orbsel", "L30")],
    "c":          [("wavec", w) for w in ["PX", "XV", "U1", "U2", "U3"]],
    "all":        [("orb", w) for w in ["PX", "XV", "U1", "U2", "U3"]] + [("jpy", w) for w in ["U1", "U2", "U3"]],
}


def build_cmd(name, entry_mode, extra, scope, window):
    out_path = os.path.join(OUTDIR, f"{name}__{window}.json")
    cmd = [PY, REPLAY, "--entry-mode", entry_mode, "--tag", name,
           "--out", out_path, "--skip-old"]
    if scope == "jpy2":
        cmd += ["--cache", CACHE60, "--symbols", JPY2, "--max-open", "99", "--spread-profile", SPREAD]
    else:
        cmd += ["--cache", CACHE60, "--add-symbols", FX12, "--exclude-symbols", EXCL,
                "--max-open", "99", "--spread-profile", SPREAD]
    start, end = WINDOWS[window]
    cmd += ["--start", start, "--end", end]
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
    jpy = sum(x["pnl"] for s, x in ps.items() if "JPY" in s)
    nonjpy = sum(x["pnl"] for s, x in ps.items() if "JPY" not in s)
    return {
        "trades": v.get("trades"), "wr": v.get("win_rate"),
        "net": v.get("net_pnl_usd"), "pf": v.get("profit_factor"),
        "dd": v.get("max_drawdown_usd"), "avg": v.get("avg_pnl_usd"),
        "jpy_net": round(jpy, 2), "nonjpy_net": round(nonjpy, 2),
        "exits": {k: v2.get("n") for k, v2 in (v.get("exit_reasons") or {}).items()},
        "per_symbol": {s: round(x["pnl"], 2) for s, x in sorted(ps.items(), key=lambda kv: -kv[1]["pnl"])},
    }


def run_one(job):
    name, entry_mode, extra, scope, window = job
    cmd, out_path = build_cmd(name, entry_mode, extra, scope, window)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    m = parse_metrics(out_path)
    log = (proc.stdout or "") + (proc.stderr or "")
    m.update({"name": name, "window": window, "scope": scope,
              "elapsed_s": round(time.time() - t0, 1)})
    if m.get("error"):
        m["log_tail"] = log[-400:]
    print(f"[{name} {window}] net={m.get('net')} n={m.get('trades')} wr={m.get('wr')} "
          f"pf={m.get('pf')} dd={m.get('dd')} ({m['elapsed_s']}s)"
          + (f" ERR={m['error']}" if m.get("error") else ""), flush=True)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wave", default="all", choices=list(WAVE_MAP.keys()))
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)

    jobs = []
    for kind, w in WAVE_MAP[args.wave]:
        if kind == "orb":
            jobs += [(c[0], "orb_ny", c[1], "fx12", w) for c in ORB_CONFIGS[:6]]
        elif kind == "orbsel":
            for nm in ("A1_orb_trail25", "A2_orb_trail25_h1", "A4_orb_10R", "C1_orb_ldn2h_sign"):
                c = [x for x in ORB_CONFIGS if x[0] == nm][0]
                jobs.append((c[0], "orb_ny", c[1], "fx12", w))
        elif kind == "wavec":
            jobs += [(c[0], "orb_ny", c[1], "fx12", w) for c in ORB_CONFIGS[6:]]
        else:
            jobs += [(c[0], c[1], c[2], "jpy2", w) for c in JPY_CONFIGS]

    print(f"[PLAN] {len(jobs)} kosum, {args.workers} worker", flush=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(run_one, jobs):
            results.append(r)

    with open(os.path.join(OUTDIR, f"_summary_{args.wave}.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    print("\n" + "=" * 100)
    print(f"{'KONFIG':22s} {'PENCERE':8s} {'n':>5s} {'WR%':>6s} {'NET$':>9s} {'PF':>6s} {'DD$':>8s} {'JPY$':>9s}")
    print("-" * 100)
    for r in sorted(results, key=lambda x: (x["window"], -(x.get("net") or -9999))):
        if r.get("error"):
            print(f"{r['name']:22s} {r['window']:8s} HATA: {r['error']}")
            continue
        print(f"{r['name']:22s} {r['window']:8s} {r['trades']:>5} {r['wr']:>6.1f} "
              f"{r['net']:>+9.2f} {r['pf']:>6.2f} {r['dd']:>8.2f} {r.get('jpy_net',0):>+9.2f}")


if __name__ == "__main__":
    main()

