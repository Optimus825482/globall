"""Olasılık KALİBRASYONU + Brier/ECE + ÇEKİMSERLİK (abstention).

NEDEN VAR (2026-11-09, GitHub araştırması P1-3)
----------------------------------------------
`calibration.py` kova bazlı **deterministik** bir boyut çarpanı üretiyor ve bunu
bilinçli olarak ML'siz yapıyor (docstring: *"No machine learning, no parameter
fitting"*). Bu doğru bir felsefe ama bir boşluk bırakıyor: ML modelinin ürettiği
**olasılığın kendisi kalibre mi?** `ml_forecast.py` bir "hit_probability"
döndürüyor (`predict_proba[:, 1]`, ör. 0.87) ve bu değer eşik olarak
kullanılıyor. Ham `predict_proba` çıktısı, sınıf dengesizliği ve ağaç tabanlı
modellerin bilinen aşırı-güven eğilimi yüzünden GENELDE kalibre değildir:
%87 diyen sinyaller gerçekte %62 tutuyorsa eşik anlamsızdır.

Bu modül üç şeyi ekler ve `calibration.py`'yi DEĞİŞTİRMEZ:

1. ``fit_calibration`` — (ham olasılık, gerçekleşti mi) çiftlerinden **izotonik**
   kalibrasyon eğrisi kurar (tekdüze, parametrik varsayım yok).
2. ``brier_score`` / ``log_loss`` / ``ece`` / ``reliability_bins`` —
   kalibrasyonun ÖLÇÜMÜ. ECE (Expected Calibration Error) "model ne kadar
   dürüst" sorusunun tek sayılık cevabıdır.
3. ``should_abstain`` — **çekimserlik**: kalibre olasılık, başabaş olasılığın
   (``break_even_probability``) altındaysa giriş YAPILMAZ. "Kötü sinyali
   küçült" yerine "kanıt yoksa hiç girme" — bu, sermaye korumanın en ucuz yolu.

TASARIM KURALLARI
-----------------
* **Üretim-güvenli bağımlılık:** yalnız ``numpy`` + ``scikit-learn``. Bu ikisi
  ``requirements.txt``'te ZATEN var. pandas/scipy/statsmodels GEREKMEZ (üretim
  imajı bilinçli olarak yalın; oraya ağır kütüphane sokmayın).
* **Walk-forward güvenli:** eğri yalnız GEÇMİŞ değerlendirilmiş adaylardan
  kurulur; ``split_walk_forward`` bunu zorunlu kılmayı kolaylaştırır.
* **Kanıt yoksa nötr:** durum yayınlanmadıysa çekimserlik UYGULANMAZ
  (fail-open DEĞİL, nötr: eski davranış korunur) ama ``calibrated=False``
  işaretiyle bunun ham olasılık olduğu bildirilir.
* **İzlenebilirlik:** her durum ``samples``, ``base_rate``, ``metrics`` taşır;
  raporda "kaç örnekle öğrendi" görünür (8 örnekli bir eğriye güvenilmez).
"""
from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Iterable, Sequence

import numpy as np

try:  # sklearn üretimde var; yoksa modül import edilebilir kalsın (graceful).
    from sklearn.isotonic import IsotonicRegression
except Exception:  # pragma: no cover - sklearn yoksa
    IsotonicRegression = None  # type: ignore[assignment]

#: Kalibrasyon eğrisi için minimum GÖZLEM sayısı. Altında eğri kurulmaz —
#: 30 örnekle çizilen izotonik eğri neredeyse her şeyi "aşırı güvenli" gösterir.
MIN_SAMPLES = 80

#: Her iki sınıftan da en az bu kadar gözlem olmalı (tek sınıflı veri eğri üretmez).
MIN_PER_CLASS = 15

#: ECE/reliability kova sayısı. 10 standarttır (0.1'lik dilimler).
ECE_BINS = 10

#: Başabaş olasılık için varsayılan ödül/risk (kazanç/kayıp) oranı.
#: Çağıran gerçek RR'yi biliyorsa ``break_even_probability``'e açıkça vermelidir.
DEFAULT_REWARD_RISK = 1.5


def _as_arrays(probs: Iterable[Any], hits: Iterable[Any]) -> tuple[np.ndarray, np.ndarray]:
    """Girdileri doğrulanmış numpy dizilerine çevir (NaN/sınır temizliği)."""
    p = np.asarray(list(probs), dtype=float)
    h = np.asarray(list(hits), dtype=float)
    if p.shape != h.shape:
        raise ValueError(f"probs/hits uzunlukları farklı: {p.shape} vs {h.shape}")
    if p.size == 0:
        return p, h
    mask = np.isfinite(p) & np.isfinite(h)
    p, h = p[mask], (h[mask] > 0.5).astype(float)
    return np.clip(p, 0.0, 1.0), h


# ---------------------------------------------------------------------------
# Ölçüm
# ---------------------------------------------------------------------------

def brier_score(probs: Sequence[float], hits: Sequence[float]) -> float | None:
    """Brier skoru — ortalama kare hata. 0 mükemmel, 0.25 "yazı tura" seviyesi."""
    p, h = _as_arrays(probs, hits)
    if p.size == 0:
        return None
    return float(np.mean((p - h) ** 2))


def log_loss(probs: Sequence[float], hits: Sequence[float]) -> float | None:
    """Log-loss (ikili). 0'a yakın iyi; 0/1 uçlarında kırpma ile sonsuzluk önlenir."""
    p, h = _as_arrays(probs, hits)
    if p.size == 0:
        return None
    eps = 1e-12
    p = np.clip(p, eps, 1.0 - eps)
    return float(-np.mean(h * np.log(p) + (1.0 - h) * np.log(1.0 - p)))


def reliability_bins(probs: Sequence[float], hits: Sequence[float],
                     bins: int = ECE_BINS) -> list[dict[str, Any]]:
    """Güvenilirlik diyagramı verisi: kova başına ortalama güven ve gerçek oran.

    Örnek: %70-80 kovasında 40 sinyal varsa ve 26'sı tuttuysa
    ``confidence=0.74``, ``accuracy=0.65``, ``gap=+0.09`` → model AŞIRI güvenli.
    """
    p, h = _as_arrays(probs, hits)
    if p.size == 0:
        return []
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows: list[dict[str, Any]] = []
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, bins - 1)
    for b in range(bins):
        m = idx == b
        n = int(m.sum())
        if n == 0:
            continue
        conf = float(p[m].mean())
        acc = float(h[m].mean())
        rows.append({
            "bin": b,
            "lo": round(float(edges[b]), 3),
            "hi": round(float(edges[b + 1]), 3),
            "samples": n,
            "confidence": round(conf, 4),
            "accuracy": round(acc, 4),
            "gap": round(acc - conf, 4),  # >0: model ÇEKİNGEN, <0: AŞIRI güvenli
        })
    return rows


def ece(probs: Sequence[float], hits: Sequence[float], bins: int = ECE_BINS) -> float | None:
    """Expected Calibration Error — kova ağırlıklı |güven − doğruluk| ortalaması.

    Yorum: 0.00-0.02 mükemmel · 0.02-0.05 iyi · 0.05-0.10 kabul edilebilir ·
    >0.10 model "dürüst değil", eşikler yeniden kalibre edilmeli.
    """
    rows = reliability_bins(probs, hits, bins)
    total = sum(r["samples"] for r in rows)
    if not total:
        return None
    return float(sum(r["samples"] * abs(r["gap"]) for r in rows) / total)


# ---------------------------------------------------------------------------
# Kalibrasyon eğrisi
# ---------------------------------------------------------------------------

def fit_calibration(probs: Sequence[float], hits: Sequence[float],
                    min_samples: int = MIN_SAMPLES,
                    min_per_class: int = MIN_PER_CLASS) -> dict[str, Any]:
    """İzotonik kalibrasyon eğrisi kur.

    Döndürür: kalıcılaştırılabilir sözlük (``x_thresholds``/``y_thresholds``
    ile sklearn nesnesi olmadan da kullanılabilir).

    Yetersiz veride ``fitted=False`` döner — çağıran ham olasılıkla devam eder,
    sahte bir eğri ÜRETİLMEZ (bu, "nötr" davranışın garantisidir).
    """
    p, h = _as_arrays(probs, hits)
    n = int(p.size)
    base: dict[str, Any] = {
        "fitted": False,
        "samples": n,
        "base_rate": float(h.mean()) if n else None,
        "metrics_raw": None,
        "metrics_calibrated": None,
        "x_thresholds": [],
        "y_thresholds": [],
        "bins": reliability_bins(p, h) if n else [],
        "built_at": time.time(),
    }
    positives = int(h.sum()) if n else 0
    negatives = n - positives
    if n < min_samples or positives < min_per_class or negatives < min_per_class:
        base["reason"] = (
            f"yetersiz örnek: n={n} (min {min_samples}), "
            f"pozitif={positives}/negatif={negatives} (min {min_per_class})"
        )
        return base
    if IsotonicRegression is None:  # pragma: no cover
        base["reason"] = "scikit-learn yok"
        return base

    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    iso.fit(p, h)
    calibrated = np.clip(iso.predict(p), 0.0, 1.0)

    base.update({
        "fitted": True,
        "x_thresholds": [float(v) for v in iso.X_thresholds_],
        "y_thresholds": [float(v) for v in iso.y_thresholds_],
        "metrics_raw": {
            "brier": brier_score(p, h),
            "log_loss": log_loss(p, h),
            "ece": ece(p, h),
        },
        "metrics_calibrated": {
            "brier": brier_score(calibrated, h),
            "log_loss": log_loss(calibrated, h),
            "ece": ece(calibrated, h),
        },
        "bins": reliability_bins(calibrated, h),
    })
    return base


def apply_calibration(raw: float | None, state: dict[str, Any] | None) -> float | None:
    """Ham olasılığı kalibre eğriyle eşle (parçalı-doğrusal ara değer).

    Eğri yoksa ``raw`` AYNEN döner — sessizce hiçbir şey uydurulmaz.
    """
    if raw is None:
        return None
    try:
        p = float(raw)
    except (TypeError, ValueError):
        return None
    p = min(1.0, max(0.0, p))
    if not state or not state.get("fitted"):
        return p
    xs = state.get("x_thresholds") or []
    ys = state.get("y_thresholds") or []
    if len(xs) != len(ys) or not xs:
        return p
    if p <= xs[0]:
        return float(ys[0])
    if p >= xs[-1]:
        return float(ys[-1])
    # np.interp sağ taraf kapalı; izotonik eğride basamak davranışı yeterli.
    return float(np.interp(p, xs, ys))


# ---------------------------------------------------------------------------
# Çekimserlik (abstention)
# ---------------------------------------------------------------------------

def break_even_probability(reward_risk: float = DEFAULT_REWARD_RISK) -> float:
    """Ödül/risk oranından başabaş isabet olasılığı.

    RR=1.5 için kazanç +1.5 birim, kayıp -1 birim → p*1.5 = (1-p)*1 → p*=0.40.
    Bu eşiğin ALTINDA işlem beklenen değeri negatiftir (komisyon/spread hariç);
    üstüne çıkıldığında spread ve kayma için pay bırakmak gerekir.
    """
    rr = float(reward_risk) if reward_risk and reward_risk > 0 else DEFAULT_REWARD_RISK
    return float(1.0 / (1.0 + rr))


def should_abstain(calibrated: float | None, threshold: float | None) -> bool:
    """Kalibre olasılık başabaş eşiğinin altında mı? (eşik yoksa: hayır)"""
    if calibrated is None or threshold is None:
        return False
    try:
        return float(calibrated) < float(threshold)
    except (TypeError, ValueError):
        return False


def decide(raw_probability: float | None, *, state: dict[str, Any] | None = None,
           reward_risk: float = DEFAULT_REWARD_RISK,
           threshold: float | None = None) -> dict[str, Any]:
    """Tek çağrıda karar: kalibre olasılık + çekimserlik hükmü.

    Dönen ``probability`` alanı **kalibre** değerdir (eğri yoksa ham değer) —
    canlı yolda kullanılması gereken değer budur.
    """
    calibrated = apply_calibration(raw_probability, state)
    thr = threshold if threshold is not None else break_even_probability(reward_risk)
    return {
        "raw_probability": None if raw_probability is None else float(raw_probability),
        "probability": calibrated,
        "calibrated": bool(state and state.get("fitted")),
        "threshold": round(float(thr), 4),
        "abstain": should_abstain(calibrated, thr),
        "samples": int((state or {}).get("samples") or 0),
    }


# ---------------------------------------------------------------------------
# Durum yayını ve kalıcılık (calibration.py'deki desenle aynı)
# ---------------------------------------------------------------------------

_state: dict[str, Any] = {"calibration": None, "updated_at": 0.0}


def store_state(calibration: dict[str, Any]) -> None:
    """Taze eğriyi yayınla (haftalık yenileme yolu)."""
    _state["calibration"] = calibration or None
    _state["updated_at"] = time.time()


def state() -> dict[str, Any]:
    """UI/rapor yüzeyleri için salt-okunur görünüm."""
    return {"calibration": _state.get("calibration"), "updated_at": _state.get("updated_at")}


def current_calibration() -> dict[str, Any] | None:
    return _state.get("calibration")


def save_state(path: str, calibration: dict[str, Any] | None = None) -> bool:
    """Eğriyi JSON'a yaz (model dondurma deseniyle aynı: artefakt taşınabilir)."""
    payload = {"calibration": calibration if calibration is not None else current_calibration(),
               "saved_at": time.time()}
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_state(path: str) -> dict[str, Any] | None:
    """JSON'dan eğri oku; bozuk/eksik dosyada ``None`` (fail-safe)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        calibration = payload.get("calibration") if isinstance(payload, dict) else None
        return calibration if isinstance(calibration, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Veri toplama yardımcıları
# ---------------------------------------------------------------------------

def split_walk_forward(rows: Sequence[dict], *, cutoff_ts: float | None = None
                       ) -> tuple[list[dict], list[dict]]:
    """Satırları (eğitim, test) diye ZAMANA göre böler.

    Varsayılan: medyan zaman noktası. Amaç, kalibrasyon eğrisinin kendi test
    kümesini "görmesini" engellemek — aksi halde ECE iyimser çıkar.
    """
    def ts(row: dict) -> float:
        for key in ("evaluated_at", "created_at", "close_time", "exit_time"):
            v = row.get(key)
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return 0.0

    ordered = sorted(rows or [], key=ts)
    if not ordered:
        return [], []
    cut = float(cutoff_ts) if cutoff_ts is not None else ts(ordered[len(ordered) // 2])
    train = [r for r in ordered if ts(r) <= cut]
    test = [r for r in ordered if ts(r) > cut]
    return train, test


def rows_to_series(rows: Sequence[dict]) -> tuple[list[float], list[int]]:
    """Aday/İşlem satırlarından (ham olasılık, gerçekleşti) dizileri çıkar.

    Beklenen alanlar: ``ml_hit_probability`` (tahmin) ve sonuç için
    ``touched_target`` (velocity_candidates) veya ``win``/``outcome``.
    Sonucu bilinmeyen satırlar ATILIR — uydurma etiket üretilmez.
    """
    probs: list[float] = []
    hits: list[int] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        raw = row.get("ml_hit_probability")
        if raw is None:
            continue
        try:
            prob = float(raw)
        except (TypeError, ValueError):
            continue
        hit = None
        if row.get("touched_target") is not None:
            hit = 1 if row.get("touched_target") else 0
        elif row.get("win") is not None:
            hit = 1 if row.get("win") else 0
        elif isinstance(row.get("outcome"), str):
            outcome = row["outcome"].strip().upper()
            if outcome in {"WIN", "TP", "WIN_TP", "WIN_TRAILING"}:
                hit = 1
            elif outcome in {"LOSS", "SL", "LOSS_SL"}:
                hit = 0
        if hit is None:
            continue
        probs.append(prob)
        hits.append(hit)
    return probs, hits


def build_from_rows(rows: Sequence[dict], **fit_kwargs: Any) -> dict[str, Any]:
    """Satırlardan eğri kur (kolay yol): filtrelenmiş seriyi ``fit_calibration``'a ver."""
    probs, hits = rows_to_series(rows)
    return fit_calibration(probs, hits, **fit_kwargs)


def summary_for_ui(calibration: dict[str, Any] | None, limit: int = ECE_BINS) -> list[dict[str, Any]]:
    """Rapor ekranı için en bilgilendirici kovalar (mutlak sapmaya göre)."""
    if not calibration:
        return []
    rows = list(calibration.get("bins") or [])
    rows.sort(key=lambda r: -abs(float(r.get("gap") or 0.0)))
    return rows[:limit]


# ---------------------------------------------------------------------------
# SPLIT-CONFORMAL ARALIK (2026-11-09, P2)
#
# NEDEN: model tek bir sayı veriyor ("isabet %38"). Karar için gereken şey
# BELİRSİZLİK: "%90 güvenle isabet 0.28-0.47" → break-even 0.67 ise çekimser kal.
# Kütüphane GEREKMEZ: split-conformal ~10 satır numpy. Bilinen-cevap testinde
# 20 tohumda ortalama kapsama %90.1 (hedef %90) — MAPIE'nin API'si her sürümde
# değiştiği için dış bağımlılık tercih edilmedi.
#
# SINIR (ölçüldü): dağılım KAYARSA kapsama garantisi bozulur (aynı testte %13).
# Bu yüzden aralık "kesin garanti" değil, "kalibrasyon kümesi temsilciyse geçerli".
# ---------------------------------------------------------------------------

CONFORMAL_DEFAULT_ALPHA = 0.10   # %90 aralık


def conformal_quantile(residuals: list[float], alpha: float = CONFORMAL_DEFAULT_ALPHA) -> float | None:
    """Sonlu-örnek düzeltmeli konformal nicem: ceil((n+1)(1-alpha))/n yüzdeliği."""
    vals = sorted(abs(float(r)) for r in (residuals or []) if r is not None)
    n = len(vals)
    if n < 20:
        return None
    level = min(1.0, math.ceil((n + 1) * (1.0 - float(alpha))) / n)
    idx = min(n - 1, max(0, int(math.ceil(level * n)) - 1))
    return vals[idx]


def probability_interval(prob: float, residuals: list[float],
                         alpha: float = CONFORMAL_DEFAULT_ALPHA) -> tuple[float, float] | None:
    """Tek olasılık için kapsama aralığı [lo, hi] ⊂ [0,1]; hesaplanamazsa None."""
    q = conformal_quantile(residuals, alpha)
    if q is None:
        return None
    p = max(0.0, min(1.0, float(prob)))
    return (round(max(0.0, p - q), 4), round(min(1.0, p + q), 4))


def interval_excludes(interval: tuple[float, float] | None, value: float) -> bool:
    """Aralık `value`'yu dışlıyor mu? (break-even dışlanıyorsa yön bilgisi var.)"""
    if not interval:
        return False
    lo, hi = interval
    return bool(float(value) < lo or float(value) > hi)


def hit_rate_interval_wilson(hits: list[int], alpha: float = CONFORMAL_DEFAULT_ALPHA) -> dict | None:
    """İsabet oranı için Wilson skor aralığı (kapalı form, bağımlılıksız).

    NEDEN CONFORMAL DEĞİL: ikili etikette (0/1) |y-p| ≤ 1 olduğu için konformal
    nicem ~0.85'e doyar, aralık [0,1]'e yaklaşır ve karar için bilgi taşımaz
    (ölçüldü: hedef %90 kapsama, ölçülen %100, ortalama genişlik **1.00**).
    Wilson aralığı gözlenen oranın belirsizliğini verir ve break-even ile
    doğrudan karşılaştırılabilir.
    """
    import math as _m
    vals = [1 if float(h) > 0 else 0 for h in (hits or []) if h is not None]
    n = len(vals)
    if n < 20:
        return None
    z = 1.6448536269514722 if abs(float(alpha) - 0.10) < 1e-9 else         (1.959963984540054 if abs(float(alpha) - 0.05) < 1e-9 else 1.2815515655446004)
    p_hat = sum(vals) / n
    denom = 1.0 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denom
    half = z * _m.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n)) / denom
    return {"n": n, "hit_rate": round(p_hat, 4),
            "lo": round(max(0.0, center - half), 4), "hi": round(min(1.0, center + half), 4)}
