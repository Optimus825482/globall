"""FX pariteleri arası dinamik korelasyon kalkanı (S6-FX).

EURUSD-GBPUSD gibi aynı dolar tezine oynayan pariteler tek pozisyon görünümündedir;
yüksek korelasyonlu aynı yönlü küme girişleri tek bir DXY/FAIZ kararına karşı
portföyün tamamını maruz bırakır. Bu modül, 5M kapanış serilerinden rolling
Pearson korelasyon matrisi üretir ve yeni girişleri küme kurallarına göre denetler:

- |ρ| >= 0.85 (aynı USD bias'ı) → doğrudan çakışma: yeni giriş ENGELLENİR
- 0.70 <= |ρ| < 0.85 (aynı USD bias'ı) → küme sayısı ``max_cluster``'ı aşarsa ENGELLENİR
- Negatif korelasyonlu çiftler (EURUSD-USDCHF ≈ -0.9) aynı USD bias'ını taşır →
  yukarıdaki kural bunları da yakalar (iki kapıdan aynı bahse girmeyi önler)
- Karşıt USD bias'ı = birbirini hedge eden pozisyonlardır → serbest

Saf ve bağımsız modüldür (import bağımlılığı yok); veri yoksa fail-open davranır.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple


class FXCorrelationMonitor:
    def __init__(self) -> None:
        self._corr: Dict[str, Dict[str, float]] = {}
        self._last_run = 0.0

    @property
    def last_updated(self) -> float:
        return self._last_run

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        return {sym: dict(info) for sym, info in self._corr.items()}

    def correlation_of(self, symbol_a: str, symbol_b: str) -> float:
        """İki sembol arasındaki Pearson korelasyonu; veri yoksa 0.0 (nötr, fail-open)."""
        info = self._corr.get(str(symbol_a).upper(), {})
        value = info.get(str(symbol_b).upper())
        return float(value) if value is not None else 0.0

    def refresh(self, closes_map: Dict[str, List[float]], lookback: int = 150) -> Dict[str, Any]:
        """5M kapanış serilerinden korelasyon matrisini yeniden hesaplar."""
        returns_map: Dict[str, List[float]] = {}
        for sym, closes in (closes_map or {}).items():
            if closes and len(closes) >= 60:
                returns_map[str(sym).upper()] = _returns(list(closes)[-lookback:])

        syms = list(returns_map)
        for i, a in enumerate(syms):
            for b in syms[i + 1:]:
                r = _pearson(returns_map[a], returns_map[b])
                self._corr.setdefault(a, {})[b] = r
                self._corr.setdefault(b, {})[a] = r

        # Artık veri gelmeyen sembolleri temizle
        stale = [s for s in self._corr if s not in returns_map]
        for s in stale:
            self._corr.pop(s, None)

        if syms:
            self._last_run = time.time()
        return {"ok": bool(syms), "symbols": len(syms), "updated_at": self._last_run}

    def maybe_refresh(self, closes_map: Dict[str, List[float]], interval_sec: int = 1800) -> Dict[str, Any]:
        """Yalnızca bayatladığında yeniler; aksi halde önbellek no-op."""
        if time.time() - self._last_run >= interval_sec:
            try:
                return self.refresh(closes_map)
            except Exception:
                return {"ok": False, "reason": "refresh_error"}
        return {"ok": True, "cached": True}

    def cluster_check(
        self,
        symbol: str,
        candidate_bias: str,
        positions_with_bias: List[Tuple[str, str]],
        max_cluster: int = 2,
        high: float = 0.85,
        medium: float = 0.70,
    ) -> Tuple[bool, str]:
        """Yeni giriş korelasyon denetimi.

        positions_with_bias: (sembol, usd_bias) tuple listesi — yalnızca adayla AYNI
        USD bias'ını taşıyan açık pozisyonlar/kuyruktaki emirler geçilmeli.

        Dönüş: (izinli_mi, gerekçe). Gerekçe formatı: "high_corr:<sembol>:<ρ>" veya
        "cluster:<semboller>".
        """
        same_bias_syms = [p_sym.upper() for p_sym, p_bias in (positions_with_bias or [])
                          if p_bias == candidate_bias and str(p_sym).upper() != str(symbol).upper()]
        if not same_bias_syms:
            return True, ""

        sym_u = str(symbol).upper()
        medium_cluster: List[str] = []
        for other in same_bias_syms:
            r = abs(self.correlation_of(sym_u, other))
            if r >= high:
                return False, f"high_corr:{other}:{r:.2f}"
            if r >= medium:
                medium_cluster.append(other)

        if len(medium_cluster) >= max(1, max_cluster):
            return False, f"cluster:{','.join(medium_cluster)}"
        return True, ""


def _returns(closes: List[float]) -> List[float]:
    """Bitişik kapanış çiftlerinden getiri serisi; sıfır tabanlı çiftler NaN işaretlenir."""
    return [float("nan") if closes[i - 1] == 0 else (closes[i] / closes[i - 1] - 1.0)
            for i in range(1, len(closes))]


def _pearson(xs: List[float], ys: List[float]) -> float:
    """NaN çiftleri aynı indekste maskeleyerek Pearson korelasyonu; incek veride 0.0 döner."""
    n = min(len(xs), len(ys))
    if n < 20:
        return 0.0
    pairs = [(x, y) for x, y in zip(xs[-n:], ys[-n:]) if not (math.isnan(x) or math.isnan(y))]
    if len(pairs) < 20:
        return 0.0
    px = [p[0] for p in pairs]
    py = [p[1] for p in pairs]
    m = len(pairs)
    mx = sum(px) / m
    my = sum(py) / m
    cov = sum((x - mx) * (y - my) for x, y in zip(px, py))
    vx = math.sqrt(sum((x - mx) ** 2 for x in px))
    vy = math.sqrt(sum((y - my) ** 2 for y in py))
    if vx == 0 or vy == 0:
        return 0.0
    return max(-1.0, min(1.0, cov / (vx * vy)))
