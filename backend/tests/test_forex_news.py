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
