"""SİNYAL KENARI RAPORU — radarın kendi sinyalleri gerçekten tahmin ediyor mu? (2026-11-09)

NE YAPAR
--------
`velocity_candidates` tablosundan (tahmin → gerçekleşen) çiftlerini çekip
`app/signal_edge.py` ile ölçer:

* `ml_hit_probability` → `mfe_pct` (ve `touched_target`) IC'si
* radarın kendi `velocity_score`'u → `mfe_pct` IC'si
* kuantil getiri tablosu (dilinim başına ortalama MFE) + tekdüzelik
* hüküm: "sinyal bilgi taşıyor mu, yoksa sıralaması anlamsız mı?"

NEDEN ÖNEMLİ
------------
Sistemde onlarca strateji/sweep var ama "sıralama anlamlı mı" sorusu ölçülmüyordu.
IC ≈ 0 ise sinyal sıralamasına göre seçim yapmak (en yüksek skoru al) **gürültü
seçmek** demektir — parametre sayısını artırmak bunu düzeltmez.

LOOK-AHEAD YOK
--------------
`mfe_pct` ve `touched_target` sinyal ÜRETİLDİKTEN sonra hesaplanır
(`mark_velocity_candidate_evaluated`), yani ileriye dönük sonuçtur. Aynı barın
getirisi kullanılmaz.

KULLANIM
--------
    python -m scripts.report_signal_edge                # son 180 gün
    ... --days 90 --quantiles 5
    ... --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import signal_edge as se  # noqa: E402


async def _fetch(days: int) -> list[dict]:
    import asyncpg

    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL gerekli (backend/.env veya ortam değişkeni).")
    cutoff = (time.time() - days * 86400) if days > 0 else None
    sql = """
        SELECT velocity_score, ml_hit_probability, mfe_pct, touched_target,
               target_pct, volume_ratio, ret3_pct, symbol, created_at, evaluated_at
          FROM velocity_candidates
         WHERE mfe_pct IS NOT NULL
           AND ($1::double precision IS NULL OR evaluated_at >= $1)
         ORDER BY evaluated_at ASC
    """
    conn = await asyncpg.connect(url)
    try:
        return [dict(r) for r in await conn.fetch(sql, cutoff)]
    finally:
        await conn.close()


def _section(title: str, signals: list[float], returns: list[float], q: int) -> dict:
    res = se.evaluate(signals, returns, q)
    print("-" * 84)
    print(f"{title}   (n={res['n']})")
    print(f"  IC = {res['ic']}   t = {res['ic_tstat']['t']}   "
          f"p≈{res['ic_tstat']['p_approx']}   anlamlı={res['ic_tstat']['significant']}")
    if res["quantiles"]:
        mono = res["monotonicity"]
        print(f"  {'dilim':<8}{'n':>6}{'ort. MFE %':>13}{'isabet':>9}")
        for row in res["quantiles"]:
            print(f"  {row['label']:<8}{row['samples']:>6}{row['mean_return']:>13.4f}"
                  f"{row['hit_rate']:>9.3f}")
        print(f"  tekdüzelik: rho={mono['spearman']} tekdüze={mono['monotonic']}")
    print(f"  >>> {res['verdict']}")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Radar sinyallerinin IC/kuantil ölçümü")
    ap.add_argument("--days", type=int, default=180, help="geriye bakış (0 = tümü)")
    ap.add_argument("--quantiles", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = asyncio.run(_fetch(args.days))
    if not rows:
        print("Kayıt yok: `velocity_candidates` içinde `mfe_pct` dolu değerlendirilmiş")
        print("aday bulunamadı. Değerlendirme döngüsü (mark_velocity_candidate_evaluated)")
        print("henüz yeterli veri üretmemiş olabilir.")
        return 1

    print("=" * 84)
    print(f"SİNYAL KENARI · {len(rows)} değerlendirilmiş aday · son {args.days} gün")
    print("=" * 84)
    print("Not: `mfe_pct` = sinyal sonrası ulaşılan en yüksek elverişli hareket (%).")
    print("     IC, sinyal sıralaması ile bu hareketin sıralaması arasındaki Spearman.")
    print()

    out = {}

    prob = [(r["ml_hit_probability"], r["mfe_pct"]) for r in rows
            if r.get("ml_hit_probability") is not None]
    if len(prob) >= 30:
        out["ml_hit_probability"] = _section(
            "ML hit probability → MFE", [p for p, _ in prob], [m for _, m in prob],
            args.quantiles)
    else:
        print(f"- ML hit probability: yetersiz veri ({len(prob)} satır, min 30)")

    score = [(r["velocity_score"], r["mfe_pct"]) for r in rows
             if r.get("velocity_score") is not None]
    if len(score) >= 30:
        out["velocity_score"] = _section(
            "Radar velocity_score → MFE", [s for s, _ in score], [m for _, m in score],
            args.quantiles)
    else:
        print(f"- velocity_score: yetersiz veri ({len(score)} satır, min 30)")

    # İkili sonuç: touched_target ile IC (nokta-ikili korelasyon yerine sıra IC)
    binary = [(r["ml_hit_probability"], 1.0 if r["touched_target"] else 0.0)
              for r in rows if r.get("ml_hit_probability") is not None
              and r.get("touched_target") is not None]
    if len(binary) >= 30:
        out["ml_prob_vs_touched"] = _section(
            "ML hit probability → touched_target (ikili)",
            [p for p, _ in binary], [t for _, t in binary], 5)
    print("-" * 84)
    print()
    print("Yorum: |IC| < 0.03 veya t < 1.96 ise sinyal SIRALAMASI bilgi taşımıyor")
    print("       → 'en yüksek skoru seç' kuralı gürültü seçiyordur. Önce ölçümü")
    print("       düzeltmek gerekir; parametre sayısını artırmak bunu çözmez.")

    if args.json:
        print(json.dumps({k: {"ic": v["ic"], "t": v["ic_tstat"]["t"],
                              "significant": v["ic_tstat"]["significant"],
                              "verdict": v["verdict"]} for k, v in out.items()},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
