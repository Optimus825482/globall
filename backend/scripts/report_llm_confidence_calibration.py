"""LLM GÜVEN KALİBRASYONU — Brier/ECE ölçer, izotonik eğri kurar, EŞİK önerir (2026-11-09)

SORUN (panelde ölçüldü)
-----------------------
`llm_trade_reviews` üzerinde: Brier **0.2679** vs taban oran **0.226** → **skill
−0.185** (taban oranı söylemekten bile kötü); AUC **0.541** (rastgeleden ayırt
edilemiyor). Kova tablosu: 60-80% güven kovasında **öngörülen %65, gerçekleşen
%37** (n=196) → model 40% üstünde SİSTEMATİK AŞIRI GÜVENLİ.

Panel bunu **ölçüyor**; bu betik **düzeltiyor**: `app/ml_probability` ile
izotonik kalibrasyon eğrisi kurar, kalibre edilmiş Brier/ECE'yi raporlar ve
**çekimserlik eşiği** önerir (`llm_review_min_confidence` kaç olmalı?).

VERİ
----
`llm_trade_reviews`: `confidence` (0-100) + gölge sonucu (`shadow_pips`) +
`sl_pips`. Gözlem = "işlem kazandı mı" (shadow_pips > 0). R = shadow_pips/sl_pips.
KALİBRASYON SİNYALİ politika kararından bağımsızdır: onaylanan VE reddedilen
tüm çözülmüş kararlar kullanılır (güven puanı sonucu öngörüyor mu sorusu).

KULLANIM
--------
    python -m scripts.report_llm_confidence_calibration
    ... --days 60 --min-samples 150
    ... --save artifacts/llm_confidence_calibration.json
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

DEFAULT_OUT = ROOT / "artifacts" / "llm_confidence_calibration.json"


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
        SELECT created_at, confidence, decision, applied, shadow_pips, sl_pips,
               tp_pips, mfe_pips, mae_pips, exploration, control_veto, latency_ms, error
          FROM llm_trade_reviews
         WHERE confidence IS NOT NULL
           AND shadow_pips IS NOT NULL
           AND ($1::double precision IS NULL OR created_at >= $1)
         ORDER BY created_at ASC
    """
    conn = await asyncpg.connect(url)
    try:
        return [dict(r) for r in await conn.fetch(sql, cutoff)]
    finally:
        await conn.close()


def _rows_to_series(rows: list[dict]) -> tuple[list[float], list[int], list[float]]:
    """(ham olasılık, kazanç?, R) dizileri — R = shadow_pips/sl_pips."""
    probs: list[float] = []
    hits: list[int] = []
    rs: list[float] = []
    for r in rows:
        try:
            conf = float(r["confidence"])
            pips = float(r["shadow_pips"])
        except (TypeError, ValueError):
            continue
        sl = r.get("sl_pips")
        try:
            sl_f = float(sl)
        except (TypeError, ValueError):
            sl_f = 0.0
        probs.append(max(0.0, min(1.0, conf / 100.0)))
        hits.append(1 if pips > 0 else 0)
        rs.append(round(pips / sl_f, 3) if sl_f > 0 else 0.0)
    return probs, hits, rs


def _suggest_threshold(cal: dict, break_even: float) -> dict:
    """Kalibre olasılık break-even'ı hangi HAM güvenden sonra aşıyor?"""
    xs = cal.get("x_thresholds") or []
    ys = cal.get("y_thresholds") or []
    if not cal.get("fitted") or not xs:
        return {"suggested_min_confidence": None, "reason": "eğri kurulmadı"}
    for x, y in zip(xs, ys):
        if float(y) >= break_even:
            return {
                "suggested_min_confidence": int(round(float(x) * 100)),
                "calibrated_at_that_point": round(float(y), 4),
                "break_even": round(break_even, 4),
                "reason": "kalibre olasılık ilk kez break-even'ı bu ham güvende aşıyor",
            }
    return {
        "suggested_min_confidence": 100,
        "calibrated_at_that_point": round(float(ys[-1]), 4),
        "break_even": round(break_even, 4),
        "reason": "kalibre olasılık hiçbir güven düzeyinde break-even'ı aşmıyor → "
                  "LLM onayı bu veriyle işlem açmayı GEREKTİRMİYOR",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="LLM güven kalibrasyonu ve eşik önerisi")
    ap.add_argument("--days", type=int, default=0, help="0 = tüm veri")
    ap.add_argument("--min-samples", type=int, default=mp.MIN_SAMPLES)
    ap.add_argument("--save", nargs="?", const=str(DEFAULT_OUT), default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = asyncio.run(_fetch(args.days))
    probs, hits, rs = _rows_to_series(rows)
    print("=" * 84)
    print(f"LLM GÜVEN KALİBRASYONU · {len(rows)} çözülmüş karar · güven+sonuç eşleşen {len(probs)}")
    print("=" * 84)
    if len(probs) < args.min_samples:
        print(f"\nYETERSİZ ÖRNEK: {len(probs)} < {args.min_samples}. Eğri kurulmaz (sahte eğri üretilmez).")
        return 0

    base_rate = sum(hits) / len(hits)
    wins = [r for r, h in zip(rs, hits) if h]
    losses = [r for r, h in zip(rs, hits) if not h]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    break_even = (avg_loss / (avg_win + avg_loss)) if (avg_win + avg_loss) > 0 else 0.5
    print(f"taban isabet={base_rate:.3f} · ort. R kazanç={avg_win:+.2f} kayıp={-avg_loss:+.2f} "
          f"· R oranı={avg_win/avg_loss if avg_loss else float('inf'):.2f}")
    print(f"BREAK-EVEN isabet = {break_even:.3f}  (bu eşiğin altında onay kâr üretmez)")

    cal = mp.fit_calibration(probs, hits, min_samples=args.min_samples)
    print()
    if not cal.get("fitted"):
        print("EĞRİ KURULMADI:", cal.get("reason"))
        return 0

    raw, cald = cal["metrics_raw"], cal["metrics_calibrated"]
    print(f"{'metrik':<12}{'ham':>10}{'kalibre':>10}   (küçük iyi)")
    print("-" * 84)
    for key, label in (("brier", "Brier"), ("log_loss", "log-loss"), ("ece", "ECE")):
        r, c = raw.get(key), cald.get(key)
        d = "" if (r is None or c is None) else ("  ✓ iyileşti" if c < r else "  ✗ kötüleşti")
        print(f"{label:<12}{(r if r is not None else -1):>10.4f}{(c if c is not None else -1):>10.4f}{d}")
    skill_raw = 1 - (raw["brier"] / (base_rate * (1 - base_rate))) if base_rate not in (0, 1) else 0
    skill_cal = 1 - (cald["brier"] / (base_rate * (1 - base_rate))) if base_rate not in (0, 1) else 0
    print(f"{'Brier skill':<12}{skill_raw:>10.3f}{skill_cal:>10.3f}   (>0 = taban orandan iyi)")

    print("\nGüvenilirlik kovaları (kalibre sonrası; gap<0 = hâlâ aşırı güvenli):")
    print(f"  {'kova':<12}{'n':>6}{'güven':>9}{'gerçek':>9}{'gap':>9}")
    for b in (cal.get("bins") or []):
        print(f"  {b['lo']:.1f}-{b['hi']:.1f}   {b['samples']:>6}{b['confidence']:>9.3f}"
              f"{b['accuracy']:>9.3f}{b['gap']:>+9.3f}")

    sugg = _suggest_threshold(cal, break_even)
    print("\nEŞİK ÖNERİSİ")
    print(f"  önerilen llm_review_min_confidence = {sugg['suggested_min_confidence']}")
    print(f"  gerekçe: {sugg['reason']}")
    print(f"  (o noktada kalibre olasılık {sugg['calibrated_at_that_point']} · break-even {sugg['break_even']})")
    print("\n  Not: eşik ÖNERİDİR. Canlıya almak `llm_review_min_confidence` ayarını")
    print("  değiştirmek demektir → gölge veriyle 2-3 hafta doğrulandıktan sonra.")

    if args.save:
        payload = {"calibration": cal, "base_rate": round(base_rate, 4),
                   "break_even": round(break_even, 4), "avg_win_r": round(avg_win, 3),
                   "avg_loss_r": round(-avg_loss, 3), "samples": len(probs),
                   "threshold": sugg, "built_at": __import__("time").time()}
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nartefakt yazıldı: {args.save}")
    if args.json:
        print(json.dumps({"base_rate": base_rate, "break_even": break_even,
                          "metrics_raw": raw, "metrics_calibrated": cald,
                          "threshold": sugg}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
