"""INVESTING.COM TAKVİM ÇEKİMİ kilitleri (2026-11-09) — app/forex_news.py.

KÖK NEDEN (canlı ölçüldü): `impersonate="chrome120"` profili Investing.com
tarafından 403 ile engelleniyordu (chrome120 → 403, chrome124 → 403,
**chrome131 → 200 + payload**). İstek sıklığı zaten doğruydu
(`_CACHE_TTL_SEC=300`, `CALENDAR_REFRESH_INTERVAL_SEC=3h`) — suçlu sıklık
değil ÖLÜ PARMAK İZİ profiliydi. Ayrıca kod `User-Agent`'ı elle `Chrome/124`
diye ezip profil parmak iziyle ÇELİŞTİRİYORDU.

Kilitlenen davranış:
  1. Profil listesi EN YENİDEN ESKİYE sıralı ve `chrome131` başta.
  2. İlk profil 403 alırsa SIRADAKİ denenir; çalışan profil kullanılır.
  3. HİÇBİR profil geçemezse `[]` döner + kaynak 15 dk DİNLENİR (ban derinleşmesin).
  4. Dinlenme sırasında **hiç ağ isteği yapılmaz**.
  5. Dinlenme süresi dolunca kaynak tekrar denenir.
  6. 429 (rate limit) görülürse hemen dinlenmeye geçilir (profil denemesi sürmez).
"""
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import forex_news as fx  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


PAYLOAD_HTML = "<script>window.economicCalendarStore = {\"rows\": []};</script>"


class TestProfileChain(unittest.TestCase):
    def setUp(self):
        fx._investing_blocked_until = 0.0
        fx._investing_blocked_reason = ""
        self.calls: list[str] = []

    def tearDown(self):
        fx._investing_blocked_until = 0.0
        fx._investing_blocked_reason = ""

    def _fake_get(self, behaviour: dict[str, _FakeResponse]):
        def _get(url, headers=None, impersonate=None, timeout=None):
            self.calls.append(impersonate or "?")
            return behaviour.get(impersonate, _FakeResponse(403, "blocked"))
        return _get

    def test_profile_order_newest_first(self):
        self.assertEqual(fx._INVESTING_PROFILES[0], "chrome131",
                         "2026-11-09: yalnız chrome131 geçiyor — başta olmalı")
        self.assertIn("chrome120", fx._INVESTING_PROFILES,
                      "eski profil yedek olarak kalsın (ileride düzelirse)")

    def test_first_profile_wins_no_extra_calls(self):
        import asyncio
        from curl_cffi import requests as cr
        with patch.object(cr, "get", self._fake_get({"chrome131": _FakeResponse(200, PAYLOAD_HTML)})):
            out = asyncio.run(fx.fetch_investing_com_events())
        self.assertEqual(self.calls, ["chrome131"], "ilk profil çalışınca diğerleri denenmemeli")
        self.assertEqual(out, [])
        self.assertFalse(fx.investing_block_state()["blocked"])

    def test_fallback_when_first_blocked(self):
        import asyncio
        from curl_cffi import requests as cr
        behaviour = {"chrome131": _FakeResponse(403), "chrome124": _FakeResponse(200, PAYLOAD_HTML)}
        with patch.object(cr, "get", self._fake_get(behaviour)):
            asyncio.run(fx.fetch_investing_com_events())
        self.assertEqual(self.calls, ["chrome131", "chrome124"],
                         "403 sonrası sıradaki profil denenmeli")

    def test_all_blocked_sets_cooldown(self):
        import asyncio
        from curl_cffi import requests as cr
        with patch.object(cr, "get", self._fake_get({})):
            out = asyncio.run(fx.fetch_investing_com_events())
        self.assertEqual(out, [])
        self.assertEqual(len(self.calls), len(fx._INVESTING_PROFILES),
                         "tüm profiller bir kez denenmeli")
        state = fx.investing_block_state()
        self.assertTrue(state["blocked"])
        self.assertGreater(state["remaining_sec"], 0)

    def test_no_network_while_blocked(self):
        import asyncio
        from curl_cffi import requests as cr
        fx._mark_investing_blocked("test")
        with patch.object(cr, "get", self._fake_get({})):
            out = asyncio.run(fx.fetch_investing_com_events())
        self.assertEqual(out, [])
        self.assertEqual(self.calls, [], "dinlenme sırasında ağ isteği OLMAMALI")

    def test_cooldown_expiry_allows_retry(self):
        import asyncio
        from curl_cffi import requests as cr
        fx._investing_blocked_until = time.time() - 1  # süresi geçmiş
        with patch.object(cr, "get", self._fake_get({"chrome131": _FakeResponse(200, PAYLOAD_HTML)})):
            asyncio.run(fx.fetch_investing_com_events())
        self.assertEqual(self.calls, ["chrome131"], "süre dolunca yeniden denenmeli")

    def test_429_stops_immediately(self):
        import asyncio
        from curl_cffi import requests as cr
        with patch.object(cr, "get", self._fake_get({"chrome131": _FakeResponse(429)})):
            out = asyncio.run(fx.fetch_investing_com_events())
        self.assertEqual(out, [])
        self.assertEqual(self.calls, ["chrome131"], "429'da diğer profiller zorlanmamalı")
        self.assertTrue(fx.investing_block_state()["blocked"],
                        "rate limit → hemen dinlenme")

    def test_block_state_shape(self):
        state = fx.investing_block_state()
        for key in ("blocked", "remaining_sec", "reason", "profiles"):
            self.assertIn(key, state)


if __name__ == "__main__":
    unittest.main()
