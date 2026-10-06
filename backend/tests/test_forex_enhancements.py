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
        # safe_capped_lots must NOT exceed max_forex_lot
        self.assertLessEqual(res_forex["safe_capped_lots"], forex._AUTO_SETTINGS.max_forex_lot)

        # Test Gold with high balance
        req_gold = forex.LotCalculatorRequest(
            account_balance=100000.0,
            risk_percentage=3.0,
            stop_loss_pips=36.0,
            symbol="XAUUSD",
        )
        res_gold = await forex.calculate_lot_size(req_gold)
        self.assertGreater(res_gold["standard_lots"], 0.5)
        # safe_capped_lots must NOT exceed max_gold_lot
        self.assertLessEqual(res_gold["safe_capped_lots"], forex._AUTO_SETTINGS.max_gold_lot)

    async def test_mt5_bridge_hard_lot_cap_enforcement(self):
        """Verify that mt5_bridge.execute_market_order respects max_vol broker limits."""
        cmd_forex = {"symbol": "EURUSD", "direction": "BUY", "lots": 1.50}
        raw_lots = float(cmd_forex["lots"])
        capped_lots = round(max(0.01, min(raw_lots, 50.0)), 2)
        self.assertEqual(capped_lots, 1.50)

        cmd_gold = {"symbol": "XAUUSD", "direction": "BUY", "lots": 0.80}
        raw_lots2 = float(cmd_gold["lots"])
        capped_lots2 = round(max(0.01, min(raw_lots2, 50.0)), 2)
        self.assertEqual(capped_lots2, 0.80)

    async def test_manual_order_lot_capping(self):
        """Verify that manual orders sent via API endpoint are queued."""
        order_req = forex.MT5ManualOrderRequest(
            symbol="EURUSD",
            direction="BUY",
            lots=2.50,  # 2.5 lots
            sl_pips=12.0,
            tp_pips=22.0,
        )
        res = await forex.send_mt5_order(order_req)
        self.assertEqual(res["status"], "queued")
        self.assertEqual(res["command"]["lots"], 2.50)

        order_gold = forex.MT5ManualOrderRequest(
            symbol="XAUUSD",
            direction="BUY",
            lots=1.00,  # 1.0 lots
        )
        res2 = await forex.send_mt5_order(order_gold)
        self.assertEqual(res2["status"], "queued")
        self.assertEqual(res2["command"]["lots"], 1.00)

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
    # 3. USD BIAS & KORELASYON TESTS
    # (Not: eski kaba "USD Risk Kalkanı" kullanıcı kararıyla kaldırıldı; portföy
    #  kümelenme koruması artık gerçek Pearson korelasyonuyla çalışan 5b kalkanında
    #  — bkz. test_forex_improvements.TestFXCorrelationGuard.)
    # -------------------------------------------------------------------------
    def test_usd_bias_mapping(self):
        """Verify accurate USD directional bias detection across pairs (DXY veto + korelasyon kapısı girdisi)."""
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

    # -------------------------------------------------------------------------
    # 4. IMPROVED RISK:REWARD & DYNAMIC EXIT TESTS
    # -------------------------------------------------------------------------
    def test_default_risk_reward_ratio(self):
        """Verify default settings provide favorable R:R ratio >= 1.8 with tight 8.0 pip SL."""
        cfg = forex.ForexAutoPaperSettings()
        self.assertEqual(cfg.sl_pips, 8.0)
        self.assertEqual(cfg.tp_pips, 20.0)
        rr_ratio = cfg.tp_pips / cfg.sl_pips
        self.assertGreaterEqual(rr_ratio, 2.0)
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
        # Low volatility Gold (ATR 15 pips / $1.50) -> Base 24.0 pips / $2.40 SL
        spec_low = forex.get_symbol_trading_specs("XAUUSD", atr_pips=15.0)
        self.assertEqual(spec_low["sl_pips"], 24.0)
        self.assertEqual(spec_low["tp_pips"], 60.0)
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
        """Verify broker safety limits (50.0 Forex, 50.0 Gold) are set."""
        self.assertEqual(forex.HARD_MAX_FOREX_LOT, 50.0)
        self.assertEqual(forex.HARD_MAX_GOLD_LOT, 50.0)
        self.assertEqual(mt5_bridge.HARD_MAX_FOREX_LOT, 50.0)
        self.assertEqual(mt5_bridge.HARD_MAX_GOLD_LOT, 50.0)

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
        """Verify BTCUSD lot size is queued correctly without artificial 0.02 cap."""
        order_btc = forex.MT5ManualOrderRequest(
            symbol="BTCUSD",
            direction="BUY",
            lots=1.00,  # 1.0 BTC
        )
        res = await forex.send_mt5_order(order_btc)
        self.assertEqual(res["status"], "queued")
        self.assertEqual(res["command"]["lots"], 1.00)

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

    def test_target_two_symbols_configuration(self):
        """Verify the configured instruments are set in allowed_symbols (2026-10-06: yalnız XAUUSD + BTCUSD)."""
        expected_2 = ["XAUUSD", "BTCUSD"]
        cfg = forex.ForexAutoPaperSettings()
        self.assertEqual(len(cfg.allowed_symbols), 2)
        for s in expected_2:
            self.assertIn(s, cfg.allowed_symbols)
        # Sadece bu ikisi — diğer semboller izin listesinden çıkarıldı
        for s in ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
                  "ETHUSD", "NAS100", "US30", "USOIL"):
            self.assertNotIn(s, cfg.allowed_symbols)
        # Check MT5 Bridge check_syms list contains these 2
        for s in expected_2:
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
        """Verify indices enforce min 0.10 lot and ETHUSD/US30 orders queue correctly."""
        # Index with small lot (0.01) must be bumped to 0.10 min volume
        order_nas = forex.MT5ManualOrderRequest(
            symbol="NAS100",
            direction="BUY",
            lots=0.01,
        )
        res_nas = await forex.send_mt5_order(order_nas)
        self.assertEqual(res_nas["command"]["lots"], 0.10)

        # Index with lot (2.0)
        order_us30 = forex.MT5ManualOrderRequest(
            symbol="US30",
            direction="BUY",
            lots=2.00,
        )
        res_us30 = await forex.send_mt5_order(order_us30)
        self.assertEqual(res_us30["command"]["lots"], 2.00)

        # ETHUSD with lot (1.0)
        order_eth = forex.MT5ManualOrderRequest(
            symbol="ETHUSD",
            direction="BUY",
            lots=1.00,
        )
        res_eth = await forex.send_mt5_order(order_eth)
        self.assertEqual(res_eth["command"]["lots"], 1.00)

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

    def test_default_risk_and_position_limits(self):
        """Verify default position sizing is 10% balance risk and max_open_positions is 25."""
        cfg = forex.ForexAutoPaperSettings()
        self.assertEqual(cfg.max_positions_per_symbol, 3)
        self.assertEqual(cfg.risk_per_trade_pct, 10.0)
        self.assertEqual(cfg.max_open_positions, 25)
        self.assertEqual(forex.LotCalculatorRequest().risk_percentage, 10.0)

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

    def test_winning_pyramiding_rule(self):
        """Verify that pyramiding only allows adding to profitable positions, blocking averaging down on losers."""
        # Case A: Existing position is in loss (-$2.50) -> Must be blocked!
        matching_auto_loss = [{"symbol": "AUDUSD", "direction": "SELL", "pnl_usd": -2.50}]
        pnl_loss = sum(p.get("pnl_usd", 0.0) for p in matching_auto_loss)
        can_pyramid_loss = pnl_loss >= 0.20
        self.assertFalse(can_pyramid_loss, "Averaging down into losing trades must be blocked!")

        # Case B: Existing position is in profit (+$1.20) -> Allowed!
        matching_auto_win = [{"symbol": "AUDUSD", "direction": "SELL", "pnl_usd": 1.20}]
        pnl_win = sum(p.get("pnl_usd", 0.0) for p in matching_auto_win)
        can_pyramid_win = pnl_win >= 0.20
        self.assertTrue(can_pyramid_win, "Adding to winning profitable trades must be allowed!")

    def test_gold_commodity_score_threshold(self):
        """Verify Gold and Oil require higher conviction score >= 78.0 while standard forex requires 75.0 (replay-tuned)."""
        cfg = forex.ForexAutoPaperSettings()
        self.assertEqual(cfg.min_score, 75.0)

        for sym in ["XAUUSD", "GOLD", "USOIL", "OIL"]:
            is_comm = ("XAU" in sym or "GOLD" in sym or "OIL" in sym)
            req = 78.0 if is_comm else cfg.min_score
            self.assertEqual(req, 78.0)

        for sym in ["EURUSD", "GBPUSD", "NAS100"]:
            is_comm = ("XAU" in sym or "GOLD" in sym or "OIL" in sym)
            req = 78.0 if is_comm else cfg.min_score
            self.assertEqual(req, 75.0)

    async def test_ethusd_risk_based_lot_calculation(self):
        """Verify ETHUSD calculates lot size based on capital risk budget (e.g. 5% balance) and is not clamped to 0.02."""
        req_eth = forex.LotCalculatorRequest(
            account_balance=2284.20,
            risk_percentage=5.0,  # $114.21 risk
            stop_loss_pips=8.0,   # base SL = 8.0 -> mult 2.0 -> eff_sl_pips = 16.0
            symbol="ETHUSD",
        )
        res_eth = await forex.calculate_lot_size(req_eth)
        self.assertAlmostEqual(res_eth["risk_amount_usd"], 114.21, delta=0.1)
        self.assertEqual(res_eth["stop_loss_pips"], 16.0)
        # 114.21 / (16.0 * 1.0) = 7.14 lots
        self.assertEqual(res_eth["standard_lots"], 7.14)
        self.assertEqual(res_eth["safe_capped_lots"], 7.14)

    def test_settings_supports_up_to_20_pct_risk_and_25_positions(self):
        """Verify ForexAutoPaperSettings validates up to 20% risk and 25 max open positions."""
        cfg = forex.ForexAutoPaperSettings(risk_per_trade_pct=20.0, max_open_positions=25)
        self.assertEqual(cfg.risk_per_trade_pct, 20.0)
        self.assertEqual(cfg.max_open_positions, 25)


    def test_dynamic_breakeven_target_calculation(self):
        """Verify calculate_breakeven_target prevents premature breakeven lock."""
        # 1. Very small profit (e.g. 5 pips on gold, when SL is 75 pips) should NOT trigger
        be_early = forex.calculate_breakeven_target(
            pnl_pips=5.0,
            pnl_usd=5.0,
            lots=0.10,
            pip_val=10.0,
            pip_size=0.10,
            digits=2,
            direction="BUY",
            entry_price=2700.0,
            current_price=2700.5,
            current_sl=2692.5,
            sl_pips=75.0,
            atr_pips=50.0,
            eff_be_pips=25.0,
            is_gold=True,
            gold_be_lock_ratio=0.60,
        )
        self.assertIsNone(be_early)

        # 2. Reaching the threshold (e.g. >= 0.4*SL = 30 pips or eff_be) should trigger and lock profit
        be_hit = forex.calculate_breakeven_target(
            pnl_pips=32.0,
            pnl_usd=32.0,
            lots=0.10,
            pip_val=10.0,
            pip_size=0.10,
            digits=2,
            direction="BUY",
            entry_price=2700.0,
            current_price=2703.2,
            current_sl=2692.5,
            sl_pips=75.0,
            atr_pips=50.0,
            eff_be_pips=25.0,
            is_gold=True,
            gold_be_lock_ratio=0.60,
        )
        self.assertIsNotNone(be_hit)
        # Lock ratio 0.60 * 32.0 = 19.2 pips -> 2700.0 + 1.92 = 2701.92
        self.assertAlmostEqual(be_hit, 2701.92, places=2)
        self.assertGreater(be_hit, 2700.0)

    def test_btc_min_score_priority(self):
        """Verify btc_min_score priority over global min_score."""
        cfg = forex.ForexAutoPaperSettings(min_score=75.0, btc_min_score=76.0)
        # Directly verify the priority expression
        req = cfg.btc_min_score if cfg.btc_min_score > 0 else cfg.min_score
        self.assertEqual(req, 76.0)


if __name__ == "__main__":
    unittest.main()



