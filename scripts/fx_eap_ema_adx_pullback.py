#!/usr/bin/env python3
"""EMA+ADX geri-cekilme skalpi (ema_adx_pullback) — kullanici spesifikasyonu replay'i (2026-10-08).

Kural seti (birebir):
  1) EMA8 > EMA21 > EMA50 -> yalniz LONG ; EMA8 < EMA21 < EMA50 -> yalniz SHORT
  2) ADX(14) > 25
  3) Fiyat EMA21'e geri cekilir (bar EMA21'i keser) ve trend yonunde kapanisla doner
  4) SL = 1.5 x ATR(14) ; TP = 2.0 x ATR(14)  VEYA ATR tabanli trailing (--chandelier)
Kapsam: 12 FX cifti + XAUUSD + BTCUSD (kullanici istegi). Maliyet: gercek p95 spread profili.

Kullanim:
    python -m scripts.fx_eap_ema_adx_pullback --wave w48
    python -m scripts.fx_eap_ema_adx_pullback --wave multi
    python -m scripts.fx_eap_ema_adx_pullback --wave stress
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
SPREAD1 = "outputs/fx_spread_p95.json"
SPREAD2 = "outputs/fx_spread_p95_x2.json"
OUTDIR = os.path.join(ROOT, "outputs", "eap14")  # 12 FX + XAUUSD + BTCUSD (--add-symbols ile; canli allowed_symbols 4 sembol oldugu icin ZORUNLU)

SYMS = ("EURUSD,GBPUSD,USDJPY,USDCHF,USDCAD,NZDUSD,EURJPY,GBPJPY,"
        "EURCHF,GBPCHF,EURNZD,GBPNZD,XAUUSD,BTCUSD")

WINDOWS = {
    "H48": ("2026-10-05", "2026-10-07"),   # kullanicinin istedigi 48 saat (veri sonu)
    "W1":  ("2026-07-25", "2026-08-10"),
    "PX":  ("2026-08-10", "2026-08-31"),
    "AU":  ("2026-08-01", "2026-09-14"),
    "L30": ("2026-09-07", "2026-10-07"),   # protokol OOS
}

CONFIGS = [
    ("E1_tp2", ["--eap-tp-atr", "2.0"],
     "SL 1.5xATR / TP 2.0xATR (spesifikasyon, sabit TP)"),
    ("E2_trail", ["--eap-tp-atr", "0", "--mode-tp-atr", "0", "--chandelier", "2.0"],
     "SL 1.5xATR / sabit TP yok, ATR trailing (chandelier 2.0xATR)"),
    ("E3_tp2_h1", ["--eap-tp-atr", "2.0", "--htf-ema200-gate"],
     "E1 + H1 EMA200 trend kapisi (ek filtre)"),
    ("E4_tp2_cap3", ["--eap-tp-atr", "2.0", "--eap-max-per-day", "3"],
     "E1 + gunde en fazla 3 giris (yigin onleme)"),
    ("E5_trail_h1", ["--eap-tp-atr", "0", "--mode-tp-atr", "0", "--chandelier", "2.0", "--htf-ema200-gate"],
     "E2 + H1 EMA200 kapisi"),
    ("E6_tp3", ["--eap-tp-atr", "3.0"], "SL 1.5xATR / TP 3.0xATR (R=2 kontrolu)"),
]

WAVE_MAP = {
    "w48":    (["H48"], SPREAD1, ["E1_tp2", "E2_trail", "E3_tp2_h1", "E4_tp2_cap3", "E5_trail_h1", "E6_tp3"]),
    "multi":  (["W1", "PX", "AU", "L30"], SPREAD1, ["E1_tp2", "E2_trail", "E3_tp2_h1", "E4_tp2_cap3", "E5_trail_h1"]),
    "m15":    (["H48", "PX", "L30"], SPREAD1, ["E1_tp2", "E2_trail", "E4_tp2_cap3"]),
    "stress": (["H48", "W1", "PX", "AU", "L30"], SPREAD2, ["E1_tp2", "E2_trail", "E3_tp2_h1"]),
}
# maliyet stresini izole et (spread kapisi islem kumesini degistirmesin)
COST_ISOLATE = ["--max-spread", "99"]


USE_M15 = [False]


def build_cmd(name, extra, window, spread):
    out_path = os.path.join(OUTDIR, f"{name}__{window}.json")
    start, end = WINDOWS[window]
    cache = CACHE15 if USE_M15[0] else CACHE5
    cmd = [PY, REPLAY, "--entry-mode", "ema_adx_pullback", "--tag", name,
           "--out", out_path, "--skip-old", "--cache", cache,
           "--add-symbols", SYMS, "--max-open", "99", "--spread-profile", spread,
           "--start", start, "--end", end]
    if spread == SPREAD2:
        cmd += COST_ISOLATE
    if USE_M15[0]:
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
    jpy = sum(x["pnl"] for s, x in ps.items() if "JPY" in s)
    return {
        "trades": v.get("trades"), "wr": v.get("win_rate"),
        "net": v.get("net_pnl_usd"), "pf": v.get("profit_factor"),
        "dd": v.get("max_drawdown_usd"), "avg": v.get("avg_pnl_usd"),
        "jpy_net": round(jpy, 2),
        "gold_net": round(ps.get("XAUUSD", {}).get("pnl", 0.0), 2),
        "btc_net": round(ps.get("BTCUSD", {}).get("pnl", 0.0), 2),
        "exits": {k: v2.get("n") for k, v2 in (v.get("exit_reasons") or {}).items()},
        "per_symbol": {s: round(x["pnl"], 2) for s, x in sorted(ps.items(), key=lambda kv: -kv[1]["pnl"])},
    }


def run_one(job):
    name, extra, window, spread = job
    cmd, out_path = build_cmd(name, extra, window, spread)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    m = parse_metrics(out_path)
    m.update({"name": name, "window": window, "tf": "15m" if USE_M15[0] else "5m",
              "elapsed_s": round(time.time() - t0, 1)})
    if m.get("error"):
        m["log_tail"] = ((proc.stdout or "") + (proc.stderr or ""))[-500:]
    print(f"[{name} {window}] net={m.get('net')} n={m.get('trades')} wr={m.get('wr')} "
          f"pf={m.get('pf')} dd={m.get('dd')} xau={m.get('gold_net')} btc={m.get('btc_net')} "
          f"({m['elapsed_s']}s)" + (f" ERR={m['error']}" if m.get("error") else ""), flush=True)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wave", default="w48", choices=list(WAVE_MAP.keys()))
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)

    wins, spread, names = WAVE_MAP[args.wave]
    USE_M15[0] = (args.wave == "m15")
    cfg = {c[0]: c for c in CONFIGS}
    jobs = [(n, cfg[n][1], w, spread) for w in wins for n in names]
    print(f"[PLAN] {args.wave}: {len(jobs)} kosum, spread={spread}", flush=True)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(run_one, jobs):
            results.append(r)

    with open(os.path.join(OUTDIR, f"_summary_{args.wave}.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    print("\n" + "=" * 108)
    print(f"{'KONFIG':14s} {'PENCERE':7s} {'n':>5s} {'WR%':>6s} {'NET$':>9s} {'PF':>6s} {'DD$':>8s} {'XAU$':>9s} {'BTC$':>9s}")
    print("-" * 108)
    for r in sorted(results, key=lambda x: (x["window"], x["name"])):
        if r.get("error"):
            print(f"{r['name']:14s} {r['window']:7s} HATA: {r['error']}")
            continue
        print(f"{r['name']:14s} {r['window']:7s} {r['trades']:>5} {r['wr']:>6.1f} "
              f"{r['net']:>+9.2f} {r['pf']:>6.2f} {r['dd']:>8.2f} {r.get('gold_net',0):>+9.2f} {r.get('btc_net',0):>+9.2f}")


if __name__ == "__main__":
    main()
