"""Tests for Binance Global public adapter (urllib3 connection pool, host fallback, rate limit handling)."""

import asyncio
import time
import unittest
from unittest import mock
import urllib3

from app import binance_public as pub


class FakeUrllib3Response:
    def __init__(self, status=200, data=b"[]", headers=None):
        self.status = status
        self.data = data
        self.headers = urllib3.response.HTTPHeaderDict(headers or {})


class BinancePublicAdapterTests(unittest.TestCase):
    def setUp(self):
        pub._ticker_24h_cache.update({"key": None, "rows": None, "expires": 0.0})
        pub._exchange_info_cache.update({"payload": None, "expires": 0.0})

    def test_connection_pool_configuration(self):
        """PoolManager should have maxsize=32 and a 5s/15s Timeout."""
        self.assertIsInstance(pub._HTTP_POOL, urllib3.PoolManager)
        self.assertEqual(32, pub._HTTP_POOL.connection_pool_kw.get("maxsize"))
        timeout = pub._HTTP_POOL.connection_pool_kw.get("timeout")
        self.assertEqual(5.0, timeout.connect_timeout)
        self.assertEqual(15.0, timeout.read_timeout)

    def test_rest_bases_fallback_pool(self):
        """Global REST_BASES should contain standard Binance Global hosts."""
        self.assertIn("https://api.binance.com", pub.REST_BASES)
        self.assertIn("https://api1.binance.com", pub.REST_BASES)
        self.assertIn("https://api2.binance.com", pub.REST_BASES)
        self.assertIn("https://api3.binance.com", pub.REST_BASES)
        self.assertGreaterEqual(len(pub.REST_BASES), 4)

    def test_successful_request_and_weight_tracking(self):
        fake_resp = FakeUrllib3Response(
            status=200,
            data=b'[["1600000000000","100.0","105.0","99.0","102.0","10.0"]]',
            headers={"X-MBX-USED-WEIGHT-1M": "42"},
        )
        with mock.patch.object(pub._HTTP_POOL, "request", return_value=fake_resp) as mock_req:
            res = pub._get_json("/api/v3/klines", {"symbol": "BTCUSDT"})
            self.assertEqual(1, len(res))
            self.assertEqual("100.0", res[0][1])
            self.assertEqual(42, pub._rate_limit_used["total"])
            self.assertEqual(42, pub._rate_limit_used["by_endpoint"]["/api/v3/klines"])
            self.assertTrue(mock_req.called)
            call_url = mock_req.call_args[0][1]
            self.assertTrue(call_url.startswith("https://api.binance.com/api/v3/klines"))

    def test_host_fallback_on_server_error(self):
        """If first host gives 502/500, next attempt falls back to api1.binance.com."""
        resp_500 = FakeUrllib3Response(status=502, data=b"Bad Gateway")
        resp_200 = FakeUrllib3Response(status=200, data=b'{"code": 0, "data": [1, 2, 3]}')

        calls = []

        def fake_request(method, url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                return resp_500
            return resp_200

        with mock.patch.object(pub._HTTP_POOL, "request", side_effect=fake_request), \
             mock.patch.object(time, "sleep"):
            data = pub._get_json("/api/v3/ping", {})
            self.assertEqual([1, 2, 3], data)
            self.assertEqual(2, len(calls))
            self.assertTrue(calls[0].startswith("https://api.binance.com"))
            self.assertTrue(calls[1].startswith("https://api1.binance.com"))

    def test_rate_limit_429_uses_retry_after(self):
        """HTTP 429 should respect Retry-After header."""
        resp_429 = FakeUrllib3Response(status=429, data=b"Too many requests", headers={"Retry-After": "2"})
        resp_200 = FakeUrllib3Response(status=200, data=b'{"ok": true}')

        calls = []

        def fake_request(method, url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                return resp_429
            return resp_200

        sleep_calls = []

        with mock.patch.object(pub._HTTP_POOL, "request", side_effect=fake_request), \
             mock.patch.object(time, "sleep", side_effect=lambda s: sleep_calls.append(s)):
            data = pub._get_json("/api/v3/ping", {})
            self.assertEqual({"ok": True}, data)
            self.assertEqual(2, len(calls))
            self.assertEqual(1, len(sleep_calls))
            self.assertEqual(2.0, sleep_calls[0])

    def test_dynamic_pacing_under_threshold(self):
        """Under 950 weight, no throttling delay should be introduced."""
        saved = (pub._rate_limit_used["total"], pub._weight_reported_at)
        try:
            pub._rate_limit_used["total"] = 500
            pub._weight_reported_at = time.time()
            with mock.patch.object(time, "sleep") as mock_sleep:
                pub._throttle_for_weight()
            self.assertFalse(mock_sleep.called)
        finally:
            pub._rate_limit_used["total"], pub._weight_reported_at = saved

    def test_dynamic_pacing_between_950_and_1100(self):
        """Between 950 and 1100, dynamic micro-delay (200-450ms) should be introduced."""
        saved = (pub._rate_limit_used["total"], pub._weight_reported_at)
        try:
            pub._rate_limit_used["total"] = 1000
            pub._weight_reported_at = time.time()
            sleeps = []
            with mock.patch.object(time, "sleep", side_effect=lambda s: sleeps.append(s)):
                pub._throttle_for_weight()
            self.assertEqual(1, len(sleeps))
            self.assertGreaterEqual(sleeps[0], 0.20)
            self.assertLessEqual(sleeps[0], 0.45)
        finally:
            pub._rate_limit_used["total"], pub._weight_reported_at = saved

    def test_dynamic_pacing_emergency_capped_at_15s(self):
        """At 1100+ emergency weight, wait time should be capped at 15s max (not 60s freeze)."""
        saved = (pub._rate_limit_used["total"], pub._weight_reported_at)
        try:
            pub._rate_limit_used["total"] = 1150
            # Reported 5 seconds ago -> remaining window is 55s, but emergency cap is 15s
            pub._weight_reported_at = time.time() - 5.0
            sleeps = []
            with mock.patch.object(time, "sleep", side_effect=lambda s: sleeps.append(s)):
                pub._throttle_for_weight()
            self.assertEqual(1, len(sleeps))
            self.assertLessEqual(sleeps[0], 15.0)
            self.assertGreater(sleeps[0], 0.0)
        finally:
            pub._rate_limit_used["total"], pub._weight_reported_at = saved

    def test_rate_limit_snapshot_schema(self):
        snap = pub.rate_limit_snapshot()
        self.assertIn("total_weight_used", snap)
        self.assertIn("by_endpoint", snap)
        self.assertIn("soft_limit", snap)
        self.assertIn("exchange_info_cache", snap)
        self.assertIn("ticker_24h_cache", snap)
        self.assertEqual(8, snap["max_concurrency"])


class BinancePublicAsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        pub._ticker_24h_cache.update({"key": None, "rows": None, "expires": 0.0})

    async def test_klines_async(self):
        fake_resp = FakeUrllib3Response(
            status=200,
            data=b'[["1600000000000","50000","51000","49000","50500","100"]]',
        )
        with mock.patch.object(pub._HTTP_POOL, "request", return_value=fake_resp):
            rows = await pub.klines("BTCUSDT", "1m", 1)
            self.assertEqual(1, len(rows))
            self.assertEqual("50000", rows[0][1])

    async def test_ticker_24h_caching(self):
        fake_resp = FakeUrllib3Response(
            status=200,
            data=b'[{"symbol": "BTCUSDT", "lastPrice": "50000", "priceChangePercent": "2.5"}]',
        )
        with mock.patch.object(pub._HTTP_POOL, "request", return_value=fake_resp) as mock_req:
            r1 = await pub.ticker_24h(["BTCUSDT"])
            r2 = await pub.ticker_24h(["BTCUSDT"])
            self.assertEqual(1, mock_req.call_count)
            self.assertEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
