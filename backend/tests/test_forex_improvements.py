"""Forex otonom scalper geliştirme paketi testleri (2026-10 iyileştirmeleri).

Kapsam:
- Pip değeri hatası düzeltmesi: paper PnL sembol spec pip_val'ını kullanır
- CMO (Chande Momentum Oscillator) ve CCI indikatörleri + skor entegrasyonu
- DXY (ABD Dolar Endeksi) rejim filtresi (get_dxy_regime + dxy_entry_veto)
- ATR bazlı dinamik çıkış motoru (get_atr_exit_levels)
- Kısmi kâr alma (apply_partial_take_profit + köprü CLOSE_PARTIAL altyapısı)
- FX korelasyon kalkanı (FXCorrelationMonitor.cluster_check)
- Zayıf saat kalkanı (is_entry_hour_blocked)
"""
import asyncio
import datetime
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.routers import forex
from backend.app.forex_correlation import FXCorrelationMonitor
from scripts import mt5_bridge


def _up_series(n=60, step=0.001, base=1.0):
    return [base + i * step for i in range(n)]


def _down_series(n=60, step=0.001, base=1.0):
    return [base - i * step for i in range(n)]


def _flat_series(n=60, base=1.0):
    return [base for _ in range(n)]


def _noisy_rets(n=119, drift=0.0008, vol=0.0012, seed=7):
    """Varyanslı getiri serisi (sabit getiri serisi korelasyonda dejenere olur)."""
    import random
    rng = random.Random(seed)
    return [drift + rng.gauss(0, vol) for _ in range(n)]


def _closes_from_rets(rets, start=100.0):
    """Getiri serisinden kapanış serisi üretir (çarpımsal — getiriler birebir korunur)."""
    closes = [start]
    for r in rets:
        closes.append(closes[-1] * (1 + r))
    return closes


class TestPipValueFix(unittest.IsolatedAsyncioTestCase):
    """BTCUSD/ETHUSD/endeks/petrol pip değeri: spec pip_val kullanılmalı (10x hata düzeltmesi)."""

    def setUp(self):
        forex._AUTO_STATE["open_positions"].clear()
        forex._AUTO_STATE["closed_trades"].clear()
        forex._AUTO_STATE["balance"] = 10000.0
        forex._AUTO_STATE["realized_pnl_usd"] = 0.0

    async def test_btcusd_paper_close_uses_spec_pip_val(self):
        """BTCUSD SELL 0.02 lot, +70 pip → $1.40 (eski hatalı kod $14.00 üretirdi)."""
        pos = {
            "id": "FX-BTC-1",
            "symbol": "BTCUSD",
            "display": "BTC/USD",
            "direction": "SELL",
            "lots": 0.02,
            "entry_price": 85000.00,
            "current_price": 84930.00,
            "sl_price": 85330.00,
            "tp_price": 84700.00,
            "pip_size": 1.0,
            "digits": 2,
        }
        forex._AUTO_STATE["open_positions"].append(pos)
        closed = await forex._close_position_internal("FX-BTC-1", "TP_HIT", 84930.00)
        self.assertIsNotNone(closed)
        # 70 pip * 0.02 lot * $1.0/pip = $1.40
        self.assertAlmostEqual(closed["pnl_usd"], 1.40, places=2)

    async def test_ethusd_paper_close_uses_spec_pip_val(self):
        """ETHUSD BUY 0.02 lot, +61.75 pip → $1.24 (10x hata olmadan)."""
        pos = {
            "id": "FX-ETH-1",
            "symbol": "ETHUSD",
            "display": "ETH/USD",
            "direction": "BUY",
            "lots": 0.02,
            "entry_price": 2700.00,
            "current_price": 2761.75,
            "sl_price": 2680.00,
            "tp_price": 2780.00,
            "pip_size": 1.0,
            "digits": 2,
        }
        forex._AUTO_STATE["open_positions"].append(pos)
        closed = await forex._close_position_internal("FX-ETH-1", "TP_HIT", 2761.75)
        self.assertAlmostEqual(closed["pnl_usd"], 61.75 * 0.02 * 1.0, places=2)

    async def test_nas100_paper_close_uses_spec_pip_val(self):
        """NAS100 (endeks, pip_val 1.0) 10x şişirmeden kapanmalı."""
        pos = {
            "id": "FX-NAS-1",
            "symbol": "NAS100",
            "display": "Nasdaq 100",
            "direction": "BUY",
            "lots": 0.10,
            "entry_price": 20400.00,
            "current_price": 20430.00,
            "sl_price": 20360.00,
            "tp_price": 20440.00,
            "pip_size": 1.0,
            "digits": 2,
        }
        forex._AUTO_STATE["open_positions"].append(pos)
        closed = await forex._close_position_internal("FX-NAS-1", "TP_HIT", 20430.00)
        self.assertAlmostEqual(closed["pnl_usd"], 30 * 0.10 * 1.0, places=2)

    async def test_eurusd_paper_close_unchanged(self):
        """Standart forex (pip_val 10.0) davranışı değişmemeli (regresyon)."""
        pos = {
            "id": "FX-EUR-1",
            "symbol": "EURUSD",
            "display": "EUR/USD",
            "direction": "BUY",
            "lots": 0.05,
            "entry_price": 1.08500,
            "current_price": 1.08570,  # +7 pip
            "sl_price": 1.08380,
            "tp_price": 1.08700,
            "pip_size": 0.0001,
            "digits": 5,
        }
        forex._AUTO_STATE["open_positions"].append(pos)
        closed = await forex._close_position_internal("FX-EUR-1", "TP_HIT", 1.08570)
        # 7 pip * 0.05 lot * $10.0/pip = $3.50
        self.assertAlmostEqual(closed["pnl_usd"], 3.50, places=2)

    async def test_usdjpy_paper_close_uses_jpy_pip_val(self):
        """USDJPY pip_val 6.60 korunmalı (regresyon)."""
        pos = {
            "id": "FX-JPY-1",
            "symbol": "USDJPY",
            "display": "USD/JPY",
            "direction": "BUY",
            "lots": 0.05,
            "entry_price": 158.000,
            "current_price": 158.200,
            "sl_price": 157.880,
            "tp_price": 158.220,
            "pip_size": 0.01,
            "digits": 3,
        }
        forex._AUTO_STATE["open_positions"].append(pos)
        closed = await forex._close_position_internal("FX-JPY-1", "TP_HIT", 158.200)
        self.assertAlmostEqual(closed["pnl_usd"], 20 * 0.05 * 6.60, delta=0.01)


class TestCMOAndCCI(unittest.IsolatedAsyncioTestCase):
    """CMO ve CCI hesaplama doğruluğu ve skor entegrasyonu."""

    def test_cmo_steady_uptrend_is_max(self):
        cmo = forex._compute_cmo(_up_series(30), 14)
        self.assertGreater(cmo, 99.0)

    def test_cmo_mixed_series_positive_band(self):
        # 0.002 yukarı / 0.001 aşağı → net pozitif momentum (CMO ≈ +33)
        closes = [1.0]
        for i in range(20):
            closes.append(closes[-1] + 0.002)
            closes.append(closes[-1] - 0.001)
        cmo = forex._compute_cmo(closes, 14)
        self.assertGreater(cmo, 0.0)
        self.assertLess(cmo, 60.0)

    def test_cmo_flat_series_guarded_zero(self):
        self.assertEqual(forex._compute_cmo(_flat_series(30), 14), 0.0)

    def test_cmo_short_series_zero(self):
        self.assertEqual(forex._compute_cmo(_up_series(10), 14), 0.0)

    def test_cci_strong_uptrend_positive(self):
        closes = _up_series(40)
        highs = [c + 0.0005 for c in closes]
        lows = [c - 0.0005 for c in closes]
        cci = forex._compute_cci(highs, lows, closes, 20)
        self.assertGreater(cci, 100.0)

    def test_cci_strong_downtrend_negative(self):
        closes = _down_series(40)
        highs = [c + 0.0005 for c in closes]
        lows = [c - 0.0005 for c in closes]
        cci = forex._compute_cci(highs, lows, closes, 20)
        self.assertLess(cci, -100.0)

    def test_cci_flat_series_guarded_zero(self):
        closes = _flat_series(40)
        highs = list(closes)
        lows = list(closes)
        self.assertEqual(forex._compute_cci(highs, lows, closes, 20), 0.0)

    def test_indicators_include_cmo_cci(self):
        closes = _up_series(30, step=0.0005, base=1.08)
        highs = [c + 0.0003 for c in closes]
        lows = [c - 0.0003 for c in closes]
        opens = [c - 0.0002 for c in closes]
        tech = forex._compute_technical_indicators(closes, highs, lows, opens, "EURUSD")
        self.assertIsNotNone(tech)
        self.assertIn("cmo", tech)
        self.assertIn("cci", tech)
        self.assertGreater(tech["cmo"], 0.0)
        # Mevcut regresyon: yükseliş serisi BULLISH ve skor > 70 kalmalı
        self.assertEqual(tech["trend"], "BULLISH")
        self.assertGreater(tech["score"], 70.0)

    def test_indicators_flat_series_no_nan(self):
        closes = _flat_series(30, base=1.08)
        highs = [1.0805] * 30
        lows = [1.0795] * 30
        opens = [1.08] * 30
        tech = forex._compute_technical_indicators(closes, highs, lows, opens, "EURUSD")
        self.assertIsNotNone(tech)
        self.assertEqual(tech["cmo"], 0.0)
        self.assertEqual(tech["cci"], 0.0)
        self.assertEqual(tech["trend"], "NEUTRAL")

    def test_ticks_cache_includes_cmo_cci_fields(self):
        """Tick önbelleği radar/frontende cmo/cci taşımali (alan varlığı)."""
        # Sadece alan sözleşmesini doğrula: radar kartı cmo/cci içeriyor mu
        import inspect
        src = inspect.getsource(forex._generate_realistic_ticks)
        self.assertIn('"cmo"', src)
        self.assertIn('"cci"', src)


class TestDXYRegimeFilter(unittest.IsolatedAsyncioTestCase):
    """DXY (ABD Dolar Endeksi) rejim hesabı ve giriş vetosu."""

    def setUp(self):
        forex._TECHNICAL_CACHE.pop("DXY", None)

    def tearDown(self):
        forex._TECHNICAL_CACHE.pop("DXY", None)

    def test_dxy_regime_usd_strong(self):
        forex._TECHNICAL_CACHE["DXY"] = {"trend": "BULLISH", "score": 80.0, "rsi": 60.0, "cmo": 40.0, "change_pct": 0.4, "updated_at": 1.0}
        dxy = forex.get_dxy_regime()
        self.assertEqual(dxy["regime"], "USD_STRONG")

    def test_dxy_regime_usd_weak(self):
        forex._TECHNICAL_CACHE["DXY"] = {"trend": "BEARISH", "score": 75.0, "rsi": 40.0, "cmo": -40.0, "change_pct": -0.4, "updated_at": 1.0}
        self.assertEqual(forex.get_dxy_regime()["regime"], "USD_WEAK")

    def test_dxy_regime_neutral_when_flat(self):
        forex._TECHNICAL_CACHE["DXY"] = {"trend": "NEUTRAL", "score": 55.0, "rsi": 50.0, "cmo": 0.0, "change_pct": 0.0, "updated_at": 1.0}
        self.assertEqual(forex.get_dxy_regime()["regime"], "USD_NEUTRAL")

    def test_dxy_regime_none_without_data(self):
        self.assertIsNone(forex.get_dxy_regime())

    def test_veto_conflicting_usd_long_in_weak_dollar(self):
        # USDJPY BUY = USD_LONG; dolar zayıfken yanlış taraf
        self.assertEqual(forex.dxy_entry_veto("USDJPY", "BUY", {"regime": "USD_WEAK"}), "dxy_conflict")

    def test_veto_conflicting_usd_short_in_strong_dollar(self):
        # EURUSD BUY = USD_SHORT; dolar güçlüyken yanlış taraf
        self.assertEqual(forex.dxy_entry_veto("EURUSD", "BUY", {"regime": "USD_STRONG"}), "dxy_conflict")

    def test_gold_fully_exempt_from_dxy(self):
        # 2026-10-06 kullanıcı kararı: XAUUSD DXY kapsamından TAMAMEN çıkarıldı —
        # çelişki rejiminde bile veto yok, nötr rejimde strict-neutral ekstra skoru da yok.
        self.assertIsNone(forex.dxy_entry_veto("XAUUSD", "BUY", {"regime": "USD_STRONG"}))
        self.assertIsNone(forex.dxy_entry_veto("XAUUSD", "SELL", {"regime": "USD_WEAK"}))
        self.assertIsNone(forex.dxy_entry_veto("XAUUSD", "BUY", {"regime": "USD_NEUTRAL"}))
        self.assertIsNone(forex.dxy_entry_veto("XAUUSD", "BUY", None))

    def test_aligned_entries_allowed(self):
        self.assertIsNone(forex.dxy_entry_veto("USDJPY", "BUY", {"regime": "USD_STRONG"}))
        self.assertIsNone(forex.dxy_entry_veto("EURUSD", "BUY", {"regime": "USD_WEAK"}))

    def test_strict_symbol_neutral_regime_requests_extra_score(self):
        self.assertEqual(forex.dxy_entry_veto("USDCHF", "SELL", {"regime": "USD_NEUTRAL"}), "dxy_strict_neutral")
        self.assertEqual(forex.dxy_entry_veto("USDJPY", "SELL", {"regime": "USD_NEUTRAL"}), "dxy_strict_neutral")
        # Zayıf olmayan sembol nötr rejimde serbest
        self.assertIsNone(forex.dxy_entry_veto("EURUSD", "BUY", {"regime": "USD_NEUTRAL"}))

    def test_no_dxy_data_fails_open(self):
        self.assertIsNone(forex.dxy_entry_veto("USDJPY", "BUY", None))

    def test_major_entry_gate_session(self):
        # Majör olmayan semboller her zaman serbest
        self.assertIsNone(forex.major_entry_gate_decision("XAUUSD", 3, 10.0, True, 7, 20, 4.0))
        # Asya seansında (03:00 UTC) majör engellenir
        self.assertEqual(forex.major_entry_gate_decision("EURUSD", 3, 10.0, True, 7, 20, 4.0), "major_session")
        # Pencere içinde (12:00 UTC London/NY) serbest
        self.assertIsNone(forex.major_entry_gate_decision("EURUSD", 12, 10.0, True, 7, 20, 4.0))
        # Filtre kapalıysa saat fark etmez
        self.assertIsNone(forex.major_entry_gate_decision("EURUSD", 3, 10.0, False, 7, 20, 4.0))

    def test_major_entry_gate_min_atr(self):
        # Ölü piyasa (ATR 3p < 4p tabanı) engellenir
        self.assertEqual(forex.major_entry_gate_decision("USDCAD", 12, 3.0, True, 7, 20, 4.0), "major_min_atr")
        # Tabana eşit veya üstü serbest
        self.assertIsNone(forex.major_entry_gate_decision("USDCAD", 12, 4.0, True, 7, 20, 4.0))
        # 0 = kapalı
        self.assertIsNone(forex.major_entry_gate_decision("USDCAD", 12, 1.0, True, 7, 20, 0.0))

    def test_major_gate_settings_defaults(self):
        cfg = forex.ForexAutoPaperSettings()
        self.assertTrue(cfg.major_session_filter)
        self.assertEqual(cfg.major_session_start_utc, 7)
        self.assertEqual(cfg.major_session_end_utc, 20)
        self.assertEqual(cfg.major_min_atr_pips, 4.0)

    def test_radar_response_contains_dxy_field(self):
        import inspect
        src = inspect.getsource(forex.get_forex_radar)
        self.assertIn('"dxy"', src)


class TestATRExitEngine(unittest.IsolatedAsyncioTestCase):
    """ATR bazlı dinamik TP/SL çıkış motoru."""

    def test_passthrough_without_atr(self):
        levels = forex.get_atr_exit_levels(None, 8.0, 20.0)
        self.assertEqual(levels["sl_pips"], 8.0)
        self.assertEqual(levels["tp_pips"], 20.0)
        self.assertEqual(levels["first_target_pips"], 12.0)

    def test_eurusd_tp_pulled_to_volatility(self):
        # ATR 5 pip: TP 20 → 12 pips'e çekilir (min TP = SL*1.5), SL nefes payı korunur
        levels = forex.get_atr_exit_levels(5.0, 8.0, 20.0)
        self.assertEqual(levels["sl_pips"], 8.0)
        self.assertEqual(levels["tp_pips"], 12.0)
        self.assertEqual(levels["first_target_pips"], 7.2)
        # TP asla SL*1.5'in altına inmemeli
        self.assertGreaterEqual(levels["tp_pips"], levels["sl_pips"] * 1.5)

    def test_gold_volatility_buffer_expands_sl(self):
        # ATR 30 pip, spec SL 45 → SL korunur; TP 82.4 → 67.5'e çekilir
        levels = forex.get_atr_exit_levels(30.0, 45.0, 82.4)
        self.assertEqual(levels["sl_pips"], 45.0)
        self.assertEqual(levels["tp_pips"], 67.5)
        self.assertEqual(levels["first_target_pips"], 40.5)

    def test_btc_noise_protection_expands_sl(self):
        # BTC ATR 300 pip: SL 40 → 330'a genişler (gürültü stoplarını önler), TP 130 → 495
        levels = forex.get_atr_exit_levels(300.0, 40.0, 130.0)
        self.assertEqual(levels["sl_pips"], 330.0)
        self.assertEqual(levels["tp_pips"], 495.0)
        self.assertGreaterEqual(levels["tp_pips"], levels["sl_pips"] * 1.5)

    def test_zero_atr_passthrough(self):
        levels = forex.get_atr_exit_levels(0.0, 8.0, 20.0)
        self.assertEqual(levels["tp_pips"], 20.0)


class TestPartialTakeProfit(unittest.IsolatedAsyncioTestCase):
    """Kısmi kâr alma motoru (paper)."""

    def _buy_pos(self):
        return {
            "id": "FX-P-1",
            "symbol": "EURUSD",
            "display": "EUR/USD",
            "direction": "BUY",
            "lots": 0.05,
            "entry_price": 1.08500,
            "current_price": 1.08580,
            "sl_price": 1.08420,
            "tp_price": 1.08596,
            "pip_size": 0.0001,
            "digits": 5,
            "partial_target_pips": 7.2,
            "partial_taken": False,
            "partial_realized_usd": 0.0,
        }

    def test_partial_fires_at_target(self):
        pos = self._buy_pos()
        realized = forex.apply_partial_take_profit(pos, 8.0, 10.0)
        self.assertIsNotNone(realized)
        expected_close_lots = round(0.05 / 2, 2)
        self.assertAlmostEqual(realized, round(8.0 * expected_close_lots * 10.0, 2), places=2)
        self.assertEqual(pos["lots"], round(0.05 - expected_close_lots, 2))
        self.assertTrue(pos["partial_taken"])
        self.assertTrue(pos["breakeven_activated"])
        # SL artık giriş üstünde (başabaş üstü kâr kilidi)
        self.assertGreater(pos["sl_price"], pos["entry_price"])

    def test_partial_no_refire(self):
        pos = self._buy_pos()
        first = forex.apply_partial_take_profit(pos, 8.0, 10.0)
        self.assertIsNotNone(first)
        self.assertIsNone(forex.apply_partial_take_profit(pos, 9.0, 10.0))

    def test_partial_below_target_noop(self):
        pos = self._buy_pos()
        self.assertIsNone(forex.apply_partial_take_profit(pos, 5.0, 10.0))
        self.assertFalse(pos["partial_taken"])
        self.assertEqual(pos["lots"], 0.05)

    def test_partial_no_target_configured(self):
        pos = self._buy_pos()
        pos["partial_target_pips"] = 0.0
        self.assertIsNone(forex.apply_partial_take_profit(pos, 10.0, 10.0))

    def test_partial_sell_side_locks_profit(self):
        pos = self._buy_pos()
        pos.update({"direction": "SELL", "entry_price": 1.08500, "sl_price": 1.08600, "current_price": 1.08420})
        realized = forex.apply_partial_take_profit(pos, 8.0, 10.0)
        self.assertIsNotNone(realized)
        self.assertTrue(pos["partial_taken"])
        self.assertLess(pos["sl_price"], pos["entry_price"])

    def test_partial_too_small_to_split_marks_done(self):
        pos = self._buy_pos()
        pos["lots"] = 0.01  # yarısı (0.005) min lot altı
        realized = forex.apply_partial_take_profit(pos, 8.0, 10.0)
        self.assertIsNone(realized)
        self.assertTrue(pos["partial_taken"])
        self.assertEqual(pos["lots"], 0.01)

    def test_bridge_partial_infra_present(self):
        """Köprüde CLOSE_PARTIAL altyapısı mevcut (pilot: MT5 tarafı kısmi kâr)."""
        self.assertTrue(hasattr(mt5_bridge, "execute_close_partial"))
        self.assertTrue(hasattr(mt5_bridge, "PARTIAL_TP_MAP"))
        self.assertIn("CLOSE_PARTIAL", pathlib.Path(mt5_bridge.__file__).read_text(encoding="utf-8"))


class TestFXCorrelationGuard(unittest.IsolatedAsyncioTestCase):
    """FX korelasyon kalkanı: matris üretimi ve küme denetimi."""

    def test_refresh_builds_matrix(self):
        mon = FXCorrelationMonitor()
        rets = _noisy_rets(119, seed=7)
        eurusd = _closes_from_rets(rets)
        gbpusd = _closes_from_rets(rets)                # birebir aynı getiriler → ρ ≈ +1
        usdchf = _closes_from_rets([-r for r in rets])  # ters işaretli getiriler → ρ ≈ -1
        res = mon.refresh({"EURUSD": eurusd, "GBPUSD": gbpusd, "USDCHF": usdchf})
        self.assertTrue(res["ok"])
        self.assertGreater(mon.correlation_of("EURUSD", "GBPUSD"), 0.95)
        self.assertLess(mon.correlation_of("EURUSD", "USDCHF"), -0.95)

    def test_missing_data_is_neutral_fail_open(self):
        mon = FXCorrelationMonitor()
        self.assertEqual(mon.correlation_of("EURUSD", "GBPUSD"), 0.0)

    def test_high_corr_same_bias_blocked(self):
        mon = FXCorrelationMonitor()
        rets = _noisy_rets(119, seed=11)
        mon.refresh({"EURUSD": _closes_from_rets(rets), "GBPUSD": _closes_from_rets(rets)})
        allowed, reason = mon.cluster_check("GBPUSD", "USD_SHORT", [("EURUSD", "USD_SHORT")])
        self.assertFalse(allowed)
        self.assertIn("high_corr", reason)

    def test_high_corr_opposite_bias_allowed_hedge(self):
        mon = FXCorrelationMonitor()
        rets = _noisy_rets(119, seed=13)
        mon.refresh({"EURUSD": _closes_from_rets(rets), "USDCHF": _closes_from_rets([-r for r in rets])})
        # EURUSD BUY = USD_SHORT iken USDCHF BUY = USD_LONG → hedge, serbest
        allowed, _ = mon.cluster_check("USDCHF", "USD_LONG", [("EURUSD", "USD_SHORT")])
        self.assertTrue(allowed)

    def test_medium_corr_cluster_cap(self):
        """0.70-0.85 bandında 2+ korele sembol → küme sınırı aşılırsa engel."""
        import math
        mon = FXCorrelationMonitor()
        # Deterministik üçlü: ortak sin20 bileşeni (a=0.866) + birbirinden ortogonal
        # idiosinkratik bileşenler (b=0.5) → tüm çiftler ρ ≈ 0.75 (medium band)
        s20 = [0.001 * math.sin(2 * math.pi * i / 20) for i in range(119)]
        c20 = [0.001 * math.cos(2 * math.pi * i / 20) for i in range(119)]
        s13 = [0.001 * math.sin(2 * math.pi * i / 13) for i in range(119)]
        s7 = [0.001 * math.sin(2 * math.pi * i / 7) for i in range(119)]

        def _mix_pair(a_rets, b_rets):
            return [0.866 * x + 0.5 * y for x, y in zip(a_rets, b_rets)]

        eurusd = _closes_from_rets(_mix_pair(s20, c20))   # ρ(E,N) ≈ ρ(E,C) ≈ ρ(N,C) ≈ 0.75
        nzdusd = _closes_from_rets(_mix_pair(s20, s13))
        gbpusd = _closes_from_rets(_mix_pair(s20, s7))
        mon.refresh({"EURUSD": eurusd, "NZDUSD": nzdusd, "GBPUSD": gbpusd})
        rho_ec = abs(mon.correlation_of("EURUSD", "GBPUSD"))
        rho_nc = abs(mon.correlation_of("NZDUSD", "GBPUSD"))
        self.assertGreaterEqual(rho_ec, 0.70)
        self.assertLess(rho_ec, 0.85)
        self.assertGreaterEqual(rho_nc, 0.70)
        self.assertLess(rho_nc, 0.85)
        allowed, reason = mon.cluster_check("GBPUSD", "USD_SHORT", [("EURUSD", "USD_SHORT"), ("NZDUSD", "USD_SHORT")], max_cluster=2)
        self.assertFalse(allowed)
        self.assertIn("cluster", reason)

    def test_no_positions_allowed(self):
        mon = FXCorrelationMonitor()
        allowed, _ = mon.cluster_check("EURUSD", "USD_SHORT", [])
        self.assertTrue(allowed)

    def test_fail_open_without_correlation_data(self):
        mon = FXCorrelationMonitor()
        allowed, _ = mon.cluster_check("EURUSD", "USD_SHORT", [("GBPUSD", "USD_SHORT")])
        self.assertTrue(allowed)

    def test_stale_symbols_pruned(self):
        mon = FXCorrelationMonitor()
        rets = _noisy_rets(119, seed=21)
        mon.refresh({"EURUSD": _closes_from_rets(rets), "GBPUSD": _closes_from_rets(rets)})
        mon.refresh({"EURUSD": _closes_from_rets(_noisy_rets(119, seed=22))})
        snap = mon.snapshot()
        self.assertNotIn("GBPUSD", snap)


class TestWeakHourGuardAndSettings(unittest.IsolatedAsyncioTestCase):
    """Zayıf saat kalkanı ve yeni ayar alanları."""

    def test_blocked_hours_logic(self):
        self.assertTrue(forex.is_entry_hour_blocked(5, [5, 15]))
        self.assertTrue(forex.is_entry_hour_blocked(15, [5, 15]))
        self.assertFalse(forex.is_entry_hour_blocked(6, [5, 15]))
        self.assertFalse(forex.is_entry_hour_blocked(5, []))
        self.assertFalse(forex.is_entry_hour_blocked(5, None))

    def test_new_settings_defaults(self):
        cfg = forex.ForexAutoPaperSettings()
        self.assertTrue(cfg.dxy_filter_enabled)
        self.assertTrue(cfg.correlation_guard)
        self.assertTrue(cfg.atr_exit_enabled)
        self.assertTrue(cfg.partial_tp_enabled)
        # ADX kalkanı KAPALI (2026-10-06 30g replay eğri taraması: KAPALI en iyi —
        # seans+minATR+EV kapıları chop kontrolünü devraldı)
        self.assertFalse(cfg.adx_filter_enabled)
        self.assertTrue(cfg.supertrend_filter_enabled)
        # Zayıf saat kalkanı kullanıcı kararıyla kaldırıldı — varsayılan boş liste
        self.assertEqual(list(cfg.blocked_hours_utc), [])
        # EV kalkanı varsayılanları (WR 45: 2026-10-06 30g replay A/B kararı; 35 → 45)
        self.assertTrue(cfg.ev_guard_enabled)
        self.assertEqual(cfg.ev_window_hours, 24.0)
        self.assertEqual(cfg.ev_min_trades, 10)
        self.assertEqual(cfg.ev_max_win_rate, 45.0)
        self.assertEqual(cfg.ev_loss_risk_mult, 3.0)
        # allowed_symbols: yalnız 2 sembol (2026-10-06 kullanıcı kararı — XAUUSD + BTCUSD)
        self.assertEqual(len(cfg.allowed_symbols), 2)
        self.assertIn("XAUUSD", cfg.allowed_symbols)
        self.assertIn("BTCUSD", cfg.allowed_symbols)
        self.assertNotIn("DXY", cfg.allowed_symbols)


class TestRiskNormalization(unittest.IsolatedAsyncioTestCase):
    """ATR genişlemiş SL'de lot risk normalizasyonu (gerçek olay: US30 0.20 lot × 81.7 pip = $16.3, bütçe $10)."""

    def test_index_narrow_sl_unchanged(self):
        # MT5 demo hesabı $1000 → işlem başına risk bütçesi $10 (hedef tolerans $12.5)
        lots, skip = forex.apply_risk_normalization("US30", 0.20, 24.0, 1.0, 10.0)
        self.assertEqual(lots, 0.20)
        self.assertFalse(skip)

    def test_index_wide_sl_shrinks(self):
        # 0.20 × 80 pip = $16 > hedef $12.5 → 0.15 lota çekilmeli ($12)
        lots, skip = forex.apply_risk_normalization("US30", 0.20, 80.0, 1.0, 10.0)
        self.assertEqual(lots, 0.15)
        self.assertFalse(skip)
        self.assertLessEqual(lots * 80.0 * 1.0, 12.5)

    def test_index_extreme_sl_floor_with_hard_cap(self):
        # 0.15'e sığmaz; kategori minimumu 0.10 × 150 pip = $15 ≤ sert sınır $20 → 0.10 devam
        lots, skip = forex.apply_risk_normalization("US30", 0.20, 150.0, 1.0, 10.0)
        self.assertEqual(lots, 0.10)
        self.assertFalse(skip)

    def test_index_extreme_sl_skips_entirely(self):
        # 0.10 × 250 pip = $25 > sert sınır $20 → işlem tamamen pas geçilmeli
        lots, skip = forex.apply_risk_normalization("US30", 0.20, 250.0, 1.0, 10.0)
        self.assertTrue(skip)

    def test_paper_account_budget_unchanged(self):
        # Paper hesabı $10.000 → bütçe $100: 0.20 × 80 = $16 zaten sığıyor
        lots, skip = forex.apply_risk_normalization("US30", 0.20, 80.0, 1.0, 100.0)
        self.assertEqual(lots, 0.20)
        self.assertFalse(skip)

    def test_forex_narrow_sl_unchanged(self):
        lots, skip = forex.apply_risk_normalization("EURUSD", 0.05, 8.0, 10.0, 10.0)
        self.assertEqual(lots, 0.05)
        self.assertFalse(skip)

    def test_gold_wide_sl_shrinks(self):
        # 0.02 × 67.5 pip × $10/pip = $13.5 > $12.5 → 0.01 lota çekilmeli
        lots, skip = forex.apply_risk_normalization("XAUUSD", 0.02, 67.5, 10.0, 10.0)
        self.assertEqual(lots, 0.01)
        self.assertFalse(skip)

    def test_btc_wide_sl_unchanged(self):
        # 0.02 × 330 pip × $1/pip = $6.6 ≤ $12.5 → dokunulmaz
        lots, skip = forex.apply_risk_normalization("BTCUSD", 0.02, 330.0, 1.0, 10.0)
        self.assertEqual(lots, 0.02)
        self.assertFalse(skip)


class TestEVGuard(unittest.IsolatedAsyncioTestCase):
    """Sembol EV kalkanı (yumuşatılmış eşikler): kararı ve istatistik toplama."""

    def test_decision_blocks_chronic_bleeder(self):
        # Derin kronik kaybeden: 10+ işlem, %30 WR, net negatif → dinlenmeli
        stats = {"n": 12, "net": -11.5, "win_rate": 30.0}
        self.assertTrue(forex.ev_guard_decision(stats, 10, 35.0, 30.0))

    def test_decision_blocks_acute_loss(self):
        # Akut: zarar 3x risk bütçesini (3 x $10 = $30) aştı → WR fark etmeksizin dinlenmeli
        stats = {"n": 10, "net": -45.0, "win_rate": 55.0}
        self.assertTrue(forex.ev_guard_decision(stats, 10, 35.0, 30.0))

    def test_decision_frees_marginal_bleeder(self):
        # Yumuşatmanın amacı: "haklı ama az zarar veren" sembol serbest
        # (canlı örneği: USDCAD 25 işlem %40 WR −$11.54 → tetiklenmemeli)
        stats = {"n": 25, "net": -11.5, "win_rate": 40.0}
        self.assertFalse(forex.ev_guard_decision(stats, 10, 35.0, 30.0))

    def test_decision_allows_small_sample(self):
        stats = {"n": 8, "net": -20.0, "win_rate": 20.0}
        self.assertFalse(forex.ev_guard_decision(stats, 10, 35.0, 30.0))

    def test_decision_allows_profitable(self):
        stats = {"n": 12, "net": 30.0, "win_rate": 30.0}
        self.assertFalse(forex.ev_guard_decision(stats, 10, 35.0, 30.0))

    def test_decision_allows_healthy_wr_with_tiny_loss(self):
        # Zarar var ama WR sağlıklı ve zarar akut eşiğin (3x=$30) altında → dokunulmaz
        stats = {"n": 10, "net": -5.0, "win_rate": 55.0}
        self.assertFalse(forex.ev_guard_decision(stats, 10, 35.0, 30.0))

    def test_collect_symbol_ev_from_paper_book(self):
        forex._AUTO_STATE["closed_trades"].clear()
        forex._MT5_STATE["connected"] = False
        now = __import__("time").time()
        for i, pnl in enumerate([-5.0, -4.0, -3.0, -2.0, -1.0, -1.0]):
            forex._AUTO_STATE["closed_trades"].append({
                "symbol": "USDCAD", "pnl_usd": pnl,
                "closed_at_ts": now - i * 600,   # son 1 saat içinde
            })
            forex._AUTO_STATE["closed_trades"].append({
                "symbol": "EURUSD", "pnl_usd": 2.0,
                "closed_at_ts": now - i * 600,
            })
        stats = forex._collect_symbol_ev("USDCAD", now, 12 * 3600)
        self.assertEqual(stats["n"], 6)
        self.assertAlmostEqual(stats["net"], -16.0, places=2)
        self.assertEqual(stats["win_rate"], 0.0)
        self.assertTrue(forex.ev_guard_decision(stats, 5, 10.0, 45.0))
        # Pencere dışındaki işlemler sayılmaz
        stats_narrow = forex._collect_symbol_ev("USDCAD", now, 900)
        self.assertEqual(stats_narrow["n"], 2)
        forex._AUTO_STATE["closed_trades"].clear()

    def test_collect_symbol_ev_prefers_mt5_when_connected(self):
        forex._MT5_STATE["connected"] = True
        forex._MT5_STATE["closed_deals"] = [
            {"symbol": "USDCAD", "pnl_usd": -30.0, "exit_time": "2026-10-02 10:00:00 UTC"},
            {"symbol": "USDCAD", "pnl_usd": -30.0, "exit_time": "2026-10-02 10:30:00 UTC"},
        ]
        try:
            # Sabit "şimdi"referansı: son işlem 10:30 → pencereyi 11:00'e koy
            now = datetime.datetime(2026, 10, 2, 11, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
            stats = forex._collect_symbol_ev("USDCAD", now, 12 * 3600)
            self.assertEqual(stats["n"], 2)
            self.assertAlmostEqual(stats["net"], -60.0, places=2)
        finally:
            forex._MT5_STATE["connected"] = False
            forex._MT5_STATE["closed_deals"] = []


class TestADXAndSuperTrend(unittest.IsolatedAsyncioTestCase):
    """ADX (trend gücü) ve SuperTrend (trend yönü) göstergeleri."""

    def test_adx_trending_series_high(self):
        closes = [1.08 + i * 0.0008 for i in range(60)]
        highs = [c + 0.0004 for c in closes]
        lows = [c - 0.0004 for c in closes]
        self.assertGreater(forex._compute_adx(highs, lows, closes, 14), 25.0)

    def test_adx_flat_series_low(self):
        closes = [1.08] * 60
        highs = [1.0802] * 60
        lows = [1.0798] * 60
        self.assertLess(forex._compute_adx(highs, lows, closes, 14), 20.0)

    def test_adx_short_series_guarded(self):
        self.assertEqual(forex._compute_adx([1.08] * 10, [1.0801] * 10, [1.08] * 10, 14), 0.0)

    def test_supertrend_bull_in_uptrend(self):
        closes = [1.08 + i * 0.0008 for i in range(60)]
        highs = [c + 0.0004 for c in closes]
        lows = [c - 0.0004 for c in closes]
        st_dir, st_level = forex._compute_supertrend(highs, lows, closes, 10, 3.0)
        self.assertEqual(st_dir, 1)
        self.assertLess(st_level, closes[-1])

    def test_supertrend_bear_in_downtrend(self):
        closes = [1.08 - i * 0.0008 for i in range(60)]
        highs = [c + 0.0004 for c in closes]
        lows = [c - 0.0004 for c in closes]
        st_dir, st_level = forex._compute_supertrend(highs, lows, closes, 10, 3.0)
        self.assertEqual(st_dir, -1)
        self.assertGreater(st_level, closes[-1])

    def test_indicators_include_adx_and_supertrend(self):
        closes = [1.08 + i * 0.0008 for i in range(60)]
        highs = [c + 0.0004 for c in closes]
        lows = [c - 0.0004 for c in closes]
        opens = [c - 0.0002 for c in closes]
        tech = forex._compute_technical_indicators(closes, highs, lows, opens, "EURUSD")
        self.assertIsNotNone(tech)
        self.assertIn("adx", tech)
        self.assertIn("supertrend_dir", tech)
        self.assertGreater(tech["adx"], 25.0)
        self.assertEqual(tech["supertrend_dir"], 1)

    def test_dxy_not_tradeable_symbol(self):
        """DXY işlem yapılabilir evrende değil, yalnızca veri haritasında."""
        sym_names = [s["symbol"] for s in forex.FOREX_SYMBOLS]
        self.assertNotIn("DXY", sym_names)
        self.assertEqual(forex.YAHOO_SYMBOL_MAP.get("DXY"), "DX-Y.NYB")

    async def test_sync_settings_include_new_flags(self):
        """MT5 köprüsüne giden ayar senkronu yeni bayrakları taşır."""
        req = forex.MT5SyncRequest(account={}, positions=[], ticks={}, deals=[])
        try:
            res = await forex.sync_mt5_bridge(req)
            settings = res["settings"]
            for key in ("atr_exit_enabled", "partial_tp_enabled", "dxy_filter_enabled", "correlation_guard"):
                self.assertIn(key, settings)
        finally:
            forex._MT5_STATE["connected"] = False
            forex._MT5_STATE["pending_commands"] = []
            forex._LAST_CLOSED_DEAL_IDS.clear()

    def test_open_order_command_carries_partial_pips(self):
        """OPEN_ORDER komutu kısmi TP hedefini taşır (köprü plansız pozisyon bırakmamalı)."""
        import inspect
        src = inspect.getsource(forex._forex_auto_paper_loop)
        self.assertIn('"partial_pips"', src)


if __name__ == "__main__":
    unittest.main()
