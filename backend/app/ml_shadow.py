"""OLASILIK KALİBRASYONU — GÖLGE MOD (shadow) (2026-11-09)

NE YAPAR, NE YAPMAZ
-------------------
Gölge mod **hiçbir kararı değiştirmez**. Her canlı ML tahmininde
`ml_probability.decide()` çağırır ve şunu kaydeder:

    ham olasılık → kalibre olasılık → çekimserlik hükmü

Amacı: eşiği **kanıtla** seçmek. `calibration.py`'nin kendi docstring'i doğru bir
şey söylüyor — "ölçülmemiş bir çarpanla boyut değiştirmek" tehlikelidir. Aynı
disiplin burada uygulanır: kalibre olasılık canlı kapıya bağlanmadan ÖNCE,
gerçek adaylar üzerinde "kalibre olsaydı ne olurdu" verisi toplanır. 1-2 hafta
sonra `velocity_candidates` sonuçlarıyla karşılaştırılıp eşik kanıtla açılır.

NEDEN AYRI MODÜL
----------------
`ml_probability` saf matematik olarak kalsın (test edilebilir, yan etkisiz).
Loglama/sayaç/artefakt önbelleği burada. Böylece "karar yolunu değiştiren bir
şey" arayan gelecekteki bir geliştirici bu dosyayı görüp durur.

GÜVENLİK KURALLARI
------------------
* `observe()` **asla istisna fırlatmaz** (tahmin yolu asla ölçüm yüzünden düşmez).
* Artefakt yoksa/bozuksa ham olasılık kullanılır ve `calibrated=False` loglanır —
  "düzeltmiş gibi" davranılmaz.
* Artefakt mtime'ı izlenir: yeni artefakt restart GEREKTİRMEDEN devreye girer.
* Kapalıysa (`ML_CALIBRATION_SHADOW_ENABLED=0`) hiçbir iş yapılmaz.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

# DİKKAT: proje `config` NESNESİNİ kullanıyor (`from .config import config`),
# modülü değil. `from app import config` modülü getirir ve attribute'lar
# bulunamaz — bir turda gölge mod bu yüzden "artifact: ''" ile çalıştı.
from app.config import config
from app import ml_probability as mp

logger = logging.getLogger("scalper.ml_calibration")

#: Artefakt önbelleği — (mtime, calibration). Dosya değişince yeniden okunur.
_cache: dict[str, Any] = {"path": None, "mtime": None, "calibration": None, "checked_at": 0.0}
_lock = threading.Lock()

#: Gölge sayaçları (sağlık/rapor yüzeyleri için).
_counters: dict[str, Any] = {
    "observations": 0,
    "calibrated_observations": 0,
    "would_abstain": 0,
    "raw_sum": 0.0,
    "calibrated_sum": 0.0,
    "started_at": None,
}

#: Özet log sıklığı (her N gözlemde bir INFO satırı).
_SUMMARY_EVERY = 500


def _artifact_path() -> str:
    return str(getattr(config, "ML_CALIBRATION_ARTIFACT", "") or "")


def _load_calibration() -> dict[str, Any] | None:
    """Artefaktı mtime kontrollü oku (değişmediyse önbellekten)."""
    path = _artifact_path()
    if not path:
        return None
    now = time.time()
    with _lock:
        same_path = _cache.get("path") == path
        # mtime kontrolünü 30 sn'de bir yap (her tahminde stat çağırmayalım).
        if same_path and now - float(_cache.get("checked_at") or 0) < 30:
            return _cache.get("calibration")
        _cache["path"] = path
        _cache["checked_at"] = now
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            _cache["mtime"] = None
            _cache["calibration"] = None
            return None
        if same_path and _cache.get("mtime") == mtime:
            return _cache.get("calibration")
        calibration = mp.load_state(path)
        _cache["mtime"] = mtime
        _cache["calibration"] = calibration
        if calibration and calibration.get("fitted"):
            logger.info(
                "[CAL] kalibrasyon artefaktı yüklendi: samples=%s base_rate=%s ece_kalibre=%s",
                calibration.get("samples"), calibration.get("base_rate"),
                (calibration.get("metrics_calibrated") or {}).get("ece"),
            )
        else:
            logger.warning("[CAL] artefakt var ama eğri kurulu değil (%s) — gölge ham olasılıkla çalışır", path)
        return calibration


def enabled() -> bool:
    return bool(getattr(config, "ML_CALIBRATION_SHADOW_ENABLED", True))


def observe(*, raw_probability: float | None, symbol: str | None = None,
            strategy: str | None = None, horizon: int | None = None) -> dict[str, Any] | None:
    """Gölge kararı üret ve kaydet. Karar yolunu DEĞİŞTİRMEZ.

    Döndürür: `ml_probability.decide()` sözlüğü (ölçüm/rapor için) ya da
    gölge mod kapalıysa/`raw_probability` yoksa ``None``.
    """
    if not enabled() or raw_probability is None:
        return None
    try:
        calibration = _load_calibration()
        decision = mp.decide(
            raw_probability,
            state=calibration,
            reward_risk=float(getattr(config, "ML_CALIBRATION_REWARD_RISK", 1.5)),
        )
        _counters["observations"] += 1
        if decision.get("calibrated"):
            _counters["calibrated_observations"] += 1
            _counters["calibrated_sum"] += float(decision.get("probability") or 0.0)
        if decision.get("abstain"):
            _counters["would_abstain"] += 1
        _counters["raw_sum"] += float(decision.get("raw_probability") or 0.0)
        if _counters["started_at"] is None:
            _counters["started_at"] = time.time()

        logger.debug(
            "[CAL-SHADOW] %s %s h=%s ham=%.4f kalibre=%.4f esik=%.3f cekimser=%s (n=%s)",
            symbol or "?", strategy or "?", horizon if horizon is not None else "-",
            float(decision["raw_probability"]), float(decision["probability"] or 0.0),
            float(decision["threshold"]), decision["abstain"], decision["samples"],
        )
        if _counters["observations"] % _SUMMARY_EVERY == 0:
            c = counters()
            logger.info(
                "[CAL-SHADOW] özet: gözlem=%s kalibre=%s çekimser=%s (%.1f%%) "
                "ort_ham=%.4f ort_kalibre=%.4f",
                c["observations"], c["calibrated_observations"], c["would_abstain"],
                c["abstain_rate_pct"], c["mean_raw"], c["mean_calibrated"],
            )
        return decision
    except Exception as exc:  # gölge katmanı tahmin yolunu ASLA düşürmez
        logger.debug("[CAL-SHADOW] atlandı: %s", exc)
        return None


def counters() -> dict[str, Any]:
    """Sağlık/rapor yüzeyi için gölge sayaçları."""
    n = int(_counters["observations"])
    calibrated = int(_counters["calibrated_observations"])
    abstain = int(_counters["would_abstain"])
    return {
        "enabled": enabled(),
        "artifact": _artifact_path(),
        "artifact_loaded": bool((_cache.get("calibration") or {}).get("fitted")),
        "artifact_samples": int((_cache.get("calibration") or {}).get("samples") or 0),
        "observations": n,
        "calibrated_observations": calibrated,
        "would_abstain": abstain,
        "abstain_rate_pct": round(abstain / n * 100, 2) if n else 0.0,
        "mean_raw": round(_counters["raw_sum"] / n, 4) if n else None,
        "mean_calibrated": (round(_counters["calibrated_sum"] / calibrated, 4)
                            if calibrated else None),
        "started_at": _counters["started_at"],
    }


def reset_counters() -> None:
    """Testler ve operasyonel sıfırlama için."""
    _counters.update({
        "observations": 0, "calibrated_observations": 0, "would_abstain": 0,
        "raw_sum": 0.0, "calibrated_sum": 0.0, "started_at": None,
    })
