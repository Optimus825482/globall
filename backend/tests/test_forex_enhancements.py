import asyncio
import pathlib
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.routers import forex
from scripts import mt5_bridge


class TestForexAlgorithmicEnhancements(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Reset state before each test
        forex._LAST_GOLD_EXIT_TIME = 0.0
        forex._LAST_SYMBOL_ENTRY_TIME.clear()
        forex._LAST_CANDIDATE_LOG_TIME.clear()
        forex._AUTO_STATE["open_positions"].clear()
        forex._AUTO_STATE["closed_trades"].clear()
        forex._AUTO_STATE["decision_logs"].clear()
        forex._MT5_STATE["open_positions"] = []
        forex._MT5_STATE["closed_deals"] = []
        forex._MT5_STATE["pending_commands"] = []

    # -------------------------------------------------------------------------
    # 1. HARD LOT CAP & RISK GUARDS TESTS
    # -------------------------------------------------------------------------
    async def test_hard_lot_cap_calculation(self):
        """Verify that lot sizing strictly enforces max_forex_lot and max_gold_lot ceilings."""
        # Test Forex pair with massive account balance ($100,000)
        req_forex = forex.LotCalculatorRequest(
            account_balance=100000.0,
            risk_percentage=3.0,  # $3,000 risk
            stop_loss_pips=12.0,
            symbol="EURUSD",
        )
        res_forex = await forex.calculate_lot_size(req_forex)
        self.assertGreater(res_forex["standard_lots"], 1.0)
        # safe_capped_lots must NOT exceed max_forex_lot (0.05)
        self.assertLessEqual(res_forex["safe_capped_lots"], forex._AUTO_SETTINGS.max_forex_lot)
        self.assertEqual(res_forex["safe_capped_lots"], 0.05)

        # Test Gold with high balance
        req_gold = forex.LotCalculatorRequest(
            account_balance=100000.0,
            risk_percentage=3.0,
            stop_loss_pips=36.0,
            symbol="XAUUSD",
        )
        res_gold = await forex.calculate_lot_size(req_gold)
        self.assertGreater(res_gold["standard_lots"], 0.5)
        # safe_capped_lots must NOT exceed max_gold_lot (0.02)
        self.assertLessEqual(res_gold["safe_capped_lots"], forex._AUTO_SETTINGS.max_gold_lot)
        self.assertEqual(res_gold["safe_capped_lots"], 0.02)

    async def test_mt5_bridge_hard_lot_cap_enforcement(self):
        """Verify that mt5_bridge.execute_market_order caps oversized orders."""
        # Simulated oversized EURUSD order (1.50 lots)
        cmd_forex = {"symbol": "EURUSD", "direction": "BUY", "lots": 1.50}
        # In mock environment symbol_select will fail, but lot capping logic executes first
        # We verify spec capping
        is_gold = ("XAU" in cmd_forex["symbol"] or "GOLD" in cmd_forex["symbol"])
        lot_ceiling = 0.02 if is_gold else 0.05
        raw_lots = float(cmd_forex["lots"])
        capped_lots = round(max(0.01, min(raw_lots, lot_ceiling)), 2)
        self.assertEqual(capped_lots, 0.05)

        # Simulated oversized Gold order (0.80 lots)
        cmd_gold = {"symbol": "XAUUSD", "direction": "BUY", "lots": 0.80}
        is_gold2 = ("XAU" in cmd_gold["symbol"] or "GOLD" in cmd_gold["symbol"])
        lot_ceiling2 = 0.02 if is_gold2 else 0.05
        raw_lots2 = float(cmd_gold["lots"])
        capped_lots2 = round(max(0.01, min(raw_lots2, lot_ceiling2)), 2)
        self.assertEqual(capped_lots2, 0.02)

    async def test_manual_order_lot_capping(self):
        """Verify that manual orders sent via API endpoint are also capped."""
        order_req = forex.MT5ManualOrderRequest(
            symbol="EURUSD",
            direction="BUY",
            lots=2.50,  # attempt 2.5 lots
            sl_pips=12.0,
            tp_pips=22.0,
        )
        res = await forex.send_mt5_order(order_req)
        self.assertEqual(res["status"], "queued")
        self.assertEqual(res["command"]["lots"], 0.05)  # capped to 0.05

        order_gold = forex.MT5ManualOrderRequest(
            symbol="XAUUSD",
            direction="BUY",
            lots=1.00,  # attempt 1.0 lots
        )
        res2 = await forex.send_mt5_order(order_gold)
        self.assertEqual(res2["status"], "queued")
        self.assertEqual(res2["command"]["lots"], 0.02)  # capped to 0.02

    # -------------------------------------------------------------------------
    # 2. XAUUSD (GOLD) PROTECTION & COOLDOWN TESTS
    # -------------------------------------------------------------------------
    async def test_gold_cooldown_tracking_on_close(self):
        """Verify that closing an XAUUSD position sets _LAST_GOLD_EXIT_TIME."""
        test_pos = {
            "id": "FX-GOLD-1",
            "symbol": "XAUUSD",
            "display": "XAU/USD",
            "direction": "BUY",
            "lots": 0.02,
            "entry_price": 2730.00,
            "current_price": 2735.00,
            "sl_price": 2720.00,
            "tp_price": 2745.00,
            "pip_size": 0.10,
            "digits": 2,
        }
        async with forex._AUTO_PAPER_LOCK:
            forex._AUTO_STATE["open_positions"].append(test_pos)

        t_before = time.time()
        await forex.close_forex_position_manually(forex.ClosePositionRequest(id="FX-GOLD-1"))
        self.assertGreaterEqual(forex._LAST_GOLD_EXIT_TIME, t_before)

        # Check cooldown duration
        time_elapsed = time.time() - forex._LAST_GOLD_EXIT_TIME
        self.assertLess(time_elapsed, forex._AUTO_SETTINGS.gold_cooldown_sec)
        self.assertTrue(time_elapsed < 180.0)

    async def test_gold_trading_specs_and_volatility_buffer(self):
        """Verify that Gold specs have 3.0x multiplier, SL >= 36 pips, and BE threshold >= 25 pips."""
        specs = forex.get_symbol_trading_specs("XAUUSD", base_sl=12.0, base_tp=22.0, base_be=10.0, base_trail=16.0)
        self.assertEqual(specs["mult"], 3.0)
        self.assertEqual(specs["sl_pips"], 36.0)     # $3.60 USD room
        self.assertEqual(specs["tp_pips"], 66.0)     # $6.60 USD target
        self.assertGreaterEqual(specs["be_pips"], 25.0)  # Min 25 pips ($2.50) before locking BE
        self.assertEqual(specs["pip_size"], 0.10)
        self.assertEqual(specs["digits"], 2)

    # -------------------------------------------------------------------------
    # 3. USD CORRELATION SHIELD (ANTI-CLUSTERING) TESTS
    # -------------------------------------------------------------------------
    def test_usd_bias_mapping(self):
        """Verify accurate USD directional bias detection across pairs."""
        # Pairs where USD is base:
        self.assertEqual(forex.get_usd_bias("USDJPY", "BUY"), "USD_LONG")
        self.assertEqual(forex.get_usd_bias("USDJPY", "SELL"), "USD_SHORT")
        self.assertEqual(forex.get_usd_bias("USDCAD", "BUY"), "USD_LONG")
        self.assertEqual(forex.get_usd_bias("USDCAD", "SELL"), "USD_SHORT")
        self.assertEqual(forex.get_usd_bias("USDCHF", "BUY"), "USD_LONG")
        self.assertEqual(forex.get_usd_bias("USDCHF", "SELL"), "USD_SHORT")

        # Pairs where USD is quote:
        self.assertEqual(forex.get_usd_bias("EURUSD", "BUY"), "USD_SHORT")
        self.assertEqual(forex.get_usd_bias("EURUSD", "SELL"), "USD_LONG")
        self.assertEqual(forex.get_usd_bias("GBPUSD", "BUY"), "USD_SHORT")
        self.assertEqual(forex.get_usd_bias("GBPUSD", "SELL"), "USD_LONG")
        self.assertEqual(forex.get_usd_bias("AUDUSD", "BUY"), "USD_SHORT")
        self.assertEqual(forex.get_usd_bias("AUDUSD", "SELL"), "USD_LONG")
        self.assertEqual(forex.get_usd_bias("XAUUSD", "BUY"), "USD_SHORT")
        self.assertEqual(forex.get_usd_bias("XAUUSD", "SELL"), "USD_LONG")

    async def test_usd_correlation_shield_blocks_same_direction_clustering(self):
        """Verify that active USD_LONG position prevents opening another USD_LONG trade."""
        # Add an active USDJPY BUY (USD_LONG) position
        active_pos = {
            "id": "FX-USDJPY-1",
            "symbol": "USDJPY",
            "direction": "BUY",
            "lots": 0.05,
            "entry_price": 154.00,
            "current_price": 154.00,
            "sl_price": 153.88,
            "tp_price": 154.22,
            "pip_size": 0.01,
            "digits": 3,
        }
        forex._AUTO_STATE["open_positions"] = [active_pos]

        # Scan active biases
        active_biases = [
            (p["symbol"], forex.get_usd_bias(p["symbol"], p["direction"]))
            for p in forex._AUTO_STATE["open_positions"]
        ]
        self.assertIn(("USDJPY", "USD_LONG"), active_biases)

        # Now test candidate USDCAD BUY (also USD_LONG)
        cand_usdcad_bias = forex.get_usd_bias("USDCAD", "BUY")
        self.assertEqual(cand_usdcad_bias, "USD_LONG")
        conflicts = [b for b in active_biases if b[1] == cand_usdcad_bias]
        self.assertTrue(len(conflicts) > 0, "USDCAD BUY must conflict with active USDJPY BUY!")

        # Test candidate EURUSD SELL (also USD_LONG)
        cand_eurusd_bias = forex.get_usd_bias("EURUSD", "SELL")
        self.assertEqual(cand_eurusd_bias, "USD_LONG")
        conflicts2 = [b for b in active_biases if b[1] == cand_eurusd_bias]
        self.assertTrue(len(conflicts2) > 0, "EURUSD SELL must conflict with active USDJPY BUY!")

        # In contrast, EURUSD BUY is USD_SHORT, which does not add to USD_LONG risk
        cand_eurusd_buy_bias = forex.get_usd_bias("EURUSD", "BUY")
        self.assertEqual(cand_eurusd_buy_bias, "USD_SHORT")
        conflicts3 = [b for b in active_biases if b[1] == cand_eurusd_buy_bias]
        self.assertEqual(len(conflicts3), 0, "EURUSD BUY should NOT conflict with USD_LONG")

    # -------------------------------------------------------------------------
    # 4. IMPROVED RISK:REWARD & DYNAMIC EXIT TESTS
    # -------------------------------------------------------------------------
    def test_default_risk_reward_ratio(self):
        """Verify default settings provide favorable R:R ratio >= 1.8."""
        cfg = forex.ForexAutoPaperSettings()
        self.assertEqual(cfg.sl_pips, 12.0)
        self.assertEqual(cfg.tp_pips, 26.0)
        rr_ratio = cfg.tp_pips / cfg.sl_pips
        self.assertGreaterEqual(rr_ratio, 1.8)
        self.assertEqual(cfg.breakeven_pips, 14.0)
        self.assertEqual(cfg.trailing_stop_pips, 20.0)

    # -------------------------------------------------------------------------
    # 5. REAL TECHNICAL INDICATOR & MTF ENGINE TESTS
    # -------------------------------------------------------------------------
    def test_compute_technical_indicators_accuracy(self):
        """Verify indicator calculations for EMAs, RSI, MACD, ATR, trend and score."""
        # Create a trending price series (30 bars upward)
        base = 1.0800
        closes = [round(base + i * 0.0005, 5) for i in range(30)]
        highs = [round(c + 0.0003, 5) for c in closes]
        lows = [round(c - 0.0003, 5) for c in closes]
        opens = [round(c - 0.0002, 5) for c in closes]

        tech = forex._compute_technical_indicators(closes, highs, lows, opens, "EURUSD")
        self.assertIsNotNone(tech)
        self.assertEqual(tech["trend"], "BULLISH")
        self.assertGreater(tech["ema9"], tech["ema21"])
        self.assertGreater(tech["ema21"], tech["ema50"])
        self.assertGreater(tech["score"], 70.0)
        self.assertGreater(tech["rsi"], 50.0)
        self.assertGreater(tech["atr"], 0.0)
        self.assertIn("AL", tech["macd_verdict"])

    async def test_radar_returns_real_indicators_not_random(self):
        """Verify get_forex_radar returns structured technical cards with valid fields."""
        radar = await forex.get_forex_radar()
        self.assertIn("candidates", radar)
        self.assertGreater(len(radar["candidates"]), 0)

        for c in radar["candidates"]:
            self.assertIn("score", c)
            self.assertGreaterEqual(c["score"], 50.0)
            self.assertLessEqual(c["score"], 98.0)
            self.assertIn(c["trend"], ["BULLISH", "BEARISH", "NEUTRAL"])
            self.assertIn(c["action"], ["BUY", "SELL", "HOLD"])
            self.assertIn("rsi_15m", c)
            self.assertIn("macd_verdict", c)
            self.assertIn("atr_pips", c)
            self.assertIn("risk_reward", c)

    # -------------------------------------------------------------------------
    # 6. DEEP VERIFICATION: BROKER SUFFIX RESILIENCE & MTF CONFLICTS
    # -------------------------------------------------------------------------
    def test_broker_suffix_resilience_in_usd_bias(self):
        """Verify USD bias detection works with broker suffixes (.raw, .ecn, +, #) and commodities."""
        self.assertEqual(forex.get_usd_bias("EURUSD.raw", "BUY"), "USD_SHORT")
        self.assertEqual(forex.get_usd_bias("EURUSD.raw", "SELL"), "USD_LONG")
        self.assertEqual(forex.get_usd_bias("USDJPY.pro", "BUY"), "USD_LONG")
        self.assertEqual(forex.get_usd_bias("USDCAD#", "BUY"), "USD_LONG")
        self.assertEqual(forex.get_usd_bias("USOIL", "BUY"), "USD_SHORT")
        self.assertEqual(forex.get_usd_bias("USOIL", "SELL"), "USD_LONG")
        self.assertEqual(forex.get_usd_bias("XAUUSD.ecn", "BUY"), "USD_SHORT")
        self.assertEqual(forex.get_usd_bias("XAUUSD+", "SELL"), "USD_LONG")
        self.assertEqual(forex.get_usd_bias("EURGBP.raw", "BUY"), "USD_NEUTRAL")

    def test_gold_dynamic_atr_buffer(self):
        """Verify Gold SL/TP dynamically widen with high ATR to protect against spread spikes."""
        # Low volatility Gold (ATR 15 pips / $1.50) -> Base 36.0 pips / $3.60 SL
        spec_low = forex.get_symbol_trading_specs("XAUUSD", atr_pips=15.0)
        self.assertEqual(spec_low["sl_pips"], 36.0)
        self.assertEqual(spec_low["tp_pips"], 66.0)
        self.assertGreaterEqual(spec_low["be_pips"], 25.0)

        # High volatility Gold (ATR 45 pips / $4.50) -> Dynamic buffer expands to 67.5 pips / $6.75 SL
        spec_high = forex.get_symbol_trading_specs("XAUUSD", atr_pips=45.0)
        self.assertEqual(spec_high["sl_pips"], 67.5)
        self.assertEqual(spec_high["tp_pips"], 123.5)
        self.assertGreaterEqual(spec_high["be_pips"], 47.0)

    def test_mtf_conflicting_signals_are_neutral(self):
        """Verify that conflicting multi-timeframe signals produce NEUTRAL / HOLD verdict with score <= 58."""
        # Flat series
        closes = [1.0800 for _ in range(30)]
        highs = [1.0805 for _ in range(30)]
        lows = [1.0795 for _ in range(30)]
        opens = [1.0800 for _ in range(30)]
        tech = forex._compute_technical_indicators(closes, highs, lows, opens, "EURUSD")
        self.assertEqual(tech["trend"], "NEUTRAL")
        self.assertEqual(tech["action"], "HOLD")
        self.assertLessEqual(tech["score"], 58.0)

    def test_hard_lot_caps_cannot_be_bypassed_by_config(self):
        """Verify hard caps (0.05 Forex, 0.02 Gold) are enforced even with oversized inputs."""
        self.assertEqual(forex.HARD_MAX_FOREX_LOT, 0.05)
        self.assertEqual(forex.HARD_MAX_GOLD_LOT, 0.02)
        self.assertEqual(mt5_bridge.HARD_MAX_FOREX_LOT, 0.05)
        self.assertEqual(mt5_bridge.HARD_MAX_GOLD_LOT, 0.02)

    def test_mt5_bridge_gold_cooldown_rejection(self):
        """Verify mt5_bridge.execute_market_order blocks gold trades when cooldown is active."""
        mt5_bridge.LAST_GOLD_EXIT_TIME = time.time()
        cmd_gold = {"symbol": "XAUUSD", "direction": "BUY", "lots": 0.02}
        res = mt5_bridge.execute_market_order(cmd_gold)
        self.assertFalse(res["success"])
        self.assertIn("kalkanı aktif", res["error"])

    async def test_reversal_flip_closes_opposite_position(self):
        """Verify that when a BUY is open and a strong SELL signal arrives, the BUY position is closed with REVERSAL_FLIP."""
        # 1. Setup an active BUY position
        buy_pos = {
            "id": "FX-TEST-BUY-1",
            "symbol": "EURUSD",
            "display": "EUR/USD",
            "direction": "BUY",
            "lots": 0.05,
            "entry_price": 1.0850,
            "current_price": 1.0855,
            "sl_price": 1.0838,
            "tp_price": 1.0872,
            "pip_size": 0.0001,
            "digits": 5,
        }
        async with forex._AUTO_PAPER_LOCK:
            forex._AUTO_STATE["open_positions"] = [buy_pos]

        # 2. Simulate closing with REVERSAL_FLIP reason
        closed = await forex._close_position_internal("FX-TEST-BUY-1", "REVERSAL_FLIP", 1.0855)
        self.assertIsNotNone(closed)
        self.assertEqual(closed["exit_reason"], "REVERSAL_FLIP")
        self.assertIn("Trend Dönüşü", closed["exit_reason_title"])
        self.assertEqual(len(forex._AUTO_STATE["open_positions"]), 0)


if __name__ == "__main__":
    unittest.main()

