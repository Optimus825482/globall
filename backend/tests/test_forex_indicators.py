"""Karar desteği göstergeleri: Bollinger, Keltner/TTM sıkışma, Supertrend, StochRSI, CCI, Donchian."""
import math
import random

import pytest

from app import forex_indicators as fi


def bars_from(closes, spread=0.4):
    return [{"open": c, "high": c + spread, "low": c - spread, "close": c} for c in closes]


def test_bollinger_bands_match_population_stdev():
    closes = [100.0 + (i % 5) for i in range(60)]
    b = fi.bollinger(bars_from(closes))
    w = closes[-20:]
    mid = sum(w) / 20
    sd = math.sqrt(sum((c - mid) ** 2 for c in w) / 20)
    assert b["orta"] == pytest.approx(mid, abs=0.01) and b["ust"] == pytest.approx(mid + 2 * sd, abs=0.01)
    assert 0.0 <= b["yuzde_b"] <= 1.0 and b["bant_disi_mum"] == 0


def test_bollinger_squeeze_after_volatility_and_band_walk():
    rng = random.Random(3)
    noisy = [100 + rng.uniform(-5, 5) for _ in range(100)]
    calm = [100 + rng.uniform(-0.2, 0.2) for _ in range(25)]
    b = fi.bollinger(bars_from(noisy + calm))
    assert b["sikisma"] and b["genislik_yuzdelik"] <= 0.2                      # son 120 mumun en dar bölgesi
    ramp = [100.0] * 50 + [100 + 2.0 * i for i in range(1, 11)]                # sert yükseliş: bant yürüyüşü
    w = fi.bollinger(bars_from(ramp))
    assert w["bant_disi_mum"] == 3 and w["yuzde_b"] > 1.0


def test_keltner_ttm_squeeze_requires_inside_channel():
    calm = bars_from([100 + (0.1 if i % 2 else -0.1) for i in range(80)], spread=0.5)       # BB dar, ATR görece geniş → içeride
    assert fi.keltner_squeeze(calm, fi.bollinger(calm)) is True
    rng = random.Random(1)
    wild = bars_from([100 + rng.uniform(-6, 6) for _ in range(80)], spread=0.2)             # BB geniş, ATR dar → dışarıda
    assert fi.keltner_squeeze(wild, fi.bollinger(wild)) is False


def test_supertrend_follows_trend_and_reports_flip():
    up = fi.supertrend(bars_from([100 + i * 0.5 for i in range(80)], spread=0.3))
    assert up["yon"] == "yukari" and up["seviye"] < 100 + 79 * 0.5
    down = fi.supertrend(bars_from([100 + i * 0.5 for i in range(60)] + [130 - i * 2.0 for i in range(1, 30)], spread=0.3))
    assert down["yon"] == "asagi" and down["kac_mum_once_dondu"] < 29


def test_stoch_rsi_extremes_and_cci_donchian():
    rising = [100 + i * 0.3 + (0.2 if i % 3 == 0 else 0) for i in range(80)]
    s = fi.stoch_rsi(rising)
    assert 0 <= s["k"] <= 100 and s["bolge"] in ("asiri_alim", "orta", "asiri_satim")
    b = bars_from(rising)
    assert fi.cci(b) > 0 and fi.donchian(b)["konum_yuzde"] >= 90
    assert fi.stoch_rsi(rising[:20]) == {} and fi.cci(b[:5]) is None


def test_pack_requires_min_bars_and_drops_empty():
    assert fi.pack(bars_from([100.0] * 30)) == {}
    p = fi.pack(bars_from([100 + (i % 7) * 0.3 for i in range(120)]))
    assert {"bollinger", "supertrend", "stoch_rsi", "cci20", "donchian20"} <= set(p)
