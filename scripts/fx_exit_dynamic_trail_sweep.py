#!/usr/bin/env python3
"""Çıkış yönetimi A/B süpürmesi: TP-iptal + dinamik takip mesafesi (2026-10-09).

Kullanıcı hipotezi (otonom işlem gözlemi):
  1) Trailing devreye girince sabit TP kaldırılsın → trend koşusu kesilmesin.
  2) Takip mesafesi sembole + ATR'ye + TREND GÜCÜNE göre dinamik olsun.

Bu sürücü hipotezi KANIT-ÖNCE test eder (FX_KALIBRASYON_PLANI.md disiplini):
  - İzole defter (--max-open 99): slot rekabeti yok, her varyant aynı girişlerle kıyaslanır.
  - Gerçek spread profili (IC Markets ölçümü) — maliyet adaleti.
  - IS (in-sample) = 09-07→10-07, OOS (out-of-sample) = 08-08→09-07: AYNI ayar iki pencerede.
  - Yalnız NEW defteri (--skip-old) — OLD referansına gerek yok, ~2x hız.

Varyantlar (forex_replay_backtest.py bayraklarıyla; KOD DEĞİŞİKLİĞİ YOK):
  V01_BASE        : mevcut motor (TP silahlı)
  V02_NOTPC       : --no-tp-crypto        → kripto TP kapalı (canlı varsayılanı eşler)
  V03_NOTRAIL     : --no-tp-on-trail-live → hipotez (1): trend koşusunda TP çekilir
  V04_CHAND12     : --chandelier 1.2      → motor canlı varsayılanı (MFE−1.2×ATR)
  V05_CHAND20     : --chandelier 2.0      → daha geniş nefes (trend koşusunu taşır)
  V06_CHAND25     : --chandelier 2.5      → en geniş (ORB araştırmasının değeri)
  V07_NOTPC_CH20  : --no-tp-crypto + --chandelier 2.0  → BTC aday (canlı taban + chandelier)
  V08_NOTRAIL_CH20: --no-tp-on-trail-live + --chandelier 2.0 → XAU/FX aday (hipotez tam)

Semboller: BTCUSD, XAUUSD, EURUSD, GBPUSD (kullanıcının izlediği + 3 majör referans).
Çıktı: outputs/exit_sweep/*.json + liderlik tablosu (stdout + summary JSON).

Kullanım:
  python scripts/fx_exit_dynamic_trail_sweep.py                 # tam matris (16 koşum)
  python scripts/fx_exit_dynamic_trail_sweep.py --smoke         # tek varyant tek pencere
  python scripts/fx_exit_dynamic_trail_sweep.py --windows IS    # yalnız in-sample
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
CACHE = os.path.join(ROOT, "outputs", "replay_cache_60d_fxwide.json")
SPREAD = os.path.join(ROOT, "outputs", "fx_spread_reality.json")
OUTDIR = os.path.join(ROOT, "outputs", "exit_sweep")

SYMBOLS = "BTCUSD,XAUUSD,EURUSD,GBPUSD"

# CLI ile geçersiz kılınabilir (taze pencere farklı cache'ten gelebilir, ör. mt5_all_5m)
CACHE_OVERRIDE = None
SYMBOLS_OVERRIDE = None

WINDOWS = {
    "IS":  ("2026-09-07", "2026-10-07"),   # in-sample: parametre burada seçilir
    "OOS": ("2026-08-08", "2026-09-07"),   # out-of-sample: kazanan burada doğrulanır
    "OOS2": ("2026-07-15", "2026-08-15"),  # ikinci bağımsız pencere (60g cache başı)
    # TAZE pencere (2026-10-09): V18 ön-kayıtlı doğrulaması için — hiç bakılmamış dönem.
    # Kaynak: replay_cache_mt5_all_5m.json (06-18→10-08). NOT: BTCUSD bu cache'te 07-23'ten
    # başlıyor → bu pencerede BTC YOK; kenar zaten ~%95 XAU olduğundan kabul edildi.
    "F1":  ("2026-06-20", "2026-07-14"),
}

# (ad, ek bayraklar, açıklama)
VARIANTS = [
    ("V01_BASE", [], "Mevcut motor (referans)"),
    ("V02_NOTPC", ["--no-tp-crypto"], "Kripto TP kapalı (canlı varsayılanı)"),
    ("V03_NOTRAIL", ["--no-tp-on-trail-live"], "Hipotez(1): trailing akt. TP çekilir"),
    ("V04_CHAND12", ["--chandelier", "1.2"], "Chandelier 1.2 (motor canlı varsayılanı)"),
    ("V05_CHAND20", ["--chandelier", "2.0"], "Chandelier 2.0 (geniş nefes)"),
    ("V06_CHAND25", ["--chandelier", "2.5"], "Chandelier 2.5 (en geniş)"),
    ("V07_NOTPC_CH20", ["--no-tp-crypto", "--chandelier", "2.0"], "BTC aday: TP kapalı + chand2.0"),
    ("V08_NOTRAIL_CH20", ["--no-tp-on-trail-live", "--chandelier", "2.0"], "XAU/FX aday: TP çekilir + chand2.0"),
    # --- Faz 2 (2026-10-09): ADX-rejimli dinamik trailing vs TP-ratchet ---
    ("V09_ADXT_15", ["--adx-trail", "--adx-trend-mult", "1.5"], "ADX-trail: trend×1.5"),
    ("V10_ADXT_20", ["--adx-trail", "--adx-trend-mult", "2.0"], "ADX-trail: trend×2.0"),
    ("V11_ADXT_30", ["--adx-trail", "--adx-trend-mult", "3.0"], "ADX-trail: trend×3.0"),
    ("V12_ADXT_TIGHT", ["--adx-trail", "--adx-trend-mult", "2.0", "--adx-chop-mult", "0.6"], "ADX-trail: trend×2.0 + chop×0.6 (sıkı)"),
    ("V13_RATCHET", ["--tp-ratchet"], "TP-ratchet (trail mesafesi = spec)"),
    ("V14_RATCHET_ADX20", ["--tp-ratchet", "--adx-trail", "--adx-trend-mult", "2.0"], "TP-ratchet + ADX-trail×2.0"),
    ("V15_RATCHET_GAP1", ["--tp-ratchet", "--tp-ratchet-gap-atr", "1.0"], "TP-ratchet + 1×ATR ek pay"),
    # --- Faz 3 (2026-10-09): TP-iptal ile ADX-trail kombinasyonu (ikisi de "kazananı koştur") ---
    ("V16_NADXT20", ["--no-tp-on-trail-live", "--adx-trail", "--adx-trend-mult", "2.0"], "TP-iptal + ADX-trail×2.0"),
    ("V17_NADXT15", ["--no-tp-on-trail-live", "--adx-trail", "--adx-trend-mult", "1.5"], "TP-iptal + ADX-trail×1.5"),
    ("V18_NCHOP06", ["--no-tp-on-trail-live", "--adx-trail", "--adx-chop-mult", "0.6"], "TP-iptal + chop×0.6 (chop'ta sıkı)"),
    # --- Faz 4: mekanizma izolasyonu — chop-sıkılaştırma tek başına mı, TP-iptal mi? ---
    ("V19_CHOPONLY", ["--no-tp-on-trail-live", "--adx-trail", "--adx-trend-mult", "1.0", "--adx-chop-mult", "0.6"], "TP-iptal + yalnız chop×0.6 (trend nötr)"),
    ("V20_CHOPNOTP", ["--adx-trail", "--adx-trend-mult", "1.0", "--adx-chop-mult", "0.6"], "chop×0.6 tek başına (TP-iptal YOK)"),
]


def build_cmd(name: str, window: str, extra: list) -> tuple:
    out_path = os.path.join(OUTDIR, f"{name}__{window}.json")
    cmd = [PY, REPLAY,
           "--cache", CACHE_OVERRIDE or CACHE,
           "--spread-profile", SPREAD,
           "--symbols", SYMBOLS_OVERRIDE or SYMBOLS,
           "--max-open", "99",
           "--skip-old",
           "--entry-mode", "classic",
           "--tag", name,
           "--out", out_path]
    start, end = WINDOWS[window]
    cmd += ["--start", start, "--end", end]
    cmd += list(extra)
    return cmd, out_path


def parse_metrics(out_path: str) -> dict:
    if not os.path.exists(out_path):
        return {"error": "no_json"}
    try:
        with open(out_path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        return {"error": f"json:{e}"}
    v = (d.get("variants") or {}).get("NEW")
    if not v:
        return {"error": "no_new"}
    ps = v.get("per_symbol") or {}
    per_sym = {s: round(float(x.get("pnl", 0.0)), 2) for s, x in ps.items()}
    return {
        "net": round(float(v.get("net_pnl_usd", 0.0)), 2),
        "trades": int(v.get("trades", 0)),
        "win_rate": round(float(v.get("win_rate", 0.0)), 1),
        "pf": round(float(v.get("profit_factor", 0.0)), 2),
        "max_dd": round(float(v.get("max_drawdown_usd", 0.0)), 2),
        "per_symbol": per_sym,
        "exit_reasons": v.get("exit_reasons") or {},
    }


def run_one(job: tuple) -> dict:
    name, window, extra = job
    cmd, out_path = build_cmd(name, window, extra)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=900)
        rc = proc.returncode
        tail = (proc.stderr or "")[-400:]
    except subprocess.TimeoutExpired:
        return {"variant": name, "window": window, "error": "timeout"}
    dt = round(time.time() - t0, 1)
    m = parse_metrics(out_path)
    m.update({"variant": name, "window": window, "rc": rc, "sec": dt})
    if rc != 0 and "error" not in m:
        m["error"] = f"rc={rc} {tail}"
    return m


def fmt_table(rows: list) -> str:
    lines = []
    lines.append(f"{'Varyant':<18}{'Pencere':<6}{'Net$':>10}{'İşlem':>7}{'WR%':>7}{'PF':>6}{'MaxDD$':>9}  "
                 f"{'BTC':>8}{'XAU':>8}{'EUR':>8}{'GBP':>8}")
    lines.append("-" * 96)
    for r in sorted(rows, key=lambda x: (x.get("window", ""), x.get("variant", ""))):
        if "error" in r and "net" not in r:
            lines.append(f"{r['variant']:<18}{r['window']:<6}   HATA: {r['error']}")
            continue
        ps = r.get("per_symbol", {})
        lines.append(
            f"{r['variant']:<18}{r['window']:<6}{r.get('net', 0):>10.2f}{r.get('trades', 0):>7}"
            f"{r.get('win_rate', 0):>7.1f}{r.get('pf', 0):>6.2f}{r.get('max_dd', 0):>9.2f}  "
            f"{ps.get('BTCUSD', 0):>8.2f}{ps.get('XAUUSD', 0):>8.2f}"
            f"{ps.get('EURUSD', 0):>8.2f}{ps.get('GBPUSD', 0):>8.2f}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", default="IS,OOS", help="IS,OOS veya tek pencere")
    ap.add_argument("--variants", default="", help="virgüllü varyant adı filtresi (boş = hepsi)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cache", default="", help="cache yolu geçersiz kıl (boş = varsayılan 60g fxwide)")
    ap.add_argument("--symbols", default="", help="sembol listesi geçersiz kıl (boş = varsayılan)")
    ap.add_argument("--smoke", action="store_true", help="tek varyant (V01) tek pencere (IS)")
    args = ap.parse_args()

    global CACHE_OVERRIDE, SYMBOLS_OVERRIDE
    if args.cache:
        CACHE_OVERRIDE = os.path.abspath(args.cache)
    if args.symbols:
        SYMBOLS_OVERRIDE = args.symbols

    os.makedirs(OUTDIR, exist_ok=True)

    windows = [w.strip() for w in args.windows.split(",") if w.strip() in WINDOWS]
    wanted = {v.strip() for v in args.variants.split(",") if v.strip()}
    variants = [v for v in VARIANTS if (not wanted or v[0] in wanted)]
    if args.smoke:
        windows = ["IS"]
        variants = [VARIANTS[0]]

    jobs = [(name, w, extra) for w in windows for (name, extra, _desc) in variants]
    print(f"[sweep] {len(jobs)} koşum başlıyor ({len(variants)} varyant × {len(windows)} pencere), "
          f"workers={args.workers}", flush=True)
    print(f"[sweep] PY={PY}", flush=True)

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(run_one, j): j for j in jobs}
        for fut in concurrent.futures.as_completed(futs):
            r = fut.result()
            rows.append(r)
            tag = "OK" if "error" not in r else f"HATA:{r['error'][:40]}"
            print(f"  [{tag:<20}] {r['variant']:<18} {r['window']:<4} "
                  f"net={r.get('net', 'NA')} sec={r.get('sec', '?')}", flush=True)

    summary = {"symbols": SYMBOLS, "windows": WINDOWS, "rows": rows}
    sp = os.path.join(OUTDIR, "SUMMARY.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    table = fmt_table(rows)
    with open(os.path.join(OUTDIR, "SUMMARY.md"), "w", encoding="utf-8") as f:
        f.write("# Çıkış A/B süpürmesi\n\n```\n" + table + "\n```\n")

    print("\n" + table)
    print(f"\n[sweep] özet: {sp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
