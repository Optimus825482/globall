"""SİNYAL KENARI — IC ve kuantil getiri ölçümü (2026-11-09)

NEDEN VAR (araştırma P2-14)
---------------------------
Sistemde `pattern_research.py`, `chat_pattern_replay.py`, `calibration.py` var ama
**standart bir sinyal-kalitesi ölçümü** yok: "sinyal gerçekten geleceği mi
anlatıyor, yoksa sıralaması anlamsız mı?" Bu modül üç temel soruyu yanıtlar:

1. **IC (Information Coefficient)** — sinyal sıralaması ile ileri getiri sıralaması
   arasındaki **Spearman** korelasyonu. 0.03-0.05 bile niceliksel finansta anlamlı
   sayılır; 0.00 ise sinyal bilgi taşımıyor.
2. **IC t-istatistiği** — IC'nin sıfırdan anlamlı uzaklığı (Fisher z yaklaşımı,
   `scipy` GEREKMEZ).
3. **Kuantil getiri** — sinyali 5 dilime bölüp her dilimin ortalama ileri getirisi;
   tekdüzelik (monotonluk) bozuksa sinyal "sıralama" olarak da işe yaramaz.

NEDEN `alphalens-reloaded` DEĞİL
--------------------------------
`alphalens` pandas + scipy ister; **üretim imajında ikisi de yok**
(`requirements.txt`: numpy + scikit-learn). Buradaki hesap saf numpy ile
yapılabilir (rank + Pearson) → bağımlılık eklenmedi. Ağır raporlama/tearsheet
gerekirse `alphalens` **araştırma katmanında** (`requirements-research.txt`)
ayrıca koşulabilir; kararı bu modül vermez.

DOĞRU KULLANIM (look-ahead yasak)
---------------------------------
`forward_returns`, sinyalin ÜRETİLDİĞİ andan SONRAKİ getiri olmalıdır. Sinyal ile
aynı bardaki getiriyi vermek yapay olarak mükemmel IC üretir. `align_forward_returns`
bu kaymayı doğru kurmak için var.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

#: "Anlamlı" kabul için kaba IC eşiği (niceliksel finansta yaygın kabul).
IC_MEANINGFUL = 0.03


def _as_1d(values: Sequence[float] | np.ndarray) -> np.ndarray:
    return np.asarray(values, dtype=float).ravel()


def _rankdata(a: np.ndarray) -> np.ndarray:
    """Sıra numaraları (eşitliklere ortalama sıra) — scipy.stats.rankdata eşdeğeri."""
    n = a.size
    if n == 0:
        return a
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    sorted_a = a[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-tabanlı ortalama sıra
        ranks[order[i:j + 1]] = avg
        i = j + 1
    return ranks


def _pearson(x: np.ndarray, y: np.ndarray) -> float | None:
    if x.size < 2 or y.size != x.size:
        return None
    xm, ym = x - x.mean(), y - y.mean()
    denom = math.sqrt(float((xm * xm).sum()) * float((ym * ym).sum()))
    if denom == 0:
        return None
    return float((xm * ym).sum() / denom)


def information_coefficient(signals: Sequence[float], forward_returns: Sequence[float]
                            ) -> float | None:
    """Spearman sıra korelasyonu (IC). NaN'lar çift olarak atılır.

    Döndürür: -1..1 ya da yetersiz/dejenere veride ``None``.
    """
    s = _as_1d(signals)
    r = _as_1d(forward_returns)
    n = min(s.size, r.size)
    if n == 0:
        return None
    s, r = s[:n], r[:n]
    mask = np.isfinite(s) & np.isfinite(r)
    s, r = s[mask], r[mask]
    if s.size < 3:
        return None
    return _pearson(_rankdata(s), _rankdata(r))


def ic_tstat(ic: float | None, n: int) -> dict[str, Any]:
    """Fisher z dönüşümüyle IC t-istatistiği (scipy gerekmez).

    ``SE ≈ 1/sqrt(n-3)``. |t| >= 1.96 → %95 güvenle sıfırdan farklı.
    """
    if ic is None or n < 4:
        return {"t": None, "p_approx": None, "significant": False}
    clipped = max(min(ic, 0.999999), -0.999999)
    z = math.atanh(clipped)
    se = 1.0 / math.sqrt(n - 3)
    t = z / se
    # Normal yaklaşımı (tek taraflı değil, iki taraflı): p ≈ 2*(1-Φ(|t|))
    p = math.erfc(abs(t) / math.sqrt(2.0))
    return {
        "t": round(t, 3),
        "p_approx": round(p, 5),
        "significant": abs(t) >= 1.96,
    }


def quantile_returns(signals: Sequence[float], forward_returns: Sequence[float],
                     n_quantiles: int = 5) -> list[dict[str, Any]]:
    """Sinyali dilimlere böl, her dilimin ortalama ileri getirisini ver.

    Tekdüze artan (Q1 < Q2 < ... < Qn) ise sinyal "sıralama" olarak çalışıyor.
    """
    s = _as_1d(signals)
    r = _as_1d(forward_returns)
    n = min(s.size, r.size)
    if n == 0:
        return []
    s, r = s[:n], r[:n]
    mask = np.isfinite(s) & np.isfinite(r)
    s, r = s[mask], r[mask]
    k = max(2, int(n_quantiles))
    if s.size < k * 2:
        return []
    order = np.argsort(s, kind="mergesort")
    s_sorted, r_sorted = s[order], r[order]
    rows = []
    for i in range(k):
        lo = int(round(i * s_sorted.size / k))
        hi = int(round((i + 1) * s_sorted.size / k))
        if hi <= lo:
            continue
        chunk = r_sorted[lo:hi]
        rows.append({
            "quantile": i + 1,
            "label": f"Q{i + 1}",
            "samples": int(chunk.size),
            "mean_return": round(float(chunk.mean()), 8),
            "hit_rate": round(float((chunk > 0).mean()), 4),
            "signal_lo": round(float(s_sorted[lo]), 6),
            "signal_hi": round(float(s_sorted[hi - 1]), 6),
        })
    return rows


def monotonicity(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Kuantil getirileri tekdüze mi? (Spearman: dilim sırası ↔ ortalama getiri)"""
    if len(rows) < 3:
        return {"spearman": None, "monotonic": False}
    q = np.array([r["quantile"] for r in rows], dtype=float)
    m = np.array([r["mean_return"] for r in rows], dtype=float)
    rho = _pearson(_rankdata(q), _rankdata(m))
    # %80 tekdüzelik: |rho| >= 0.8
    return {
        "spearman": None if rho is None else round(rho, 4),
        "monotonic": bool(rho is not None and abs(rho) >= 0.8),
    }


def align_forward_returns(prices: Sequence[float], signal_index: Sequence[int],
                          horizon: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Sinyal indekslerini ileri getiriyle hizala — LOOK-AHEAD KORUMASI.

    `signal_index[i]`, sinyalin üretildiği barın indeksidir. İleri getiri
    ``prices[j+horizon]/prices[j] - 1`` olarak hesaplanır ve **yalnızca
    j+horizon veri içindeyse** döndürülür. Aynı bardaki getiri ASLA kullanılmaz.
    """
    p = _as_1d(prices)
    valid_sig, valid_ret = [], []
    for idx in signal_index:
        try:
            j = int(idx)
        except (TypeError, ValueError):
            continue
        if j < 0 or j + horizon >= p.size:
            continue
        base, future = float(p[j]), float(p[j + horizon])
        if not (math.isfinite(base) and math.isfinite(future)) or base == 0:
            continue
        valid_sig.append(j)
        valid_ret.append(future / base - 1.0)
    return np.asarray(valid_sig, dtype=float), np.asarray(valid_ret, dtype=float)


def evaluate(signals: Sequence[float], forward_returns: Sequence[float],
             n_quantiles: int = 5) -> dict[str, Any]:
    """Tek çağrıda sinyal kalitesi raporu (IC + t + kuantiller + hüküm)."""
    s = _as_1d(signals)
    r = _as_1d(forward_returns)
    n = int(min(s.size, r.size))
    mask = np.isfinite(s[:n]) & np.isfinite(r[:n]) if n else np.array([], dtype=bool)
    n_used = int(mask.sum())
    ic = information_coefficient(s, r)
    tstat = ic_tstat(ic, n_used)
    rows = quantile_returns(s, r, n_quantiles)
    mono = monotonicity(rows)

    verdict = "KANIT YOK (IC anlamsız)"
    if ic is not None and tstat["significant"] and abs(ic) >= IC_MEANINGFUL:
        verdict = "SİNYAL BİLGİ TAŞIYOR" + (" (ters yön)" if ic < 0 else "")
    elif ic is not None and tstat["significant"]:
        verdict = "İSTATİSTİKSEL OLARAK ANLAMLI AMA ZAYIF (|IC| < 0.03)"

    return {
        "n": n_used,
        "ic": None if ic is None else round(ic, 5),
        "ic_tstat": tstat,
        "quantiles": rows,
        "monotonicity": mono,
        "verdict": verdict,
    }
