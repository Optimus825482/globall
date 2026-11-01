"""Dondurulmuş ML modelinin İLERİ (forward) test kaydı.

Neden gerekli: bir modelin işe yaradığını yalnızca eğitimden SONRA, hiç
görülmemiş veriyle ölçebilirsin. Hem geriye dönük backtest hem in-sample
holdout bu soruyu yanıtlayamaz — ikisi de modelin gördüğü dağılıma yakın
durur. Bu modül, modeli dondurup her canlı tahmini kaydeder ve sonucu
gerçek mumlardan ölçer. Hiçbir parametre ayarlanmaz.

Ölçüm disiplini (2026-11-01 ölçümlerinden):
  • AUC 0.88 ama özellikler karıştırılınca 0.87'ye düşüyor → modelin gücünün
    çoğu "saat kaç" + "hangi sembol" bilgisinden geliyor; 12 piyasa özelliğinin
    marjinal katkısı küçük. Forward test bu ikisini ayırt eder.
  • Seçim çok seyrek: 740 bin barın %0.2'si, günde ~5 seçim. Anlamlı bir sonuç
    için HAFTALAR gerekir; birkaç günün verisi hiçbir şey kanıtlamaz.

Bu modül İŞLEM ENGELLEMEZ ve karar vermez: salt kayıt + raporlama.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from typing import Any

from app.config import config

logger = logging.getLogger("scalper.ml.forward")

_FROZEN_CACHE: dict[str, Any] = {"id": None, "loaded_at": 0.0}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def freeze_current_model(note: str = "") -> dict[str, Any] | None:
    """Aktif artifact'ı dondurur: kopyalar, sha256 alır, DB'ye yazar.

    Neden kopya: eğitim döngüsü 12 saatte bir `upside_v3.joblib`'in ÜZERİNE
    yazar. Dondurulmuş model dosyası sabit kalmalı, yoksa "öngörülen" model ile
    "ölçülen" model farklı olur ve forward test anlamsızlaşır.
    """
    src = os.path.join(config.ML_MODELS_DIR, f"upside_{_feature_version()}.joblib")
    if not os.path.exists(src):
        logger.warning("[forward] dondurulacak artifact yok: %s", src)
        return None
    digest = _sha256(src)
    frozen_dir = os.path.join(config.ML_MODELS_DIR, "frozen")
    os.makedirs(frozen_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    dst = os.path.join(frozen_dir, f"frozen_{stamp}_{digest[:12]}.joblib")
    if not os.path.exists(dst):
        shutil.copy2(src, dst)

    # Meta veriyi diskteki artifact'tan oku (eğitim sırasında yazılmış)
    meta: dict[str, Any] = {}
    try:
        from app import ml_forecast
        art = ml_forecast.load_model() or {}
        meta = {"trained_at": art.get("trained_at"),
                "horizons": list(art.get("horizons") or []),
                "symbol_count": len(art.get("symbol_codes") or {})}
    except Exception as exc:  # noqa: BLE001
        logger.info("[forward] artifact meta okunamadı: %s", exc)

    return {
        "frozen_at": time.time(),
        "artifact_path": dst,
        "artifact_sha256": digest,
        "feature_version": _feature_version(),
        "trained_at": meta.get("trained_at"),
        "horizons": json.dumps(meta.get("horizons") or []),
        "symbol_count": meta.get("symbol_count") or 0,
        "gate_probability": config.ML_MIN_HIT_PROBABILITY,
        "note": note or "ileri test (dondurulmuş model)",
    }


def _feature_version() -> str:
    try:
        from app.ml_forecast import FEATURE_VERSION
        return FEATURE_VERSION
    except Exception:  # noqa: BLE001
        return "v3"


def load_frozen_model(frozen: dict[str, Any]):
    """Dondurulmuş artifact'ı yükler (canlı modelden BAĞIMSIZ).

    `ml_forecast.load_model()` KULLANILMAZ: o fonksiyon canlı dosyayı okur ve
    eğitim onun üzerine yazdığında dondurulmuş test kirlidir.

    GÜVENLİK NOTU — joblib.load: bu bir pickle tabanlı yükleyicidir ve keyfi
    kod çalıştırabilir, dolayısıyla YALNIZCA güvenilen kaynaktan okunmalıdır.
    Okunan dosya dışarıdan gelmez: `freeze_current_model` kendi eğitim
    çıktımızı (`ml_forecast.train` → `joblib.dump`) `ML_MODELS_DIR/frozen/`
    altına `shutil.copy2` ile kopyalar. Yol da bu modül tarafından üretilir,
    kullanıcı girdisinden gelmez. Yine de yol `ML_MODELS_DIR` dışına çıkarsa
    yükleme reddedilir (savunma amaçlı).
    """
    import joblib
    path = frozen.get("artifact_path")
    if not path or not os.path.exists(path):
        return None
    models_dir = os.path.abspath(config.ML_MODELS_DIR)
    if not os.path.abspath(path).startswith(models_dir):
        logger.warning("[forward] artifact yolu ML_MODELS_DIR dışında, reddedildi: %s", path)
        return None
    try:
        return joblib.load(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[forward] dondurulmuş model yüklenemedi: %s", exc)
        return None


async def get_active_frozen():
    """Aktif (emekli edilmemiş) dondurulmuş modeli döndürür; yoksa None.

    Süreç içi önbellek: her taramada DB'ye gidilmesin. `retired_at` ile
    emekliye ayrılan model bir daha seçilmez.
    """
    from app import database
    rows = await database.get_frozen_models(active_only=True)
    if not rows:
        return None
    return rows[0]


async def record_shadow(predictions: list[dict[str, Any]]) -> int:
    """Ölçülen tahminleri kaydeder. Boş liste sorun değil."""
    if not predictions:
        return 0
    from app import database
    return await database.insert_shadow_predictions(predictions)


async def evaluate_pending(limit: int = 500) -> dict[str, Any]:
    """Ufku dolmuş tahminlerin sonucunu gerçek mumlardan ölçer.

    Bir tahmin, ufku kadar (artı biraz pay) zaman geçtikten sonra değerlendirilir.
    Fiyat serisi `historical_candles`'tan gelir — yani ölçüm, modelin
    eğitildiği veri kaynağının aynısıdır (sızıntı yok: yalnızca tahmin ANINDAN
    SONRAKİ barlar kullanılır).
    """
    from app import database
    pending = await database.get_pending_shadow_predictions(limit=limit)
    if not pending:
        return {"evaluated": 0, "expired": 0}

    now_ms = int(time.time() * 1000)
    evaluated, expired = 0, 0
    for row in pending:
        horizon_ms = int(row["horizon_minutes"]) * 60_000
        start_ms = int(row["predicted_at"] * 1000)
        if now_ms < start_ms + horizon_ms:
            continue                      # ufuk dolmadı
        bars = _bars_after(row["symbol"], start_ms)
        if not bars or len(bars) < 2:
            expired += 1                  # veri yok (sembol çıkmış olabilir)
            await database.mark_shadow_expired(row["id"])
            continue
        entry = float(row["entry_price"])
        if entry <= 0:
            await database.mark_shadow_expired(row["id"])
            expired += 1
            continue
        outcome = _measure_outcome(entry, bars, int(row["horizon_minutes"]))
        await database.save_shadow_outcome(row["id"], outcome)
        evaluated += 1
    return {"evaluated": evaluated, "expired": expired}


def _bars_after(symbol: str, start_ms: int) -> list[dict]:
    """Tahmin anından SONRAKİ gerçek mumlar (Binance public API).

    `historical_candles` KULLANILMAZ: o tablo canlı değil, backfill ile
    doldurulur ve ölçüm anında günler geride kalabilir (2026-11-01 ölçümü:
    son satır bir gün öncesine aitti). Bayat veriyle ölçüm yapmak, tahminleri
    yanlış fiyatlarla "değerlendirir". Mumlar doğrudan borsadan çekilir.
    """
    import urllib.request
    end_ms = start_ms + 60 * 60 * 1000          # en fazla 1 saat ileri
    url = (f"https://api.binance.com/api/v3/klines?symbol={symbol}"
           f"&interval=5m&startTime={int(start_ms)}&endTime={int(end_ms)}&limit=60")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        logger.info("[forward] mum çekilemedi %s: %s", symbol, exc)
        return []
    # Yalnızca KAPANMIŞ barlar: son bar hâlâ oluşuyor olabilir
    now_ms = int(time.time() * 1000)
    out = []
    for k in raw:
        if int(k[6]) >= now_ms:                 # close_time henüz gelmedi
            continue
        out.append({"open_time": int(k[0]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4])})
    return out


def _measure_outcome(entry: float, bars: list[dict], horizon_minutes: int) -> dict[str, Any]:
    """Takipçi çıkışıyla net getiriyi ölçer (canlı simülatörle aynı kurallar).

    Kurallar `spot_monitor`'dan alınır ki forward test ile paper trade aynı şeyi
    ölçsün: kâr %1.5'te takipçi devreye girer, %0.8 kilitlenir, zirveden %0.6
    geriden gelir. Komisyon round-trip düşülür.
    """
    from app import spot_monitor as sm
    # Komisyon, spot simülatörünün SEÇİLİ ücret senaryosundan gelir — forward
    # test ile paper trade aynı maliyeti görsün.
    fee = sm._round_trip_cost_pct()
    # Başlangıç stopu: 5dk taraması için %0.9 (spot_monitor TIMEFRAMES ile aynı)
    stop = entry * (1.0 - 0.90 / 100.0)
    peak, trail = entry, False
    max_fav, max_adv = 0.0, 0.0
    n = max(1, min(len(bars), horizon_minutes // 5))
    for i, b in enumerate(bars[:n]):
        hi, lo = float(b["high"]), float(b["low"])
        max_fav = max(max_fav, (hi - entry) / entry * 100.0)
        max_adv = min(max_adv, (lo - entry) / entry * 100.0)
        peak = max(peak, hi)
        if not trail and (peak - entry) / entry * 100.0 >= sm.TRAIL_ACTIVATE_PCT:
            trail = True
        if trail:
            stop = max(stop, entry * (1.0 + sm.TRAIL_LOCK_PCT / 100.0),
                       peak * (1.0 - sm.TRAIL_DISTANCE_PCT / 100.0))
        if lo <= stop:
            return {"max_favorable_pct": round(max_fav, 4),
                    "max_adverse_pct": round(max_adv, 4),
                    "exit_pct": round((stop - entry) / entry * 100.0 - fee, 4),
                    "hit_target": bool(max_fav >= sm.TRAIL_ACTIVATE_PCT),
                    "bars_held": i + 1}
    last = float(bars[min(n, len(bars)) - 1]["close"])
    return {"max_favorable_pct": round(max_fav, 4),
            "max_adverse_pct": round(max_adv, 4),
            "exit_pct": round((last - entry) / entry * 100.0 - fee, 4),
            "hit_target": bool(max_fav >= sm.TRAIL_ACTIVATE_PCT),
            "bars_held": n}


async def forward_report(frozen_id: int | None = None) -> dict[str, Any]:
    """Dondurulmuş modelin ileri test karnesi. Hiçbir şey ayarlamaz."""
    from app import database
    frozen = None
    if frozen_id:
        frozen = await database.get_frozen_model(frozen_id)
    else:
        rows = await database.get_frozen_models(active_only=True)
        frozen = rows[0] if rows else None
    if not frozen:
        return {"status": "no_frozen_model"}
    summary = await database.shadow_summary(frozen["id"])
    summary["frozen"] = {
        "id": frozen["id"],
        "frozen_at": frozen["frozen_at"],
        "artifact_sha256": (frozen["artifact_sha256"] or "")[:12],
        "gate_probability": frozen["gate_probability"],
        "days_running": round((time.time() - float(frozen["frozen_at"])) / 86400.0, 2),
    }
    return summary
