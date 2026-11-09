"""OLASILIK KALİBRASYONU RAPORU — DB'den eğri kur, artefakt üret (2026-11-09)

NE YAPAR
--------
`velocity_candidates` tablosundaki **tahmin → sonuç** çiftlerinden
(`ml_hit_probability` → `touched_target`) izotonik kalibrasyon eğrisi kurar,
dürüstlük metriklerini (Brier / log-loss / ECE / güvenilirlik kovaları) basar
ve artefaktı JSON olarak yazar. Üretim katmanı bu JSON'u okuyup ham olasılığı
kalibre edebilir; böylece üretim imajına pandas/scipy EKLEMEK gerekmez.

NEDEN GEREKLİ
-------------
`ml_forecast.py` bir "hit_probability" (`predict_proba[:,1]`) üretiyor ve bu
değer eşik olarak kullanılıyor. Ham `predict_proba` genelde KALİBRE DEĞİLDİR
(sınıf dengesizliği + ağaç modellerinin aşırı-güven eğilimi). %87 diyen
sinyaller gerçekte %62 tutuyorsa eşik anlamsızdır. ECE bu farkı ölçer;
izotonik eğri düzeltir; başabaş olasılık ise **çekimserlik** eşiğini verir.

KULLANIM
--------
    python -m scripts.report_probability_calibration                 # DB'den oku, raporla
    ... --save artifacts/ml_calibration.json                         # artefakt yaz
    ... --days 120 --min-samples 120                                 # pencere/örnek ayarı
    ... --rr 1.5                                                     # ödül/risk (başabaş için)

WALK-FORWARD GÜVENLİĞİ
----------------------
Eğri, veriyi zamana göre böler: ilk yarıda eğitir, ikinci yarıda TEST eder ve
**test** metriğini basar. Rapor "eğri kendi verisini gördü" yanılsaması
taşımaz; `insample` ve `outsample` metrikleri ayrı gösterilir.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ml_probability as mp  # noqa: E402

DEFAULT_OUT = ROOT / "artifacts" / "ml_calibration.json"


async def _fetch_rows(days: int) -> list[dict]:
    """Değerlendirilmiş adayları çek (tahmin + sonuç birlikte)."""
    import asyncpg

    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL gerekli (backend/.env veya ortam değişkeni).")
    cutoff = None
    if days > 0:
        import time
        cutoff = time.time() - days * 86400

    sql = """
        SELECT ml_hit_probability, touched_target, target_pct, mfe_pct,
               evaluated_at, created_at, symbol, status
          FROM velocity_candidates
         WHERE ml_hit_probability IS NOT NULL
           AND touched_target IS NOT NULL
           AND evaluated_at IS NOT NULL
           AND ($1::double precision IS NULL OR evaluated_at >= $1)
         ORDER BY evaluated_at ASC
    """
    conn = await asyncpg.connect(url)
    try:
        records = await conn.fetch(sql, cutoff)
    finally:
        await conn.close()
    return [dict(r) for r in records]


def _fmt(x, nd=4) -> str:
    return "-" if x is None else f"{float(x):.{nd}f}"


def _report(cal: dict, test_cal: dict | None, rr: float, train_n: int, test_n: int) -> None:
    gate = mp.break_even_probability(rr)
    print("=" * 84)
    print("OLASILIK KALİBRASYONU — ham `predict_proba` dürüst mü?")
    print("=" * 84)
    print(f"gözlem: eğitim={train_n}  test={test_n}  |  taban isabet={_fmt(cal.get('base_rate'))}"
          f"  |  başabaş p (RR={rr})={gate:.3f}")
    print()

    if not cal.get("fitted"):
        print("EĞRİ KURULMADI:", cal.get("reason"))
        print("→ Yetersiz/tek sınıflı veri. Sahte eğri ÜRETİLMEZ; ham olasılık kullanılmaya devam eder.")
        return

    raw, cals = cal.get("metrics_raw") or {}, cal.get("metrics_calibrated") or {}
    print(f"{'metrik':<12}{'ham':>12}{'kalibre':>12}   yorum")
    print("-" * 84)
    for key, label, good in (("brier", "Brier", "küçük iyi"), ("log_loss", "log-loss", "küçük iyi"),
                             ("ece", "ECE", "küçük iyi")):
        r, c = raw.get(key), cals.get(key)
        delta = "" if (r is None or c is None) else ("  iyileşti" if c < r else "  KÖTÜLEŞTİ")
        print(f"{label:<12}{_fmt(r):>12}{_fmt(c):>12}   {good}{delta}")
    print()
    print("Güvenilirlik kovaları (kalibre sonrası; gap<0 = model hâlâ aşırı güvenli):")
    print(f"  {'kova':<12}{'n':>6}{'güven':>9}{'gerçek':>9}{'gap':>9}")
    for b in (cal.get("bins") or [])[:12]:
        print(f"  {b['lo']:.1f}-{b['hi']:.1f}   {b['samples']:>6}{b['confidence']:>9.3f}"
              f"{b['accuracy']:>9.3f}{b['gap']:>+9.3f}")
    print()
    if test_cal is not None and test_cal.get("fitted"):
        print("TEST KÜMESİ (eğrinin görmediği dönem):")
        t_raw, t_cal = test_cal.get("metrics_raw") or {}, test_cal.get("metrics_calibrated") or {}
        print(f"  Brier  ham={_fmt(t_raw.get('brier'))} → kalibre={_fmt(t_cal.get('brier'))}")
        print(f"  ECE    ham={_fmt(t_raw.get('ece'))} → kalibre={_fmt(t_cal.get('ece'))}")
        if (t_raw.get("brier") is not None and t_cal.get("brier") is not None
                and t_cal["brier"] > t_raw["brier"]):
            print("  ⚠ TEST kümesinde kalibrasyon KÖTÜLEŞTİ → eğri aşırı uyumlu, yayınlamayın.")
    else:
        print("TEST KÜMESİ: yeterli gözlem yok — dış-örneklem doğrulaması yapılamadı.")
    print()
    print(f"ÇEKİMSERLİK: kalibre olasılık {gate:.3f} altındaysa giriş YAPILMAMALI.")
    print("  (bu eşik komisyon/spread hariçtir; gerçek RR ve maliyetle biraz yukarı çekin)")


async def _main_async(args) -> int:
    rows = await _fetch_rows(args.days)
    if not rows:
        print("Kayıt yok: `velocity_candidates` içinde ml_hit_probability + touched_target dolu satır bulunamadı.")
        print("→ Değerlendirme döngüsü henüz çalışmamış olabilir (mark_velocity_candidate_evaluated).")
        return 1

    train, test = mp.split_walk_forward(rows)
    cal = mp.build_from_rows(train, min_samples=args.min_samples)
    test_cal = mp.build_from_rows(test, min_samples=args.min_samples) if len(test) >= args.min_samples else None

    # Eğri tüm veriyle de kurulur (yayınlanacak artefakt: daha çok örnek = daha iyi).
    full = mp.build_from_rows(rows, min_samples=args.min_samples)
    mp.store_state(full)

    _report(cal, test_cal, args.rr, len(train), len(test))

    if args.save and full.get("fitted"):
        if mp.save_state(args.save, full):
            print(f"\nartefakt yazıldı: {args.save}")
        else:
            print(f"\nHATA: artefakt yazılamadı: {args.save}")
    elif args.save:
        print("\nartefakt YAZILMADI (eğri kurulmadı) — eski artefakt varsa korunur.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ML olasılık kalibrasyonu raporu")
    ap.add_argument("--days", type=int, default=180, help="geriye bakış penceresi (0 = tümü)")
    ap.add_argument("--min-samples", type=int, default=mp.MIN_SAMPLES)
    ap.add_argument("--rr", type=float, default=mp.DEFAULT_REWARD_RISK, help="ödül/risk oranı")
    ap.add_argument("--save", nargs="?", const=str(DEFAULT_OUT), default=None,
                    help=f"artefakt yolu (varsayılan {DEFAULT_OUT})")
    ap.add_argument("--json", action="store_true", help="yalnız artefaktı stdout'a bas")
    args = ap.parse_args(argv)
    rc = asyncio.run(_main_async(args))
    if args.json and args.save is None:
        cal = mp.current_calibration()
        print(json.dumps(cal, ensure_ascii=False, indent=2))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
