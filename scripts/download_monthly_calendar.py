import sys
import os
import urllib.request
import json
import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from app import forex_news, forex_news_bias

def download_and_save():
    # 2026-09-20'den 2026-10-18'e kadar tum ekonomik olaylar
    from_str = "2026-09-20T00:00:00.000Z"
    to_str = "2026-10-18T23:59:59.000Z"
    countries = "US,EU,GB,JP,CA,AU,CH,NZ"
    url = f"https://economic-calendar.tradingview.com/events?from={from_str}&to={to_str}&countries={countries}"
    
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Origin": "https://www.tradingview.com",
            "Accept": "application/json"
        }
    )

    print(f"TradingView Ekonomik Takvim verisi indiriliyor: {from_str} -> {to_str}...")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="ignore"))

    raw_items = data.get("result", [])
    print(f"Toplam ham olay sayisi: {len(raw_items)}")

    parsed_events = []
    for item in raw_items:
        imp = item.get("importance")
        # 1 = Yuksek (3 Yildiz), 0 = Orta (2 Yildiz), -1 = Dusuk (1 Yildiz)
        if imp not in [0, 1]:
            continue

        stars = 3 if imp == 1 else 2
        orig_title = str(item.get("title") or item.get("indicator") or "").strip()
        country_code = str(item.get("country") or "").strip().upper()
        currency = str(item.get("currency") or "").strip().upper()
        date_iso = str(item.get("date") or "")
        unit = str(item.get("unit") or "")

        actual = item.get("actual")
        forecast = item.get("forecast")
        previous = item.get("previous")

        def _fmt(v):
            if v is None:
                return "—"
            return f"{v}{unit}" if unit else str(v)

        actual_str = _fmt(actual)
        forecast_str = _fmt(forecast)
        previous_str = _fmt(previous)

        # evaluate outcome
        outcome = forex_news.evaluate_event_outcome(orig_title, forecast_str, previous_str, actual_str)
        affected_symbols = forex_news.map_symbols_for_event(currency or country_code, orig_title)

        parsed_events.append({
            "id": f"cal-tv-{item.get('id') or abs(hash(orig_title + date_iso)) % 1000000}",
            "title": orig_title,
            "original_title": orig_title,
            "country": country_code,
            "currency": currency or country_code,
            "date_iso": date_iso,
            "importance": imp,
            "stars": stars,
            "actual": actual_str,
            "forecast": forecast_str,
            "previous": previous_str,
            "outcome": outcome,
            "affected_symbols": affected_symbols
        })

    out_path = os.path.join(os.path.dirname(__file__), "..", "outputs", "economic_calendar_events_monthly.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(parsed_events, f, indent=2, ensure_ascii=False)

    print(f"Basariyla {len(parsed_events)} adet (2 ve 3 yildizli) olay kaydedildi: {out_path}")
    decisive = [e for e in parsed_events if e["outcome"] and e["outcome"].get("side")]
    print(f"Yön karari olan olay sayisi (bullish/bearish): {len(decisive)}")

if __name__ == "__main__":
    download_and_save()
