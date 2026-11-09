"""FOREX ML v1 — işlem dosyası özelliklerinden isabet modeli (2026-11-09).

NEDEN BU MODÜL
--------------
Kullanıcı sorusu: "ML hattını neden forex'te kullanmıyoruz?" Ölçülmüş cevaplar:
  1. Mevcut model spot-kripto şeklinde: `velocity_candidates` 272 USDT coin,
     **0 forex satırı** → XAUUSD/EURUSD için skor üretemez.
  2. Sinyali ölçüldü: EV tüm varyantlarda negatif (en iyi -0.378) → kenar yok.
  3. Kök neden model değil, geometri (break-even %67 vs gerçek %56).

AMA forex'e özel eğitim verisi BİRİKİYOR: her LLM kararında deterministik giriş
özellikleri `llm_trade_reviews.features` altına yazılıyor (session, htf_agree_count,
seviye mesafesi, EMA uzantısı, spread/ATR, haber dakikası…) ve her kararın gölge
sonucu (`shadow_pips`) izleniyor. Bu tablo forex'e ÖZEL eğitim setidir.

BU MODÜL NE YAPAR
-----------------
`llm_trade_reviews` özellik+sonuç satırlarından **lojistik model** eğitir:
  * KRONOLOJİK split (ilk %70 eğitim, son %30 test) — rastgele split zamanda
    sızdırır (aynı günün işlemleri iki yarıya düşer).
  * JSON-serializable artifact (pickle YOK): ortalama/ölçek/medyan + katsayılar.
    Üretim imajı yalın kalır; modeli okumak için sklearn bile gerekmez.
  * OOS kanıt: Brier/skill, IC (Spearman), Wilson aralığı.
  * HÜKÜM: OOS skill <= 0 ise "model karar kapısı OLMAMALI" yazar.

KARAR DEĞİŞTİRMEZ: eğitim + ölçüm + rapor. Modeli bir kapıya bağlamak replay
A/B kanıtı ister (chandelier/P1'deki disiplin).
"""
from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("scalper.forex_ml")

#: Karar için gereken en az SATIR (özellik+sonuç ikisi dolu).
MIN_ROWS = 120
#: Kronolojik test payı.
TEST_FRACTION = 0.30
DEFAULT_ARTIFACT = Path(__file__).resolve().parents[1] / "artifacts" / "forex_ml.json"

#: Sayısal özellikler (sıra artifact'ta da bu sıra ile korunur).
NUMERIC_FEATURES = (
    "htf_agree_count", "htf_frames", "level_clearance_atr", "extension_atr",
    "spread_atr_ratio", "news_minutes", "ta_score", "llm_confidence", "motor_score",
)
#: Kategorik özellikler (one-hot; bilinmeyen değer → tüm bitler 0).
SESSION_VALUES = ("asia", "london", "new_york", "overlap")
BIAS_VALUES = ("bullish", "bearish", "neutral")


def _f(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if v == v and v not in (float("inf"), float("-inf")) else default


def featurize(row: dict[str, Any], *, medians: Optional[dict[str, float]] = None,
              sessions: tuple[str, ...] = SESSION_VALUES,
              biases: tuple[str, ...] = BIAS_VALUES) -> dict[str, float]:
    """Bir karar satırını sayısal özellik vektörüne çevirir (deterministik).

    Eksik sayısal özellikler `medians` (eğitim medyanı) ile doldurulur;
    `medians` yoksa 0.0 (test/çıplak çağrı). Kategorik bilinmeyen → tüm bitler 0.
    Dönen sözlük sıralı anahtarlıdır → vektör sırası kararlıdır.
    """
    f_raw = row.get("features") or {}
    if isinstance(f_raw, str):
        import json
        try:
            f_raw = json.loads(f_raw)
        except Exception:  # noqa: BLE001
            f_raw = {}
    f_raw = f_raw if isinstance(f_raw, dict) else {}
    med = medians or {}
    out: dict[str, float] = {}
    for name in NUMERIC_FEATURES:
        if name == "llm_confidence":
            v = _f(row.get("confidence"))
        elif name == "motor_score":
            v = _f(row.get("score"))
        else:
            v = _f(f_raw.get(name))
        out[name] = v if v is not None else float(med.get(name, 0.0))
    # eksik göstergeleri (imputation sinyali) üç opsiyonel özellik için tut
    for name in ("level_clearance_atr", "extension_atr", "spread_atr_ratio"):
        out[f"{name}_eksik"] = 1.0 if _f(f_raw.get(name)) is None else 0.0
    session = str(f_raw.get("session") or "").strip().lower()
    for s in sessions:
        out[f"session_{s}"] = 1.0 if session == s else 0.0
    bias = str(f_raw.get("ta_bias") or "").strip().lower()
    for b in biases:
        out[f"bias_{b}"] = 1.0 if bias == b else 0.0
    out["direction_buy"] = 1.0 if str(row.get("direction") or "").upper() == "BUY" else 0.0
    return out


def feature_names(*, sessions: tuple[str, ...] = SESSION_VALUES,
                  biases: tuple[str, ...] = BIAS_VALUES) -> list[str]:
    """`featurize` çıktısının ANAHTAR SIRASI (artifact ile birebir aynı olmalı)."""
    names = list(NUMERIC_FEATURES)
    names += [f"{n}_eksik" for n in ("level_clearance_atr", "extension_atr", "spread_atr_ratio")]
    names += [f"session_{s}" for s in sessions]
    names += [f"bias_{b}" for b in biases]
    names += ["direction_buy"]
    return names


def _vector(row: dict[str, Any], medians: dict[str, float]) -> list[float]:
    f = featurize(row, medians=medians)
    return [f[k] for k in feature_names()]


def _spearman(a: list[float], b: list[float]) -> Optional[float]:
    n = len(a)
    if n < 20 or len(b) != n:
        return None
    def _rank(xs):
        order = sorted(range(n), key=lambda i: xs[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks
    ra, rb = _rank(a), _rank(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    da = math.sqrt(sum((ra[i] - ma) ** 2 for i in range(n)))
    db = math.sqrt(sum((rb[i] - mb) ** 2 for i in range(n)))
    if da <= 0 or db <= 0:
        return None
    return num / (da * db)


def train(rows: list[dict[str, Any]], *, test_fraction: float = TEST_FRACTION,
          min_rows: int = MIN_ROWS) -> dict[str, Any]:
    """Kronolojik split + lojistik model + OOS değerlendirme. İstisna FIRLATMAZ."""
    out: dict[str, Any] = {
        "n_rows": len(rows or []), "min_rows": int(min_rows), "trained": False,
        "test_fraction": float(test_fraction),
    }
    clean = []
    for r in rows or []:
        try:
            sp = float(r.get("shadow_pips"))
            if not (sp == sp) or r.get("features") in (None, "", "{}"):
                continue
            clean.append(r)
        except (TypeError, ValueError):
            continue
    clean.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("id") or "")))
    out["n_usable"] = len(clean)
    if len(clean) < int(min_rows):
        out["reason"] = (f"yetersiz eğitim verisi: {len(clean)} < {min_rows} "
                         "(features + shadow_pips dolu satır gerekli)")
        return out

    medians: dict[str, float] = {}
    for name in NUMERIC_FEATURES:
        vals = sorted(v for v in (_f((r.get("features") or {}).get(name) if isinstance(r.get("features"), dict) else None)
                                  for r in clean) if v is not None)
        medians[name] = vals[len(vals) // 2] if vals else 0.0
    out["medians"] = medians

    X = [_vector(r, medians) for r in clean]
    y = [1 if float(r.get("shadow_pips")) > 0 else 0 for r in clean]
    names = feature_names()
    cut = int(len(clean) * (1.0 - float(test_fraction)))
    cut = max(1, min(len(clean) - 1, cut))
    Xtr, Xte, ytr, yte = X[:cut], X[cut:], y[:cut], y[cut:]
    out.update({"n_train": len(Xtr), "n_test": len(Xte)})

    base = sum(ytr) / len(ytr)
    out["base_rate_train"] = round(base, 4)
    base_te = sum(yte) / len(yte)
    out["base_rate_test"] = round(base_te, 4)

    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"sklearn yok: {type(exc).__name__}"
        return out

    Xtr_a = np.asarray(Xtr, dtype=float)
    Xte_a = np.asarray(Xte, dtype=float)
    mean = Xtr_a.mean(axis=0)
    std = np.where(Xtr_a.std(axis=0) < 1e-9, 1.0, Xtr_a.std(axis=0))
    model = LogisticRegression(max_iter=2000, C=1.0, random_state=0)
    try:
        model.fit((Xtr_a - mean) / std, ytr)
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"eğitim başarısız: {type(exc).__name__}: {exc}"
        return out

    p_tr = model.predict_proba((Xtr_a - mean) / std)[:, 1].tolist()
    p_te = model.predict_proba((Xte_a - mean) / std)[:, 1].tolist()

    from app import ml_probability as mp
    brier_tr = mp.brier_score(p_tr, ytr)
    brier_te = mp.brier_score(p_te, yte)
    denom_te = base_te * (1 - base_te)
    skill = round(1 - brier_te / denom_te, 4) if denom_te else None
    ece_te = mp.ece(p_te, yte)
    ic = _spearman(p_te, [float(v) for v in yte])
    ic_p = None
    if ic is not None:
        ic_p = round(ic / math.sqrt(max(1, len(yte))), 4)   # yaklaşık z-skoru
    iv = mp.hit_rate_interval_wilson(yte, alpha=0.10)

    # OOS hüküm: skill > 0 VE yön tutarlı → model bilgi taşıyor.
    verdict = ("OOS skill > 0: model test yarısında bilgi taşıyor (kapı için YİNE replay A/B şart)"
               if (skill is not None and skill > 0) else
               "OOS skill <= 0: model test yarısında bilgi TAŞIMIYOR — karar kapısı OLMAMALI")
    out.update({
        "trained": True,
        "brier_train": round(brier_tr, 4),
        "brier_test": round(brier_te, 4),
        "brier_skill_oos": skill,
        "ece_test": round(ece_te, 4),
        "ic_test": round(ic, 4) if ic is not None else None,
        "ic_significance": ic_p,
        "wilson": iv,
        "verdict": verdict,
        "coefficients": {names[i]: round(float(model.coef_[0][i]), 4) for i in range(len(names))},
        "intercept": round(float(model.intercept_[0]), 4),
        "feature_names": names,
        "means": [round(float(v), 6) for v in mean],
        "scales": [round(float(v), 6) for v in std],
        "trained_at": time.time(),
    })

    # Kalibrasyon: izotonik (eğitim yarısında kurulur, test yarısında ölçülür)
    try:
        cal = mp.fit_calibration(p_tr, ytr, min_samples=60)
        if cal.get("fitted"):
            cal_te = [mp.apply_calibration(p, cal) for p in p_te]
            brier_cal = mp.brier_score(cal_te, yte)
            out["calibrated_brier_test"] = round(brier_cal, 4)
            out["calibration_improved"] = bool(brier_cal < brier_te)
    except Exception as exc:  # noqa: BLE001
        out["calibration_note"] = f"kalibrasyon atlandı: {type(exc).__name__}"
    return out


def save_artifact(report: dict[str, Any], path: str | Path | None = None) -> str:
    """Eğitilmiş modeli JSON'a yazar (pickle yok). Yalnız `trained=True` iken."""
    target = Path(path) if path else DEFAULT_ARTIFACT
    if not report.get("trained"):
        raise ValueError("eğitilmemiş rapor artifact'a yazılamaz")
    target.parent.mkdir(parents=True, exist_ok=True)
    import json
    payload = {"saved_at": time.time(), "version": 1,
               "feature_names": report.get("feature_names"),
               "means": report.get("means"), "scales": report.get("scales"),
               "coefficients": report.get("coefficients"), "intercept": report.get("intercept"),
               "medians": report.get("medians"),
               "metrics": {k: report.get(k) for k in (
                   "n_rows", "n_usable", "n_train", "n_test", "base_rate_train",
                   "base_rate_test", "brier_train", "brier_test", "brier_skill_oos",
                   "ece_test", "ic_test", "wilson", "verdict", "trained_at")}}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


async def run(*, min_rows: int = MIN_ROWS, save: bool = True) -> dict[str, Any]:
    """Panelden çağrılan tam akış: veri çek → eğit → artifact + DB kaydı."""
    from app import database

    rows = await database.get_forex_ml_dataset()
    report = train(rows, min_rows=min_rows)
    if report.get("trained") and save:
        try:
            report["artifact_path"] = save_artifact(report)
        except Exception as exc:  # noqa: BLE001
            report["artifact_error"] = f"{type(exc).__name__}: {exc}"
    try:
        await database.save_forex_ml_run(report)
    except Exception as exc:  # noqa: BLE001
        report["run_log_error"] = f"{type(exc).__name__}: {exc}"
    return report
