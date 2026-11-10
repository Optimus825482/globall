"""TOKYO PENCERE KOLU — ölçülmüş saat pencereleri (dosya tabanlı ilk kol).

KAYNAK ÖLÇÜM (`docs/FX_YENI_SINYAL_AILESI_ARASTIRMASI_2026-11-10.md` §0):
5 yıl H1, 1.290 gözlem/sembol/saat, TREND DEMEAN edilmiş, maliyet düşülmüş net:
  GBPUSD 01:00 BUY +1.58p (t=10.7) · USDJPY 01:00 BUY +1.27p (t=6.4) ·
  EURUSD 01:00 BUY +0.67p (t=7.3) · XAUUSD 01:00 BUY +70p (t=3.2) ·
  EURUSD 14:00 SELL +0.56p (t=-4.6) · GBPUSD 13:00 SELL +0.25p (t=-2.7)
15 sembol × 24 saat tarandı: başka pozitif pencere YOK.

SÖZLEŞME: `signal()` +1/−1/0 döner; **0 pozisyon kapatmaz** (çıkış ayrı katman).
Saf ve vektörize: yalnız bar zaman damgalarına bakar.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Sequence, Tuple

from app.arms.base import ArmSpec, SIGNAL_LONG, SIGNAL_NONE, SIGNAL_SHORT, register_arm

#: sembol → [(saat_utc, yön)] — ölçülmüş pencereler (yön: +1 LONG, -1 SHORT)
WINDOWS: Dict[str, List[Tuple[int, int]]] = {
    "GBPUSD": [(1, SIGNAL_LONG), (13, SIGNAL_SHORT)],
    "EURUSD": [(1, SIGNAL_LONG), (14, SIGNAL_SHORT)],
    "USDJPY": [(1, SIGNAL_LONG)],
    "XAUUSD": [(1, SIGNAL_LONG)],
}

#: pencere başlangıcından sonra kaç dakika içinde sinyal üretilir (giriş penceresi)
ENTRY_WINDOW_MIN = 5


def signal(bars: Sequence[Sequence[float]], symbol: str) -> List[int]:
    """Bar serisi → sinyal serisi (+1/−1/0). Bar biçimi: (ts_sn, o, h, l, c).

    Sözleşme: uzunluk eşit; değerler {+1,−1,0}; saf (yan etki yok).
    """
    wins = WINDOWS.get(str(symbol).upper())
    out: List[int] = [SIGNAL_NONE] * len(bars)
    if not wins:
        return out
    for i, bar in enumerate(bars):
        ts = int(bar[0])
        t = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
        if t.weekday() >= 5:                    # hafta sonu FX kapalı
            continue
        for hour, direction in wins:
            if t.hour == hour and t.minute < ENTRY_WINDOW_MIN:
                out[i] = direction
                break
    return out


register_arm(ArmSpec(
    name="tokyo_window",
    description=("Ölçülmüş saat pencerelerinde yön sinyali (01:00 LONG; GBPUSD 13:00 ve "
                 "EURUSD 14:00 SHORT). Zaman tabanlı; bar deseni kullanmaz."),
    timeframe="1h",
    symbols=sorted(WINDOWS),
    handler=signal,
    evidence=("5y H1, trend demean, maliyet düşülmüş: GBPUSD 01:00 +1.58p t=10.7 · "
              "USDJPY +1.27p t=6.4 · EURUSD +0.67p t=7.3 · XAUUSD +70p t=3.2 · "
              "EURUSD 14:00 SELL +0.56p t=-4.6 · GBPUSD 13:00 SELL +0.25p t=-2.7"),
    tags=["time", "session", "measured"],
))
