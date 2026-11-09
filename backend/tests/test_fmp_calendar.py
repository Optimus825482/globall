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
import pathlib
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


if __name__ == "__main__":
    unittest.main()
