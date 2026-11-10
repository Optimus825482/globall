"""ÇAPRAZ VARLIK GECİKMESİ KOLU — dış seriden günlük yön (2026-11-10).

**DURUM: ELENDİ (2026-11-10).** İlk turda "günlük gecikme" sanılan sonuç, X'in de Y ile
AYNI gün penceresinde hesaplanmasından kaynaklanan **eşzamanlı korelasyondu** (ölçüm hatası).
Gerçek gecikmeyle yeniden ölçüldüğünde etki yok; saatlikte var ama maliyetin altında.
Bu dosya yalnız **negatif sonucun yeniden üretilebilir kaydı** için durur; `register_arm` YOK.

ESKİ (hatalı) not — kaynak: `docs/FX_YENI_SINYAL_AILESI_TUR2_2026-11-10.md`:
10 yıl, gecikmeli X (t−1), Y_{t−1} kontrollü kısmi korelasyon, maliyet düşülmüş, 24 saat tutuş:
  ^TNX → USDJPY : kısmi rho +0.094 (t=4.22) · net +4.29 p/gün · yarılar +2.24 / +6.33 ·
                  maliyet 2×'te +3.09 →
  ^GSPC → AUDUSD: kısmi rho +0.156 (t=7.05) · net +2.99 p/gün · yarılar +1.74 / +4.24 ·
                  maliyet 2×'te +1.99 →
PLASEBO ^FVX→EURUSD para KAYBEDİYOR (saatlik −1.82p, t=−6.89) → aile ayrıştırıcı.
DÜRÜST UYARI: X_{t−2} plasebosu da anlamlı (rho ~aynı) → etki tek günlük "lead" değil,
**çok günlük sürüklenme**dir; bu yüzden kol **günlük rebalans** olarak tasarlandı.
Saatlik sürümler maliyeti aşamadı (+0.23p, t=0.57) → kol SAATLİK DEĞİL, günlük çalışır.

SÖZLEŞME: +1/−1/0; `0` pozisyon kapatmaz; saf (ağ erişimi YOK — dış seri `ctx` ile gelir).
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Sequence

from app.arms.base import ArmSpec, SIGNAL_LONG, SIGNAL_NONE, SIGNAL_SHORT, register_arm

#: sembol → dış seri (Yahoo). Yön: dış seri ARTTIYSA sembol LONG (ölçülen işaret).
EXTERNAL: Dict[str, str] = {"AUDUSD": "^GSPC", "USDJPY": "^TNX"}

#: giriş günü = bir önceki günün dış-seri kapanış değişimi
LOOKBACK_DAYS = 1


def _date_of(ts: int, offset_h: int) -> dt.date:
    return (dt.datetime.fromtimestamp(int(ts), dt.timezone.utc) - dt.timedelta(hours=offset_h)).date()


def signal(bars: Sequence[Sequence[float]], symbol: str,
           ctx: Optional[Dict[str, Any]] = None) -> List[int]:
    """Bar serisi → sinyal. Dış seri `ctx["external"][yahoo_symbol]` (tarih → kapanış)."""
    sym = str(symbol).upper()
    ext_sym = EXTERNAL.get(sym)
    out: List[int] = [SIGNAL_NONE] * len(bars)
    if not ext_sym or not ctx:
        return out
    series = (ctx.get("external") or {}).get(ext_sym) or {}
    if not series:
        return out
    offset_h = int(ctx.get("offset_h", 2) or 0)
    # tarih → float
    closes: Dict[dt.date, float] = {}
    for k, v in series.items():
        try:
            closes[dt.date.fromisoformat(str(k))] = float(v)
        except Exception:  # noqa: BLE001
            continue
    days = sorted(closes)
    if len(days) < LOOKBACK_DAYS + 1:
        return out
    prev_of: Dict[dt.date, dt.date] = {b: a for a, b in zip(days, days[1:])}
    for i, bar in enumerate(bars):
        d = _date_of(int(bar[0]), offset_h)
        # bar günü D ise, D'den ÖNCEKİ dış-seri değişimi kullanılır (look-ahead yok)
        prior = [x for x in days if x < d]
        if len(prior) < 2:
            continue
        k, p = prior[-1], prior[-2]
        if not closes.get(p):
            continue
        r = closes[k] - closes[p]
        if r > 0:
            out[i] = SIGNAL_LONG
        elif r < 0:
            out[i] = SIGNAL_SHORT
    return out


#: KAYIT YOK — bu aile 2026-11-10'da ÖLÇÜMLE ELENDİ (aşağıdaki kanıt notu).
#: Dosya, ölçümü yeniden üretilebilir tutmak için saklanır; CANLIYA ALINMAZ.
EVIDENCE = (
    "GERÇEK GECİKME (düzeltilmiş): ^TNX→USDJPY günlük kısmi rho +0.025 (t=1.10), net -2.10 p/gün, "
    "yarılar -0.09 / -4.10 | ^GSPC→AUDUSD rho +0.027 (t=1.20), net -0.69, yarılar +0.92 / -2.30 | "
    "PLASEBO ^FVX→EURUSD rho +0.012 (t=0.52). Saatlikte gerçek gecikme VAR ama ekonomik değil: "
    "^GSPC→AUDUSD rho +0.251 (t=14.1) net +0.32p (t=1.61) < 1 pip maliyet; ^TNX→USDJPY rho +0.130 "
    "(t=7.18) net +0.23p (t=0.57). Arm A/B: -0.005R, PF 0.94, t=-2.09."
)
