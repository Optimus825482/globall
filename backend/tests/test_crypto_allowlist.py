"""KRİPTO SEMBOL ALLOWLIST kilitleri (2026-11-09) — BTC/ETH/XRP dışı tamamen çıkar.

Talep: "BTCUSD, ETHUSD ve XRPUSD hariçindeki tüm kripto çiftlerini her yerden
kaldır". Bu projede kripto quote'u QUOTE_ASSET (TRY/USDT) olduğu için gerçek
adlar `BTCTRY` / `BTCUSDT` biçimindedir; filtre **taban varlığa** bakar, yani
BTCUSDT / BTC_USDT / BTCTRY / BTCUSD hepsi geçer.

Kilitlenen davranış:
  1. İzinli tabanlar (BTC/ETH/XRP) her quote biçiminde geçer.
  2. Diğer kripto çiftleri (SOLUSDT, DOGETRY, ORCAUSDT …) ELENİR.
  3. **FX/EMTİA DOKUNULMAZ** (XAUUSD, EURUSD, USDJPY, USOIL, NAS100) — filtre
     yalnız KRİPTO sembollere uygulanır. 2026-11-09: `XXXUSD` biçimi de kapsandı
     (broker kriptoyu SOLUSD/ADAUSD diye adlandırıyor ve `USD` quote listesinde
     olmadığı için bu isimler eski filtreye TAKILMIYORDU → ürün kuralı delikti).
  4. `apply_symbol_universe` evreni filtreler; hepsi elenirse **izinli
     varsayılanlara düşer** (evren asla boş kalmaz, `_reject_empty` patlamaz).
  5. `_DEFAULT_SYMBOLS` ve `spot_monitor.CORE_SYMBOLS` yalnız izinli çiftleri taşır.
  6. Radar havuzunun tek kapısı (`_add`) filtreyi uygular (kaynak düzeyinde kilit).
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config  # noqa: E402


class TestHelpers(unittest.TestCase):
    def test_allowed_bases(self):
        self.assertEqual(set(config.CRYPTO_ALLOWED_BASES), {"BTC", "ETH", "XRP"})

    def test_crypto_base_detection(self):
        self.assertEqual(config.crypto_base_of("BTCUSDT"), "BTC")
        self.assertEqual(config.crypto_base_of("btc_usdt"), "BTC")
        self.assertEqual(config.crypto_base_of("XRPTRY"), "XRP")
        self.assertEqual(config.crypto_base_of("BTCETH"), "BTC")   # kripto-kripto
        self.assertIsNone(config.crypto_base_of("XAUUSD"))          # FX
        self.assertIsNone(config.crypto_base_of("EURUSD"))
        self.assertIsNone(config.crypto_base_of("USDJPY"))
        self.assertIsNone(config.crypto_base_of(""))

    def test_allowed_cryptos_pass_every_quote(self):
        for sym in ("BTCTRY", "BTCUSDT", "BTC_USDT", "ETHUSDT", "ETHTRY",
                    "XRPUSDT", "XRPTRY", "BTCUSD", "ETHUSD", "XRPUSD"):
            self.assertTrue(config.is_crypto_symbol_allowed(sym), sym)

    def test_other_cryptos_dropped(self):
        for sym in ("SOLUSDT", "DOGETRY", "PEPETRY", "ADAUSDT", "ORCAUSDT",
                    "RADUSDT", "AVAXTRY", "SHIBTRY", "BNBUSDT", "LINKUSDT"):
            self.assertFalse(config.is_crypto_symbol_allowed(sym), sym)

    def test_fx_and_commodities_untouched(self):
        for sym in ("XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY",
                    "USDCAD", "USOIL", "NAS100", "US30", "DXY"):
            self.assertTrue(config.is_crypto_symbol_allowed(sym),
                            f"{sym} FX/emtia — filtreden ETKİLENMEMELİ")

    def test_filter_returns_kept_and_dropped(self):
        kept, dropped = config.filter_crypto_symbols(
            ["BTCUSDT", "SOLUSDT", "XAUUSD", "EURUSD", "ORCAUSDT", "XRPTRY"])
        self.assertEqual(kept, ["BTCUSDT", "XAUUSD", "EURUSD", "XRPTRY"])
        self.assertEqual(dropped, ["SOLUSDT", "ORCAUSDT"])

    def test_allowed_symbols_follow_quote(self):
        self.assertEqual(config.allowed_crypto_symbols("TRY"),
                         ["BTCTRY", "ETHTRY", "XRPTRY"])
        self.assertEqual(config.allowed_crypto_symbols("USDT"),
                         ["BTCUSDT", "ETHUSDT", "XRPUSDT"])


class TestDefaultUniverse(unittest.TestCase):
    def test_default_symbols_only_allowed(self):
        for quote, symbols in config._DEFAULT_SYMBOLS.items():
            for sym in symbols:
                self.assertTrue(config.is_crypto_symbol_allowed(sym),
                                f"{quote}/{sym} izinli olmalı")
        self.assertEqual(config._DEFAULT_SYMBOLS["TRY"],
                         ["BTCTRY", "ETHTRY", "XRPTRY"])
        self.assertEqual(config._DEFAULT_SYMBOLS["USDT"],
                         ["BTCUSDT", "ETHUSDT", "XRPUSDT"])

    def test_spot_monitor_core_symbols_only_allowed(self):
        from app import spot_monitor
        self.assertTrue(spot_monitor.CORE_SYMBOLS)
        for sym in spot_monitor.CORE_SYMBOLS:
            self.assertTrue(config.is_crypto_symbol_allowed(sym), sym)


class TestUniverseFunnel(unittest.TestCase):
    def setUp(self):
        self._orig_symbols = list(config.SYMBOLS)

    def tearDown(self):
        config.SYMBOLS = self._orig_symbols
        from app import state
        state.market.symbols = [s.lower() for s in self._orig_symbols]

    def test_universe_is_filtered(self):
        from app import state
        out = state.apply_symbol_universe(
            ["BTCUSDT", "SOLUSDT", "XAUUSD", "ORCAUSDT", "ETHUSDT"], source="test")
        self.assertEqual(sorted(out), ["BTCUSDT", "ETHUSDT", "XAUUSD"])
        self.assertEqual(sorted(config.SYMBOLS), ["BTCUSDT", "ETHUSDT", "XAUUSD"])

    def test_empty_after_filter_falls_back_and_does_not_raise(self):
        """Top-gainer rotasyonu izinli çift içermezse evren BOŞ kalmamalı."""
        from app import state
        out = state.apply_symbol_universe(
            ["SOLUSDT", "ORCAUSDT", "RADUSDT"], source="top_gainers")
        self.assertTrue(out, "evren boş kalmamalı (fallback beklenir)")
        self.assertEqual(sorted(out), sorted(config.allowed_crypto_symbols()))
        for sym in out:
            self.assertTrue(config.is_crypto_symbol_allowed(sym))

    def test_extend_stream_universe_not_filtered(self):
        """Açık pozisyonların akış verisi kesilmemeli → burada filtre YOK."""
        from app import state
        before = set(state.market.symbols)
        state.extend_stream_universe(["SOLUSDT"], source="open_position")
        self.assertIn("solusdt", state.market.symbols,
                      "açık pozisyon sembolü akış evreninde kalmalı")
        state.market.symbols = [s for s in state.market.symbols
                                if s not in ("solusdt",)]
        self.assertEqual(set(state.market.symbols), before)


class TestConfigSaveReportsDropped(unittest.IsolatedAsyncioTestCase):
    """Config kaydında elenen semboller RAPORLANMALI (sessiz kayıp olmasın)."""

    async def test_disallowed_crypto_is_reported(self):
        from unittest.mock import AsyncMock, patch
        from app import main

        orig = {"symbols": list(main.config.SYMBOLS),
                "order_pct": dict(main.config.SYMBOL_ORDER_PCT),
                "market_symbols": list(main.market.symbols)}
        try:
            # NOT: FX/emtia (XAUUSD) bu yoldan test EDİLEMEZ — o semboller
            # Binance TR'de listeli olmadığı için ZATEN borsa filtresine takılır
            # (allowlist'ten bağımsız, önceden var olan davranış). FX muafiyeti
            # TestHelpers.test_fx_and_commodities_untouched içinde kilitli.
            with (
                patch("app.main.trading_symbols",
                      new=AsyncMock(return_value=["BTCTRY", "SOLTRY"])),
                patch.object(main.market, "fetch_historical_data", new=AsyncMock()),
                patch("app.main.database.get_llm_setting", new=AsyncMock(return_value="{}")),
                patch("app.main.database.set_llm_setting", new=AsyncMock()),
                patch("app.main.get_config",
                      new=AsyncMock(return_value={"symbols": ["BTCTRY"]})),
            ):
                result = await main._apply_config_update({"symbols": ["BTCTRY", "SOLTRY"]})
            self.assertIn("SOLTRY", result.get("removed_invalid_symbols") or [],
                          "elenen kripto çifti kullanıcıya BİLDİRİLMELİ (sessiz kayıp yok)")
            self.assertEqual(main.config.SYMBOLS, ["BTCTRY"])
        finally:
            main.config.SYMBOLS = orig["symbols"]
            main.config.SYMBOL_ORDER_PCT = orig["order_pct"]
            main.market.symbols = orig["market_symbols"]


class TestWiring(unittest.TestCase):
    def test_radar_pool_gate_is_filtered(self):
        src = pathlib.Path(ROOT, "app", "routers", "velocity.py").read_text(encoding="utf-8")
        self.assertIn("if not config.is_crypto_symbol_allowed(sym):", src,
                      "radar havuzunun tek kapısı (_add) filtre uygulamalı")

    def test_universe_funnel_is_filtered(self):
        src = pathlib.Path(ROOT, "app", "state.py").read_text(encoding="utf-8")
        self.assertIn("config.filter_crypto_symbols(symbols)", src)

    def test_chat_gainers_filtered(self):
        src = pathlib.Path(ROOT, "app", "routers", "llm_chat.py").read_text(encoding="utf-8")
        self.assertIn("config.filter_crypto_symbols(", src)


if __name__ == "__main__":
    unittest.main()

class TestUsdFormIsCovered(unittest.TestCase):
    """`XXXUSD` biçimi (2026-11-09 deliği) — `USD` quote listesinde OLMADIĞI için
    eski filtre `SOLUSD`/`ADAUSD` gibi isimleri FX sanıyordu ve ürün kuralı
    ("yalnız BTC/ETH/XRP") bu biçimde DELİKTİ. Hafta sonu tarama evreninde 7
    emekli coin görünmesiyle ortaya çıktı.
    """

    def test_retired_usd_cryptos_are_detected(self):
        for sym in ("SOLUSD", "ADAUSD", "XTZUSD", "DATAUSD", "UNIUSD", "AVXUSD", "LNKUSD"):
            self.assertFalse(config.is_crypto_symbol_allowed(sym), f"{sym} elenmeli")
            self.assertIsNotNone(config.crypto_base_of(sym), f"{sym} kripto sayılmalı")

    def test_allowed_usd_cryptos_kept(self):
        for sym in ("BTCUSD", "ETHUSD", "XRPUSD"):
            self.assertTrue(config.is_crypto_symbol_allowed(sym), f"{sym} kalmalı")

    def test_fx_and_commodity_never_treated_as_crypto(self):
        # REGRESYON KAPISI: `USD` quote listesine eklenirse bu liste patlar —
        # tüm forex evreni "kripto" sayılırdı.
        for sym in ("EURUSD", "GBPUSD", "USDJPY", "AUDCAD", "NZDUSD", "XAUUSD",
                    "US30", "NAS100", "USTEC", "GBPJPY", "AUDJPY"):
            self.assertIsNone(config.crypto_base_of(sym), f"{sym} kripto SAYILMAMALI")

    def test_scan_universe_obeys_engine_rules(self):
        """Fırsat taraması evreni motorun kurallarına uymalı: kara liste + allowlist."""
        from app import opportunity_trades as ot
        from app.routers import forex as fx
        import datetime

        blocked = {b.strip().upper() for b in (fx._AUTO_SETTINGS.blocked_symbols or [])}
        for now_ts in (0, datetime.datetime(2026, 11, 14, 12, 0).timestamp()):  # hafta içi + hafta sonu
            universe = ot.universe_now(now_ts)
            self.assertTrue(universe, "evren boş kalmamalı")
            for sym in universe:
                self.assertTrue(config.is_crypto_symbol_allowed(sym),
                                f"{sym} tarama evreninde ama kripto allowlist'i dışında")
                self.assertNotIn(sym, blocked, f"{sym} tarama evreninde ama kara listede")


if __name__ == "__main__":
    unittest.main()
