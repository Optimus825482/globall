"""Saati geçip değeri gelmemiş olayların tespiti (açıklama anı hızlı yoklama)."""
import time
from datetime import datetime, timezone

from app.forex_news import events_awaiting_actual


def _iso(offset_sec, now):
    return datetime.fromtimestamp(now + offset_sec, tz=timezone.utc).isoformat()


def test_waiting_events_within_window_only():
    now = time.time()
    items = [
        {"title": "geçti-boş", "date_iso": _iso(-120, now), "actual": "—"},
        {"title": "geçti-dolu", "date_iso": _iso(-120, now), "actual": "2.4%"},
        {"title": "yaklaşıyor", "date_iso": _iso(10, now), "actual": ""},
        {"title": "uzak-gelecek", "date_iso": _iso(3600, now), "actual": "—"},
        {"title": "çok-eski", "date_iso": _iso(-3 * 3600, now), "actual": "—"},
        {"title": "tarihsiz", "actual": "—"},
    ]
    names = {e["title"] for e in events_awaiting_actual(items, now)}
    assert names == {"geçti-boş", "yaklaşıyor"}


def test_bad_input_is_ignored():
    now = time.time()
    assert events_awaiting_actual(None, now) == []
    assert events_awaiting_actual([{"date_iso": "bozuk", "actual": ""}, "x"], now) == []
