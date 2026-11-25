"""Radar Faz 1 Quant Modülü (Hurst + Kalman + Algorithmic SMC) birim testleri."""
from __future__ import annotations

from datetime import datetime, timezone
import math

import pytest

from app import radar_quant


# --------------------------------------------------------------------------- Hurst Exponent


def test_hurst_trending_series():
    # Güçlü doğrusal/üstel yükseliş serisi -> H > 0.55, TREND
    closes = [100.0 * (1.003 ** i) for i in range(80)]
    res = radar_quant.compute_hurst_exponent(closes)
    assert res["hurst"] is not None
    assert res["hurst"] > 0.55
    assert res["regime"] == "TREND"


def test_hurst_mean_reverting_alternating_series():
    # Sürekli salınan ortalama-dönüşlü seri -> H < 0.45, MEAN_REVERT
    closes = [100.0 + (1.2 if i % 2 == 0 else -1.2) for i in range(80)]
    res = radar_quant.compute_hurst_exponent(closes)
    assert res["hurst"] is not None
    assert res["hurst"] < 0.45
    assert res["regime"] == "MEAN_REVERT"


def test_hurst_short_series_fallback():
    closes = [1.08 + i * 0.0001 for i in range(20)]
    res = radar_quant.compute_hurst_exponent(closes)
    assert res == {"hurst": None, "regime": "UNKNOWN"}


# --------------------------------------------------------------------------- Kalman Filter


def test_kalman_scale_invariance_fx_and_gold():
    # Aynı göreceli hareket EURUSD (~1.08) ve XAUUSD (~2700) üzerinde özdeş metrik vermeli
    rel = [1.0015 ** i * (1.0 + 0.0004 * math.sin(i)) for i in range(60)]
    eur_closes = [1.08 * r for r in rel]
    xau_closes = [2700.0 * r for r in rel]

    k_eur = radar_quant.compute_kalman_filter(eur_closes)
    k_xau = radar_quant.compute_kalman_filter(xau_closes)

    assert k_eur["dir"] == "UP"
    assert k_xau["dir"] == "UP"
    assert k_eur["slope_bps"] == pytest.approx(k_xau["slope_bps"], abs=0.05)
    assert k_eur["zscore"] == pytest.approx(k_xau["zscore"], abs=0.05)
    assert k_eur["overextended"] == k_xau["overextended"]
    assert k_eur["level"] is not None and 1.0 < k_eur["level"] < 1.3
    assert k_xau["level"] is not None and 2500.0 < k_xau["level"] < 3200.0


def test_kalman_uptrend_and_downtrend_direction():
    up_closes = [100.0 * (1.002 ** i) for i in range(50)]
    down_closes = [100.0 * (0.998 ** i) for i in range(50)]

    k_up = radar_quant.compute_kalman_filter(up_closes)
    k_down = radar_quant.compute_kalman_filter(down_closes)

    assert k_up["dir"] == "UP"
    assert k_up["slope_bps"] > 1.5
    assert k_down["dir"] == "DOWN"
    assert k_down["slope_bps"] < -1.5


def test_kalman_overextended_on_sharp_spike():
    # Sakin salınım ardından son barda sert yukarı sıçrama -> overextended=True, zscore >= 2.2
    closes = [100.0 + 0.1 * math.sin(i) for i in range(49)] + [106.0]
    k = radar_quant.compute_kalman_filter(closes)
    assert k["overextended"] is True
    assert k["zscore"] >= 2.2

    # Sert aşağı çöküş -> overextended=True, zscore <= -2.2
    closes_down = [100.0 + 0.1 * math.sin(i) for i in range(49)] + [94.0]
    k_down = radar_quant.compute_kalman_filter(closes_down)
    assert k_down["overextended"] is True
    assert k_down["zscore"] <= -2.2


# --------------------------------------------------------------------------- SMC Structure & Sweeps


def _ohlc_from_closes(closes, spread=0.2):
    opens = [closes[0]] + list(closes[:-1])
    highs = [max(o, c) + spread for o, c in zip(opens, closes)]
    lows = [min(o, c) - spread for o, c in zip(opens, closes)]
    return opens, highs, lows, list(closes)


def test_smc_bullish_bos():
    # Yükselen yapı: SL1(100) -> SH1(105) -> SL2(102) -> SH2(108) -> geri çekilme(106) -> kırılım(109.5)
    closes = [
        103, 102, 101, 100, 101, 102, 103,   # SL1 at idx 3 (100)
        104, 105, 104, 103, 102,             # SH1 at idx 8 (105), SL2 at idx 11 (102)
        103, 105, 107, 108, 107, 106, 105,   # SH2 at idx 15 (108), confirmed by 16,17,18
        106, 109.5,                          # last bar breaks above SH2 (108 + spread=108.2)
    ]
    opens, highs, lows, c = _ohlc_from_closes(closes, spread=0.2)
    res = radar_quant.detect_smc_structure(opens, highs, lows, c, swing_len=3)
    assert res["structure"] == "BULLISH_BOS"


def test_smc_bearish_choch():
    # Yükselen yapı (SL1=100, SH1=105, SL2=102, SH2=108) ardından son bar SL2 altına kırar -> BEARISH_CHOCH
    closes = [
        103, 102, 101, 100, 101, 102, 103,   # SL1 at idx 3 (100)
        104, 105, 104, 103, 102,             # SH1 at idx 8 (105), SL2 at idx 11 (102)
        103, 105, 107, 108, 107, 106, 104,   # SH2 at idx 15 (108)
        103, 100.5,                          # last bar breaks below SL2 (102 - 0.2 = 101.8)
    ]
    opens, highs, lows, c = _ohlc_from_closes(closes, spread=0.2)
    res = radar_quant.detect_smc_structure(opens, highs, lows, c, swing_len=3)
    assert res["structure"] == "BEARISH_CHOCH"


def test_smc_bullish_and_bearish_sweep():
    # Onaylı dip (idx 6 -> low=99.0) ve onaylı tepe (idx 12 -> high=106.0)
    closes = [
        102, 101.5, 101, 100.5, 100, 99.5, 99.2,
        100, 101, 102, 103, 104, 105.5,
        104, 103, 102, 101.5, 101.2,
    ]
    opens, highs, lows, c = _ohlc_from_closes(closes, spread=0.2)
    # Son bar onaylı swing low (99.0) altına fitil atıp üstünde kapanır -> BULLISH_SWEEP
    lows[-1] = 98.4
    c[-1] = 100.2
    highs[-1] = 101.5
    res_bull = radar_quant.detect_smc_structure(opens, highs, lows, c, swing_len=3)
    assert res_bull["sweep"] == "BULLISH_SWEEP"

    # Son bar onaylı swing high (105.7) üstüne fitil atıp altında kapanır -> BEARISH_SWEEP
    lows[-1] = 101.0
    highs[-1] = 106.5
    c[-1] = 104.5
    res_bear = radar_quant.detect_smc_structure(opens, highs, lows, c, swing_len=3)
    assert res_bear["sweep"] == "BEARISH_SWEEP"


def test_smc_asian_box_sweep_high_and_low():
    # 00:00-05:30 UTC Asya seansı barları (yüksek=102.0, düşük=100.0), ardından 08:00 UTC Londra barı
    base_ts = int(datetime(2026, 11, 25, 0, 0, tzinfo=timezone.utc).timestamp())
    bar_times = [base_ts + i * 1800 for i in range(12)]  # 00:00 .. 05:30 UTC
    bar_times += [base_ts + 7 * 3600, base_ts + 8 * 3600]  # 07:00, 08:00 UTC

    n = len(bar_times)
    opens = [101.0] * n
    highs = [102.0] * n
    lows = [100.0] * n
    closes = [101.0] * n

    # Londra 08:00 barı Asya tepesini (102.0) fitille geçip altında kapanır -> HIGH_SWEPT
    highs[-1] = 102.6
    lows[-1] = 100.8
    closes[-1] = 101.6
    res_hi = radar_quant.detect_smc_structure(opens, highs, lows, closes, bar_times=bar_times, swing_len=2)
    assert res_hi["asian_sweep"] == "HIGH_SWEPT"

    # Londra 08:00 barı Asya dibini (100.0) fitille geçip üstünde kapanır -> LOW_SWEPT
    highs[-1] = 101.2
    lows[-1] = 99.4
    closes[-1] = 100.5
    res_lo = radar_quant.detect_smc_structure(opens, highs, lows, closes, bar_times=bar_times, swing_len=2)
    assert res_lo["asian_sweep"] == "LOW_SWEPT"


# --------------------------------------------------------------------------- evaluate_ohlc


def test_evaluate_ohlc_delta_bounds_and_overextended_penalty():
    # Güçlü trend + son barda aşırı yukarı sıçrama -> BUY için tepe kovalama cezası (-5.0) çalışmalı
    closes_normal = [100.0 * (1.001 ** i) + 0.05 * math.sin(i) for i in range(60)]
    closes_spike = closes_normal[:-1] + [closes_normal[-2] * 1.05]

    o1, h1, l1, c1 = _ohlc_from_closes(closes_normal, spread=0.05)
    o2, h2, l2, c2 = _ohlc_from_closes(closes_spike, spread=0.05)

    res_normal = radar_quant.evaluate_ohlc(o1, h1, l1, c1, action="BUY")
    res_spike = radar_quant.evaluate_ohlc(o2, h2, l2, c2, action="BUY")
    res_hold = radar_quant.evaluate_ohlc(o2, h2, l2, c2, action="HOLD")

    assert -12.0 <= res_normal["quant_score_delta"] <= 12.0
    assert -12.0 <= res_spike["quant_score_delta"] <= 12.0
    assert res_hold["quant_score_delta"] == 0.0
    assert res_spike["kalman_overextended"] is True
    assert "⚠️ Aşırı Uzamış" in res_spike["quant_badges"]
    assert res_spike["quant_score_delta"] < res_normal["quant_score_delta"]
