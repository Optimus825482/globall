"""Sembol takibi: ayrıştırma, aralık uyarlama, tek tur yürütme ve durdurma."""
import asyncio

import pytest

from app import symbol_watch as sw


def test_parse_watch_start_and_stop():
    assert sw.parse_watch_request("BTC YI TAKIBE AL", ["BTCUSD"]) == {"action": "start", "symbol": "BTCUSD"}
    assert sw.parse_watch_request("btc'yi takip et", ["BTCUSD"]) == {"action": "start", "symbol": "BTCUSD"}
    assert sw.parse_watch_request("BTC takibini durdur", ["BTCUSD"]) == {"action": "stop", "symbol": "BTCUSD"}
    assert sw.parse_watch_request("tüm takipleri bitir", []) == {"action": "stop", "symbol": None}
    assert sw.parse_watch_request("BTC takibe al ama durdur dersem bırak", ["BTCUSD"])["action"] == "start"   # "takibe al" varsa başlat
    assert sw.parse_watch_request("BTC nasıl görünüyor", ["BTCUSD"]) is None
    assert sw.parse_watch_request("takibe al", []) is None                                                    # sembol yok → kurulmaz
    assert sw.parse_watch_request("btc eth takibe al", ["BTCUSD", "ETHUSD"]) is None                          # tek sembol şart


def test_next_interval_adapts_and_is_clamped():
    hot = {"ok": True, "score": -3.0, "frames": {"4h": {"trending": True}}}
    calm = {"ok": True, "score": 0.5, "frames": {"4h": {"trending": False}}}
    normal = {"ok": True, "score": 1.0, "frames": {"4h": {"trending": True}}}
    squeeze = {"ok": True, "score": 1.0, "frames": {"4h": {"trending": True}}, "indicators": {"15m": {"bollinger": {"sikisma": True}}}}
    assert sw.next_interval_sec(hot, False) == 120 and sw.next_interval_sec(squeeze, False) == 180
    assert sw.next_interval_sec(normal, False) == 300 and sw.next_interval_sec(calm, False) == 600
    assert sw.next_interval_sec(hot, True) == 900 and sw.next_interval_sec({}, False) == 600


class FakeDB:
    def __init__(self, jobs):
        self.jobs, self.log = jobs, []

    async def sched_list(self, limit):
        return self.jobs

    async def sched_create(self, kind, due, params, text):
        self.log.append(("create", kind, params))
        return 7

    async def sched_cancel(self, job_id):
        self.log.append(("cancel", job_id))
        return True

    async def sched_update(self, job_id, status, result):
        self.log.append(("update", job_id, status, result))

    async def sched_reschedule(self, job_id, due, params, result):
        self.log.append(("resched", job_id, params, result))


def install(monkeypatch, jobs):
    db = FakeDB(jobs)
    for name in ("sched_list", "sched_create", "sched_cancel", "sched_update", "sched_reschedule"):
        monkeypatch.setattr(sw.database, name, getattr(db, name))
    return db


def watch_job(sym="BTCUSD", **kw):
    p = {"symbol": sym, "runs": 0, "opens": 0, "started_ts": 10 ** 12}
    p.update(kw)
    return {"id": 3, "kind": "watch", "status": "pending", "params": p}


def test_start_dedupes_limits_and_stop_cancels(monkeypatch):
    db = install(monkeypatch, [watch_job()])
    assert "zaten takipte" in asyncio.run(sw.start_watch("BTCUSD"))
    db.jobs = [watch_job("A"), watch_job("B"), watch_job("C")]
    assert "En çok" in asyncio.run(sw.start_watch("ETHUSD"))
    db.jobs = []
    assert "takibe alındı" in asyncio.run(sw.start_watch("BTCUSD")) and db.log[-1][0] == "create"
    db.jobs = [watch_job()]
    assert "durduruldu" in asyncio.run(sw.stop_watches("BTCUSD")) and ("cancel", 3) in db.log
    assert "aktif takip yok" in asyncio.run(sw.stop_watches("XAUUSD"))


def patch_world(monkeypatch, *, connected=True, opened=None, bias="SELL", score=-3.0):
    from app import forex_research as fr, opportunity_trades as ot
    from app.routers import forex as fx, forex_chat as fc
    monkeypatch.setattr(fx, "_MT5_STATE", {"connected": connected})

    async def blocking(fn, *a):
        if fn is fr.analyze_symbol:
            return {"ok": True, "symbol": a[0], "bias": bias, "score": score, "frames": {"4h": {"trending": True}}}
        if fn is fr.scan_opportunities:
            return {"all": []}
        return None

    async def news(force_refresh=False):
        return []

    async def surprise(cal):
        return None

    async def fake_open(analyses, scan, cal):
        return {"opened": opened or [], "skipped": [{"symbol": "BTCUSD", "reason": "teknik sinyal gücü düşük"}]}

    monkeypatch.setattr(fr, "run_blocking", blocking)
    import app.forex_news as fn_
    monkeypatch.setattr(fn_, "get_forex_news", news)
    monkeypatch.setattr(fc, "compact_calendar", lambda *a, **k: {})
    monkeypatch.setattr(fc, "attach_surprise_z", surprise)
    monkeypatch.setattr(ot, "open_from_scan", fake_open)


def test_run_watch_once_reschedules_without_opening(monkeypatch):
    db = install(monkeypatch, [watch_job()])
    patch_world(monkeypatch)
    asyncio.run(sw.run_watch_once(db.jobs[0]))
    kind, jid, params, result = db.log[-1]
    assert kind == "resched" and params["runs"] == 1 and params["opens"] == 0 and params["interval"] == 120
    assert "işlem yok" in result and "teknik sinyal" in result


def test_run_watch_once_opens_counts_and_finishes_at_limit(monkeypatch):
    opened = [{"symbol": "BTCUSD", "direction": "SELL", "lots": 0.01, "sl_pips": 2000, "tp_pips": 3000}]
    db = install(monkeypatch, [watch_job(opens=1)])
    patch_world(monkeypatch, opened=opened)
    asyncio.run(sw.run_watch_once(db.jobs[0]))
    assert db.log[-1][0] == "resched" and db.log[-1][2]["opens"] == 2 and "AÇILDI" in db.log[-1][3] and db.log[-1][2]["interval"] == 900
    db2 = install(monkeypatch, [watch_job(opens=sw.MAX_OPENS - 1)])
    patch_world(monkeypatch, opened=opened)
    asyncio.run(sw.run_watch_once(db2.jobs[0]))
    assert db2.log[-1][:3] == ("update", 3, "done")                      # sınıra ulaşınca takip biter


def test_run_watch_once_guards(monkeypatch):
    db = install(monkeypatch, [watch_job()])
    patch_world(monkeypatch, connected=False)
    asyncio.run(sw.run_watch_once(db.jobs[0]))
    assert db.log[-1][0] == "resched" and "köprüsü bağlı değil" in db.log[-1][3]          # köprü yok: bekler, bitirmez
    old = watch_job(started_ts=1.0)                                                         # 24 saat dolmuş
    db3 = install(monkeypatch, [old])
    patch_world(monkeypatch)
    asyncio.run(sw.run_watch_once(old))
    assert db3.log[-1][:3] == ("update", 3, "done")
    stopped = install(monkeypatch, [])                                                     # kullanıcı durdurmuş: tur sonucu yazılmaz
    patch_world(monkeypatch)
    asyncio.run(sw.run_watch_once(watch_job()))
    assert not any(e[0] in ("resched", "update") for e in stopped.log)
