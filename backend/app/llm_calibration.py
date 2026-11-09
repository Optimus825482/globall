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


def walk_forward_metrics(probs: list[float], hits: list[int], *,
                         min_samples: int, test_fraction: float = 0.35) -> dict[str, Any]:
    """Zaman sırasına göre İLK kısımda eğit, SON kısımda ölç (out-of-sample).

    NEDEN ŞART: `fit_calibration` kalibre metriklerini eğittiği veri üzerinde
    hesaplar; izotonik eğri tanımı gereği eğitim noktalarında ECE'yi ~0 yapar.
    2026-11-09'da sunucu çıktısı "ECE 0.3880 → 0.0000" gösterdi — bu bir
    İYİLEŞME DEĞİL, in-sample yanılsamasıydı. Burada eğri yalnız geçmişte
    kurulur, gelecekte ölçülür.
    """
    n = len(probs)
    cut = int(n * (1 - test_fraction))
    if n < min_samples or cut < 40 or (n - cut) < 30:
        return {"available": False, "reason": "out-of-sample için yetersiz veri"}
    tr_p, tr_h = probs[:cut], hits[:cut]
    te_p, te_h = probs[cut:], hits[cut:]
    cal = mp.fit_calibration(tr_p, tr_h, min_samples=min(min_samples, len(tr_p)))
    if not cal.get("fitted"):
        return {"available": False, "reason": f"eğitim yarısı eğri kuramadı: {cal.get('reason')}"}
    cal_te = [mp.apply_calibration(x, cal) for x in te_p]
    base = sum(te_h) / len(te_h) if te_h else 0.0
    denom = base * (1 - base)
    raw = {"brier": mp.brier_score(te_p, te_h), "log_loss": mp.log_loss(te_p, te_h),
           "ece": mp.ece(te_p, te_h)}
    cals = {"brier": mp.brier_score(cal_te, te_h), "log_loss": mp.log_loss(cal_te, te_h),
            "ece": mp.ece(cal_te, te_h)}
    return {
        "available": True,
        "n_train": len(tr_p), "n_test": len(te_p),
        "base_rate_test": round(base, 4),
        "metrics_raw": raw, "metrics_calibrated": cals,
        "brier_skill_raw": None if (not denom or raw["brier"] is None) else round(1 - raw["brier"] / denom, 4),
        "brier_skill_calibrated": None if (not denom or cals["brier"] is None) else round(1 - cals["brier"] / denom, 4),
        "improved": bool(raw["brier"] is not None and cals["brier"] is not None and cals["brier"] < raw["brier"]),
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

    threshold = suggest_threshold(cal, break_even)
    # KAPSAM KORUMASI (2026-11-09): 92 gibi bir eşik, kararların binde birini
    # kapsıyorsa "onay" fiilen YOK demektir → uygulanırsa ticaret durur.
    # Bu, sessiz bir tuzak: kullanıcı "eşiği uygula" der ve işlem gelmez.
    if threshold.get("suggested_min_confidence") is not None:
        thr = float(threshold["suggested_min_confidence"]) / 100.0
        coverage = sum(1 for x in probs if x >= thr) / len(probs)
        threshold["coverage"] = round(coverage, 4)
        if coverage < 0.02:
            threshold["unreachable"] = True
            threshold["reason"] = (
                f"BU EŞİĞİ UYGULAMAYIN: kararların yalnız %{coverage * 100:.2f}'i bu güvene "
                f"ulaşıyor → onay fiilen yok, ticaret durur. " + str(threshold.get("reason", ""))
            )
        else:
            threshold["unreachable"] = False

    out.update({
        "threshold": threshold,
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
        "reason": cal.get("reason"),
        "built_at": time.time(),
    })
    # OUT-OF-SAMPLE: raporun ASIL kanıtı bu (in-sample ECE ~0 bir yanılsamadır).
    out["out_of_sample"] = walk_forward_metrics(probs, hits, min_samples=min_samples)
    # Ham (kalibre edilmemiş) Brier skill — panelin ölçtüğü şey:
    raw_brier = raw.get("brier")
    out["brier_skill_raw_only"] = (None if (not denom or raw_brier is None)
                                   else round(1 - raw_brier / denom, 4))
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
