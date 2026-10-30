"""Edge TTS: Microsoft bağlantısı reddedilince boş 200 yerine 502 dönmeli."""
import asyncio

import pytest
from fastapi import HTTPException

import app.main as main


class _FailingTTS:
    class Communicate:
        def __init__(self, *a, **k):
            pass

        async def stream(self):
            raise RuntimeError("403 Invalid response status")
            yield  # pragma: no cover


class _OkTTS:
    class Communicate:
        def __init__(self, *a, **k):
            pass

        async def stream(self):
            yield {"type": "WordBoundary", "data": None}
            yield {"type": "audio", "data": b"AAA"}
            yield {"type": "audio", "data": b"BBB"}


def _setup(monkeypatch, fake):
    monkeypatch.setattr(main, "_require_admin", lambda request: {})
    monkeypatch.setattr(main, "edge_tts", fake)
    monkeypatch.setattr(main, "rate_limit", lambda *a, **k: True)


def test_failure_returns_502_not_empty_audio(monkeypatch):
    _setup(monkeypatch, _FailingTTS)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.edge_tts_audio({"text": "Merhaba dünya"}, None))
    assert exc.value.status_code == 502


def test_success_streams_all_audio_chunks(monkeypatch):
    _setup(monkeypatch, _OkTTS)

    async def run():
        # Üretici ve tüketici AYNI olay döngüsünde olmalı (asyncio.run kapanırken
        # askıdaki async üreteçleri kapatır).
        resp = await main.edge_tts_audio({"text": "Merhaba dünya"}, None)
        return b"".join([c async for c in resp.body_iterator])

    assert asyncio.run(run()) == b"AAABBB"
