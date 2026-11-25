"""Tests for 1D EMA 12/50 Daily Bias Filter and Meta-Labeling Probability Scorer."""
from app.daily_bias_filter import compute_daily_bias_from_candles, daily_bias_alignment
from app.meta_label_filter import score_meta_signal, get_meta_filter_stats


def test_daily_bias_bullish_bearish_and_alignment():
    up_candles = [{"close": 1.0500 + i * 0.0010} for i in range(60)]
    res_up = compute_daily_bias_from_candles(up_candles)
    assert res_up["bias"] == "BULLISH"
    assert daily_bias_alignment(res_up["bias"], "BUY") == "ALIGNED"
    assert daily_bias_alignment(res_up["bias"], "SELL") == "COUNTER"

    dn_candles = [{"close": 1.1500 - i * 0.0010} for i in range(60)]
    res_dn = compute_daily_bias_from_candles(dn_candles)
    assert res_dn["bias"] == "BEARISH"
    assert daily_bias_alignment(res_dn["bias"], "SELL") == "ALIGNED"
    assert daily_bias_alignment(res_dn["bias"], "BUY") == "COUNTER"


def test_meta_label_scorer_boost_and_reduce():
    strong = score_meta_signal(
        "EURUSD", "BUY",
        daily_alignment="ALIGNED",
        hurst_regime="TREND",
        hmm_regime="TREND_EXPANSION",
        kalman_zscore=0.4,
        macro_alignment="SUPPORTIVE",
        spread_sl_ratio=0.08,
    )
    assert strong["verdict"] == "BOOST"
    assert strong["meta_prob"] >= 0.72
    assert strong["size_mult"] == 1.15

    weak = score_meta_signal(
        "EURUSD", "SELL",
        daily_alignment="COUNTER",
        hurst_regime="RANDOM_WALK",
        hmm_regime="SHOCK_VOLATILITY",
        kalman_zscore=-2.0,
        macro_alignment="OPPOSING",
        spread_sl_ratio=0.22,
    )
    assert weak["verdict"] == "REDUCE"
    assert weak["meta_prob"] < 0.45
    assert weak["size_mult"] == 0.6

    stats = get_meta_filter_stats()
    assert stats["total_evaluated"] >= 2
