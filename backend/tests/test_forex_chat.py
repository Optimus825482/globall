"""Forex uzman sohbeti: bağlam sıkıştırma ve sembol çözümleme."""
import time
from datetime import datetime, timezone

from app.routers import forex_chat


def _iso(offset_min):
    return datetime.fromtimestamp(time.time() + offset_min * 60, tz=timezone.utc).isoformat()


def test_mentioned_symbols_turkish_aliases():
    assert forex_chat._mentioned_symbols("Altın ve bitcoin ne olur?") == ["XAUUSD", "BTCUSD"]
    assert forex_chat._mentioned_symbols("eurusd bugün nasıl") == ["EURUSD"]
    assert forex_chat._mentioned_symbols("merhaba") == []


def test_compact_calendar_splits_released_and_upcoming():
    now = time.time()
    items = [
        {"title": "CPI", "currency": "USD", "stars": 3, "date_iso": _iso(-30), "actual": "3.1%",
         "forecast": "3.0%", "outcome": {"side": "bullish", "label_tr": "Beklentiden yüksek"},
         "affected_symbols": ["XAUUSD"]},
        {"title": "NFP", "currency": "USD", "stars": 3, "date_iso": _iso(90), "actual": None},
        {"title": "Eski", "currency": "EUR", "stars": 3, "date_iso": _iso(-900), "actual": "1"},
    ]
    out = forex_chat.compact_calendar(items, now)
    assert [r["title"] for r in out["aciklanan_son_6_saat"]] == ["CPI"]
    assert out["aciklanan_son_6_saat"][0]["sonuc"] == "Beklentiden yüksek"
    assert [r["title"] for r in out["yaklasan_12_saat"]] == ["NFP"]


def test_compact_helpers_tolerate_bad_input():
    assert forex_chat.compact_radar(None) == {}
    assert forex_chat.compact_status("x") == {}
    assert forex_chat.compact_calendar(None, time.time()) == {"aciklanan_son_6_saat": [], "yaklasan_12_saat": []}


def test_stream_delta_keeps_spaces():
    from app.llm_analysis import _stream_delta_text

    # Akış parçalarında baştaki/sondaki boşluk korunmalı; yoksa kelimeler yapışır.
    parts = [{"content": "sterlin"}, {"content": " güçlü,"}, {"content": " dolar"}, {"content": " zayıf"}]
    assert "".join(_stream_delta_text(p) for p in parts) == "sterlin güçlü, dolar zayıf"
    assert _stream_delta_text({"content": " "}) == " "
    assert _stream_delta_text({"content": ""}) is None
    assert _stream_delta_text({}, {"text": "x"}) == "x"
