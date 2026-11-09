"""FMP TAKVİM KAYNAĞI kilidi (2026-11-09) — `forex_news.parse_fmp_events`.

NEDEN: aynı gün açıklanan değer (`actual`) için ÜCRETSİZ+ANAHTARSIZ kaynak
kalmadı; hepsi canlı denendi (bkz. forex_news'teki ölçüm notu): Yahoo'da takvim
verisi yok, ForexFactory XML'inde `<actual>` yok + HTML 403, Investing tüm
host/parmak izlerinde 403, TradingEconomics guest API 410. Anahtarlı kaynak bu
yüzden eklendi.

Kilitlenen davranış:
  1. Şema doğrulaması FAIL-CLOSED: beklenmeyen gövde `[]` döner (sahte veri yok).
  2. Yalnız High/Medium etkili olaylar; `estimate`→forecast, `actual`→actual.
  3. `date_iso` KANONİK biçime çevrilir (…T00:00:00.000Z).
  4. Kimlik KARARLI: aynı olay her koşuda aynı id'yi alır (`hash()` yasak —
     süreç başına rastgeleleşir ve yinelenen satır üretir).
  5. Anahtar yoksa ağa HİÇ gidilmez (sessiz atlama, hata değil).
"""
import asyncio
import os
import json
import pathlib
import time
import sys
import unittest
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import forex_news as fn  # noqa: E402

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def item(**kw):
    base = {"date": "2026-11-09 13:30:00", "country": "US", "currency": "USD",
            "event": "Non Farm Payrolls", "impact": "High",
            "actual": 165, "estimate": 160, "previous": 150}
    base.update(kw)
    return base


class TestParse(unittest.TestCase):
    def test_basic_mapping(self):
        out = fn.parse_fmp_events([item()], now_utc=NOW)
        self.assertEqual(len(out), 1)
        ev = out[0]
        self.assertEqual(ev["original_title"], "Non Farm Payrolls")
        self.assertEqual(ev["stars"], 3)
        self.assertEqual(ev["actual"], "165")
        self.assertEqual(ev["forecast"], "160", "FMP `estimate` → bizim `forecast`")
        self.assertEqual(ev["date_iso"], "2026-11-09T13:30:00.000Z")
        self.assertEqual(ev["status"], "Açıklandı")
        self.assertEqual(ev["currency"], "USD")

    def test_low_impact_skipped(self):
        out = fn.parse_fmp_events([item(impact="Low"), item(impact="Medium")], now_utc=NOW)
        self.assertEqual([e["stars"] for e in out], [2])

    def test_empty_actual_marks_pending_or_passed(self):
        out = fn.parse_fmp_events([item(actual=None, date="2026-11-09 15:00:00")], now_utc=NOW)
        self.assertEqual(out[0]["actual"], "—")
        self.assertEqual(out[0]["status"], "Bekleniyor")
        out2 = fn.parse_fmp_events([item(actual="", date="2026-11-09 08:00:00")], now_utc=NOW)
        self.assertEqual(out2[0]["status"], "Geçti", "saati geçmiş ve değer yok → Geçti")

    def test_unexpected_schema_fails_closed(self):
        for bad in ([], None, {"result": []}, [{"foo": 1}], "text"):
            self.assertEqual(fn.parse_fmp_events(bad, now_utc=NOW), [])

    def test_stable_identity_across_calls(self):
        a = fn.parse_fmp_events([item()], now_utc=NOW)[0]["id"]
        b = fn.parse_fmp_events([item()], now_utc=NOW)[0]["id"]
        self.assertEqual(a, b, "aynı olay aynı kimliği almalı (upsert çalışsın)")
        self.assertTrue(a.startswith("cal-fmp-"))
        # Eski hash-kimlik desenine DÜŞMEMELİ (temizlik onu silerdi)
        from app.database import LEGACY_CALENDAR_ID_RE
        self.assertFalse(bool(LEGACY_CALENDAR_ID_RE.match(a)))

    def test_bad_row_does_not_drop_others(self):
        out = fn.parse_fmp_events([item(date="bozuk-tarih"), item()], now_utc=NOW)
        self.assertEqual(len(out), 1)


class TestNoKey(unittest.TestCase):
    def test_no_key_means_no_network(self):
        orig = os.environ.pop(fn.FMP_KEY_ENV, None)
        try:
            # Anahtar yokken ağ çağrısı YAPILMAMALI (anında boş döner).
            got = asyncio.run(fn.fetch_fmp_events())
            self.assertEqual(got, [])
            self.assertFalse(fn.fmp_state()["configured"])
        finally:
            if orig is not None:
                os.environ[fn.FMP_KEY_ENV] = orig

    def test_state_surface_for_health_ui(self):
        st = fn.fmp_state()
        for key in ("configured", "key_env", "last_error", "last_count"):
            self.assertIn(key, st)
        # Sağlık yükünde görünür olmalı (sessiz kaynak yok)
        self.assertIn("fmp", fn.investing_block_state())


class TestBudgetGuard(unittest.TestCase):
    """ÜCRETSİZ PLAN = 25 SORGU/GÜN (kullanıcı). Release-chase 45 sn'de bir tam
    senkron tetiklediği için bu frenler olmadan kota dakikalar içinde yanardı."""

    def setUp(self):
        self._orig = os.environ.get(fn.FMP_KEY_ENV)
        os.environ[fn.FMP_KEY_ENV] = "test-key"
        fn._FMP_STATE.update({"day": time.strftime("%Y-%m-%d", time.gmtime()),
                              "day_count": 0, "last_call_at": 0.0, "last_error": None})

    def tearDown(self):
        if self._orig is None:
            os.environ.pop(fn.FMP_KEY_ENV, None)
        else:
            os.environ[fn.FMP_KEY_ENV] = self._orig
        fn._FMP_STATE.update({"day_count": 0, "last_call_at": 0.0, "last_error": None})

    def test_min_interval_blocks_second_call(self):
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req.full_url)
            raise RuntimeError("ağ yok")

        import urllib.request as ur
        orig = ur.urlopen
        ur.urlopen = fake_urlopen
        try:
            asyncio.run(fn.fetch_fmp_events())
            n_first = len(calls)
            asyncio.run(fn.fetch_fmp_events())          # 4 saat dolmadı
            self.assertEqual(len(calls), n_first, "min aralık içinde ağa GİDİLMEMELİ")
        finally:
            ur.urlopen = orig

    def test_daily_cap_blocks_call(self):
        fn._FMP_STATE.update({"day_count": fn.FMP_DAILY_CAP, "last_call_at": 0.0})
        got = asyncio.run(fn.fetch_fmp_events())
        self.assertEqual(got, [])
        self.assertIn("kota doldu", str(fn._FMP_STATE.get("last_error")))

    def test_counter_resets_on_new_day(self):
        fn._FMP_STATE.update({"day": "1999-01-01", "day_count": fn.FMP_DAILY_CAP})
        import urllib.request as ur
        orig = ur.urlopen
        ur.urlopen = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ağ yok"))
        try:
            asyncio.run(fn.fetch_fmp_events())
        finally:
            ur.urlopen = orig
        self.assertEqual(fn._FMP_STATE["day"], time.strftime("%Y-%m-%d", time.gmtime()))
        self.assertEqual(fn._FMP_STATE["day_count"], 1, "yeni günde sayaç sıfırlanıp 1 olmalı")


class TestEndpointFallback(unittest.TestCase):
    """FMP plan değişiminde `/api/v3` yolunu kapatıyor → `/stable` denenmeli."""

    def setUp(self):
        self._orig = os.environ.get(fn.FMP_KEY_ENV)
        os.environ[fn.FMP_KEY_ENV] = "test-key"
        fn._FMP_STATE.update({"day": time.strftime("%Y-%m-%d", time.gmtime()),
                              "day_count": 0, "last_call_at": 0.0, "last_error": None,
                              "endpoint": None})

    def tearDown(self):
        if self._orig is None:
            os.environ.pop(fn.FMP_KEY_ENV, None)
        else:
            os.environ[fn.FMP_KEY_ENV] = self._orig

    def test_v3_error_then_stable_ok(self):
        seen = []

        class Resp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body.encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            url = req.full_url
            seen.append(url)
            # GÜNCEL SIRA: stable önce; legacy v3 yedek (25/gün kotası ikiye bölünmesin)
            if "/stable/" in url:
                return Resp('{"Error Message": "Invalid API KEY"}')
            return Resp(json.dumps([item()]))

        import urllib.request as ur
        orig = ur.urlopen
        ur.urlopen = fake_urlopen
        try:
            got = asyncio.run(fn.fetch_fmp_events())
        finally:
            ur.urlopen = orig
        self.assertEqual(len(got), 1, "yedek uçtan olay gelmeli")
        self.assertTrue(seen and "/stable/" in seen[0], "ÖNCE stable denenmeli (kota)")
        self.assertIn("/api/v3/", str(fn._FMP_STATE.get("endpoint")), "v3 yedeğe düşülmeli")

    def test_error_body_is_surfaced(self):
        self.assertIn("Legacy Endpoint", fn._fmp_error_message(
            {"Error Message": "Legacy Endpoint. Please switch to stable API"}))
        self.assertIsNone(fn._fmp_error_message([item()]))
        self.assertIn("beklenmeyen gövde", fn._fmp_error_message({"foo": 1}))


class TestForexFactoryBudget(unittest.TestCase):
    """FF HTML de 45 sn'lik chase'te dövülmemeli (5 dk önbellek)."""

    def test_cache_prevents_extra_requests(self):
        fn._FF_STATE.update({"blocked_until": 0.0, "cached_items": [{"id": "x"}],
                             "cached_at": time.time()})
        calls = []
        orig = fn.fetch_forexfactory_html_events_sync
        fn.fetch_forexfactory_html_events_sync = lambda: (calls.append(1), ([], None))[1]
        try:
            got = asyncio.run(fn.fetch_forexfactory_html_events())
        finally:
            fn.fetch_forexfactory_html_events_sync = orig
            fn._FF_STATE.update({"cached_items": [], "cached_at": 0.0})
        self.assertEqual(got, [{"id": "x"}], "önbellekten dönmeli")
        self.assertEqual(calls, [], "ağa gidilmemeli")

    def test_fmp_only_when_ff_empty(self):
        src = (ROOT / "app" / "forex_news.py").read_text(encoding="utf-8")
        self.assertIn("[] if ff_html_items else await fetch_fmp_events()", src,
                      "FF çalışırken FMP çağrılmamalı (25/gün kota)")


if __name__ == "__main__":
    unittest.main()
