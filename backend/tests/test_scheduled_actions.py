"""Sohbetten kurulan zamanlanmış işler: ayrıştırma, seçim, yürütme güvenceleri."""
import asyncio
from datetime import datetime

import pytest

from app import scheduled_actions as sa
from app.routers import forex as fx


def ts(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=sa.TR_TZ).timestamp()


NOW = ts(2026, 10, 30, 19, 20)        # 30 Ekim 2026 Cuma 19:20 TSİ
Q = "bugün cuma piyasalar kapanacak saat 23:50 ye kendine hatırlatıcı kurarak 23:50 btc ve coinler hariç tüm pozisyonları kapatabilirmisin"


def test_user_example_closes_all_except_crypto_tonight():
    j = sa.parse_schedule_request(Q, NOW, ["BTCUSD"])
    assert j["kind"] == "close_positions" and j["due_ts"] == ts(2026, 10, 30, 23, 50)
    assert j["params"]["exclude_groups"] == ["crypto"] and j["params"]["only_symbols"] == [] and j["params"]["exclude_symbols"] == []


def test_day_resolution():
    assert sa.parse_schedule_request("yarın 09:30'da tüm pozisyonları kapat", NOW)["due_ts"] == ts(2026, 10, 31, 9, 30)
    assert sa.parse_schedule_request("14:00'te hatırlat: haber", NOW)["due_ts"] == ts(2026, 10, 31, 14, 0)     # bugün geçti → yarın
    assert sa.parse_schedule_request("pazartesi 10:00'da hatırlat", NOW)["due_ts"] == ts(2026, 11, 2, 10, 0)
    assert sa.parse_schedule_request("cuma 23:50 de tüm pozisyonları kapat", NOW)["due_ts"] == ts(2026, 10, 30, 23, 50)   # bugün cuma, saat gelecekte
    assert sa.parse_schedule_request("cumartesi 10:00 hatırlat", NOW)["due_ts"] == ts(2026, 10, 31, 10, 0)     # 'cuma' öneki cumartesi'yi ezmez


def test_not_a_schedule_request():
    assert sa.parse_schedule_request("XAUUSD 23:50 civarında nasıl görünüyor?", NOW) is None
    assert sa.parse_schedule_request("pozisyonları kapatabilir misin", NOW) is None              # saat yok
    assert sa.parse_schedule_request("dün 14:30'da pozisyonu kapattım", NOW) is None             # geçmiş fiil
    assert sa.parse_schedule_request("23:50'de kapat", NOW) is None                              # neyi? belirsiz → kurulmaz


def test_ambiguous_exclusion_is_not_scheduled():
    assert sa.parse_schedule_request("23:50'de pozisyonları kapat, bazıları hariç", NOW) is None


def test_symbol_scope_and_gold_exclusion():
    j = sa.parse_schedule_request("23:50'de EURUSD pozisyonunu kapat", NOW, ["EURUSD"])
    assert j["params"]["only_symbols"] == ["EURUSD"]
    j2 = sa.parse_schedule_request("23:50'de altın ve btc hariç tüm pozisyonları kapat", NOW, ["XAUUSD", "BTCUSD"])
    assert set(j2["params"]["exclude_groups"]) == {"crypto", "gold"}


def test_reminder_kind():
    j = sa.parse_schedule_request("19:45'te bana ABD verisini hatırlat", NOW)
    assert j["kind"] == "reminder" and "ABD verisini" in j["params"]["message"]


POS = [{"ticket": 1, "symbol": "EURUSD", "direction": "BUY"}, {"ticket": 2, "symbol": "BTCUSD", "direction": "SELL"},
       {"ticket": 3, "symbol": "XAUUSD", "direction": "SELL"}, {"ticket": 4, "symbol": "ETHUSD", "direction": "BUY"}]


def test_select_positions_excludes_crypto_gold_and_symbols():
    assert [p["ticket"] for p in sa.select_positions(POS, {"exclude_groups": ["crypto"]})] == [1, 3]
    assert [p["ticket"] for p in sa.select_positions(POS, {"exclude_groups": ["crypto", "gold"]})] == [1]
    assert [p["ticket"] for p in sa.select_positions(POS, {"exclude_symbols": ["EURUSD"]})] == [2, 3, 4]
    assert [p["ticket"] for p in sa.select_positions(POS, {"only_symbols": ["XAUUSD"]})] == [3]


@pytest.fixture
def state(monkeypatch):
    st = {"connected": True, "account": {"server": "ICMarkets-Demo"}, "open_positions": [dict(p) for p in POS], "pending_commands": []}
    monkeypatch.setattr(fx, "_MT5_STATE", st)
    monkeypatch.setattr(fx, "_log_auto_decision", lambda *a, **k: None)
    monkeypatch.setattr(fx, "_invalidate_status_cache", lambda: None)
    return st


def job(**kw):
    base = {"id": 9, "kind": "close_positions", "due_ts": NOW, "params": {"exclude_groups": ["crypto"]}}
    base.update(kw)
    return base


def test_execute_close_queues_only_selected_and_skips_duplicates(state):
    state["pending_commands"].append({"id": "CMD-X", "action": "CLOSE_ORDER", "ticket": 3})
    status, result = sa._execute_close(job(), NOW)
    assert status == "done" and [c["ticket"] for c in state["pending_commands"] if c["id"].startswith("CMD-SCHED")] == [1]
    assert "EURUSD" in result and "BTCUSD" not in result


def test_execute_close_guards(state):
    state["connected"] = False
    assert sa._execute_close(job(), NOW)[0] is None                       # köprü yok → beklemede kalır
    state["connected"] = True
    state["account"]["server"] = "ICMarkets-Live"
    assert sa._execute_close(job(), NOW)[0] == "failed" and not state["pending_commands"]       # canlı hesapta kapatmaz
    state["account"]["server"] = "Demo"
    state["open_positions"] = []
    assert sa._execute_close(job(), NOW) == ("done", "Kapatılacak pozisyon yoktu")


def test_run_due_jobs_stale_close_is_missed_and_reminder_delivered(monkeypatch, state):
    updates = []

    async def due(now):
        return [job(id=1, due_ts=NOW - 3600), job(id=2, kind="reminder", params={"message": "x"}), job(id=3)]

    async def upd(job_id, status, result):
        updates.append((job_id, status, result))

    monkeypatch.setattr(sa.database, "sched_due", due)
    monkeypatch.setattr(sa.database, "sched_update", upd)
    assert asyncio.run(sa.run_due_jobs(NOW)) == 3
    by = {u[0]: u for u in updates}
    assert by[1][1] == "missed"
    assert by[2][1] == "done" and "Hatırlatıcı" in by[2][2]
    assert by[3][1] == "done"
    assert [c["ticket"] for c in state["pending_commands"]] == [1, 3]      # yalnızca #3 işi çalıştı; bayat iş komut üretmedi


def test_confirmation_text_lists_closing_and_kept():
    j = sa.parse_schedule_request(Q, NOW, ["BTCUSD"])
    t = sa.confirmation_text(j, 5, POS)
    assert "#5" in t and "EURUSD BUY" in t and "Açık kalacaklar: BTCUSD, ETHUSD" in t and "DEMO" in t
