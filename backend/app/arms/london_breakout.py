"""LONDON BREAKOUT KOLU (2026-11-12) — maliyet+saat düzeltmesinden sonra terfi adayı.

**DURUM: TERFİ EDİLMEDİ (signal-level kenar YOK) — dosya ölçüm artefaktı olarak duruyor.**

Replay (motorun tam çıkış yığınıyla) PF 1,73/1,59 veriyordu; **bağımsız kol ölçümü
bunu doğrulamadı**: 2 yıl 5m, 1.499 işlem, beklenti **+0,008R (t=0,31)**, PF 1,16.
t≈0 → kenar sıfırdan ayırt edilemiyor. AUDUSD anlamlı NEGATİF (−0,136R, t=−2,20).

**Ders:** replay'in kârı **motorun çıkış/kapı yığınından** (BE `cost+1`, chandelier,
EV kalkanı, seans kapıları, risk normalizasyonu) geliyor, kırılım sinyalinin
kendisinden değil. Bu kol tek başına canlıya alınmaz; doğru yol **motor içinde
gölge** (çıkışlar orada var), kol dosyası olarak terfi değil.

KURAL (Asya kutusu kırılımı)
----------------------------
1. Günün **Asya aralığı** (00:00–`BOX_END_H` UTC) → kutu yüksek/düşük.
2. `BOX_END_H` … `ENTRY_END_H` (07:00–11:00 UTC) arasında kapanış kutunun
   üstünü aşarsa **+1**, altını kırarsa **−1**.
3. **Gün+yön başına tek giriş** (`0` kapatmaz; çıkış ayrı katman).

KANIT — MOTOR SEVİYESİ (2026-11-12, `docs/GIRIS_MODU_YENIDEN_TARAMA_2026-11-12.md`)
-----------------------------------------------------------------
Düzeltilmiş ayar = ölçülen saatlik spread + `--bar-tz-offset 2`:

| Pencere | PF | Net | İşlem |
|---|---|---|---|
| IS (son 30 gün) | **1,73** | +5.834 $ | 246 |
| OOS (önceki 30 gün) | **1,59** | +3.959 $ | 217 |
| 2× maliyet IS | **1,69** | +5.526 $ | 246 |
| 2× maliyet OOS | **1,54** | +3.668 $ | 217 |

Sembol katkısı (IS, $): GBPUSD +3.017 · AUDUSD +1.831 · XAUUSD +670 · US30 +657 ·
NAS100 +298 · EURJPY +52 · BTCUSD +52 · GBPJPY +19 | negatif: USDCHF −327 · USDJPY −340.
Kol yalnız **pozitif katkılı** sembolleri bildirir.

DÜRÜSTLÜK NOTLARI
-----------------
* İsabet oranı %75-96 görünüyor ama bunlar **BE (break-even) çıkışları**; ortalama
  kazanç küçük. PF'e bak, isabet yüzdesine değil.
* 2× maliyet testi geçti (kill kriteri PF ≥ 1,1) — **iki pencerede de**.
* SAAT DİLİMİ: MT5 barları broker saatinde (UTC+2). Kol, `ctx["offset_h"]` ile
  düzeltir; harness offset vermezse varsayılan 2 kullanılır. Düzeltme olmadan
  kutu sınırı 2 saat kayar ve kural başka bir strateji olur.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import List, Optional, Sequence

from app.arms.base import ArmSpec, SIGNAL_LONG, SIGNAL_NONE, SIGNAL_SHORT, register_arm

#: Kutu bitiş saati (UTC) — Asya aralığı 00:00…bu saat
BOX_END_H = int(os.getenv("LB_BOX_END_H", "7"))
#: Tetik penceresi bitişi (UTC) — bu saatten sonra yeni giriş yok
ENTRY_END_H = int(os.getenv("LB_ENTRY_END_H", "11"))
#: Broker saat ofseti (saat) — bar damgasını UTC'ye çevirir
DEFAULT_OFFSET_H = int(os.getenv("LB_BAR_TZ_OFFSET", "2"))

#: Semboller: replay ölçümünde POZİTİF katkı verenler (n>15)
SYMBOLS: List[str] = ["GBPUSD", "AUDUSD", "XAUUSD", "US30", "NAS100"]


def _hour_utc(ts: float, offset_h: int) -> int:
    return dt.datetime.fromtimestamp(float(ts) - offset_h * 3600, dt.timezone.utc).hour


def signal(bars: Sequence[Sequence[float]], symbol: str,
           ctx: Optional[dict] = None) -> List[int]:
    """Asya kutusu kırılımı → +1/−1, gün+yön başına bir kez. `0` kapatmaz."""
    sym = str(symbol).upper()
    out: List[int] = [SIGNAL_NONE] * len(bars)
    if sym not in SYMBOLS or not bars:
        return out
    offset_h = int((ctx or {}).get("offset_h", DEFAULT_OFFSET_H) or 0)

    # Gün → (kutu_hi, kutu_lo). Kutu, günün BOX_END_H'ten ÖNCEKİ barlarından.
    boxes: dict[int, list[float]] = {}
    for b in bars:
        ts = float(b[0])
        t = dt.datetime.fromtimestamp(ts - offset_h * 3600, dt.timezone.utc)
        day = (int(ts) - offset_h * 3600) // 86400
        if t.hour >= BOX_END_H:
            continue
        box = boxes.get(day)
        if box is None:
            boxes[day] = [float(b[2]), float(b[3])]     # hi, lo
        else:
            if float(b[2]) > box[0]:
                box[0] = float(b[2])
            if float(b[3]) < box[1]:
                box[1] = float(b[3])

    fired: set[tuple[int, int]] = set()
    for i, b in enumerate(bars):
        ts = float(b[0])
        t = dt.datetime.fromtimestamp(ts - offset_h * 3600, dt.timezone.utc)
        if t.weekday() >= 5:
            continue
        if not (BOX_END_H <= t.hour < ENTRY_END_H):
            continue
        day = (int(ts) - offset_h * 3600) // 86400
        box = boxes.get(day)
        if not box:
            continue
        hi, lo = box
        if hi <= lo:
            continue
        close = float(b[4])
        if close > hi and (day, SIGNAL_LONG) not in fired:
            fired.add((day, SIGNAL_LONG))
            out[i] = SIGNAL_LONG
        elif close < lo and (day, SIGNAL_SHORT) not in fired:
            fired.add((day, SIGNAL_SHORT))
            out[i] = SIGNAL_SHORT
    return out


register_arm(ArmSpec(
    name="london_breakout",
    description=(
        "Asya kutusu kırılımı: 00:00-07:00 UTC aralığının dışına kapanış → o yönde "
        "giriş (07:00-11:00 UTC penceresi, gün+yön başına bir kez)."
    ),
    timeframe="5m",
    symbols=SYMBOLS,
    handler=signal,
    evidence=(
        "MOTOR: IS PF 1,73 / OOS 1,59 / 2× maliyet 1,69-1,54 (kill kriteri geçildi). "
        "BAĞIMSIZ KOL (2y 5m, harness çıkışları): n=1499, beklenti +0,008R t=0,31, "
        "PF 1,16 → SİNYAL KENARI YOK; kâr motorun çıkış yığınından. AUDUSD −0,136R t=−2,20. "
        "SONUÇ: terfi edilmedi; motor içi gölge ile ölçülmeli."
    ),
    tags=["breakout", "session", "fx"],
))
