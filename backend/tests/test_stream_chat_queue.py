"""stream_chat: yavaş (ilk jeton >1 sn) sağlayıcıda parça kaybı ve thread sızıntısı olmamalı.

Eski uygulama `wait_for(to_thread(queue.get), 1 sn)` kullanıyordu: zaman aşımında thread kuyrukta
sonsuza dek bloke kalıyor (havuz tükeniyor) ve sonradan gelen parça iptal edilmiş bekleyene gidip
KAYBOLUYORDU. Bu test yavaş sağlayıcıyı taklit eder.
"""
import asyncio
import json
import threading
import time

from app import llm_analysis


class _SlowResponse:
    status = 200

    def __init__(self, first_delay):
        self.first_delay = first_delay

    def __iter__(self):
        time.sleep(self.first_delay)               # ilk jeton gecikir (LLM "düşünüyor")
        for tok in ("Merhaba", " dünya", ", altın", " düşüyor"):
            yield ("data: " + json.dumps({"choices": [{"delta": {"content": tok}}]}) + "\n").encode()
            time.sleep(0.05)
        yield b"data: [DONE]\n"

    def read(self, n=0):
        return b""

    def close(self):
        pass


def _patch(monkeypatch, first_delay):
    async def cfg():
        return {"skills": [], "model": {"name": "m", "temperature": 0.1},
                "provider": {"base_url": "https://llm.test/v1", "api_key_encrypted": "x"}}

    async def opener(request, timeout=None):
        return _SlowResponse(first_delay)

    async def validate(url):
        return url

    monkeypatch.setattr(llm_analysis.database, "get_active_llm_config", cfg)
    monkeypatch.setattr(llm_analysis, "safe_provider_open", opener)
    monkeypatch.setattr(llm_analysis, "validate_provider_url", validate)
    monkeypatch.setattr(llm_analysis, "decrypt_key", lambda v: "k")


def test_slow_first_token_loses_nothing_and_leaks_no_threads(monkeypatch):
    _patch(monkeypatch, first_delay=2.6)           # 1 sn'lik yoklama zaman aşımı en az 2 kez tetiklenir
    before = threading.active_count()

    async def run():
        out = []
        async for ev in llm_analysis.stream_chat({"x": 1}, [{"role": "user", "content": "selam"}], system_override="s"):
            if ev["event"] == "delta":
                out.append(ev["data"]["text"])
            elif ev["event"] == "error":
                raise AssertionError(ev["data"])
        return "".join(out)

    text = asyncio.run(run())
    assert text == "Merhaba dünya, altın düşüyor"      # tek parça kaybolmadı, boşluklar korundu
    time.sleep(1.5)                                     # drain thread'in bitmesi için pay
    assert threading.active_count() <= before + 1       # sızan (bloke) thread yok
