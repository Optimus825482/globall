#!/usr/bin/env python3
"""EMA+ADX geri-cekilme skalpi — TEMIZ 48 SAAT kampanyasi (2026-10-08).

Neden yeni surucu: `scripts/fx_eap_ema_adx_pullback.py` cikislari `outputs/eap14/`
dizininde w48 ve m15 dalgalariyla PAYLASILIYOR; 15m kosumu 5m H48 dosyalarinin
uzerine yazdi ve `_summary_w48.json` bayat kaldi (0 islem). Bu surucu AYRI dizine
yazar (`outputs/eap_h48/`) ve her kosumu (tf x mod x konfig x pencere) tekil adla
saklar; boylece hicbir sonuc ezilmez.

Kural seti (kullanici spesifikasyonu, birebir):
  1) EMA8 > EMA21 > EMA50 -> yalniz LONG ; EMA8 < EMA21 < EMA50 -> yalniz SHORT
  2) ADX(14) > 25
  3) Fiyat EMA21'e geri cekilir (bar EMA21'i keser / 0.30xATR temas) ve trend
     yonunde kapanisla doner (onay bari)
  4) SL = 1.5 x ATR(14) ; TP = 2.0 x ATR(14) VEYA ATR tabanli trailing (chandelier)

Iki kapi modu:
  PURE : kural seti BIREBIR — seans/minATR/EV kapilari KAPALI (spec'te yok)
  LIVE : motor varsayilanlari (major seans 7-20 UTC, minATR 4.0, EV kalkani, spread 3.0)

Kapsam: 12 FX cifti + XAUUSD + BTCUSD (kullanici istegi: altin ve BTC dahil).
Maliyet: gercek p95 spread profili (`outputs/fx_spread_p95.json`).

Kullanim:
    python -m scripts.fx_eap_h48_campaign            # tam kampanya
    python -m scripts.fx_eap_h48_campaign --quick     # yalniz H48 penceresi
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
OUTDIR = os.path.join(ROOT, "outputs", "eap_h48")

SYMS = ("EURUSD,GBPUSD,USDJPY,USDCHF,USDCAD,NZDUSD,EURJPY,GBPJPY,"
        "EURCHF,GBPCHF,EURNZD,GBPNZD,XAUUSD,BTCUSD")

# Pencere kodu -> (baslangic, bitis-dahil-degil).  H48 = kullanicinin istedigi 48 saat.
WINDOWS = {
    "H48": ("2026-10-05", "2026-10-07"),   # istenen 48 saat (veri sonu 10-07 07:58)
    "L30": ("2026-09-07", "2026-10-07"),   # 30 gunluk baglam (protokol OOS)
    "PX":  ("2026-08-10", "2026-08-31"),   # ikinci gorulmus pencere
}

# Konfig kodu -> (ekstra argumanlar, aciklama)
CONFIGS = {
    "C1_tp2":       (["--eap-tp-atr", "2.0"], "SL 1.5xATR / TP 2.0xATR (spec sabit TP, R=1.33)"),
    "C2_tp3":       (["--eap-tp-atr", "3.0"], "SL 1.5xATR / TP 3.0xATR (R=2 kontrol)"),
    "C3_trail":     (["--eap-tp-atr", "0", "--mode-tp-atr", "0", "--chandelier", "2.0"],
                     "SL 1.5xATR / sabit TP yok, ATR trailing (chandelier 2.0xATR)"),
    "C4_tp2_cap3":  (["--eap-tp-atr", "2.0", "--eap-max-per-day", "3"],
                     "C1 + gunde azami 3 giris (yigin onleme)"),
}

TFS = {"5m": CACHE5, "15m": CACHE15}

# Mod -> kapilar
MODES = {
    "PURE": ["--no-ev-guard", "--major-hours", "", "--major-min-atr", "0"],
    "LIVE": [],
}


def build_cmd(name, mode, tf, window, cfg):
    extra = CONFIGS[cfg][0]
    start, end = WINDOWS[window]
    out_path = os.path.join(OUTDIR, f"{cfg}__{mode}__{tf}__{window}.json")
    cmd = [PY, REPLAY, "--entry-mode", "ema_adx_pullback", "--tag", f"{cfg}|{mode}|{tf}",
           "--out", out_path, "--skip-old", "--cache", TFS[tf],
           "--add-symbols", SYMS, "--max-open", "99", "--spread-profile", SPREAD,
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
        "per_symbol": {s: round(x["pnl"], 2) for s, x in sorted(ps.items(), key=lambda kv: -kv[1]["pnl"])},
    }


def run_one(job):
    cfg, mode, tf, window = job
    cmd, out_path = build_cmd(cfg, mode, tf, window, cfg)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    m = parse_metrics(out_path)
    m.update({"cfg": cfg, "mode": mode, "tf": tf, "window": window,
              "elapsed_s": round(time.time() - t0, 1)})
    if m.get("error"):
        m["log_tail"] = ((proc.stdout or "") + (proc.stderr or ""))[-800:]
    print(f"[{cfg} {mode} {tf} {window}] net={m.get('net')} n={m.get('trades')} "
          f"wr={m.get('wr')} pf={m.get('pf')} dd={m.get('dd')} "
          f"xau={m.get('xau')} btc={m.get('btc')} ({m['elapsed_s']}s)"
          + (f" ERR={m['error']}" if m.get("error") else ""), flush=True)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="yalniz H48 penceresi")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)

    wins = ["H48"] if args.quick else list(WINDOWS.keys())
    jobs = [(cfg, mode, tf, w) for w in wins for tf in TFS for mode in MODES for cfg in CONFIGS]
    print(f"[PLAN] {len(jobs)} kosum, pencereler={wins}", flush=True)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(run_one, jobs):
            results.append(r)

    tag = "quick" if args.quick else "full"
    with open(os.path.join(OUTDIR, f"_summary_{tag}.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    def table(window):
        rows = [r for r in results if r["window"] == window and not r.get("error")]
        if not rows:
            return
        print(f"\n=== {window} ===")
        print(f"{'KONFIG':13s}{'MOD':5s}{'TF':4s}{'n':>6s}{'WR%':>7s}{'NET$':>10s}"
              f"{'PF':>6s}{'DD$':>8s}{'XAU$':>9s}{'BTC$':>8s}{'JPY$':>9s}")
        print("-" * 91)
        for r in sorted(rows, key=lambda x: (x["tf"], x["mode"], x["cfg"])):
            print(f"{r['cfg']:13s}{r['mode']:5s}{r['tf']:4s}{r['trades']:>6}{r['wr']:>7.1f}"
                  f"{r['net']:>+10.2f}{r['pf']:>6.2f}{r['dd']:>8.2f}{r['xau']:>+9.2f}"
                  f"{r['btc']:>+8.2f}{r['jpy']:>+9.2f}")

    for w in wins:
        table(w)
    errs = [r for r in results if r.get("error")]
    if errs:
        print(f"\n[HATA] {len(errs)} kosum")
        for e in errs:
            print(f"  {e['cfg']} {e['mode']} {e['tf']} {e['window']}: {e['error']}")


if __name__ == "__main__":
    main()
