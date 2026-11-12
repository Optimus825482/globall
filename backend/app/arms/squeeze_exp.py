"""SIKIŞMA-GENİŞLEME KOLU (squeeze_exp) — 2026-11-12

**DURUM: ELENDİ (sinyal-seviyesi NEGATİF) — canlıya ALINMADI.**

Motor replay'i üç kapıyı geçmişti (IS 1,28 · OOS 1,24 · 2× maliyet 1,16/1,12), AMA
**bağımsız kol ölçümü bunu çürüttü**: 2 yıl 5m, **4.413 işlem, beklenti −0,039R,
t=−2,35** (anlamlı NEGATİF), PF 0,97. Yani replay kârı **motorun çıkış yığınından**
geliyordu (london_breakout dersinin daha keskin hâli: orada t≈0, burada t=−2,35).
Sembol kırılımı: yalnız USDCHF pozitif (+0,121R, t=1,91); UK100/US2000/EURJPY
anlamlı negatif.

**Sonuç:** sinyal olarak kullanılmaz. Dosya, ölçümü yeniden üretilebilir tutmak için
kayıtlı duruyor.

KURAL (replay `TUN_ENTRY_MODE == "squeeze_exp"` ile birebir)
-----------------------------------------------------------
1. **15m SIKIŞMA**: son tamamlanan 15m kovasında ATR(14)% ve Bollinger bant genişliği
   (20, 2σ), son 200 değerin **≤ %20 persentilinde** olmalı (ikisi de).
2. **5m GENİŞLEME BARI**: kapanış önceki 5m barın aralığının dışında VE gövde üst/alt
   üçte birlik dilimde (kapanış güçlü tarafta).
3. **YÖN**: H1 EMA200 trendi yukarıysa yalnız AL, aşağıysa yalnız SAT; trend yataysa
   barın kendi yönü kabul.
4. **Sınır**: gün + yön başına en çok 2 giriş.

ÇIKIŞ (replay'de): SL 1,5×ATR(5m) · TP 3,0×ATR → R:R 2,0.
Kol ölçümünde harness çıkışları kullanılır (`--hold-bars 6 --tp-r 2.0`).
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from app.arms.base import ArmSpec, SIGNAL_LONG, SIGNAL_NONE, SIGNAL_SHORT, register_arm

COMP_PCT = 20.0          # sıkışma persentili (ATR% ve BBW)
WINDOW = 200             # persentil penceresi (15m bar)
MAX_PER_DAY = 2          # gün + yön başına giriş
SYMBOLS: List[str] = [
    "XAUUSD", "BTCUSD", "US30", "NAS100", "GBPUSD", "AUDUSD", "USDJPY",
    "USDCHF", "EURJPY", "GBPJPY", "AUDCAD", "JP225", "US2000", "UK100",
]


def _resample(bars: Sequence[Sequence[float]], secs: int) -> List[dict]:
    """5m barları `secs` saniyelik kovalara indirger (kapanmış kovalar)."""
    out: List[dict] = []
    cur_key: Optional[int] = None
    cur = None
    for b in bars:
        ts = int(b[0])
        key = ts // secs
        if key != cur_key:
            if cur is not None:
                out.append(cur)
            cur_key = key
            cur = {"ts": ts, "o": float(b[1]), "h": float(b[2]),
                   "l": float(b[3]), "c": float(b[4])}
        else:
            cur["h"] = max(cur["h"], float(b[2]))
            cur["l"] = min(cur["l"], float(b[3]))
            cur["c"] = float(b[4])
    return out


def _atr(bars: List[dict], n: int = 14) -> List[float]:
    trs, out = [], []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b["h"] - b["l"])
        else:
            pc = bars[i - 1]["c"]
            trs.append(max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)))
        out.append(sum(trs[-n:]) / min(n, len(trs)))
    return out


def _bbw(bars: List[dict], n: int = 20, k: float = 2.0) -> List[float]:
    out = []
    for i in range(len(bars)):
        seg = bars[max(0, i - n + 1):i + 1]
        if len(seg) < n:
            out.append(0.0)
            continue
        cl = [x["c"] for x in seg]
        m = sum(cl) / len(cl)
        sd = (sum((x - m) ** 2 for x in cl) / len(cl)) ** 0.5
        out.append((2.0 * k * sd) / m * 100.0 if m > 0 else 0.0)
    return out


def _ema_last(vals: List[float], n: int) -> float:
    if not vals:
        return 0.0
    a = 2.0 / (n + 1)
    v = vals[0]
    for x in vals[1:]:
        v = a * x + (1 - a) * v
    return v


def _rank_pct(series: List[float], i: int, window: int = WINDOW) -> float:
    seg = [x for x in series[max(0, i - window + 1):i + 1] if x > 0]
    if len(seg) < 50:
        return 100.0
    cur = series[i]
    if cur <= 0:
        return 100.0
    return 100.0 * sum(1 for x in seg if x <= cur) / len(seg)


def signal(bars: Sequence[Sequence[float]], symbol: str,
           ctx: Optional[dict] = None) -> List[int]:
    sym = str(symbol).upper()
    out: List[int] = [SIGNAL_NONE] * len(bars)
    if sym not in SYMBOLS or len(bars) < 200:
        return out

    m15 = _resample(bars, 900)
    if len(m15) < 60:
        return out
    atr15, bbw15 = _atr(m15, 14), _bbw(m15, 20)
    # 15m kova → 15m seri indeksi (O(1) arama; iç tarama O(n^2) idi)
    idx15_by_key: dict[int, int] = {int(x["ts"]) // 900: j for j, x in enumerate(m15)}

    # H1 EMA200 trend (her saat için son değer)
    m60 = _resample(bars, 3600)
    h1_trend: dict[int, float] = {}
    closes60: List[float] = []
    for hb in m60:
        closes60.append(hb["c"])
        hour_key = int(hb["ts"]) // 3600
        e200 = _ema_last(closes60[-400:], 200) if len(closes60) >= 200 else 0.0
        h1_trend[hour_key] = 0 if e200 <= 0 else (1 if hb["c"] > e200 else -1)

    fired: set[tuple[int, int]] = set()
    for i in range(60, len(bars)):
        b = bars[i]
        pb = bars[i - 1]
        key15 = int(b[0]) // 900
        # son TAMAMLANMIŞ 15m kova: bu barın kovası DEĞİL (sıkışma önce oluşur)
        prev_key = key15 - 1
        idx15 = idx15_by_key.get(prev_key)
        if idx15 is None or idx15 < 50:
            continue
        if _rank_pct(atr15, idx15) > COMP_PCT or _rank_pct(bbw15, idx15) > COMP_PCT:
            continue
        c, o, h, l = float(b[4]), float(b[1]), float(b[2]), float(b[3])
        rng = h - l
        if rng <= 0:
            continue
        h1s = h1_trend.get(int(b[0]) // 3600, 0)
        up = c > float(pb[2]) and (c - l) / rng >= 0.66 and h1s >= 0
        dn = c < float(pb[3]) and (h - c) / rng >= 0.66 and h1s <= 0
        day = int(b[0]) // 86400
        if up and (day, SIGNAL_LONG) not in fired:
            if sum(1 for d, s in fired if d == day and s == SIGNAL_LONG) >= MAX_PER_DAY:
                continue
            fired.add((day, SIGNAL_LONG))
            out[i] = SIGNAL_LONG
        elif dn and (day, SIGNAL_SHORT) not in fired:
            if sum(1 for d, s in fired if d == day and s == SIGNAL_SHORT) >= MAX_PER_DAY:
                continue
            fired.add((day, SIGNAL_SHORT))
            out[i] = SIGNAL_SHORT
    return out


EVIDENCE = (
    "MOTOR: IS PF 1,28 (n=318) · OOS 1,24 (n=280) · 2× maliyet 1,16/1,12. "
    "SİNYAL (bağımsız kol, 2y 5m): n=4413, beklenti −0,039R, t=−2,35, PF 0,97 → "
    "ANLAMLI NEGATİF. Replay kârı motorun çıkış yığınından; kol olarak ELENDİ "
    "(canlıya alınmaz). Yalnız USDCHF pozitif (+0,121R t=1,91)."
)


register_arm(ArmSpec(
    name="squeeze_exp",
    description=("15m sıkışma (ATR% ve BBW ≤ %20 persentil) → 5m genişleme barı; "
                 "yön H1 EMA200 tarafından. Gün+yön başına en çok 2 giriş."),
    timeframe="5m",
    symbols=SYMBOLS,
    handler=signal,
    evidence=EVIDENCE,
    tags=["squeeze", "breakout", "fx", "candidate"],
))
