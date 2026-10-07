"""Forex Economic Calendar & Macro Event What-If Scenario Analyzer.

Provides:
- Live Economic Calendar events (ForexFactory / Investing.com macro feed)
- Focus on High & Medium impact events (Fed, CPI, NFP, ECB, PMI, Oil Stocks, etc.)
- Symbol impact mapping (EURUSD, XAUUSD, BTCUSD, USDJPY, GBPUSD)
- Automated "What-If" (Ne Olursa Ne Olur?) Scenario Generation
- In-memory cache for ultra-fast, resilient responses
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
import time
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Önbellek
_CALENDAR_CACHE: Dict[str, Any] = {
    "timestamp": 0,
    "items": [],
}
_CACHE_TTL_SEC = 300  # 5 dakika

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Türkçe İsimlendirme ve Eşleme Sözlüğü
TRANSLATIONS: Dict[str, str] = {
    "Non-Farm Employment Change": "ABD Tarım Dışı İstihdam (NFP)",
    "Unemployment Rate": "İşsizlik Oranı",
    "CPI m/m": "TÜFE Enflasyon (Aylık)",
    "CPI y/y": "TÜFE Enflasyon (Yıllık)",
    "Core CPI m/m": "Çekirdek TÜFE (Aylık)",
    "Core CPI y/y": "Çekirdek TÜFE (Yıllık)",
    "Federal Funds Rate": "Fed Faiz Kararı",
    "FOMC Statement": "FOMC Faiz Beyanatı",
    "FOMC Press Conference": "Powell Basın Toplantısı",
    "FOMC Meeting Minutes": "FOMC Toplantı Tutanakları",
    "PPI m/m": "ÜFE Üretici Fiyat Endeksi (Aylık)",
    "Retail Sales m/m": "Perakende Satışlar (Aylık)",
    "Core Retail Sales m/m": "Çekirdek Perakende Satışlar",
    "Crude Oil Inventories": "ABD Ham Petrol Stokları (EIA)",
    "ECB Monetary Policy Statement": "ECB Para Politikası Beyanatı",
    "Main Refinancing Rate": "ECB Faiz Kararı",
    "ECB Press Conference": "Lagarde Basın Toplantısı",
    "Monetary Policy Statement": "Merkez Bankası Para Politikası",
    "Official Bank Rate": "İngiltere (BoE) Faiz Kararı",
    "BOJ Policy Rate": "Japonya (BoJ) Faiz Kararı",
    "Flash Manufacturing PMI": "İmalat PMI (Öncü)",
    "Flash Services PMI": "Hizmet PMI (Öncü)",
    "ISM Manufacturing PMI": "ABD ISM İmalat PMI",
    "ISM Services PMI": "ABD ISM Hizmet PMI",
    "Prelim GDP q/q": "GSYH Büyüme Oranı (Öncü)",
    "Final GDP q/q": "GSYH Büyüme Oranı (Nihai)",
    "Unemployment Claims": "İşsizlik Haklarından Yararlanma Başvuruları",
    "OPEC-JMMC Meetings": "OPEC+ Petrol Bakanları Toplantısı",
    "OPEC Meetings": "OPEC Zirvesi",
    "Natural Gas Storage": "Doğalgaz Depolama Raporu",
}

FALLBACK_EVENTS = [
    {
        "id": "cal-fed-decision",
        "title": "Fed Faiz Kararı & FOMC Beyanatı",
        "original_title": "Federal Funds Rate",
        "country": "USD",
        "date_str": "Bugün 21:00",
        "impact": "High",
        "impact_label": "YÜKSEK (3 Boğa)",
        "forecast": "5.00%",
        "previous": "5.25%",
        "affected_symbols": ["XAUUSD", "EURUSD", "BTCUSD", "USDJPY", "GBPUSD"],
        "scenario": {
            "title": "Fed Faiz & Para Politikası Senaryosu",
            "bullish_trigger": "Faiz beklenti üzeri kalırsa veya Powell Şahin konuşursa",
            "bullish_outcome": "Dolar Endeksi (DXY) fırlar. XAUUSD (Altın), EURUSD ve BTCUSD sert satış yer.",
            "bearish_trigger": "Faiz indirimi onaylanır ve Güvercin mesajlar verilirse",
            "bearish_outcome": "Dolar zayıflar. XAUUSD ve EURUSD yukarı patlar, BTCUSD güçlü yükselir.",
            "scalper_tip": "Açıklanma dakikasında (21:00 - 21:05) yüksek spread oluşur; yön oturduktan sonra momentumla scalp yapın."
        }
    },
    {
        "id": "cal-us-cpi",
        "title": "ABD TÜFE Enflasyon Verisi (CPI)",
        "original_title": "CPI m/m",
        "country": "USD",
        "date_str": "Bugün 15:30",
        "impact": "High",
        "impact_label": "YÜKSEK (3 Boğa)",
        "forecast": "0.2%",
        "previous": "0.3%",
        "affected_symbols": ["XAUUSD", "EURUSD", "BTCUSD", "USDJPY"],
        "scenario": {
            "title": "ABD Enflasyon Senaryosu",
            "bullish_trigger": "TÜFE Beklentiden Yüksek Gelirse (> 0.2%)",
            "bullish_outcome": "Dolar güçlenir, faiz indirimi beklentileri ertelenir. XAUUSD ve EURUSD düşüşe geçer.",
            "bearish_trigger": "TÜFE Beklentiden Düşük Gelirse (< 0.2%)",
            "bearish_outcome": "Enflasyonun soğuduğu teyit edilir, Dolar değer kaybeder. XAUUSD ve EURUSD hızla yükselir.",
            "scalper_tip": "Veri açıklandığı anda ters yöne emir asmayın; ilk 1 dakikalık fitilin yönüne göre pozisyon alın."
        }
    },
    {
        "id": "cal-us-nfp",
        "title": "ABD Tarım Dışı İstihdam (NFP)",
        "original_title": "Non-Farm Employment Change",
        "country": "USD",
        "date_str": "Cuma 15:30",
        "impact": "High",
        "impact_label": "YÜKSEK (3 Boğa)",
        "forecast": "145K",
        "previous": "142K",
        "affected_symbols": ["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"],
        "scenario": {
            "title": "İstihdam Piyasası Senaryosu",
            "bullish_trigger": "İstihdam Beklenti Üzeri Çıkarsa (> 150K)",
            "bullish_outcome": "ABD ekonomisi güçlü algısıyla Dolar değer kazanır. EURUSD ve XAUUSD geri çekilir.",
            "bearish_trigger": "İstihdam Beklenti Altı Kalırsa (< 130K)",
            "bearish_outcome": "Resesyon / faiz indirimi fiyatlanır. Dolar satılır, Altın ve Kripto yukarı fırlar.",
            "scalper_tip": "NFP anında piyasanın en sert hareket ettiği zamandır. 15-20 saniye bekleyip yön trendine katılın."
        }
    },
    {
        "id": "cal-oil-inventory",
        "title": "ABD Ham Petrol Stokları (EIA)",
        "original_title": "Crude Oil Inventories",
        "country": "USD",
        "date_str": "Çarşamba 17:30",
        "impact": "Medium",
        "impact_label": "ORTA (2 Boğa)",
        "forecast": "-1.5M",
        "previous": "+3.8M",
        "affected_symbols": ["USOIL", "USDCAD"],
        "scenario": {
            "title": "Petrol Arz-Stok Senaryosu",
            "bullish_trigger": "Stoklar beklenenden fazla düşerse (Arz kısıtlı)",
            "bullish_outcome": "USOIL (Ham Petrol) yükselir. USDCAD düşüş eğilimine girer.",
            "bearish_trigger": "Stoklarda beklenmeyen yüksek artış olursa (Talep zayıf)",
            "bearish_outcome": "USOIL hızlı satış yer ve gevşer.",
            "scalper_tip": "USOIL işlemlerinde stok verisi sonrası oluşan mumun kırıldığı yöne stoplu girin."
        }
    },
    {
        "id": "cal-ecb-rate",
        "title": "Avrupa Merkez Bankası (ECB) Faiz Kararı",
        "original_title": "Main Refinancing Rate",
        "country": "EUR",
        "date_str": "Perşembe 15:15",
        "impact": "High",
        "impact_label": "YÜKSEK (3 Boğa)",
        "forecast": "3.50%",
        "previous": "3.65%",
        "affected_symbols": ["EURUSD", "EURGBP", "EURJPY"],
        "scenario": {
            "title": "Avrupa Faiz Senaryosu",
            "bullish_trigger": "Faiz sabit tutulur veya Lagarde Şahin kalırsa",
            "bullish_outcome": "EURUSD ve EURGBP pariteleri güçlü alımlarla 40-60 pip yukarı gider.",
            "bearish_trigger": "Erken faiz indirimi ve gevşek mesajlar",
            "bearish_outcome": "EURUSD satış baskısıyla desteklere çekilir.",
            "scalper_tip": "ECB kararı sonrası 15:45'teki Lagarde konuşmasında da volatilite devam eder."
        }
    }
]


def format_event_date(date_iso: str) -> str:
    """ISO tarihini kullanıcı dostu Türkçe zaman formatına çevirir."""
    try:
        dt = datetime.datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
        # Türkiye saatine göre düzenle
        now = datetime.datetime.now(dt.tzinfo)
        diff_days = (dt.date() - now.date()).days
        time_str = dt.strftime("%H:%M")

        if diff_days == 0:
            return f"Bugün {time_str}"
        elif diff_days == 1:
            return f"Yarın {time_str}"
        elif diff_days == -1:
            return f"Dün {time_str}"
        else:
            days_tr = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
            day_name = days_tr[dt.weekday()]
            return f"{day_name} {time_str}"
    except Exception:
        return date_iso[:16].replace("T", " ")


def map_symbols_for_event(country: str, title: str) -> List[str]:
    """Ülke ve olaya göre etkilenen forex sembollerini belirler."""
    t = title.lower()
    symbols: List[str] = []

    if country == "USD":
        symbols = ["XAUUSD", "EURUSD", "BTCUSD", "USDJPY", "GBPUSD"]
    elif country == "EUR":
        symbols = ["EURUSD", "EURGBP", "EURJPY"]
    elif country == "GBP":
        symbols = ["GBPUSD", "EURGBP", "GBPJPY"]
    elif country == "JPY":
        symbols = ["USDJPY", "EURJPY", "GBPJPY"]
    elif country == "CAD":
        symbols = ["USDCAD", "USOIL"]
    elif country == "AUD":
        symbols = ["AUDUSD", "XAUUSD"]
    elif country == "CHF":
        symbols = ["USDCHF", "EURCHF"]
    else:
        symbols = ["EURUSD", "XAUUSD"]

    if "oil" in t or "petrol" in t or "crude" in t:
        if "USOIL" not in symbols:
            symbols.insert(0, "USOIL")

    if "gold" in t or "altın" in t:
        if "XAUUSD" not in symbols:
            symbols.insert(0, "XAUUSD")

    return symbols[:5]


def generate_event_scenario(title: str, country: str, symbols: List[str]) -> Dict[str, str]:
    """Ekonomik gösterge için 'Ne Olursa Ne Olur?' senaryosu oluşturur."""
    sym_str = ", ".join(symbols[:3])
    t = title.lower()

    if any(k in t for k in ["rate", "faiz", "fomc", "fed", "monetary"]):
        return {
            "title": f"{country} Faiz & Politika Senaryosu",
            "bullish_trigger": "Faiz Beklenti Üzeri / Şahin Açıklama",
            "bullish_outcome": f"{country} para birimi hızla değer kazanır. Ters pariteler ve Altın (XAUUSD) düşer.",
            "bearish_trigger": "Faiz İndirimi / Güvercin Açıklama",
            "bearish_outcome": f"{country} değer kaybeder. {sym_str} yukarı yönlü rahatlama rallisi yapar.",
            "scalper_tip": "Açıklanma anında ilk 2-3 dakika spread açılabilir; yön netleşince kırılıma katılın."
        }
    elif any(k in t for k in ["cpi", "tüfe", "inflation", "enflasyon", "ppi", "üfe"]):
        return {
            "title": f"{country} Enflasyon (TÜFE) Senaryosu",
            "bullish_trigger": "Enflasyon Beklenti Üstü Çıkarsa (Sıcak Veri)",
            "bullish_outcome": f"Faiz artışı / sıkılaşma fiyatlanır. {country} güçlenir, XAUUSD ve risk varlıkları baskılanır.",
            "bearish_trigger": "Enflasyon Beklenti Altı Kalırsa (Soğuma)",
            "bearish_outcome": f"Faiz indirimi ihtimali güçlenir. Altın (XAUUSD) ve {sym_str} sert alım görür.",
            "scalper_tip": "Veri anında ters yöne emir yazmayın; ilk 1 dakikalık mum kapanış yönünde scalp deneyin."
        }
    elif any(k in t for k in ["employment", "nfp", "istihdam", "payrolls", "işsizlik", "claims"]):
        return {
            "title": f"{country} İstihdam Senaryosu",
            "bullish_trigger": "İstihdam Beklenti Üstü / Güçlü İş Gücü",
            "bullish_outcome": f"Ekonomi güçlü algısıyla {country} prim yapar. Karşıt pariteler geri çekilir.",
            "bearish_trigger": "İstihdam Beklenti Altı / Zayıf İş Gücü",
            "bearish_outcome": f"Ekonomik yavaşlama algısıyla {country} satılır; XAUUSD ve diğer pariteler yükselir.",
            "scalper_tip": "Volatilite dalgası 10-15 dakika sürebilir; stop mesafesini normalin 1.5 katı tutun."
        }
    elif any(k in t for k in ["oil", "petrol", "crude", "inventories"]):
        return {
            "title": "Ham Petrol Stok Senaryosu",
            "bullish_trigger": "Stoklarda Beklenmedik Düşüş (Arz Azalması)",
            "bullish_outcome": "USOIL hızlı yükselişe geçer. USDCAD düşer.",
            "bearish_trigger": "Stoklarda Yüksek Artış (Arz Fazlası)",
            "bearish_outcome": "USOIL sert satış yer. USDCAD yukarı tepki verir.",
            "scalper_tip": "Stok verisi açıklandıktan 30 saniye sonra trend yönüne stoplu katılın."
        }
    else:
        return {
            "title": f"{country} Makro Veri Senaryosu",
            "bullish_trigger": "Açıklanan > Beklenti (Pozitif Sürpriz)",
            "bullish_outcome": f"{country} varlıkları primlenir. {sym_str} üzerinde hareketlilik artar.",
            "bearish_trigger": "Açıklanan < Beklenti (Negatif Sürpriz)",
            "bearish_outcome": f"{country} üzerinde kâr satışı gelir, karşıt pariteler destek bulur.",
            "scalper_tip": "Veri açıklandığında seans hacmine dikkat edin; düşük hacimde sahte kırılımlar oluşabilir."
        }


async def fetch_economic_calendar() -> List[Dict[str, Any]]:
    """ForexFactory & Küresel ekonomik takvim verisini çeker ve analiz eder."""
    def _fetch() -> Optional[str]:
        try:
            req = urllib.request.Request(
                CALENDAR_URL,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                }
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    return resp.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            logger.debug("Calendar fetch error: %s", exc)
        return None

    loop = asyncio.get_running_loop()
    raw_json = await loop.run_in_executor(None, _fetch)
    if not raw_json:
        return []

    try:
        events = json.loads(raw_json)
    except Exception as exc:
        logger.debug("Calendar JSON parse error: %s", exc)
        return []

    parsed: List[Dict[str, Any]] = []

    for ev in events:
        impact = str(ev.get("impact", "")).capitalize()
        # Yalnızca High ve Medium olan önemli olayları al
        if impact not in ["High", "Medium"]:
            continue

        orig_title = str(ev.get("title", "")).strip()
        country = str(ev.get("country", "")).strip().upper()
        date_iso = str(ev.get("date", "")).strip()

        # Türkçe Başlık Eşlemesi
        tr_title = TRANSLATIONS.get(orig_title)
        if not tr_title:
            # Kısmi arama
            for en_k, tr_v in TRANSLATIONS.items():
                if en_k.lower() in orig_title.lower():
                    tr_title = f"{country} {tr_v}"
                    break
        if not tr_title:
            tr_title = f"{country} {orig_title}"

        affected_symbols = map_symbols_for_event(country, orig_title)
        scenario = generate_event_scenario(orig_title, country, affected_symbols)

        parsed.append({
            "id": f"cal-{abs(hash(orig_title + date_iso)) % 1000000}",
            "title": tr_title,
            "original_title": orig_title,
            "country": country,
            "date_str": format_event_date(date_iso),
            "impact": impact,
            "impact_label": "YÜKSEK (3 Boğa)" if impact == "High" else "ORTA (2 Boğa)",
            "forecast": ev.get("forecast") or "—",
            "previous": ev.get("previous") or "—",
            "affected_symbols": affected_symbols,
            "scenario": scenario,
        })

    return parsed


async def get_forex_news(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """Ekonomik takvim açıklamalarını analiz edilmiş 'Ne Olursa Ne Olur' senaryolarıyla döner."""
    now = time.time()
    if not force_refresh and _CALENDAR_CACHE["items"] and (now - _CALENDAR_CACHE["timestamp"]) < _CACHE_TTL_SEC:
        return _CALENDAR_CACHE["items"]

    items = await fetch_economic_calendar()

    # Eğer canlı takvim çekilemezse veya az geldiyse hazır olayları ekle
    if len(items) < 4:
        for fb in FALLBACK_EVENTS:
            if not any(x["title"] == fb["title"] for x in items):
                items.append(fb)

    # Önem derecesine göre sırala (High önce)
    def sort_key(x: Dict[str, Any]) -> int:
        return 0 if x.get("impact") == "High" else 1

    items.sort(key=sort_key)

    _CALENDAR_CACHE["timestamp"] = now
    _CALENDAR_CACHE["items"] = items[:15]
    return _CALENDAR_CACHE["items"]
