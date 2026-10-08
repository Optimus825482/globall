import pytest
from app.forex_news import get_forex_news, FALLBACK_EVENTS, FALLBACK_NEWS, translate_title, map_symbols_for_event, generate_event_scenario


import asyncio

def test_get_forex_news_structure():
    events = asyncio.run(get_forex_news(force_refresh=False))
    assert isinstance(events, list)
    assert len(events) > 0

    first = events[0]
    assert "id" in first
    assert "title" in first
    assert "country" in first
    assert "stars" in first
    assert first["stars"] in [2, 3]
    assert "impact" in first
    assert first["impact"] in ["High", "Medium"]
    assert "scenario" in first
    assert "bullish_trigger" in first["scenario"]
    assert "bullish_outcome" in first["scenario"]
    assert "bearish_trigger" in first["scenario"]
    assert "bearish_outcome" in first["scenario"]
    assert "summary_short" in first["scenario"]
    assert "affected_symbols" in first
    assert len(first["affected_symbols"]) > 0


def test_symbol_mapping():
    usd_syms = map_symbols_for_event("USD", "Consumer Price Index")
    assert "XAUUSD" in usd_syms
    assert "EURUSD" in usd_syms

    oil_syms = map_symbols_for_event("USD", "EIA Crude Oil Stocks")
    assert "USOIL" in oil_syms


def test_fallback_news_alias():
    assert FALLBACK_NEWS is FALLBACK_EVENTS
    assert len(FALLBACK_EVENTS) >= 5
    for ev in FALLBACK_EVENTS:
        assert ev["stars"] in [2, 3]
        assert len(ev["affected_symbols"]) > 0


def test_turkish_comment_resolution():
    from app.forex_news import get_turkish_comment
    # Trade balance
    c1 = get_turkish_comment("", "Trade Balance", "Almanya Dış Ticaret Dengesi")
    assert "Dış Ticaret Dengesi" in c1
    # CPI
    c2 = get_turkish_comment("", "Consumer Price Index", "TÜFE Enflasyon")
    assert "Tüketici Fiyat Endeksi" in c2
    # Generic
    c3 = get_turkish_comment("", "Some Unknown Event", "Bilinmeyen Gösterge")
    assert "piyasa katılımcıları" in c3


def test_economic_calendar_db_persistence():
    from app import database
    from app.forex_news import sync_economic_calendar_to_db, _CALENDAR_CACHE

    # Test event saving and loading
    sample_events = [
        {
            "id": "test-cal-1",
            "title": "Fed Faiz Kararı Test",
            "original_title": "Fed Interest Rate Test",
            "country": "USD",
            "currency": "USD",
            "country_name": "ABD",
            "flag": "🇺🇸",
            "date_str": "Bugün 21:00",
            "date_iso": "2026-10-08T18:00:00Z",
            "impact": "High",
            "stars": 3,
            "stars_str": "⭐⭐⭐",
            "impact_label": "⭐⭐⭐ YÜKSEK (3 Yıldız)",
            "forecast": "5.00%",
            "previous": "5.25%",
            "actual": "—",
            "status": "Bekleniyor",
            "affected_symbols": ["XAUUSD", "EURUSD"],
            "scenario": {
                "title": "Test Senaryo",
                "bullish_trigger": "Faiz Sabit",
                "bullish_outcome": "Dolar Artar",
                "bearish_trigger": "Faiz İndirimi",
                "bearish_outcome": "Dolar Düşer",
                "summary_short": "Test Özet",
            },
        }
    ]

    # Test DB save
    count = asyncio.run(database.save_economic_calendar_events(sample_events))
    assert count == 1

    # Test DB read
    loaded = asyncio.run(database.get_economic_calendar_events())
    assert len(loaded) >= 1
    found = next((x for x in loaded if x.get("id") == "test-cal-1"), None)
    assert found is not None
    assert found["title"] == "Fed Faiz Kararı Test"
    assert found["stars"] == 3

    # Test last sync ts
    last_sync = asyncio.run(database.get_last_economic_calendar_sync())
    assert last_sync > 0

    # Test get_forex_news reads from cache / DB without network delay
    _CALENDAR_CACHE["items"] = []
    _CALENDAR_CACHE["timestamp"] = 0
    news = asyncio.run(get_forex_news(force_refresh=False))
    assert isinstance(news, list)
    assert len(news) > 0
    assert any(x.get("id") == "test-cal-1" for x in news)

