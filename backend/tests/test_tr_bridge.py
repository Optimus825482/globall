"""Unit tests for Binance Global -> Binance TR Lead-Lag Signal Bridge."""
import asyncio
import json
import unittest
from unittest.mock import patch, MagicMock

from app import tr_bridge
from app.tr_bridge import map_to_tr_symbol, send_signal_to_tr, queue_signal_to_tr, test_ping_tr as ping_tr


class LeadLagBridgeTests(unittest.TestCase):
    def setUp(self):
        tr_bridge._COOLDOWN_MAP.clear()
        tr_bridge._BRIDGE_HISTORY.clear()

    def test_map_to_tr_symbol(self):
        base, tr_symbol = map_to_tr_symbol("SOLUSDT")
        self.assertEqual("SOL", base)
        self.assertEqual("SOLTRY", tr_symbol)

        base, tr_symbol = map_to_tr_symbol("BTCUSDT")
        self.assertEqual("BTC", base)
        self.assertEqual("BTCTRY", tr_symbol)

        base, tr_symbol = map_to_tr_symbol("PEPEUSDT")
        self.assertEqual("PEPE", base)
        self.assertEqual("PEPETRY", tr_symbol)

    def test_bridge_disabled_skip(self):
        async def run():
            with patch.object(tr_bridge, "get_bridge_config") as mock_cfg:
                mock_cfg.return_value = {
                    "enabled": False,
                    "url": "http://mock-tr/api/bridge",
                    "secret": "test-secret",
                    "min_score": 0.0,
                    "cooldown_sec": 10.0,
                }
                return await send_signal_to_tr("SOLUSDT", "radar", score=85.0)

        res = asyncio.run(run())
        self.assertFalse(res["ok"])
        self.assertTrue(res["skipped"])
        self.assertEqual("bridge_disabled", res["reason"])

    def test_bridge_successful_dispatch(self):
        async def run():
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.data = b'{"ok": true, "received": true}'

            with patch.object(tr_bridge, "get_bridge_config") as mock_cfg, \
                 patch.object(tr_bridge._POOL, "request", return_value=mock_resp) as mock_req:
                mock_cfg.return_value = {
                    "enabled": True,
                    "url": "https://scalper.erkanerdem.online/api/bridge/global-signal",
                    "secret": "my-bridge-secret",
                    "min_score": 50.0,
                    "cooldown_sec": 10.0,
                }

                res = await send_signal_to_tr(
                    "SOLUSDT",
                    "radar",
                    score=82.5,
                    price=145.2,
                    action="BUY_SIGNAL",
                    title="Radar Sinyali",
                    message="SOL yukselis trendinde",
                    data={"target_pct": 2.5},
                    force=True,
                )

                self.assertTrue(res["ok"])
                self.assertEqual("SOLUSDT", res["global_symbol"])
                self.assertEqual("SOLTRY", res["tr_symbol"])
                self.assertEqual(200, res["status_code"])

                # Verify request parameters
                mock_req.assert_called_once()
                args, kwargs = mock_req.call_args
                self.assertEqual("POST", args[0])
                self.assertEqual("https://scalper.erkanerdem.online/api/bridge/global-signal", args[1])
                headers = kwargs["headers"]
                self.assertEqual("my-bridge-secret", headers["X-Bridge-Secret"])
                self.assertEqual("application/json", headers["Content-Type"])

                # Verify payload content
                payload = json.loads(kwargs["body"].decode("utf-8"))
                self.assertEqual("binance_global", payload["source"])
                self.assertEqual("SOLUSDT", payload["global_symbol"])
                self.assertEqual("SOLTRY", payload["tr_symbol"])
                self.assertEqual("SOL", payload["base_asset"])
                self.assertEqual(82.5, payload["score"])
                self.assertEqual(145.2, payload["price"])

        asyncio.run(run())

    def test_bridge_cooldown_deduplication(self):
        async def run():
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.data = b'{"ok": true}'

            with patch.object(tr_bridge, "get_bridge_config") as mock_cfg, \
                 patch.object(tr_bridge._POOL, "request", return_value=mock_resp):
                mock_cfg.return_value = {
                    "enabled": True,
                    "url": "http://mock-tr/api/bridge",
                    "secret": "sec",
                    "min_score": 0.0,
                    "cooldown_sec": 30.0,
                }

                # First dispatch succeeds
                res1 = await send_signal_to_tr("AVAXUSDT", "fast_jump", score=90.0)
                self.assertTrue(res1["ok"])

                # Second dispatch within cooldown is skipped
                res2 = await send_signal_to_tr("AVAXUSDT", "fast_jump", score=92.0)
                self.assertFalse(res2["ok"])
                self.assertTrue(res2["skipped"])
                self.assertEqual("cooldown_active", res2["reason"])

                # Force bypasses cooldown
                res3 = await send_signal_to_tr("AVAXUSDT", "fast_jump", score=92.0, force=True)
                self.assertTrue(res3["ok"])

        asyncio.run(run())

    def test_bridge_network_error_resilience(self):
        async def run():
            with patch.object(tr_bridge, "get_bridge_config") as mock_cfg, \
                 patch.object(tr_bridge._POOL, "request", side_effect=Exception("Connection refused")):
                mock_cfg.return_value = {
                    "enabled": True,
                    "url": "http://127.0.0.1:9999/api/bridge",
                    "secret": "sec",
                    "min_score": 0.0,
                    "cooldown_sec": 10.0,
                }

                # Must never raise an exception
                res = await send_signal_to_tr("BTCUSDT", "velocity_auto", price=65000.0, force=True)
                self.assertFalse(res["ok"])
                self.assertIn("Connection refused", res["error"])
                self.assertIsNone(res["status_code"])

        asyncio.run(run())

    def test_queue_signal_to_tr_nonblocking(self):
        async def run():
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.data = b'{"ok": true}'

            with patch.object(tr_bridge, "get_bridge_config") as mock_cfg, \
                 patch.object(tr_bridge._POOL, "request", return_value=mock_resp):
                mock_cfg.return_value = {
                    "enabled": True,
                    "url": "http://mock-tr/api/bridge",
                    "secret": "sec",
                    "min_score": 0.0,
                    "cooldown_sec": 10.0,
                }

                # Fire and forget
                task = queue_signal_to_tr("NEARUSDT", "radar", score=75.0, force=True)
                self.assertIsNotNone(task)
                self.assertIsInstance(task, asyncio.Task)
                await task
                self.assertTrue(task.done())

        asyncio.run(run())

    def test_test_ping_tr(self):
        async def run():
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.data = b'{"status": "pong", "message": "Lead-lag signal receiver active"}'

            with patch.object(tr_bridge, "get_bridge_config") as mock_cfg, \
                 patch.object(tr_bridge._POOL, "request", return_value=mock_resp):
                mock_cfg.return_value = {
                    "enabled": True,
                    "url": "https://scalper.erkanerdem.online/api/bridge/global-signal",
                    "secret": "sec",
                    "min_score": 0.0,
                    "cooldown_sec": 10.0,
                }

                res = await ping_tr(symbol="ETHUSDT")
                self.assertTrue(res["ok"])
                self.assertEqual(200, res["status_code"])
                self.assertIn("pong", res["response"])
                self.assertGreaterEqual(res["latency_ms"], 0)

        asyncio.run(run())

    def test_router_endpoints(self):
        from app.routers import bridge as br
        from unittest.mock import AsyncMock

        async def run():
            # 1. get_bridge_status
            with patch.object(tr_bridge, "get_bridge_config") as mock_cfg:
                mock_cfg.return_value = {
                    "enabled": True,
                    "url": "http://mock-tr/api/bridge",
                    "secret": "my-secret-key",
                    "min_score": 10.0,
                    "cooldown_sec": 5.0,
                }
                status_res = await br.get_bridge_status()
                self.assertTrue(status_res["enabled"])
                self.assertEqual("http://mock-tr/api/bridge", status_res["url"])
                self.assertTrue(status_res["secret_configured"])
                self.assertIn("***", status_res["masked_secret"])

            # 2. post_test_ping
            with patch.object(tr_bridge, "test_ping_tr", new_callable=AsyncMock) as mock_ping:
                mock_ping.return_value = {"ok": True, "status_code": 200, "latency_ms": 12.3}
                ping_res = await br.post_test_ping(br.BridgeTestPingRequest(symbol="SOLUSDT"))
                self.assertTrue(ping_res["ok"])

            # 3. update_bridge_configuration
            with patch.object(tr_bridge, "update_bridge_config", new_callable=AsyncMock) as mock_upd:
                mock_upd.return_value = {
                    "enabled": False,
                    "url": "http://new-url",
                    "secret": "new-sec",
                    "min_score": 20.0,
                    "cooldown_sec": 15.0,
                }
                fake_req = MagicMock()
                cfg_res = await br.update_bridge_configuration(
                    br.BridgeConfigRequest(enabled=False, url="http://new-url"),
                    fake_req,
                )
                self.assertTrue(cfg_res["ok"])
                self.assertFalse(cfg_res["config"]["enabled"])

            # 4. manual_dispatch
            with patch.object(tr_bridge, "send_signal_to_tr", new_callable=AsyncMock) as mock_disp:
                mock_disp.return_value = {"ok": True, "status_code": 200, "event_id": "test-123"}
                disp_res = await br.manual_dispatch(
                    br.BridgeDispatchRequest(symbol="BTCUSDT", signal_type="manual_test"),
                    fake_req,
                )
                self.assertTrue(disp_res["ok"])
                self.assertEqual("test-123", disp_res["event_id"])

        asyncio.run(run())

