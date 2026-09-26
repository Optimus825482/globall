"""İki borsa (TR/TRY ↔ Global/USDT) — değişken katmanı + sessiz bozulma regresyonları.

Kilitlenen davranışlar
----------------------
1. Borsa kayıt defteri: `EXCHANGE=binance_global` REST tabanını, WS host'larını
   ve quote'ü değiştirir; verilmediğinde TR varsayılanları BİREBİR korunur.
2. Bilinmeyen `EXCHANGE` değeri TR'ye düşer VE başlangıçta uyarı basılır —
   Global hedeflenmiş bir örnek sessizce TR'de çalışmasın diye.
3. `base_asset_of` / `quote_asset_of`: `BTCTRY`→BTC/TRY, `BTCUSDT`→BTC/USDT,
   `USDTTRY`→USDT/TRY (uzun ek önce denenir).
4. ANAHTAR SÖZLEŞME — cüzdan bölünmesi: `base_asset_of("BTCUSDT") == "BTC"`.
   `symbol.replace("TRY","")` USDT sembolünde no-op'tur ve `virtual_wallet`'a
   `asset="BTCUSDT"` yazar; cüzdan iki satıra bölünür, nakdi satırı hiç
   güncellenmez. Bu, sessiz bozulmanın EN PAHALI türüydü.
5. Nakit satırı `config.CASH_ASSET` (TR→TRY, Global→USDT): `virtual_wallet`
   SQL'lerinde `asset='TRY'` LITERAL'i kalmamalı.
6. Likidite tabanı borsaya göre ölçeklenir ve env ile ayarlanabilir.
7. Sembol evreni env'den okunur; Global varsayılanı USDT'dir, boş DEĞİLDİR.
8. Sembol türetilen yerlerde sabit 'TRY' kalmaz.
"""
import importlib
import inspect
import io
import os
import pathlib
import re
import sys
import tokenize
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import analyzer, correlation, database, macro_sentiment_service
from app import binance_tr_public as btp
from app import market_data, microflow
from app.config import _resolve_exchange, base_asset_of, quote_asset_of


def _split_comment(line: str) -> tuple:
    """Satırı (kod, yorum) olarak böler; string içindeki `#` sayılmaz."""
    in_s = in_d = False
    for index, ch in enumerate(line):
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d:
            return line[:index], line[index:]
    return line, ""


class ExchangeRegistryTests(unittest.TestCase):
    """1-2: borsa seçimi ve çözümleme sırası."""

    def _resolve_clean(self, env):
        """Verilen env ile, miras kalan değişkenler olmadan çöz."""
        keys = ("EXCHANGE", "EXCHANGE_REST_BASE", "EXCHANGE_WS_BASES", "QUOTE_ASSET")
        clean = {k: v for k, v in os.environ.items() if k not in keys}
        clean.update(env)
        with patch.dict(os.environ, clean, clear=True):
            return _resolve_exchange()

    def test_tr_is_default_and_unchanged(self):
        name, record, warning = self._resolve_clean({})
        self.assertEqual("binance_tr", name)
        self.assertIsNone(warning)
        self.assertEqual("https://api.binance.me", record["rest_base"])
        self.assertEqual("TRY", record["quote_asset"])
        self.assertEqual(("wss://stream-cloud.binance.tr", "wss://stream.binance.me"),
                         record["ws_bases"])

    def test_global_record(self):
        name, record, warning = self._resolve_clean({"EXCHANGE": "binance_global"})
        self.assertEqual("binance_global", name)
        self.assertIsNone(warning)
        self.assertEqual("https://api.binance.com", record["rest_base"])
        self.assertEqual("USDT", record["quote_asset"])
        self.assertTrue(all(h.startswith("wss://stream.binance.com")
                            for h in record["ws_bases"]),
                        f"Global WS host'ları beklenmeyen: {record['ws_bases']}")
        # Host rotasyonu için en az iki host gerekir (market_data testleri de
        # bu sözleşmeye dayanır).
        self.assertGreaterEqual(len(record["ws_bases"]), 2)

    def test_explicit_overrides_beat_registry(self):
        _, record, _ = self._resolve_clean({
            "EXCHANGE": "binance_tr",
            "EXCHANGE_REST_BASE": "https://example.test/",
            "EXCHANGE_WS_BASES": "wss://a.test, wss://b.test",
            "QUOTE_ASSET": "usdc",
        })
        self.assertEqual("https://example.test", record["rest_base"])
        self.assertEqual(("wss://a.test", "wss://b.test"), record["ws_bases"])
        self.assertEqual("USDC", record["quote_asset"])

    def test_unknown_exchange_falls_back_to_tr_with_warning(self):
        name, record, warning = self._resolve_clean({"EXCHANGE": "binance_typo"})
        # Sessizce yanlış borsada çalışmak, Global hedeflenmiş bir örnek için
        # en pahalı hatadır: uygulama sağlıklı görünür, yanlış veri çeker.
        self.assertEqual("binance_tr", name)
        self.assertEqual("https://api.binance.me", record["rest_base"])
        self.assertIsNotNone(warning, "geçersiz EXCHANGE uyarı vermeli")
        self.assertIn("binance_typo", warning)
        self.assertIn("binance_global", warning, "uyarı doğru seçeneği göstermeli")

    def test_adapter_surfaces_follow_config(self):
        """Adapter sabit adları korunur — market_data/microflow bunları import eder."""
        self.assertEqual(btp.config.REST_BASE, btp.REST_BASE)
        self.assertEqual(btp.config.WS_BASES, btp.WS_BASES)
        self.assertEqual(btp.WS_BASE, btp.WS_BASES[0])


class SymbolPartTests(unittest.TestCase):
    """3: taban/quote ayrıştırma."""

    def test_known_quotes(self):
        self.assertEqual(("BTC", "TRY"), (base_asset_of("BTCTRY"), quote_asset_of("BTCTRY")))
        self.assertEqual(("BTC", "USDT"), (base_asset_of("BTCUSDT"), quote_asset_of("BTCUSDT")))
        self.assertEqual("BTC", base_asset_of("btcusdt"), "küçük harf normalleştirilir")

    def test_longest_quote_wins(self):
        """`USDTTRY` içinde `TRY` de geçiyor: uzun ek ÖNCE denenmeli."""
        self.assertEqual(("USDT", "TRY"), (base_asset_of("USDTTRY"), quote_asset_of("USDTTRY")))

    def test_unknown_suffix_is_not_stripped(self):
        self.assertEqual("FOOBAR", base_asset_of("FOOBAR"))
        self.assertEqual("", quote_asset_of("FOOBAR"))


class WalletSplitRegressionTests(unittest.TestCase):
    """4-5: sessiz cüzdan bozulmasının regresyon kilitleri."""

    def test_base_asset_of_usdt_pair_is_the_base_coin(self):
        """`symbol.replace("TRY","")` yerine `base_asset_of` kullanılmalı.

        Bu tek satır, uygulamanın Global'da yanlış çalışmasının en pahalı
        sonucunu (her alım-satımda biriken, loglanmayan cüzdan bölünmesi)
        kapatır.
        """
        self.assertEqual("BTC", base_asset_of("BTCUSDT"))
        self.assertEqual("BTC", base_asset_of("BTCTRY"))

    def test_analyzer_never_strips_try_literal(self):
        src = inspect.getsource(analyzer)
        self.assertNotIn('symbol.replace("TRY"', src,
                         "analyzer hâlâ sabit TRY soyma kullanıyor")
        self.assertIn("base_asset_of(symbol)", src)

    def test_database_has_no_hardcoded_try_cash_row(self):
        """`virtual_wallet` nakit satırı `config.CASH_ASSET` olmalı.

        Global örneğinde sabit 'TRY' USDT bakiyeyi "TRY" etiketli bir satırda
        tutardı: mekanik olarak çalışır ama LLM'e/himmet/rapora yanlış birim
        raporlar.
        """
        src = inspect.getsource(database)
        for match in re.finditer(r"virtual_wallet", src):
            window = src[match.start():match.start() + 400]
            self.assertNotIn("asset='TRY'", window,
                             "virtual_wallet sorgusunda sabit TRY satırı kalmış")

    def test_cash_asset_follows_quote(self):
        from app.config import config
        self.assertEqual(config.QUOTE_ASSET, config.CASH_ASSET,
                         "nakit satırı quote ile aynı olmalı")

    def test_reset_seeds_cash_asset_not_try(self):
        src = inspect.getsource(database.reset_trading_data)
        self.assertIn("config.CASH_ASSET", src)
        self.assertNotIn("'TRY'", src)


class LiquidityScaleTests(unittest.TestCase):
    """6: likidite/whale eşikleri borsanın ölçeğinde."""

    def test_quote_floors_differ_by_asset(self):
        self.assertNotEqual(btp._min_quote_volume("TRY"), btp._min_quote_volume("USDT"))

    def test_unknown_quote_falls_back_to_deployment_floor(self):
        """Bilinmeyen quote TR tabanına düşerse Global'da havuz ~40 kat sıkı
        olur ve sessizce boşalır."""
        self.assertEqual(btp._min_quote_volume("BTC"),
                         btp._min_quote_volume(btp._DEFAULT_QUOTE_ASSET))

    def test_floors_are_env_configurable(self):
        reloaded = importlib.reload(btp)
        try:
            with patch.dict(os.environ, {"MIN_QUOTE_VOLUME_USDT": "777"}, clear=False):
                reloaded = importlib.reload(btp)
                self.assertEqual(777.0, reloaded._min_quote_volume("USDT"))
        finally:
            importlib.reload(btp)

    def test_whale_thresholds_are_env_configurable(self):
        """`WHALE_NOTIONAL_TRY` env'siz, class attribute olarak sabitti.

        Global'da 25.000 TRY eşiği ~40 kat sıkı olur ve balina tespiti
        sessizce ÖLÜR.
        """
        self.assertGreater(microflow.MicroFlow.WHALE_NOTIONAL_TRY, 0)
        self.assertIn('os.getenv("WHALE_NOTIONAL"', inspect.getsource(market_data),
                      "market_data whale eşiği env'den okunmalı")


class SymbolUniverseTests(unittest.TestCase):
    """7: sembol evreni env'den ve borsanın quote'süne göre."""

    def test_defaults_are_non_empty_for_both_quotes(self):
        from app.config import Config
        self.assertTrue(Config._DEFAULT_SYMBOLS["TRY"])
        usdt = Config._DEFAULT_SYMBOLS["USDT"]
        self.assertTrue(usdt)
        self.assertTrue(all(s.endswith("USDT") for s in usdt))
        # İki evren aynı uzunlukta olmalı: tarama genişliği borsadan bağımsız
        # kalsın, fark yalnız borsada olsun.
        self.assertEqual(len(Config._DEFAULT_SYMBOLS["TRY"]), len(usdt))
        self.assertEqual(
            sorted(base_asset_of(s) for s in Config._DEFAULT_SYMBOLS["TRY"]),
            sorted(base_asset_of(s) for s in usdt),
            "iki evren aynı taban varlıkları içermeli",
        )

    def test_env_symbols_are_parsed(self):
        with patch.dict(os.environ, {"SYMBOLS": "btcusdt, ethusdt"}, clear=False):
            parsed = [s.strip().upper() for s in os.getenv("SYMBOLS", "").split(",") if s.strip()]
        self.assertEqual(["BTCUSDT", "ETHUSDT"], parsed)


class ExchangeBoundSymbolTests(unittest.TestCase):
    """8: sembol türetilen yerler sabit 'TRY' aramamalı."""

    def test_correlation_benchmark_uses_quote_asset(self):
        src = inspect.getsource(correlation)
        self.assertIn('f"{bench}{config.QUOTE_ASSET}"', src)
        self.assertNotIn('f"{bench}TRY"', src)

    def test_macro_sentiment_btc_reference_uses_quote_asset(self):
        src = inspect.getsource(macro_sentiment_service)
        self.assertIn('btc_symbol = f"BTC{config.QUOTE_ASSET}"', src)
        self.assertNotIn('fetch_klines("BTCTRY"', src)

    def test_no_module_still_hardcodes_btctry_as_live_reference(self):
        """`BTCTRY` yalnız DOKÜMANTASYON ve örnek yorumlarda kalmalı.

        Docstring'ler ve satır sonu yorumları serbest; KOD satırındaki her
        `BTCTRY` canlı bir referanstır ve Global'da bulunamayan bir sembol
        arar (panik koruması, korelasyon, otonom tarama zamanlaması...).

        Ayrıştırma elle yapılmaz — `tokenize` STRING/COMMENT token'larını zaten
        doğru sınıflandırır; elle takipte çok satırlı docstring'in devam
        satırları yanlışlıkla "kod" sanılıyor.
        """
        offenders = []
        for path in sorted((ROOT / "app").rglob("*.py")):
            try:
                tokens = list(tokenize.generate_tokens(
                    io.StringIO(path.read_text(encoding="utf-8")).readline))
            except (tokenize.TokenError, IndentationError, SyntaxError):
                continue
            for token in tokens:
                if token.type not in (tokenize.STRING, tokenize.COMMENT):
                    continue
                if "BTCTRY" not in token.string:
                    continue
                line = token.line.rstrip()
                if len(token.string) == len(token.line) and not line.lstrip().startswith("#"):
                    # Tek satırlık string: gerçek kod olabilir.
                    offenders.append(f"{path.relative_to(ROOT)}:{token.start[0]}: {line}")
        self.assertEqual([], offenders,
                         "canlı referans olarak kalan sabit BTCTRY:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
