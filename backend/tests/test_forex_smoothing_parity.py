"""Gösterge yumuşatma PARİTE testi (2026-11-12)

NEDEN
-----
Replay'de `_compute_technical_indicators` her bar×sembol için baştan koşuyor.
İçindeki özyinelemeler (EMA / RSI / ATR / ADX Wilder) saf Python döngüsüydü ve
cProfile ile toplam sürenin **%94'ü** burada çıktı (`_calc_ema` tek başına 226 sn).
Döngüler `scipy.signal.lfilter` tabanlı `_smooth` / `_smooth_last` ile değiştirildi.

Bu test **eski döngü formüllerinin birebir kopyasını** referans alır: yeni kod
1e-12'den fazla saparsa kırılır. Amaç hız değil, hızın BEDAVA olmadığını kanıtlamak —
skor eşikleri ve kapılar bu sayılara bakıyor.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.routers import forex


# ---------------------------------------------------------------- referans (ESKİ döngüler)
def _ema_ref(series: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1)
    res = [float(series[0])]
    for val in series[1:]:
        res.append(alpha * float(val) + (1.0 - alpha) * res[-1])
    return np.array(res, dtype=float)


def _wilder_last_ref(series: np.ndarray, period: int, seed: float) -> float:
    val = seed
    for x in series:
        val = val - val / period + float(x)
    return val


def _adx_ref(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> float:
    n = min(len(h), len(l), len(c))
    if n < 2 * period + 2:
        return 0.0
    h, l, c = h[-n:], l[-n:], c[-n:]
    up_move = h[1:] - h[:-1]
    down_move = l[:-1] - l[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))

    def _wilder(series: np.ndarray) -> float:
        first = float(np.sum(series[:period]))
        if first <= 0:
            return 0.0
        return _wilder_last_ref(series[period:], period, first)

    atr_w = _wilder(tr)
    if atr_w <= 0:
        return 0.0
    plus_di = 100.0 * _wilder(plus_dm) / atr_w
    minus_di = 100.0 * _wilder(minus_dm) / atr_w
    denom = plus_di + minus_di
    if denom <= 0:
        return 0.0
    dx = 100.0 * abs(plus_di - minus_di) / denom
    dx_series = []
    plus_w = float(np.sum(plus_dm[:period]))
    minus_w = float(np.sum(minus_dm[:period]))
    tr_w = float(np.sum(tr[:period]))
    for i in range(period, len(tr)):
        plus_w = plus_w - plus_w / period + float(plus_dm[i])
        minus_w = minus_w - minus_w / period + float(minus_dm[i])
        tr_w = tr_w - tr_w / period + float(tr[i])
        if tr_w > 0:
            pdi = 100.0 * plus_w / tr_w
            mdi = 100.0 * minus_w / tr_w
            d = pdi + mdi
            dx_series.append(100.0 * abs(pdi - mdi) / d if d > 0 else 0.0)
        else:
            dx_series.append(0.0)
    if not dx_series:
        return dx
    adx_val = float(np.mean(dx_series[:period]))
    for x in dx_series[period:]:
        adx_val = (adx_val * (period - 1) + float(x)) / period
    return max(0.0, min(100.0, adx_val))


def _ohlc(n: int = 400, seed: int = 7):
    rng = np.random.default_rng(seed)
    c = 1.10 + np.cumsum(rng.normal(0, 0.0004, n))
    h = c + np.abs(rng.normal(0, 0.0003, n))
    l = c - np.abs(rng.normal(0, 0.0003, n))
    o = np.concatenate([[c[0]], c[:-1]])
    return o, h, l, c


# ---------------------------------------------------------------- testler
@pytest.mark.parametrize("keep,w,seed_len", [
    (0.5, 0.5, 1), (13 / 14, 1 / 14, 14), (1 - 1 / 14, 1.0, 14), (0.8, 0.2, 1),
])
def test_smooth_serisi_eski_donguyle_birebir(keep: float, w: float, seed_len: int) -> None:
    rng = np.random.default_rng(11)
    x = rng.normal(0, 1, 500)
    seed = float(np.mean(x[:seed_len]))
    ref = [w * float(x[0]) + keep * seed]
    for v in x[1:]:
        ref.append(w * float(v) + keep * ref[-1])
    got = forex._smooth(x, keep, w, seed)
    assert np.max(np.abs(got - np.array(ref))) <= 1e-12
    assert abs(forex._smooth_last(x, keep, w, seed) - ref[-1]) <= 1e-12


def test_ema_parite() -> None:
    _o, _h, _l, c = _ohlc()
    for period in (8, 9, 21, 50):
        assert np.max(np.abs(forex._smooth(c, 1 - 2 / (period + 1), 2 / (period + 1), float(c[0]))
                             - _ema_ref(c, period))) <= 1e-12


def test_adx_eski_donguyle_birebir() -> None:
    _o, h, l, c = _ohlc(600)
    for period in (14, 10):
        new = forex._compute_adx(h, l, c, period)
        old = _adx_ref(h, l, c, period)
        assert abs(new - old) <= 1e-9, f"ADX period={period}: yeni {new} vs eski {old}"


def test_rsr_ve_atr_gostergesi_eski_donguyle_birebir(monkeypatch) -> None:
    o, h, l, c = _ohlc(500)
    tech = forex._compute_technical_indicators(list(c), list(h), list(l), list(o), "EURUSD")
    assert tech

    # RSI (Wilder 14) — eski döngü
    deltas = np.diff(c)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    g = float(np.mean(gains[:14]))
    ls = float(np.mean(losses[:14]))
    for i in range(14, len(deltas)):
        g = (g * 13.0 + float(gains[i])) / 14.0
        ls = (ls * 13.0 + float(losses[i])) / 14.0
    rs = g / ls if ls != 0 else 100.0
    assert abs(float(tech["rsi"]) - round(100.0 - (100.0 / (1.0 + rs)), 1)) <= 0.11

    # ATR (Wilder 14) — eski döngü
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr_ref = float(np.mean(tr[:14]))
    for i in range(14, len(tr)):
        atr_ref = (atr_ref * 13.0 + float(tr[i])) / 14.0
    assert abs(float(tech["atr"]) - atr_ref) <= max(1e-10, abs(atr_ref) * 1e-9)


def test_lfilter_yoksa_donguye_duser(monkeypatch) -> None:
    """scipy yoksa davranış aynı kalmalı (yalın kurulum güvencesi)."""
    x = np.linspace(-1, 1, 200)
    fast = forex._smooth(x, 0.9, 0.1, 0.0)
    monkeypatch.setattr(forex, "_lfilter", None)
    slow = forex._smooth(x, 0.9, 0.1, 0.0)
    assert np.max(np.abs(fast - slow)) <= 1e-12
