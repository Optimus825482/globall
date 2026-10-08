#!/usr/bin/env python3
"""goose AI stratejileri #3 (Supertrend+RSI) ve #4 (BB Band Walk) — 24/48 SAAT replay.

Kullanici istegi (2026-10-08): BE istismarini kaldir (--no-be), XAU ayri test et,
digerleri (FX+BTC) ayri — 24 saatlik replay.

Kural setleri (goose sessions.db 20261008_2, birebir):
  #3 supertrend_rsi : ST(10,3) yonu + EMA200 tarafi + ADX>25 + RSI(14) pullback
                      (40-50 sarkip 50 ustu kapanis -> BUY; 50-60 -> 50 alti -> SELL)
                      SL 1.5xATR14; TP 2.0xATR14 VEYA TP'siz + ST-flip cikisi
  #4 bb_bandwalk    : son 8 barda 3+ bant temasi + kapanislar SMA20 tarafi + ADX>25
                      + EMA200 tarafi + BBW squeeze korumasi (alt %40) + re-entry
                      SL 1.5xATR14 (swing duzeltmeli); TP yok -> orta-bant/karsi-bant cikisi

Kapsam gruplari (kullanici istegi: XAU ayri, digerleri ayri):
  FX  : 12 FX cifti + BTCUSD   (--symbols ile)
  XAU : yalniz XAUUSD
Maliyet: gercek p95 spread profili. Cikti: outputs/str_h24/ (ayri dizin).
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
OUTDIR = os.path.join(ROOT, "outputs", "str_h24")

FXBTC = "EURUSD,GBPUSD,USDJPY,USDCHF,USDCAD,NZDUSD,EURJPY,GBPJPY," \
        "EURCHF,GBPCHF,EURNZD,GBPNZD,BTCUSD"
GROUPS = {"FX": FXBTC, "XAU": "XAUUSD"}

# H24 = kullanıcının istediği 24 saat (en taze tam gün: 2026-10-06)
WINDOW = ("2026-10-06", "2026-10-07")

TFS = {"5m": CACHE5, "15m": CACHE15}

# Strateji #3 TP varyantları + BE kolu (kullanıcı: BE istismarını kaldır)
SRP_CONFIGS = {
    "S_tp2":     (["--srp-tp-atr", "2.0"], "#3 sabit TP 2.0xATR14 (spec sabit seçenek)"),
    "S_stflip":  (["--srp-tp-atr", "0", "--st-flip-exit", "--chandelier", "2.0"],
                  "#3 TP yok + ST çevirince çık (spec trail önerisi; chandelier yedek)"),
    "S_tp2_nobe":   (["--srp-tp-atr", "2.0", "--no-be"], "#3 TP 2.0xATR14, BE kilidi KAPALI"),
    "S_stflip_nobe": (["--srp-tp-atr", "0", "--st-flip-exit", "--chandelier", "2.0", "--no-be"],
                      "#3 TP yok + ST flip çıkışı, BE kilidi KAPALI"),
}
# Strateji #4 varyantları: çıkış yöntemi + BE kolu
BBW_CONFIGS = {
    "B_opp":        (["--bbw-no-exit-mid"], "#4 çıkış: yalnız karşı-bant dokunuşu"),
    "B_opp_nobe":   (["--bbw-no-exit-mid", "--no-be"], "#4 karşı-bant çıkışı, BE kilidi KAPALI"),
}

CONFIGS = {**SRP_CONFIGS, **BBW_CONFIGS}

MODES = {
    "PURE": ["--no-ev-guard", "--major-hours", "", "--major-min-atr", "0"],
}


def build_cmd(mode_name, mode, tf, cfg, grp):
    extra = CONFIGS[cfg][0]
    start, end = WINDOW
    entry_mode = "supertrend_rsi" if cfg.startswith("S_") else "bb_bandwalk"
    out_path = os.path.join(OUTDIR, f"{grp}__{cfg}__{mode}__{tf}.json")
    cmd = [PY, REPLAY, "--entry-mode", entry_mode, "--tag", f"{grp}|{cfg}|{mode}|{tf}",
           "--out", out_path, "--skip-old", "--cache", TFS[tf],
           "--add-symbols", GROUPS[grp], "--max-open", "99", "--spread-profile", SPREAD,
           "--start", start, "--end", end]
    if tf == "15m":
        cmd += ["--interval", "15m"]
    cmd += MODES[mode]
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

    def g(s):
        return round(ps.get(s, {}).get("pnl", 0.0), 2)
    jpy = round(sum(x["pnl"] for s, x in ps.items() if "JPY" in s), 2)
    fx = round(sum(x["pnl"] for s, x in ps.items()
                   if s not in ("XAUUSD", "BTCUSD") and "JPY" not in s), 2)
    return {
        "trades": v.get("trades"), "wr": v.get("win_rate"),
        "net": round(v.get("net_pnl_usd", 0.0), 2), "pf": v.get("profit_factor"),
        "dd": round(v.get("max_drawdown_usd", 0.0), 2),
        "xau": g("XAUUSD"), "btc": g("BTCUSD"), "jpy": jpy, "fx_maj": fx,
        "n_xau": ps.get("XAUUSD", {}).get("n", 0), "n_btc": ps.get("BTCUSD", {}).get("n", 0),
        "exits": {k: v2.get("n") for k, v2 in (v.get("exit_reasons") or {}).items()},
        "daily": v.get("daily_pnl") or {},
        "per_symbol": {s: {"n": x["n"], "pnl": round(x["pnl"], 2)}
                       for s, x in sorted(ps.items(), key=lambda kv: -kv[1]["pnl"])},
    }


def run_one(job):
    grp, mode_name, mode, tf, cfg = job
    cmd, out_path = build_cmd(mode_name, mode, tf, cfg, grp)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    m = parse_metrics(out_path)
    m.update({"grp": grp, "strat": mode_name, "mode": mode, "tf": tf, "cfg": cfg,
              "elapsed_s": round(time.time() - t0, 1)})
    if m.get("error"):
        m["log_tail"] = ((proc.stdout or "") + (proc.stderr or ""))[-800:]
    print(f"[{grp} {mode_name} {mode} {tf} {cfg}] net={m.get('net')} n={m.get('trades')} "
          f"wr={m.get('wr')} pf={m.get('pf')} dd={m.get('dd')} ({m['elapsed_s']}s)"
          + (f" ERR={m['error']}" if m.get("error") else ""), flush=True)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--tfs", default="5m,15m", help="koşulacak zaman dilimleri")
    ap.add_argument("--groups", default="FX,XAU")
    args = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)

    tfs = [t.strip() for t in args.tfs.split(",") if t.strip()]
    grps = [g.strip() for g in args.groups.split(",") if g.strip()]
    jobs = [(grp, s, "PURE", tf, cfg) for grp in grps for s in ("S3", "S4") for tf in tfs
            for cfg in CONFIGS if cfg.startswith("S_") == (s == "S3")]
    print(f"[PLAN] {len(jobs)} koşum — H24 {WINDOW[0]}→{WINDOW[1]}, "
          f"gruplar={grps} (FX=12çift+BTC, XAU=altın), stratejiler=S3 S4, BE kolu dahil", flush=True)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(run_one, jobs):
            results.append(r)

    with open(os.path.join(OUTDIR, "_summary_h24.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    rows = [r for r in results if not r.get("error")]
    if rows:
        print(f"\n=== H24 ({WINDOW[0]} → {WINDOW[1]}) — strateji x grup x BE kolu ===")
        print(f"{'GRP':4s}{'STR':4s}{'CFG':15s}{'TF':4s}{'n':>5s}{'WR%':>7s}{'NET$':>10s}"
              f"{'PF':>6s}{'DD$':>8s}{'JPY$':>9s}")
        print("-" * 84)
        for r in sorted(rows, key=lambda x: (x["grp"], x["strat"], x["cfg"], x["tf"])):
            print(f"{r['grp']:4s}{r['strat']:4s}{r['cfg']:15s}{r['tf']:4s}{r['trades']:>5}"
                  f"{r['wr']:>7.1f}{r['net']:>+10.2f}{r['pf']:>6.2f}{r['dd']:>8.2f}"
                  f"{r['jpy']:>+9.2f}")
    errs = [r for r in results if r.get("error")]
    if errs:
        print(f"\n[HATA] {len(errs)} koşum")
        for e in errs:
            print(f"  {e.get('grp')} {e['strat']} {e['cfg']} {e['tf']}: {e['error']}")
            print(f"    tail: {e.get('log_tail','')[-300:]}")


if __name__ == "__main__":
    main()
