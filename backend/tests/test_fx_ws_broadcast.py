"""MT5 → PANEL CANLI YAYINI (2026-11-09).

NEDEN: köprü `/sync-mt5` POST'unu **1,5 sn**'de bir atıyordu ama panel bu veriyi
yalnız REST yoklamasıyla (3 sn) görüyordu → tazelik ortalama ~2,5 sn, en kötü
~4,5 sn bayat. Artık senkron sonunda WS'e de basılıyor.

Kilitlenen davranış:
  1. `_broadcast_fx_state` yükü `/auto-paper/status` ile **BİREBİR aynı** alanlarla
     yayınlar (istemci iki ayrı reducer yazmak zorunda kalmaz).
  2. Yayından ÖNCE status önbelleği geçersiz kılınır — yoksa 1 sn TTL'li eski yük
     gider ve yayın "en son tick'i göstermiyor" olurdu.
  3. NaN/±Infinity `None`'a çevrilir: `json.dumps` bunları geçersiz JSON olarak
     yazar ve istemci `JSON.parse` hatasıyla mesajı **sessizce** düşürür.
  4. `fx_trade_closed` YALNIZ yeni kapanan işlem varsa yayınlanır (ağır liste WS
     ile taşınmaz, yalnız "değişti" sinyali).
  5. Sync ucu yayın hatasında DÜŞMEZ: köprü hata görürse komutları tekrar dener ve
     emirler çift iletilir.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ws_runtime  # noqa: E402
from app.routers import forex as fx  # noqa: E402

SRC = (ROOT / "app" / "routers" / "forex.py").read_text(encoding="utf-8")


class _FakeWS:
    def __init__(self, connections: int = 1):
        self.sent = []
        self.connection_count = connections

    async def broadcast(self, message, **kw):
        self.sent.append(message)


class TestBroadcastFxState(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._orig_ws = ws_runtime.ws_manager
        self._orig_status = fx.get_forex_auto_paper_status
        self.fake = _FakeWS()
        ws_runtime.ws_manager = self.fake
        fx._STATUS_CACHE = None
        # Gerçek durum yükü üretimde ağır (EV hesapları); burada yalnız sözleşme test edilir.
        async def _fake_status():
            return {"status": "ok", "balance": 1234.5, "equity": 1240.0,
                    "bad_nan": float("nan"), "bad_inf": float("inf"),
                    "open_positions": [{"ticket": 11, "pnl_usd": float("-inf"), "symbol": "XAUUSD"}]}
        fx.get_forex_auto_paper_status = _fake_status

    async def asyncTearDown(self):
        ws_runtime.ws_manager = self._orig_ws
        fx.get_forex_auto_paper_status = self._orig_status
        fx._STATUS_CACHE = None

    async def test_payload_is_the_status_response_verbatim(self):
        await fx._broadcast_fx_state()
        self.assertEqual(len(self.fake.sent), 1)
        msg = self.fake.sent[0]
        self.assertEqual(msg["type"], "fx_state")
        self.assertEqual(msg["data"]["balance"], 1234.5)
        self.assertEqual(msg["data"]["open_positions"][0]["ticket"], 11)
        self.assertEqual(msg["data"]["open_positions"][0]["symbol"], "XAUUSD")

    async def test_nan_and_inf_become_none(self):
        await fx._broadcast_fx_state()
        data = self.fake.sent[0]["data"]
        self.assertIsNone(data["bad_nan"], "NaN geçersiz JSON üretir → None olmalı")
        self.assertIsNone(data["bad_inf"])
        self.assertIsNone(data["open_positions"][0]["pnl_usd"])

    async def test_status_cache_invalidated_before_publishing(self):
        fx._STATUS_CACHE = (0.0, {"status": "bayat"})
        await fx._broadcast_fx_state()
        self.assertIsNone(fx._STATUS_CACHE, "yayından önce 1 sn TTL önbelleği temizlenmeli")

    async def test_no_connections_means_no_work(self):
        """Kimse dinlemiyorsa yük üretilmez VE 1 sn önbelleği boşa düşürülmez."""
        self.fake.connection_count = 0
        fx._STATUS_CACHE = (0.0, {"status": "taze"})
        await fx._broadcast_fx_state(closed_count=2)
        self.assertEqual(self.fake.sent, [], "bağlı istemci yokken yayın yapılmamalı")
        self.assertIsNotNone(fx._STATUS_CACHE, "boşa yayın için önbellek yakılmamalı")

    async def test_closed_event_only_when_count(self):
        await fx._broadcast_fx_state(closed_count=0)
        self.assertEqual([m["type"] for m in self.fake.sent], ["fx_state"])
        self.fake.sent.clear()
        await fx._broadcast_fx_state(closed_count=3)
        self.assertEqual([m["type"] for m in self.fake.sent], ["fx_state", "fx_trade_closed"])
        self.assertEqual(self.fake.sent[1]["data"]["count"], 3)


class TestWiring(unittest.TestCase):
    def test_sync_handler_publishes(self):
        i = SRC.index("async def sync_mt5_bridge")
        block = SRC[i:i + 26000]
        self.assertIn("await _broadcast_fx_state(closed_count=_new_closed_count)", block)

    def test_broadcast_failure_does_not_break_sync(self):
        i = SRC.index("await _broadcast_fx_state(closed_count=_new_closed_count)")
        around = SRC[max(0, i - 400):i + 300]
        self.assertIn("try:", around)
        self.assertIn("except Exception", around)

    def test_closed_count_initialised_before_use(self):
        i = SRC.index("_new_closed_count = 0")
        j = SRC.index("newly_closed_deals: List[Dict[str, Any]] = []")
        self.assertLess(i, j, "sayaç ilk kullanımdan önce tanımlı olmalı (deals bloğu opsiyonel)")

    def test_publish_happens_before_return(self):
        i = SRC.index("await _broadcast_fx_state(closed_count=_new_closed_count)")
        j = SRC.index('"server_time": now_ts,')
        self.assertLess(i, j)


if __name__ == "__main__":
    unittest.main()
