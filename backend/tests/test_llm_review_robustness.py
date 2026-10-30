"""Üretimde görülen LLM inceleme hataları: reasoning-only yanıt, çok JSON'lu akıl yürütme, hata önbelleği."""
import asyncio
import json
import time

from app import llm_analysis, llm_trade_review as ltr


def test_parse_verdict_takes_last_decision_block_from_reasoning():
    text = (
        "Let me think. Draft: {\"decision\": \"REJECT\", \"confidence\": 90, \"summary\": \"draft\"}. "
        "On reflection the setup is fine. Final answer: "
        "{\"decision\":\"APPROVE\",\"confidence\":72,\"summary\":\"Uyumlu {kapsam}\",\"reasons\":[\"a\"],\"risks\":[],\"checks\":{}}"
    )
    v = ltr.parse_verdict(text)
    assert v["decision"] == "APPROVE" and v["confidence"] == 72 and "{kapsam}" in v["summary"]


def test_parse_verdict_ignores_non_decision_json_and_prose():
    assert ltr.parse_verdict('analysis {"foo": 1} and more text') is None
    assert ltr.parse_verdict("") is None


class _ReasoningOnly:
    """Düşünen model: content hiç yok, yanıt reasoning_content'te (İngilizce)."""
    status = 200

    def __iter__(self):
        parts = ['The user wants me to evaluate this trade, so I should check the higher timeframes and the news calendar carefully before I decide. ', '{"decision":"APPROVE","confidence":66,', '"summary":"ok","reasons":[],"risks":[],"checks":{}}']
        for p in parts:
            yield ("data: " + json.dumps({"choices": [{"delta": {"reasoning_content": p}}]}) + "\n").encode()
        yield b"data: [DONE]\n"

    def read(self, n=0):
        return b""

    def close(self):
        pass


def _patch(monkeypatch):
    async def cfg():
        return {"skills": [], "model": {"name": "m", "temperature": 0.1},
                "provider": {"base_url": "https://llm.test/v1", "api_key_encrypted": "x"}}

    async def opener(request, timeout=None):
        return _ReasoningOnly()

    async def validate(url):
        return url

    monkeypatch.setattr(llm_analysis.database, "get_active_llm_config", cfg)
    monkeypatch.setattr(llm_analysis, "safe_provider_open", opener)
    monkeypatch.setattr(llm_analysis, "validate_provider_url", validate)
    monkeypatch.setattr(llm_analysis, "decrypt_key", lambda v: "k")


def test_reasoning_only_answer_is_accepted_for_structured_output(monkeypatch):
    _patch(monkeypatch)
    verdict, _model = asyncio.run(ltr.ask_llm({"x": 1}, timeout=10))
    assert verdict["decision"] == "APPROVE" and verdict["confidence"] == 66


def test_reasoning_only_without_flag_still_errors_as_before(monkeypatch):
    _patch(monkeypatch)

    async def run():
        events = []
        async for ev in llm_analysis.stream_chat({}, [{"role": "user", "content": "x"}], system_override="s"):
            events.append(ev["event"])
        return events

    assert "error" in asyncio.run(run())          # sohbet metni için Türkçe-yalnızca kuralı korunur


def test_error_results_are_cached_briefly_real_ones_longer():
    assert ltr._ttl({"verdict": None}) == ltr.ERROR_CACHE_SEC
    assert ltr._ttl({"verdict": {"decision": "REJECT"}}) == ltr.CACHE_SEC
    assert ltr.ERROR_CACHE_SEC < ltr.CACHE_SEC


def test_error_then_retry_after_short_ttl(monkeypatch):
    from app import database
    saved = []

    async def fake_save(rec):
        saved.append(rec)
        return len(saved)

    async def fake_dossier(ctx):
        return {}

    calls = []

    async def flaky(dossier, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("yavaş")
        return {"decision": "APPROVE", "confidence": 70, "summary": "ok", "reasons": [], "risks": [], "checks": {}}, "m"

    monkeypatch.setattr(database, "save_llm_review", fake_save)
    monkeypatch.setattr(ltr, "build_dossier", fake_dossier)
    monkeypatch.setattr(ltr, "ask_llm", flaky)
    ltr._cache.clear()
    ctx = {"symbol": "BTCUSD", "direction": "SELL", "cand": {}, "mode": "veto", "fail_open": True, "min_confidence": 55, "timeout_sec": 5}

    async def run():
        first = await ltr.review_entry(ctx)
        same_moment = await ltr.review_entry(ctx)            # hata önbellekte: LLM'e tekrar gidilmez
        ltr._cache[("BTCUSD", "SELL")] = (time.time() - ltr.ERROR_CACHE_SEC - 1, first)   # kısa TTL doldu
        later = await ltr.review_entry(ctx)
        return first, same_moment, later

    first, same, later = asyncio.run(run())
    assert first["applied"] == "fail_open" and same["cached"] and len(calls) == 2
    assert later["applied"] == "allowed" and not later["cached"]
