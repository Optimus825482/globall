"""GEOMETRİ GÖLGESİ RAPORU — gerçek vs alternatif (2026-11-09)

NE YAPAR
--------
`velocity_candidates.outcome_details.shadow_geometry` altına yazılan alternatif
geometri sonuçlarını (varsayılan SL %0,9 / hedef ATR×4) **mevcut geometriyle
EŞLEŞTİRİLMİŞ (paired)** olarak karşılaştırır. Aynı aday üzerinde iki ölçüm
olduğu için fark, aday havuzundaki değişimden arındırılmıştır → bootstrap GA'sı
güvenilir.

NEDEN BU, §14'teki KARŞI-OLGUSAL ANALİZDEN ÜSTÜN
------------------------------------------------
§14 `mfe_pct` üzerinden çalıştı ve "stop mu önce, hedef mi?" sırasını
bilemiyordu (alt/üst sınır). Gölge ise **gerçek bar penceresinde, gerçek
değerlendirme fonksiyonuyla** ölçülür → tahmin değil ÖLÇÜM.

KULLANIM
--------
    python -m scripts.report_geometry_shadow                 # tüm birikmiş veri
    ... --days 21                                            # son 3 hafta
    ... --min-samples 300                                    # erken karar verme
    ... --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def _fetch(days: int) -> list[dict]:
    import asyncpg

    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL gerekli")
    cutoff = None
    if days > 0:
        import time
        cutoff = time.time() - days * 86400
    sql = """
        SELECT created_at,
               net_pct,
               outcome_details->>'status_reason' AS real_status,
               (outcome_details->'shadow_geometry'->>'status_reason') AS shadow_status,
               (outcome_details->'shadow_geometry'->>'net_pct')::float AS shadow_net,
               (outcome_details->'shadow_geometry'->>'target_pct')::float AS shadow_target,
               (outcome_details->'shadow_geometry'->>'atr_pct')::float AS atr_pct
          FROM velocity_candidates
         WHERE outcome_details ? 'shadow_geometry'
           AND ($1::double precision IS NULL OR created_at >= $1)
         ORDER BY created_at ASC
    """
    conn = await asyncpg.connect(url)
    try:
        return [dict(r) for r in await conn.fetch(sql, cutoff)]
    finally:
        await conn.close()


def _block(label: str, net: np.ndarray, statuses: list[str]) -> dict:
    n = net.size
    ev = float(net.mean()) if n else float("nan")
    wins = float((net > 0).mean()) if n else float("nan")
    counts: dict[str, int] = {}
    for s in statuses:
        counts[s or "?"] = counts.get(s or "?", 0) + 1
    print(f"  {label:<22}n={n:>6}  EV={ev:+.4f}  kazanma={wins:.3f}  "
          f"{'  '.join(f'{k}={v}' for k, v in sorted(counts.items()))}")
    return {"n": n, "ev": ev, "win_rate": wins, "status_counts": counts}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Geometri gölgesi: gerçek vs alternatif")
    ap.add_argument("--days", type=int, default=0, help="0 = tüm birikmiş veri")
    ap.add_argument("--min-samples", type=int, default=300)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = asyncio.run(_fetch(args.days))
    usable = [r for r in rows if r["net_pct"] is not None and r["shadow_net"] is not None]
    print("=" * 90)
    print(f"GEOMETRİ GÖLGESİ · {len(rows)} kayıt · {len(usable)} eşleştirilmiş (paired)")
    print("=" * 90)

    if len(usable) < args.min_samples:
        print(f"\nYETERSİZ ÖRNEK: {len(usable)} < {args.min_samples}. "
              f"Gölge mod yeni başladıysa 2-3 hafta bekleyin.")
        print("(Erken bakmak yanıltıcı olur — küçük örnekte EV gürültüsü baskındır.)")
        if rows:
            print(f"\nnot: {len(rows)} kayıt var ama bazılarında net_pct eksik "
                  f"(PENDING / MAX_HORIZON).")
        return 0

    real_net = np.array([float(r["net_pct"]) for r in usable])
    shadow_net = np.array([float(r["shadow_net"]) for r in usable])
    real_status = [r["real_status"] for r in usable]
    shadow_status = [r["shadow_status"] for r in usable]

    print("\n[1] GEOMETRİLER")
    real = _block("GERÇEK (SL 1.5/mevcut)", real_net, real_status)
    shadow = _block("GÖLGE (SL 0.9/ATR×4)", shadow_net, shadow_status)

    # Hedeflerin gerçekten ayrıştığını doğrula (ayrıştırma çalışıyor mu?)
    tg = np.array([r["shadow_target"] for r in usable if r["shadow_target"] is not None])
    print(f"\n[2] AYRIŞTIRMA KONTROLÜ — gölge hedefi ort={tg.mean():.3f}% "
          f"medyan={np.median(tg):.3f}% aralık=[{tg.min():.2f}, {tg.max():.2f}]")
    print("    (hedef artık ATR'ye bağlı, olasılığa DEĞİL — §13 bozukluğu ayrıştırıldı)")

    print("\n[3] EŞLEŞTİRİLMİŞ FARK (paired)")
    diff = shadow_net - real_net
    print(f"    ΔEV = {diff.mean():+.4f} puan  ·  medyan Δ = {np.median(diff):+.4f}  "
          f"·  gölge daha iyi olan işlem oranı = {(diff > 0).mean():.3f}")
    rng = np.random.default_rng(7)
    n = diff.size
    boot = np.array([diff[rng.integers(0, n, n)].mean() for _ in range(args.boot)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f"    %95 GA = [{lo:+.4f}, {hi:+.4f}]  -> "
          f"{'ANLAMLI' if lo > 0 or hi < 0 else 'ANLAMSIZ (sıfırı içeriyor)'}")

    print("\n[4] GEÇİŞ MATRİSİ (gerçek → gölge)")
    pairs: dict[tuple[str, str], int] = {}
    for r_s, s_s in zip(real_status, shadow_status):
        key = (r_s or "?", s_s or "?")
        pairs[key] = pairs.get(key, 0) + 1
    for (a, b), c in sorted(pairs.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {a:<22} → {b:<22} {c:>6}")

    print("\n[5] HÜKÜM")
    better = diff.mean()
    if lo > 0:
        verdict = (f"GÖLGE GEOMETRİ ANLAMLI DAHA İYİ (ΔEV {better:+.3f}) "
                   f"→ canlıya alma değerlendirilebilir")
    elif hi < 0:
        verdict = (f"GÖLGE ANLAMLI DAHA KÖTÜ (ΔEV {better:+.3f}) → "
                   f"SL %1,5 mevcut ayarı korunmalı")
    else:
        verdict = ("FARK İSTATİSTİKSEL OLARAK ANLAMSIZ → daha fazla örnek "
                   "gerekli (veya geometri gerçekten etkisiz)")
    print(f"  {verdict}")
    print(f"\n  Mutlak seviye: gerçek EV {real['ev']:+.4f} · gölge EV {shadow['ev']:+.4f}")
    if max(real["ev"], shadow["ev"]) < 0:
        print("  ⚠ İKİ GEOMETRİ DE NEGATİF: geometri seçimi tek başına kârlılık")
        print("    üretmiyor — aday havuzu/filtre kalitesi de ele alınmalı (§14).")

    if args.json:
        print(json.dumps({"paired_n": n, "real": real, "shadow": shadow,
                          "delta_ev": float(diff.mean()),
                          "delta_ci": [float(lo), float(hi)], "verdict": verdict},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
