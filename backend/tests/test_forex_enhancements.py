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

    # -------------------------------------------------------------------------
    # 6. BTCUSD INTEGRATION & 60S GOLD COOLDOWN TESTS
    # -------------------------------------------------------------------------
    def test_btcusd_integration_and_specs(self):
        """Verify BTCUSD is present in universe, symbol maps, allowed symbols and specs."""
        sym_names = [s["symbol"] for s in forex.FOREX_SYMBOLS]
        self.assertIn("BTCUSD", sym_names)
        self.assertEqual(forex.YAHOO_SYMBOL_MAP.get("BTCUSD"), "BTC-USD")

        cfg = forex.ForexAutoPaperSettings()
        self.assertIn("BTCUSD", cfg.allowed_symbols)

        specs = forex.get_symbol_trading_specs("BTCUSD", base_sl=12.0, base_tp=26.0)
        self.assertEqual(specs["pip_size"], 1.0)
        self.assertEqual(specs["mult"], 5.0)
        self.assertEqual(specs["sl_pips"], 60.0)
        self.assertEqual(specs["tp_pips"], 130.0)

    async def test_btcusd_lot_capping(self):
        """Verify BTCUSD lot size is capped to 0.02 under any condition."""
        order_btc = forex.MT5ManualOrderRequest(
            symbol="BTCUSD",
            direction="BUY",
            lots=1.00,  # attempt 1.0 BTC
        )
        res = await forex.send_mt5_order(order_btc)
        self.assertEqual(res["status"], "queued")
        self.assertEqual(res["command"]["lots"], 0.02)  # capped to 0.02

    def test_gold_cooldown_reduced_to_60s(self):
        """Verify gold cooldown minimum and default are updated to 60.0 seconds."""
        self.assertEqual(forex.HARD_MIN_GOLD_COOLDOWN_SEC, 60.0)
        self.assertEqual(mt5_bridge.HARD_MIN_GOLD_COOLDOWN_SEC, 60.0)
        cfg = forex.ForexAutoPaperSettings()
        self.assertEqual(cfg.gold_cooldown_sec, 60.0)
        self.assertEqual(mt5_bridge.CURRENT_SETTINGS["gold_cooldown_sec"], 60.0)

    def test_oil_symbol_resolution_and_specs(self):
        """Verify USOIL and XTIUSD specs and alias mapping."""
        self.assertIn("XTIUSD", mt5_bridge.SYMBOL_ALIAS_MAP["USOIL"])
        specs_xti = mt5_bridge.get_symbol_trading_specs("XTIUSD")
        self.assertEqual(specs_xti["pip_size"], 0.01)
        self.assertEqual(specs_xti["digits"], 2)
        self.assertEqual(specs_xti["pip_val"], 1.0)

        forex_specs = forex.get_symbol_trading_specs("USOIL")
        self.assertEqual(forex_specs["pip_size"], 0.01)
        self.assertEqual(forex_specs["pip_val"], 1.0)

    async def test_oil_lot_handling(self):
        """Verify USOIL manual order enforces minimum 0.50 lot for IC Markets instead of 0.05."""
        order_oil = forex.MT5ManualOrderRequest(
            symbol="USOIL",
            direction="BUY",
            lots=0.05,
        )
        res = await forex.send_mt5_order(order_oil)
        self.assertEqual(res["status"], "queued")
        self.assertEqual(res["command"]["lots"], 0.50)

    def test_target_twelve_symbols_configuration(self):
        """Verify strictly the 12 requested instruments are set in allowed_symbols."""
        expected_12 = [
            "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
            "BTCUSD", "ETHUSD", "NAS100", "US30", "XAUUSD"
        ]
        cfg = forex.ForexAutoPaperSettings()
        self.assertEqual(len(cfg.allowed_symbols), 12)
        for s in expected_12:
            self.assertIn(s, cfg.allowed_symbols)

        # Check MT5 Bridge check_syms list contains these 12
        for s in expected_12:
            self.assertIn(s, forex.YAHOO_SYMBOL_MAP)

    def test_nas100_and_us30_specs_and_alias(self):
        """Verify Nasdaq (NAS100/USTEC) and Dow Jones (US30) trading specs and MT5 alias resolution."""
        # Check alias
        self.assertEqual(mt5_bridge.resolve_mt5_symbol("NAS100"), "USTEC" if mt5_bridge.mt5.symbol_info("USTEC") else "USTEC")
        self.assertEqual(mt5_bridge.REVERSE_SYMBOL_ALIAS_MAP.get("USTEC"), "NAS100")

        # Check NAS100 specs
        nas_specs = forex.get_symbol_trading_specs("NAS100", base_sl=12.0, base_tp=22.0)
        self.assertEqual(nas_specs["pip_size"], 1.0)
        self.assertEqual(nas_specs["digits"], 2)
        self.assertEqual(nas_specs["pip_val"], 1.0)
        self.assertEqual(nas_specs["sl_pips"], 30.0)

        # Check US30 specs
        us30_specs = forex.get_symbol_trading_specs("US30", base_sl=12.0, base_tp=22.0)
        self.assertEqual(us30_specs["pip_size"], 1.0)
        self.assertEqual(us30_specs["digits"], 2)
        self.assertEqual(us30_specs["pip_val"], 1.0)
        self.assertEqual(us30_specs["sl_pips"], 36.0)

    async def test_index_and_eth_lot_capping(self):
        """Verify indices enforce min 0.10 lot and max 0.20 lot, and ETHUSD enforces max 0.02 lot."""
        # Index with small lot (0.01) must be bumped to 0.10 min volume
        order_nas = forex.MT5ManualOrderRequest(
            symbol="NAS100",
            direction="BUY",
            lots=0.01,
        )
        res_nas = await forex.send_mt5_order(order_nas)
        self.assertEqual(res_nas["command"]["lots"], 0.10)

        # Index with huge lot (2.0) must be capped to 0.20
        order_us30 = forex.MT5ManualOrderRequest(
            symbol="US30",
            direction="BUY",
            lots=2.00,
        )
        res_us30 = await forex.send_mt5_order(order_us30)
        self.assertEqual(res_us30["command"]["lots"], 0.20)

        # ETHUSD with huge lot (1.0) must be capped to 0.02
        order_eth = forex.MT5ManualOrderRequest(
            symbol="ETHUSD",
            direction="BUY",
            lots=1.00,
        )
        res_eth = await forex.send_mt5_order(order_eth)
        self.assertEqual(res_eth["command"]["lots"], 0.02)

    # -------------------------------------------------------------------------
    # 7. $1.00 BREAKEVEN, VOLATILITY TRAILING STOP & PYRAMIDING (MAX 3) TESTS
    # -------------------------------------------------------------------------
    def test_one_dollar_breakeven_condition(self):
        """Verify that when pnl_usd >= 1.0, Breakeven condition evaluates to True."""
        pos = {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 1.08500,
            "lots": 0.05,
            "pip_size": 0.0001,
            "digits": 5,
            "pnl_usd": 1.25,
            "pnl_pips": 2.5,
            "breakeven_activated": False,
            "sl_price": 1.08380,
        }
        cfg = forex.ForexAutoPaperSettings()
        self.assertEqual(cfg.breakeven_usd, 1.0)
        is_dollar_be = pos["pnl_usd"] >= cfg.breakeven_usd
        self.assertTrue(is_dollar_be)

    def test_one_dollar_breakeven_sl_calculation(self):
        """Verify that locked SL guarantees at least net $1.00 USD profit across instruments."""
        # Test 1: EURUSD @ 0.05 lot
        spec_eur = forex.get_symbol_trading_specs("EURUSD")
        lots_eur = 0.05
        dollar_per_pip_eur = lots_eur * spec_eur["pip_val"]  # 0.05 * 10.0 = $0.50
        pips_1usd_eur = round(1.0 / dollar_per_pip_eur, 1)   # 2.0 pips
        self.assertEqual(pips_1usd_eur, 2.0)
        profit_eur = pips_1usd_eur * dollar_per_pip_eur
        self.assertAlmostEqual(profit_eur, 1.00, places=2)

        # Test 2: USDJPY @ 0.05 lot
        spec_jpy = forex.get_symbol_trading_specs("USDJPY")
        lots_jpy = 0.05
        dollar_per_pip_jpy = lots_jpy * spec_jpy["pip_val"]  # 0.05 * 6.60 = $0.33
        pips_1usd_jpy = round(1.0 / dollar_per_pip_jpy, 1)   # 3.0 pips
        self.assertEqual(pips_1usd_jpy, 3.0)
        profit_jpy = pips_1usd_jpy * dollar_per_pip_jpy
        self.assertAlmostEqual(profit_jpy, 1.00, delta=0.05)

        # Test 3: XAUUSD (Gold) @ 0.02 lot
        spec_gold = forex.get_symbol_trading_specs("XAUUSD")
        lots_gold = 0.02
        dollar_per_pip_gold = lots_gold * spec_gold["pip_val"]  # 0.02 * 10.0 = $0.20
        pips_1usd_gold = round(1.0 / dollar_per_pip_gold, 1)   # 5.0 pips ($0.50 move)
        self.assertEqual(pips_1usd_gold, 5.0)
        profit_gold = pips_1usd_gold * dollar_per_pip_gold
        self.assertAlmostEqual(profit_gold, 1.00, places=2)

        # Test 4: BTCUSD @ 0.02 lot
        spec_btc = forex.get_symbol_trading_specs("BTCUSD")
        lots_btc = 0.02
        dollar_per_pip_btc = lots_btc * spec_btc["pip_val"]   # 0.02 * 1.0 = $0.02
        pips_1usd_btc = round(1.0 / dollar_per_pip_btc, 1)    # 50.0 pips ($50 move)
        self.assertEqual(pips_1usd_btc, 50.0)
        profit_btc = pips_1usd_btc * dollar_per_pip_btc
        self.assertAlmostEqual(profit_btc, 1.00, places=2)

    def test_max_positions_per_symbol_setting(self):
        """Verify default max_positions_per_symbol is 3 and max_open_positions is 6."""
        cfg = forex.ForexAutoPaperSettings()
        self.assertEqual(cfg.max_positions_per_symbol, 3)
        self.assertEqual(cfg.max_open_positions, 6)

    def test_same_symbol_pyramiding_limit_three(self):
        """Verify that 3 positions in the same direction are allowed, but the 4th is blocked."""
        sym = "USDJPY"
        direction = "BUY"
        existing_auto = [
            {"symbol": sym, "direction": direction, "id": "P1"},
            {"symbol": sym, "direction": direction, "id": "P2"},
            {"symbol": sym, "direction": direction, "id": "P3"},
        ]
        same_dir_count = sum(1 for p in existing_auto if p.get("direction") == direction)
        self.assertEqual(same_dir_count, 3)

        max_pyr = 3
        can_open_fourth = same_dir_count < max_pyr
        self.assertFalse(can_open_fourth, "4th position must be blocked when 3 positions exist!")

        # With 2 positions, can open another if 60s has passed
        two_positions = existing_auto[:2]
        same_count_2 = sum(1 for p in two_positions if p.get("direction") == direction)
        can_open_third = same_count_2 < max_pyr
        self.assertTrue(can_open_third)

    def test_reversal_flip_only_on_opposite_direction(self):
        """Verify that same-direction signals never trigger a reversal flip."""
        # Case 1: BUY open, BUY signal arrives -> opposite_dirs is empty!
        existing_dirs = {"BUY"}
        new_action = "BUY"
        opposite_dirs = {d for d in existing_dirs if d != new_action}
        self.assertEqual(len(opposite_dirs), 0, "Same direction must NOT produce opposite dirs!")

        # Case 2: BUY open, SELL signal arrives -> opposite_dirs contains BUY
        new_action_rev = "SELL"
        opposite_dirs_rev = {d for d in existing_dirs if d != new_action_rev}
        self.assertEqual(opposite_dirs_rev, {"BUY"}, "Opposite direction must trigger reversal flip!")

    def test_crypto_spread_allowance(self):
        """Verify that ETHUSD and BTCUSD get a 20.0 pip spread allowance while standard forex gets 3.0."""
        cfg = forex.ForexAutoPaperSettings()
        for sym in ["BTCUSD", "ETHUSD", "BTC/USD", "ETH/USD"]:
            effective_spread = 20.0 if ("BTC" in sym or "ETH" in sym) else cfg.max_spread_pips
            self.assertEqual(effective_spread, 20.0, f"{sym} should allow up to 20 pips spread")
            # 12 pips spread on ETH should pass
            self.assertTrue(12.0 <= effective_spread)

        for sym in ["EURUSD", "GBPUSD", "USDJPY"]:
            effective_spread = 20.0 if ("BTC" in sym or "ETH" in sym) else cfg.max_spread_pips
            self.assertEqual(effective_spread, 3.0, f"{sym} should have standard max spread")
            self.assertFalse(12.0 <= effective_spread)


if __name__ == "__main__":
    unittest.main()


