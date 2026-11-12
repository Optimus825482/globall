#!/usr/bin/env python3
"""BACKTEST REGRESYON PAKETİ — strateji çıktıları sessizce kaydı mı? (2026-11-12)

NEDEN
-----
Motor, maliyet modeli ve gösterge hesapları değiştikçe backtest sonuçları sessizce
kayabilir. Birim testler bunu yakalamaz: spread/saat/çıkış mantığı **sayısal**
değişebilir ve testler yeşil kalır. Bu betik altın-master karşılaştırması yapar.

HIZ (2026-11-12, Erkan: "çok uzun sürüyor, kısalt")
--------------------------------------------------
1. **PARALEL**: hücreler `--jobs` (varsayılan 4) ile eşzamanlı koşar.
2. **PROFİL**: `quick` (varsayılan) kısa pencerelerle ~2-3 dk; `full` kanonik
   (30/60 gün + 2y/5y) ~6-8 dk. İki profilin beklenen değerleri ayrı tutulur.
3. **DEĞİŞİKLİK YOKSA ATLA**: `--if-changed` (varsayılan açık) izlenen motor
   dosyalarının hash'ini saklar; dosyalar değişmediyse hiç koşmaz.

KAPSAM
------
  replay `cur` / `prior`  — ölçülen saatlik spread + `--bar-tz-offset 2`
  arm `london_breakout`   — 5m (quick: 1 yıl, full: 2 yıl)
  arm `tokyo_window`      — 1h (quick: 2 yıl, full: 5 yıl)

Kullanim:
    python scripts/backtest_regression.py                  # quick, paralel, atlama açık
    python scripts/backtest_regression.py --profile full   # kanonik
    python scripts/backtest_regression.py --force          # hash'e bakmadan koş
    python scripts/backtest_regression.py --update         # baseline'ı yenile (DİKKAT)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_PATH = os.path.join(ROOT, "scripts", "backtest_baseline.json")
OUT_DIR = os.path.join(ROOT, "outputs", "regression")
HASH_PATH = os.path.join(OUT_DIR, ".source_hash")

#: Regresyonu etkileyen dosyalar — biri değişirse koşu gerekir.
WATCHED = [
    "scripts/forex_replay_backtest.py",
    "scripts/fx_arm_backtest.py",
    "backend/app/routers/forex.py",
    "backend/app/arms/base.py",
    "backend/app/arms/london_breakout.py",
    "backend/app/arms/tokyo_window.py",
]


def _source_hash() -> str:
    h = hashlib.sha256()
    for rel in WATCHED:
        p = os.path.join(ROOT, rel)
        h.update(rel.encode())
        try:
            h.update(open(p, "rb").read())
        except OSError:
            h.update(b"<missing>")
    return h.hexdigest()[:16]


def _run(cmd: list[str], log_path: str) -> int:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        return subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT).returncode


def _cmp(expect: dict, got: dict, tol: dict | None = None) -> list[str]:
    tol = tol or {}
    diffs = []
    for key, want in expect.items():
        have = got.get(key)
        t = float(tol.get(key, 0.0))
        if have is None:
            diffs.append(f"{key}: beklenen {want} ama sonuçta YOK")
        elif isinstance(want, (int, float)):
            if abs(float(have) - float(want)) > t:
                diffs.append(f"{key}: beklenen {want} ± {t}, gelen {have}")
        elif str(have) != str(want):
            diffs.append(f"{key}: beklenen {want}, gelen {have}")
    return diffs


def _replay_cell(name: str, spec: dict, profile: str, py: str):
    out = os.path.join(OUT_DIR, f"replay_{profile}_{name}.json")
    cmd = [py, "scripts/forex_replay_backtest.py", "--interval", "5m", "--skip-old",
           "--spread-profile", "outputs/fx_spread_replay_profile.json",
           "--bar-tz-offset", "2", "--tag", f"rg_{profile}_{name}", "--out", out] + spec["args"]
    t0 = time.time()
    rc = _run(cmd, os.path.join(OUT_DIR, f"replay_{profile}_{name}.log"))
    if rc != 0 or not os.path.exists(out):
        return None, [f"koşu başarısız (exit {rc})"], int(time.time() - t0)
    var = json.load(open(out, encoding="utf-8"))["variants"]["NEW"]
    got = {k: var.get(k) for k in ("trades", "profit_factor", "net_pnl_usd")}
    return got, _cmp(spec["expect"], got, tol={"net_pnl_usd": 0.01}), int(time.time() - t0)


def _arm_cell(name: str, spec: dict, profile: str, py: str):
    out = os.path.join(OUT_DIR, f"arm_{profile}_{name}.json")
    cmd = [py, "scripts/fx_arm_backtest.py"] + spec["args"] + ["--json", out]
    t0 = time.time()
    rc = _run(cmd, os.path.join(OUT_DIR, f"arm_{profile}_{name}.log"))
    if rc != 0 or not os.path.exists(out):
        return None, [f"koşu başarısız (exit {rc})"], int(time.time() - t0)
    tot = json.load(open(out, encoding="utf-8")).get("total") or {}
    got = {"n": tot.get("n"), "expectancy_r": tot.get("beklenti_R"),
           "profit_factor": tot.get("PF")}
    return got, _cmp(spec["expect"], got, tol={"expectancy_r": 0.0005,
                                               "profit_factor": 0.002}), int(time.time() - t0)


def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest regresyon paketi (hızlı/paralel)")
    ap.add_argument("--profile", choices=["quick", "full"], default="quick")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--force", action="store_true", help="hash değişmese de koş")
    ap.add_argument("--if-changed", dest="if_changed", action="store_true", default=True)
    ap.add_argument("--no-if-changed", dest="if_changed", action="store_false")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "result.json"))
    args = ap.parse_args()

    base_all = json.load(open(BASE_PATH, encoding="utf-8"))
    base = base_all.get(args.profile) or {}
    if not base:
        print(f"[HATA] baseline'da '{args.profile}' profili yok: {BASE_PATH}")
        return 2
    py = sys.executable
    os.makedirs(OUT_DIR, exist_ok=True)

    cur_hash = _source_hash()
    if args.if_changed and not args.force and not args.update and os.path.exists(HASH_PATH):
        if open(HASH_PATH, encoding="utf-8").read().strip() == cur_hash:
            print(f"[ATLANDI] Motor dosyaları değişmedi (hash {cur_hash}). Zorlamak için --force.")
            return 0

    t_start = time.time()
    cells = ([("replay", n, s) for n, s in (base.get("replay") or {}).items()]
             + [("arm", n, s) for n, s in (base.get("arms") or {}).items()])
    results: dict = {"profile": args.profile, "replay": {}, "arms": {},
                     "failures": [], "source_hash": cur_hash}
    failures: list[str] = []

    def worker(cell):
        kind, name, spec = cell
        fn = _replay_cell if kind == "replay" else _arm_cell
        got, diffs, sec = fn(name, spec, args.profile, py)
        return kind, name, got, diffs, sec

    with cf.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        for kind, name, got, diffs, sec in ex.map(worker, cells):
            bucket = results["replay"] if kind == "replay" else results["arms"]
            bucket[name] = {"got": got, "diffs": diffs, "sec": sec}
            label = f"{kind}/{name}"
            if got:
                detail = ((f"trades={got.get('trades')} PF={got.get('profit_factor')} "
                           f"net={got.get('net_pnl_usd')}") if kind == "replay" else
                          (f"n={got.get('n')} beklentiR={got.get('expectancy_r')} "
                           f"PF={got.get('profit_factor')}"))
                print(f"  {label:<24} {detail} {'OK' if not diffs else 'SAPMA'} ({sec}s)", flush=True)
            else:
                print(f"  {label:<24} KOŞMADI ({sec}s)", flush=True)
            failures += [f"{label}: {d}" for d in diffs]

    elapsed = int(time.time() - t_start)
    results["failures"] = failures
    results["elapsed_sec"] = elapsed
    json.dump(results, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    if args.update:
        if failures:
            print("\n[--update] SAPMA VAR — baseline GÜNCELLENMEDİ (bilinçli değilse güncelleme).")
            return 1
        print("\n[--update] Sapma yok. Yeni beklenen değerler (elle baseline'a yaz):")
        for kind in ("replay", "arms"):
            for name, v in results[kind].items():
                print(f"  {kind}/{name}: {v['got']}")
        return 0

    if failures:
        print(f"\n=== REGRESYON ({elapsed}s) ===")
        for f in failures:
            print("  ✗", f)
        print(f"\nDetay: {args.out}")
        return 1

    open(HASH_PATH, "w", encoding="utf-8").write(cur_hash)
    print(f"\n=== TEMİZ ({elapsed}s, profil={args.profile}): çıktılar baseline ile uyumlu ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
