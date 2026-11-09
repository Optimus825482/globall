"""ML OLASILIK KALİBRASYON RAPORU (2026-11-09)

NEDEN VAR
---------
`ml_probability` (izotonik eğri + Brier/ECE) ve `ml_shadow` (gölge gözlem
sayaçları) yazıldı ama sonuç **yalnız `/api/system/health` içinde sayaç**
olarak görünüyordu: kullanıcı "modelin güven puanı dürüst mü?" sorusunu
panelden okuyamıyor, ham veriyi CSV olarak alamıyordu.

TEK UYGULAMA: bu modül hem panel ucunu (`GET /api/reports/ml-calibration`)
hem CSV ucunu (`.../csv`) besler. İki ayrı hesap olsaydı panelin gösterdiği
sayı ile indirilen dosya birbirini tutmazdı.

KANIT KURALI
------------
Asıl kanıt **OUT-OF-SAMPLE**: izotonik eğri tanımı gereği EĞİTİM noktalarında
ECE'yi ~0 yapar (in-sample yanılsaması, 2026-11-09'da LLM kalibrasyonunda da
yaşandı). Burada eğri verinin ilk %65'inde kurulur, son %35'inde ölçülür; ham
ile kalibre metrikler AYNI test kümesinde karşılaştırılır.
"""
from __future__ import annotations

import time
from typing import Any

from app import ml_probability as mp

#: Rapor için gereken en az değerlendirilmiş örnek (altında hüküm verilmez).
MIN_SAMPLES = 200


def _series(rows: list[dict]) -> tuple[list[float], list[int], list[float], list[dict]]:
    """`ml_shadow_predictions` satırları → (olasılık, isabet, R, geçerli satırlar)."""
    probs: list[float] = []
    hits: list[int] = []
    rs: list[float] = []
    valid: list[dict] = []
    for r in rows or []:
        try:
            p = float(r["hit_probability"])
            exit_pct = float(r["exit_pct"] or 0.0)
            target = float(r["target_pct"] or 0.0)
        except (TypeError, ValueError):
            continue
        hit = 1 if r.get("hit_target") else 0
        probs.append(max(0.0, min(1.0, p)))
        hits.append(hit)
        rs.append(round(exit_pct / target, 3) if target > 0 else round(exit_pct, 4))
        valid.append({**r, "hit": hit, "r": rs[-1]})
    return probs, hits, rs, valid


def _walk_forward(probs: list[float], hits: list[int], *, min_samples: int,
                  test_fraction: float = 0.35) -> dict[str, Any]:
    """İlk kısımda eğri kur, son kısımda ölç (out-of-sample).

    `llm_calibration.walk_forward_metrics` ile AYNI disiplin; oradan import
    ETMİYORUZ çünkü o modül LLM güven sütunlarına özel sözlük döndürür —
    burada anahtarlar ML raporunun kendi adlarıyla verilir.
    """
    n = len(probs)
    cut = int(n * (1 - test_fraction))
    if n < min_samples or cut < 40 or (n - cut) < 30:
        return {"available": False, "reason": f"out-of-sample için yetersiz veri (n={n})"}
    tr_p, tr_h = probs[:cut], hits[:cut]
    te_p, te_h = probs[cut:], hits[cut:]
    cal = mp.fit_calibration(tr_p, tr_h, min_samples=min(min_samples, len(tr_p)))
    if not cal.get("fitted"):
        return {"available": False, "reason": f"eğitim yarısı eğri kuramadı: {cal.get('reason')}"}
    cal_te = [mp.apply_calibration(x, cal) for x in te_p]
    base = sum(te_h) / len(te_h) if te_h else 0.0
    denom = base * (1 - base)
    raw = {"brier": mp.brier_score(te_p, te_h), "ece": mp.ece(te_p, te_h)}
    cals = {"brier": mp.brier_score(cal_te, te_h), "ece": mp.ece(cal_te, te_h)}
    skill = lambda b: None if (not denom or b is None) else round(1 - b / denom, 4)
    return {
        "available": True,
        "n_train": len(tr_p), "n_test": len(te_p),
        "base_rate_test": round(base, 4),
        "raw": raw, "calibrated": cals,
        "brier_skill_raw": skill(raw["brier"]),
        "brier_skill_calibrated": skill(cals["brier"]),
        "improved": bool(raw["brier"] is not None and cals["brier"] is not None
                         and cals["brier"] < raw["brier"]),
    }


def _threshold_curve(valid: list[dict]) -> list[dict]:
    """Eşik → kapsam/isabet/lift. Eşiğe kilitlenmek yerine eğri okunur."""
    if not valid:
        return []
    base = sum(v["hit"] for v in valid) / len(valid)
    out: list[dict] = []
    for thr in (0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8):
        picked = [v for v in valid if float(v["hit_probability"]) >= thr]
        n = len(picked)
        if n < 10:
            out.append({"threshold": thr, "n": n, "coverage": round(n / len(valid), 4),
                        "hit_rate": None, "lift": None, "avg_r": None})
            continue
        hr = sum(v["hit"] for v in picked) / n
        out.append({
            "threshold": thr, "n": n, "coverage": round(n / len(valid), 4),
            "hit_rate": round(hr, 4),
            "lift": round(hr / base, 3) if base > 0 else None,
            "avg_r": round(sum(float(v["r"]) for v in picked) / n, 4),
        })
    return out


def summarize_rows(rows: list[dict]) -> dict[str, Any]:
    """Saf hesaplama: değerlendirilmiş satırlar → rapor gövdesi (yan etki yok)."""
    probs, hits, rs, valid = _series(rows)
    out: dict[str, Any] = {
        "samples": len(probs),
        "min_samples": MIN_SAMPLES,
        "fitted": False,
    }
    if len(probs) < MIN_SAMPLES:
        kalan = MIN_SAMPLES - len(probs)
        out["reason"] = (
            f"yetersiz değerlendirilmiş örnek: {len(probs)} < {MIN_SAMPLES}"
            + (f" — {kalan} örnek daha birikince hüküm verilir" if len(probs) else
               " — hiç değerlendirilmiş tahmin yok (gölge tahmin hattı çalışmıyor olabilir)")
        )
        out["samples_needed"] = kalan
        return out
    base_rate = sum(hits) / len(hits)
    wins = [r for r, h in zip(rs, hits) if h]
    losses = [r for r, h in zip(rs, hits) if not h]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    break_even = (avg_loss / (avg_win + avg_loss)) if (avg_win + avg_loss) > 0 else 0.5

    cal = mp.fit_calibration(probs, hits, min_samples=MIN_SAMPLES)
    raw, cald = cal.get("metrics_raw") or {}, cal.get("metrics_calibrated") or {}
    denom = base_rate * (1 - base_rate)
    skill = lambda b: None if (not denom or b is None) else round(1 - b / denom, 4)

    out.update({
        "fitted": bool(cal.get("fitted")),
        "base_rate": round(base_rate, 4),
        "break_even": round(break_even, 4),
        "break_even_reachable": bool(base_rate >= break_even),
        "avg_win_r": round(avg_win, 3),
        "avg_loss_r": round(-avg_loss, 3),
        "metrics_raw": raw,
        "metrics_calibrated": cald,
        "brier_skill_raw": skill(raw.get("brier")),
        "brier_skill_calibrated": skill(cald.get("brier")),
        "bins": cal.get("bins") or [],
        "reason": cal.get("reason"),
        "threshold_curve": _threshold_curve(valid),
        "generated_at": time.time(),
    })
    out["out_of_sample"] = _walk_forward(probs, hits, min_samples=MIN_SAMPLES)
    # KONFORMAL ARALIK (P2): "isabet oranı şu aralıkta" — karar desteği.
    # Eğri/nicem eğitim yarısında kurulur, test yarısında kapsama ÖLÇÜLÜR.
    out["conformal"] = _conformal_block(probs, hits, break_even)
    return out


def _conformal_block(probs: list[float], hits: list[int], break_even: float,
                     alpha: float = mp.CONFORMAL_DEFAULT_ALPHA) -> dict[str, Any]:
    """Test yarısında isabet oranı + Wilson aralığı + break-even karşılaştırması.

    CONFORMAL REDDEDİLDİ (ölçüm): ikili etikette |y-p| ≤ 1 → nicem 0.85'e doyar,
    aralık genişliği **1.00**, kapsama %100 → karar için bilgi YOK. Wilson aralığı
    gözlenen oranın belirsizliğini verir ve doğrudan break-even ile kıyaslanır.
    """
    n = len(probs)
    cut = int(n * 0.65)
    if n < MIN_SAMPLES or cut < 40 or (n - cut) < 30:
        return {"available": False, "reason": "aralık için yetersiz veri"}
    te_h = hits[cut:]
    iv = mp.hit_rate_interval_wilson(te_h, alpha)
    if iv is None:
        return {"available": False, "reason": "yetersiz test örneği"}
    be = float(break_even)
    verdict = ("aralık break-even'ın TAMAMEN ALTINDA → bu güven düzeyinde kenar YOK"
               if iv["hi"] < be else
               "aralık break-even'ın TAMAMEN ÜSTÜNDE → kenar mümkün"
               if iv["lo"] > be else
               "aralık break-even'ı KESİYOR → belirsiz, çekimser kal")
    return {
        "available": True,
        "alpha": alpha,
        "n_test": iv["n"],
        "hit_rate": iv["hit_rate"],
        "wilson_lo": iv["lo"],
        "wilson_hi": iv["hi"],
        "break_even": round(be, 4),
        "verdict": verdict,
        "note": "Wilson %90 aralığı; konformal ikili etikette doyduğu için kullanılmadı.",
    }


def csv_rows(rows: list[dict]) -> tuple[list[str], list[list[Any]]]:
    """CSV başlıkları + satırları (ham + türetilmiş kalibre olasılık)."""
    headers = [
        "tahmin_zamani", "sembol", "ufuk_dk", "giris_fiyati", "ham_olasilik",
        "kalibre_olasilik", "hedef_pct", "kapi_gecti", "durum",
        "mfe_pct", "mae_pct", "cikis_pct", "hedef_vuruldu", "bar_sayisi", "R",
    ]
    art = None
    try:
        from app.config import config as _cfg      # SINGLETON nesne (modül değil)
        art = mp.load_state(_cfg.ML_CALIBRATION_ARTIFACT)
    except Exception:  # noqa: BLE001 - artefakt yoksa ham olasılık yazılır
        art = None
    out: list[list[Any]] = []
    for r in rows or []:
        raw = r.get("hit_probability")
        calib = None
        if art and raw is not None:
            try:
                calib = round(mp.apply_calibration(float(raw), art), 4)
            except Exception:  # noqa: BLE001
                calib = None
        rv = None
        try:
            target = float(r.get("target_pct") or 0.0)
            if target > 0:
                rv = round(float(r.get("exit_pct") or 0.0) / target, 3)
        except (TypeError, ValueError):
            rv = None
        out.append([
            time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(float(r.get("predicted_at") or 0))),
            str(r.get("symbol") or ""),
            r.get("horizon_minutes"),
            r.get("entry_price"),
            None if raw is None else round(float(raw), 4),
            calib,
            r.get("target_pct"),
            "evet" if r.get("gate_passed") else "hayır",
            r.get("status"),
            r.get("max_favorable_pct"),
            r.get("max_adverse_pct"),
            r.get("exit_pct"),
            "evet" if r.get("hit_target") else "hayır",
            r.get("bars_held"),
            rv,
        ])
    return headers, out


async def build(days: float = 0.0) -> dict[str, Any]:
    """Panel ucu: canlı sayaçlar + artefakt özeti + türetilmiş kalibrasyon."""
    from app import ml_shadow
    rows = await _fetch(days)
    report = summarize_rows(rows)
    report["rows_total"] = len(rows)
    report["counters"] = ml_shadow.counters()
    # KAPSAM (dürüstlük): bu metrikler `ml_shadow_predictions` (spot/velocity
    # tahmin hattı) üzerinden hesaplanır. FOREX işlemleri bu tabloya GİRMEZ;
    # forex için geometri gölgesi ve LLM güven kalibrasyonu ayrı yüzeylerdir.
    # "Neden hep 0?" sorusunun cevabı burada dursun.
    report["scope"] = ("ml_shadow_predictions (spot/velocity tahmin hattı) — "
                       "forex işlemleri bu tabloya girmez; forex için geometri gölgesi "
                       "ve LLM güven kalibrasyonu ayrı raporlardadır.")
    report["artifact"] = _artifact_summary()
    return report


def _artifact_summary() -> dict[str, Any]:
    """Kayıtlı kalibrasyon eğrisinin özeti (varsa)."""
    try:
        from app.config import config as _cfg      # SINGLETON nesne (modül değil)
        art = mp.load_state(_cfg.ML_CALIBRATION_ARTIFACT)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    if not art:
        return {"available": False, "reason": "kalibrasyon artefaktı yok (scripts/report_probability_calibration.py --save)"}
    return {
        "available": bool(art.get("fitted", True)),
        "samples": art.get("samples"),
        "base_rate": art.get("base_rate"),
        "brier_skill_raw": art.get("brier_skill_raw"),
        "brier_skill_calibrated": art.get("brier_skill_calibrated"),
        "saved_at": art.get("saved_at"),
        "x_thresholds": art.get("x_thresholds"),
        "y_thresholds": art.get("y_thresholds"),
    }


async def _fetch(days: float) -> list[dict]:
    from app import database
    return await database.get_shadow_predictions(days=days, limit=200000, evaluated_only=True)


async def rows_for_csv(days: float = 0.0) -> list[dict]:
    """CSV ucu: değerlendirilmiş + bekleyen tüm satırlar (ham veri)."""
    from app import database
    return await database.get_shadow_predictions(days=days, limit=200000, evaluated_only=False)
