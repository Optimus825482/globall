#!/usr/bin/env python3
"""replay_strateji_gunluk.py koşum matrisi: strateji x zaman dilimi (x risk) paralel.

Her hucre ayri surec (motor global durum tasidigi icin). Sonuclar
outputs/replay_strateji/gun_<tag>.json; ozet outputs/replay_strateji/ozet_<tur>.json.

Kullanim:
  python scripts/replay_strateji_tarama.py --tur 1 --tfs m3,m5,m15 --strategies all --jobs 10
  python scripts/replay_strateji_tarama.py --tur 2 --risk-gold 25 --risk-btc 10 ...
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from replay_strateji_gunluk import STRATEGIES  # noqa: E402

OUT_DIR = os.path.join(ROOT, "outputs", "replay_strateji")


def run_cell(strategy: str, tf: str, tur: str, extra_args: list[str], symbol: str = "") -> tuple[str, int, float]:
    tag = f"t{tur}_{strategy}_{tf}" + (f"_{symbol}" if symbol else "")
    log = os.path.join(OUT_DIR, f"log_{tag}.txt")
    cmd = [sys.executable, "-u", os.path.join(ROOT, "scripts", "replay_strateji_gunluk.py"),
           "--strategy", strategy, "--tf", tf, "--tag", tag] + extra_args
    if symbol:
        cmd += ["--symbols", symbol]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.call(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env, cwd=ROOT)
    return tag, rc, time.time() - t0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tur", default="1")
    ap.add_argument("--tfs", default="m3,m5,m15")
    ap.add_argument("--strategies", default="all")
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--risk-gold", type=float, default=0.0)
    ap.add_argument("--risk-btc", type=float, default=0.0)
    ap.add_argument("--sl-atr", type=float, default=0.0)
    ap.add_argument("--tp-r", type=float, default=0.0)
    ap.add_argument("--extra", default="")
    ap.add_argument("--symbols", default="", help="Virgullu: her sembol AYRI hucre (izole defter)")
    ap.add_argument("--cache-pattern", default="", help="Ornek: outputs/replay_cache_fx21_{tf}.json")
    ap.add_argument("--db", action="store_true", help="Veri kaynagi PostgreSQL historical_candles (--source db)")
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    strategies = list(STRATEGIES) if args.strategies == "all" else [s for s in args.strategies.split(",") if s]
    tfs = [t for t in args.tfs.split(",") if t]
    extra: list[str] = []
    if args.risk_gold > 0:
        extra += ["--risk-gold", str(args.risk_gold)]
    if args.risk_btc > 0:
        extra += ["--risk-btc", str(args.risk_btc)]
    if args.sl_atr > 0:
        extra += ["--sl-atr", str(args.sl_atr)]
    if args.tp_r > 0:
        extra += ["--tp-r", str(args.tp_r)]
    if args.extra:
        extra += [f"--extra={args.extra}"]  # '=' sart: deger '--' ile baslayabilir
    symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()] or [""]
    cells = [(s, tf, sym) for tf in tfs for s in strategies for sym in symbols]
    print(f"[TARAMA] tur {args.tur}: {len(cells)} hucre, {args.jobs} paralel, ek {extra}", flush=True)
    results = []

    def _extra_for(tf: str) -> list[str]:
        if args.db:
            return extra + ["--source", "db"]
        if not args.cache_pattern:
            return extra
        return extra + ["--cache", args.cache_pattern.format(tf=tf)]

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(run_cell, s, tf, args.tur, _extra_for(tf), sym): (s, tf, sym) for s, tf, sym in cells}
        for fut in as_completed(futs):
            tag, rc, secs = fut.result()
            gun = os.path.join(OUT_DIR, f"gun_{tag}.json")
            row = {"tag": tag, "rc": rc, "secs": round(secs)}
            if rc == 0 and os.path.exists(gun):
                ev = json.load(open(gun, encoding="utf-8"))
                c14, c7 = ev["combined"]["14w"], ev["combined"]["7w"]
                row.update({"trades": ev["trades"], "wr": ev["win_rate"], "net": ev["net"], "pf": ev["pf"],
                            "h14_hedef": c14["target_days"], "h14_gun": c14["days_with_trades"], "h14_iflas": c14["ruin_days"],
                            "h14_ort": c14["mean"], "h14_best": c14["best"], "h7_hedef": c7["target_days"], "h7_gun": c7["days_with_trades"], "h7_ort": c7["mean"],
                            "per_symbol": {s: {"h14_hedef": v["14w"]["target_days"], "h14_sum": v["14w"]["sum"], "h14_best": v["14w"]["best"]} for s, v in ev["per_symbol"].items()}})
            results.append(row)
            print(f"  {tag:34s} rc={rc} {row.get('secs')}s islem {row.get('trades')} wr {row.get('wr')} net {row.get('net')} | 14h hedef {row.get('h14_hedef')}/{row.get('h14_gun')} iflas {row.get('h14_iflas')} ort {row.get('h14_ort')} best {row.get('h14_best')}", flush=True)
    results.sort(key=lambda r: (-(r.get("h14_hedef") or 0), -(r.get("net") or -1e9)))
    with open(os.path.join(OUT_DIR, f"ozet_tur{args.tur}.json"), "w", encoding="utf-8") as fh:
        json.dump({"tur": args.tur, "extra": extra, "rows": results}, fh, ensure_ascii=False, indent=1)
    print("[TARAMA] bitti; ozet yazildi", flush=True)


if __name__ == "__main__":
    main()
