#!/usr/bin/env python3
"""Zaman-dilimi merdiveni (Asama 3): M15 tabanli trend/breakout kollari — 2026-10-08.

Neden ayri bir onbellek: forex_replay_backtest.py'de --interval YALNIZCA Yahoo fetch
URL'ini degistirir; --cache verildiginde yeniden-ornekleme YAPILMAZ. Bu yuzden
"--interval 15m" tek basina sahte bir M15 kosumu uretir. Gercek 15m barlar
scripts/fx_build_m15_cache.py ile uretilir (3x5m -> 1x15m).

Cikis mimarisi duzeltmesi: spec BE=14 pip / trail=20 pip 5m icin kalibre edilmistir.
Ampirik olcum (bu depo, 12 FX cifti, 24 Agu-7 Eki): ATR(14) 15m/5m medyan orani = 1.735
(teorik sqrt(3)=1.732). Bu yuzden 15m kolu icin BE=24 / trail=35 (x1.7) ayri bir kol
olarak kosulur (--be-pips / --trail-pips); aksi halde M15 testi "5m cikis politikasi"
testine donusur.

Baraj: en az 2 ayrik pencerede pozitif + OOS (L30) pozitif + toplam >=100 islem +
2x maliyet stresinde ayakta kalma.

Kullanim:
    python -m scripts.fx_m15_ladder_windows --wave m15
    python -m scripts.fx_m15_ladder_windows --wave m15exit
    python -m scripts.fx_m15_ladder_windows --wave m15stress
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
CACHE15 = os.path.join(ROOT, "outputs", "replay_cache_60d_fxwide_m15.json")
SPREAD1 = "outputs/fx_spread_p95.json"
SPREAD2 = "outputs/fx_spread_p95_x2.json"
OUTDIR = os.path.join(ROOT, "outputs", "fxsweep3")

FX12 = "EURUSD,GBPUSD,USDJPY,USDCHF,USDCAD,NZDUSD,EURJPY,GBPJPY,EURCHF,GBPCHF,EURNZD,GBPNZD"
JPY2 = "GBPJPY,EURJPY"
EXCL = "XAUUSD,BTCUSD,US30,NAS100"

RATR15 = "192"          # 15m barlarda ~2 gun (5m'deki 576'nin karsiligi)
BE15, TRAIL15 = "24", "35"   # x1.7 ATR olcekleme

WINDOWS = {
    "U3":  ("2026-07-16", "2026-08-01"),   # gorulmemis (isinma payi kisitli)
    "W1":  ("2026-07-25", "2026-08-10"),   # gorulmemis
    "PX":  ("2026-08-10", "2026-08-31"),   # gorulmus
    "AU":  ("2026-08-01", "2026-09-14"),   # gorulmus (genis)
    "L30": ("2026-09-07", "2026-10-07"),   # protokol OOS
}

ORB15 = [
    ("M1_orb15_trail25_h1",
     ["--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate"],
     "ORB (kutu 07-13 -> tetik 13-16) + chandelier 2.5 + H1 EMA200 kapisi"),
    ("M2_orb15_trail25_h1_band",
     ["--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate",
      "--rel-atr-band", "--rel-atr-lookback", RATR15],
     "M1 + goreli-ATR bandi"),
    ("M3_orb15_trail25_h1_flat16",
     ["--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate", "--flat-16"],
     "M1 + 16:00 UTC zorla kapanis"),
    ("M4_orb15_trail25_h1_band_flat16",
     ["--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate", "--flat-16",
      "--rel-atr-band", "--rel-atr-lookback", RATR15],
     "M1 + bant + flat16"),
    ("M5_orb15_asia_ldn",
     ["--orb-box-start", "4", "--orb-box-end", "9", "--orb-entry-start", "9",
      "--orb-entry-end", "13", "--chandelier", "2.5", "--mode-tp-atr", "0",
      "--htf-ema200-gate", "--rel-atr-band", "--rel-atr-lookback", RATR15],
     "Asya kutusu 04-09 -> Londra 09-13 (kutuda 20 bar)"),
    ("M6_orb15_h1_tp15",
     ["--htf-ema200-gate", "--orb-tp-r", "1.5"],
     "M1'in sabit 1.5R TP'li kontrolu (cikis mimarisi A/B)"),
]

JPY15 = [
    ("M7_jp_da15_h1_band", "donchian_adx",
     ["--htf-ema200-gate", "--rel-atr-band", "--rel-atr-lookback", RATR15],
     "Donchian+ADX + H1 kapi + ATR bandi"),
    ("M8_jp_dp15_h1_band", "donchian_pure",
     ["--chandelier", "2.5", "--htf-ema200-gate", "--rel-atr-band", "--rel-atr-lookback", RATR15],
     "Donchian saf + chand2.5 + H1 kapi + ATR bandi"),
    ("M9_jp_da15_h1_band_flat16", "donchian_adx",
     ["--htf-ema200-gate", "--flat-16", "--rel-atr-band", "--rel-atr-lookback", RATR15],
     "M7 + 16:00 UTC zorla kapanis"),
    ("M10_jp_da15_h1", "donchian_adx",
     ["--htf-ema200-gate"],
     "M7'nin bantsiz hali (bant etkisini izole eder)"),
    ("M11_jp_da15_plain", "donchian_adx", [], "kapi/band yok (kontrol)"),
]

EXIT15 = [
    ("Y1_orb15_dolarBE_kapali", "orb_ny",
     ["--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate", "--be-usd-fx", "0"], "fx12",
     "M1, dolar-kurali BE KAPALI (saf trail)"),
    ("Y2_orb15_pipBE24", "orb_ny",
     ["--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate",
      "--be-usd-fx", "0", "--be-pips", BE15], "fx12",
     "M1, dolar BE kapali + pip-BE 24 (x1.7 olcekli)"),
    ("Y3_orb15_flat16_pipBE24", "orb_ny",
     ["--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate", "--flat-16",
      "--be-usd-fx", "0", "--be-pips", BE15], "fx12",
     "M3 (flat16) + olcekli pip-BE"),
    ("Y4_jp15_dolarBE_kapali", "donchian_adx",
     ["--htf-ema200-gate", "--rel-atr-band", "--rel-atr-lookback", RATR15,
      "--be-usd-fx", "0"], "jpy2",
     "M7, dolar-kurali BE KAPALI"),
    ("Y5_jp15_pipBE24", "donchian_adx",
     ["--htf-ema200-gate", "--rel-atr-band", "--rel-atr-lookback", RATR15,
      "--be-usd-fx", "0", "--be-pips", BE15], "jpy2",
     "M7, dolar BE kapali + pip-BE 24"),
]

# m15stress: 2x spread altinda barajdan gecen adaylar (sonuclara gore doldurulur)
STRESS15 = [
    ("S1_M1_2x", "orb_ny", ["--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate"], "fx12",
     "M1, 2x maliyet"),
    ("S2_M3_2x", "orb_ny",
     ["--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate", "--flat-16"], "fx12",
     "M3 (flat16), 2x maliyet"),
    ("S3_M7_2x", "donchian_adx",
     ["--htf-ema200-gate", "--rel-atr-band", "--rel-atr-lookback", RATR15], "jpy2",
     "M7, 2x maliyet"),
    ("S4_M8_2x", "donchian_pure",
     ["--chandelier", "2.5", "--htf-ema200-gate", "--rel-atr-band", "--rel-atr-lookback", RATR15], "jpy2",
     "M8, 2x maliyet"),
    ("S5_M10_2x", "donchian_adx", ["--htf-ema200-gate"], "jpy2", "M10 (bantsiz), 2x maliyet"),
]

# Maliyet stresini IZOLE eden kol: motorun 3.0-pip spread kapisi 2x profilde
# EURNZD/GBPNZD girislerini tamamen kesiyor (islem kumesi degisir -> kiyas bozulur).
# --max-spread 99 ile kapi devre disi birakilir; 1x ve 2x AYNI islem kumesini gorur.
# En iyi iki adayin CJKIS MIMARISI kolunun 2x maliyet stresi (izole kapi ile)
COST3 = [
    ("Z1_orb15_flat16_pipBE24", "orb_ny",
     ["--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate", "--flat-16",
      "--be-usd-fx", "0", "--be-pips", BE15, "--max-spread", "99"], "fx12",
     "Y3 (en iyi ORB cikis mimarisi)"),
    ("Z2_jp15_dolarBE_kapali", "donchian_adx",
     ["--htf-ema200-gate", "--rel-atr-band", "--rel-atr-lookback", RATR15,
      "--be-usd-fx", "0", "--max-spread", "99"], "jpy2", "Y4 (JPY, dolar BE kapali)"),
    ("Z3_jp15_pipBE24", "donchian_adx",
     ["--htf-ema200-gate", "--rel-atr-band", "--rel-atr-lookback", RATR15,
      "--be-usd-fx", "0", "--be-pips", BE15, "--max-spread", "99"], "jpy2", "Y5 (JPY, pipBE24)"),
]

COST15 = [
    ("C1_orb15_flat16", "orb_ny",
     ["--chandelier", "2.5", "--mode-tp-atr", "0", "--htf-ema200-gate", "--flat-16", "--max-spread", "99"],
     "fx12", "M3 (baraj adayi)"),
    ("C2_jp15_da_h1_band", "donchian_adx",
     ["--htf-ema200-gate", "--rel-atr-band", "--rel-atr-lookback", RATR15, "--max-spread", "99"],
     "jpy2", "M7 (baraj adayi)"),
    ("C3_jp15_dp_h1_band", "donchian_pure",
     ["--chandelier", "2.5", "--htf-ema200-gate", "--rel-atr-band", "--rel-atr-lookback", RATR15,
      "--max-spread", "99"], "jpy2", "M8 (baraj adayi)"),
    ("C4_jp15_da_h1", "donchian_adx",
     ["--htf-ema200-gate", "--max-spread", "99"], "jpy2", "M10 (bantsiz)"),
]

WAVE_MAP = {
    "m15":       ("orbjpy", SPREAD1),
    "m15exit":   ("exit", SPREAD1),
    "m15exit2":  ("exit", SPREAD1),
    "m15stress": ("stress", SPREAD2),
    "m15cost1":  ("cost", SPREAD1),
    "m15cost2":  ("cost", SPREAD2),
    "m15cost3":  ("cost3", SPREAD2),
}


def build_cmd(name, entry_mode, extra, scope, window, spread):
    out_path = os.path.join(OUTDIR, f"{name}__{window}.json")
    cmd = [PY, REPLAY, "--entry-mode", entry_mode, "--tag", name,
           "--out", out_path, "--skip-old", "--cache", CACHE15,
           "--interval", "15m", "--max-open", "99", "--spread-profile", spread]
    if scope == "jpy2":
        cmd += ["--symbols", JPY2]
    else:
        cmd += ["--add-symbols", FX12, "--exclude-symbols", EXCL]
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
    name, entry_mode, extra, scope, window, spread = job
    cmd, out_path = build_cmd(name, entry_mode, extra, scope, window, spread)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    m = parse_metrics(out_path)
    log = (proc.stdout or "") + (proc.stderr or "")
    m.update({"name": name, "window": window, "scope": scope,
              "elapsed_s": round(time.time() - t0, 1)})
    if m.get("error"):
        m["log_tail"] = log[-500:]
    print(f"[{name} {window}] net={m.get('net')} n={m.get('trades')} wr={m.get('wr')} "
          f"pf={m.get('pf')} dd={m.get('dd')} ({m['elapsed_s']}s)"
          + (f" ERR={m['error']}" if m.get("error") else ""), flush=True)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wave", default="m15", choices=list(WAVE_MAP.keys()))
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)

    kind, spread = WAVE_MAP[args.wave]
    jobs = []
    if kind == "orbjpy":
        for w in WINDOWS:
            jobs += [(c[0], "orb_ny", c[1], "fx12", w, spread) for c in ORB15]
            jobs += [(c[0], c[1], c[2], "jpy2", w, spread) for c in JPY15]
    elif kind == "exit":
        for w in WINDOWS:
            jobs += [(c[0], c[1], c[2], c[3], w, spread) for c in EXIT15]
    elif kind == "cost":
        for w in WINDOWS:
            jobs += [(c[0], c[1], c[2], c[3], w, spread) for c in COST15]
    elif kind == "cost3":
        for w in WINDOWS:
            jobs += [(c[0], c[1], c[2], c[3], w, spread) for c in COST3]
    else:
        for w in WINDOWS:
            jobs += [(c[0], c[1], c[2], c[3], w, spread) for c in STRESS15]

    print(f"[PLAN] {args.wave}: {len(jobs)} kosum, {args.workers} worker, spread={spread}", flush=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(run_one, jobs):
            results.append(r)

    with open(os.path.join(OUTDIR, f"_summary_{args.wave}.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    print("\n" + "=" * 104)
    print(f"{'KONFIG':34s} {'PENCERE':7s} {'n':>5s} {'WR%':>6s} {'NET$':>9s} {'PF':>6s} {'DD$':>8s} {'JPY$':>9s}")
    print("-" * 104)
    for r in sorted(results, key=lambda x: (x["window"], -(x.get("net") or -9999))):
        if r.get("error"):
            print(f"{r['name']:34s} {r['window']:7s} HATA: {r['error']}")
            continue
        print(f"{r['name']:34s} {r['window']:7s} {r['trades']:>5} {r['wr']:>6.1f} "
              f"{r['net']:>+9.2f} {r['pf']:>6.2f} {r['dd']:>8.2f} {r.get('jpy_net',0):>+9.2f}")


if __name__ == "__main__":
    main()
