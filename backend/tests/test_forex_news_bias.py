"""Ekonomik takvim yön kanıtı (forex_news_bias) testleri — 2026-10-14.

Kapsam:
- Para birimi gücü → sembol yönü eşlemesi (`symbol_direction`)
- Açıklanmış olay süzgeci (`released_biases`): gelecek/bayat/açıklanmamış olaylar
  yön ÜRETMEZ; çelişen olaylar nötre döner
- Ayarların varsayılanları ve giriş zincirindeki kapı kablolaması (kaynak kilidi)
"""
from __future__ import annotations

import datetime
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import forex_news_bias as nb
from app.routers import forex


def _ts(y, mo, d, h=0, mi=0):
    return datetime.datetime(y, mo, d, h, mi, tzinfo=datetime.timezone.utc).timestamp()


class SymbolDirectionTests(unittest.TestCase):
    def test_base_quote_mapping(self):
        # Para birimi BASE ise aynı yön, QUOTE ise ters yön
        self.assertEqual(nb.symbol_direction("EUR", True, "EURUSD"), 1)
        self.assertEqual(nb.symbol_direction("EUR", False, "EURUSD"), -1)
        self.assertEqual(nb.symbol_direction("USD", True, "EURUSD"), -1)
        self.assertEqual(nb.symbol_direction("USD", False, "EURUSD"), 1)
        self.assertEqual(nb.symbol_direction("USD", True, "USDJPY"), 1)
        self.assertEqual(nb.symbol_direction("JPY", True, "USDJPY"), -1)

    def test_usd_quoted_metals_and_crypto(self):
        # USD güçlenince altın ve BTC düşer
        self.assertEqual(nb.symbol_direction("USD", True, "XAUUSD"), -1)
        self.assertEqual(nb.symbol_direction("USD", False, "XAUUSD"), 1)
        self.assertEqual(nb.symbol_direction("USD", True, "BTCUSD"), -1)

    def test_oil_and_ambiguous_are_handled(self):
        # Petrol: USD↑ → petrol ↓ ; CAD↑ → petrol ↑
        self.assertEqual(nb.symbol_direction("USD", True, "USOIL"), -1)
        self.assertEqual(nb.symbol_direction("CAD", True, "USOIL"), 1)
        # Endeksler ve XAUUSD×AUD: yön savunulamaz → nötr
        self.assertEqual(nb.symbol_direction("USD", True, "US30"), 0)
        self.assertEqual(nb.symbol_direction("USD", True, "NAS100"), 0)
        self.assertEqual(nb.symbol_direction("AUD", True, "XAUUSD"), 0)

    def test_degenerate_inputs_are_neutral(self):
        for args in (("", True, "EURUSD"), ("USD", True, ""), ("", True, "")):
            self.assertEqual(nb.symbol_direction(*args), 0)


class ReleasedBiasesTests(unittest.TestCase):
    def _ev(self, **kw):
        base = {
            "title": "US CPI m/m", "currency": "USD",
            "date_iso": "2026-10-14T06:00:00Z",
            "forecast": "3.0%", "previous": "2.8%", "actual": "3.4%",
            "affected_symbols": ["XAUUSD", "EURUSD", "USDJPY"],
        }
        base.update(kw)
        return base

    def test_released_above_forecast_gives_expected_directions(self):
        now = _ts(2026, 10, 14, 6, 5)
        b = nb.released_biases([self._ev()], now)
        self.assertEqual(b["XAUUSD"]["dir"], -1)   # USD güçlü → altın SELL
        self.assertEqual(b["EURUSD"]["dir"], -1)   # USD quote → ters
        self.assertEqual(b["USDJPY"]["dir"], 1)    # USD base → aynı
        self.assertEqual(b["XAUUSD"]["hits"], 1)
        self.assertEqual(b["XAUUSD"]["events"][0]["side"], "bullish")

    def test_released_below_forecast_flips_direction(self):
        now = _ts(2026, 10, 14, 6, 5)
        b = nb.released_biases([self._ev(actual="2.1%")], now)
        self.assertEqual(b["XAUUSD"]["dir"], 1)
        self.assertEqual(b["USDJPY"]["dir"], -1)

    def test_future_and_stale_events_produce_no_bias(self):
        # Henüz açıklanmadı (age < 0)
        self.assertEqual(nb.released_biases([self._ev()], _ts(2026, 10, 14, 5, 50)), {})
        # Pencere dışı (age > 900 sn)
        self.assertEqual(nb.released_biases([self._ev()], _ts(2026, 10, 14, 6, 20)), {})
        # Pencere içi ama actual yok → yön YOK (beklentiyle spekülasyon yapılmaz)
        self.assertEqual(nb.released_biases([self._ev(actual="—")], _ts(2026, 10, 14, 6, 5)), {})

    def test_inverted_family_employment(self):
        # İşsizlik beklenti ÜSTÜ → para birimi ZAYIF → USD quote sembol YUKARI
        ev = self._ev(title="US Unemployment Rate", actual="4.9%", forecast="4.2%")
        b = nb.released_biases([ev], _ts(2026, 10, 14, 6, 5))
        self.assertEqual(b["XAUUSD"]["dir"], 1)
        self.assertEqual(b["USDJPY"]["dir"], -1)

    def test_equal_to_forecast_is_neutral(self):
        self.assertEqual(
            nb.released_biases([self._ev(actual="3.0%")], _ts(2026, 10, 14, 6, 5)), {})

    def test_conflicting_events_cancel_out(self):
        now = _ts(2026, 10, 14, 6, 5)
        events = [
            self._ev(actual="3.4%", affected_symbols=["XAUUSD"]),           # USD↑ → -1
            self._ev(title="US CPI y/y", actual="2.1%", affected_symbols=["XAUUSD"]),  # USD↓ → +1
        ]
        b = nb.released_biases(events, now)
        self.assertEqual(b["XAUUSD"]["hits"], 2)
        self.assertEqual(b["XAUUSD"]["dir"], 0)   # çelişki → kanıt yok

    def test_unit_mismatch_is_rejected(self):
        # Birim kapısı: "3.0%" beklenti vs "145K" açıklanan → yön UYDURULMAZ
        ev = self._ev(actual="145K", forecast="3.0%")
        self.assertEqual(nb.released_biases([ev], _ts(2026, 10, 14, 6, 5)), {})

    def test_cache_refresh_and_bias_for(self):
        now = _ts(2026, 10, 14, 6, 5)
        nb.refresh_biases([self._ev()], now, force=True)
        self.assertEqual(nb.bias_for("XAUUSD")["dir"], -1)
        self.assertEqual(nb.bias_for("GBPUSD"), {"dir": 0, "hits": 0, "events": []})


class NewsBiasWiringTests(unittest.TestCase):
    def test_settings_defaults_are_off(self):
        cfg = forex.ForexAutoPaperSettings()
        self.assertFalse(cfg.news_bias_enabled, "kanıt olmadan açılmamalı")
        self.assertTrue(cfg.news_bias_block_opposing)
        self.assertFalse(cfg.news_bias_bypass_filters, "strateji değişikliği — kanıt ister")
        self.assertEqual(cfg.news_bias_window_sec, 900.0)

    def test_entry_chain_is_wired(self):
        src = pathlib.Path(forex.__file__).read_text(encoding="utf-8")
        # Karşıt yön engeli + destek yönü baypası + audit log
        self.assertIn("_nb_slot = _nb_mod.bias_for(sym)", src)
        self.assertIn("news_bias_block_opposing", src)
        self.assertIn("news_bias_bypass_filters", src)
        # Yumuşak filtre kapıları baypas bayrağına bağlı olmalı
        self.assertIn('if gate_reason and not _news_bypass:', src)
        self.assertIn('if cand["score"] < req_score and not _news_bypass:', src)
        self.assertIn('adx_val < _AUTO_SETTINGS.adx_min and not _news_bypass:', src)
        # Maliyet/risk kapıları baypastan ETKİLENMEMELİ
        self.assertIn('if cand["spread_pips"] > effective_max_spread:', src)
        self.assertNotIn('effective_max_spread and not _news_bypass', src)


if __name__ == "__main__":
    unittest.main()
