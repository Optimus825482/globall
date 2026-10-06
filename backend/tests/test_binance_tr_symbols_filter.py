"""Unit tests for Binance TR symbol filtering across spot scanning, discovery,
alerting, radar, velocity, auto_paper, and bridge dispatch.
"""

import asyncio
import unittest
from unittest import mock

from app.binance_tr_symbols import (
    is_binance_tr_symbol,
    filter_binance_tr_symbols,
    get_binance_tr_base_assets,
)
from app import binance_public as b_pub
from app import early_discovery as ed
from app.routers import velocity as vel
from app.routers import monitoring as mon
from app import alerting
from app import tr_bridge
from app import combined_radar as radar
from app import rising_signals as rising
from app.routers import auto_paper


class TestBinanceTRSymbolsFilter(unittest.IsolatedAsyncioTestCase):

    def test_symbol_membership_and_normalization(self):
        """Test base asset extraction and membership check for Binance TR."""
        # Known Binance TR pairs
        self.assertTrue(is_binance_tr_symbol("BTCUSDT"))
        self.assertTrue(is_binance_tr_symbol("btcusdt"))
        self.assertTrue(is_binance_tr_symbol("BTCTRY"))
        self.assertTrue(is_binance_tr_symbol("BTC_TRY"))
        self.assertTrue(is_binance_tr_symbol("BTC"))
        self.assertTrue(is_binance_tr_symbol("SOLUSDT"))
        self.assertTrue(is_binance_tr_symbol("ETHFDUSD"))
        self.assertTrue(is_binance_tr_symbol("AVAXUSDT"))
        self.assertTrue(is_binance_tr_symbol("PEPEUSDT"))

        # Coins NOT available on Binance TR
        self.assertFalse(is_binance_tr_symbol("1INCHUSDT"))
        self.assertFalse(is_binance_tr_symbol("1INCH"))
        self.assertFalse(is_binance_tr_symbol("ASTRUSDT"))
        self.assertFalse(is_binance_tr_symbol("BATUSDT"))
        self.assertFalse(is_binance_tr_symbol("CHEEMSUSDT"))

        # Edge cases
        self.assertFalse(is_binance_tr_symbol(""))
        self.assertFalse(is_binance_tr_symbol(None))

        # Filter helper
        symbols = ["BTCUSDT", "1INCHUSDT", "SOLUSDT", "ASTRUSDT", "AVAXUSDT"]
        filtered = filter_binance_tr_symbols(symbols)
        self.assertEqual(filtered, ["BTCUSDT", "SOLUSDT", "AVAXUSDT"])

    def test_binance_public_trading_symbols_filtered(self):
        """Verify binance_public.trading_symbols filters out non-TR symbols."""
        mock_exchange_info = {
            "symbols": [
                {"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT", "isSpotTradingAllowed": True},
                {"symbol": "1INCHUSDT", "status": "TRADING", "quoteAsset": "USDT", "isSpotTradingAllowed": True},
                {"symbol": "SOLUSDT", "status": "TRADING", "quoteAsset": "USDT", "isSpotTradingAllowed": True},
                {"symbol": "ASTRUSDT", "status": "TRADING", "quoteAsset": "USDT", "isSpotTradingAllowed": True},
            ]
        }
        with mock.patch("app.binance_public._get_json", return_value=mock_exchange_info):
            # Clear exchange info cache
            b_pub._exchange_info_cache["expires"] = 0.0
            symbols = asyncio.run(b_pub.trading_symbols(quote_asset="USDT"))
            self.assertIn("BTCUSDT", symbols)
            self.assertIn("SOLUSDT", symbols)
            self.assertNotIn("1INCHUSDT", symbols)
            self.assertNotIn("ASTRUSDT", symbols)

    def test_early_discovery_ignores_non_tr(self):
        """Verify early_discovery does not ingest tickers for non-TR symbols."""
        ed._state.clear()
        # Ingest a non-TR row
        ed._ingest_row({
            "s": "1INCHUSDT",
            "c": "0.50",
            "v": "1000000",
            "q": "500000",
        }, suffix="USDT")
        self.assertNotIn("1INCHUSDT", ed._state)

        # Ingest a valid TR row
        ed._ingest_row({
            "s": "BTCUSDT",
            "c": "60000",
            "v": "1000",
            "q": "60000000",
        }, suffix="USDT")
        self.assertIn("BTCUSDT", ed._state)
        ed._state.clear()

    async def test_velocity_drops_non_tr(self):
        """Verify velocity rejects non-TR symbols in candidate pool and scanning."""
        with mock.patch("app.binance_tr_public.ticker_24h", return_value=[]), \
             mock.patch("app.binance_tr_public.top_gainers", return_value=[{"symbol": "1INCHUSDT"}]), \
             mock.patch("app.binance_tr_public.active_movers_pool", return_value=[{"symbol": "ASTRUSDT"}]), \
             mock.patch("app.early_discovery.top_candidates", return_value=[]), \
             mock.patch("app.config.config.SYMBOLS", []):
            res = await vel.detect_velocity_candidates({"limit": 5}, horizon_minutes=5, extra_symbols=["1INCHUSDT", "ASTRUSDT"])
            syms = [c["symbol"] for c in res.get("candidates", [])]
            self.assertNotIn("1INCHUSDT", syms)
            self.assertNotIn("ASTRUSDT", syms)

    async def test_monitoring_send_push_drops_non_tr(self):
        """Verify monitoring._send_push immediately skips non-TR notifications."""
        notif = {
            "symbol": "1INCHUSDT",
            "title": "Radar 1INCHUSDT",
            "message": "test",
            "target_pct": 2.0,
            "price": 0.5,
        }
        sent = await mon._send_push(notif)
        self.assertFalse(sent)

    async def test_alerting_web_push_drops_non_tr_crypto_preserves_forex(self):
        """Verify alerting.deliver_web_push drops non-TR crypto but allows Forex."""
        # Non-TR crypto should be skipped
        res = await alerting.deliver_web_push(
            "1INCH alert",
            title="Crypto Alert",
            extra={"symbol": "1INCHUSDT", "source": "velocity"},
        )
        self.assertFalse(res.get("ok"))
        self.assertTrue(res.get("skipped"))
        self.assertEqual(res.get("reason"), "symbol_not_on_binance_tr")

        # Forex pair EURUSD should not be skipped by Binance TR filter
        res_forex = await alerting.deliver_web_push(
            "EURUSD alert",
            title="Forex Alert",
            extra={"symbol": "EURUSD", "source": "forex"},
        )
        self.assertNotEqual(res_forex.get("reason"), "symbol_not_on_binance_tr")

    async def test_tr_bridge_guards(self):
        """Verify tr_bridge rejects signals for non-TR symbols."""
        res = await tr_bridge.send_signal_to_tr("1INCHUSDT", "velocity", price=0.5, score=80.0)
        self.assertFalse(res.get("ok"))
        self.assertTrue(res.get("skipped"))
        self.assertEqual(res.get("reason"), "symbol_not_on_binance_tr")

        q_res = tr_bridge.queue_signal_to_tr("1INCHUSDT", "velocity", price=0.5, score=80.0)
        self.assertIsNone(q_res)

    def test_combined_radar_normalizers(self):
        """Verify combined_radar normalizers reject non-TR symbols."""
        norm_v = radar.normalize_velocity_candidate({"symbol": "1INCHUSDT", "score": 80.0})
        self.assertIsNone(norm_v)

        norm_r = radar.normalize_rising_evidence({"symbol": "1INCHUSDT", "score": 80.0})
        self.assertIsNone(norm_r)

        norm_ok = radar.normalize_velocity_candidate({"symbol": "BTCUSDT", "score": 80.0})
        self.assertIsNotNone(norm_ok)
        self.assertEqual(norm_ok["symbol"], "BTCUSDT")

    def test_rising_signals_detect_filter(self):
        """Verify rising_signals candidate detection drops non-TR symbols."""
        fake_snapshot = {
            "universe": ["BTCUSDT", "1INCHUSDT"],
            "symbols": {
                "BTCUSDT": {"pre": {"dip": True}, "early_score": 75.0, "strength": 8.0},
                "1INCHUSDT": {"pre": {"dip": True}, "early_score": 90.0, "strength": 9.5},
            },
            "generated_at": 1000.0,
        }
        with mock.patch("app.routers.macd_monitor._SNAPSHOT", fake_snapshot):
            with mock.patch("app.rising_signals.rising_is_stale", return_value=False):
                candidates = rising.detect_rising_candidates()
                syms = [c["symbol"] for c in candidates]
                self.assertIn("BTCUSDT", syms)
                self.assertNotIn("1INCHUSDT", syms)

    async def test_auto_paper_trade_guard(self):
        """Verify auto_paper.try_open_from_notification rejects non-TR symbol."""
        notif = {
            "symbol": "1INCHUSDT",
            "score": 85.0,
            "price": 0.5,
            "target_pct": 2.5,
        }
        result = await auto_paper.try_open_from_notification(notif)
        self.assertIsNotNone(result)
        self.assertEqual(result.get("status"), "blocked")
        self.assertEqual(result.get("reason"), "symbol_not_on_binance_tr")


if __name__ == "__main__":
    unittest.main()
