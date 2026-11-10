#!/usr/bin/env python3
"""REPLAY PAYOFF KARŞILAŞTIRMA — PF yerine "kazanan/kaybeden" ölçütü (2026-11-10)

NEDEN
-----
Replay raporu bugüne kadar PF / net USD / isabet ile okunuyordu. Broker defterinin
ölçümü (bkz. `scripts/fx_symbol_expectancy.py`) kök nedenin **payoff** olduğunu
gösterdi: ortalama kazanan +0.43R, ortalama kaybeden −0.87R → payoff 0.50, ve bu
payoff için break-even isabet %66.8. Yani "isabeti artır" hedefi yanlış hedefti;
doğru hedef **payoff'u 0.67'nin üstüne çıkarmak**.

Bu betik replay JSON'larını (birden çok varyant dosyası) bu gözle okur:
  n · isabet · ort kazanan $ · ort kaybeden $ · payoff · bu payoff için break-even isabet
  · işlem başına beklenti · PF · net · en iyi/en kötü sembol

Kullanim:
    python scripts/fx_payoff_compare.py outputs/payoff_base_60d.json outputs/payoff_tp25_60d.json
    python scripts/fx_payoff_compare.py --variant NEW outputs/payoff_*.json --json outputs/payoff_cmp.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys


def variant_stats(v: dict) -> dict:
    """Bir varyantın kapalı işlemlerinden payoff/break-even hesabı."""
    daily = v.get("daily_stats") or {}
    wins = losses = 0
    gw = gl = 0.0
    for ds in daily.values():
        wins += int(ds.get("wins") or 0)
        losses += int(ds.get("losses") or 0)
        gw += float(ds.get("gw") or 0.0)
        gl += float(ds.get("gl") or 0.0)
    n = int(v.get("trades") or 0)
    if not n or not wins:
        return {"trades": n, "payoff": None}
    avg_win = gw / wins if wins else 0.0
    avg_loss = gl / losses if losses else 0.0
    be = 100.0 * avg_loss / (avg_win + avg_loss) if (avg_win + avg_loss) else 0.0
    syms = v.get("per_symbol") or {}
    ranked = sorted(syms.items(), key=lambda kv: float(kv[1].get("pnl") or 0.0))
    return {
        "trades": n,
        "win_pct": round(100.0 * wins / n, 1),
        "avg_win_usd": round(avg_win, 3),
        "avg_loss_usd": round(avg_loss, 3),
        "payoff": round(avg_win / avg_loss, 3) if avg_loss else None,
        "break_even_win_pct": round(be, 1),
        "edge_pct": round(100.0 * wins / n - be, 1),
        "expectancy_usd": round(float(v.get("avg_pnl_usd") or 0.0), 3),
        "net_usd": round(float(v.get("net_pnl_usd") or 0.0), 2),
        "profit_factor": v.get("profit_factor"),
        "max_dd_usd": v.get("max_drawdown_usd"),
        "worst_symbols": [(s, round(float(x.get("pnl") or 0.0), 2)) for s, x in ranked[:3]],
        "best_symbols": [(s, round(float(x.get("pnl") or 0.0), 2)) for s, x in ranked[-3:][::-1]],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Replay payoff (kazanan/kaybeden) karşılaştırma")
    ap.add_argument("files", nargs="+", help="replay rapor JSON'ları (glob olabilir)")
    ap.add_argument("--variant", default="NEW", help="hangi varyant okunacak (varsayılan NEW)")
    ap.add_argument("--json", default="", help="karşılaştırma JSON çıktısı")
    args = ap.parse_args()

    paths: list[str] = []
    for f in args.files:
        paths.extend(sorted(glob.glob(f)) or [f])

    rows: list[tuple[str, dict]] = []
    for p in paths:
        if not os.path.exists(p):
            print(f"[UYARI] yok: {p}")
            continue
        with open(p, encoding="utf-8") as fh:
            rep = json.load(fh)
        variants = rep.get("variants") or {}
        v = variants.get(args.variant)
        if v is None:
            # varyant adı farklıysa (mini mod vb.) ilk uygun olanı al
            v = next(iter(variants.values()), None)
            if v is None:
                print(f"[UYARI] varyant yok: {p}")
                continue
        rows.append((os.path.basename(p), variant_stats(v)))

    if not rows:
        print("Karşılaştırılacak rapor bulunamadı.")
        return 1

    hdr = (f"{'rapor':<34}{'n':>6}{'isabet%':>9}{'kaz$':>8}{'kay$':>8}{'payoff':>8}"
           f"{'BE_isabet%':>11}{'kenar%':>8}{'beklenti$':>11}{'net$':>10}{'PF':>7}")
    print(hdr)
    print("-" * len(hdr))
    for name, s in sorted(rows, key=lambda kv: -(kv[1].get("payoff") or 0.0)):
        if s.get("payoff") is None:
            print(f"{name:<34}{s.get('trades', 0):>6}  — payoff hesaplanamadı (kazanan yok)")
            continue
        print(f"{name:<34}{s['trades']:>6}{s['win_pct']:>9.1f}{s['avg_win_usd']:>8.2f}"
              f"{s['avg_loss_usd']:>8.2f}{s['payoff']:>8.2f}{s['break_even_win_pct']:>11.1f}"
              f"{s['edge_pct']:>+8.1f}{s['expectancy_usd']:>+11.3f}{s['net_usd']:>+10.0f}"
              f"{(s['profit_factor'] or 0):>7.2f}")
    print("\n  payoff   = ortalama kazanan / ortalama kaybeden (hedef: ≥ 0.67 → break-even isabet %40)")
    print("  BE_isabet= bu payoff ile başabaş için gereken isabet (gerçek isabet onun altındaysa zarar)")
    print("  kenar%   = gerçek isabet − break-even isabet (pozitif olmalı)")
    for name, s in rows:
        if s.get("payoff") is not None:
            print(f"\n  {name}: en kötü {s['worst_symbols']} | en iyi {s['best_symbols']}")

    if args.json:
        out = args.json if os.path.isabs(args.json) else os.path.join(os.path.dirname(__file__), "..", args.json)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({n: s for n, s in rows}, fh, ensure_ascii=False, indent=2)
        print(f"\nJSON: {os.path.abspath(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
