"""Karar desteği göstergeleri (LLM bağlamı): Bollinger, Keltner/TTM sıkışma, Supertrend, StochRSI, CCI, Donchian.

Seçim ölçütü (TradingView gösterge kataloğundan): yalnızca fiyat mumlarından (hacim gerektirmeden) hesaplanabilen, scalper karar
bağlamında rejim/aşırılık/kırılım bilgisi veren göstergeler. Hepsi saf fonksiyondur (test edilebilir); formüller TradingView
varsayılanlarıdır: Bollinger 20/2 (popülasyon sapması), Keltner EMA20 ± 1.5×ATR20 (TTM), Supertrend 10/3, StochRSI 14/14/3/3, CCI 20,
Donchian 20. Göstergeler tek başına işlem nedeni değildir; teyit/çelişki bilgisi olarak sunulur.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

Bar = Dict[str, float]
MIN_BARS = 60


def _dec(price: float) -> int:
    return 2 if price >= 100 else 4 if price >= 1 else 5


def _sma(xs: List[float], n: int) -> Optional[float]:
    return sum(xs[-n:]) / n if len(xs) >= n else None


def _ema_series(xs: List[float], n: int) -> List[float]:
    k = 2.0 / (n + 1.0)
    out = [xs[0]]
    for v in xs[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _true_ranges(bars: List[Bar]) -> List[float]:
    return [max(b["high"] - b["low"], abs(b["high"] - bars[i]["close"]), abs(b["low"] - bars[i]["close"]))
            for i, b in enumerate(bars[1:])]


def _rma_series(xs: List[float], n: int) -> List[float]:
    """Wilder yumuşatması (TradingView RMA); ilk değer ilk n elemanın ortalaması."""
    if len(xs) < n:
        return []
    out = [sum(xs[:n]) / n]
    for v in xs[n:]:
        out.append((out[-1] * (n - 1) + v) / n)
    return out


def bollinger(bars: List[Bar], n: int = 20, k: float = 2.0, lookback: int = 120) -> Dict[str, Any]:
    closes = [b["close"] for b in bars]
    if len(closes) < n + 5:
        return {}

    def at(end: int):
        w = closes[end - n:end]
        mid = sum(w) / n
        sd = math.sqrt(sum((c - mid) ** 2 for c in w) / n)          # popülasyon sapması (TradingView)
        return mid, sd

    mid, sd = at(len(closes))
    up, lo = mid + k * sd, mid - k * sd
    width = (up - lo) / mid * 100.0 if mid else 0.0
    widths = []
    for end in range(max(n, len(closes) - lookback), len(closes) + 1):
        m, s_ = at(end)
        if m:
            widths.append(2 * k * s_ / m * 100.0)
    pct_rank = sum(1 for w in widths if w <= width) / len(widths) if widths else None
    price = closes[-1]
    outside = 0
    for end in (len(closes), len(closes) - 1, len(closes) - 2):
        m, s_ = at(end)
        c = closes[end - 1]
        if c > m + k * s_:
            outside += 1
        elif c < m - k * s_:
            outside -= 1
        else:
            break
    d = _dec(price)
    return {"ust": round(up, d), "orta": round(mid, d), "alt": round(lo, d),
            "yuzde_b": round((price - lo) / (up - lo), 2) if up > lo else None,
            "genislik_yuzde": round(width, 3),
            "genislik_yuzdelik": round(pct_rank, 2) if pct_rank is not None else None,   # 0.1 = son 120 mumun en dar %10'u
            "sikisma": bool(pct_rank is not None and pct_rank <= 0.2),
            "bant_disi_mum": outside}          # +3 / -3: son 3 mum üst/alt bandın dışında kapandı (bant yürüyüşü)


def keltner_squeeze(bars: List[Bar], boll: Dict[str, Any], n: int = 20, mult: float = 1.5) -> Optional[bool]:
    """TTM sıkışma: Bollinger bantları Keltner kanalının İÇİNDE mi? (patlama öncesi düşük oynaklık)"""
    if not boll or len(bars) < n + 2:
        return None
    closes = [b["close"] for b in bars]
    trs = _true_ranges(bars)
    if len(trs) < n:
        return None
    atr = sum(trs[-n:]) / n
    mid = _ema_series(closes, n)[-1]
    return bool(boll["ust"] < mid + mult * atr and boll["alt"] > mid - mult * atr)


def supertrend(bars: List[Bar], n: int = 10, mult: float = 3.0) -> Dict[str, Any]:
    if len(bars) < n + 5:
        return {}
    trs = _true_ranges(bars)
    atr = _rma_series(trs, n)
    if not atr:
        return {}
    offset = len(bars) - len(atr)                      # atr[i] ↔ bars[offset + i]
    f_up = f_lo = None
    direction = 1
    flipped_at = offset
    level = None
    for i, a in enumerate(atr):
        b = bars[offset + i]
        hl2 = (b["high"] + b["low"]) / 2.0
        up, lo = hl2 + mult * a, hl2 - mult * a
        prev_close = bars[offset + i - 1]["close"]
        if f_up is None:
            f_up, f_lo = up, lo
        else:
            f_up = up if (up < f_up or prev_close > f_up) else f_up
            f_lo = lo if (lo > f_lo or prev_close < f_lo) else f_lo
        new_dir = direction
        if b["close"] > f_up:
            new_dir = 1
        elif b["close"] < f_lo:
            new_dir = -1
        if new_dir != direction:
            direction, flipped_at = new_dir, offset + i
        level = f_lo if direction == 1 else f_up
    price = bars[-1]["close"]
    return {"yon": "yukari" if direction == 1 else "asagi", "seviye": round(level, _dec(price)),
            "kac_mum_once_dondu": len(bars) - 1 - flipped_at}


def stoch_rsi(closes: List[float], rsi_n: int = 14, stoch_n: int = 14, k_n: int = 3, d_n: int = 3) -> Dict[str, Any]:
    if len(closes) < rsi_n + stoch_n + k_n + d_n + 5:
        return {}
    gains = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    losses = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    ag, al = _rma_series(gains, rsi_n), _rma_series(losses, rsi_n)
    rsi = [100.0 if l == 0 else 100.0 - 100.0 / (1.0 + g / l) for g, l in zip(ag, al)]
    st = []
    for i in range(stoch_n - 1, len(rsi)):
        w = rsi[i - stoch_n + 1:i + 1]
        hi, lo = max(w), min(w)
        st.append((rsi[i] - lo) / (hi - lo) * 100.0 if hi > lo else 50.0)
    ks = [sum(st[i - k_n + 1:i + 1]) / k_n for i in range(k_n - 1, len(st))]
    ds = [sum(ks[i - d_n + 1:i + 1]) / d_n for i in range(d_n - 1, len(ks))]
    if not ks or not ds:
        return {}
    k, d_ = ks[-1], ds[-1]
    zone = "asiri_alim" if k >= 80 else "asiri_satim" if k <= 20 else "orta"
    return {"k": round(k, 1), "d": round(d_, 1), "bolge": zone}


def cci(bars: List[Bar], n: int = 20) -> Optional[float]:
    if len(bars) < n + 1:
        return None
    tp = [(b["high"] + b["low"] + b["close"]) / 3.0 for b in bars[-n:]]
    m = sum(tp) / n
    md = sum(abs(x - m) for x in tp) / n
    return round((tp[-1] - m) / (0.015 * md), 1) if md > 0 else 0.0


def donchian(bars: List[Bar], n: int = 20) -> Dict[str, Any]:
    if len(bars) < n:
        return {}
    w = bars[-n:]
    hi, lo = max(b["high"] for b in w), min(b["low"] for b in w)
    price = bars[-1]["close"]
    d = _dec(price)
    return {"ust": round(hi, d), "alt": round(lo, d), "konum_yuzde": round((price - lo) / (hi - lo) * 100.0, 0) if hi > lo else None}


def pack(bars: List[Bar]) -> Dict[str, Any]:
    """Bir zaman dilimi için LLM'e gidecek gösterge paketi; veri yetersizse {}."""
    if len(bars) < MIN_BARS:
        return {}
    closes = [b["close"] for b in bars]
    boll = bollinger(bars)
    out: Dict[str, Any] = {"bollinger": boll, "bb_keltner_sikisma": keltner_squeeze(bars, boll),
                           "supertrend": supertrend(bars), "stoch_rsi": stoch_rsi(closes), "cci20": cci(bars),
                           "donchian20": donchian(bars)}
    return {k: v for k, v in out.items() if v not in ({}, None)}
