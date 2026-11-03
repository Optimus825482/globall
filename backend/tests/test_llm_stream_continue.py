"""Akış yolu kesilme koruması: sahte sağlayıcıyla otomatik devam turu (2026-11-04).

Kullanıcı raporu: forex sohbetinde yanıt 4096 jetonda kesilip «devam et» notu düşüyordu;
akış yolu (stream_chat) bunda YOKTU (yalnız tamponlu chat() vardı). Bu test akış yolunun
(1) kesilince kendisi bir devam turu kurduğunu, (2) devam başarısızsa eski notu
korumasını, (3) kesilme yoksa ek istek ATILMADIĞINI doğrular.
"""
import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.fernet import Fernet

os.environ["LLM_ALLOW_PRIVATE_PROVIDER"] = "1"

from app.llm_analysis import encrypt_key, stream_chat   # noqa: E402 - env kancasından sonra

PART1 = "## Tarama — adaylar var\n- NZDUSD: SELL\n- AUDNZD: BUY\nNedeni: zaten açık pozis"
CONT = "yon var, yeni emir açılmadı. Risk: stop mesafesini koru."
CONTINUE_PROMPT_MARK = "kesintisiz kapatıp devam et"

_seen_requests: list = []
_fail_continue = False
_end_reason = "length"   # sahte akışın finish_reason'u ("length" → koruma devrede, "stop" → yok)


class _FakeProvider(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        _seen_requests.append(body)
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for piece in (PART1[:12], PART1[12:]):
                chunk = {"choices": [{"delta": {"content": piece}, "finish_reason": None}]}
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
            end = {"choices": [{"delta": {}, "finish_reason": _end_reason}]}
            self.wfile.write(f"data: {json.dumps(end, ensure_ascii=False)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        elif _fail_continue:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error": "sahte sunucu hatasi"}')
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {"choices": [{"message": {"role": "assistant", "content": CONT}, "finish_reason": "stop"}]}
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode())


_server: ThreadingHTTPServer = None
_port = 0


def _start_server():
    global _server, _port
    os.environ["LLM_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    _server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeProvider)
    _port = _server.server_address[1]
    threading.Thread(target=_server.serve_forever, daemon=True).start()


def _stop_server():
    _server.shutdown()


def _cfg():
    return {"provider": {"base_url": f"http://127.0.0.1:{_port}",
                         "api_key_encrypted": encrypt_key("test-key")},
            "model": {"name": "fake-model", "temperature": 0.7}, "skills": []}


def _collect(events):
    return "".join((ev["data"] or {}).get("text", "") for ev in events if ev["event"] == "delta")


async def _run_stream():
    events = []
    async for ev in stream_chat({}, [{"role": "user", "content": "tara"}], max_tokens=50,
                                system_override="SAHNE TEST", cfg_override=_cfg()):
        events.append(ev)
    return events


def test_stream_truncated_auto_continues():
    _start_server()
    try:
        _seen_requests.clear()
        events = asyncio.run(_run_stream())
        text = _collect(events)
        assert PART1 in text and CONT in text, f"birleşik metin eksik: {text!r}"
        assert "devamı için" not in text, "otomatik devam varken not düşmemeliydi"
        assert events[-1]["data"]["auto_continued"] is True
        assert events[-1]["data"]["truncated"] is True
        body = _seen_requests[-1]
        assert body.get("stream") is False, "devam turu non-streaming olmalı"
        contents = [str(m.get("content")) for m in body["messages"]]
        assert any(PART1 in c for c in contents), "devam gövdesinde yarım yanıt yok"
        assert any(CONTINUE_PROMPT_MARK in c for c in contents), "devam gövdesinde talimat yok"
    finally:
        _stop_server()


def test_stream_continue_failure_keeps_notice():
    _start_server()
    try:
        global _fail_continue
        _fail_continue = True
        _seen_requests.clear()
        events = asyncio.run(_run_stream())
        text = _collect(events)
        assert PART1 in text and "devamı için «devam et» yazın" in text, f"not bekleniyordu: {text!r}"
        assert events[-1]["data"]["auto_continued"] is False
    finally:
        _fail_continue = False
        _stop_server()


def test_stream_untruncated_makes_no_extra_request():
    _start_server()
    try:
        global _end_reason
        _end_reason = "stop"
        _seen_requests.clear()
        events = asyncio.run(_run_stream())
        text = _collect(events)
        assert PART1 in text and "devamı için" not in text
        assert len(_seen_requests) == 1, f"kesilme yokken 1 istek beklenir, {len(_seen_requests)} gitti"
        assert events[-1]["data"]["auto_continued"] is False
    finally:
        _end_reason = "length"
        _stop_server()
