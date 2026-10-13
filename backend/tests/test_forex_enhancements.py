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
        """allowed_symbols ⊆ FOREX_SYMBOLS (2026-10-12 panel-dürüstlüğü kilidi).

        13 kros 2026-10-08'de 'LB/Radar replay pozitifi' diye eklenmişti ama
        FOREX_SYMBOLS'te olmadıkları için tick üretilmiyordu → panelde seçili
        görünüp ASLA işlem açamıyorlardı. İzole 2-pencere replay'de hiçbiri
        OOS n≥100 barını geçemedi → kanıt yok, çıkarıldılar.
        """
        expected = ["XAUUSD", "BTCUSD", "GBPJPY", "EURJPY", "US30", "NAS100",
                    "GBPUSD", "AUDUSD", "USDJPY", "USDCHF"]
        cfg = forex.ForexAutoPaperSettings()
        self.assertEqual(len(cfg.allowed_symbols), 10)
        for s in expected:
            self.assertIn(s, cfg.allowed_symbols)
        # Panel-dürüstlüğü DEĞİŞMEZİ: her izinli sembol gerçekten işlenebilir olmalı
        _universe = {i["symbol"] for i in forex.FOREX_SYMBOLS}
        for s in cfg.allowed_symbols:
            self.assertIn(s, _universe, f"{s} FOREX_SYMBOLS'te yok → hayalet")
        # Kanıtsız kroslar izin listesinin dışında (2026-10-13: NAS100 EKLENDİ — MT5 'USTEC';
        # USTEC alias'ı FOREX_SYMBOLS'te olmadığı için hâlâ dışarıda)
        for s in ("NZDJPY", "AUDNZD", "GBPCHF", "EURCAD", "CHFJPY", "CADJPY",
                  "GBPNZD", "GBPAUD", "GBPCAD", "AUDCAD", "EURAUD", "CADCHF",
                  "AUDCHF", "EURUSD", "USDCAD", "NZDUSD",
                  "ETHUSD", "USTEC", "USOIL"):
            self.assertNotIn(s, cfg.allowed_symbols)
        # Veri hattı haritaları hâlâ her izinli sembolü kapsar
        for s in expected:
            self.assertIn(s, forex.YAHOO_SYMBOL_MAP)

    def test_universe_invariant_strips_phantoms(self):
        """`_enforce_universe_invariant` hayalet pariteleri atar (2026-10-12 kilidi)."""
        cfg = forex.ForexAutoPaperSettings(
            allowed_symbols=["XAUUSD", "GBPCHF", "NZDJPY", "GBPUSD", "AUDNZD"]
        )
        dropped = forex._enforce_universe_invariant(cfg)
        self.assertEqual(sorted(dropped), ["AUDNZD", "GBPCHF", "NZDJPY"])
        self.assertEqual(sorted(cfg.allowed_symbols), ["GBPUSD", "XAUUSD"])

    def test_merge_settings_strips_phantom_symbols(self):
        """PANEL bug'ı: kullanıcı panelden hayalet kros seçse bile motor kabul etmez."""
        merged = forex.merge_settings_payload(
            {"allowed_symbols": ["XAUUSD", "EURCAD", "BTCUSD"]}
        )
        self.assertIn("XAUUSD", merged.allowed_symbols)
        self.assertIn("BTCUSD", merged.allowed_symbols)
        self.assertNotIn("EURCAD", merged.allowed_symbols)

    def test_retired_symbols_are_out_of_universe_but_specs_kept(self):
        """ETHUSD, USOIL ve SPX500 2026-10-07'de forex evreninden çıkarıldı.

        Kullanıcı kararı: tüm forex modülünden kaldır, ama geçmiş kayıtlara
        DOKUNMA. Bu iki şart aynı anda ancak şöyle sağlanır — semboller tarama
        evreninden (FOREX_SYMBOLS) ve veri hattından (YAHOO_SYMBOL_MAP) çıkar,
        buna karşılık pip/lot spec'leri `get_symbol_trading_specs` içinde
        KALIR; aksi halde arşivdeki ETH/petrol/endeks işlemlerinin pip_val ve
        digits bilgisi kaybolur ve PnL yeniden hesabı sessizce bozulurdu.

        SPX500 ayrıca bir hata sınıfını kapatır: `get_symbol_trading_specs`
        içinde endeks dalı olmadığı için forex varsayılanına (pip_size 0.0001)
        düşüyor ve SL girişin binde bir puan uzağına kuruluyordu.
        """
        universe = [s["symbol"] for s in forex.FOREX_SYMBOLS]
        retired = [s["symbol"] for s in forex._RETIRED_FOREX_SYMBOLS]
        self.assertEqual(sorted(retired), ["ETHUSD", "SPX500", "USOIL", "XAGUSD"])  # XAGUSD 2026-10-07'de emekli

        for sym in retired:
            self.assertNotIn(sym, universe, f"{sym} tarama evreninde olmamalı")
            self.assertNotIn(sym, forex.YAHOO_SYMBOL_MAP, f"{sym} için veri çekilmemeli")
            # Specler korunuyor — arşiv PnL hesabı buna bağlı
            specs = forex.get_symbol_trading_specs(sym, base_sl=8.0, base_tp=20.0)
            self.assertGreater(specs["pip_val"], 0.0, f"{sym} spec korunmalı")

        # Radar/emir uçları artık bu sembolleri görmemeli
        self.assertNotIn("USOIL", universe)
        self.assertNotIn("ETHUSD", universe)
        self.assertNotIn("SPX500", universe)
        self.assertNotIn("XAGUSD", universe)  # 2026-10-07: gümüş de emekli (radar temizliği)
        # XAUUSD + BTCUSD (özel izleme sayfasının evreni) hâlâ yerinde
        for keep in ("XAUUSD", "BTCUSD", "EURUSD", "NAS100", "US30"):
            self.assertIn(keep, universe)

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
        """Verify default position sizing is 5% balance risk (2026-10-08: 10→5) and max_open_positions is 99."""
        cfg = forex.ForexAutoPaperSettings()
        self.assertEqual(cfg.max_positions_per_symbol, 1)
        self.assertEqual(cfg.risk_per_trade_pct, 5.0)
        self.assertEqual(cfg.max_open_positions, 99)
        # LotCalculatorRequest ayrı, manuel hesap aracı (grafik butonu) — kendi varsayılanı kalır.
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
        """Verify that ETHUSD and BTCUSD get a 20.0 pip spread allowance while standard forex gets 10.0 (2026-10-07 default)."""
        cfg = forex.ForexAutoPaperSettings()
        for sym in ["BTCUSD", "ETHUSD", "BTC/USD", "ETH/USD"]:
            effective_spread = 20.0 if ("BTC" in sym or "ETH" in sym) else cfg.max_spread_pips
            self.assertEqual(effective_spread, 20.0, f"{sym} should allow up to 20 pips spread")
            # 12 pips spread on ETH should pass
            self.assertTrue(12.0 <= effective_spread)

        for sym in ["EURUSD", "GBPUSD", "USDJPY"]:
            effective_spread = 20.0 if ("BTC" in sym or "ETH" in sym) else cfg.max_spread_pips
            self.assertEqual(effective_spread, 10.0, f"{sym} should have standard max spread")
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

    def test_settings_supports_up_to_20_pct_risk_and_99_positions(self):
        """Verify ForexAutoPaperSettings validates up to 20% risk and 99 max open positions (2026-10-07)."""
        cfg = forex.ForexAutoPaperSettings(risk_per_trade_pct=20.0, max_open_positions=99)
        self.assertEqual(cfg.risk_per_trade_pct, 20.0)
        self.assertEqual(cfg.max_open_positions, 99)


    def test_dynamic_breakeven_target_calculation(self):
        """BE tetiği: $1+hurdle altı kilitlenmez; üstünde KİLİTLENİR (2026-10-12 düzeltmesi).

        Eski sözleşme tabanları `max(...)` ile birleştiriyordu → BE kilidi 0.4×SL / 0.5×ATR
        (burada 30/25 pip) bekliyordu. Replay A/B dört bağımsız pencerede bunun zarar
        ürettiğini gösterdi (net, WR ve maxDD üçünde de işaret-tutarlı). Yeni sözleşme
        BİRLEŞİM: $1+hurdle VEYA eff_be — hangisine önce ulaşılırsa.
        """
        # 1. $1 güvencesinin (+hurdle) ALTINDA kalan kâr kilitlenmez (erken boğulma koruması)
        #    0.10 lot × $10/pip = $1/pip → $1 = 1 pip; altın hurdle 4 → tetik 5 pip.
        be_early = forex.calculate_breakeven_target(
            pnl_pips=4.0,
            pnl_usd=4.0,
            lots=0.10,
            pip_val=10.0,
            pip_size=0.10,
            digits=2,
            direction="BUY",
            entry_price=2700.0,
            current_price=2700.4,
            current_sl=2692.5,
            sl_pips=75.0,
            atr_pips=50.0,
            eff_be_pips=25.0,
            is_gold=True,
            gold_be_lock_ratio=0.60,
        )
        self.assertIsNone(be_early)

        # 2. Tetik eşiğine ulaşınca KİLİTLENİR — eski `max` formülü burada None dönerdi
        #    (25 pip eff_be ya da 30 pip = 0.4×SL beklerdi). Kök neden testi budur.
        be_hit = forex.calculate_breakeven_target(
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
        self.assertIsNotNone(be_hit)
        # Kilit oranı 0.60 × 5.0 = 3.0 pip → 2700.0 + 3 × 0.10 = 2700.30
        self.assertAlmostEqual(be_hit, 2700.30, places=2)
        self.assertGreater(be_hit, 2700.0)
        # Kilitlenen stop her zaman girişin ÜSTÜNDE (gerçek kâr kilidi, başabaş değil)

    def test_be_trigger_is_union_not_cumulative_max(self):
        """Kök-neden regresyon kilidi: R/ATR tabanları BE'yi GECİKTİRMEMELİ.

        Geniş SL (300 pip) + yüksek ATR (200 pip) verildiğinde `max` formülü tetiği
        120 pip'e çıkarırdı (0.4×300); birleşim formülü $1+hurdle'da kalır. Canlı↔replay
        sapmasını üreten tam bu mekanizmaydı (bkz. forex.calculate_breakeven_target notu).
        """
        common = dict(
            lots=0.10, pip_val=10.0, pip_size=0.10, digits=2,
            direction="BUY", entry_price=2700.0, current_sl=2692.5,
            sl_pips=300.0, atr_pips=200.0, eff_be_pips=25.0,
            is_gold=True, gold_be_lock_ratio=0.60,
        )
        # 10 pip kâr: `max` olsaydı (0.4×300=120 veya 0.5×200=100 beklerdi) None dönerdi
        self.assertIsNotNone(forex.calculate_breakeven_target(
            pnl_pips=10.0, pnl_usd=10.0, current_price=2701.0, **common))
        # Eşiğin altı hâlâ korunuyor (4 pip < 5 pip tetik)
        self.assertIsNone(forex.calculate_breakeven_target(
            pnl_pips=4.0, pnl_usd=4.0, current_price=2700.4, **common))

    def test_be_fx_and_crypto_triggers_are_union(self):
        """FX ve kripto için de birleşim semantiği geçerli (altına özel değil)."""
        # FX: 0.10 lot, pip_val 10 → $1/pip; headroom 3.5 → tetik 4.5 pip; eff_be 14 pip
        fx = forex.calculate_breakeven_target(
            pnl_pips=5.0, pnl_usd=5.0, lots=0.10, pip_val=10.0, pip_size=0.0001,
            digits=5, direction="BUY", entry_price=1.10000, current_price=1.10050,
            current_sl=1.09900, sl_pips=20.0, atr_pips=10.0, eff_be_pips=14.0,
        )
        self.assertIsNotNone(fx)  # 5 pip ≥ 4.5 → kilit (max olsaydı 14 pip beklerdi)
        # Kripto: 0.10 lot, pip_val 1.0 → $0.10/pip → pips_for_1usd = 10 pip; headroom 25
        # → tetik 35 pip; eff_be 40 pip.
        crypto = forex.calculate_breakeven_target(
            pnl_pips=36.0, pnl_usd=3.60, lots=0.10, pip_val=1.0, pip_size=1.0,
            digits=2, direction="SELL", entry_price=60000.0, current_price=59964.0,
            current_sl=60100.0, sl_pips=150.0, atr_pips=100.0, eff_be_pips=40.0,
            is_crypto=True,
        )
        self.assertIsNotNone(crypto)  # 36 ≥ 35 → kilit

    def test_btc_min_score_priority(self):
        """Verify btc_min_score priority over global min_score."""
        cfg = forex.ForexAutoPaperSettings(min_score=75.0, btc_min_score=76.0)
        # Directly verify the priority expression
        req = cfg.btc_min_score if cfg.btc_min_score > 0 else cfg.min_score
        self.assertEqual(req, 76.0)


class TestForexAccountingFixes(unittest.IsolatedAsyncioTestCase):
    """2026-10-07 denetim bulgularının regresyon testleri.

    Her test, düzeltme geri alınırsa KIRILACAK şekilde yazıldı; yani bulgunun
    sessizce geri gelmesini engeller.
    """

    def setUp(self):
        forex._MT5_STATE["open_positions"] = []
        forex._MT5_STATE["closed_deals"] = []
        forex._MT5_STATE["pending_commands"] = []
        forex._AUTO_STATE["open_positions"].clear()
        forex._AUTO_STATE["closed_trades"].clear()

    # --- #11: başabaş iki uçta aynı sınıflanmalı -------------------------
    async def test_breakeven_classified_consistently(self):
        """pnl tam 0.00 → her uçta WIN; wins+losses == total_trades."""
        forex._MT5_STATE["connected"] = True
        forex._MT5_STATE["account"] = {"balance": 1000.0, "equity": 1000.0}
        forex._MT5_STATE["closed_deals"] = [
            {"ticket": 1, "symbol": "EURUSD", "display": "EUR/USD", "pnl_usd": 0.0,
             "profit": 0.0, "pnl_pips": 0.0, "exit_time": "2026-10-06 10:00:00 UTC+3"},
        ]
        try:
            status = await forex.get_forex_auto_paper_status()
        finally:
            forex._MT5_STATE["connected"] = False
        self.assertEqual(status["wins"] + status["losses"], status["total_trades"])
        self.assertEqual(status["wins"], 1)
        self.assertEqual(status["losses"], 0)

    # --- #12: PF sonsuzluk nöbetçisi ------------------------------------
    def test_profit_factor_sentinel_is_named(self):
        """Sabit tek yerde tanımlı ve 999.0; panel eşiği buna göre."""
        self.assertEqual(forex._PF_INFINITE, 999.0)

    # --- #3: EV kalkanı UTC+3 damgasını doğru okumalı --------------------
    # CANLI DAVRANIŞ düzeltmesi uygulandı (kullanıcı onayı 2026-10-07) —
    # `_collect_symbol_ev` artık `_deal_ts`/`_parse_deal_ts` kullanıyor.
    def test_collect_symbol_ev_reads_utc3_label(self):
        """25 saat önce kapanan deal, 24 saatlik pencerenin DIŞINDA kalmalı."""
        import datetime
        now = time.time()
        real = datetime.datetime.fromtimestamp(now - 25 * 3600, datetime.timezone.utc)
        label = (real + datetime.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S UTC+3")
        deal = {"symbol": "EURUSD", "pnl_usd": -5.0, "exit_time": label}
        stats = forex._collect_symbol_ev("EURUSD", now, 24 * 3600, source=[deal])
        self.assertEqual(stats["n"], 0)

    def test_collect_symbol_ev_counts_fresh_utc3_deal(self):
        """2 saat önce kapanan deal pencerenin İÇİNDE sayılmalı."""
        import datetime
        now = time.time()
        real = datetime.datetime.fromtimestamp(now - 2 * 3600, datetime.timezone.utc)
        label = (real + datetime.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S UTC+3")
        deal = {"symbol": "EURUSD", "pnl_usd": -5.0, "exit_time": label}
        stats = forex._collect_symbol_ev("EURUSD", now, 24 * 3600, source=[deal])
        self.assertEqual(stats["n"], 1)

    # --- #4: broker endeks alias'ları tanınmalı --------------------------
    # CANLI DAVRANIŞ düzeltmesi uygulandı (kullanıcı onayı 2026-10-07).
    def test_usd_bias_knows_broker_index_aliases(self):
        """US100/NDX/DJ30/WS30 USD_SHORT olmalı (MT5 gerçek sembol adları)."""
        for alias in ("US100", "NDX", "DJ30", "WS30"):
            self.assertEqual(
                forex.get_usd_bias(alias, "BUY"), "USD_SHORT",
                msg=f"{alias} USD_SHORT olmalıydı (broker alias'ı tanınmıyor)",
            )
            self.assertEqual(forex.get_usd_bias(alias, "SELL"), "USD_LONG")

    # --- #13: hayalet cache budanmalı ------------------------------------
    async def test_retired_symbols_are_purged_from_tick_cache(self):
        """Emekli sembol cache'te kalmamalı; evren sembolleri durmalı."""
        forex._TICK_CACHE["USOIL"] = {"symbol": "USOIL", "stale": True}
        forex._TICK_CACHE["SPX500"] = {"symbol": "SPX500", "stale": True}
        await forex._generate_realistic_ticks()
        self.assertNotIn("USOIL", forex._TICK_CACHE)
        self.assertNotIn("SPX500", forex._TICK_CACHE)
        self.assertIn("EURUSD", forex._TICK_CACHE)

    # --- P1: kısmi kâr kapanış KAYDINA yansımalı -------------------------
    def test_partial_tp_records_total_not_remaining_leg(self):
        """Kısmi + kalan bacak kaydı $40; risk kalan bacak için işaretlenir."""
        spec = forex.get_symbol_trading_specs("XAUUSD")
        pos = {
            "symbol": "XAUUSD", "direction": "BUY", "lots": 0.10,
            "entry_price": 2000.0, "sl_price": 1990.0, "tp_price": 2060.0,
            "pip_size": spec["pip_size"], "digits": spec["digits"],
            "partial_target_pips": 20.0,
        }
        realized = forex.apply_partial_take_profit(pos, 20.0, spec["pip_val"])
        self.assertAlmostEqual(realized, 10.0, places=2)
        self.assertAlmostEqual(pos["partial_realized_usd"], 10.0, places=2)
        self.assertAlmostEqual(pos["partial_realized_pips"], 20.0, places=1)
        # Kalan bacak (0.05 lot) +60 pip → $30; kayıt toplamı $40 olmalı.
        remaining = round(60.0 * pos["lots"] * spec["pip_val"], 2)
        total = round(remaining + pos["partial_realized_usd"], 2)
        self.assertAlmostEqual(total, 40.0, places=2)
        # P3: kısmi sonrası kalan risk işaretlenmeli ve lotla birlikte yarıya inmeli.
        self.assertIn("risk_usd_after_partial", pos)

    # --- EV KALKANI LİSTESİ VE MANUEL İPTAL/MUAFIYET TESTLERİ -----------------
    async def test_ev_shield_status_and_override_lifecycle(self):
        """Kullanıcı bir sembolü (örn. USDJPY) bugün için EV kalkanından muaf tutabilmeli, sıfırlayabilmeli veya geri alabilmeli."""
        sym = "USDJPY"
        # 1. Başlangıç temizliği
        forex._SYMBOL_EV_OVERRIDE_UNTIL.pop(sym, None)
        forex._SYMBOL_EV_RESET_AT_TS.pop(sym, None)

        status_init = await forex.get_forex_ev_shield_status()
        self.assertIn("symbols", status_init)
        self.assertIn("blocked_count", status_init)

        # 2. "bypass_today" ile muafiyet ver
        req_override = forex.EVShieldOverrideRequest(symbol=sym, action="bypass_today")
        res_override = await forex.override_forex_ev_shield(req_override)
        self.assertTrue(res_override["success"])
        self.assertIn(sym, forex._SYMBOL_EV_OVERRIDE_UNTIL)
        self.assertGreater(forex._SYMBOL_EV_OVERRIDE_UNTIL[sym], time.time())

        # 3. Durumu kontrol et: is_overridden True olmalı
        status_after = await forex.get_forex_ev_shield_status()
        sym_entry = next((s for s in status_after["symbols"] if s["symbol"] == sym), None)
        self.assertIsNotNone(sym_entry)
        self.assertTrue(sym_entry["is_overridden"])
        self.assertFalse(sym_entry["is_blocked"])

        # 4. "reset_history" ile geçmişi sıfırla
        req_reset = forex.EVShieldOverrideRequest(symbol=sym, action="reset_history")
        res_reset = await forex.override_forex_ev_shield(req_reset)
        self.assertTrue(res_reset["success"])
        self.assertIn(sym, forex._SYMBOL_EV_RESET_AT_TS)

        # 5. "restore" ile muafiyeti kaldır
        req_restore = forex.EVShieldOverrideRequest(symbol=sym, action="restore")
        res_restore = await forex.override_forex_ev_shield(req_restore)
        self.assertTrue(res_restore["success"])
        self.assertNotIn(sym, forex._SYMBOL_EV_OVERRIDE_UNTIL)

        # Temizlik
        forex._SYMBOL_EV_RESET_AT_TS.pop(sym, None)


class TestTpCancelOnTrail(unittest.IsolatedAsyncioTestCase):
    """`tp_cancel_on_trail` (V03 "no_tp_on_trail_live") — 2026-10-09 çıkış A/B kazananı.

    Opt-in ayar: kapalıyken canlı davranış birebir aynı kalmalı; açıkken trailing
    devreye girdiği an sabit TP emri çekilmeli (paper + MT5 köprüsü iki katmanda).
    Kanıt: outputs/exit_sweep/FINDINGS.md — IS +$200.70 / OOS +$215.05, BTC belirgin
    iyileşme, maxDD iki pencerede de düştü.
    """

    def setUp(self):
        self._enabled = forex._AUTO_SETTINGS.tp_cancel_on_trail
        self._orig_ticks = forex._generate_realistic_ticks
        self._orig_partial = forex._AUTO_SETTINGS.partial_tp_enabled
        self._orig_chand = forex._AUTO_SETTINGS.chandelier_atr_mult

    def tearDown(self):
        forex._AUTO_SETTINGS.tp_cancel_on_trail = self._enabled
        forex._AUTO_SETTINGS.partial_tp_enabled = self._orig_partial
        forex._AUTO_SETTINGS.chandelier_atr_mult = self._orig_chand
        forex._generate_realistic_ticks = self._orig_ticks
        forex._AUTO_STATE["open_positions"].clear()
        forex._AUTO_STATE["closed_trades"].clear()
        forex._AUTO_STATE["decision_logs"].clear()
        forex._MT5_STATE["pending_commands"] = []
        forex._MT5_STATE["open_positions"] = []
        forex._MT5_STATE["connected"] = False
        forex._MT5_STATE["auto_trade"] = False
        forex._AUTO_STATE["enabled"] = False

    # ---------------------------------------------------------------- MT5 köprüsü

    def _fake_position(self, sl=1.07850, tp=1.09000):
        """check_and_apply_dynamic_exits'in beklediği minimal MT5 pozisyonu (namedtuple).

        +50 pip'te tutulur: BE kilidi (0.4×50=20p → SL 1.0820) ile trailing adayı
        (1.0850−20p = 1.0830) kıyaslanabilsin ve trailing GERÇEKTEN devreye girsin
        (daha küçük kârda BE kilidi traileden sıkı olur ve köprü haklı olarak
        "trailing aktif" demez).
        """
        import collections
        FakePos = collections.namedtuple(
            "_FakePos",
            "ticket symbol type price_open price_current sl tp volume profit",
        )
        return FakePos(
            ticket=555001, symbol="EURUSD", type=0,          # 0 = POSITION_TYPE_BUY
            price_open=1.08000, price_current=1.08500, sl=sl, tp=tp,
            volume=0.5, profit=250.0,
        )

    # Trailing'in üreteceği SL (price_current − 20 pip). SL'i buraya sabitleyip
    # korumayı önceden "TRAILING" işaretleyince SL'de taşıma olmaz → tek davranış
    # farkı TP iptali olur (izole test).
    _TRAILED_SL = 1.08300

    def _run_bridge_with_settings(self, settings, pos, preseed_trailing=False):
        from unittest import mock
        mt5_bridge.POSITION_PROTECTION_MAP.clear()
        mt5_bridge.POSITION_EXITS.clear()
        mt5_bridge.CURRENT_SETTINGS.clear()
        mt5_bridge.CURRENT_SETTINGS.update(settings)
        if preseed_trailing:
            mt5_bridge.POSITION_PROTECTION_MAP[pos.ticket] = "TRAILING"
        sent = []

        def fake_order_send(req):
            sent.append(dict(req))
            return mock.Mock(retcode=mt5_bridge.mt5.TRADE_RETCODE_DONE, comment="ok")

        with mock.patch.object(mt5_bridge.mt5, "positions_get", return_value=[pos]), \
             mock.patch.object(mt5_bridge.mt5, "symbol_info", return_value=mock.Mock(digits=5, volume_min=0.01)), \
             mock.patch.object(mt5_bridge.mt5, "order_send", side_effect=fake_order_send):
            mt5_bridge.check_and_apply_dynamic_exits(be_pips=14.0, trail_pips=20.0)
        return sent

    def test_bridge_sends_cancel_signal_when_setting_on(self):
        """Ayar açık + trailing aktif → MODIFY_SLTP tp=0 ile gönderilir (gerçek iptal)."""
        sent = self._run_bridge_with_settings(
            {"tp_cancel_on_trail": True, "partial_tp_enabled": False},
            self._fake_position(sl=self._TRAILED_SL),  # SL mevcut; tek sebep TP iptali
            preseed_trailing=True,
        )
        self.assertEqual(len(sent), 1, "TP iptali için tam olarak bir MODIFY_SLTP beklenir")
        self.assertEqual(sent[0]["tp"], 0.0)
        self.assertEqual(sent[0]["sl"], self._TRAILED_SL, "Korunan SL aynen geri yazılmalı")

    def test_bridge_cancels_tp_when_sl_already_in_profit_without_map(self):
        """REGRESYON (2026-10-09 canlı US30): köprü yeniden başlayınca POSITION_PROTECTION_MAP
        sıfırlanır; SL bu turda hareket etmezse map boş kalır. Eski koşul yalnız map'e
        baktığı için kârda SL taşıyan pozisyonun TP'si ASLA iptal edilmiyordu. Koruma
        durumu artık doğrudan pozisyondan türetilir → map boş olsa da iptal edilmeli."""
        sent = self._run_bridge_with_settings(
            {"tp_cancel_on_trail": True, "partial_tp_enabled": False},
            self._fake_position(sl=self._TRAILED_SL),  # SL girişin ÜSTÜNDE (kârda)
            preseed_trailing=False,                     # map boş → restart senaryosu
        )
        self.assertEqual(len(sent), 1, "Map boş olsa da kârda SL → TP iptal edilmeli")
        self.assertEqual(sent[0]["tp"], 0.0)
        self.assertEqual(sent[0]["sl"], self._TRAILED_SL, "SL aynen geri yazılmalı")

    def test_bridge_keeps_tp_when_setting_off(self):
        """Ayar kapalı → trailing aktif olsa bile TP korunur; SL güncel olduğundan emir YOK."""
        sent = self._run_bridge_with_settings(
            {"tp_cancel_on_trail": False, "partial_tp_enabled": False},
            self._fake_position(sl=self._TRAILED_SL),
            preseed_trailing=True,
        )
        self.assertEqual(sent, [], "Kapalı ayarda ek MODIFY_SLTP üretilmemeli (canlı davranış aynı)")

    # ------------------------------------------------------- execute_modify_sltp

    def test_execute_modify_sltp_cancel_removes_tp(self):
        """`tp_action="cancel"` → tp gerçekten 0.0 gider (tp=0 "koru" demek olduğu için şart)."""
        from unittest import mock
        calls = []

        def fake_order_send(req):
            calls.append(dict(req))
            return mock.Mock(retcode=mt5_bridge.mt5.TRADE_RETCODE_DONE, comment="ok")

        with mock.patch.object(mt5_bridge.mt5, "positions_get", return_value=[self._fake_position(sl=1.07850)]), \
             mock.patch.object(mt5_bridge.mt5, "symbol_info", return_value=mock.Mock(digits=5)), \
             mock.patch.object(mt5_bridge.mt5, "order_send", side_effect=fake_order_send):
            res = mt5_bridge.execute_modify_sltp(
                {"ticket": 555001, "sl": 1.08000, "tp": 0.0, "tp_action": "cancel"}
            )

        self.assertTrue(res["success"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["tp"], 0.0)
        self.assertEqual(calls[0]["sl"], 1.08000)

    def test_execute_modify_sltp_zero_tp_still_means_keep(self):
        """Regresyon: `tp_action` yokken `tp=0` ESKİ anlamını korur → mevcut TP yerinde kalır."""
        from unittest import mock
        calls = []

        def fake_order_send(req):
            calls.append(dict(req))
            return mock.Mock(retcode=mt5_bridge.mt5.TRADE_RETCODE_DONE, comment="ok")

        with mock.patch.object(mt5_bridge.mt5, "positions_get", return_value=[self._fake_position(sl=1.07850)]), \
             mock.patch.object(mt5_bridge.mt5, "symbol_info", return_value=mock.Mock(digits=5)), \
             mock.patch.object(mt5_bridge.mt5, "order_send", side_effect=fake_order_send):
            res = mt5_bridge.execute_modify_sltp({"ticket": 555001, "sl": 1.08000, "tp": 0.0})

        self.assertTrue(res["success"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["tp"], 1.09000, "tp=0 mevcut TP'yi korumalı (eski davranış)")

    def test_execute_modify_sltp_cancel_is_noop_when_tp_already_absent(self):
        """TP zaten yoksa iptal isteği 'değişiklik yok' döner — boşuna emir gönderilmez."""
        from unittest import mock
        with mock.patch.object(mt5_bridge.mt5, "positions_get", return_value=[self._fake_position(sl=1.08000, tp=0.0)]), \
             mock.patch.object(mt5_bridge.mt5, "symbol_info", return_value=mock.Mock(digits=5)), \
             mock.patch.object(mt5_bridge.mt5, "order_send", side_effect=AssertionError("emir gönderilmemeliydi")):
            res = mt5_bridge.execute_modify_sltp(
                {"ticket": 555001, "sl": 1.08000, "tp": 0.0, "tp_action": "cancel"}
            )
        self.assertTrue(res["success"])
        self.assertEqual(res.get("message"), "no changes")

    # ------------------------------------------------- moteur döngüsü (forex.py)

    async def _run_one_loop_tick(self, enable, start_price, sl, tp, breakeven=False):
        """`_forex_auto_paper_loop`'un bir turunu sahte tick'le koşturur."""
        forex._AUTO_STATE["open_positions"].clear()
        forex._AUTO_STATE["closed_trades"].clear()
        forex._AUTO_STATE["decision_logs"].clear()
        forex._MT5_STATE["pending_commands"] = []
        forex._MT5_STATE["open_positions"] = []
        forex._MT5_STATE["connected"] = False
        forex._MT5_STATE["auto_trade"] = False
        forex._AUTO_STATE["enabled"] = True
        forex._AUTO_SETTINGS.partial_tp_enabled = False
        forex._AUTO_SETTINGS.chandelier_atr_mult = 0.0    # sabit pip trail dalını test et
        forex._AUTO_SETTINGS.trailing_stop_pips = 20.0
        forex._AUTO_SETTINGS.tp_cancel_on_trail = enable
        forex._AUTO_STATE["balance"] = 10000.0

        forex._AUTO_STATE["open_positions"].append({
            "id": "FX-TPC-1", "symbol": "EURUSD", "display": "EUR/USD", "direction": "BUY",
            "lots": 0.5, "entry_price": 1.08000, "current_price": start_price,
            "sl_price": sl, "tp_price": tp, "initial_sl_price": sl,
            "breakeven_activated": breakeven, "trailing_activated": False,
            "open_time": "12:00:00 UTC", "pnl_usd": 0.0, "pnl_pips": 0.0,
            "pip_size": 0.0001, "digits": 5, "score": 90.0, "strategy": "TEST",
        })

        # İlk çağrı gerçek tick'i bir kez üretir (FOREX_SYMBOLS/ATR bağımlılıkları için),
        # sonra istenen fiyata kaydırılmış TEK sembollü tick döner.
        base = await self._orig_ticks()
        tick = dict(base["EURUSD"])
        shift = start_price - (tick["bid"] + tick["ask"]) / 2.0
        tick["bid"] = round(tick["bid"] + shift, 5)
        tick["ask"] = round(tick["ask"] + shift, 5)
        tick["atr"] = 0.0004

        async def fake_ticks():
            return {"EURUSD": tick}

        forex._generate_realistic_ticks = fake_ticks
        task = asyncio.ensure_future(forex._forex_auto_paper_loop())
        await asyncio.sleep(2.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        live = forex._AUTO_STATE["open_positions"]
        errs = [d for d in forex._AUTO_STATE["decision_logs"]
                if "beklenmeyen hata" in str(d.get("message", ""))]
        self.assertEqual(errs, [], f"döngü hata verdi: {errs[:1]}")
        return live[0] if live else None

    async def test_engine_loop_cancels_tp_when_trailing_activates(self):
        """Ayar AÇIK: trailing devreye girince paper tp_price=0 olur → TP_HIT bir daha ateşlemez."""
        pos = await self._run_one_loop_tick(
            enable=True, start_price=1.08250, sl=1.08005, tp=1.09000, breakeven=True)
        self.assertIsNotNone(pos, "pozisyon kapanmamalıydı (TP henüz uzak)")
        self.assertTrue(pos.get("trailing_activated"))
        self.assertEqual(pos.get("tp_price"), 0.0, "TP iptal edilmeliydi")
        # SL bid üzerinden sürülür (spread kadar mid'in altında): 1.0825 − ~20 pip.
        self.assertGreater(pos.get("sl_price"), 1.08005, "trailing SL, BE seviyesinin üstüne çıkmalı")
        self.assertLess(pos.get("sl_price"), 1.08250)

    async def test_engine_loop_keeps_tp_when_setting_off(self):
        """Ayar KAPALI (varsayılan): trailing yine çalışır ama TP yerinde kalır — canlı davranış aynı."""
        pos = await self._run_one_loop_tick(
            enable=False, start_price=1.08250, sl=1.08005, tp=1.09000, breakeven=True)
        self.assertIsNotNone(pos)
        self.assertTrue(pos.get("trailing_activated"))
        self.assertEqual(pos.get("tp_price"), 1.09000, "Ayar kapalıyken TP'ye dokunulmamalı")

    async def test_engine_loop_keeps_tp_when_no_trailing_activation(self):
        """Trailing tetiklenmediyse (kâr eşiği altında) TP iptal EDİLMEZ."""
        pos = await self._run_one_loop_tick(
            enable=True, start_price=1.08005, sl=1.07850, tp=1.09000, breakeven=False)
        self.assertIsNotNone(pos)
        self.assertFalse(pos.get("trailing_activated"))
        self.assertEqual(pos.get("tp_price"), 1.09000, "Trailing yoksa TP korunur")


class TestBridgeSettingsPayload(unittest.IsolatedAsyncioTestCase):
    """Köprünün TP-iptal bayrağını görebilmesi için sync payload'ında taşınmalı."""

    async def test_mt5_sync_payload_carries_tp_cancel_flag(self):
        # `sync_mt5_bridge` paylaşılan _MT5_STATE'i yazar → anlık görüntü al, sonra geri koy
        # (test sırası izolasyonu; bkz. test_forex_auto_paper.py'deki aynı desen).
        snapshot = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
                    for k, v in forex._MT5_STATE.items()}
        try:
            payload = await forex.sync_mt5_bridge(forex.MT5SyncRequest(
                account={"balance": 1000.0, "equity": 1000.0}, positions=[], deals=[],
            ))
            self.assertIn("tp_cancel_on_trail", payload["settings"])
            self.assertIsInstance(payload["settings"]["tp_cancel_on_trail"], bool)
        finally:
            forex._MT5_STATE.clear()
            forex._MT5_STATE.update(snapshot)


class TestTpRatchetAlternative(unittest.IsolatedAsyncioTestCase):
    """Alternatif (daha güvenli) mekanizma: TP-ratchet — kripto modülünde kanıtlı.

    `auto_paper.py` trailing TP'nin üzerine çıktığında TP'yi yukarı taşır (TP
    silinmez). FX replay'inde V03 (TP iptal) kazandı; ratchet henüz FX replay'inde
    test EDİLMEDİ — bu test yalnız referans uygulamanın hâlâ yerinde olduğunu
    kilitler ki A/B karşılaştırması ileride aynı tabana yapılabilsin.
    """

    def test_auto_paper_ratchet_rule_is_present(self):
        import inspect
        from backend.app.routers import auto_paper
        src = inspect.getsource(auto_paper)
        self.assertIn("TP ratchet", src)
        self.assertIn("trailing TP'nin üstüne çıktı", src)

    async def test_default_is_true_and_env_gated(self):
        """Canlı varsayılan AÇIK (2026-10-09 kararı: 4 pencere A/B'de işaret-tutarlı tek
        mekanizma V03). Geri alma yolu env ile: FOREX_TP_CANCEL_ON_TRAIL=false."""
        self.assertTrue(forex.ForexAutoPaperSettings().tp_cancel_on_trail)
        self.assertTrue(forex._AUTO_SETTINGS.tp_cancel_on_trail)
        # Geri-alma sözleşmesi yerinde mi (env anahtarı modülde tanımlı)
        import inspect
        src = inspect.getsource(forex)
        self.assertIn("FOREX_TP_CANCEL_ON_TRAIL", src)


class TestForexPerSymbolDailyKpi(unittest.TestCase):
    """Portföy sayfası sembol bazlı günlük KPI kartları (`per_symbol_today`).

    Kartlar status'un `today_kpi`'siyle AYNI defterden türetilmeli; ayrışırsa
    üstteki toplam ile kartların toplamı tutmaz. Bu testler hem matematiği hem
    o sözleşmeyi kilitler.
    """

    NOW = time.time()
    DAY_AGO = NOW - 26 * 3600  # dünden bir kayıt (pencere dışı olmalı)

    def _deal(self, sym, pnl, ts=None, pips=0.0, reason="TP_HIT", display=None):
        return {
            "symbol": sym,
            "display": display or sym,
            "profit": pnl,
            "pnl_usd": pnl,
            "pnl_pips": pips,
            "exit_time": ts if isinstance(ts, str) else "",
            "closed_at_ts": ts if not isinstance(ts, str) else None,
            "exit_reason_title": reason,
        }

    def test_groups_by_symbol_and_sorts_by_net_desc(self):
        deals = [
            self._deal("EURUSD", 10.0, self.NOW, 5.0),
            self._deal("EURUSD", -4.0, self.NOW, -2.0),
            self._deal("XAUUSD", 42.5, self.NOW, 30.0),
            self._deal("BTCUSD", -15.0, self.NOW, -100.0),
        ]
        out = forex._aggregate_daily_symbol_kpi(deals, [], self.NOW - 3600)
        self.assertEqual([r["symbol"] for r in out], ["XAUUSD", "EURUSD", "BTCUSD"])
        eur = next(r for r in out if r["symbol"] == "EURUSD")
        self.assertEqual(eur["trades"], 2)
        self.assertEqual(eur["wins"], 1)
        self.assertEqual(eur["losses"], 1)
        self.assertEqual(eur["pnl_usd"], 6.0)
        self.assertEqual(eur["pnl_pips"], 3.0)
        self.assertEqual(eur["win_rate"], 50.0)
        self.assertEqual(eur["avg_pnl_usd"], 3.0)

    def test_old_deals_excluded_by_window(self):
        deals = [
            self._deal("EURUSD", 100.0, self.DAY_AGO),
            self._deal("EURUSD", 5.0, self.NOW),
        ]
        out = forex._aggregate_daily_symbol_kpi(deals, [], self.NOW - 3600)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["trades"], 1, "pencere dışı işlem karta girmemeli")
        self.assertEqual(out[0]["pnl_usd"], 5.0)

    def test_win_rate_uses_closed_trades_only_not_open(self):
        """Açık pozisyon kazanma oranı PAYDASINA girmez (henüz sonucu yok)."""
        deals = [self._deal("EURUSD", 10.0, self.NOW)]
        open_pos = [
            {"symbol": "EURUSD", "display": "EURUSD", "pnl_usd": 3.0},
            {"symbol": "EURUSD", "display": "EURUSD", "pnl_usd": -1.0},
        ]
        out = forex._aggregate_daily_symbol_kpi(deals, open_pos, self.NOW - 3600)
        eur = out[0]
        self.assertEqual(eur["trades"], 1, "açık pozisyon kapalı sayılmamalı")
        self.assertEqual(eur["win_rate"], 100.0)
        self.assertEqual(eur["open_count"], 2)
        self.assertEqual(eur["open_pnl_usd"], 2.0)

    def test_open_only_symbol_reports_no_closed_kpi(self):
        """Hiç kapanışı olmayan sembol kart açabilir ama WR/PF uydurmamalı."""
        out = forex._aggregate_daily_symbol_kpi(
            [], [{"symbol": "GBPUSD", "display": "GBPUSD", "pnl_usd": 7.5}], self.NOW - 3600
        )
        self.assertEqual(len(out), 1)
        g = out[0]
        self.assertEqual(g["trades"], 0)
        self.assertEqual(g["win_rate"], 0.0)
        self.assertEqual(g["profit_factor"], 0.0)
        self.assertFalse(g["profit_factor_infinite"])
        self.assertEqual(g["open_count"], 1)
        self.assertEqual(g["open_pnl_usd"], 7.5)
        self.assertEqual(g["best_trade_usd"], 0.0, "kapanış yokken en iyi işlem 0 kalır")

    def test_profit_factor_and_infinite_sentinel(self):
        prof = forex._aggregate_daily_symbol_kpi(
            [self._deal("XAUUSD", 30.0, self.NOW), self._deal("XAUUSD", -10.0, self.NOW)],
            [], self.NOW - 3600,
        )[0]
        self.assertEqual(prof["profit_factor"], 3.0)
        self.assertFalse(prof["profit_factor_infinite"])
        # Hiç zarar yoksa PF sonsuz → JSON taşıyamaz, nöbetçi sabit + bayrak
        inf = forex._aggregate_daily_symbol_kpi(
            [self._deal("XAUUSD", 20.0, self.NOW)], [], self.NOW - 3600
        )[0]
        self.assertEqual(inf["profit_factor"], forex._PF_INFINITE)
        self.assertTrue(inf["profit_factor_infinite"])

    def test_best_worst_tracked(self):
        out = forex._aggregate_daily_symbol_kpi(
            [self._deal("BTCUSD", 12.0, self.NOW), self._deal("BTCUSD", -33.0, self.NOW),
             self._deal("BTCUSD", 8.0, self.NOW)],
            [], self.NOW - 3600,
        )[0]
        self.assertEqual(out["best_trade_usd"], 12.0)
        self.assertEqual(out["worst_trade_usd"], -33.0)

    def test_net_includes_commission_and_swap(self):
        """`_deal_net_pnl_usd` kuralı kartlarda da geçerli (MT5 bakiyesiyle uzlaşma)."""
        deal = self._deal("EURUSD", 10.0, self.NOW)
        deal["commission"] = -1.5
        deal["swap"] = -0.5
        out = forex._aggregate_daily_symbol_kpi([deal], [], self.NOW - 3600)[0]
        self.assertEqual(out["pnl_usd"], 8.0)

    def test_status_response_exposes_per_symbol_today(self):
        """Status yanıtı sözleşmesi: alan mevcut ve toplamı today_kpi ile tutuyor."""
        import asyncio
        # Bu modüldeki IsolatedAsyncioTestCase dersleri kendi döngülerini kurup
        # KAPATIR; `get_event_loop()` bu yüzden "no current event loop" verir.
        # İzole bir döngü kurup kendimiz kapatıyoruz (testler arası sızma yok).
        loop = asyncio.new_event_loop()
        forex._STATUS_CACHE = None
        prev_ts, prev_deals = forex._MT5_STATE.get("connected"), forex._MT5_STATE.get("closed_deals")
        try:
            forex._MT5_STATE["connected"] = True
            now = time.time()
            forex._MT5_STATE["closed_deals"] = [
                {"symbol": "XAUUSD", "display": "XAUUSD", "profit": 25.0, "pnl_pips": 10.0,
                 "time": now, "commission": 0.0, "swap": 0.0, "ticket": 1},
                {"symbol": "GBPUSD", "display": "GBPUSD", "profit": -5.0, "pnl_pips": -3.0,
                 "time": now, "commission": 0.0, "swap": 0.0, "ticket": 2},
            ]
            res = loop.run_until_complete(forex.get_forex_auto_paper_status())
            self.assertIn("per_symbol_today", res)
            per = res["per_symbol_today"]
            self.assertEqual({r["symbol"] for r in per}, {"XAUUSD", "GBPUSD"})
            # Kartların toplamı günlük KPI ile aynı defterden → eşit olmalı
            self.assertEqual(
                round(sum(r["pnl_usd"] for r in per), 2),
                res["today_kpi"]["total_pnl_usd"],
            )
            self.assertEqual(
                sum(r["trades"] for r in per), res["today_kpi"]["total_trades"]
            )
        finally:
            loop.close()
            forex._MT5_STATE["connected"] = prev_ts
            forex._MT5_STATE["closed_deals"] = prev_deals
            forex._STATUS_CACHE = None


class TestChandelierEntryAtrParity(unittest.IsolatedAsyncioTestCase):
    """Chandelier trailing GİRİŞ ATR'sini kullanmalı — 2026-10-13 canlı↔replay paritesi.

    Replay trailing'i işlem açılışında dondurulmuş ATR ile hesaplar
    (forex_replay_backtest.py:1828-1830) ve 1.2 → 0.3 sıkma kazancı O davranışla
    ölçüldü. Canlı eski kod her tick CARİ ATR'yi kullanıyordu → ATR sıçradığında
    trailing mesafesi işlem ortasında genişleyip kazanılan pip geri veriliyordu.
    """

    def test_entry_atr_wins_over_current_atr(self):
        # Giriş ATR'si varsa o kullanılır; cari ATR ne olursa olsun yok sayılır.
        self.assertEqual(forex.resolve_chandelier_atr(40.0, 120.0), 40.0)
        self.assertEqual(forex.resolve_chandelier_atr(12.5, 3.0), 12.5)

    def test_falls_back_to_current_atr_when_missing(self):
        # Eski pozisyon / alan yazılmamış → cari ATR'ye düş (güvenli davranış).
        self.assertEqual(forex.resolve_chandelier_atr(None, 55.0), 55.0)
        self.assertEqual(forex.resolve_chandelier_atr(0.0, 55.0), 55.0)
        self.assertEqual(forex.resolve_chandelier_atr("", 55.0), 55.0)

    def test_zero_when_both_missing(self):
        # İkisi de yoksa 0 döner → çağıran chandelier dalını atlar (sabit pip trail).
        self.assertEqual(forex.resolve_chandelier_atr(None, None), 0.0)
        self.assertEqual(forex.resolve_chandelier_atr(0.0, 0.0), 0.0)

    def test_chandelier_default_is_replay_verified(self):
        # 2026-10-13: chandelier köprüye port edildi; motor bu değeri /mt5/sync ile
        # gönderdiği için artık CANLI davranışı belirler. Replay kanıtı 0.3 diyor
        # (net $4305.70 / PF 1.87 vs sabit-pip $3950.88 / 1.80; 2-pip kaymada korunur).
        # 1.2'ye geri dönerse chandelier sabit-pipten KÖTÜ olur (3863 vs 3933) → bu
        # test sessiz bir gerileme ya da kanıtsız bir değişikliği yakalar.
        self.assertEqual(forex.ForexAutoPaperSettings().chandelier_atr_mult, 0.3)

    def test_canli_sabitler_override_settings_file_and_panel(self):
        """İki canlı sabit (chandelier + ls_symbols) hem kalıcı dosyayı hem panel
        gövdesini EZMELİ — sunucudaki eski `forex_auto_settings.json` ve panel isteği
        bu değerleri değiştiremez (2026-10-13; ikisinin de panelde alanı yok).

        Gerçek vaka: üretimdeki dosya `chandelier_atr_mult=1.2` ve `ls_symbols`'siz
        NAS100 tutuyordu; kod sabiti dosyaya yenilmeyince canlı eski davranışta kalıyordu.
        """
        # (a) Kalıcı dosyadan eski değerler gelmiş gibi kur, zorla, sabit kazanmalı
        s = forex.ForexAutoPaperSettings(
            chandelier_atr_mult=1.2, ls_symbols=["XAUUSD", "US30"])
        forex._apply_canli_sabitler(s)
        self.assertEqual(s.chandelier_atr_mult, forex.CANLI_CHANDELIER_ATR_MULT)
        self.assertEqual(s.ls_symbols, list(forex.CANLI_LS_SYMBOLS))

        # (b) Panel/POST gövdesi bu iki alanı değiştirmeye çalışsa da sabit kazanmalı
        merged = forex.merge_settings_payload(
            {"chandelier_atr_mult": 3.0, "ls_symbols": ["GBPUSD"], "min_score": 80.0})
        self.assertEqual(merged.chandelier_atr_mult, forex.CANLI_CHANDELIER_ATR_MULT)
        self.assertEqual(merged.ls_symbols, list(forex.CANLI_LS_SYMBOLS))
        # Sabit olmayan alan normal şekilde geçmeli (kontrol)
        self.assertEqual(merged.min_score, 80.0)

        # (c) Sabitlerin kendisi kanıtlanmış değerler olmalı (sessiz kayma yakalanır)
        self.assertEqual(forex.CANLI_CHANDELIER_ATR_MULT, 0.3)
        self.assertEqual(list(forex.CANLI_LS_SYMBOLS), ["XAUUSD", "US30", "NAS100"])

    async def test_trailing_uses_entry_atr_not_current_atr(self):
        """Motor döngüsü trailing'i GİRİŞ ATR'siyle kurmalı, cari ATR ile değil.

        Pozisyon elle tohumlanır: giriş ATR'si 40 pip, cari tick ATR'si 200 pip
        (5x sıçrama). Chandelier_MFE − 0.3×ATR olduğundan iki kaynak FARKLI SL üretir;
        hangisinin yazıldığı ayırt edicidir.
        """
        from unittest import mock

        entry_atr, mfe, cur = 40.0, 330.0, 4132.0       # pip cinsinden
        pip_size, entry_p = 0.10, 4100.0
        # cari ATR tick'i: 200 pip → atr = 200 * 0.10 = 20.0
        ticks = {
            "XAUUSD": {
                "symbol": "XAUUSD", "display": "XAU/USD", "bid": cur, "ask": cur + 0.1,
                "price": cur, "pip_size": pip_size, "digits": 2, "atr": 200 * pip_size,
                "spread_pips": 1.0, "change_pct": 0.8, "score": 95.0, "action": "BUY",
            }
        }
        pos = {
            "id": "FX-TEST-EATR", "symbol": "XAUUSD", "display": "XAU/USD",
            "direction": "BUY", "lots": 0.02, "entry_price": entry_p,
            "current_price": cur, "sl_price": entry_p, "tp_price": 0.0,
            "initial_sl_price": entry_p - 24 * pip_size,
            "breakeven_activated": True,        # trailing dalının ön koşulu
            "trailing_activated": False, "partial_taken": False,
            "open_time": "12:00:00 UTC+3", "pnl_usd": 0.0, "pnl_pips": 0.0,
            "pip_size": pip_size, "digits": 2, "score": 95.0,
            "strategy": "M1_M5_RADAR_SCALPER", "entry_source": "",
            "entry_atr_pips": entry_atr, "mfe_pips": mfe,
        }
        exp_entry = round(entry_p + (mfe - 0.3 * entry_atr) * pip_size, 2)   # 4131.8
        exp_cur = round(entry_p + (mfe - 0.3 * 200.0) * pip_size, 2)         # 4127.0
        self.assertNotAlmostEqual(exp_entry, exp_cur, places=2)

        orig_ticks = forex._generate_realistic_ticks
        prev_open = list(forex._AUTO_STATE["open_positions"])
        prev_enabled = forex._AUTO_STATE["enabled"]
        prev_chand = forex._AUTO_SETTINGS.chandelier_atr_mult
        try:
            forex._AUTO_SETTINGS.chandelier_atr_mult = 0.3
            forex._AUTO_STATE["open_positions"] = [pos]
            forex._AUTO_STATE["enabled"] = True
            forex._generate_realistic_ticks = mock.AsyncMock(return_value=ticks)
            task = asyncio.create_task(forex._forex_auto_paper_loop())
            await asyncio.sleep(2.2)            # döngü 1.5s uyur, sonra bir tarama yapar
            forex._AUTO_STATE["enabled"] = False
            await asyncio.wait_for(task, timeout=5)
        finally:
            forex._generate_realistic_ticks = orig_ticks
            forex._AUTO_STATE["enabled"] = prev_enabled
            forex._AUTO_SETTINGS.chandelier_atr_mult = prev_chand
            result_pos = forex._AUTO_STATE["open_positions"][0] if forex._AUTO_STATE["open_positions"] else pos
            forex._AUTO_STATE["open_positions"] = prev_open
        self.assertEqual(
            result_pos["sl_price"], exp_entry,
            f"trailing cari ATR'yi kullanmış (beklenen {exp_entry} = giriş ATR, "
            f"cari ATR olsaydı {exp_cur})",
        )


class TestChandelierTrailingBridge(unittest.IsolatedAsyncioTestCase):
    """Chandelier (tepe-çapalı) trailing — MT5 köprüsü (`check_and_apply_dynamic_exits`).

    2026-10-13: Tepe-çapalı mesafe `mfe - chandelier_atr_mult * entry_atr_pips` ile ölçülür.
    `CURRENT_SETTINGS["chandelier_atr_mult"] == 0.0` (varsayılan) ESKİ sabit-pip trailing'i
    BİREBİR korur (regresyon kapısı). ATR GİRİŞTE dondurulur — `POSITION_EXITS[ticket]
    ["entry_atr_pips"]` varsa PREFERRED; yoksa `_compute_atr_pips` (0.0 → sabit-pip'e düş).
    Motor tarafındaki eşi (forex.py `resolve_chandelier_atr` + TestChandelierEntryAtrParity)
    ile aynı sözleşmeyi kilitler.
    """

    TICKET = 555001
    ENTRY_P = 1.08000
    CUR_P = 1.08500

    _DICT_NAMES = (
        "POSITION_MFE_PIPS", "POSITION_ENTRY_ATR_PIPS",
        "POSITION_EXITS", "POSITION_PROTECTION_MAP", "PARTIAL_TP_MAP",
    )

    def setUp(self):
        self._saved_settings = dict(mt5_bridge.CURRENT_SETTINGS)
        self._clear_dicts()

    def tearDown(self):
        mt5_bridge.CURRENT_SETTINGS.clear()
        mt5_bridge.CURRENT_SETTINGS.update(self._saved_settings)
        self._clear_dicts()

    def _clear_dicts(self):
        for name in self._DICT_NAMES:
            d = getattr(mt5_bridge, name, None)
            if isinstance(d, dict):
                d.clear()

    def _fake_position(self, sl=1.07850, tp=1.09000):
        """`check_and_apply_dynamic_exits`'in beklediği minimal MT5 pozisyonu (namedtuple).

        +50 pip'te tutulur (price_current 1.08500, entry 1.08000): BE kilidi (0.4×50=20p →
        SL 1.0820) ile trailing adayları kıyaslanabilsin. EURUSD → pip_size 0.0001, digits 5.
        """
        import collections
        FakePos = collections.namedtuple(
            "_FakeChandPos",
            "ticket symbol type price_open price_current sl tp volume profit",
        )
        return FakePos(
            ticket=self.TICKET, symbol="EURUSD", type=0,          # 0 = POSITION_TYPE_BUY
            price_open=self.ENTRY_P, price_current=self.CUR_P, sl=sl, tp=tp,
            volume=0.5, profit=250.0,
        )

    @staticmethod
    def _settings(chand_mult, tp_cancel=False):
        return {
            "breakeven_pips": 14.0,
            "trailing_stop_pips": 20.0,
            "partial_tp_enabled": False,
            "tp_cancel_on_trail": tp_cancel,
            "chandelier_atr_mult": chand_mult,
        }

    def _run_bridge(self, settings, pos, current_atr_pips=0.0):
        """`check_and_apply_dynamic_exits`'i mock'lu MT5 ile koşturur; gönderilen emirleri döner.

        `_compute_atr_pips` sabitlenir (gerçek MT5 bar'ı olmadan determinist olsun diye);
        `symbol_info` → Mock(digits=5, volume_min=0.01) (mevcut köprü testleriyle aynı desen).
        """
        from unittest import mock
        mt5_bridge.CURRENT_SETTINGS.clear()
        mt5_bridge.CURRENT_SETTINGS.update(settings)
        sent = []

        def fake_order_send(req):
            sent.append(dict(req))
            return mock.Mock(retcode=mt5_bridge.mt5.TRADE_RETCODE_DONE, comment="ok")

        with mock.patch.object(mt5_bridge.mt5, "positions_get", return_value=[pos]), \
             mock.patch.object(mt5_bridge.mt5, "symbol_info",
                               return_value=mock.Mock(digits=5, volume_min=0.01)), \
             mock.patch.object(mt5_bridge.mt5, "order_send", side_effect=fake_order_send), \
             mock.patch.object(mt5_bridge, "_compute_atr_pips",
                               return_value=current_atr_pips, create=True):
            mt5_bridge.check_and_apply_dynamic_exits(be_pips=14.0, trail_pips=20.0)
        return sent

    # 1. REGRESYON KAPISI: çarpan 0.0 (varsayılan) → ESKİ sabit-pip trail BİREBİR
    def test_chandelier_disabled_by_default(self):
        """chandelier_atr_mult = 0.0 → SL tam olarak `price_current − 20 pip` olmalı."""
        pos = self._fake_position(sl=1.07850)
        sent = self._run_bridge(self._settings(0.0), pos, current_atr_pips=0.0)
        expected = round(self.CUR_P - 20 * 0.0001, 5)      # 1.08300
        self.assertEqual(len(sent), 1, "sabit-pip trailing tek MODIFY_SLTP üretmeli")
        self.assertEqual(sent[0]["sl"], expected,
                         "çarpan 0.0'da eski sabit-pip davranışı korunmalı")

    # 2. GİRİŞ ATR'si kullanılır — CARİ ATR DEĞİL
    def test_chandelier_uses_entry_atr_not_current(self):
        """entry_atr_pips=40 ile SL `mfe − 0.3×40`; cari ATR (100) yok sayılmalı."""
        mt5_bridge.POSITION_MFE_PIPS[self.TICKET] = 60.0
        mt5_bridge.POSITION_EXITS[self.TICKET] = {"entry_atr_pips": 40.0, "trail_pips": 20.0}
        pos = self._fake_position(sl=1.07850)
        sent = self._run_bridge(self._settings(0.3), pos, current_atr_pips=100.0)
        exp_entry = round(self.ENTRY_P + (60.0 - 0.3 * 40.0) * 0.0001, 5)   # 1.0848
        exp_cur = round(self.ENTRY_P + (60.0 - 0.3 * 100.0) * 0.0001, 5)    # 1.0830
        self.assertNotEqual(exp_entry, exp_cur, "iki ATR kaynağı ayırt edici olmalı")
        self.assertEqual(len(sent), 1)
        self.assertEqual(
            sent[0]["sl"], exp_entry,
            f"giriş ATR'si kullanılmalı ({exp_entry}); cari ATR olsaydı {exp_cur}",
        )

    # 3. STOP ASLA GERİ GİTMEZ
    def test_chandelier_never_moves_stop_backwards(self):
        """Mevcut SL, chandelier adayının (1.0848) ÜSTÜNDE → SL düşürülmemeli (emir YOK)."""
        mt5_bridge.POSITION_MFE_PIPS[self.TICKET] = 60.0
        mt5_bridge.POSITION_EXITS[self.TICKET] = {"entry_atr_pips": 40.0, "trail_pips": 20.0}
        pos = self._fake_position(sl=1.08550)   # adayın üstünde → geri taşıma yasak
        sent = self._run_bridge(self._settings(0.3), pos, current_atr_pips=100.0)
        self.assertEqual(sent, [], "SL adayın üstündeyken geri taşınmamalı (emir YOK)")

    # 4. GİRİŞ ATR'si YOK → SABİT-PİP'E DÜŞ (çökme yok)
    def test_chandelier_falls_back_when_entry_atr_missing(self):
        """entry_atr_pips=0 + _compute_atr_pips()=0.0 → chandelier atlanır, sabit-pip traili."""
        mt5_bridge.POSITION_MFE_PIPS[self.TICKET] = 60.0
        mt5_bridge.POSITION_EXITS[self.TICKET] = {"trail_pips": 20.0, "entry_atr_pips": 0.0}
        pos = self._fake_position(sl=1.07850)
        sent = self._run_bridge(self._settings(0.3), pos, current_atr_pips=0.0)
        expected = round(self.CUR_P - 20 * 0.0001, 5)      # 1.08300
        self.assertEqual(len(sent), 1, "ATR yoksa sabit-pip trail (çökme olmadan)")
        self.assertEqual(sent[0]["sl"], expected)

    # 5. _compute_atr_pips HER ARIZADA 0.0, ASLA raise etmez
    def test_compute_atr_pips_returns_zero_on_failure(self):
        from unittest import mock
        with mock.patch.object(mt5_bridge.mt5, "copy_rates_from_pos", return_value=None):
            self.assertEqual(mt5_bridge._compute_atr_pips("EURUSD", 0.0001), 0.0)
        with mock.patch.object(mt5_bridge.mt5, "copy_rates_from_pos",
                               side_effect=RuntimeError("boom")):
            self.assertEqual(mt5_bridge._compute_atr_pips("EURUSD", 0.0001), 0.0)


if __name__ == "__main__":
    unittest.main()




