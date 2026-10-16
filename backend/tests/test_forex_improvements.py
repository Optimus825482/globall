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
import os
import pathlib
import sys
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import HTTPException

from backend.app.forex_correlation import FXCorrelationMonitor
from backend.app.routers import forex
from scripts import mt5_bridge


class _BridgeHeaders:
    def __init__(self, token: str):
        self.headers = {"x-bridge-token": token}


def _bridge_request():
    token = "unit-test-bridge-token"
    os.environ["MT5_BRIDGE_TOKEN"] = token
    return _BridgeHeaders(token)


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
        self.assertEqual(forex.dxy_entry_veto("USDJPY", "BUY", None), "dxy_no_data")
        self.assertEqual(forex.dxy_entry_veto("EURUSD", "SELL", None), "dxy_no_data")
        self.assertIsNone(forex.dxy_entry_veto("XAUUSD", "BUY", None))

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
        self.assertEqual(cfg.major_min_atr_pips, 2.5)
        # 2026-10-06 B3 kazananı: kripto özel stop + BTC özel skor (süpürme: 76 en iyi nokta —
        # işlem düşüşü yalnız %11.5, BTC −$30→+$78, net +$2.018; 78'de hem az işlem hem az kâr)
        self.assertEqual(cfg.crypto_sl_atr_mult, 1.5)
        self.assertEqual(cfg.btc_min_score, 76.0)

    def test_radar_response_contains_dxy_field(self):
        import inspect
        src = inspect.getsource(forex.get_forex_radar)
        self.assertIn('"dxy"', src)


class TestRadarSignalGate(unittest.TestCase):
    """Radar "güçlü sinyal" kapısı — otonom motorun gerçek giriş kararıyla aynı olmalı.

    Regresyon: radar eskiden yalnız skor döndürüyordu ve skor HOLD'da da 50-58
    bandında gezindiği için yönsüz piyasada 15 sembol "sinyal" gibi listeleniyordu.
    """

    def _cand(self, **over):
        base = {
            "symbol": "EURUSD", "display": "EUR/USD", "action": "BUY",
            "score": 90.0, "spread_pips": 1.2, "adx": 30.0, "supertrend_dir": 1,
            "atr_pips": 10.0,
        }
        base.update(over)
        return base

    def _gate(self, sym="EURUSD", hour=12, cand=None, **kw):
        # Saat 12 UTC → majör seans penceresi (7-20) içinde.
        # Nötr DXY: majörde veri yok vetosu bu kapı testlerini kilitlemesin.
        return forex._evaluate_signal_gate(
            sym, cand or self._cand(), hour, {"regime": "USD_NEUTRAL"}, **kw)

    def test_all_gates_open_is_signal_ready(self):
        res = self._gate()
        # Korrelasyon kalkanı açık pozisyon listesi boşken geçer.
        self.assertTrue(res["signal_ready"], res["blocked_by"])
        self.assertEqual(res["blocked_by"], [])
        self.assertIsNone(res["primary_blocker"])

    def test_hold_is_not_a_signal(self):
        """Yönsüz piyasada skor yüksek olsa bile sinyal SAYILMAZ."""
        res = self._gate(cand=self._cand(action="HOLD", score=58.0))
        self.assertFalse(res["signal_ready"])
        self.assertIn("direction", res["blocked_by"])

    def test_score_below_threshold_blocks(self):
        res = self._gate(cand=self._cand(score=70.0))
        self.assertFalse(res["signal_ready"])
        self.assertIn("score", res["blocked_by"])
        self.assertEqual(res["required_score"], 75.0)

    def test_commodity_requires_higher_score(self):
        """Altın/emtia 78 eşiği ister; 75 alan forex paritesi geçemez."""
        res = self._gate(sym="XAUUSD", cand=self._cand(score=76.0, spread_pips=2.5))
        self.assertIn("score", res["blocked_by"])
        self.assertEqual(res["required_score"], 78.0)

    def test_major_session_closed_is_market_blocker(self):
        """Asya seansı (03:00 UTC) majörde piyasa engeli — "ayar" değil."""
        res = self._gate(hour=3)
        self.assertFalse(res["gate_passed"])
        self.assertIn("major_session", res["market_blockers"])

    def test_atr_floor_is_market_blocker(self):
        res = self._gate(cand=self._cand(atr_pips=1.5))
        self.assertIn("major_min_atr", res["market_blockers"])

    def test_supertrend_conflict_blocks(self):
        res = self._gate(cand=self._cand(action="BUY", supertrend_dir=-1))
        self.assertIn("supertrend", res["blocked_by"])

    def test_open_position_is_not_a_market_blocker(self):
        """Açık pozisyon piyasa kalitesini bozmaz: kullanıcı "ayar" ile karıştırmasın."""
        res = self._gate(has_open_position=True)
        self.assertIn("open_position", res["blocked_by"])
        self.assertEqual(res["market_blockers"], [])
        self.assertTrue(res["gate_passed"])
        self.assertFalse(res["signal_ready"])

    def test_market_blockers_come_before_position_state(self):
        """Sıralama: gerçek piyasa engeli, "zaten pozisyonum var"ın önüne geçer."""
        res = self._gate(cand=self._cand(atr_pips=1.0), has_open_position=True)
        self.assertEqual(res["primary_blocker"], "major_min_atr")

    def test_commodity_uses_higher_threshold_than_btc(self):
        self.assertEqual(self._gate(sym="XAUUSD")["required_score"], 78.0)
        self.assertEqual(self._gate(sym="USOIL")["required_score"], 78.0)
        self.assertEqual(self._gate(sym="EURUSD")["required_score"], 75.0)

    def test_gate_has_no_allowed_symbols_gate(self):
        """`allowed_symbols` (XAUUSD+BTCUSD) yalnız BTC+Altın izleme sayfasının
        kısıtıdır; genel forex radarını elemEMELİ.

        Regresyon: bu kapı eklendiğinde 15 sembolün 13'ü "izin listesinde
        değil" diye düşüyor ve radar işe yaramaz hale geliyordu.
        """
        res = self._gate(sym="EURUSD")
        self.assertNotIn("allowed", res["blocked_by"])
        self.assertTrue(res["signal_ready"], res["blocked_by"])
        self.assertNotIn("allowed", forex._GATE_LABELS)


class TestRadarScanNote(unittest.TestCase):
    """Tarama durum cümlesi: kullanıcıya sinyal var/yok ve nedenini söyler."""

    def _c(self, tier, blocker=None, display="EUR/USD"):
        return {"tier": tier, "display": display, "primary_blocker": blocker}

    def test_reports_strong_signals_with_names(self):
        note = forex._radar_scan_note(
            [self._c("STRONG", display="BTC/USD"), self._c("STRONG", display="XAU/USD"),
             self._c("WAIT", "direction")], 12)
        self.assertIn("2 güçlü sinyal", note)
        self.assertIn("BTC/USD", note)

    def test_strong_list_truncates_after_three(self):
        note = forex._radar_scan_note(
            [self._c("STRONG", display=f"S{i}") for i in range(5)], 12)
        self.assertIn("+2 daha", note)

    def test_no_signal_names_dominant_blocker(self):
        note = forex._radar_scan_note(
            [self._c("WAIT", "direction"), self._c("WAIT", "direction"),
             self._c("WATCH", "major_session")], 3)
        self.assertIn("en yaygın engel", note)
        self.assertIn("Yön belirsiz", note)

    def test_empty_scan_says_data_pending(self):
        self.assertIn("verisi bekleniyor", forex._radar_scan_note([], 12))


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
        # BTC ATR 300 pip: SL 40 → 330. TP spec 130'un üstüne çıkmaz (1.5R tabanı spec'i ezmez).
        levels = forex.get_atr_exit_levels(300.0, 40.0, 130.0)
        self.assertEqual(levels["sl_pips"], 330.0)
        self.assertEqual(levels["tp_pips"], 130.0)
        self.assertLessEqual(levels["tp_pips"], 130.0)

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

    def test_missing_data_reports_none_not_zero(self):
        """#9: matriste olmayan çift None döner (fail-closed); 0.0 "güvenli" DEĞİL."""
        mon = FXCorrelationMonitor()
        self.assertIsNone(mon.correlation_of("EURUSD", "GBPUSD"))

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

    def test_fail_closed_without_correlation_data(self):
        """#9: korelasyon verisi yoksa çift BİLİNMİYOR sayılır → engellenir."""
        mon = FXCorrelationMonitor()
        allowed, reason = mon.cluster_check("EURUSD", "USD_SHORT", [("GBPUSD", "USD_SHORT")])
        self.assertFalse(allowed)
        self.assertIn("no_corr_data", reason)

    def test_stale_symbols_kept_not_pruned(self):
        """#9: bir turda veri gelmeyen sembol matristen SİLİNMEZ (kalkan körleşmesin)."""
        mon = FXCorrelationMonitor()
        rets = _noisy_rets(119, seed=21)
        mon.refresh({"EURUSD": _closes_from_rets(rets), "GBPUSD": _closes_from_rets(rets)})
        mon.refresh({"EURUSD": _closes_from_rets(_noisy_rets(119, seed=22))})
        snap = mon.snapshot()
        # GBPUSD hâlâ matriste: verisi gelmeyince korunur, silinmez.
        self.assertIn("GBPUSD", snap)


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
        # TP-iptal canlı VARSAYILAN AÇIK (2026-10-09 kararı: IS/OOS/OOS2/F1 dört pencerede
        # işaret-tutarlı tek kazanan, net + maxDD iyi). Geri alma: FOREX_TP_CANCEL_ON_TRAIL=false
        self.assertTrue(cfg.tp_cancel_on_trail)
        # Zayıf saat kalkanı kullanıcı kararıyla kaldırıldı — varsayılan boş liste
        self.assertEqual(list(cfg.blocked_hours_utc), [])
        # EV kalkanı varsayılanları (WR 45: 2026-10-06 30g replay A/B kararı; 35 → 45)
        self.assertTrue(cfg.ev_guard_enabled)
        self.assertEqual(cfg.ev_window_hours, 24.0)
        self.assertEqual(cfg.ev_min_trades, 10)
        self.assertEqual(cfg.ev_max_win_rate, 45.0)
        self.assertEqual(cfg.ev_loss_risk_mult, 3.0)
        # allowed_symbols: 10 sembol (2026-10-12: 13 hayalet kros çıkarıldı; 2026-10-13: NAS100
        # (= MT5 USTEC) EKLENDİ — kullanıcı kararı 'tüm kollarda aç', tam-defter A/B +$207/+)
        self.assertEqual(len(cfg.allowed_symbols), 10)
        self.assertIn("XAUUSD", cfg.allowed_symbols)
        self.assertIn("BTCUSD", cfg.allowed_symbols)
        self.assertIn("US30", cfg.allowed_symbols)
        self.assertIn("GBPUSD", cfg.allowed_symbols)
        self.assertIn("NAS100", cfg.allowed_symbols)      # 2026-10-13 eklendi (MT5 'USTEC')
        self.assertNotIn("AUDNZD", cfg.allowed_symbols)   # hayalet — çıkarıldı
        self.assertNotIn("GBPCHF", cfg.allowed_symbols)   # hayalet — çıkarıldı
        self.assertNotIn("DXY", cfg.allowed_symbols)


class TestManualScanNow(unittest.TestCase):
    """Manuel 'Şimdi Tara' satır üreticisi — salt-okunur tarama disiplini.

    Regresyon: `_scan_now_strategy_rows` motor sayaçlarını (day_counts,
    `_DONCHIAN_STATE`/`_LB_STATE`) güncellememeli; aksi halde manuel tarama
    gerçek girişin gün-limitini yakar ve motor o gün işlem açamaz.
    """

    def test_rows_readonly_and_complete(self):
        cfg = forex.ForexAutoPaperSettings()
        radar = {"candidates": [{"symbol": "EURUSD", "display": "EUR/USD", "action": "BUY",
                                 "score": 88.0, "tier": "ACTIVE"}], "scan_note": ""}
        ticks = {sym: {"display": sym, "bid": 1.1, "ask": 1.1001} for sym in cfg.lb_symbols}
        for sym in cfg.mode_symbols + cfg.ema_adx_symbols + cfg.s3_symbols_5m + cfg.s3_symbols_15m:
            ticks.setdefault(sym, {"display": sym, "bid": 1.1, "ask": 1.1001})

        donch_before = {k: dict(v) for k, v in forex._DONCHIAN_STATE.items()}
        lb_before = {k: dict(v) for k, v in forex._LB_STATE.items()}
        s3day_before = {k: dict(v) for k, v in forex._S3_DAY_STATE.items()}
        ema_before = {k: dict(v) for k, v in forex._EMA_ADX_STATE.items()}

        rows = forex._scan_now_strategy_rows(ticks, radar)

        # Tüm strateji kolları temsil edilmeli
        strategies = {r["strategy"] for r in rows}
        self.assertIn("RADAR", strategies)
        self.assertIn("DONCHIAN_ADX", strategies)
        self.assertNotIn("S3_5M", strategies)
        self.assertNotIn("S3_15M", strategies)
        self.assertIn("LONDON_BREAKOUT", strategies)
        # EAP kolu da var (ema_adx_enabled=True)
        self.assertIn(forex.EMA_ADX_PULLBACK_STRATEGY, strategies)
        # Her satır insan-okur alanlar taşır
        for r in rows:
            self.assertTrue(r["status"], f"boş status: {r}")
            self.assertIn("strategy_label", r)
            self.assertIn("panel_kapsaminda", r)

        # Salt-okunur: motor state dict'lerine yazılmamış olmalı
        self.assertEqual({k: dict(v) for k, v in forex._DONCHIAN_STATE.items()}, donch_before)
        self.assertEqual({k: dict(v) for k, v in forex._LB_STATE.items()}, lb_before)
        self.assertEqual({k: dict(v) for k, v in forex._S3_DAY_STATE.items()}, s3day_before)
        self.assertEqual({k: dict(v) for k, v in forex._EMA_ADX_STATE.items()}, ema_before)

    def test_lb_state_not_advanced_by_scan(self):
        """LB örneği: kutu-dışı saatta tarama `counts`'a dokunmaz (giriş olsa bile
        manuel tur motorun gün-limitini harcamaz)."""
        cfg = forex.ForexAutoPaperSettings()
        radar = {"candidates": [], "scan_note": "yok"}
        sym = "GBPUSD"  # default lb_symbols üyesi
        ticks = {sym: {"display": "GBP/USD", "bid": 1.09, "ask": 1.0901}}
        # Kutuyu kırılıma zorla: hour < entry_end varsayımıyla box üstüne fiyat
        forex._LB_STATE[sym] = {
            "day": datetime.datetime.now(datetime.timezone.utc).toordinal(),
            "box_hi": 1.08, "box_lo": 1.07, "counts": {},
        }
        try:
            rows = forex._scan_now_strategy_rows(ticks, radar)
            lb_rows = [r for r in rows if r["strategy"] == "LONDON_BREAKOUT" and r["symbol"] == sym]
            self.assertTrue(lb_rows)
            # Sayaçlar taramayla artmamalı
            self.assertEqual(forex._LB_STATE[sym]["counts"], {})
        finally:
            forex._LB_STATE.pop(sym, None)

    def test_every_enabled_arm_is_scanned(self):
        """Motordaki HER açık giriş kolu tarama raporunda temsil edilmeli.

        Regresyon (2026-10-13): London Sign 2026-10-12'de 6. giriş kolu olarak
        canlıya alındı ama `_scan_now_strategy_rows`'a eklenmedi — kol gerçekte
        işlem açıyordu, radar sayfası ise onu hiç taramıyordu. Bu test, kol
        listesi ile tarayıcının kapsamı ayrışırsa kırılır.
        """
        cfg = forex.ForexAutoPaperSettings()
        self.assertFalse(cfg.s3_enabled, "2026-10-16 replay: S3 varsayılan kapalı")
        self.assertFalse(cfg.ls_enabled, "2026-10-16 replay: London Sign varsayılan kapalı")
        self.assertFalse(forex._AUTO_SETTINGS.s3_enabled)
        self.assertFalse(forex._AUTO_SETTINGS.ls_enabled)
        radar = {"candidates": [], "scan_note": "yok"}
        ticks = {sym: {"display": sym, "bid": 1.1, "ask": 1.1001} for sym in cfg.ls_symbols}
        for sym in cfg.lb_symbols + cfg.mode_symbols + cfg.ema_adx_symbols \
                + cfg.s3_symbols_5m + cfg.s3_symbols_15m:
            ticks.setdefault(sym, {"display": sym, "bid": 1.1, "ask": 1.1001})

        rows = forex._scan_now_strategy_rows(ticks, radar)

        strategies = {r["strategy"] for r in rows}
        expected = {
            "RADAR",
            "DONCHIAN_ADX",
            forex.EMA_ADX_PULLBACK_STRATEGY,
            forex.LONDON_BREAKOUT_STRATEGY,
            forex.SQUEEZE_KC_STRATEGY,
        }
        missing = expected - strategies
        self.assertEqual(missing, set(), f"taranmayan giriş kolu: {missing}")
        self.assertNotIn("S3_5M", strategies)
        self.assertNotIn("S3_15M", strategies)
        self.assertNotIn(forex.LONDON_SIGN_STRATEGY, strategies)

    def test_ls_state_not_advanced_by_scan(self):
        """LS örneği: tarama `_LS_STATE`'i (sign/entered) değiştirmemeli —
        aksi halde manuel tur motorun günlük tek-giriş hakkını yakardı."""
        sym = "XAUUSD"  # varsayılan ls_symbols üyesi
        radar = {"candidates": [], "scan_note": "yok"}
        ticks = {sym: {"display": "XAU/USD", "bid": 2400.0, "ask": 2400.3}}
        day = datetime.datetime.now(datetime.timezone.utc).toordinal()
        forex._LS_STATE[sym] = {
            "day": day, "sign_open": 2400.0, "sign_close": 2401.0, "entered": False,
        }
        try:
            forex._scan_now_strategy_rows(ticks, radar)
            state = forex._LS_STATE[sym]
            self.assertEqual(state["sign_open"], 2400.0)
            self.assertEqual(state["sign_close"], 2401.0)
            self.assertFalse(state["entered"], "tarama LS 'entered' bayrağını yakmamalı")
        finally:
            forex._LS_STATE.pop(sym, None)

    def test_ls_row_mirrors_motor_on_missing_atr(self):
        """Giriş penceresi sembol başına TEK satır üretmeli ve ATR yokken aday
        göstermemeli — motor da 5191-5192'de SL hesaplanamayınca girişe izin
        vermez. Aksi halde radar "BUY adayı, SL 0.0p" gösterip kullanıcıyı
        açılmayacak bir işleme inandırırdı.
        """
        cfg = forex.ForexAutoPaperSettings()
        sym = "XAUUSD"  # varsayılan ls_symbols üyesi
        radar = {"candidates": [], "scan_note": "yok"}
        ticks = {sym: {"display": "XAU/USD", "bid": 2400.0, "ask": 2400.3}}
        day = datetime.datetime.now(datetime.timezone.utc).toordinal()
        # Sign yukarı: giriş penceresi açık olsa BUY adayı çıkardı
        forex._LS_STATE[sym] = {"day": day, "sign_open": 2400.0,
                                "sign_close": 2401.0, "entered": False}
        had_tech = sym in forex._TECHNICAL_CACHE
        tech_before = dict(forex._TECHNICAL_CACHE.get(sym) or {})

        _today = datetime.datetime.now(datetime.timezone.utc)

        class _FixedDT(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                # 14:05 UTC — giriş penceresi (14:00–14:30) içinde, gün state ile aynı.
                return cls(_today.year, _today.month, _today.day, 14, 5, tzinfo=datetime.timezone.utc)

        saved_ls = forex._AUTO_SETTINGS.ls_enabled
        try:
            forex._AUTO_SETTINGS.ls_enabled = True
            forex._TECHNICAL_CACHE.pop(sym, None)  # ATR yok
            with mock.patch.object(forex.datetime, "datetime", _FixedDT):
                rows = forex._scan_now_strategy_rows(ticks, radar)
            ls_rows = [r for r in rows
                       if r["strategy"] == forex.LONDON_SIGN_STRATEGY and r["symbol"] == sym]
            self.assertEqual(len(ls_rows), 1, f"sembol başına tek satır olmalı: {ls_rows}")
            self.assertIsNone(ls_rows[0]["action"], "ATR yokken aday gösterilmemeli")
            self.assertIn("ATR", ls_rows[0]["status"])

            # ATR varken aynı durum gerçek aday üretmeli
            forex._TECHNICAL_CACHE[sym] = {"atr": 12.0}
            with mock.patch.object(forex.datetime, "datetime", _FixedDT):
                rows2 = forex._scan_now_strategy_rows(ticks, radar)
            ls2 = [r for r in rows2
                   if r["strategy"] == forex.LONDON_SIGN_STRATEGY and r["symbol"] == sym]
            self.assertEqual(len(ls2), 1)
            self.assertEqual(ls2[0]["action"], "BUY")
        finally:
            forex._AUTO_SETTINGS.ls_enabled = saved_ls
            if had_tech:
                forex._TECHNICAL_CACHE[sym] = tech_before
            else:
                forex._TECHNICAL_CACHE.pop(sym, None)
            forex._LS_STATE.pop(sym, None)


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

    def test_risk_hard_mult_single_source(self):
        """Sert tavan TEK KAYNAK olmalı: normalizasyon ve kelepçe aynı çarpanı kullanır (2026-10-14)."""
        self.assertEqual(forex.RISK_HARD_MULT, 2.0)
        # Tam sınır: kategori tabanı 0.10 × 200 pip × 1.0 = 20.0 == 2 × bütçe 10.0 → geçer
        lots, skip = forex.apply_risk_normalization("US30", 0.20, 200.0, 1.0, 10.0)
        self.assertFalse(skip)
        self.assertEqual(lots, 0.10)
        self.assertAlmostEqual(lots * 200.0 * 1.0, 10.0 * forex.RISK_HARD_MULT, places=6)

    def test_floor_lot_budget_guard_blocks_oversized_minimum(self):
        """Kelepçe düzeltmesi: taban lot sert tavanı aşıyorsa kelepçe UYGULANMAMALI (işlem pas).

        Gerçek olay (ReportHistory-53077151, 2026-10-13 17:14): bakiye ~$58.7, ayar %5
        → bütçe $2.94; taban lot 0.01 × 73.4 pip × $10 = $7.34 = 2.5 × bütçe.
        """
        self.assertFalse(forex.floor_lot_respects_budget(0.01, 73.4, 10.0, 58.7 * 0.05))
        # 2026-10-14 varsayılanı %2 ile $41.16 bakiye: bütçe $0.82 → taban lot 8.9× bütçe → pas
        self.assertFalse(forex.floor_lot_respects_budget(0.01, 73.4, 10.0, 41.16 * 0.02))
        # Bakiye ~$250 (%2) olduğunda taban lot sert tavana sığar → kelepçe tekrar çalışır
        self.assertTrue(forex.floor_lot_respects_budget(0.01, 73.4, 10.0, 250.0 * 0.02))
        # Tam sınır: 0.01 × 100 pip × 10 = 10.0 == 2 × 5.0 → geçer (<=)
        self.assertTrue(forex.floor_lot_respects_budget(0.01, 100.0, 10.0, 5.0))
        # Dejenere girdiler güvenli tarafta kalmalı (kelepçe uygulanmaz)
        for bad in ((0.0, 73.4, 10.0, 5.0), (0.01, 0.0, 10.0, 5.0),
                    (0.01, 73.4, 0.0, 5.0), (0.01, 73.4, 10.0, 0.0),
                    (-0.01, 73.4, 10.0, 5.0)):
            self.assertFalse(forex.floor_lot_respects_budget(*bad))

    def test_clamp_is_guarded_by_budget(self):
        """Kaynak kilidi: kelepçe dalı bütçe kapısından geçmeden lotu sabitlememeli."""
        src = pathlib.Path(forex.__file__).read_text(encoding="utf-8")
        self.assertIn("floor_lot_respects_budget(_floor_lot, sl_pips, pip_val, risk_usd)", src)
        # Eski koşulsuz sabitleme deseni geri gelmemeli
        self.assertNotIn(
            "_floor_lot = min(HARD_MAX_GOLD_LOT, _AUTO_SETTINGS.max_gold_lot, 0.01)\n"
            "                        mt5_lots = max(0.01, _floor_lot)", src)


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
            res = await forex.sync_mt5_bridge(req, _bridge_request())
            settings = res["settings"]
            for key in ("atr_exit_enabled", "partial_tp_enabled", "dxy_filter_enabled", "correlation_guard",
                        "tp_cancel_on_trail"):
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


class TestTickPrimaryGuards(unittest.IsolatedAsyncioTestCase):
    """Tik birincil kaynak, Wilder ADX, kısa Pearson ve köprü fail-closed."""

    async def test_rsi_uses_closed_broker_candles_when_ticks_are_short(self):
        """5m tik kovası 30 bar dolmadan RSI, kapanmış MT5 mumundan gelir.

        Açık (oluşan) mum hesaba girmez. Yükselen kapanmış seri RSI'yi 50'nin
        üstüne taşır; oluşan mumun çöküşü dahil edilirse RSI çöker.
        """
        sym = "XAUUSD"
        forex._TECHNICAL_CACHE.pop(sym, None)
        forex._CLOSED_TICK_BARS.pop((sym, 300), None)
        forex._OPEN_TICK_BUCKET.pop((sym, 300), None)
        forex._TICK_CACHE.pop(sym, None)
        now = time.time()
        bucket = int(now // 300) * 300
        closed = []
        for i in range(40, 0, -1):
            px = 4000.0 + (40 - i)
            closed.append({
                "time": bucket - i * 300,
                "open": px,
                "high": px + 1.0,
                "low": px - 0.5,
                "close": px + 0.4,
                "volume": 0.0,
            })
        forming = {
            "time": bucket,
            "open": 4100.0,
            "high": 4100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 0.0,
        }
        forex._MT5_CANDLES_CACHE[f"{sym}|5m"] = (now, closed + [forming])
        forex._PRICE_SOURCE[sym] = "mt5_tick"
        forex._PRICE_TS[sym] = now
        forex._LIVE_PRICES_CACHE[sym] = 4173.0
        forex._LIVE_SPREAD_PIPS[sym] = 0.5
        forex._LAST_TECH_FETCH_TIME = 0.0
        try:
            ticks = await forex._generate_realistic_ticks()
            row = ticks[sym]
            tech = forex._TECHNICAL_CACHE[sym]
            self.assertGreater(row["rsi"], 80.0)
            self.assertNotEqual(row["macd_verdict"], "NÖTR (Veri Bekleniyor)")
            self.assertEqual(tech["source"], "mt5_candle")
            self.assertEqual(tech["signal_bar_time"], closed[-1]["time"])
        finally:
            forex._MT5_CANDLES_CACHE.pop(f"{sym}|5m", None)
            forex._TECHNICAL_CACHE.pop(sym, None)
            forex._PRICE_SOURCE.pop(sym, None)
            forex._PRICE_TS.pop(sym, None)
            forex._LIVE_PRICES_CACHE.pop(sym, None)
            forex._LIVE_SPREAD_PIPS.pop(sym, None)

    def test_strategy_bars_use_broker_candles_when_ticks_are_short(self):
        """London / Squeeze / S3 barları tik kovası dolmadan kapanmış mumdan gelir."""
        sym = "XAUUSD"
        forex._CLOSED_TICK_BARS.pop((sym, 300), None)
        forex._CLOSED_TICK_BARS.pop((sym, 900), None)
        forex._OPEN_TICK_BUCKET.pop((sym, 300), None)
        forex._OPEN_TICK_BUCKET.pop((sym, 900), None)
        now = time.time()
        bucket = int(now // 300) * 300
        closed = []
        for i in range(40, 0, -1):
            px = 4100.0 + (40 - i) * 0.2
            closed.append({
                "time": bucket - i * 300,
                "open": px,
                "high": px + 0.8,
                "low": px - 0.4,
                "close": px + 0.2,
                "volume": 0.0,
            })
        forming = {"time": bucket, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0.0}
        forex._MT5_CANDLES_CACHE[f"{sym}|5m"] = (now, closed + [forming])
        try:
            bars = forex._s3_bars_for(sym, "5m", limit=220)
            self.assertIsNotNone(bars)
            self.assertGreaterEqual(len(bars), 30)
            self.assertEqual(bars[-1]["time"], closed[-1]["time"])
            self.assertNotEqual(bars[-1]["close"], 1.0)
        finally:
            forex._MT5_CANDLES_CACHE.pop(f"{sym}|5m", None)

    def test_score_path_does_not_call_yahoo(self):
        import inspect
        refresh = inspect.getsource(forex._refresh_live_rates_if_needed)
        self.assertIn("_rebuild_tech_from_ticks", refresh)
        self.assertNotIn("_sync_fetch", refresh)
        self.assertNotIn("query1.finance.yahoo", refresh)
        bars = inspect.getsource(forex._s3_bars_for)
        self.assertNotIn("_fetch_forex_klines", bars)
        self.assertNotIn("query1.finance.yahoo", bars)
        klines = inspect.getsource(forex._fetch_forex_klines)
        self.assertNotIn("finance.yahoo", klines)
        self.assertNotIn("frankfurter", inspect.getsource(forex._sync_fetch_live_rates))

    def test_compute_adx_same_direction_as_canonical(self):
        from backend.app.technical_analysis import _adx
        n = 80
        closes = [100.0 + i * 0.4 for i in range(n)]
        highs = [c + 0.15 for c in closes]
        lows = [c - 0.05 for c in closes]
        fx = forex._compute_adx(highs, lows, closes, 14)
        ta = _adx(highs, lows, closes, 14)
        ta_adx = float(ta["adx"]) if isinstance(ta, dict) else float(ta)
        self.assertGreater(fx, 20.0)
        self.assertGreater(ta_adx, 20.0)
        flat = [100.0] * n
        self.assertEqual(forex._compute_adx(flat, flat, flat, 14), 0.0)
        self.assertLess(abs(fx - ta_adx), 5.0)

    def test_supertrend_series_matches_compute(self):
        bars = []
        for i in range(40):
            c = 1.10 + i * 0.001
            bars.append({"time": 1_700_000_000 + i * 300, "open": c - 0.0002,
                         "high": c + 0.0004, "low": c - 0.0003, "close": c})
        dirs = forex._s3_st_dir_series(bars, 10, 3.0)
        st_dir, _level = forex._compute_supertrend(
            [b["high"] for b in bars], [b["low"] for b in bars], [b["close"] for b in bars], 10, 3.0,
        )
        self.assertEqual(dirs[-1], st_dir)
        self.assertNotEqual(st_dir, 0)

    def test_short_pearson_is_none_and_blocks(self):
        from backend.app.forex_correlation import _pearson
        self.assertIsNone(_pearson(list(range(10)), list(range(10))))
        mon = FXCorrelationMonitor()
        ok, why = mon.cluster_check("EURUSD", "USD_SHORT", [("GBPUSD", "USD_SHORT")])
        self.assertFalse(ok)
        self.assertIn("no_corr", why)

    def test_canonical_tick_lands_on_app_symbol(self):
        ts = time.time()
        forex._note_mt5_tick("USTEC", 18000.0, 18002.0, ts)
        forex._note_mt5_tick("XAUUSD.m", 2300.0, 2300.4, ts)
        self.assertEqual(forex._PRICE_SOURCE.get("NAS100"), "mt5_tick")
        self.assertEqual(forex._PRICE_SOURCE.get("XAUUSD"), "mt5_tick")
        self.assertIn("NAS100", forex._LIVE_PRICES_CACHE)
        self.assertIn("XAUUSD", forex._LIVE_PRICES_CACHE)

    def test_s3_15m_does_not_reuse_5m_bars(self):
        key5 = ("GBPCAD", 300)
        key15 = ("GBPCAD", 900)
        forex._CLOSED_TICK_BARS.pop(key5, None)
        forex._CLOSED_TICK_BARS.pop(key15, None)
        forex._OPEN_TICK_BUCKET.pop(key5, None)
        forex._OPEN_TICK_BUCKET.pop(key15, None)
        base = 1_700_000_000
        for i in range(230):
            px = 1.2 + i * 0.0002
            forex._fold_tick_into_bucket("GBPCAD", 900, base + i * 900, px)
        forex._fold_tick_into_bucket("GBPCAD", 900, base + 230 * 900, 1.3)
        self.assertIsNone(forex._s3_tech_for("GBPCAD", "5m"))
        self.assertIsNotNone(forex._s3_tech_for("GBPCAD", "15m"))

    async def test_unauthorized_sync_does_not_drain(self):
        keys = ("MT5_BRIDGE_TOKEN", "FOREX_MT5_SYNC_TOKEN", "BINANCE_TR_BRIDGE_SECRET")
        saved = {k: os.environ.get(k) for k in keys}
        pending = [{"id": "KEEP-ME", "action": "OPEN_ORDER", "symbol": "EURUSD"}]
        forex._MT5_STATE["connected"] = False
        forex._MT5_STATE["pending_commands"] = list(pending)
        try:
            for k in keys:
                os.environ.pop(k, None)
            with self.assertRaises(HTTPException) as ctx:
                await forex.sync_mt5_bridge(forex.MT5SyncRequest(
                    ticks={"EURUSD": {"bid": 1.1, "ask": 1.1002}},
                ))
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertFalse(forex._MT5_STATE["connected"])
            self.assertEqual(forex._MT5_STATE["pending_commands"], pending)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            forex._MT5_STATE["pending_commands"] = []
            forex._MT5_STATE["connected"] = False

    async def test_missing_command_success_is_failure(self):
        now = time.time()
        forex._LAST_SYMBOL_ENTRY_TIME["EURUSD"] = now
        forex._LAST_GOLD_EXIT_TIME = now
        try:
            await forex.sync_mt5_bridge(forex.MT5SyncRequest(command_results=[
                {"id": "CMD-X", "action": "OPEN_ORDER", "symbol": "EURUSD"},
            ]), _bridge_request())
            self.assertNotIn("EURUSD", forex._LAST_SYMBOL_ENTRY_TIME)
            self.assertEqual(forex._LAST_GOLD_EXIT_TIME, now)
        finally:
            forex._LAST_SYMBOL_ENTRY_TIME.pop("EURUSD", None)

    async def test_placeholder_price_does_not_arm(self):
        forex._RADAR_CACHE = None
        forex._LAST_TECH_FETCH_TIME = 0.0
        sym = "GBPUSD"
        forex._TECHNICAL_CACHE.pop(sym, None)
        forex._PRICE_SOURCE.pop(sym, None)
        forex._PRICE_TS.pop(sym, None)
        forex._LIVE_PRICES_CACHE.pop(sym, None)
        forex._LIVE_SPREAD_PIPS.pop(sym, None)
        forex._CLOSED_TICK_BARS.pop((sym, 300), None)
        forex._CLOSED_TICK_BARS.pop((sym, 900), None)
        forex._OPEN_TICK_BUCKET.pop((sym, 300), None)
        forex._OPEN_TICK_BUCKET.pop((sym, 900), None)
        ticks = await forex._generate_realistic_ticks()
        row = ticks[sym]
        self.assertEqual(row["action"], "HOLD")
        self.assertNotEqual(row["source"], "mt5_tick")
        self.assertFalse(row["spread_known"])
        self.assertEqual(row["updated_at"], 0.0)
        radar = await forex.get_forex_radar(use_cache=False)
        card = next(c for c in radar["candidates"] if c["symbol"] == sym)
        self.assertIn("rsi_5m", card)
        self.assertEqual(card["rsi_5m"], card["rsi_15m"])
        self.assertIn("age_sec", card)
        self.assertIn("skor_gecti", card)
        self.assertIn("motor_acar", card)
        self.assertFalse(card["motor_acar"])

    async def test_klines_and_tickers_fail_closed_without_ticks(self):
        forex._CLOSED_TICK_BARS.pop(("EURUSD", 60), None)
        forex._CLOSED_TICK_BARS.pop(("EURUSD", 300), None)
        forex._CLOSED_TICK_BARS.pop(("EURUSD", 900), None)
        forex._OPEN_TICK_BUCKET.pop(("EURUSD", 300), None)
        forex._PRICE_SOURCE.pop("EURUSD", None)
        forex._LIVE_PRICES_CACHE.pop("EURUSD", None)
        forex._MT5_CANDLES_CACHE.pop("EURUSD|5m", None)
        bars, err = forex._forex_klines_from_ticks("EURUSD", "5m", 50)
        self.assertEqual(bars, [])
        self.assertEqual(err, "MT5 tik yok")
        payload = await forex.get_forex_klines(symbol="EURUSD", interval="5m", limit=50)
        self.assertEqual(payload["candles"], [])
        self.assertEqual(payload["error"], "MT5 geçmişi bekleniyor")
        self.assertIsNone(payload["current_price"])
        now = 1_700_000_000
        forex._MT5_CANDLES_CACHE["EURUSD|5m"] = (time.time(), [
            {"time": now + i * 300, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "volume": 0.0}
            for i in range(40)
        ])
        filled = await forex.get_forex_klines(symbol="EURUSD", interval="5m", limit=50)
        self.assertIsNone(filled["error"])
        self.assertEqual(filled["source"], "mt5_candle")
        self.assertEqual(len(filled["candles"]), 40)
        forex._MT5_CANDLES_CACHE.pop("EURUSD|5m", None)
        tickers = await forex.get_forex_tickers()
        eurusd = next(t for t in tickers["tickers"] if t["symbol"] == "EURUSD")
        self.assertIsNone(eurusd["price"])
        self.assertEqual(eurusd["error"], "MT5 tik yok")

    def test_klines_use_closed_tick_buckets(self):
        sym = "NZDUSD"
        for sec in (60, 300, 900):
            forex._CLOSED_TICK_BARS.pop((sym, sec), None)
            forex._OPEN_TICK_BUCKET.pop((sym, sec), None)
        forex._PRICE_SOURCE[sym] = "mt5_tick"
        forex._LIVE_PRICES_CACHE[sym] = 0.61
        base = 1_700_000_000
        for i in range(20):
            forex._fold_tick_into_bucket(sym, 300, base + i * 300, 0.60 + i * 0.0001)
        forex._fold_tick_into_bucket(sym, 300, base + 20 * 300, 0.62)
        short, short_err = forex._forex_klines_from_ticks(sym, "5m", 100)
        self.assertEqual(short, [])
        self.assertEqual(short_err, "MT5 tik geçmişi kısa")
        for i in range(21, 40):
            forex._fold_tick_into_bucket(sym, 300, base + i * 300, 0.60 + i * 0.0001)
        forex._fold_tick_into_bucket(sym, 300, base + 40 * 300, 0.64)
        bars, err = forex._forex_klines_from_ticks(sym, "5m", 100)
        self.assertIsNone(err)
        self.assertGreaterEqual(len(bars), 30)
        self.assertEqual(bars[0]["time"] % 300, 0)


if __name__ == "__main__":
    unittest.main()
