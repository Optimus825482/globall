"""IBS + RSI(21) MEAN-REVERSION KOLU (2026-11-10) — vbt taramasında PLATO bulan aday.

KAYNAK: `docs/VBT_STRATEJI_TARAMASI_2026-11-10.md` §6. 10 yıl GÜNLÜK, IS %70 / OOS %30,
ölçülen maliyet, sinyal 1 bar geciktirilmiş. Hücre ızgarası (IBS eşiği × RSI eşiği):

| sembol | pozitif hücre | OOS Sharpe medyanı |
|---|---|---|
| BTCUSD | **18/19** | 0.65 |
| EURUSD | **16/20** | 0.75 |
| GBPUSD | **15/15** | 0.87 |
| AUDUSD | **15/15** | 1.03 |
| XAUUSD | 9/15 | 0.98 |
| USDJPY / USDCHF | 3/20 · 0/20 | negatif (KAPSAM DIŞI) |

**DÜZELTME (2026-11-10, aynı gün):** yukarıdaki tablo **yalnız OOS** (son %30) penceresidir. TAM 10 yılda
EURUSD/GBPUSD Sharpe **0.15** (PF 1.08) → FX majörleri elenir; **XAUUSD 1.14 / PF 2.01** ve BTCUSD 0.62
ayakta kalır. Ayrıca **dolum zamanı** sonucu değiştiriyor (kapanış vs sonraki açılış: XAU PF 2.01 → 0.59);
tick ile doğrulanmadan canlıya alınmaz. Kapsam bu yüzden yalnız XAUUSD + BTCUSD.

Yani tek hücre şansı değil, **geniş parametre platosu** — ve dikkat: platonun olduğu yerler
**FX majörleri** (intraday RADAR'ın kenarı olmadığı yer).

KURAL: `IBS = (C−L)/(H−L) < eşik` **ve** `RSI(21) < eşik` → gün kapanışında LONG (+1).
Çıkış: `kapanış > önceki kapanış` → −1 (sözleşmede "0 kapatmaz", −1 kapatır).
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from app.arms.base import ArmSpec, SIGNAL_LONG, SIGNAL_NONE, SIGNAL_SHORT, register_arm

#: sembol → (IBS eşiği, RSI(21) eşiği) — vbt ızgarasında platonun ortası
PARAMS: Dict[str, Tuple[float, float]] = {
    "XAUUSD": (0.25, 45.0),
    "BTCUSD": (0.25, 45.0),
}
RSI_LEN = 21


def _rsi(closes: Sequence[float], length: int) -> List[float]:
    """Wilder RSI (saf python; bar listesi üzerinde)."""
    out = [float("nan")] * len(closes)
    if len(closes) <= length:
        return out
    gains = losses = 0.0
    for i in range(1, length + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / length, losses / length
    out[length] = 100.0 - 100.0 / (1.0 + ag / al) if al > 0 else 100.0
    for i in range(length + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (length - 1) + max(d, 0.0)) / length
        al = (al * (length - 1) + max(-d, 0.0)) / length
        out[i] = 100.0 - 100.0 / (1.0 + ag / al) if al > 0 else 100.0
    return out


def signal(bars: Sequence[Sequence[float]], symbol: str) -> List[int]:
    """Giriş: IBS < eşik ve RSI(21) < eşik → +1. Çıkış: kapanış > önceki kapanış → −1."""
    sym = str(symbol).upper()
    p = PARAMS.get(sym)
    n = len(bars)
    out: List[int] = [SIGNAL_NONE] * n
    if not p or n < RSI_LEN + 5:
        return out
    ibs_max, rsi_max = p
    closes = [float(b[4]) for b in bars]
    rsi = _rsi(closes, RSI_LEN)
    for i in range(RSI_LEN + 1, n):
        h, l, c = float(bars[i][2]), float(bars[i][3]), closes[i]
        rng = h - l
        ibs = (c - l) / rng if rng > 0 else 0.5
        r = rsi[i]
        if r == r and ibs < ibs_max and r < rsi_max:
            out[i] = SIGNAL_LONG
        elif c > closes[i - 1]:
            out[i] = SIGNAL_SHORT        # çıkış sinyali (long-only kolda kapatır)
    return out


#: KAYIT YOK — kanıt ÇELİŞKİLİ (dolum zamanı sonucun işaretini değiştiriyor). Tick ile
#: doğrulanana kadar canlıya alınmaz; dosya ölçümün yeniden üretilebilir kaydıdır.
EVIDENCE_DETAIL = (
    "XAUUSD 10y tam örneklem: kapanış dolumu PF 2.01 / Sharpe 1.14 / 145 işlem; "
    "sonraki-bar-açılış dolumu (bizim muhafazakâr backtester) PF 0.59 / negatif beklenti. "
    "BTCUSD: 1.37 vs 0.90. Fark gecelik boşluk kaynaklı → SIRADAKİ TEST: bu 145 günün tick'ini "
    "çekip kapanış dolumunun gerçekten mümkün olduğunu ölçmek."
)
