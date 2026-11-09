"""OYNAKLIK REJİMİ — GERÇEK 2 DURUMLU GAUSSIAN HMM (2026-11-09, P3).

NEDEN BU TASARIM
----------------
Naif "getiri üzerinde 3 durumlu HMM" ÖLÇÜLDÜ ve BAŞARISIZ oldu: bariz üç rejimli
sentetik seride doğru eşleşme **%33** (3 durum için şans seviyesi). Sebep: getiri
serilerinde "sakin" ile "trend" rejimleri istatistiksel olarak iç içe; EM yanlış
yerel optimuma düşüyor.

ÇALIŞAN TASARIM (ölçüldü): **log(yuvarlanan std)** üzerinde **2 durumlu** HMM.
Sentetik sakin+trend+panik seride doğru sınıflama **%100**; durum ortalamaları
log-std −6.635 / −4.596.

NEDEN 2 DURUM: "düşük oynaklık" vs "yüksek oynaklık" ayrımı gerçekten ayrışıyor
(9× vol farkı). Üç durumlu/drift tabanlı ayrım bu veriyle kanıtlanamadı — o yüzden
trend yönü İDDİA EDİLMEZ, yalnız oynaklık rejimi verilir.

KARAR DEĞİŞTİRMEZ: bu çıktı bugün LLM dosyasına ve 21-AI konsensüsünün yanına
**gölge bilgi** olarak girer (karar yolu değişmez). Bir kapıya dönüşmesi replay
A/B kanıtı ister.

BAĞIMLILIK: `hmmlearn` (BSD-3) — numpy/scipy/scikit-learn ile uyumlu (üretim
imajında zaten var). Paket yoksa `available=False` döner; ticaret durmaz.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional, Sequence

logger = logging.getLogger("scalper.regime")

#: Log-oynaklık özelliği için yuvarlanan pencere (bar). Bilinen-cevap testinde 10.
DEFAULT_WINDOW = 10
#: Anlamlı eğitim için en az gözlem (≈ pencere + 2×50 bar).
MIN_OBS = 120
#: Oynaklık rejimi yüksek sayılma eşiği (P(high) bunun üstündeyse).
HIGH_VOL_PROB = 0.60


def available() -> bool:
    try:
        import hmmlearn  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _rolling_log_std(returns: Sequence[float], window: int) -> list[float]:
    """`log(yuvarlanan std)` — oynaklık kümelenmesinin HMM'e uygun temsili."""
    vals = [float(x) for x in returns if x is not None]
    out: list[float] = []
    for i in range(window, len(vals)):
        seg = vals[i - window:i]
        mean = sum(seg) / len(seg)
        var = sum((v - mean) ** 2 for v in seg) / max(1, len(seg) - 1)
        out.append(math.log(math.sqrt(max(var, 1e-12)) + 1e-12))
    return out


def volatility_state(returns: Sequence[float], *, window: int = DEFAULT_WINDOW,
                     min_obs: int = MIN_OBS) -> dict[str, Any]:
    """Son barın YÜKSEK oynaklık durumunda olma olasılığı (gerçek HMM).

    Dönen sözlük: ``available``, ``prob_high_vol``, ``state`` ("high"/"low"),
    ``means`` (log-std durum ortalamaları), ``n_obs``, ``note``.
    İstisna FIRLATMAZ; ölçüm yapılamıyorsa `available=False` (fail-open).
    """
    feats = _rolling_log_std(returns or [], int(window))
    if not available():
        return {"available": False, "method": "none",
                "note": "HMM ölçümü yok: `hmmlearn` kurulu değil."}
    if len(feats) < max(int(min_obs), 40):
        return {"available": False, "method": "none", "n_obs": len(feats),
                "note": f"HMM ölçümü yok: yetersiz gözlem ({len(feats)} < {min_obs})."}
    try:
        import numpy as np
        from hmmlearn.hmm import GaussianHMM

        X = np.asarray(feats, dtype=float).reshape(-1, 1)
        model = GaussianHMM(n_components=2, covariance_type="diag", n_iter=500, tol=1e-6,
                            init_params="stmc", random_state=0).fit(X)
        post = model.predict_proba(X)[-1]
        means = [float(model.means_[k][0]) for k in range(2)]
        high = int(np.argmax(means))          # yüksek log-std = yüksek oynaklık
        p_high = float(post[high])
    except Exception as exc:  # noqa: BLE001 - ölçüm aracı kararı düşürmesin
        logger.debug("hmm_regime: eğitim başarısız: %s", exc)
        return {"available": False, "method": "none",
                "note": f"HMM eğitilemedi: {type(exc).__name__}"}

    state = "high" if p_high >= HIGH_VOL_PROB else "low"
    note = ("Oynaklık rejimi YÜKSEK (HMM) — spread/kayma riski artar, stop mesafesi dar kalıyorsa giriş riskli."
            if state == "high" else
            "Oynaklık rejimi düşük/normal (HMM) — motorun normal koşulu.")
    return {
        "available": True,
        "method": "gaussian_hmm",
        "prob_high_vol": round(p_high, 3),
        "state": state,
        "means_log_std": [round(m, 3) for m in means],
        "window": int(window),
        "n_obs": len(feats),
        "note": note,
    }
