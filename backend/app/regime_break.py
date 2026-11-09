"""YAPI KIRILMASI (change-point) — KARAR DESTEĞİ (2026-11-09, P1).

NEDEN: girişin en pahalı hatası **rejim değişiminden hemen sonra** eski kuralla
işlem açmak (whipsaw). Bu modül fiyat serisinde istatistiksel kırılma noktası
arar ve "yapı yeni mi kırıldı?" sorusunu veriyle cevaplar.

KÜTÜPHANE: `ruptures` (BSD-2, `Pelt` + rbf maliyeti) — numpy/scipy dışında bir şey
istemez, üretim imajıyla uyumlu. Bilinen-cevap testi geçti (200. noktadaki rejim
değişimini TAM buldu). Paket yoksa modül **fail-open** davranır: `available=False`
döner, karar DEĞİŞMEZ (ölçüm eksik kalır, ticaret durmaz).

KARAR DEĞİŞTİRMEZ (gölge/bağlam): bu bilgi LLM dosyasına eklenir. KAPI olarak
denenmesi REDDEDİLDİ — ölçüm (`scripts/forex_replay_backtest.py --break-gate-bars`,
14 gün XAU+BTC, chandelier 0.1):

    kapı      n     WR%    net $      PF    maxDD $
    yok       849   86.1   101,357    2.47   3,502
    12 bar    849   86.1   101,357    2.47   3,502   (fiilen hiç tetiklenmiyor)
    24 bar    732   85.5    83,783    2.38   3,646   (−%17)
    48 bar    448   83.5    40,154    1.99   5,898   (−%60)

Yani "kırılma sonrası giriş yasak" bu sistemde KÂR KESİYOR (stratejiler kırılmanın
İÇİNDE işlem yapıyor). Bu yüzden bilgi olarak kalır, kapı olarak KULLANILMAZ.
Tekrar önerilmesin: ölçüm yukarıda.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional, Sequence

logger = logging.getLogger("scalper.regime")

#: PELT cezası. Bilinen-cevap sentetik testte (400 nokta, 200'de rejim değişimi,
#: getiri std 0.002 → 0.010) 10.0 cezası kırılmayı tam buldu, gürültüde tetiklemedi.
DEFAULT_PENALTY = 10.0
#: Kırılma "taze" sayılan bar sayısı (5m seride 12 bar = 1 saat).
DEFAULT_MAX_AGE_BARS = 12
#: ruptures'ın anlamlı çalışması için gereken en az bar.
MIN_BARS = 60


def _as_floats(values) -> list[float]:
    """Sayıya çevrilemeyen değerleri SESSİZCE atar (bozuk seri ölçümü düşürmesin)."""
    out: list[float] = []
    for v in (values or []):
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(f)
    return out


def available() -> bool:
    """`ruptures` kurulu mu? (Üretimde kurulu olmalı; değilse ölçüm sessizce atlanır.)"""
    try:
        import ruptures  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def detect_breaks(values: Sequence[float], *, penalty: float = DEFAULT_PENALTY,
                  min_bars: int = MIN_BARS) -> list[int]:
    """Kırılma noktalarının İNDEKSLERİNİ döndürür (seri sonu indeksi hariç).

    Bozuk/kısa seride veya paket yoksa `[]` — istisna fırlatmaz.
    """
    try:
        import numpy as np
        import ruptures as rpt
    except Exception:  # noqa: BLE001
        return []
    arr = _as_floats(values)
    if len(arr) < max(int(min_bars), 10):
        return []
    try:
        signal = np.asarray(arr, dtype=float).reshape(-1, 1)
        algo = rpt.Pelt(model="rbf", min_size=max(5, len(arr) // 20)).fit(signal)
        points = algo.predict(pen=float(penalty))
    except Exception as exc:  # noqa: BLE001 - ölçüm aracı asla kararı düşürmesin
        logger.debug("regime_break: kırılma tespiti başarısız: %s", exc)
        return []
    # ruptures son eleman olarak seri uzunluğunu döndürür → kırılma değil.
    return [int(p) for p in (points or []) if 0 < int(p) < len(arr)]


def recent_break(closes: Sequence[float], *, max_age_bars: int = DEFAULT_MAX_AGE_BARS,
                 penalty: float = DEFAULT_PENALTY, min_bars: int = MIN_BARS) -> dict[str, Any]:
    """Son kırılma `max_age_bars` içindeyse raporlar.

    Dönen sözlük LLM/panel tüketimine hazır:
      ``available``  ölçüm yapılabildi mi (paket + yeterli veri)
      ``broken``     yapı yeni mi kırıldı
      ``bars_since`` kaç bar önce
      ``direction``  kırılma sonrası eğim ("up"/"down"/None)
      ``note``       insan-okur tek cümle
    """
    arr = _as_floats(closes)
    if not available():
        return {"available": False, "broken": False, "bars_since": None, "direction": None,
                "note": "Kırılma ölçümü yok: `ruptures` kurulu değil."}
    if len(arr) < max(int(min_bars), 10):
        return {"available": False, "broken": False, "bars_since": None, "direction": None,
                "note": f"Kırılma ölçümü yok: yetersiz bar ({len(arr)} < {min_bars})."}
    breaks = detect_breaks(arr, penalty=penalty, min_bars=min_bars)
    if not breaks:
        return {"available": True, "broken": False, "bars_since": None, "direction": None,
                "note": "Yapı kırılması yok (seri tek rejimli)."}
    last = breaks[-1]
    bars_since = len(arr) - last
    # Yön: kırılma sonrası ortalamayı öncesiyle karşılaştır (küçük pencereler).
    window = max(5, min(20, (len(arr) - last)))
    after = arr[last:]
    before = arr[max(0, last - window):last]
    direction = None
    if after and before:
        delta = (sum(after) / len(after)) - (sum(before) / len(before))
        if abs(delta) > 1e-12:
            direction = "up" if delta > 0 else "down"
    broken = bars_since <= int(max_age_bars)
    if broken:
        note = (f"Yapı {bars_since} bar önce KIRILDI ({'yukarı' if direction == 'up' else 'aşağı' if direction == 'down' else 'yön belirsiz'}) "
                f"— eski rejim kuralıyla giriş riskli.")
    else:
        note = f"Son kırılma {bars_since} bar önce (taze değil)."
    return {"available": True, "broken": broken, "bars_since": bars_since,
            "direction": direction, "note": note}


def from_candles(candles: Sequence[dict], *, max_age_bars: int = DEFAULT_MAX_AGE_BARS,
                 penalty: float = DEFAULT_PENALTY) -> dict[str, Any]:
    """Mum listesinden (MT5/Yahoo) kapanış serisi çıkarıp `recent_break` çağırır."""
    closes = []
    for bar in candles or []:
        try:
            val = bar.get("close")
            if val is not None:
                closes.append(float(val))
        except (AttributeError, TypeError, ValueError):
            continue
    return recent_break(closes, max_age_bars=max_age_bars, penalty=penalty)
