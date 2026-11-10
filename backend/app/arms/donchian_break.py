"""DONCHIAN KIRILIMI KOLU (2026-11-10) — vectorbt taramasından gelen aday.

**DURUM: ELENDİ (2026-11-10).** 5 yıl 1h'te iyi görünen sonuç **10 yıllık günlükte
tutmadı** (buy&hold'un altında) ve short tarafı felaket → kayıtlı DEĞİL, canlıya alınmaz.

KAYNAK: `docs/VBT_STRATEJI_TARAMASI_2026-11-10.md`. 5 yıl, 1h, IS %70 / OOS %30, ölçülen maliyet,
sinyal 1 bar geciktirilmiş. **Komşu parametre kararlılığı 6/6** (şanslı hücre değil):
  XAUUSD 1h: n=10/15/20/25/30/40 → OOS Sharpe 1.71 / 1.65 / 1.58 / 1.19 / 1.17 / 1.00
  USDJPY 1h: n=10/15/20/25/30/40 → OOS Sharpe 1.57 / 1.54 / 0.78 / 0.73 / 0.76 / 0.47
Çıkış: karşıt bant (Donchian alt/üst) → sözleşmede −1 sinyali ("0 kapatmaz" kuralı korunur).
"""
from __future__ import annotations

from typing import List, Sequence

from app.arms.base import ArmSpec, SIGNAL_LONG, SIGNAL_NONE, SIGNAL_SHORT, register_arm

#: sembol → kırılım penceresi (vbt taramasında en kararlı hücre)
PARAMS = {"XAUUSD": 15, "USDJPY": 10}


def signal(bars: Sequence[Sequence[float]], symbol: str) -> List[int]:
    """Donchian kırılımı: kapanış önceki n barın zirvesini aşarsa +1, dibini kırarsa −1."""
    sym = str(symbol).upper()
    n = PARAMS.get(sym)
    out: List[int] = [SIGNAL_NONE] * len(bars)
    if not n or len(bars) <= n:
        return out
    for i in range(n, len(bars)):
        window = bars[i - n:i]
        hi = max(b[2] for b in window)
        lo = min(b[3] for b in window)
        close = bars[i][4]
        if close > hi:
            out[i] = SIGNAL_LONG
        elif close < lo:
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
