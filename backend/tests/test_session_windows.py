"""FX SEANS PENCERELERİ kilitleri (2026-11-09) — app/session_windows.py.

Kilitlenen davranış (hepsi SABİT UTC zamanlarla, saat dilimi sürprizi yok):
  1. Seanslar doğru sınıflanır (Asya / Londra / NY / örtüşme).
  2. Londra+NY örtüşmesi (12:00-16:00 UTC) en yüksek likidite (1.0).
  3. Ölü bölge (21:00+ UTC) düşük likidite ve `dead_zone=True`.
  4. Hafta sonu: Cuma 21:00 → Pazar 21:00 UTC arası piyasa KAPALI.
  5. Seans açılış/kapanış ±15 dk `spread_risk` işaretlenir.
  6. Naif datetime UTC kabul edilir; farklı tz UTC'ye çevrilir.
  7. Gece yarısını aşan pencere mantığı doğru (`_in_window`).
"""
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import session_windows as sw  # noqa: E402

UTC = timezone.utc


def dt(y=2026, m=11, day=9, h=0, mi=0):  # 2026-11-09 Pazartesi
    return datetime(y, m, day, h, mi, tzinfo=UTC)


class TestSessions(unittest.TestCase):
    def test_asia_only(self):
        self.assertEqual(sw.active_sessions(dt(h=2)), ["asia"])
        self.assertFalse(sw.in_overlap(dt(h=2)))

    def test_london_asia_handover(self):
        # 07:00-09:00 UTC: Londra açık, Asya hâlâ açık
        self.assertEqual(sw.active_sessions(dt(h=8)), ["asia", "london"])

    def test_london_only(self):
        self.assertEqual(sw.active_sessions(dt(h=10)), ["london"])

    def test_overlap_window(self):
        for hour in (12, 13, 15):
            self.assertTrue(sw.in_overlap(dt(h=hour)), f"{hour}:00 örtüşmede olmalı")
            self.assertEqual(sw.active_sessions(dt(h=hour)), ["london", "new_york"])
        self.assertFalse(sw.in_overlap(dt(h=16)), "16:00 sonrası örtüşme bitti")

    def test_ny_only(self):
        self.assertEqual(sw.active_sessions(dt(h=18)), ["new_york"])

    def test_after_ny_close_is_dead(self):
        self.assertEqual(sw.active_sessions(dt(h=22)), [])
        self.assertTrue(sw.is_dead_zone(dt(h=22)))


class TestLiquidity(unittest.TestCase):
    def test_overlap_is_highest(self):
        self.assertEqual(sw.liquidity_score(dt(h=13)), 1.0)
        self.assertGreater(sw.liquidity_score(dt(h=13)), sw.liquidity_score(dt(h=10)))
        self.assertGreater(sw.liquidity_score(dt(h=10)), sw.liquidity_score(dt(h=2)))
        self.assertGreater(sw.liquidity_score(dt(h=2)), sw.liquidity_score(dt(h=22)))

    def test_closed_is_zero(self):
        self.assertEqual(sw.liquidity_score(dt(day=7, h=12)), 0.0)  # Cumartesi


class TestWeekend(unittest.TestCase):
    def test_friday_after_21_closed(self):
        self.assertTrue(sw.is_weekend_closed(dt(day=13, h=21)))   # Cuma
        self.assertFalse(sw.is_weekend_closed(dt(day=13, h=20)))  # Cuma 20:00 açık

    def test_saturday_closed(self):
        self.assertTrue(sw.is_weekend_closed(dt(day=14, h=12)))

    def test_sunday_before_21_closed_after_open(self):
        self.assertTrue(sw.is_weekend_closed(dt(day=15, h=20)))   # Pazar 20:00
        self.assertFalse(sw.is_weekend_closed(dt(day=15, h=21)))  # Pazar 21:00 açıldı
        # Açılış anı: seans YOK (Asya 00:00'da başlar) ve DEAD penceresinde
        # (21:00+) → likidite düşük. 0.0 değil, "ölü bölge" skoru beklenir:
        # piyasa yeni açıldı, spread geniş. Asya skorundan KÜÇÜK olmalı.
        self.assertEqual(sw.liquidity_score(dt(day=15, h=21)),
                         sw.LIQUIDITY_SCORES["dead"])
        self.assertLess(sw.liquidity_score(dt(day=15, h=21)),
                        sw.liquidity_score(dt(day=16, h=2)))

    def test_weekend_has_no_sessions(self):
        self.assertEqual(sw.active_sessions(dt(day=14, h=13)), [])
        self.assertFalse(sw.in_overlap(dt(day=14, h=13)))


class TestSpreadRisk(unittest.TestCase):
    def test_london_open_flagged(self):
        self.assertEqual(sw.spread_risk_window(dt(h=7, mi=10)), "open")

    def test_london_close_flagged(self):
        self.assertEqual(sw.spread_risk_window(dt(h=15, mi=50)), "close")

    def test_mid_session_clean(self):
        self.assertIsNone(sw.spread_risk_window(dt(h=10, mi=30)))

    def test_weekend_no_flag(self):
        self.assertIsNone(sw.spread_risk_window(dt(day=14, h=7, mi=10)))


class TestTimeZoneHandling(unittest.TestCase):
    def test_naive_datetime_treated_as_utc(self):
        naive = datetime(2026, 11, 9, 13, 0)
        self.assertTrue(sw.in_overlap(naive))

    def test_other_tz_converted(self):
        # 15:00 UTC+3 = 12:00 UTC → örtüşme başlangıcı
        tz3 = timezone(timedelta(hours=3))
        d = datetime(2026, 11, 9, 15, 0, tzinfo=tz3)
        self.assertTrue(sw.in_overlap(d))
        self.assertEqual(sw.describe(d)["utc"], "2026-11-09 12:00")

    def test_none_uses_now(self):
        self.assertIsInstance(sw.describe()["liquidity_score"], float)


class TestDescribe(unittest.TestCase):
    def test_overlap_label(self):
        d = sw.describe(dt(h=13))
        self.assertTrue(d["overlap"])
        self.assertFalse(d["market_closed"])
        self.assertIn("örtüşme", d["label"])

    def test_dead_zone_label(self):
        d = sw.describe(dt(h=22))
        self.assertTrue(d["dead_zone"])
        self.assertIn("Ölü bölge", d["label"])

    def test_closed_label(self):
        d = sw.describe(dt(day=14, h=12))
        self.assertTrue(d["market_closed"])
        self.assertIn("KAPALI", d["label"])

    def test_keys_present(self):
        d = sw.describe(dt(h=10))
        for key in ("utc", "sessions", "overlap", "dead_zone", "market_closed",
                    "liquidity_score", "spread_risk", "next_session_open_min", "label"):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()
