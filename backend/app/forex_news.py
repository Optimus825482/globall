"""Forex Economic Calendar & Macro Event What-If Scenario Analyzer.

Provides:
- Live Economic Calendar events matching Investing.com 2-Star (Medium) and 3-Star (High) impact.
- Focus on High & Medium volatility events (Fed, CPI, NFP, ECB, BoE, BoJ, PMI, Retail Sales, EIA Oil, etc.)
- Specific Forex & Crypto symbol impact mapping (XAUUSD, EURUSD, BTCUSD, USDJPY, GBPUSD, USOIL, USDCAD, AUDUSD)
- Automated "What-If" (Ne Olursa Ne Olur?) Scenario Generation with explicit triggers and outcomes
- Multi-provider resilience: TradingView API + Investing.com parser + ForexFactory + Curated Fallback
- In-memory & disk caching for fast responses and zero downtime
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from app import database
except ImportError:
    try:
        from . import database
    except ImportError:
        database = None  # type: ignore

# Önbellek ve Senkronizasyon Ayarları
_CACHE_TTL_SEC = 300  # 5 dakika bellek tazeleme
CALENDAR_REFRESH_INTERVAL_SEC = 3 * 3600  # 3 saatte bir arka planda kontrol ve DB güncelleme

_CALENDAR_CACHE: Dict[str, Any] = {
    "timestamp": 0,
    "items": [],
}

CACHE_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "economic_calendar_cache.json")

# Türkçe İsimlendirme ve Eşleme Sözlüğü
TRANSLATIONS: Dict[str, str] = {
    # Faiz ve Merkez Bankası
    "Federal Funds Rate": "Fed Faiz Kararı",
    "Fed Interest Rate Decision": "Fed Faiz Kararı",
    "FOMC Statement": "FOMC Faiz Beyanatı",
    "FOMC Press Conference": "Powell Basın Toplantısı",
    "FOMC Meeting Minutes": "FOMC Toplantı Tutanakları",
    "FOMC Minutes": "FOMC Toplantı Tutanakları",
    "Fed Chair Powell Speaks": "Powell Konuşması",
    "ECB Monetary Policy Statement": "ECB Para Politikası Beyanatı",
    "Main Refinancing Rate": "ECB Faiz Kararı",
    "ECB Interest Rate Decision": "ECB Faiz Kararı",
    "ECB Press Conference": "Lagarde Basın Toplantısı",
    "ECB President Lagarde Speaks": "Lagarde Konuşması",
    "Monetary Policy Statement": "Merkez Bankası Para Politikası",
    "Official Bank Rate": "İngiltere (BoE) Faiz Kararı",
    "BoE Interest Rate Decision": "İngiltere (BoE) Faiz Kararı",
    "BoE Gov Bailey Speaks": "BoE Başkanı Bailey Konuşması",
    "BOJ Policy Rate": "Japonya (BoJ) Faiz Kararı",
    "BoJ Interest Rate Decision": "Japonya (BoJ) Faiz Kararı",
    "BOJ Gov Ueda Speaks": "BoJ Başkanı Ueda Konuşması",
    "BoJ Monetary Policy Statement": "BoJ Para Politikası Raporu",
    "RBA Interest Rate Decision": "Avustralya (RBA) Faiz Kararı",
    "BOC Interest Rate Decision": "Kanada (BoC) Faiz Kararı",
    "SNB Interest Rate Decision": "İsviçre (SNB) Faiz Kararı",

    # Enflasyon
    "CPI m/m": "TÜFE Enflasyon (Aylık)",
    "CPI y/y": "TÜFE Enflasyon (Yıllık)",
    "CPI MoM": "TÜFE Enflasyon (Aylık)",
    "CPI YoY": "TÜFE Enflasyon (Yıllık)",
    "Core CPI m/m": "Çekirdek TÜFE (Aylık)",
    "Core CPI y/y": "Çekirdek TÜFE (Yıllık)",
    "Core CPI MoM": "Çekirdek TÜFE (Aylık)",
    "Core CPI YoY": "Çekirdek TÜFE (Yıllık)",
    "PCE Price Index m/m": "PCE Fiyat Endeksi (Aylık)",
    "Core PCE Price Index m/m": "Çekirdek PCE Enflasyon (Aylık)",
    "Core PCE Price Index MoM": "Çekirdek PCE Enflasyon (Aylık)",
    "PPI m/m": "ÜFE Üretici Fiyat Endeksi (Aylık)",
    "PPI y/y": "ÜFE Üretici Fiyat Endeksi (Yıllık)",
    "PPI MoM": "ÜFE Üretici Fiyat Endeksi (Aylık)",
    "PPI YoY": "ÜFE Üretici Fiyat Endeksi (Yıllık)",
    "Core PPI MoM": "Çekirdek ÜFE (Aylık)",

    # İstihdam
    "Non-Farm Employment Change": "ABD Tarım Dışı İstihdam (NFP)",
    "Nonfarm Payrolls": "ABD Tarım Dışı İstihdam (NFP)",
    "Unemployment Rate": "İşsizlik Oranı",
    "Average Hourly Earnings m/m": "Ortalama Saatlik Kazançlar (Aylık)",
    "Average Hourly Earnings MoM": "Ortalama Saatlik Kazançlar (Aylık)",
    "ADP Nonfarm Employment Change": "ADP Özel Sektör İstihdamı",
    "Initial Jobless Claims": "Haftalık İşsizlik Başvuruları",
    "Jobless Claims": "İşsizlik Başvuruları",
    "Continuing Jobless Claims": "Devam Eden İşsizlik Başvuruları",
    "JOLTS Job Openings": "JOLTS Açık İş Sayısı",
    "Employment Change": "İstihdam Değişimi",

    # Büyüme & PMI & Perakende
    "Prelim GDP q/q": "GSYH Büyüme Oranı (Öncü)",
    "Final GDP q/q": "GSYH Büyüme Oranı (Nihai)",
    "GDP QoQ": "GSYH Büyüme Oranı (Çeyreklik)",
    "GDP YoY": "GSYH Büyüme Oranı (Yıllık)",
    "Retail Sales m/m": "Perakende Satışlar (Aylık)",
    "Retail Sales MoM": "Perakende Satışlar (Aylık)",
    "Core Retail Sales m/m": "Çekirdek Perakende Satışlar",
    "Core Retail Sales MoM": "Çekirdek Perakende Satışlar",
    "ISM Manufacturing PMI": "ABD ISM İmalat PMI",
    "ISM Services PMI": "ABD ISM Hizmet PMI",
    "S&P Global Manufacturing PMI": "İmalat PMI",
    "S&P Global Services PMI": "Hizmet PMI",
    "Flash Manufacturing PMI": "Öncü İmalat PMI",
    "Flash Services PMI": "Öncü Hizmet PMI",
    "Michigan Consumer Sentiment": "Michigan Tüketici Güveni",
    "CB Consumer Confidence": "CB Tüketici Güveni",

    # Emtia ve Diğer
    "Crude Oil Inventories": "ABD Ham Petrol Stokları (EIA)",
    "EIA Crude Oil Stocks Change": "ABD Ham Petrol Stokları (EIA)",
    "Natural Gas Storage": "Doğalgaz Depolama Raporu",
    "OPEC Meetings": "OPEC Zirvesi",
    "Trade Balance": "Dış Ticaret Dengesi",
    "Balance of Trade": "Dış Ticaret Dengesi",
    "Current Account": "Cari Denge",
    "Industrial Production": "Sanayi Üretimi",
    "Industrial Production MoM": "Sanayi Üretimi (Aylık)",
    "Industrial Production YoY": "Sanayi Üretimi (Yıllık)",
    "Manufacturing Production MoM": "İmalat Üretimi (Aylık)",
    "Factory Orders MoM": "Fabrika Siparişleri (Aylık)",
    "Durable Goods Orders MoM": "Dayanıklı Tüketim Malları Siparişleri",
    "Consumer Confidence": "Tüketici Güveni",
    "Business Climate": "İş Dünyası Güven Endeksi (IFO)",
    "Building Permits": "İnşaat İzinleri",
    "Building Permits MoM": "İnşaat İzinleri (Aylık)",
    "Existing Home Sales": "İkinci El Konut Satışları",
    "New Home Sales": "Yeni Konut Satışları",
}

COUNTRY_MAP: Dict[str, Dict[str, str]] = {
    "US": {"code": "USD", "name": "ABD", "flag": "🇺🇸"},
    "USA": {"code": "USD", "name": "ABD", "flag": "🇺🇸"},
    "USD": {"code": "USD", "name": "ABD", "flag": "🇺🇸"},
    "EU": {"code": "EUR", "name": "Euro Bölgesi", "flag": "🇪🇺"},
    "EUR": {"code": "EUR", "name": "Euro Bölgesi", "flag": "🇪🇺"},
    "EMU": {"code": "EUR", "name": "Euro Bölgesi", "flag": "🇪🇺"},
    "DE": {"code": "EUR", "name": "Almanya", "flag": "🇩🇪"},
    "FR": {"code": "EUR", "name": "Fransa", "flag": "🇫🇷"},
    "GB": {"code": "GBP", "name": "İngiltere", "flag": "🇬🇧"},
    "UK": {"code": "GBP", "name": "İngiltere", "flag": "🇬🇧"},
    "GBP": {"code": "GBP", "name": "İngiltere", "flag": "🇬🇧"},
    "JP": {"code": "JPY", "name": "Japonya", "flag": "🇯🇵"},
    "JPN": {"code": "JPY", "name": "Japonya", "flag": "🇯🇵"},
    "JPY": {"code": "JPY", "name": "Japonya", "flag": "🇯🇵"},
    "CA": {"code": "CAD", "name": "Kanada", "flag": "🇨🇦"},
    "CAD": {"code": "CAD", "name": "Kanada", "flag": "🇨🇦"},
    "AU": {"code": "AUD", "name": "Avustralya", "flag": "🇦🇺"},
    "AUD": {"code": "AUD", "name": "Avustralya", "flag": "🇦🇺"},
    "CH": {"code": "CHF", "name": "İsviçre", "flag": "🇨🇭"},
    "CHF": {"code": "CHF", "name": "İsviçre", "flag": "🇨🇭"},
    "NZ": {"code": "NZD", "name": "Yeni Zelanda", "flag": "🇳🇿"},
    "NZD": {"code": "NZD", "name": "Yeni Zelanda", "flag": "🇳🇿"},
}

FALLBACK_EVENTS: List[Dict[str, Any]] = [
    {
        "id": "cal-fed-decision",
        "title": "Fed Faiz Kararı & FOMC Beyanatı",
        "original_title": "Federal Funds Rate & FOMC Statement",
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
        "affected_symbols": ["XAUUSD", "EURUSD", "BTCUSD", "USDJPY", "GBPUSD"],
        "scenario": {
            "title": "Fed Faiz & Para Politikası Senaryosu",
            "bullish_trigger": "Faiz Beklenti Üzeri Kalırsa veya Powell Şahin Konuşursa",
            "bullish_outcome": "Dolar Endeksi (DXY) güçlenir. Altın (XAUUSD), EURUSD ve BTCUSD sert geri çekilir.",
            "bearish_trigger": "Faiz İndirimi Gelirse veya Güvercin Mesajlar Verilirse",
            "bearish_outcome": "Dolar satılır. Altın (XAUUSD) ve EURUSD yukarı fırlar, BTCUSD güçlü prim yapar.",
            "scalper_tip": "Açıklanma dakikasında (21:00-21:05) yüksek spread oluşur; yön oturduktan sonra momentumla scalp yapın.",
            "summary_short": "Beklenti Üzeri: Dolar↑ / Altın↓ | Beklenti Altı: Altın↑ / Dolar↓",
        },
    },
    {
        "id": "cal-us-cpi",
        "title": "ABD TÜFE Enflasyon Verisi (Tüketici Fiyat Endeksi)",
        "original_title": "US CPI m/m & y/y",
        "country": "USD",
        "currency": "USD",
        "country_name": "ABD",
        "flag": "🇺🇸",
        "date_str": "Bugün 15:30",
        "date_iso": "2026-10-08T12:30:00Z",
        "impact": "High",
        "stars": 3,
        "stars_str": "⭐⭐⭐",
        "impact_label": "⭐⭐⭐ YÜKSEK (3 Yıldız)",
        "forecast": "0.2%",
        "previous": "0.3%",
        "actual": "—",
        "status": "Bekleniyor",
        "affected_symbols": ["XAUUSD", "EURUSD", "BTCUSD", "USDJPY"],
        "scenario": {
            "title": "ABD Enflasyon (TÜFE) Senaryosu",
            "bullish_trigger": "TÜFE Beklentiden Yüksek Gelirse (Sıcak Veri > 0.2%)",
            "bullish_outcome": "Faiz indirimi ötelenir, Dolar güçlenir. XAUUSD ve EURUSD düşüş trendine girer.",
            "bearish_trigger": "TÜFE Beklentiden Düşük Gelirse (Soğuyan Veri < 0.2%)",
            "bearish_outcome": "Enflasyonun soğuduğu teyit edilir, Dolar değer kaybeder. XAUUSD ve EURUSD roketler.",
            "scalper_tip": "Veri açıklandığı anda ters yöne limit emir asmayın; ilk 1 dakikalık fitilin yönüne göre scalp deneyin.",
            "summary_short": "Sıcak Veri (>): Dolar↑ / Altın↓ | Soğuk Veri (<): Altın↑ / Dolar↓",
        },
    },
    {
        "id": "cal-us-nfp",
        "title": "ABD Tarım Dışı İstihdam (NFP)",
        "original_title": "Non-Farm Employment Change",
        "country": "USD",
        "currency": "USD",
        "country_name": "ABD",
        "flag": "🇺🇸",
        "date_str": "Cuma 15:30",
        "date_iso": "2026-10-09T12:30:00Z",
        "impact": "High",
        "stars": 3,
        "stars_str": "⭐⭐⭐",
        "impact_label": "⭐⭐⭐ YÜKSEK (3 Yıldız)",
        "forecast": "145K",
        "previous": "142K",
        "actual": "—",
        "status": "Bekleniyor",
        "affected_symbols": ["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"],
        "scenario": {
            "title": "ABD İstihdam Senaryosu",
            "bullish_trigger": "İstihdam Beklenti Üzeri Çıkarsa (> 150K)",
            "bullish_outcome": "ABD ekonomisi güçlü algısıyla Dolar primlenir. EURUSD ve XAUUSD geri çekilir.",
            "bearish_trigger": "İstihdam Beklenti Altı Kalırsa (< 130K)",
            "bearish_outcome": "Resesyon kaygısı ve faiz indirimi fiyatlanır. Dolar satılır, Altın yukarı fırlar.",
            "scalper_tip": "Piyasanın en oynak 15 dakikasıdır. 30 saniye yönün oturmasını bekleyip kırılım yönünde girin.",
            "summary_short": "Güçlü İstihdam (>): Dolar↑ / Altın↓ | Zayıf İstihdam (<): Altın↑ / Dolar↓",
        },
    },
    {
        "id": "cal-ecb-rate",
        "title": "Avrupa Merkez Bankası (ECB) Faiz Kararı",
        "original_title": "ECB Main Refinancing Rate",
        "country": "EUR",
        "currency": "EUR",
        "country_name": "Euro Bölgesi",
        "flag": "🇪🇺",
        "date_str": "Perşembe 15:15",
        "date_iso": "2026-10-08T12:15:00Z",
        "impact": "High",
        "stars": 3,
        "stars_str": "⭐⭐⭐",
        "impact_label": "⭐⭐⭐ YÜKSEK (3 Yıldız)",
        "forecast": "3.50%",
        "previous": "3.65%",
        "actual": "—",
        "status": "Bekleniyor",
        "affected_symbols": ["EURUSD", "EURGBP", "EURJPY"],
        "scenario": {
            "title": "Avrupa Faiz & Para Politikası Senaryosu",
            "bullish_trigger": "Faiz Sabit Tutulur veya Lagarde Şahin Konuşursa",
            "bullish_outcome": "EURUSD ve EURGBP pariteleri 40-70 pip yukarı tepki verir.",
            "bearish_trigger": "Erken Faiz İndirimi ve Güvercin Mesajlar",
            "bearish_outcome": "Euro zayıflar, EURUSD paritesinde destek seviyeleri test edilir.",
            "scalper_tip": "Karar sonrası 15:45 Lagarde konuşmasında da volatilite devam eder, stopu sıkı tutun.",
            "summary_short": "Şahin Lagarde: EURUSD↑ / EURGBP↑ | Güvercin: EURUSD↓",
        },
    },
    {
        "id": "cal-oil-inventory",
        "title": "ABD Ham Petrol Stokları (EIA)",
        "original_title": "Crude Oil Inventories",
        "country": "USD",
        "currency": "USD",
        "country_name": "ABD",
        "flag": "🇺🇸",
        "date_str": "Çarşamba 17:30",
        "date_iso": "2026-10-07T14:30:00Z",
        "impact": "Medium",
        "stars": 2,
        "stars_str": "⭐⭐",
        "impact_label": "⭐⭐ ORTA (2 Yıldız)",
        "forecast": "-1.5M",
        "previous": "+3.8M",
        "actual": "-2.1M",
        "status": "Açıklandı",
        "affected_symbols": ["USOIL", "USDCAD"],
        "scenario": {
            "title": "Ham Petrol Arz-Stok Senaryosu",
            "bullish_trigger": "Stoklarda Beklenmedik Düşüş (Arz Daralması)",
            "bullish_outcome": "USOIL (Ham Petrol) yukarı sıçrar. USDCAD düşüş eğilimine girer.",
            "bearish_trigger": "Stoklarda Yüksek Artış (Talep Yetersizliği)",
            "bearish_outcome": "USOIL hızlı satış yer ve geri çekilir. USDCAD yukarı tepki verir.",
            "scalper_tip": "USOIL işlemlerinde stok verisi sonrası oluşan 5 dakikalık mum kırılımında pozisyon açın.",
            "summary_short": "Stok Azalması (-): USOIL↑ / USDCAD↓ | Stok Artışı (+): USOIL↓ / USDCAD↑",
        },
    },
    {
        "id": "cal-us-jobless-claims",
        "title": "ABD Haftalık İşsizlik Haklarından Yararlanma Başvuruları",
        "original_title": "Initial Jobless Claims",
        "country": "USD",
        "currency": "USD",
        "country_name": "ABD",
        "flag": "🇺🇸",
        "date_str": "Bugün 15:30",
        "date_iso": "2026-10-08T12:30:00Z",
        "impact": "Medium",
        "stars": 2,
        "stars_str": "⭐⭐",
        "impact_label": "⭐⭐ ORTA (2 Yıldız)",
        "forecast": "221K",
        "previous": "225K",
        "actual": "—",
        "status": "Bekleniyor",
        "affected_symbols": ["XAUUSD", "EURUSD", "USDJPY"],
        "scenario": {
            "title": "Haftalık İşsizlik Başvuruları Senaryosu",
            "bullish_trigger": "Başvuru Sayısı Düşük Gelirse (< 215K)",
            "bullish_outcome": "İstihdam piyasası sıkı algısıyla Dolar değer kazanır, Altın gevşer.",
            "bearish_trigger": "Başvuru Sayısı Yüksek Gelirse (> 230K)",
            "bearish_outcome": "İş gücünde zayıflama algısıyla Dolar gevşer, Altın ve EURUSD destek bulur.",
            "scalper_tip": "Veri anında kısa vadeli 15-25 pip scalping fırsatı sunar.",
            "summary_short": "Başvuru Azalırsa: Dolar↑ Altın↓ | Başvuru Artarsa: Altın↑ Dolar↓",
        },
    },
    {
        "id": "cal-boj-rate",
        "title": "Japonya Merkez Bankası (BoJ) Faiz Kararı & Ueda Konuşması",
        "original_title": "BOJ Policy Rate & Gov Ueda Speaks",
        "country": "JPY",
        "currency": "JPY",
        "country_name": "Japonya",
        "flag": "🇯🇵",
        "date_str": "Cuma 06:00",
        "date_iso": "2026-10-09T03:00:00Z",
        "impact": "High",
        "stars": 3,
        "stars_str": "⭐⭐⭐",
        "impact_label": "⭐⭐⭐ YÜKSEK (3 Yıldız)",
        "forecast": "0.25%",
        "previous": "0.25%",
        "actual": "—",
        "status": "Bekleniyor",
        "affected_symbols": ["USDJPY", "EURJPY", "GBPJPY"],
        "scenario": {
            "title": "Yen (JPY) Faiz & Carry Trade Senaryosu",
            "bullish_trigger": "BoJ Faiz Artırırsa veya Ueda Şahin Sinyal Verirse",
            "bullish_outcome": "Japon Yeni hızla güçlenir; USDJPY sert düşer (100-150 pip), EURJPY çöker.",
            "bearish_trigger": "Faiz Sabit ve Genişlemeci Güvercin Duruş Korunursa",
            "bearish_outcome": "USDJPY ve GBPJPY paritelerinde yeni zirve denemeleri başlar.",
            "scalper_tip": "USDJPY'de faiz kararlarında fitiller çok geniştir; stop-loss'u geniş tutun.",
            "summary_short": "Şahin BoJ: USDJPY Sert Düşer↓ | Güvercin BoJ: USDJPY Yükselir↑",
        },
    },
    {
        "id": "cal-uk-cpi",
        "title": "İngiltere TÜFE Enflasyon Verisi (Aylık & Yıllık)",
        "original_title": "UK CPI YoY",
        "country": "GBP",
        "currency": "GBP",
        "country_name": "İngiltere",
        "flag": "🇬🇧",
        "date_str": "Çarşamba 09:00",
        "date_iso": "2026-10-07T06:00:00Z",
        "impact": "High",
        "stars": 3,
        "stars_str": "⭐⭐⭐",
        "impact_label": "⭐⭐⭐ YÜKSEK (3 Yıldız)",
        "forecast": "2.2%",
        "previous": "2.2%",
        "actual": "—",
        "status": "Bekleniyor",
        "affected_symbols": ["GBPUSD", "EURGBP", "GBPJPY"],
        "scenario": {
            "title": "İngiltere Enflasyon & BoE Senaryosu",
            "bullish_trigger": "TÜFE Beklenti Üzeri Gelirse",
            "bullish_outcome": "BoE faiz indirimlerini erteler, GBPUSD yukarı ivmelenir, EURGBP geriler.",
            "bearish_trigger": "TÜFE Beklenti Altı Gelirse",
            "bearish_outcome": "BoE faiz indirimi beklentisi artar, GBPUSD satılır, EURGBP yükselir.",
            "scalper_tip": "GBPUSD paritesinde Londra açılışındaki ivme ile işlem yapın.",
            "summary_short": "Yüksek TÜFE: GBPUSD↑ / EURGBP↓ | Düşük TÜFE: GBPUSD↓ / EURGBP↑",
        },
    },
]

# Geriye dönük uyumluluk için alias
FALLBACK_NEWS = FALLBACK_EVENTS


def format_event_date(date_iso: str) -> str:
    """ISO zamanını kullanıcı dostu Türkiye saati (UTC+3) formatına çevirir."""
    try:
        dt = datetime.datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
        tr_tz = datetime.timezone(datetime.timedelta(hours=3))
        dt_tr = dt.astimezone(tr_tz)
        now_tr = datetime.datetime.now(tr_tz)

        diff_days = (dt_tr.date() - now_tr.date()).days
        time_str = dt_tr.strftime("%H:%M")

        months_tr = ["", "Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
        days_tr = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
        day_name = days_tr[dt_tr.weekday()]

        if diff_days == 0:
            return f"Bugün {time_str}"
        elif diff_days == 1:
            return f"Yarın {time_str}"
        elif diff_days == -1:
            return f"Dün {time_str}"
        else:
            return f"{dt_tr.day} {months_tr[dt_tr.month]} ({day_name}) {time_str}"
    except Exception:
        return date_iso[:16].replace("T", " ")


def map_symbols_for_event(currency: str, title: str) -> List[str]:
    """Para birimi ve olaya göre etkilenen Forex & Kripto sembollerini çıkarır."""
    t = title.lower()
    c = currency.upper()
    symbols: List[str] = []

    if c == "USD":
        symbols = ["XAUUSD", "EURUSD", "BTCUSD", "USDJPY", "GBPUSD"]
    elif c == "EUR":
        symbols = ["EURUSD", "EURGBP", "EURJPY"]
    elif c == "GBP":
        symbols = ["GBPUSD", "EURGBP", "GBPJPY"]
    elif c == "JPY":
        symbols = ["USDJPY", "EURJPY", "GBPJPY"]
    elif c == "CAD":
        symbols = ["USDCAD", "USOIL"]
    elif c == "AUD":
        symbols = ["AUDUSD", "XAUUSD"]
    elif c == "CHF":
        symbols = ["USDCHF", "EURCHF"]
    else:
        symbols = ["EURUSD", "XAUUSD"]

    if any(k in t for k in ["oil", "petrol", "crude", "energy", "enerji", "eia"]):
        if "USOIL" not in symbols:
            symbols.insert(0, "USOIL")

    if any(k in t for k in ["gold", "altın", "precious"]):
        if "XAUUSD" not in symbols:
            symbols.insert(0, "XAUUSD")

    return symbols[:5]


def translate_title(title: str, country_code: str) -> str:
    """Gösterge başlığını profesyonel Türkçe isimlendirmeye çevirir."""
    orig = title.strip()
    c_info = COUNTRY_MAP.get(country_code, {})
    c_name = c_info.get("name", country_code)

    tr_term = TRANSLATIONS.get(orig)
    if not tr_term:
        for en_k, tr_v in TRANSLATIONS.items():
            if en_k.lower() in orig.lower():
                tr_term = tr_v
                break

    if tr_term:
        if c_name and not any(k in tr_term for k in [c_name, "ABD", "Euro", "İngiltere", "Japonya", "Avustralya", "Kanada"]):
            return f"{c_name} {tr_term}"
        return tr_term

    return f"{c_name} {orig}" if c_name and not orig.startswith(c_name) else orig


# ============================================================================
# OLAY KOVASI (BUCKET) SINIFLANDIRMASI — TEK DOĞRULUK KAYNAĞI
# ============================================================================

# Kova adı -> anahtar kelime listesi. SIRA ANLAMLIDIR: "Fed ... Inflation" gibi
# başlıklar `rate` kovasına düşmelidir, `inflation` kovasına değil. Bu sözlük hem
# `generate_event_scenario` (gösterilecek senaryo metni) hem de
# `evaluate_event_outcome` (hangi dalın gerçekleştiği) tarafından kullanılır —
# böylece gösterilen metin ile seçilen dal ASLA çelişmez.
_EVENT_BUCKET_KEYWORDS: List[tuple] = [
    ("rate", ["rate", "faiz", "fomc", "fed", "monetary", "beyanat", "statement", "powell", "lagarde", "ueda"]),
    ("inflation", ["cpi", "tüfe", "inflation", "enflasyon", "pce", "ppi", "üfe"]),
    ("employment", ["employment", "nfp", "istihdam", "payrolls", "işsizlik", "claims", "adp"]),
    ("oil_stocks", ["oil", "petrol", "crude", "inventories", "stok"]),
    ("gdp", ["gdp", "gsyh", "büyüme"]),
    ("pmi", ["pmi", "ism", "imalat", "hizmet"]),
]

# İşsizlik/başvuru serileri AYNI istihdam kovasında ama AYNI yön kuralını paylaşmaz:
# istihdam artışı güçlü ekonomidir, işsizlik/başvuru artışı ise zayıflıktır.
_EMPLOYMENT_INVERTED_KEYWORDS = ["işsizlik", "unemployment", "claims", "jobless"]

# Petrol dışı "Business Inventories" gibi başlıklar stok kovasına girip yanlış
# yorumlanmasın diye ters çevirme YALNIZ gerçek petrol belirteci taşıyan olaylara
# uygulanır. "Inventories"/"stok" tek başına YETMEZ — petrol belirteci şarttır.
# (Mevcut `generate_event_scenario` `inventories`/`stok` anahtarını geniş tutuyor;
# bu daraltma YALNIZ yön kuralına uygulanır, gösterilen metne dokunulmaz.)
_OIL_STOCK_HINTS = ["crude", "oil", "petrol", "eia", "ham petrol"]


def classify_event_bucket(title: str) -> str:
    """Olay başlığını senaryo kovasına haritalar.

    Dönen değerler: `rate`, `inflation`, `employment`, `oil_stocks`, `gdp`,
    `pmi`, `generic`. `_EVENT_BUCKET_KEYWORDS` sırası korunur.
    """
    t = (title or "").lower()
    for bucket, keywords in _EVENT_BUCKET_KEYWORDS:
        if any(k in t for k in keywords):
            return bucket
    return "generic"


def higher_is_bullish_for_event(title: str) -> bool:
    """Açıklanan veri taban değerden YÜKSEK geldiğinde dalın 🟢 (bullish) olup olmadığını döner.

    Varsayılan kural: beklenti üstü veri = 🟢 (olayın `bullish_trigger`'ı). İki istisna
    ters çevrilir:

    * **İşsizlik / başvuru** (`işsizlik`, `unemployment`, `claims`, `jobless`): yüksek
      işsizlik zayıflıktır → 🔴.
    * **Ham petrol stokları** (`crude`/`oil`/`petrol`/`eia` + `inventories`/`stok`):
      stok artışı arz bolluğudur → 🔴.

    Enflasyon ailesi (TÜFE/ÜFE/PCE) **ters çevrilmez**: yüksek enflasyon şahin duruşu
    gerektirir ve olayın senaryosunda zaten `bullish_trigger` olarak yazılıdır.
    """
    t = (title or "").lower()
    if any(k in t for k in _EMPLOYMENT_INVERTED_KEYWORDS):
        return False
    if classify_event_bucket(t) == "oil_stocks" and any(k in t for k in _OIL_STOCK_HINTS):
        return False
    return True


def generate_event_scenario(title: str, country: str, currency: str, symbols: List[str]) -> Dict[str, str]:
    """Her ekonomik olay için 'Ne Olursa Ne Olur?' senaryosu üretir."""
    sym_str = ", ".join(symbols[:3])

    if classify_event_bucket(title) == "rate":
        return {
            "title": f"{currency} Faiz & Para Politikası Senaryosu",
            "bullish_trigger": "Faiz Beklenti Üzeri Kalırsa / Şahin Açıklama",
            "bullish_outcome": f"{currency} para birimi hızla primlenir. Karşıt pariteler ve Altın (XAUUSD) düşüşe geçer.",
            "bearish_trigger": "Faiz İndirimi Gelirse / Güvercin Açıklama",
            "bearish_outcome": f"{currency} değer kaybeder. {sym_str} üzerinde güçlü rahatlama yükselişi başlar.",
            "scalper_tip": "Açıklanma dakikasında spread 2-3 katına çıkabilir; fitil oluştuktan 30 saniye sonra kırılımla girin.",
            "summary_short": f"Şahin/Yüksek: {currency}↑ / Altın↓ | Güvercin/Düşük: Altın↑ / {currency}↓",
        }
    elif classify_event_bucket(title) == "inflation":
        return {
            "title": f"{currency} Enflasyon Verisi Senaryosu",
            "bullish_trigger": "Enflasyon Beklenti Üstü Çıkarsa (Sıcak Veri)",
            "bullish_outcome": f"Sıkılaşma/faiz koruma fiyatlanır. {currency} güçlenir, XAUUSD ve risk varlıkları baskılanır.",
            "bearish_trigger": "Enflasyon Beklenti Altı Kalırsa (Soğuma)",
            "bearish_outcome": f"Faiz indirim kapısı aralanır. {currency} değer kaybeder, Altın (XAUUSD) ve {sym_str} sert yükselir.",
            "scalper_tip": "Veri anında ters yöne emir yazmayın; ilk 1 dakikalık mum kapanış yönünde momentum scalping yapın.",
            "summary_short": f"Sıcak Veri (>): {currency}↑ / Altın↓ | Soğuk Veri (<): Altın↑ / {currency}↓",
        }
    elif classify_event_bucket(title) == "employment":
        return {
            "title": f"{currency} İstihdam & İş Gücü Senaryosu",
            "bullish_trigger": "İstihdam Beklenti Üstü / Düşük İşsizlik",
            "bullish_outcome": f"Ekonomi güçlü algısıyla {currency} alım görür. Karşıt pariteler geri çekilir.",
            "bearish_trigger": "İstihdam Beklenti Altı / Yüksek İşsizlik",
            "bearish_outcome": f"Ekonomik yavaşlama endişesiyle {currency} satılır; XAUUSD ve diğer varlıklar fırlar.",
            "scalper_tip": "İstihdam dalgası 10-15 dakika sürebilir; stop mesafesini normalin 1.5 katı tutun.",
            "summary_short": f"Güçlü İstihdam: {currency}↑ / Altın↓ | Zayıf İstihdam: Altın↑ / {currency}↓",
        }
    elif classify_event_bucket(title) == "oil_stocks":
        return {
            "title": "Ham Petrol Stok Senaryosu",
            "bullish_trigger": "Stoklarda Beklenmedik Düşüş (Arz Kısıtı)",
            "bullish_outcome": "USOIL (Ham Petrol) yukarı sıçrar. USDCAD düşüş eğilimine girer.",
            "bearish_trigger": "Stoklarda Beklenti Üstü Artış (Talep Yetersizliği)",
            "bearish_outcome": "USOIL sert satış yer. USDCAD yukarı tepki verir.",
            "scalper_tip": "Stok verisi açıklandıktan 30 saniye sonra trend yönüne stoplu katılın.",
            "summary_short": "Stok Düşüşü: USOIL↑ / USDCAD↓ | Stok Artışı: USOIL↓ / USDCAD↑",
        }
    elif classify_event_bucket(title) == "gdp":
        return {
            "title": f"{currency} Büyüme (GSYH) Senaryosu",
            "bullish_trigger": "GSYH Beklenti Üzeri Çıkarsa",
            "bullish_outcome": f"Büyüme ivmesiyle {currency} güçlenir, hisse endeksleri ve {sym_str} yön bulur.",
            "bearish_trigger": "GSYH Beklenti Altı Kalırsa",
            "bearish_outcome": f"Resesyon riskiyle {currency} baskılanır, güvenli limanlara kaçış hızlanır.",
            "scalper_tip": "Öncü veriler nihai verilerden daha yüksek oynaklık yaratır.",
            "summary_short": f"Güçlü GSYH: {currency}↑ | Zayıf GSYH: {currency}↓",
        }
    elif classify_event_bucket(title) == "pmi":
        return {
            "title": f"{currency} PMI Satın Alma Yöneticileri Senaryosu",
            "bullish_trigger": "PMI > 50 ve Beklenti Üzeri (Genişleme)",
            "bullish_outcome": f"Sektörel canlılık teyit edilir, {currency} alıcı bulur.",
            "bearish_trigger": "PMI < 50 veya Beklenti Altı (Daralma)",
            "bearish_outcome": f"Daralma endişesiyle {currency} geriler, savunmacı varlıklar prim yapar.",
            "scalper_tip": "PMI verilerinde ilk 5 dakikalık hareket genellikle trend oluşturur.",
            "summary_short": f"PMI > 50: {currency}↑ | PMI < 50: {currency}↓",
        }
    else:
        return {
            "title": f"{currency} Makro Gösterge Senaryosu",
            "bullish_trigger": "Açıklanan > Beklenti (Pozitif Sürpriz)",
            "bullish_outcome": f"{currency} varlıkları primlenir. {sym_str} üzerinde volatilite artar.",
            "bearish_trigger": "Açıklanan < Beklenti (Negatif Sürpriz)",
            "bearish_outcome": f"{currency} üzerinde kâr satışı gelir, karşıt pariteler destek bulur.",
            "scalper_tip": "Veri açıklandığında seans hacmini kontrol edin; düşük hacimde sahte kırılımlar olabilir.",
            "summary_short": f"Beklenti Üzeri: {currency}↑ | Beklenti Altı: {currency}↓",
        }


# ============================================================================
# AÇIKLANAN VERİ KIYASI — HANGİ SENARYO GERÇEKLEŞTİ?
# ============================================================================
#
# Takvim değerleri `_fmt_val` ile "0.2%", "145K", "-1.5M" gibi METİN olarak
# saklanıyor (kaynak TradingView sayı + `unit` gönderiyor). Aşağıdaki iki
# fonksiyon bu metinleri kıyaslanabilir sayıya çevirir ve `actual` ile taban
# değeri karşılaştırıp olayın hangi senaryo dalının gerçekleştiğini söyler.

# Ayrıştırılamayan / veri yok anlamına gelen metinler.
_MISSING_VALUE_TOKENS = {"", "—", "-", "–", "n/a", "na", "null", "none", "nan", "--"}

# Sondaki çarpan ekleri (TradingView 145K / -1.5M biçimini üretir).
_SUFFIX_MULTIPLIERS = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


def parse_calendar_value(value: Any) -> Optional[float]:
    """Takvim değerini kıyaslanabilir sayıya çevirir; çevrilemezse `None`.

    Örnekler: `"0.2%"` → 0.2, `"145K"` → 145000.0, `"-1.5M"` → -1500000.0,
    `"3.50%"` → 3.5. Yüzde işareti SADECE atılır, 100'e bölünmez — `actual` ile
    `forecast` aynı birimi taşıdığı için kıyas yine doğrudur.

    Ondalık virgül yalnız NOKTA yokken ayraç sayılır (`"2,2%"` → 2.2); nokta varsa
    virgüller binlik ayraçtır (`"1,234.5"` → 1234.5). Binlik ayraç olarak virgül
    kullanılan `"1,234"` de doğru okunur.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)

    raw = str(value).strip()
    if raw.lower() in _MISSING_VALUE_TOKENS:
        return None

    text = raw.replace("%", "").replace(" ", "").replace(" ", "")
    # Para birimi simgeleri ve harf kalıntıları (₺ $ € £ ¥) baştaki/sondaki.
    text = re.sub(r"^[^\d+\-.,]+", "", text)

    multiplier = 1.0
    if text and text[-1].lower() in _SUFFIX_MULTIPLIERS:
        multiplier = _SUFFIX_MULTIPLIERS[text[-1].lower()]
        text = text[:-1]

    # Kalan harfleri at (birim eki vb.); yalnız sayısal gövde kalsın.
    text = re.sub(r"[^\d+\-.,]", "", text)
    if not text:
        return None

    if "." in text:
        # Nokta ondalık ayraç: virgüller binlik ayraçtır.
        text = text.replace(",", "")
    elif "," in text:
        # Virgül var, nokta yok. "1,234" binlik, "2,2" ondalık olabilir.
        head, _, tail = text.rpartition(",")
        if len(tail) == 3 and head.lstrip("+-").isdigit():
            text = text.replace(",", "")  # "1,234" -> 1234
        else:
            text = text.replace(",", ".")  # "2,2" -> 2.2

    try:
        return float(text) * multiplier
    except (TypeError, ValueError):
        return None


def _format_comparison_value(raw: Any, parsed: float) -> str:
    """Kıyas metninde kullanılacak okunabilir sayı biçimi.

    Kaynak metin **kendi birimini zaten taşır** ("231K", "3.2%", "2.4M") ve
    kıyaslanan iki değer aynı kaynaktan geldiği için tutarlıdır. Bu yüzden ham
    metin olduğu gibi kullanılır.

    Sayısal biçime düşmek (`f"{parsed:g}"`) yalnız ham metin yoksa/anlamsızsa
    gerekir: bir kez `parse_calendar_value` içinde çarpılmış bir sayıyı
    `:g` ile basmak `2400000 -> 2.4e+06` gibi okunmaz çıktı üretir.
    """
    text = str(raw).strip() if raw is not None else ""
    return text or f"{parsed:g}"


def evaluate_event_outcome(
    title: str,
    forecast: Any,
    previous: Any,
    actual: Any,
) -> Optional[Dict[str, Any]]:
    """Açıklanan veriyi taban değerle kıyaslayıp gerçekleşen senaryo dalını bulur.

    Taban önceliği **forecast**, yoksa **previous**'dur. Canlı TradingView akışında
    olayların çoğunda `forecast` boş, `previous` doludur — bu yüzden previous tabanı
    istisna değil ana yoldur ve rozet metni tabana göre değişir.

    Dönen sözlük: `side` ("bullish"/"bearish"/None), `bucket`, `basis`,
    `actual_num`, `baseline_num`, `comparison_tr`, `label_tr`, `direction_note_tr`.
    `actual` yok/ayrıştırılamıyor ya da **her iki taban da** yok ise `None` döner
    (asla tahmin edilmez). Eşitlikte `side=None` — dal gizlenmez.

    `direction_note_tr` yalnız ters yorumlanan ailelerde doludur; orada sayısal
    ilişki ile piyasa yönü ayrıştığı için ("231K > 220K" ama 🔴) arayüzün bunu
    açıklayabilmesi gerekir.
    """
    actual_num = parse_calendar_value(actual)
    if actual_num is None:
        return None

    forecast_num = parse_calendar_value(forecast)
    previous_num = parse_calendar_value(previous)

    if forecast_num is not None:
        baseline_num, basis = forecast_num, "forecast"
    elif previous_num is not None:
        baseline_num, basis = previous_num, "previous"
    else:
        return None

    higher_is_bullish = higher_is_bullish_for_event(title)

    if abs(actual_num - baseline_num) < 1e-9:
        side: Optional[str] = None
        label_tr = "Beklentiye Uygun"
    else:
        is_higher = actual_num > baseline_num
        side = "bullish" if (is_higher == higher_is_bullish) else "bearish"
        if basis == "forecast":
            label_tr = "Beklenti Üzeri" if is_higher else "Beklenti Altı"
        else:
            label_tr = "Önceki'ye Göre Artış" if is_higher else "Önceki'ye Göre Azalış"

    # Kıyas metni HAM kaynak metinlerden kurulur — birim eki ("%", "K", "M")
    # böylece ayrıca çıkarılmak zorunda kalmaz. Ayrıştırma çarpanı uyguladığı
    # için (`145K` → 145000.0) sayıyı yeniden basmak "145000K" gibi çift birim
    # üretirdi.
    baseline_raw = forecast if basis == "forecast" else previous

    actual_text = _format_comparison_value(actual, actual_num)
    baseline_text = _format_comparison_value(baseline_raw, baseline_num)

    operator = "=" if side is None else (">" if actual_num > baseline_num else "<")
    comparison_tr = f"{actual_text} {operator} {baseline_text} ({label_tr})"

    # Ters yorumlanan ailelerde (işsizlik/başvuru, petrol stoğu) sayısal ilişki
    # ile piyasa yönü AYRIŞIR: "231K > 220K" ama sonuç 🔴. Rozetin yanında bu
    # çelişkiyi açıklamayan bir "Beklenti Üzeri" metni, bu özelliğin önlemek için
    # var olduğu yanlış okumayı bizzat üretir. `label_tr` kıyas satırının içinde
    # de geçtiği için oraya uzun bir ek koymak yerine AYRI alan döndürülür;
    # gösterip göstermemek görüntü katmanının kararıdır.
    direction_note_tr = None
    if side is not None and not higher_is_bullish:
        direction_note_tr = "Yüksek değer bu olayda ayı yönlüdür"

    return {
        "side": side,
        "bucket": classify_event_bucket(title),
        "basis": basis,
        "actual_num": actual_num,
        "baseline_num": baseline_num,
        "comparison_tr": comparison_tr,
        "label_tr": label_tr,
        "direction_note_tr": direction_note_tr,
    }


# ============================================================================
# TÜRKÇE GÖSTERGE AÇIKLAMALARI VE ÇEVİRİ MOTORU
# ============================================================================

INDICATOR_DESCRIPTIONS_TR: Dict[str, str] = {
    "trade balance": "Dış Ticaret Dengesi, bir ülkenin ihraç ettiği mal ve hizmetlerin toplam değeri ile ithal ettiği mal ve hizmetlerin toplam değeri arasındaki net farktır. Pozitif rakam (dış ticaret fazlası), ülkeye net döviz girişi olduğunu gösterir ve yerel para birimini güçlendirir. Negatif rakam (dış ticaret açığı) ise döviz çıkışını artırarak para birimi üzerinde değer kaybı baskısı yaratır.",
    "balance of trade": "Dış Ticaret Dengesi, bir ülkenin ihraç ettiği mal ve hizmetlerin toplam değeri ile ithal ettiği mal ve hizmetlerin toplam değeri arasındaki net farktır. Pozitif rakam (dış ticaret fazlası), ülkeye net döviz girişi olduğunu gösterir ve yerel para birimini güçlendirir. Negatif rakam (dış ticaret açığı) ise döviz çıkışını artırarak para birimi üzerinde değer kaybı baskısı yaratır.",
    "current account": "Cari İşlemler Dengesi, bir ülkenin mal, hizmet ve transferler dahil uluslararası net döviz hareketleridir. Fazla verilmesi para birimini doğrudan destekler.",
    "cpi": "Tüketici Fiyat Endeksi (TÜFE), tüketicilerin satın aldığı temel mal ve hizmet sepetindeki fiyat değişimlerini ölçer. Merkez bankalarının faiz kararlarında en kritik göstergedir. Beklenti üzeri gelen yüksek TÜFE, faizlerin yüksek tutulmasına yol açarak para birimini güçlendirir; Altın ve hisse senetlerinde satış baskısı yaratır.",
    "tüfe": "Tüketici Fiyat Endeksi (TÜFE), enflasyonun en temel göstergesidir. Yüksek TÜFE sıkı para politikasını ve faiz artırımlarını tetikler; Altın ve riskli varlıkları baskılar.",
    "ppi": "Üretici Fiyat Endeksi (ÜFE), üreticilerin yurt içinde ürettikleri malların fabrika çıkış fiyatlarındaki değişimi ölçer. Tüketici enflasyonunun (TÜFE) en önemli öncü göstergesidir.",
    "üfe": "Üretici Fiyat Endeksi (ÜFE), maliyet enflasyonunun tüketici fiyatlarına nasıl yansıyacağını gösteren öncü göstergedir.",
    "federal funds rate": "Federal Fonlama Faiz Oranı, ABD Merkez Bankası'nın (Fed) politika faizidir. Faizlerin yüksek tutulması Dolar Endeksini (DXY) güçlendirir, Altın ve karşıt pariteleri baskılar. Faiz indirimi ise Altın (XAUUSD) ve paritelerde ralli başlatır.",
    "fed": "Fed faiz kararları ve FOMC tutanakları küresel piyasalarda en yüksek oynaklığı yaratır. Şahin mesajlar Doları güçlendirir, Altın ve Kriptoyu geri çeker.",
    "fomc": "FOMC (Federal Açık Piyasa Komitesi) tutanakları, Fed üyelerinin faiz patikasına dair beklentilerini ortaya koyar. Beklenenden şahin tutanaklar Doları destekler.",
    "non-farm": "ABD Tarım Dışı İstihdam (NFP), tarım sektörü hariç çalışan toplam bordrolu istihdamdaki aylık net değişimi gösterir. Piyasa oynaklığı en yüksek veridir. Güçlü istihdam Doları primlendirir, zayıf istihdam Altını yukarı taşır.",
    "nfp": "ABD Tarım Dışı İstihdam (NFP), tarım sektörü hariç istihdamdaki değişimi gösterir. Güçlü istihdam Doları güçlendirir; zayıf istihdam resesyon kaygısıyla Altını yukarı fırlatır.",
    "jobless claims": "Haftalık İşsizlik Başvuruları, ilk defa işsizlik maaşı talebinde bulunan kişi sayısıdır. Düşük başvuru sayısı sıkı ve canlı bir istihdam piyasasını gösterir.",
    "unemployment": "İşsizlik Oranı, iş gücüne dahil olup iş arayan kişilerin toplam iş gücüne oranını ölçer. Düşük işsizlik ekonomik gücü ve sıkı para politikasını destekler.",
    "crude oil": "ABD Enerji Enformasyon İdaresi (EIA) ticari ham petrol stoklarındaki haftalık değişimi gösterir. Stoklardaki beklenmedik düşüş arz kısıtı algısıyla petrol (USOIL) fiyatlarını yukarı taşır; stok artışı ise fiyatları gevşetir.",
    "inventories": "Ticari ham petrol stokları, küresel enerji arz-talep dengesini yansıtır. Stoklardaki düşüş petrole alım getirir.",
    "pmi": "Satın Alma Yöneticileri Endeksi (PMI), imalat ve hizmet sektörlerindeki yönetici anketlerine dayanan öncü büyüme göstergesidir. 50 seviyesinin üzeri büyümeyi, altı daralmayı ifade eder.",
    "ism": "ABD ISM İmalat ve Hizmet Endeksleri, ABD ekonomisindeki aktiviteyi ölçen en saygın öncü göstergelerdendir. 50 üzeri değerler ekonomik genişlemeyi doğrular.",
    "gdp": "Gayri Safi Yurtiçi Hasıla (GSYH), bir ülkenin sınırları içinde üretilen tüm nihai mal ve hizmetlerin parasal değeridir. Ekonominin genel büyüme hızını gösterir.",
    "retail sales": "Perakende Satışlar, tüketici harcamalarının toplam hacmini ve hanehalkı talebinin gücünü ölçer. Ekonomik büyümenin en önemli itici gücüdür.",
    "building permits": "İnşaat İzinleri, gelecekteki konut inşaatı faaliyetlerinin öncü göstergesidir. İzinlerin artması konut sektörüne ve genel ekonomiye olan güveni gösterir.",
}

_TRANSLATION_CACHE: Dict[str, str] = {}

def translate_to_turkish(text: str) -> str:
    """İngilizce açıklamaları profesyonel Türkçe finansal metne çevirir."""
    if not text or not text.strip():
        return ""
    t_clean = text.strip()
    if t_clean in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[t_clean]

    tr_chars = sum(1 for c in t_clean if c in "şığüöçŞİĞÜÖÇ")
    if tr_chars >= 4:
        _TRANSLATION_CACHE[t_clean] = t_clean
        return t_clean

    try:
        url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=tr&dt=t&q=" + urllib.parse.quote(t_clean)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            res = json.loads(r.read().decode("utf-8"))
            tr_text = "".join(x[0] for x in res[0] if x[0])
            if tr_text and len(tr_text.strip()) > 5:
                result = tr_text.strip()
                _TRANSLATION_CACHE[t_clean] = result
                return result
    except Exception as exc:
        logger.debug("Çeviri servisi hatası: %s", exc)

    return ""


def get_turkish_comment(raw_comment: str, orig_title: str, tr_title: str) -> str:
    """Olay açıklaması için daima temiz ve profesyonel Türkçe metin döner."""
    t_key = f"{orig_title} {tr_title}".lower()

    # 1. Eğer raw_comment varsa, öncelikle Türkçeye çevir
    if raw_comment and len(raw_comment.strip()) > 10:
        translated = translate_to_turkish(raw_comment)
        if translated:
            tr_chars = sum(1 for c in translated if c in "şığüöçŞİĞÜÖÇ")
            # Çeviri başarılı ve Türkçe içeriyorsa dön
            if tr_chars >= 2 or any(k in translated.lower() for k in ["oran", "faiz", "ve", "ile", "dolar", "fiyat", "endeks"]):
                return translated

    # 2. Hazır zengin Türkçe gösterge açıklamasına bak
    for k, v in INDICATOR_DESCRIPTIONS_TR.items():
        if k in t_key:
            return v

    return f"{tr_title}, piyasa katılımcıları ve merkez bankaları tarafından yakından takip edilen önemli bir makroekonomik göstergedir."


# ============================================================================
# VERİ ÇEKİCİLER (PROVIDERS)
# ============================================================================

async def fetch_tradingview_events() -> List[Dict[str, Any]]:
    """TradingView Economic Calendar API'den 2 ve 3 yıldızlı olayları çeker."""
    def _fetch() -> Optional[str]:
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            # Dün ile önümüzdeki 7 gün arasındaki kritik veriler
            from_str = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000Z")
            to_str = (now + datetime.timedelta(days=7)).strftime("%Y-%m-%dT23:59:59.000Z")
            url = f"https://economic-calendar.tradingview.com/events?from={from_str}&to={to_str}&countries=US,EU,GB,JP,CA,AU,CH,DE,FR"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Origin": "https://www.tradingview.com",
                    "Accept": "application/json",
                }
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    return resp.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            logger.debug("TradingView calendar fetch error: %s", exc)
        return None

    loop = asyncio.get_running_loop()
    raw_json = await loop.run_in_executor(None, _fetch)
    if not raw_json:
        return []

    try:
        data = json.loads(raw_json)
        results = data.get("result", [])
    except Exception as exc:
        logger.debug("TradingView JSON parse error: %s", exc)
        return []

    parsed: List[Dict[str, Any]] = []
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    for item in results:
        # importance: 1 = Yüksek (3 Yıldız), 0 = Orta (2 Yıldız), -1 = Düşük (1 Yıldız)
        imp = item.get("importance")
        if imp not in [0, 1]:
            continue

        stars = 3 if imp == 1 else 2
        impact = "High" if stars == 3 else "Medium"
        orig_title = str(item.get("title") or item.get("indicator") or "").strip()
        country_code = str(item.get("country") or "").strip().upper()
        currency = str(item.get("currency") or "").strip().upper()

        c_info = COUNTRY_MAP.get(country_code) or COUNTRY_MAP.get(currency) or {
            "code": currency or country_code,
            "name": country_code,
            "flag": "🌐"
        }
        actual_currency = currency or c_info["code"]

        date_iso = str(item.get("date") or "")
        unit = str(item.get("unit") or "")

        def _fmt_val(v: Any) -> str:
            if v is None:
                return "—"
            return f"{v}{unit}" if unit else str(v)

        forecast = _fmt_val(item.get("forecast"))
        previous = _fmt_val(item.get("previous"))
        actual = _fmt_val(item.get("actual"))

        is_passed = False
        try:
            ev_dt = datetime.datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
            is_passed = ev_dt < now_utc
        except Exception:
            pass

        status = "Açıklandı" if actual != "—" else ("Geçti" if is_passed else "Bekleniyor")
        tr_title = translate_title(orig_title, country_code)
        affected_symbols = map_symbols_for_event(actual_currency, orig_title)
        scenario = generate_event_scenario(orig_title, c_info["name"], actual_currency, affected_symbols)

        parsed.append({
            "id": f"cal-tv-{item.get('id') or abs(hash(orig_title + date_iso)) % 1000000}",
            "title": tr_title,
            "original_title": orig_title,
            "country": actual_currency,
            "currency": actual_currency,
            "country_name": c_info["name"],
            "flag": c_info["flag"],
            "date_str": format_event_date(date_iso),
            "date_iso": date_iso,
            "impact": impact,
            "stars": stars,
            "stars_str": "⭐⭐⭐" if stars == 3 else "⭐⭐",
            "impact_label": "⭐⭐⭐ YÜKSEK (3 Yıldız)" if stars == 3 else "⭐⭐ ORTA (2 Yıldız)",
            "forecast": forecast,
            "previous": previous,
            "actual": actual,
            "status": status,
            "comment": get_turkish_comment(str(item.get("comment") or ""), orig_title, tr_title),
            "affected_symbols": affected_symbols,
            "scenario": scenario,
            "is_passed": is_passed,
        })

    return parsed


async def fetch_investing_com_events() -> List[Dict[str, Any]]:
    """Investing.com HTML / JSON verisinden 2 ve 3 yıldızlı olayları çeker."""
    def _fetch() -> Optional[str]:
        try:
            from curl_cffi import requests
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            }
            # tr.investing.com veya www.investing.com
            for target_url in ["https://tr.investing.com/economic-calendar/", "https://www.investing.com/economic-calendar"]:
                try:
                    r = requests.get(target_url, headers=headers, impersonate="chrome120", timeout=7)
                    if r.status_code == 200 and "economicCalendarStore" in r.text:
                        return r.text
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Investing.com fetch exception: %s", exc)
        return None

    loop = asyncio.get_running_loop()
    html_text = await loop.run_in_executor(None, _fetch)
    if not html_text:
        return []

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_text, "html.parser")
        script_tag = None
        for s in soup.find_all("script"):
            if s.string and "economicCalendarStore" in s.string:
                script_tag = s
                break

        if not script_tag:
            return []

        data = json.loads(script_tag.string)
        store = data.get("props", {}).get("pageProps", {}).get("state", {}).get("economicCalendarStore", {})
        events_by_date = store.get("calendarEventsByDate", {})

        parsed: List[Dict[str, Any]] = []
        for _, ev_list in events_by_date.items():
            for ev in ev_list:
                imp = str(ev.get("importance", "")).strip()
                if imp not in ["2", "3"]:
                    continue

                stars = int(imp)
                orig_title = str(ev.get("event") or ev.get("eventLong") or "").strip()
                currency = str(ev.get("currency") or "").strip().upper()
                country = str(ev.get("country") or "").strip()
                time_iso = str(ev.get("time") or ev.get("date") or "")

                c_info = COUNTRY_MAP.get(currency) or {"code": currency or "USD", "name": country or currency, "flag": "🌐"}
                affected_symbols = map_symbols_for_event(currency, orig_title)
                scenario = generate_event_scenario(orig_title, c_info["name"], currency or "USD", affected_symbols)

                actual = str(ev.get("actual") or "—")
                forecast = str(ev.get("forecast") or "—")
                previous = str(ev.get("previous") or "—")

                parsed.append({
                    "id": f"cal-inv-{ev.get('eventId') or abs(hash(orig_title + time_iso)) % 1000000}",
                    "title": orig_title,
                    "original_title": orig_title,
                    "country": currency or "USD",
                    "currency": currency or "USD",
                    "country_name": c_info["name"],
                    "flag": c_info["flag"],
                    "date_str": format_event_date(time_iso) if time_iso else "Bugün",
                    "date_iso": time_iso,
                    "impact": "High" if stars == 3 else "Medium",
                    "stars": stars,
                    "stars_str": "⭐⭐⭐" if stars == 3 else "⭐⭐",
                    "impact_label": "⭐⭐⭐ YÜKSEK (3 Yıldız)" if stars == 3 else "⭐⭐ ORTA (2 Yıldız)",
                    "forecast": forecast,
                    "previous": previous,
                    "actual": actual,
                    "status": "Açıklandı" if actual != "—" else "Bekleniyor",
                    "comment": get_turkish_comment(str(ev.get("comment") or ""), orig_title, orig_title),
                    "affected_symbols": affected_symbols,
                    "scenario": scenario,
                })

        return parsed
    except Exception as exc:
        logger.debug("Investing.com parse error: %s", exc)
        return []


async def fetch_forexfactory_events() -> List[Dict[str, Any]]:
    """ForexFactory JSON akışından High ve Medium olayları çeker."""
    def _fetch() -> Optional[str]:
        try:
            req = urllib.request.Request(
                "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    return resp.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            logger.debug("ForexFactory fetch error: %s", exc)
        return None

    loop = asyncio.get_running_loop()
    raw_json = await loop.run_in_executor(None, _fetch)
    if not raw_json:
        return []

    try:
        events = json.loads(raw_json)
        parsed: List[Dict[str, Any]] = []
        for ev in events:
            impact = str(ev.get("impact", "")).capitalize()
            if impact not in ["High", "Medium"]:
                continue

            stars = 3 if impact == "High" else 2
            orig_title = str(ev.get("title", "")).strip()
            country = str(ev.get("country", "")).strip().upper()
            date_iso = str(ev.get("date", "")).strip()

            c_info = COUNTRY_MAP.get(country, {"code": country, "name": country, "flag": "🌐"})
            tr_title = translate_title(orig_title, country)
            affected_symbols = map_symbols_for_event(country, orig_title)
            scenario = generate_event_scenario(orig_title, c_info["name"], country, affected_symbols)

            parsed.append({
                "id": f"cal-ff-{abs(hash(orig_title + date_iso)) % 1000000}",
                "title": tr_title,
                "original_title": orig_title,
                "country": country,
                "currency": country,
                "country_name": c_info["name"],
                "flag": c_info["flag"],
                "date_str": format_event_date(date_iso),
                "date_iso": date_iso,
                "impact": impact,
                "stars": stars,
                "stars_str": "⭐⭐⭐" if stars == 3 else "⭐⭐",
                "impact_label": "⭐⭐⭐ YÜKSEK (3 Yıldız)" if stars == 3 else "⭐⭐ ORTA (2 Yıldız)",
                "forecast": ev.get("forecast") or "—",
                "previous": ev.get("previous") or "—",
                "actual": "—",
                "status": "Bekleniyor",
                "comment": get_turkish_comment("", orig_title, tr_title),
                "affected_symbols": affected_symbols,
                "scenario": scenario,
            })
        return parsed
    except Exception as exc:
        logger.debug("ForexFactory parse error: %s", exc)
        return []


def _load_disk_cache() -> List[Dict[str, Any]]:
    """Disk önbelleğinden takvim verisini okur."""
    try:
        if os.path.exists(CACHE_FILE_PATH):
            with open(CACHE_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
    except Exception as exc:
        logger.debug("Disk cache okuma hatası: %s", exc)
    return []


def _save_disk_cache(items: List[Dict[str, Any]]) -> None:
    """Başarıyla çekilen takvim verilerini diske yazar."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE_PATH), exist_ok=True)
        with open(CACHE_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.debug("Disk cache yazma hatası: %s", exc)


# ============================================================================
# DİNAMİK ALAN VE SAYIM HESAPLAYICI
# ============================================================================

def _update_event_dynamic_fields(items: List[Dict[str, Any]]) -> None:
    """Olayların dakikasını, 5 dakika uyarısını, durumunu ve veri sonucunu günceller.

    Bu fonksiyon **her okuma yolunda** (bellek önbelleği, veritabanı, disk önbelleği,
    yedek olaylar) çağrılır; bu yüzden `outcome`/`has_data` alanları da burada
    hesaplanır — veritabanına yeni sütun eklemeye gerek kalmaz, eski satırlar ilk
    okumada bu alanları kazanır.
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    for ev in items:
        # `outcome`/`has_data` VERİ türevlidir, ZAMAN türevli değil: `if date_iso:`
        # bloğunun DIŞINDA hesaplanmalıdır, aksi halde `date_iso`'su olmayan
        # önbellek satırları hiç sonuç alamaz.
        has_forecast = bool(str(ev.get("forecast") or "").strip()) and ev.get("forecast") != "—"
        has_previous = bool(str(ev.get("previous") or "").strip()) and ev.get("previous") != "—"
        has_actual = bool(str(ev.get("actual") or "").strip()) and ev.get("actual") != "—"
        ev["has_data"] = bool(has_forecast or has_previous)
        ev["outcome"] = (
            evaluate_event_outcome(
                str(ev.get("original_title") or ev.get("title") or ""),
                ev.get("forecast"),
                ev.get("previous"),
                ev.get("actual"),
            )
            if has_actual
            else None
        )

        date_iso = ev.get("date_iso")
        if date_iso:
            try:
                ev_dt = datetime.datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
                diff_sec = (ev_dt - now_utc).total_seconds()
                mins = round(diff_sec / 60, 1)
                ev["minutes_until"] = mins
                ev["is_within_5m"] = bool(0 <= mins <= 5.5)
                ev["is_passed"] = bool(diff_sec < 0)
                if has_actual:
                    ev["status"] = "Açıklandı"
                elif ev["is_passed"]:
                    ev["status"] = "Geçti"
                elif ev["is_within_5m"]:
                    ev["status"] = "⏰ 5 Dk İçinde!"
            except Exception:
                pass


# ============================================================================
# ARKA PLAN SENKRONİZASYONU VE VERİTABANI YAZIMI (INVESTING.COM 2 & 3 YILDIZ)
# ============================================================================

async def sync_economic_calendar_to_db(min_stars: int = 2) -> List[Dict[str, Any]]:
    """Investing.com, TradingView ve ForexFactory üzerinden verileri çeker ve veritabanına yazar.
    
    Kullanıcı arayüzünü bekletmez; arka planda periyodik (3 saatte bir) veya ilk kurulumda çalışır.
    """
    now = time.time()
    items: List[Dict[str, Any]] = []

    # 1. TradingView API'den çekmeyi dene (Hızlı, engelsiz, 2 ve 3 yıldız filtreli)
    try:
        tv_items = await fetch_tradingview_events()
        if tv_items:
            items.extend(tv_items)
            logger.info("[EconomicCalendar] TradingView takviminden %d adet 2/3 yıldızlı olay çekildi.", len(tv_items))
    except Exception as exc:
        logger.warning("[EconomicCalendar] TradingView takvim çekme hatası: %s", exc)

    # 2. Eğer az geldiyse Investing.com'u dene
    if len(items) < 10:
        try:
            inv_items = await fetch_investing_com_events()
            if inv_items:
                for inv in inv_items:
                    if not any(x.get("original_title") == inv.get("original_title") for x in items):
                        items.append(inv)
                logger.info("[EconomicCalendar] Investing.com'dan ek olaylar eklendi. Toplam: %d", len(items))
        except Exception as exc:
            logger.debug("[EconomicCalendar] Investing.com ekleme hatası: %s", exc)

    # 3. Hala az geldiyse ForexFactory akışını dene
    if len(items) < 6:
        try:
            ff_items = await fetch_forexfactory_events()
            for ff in ff_items:
                if not any(x.get("title") == ff.get("title") for x in items):
                    items.append(ff)
        except Exception as exc:
            logger.debug("[EconomicCalendar] ForexFactory ekleme hatası: %s", exc)

    # 4. İnternet kesikse disk önbelleğine bak
    if len(items) < 4:
        disk_items = _load_disk_cache()
        if disk_items:
            items = disk_items
            logger.info("[EconomicCalendar] Disk önbelleğinden %d adet takvim olayı yüklendi.", len(items))

    # 5. Kritik olaylar eksikse FALLBACK_EVENTS ile harmanla
    if len(items) < 6:
        for fb in FALLBACK_EVENTS:
            if not any(x.get("title") == fb.get("title") or x.get("original_title") == fb.get("original_title") for x in items):
                items.append(fb)

    # Yalnızca 2 ve 3 Yıldızlı Olayları filtrele
    filtered_items = [
        x for x in items 
        if x.get("stars", 0) >= min_stars or x.get("impact") in ["High", "Medium"]
    ]

    def sort_key(ev: Dict[str, Any]) -> tuple:
        passed = 1 if ev.get("is_passed", False) or ev.get("status") == "Açıklandı" else 0
        stars_priority = 0 if ev.get("stars") == 3 or ev.get("impact") == "High" else 1
        date_sort = ev.get("date_iso") or "9999-99-99"
        return (passed, stars_priority, date_sort)

    filtered_items.sort(key=sort_key)
    final_items = filtered_items[:30]

    # Bellek ve disk önbelleğini güncelle
    _CALENDAR_CACHE["timestamp"] = now
    _CALENDAR_CACHE["items"] = final_items
    if len(final_items) >= 4:
        _save_disk_cache(final_items)

    # Veritabanına kaydet
    if database and final_items:
        try:
            saved_cnt = await database.save_economic_calendar_events(final_items)
            logger.info("[EconomicCalendar] %d adet takvim olayı veritabanına başarıyla kaydedildi.", saved_cnt)
        except Exception as exc:
            logger.warning("[EconomicCalendar] Veritabanına kaydetme hatası: %s", exc)

    _update_event_dynamic_fields(final_items)
    return final_items


# ============================================================================
# HIZLI OKUMA VE SUNUM (VERİTABANI / BELLEK ÖNCELİKLİ - SIFIR BEKLEME)
# ============================================================================

async def get_forex_news(force_refresh: bool = False, min_stars: int = 2) -> List[Dict[str, Any]]:
    """Investing.com 2 ve 3 Yıldızlı Olayları veritabanından / bellekten anında döner.
    
    Sayfa açılışlarında harici sitelere istek atarak kullanıcıyı bekletmez.
    Tüm veriler önceden veritabanına yazılmıştır; doğrudan veritabanından okunur.
    """
    now = time.time()

    # Kullanıcı elle "Yenile" butonuna bastıysa arka plan senkronunu hemen tetikle
    if force_refresh:
        return await sync_economic_calendar_to_db(min_stars=min_stars)

    # 1. Bellek Önbelleği (RAM) Kontrolü
    if _CALENDAR_CACHE["items"] and (now - _CALENDAR_CACHE["timestamp"]) < _CACHE_TTL_SEC:
        items = _CALENDAR_CACHE["items"]
        _update_event_dynamic_fields(items)
        return items

    # 2. Veritabanı Kontrolü (Hızlı SQL Okuması)
    db_items: List[Dict[str, Any]] = []
    if database:
        try:
            db_items = await database.get_economic_calendar_events(min_stars=min_stars)
        except Exception as exc:
            logger.debug("[EconomicCalendar] Veritabanından okuma hatası: %s", exc)

    if db_items and len(db_items) > 0:
        _CALENDAR_CACHE["timestamp"] = now
        _CALENDAR_CACHE["items"] = db_items
        _update_event_dynamic_fields(db_items)
        return db_items

    # 3. Veritabanı boşsa (ilk kurulum anı): Disk önbelleğine bak
    disk_items = _load_disk_cache()
    if disk_items and len(disk_items) > 0:
        _CALENDAR_CACHE["timestamp"] = now
        _CALENDAR_CACHE["items"] = disk_items
        _update_event_dynamic_fields(disk_items)
        # Arka planda DB'yi doldurması için görevi asenkron başlat (kullanıcıyı bekletme)
        asyncio.create_task(sync_economic_calendar_to_db(min_stars=min_stars))
        return disk_items

    # 4. Tamamen boşsa hazır yedek olayları hemen sun ve arka planda DB'yi doldur
    fallback = [x for x in FALLBACK_EVENTS if x.get("stars", 0) >= min_stars or x.get("impact") in ["High", "Medium"]]
    _CALENDAR_CACHE["timestamp"] = now
    _CALENDAR_CACHE["items"] = fallback
    _update_event_dynamic_fields(fallback)
    asyncio.create_task(sync_economic_calendar_to_db(min_stars=min_stars))
    return fallback


# ============================================================================
# 3 SAATLİK ARKA PLAN DÖNGÜSÜ (GÜNDE BİR VE GÜN İÇİNDE 3 SAATTE BİR)
# ============================================================================

async def economic_calendar_background_loop():
    """Investing.com 2 & 3 yıldızlı takvim verilerini 3 saatte bir arka planda kontrol eder ve DB'ye yazar."""
    logger.info("[EconomicCalendar] 3 saatlik arka plan senkronizasyon servisi devrede.")

    # 1. Başlangıçta: Veri hiç çekilmemişse veya 3 saatten eskiyse arka planda hemen çek
    try:
        last_sync = 0.0
        if database:
            last_sync = await database.get_last_economic_calendar_sync()
        now = time.time()

        if (now - last_sync) >= CALENDAR_REFRESH_INTERVAL_SEC or last_sync == 0:
            logger.info("[EconomicCalendar] İlk açılışta takvim verisi eski veya boş (Son senkron: %.0f sn önce). Arka planda çekiliyor...", now - last_sync if last_sync else 0)
            await sync_economic_calendar_to_db()
        else:
            # DB'de geçerli taze veri var; belleğe aktar
            if database:
                db_items = await database.get_economic_calendar_events()
                if db_items:
                    _CALENDAR_CACHE["items"] = db_items
                    _CALENDAR_CACHE["timestamp"] = now
                    logger.info("[EconomicCalendar] Veritabanından %d olay belleğe yüklendi (Son senkron: %.1f saat önce).", len(db_items), (now - last_sync) / 3600)
    except Exception as exc:
        logger.warning("[EconomicCalendar] Başlangıç senkronizasyon kontrol hatası: %s", exc)

    # 2. Periyodik Kontrol Döngüsü: Her 60 saniyede bir kontrol et, 3 saatlik süre dolduğunda arka planda çek
    while True:
        try:
            await asyncio.sleep(60)
            now = time.time()
            last_sync = 0.0
            if database:
                last_sync = await database.get_last_economic_calendar_sync()

            if (now - last_sync) >= CALENDAR_REFRESH_INTERVAL_SEC:
                logger.info("[EconomicCalendar] 3 saatlik periyot doldu, arka planda ekonomik takvim güncelleniyor...")
                await sync_economic_calendar_to_db()
        except asyncio.CancelledError:
            logger.info("[EconomicCalendar] Arka plan servisi durduruldu.")
            break
        except Exception as exc:
            logger.error("[EconomicCalendar] Arka plan döngüsünde beklenmeyen hata: %s", exc)
            await asyncio.sleep(180)

