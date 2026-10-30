"""Yedek LLM: ana model metin üretmeden hata verirse yedek modele geçilir."""
import asyncio

import pytest

from app import llm_analysis, llm_trade_review as ltr

FB = {"provider": {}, "model": {"name": "yedek-model"}, "skills": []}


def run(coro):
    return asyncio.run(coro)


async def collect(agen):
    return [ev async for ev in agen]


def patch_once(monkeypatch, script):
    """script: cfg_override -> olay listesi."""
    seen = []

    async def fake_once(snapshot, messages, tools, tool_executor, active_skills, max_tokens, system_override, accept_reasoning, cfg_override=None):
        seen.append(cfg_override)
        for ev in script(cfg_override):
            yield ev

    monkeypatch.setattr(llm_analysis, "_stream_chat_once", fake_once)
    return seen


def patch_fb(monkeypatch, cfg):
    async def get_fb():
        return cfg
    monkeypatch.setattr(llm_analysis.database, "get_fallback_llm_config", get_fb)
    monkeypatch.setattr(ltr.database, "get_fallback_llm_config", get_fb)


def fail_then_ok(cfg):
    if cfg is None:
        return [{"event": "error", "data": {"error": "TimeoutError"}}]
    return [{"event": "delta", "data": {"text": "merhaba"}}, {"event": "done", "data": {"status": "ok", "model": "yedek-model"}}]


def test_stream_chat_switches_to_fallback_before_any_text(monkeypatch):
    seen = patch_once(monkeypatch, fail_then_ok)
    patch_fb(monkeypatch, FB)
    evs = run(collect(llm_analysis.stream_chat({}, [])))
    assert [e["event"] for e in evs] == ["delta", "done"] and evs[-1]["data"]["fallback_used"] is True
    assert seen == [None, FB]


def test_stream_chat_does_not_switch_after_text_started(monkeypatch):
    patch_once(monkeypatch, lambda cfg: [{"event": "delta", "data": {"text": "yarım"}}, {"event": "error", "data": {"error": "koptu"}}])
    patch_fb(monkeypatch, FB)
    evs = run(collect(llm_analysis.stream_chat({}, [])))
    assert [e["event"] for e in evs] == ["delta", "error"]


def test_stream_chat_without_fallback_config_keeps_error(monkeypatch):
    patch_once(monkeypatch, fail_then_ok)
    patch_fb(monkeypatch, None)
    evs = run(collect(llm_analysis.stream_chat({}, [])))
    assert [e["event"] for e in evs] == ["error"]
    patch_fb(monkeypatch, FB)
    assert [e["event"] for e in run(collect(llm_analysis.stream_chat({}, [], fallback=False)))] == ["error"]


VERDICT = '{"decision":"APPROVE","confidence":70,"summary":"ok","reasons":[],"risks":[],"checks":{}}'


def test_ask_llm_falls_back_on_timeout_and_marks_model(monkeypatch):
    def script(cfg):
        if cfg is None:
            return [{"event": "error", "data": {"error": "ilk jeton zaman aşımı"}}]
        return [{"event": "delta", "data": {"text": VERDICT}}, {"event": "done", "data": {"model": "yedek-model"}}]
    patch_once(monkeypatch, script)
    patch_fb(monkeypatch, FB)
    verdict, model = run(ltr.ask_llm({}, 25))
    assert verdict["decision"] == "APPROVE" and model == "yedek-model (yedek)"


def test_ask_llm_falls_back_on_invalid_json_and_raises_when_both_fail(monkeypatch):
    patch_fb(monkeypatch, FB)
    patch_once(monkeypatch, lambda cfg: [{"event": "delta", "data": {"text": "json değil"}}, {"event": "done", "data": {}}])
    with pytest.raises(ValueError):
        run(ltr.ask_llm({}, 25))
    patch_once(monkeypatch, lambda cfg: [{"event": "error", "data": {"error": "x"}}])
    with pytest.raises(RuntimeError):
        run(ltr.ask_llm({}, 25))


def test_ask_llm_without_fallback_uses_full_budget(monkeypatch):
    patch_fb(monkeypatch, None)
    seen = patch_once(monkeypatch, lambda cfg: [{"event": "delta", "data": {"text": VERDICT}}, {"event": "done", "data": {"model": "m"}}])
    verdict, model = run(ltr.ask_llm({}, 25))
    assert model == "m" and seen == [None]
