"""LLM GÜVEN KALİBRASYONU — paylaşılan çekirdek (2026-11-09)

Hem CLI (`scripts/report_llm_confidence_calibration.py`) hem de Ayarlar
panelindeki **"Kalibrasyonu Çalıştır"** düğmesi (`POST /api/system/llm-calibration`)
bu modülü kullanır. Tek uygulama, iki yüzey — kopya yok.

NE ÖLÇER
--------
`llm_trade_reviews` üzerindeki (confidence, gölge sonuç) çiftlerinden:
  1. Ham **Brier / log-loss / ECE** (model dürüst mü?)
  2. **İzotonik kalibrasyon eğrisi** (`ml_probability`) ve kalibre metrikler
  3. Güvenilirlik kovaları (hangi güven aralığı aşırı güvenli?)
  4. **Eşik önerisi**: kalibre olasılığın break-even'ı ilk aştığı ham güven →
     `llm_review_min_confidence` için veri temelli değer.

Panelde ölçülen durum (517 karar): Brier 0.2679 vs taban 0.226 → skill -0.185;
60-80% kovasında öngörülen %65, gerçekleşen %37. Yani model 40% üstünde
sistematik aşırı güvenli — bu modül o eğriyi kurup düzeltmeyi ölçer.

KARAR DEĞİŞTİRMEZ: yalnız ölçüm üretir + artefakt yazar. Eşiği canlıya almak
`llm_review_min_confidence` ayarını değiştirmektir (kullanıcı onayı ile).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from app import ml_probability as mp

DEFAULT_ARTIFACT = Path(__file__).resolve().parents[1] / "artifacts" / "llm_confidence_calibration.json"


async def fetch_reviews(days: int = 0) -> list[dict]:
    """Çözülmüş LLM kararlarını çek (confidence + gölge sonuç)."""
    import asyncpg

    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL gerekli")
    cutoff = (time.time() - days * 86400) if days > 0 else None
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


def rows_to_series(rows: list[dict]) -> tuple[list[float], list[int], list[float]]:
    """(ham olasılık, kazanç?, R) — R = shadow_pips / sl_pips."""
    probs: list[float] = []
    hits: list[int] = []
    rs: list[float] = []
    for r in rows or []:
        try:
            conf = float(r["confidence"])
            pips = float(r["shadow_pips"])
        except (TypeError, ValueError):
            continue
        try:
            sl_f = float(r.get("sl_pips"))
        except (TypeError, ValueError):
            sl_f = 0.0
        probs.append(max(0.0, min(1.0, conf / 100.0)))
        hits.append(1 if pips > 0 else 0)
        rs.append(round(pips / sl_f, 3) if sl_f > 0 else 0.0)
    return probs, hits, rs


def suggest_threshold(cal: dict, break_even: float) -> dict[str, Any]:
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


def compute(rows: list[dict], *, min_samples: int | None = None) -> dict[str, Any]:
    """Saf hesaplama: satırlar → rapor sözlüğü (yan etki yok)."""
    min_samples = int(min_samples if min_samples is not None else mp.MIN_SAMPLES)
    probs, hits, rs = rows_to_series(rows)
    out: dict[str, Any] = {
        "reviews": len(rows or []),
        "samples": len(probs),
        "min_samples": min_samples,
        "fitted": False,
    }
    if len(probs) < min_samples:
        out["reason"] = f"yetersiz örnek: {len(probs)} < {min_samples}"
        return out

    base_rate = sum(hits) / len(hits)
    wins = [r for r, h in zip(rs, hits) if h]
    losses = [r for r, h in zip(rs, hits) if not h]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    break_even = (avg_loss / (avg_win + avg_loss)) if (avg_win + avg_loss) > 0 else 0.5

    cal = mp.fit_calibration(probs, hits, min_samples=min_samples)
    raw, cald = cal.get("metrics_raw") or {}, cal.get("metrics_calibrated") or {}
    denom = base_rate * (1 - base_rate)
    skill_raw = (1 - raw["brier"] / denom) if (denom and raw.get("brier") is not None) else None
    skill_cal = (1 - cald["brier"] / denom) if (denom and cald.get("brier") is not None) else None

    out.update({
        "fitted": bool(cal.get("fitted")),
        "base_rate": round(base_rate, 4),
        "avg_win_r": round(avg_win, 3),
        "avg_loss_r": round(-avg_loss, 3),
        "break_even": round(break_even, 4),
        "metrics_raw": raw,
        "metrics_calibrated": cald,
        "brier_skill_raw": None if skill_raw is None else round(skill_raw, 4),
        "brier_skill_calibrated": None if skill_cal is None else round(skill_cal, 4),
        "bins": cal.get("bins") or [],
        "threshold": suggest_threshold(cal, break_even),
        "reason": cal.get("reason"),
        "built_at": time.time(),
    })
    return out


async def run(days: int = 0, *, min_samples: int | None = None,
              save: str | Path | None = None) -> dict[str, Any]:
    """DB'den çek + hesapla + (istenirse) artefakt yaz. API ve CLI ortak yolu."""
    rows = await fetch_reviews(days)
    report = compute(rows, min_samples=min_samples)
    if save and report.get("fitted"):
        try:
            path = Path(save)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            report["artifact_path"] = str(path)
        except Exception as exc:  # artefakt yazımı raporu düşürmesin
            report["artifact_error"] = f"{type(exc).__name__}: {exc}"
    return report
