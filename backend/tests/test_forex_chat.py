"""Forex uzman sohbeti: sembol çözümleme, takvim sıkıştırma, araştırma hattı ve teknik analiz."""
import asyncio
import json
import time
from datetime import datetime, timezone

from app import forex_research
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
    assert [r["title"] for r in out["yaklasan_24_saat"]] == ["NFP"]


def test_calendar_currency_filter_keeps_high_impact():
    now = time.time()
    items = [
        {"title": "JPY orta", "currency": "JPY", "stars": 2, "date_iso": _iso(30)},
        {"title": "EUR kritik", "currency": "EUR", "stars": 3, "date_iso": _iso(30)},
        {"title": "USD orta", "currency": "USD", "stars": 2, "date_iso": _iso(30)},
    ]
    out = forex_chat.compact_calendar(items, now, {"USD"})
    assert {r["title"] for r in out["yaklasan_24_saat"]} == {"EUR kritik", "USD orta"}


def test_compact_calendar_tolerates_bad_input():
    assert forex_chat.compact_calendar(None, time.time()) == {"aciklanan_son_6_saat": [], "yaklasan_24_saat": []}


def test_stream_delta_keeps_spaces():
    from app.llm_analysis import _stream_delta_text

    parts = [{"content": "sterlin"}, {"content": " güçlü,"}, {"content": " dolar"}, {"content": " zayıf"}]
    assert "".join(_stream_delta_text(p) for p in parts) == "sterlin güçlü, dolar zayıf"
    assert _stream_delta_text({"content": " "}) == " "
    assert _stream_delta_text({"content": ""}) is None
    assert _stream_delta_text({}, {"text": "x"}) == "x"


def _trend(n=260, step=1.0, start=100.0):
    return [{"time": i * 3600, "open": start + i * step, "high": start + i * step + 0.5,
             "low": start + i * step - 0.5, "close": start + i * step + 0.2} for i in range(n)]


def test_analyze_candles_trend_direction_and_short_series():
    up = forex_research.analyze_candles(_trend(step=1.0))
    down = forex_research.analyze_candles(_trend(step=-0.2, start=500.0))
    assert up["score"] > 2 and down["score"] < -2
    assert forex_research.analyze_candles(_trend(n=30)) is None


def test_symbol_tickers_and_currencies():
    assert forex_research.yahoo_ticker("XAUUSD") == "GC=F"
    assert forex_research.yahoo_ticker("GBPUSD") == "GBPUSD=X"
    assert forex_research.yahoo_ticker("FOOBAR") is None
    assert forex_research.currencies_for("GBPJPY") == {"GBP", "JPY"}
    assert forex_research.currencies_for("XAUUSD") == {"USD"}


def test_research_events_stream_each_step_as_it_finishes():
    async def fast():
        return "hızlı bulgu", {"a": 1}

    async def slow():
        await asyncio.sleep(0.05)
        return "yavaş bulgu", {"b": 2}

    async def broken():
        raise RuntimeError("x")

    async def run():
        findings = {}
        steps = [("slow", "Yavaş", slow()), ("fast", "Hızlı", fast()), ("bad", "Bozuk", broken())]
        out = []
        async for chunk in forex_chat.research_events(steps, findings):
            out.append(json.loads(chunk.split("data: ", 1)[1]))
        return findings, out

    findings, events = asyncio.run(run())
    done_order = [e["id"] for e in events if e["status"] == "done"]
    assert done_order == ["fast", "slow"]            # hızlı olan önce bildirilir
    assert [e["id"] for e in events if e["status"] == "error"] == ["bad"]
    assert [e["status"] for e in events[:3]] == ["running"] * 3
    assert set(findings) == {"fast", "slow"}


def test_build_context_marks_empty_research():
    assert "uyari" in forex_chat.build_context({})
    ctx = forex_chat.build_context({"ta:XAUUSD": {"yon": "SELL"}, "calendar": {"x": 1}})
    assert ctx["teknik_analiz"] == [{"yon": "SELL"}] and ctx["ekonomik_takvim"] == {"x": 1}


def test_get_candles_prefers_mt5_and_falls_back_to_yahoo(monkeypatch):
    bars = _trend(n=80)
    monkeypatch.setattr(forex_research, "mt5_candles", lambda s, tf: bars if tf == "5m" else [])
    monkeypatch.setattr(forex_research, "_yahoo_tf", lambda s, tf: _trend(n=70))
    got, src = forex_research.get_candles("XAUUSD", "5m")
    assert src == "mt5" and got is bars
    got, src = forex_research.get_candles("XAUUSD", "15m")
    assert src == "yahoo" and len(got) == 70


def test_analysis_reports_data_sources(monkeypatch):
    monkeypatch.setattr(forex_research, "get_candles", lambda s, tf: (_trend(), "mt5"))
    monkeypatch.setattr(forex_research, "live_price", lambda s, fallback=None: (4000.5, "mt5_tick", 2.0))
    a = forex_research.analyze_symbol("XAUUSD")
    assert a["ok"] and a["price"] == 4000.5 and len(a["frames"]) == 8
    text = forex_research.describe_analysis(a)
    assert "MT5 köprüsü, 8 zaman diliminin hepsi" in text and "anlık" in text
