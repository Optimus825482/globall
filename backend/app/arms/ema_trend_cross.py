"""EMA KESİŞİMİ (TREND) KOLU (2026-11-10) — vectorbt taramasından gelen aday.

**DURUM: ELENDİ (2026-11-10).** 5 yıl 1h'te iyi görünen sonuç **10 yıllık günlükte
tutmadı** (buy&hold'un altında) ve short tarafı felaket → kayıtlı DEĞİL, canlıya alınmaz.

KAYNAK: `docs/VBT_STRATEJI_TARAMASI_2026-11-10.md`. NAS100 1h, fast 5/10/20 × slow 100/150/200
**tüm ızgara OOS'ta pozitif (Sharpe 0.57–1.33, 46-122 işlem)** → tek hücre şansı değil, plato.
Çıkış: hızlı EMA yavaşı keserse (karşıt sinyal).
"""
from __future__ import annotations

from typing import List, Sequence

from app.arms.base import ArmSpec, SIGNAL_LONG, SIGNAL_NONE, SIGNAL_SHORT, register_arm

PARAMS = {"NAS100": (10, 200)}


def _ema(values: Sequence[float], span: int) -> List[float]:
    alpha = 2.0 / (span + 1.0)
    out: List[float] = []
    prev = float(values[0]) if values else 0.0
    for v in values:
        prev = alpha * float(v) + (1 - alpha) * prev
        out.append(prev)
    return out


def signal(bars: Sequence[Sequence[float]], symbol: str) -> List[int]:
    """EMA kesişimi: hızlı yavaşı yukarı keserse +1, aşağı keserse −1."""
    sym = str(symbol).upper()
    p = PARAMS.get(sym)
    out: List[int] = [SIGNAL_NONE] * len(bars)
    if not p or len(bars) < max(p) + 2:
        return out
    fast, slow = p
    closes = [b[4] for b in bars]
    ef, es = _ema(closes, fast), _ema(closes, slow)
    for i in range(1, len(bars)):
        if ef[i] > es[i] and ef[i - 1] <= es[i - 1]:
            out[i] = SIGNAL_LONG
        elif ef[i] < es[i] and ef[i - 1] >= es[i - 1]:
            out[i] = SIGNAL_SHORT
    return out


#: KAYIT YOK — 2026-11-10'da **10 yıllık günlük** doğrulamada ELENDİ (aşağıya bak).
#: Dosya, ölçümü yeniden üretilebilir tutmak için saklanır; CANLIYA ALINMAZ.
EVIDENCE = (
    "5 yıl 1h: XAUUSD Long Donchian(15) Sharpe 1.65 / getiri +128% / DD 14% "
    "(buy&hold 1.19 / +125% / 30%) · USDJPY 1.14 / +38% / 12% (b&h 0.86 / +40% / 16%) · "
    "NAS100 Long EMA(10,200) 0.76 / +47% / 17% (b&h 0.72 / +72% / 37%). "
    "ANCAK 10 yıl GÜNLÜK'te üstünlük KAYBOLUYOR: XAUUSD 0.68 vs b&h 0.98 (+93% vs +236%), "
    "USDJPY 0.37 vs 0.58, NAS100 1.04 vs 1.06. SHORT tarafı felaket (Sharpe -0.8…-1.7). "
    "SONUÇ: 5 yıllık 1h 'kenarı' rejim artefaktı; trend takibi bu enstrümanlarda beta + DD "
    "zamanlaması, alfa değil."
)
