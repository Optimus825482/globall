"""FOREXFACTORY HTML KAYNAĞI kilidi (2026-11-09).

NEDEN: aynı gün açıklanan değer (`actual`) için ücretsiz kaynak kalmamıştı;
hepsi canlı denendi (Yahoo'da takvim verisi yok, FF XML'de `<actual>` yok,
Investing/forexprostools/MQL5 403, TradingEconomics guest API 410, MT5 Python
paketinde takvim fonksiyonu YOK). FF HTML yalnız
`curl_cffi impersonate="safari17_0"` ile açılıyor (chrome131/124 → 403) ve
aynı gün değerleri İÇERİYOR — ölçüm: EUR German Trade Balance 15.6B,
EUR Sentix 2.4.

Kilitlenen davranış:
  1. Saat dilimine GÜVENİLMEZ: her günün `data-day-dateline`'ı (yerel gece
     yarısının mutlak epoch'u) + saat-ofseti kullanılır → hesap coğrafi IP'den
     bağımsızdır.
  2. Yalnız 2-3 yıldızlı VERİ olayları; tatil/konuşma ve saati olmayan
     ("All Day"/"Tentative") satırlar ELENİR (saat uydurulmaz).
  3. Boş zaman hücresi üstteki saati devralır (FF aynı saati tekrar yazmaz).
  4. Geri dolum yalnız GÜVENLİ eşleşmede: aynı (para birimi, dakika) için hem
     hedefte hem kaynakta TEK olay, ya da başlık belirteçleriyle TEK net kazanan.
     Belirsizse DOKUNULMAZ — yanlış değer, boş değerden daha pahalıdır.
  5. Aynı (para birimi, dakika) zaten varsa olay EKLENMEZ (yinelenen satır yok).
"""
import datetime
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import forex_news as fn  # noqa: E402

#: 2026-11-09 00:00 Europe/Istanbul == 2026-11-08T21:00:00Z
DAY1 = 1794171600
DAY2 = DAY1 + 86400


def row(*, time_txt="1:30am", currency="EUR", impact="red", title="German Trade Balance",
        actual="", forecast="19.2B", previous="18.0B", dateline=None, eid="111"):
    dl = f' data-day-dateline="{dateline}"' if dateline is not None else ""
    icon = f'<span class="icon icon--ff-impact-{impact}"></span>' if impact else ""
    return (
        f'<tr data-event-id="{eid}"{dl} class="calendar__row">'
        f'<td class="calendar__cell calendar__time">{time_txt}</td>'
        f'<td class="calendar__cell calendar__currency">{currency}</td>'
        f'<td class="calendar__cell calendar__impact">{icon}</td>'
        f'<td class="calendar__cell calendar__event"><span class="calendar__event-title">{title}</span></td>'
        f'<td class="calendar__cell calendar__actual">{actual}</td>'
        f'<td class="calendar__cell calendar__forecast">{forecast}</td>'
        f'<td class="calendar__cell calendar__previous">{previous}</td></tr>'
    )


BREAKER = '<tr class="calendar__row calendar__row--day-breaker"><td colspan="10">Mon Nov 9</td></tr>'
NOW = datetime.datetime(2026, 11, 9, 12, 0, tzinfo=datetime.timezone.utc)


def html_doc(*rows):
    return "<table>" + BREAKER + "".join(rows) + "</table>"


class TestParse(unittest.TestCase):
    def test_timezone_from_dateline(self):
        """10:00am + dateline(İstanbul gece yarısı) → 07:00Z (TradingView ile aynı)."""
        out = fn.parse_forexfactory_html(
            html_doc(row(time_txt="10:00am", actual="15.6B", dateline=DAY1)), now_utc=NOW)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["date_iso"], "2026-11-09T07:00:00.000Z")

    def test_pm_meridiem(self):
        out = fn.parse_forexfactory_html(
            html_doc(row(time_txt="12:30pm", dateline=DAY1)), now_utc=NOW)
        self.assertEqual(out[0]["date_iso"], "2026-11-09T09:30:00.000Z")

    def test_empty_time_inherits_previous(self):
        doc = html_doc(row(time_txt="8:00am", dateline=DAY1, title="A", eid="1"),
                       row(time_txt="", dateline=DAY1, title="B", eid="2"))
        out = fn.parse_forexfactory_html(doc, now_utc=NOW)
        self.assertEqual([o["date_iso"][11:16] for o in out], ["05:00", "05:00"])

    def test_all_day_rows_are_dropped(self):
        doc = html_doc(row(time_txt="All Day", dateline=DAY1, title="Bank Holiday"))
        self.assertEqual(fn.parse_forexfactory_html(doc, now_utc=NOW), [])

    def test_low_impact_and_missing_currency_dropped(self):
        doc = html_doc(row(impact="ora", dateline=DAY1, title="Low", eid="1"),
                       row(impact="red", currency="", dateline=DAY1, title="Cur", eid="2"),
                       row(impact="yel", dateline=DAY1, title="Med", eid="3"))
        out = fn.parse_forexfactory_html(doc, now_utc=NOW)
        self.assertEqual([o["original_title"] for o in out], ["Med"])

    def test_actual_and_status(self):
        out = fn.parse_forexfactory_html(
            html_doc(row(time_txt="10:00am", actual="15.6B", dateline=DAY1)), now_utc=NOW)
        self.assertEqual(out[0]["actual"], "15.6B")
        self.assertEqual(out[0]["status"], "Açıklandı")
        out2 = fn.parse_forexfactory_html(
            html_doc(row(time_txt="10:00am", actual="", dateline=DAY1)), now_utc=NOW)
        self.assertEqual(out2[0]["actual"], "—")
        self.assertEqual(out2[0]["status"], "Geçti", "saat geçti ve değer yok")

    def test_event_id_is_stable(self):
        doc = html_doc(row(dateline=DAY1, eid="155590"))
        a = fn.parse_forexfactory_html(doc, now_utc=NOW)[0]["id"]
        b = fn.parse_forexfactory_html(doc, now_utc=NOW)[0]["id"]
        self.assertEqual(a, b)
        self.assertEqual(a, "cal-ff-155590")

    def test_bad_html_fails_closed(self):
        for bad in ("", "<table></table>", "rastgele"):
            self.assertEqual(fn.parse_forexfactory_html(bad, now_utc=NOW), [])


class TestBackfill(unittest.TestCase):
    def _tv(self, **kw):
        base = {"id": "tv1", "currency": "EUR", "original_title": "Balance of Trade",
                "date_iso": "2026-11-09T07:00:00.000Z", "actual": "—", "forecast": "—",
                "previous": "—", "status": "Bekleniyor"}
        base.update(kw)
        return base

    def _ff(self, **kw):
        base = {"id": "cal-ff-1", "currency": "EUR", "original_title": "German Trade Balance",
                "date_iso": "2026-11-09T07:00:00.000Z", "actual": "15.6B",
                "forecast": "19.2B", "previous": "18.0B"}
        base.update(kw)
        return base

    def test_single_on_both_sides_fills(self):
        tv = [self._tv(original_title="Sentix Investor Confidence")]
        ff = [self._ff(original_title="Sentix Investor Confidence", actual="2.4")]
        self.assertEqual(fn.backfill_values_from_ff(tv, ff), 1)
        self.assertEqual(tv[0]["actual"], "2.4")

    def test_ambiguous_minute_is_skipped(self):
        """07:00 EUR'da 3 hedef var, 1 kaynak → YANLIŞ dolum yapılmamalı."""
        tv = [self._tv(original_title="Balance of Trade"),
              self._tv(id="tv2", original_title="Exports MoM"),
              self._tv(id="tv3", original_title="Imports MoM")]
        ff = [self._ff()]
        fn.backfill_values_from_ff(tv, ff)
        self.assertEqual(tv[0]["actual"], "15.6B", "başlık eşleşen dolduruldu")
        self.assertEqual(tv[1]["actual"], "—", "Exports MoM BOŞ kalmalı (yanlış dolum yok)")
        self.assertEqual(tv[2]["actual"], "—")

    def test_existing_actual_not_overwritten(self):
        tv = [self._tv(actual="99", original_title="Sentix Investor Confidence")]
        ff = [self._ff(original_title="Sentix Investor Confidence")]
        self.assertEqual(fn.backfill_values_from_ff(tv, ff), 0)
        self.assertEqual(tv[0]["actual"], "99")

    def test_append_unmatched_adds_only_new_minutes(self):
        tv = [self._tv(original_title="Sentix Investor Confidence")]
        ff = [self._ff(original_title="German Trade Balance"),
              self._ff(id="cal-ff-2", currency="CNY", date_iso="2026-11-09T01:30:00.000Z",
                       original_title="CPI y/y", actual="0.7%")]
        added = fn.append_unmatched_ff(tv, ff)
        self.assertEqual(added, 1, "aynı (para birimi, dakika) varsa eklenmemeli")
        self.assertEqual(tv[-1]["original_title"], "CPI y/y")


class TestWiring(unittest.TestCase):
    def test_sync_uses_ff_html(self):
        src = (ROOT / "app" / "forex_news.py").read_text(encoding="utf-8")
        self.assertIn("await fetch_forexfactory_html_events()", src)
        self.assertIn("backfill_values_from_ff(items, ff_html_items)", src)
        self.assertIn("append_unmatched_ff(items, ff_html_items)", src)
        self.assertIn('"forexfactory_html": ff_state()', src)

    def test_safari_profile_first(self):
        self.assertEqual(fn.FF_PROFILES[0], "safari17_0",
                         "chrome profilleri 403 alıyor; safari önce denenmeli")


if __name__ == "__main__":
    unittest.main()
