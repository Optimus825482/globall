"""LLM Trader incelemesi: karar ayrıştırma, politika, gölge sonuç, rapor özeti, önbellek + araştırma kaynakları."""
import asyncio
import json
import time

import pytest

from app import forex_research, llm_trade_review as ltr
from app.routers import forex_chat, llm_review


# ----------------------------------------------------------------------------- karar ayrıştırma

def test_parse_verdict_accepts_fenced_and_clamps():
    text = 'Tabii:\n```json\n{"decision":"reject","confidence":140,"summary":"Haber yakın","reasons":["a","b","c","d","e"],' \
           '"risks":["r"],"checks":{"haber":"olumsuz"}}\n```'
    v = ltr.parse_verdict(text)
    assert v["decision"] == "REJECT" and v["confidence"] == 100 and len(v["reasons"]) == 4
    assert v["checks"] == {"haber": "olumsuz"}


@pytest.mark.parametrize("bad", ["", "merhaba", '{"decision":"MAYBE"}', "[]"])
def test_parse_verdict_rejects_garbage(bad):
    assert ltr.parse_verdict(bad) is None


# ----------------------------------------------------------------------------- politika

def _v(dec="APPROVE", conf=70):
    return {"decision": dec, "confidence": conf, "summary": "özet"}


def test_decide_veto_mode():
    kw = dict(mode="veto", fail_open=True, min_confidence=55)
    assert ltr.decide(_v("APPROVE", 70), None, **kw)["blocked"] is False
    assert ltr.decide(_v("REJECT", 90), None, **kw)["blocked"] is True
    low = ltr.decide(_v("APPROVE", 40), None, **kw)           # eşik altı onay da engellenir
    assert low["blocked"] and "eşik" in low["reason"]


def test_decide_advisory_never_blocks():
    r = ltr.decide(_v("REJECT", 95), None, mode="advisory", fail_open=False, min_confidence=55)
    assert r["blocked"] is False and r["applied"] == "advisory_reject"


def test_decide_llm_failure_follows_fail_open():
    assert ltr.decide(None, "timeout", mode="veto", fail_open=True, min_confidence=55) == {
        "blocked": False, "applied": "fail_open", "reason": "timeout"}
    assert ltr.decide(None, "timeout", mode="veto", fail_open=False, min_confidence=55)["blocked"] is True


# ----------------------------------------------------------------------------- gölge sonuç

def _row(direction="BUY", **kw):
    base = {"direction": direction, "entry_price": 100.0, "pip_size": 0.1, "sl_pips": 10, "tp_pips": 20,
            "created_at": time.time(), "mfe_pips": 0, "mae_pips": 0}
    base.update(kw)
    return base


def test_shadow_tp_sl_and_direction():
    now = time.time()
    assert ltr.shadow_update(_row("BUY"), 102.0, now)["shadow_status"] == "TP"      # +20 pip
    assert ltr.shadow_update(_row("BUY"), 99.0, now)["shadow_status"] == "SL"       # -10 pip
    assert ltr.shadow_update(_row("SELL"), 98.0, now)["shadow_status"] == "TP"      # SELL: düşüş kâr
    mid = ltr.shadow_update(_row("BUY"), 100.5, now)                                # +5: henüz açık
    assert "shadow_status" not in mid and mid["shadow_pips"] == 5.0 and mid["mfe_pips"] == 5.0


def test_shadow_timeout_and_no_tp_mode():
    now = time.time()
    old = _row("BUY", created_at=now - ltr.SHADOW_WINDOW_SEC - 1)
    assert ltr.shadow_update(old, 100.3, now)["shadow_status"] == "ZAMAN_ASIMI"
    no_tp = _row("BUY", tp_pips=0)                                                  # trail modları: sabit TP yok
    assert "shadow_status" not in ltr.shadow_update(no_tp, 105.0, now)
    assert ltr.shadow_update(_row(pip_size=0), 101.0, now) == {}


# ----------------------------------------------------------------------------- rapor özeti

def test_summarize_counts_value_of_rejections():
    rows = [
        {"decision": "REJECT", "applied": "blocked", "symbol": "XAUUSD", "shadow_status": "SL", "shadow_pips": -10, "confidence": 80},
        {"decision": "REJECT", "applied": "blocked", "symbol": "XAUUSD", "shadow_status": "TP", "shadow_pips": 20, "confidence": 60},
        {"decision": "APPROVE", "applied": "allowed", "symbol": "EURUSD", "shadow_status": "TP", "shadow_pips": 20, "confidence": 85},
        {"decision": "APPROVE", "applied": "allowed", "symbol": "EURUSD", "shadow_status": "SL", "shadow_pips": -8, "confidence": 65},
        {"decision": "APPROVE", "applied": "fail_open", "symbol": "EURUSD", "shadow_status": "IZLENIYOR", "confidence": 90},
        {"decision": "HATA", "applied": "fail_open", "symbol": "EURUSD", "shadow_status": "IZLENIYOR"},
    ]
    s = llm_review.summarize(rows)
    assert (s["total"], s["approved"], s["rejected"], s["errors"], s["blocked"], s["tracking"]) == (6, 3, 2, 1, 2, 2)
    assert s["rejected_stats"]["avoided_pips"] == 10 and s["rejected_stats"]["missed_pips"] == 20
    assert s["net_value_pips"] == -10                       # reddedilenlerden net -10: LLM bu örnekte zarar yazdırdı
    assert s["approved_stats"]["win_rate"] == 50.0 and s["rejected_stats"]["correct_rate"] == 50.0
    assert s["calibration"]["80+"]["win_rate"] == 100.0 and s["calibration"]["60-79"]["win_rate"] == 0.0
    assert s["by_symbol"]["XAUUSD"]["rejected"] == 2


def test_summarize_empty():
    s = llm_review.summarize([])
    assert s["total"] == 0 and s["net_value_pips"] == 0 and s["approved_stats"]["win_rate"] is None


# ----------------------------------------------------------------------------- review_entry (LLM + DB sahte)

def test_review_entry_blocks_caches_and_records(monkeypatch):
    saved, bumped = [], []

    async def fake_save(rec):
        saved.append(rec)
        return 41

    async def fake_bump(rid):
        bumped.append(rid)

    from app import database
    monkeypatch.setattr(database, "save_llm_review", fake_save)
    monkeypatch.setattr(database, "bump_llm_review_repeat", fake_bump)

    async def fake_dossier(ctx):
        return {"x": 1}

    calls = []

    async def fake_ask(dossier, timeout):
        calls.append(1)
        return {"decision": "REJECT", "confidence": 88, "summary": "Haber 20 dk sonra", "reasons": ["a"], "risks": [], "checks": {}}, "m1"

    monkeypatch.setattr(ltr, "build_dossier", fake_dossier)
    monkeypatch.setattr(ltr, "ask_llm", fake_ask)
    ltr._cache.clear()
    ctx = {"symbol": "XAUUSD", "direction": "BUY", "cand": {"score": 80}, "mode": "veto", "fail_open": True,
           "min_confidence": 55, "timeout_sec": 5}

    async def run():
        first = await ltr.review_entry(ctx)
        second = await ltr.review_entry(ctx)           # önbellek: LLM'e ikinci kez gidilmez
        return first, second

    first, second = asyncio.run(run())
    assert first["blocked"] and first["review_id"] == 41 and not first["cached"]
    assert second["blocked"] and second["cached"] and len(calls) == 1 and bumped == [41]
    assert saved[0]["decision"] == "REJECT" and saved[0]["applied"] == "blocked" and saved[0]["model"] == "m1"


def test_review_entry_llm_error_fails_open_and_is_recorded(monkeypatch):
    from app import database
    saved = []

    async def fake_save(rec):
        saved.append(rec)
        return 7

    async def boom(dossier, timeout):
        raise TimeoutError("yavaş")

    async def fake_dossier(ctx):
        return {}

    monkeypatch.setattr(database, "save_llm_review", fake_save)
    monkeypatch.setattr(ltr, "build_dossier", fake_dossier)
    monkeypatch.setattr(ltr, "ask_llm", boom)
    ltr._cache.clear()
    res = asyncio.run(ltr.review_entry({"symbol": "EURUSD", "direction": "SELL", "cand": {}, "mode": "veto",
                                        "fail_open": True, "min_confidence": 55, "timeout_sec": 1}))
    assert res["blocked"] is False and res["applied"] == "fail_open"
    assert saved[0]["decision"] == "HATA" and "TimeoutError" in saved[0]["error"]


# ----------------------------------------------------------------------------- araştırma kaynakları

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Gold slips as Fed hike bets rise</title><pubDate>%s</pubDate></item>
<item><title>Unrelated cooking tips</title><pubDate>%s</pubDate></item></channel></rss>"""


def _rfc(ts):
    from email.utils import formatdate
    return formatdate(ts, usegmt=True).encode()


def test_investing_feed_filtered_by_relevance(monkeypatch):
    now = time.time()
    body = RSS % (_rfc(now - 600), _rfc(now - 600))
    monkeypatch.setattr(forex_research, "_http_bytes", lambda *a, **k: body)
    got = forex_research._investing_headlines("XAUUSD", now, 36)
    assert [g["title"] for g in got] == ["Gold slips as Fed hike bets rise"] and got[0]["via"] == "Investing.com"


def test_rss_with_dtd_is_rejected():
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'
    assert forex_research._parse_rss(evil, "x", time.time(), 36) == []


def test_fetch_headlines_merges_dedupes_and_labels(monkeypatch):
    now = time.time()
    item = lambda t, via, age: {"title": t, "source": via, "via": via, "age_hours": age, "ts": now - age * 3600}
    monkeypatch.setattr(forex_research, "_google_headlines", lambda s, n, m: [item("Gold falls below 4000", "Google News", 1)])
    monkeypatch.setattr(forex_research, "_investing_headlines", lambda s, n, m: [item("Gold falls below 4000!", "Investing.com", 2)])
    monkeypatch.setattr(forex_research, "_tradingview_headlines", lambda s, n, m: [item("Oil gains", "TradingView", 3)])
    out = forex_research.fetch_headlines("XAUUSD")
    assert [o["via"] for o in out] == ["Google News", "TradingView"]            # yinelenen başlık tek sayılır
    assert {o["via"] for o in out} <= {"Google News", "Investing.com", "TradingView"}
    assert "Google News" in forex_research.describe_headlines("XAUUSD", out)


def test_scan_ranks_by_agreement_and_strength(monkeypatch):
    def fake_http(url, headers=None, data=None):
        req = json.loads(data)
        rows = []
        for tick in req["symbols"]["tickers"]:
            if tick.endswith("EURUSD"):
                d = [0.1, 0.1, 0.5, 0.5, 0.5, 0.5, 0.6, 1.1]        # net AL, tüm dilimler hemfikir
            elif tick.endswith("GBPUSD"):
                d = [0.0, 0.0, 0.3, -0.3, 0.4, -0.4, 0.5, 1.3]      # karışık
            else:
                continue
            rows.append({"s": tick, "d": d})
        return json.dumps({"data": rows}).encode()

    monkeypatch.setattr(forex_research, "_http_bytes", fake_http)
    scan = forex_research.scan_opportunities(["EURUSD", "GBPUSD"])
    assert [r["symbol"] for r in scan["top"]] == ["EURUSD", "GBPUSD"]
    assert scan["top"][0]["direction"] == "BUY" and scan["top"][0]["agreement"] == 1.0


def test_wants_scan_only_when_no_symbol():
    assert forex_chat.wants_scan("Bugün hangi pariteler?")
    assert forex_chat.wants_scan("en iyi fırsat nerede")
    assert not forex_chat.wants_scan("Altın hangi seviyede?")
    assert not forex_chat.wants_scan("Yaklaşan haberler")
