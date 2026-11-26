"""Tests for 1D EMA 12/50 Daily Bias Filter and Meta-Labeling Probability Scorer."""
from app import meta_label_filter as mlf
from app.daily_bias_filter import compute_daily_bias_from_candles, daily_bias_alignment
from app.meta_label_filter import score_meta_signal, get_meta_filter_stats, train_meta_model_from_trades


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
    assert 1.10 <= strong["size_mult"] <= 1.25

    mid = score_meta_signal(
        "EURUSD", "BUY",
        daily_alignment="NEUTRAL",
        hurst_regime="MEAN_REVERT",
        hmm_regime="LOW_VOL_RANGE",
        kalman_zscore=0.2,
        macro_alignment="NEUTRAL",
        spread_sl_ratio=0.08,
    )
    assert mid["verdict"] == "PASS"
    assert 0.45 <= mid["meta_prob"] < 0.72
    assert 0.85 <= mid["size_mult"] <= 1.05

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
    assert 0.45 <= weak["size_mult"] <= 0.80

    stats = get_meta_filter_stats()
    assert stats["total_evaluated"] >= 3


def test_meta_label_low_accuracy_or_few_samples_skips_ml(monkeypatch):
    class _DummyModel:
        def predict_proba(self, x):
            return [[0.05, 0.95]]

    monkeypatch.setattr(mlf, "_ML_MODEL", _DummyModel())

    # 1) Düşük doğruluk (<0.52) -> rule_prior + ML_SKIP_LOW_ACC
    monkeypatch.setattr(mlf, "_ML_META", {"trained": True, "n_samples": 50, "accuracy": 0.49})
    low_acc = score_meta_signal("EURUSD", "BUY", daily_alignment="NEUTRAL")
    assert low_acc["model_source"] == "rule_prior"
    assert "ML_SKIP_LOW_ACC" in low_acc["reasons"]

    # 2) Az örnek (<30) -> rule_prior + ML_SKIP_LOW_ACC
    monkeypatch.setattr(mlf, "_ML_META", {"trained": True, "n_samples": 25, "accuracy": 0.75})
    few_n = score_meta_signal("EURUSD", "BUY", daily_alignment="NEUTRAL")
    assert few_n["model_source"] == "rule_prior"
    assert "ML_SKIP_LOW_ACC" in few_n["reasons"]

    # 3) Yeterli örnek ve doğruluk -> ml_blend
    monkeypatch.setattr(mlf, "_ML_META", {"trained": True, "n_samples": 40, "accuracy": 0.65})
    ok_ml = score_meta_signal("EURUSD", "BUY", daily_alignment="NEUTRAL")
    assert ok_ml["model_source"] == "ml_blend"
    assert "ML_SKIP_LOW_ACC" not in ok_ml["reasons"]


def test_train_meta_model_require_feature_coverage_guard(monkeypatch):
    sentinel_model = object()
    sentinel_meta = {"trained": False, "n_samples": 0, "trained_at": None, "accuracy": None}
    monkeypatch.setattr(mlf, "_ML_MODEL", sentinel_model)
    monkeypatch.setattr(mlf, "_ML_META", dict(sentinel_meta))

    default_trades = [
        {"direction": "BUY" if i % 2 == 0 else "SELL", "pnl_usd": 10.0 if i % 2 == 0 else -5.0}
        for i in range(25)
    ]
    res_low = train_meta_model_from_trades(
        default_trades, min_samples=20, save_to_disk=False, require_feature_coverage=True
    )
    assert res_low["ok"] is False
    assert res_low["trained"] is False
    assert res_low["n_samples"] == 25
    assert res_low["reason"] == "Yetersiz rejim özelliği kapsamı"
    assert mlf._ML_MODEL is sentinel_model
    assert mlf._ML_META == sentinel_meta

    # >= %30 kapsama ile eğitim gerçekleşmeli
    covered_trades = []
    for i in range(25):
        tr = {"direction": "BUY" if i % 2 == 0 else "SELL", "pnl_usd": 10.0 if i % 2 == 0 else -5.0}
        if i < 10:
            tr["daily_alignment"] = "ALIGNED"
        covered_trades.append(tr)
    res_ok = train_meta_model_from_trades(
        covered_trades, min_samples=20, save_to_disk=False, require_feature_coverage=True
    )
    assert res_ok["ok"] is True
    assert res_ok["trained"] is True
    assert mlf._ML_MODEL is not sentinel_model
