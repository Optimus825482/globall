"""Radar Faz 2 birim testleri: 3-Durumlu HMM Rejim Sınıflandırıcısı ve Makro Lead-Lag (US10Y/VIX/DXY)."""
from app import macro_lead_lag as mll
from app import radar_quant as rq


def test_hmm_regime_short_series_returns_unknown():
    res = rq.compute_hmm_regime([101.0] * 10, [99.0] * 10, [100.0] * 10)
    assert res["hmm_regime"] == "UNKNOWN"
    assert res["hmm_confidence"] == 0.0


def test_hmm_regime_detects_clean_trend_expansion():
    # Steady upward trend with clean directional efficiency
    closes = [100.0 + i * 0.45 for i in range(60)]
    highs = [c + 0.30 for c in closes]
    lows = [c - 0.15 for c in closes]
    res = rq.compute_hmm_regime(highs, lows, closes)
    assert res["hmm_regime"] == "TREND_EXPANSION"
    assert res["hmm_confidence"] >= 0.55
    assert abs(sum(res["hmm_probs"].values()) - 1.0) < 0.02


def test_hmm_regime_detects_low_vol_range():
    # Tight alternating range with low efficiency and low bar range
    closes = [100.0 + (0.04 if i % 2 == 0 else -0.04) for i in range(60)]
    highs = [c + 0.06 for c in closes]
    lows = [c - 0.06 for c in closes]
    res = rq.compute_hmm_regime(highs, lows, closes)
    assert res["hmm_regime"] == "LOW_VOL_RANGE"
    assert res["hmm_confidence"] >= 0.50


def test_hmm_regime_detects_shock_volatility():
    # Calm baseline followed by sudden 4x extreme-range choppy shock bars
    closes = [100.0 + (0.05 if i % 2 == 0 else -0.05) for i in range(45)]
    highs = [c + 0.12 for c in closes]
    lows = [c - 0.12 for c in closes]
    for i in range(15):
        c = 100.0 + (0.4 if i % 2 == 0 else -0.4)
        closes.append(c)
        highs.append(c + 1.8)
        lows.append(c - 1.8)
    res = rq.compute_hmm_regime(highs, lows, closes)
    assert res["hmm_regime"] == "SHOCK_VOLATILITY"
    assert res["hmm_confidence"] >= 0.55


def test_macro_alignment_gold_falling_us10y_weak_dxy():
    macro = {
        "us10y": {"last": 4.10, "change_pct_1h": -0.8, "dir": "FALLING"},
        "vix": {"last": 24.5, "change_pct_1h": 7.0, "regime": "RISK_OFF_PANIC"},
        "dxy_regime": "USD_WEAK",
    }
    buy = mll.evaluate_macro_alignment("XAUUSD", "BUY", macro)
    sell = mll.evaluate_macro_alignment("XAUUSD", "SELL", macro)
    assert buy["macro_alignment"] == "SUPPORTIVE" and buy["macro_delta"] == 8.0
    assert sell["macro_alignment"] == "OPPOSING" and sell["macro_delta"] == -7.0
    assert "US10Y düşüyor" in buy["macro_note"]


def test_macro_alignment_usdjpy_and_risk_off_assets():
    panic_macro = {
        "us10y": {"last": 4.45, "change_pct_1h": -0.6, "dir": "FALLING"},
        "vix": {"last": 25.0, "change_pct_1h": 8.0, "regime": "RISK_OFF_PANIC"},
        "dxy_regime": "USD_STRONG",
    }
    jpy_buy = mll.evaluate_macro_alignment("USDJPY", "BUY", panic_macro)
    jpy_sell = mll.evaluate_macro_alignment("USDJPY", "SELL", panic_macro)
    assert jpy_buy["macro_alignment"] == "OPPOSING" and jpy_buy["macro_delta"] == -7.0
    assert jpy_sell["macro_alignment"] == "SUPPORTIVE" and jpy_sell["macro_delta"] == 6.0

    btc_buy = mll.evaluate_macro_alignment("BTCUSD", "BUY", panic_macro)
    assert btc_buy["macro_alignment"] == "OPPOSING" and btc_buy["macro_delta"] == -4.0

    aud_buy = mll.evaluate_macro_alignment("AUDUSD", "BUY", panic_macro)
    assert aud_buy["macro_alignment"] == "OPPOSING" and aud_buy["macro_delta"] == -7.0

    oil_buy = mll.evaluate_macro_alignment("USOIL", "BUY", panic_macro)
    assert oil_buy["macro_alignment"] == "OPPOSING" and oil_buy["macro_delta"] == -3.0

    hold = mll.evaluate_macro_alignment("EURUSD", "HOLD", panic_macro)
    assert hold["macro_alignment"] == "NEUTRAL" and hold["macro_delta"] == 0.0
