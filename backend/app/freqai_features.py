"""FreqAI & TradeMaster İlhamlı Adaptif Öznitelik Mühendisliği ve Piyasa Rejimi Tespiti.

Bu modül, zaman serisi verilerinden oynaklık genişlemesi, trend sürekliliği (persistence),
hacim patlama katsayısı ve mikro-yapı rejimini (TRENDING, RANGE, PANIC) deterministik
olarak hesaplar.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def compute_adaptive_regime_features(
    closes: List[float],
    highs: Optional[List[float]] = None,
    lows: Optional[List[float]] = None,
    vols: Optional[List[float]] = None,
    n_period: int = 20,
) -> Dict[str, Any]:
    """Zaman serisinden FreqAI tarzı adaptif rejim ve momentum göstergeleri türetir."""
    if not closes or len(closes) < 5:
        return {
            "regime_class": "RANGE",
            "regime_confidence": 50,
            "vol_spike_ratio": 1.0,
            "rolling_volatility_pct": 0.0,
            "trend_persistence_ratio": 0.5,
            "momentum_atr_ratio": 0.0,
        }

    c = [float(x) for x in closes]
    n = len(c)
    p = min(n, n_period)

    # 1. Rolling Volatility (%)
    window_c = c[-p:]
    mean_c = sum(window_c) / p
    var_c = sum((x - mean_c) ** 2 for x in window_c) / p
    std_c = math.sqrt(max(var_c, 1e-12))
    rolling_vol_pct = (std_c / mean_c * 100.0) if mean_c > 0 else 0.0

    # 2. Trend Persistence (Son barlarda kaç tanesi pozitif kapattı?)
    pos_bars = 0
    total_bars = min(n - 1, 10)
    for i in range(1, total_bars + 1):
        if c[-i] > c[-i - 1]:
            pos_bars += 1
    persistence_ratio = round(pos_bars / total_bars, 2) if total_bars > 0 else 0.5

    # 3. Volume Spike Ratio
    vol_spike = 1.0
    if vols and len(vols) >= 5:
        v = [float(x) for x in vols]
        v_win = v[-p:]
        v_mean = sum(v_win[:-1]) / max(len(v_win) - 1, 1)
        if v_mean > 0:
            vol_spike = round(v[-1] / v_mean, 2)

    # 4. ATR Normalize Momentum
    atr = None
    if highs and lows and len(highs) >= 5 and len(lows) >= 5:
        h = [float(x) for x in highs]
        l = [float(x) for x in lows]
        tr_list = []
        for i in range(1, min(len(c), 15)):
            tr = max(h[-i] - l[-i], abs(h[-i] - c[-i - 1]), abs(l[-i] - c[-i - 1]))
            tr_list.append(tr)
        if tr_list:
            atr = sum(tr_list) / len(tr_list)

    mom_atr_ratio = 0.0
    if atr and atr > 0:
        ret_val = c[-1] - c[-min(5, n)]
        mom_atr_ratio = round(ret_val / atr, 2)

    # 5. Deterministik Rejim Sınıflandırması (FreqAI & TradeMaster Kuralı)
    # PANIC: Anormal yüksek oynaklık + yüksek hacim patlaması + sert düşüş
    if rolling_vol_pct > 3.0 and vol_spike > 2.0 and persistence_ratio <= 0.2:
        regime = "PANIC"
        confidence = min(95, int(70 + (rolling_vol_pct * 5)))
    # TRENDING: Yüksek persistence (>= 0.70) veya güçlü yönlü ivme + hacim desteği
    elif (persistence_ratio >= 0.7 or persistence_ratio <= 0.3) and rolling_vol_pct >= 0.8:
        regime = "TRENDING"
        confidence = min(95, int(65 + (abs(persistence_ratio - 0.5) * 60)))
    # RANGE: Düşük oynaklık ve yön belirsizliği
    else:
        regime = "RANGE"
        confidence = min(90, int(60 + (1.0 - abs(persistence_ratio - 0.5)) * 30))

    return {
        "regime_class": regime,
        "regime_confidence": confidence,
        "vol_spike_ratio": vol_spike,
        "rolling_volatility_pct": round(rolling_vol_pct, 2),
        "trend_persistence_ratio": persistence_ratio,
        "momentum_atr_ratio": mom_atr_ratio,
    }
