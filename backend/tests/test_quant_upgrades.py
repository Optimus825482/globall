"""Unit tests for QuantStats tear-sheet, SMC engine, Triple-Barrier ML meta-filter, and Episodic Reflection."""
from __future__ import annotations

from app import episodic_reflection, meta_label_filter, quantstats_analytics, smc_engine


def test_quantstats_tearsheet_json_and_html():
    trades = [
        {"symbol": "XAUUSD", "strategy": "RADAR", "pnl_usd": 25.0, "exit_ts": 1000},
        {"symbol": "EURJPY", "strategy": "FIRSAT_TARAMASI", "pnl_usd": -15.0, "exit_ts": 2000},
        {"symbol": "XAUUSD", "strategy": "RADAR", "pnl_usd": 30.0, "exit_ts": 3000},
        {"symbol": "GBPJPY", "strategy": "FIRSAT_TARAMASI", "pnl_usd": -10.0, "exit_ts": 4000},
    ]
    rep = quantstats_analytics.build_tearsheet(trades, initial_balance=1000.0)
    assert rep["trade_count"] == 4
    assert rep["net_pnl_usd"] == 30.0
    assert rep["win_rate_pct"] == 50.0
    assert rep["profit_factor"] == 2.2
    assert rep["max_drawdown_usd"] < 0
    assert "sharpe" in rep and "sortino" in rep and "calmar" in rep
    assert len(rep["win_loss_distribution"]) == 6
    html_out = quantstats_analytics.render_tearsheet_html(rep)
    assert "<!doctype html>" in html_out and "Sharpe" in html_out and "XAUUSD" in html_out


def test_smc_engine_ob_bos_and_sweep():
    # Construct candles with a clear bullish OB and bullish BOS
    candles = []
    px = 100.0
    for i in range(18):
        o = px
        c = px + 0.2
        candles.append({"open": o, "high": c + 0.1, "low": o - 0.1, "close": c})
        px = c
    # Last bearish candle before strong impulse (Bullish OB)
    candles.append({"open": px, "high": px + 0.2, "low": px - 0.5, "close": px - 0.3})
    # Strong bullish impulse breaking structure
    candles.append({"open": px - 0.3, "high": px + 3.0, "low": px - 0.3, "close": px + 2.8})
    candles.append({"open": px + 2.8, "high": px + 4.5, "low": px + 2.5, "close": px + 4.2})

    res = smc_engine.analyze_smc(candles, direction="BUY")
    assert res["order_block"] is not None
    assert res["order_block"]["type"] == "BULLISH_OB"
    assert res["smc_structure"] in ("BOS_BULL", "CHOCH_BULL")
    assert res["smc_alignment"] == "SUPPORTIVE"
    assert res["smc_score_delta"] > 0


def test_triple_barrier_and_meta_ml_training():
    assert meta_label_filter.triple_barrier_label(100.0, [101.0, 103.0], [99.5, 100.5], "BUY", 2.0, 1.5) == 1
    assert meta_label_filter.triple_barrier_label(100.0, [100.5, 101.0], [98.0, 99.0], "BUY", 2.0, 1.5) == 0

    trades = []
    for i in range(24):
        win = (i % 2 == 0)
        trades.append({
            "direction": "BUY" if win else "SELL",
            "daily_alignment": "ALIGNED" if win else "COUNTER",
            "hurst_regime": "TREND" if win else "RANDOM_WALK",
            "hmm_regime": "TREND_EXPANSION" if win else "SHOCK_VOLATILITY",
            "kalman_zscore": 0.3 if win else -2.5,
            "macro_alignment": "SUPPORTIVE" if win else "OPPOSING",
            "spread_sl_ratio": 0.05 if win else 0.30,
            "pnl_usd": 15.0 if win else -12.0,
            "exit_ts": 1700000000 + i * 3600,
        })
    res = meta_label_filter.train_meta_model_from_trades(trades, min_samples=20, save_to_disk=False)
    assert res["ok"] is True and res["trained"] is True and res["n_samples"] == 24

    scored = meta_label_filter.score_meta_signal(
        "EURUSD", "BUY",
        daily_alignment="ALIGNED", hurst_regime="TREND",
        hmm_regime="TREND_EXPANSION", macro_alignment="SUPPORTIVE",
    )
    assert scored["model_source"] == "ml_blend"
    assert 0.05 <= scored["meta_prob"] <= 0.95


def test_episodic_reflection_store_and_retrieve():
    episodic_reflection._EPISODIC_STORE.clear()
    trades = [
        {"ticket": 101, "symbol": "EURJPY", "direction": "SELL", "strategy": "FIRSAT_TARAMASI", "pnl_usd": -16.77, "reason": "Zarar Durdur (SL)", "exit_ts": 1700001000},
        {"ticket": 102, "symbol": "EURJPY", "direction": "SELL", "strategy": "FIRSAT_TARAMASI", "pnl_usd": -8.43, "reason": "Zarar Durdur (SL)", "exit_ts": 1700005000},
    ]
    added = episodic_reflection.sync_reflections_from_closed_trades(trades)
    assert added == 2
    # Deduplicated on second call
    assert episodic_reflection.sync_reflections_from_closed_trades(trades) == 0

    ctx = episodic_reflection.retrieve_relevant_lessons("EURJPY", "SELL", "FIRSAT_TARAMASI", limit=3)
    assert ctx["caution"] is True
    assert len(ctx["lessons"]) == 2
    assert "EURJPY" in ctx["summary"]
