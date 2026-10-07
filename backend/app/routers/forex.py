"""Forex & Commodities Market Engine Router.

Provides:
- Major/Minor FX pairs and Commodities metadata
- Global market session states (Sydney, Tokyo, London, New York)
- Live ticker data, spreads, bid/ask prices
- Forex technical radar signals (RSI, MACD, Trend conviction)
- Lot size, Pip value, and Margin requirement calculators
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import csv
import datetime
import io
import json
import logging
import math
import os
import random
import tempfile
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

try:
    from app.forex_correlation import FXCorrelationMonitor
except ImportError:  # paket dışı bağlam (test/script)
    from ..forex_correlation import FXCorrelationMonitor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/forex", tags=["forex"])

# Standard Forex & Commodities Universe
FOREX_SYMBOLS = [
    # Majors
    {
        "symbol": "EURUSD",
        "display": "EUR/USD",
        "name": "Euro / US Dollar",
        "category": "major",
        "base": "EUR",
        "quote": "USD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:EURUSD",
        "default_price": 1.08542,
    },
    {
        "symbol": "GBPUSD",
        "display": "GBP/USD",
        "name": "British Pound / US Dollar",
        "category": "major",
        "base": "GBP",
        "quote": "USD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:GBPUSD",
        "default_price": 1.29650,
    },
    {
        "symbol": "USDJPY",
        "display": "USD/JPY",
        "name": "US Dollar / Japanese Yen",
        "category": "major",
        "base": "USD",
        "quote": "JPY",
        "pip_size": 0.01,
        "digits": 3,
        "tv_symbol": "FX:USDJPY",
        "default_price": 152.450,
    },
    {
        "symbol": "USDCHF",
        "display": "USD/CHF",
        "name": "US Dollar / Swiss Franc",
        "category": "major",
        "base": "USD",
        "quote": "CHF",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:USDCHF",
        "default_price": 0.88420,
    },
    {
        "symbol": "AUDUSD",
        "display": "AUD/USD",
        "name": "Australian Dollar / US Dollar",
        "category": "major",
        "base": "AUD",
        "quote": "USD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:AUDUSD",
        "default_price": 0.65820,
    },
    {
        "symbol": "USDCAD",
        "display": "USD/CAD",
        "name": "US Dollar / Canadian Dollar",
        "category": "major",
        "base": "USD",
        "quote": "CAD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:USDCAD",
        "default_price": 1.38950,
    },
    {
        "symbol": "NZDUSD",
        "display": "NZD/USD",
        "name": "New Zealand Dollar / US Dollar",
        "category": "major",
        "base": "NZD",
        "quote": "USD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:NZDUSD",
        "default_price": 0.59750,
    },
    # JPY krosçarları (2026-10-07 giriş-kalibrasyonu: GBPJPY/EURJPY donchian_adx moduyla canlıya alındı)
    {
        "symbol": "GBPJPY",
        "display": "GBP/JPY",
        "name": "British Pound / Japanese Yen",
        "category": "cross",
        "base": "GBP",
        "quote": "JPY",
        "pip_size": 0.01,
        "digits": 3,
        "tv_symbol": "FX:GBPJPY",
        "default_price": 199.850,
    },
    {
        "symbol": "EURJPY",
        "display": "EUR/JPY",
        "name": "Euro / Japanese Yen",
        "category": "cross",
        "base": "EUR",
        "quote": "JPY",
        "pip_size": 0.01,
        "digits": 3,
        "tv_symbol": "FX:EURJPY",
        "default_price": 168.420,
    },
    # Commodities / Precious Metals
    {
        "symbol": "XAUUSD",
        "display": "XAU/USD",
        "name": "Gold / US Dollar",
        "category": "commodity",
        "base": "XAU",
        "quote": "USD",
        "pip_size": 0.1,
        "digits": 2,
        "tv_symbol": "OANDA:XAUUSD",
        "default_price": 2735.60,
    },
    # Indices
    {
        "symbol": "NAS100",
        "display": "Nasdaq 100",
        "name": "US Tech 100 Index",
        "category": "index",
        "base": "NDX",
        "quote": "USD",
        "pip_size": 1.0,
        "digits": 2,
        "tv_symbol": "FOREXCOM:NSXUSD",
        "default_price": 20420.50,
    },
    {
        "symbol": "US30",
        "display": "Dow Jones 30",
        "name": "Wall Street 30 / Dow Jones",
        "category": "index",
        "base": "DJI",
        "quote": "USD",
        "pip_size": 1.0,
        "digits": 2,
        "tv_symbol": "FOREXCOM:DJI",
        "default_price": 43500.0,
    },
    # Crypto
    {
        "symbol": "BTCUSD",
        "display": "BTC/USD",
        "name": "Bitcoin / US Dollar",
        "category": "crypto",
        "base": "BTC",
        "quote": "USD",
        "pip_size": 1.0,
        "digits": 2,
        "tv_symbol": "BINANCE:BTCUSDT",
        "default_price": 66500.0,
    },
]

# 2026-10-07 kullanıcı kararı: ETH/USD, WTI Oil (USOIL) ve S&P 500 (SPX500)
# forex evreninden ÇIKARILDI — radar, grafikler, teknik grafikler ve raporlar
# sembol listesinde artık görünmez, veri hattı bunları çekmez.
# SPX500 gerekçesi: `get_symbol_trading_specs` içinde endeks dalı olmadığı için
# forex varsayılanına (pip_size 0.0001) düşüyordu ve SL girişin binde bir puan
# uzağına kurulup açılış saniyesinde patlıyordu. Sembolü spec dalı ekleyerek
# kurtarmak yerine kullanıcı evrenden tamamen çıkarmayı seçti (2026-10-07).
# Spec kayıtları SİLİNMEDİ, buraya taşındı: geçmiş işlemlerin PnL/pip
# gösterimi ve açık pozisyonların kapanışı bozulmasın. Bu liste HİÇBİR tarama
# döngüsünde okunmaz (yalnızca kayıt/geri dönüş amaçlı); mevcut kayıtlara
# dokunulmadı — açık pozisyon varsa normal SL/TP kurallarıyla kendiliğinden
# kapanır. Geri almak için ilgili blok `FOREX_SYMBOLS` içine geri taşınır.
_RETIRED_FOREX_SYMBOLS = [
    # XAGUSD 2026-10-07'de kullanıcı kararıyla emekliye ayrıldı (radar/panel temizliği);
    # spec ve arşiv uyumluluğu yukarıdaki gibi korunur.
    {
        "symbol": "XAGUSD",
        "display": "XAG/USD",
        "name": "Silver / US Dollar",
        "category": "commodity",
        "base": "XAG",
        "quote": "USD",
        "pip_size": 0.01,
        "digits": 3,
        "tv_symbol": "OANDA:XAGUSD",
        "default_price": 33.850,
    },
    {
        "symbol": "USOIL",
        "display": "WTI Oil",
        "name": "Crude Oil (WTI)",
        "category": "commodity",
        "base": "OIL",
        "quote": "USD",
        "pip_size": 0.01,
        "digits": 2,
        "tv_symbol": "TVC:USOIL",
        "default_price": 71.40,
    },
    {
        "symbol": "ETHUSD",
        "display": "ETH/USD",
        "name": "Ethereum / US Dollar",
        "category": "crypto",
        "base": "ETH",
        "quote": "USD",
        "pip_size": 1.0,
        "digits": 2,
        "tv_symbol": "BINANCE:ETHUSDT",
        "default_price": 2700.0,
    },
    {
        "symbol": "SPX500",
        "display": "S&P 500",
        "name": "S&P 500 Index",
        "category": "index",
        "base": "SPX",
        "quote": "USD",
        "pip_size": 0.1,
        "digits": 2,
        "tv_symbol": "FOREXCOM:SPXUSD",
        "default_price": 5830.20,
    },
]

# In-memory realistic price and tick cache
_TICK_CACHE: Dict[str, Dict[str, Any]] = {}
_LAST_CACHE_TIME = 0.0


def _get_market_sessions() -> List[Dict[str, Any]]:
    """Determine which global forex trading sessions are currently active (UTC)."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    current_hour = now_utc.hour + now_utc.minute / 60.0
    weekday = now_utc.weekday()  # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday

    # Forex weekend market close check (Friday 21:00 UTC to Sunday 21:00 UTC)
    is_weekend = (weekday == 4 and current_hour >= 21) or (weekday == 5) or (weekday == 6 and current_hour < 21)

    sessions_def = [
        {"name": "Sydney", "flag": "🇦🇺", "open_utc": 21, "close_utc": 6, "city": "Sydney"},
        {"name": "Tokyo", "flag": "🇯🇵", "open_utc": 0, "close_utc": 9, "city": "Tokyo"},
        {"name": "London", "flag": "🇬🇧", "open_utc": 7, "close_utc": 16, "city": "London"},
        {"name": "New York", "flag": "🇺🇸", "open_utc": 12, "close_utc": 21, "city": "New York"},
    ]

    result = []
    for s in sessions_def:
        open_h = s["open_utc"]
        close_h = s["close_utc"]
        if open_h < close_h:
            is_active = open_h <= current_hour < close_h
        else:
            is_active = current_hour >= open_h or current_hour < close_h

        if is_weekend:
            is_active = False

        result.append({
            "name": s["name"],
            "flag": s["flag"],
            "city": s["city"],
            "active": is_active,
            "hours_utc": f"{s['open_utc']:02d}:00 - {s['close_utc']:02d}:00 UTC",
        })

    return result


_LAST_LIVE_FETCH_TIME = 0.0
_LIVE_PRICES_CACHE: Dict[str, float] = {}

# Hard Risk Constants (Broker safety ceilings)
HARD_MAX_FOREX_LOT = 50.0
HARD_MAX_GOLD_LOT = 50.0
HARD_MIN_GOLD_COOLDOWN_SEC = 60.0
HARD_MIN_BREAKEVEN_PIPS = 14.0
TZ_UTC3 = datetime.timezone(datetime.timedelta(hours=3), name="UTC+3")

# Technical Analysis & Indicator Cache
_TECHNICAL_CACHE: Dict[str, Dict[str, Any]] = {}
_LAST_TECH_FETCH_TIME = 0.0

# Teknik veri bayatlık sınırı (#5). Yahoo fetch'i başarısız olduğunda
# `_TECHNICAL_CACHE.update()` yalnız BAŞARILI sembolleri yazar; başarısız
# sembolün önceki değeri süresiz kalıyordu ve motor o bayat skor/ATR ile giriş
# açabiliyordu. refreshed_at bu sınırı aşınca sembolün göstergeleri yok sayılır
# (skor 50/HOLD) — SL/TP de bayat ATR'den hesaplanmaz. 180 sn, 15 sn'lik
# normal tazeleme kadansına karşı 12 ardışık başarısızlık demektir; geçici
# Yahoo kesintisi tek başına tetiklemez, gerçek veri kesilmesi tetikler.
_TECH_STALE_SEC = 180.0

# ATR yumuşatma yöntemi (#15). True = Wilder yumuşatması (RSI ile tutarlı;
# CANLI VARSAYILAN). False = son 14 TR'nin düz ortalaması (eski davranış).
# ATR tabanlı SL/TP mesafelerini ve `major_min_atr` kapısını değiştirir.
# 2026-10-07 A/B (32g, 2026-09-07→10-03, tek değişken): net kâr ≈ aynı
# (+$45) ama maxDD $183 → $125 (-%32), zararlı gün 7 → 5, günlük Sharpe
# 0.76 → 0.85. OOS (09-20→10-03) aynı yönü doğruladı: $880 → $975,
# DD $183 → $113. Kullanıcı kararı: canlıda Wilder açık.
# Replay'de A/B için: `--wilder-atr` (True) / bayraksız (script bunu False'a
# çeker, bkz. forex_replay_backtest.py --wilder-atr dalı).
ATR_USE_WILDER = True
_LAST_GOLD_EXIT_TIME = 0.0
_LAST_BTC_EXIT_TIME = 0.0
_LAST_CLOSED_DEAL_IDS: set = set()

# FX korelasyon kalkanı: 5M kapanış önbelleğinden rolling Pearson matrisi
_CLOSES_CACHE: Dict[str, List[float]] = {}
_FX_CORR = FXCorrelationMonitor()


def _tech_is_stale(sym: str, now: Optional[float] = None) -> bool:
    """Teknik gösterge kaydı `_TECH_STALE_SEC`'ten eski mi (#5).

    Kayıt yoksa False (henüz veri gelmedi; çağıran zaten varsayılana düşer).
    Amaç: Yahoo o sembol için ardışık kez başarısız olduğunda bayat RSI/MACD/
    ADX/ATR ile giriş kararı ve SL/TP hesabı yapılmasını engellemek.
    """
    tech = _TECHNICAL_CACHE.get(sym)
    if not tech:
        return False
    ts = float(tech.get("updated_at", 0.0) or 0.0)
    if ts <= 0.0:
        return False
    return ((now if now is not None else time.time()) - ts) > _TECH_STALE_SEC

# MT5 köprüsünden gelen gerçek spread (pip) önbelleği
_LIVE_SPREAD_PIPS: Dict[str, float] = {}
# Köprü MT5 sembol adı -> uygulama sembol adı (spread eşlemesi için)
_MT5_TO_APP_SYMBOLS: Dict[str, str] = {
    "XTIUSD": "USOIL",
    "XBRUSD": "USOIL",
    "USTEC": "NAS100",
    "US100": "NAS100",
    "NDX100": "NAS100",
    "DJ30": "US30",
    "WS30": "US30",
    "W30": "US30",
    "GOLD": "XAUUSD",
    "XAU": "XAUUSD",
    "SILVER": "XAGUSD",
    "XAG": "XAGUSD",
}

YAHOO_SYMBOL_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
    "NZDUSD": "NZDUSD=X",
    "XAUUSD": "GC=F",
    # USOIL (CL=F), ETHUSD (ETH-USD) ve SPX500 (^GSPC) 2026-10-07'de kaldırıldı
    # — bkz. _RETIRED_FOREX_SYMBOLS. Bu harita veri hattının çektiği evrendir.
    # JPY krosçarları (donchian_adx giriş modu sembolleri — 2026-10-07)
    "GBPJPY": "GBPJPY=X",
    "EURJPY": "EURJPY=X",
    "NAS100": "^NDX",
    "US30": "^DJI",
    "BTCUSD": "BTC-USD",
    # ABD Dolar Endeksi (DXY) — işlem yapılmaz, yalnızca rejim filtresi için çekilir
    "DXY": "DX-Y.NYB",
}


def get_usd_bias(symbol: str, direction: str) -> str:
    """Determine if an order has USD_LONG, USD_SHORT, or USD_NEUTRAL exposure.
    Resilient to broker suffixes (.raw, .ecn, +, -, #) and non-standard commodity tickers.
    - Pairs with USD as Base (USDJPY, USDCAD, USDCHF): BUY -> USD_LONG, SELL -> USD_SHORT
    - Pairs with USD as Quote (EURUSD, GBPUSD, AUDUSD, NZDUSD, XAUUSD, XAGUSD, SPX500, NAS100, US30, USTEC, BTCUSD):
      BUY -> USD_SHORT, SELL -> USD_LONG

    Emekliye ayrılan semboller (USOIL/ETHUSD/SPX500, bkz. _RETIRED_FOREX_SYMBOLS)
    burada KALIR: arşivdeki eski pozisyonların kapanışı ve korelasyon kalkanı
    hâlâ onların USD yönünü bilmek zorunda.
    """
    s = str(symbol).upper().replace("/", "").strip()
    clean_sym = s.split(".")[0].split("+")[0].split("-")[0].replace("#", "").strip()
    d = str(direction).upper()

    if clean_sym.startswith("USD"):
        return "USD_LONG" if d == "BUY" else "USD_SHORT"
    elif clean_sym.endswith("USD") or clean_sym in (
        "USOIL", "OIL", "WTI", "XAUUSD", "XAGUSD", "SPX500", "NAS100", "US30", "USTEC",
        # MT5'te endekslerin GERÇEK sembol adları: NAS100 → USTEC/US100/NDX,
        # US30 → DJ30/WS30 (bkz. mt5_bridge.py SYMBOL_ALIAS_MAP). Köprünün
        # REVERSE_SYMBOL_ALIAS_MAP'i bu dördünü geri eşlemediği için pozisyon
        # adı ham hâliyle gelebiliyordu; tanınmadıklarında USD_NEUTRAL dönüp
        # korelasyon kalkanından (aynı-bias şartı) tamamen düşüyorlardı (#4).
        "US100", "NDX", "DJ30", "WS30", "DOW",
    ):
        return "USD_SHORT" if d == "BUY" else "USD_LONG"
    return "USD_NEUTRAL"


# DXY uyum şartı aranan zayıf semboller: USDJPY ve USDCHF — nötr rejimde giriş ekstra skor ister.
DXY_STRICT_SYMBOLS = ("USDJPY", "USDCHF")
# 2026-10-06 kullanıcı kararı: Ons Altın (XAUUSD), Kripto (BTCUSD, ETHUSD) ve ABD Endeksleri
# (NASDAQ 100 / Dow Jones) DXY rejim kapsamından TAMAMEN çıkarıldı — DXY çelişki vetosu ve
# strict-neutral engeli uygulanmaz. NOT (dürüst kayıt): 30g replay'de endeks muafiyeti −$153/maxDD +$35
# ölçüldü (gölge: 495 engel −$150 üretecekti); kullanıcı yine de kaldırma kararı verdi ve yerine
# NAS100'e özel strateji araştırması istedi. Tek satırla geri alınabilir.
DXY_EXEMPT_SYMBOLS = ("XAU", "GOLD", "BTC", "ETH", "NAS", "USTEC", "US100", "NDX", "US30", "DJ30", "WS30", "DOW")

# Majör FX pariteleri — seans penceresi ve volatilite tabanı kapılarının kapsamı.
FX_MAJORS_SET = {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"}


def major_entry_gate_decision(symbol: str, utc_hour: int, atr_pips: float,
                              session_filter: bool, session_start: int, session_end: int,
                              min_atr_pips: float) -> Optional[str]:
    """Majör FX giriş kapısı kararı (saf fonksiyon — test edilebilir).

    2026-10-06 30g replay A/B kazananları (7Eyl–2Eki, canlı ayar tabanı):
    - Seans penceresi (7-20 UTC): sistem −$170 → +$257, majör zararı −$896 → −$676
    - Min ATR 4.0p: üstüne +$199, WR %63 → %68 (kombinasyon: +$455.55, maxDD $210)
    Asya seansında majörlerde false breakout/chop kaynaklı kayıp yaygın (web araştırması
    ile destekli); ölü/oyalanmış piyasa girişleri volatilite tabanıyla elenir.

    Majör olmayan semboller için None döner. Majörlerde engel gerekçesi döner:
    - "major_session": UTC saati pencere dışında.
    - "major_min_atr": ATR tabanının altında (ölü piyasa).
    """
    if symbol not in FX_MAJORS_SET:
        return None
    if session_filter and not (session_start <= utc_hour < session_end):
        return "major_session"
    if min_atr_pips > 0 and atr_pips < min_atr_pips:
        return "major_min_atr"
    return None


def get_dxy_regime() -> Optional[Dict[str, Any]]:
    """ABD Dolar Endeksi (DXY / DX-Y.NYB) rejimini döner.

    DXY ile EURUSD korelasyonu ~-0.97 olduğu için değer yalnızca yön değil,
    doların güçlü/zayıf/sıkışık rejim bilgisidir:
    - USD_STRONG: DXY 15M trendi boğa ve momentum teyitli → USD lehine baskı
    - USD_WEAK:   DXY 15M trendi ayı ve momentum teyitli → USD aleyhine baskı
    - USD_NEUTRAL: Sıkışık/ belirsiz rejim → filtre etkisiz
    Veri yoksa None döner (fail-open).
    """
    tech = _TECHNICAL_CACHE.get("DXY")
    if not tech:
        return None
    trend = tech.get("trend", "NEUTRAL")
    score = float(tech.get("score", 50.0))
    rsi = float(tech.get("rsi", 50.0))
    if trend == "BULLISH" and (score >= 65.0 or rsi >= 55.0):
        regime = "USD_STRONG"
    elif trend == "BEARISH" and (score >= 65.0 or rsi <= 45.0):
        regime = "USD_WEAK"
    else:
        regime = "USD_NEUTRAL"
    return {
        "regime": regime,
        "trend": trend,
        "score": score,
        "rsi": rsi,
        "cmo": tech.get("cmo", 0.0),
        "change_pct": tech.get("change_pct", 0.0),
        "updated_at": tech.get("updated_at", 0.0),
    }


def dxy_entry_veto(symbol: str, direction: str, dxy: Optional[Dict[str, Any]]) -> Optional[str]:
    """DXY rejimine göre giriş denetimi (saf fonksiyon — test edilebilir).

    Dönen değer:
    - None: İzin var (DXY verisi yoksa da fail-open olarak izin).
    - "dxy_conflict": Pozisyon DXY rejimiyle ÇELİŞİYOR → giriş veto.
        (USD_LONG isteği + USD_WEAK rejimi, veya USD_SHORT isteği + USD_STRONG rejimi)
    - "dxy_strict_neutral": Zayıf sembol (USDJPY/USDCHF) ve rejim nötr →
        giriş ancak ekstra skor eşiğiyle kabul (req_score + 5).

    XAUUSD/GOLD muafiyetli: DXY rejiminden tamamen bağımsız işlem yapılır
    (DXY_EXEMPT_SYMBOLS — kullanıcı kararı 2026-10-06).
    """
    s = str(symbol).upper()
    if any(w in s for w in DXY_EXEMPT_SYMBOLS):
        return None
    if not dxy:
        # DXY verisi hiç yoksa kalkan devre dışı (fail-open)
        return None
    if dxy.get("regime", "USD_NEUTRAL") == "USD_NEUTRAL":
        if any(w in s for w in DXY_STRICT_SYMBOLS):
            return "dxy_strict_neutral"
        return None

    regime = dxy["regime"]
    bias = get_usd_bias(symbol, direction)
    if bias == "USD_LONG" and regime == "USD_WEAK":
        return "dxy_conflict"
    if bias == "USD_SHORT" and regime == "USD_STRONG":
        return "dxy_conflict"
    return None


def _collect_symbol_ev(symbol: str, now_ts: float, window_sec: float, source: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Kapanmış işlemlerden sembol bazlı son `window_sec` EV istatistiği.

    Kaynak önceliği: MT5 kapanmış anlaşmalar (bağlıysa) → paper defteri.
    Döner: {"n", "net", "wins", "win_rate"}.
    """
    sym = str(symbol).upper()
    if source is None:
        if _MT5_STATE.get("connected"):
            source = _MT5_STATE.get("closed_deals", [])
        else:
            source = _AUTO_STATE.get("closed_trades", [])
    rows: List[float] = []
    for d in source or []:
        if str(d.get("symbol", "")).upper() != sym:
            continue
        # Zaman damgası `_deal_ts` ile çözülür: MT5 köprüsü "… UTC+3" gönderir ve
        # eski satır içi parser "UTC+3" etiketini atıp değeri UTC sanıyordu →
        # pencere 3 saat kayıyordu. `_deal_ts` damga adını okur ve üç biçimi de
        # (epoch / ISO+offset / "… UTC+3") doğru çözer. (Canlı EV kalkanı, #3.)
        ts = _deal_ts(d)
        if ts is None:
            # Zamanı çözülemeyen kayıt EV penceresine alınmaz (fail-open: n
            # küçülür, kalkan tetiklenmez). Biçim değişirse bu sessiz kalır —
            # bilinen sınır; format değişikliğinde buraya bakılmalı.
            continue
        try:
            if now_ts - float(ts) > window_sec:
                continue
            # EV reset kesimi: reset anından önce kapanan işlemler sicile girmez —
            # sembol, reset sonrasındaki davranışıyla değerlendirilir.
            if _EV_RESET_AT_TS and float(ts) < _EV_RESET_AT_TS:
                continue
            pnl = float(d.get("pnl_usd", d.get("profit", 0.0)) or 0.0)
        except Exception:
            continue
        rows.append(pnl)
    n = len(rows)
    wins = sum(1 for p in rows if p >= 0)
    return {
        "n": n,
        "net": round(sum(rows), 2),
        "wins": wins,
        "win_rate": round(100.0 * wins / n, 1) if n else 0.0,
    }


def ev_guard_decision(stats: Dict[str, Any], min_samples: int, max_win_rate: float, risk_loss_floor: float) -> bool:
    """Sembol EV kalkanı kararı (saf fonksiyon — test edilebilir).

    True = sembol dinlenmeye alınmalı. İki tetik (yeterli örnek ve net zarar şartıyla):
    - Kronik kaybeden: kazanma oranı max_win_rate altında,
    - Akut kayıp: toplam net zarar risk bütçesinin `risk_loss_floor` katını aştı.
    Kendini onaran yapı: sembol işlem yapmadıkça kayıplar zaman penceresinden
    yaşlanarak dışarı düşer ve kalkan kendiliğinden kalkar.
    """
    n = int(stats.get("n", 0))
    if n < min_samples:
        return False
    net = float(stats.get("net", 0.0))
    if net > 0:
        return False
    wr = float(stats.get("win_rate", 100.0))
    return wr < float(max_win_rate) or net <= -abs(float(risk_loss_floor))


def loss_streak_on_close(streak: int, reason: str, pnl_usd: float, limit: int) -> Tuple[int, bool]:
    """Seri-SL sigortası sayacı (saf fonksiyon — test edilebilir).

    Kullanıcı kuralı: aynı sembolde arka arkaya N kez tam-SL ile zararla kapanan işlem
    olursa sembol kısa süreliğine YENİ giriş almaz (normal cooldown'dan bağımsız), süre
    bitince normal değerlendirme devam eder. Kazançla kapanış seriyi sıfırlar.

    Kurallar:
      - pnl > 0 → seri sıfırlanır (BE/trailing kazançları da seriyi bozar).
      - `SL_HIT` + pnl < 0 → seri 1 artar. BE/trailing çıkışları pnl < 0 üretemez
        (SL hep giriş üstünde kilitlenir), yani "SL ile zarar" tam-SL kaybıdır.
      - Sayı `limit`e ulaşınca (0, True) döner: soğuma tetiklenir, sayaç sıfırdan başlar.
      - limit <= 0 → mekanizma kapalı; pnl==0 veya diğer nedenler sayacı değiştirmez.
    """
    if pnl_usd > 0:
        return 0, False
    if limit <= 0 or pnl_usd >= 0 or reason != "SL_HIT":
        return streak, False
    streak += 1
    if streak >= limit:
        return 0, True
    return streak, False


def donchian_adx_entry(prev_close: Optional[float], prev_mid: Optional[float], close: float,
                       mid: float, adx: float, adx_min: float, day: int, day_counts: Dict[str, int],
                       max_per_day: int, hour_utc: int, is_jpy: bool) -> Optional[str]:
    """Donchian(20) orta-hat çaprazı giriş kararı (saf fonksiyon — replay ile aynı kural).

    Kural (2026-10-07 kalibrasyon kazananı): önceki değerlendirme orta hattın bir tarafında
    iken şu an fiyat orta hattı LEHTE keserse ve ADX ≥ eşikse giriş. Gün içi yön başına
    max_per_day limiti; seans: JPY çiftleri 00-16 UTC, diğerleri 07-16 UTC.
    Döner: "BUY" / "SELL" / None.
    """
    if prev_close is None or not prev_mid or prev_mid <= 0 or mid <= 0 or close <= 0:
        return None
    if adx < adx_min:
        return None
    if is_jpy:
        if not (0 <= hour_utc < 16):
            return None
    else:
        if not (7 <= hour_utc < 16):
            return None
    if day_counts.get("BUY", 0) >= max_per_day and day_counts.get("SELL", 0) >= max_per_day:
        return None
    if prev_close <= prev_mid and close > mid:
        return "BUY" if day_counts.get("BUY", 0) < max_per_day else None
    if prev_close >= prev_mid and close < mid:
        return "SELL" if day_counts.get("SELL", 0) < max_per_day else None
    return None


def apply_risk_normalization(symbol: str, lots: float, sl_pips: float, pip_val: float, risk_usd: float) -> Tuple[float, bool]:
    """Lot × SL × pip_val riskini bütçeye sıkıştırır (saf fonksiyon — test edilebilir).

    Kategori lot tavanı (endeks 0.20, emtia/kripto 0.02) dar SL'ler için tasarlandı;
    ATR çıkış motoru SL'i genişlettiğinde tavan lotu risk bütçesini aşabilir
    (gerçek örnek: US30 0.20 lot × 81.7 pip = %1.6 risk). Bu fonksiyon:
    - risk ≤ hedef×1.25 ise dokunmaz (mevcut davranış),
    - aşım varsa lotu adım adım aşağı çeker (endeks 0.05, petrol 0.05, diğer 0.01),
    - kategori minimum lotu bile hedefin 2 katını (sert sınır) aşıyorsa skip=True
      döner ve arayan taraf işlemi tamamen pas geçmelidir.
    """
    s = str(symbol).upper()
    # "SPX" dalı emekliye ayrılan SPX500 için KALIR (bkz. _RETIRED_FOREX_SYMBOLS):
    # arşivdeki eski endeks kayıtları yeniden hesaplanırken bu tavan okunur.
    if "NAS" in s or "USTEC" in s or "US30" in s or "SPX" in s:
        floor_lot, step = 0.10, 0.05
    elif "OIL" in s or "WTI" in s:
        floor_lot, step = 0.50, 0.05
    else:
        floor_lot, step = 0.01, 0.01

    if sl_pips <= 0 or pip_val <= 0 or lots <= 0:
        return round(float(lots), 2), False
    target_risk = float(risk_usd) * 1.25
    hard_risk = float(risk_usd) * 2.0
    current_risk = float(lots) * float(sl_pips) * float(pip_val)
    if current_risk <= target_risk:
        return round(float(lots), 2), False

    fitted = math.floor((target_risk / (float(sl_pips) * float(pip_val))) / step) * step
    fitted = round(max(0.0, fitted), 2)
    if fitted < floor_lot:
        if floor_lot * float(sl_pips) * float(pip_val) <= hard_risk:
            return floor_lot, False
        return round(float(lots), 2), True
    return fitted, False


def is_entry_hour_blocked(current_utc_hour: int, blocked_hours: List[int]) -> bool:
    """Zayıf saat kalkanı (saf fonksiyon): UTC saati engelli listedeyse True."""
    if not blocked_hours:
        return False
    return int(current_utc_hour) in {int(h) for h in blocked_hours}


def get_symbol_trading_specs(
    symbol: str,
    base_sl: float = 8.0,
    base_tp: float = 20.0,
    base_be: float = 10.0,
    base_trail: float = 16.0,
    atr_pips: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Her parite ve emtia için doğru pip büyüklüğünü (pip_size),
    volatilite çarpanını (mult), basamak sayısını (digits) ve lot başına 1 pip dolar değerini döner.

    Özellikle Ons Altın (XAUUSD) için:
    - MT5 ve uluslararası piyasalarda 1 pip = 0.10 USD (10 point / 10 cent) kabul edilir.
    - Altın'ın yüksek oynaklığı nedeniyle en az 3.0x volatilite tamponu (min 24 pip / $2.40 USD koruma)
      ve dinamik ATR(14) volatilite tamponu uygulanır. Volatilite arttığında SL dinamik olarak genişler.
    - Erken başabaş (breakeven) stop kilitlenmesini engellemek için altın BE eşiği en az 25 pip ($2.50) olmalıdır.
    - Standart paritelerde de erken boğulmayı engellemek için BE eşiği en az 10.0 pip olmalıdır.
    """
    s = str(symbol).upper().replace("/", "").strip()
    clean_sym = s.split(".")[0].split("+")[0].split("-")[0].replace("#", "").strip()
    base_be_floored = max(HARD_MIN_BREAKEVEN_PIPS, base_be)

    if "XAU" in clean_sym or "GOLD" in clean_sym:
        pip_size = 0.10          # 1 pip = 0.10 USD (10 cent / 10 point)
        mult = 3.0               # 3.0x taban volatilite nefes alma çarpanı
        digits = 2
        pip_val = 10.0           # 1 lot (100 oz) * 0.10 USD = $10.0
        base_sl_pips = round(base_sl * mult, 1)  # 8.0 * 3.0 = 24.0 pips ($2.40)
        base_tp_pips = round(base_tp * mult, 1)  # 20.0 * 3.0 = 60.0 pips ($6.00)

        # Dinamik ATR volatilite tamponu: ATR genişlediğinde SL ve TP dinamik genişletilir
        if atr_pips is not None and atr_pips > 0:
            eff_sl_pips = max(base_sl_pips, round(atr_pips * 1.5, 1))
        else:
            eff_sl_pips = base_sl_pips

        eff_tp_pips = max(base_tp_pips, round(eff_sl_pips * 1.83, 1))
        eff_be_pips = max(25.0, round(eff_sl_pips * 0.7, 1))
        eff_trail_pips = max(40.0, round(eff_sl_pips * 1.2, 1))

    elif "XAG" in clean_sym or "SILVER" in clean_sym:
        pip_size = 0.01          # 1 pip = 0.01 USD
        mult = 2.0
        digits = 3
        pip_val = 50.0           # 1 lot (5000 oz) * 0.01 USD = $50.0
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(20.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    elif "USOIL" in clean_sym or "OIL" in clean_sym or "WTI" in clean_sym or "XTI" in clean_sym or "XBR" in clean_sym:
        pip_size = 0.01          # 1 pip = 0.01 USD (1 cent)
        mult = 2.0
        digits = 2
        pip_val = 1.0            # IC Markets: 1 lot (100 varil) * 0.01 USD = $1.00
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(20.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    elif "JPY" in clean_sym:
        pip_size = 0.01          # 1 pip = 0.01 JPY (10 point)
        mult = 1.0
        digits = 3
        pip_val = 6.60
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(HARD_MIN_BREAKEVEN_PIPS, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    elif "BTC" in clean_sym:
        pip_size = 1.0           # 1 pip = $1.00
        mult = 5.0
        digits = 2
        pip_val = 1.0
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(40.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    # ETHUSD emekliye ayrıldı ama spec dalı KALIR: arşivdeki ETH kayıtları
    # yeniden hesaplanırken pip_val/digits buradan okunur (bkz. _RETIRED_FOREX_SYMBOLS).
    elif "ETH" in clean_sym:
        pip_size = 1.0           # 1 pip = $1.00
        mult = 2.0
        digits = 2
        pip_val = 1.0            # IC Markets: contract_size 1.0 -> 1 lot * $1.0 = $1.00
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(20.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    elif "USTEC" in clean_sym or "NAS100" in clean_sym or "US100" in clean_sym or "NDX" in clean_sym:
        pip_size = 1.0           # 1 pip = 1.0 index point
        mult = 2.5
        digits = 2
        pip_val = 1.0            # IC Markets: contract_size 1.0 -> 1 lot * 1.0 point = $1.00
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(20.0, round(base_be_floored * mult, 1))
        eff_trail_pips = max(35.0, round(base_trail * mult, 1))

    elif "US30" in clean_sym or "DJ30" in clean_sym or "WS30" in clean_sym:
        pip_size = 1.0           # 1 pip = 1.0 index point
        mult = 3.0
        digits = 2
        pip_val = 1.0            # IC Markets: contract_size 1.0 -> 1 lot * 1.0 point = $1.00
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(25.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    else:
        # Standart Forex (EURUSD, GBPUSD, AUDUSD, NZDUSD, USDCAD, USDCHF)
        pip_size = 0.0001        # 1 pip = 0.0001 (10 point)
        mult = 1.0
        digits = 5
        pip_val = 10.0
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(HARD_MIN_BREAKEVEN_PIPS, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    return {
        "pip_size": pip_size,
        "digits": digits,
        "pip_val": pip_val,
        "mult": mult,
        "sl_pips": eff_sl_pips,
        "tp_pips": eff_tp_pips,
        "be_pips": eff_be_pips,
        "trail_pips": eff_trail_pips,
    }


def get_atr_exit_levels(
    atr_pips: Optional[float],
    sl_pips: float,
    tp_pips: float,
    sl_atr_mult: float = 1.1,
    tp_atr_mult: float = 1.4,
    rr_floor: float = 1.5,
) -> Dict[str, float]:
    """ATR bazlı dinamik çıkış motoru (saf fonksiyon — test edilebilir).

    Gerçek işlem verisinde TP isabet oranı %5.3'te kalmıştı: sabit 2.5R hedef
    volatiliteden uzaktı. Bu motor TP'yi volatiliteye çeker:
    - SL: ATR * sl_atr_mult volatilite nefes payı (spec SL'inin altına inmez)
    - TP: ATR * tp_atr_mult hedef, ama TP asla SL * rr_floor'un altına inmez
      (spread maliyeti koruması) ve asla spec TP'sinin üzerine çıkmaz
    - first_target_pips: Kısmi kâr hedefi (max(SL*0.9, ATR*1.0), TP'nin altında)

    ATR verisi yoksa passthrough döner (eski davranış).
    rr_floor=1.5 ve min_score=75.0 varsayılanları 7 günlük replay A/B ile seçildi;
    tümü ayarlanabilir (replay: scripts/forex_replay_backtest.py).
    """
    if atr_pips is None or atr_pips <= 0:
        return {
            "sl_pips": float(sl_pips),
            "tp_pips": float(tp_pips),
            "first_target_pips": round(float(tp_pips) * 0.6, 1),
        }
    eff_sl = max(float(sl_pips), round(atr_pips * sl_atr_mult, 1))
    min_tp = round(eff_sl * rr_floor, 1)
    atr_tp = round(atr_pips * tp_atr_mult, 1)
    eff_tp = max(min_tp, min(float(tp_pips), max(atr_tp, min_tp)))
    first_target = min(eff_tp, max(round(eff_sl * 0.9, 1), round(atr_pips * 1.0, 1)))
    first_target = max(1.0, first_target)
    return {
        "sl_pips": eff_sl,
        "tp_pips": round(eff_tp, 1),
        "first_target_pips": round(first_target, 1),
    }


def calculate_breakeven_target(
    pnl_pips: float,
    pnl_usd: float,
    lots: float,
    pip_val: float,
    pip_size: float,
    digits: int,
    direction: str,
    entry_price: float,
    current_price: float,
    current_sl: float,
    sl_pips: float,
    atr_pips: float,
    eff_be_pips: float,
    is_gold: bool = False,
    is_crypto: bool = False,
    gold_be_lock_ratio: float = 0.60,
    be_r_mult: float = 0.40,
    be_atr_mult: float = 0.50,
) -> Optional[float]:
    """Volatilite (ATR) ve Risk (R) tabanlı başabaş (Breakeven) hedefi hesaplar.
    
    Tetiklenme kuralı:
      Kâr en az min_be_pips (ör. 0.4*SL veya 0.5*ATR veya eff_be_pips) seviyesine
      ulaşmalı ve net $1.00 minimum güvencesini sağlamalıdır.
      Böylece hesap bakiyesine göre erken boğulma (0.06R stop) engellenir.
    
    Kilitlenme kuralı:
      SL seviyesi giriş fiyatının ötesine taşınır (kârın lock_ratio kadarı veya min $1).
    """
    if pnl_pips <= 0:
        return None

    dollar_per_pip = max(0.0001, lots * pip_val)
    pips_for_1usd = max(0.5, round(1.0 / dollar_per_pip, 1))
    headroom = 4.0 if is_gold else (25.0 if is_crypto else 3.5)

    # Volatilite & Risk tabanlı tetik eşiği
    r_trigger = sl_pips * be_r_mult if sl_pips > 0 else 0.0
    atr_trigger = atr_pips * be_atr_mult if atr_pips > 0 else 0.0
    
    # En az dolar güvencesi + R/ATR tetik tabanı
    min_trigger_pips = max(
        pips_for_1usd + headroom,
        r_trigger,
        atr_trigger,
        eff_be_pips if eff_be_pips > 0 else 0.0
    )

    if pnl_pips < min_trigger_pips:
        return None

    # Kilitlenecek pips: kârın belirli oranı, ama en az $1 kâr güvencesi
    lock_ratio = gold_be_lock_ratio if is_gold else 0.40
    locked_pips = max(pips_for_1usd, round(pnl_pips * lock_ratio, 1))

    if direction == "BUY":
        cand_be = round(entry_price + (locked_pips * pip_size), digits)
        if cand_be > current_sl and cand_be < current_price:
            return cand_be
    else:
        cand_be = round(entry_price - (locked_pips * pip_size), digits)
        if (current_sl == 0.0 or cand_be < current_sl) and cand_be > current_price:
            return cand_be

    return None


def apply_partial_take_profit(pos: Dict[str, Any], pnl_pips: float, pip_usd_val: float) -> Optional[float]:
    """Kısmi kâr alma (saf fonksiyon — test edilebilir).

    Pozisyon ilk kâr hedefine (partial_target_pips) ulaştıysa lot'un yarısını
    kapatıp gerçekleştirilen kârı (USD) döner; kalan pozisyonda SL'i başabaş
    üstü net kâra kilitler. Pozisyon dict'i yerinde güncellenir.

    Dönüş: gerçekleşen kısmi kâr USD (henüz alınmadıysa None).
    """
    target = float(pos.get("partial_target_pips") or 0.0)
    if target <= 0.0 or pos.get("partial_taken"):
        return None
    if pnl_pips < target:
        return None

    pos["partial_taken"] = True
    lots = float(pos.get("lots", 0.0))
    close_lots = round(lots / 2.0, 2)

    if close_lots < 0.01 or close_lots >= lots:
        # Yarısı minimum lotun altında → kapatma yok, sadece kilit işaretle
        return None

    realized = round(pnl_pips * close_lots * pip_usd_val, 2)
    pos["lots"] = round(lots - close_lots, 2)
    pos["partial_realized_usd"] = round(float(pos.get("partial_realized_usd", 0.0)) + realized, 2)
    # Kısmi bacağın pip'i de birikir: kapanış kaydı toplam pip'i gösterebilsin
    # (yoksa yalnız kalan bacak raporlanır ve kazanan işlem eksik görünür — P1).
    pos["partial_realized_pips"] = round(float(pos.get("partial_realized_pips", 0.0)) + pnl_pips, 1)

    # Kalan pozisyon için SL'i başabaş üstü net kâra kilit ($1 garantisinden aşağı inmez)
    pip_size = float(pos.get("pip_size", 0.0001))
    digits = int(pos.get("digits", 5))
    direction = pos.get("direction", "BUY")
    entry_p = float(pos["entry_price"])
    dollar_per_pip = max(0.0001, float(pos["lots"]) * pip_usd_val)
    lock_pips = max(0.5, round(1.0 / dollar_per_pip, 1))
    if direction == "BUY":
        lock_sl = round(entry_p + (lock_pips * pip_size), digits)
        if lock_sl > float(pos.get("sl_price", 0.0)) and lock_sl < entry_p + (target * pip_size):
            pos["sl_price"] = lock_sl
            pos["breakeven_activated"] = True
    else:
        lock_sl = round(entry_p - (lock_pips * pip_size), digits)
        cur_sl = float(pos.get("sl_price", 0.0))
        if (cur_sl == 0.0 or lock_sl < cur_sl) and lock_sl > entry_p - (target * pip_size):
            pos["sl_price"] = lock_sl
            pos["breakeven_activated"] = True

    # Kısmi kapanıştan sonra kalan bacak aynı SL mesafesini ama YARI lotu taşır;
    # yani gerçek risk anında yarıya iner. Eskiden bu hiçbir yerde işaretlenmediği
    # için risk bütçesi modeli (apply_risk_normalization) kalan bacağı tam riskli
    # sanıyordu (P3). Kalan riski pozisyona yazıyoruz ki replay/rapor doğru tabanı
    # görsün — davranış değişmez, yalnız model şeffaflaşır. Nihai SL kilidinden
    # SONRA hesaplanır, çünkü asıl korunan mesafe odur.
    entry_p_check = float(pos.get("entry_price", 0.0))
    sl_after_lock = float(pos.get("sl_price", 0.0))
    sl_dist = abs(entry_p_check - sl_after_lock) if sl_after_lock > 0 else 0.0
    if sl_dist > 0:
        pos["risk_usd_after_partial"] = round(
            sl_dist / max(pip_size, 1e-9) * float(pos.get("lots", 0.0)) * pip_usd_val, 2
        )
    return realized


def _resample_5m_to_15m(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
) -> Tuple[List[float], List[float], List[float], List[float]]:
    """Resample 5-minute candles into 15-minute candles for multi-timeframe analysis."""
    n = len(closes)
    rem = n % 3
    o15, h15, l15, c15 = [], [], [], []
    for i in range(rem, n, 3):
        chunk_o = opens[i:i + 3]
        chunk_h = highs[i:i + 3]
        chunk_l = lows[i:i + 3]
        chunk_c = closes[i:i + 3]
        if chunk_c:
            o15.append(chunk_o[0])
            h15.append(max(chunk_h))
            l15.append(min(chunk_l))
            c15.append(chunk_c[-1])
    return o15, h15, l15, c15


def _compute_cmo(closes: np.ndarray, period: int = 14) -> float:
    """Chande Momentum Oscillator (CMO): -100..+100.

    CMO = 100 * (toplam kazanç - toplam kayıp) / (toplam kazanç + toplam kayıp)
    RSI'dan farkı: momentumun hem yönünü hem hızını ölçer; 0 çizgisi trend onayıdır.
    Düz/ hareketsiz seride 0 döner (0/0 koruması).
    """
    n = len(closes)
    if n < period + 1:
        return 0.0
    deltas = np.diff(closes[-(period + 1):])
    gains = float(deltas[deltas > 0].sum())
    losses = float(-deltas[deltas < 0].sum())
    denom = gains + losses
    if denom <= 0.0:
        return 0.0
    return float(100.0 * (gains - losses) / denom)


def _compute_cci(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 20) -> float:
    """Commodity Channel Index (CCI): tipik fiyat (H+L+C)/3 ile SMA sapması / (0.015 * ortalama sapma).

    +100 üstü güçlü yukarı momentum, -100 altı güçlü aşağı momentum; ±200 aşırı uzama.
    Hareketsiz seride (ortalama sapma ~0) 0 döner (0/0 koruması).
    """
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = min(len(h), len(l), len(c))
    if n < period:
        return 0.0
    tp = (h[-period:] + l[-period:] + c[-period:]) / 3.0
    sma = float(np.mean(tp))
    mean_dev = float(np.mean(np.abs(tp - sma)))
    if mean_dev <= 1e-12:
        return 0.0
    return float((float(tp[-1]) - sma) / (0.015 * mean_dev))


def _compute_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Ortalama Yönsel Endeks (ADX, Wilder): trend VAR mı sorusuna odaklanır (0-100).

    ADX < 20-22 → yönsüz/çalkantılı piyasa (trend girişleri için riskli bölge),
    ADX >= 25 → güçlü trend. Yön bilgisi +DI/-DI'dan gelir; burada yalnız güç döner.
    Yetersiz veri veya sıfır aralıkta 0.0 döner.
    """
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = min(len(h), len(l), len(c))
    if n < 2 * period + 2:
        return 0.0
    h, l, c = h[-n:], l[-n:], c[-n:]
    up_move = h[1:] - h[:-1]
    down_move = l[:-1] - l[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))

    def _wilder(series: np.ndarray) -> float:
        first = float(np.sum(series[:period]))
        if first <= 0:
            return 0.0
        val = first
        for x in series[period:]:
            val = val - val / period + float(x)
        return val

    atr_w = _wilder(tr)
    if atr_w <= 0:
        return 0.0
    plus_di = 100.0 * _wilder(plus_dm) / atr_w
    minus_di = 100.0 * _wilder(minus_dm) / atr_w
    denom = plus_di + minus_di
    if denom <= 0:
        return 0.0
    dx = 100.0 * abs(plus_di - minus_di) / denom
    # ADX = DX serisinin Wilder düzleştirmesi
    dx_series = []
    plus_w = float(np.sum(plus_dm[:period]))
    minus_w = float(np.sum(minus_dm[:period]))
    tr_w = float(np.sum(tr[:period]))
    for i in range(period, len(tr)):
        plus_w = plus_w - plus_w / period + float(plus_dm[i - 1])
        minus_w = minus_w - minus_w / period + float(minus_dm[i - 1])
        tr_w = tr_w - tr_w / period + float(tr[i - 1])
        if tr_w > 0:
            pdi = 100.0 * plus_w / tr_w
            mdi = 100.0 * minus_w / tr_w
            d = pdi + mdi
            dx_series.append(100.0 * abs(pdi - mdi) / d if d > 0 else 0.0)
        else:
            dx_series.append(0.0)
    if not dx_series:
        return dx
    # Wilder düzleştirme: ilk değer ilk `period` DX ortalaması, sonra özyinelemeli
    adx_val = float(np.mean(dx_series[:period]))
    for x in dx_series[period:]:
        adx_val = (adx_val * (period - 1) + float(x)) / period
    return max(0.0, min(100.0, adx_val))


def _compute_supertrend(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                        period: int = 10, mult: float = 3.0) -> Tuple[int, float]:
    """SuperTrend (ATR bandlı trend takibi): yön (+1 boğa / -1 ayı) ve bant seviyesi döner.

    Fiyat bant üstündeyse trend boğa, altındaysa ayı; bant ratchet (tek yönlü)
    kilitlenir. Trend yönü filtresi ve ATR tabanlı stop referansı sağlar.
    """
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = min(len(h), len(l), len(c))
    if n < period + 2:
        return 0, 0.0
    h, l, c = h[-n:], l[-n:], c[-n:]
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr_series = []
    atr_val = float(np.mean(tr[:period]))
    atr_series.append(atr_val)
    for i in range(period, len(tr)):
        atr_val = (atr_val * (period - 1) + float(tr[i])) / period
        atr_series.append(atr_val)

    hl2 = (h + l) / 2.0
    direction = 0
    final_upper = 0.0
    final_lower = 0.0
    st_level = 0.0
    for i in range(period, n):
        atr_i = atr_series[i - period] if (i - period) < len(atr_series) else atr_series[-1]
        upper = hl2[i] + mult * atr_i
        lower = hl2[i] - mult * atr_i
        prev_close = c[i - 1]
        if i == period:
            final_upper, final_lower = upper, lower
            direction = 1 if c[i] >= hl2[i] else -1
        else:
            final_upper = upper if (upper < final_upper or prev_close > final_upper) else final_upper
            final_lower = lower if (lower > final_lower or prev_close < final_lower) else final_lower
            if c[i] > final_upper:
                direction = 1
            elif c[i] < final_lower:
                direction = -1
        st_level = final_lower if direction == 1 else final_upper
    return direction, float(st_level)


def _compute_technical_indicators(
    closes: List[float],
    highs: List[float],
    lows: List[float],
    opens: List[float],
    symbol: str,
    include_momentum: bool = True,
) -> Optional[Dict[str, Any]]:
    """Calculates Multi-Timeframe (15M HTF Trend + 5M LTF Execution) indicators, RSI(14), MACD, ATR, CMO, CCI and composite score.

    include_momentum=False → CMO/CCI/üçlü teyit puanları devre dışı (eski skor davranışı — A/B replay için).
    """
    if len(closes) < 15:
        return None
    c = np.asarray(closes, dtype=float)
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)

    def _calc_ema(series: np.ndarray, period: int) -> np.ndarray:
        alpha = 2.0 / (period + 1)
        res = [float(series[0])]
        for val in series[1:]:
            res.append(alpha * float(val) + (1.0 - alpha) * res[-1])
        return np.array(res, dtype=float)

    # 1. 5M LTF EMAs
    ema9_series = _calc_ema(c, 9)
    ema21_series = _calc_ema(c, 21)
    ema50_series = _calc_ema(c, min(len(c), 50))

    ema9 = float(ema9_series[-1])
    ema21 = float(ema21_series[-1])
    ema50 = float(ema50_series[-1])
    last_price = float(c[-1])

    # 2. 15M HTF Trend Filter (Resampled from 5M bars)
    o15, h15, l15, c15 = _resample_5m_to_15m(opens, highs, lows, closes)
    if len(c15) >= 15:
        c15_arr = np.asarray(c15, dtype=float)
        ema_fast_15m = float(_calc_ema(c15_arr, 10)[-1])
        ema_slow_15m = float(_calc_ema(c15_arr, min(len(c15_arr), 25))[-1])
        if ema_fast_15m > ema_slow_15m and last_price >= ema_slow_15m * 0.998:
            htf_trend = "BULLISH"
        elif ema_fast_15m < ema_slow_15m and last_price <= ema_slow_15m * 1.002:
            htf_trend = "BEARISH"
        else:
            htf_trend = "NEUTRAL"
    else:
        # Fallback to 5M EMA21 vs EMA50 if not enough 15M bars
        htf_trend = "BULLISH" if ema21 > ema50 else ("BEARISH" if ema21 < ema50 else "NEUTRAL")

    # 3. Wilder-smoothed RSI 14 (5M)
    deltas = np.diff(c)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    period = 14
    if len(deltas) >= period:
        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * 13.0 + float(gains[i])) / 14.0
            avg_loss = (avg_loss * 13.0 + float(losses[i])) / 14.0
        rs = avg_gain / avg_loss if avg_loss != 0 else 100.0
        rsi = float(100.0 - (100.0 / (1.0 + rs)))
    else:
        rsi = 50.0

    # 4. MACD (12, 26, 9)
    fast = _calc_ema(c, 12)
    slow = _calc_ema(c, 26)
    macd_line = fast - slow
    signal_line = _calc_ema(macd_line, 9)
    hist = float(macd_line[-1] - signal_line[-1])

    # 5. ATR 14
    # Varsayılan (ATR_USE_WILDER=True): Wilder yumuşatması — ilk 14 TR'nin
    # ortalaması tohum, sonra `avg = (avg*13 + tr)/14` (RSI ile aynı yöntem).
    # ATR_USE_WILDER=False: son 14 gerçek aralığın DÜZ ortalaması (eski davranış,
    # replay'de `--plain-atr` ile ölçülür). 2026-10-07 A/B: Wilder net kârı aynı
    # tutarken maxDD'yi %32 düşürdü → canlıda açık (bkz. #15).
    if len(h) >= 15:
        tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
        if ATR_USE_WILDER and len(tr) >= 14:
            atr_w = float(np.mean(tr[:14]))
            for i in range(14, len(tr)):
                atr_w = (atr_w * 13.0 + float(tr[i])) / 14.0
            atr = atr_w
        else:
            atr = float(np.mean(tr[-14:]))
    else:
        atr = float(np.mean(h - l)) if len(h) > 0 else 0.001

    # 5b. ADX (trend gücü) ve SuperTrend (trend yönü) — giriş kapıları için
    adx_val = _compute_adx(h, l, c, 14)
    st_dir, _st_level = _compute_supertrend(h, l, c, 10, 3.0)

    first_open = float(opens[0]) if opens else float(c[0])
    change_pct = round(((last_price - first_open) / first_open) * 100.0, 2) if first_open > 0 else 0.0

    # 6. Multi-Timeframe Scoring & Trend Synthesis (OPTIMIZED)
    bullish_pts = 0
    bearish_pts = 0

    # (a) HTF 15M Trend Filter (30 Pts) - Trend direction gate
    if htf_trend == "BULLISH":
        bullish_pts += 30
    elif htf_trend == "BEARISH":
        bearish_pts += 30
    else:
        bullish_pts += 8
        bearish_pts += 8

    # (b) LTF 5M EMA Alignment (25 Pts)
    if last_price > ema9 > ema21 > ema50:
        bullish_pts += 25
    elif last_price < ema9 < ema21 < ema50:
        bearish_pts += 25
    elif ema9 > ema21:
        bullish_pts += 12
    elif ema9 < ema21:
        bearish_pts += 12

    # (b2) EMA Slope Momentum Bonus (10 Pts) - Trend hızlanıyor mu?
    if len(ema9_series) >= 3:
        ema9_slope = float(ema9_series[-1]) - float(ema9_series[-3])
        if ema9_slope > 0 and htf_trend == "BULLISH":
            bullish_pts += 10
        elif ema9_slope < 0 and htf_trend == "BEARISH":
            bearish_pts += 10

    # (c) RSI Pullback & Momentum (25 Pts)
    # Healthy pullback zone (sweet spot for scalper entry without chasing extremes)
    if 40.0 <= rsi <= 60.0:
        if htf_trend == "BULLISH":
            bullish_pts += 25
        elif htf_trend == "BEARISH":
            bearish_pts += 25
        else:
            bullish_pts += 10
            bearish_pts += 10
    elif 30.0 <= rsi < 40.0:
        # Oversold bounce opportunity
        bullish_pts += 18
    elif 60.0 < rsi <= 70.0:
        # Overbought pullback opportunity
        bearish_pts += 18
    elif rsi > 75.0:
        # Extreme high - strong penalty
        bullish_pts -= 20
        bearish_pts += 12
    elif rsi < 25.0:
        # Extreme low - strong penalty
        bearish_pts -= 20
        bullish_pts += 12

    # (c2) RSI-Trend Alignment Bonus (8 Pts)
    if htf_trend == "BULLISH" and 45.0 <= rsi <= 65.0:
        bullish_pts += 8
    elif htf_trend == "BEARISH" and 35.0 <= rsi <= 55.0:
        bearish_pts += 8

    # (d) MACD Histogram Momentum (20 Pts)
    if hist > 0:
        bullish_pts += 20
    else:
        bearish_pts += 20

    # (e) CMO — Chande Momentum Osilatörü (5M, 14): yön + hız teyidi
    # (f) CCI — Commodity Channel Index (5M, 20): tipik fiyat sapma teyidi
    # (g) Üçlü Momentum Teyidi: RSI + CMO + CCI aynı yönde → bonus
    cmo = 0.0
    cci = 0.0
    if include_momentum:
        cmo = _compute_cmo(c, 14)
        if cmo > 0.0:
            bullish_pts += 5
        elif cmo < 0.0:
            bearish_pts += 5
        if cmo > 25.0:
            # Güçlü boğa momentumu ayı tezini çürütüyor
            bearish_pts -= 8
        elif cmo < -25.0:
            bullish_pts -= 8
        if cmo > 65.0:
            # Aşırı uzama — trend kovalamayı engelle (RSI > 75 cezasının CMO karşılığı)
            bullish_pts -= 10
            bearish_pts += 5
        elif cmo < -65.0:
            bearish_pts -= 10
            bullish_pts += 5

        cci = _compute_cci(h, l, c, 20)
        if cci > 0.0:
            bullish_pts += 6
        elif cci < 0.0:
            bearish_pts += 6
        if cci > 100.0:
            bearish_pts -= 6
        elif cci < -100.0:
            bullish_pts -= 6
        if cci > 200.0:
            # Aşırı uzama — mean reversion riski
            bullish_pts -= 6
            bearish_pts += 3
        elif cci < -200.0:
            bearish_pts -= 6
            bullish_pts += 3

        if rsi >= 50.0 and cmo > 0.0 and cci > 0.0:
            bullish_pts += 8
        elif rsi <= 50.0 and cmo < 0.0 and cci < 0.0:
            bearish_pts += 8

    # MTF Alignment Verdict
    ltf_bullish = (ema9 > ema21 and last_price >= ema21 * 0.999)
    ltf_bearish = (ema9 < ema21 and last_price <= ema21 * 1.001)

    if (htf_trend == "BULLISH" or htf_trend == "NEUTRAL") and ltf_bullish and bullish_pts >= bearish_pts:
        trend = "BULLISH"
        action = "BUY" if rsi <= 78.0 else "HOLD"
        score = round(min(96.0, max(60.0, 50.0 + (bullish_pts * 0.46))), 1)
        macd_verdict = f"AL (MTF Boğa Uyumu | 15M: {htf_trend} + 5M Momentum)"
    elif (htf_trend == "BEARISH" or htf_trend == "NEUTRAL") and ltf_bearish and bearish_pts >= bullish_pts:
        trend = "BEARISH"
        action = "SELL" if rsi >= 22.0 else "HOLD"
        score = round(min(96.0, max(60.0, 50.0 + (bearish_pts * 0.46))), 1)
        macd_verdict = f"SAT (MTF Ayı Uyumu | 15M: {htf_trend} + 5M Momentum)"
    else:
        # Choppy, conflicting timeframes, or indecisive market
        trend = "NEUTRAL"
        action = "HOLD"
        score = round(max(50.0, min(58.0, 50.0 + abs(bullish_pts - bearish_pts) * 0.1)), 1)
        macd_verdict = f"NÖTR (MTF Uyumsuzluğu | 15M: {htf_trend}, 5M: {'Boğa' if ltf_bullish else 'Ayı'} - Beklemede)"

    return {
        "price": last_price,
        "high": float(np.max(h)),
        "low": float(np.min(l)),
        "change_pct": change_pct,
        "ema9": ema9,
        "ema21": ema21,
        "ema50": ema50,
        "rsi": round(rsi, 1),
        "macd_hist": round(hist, 6),
        "macd_verdict": macd_verdict,
        "cmo": round(cmo, 1),
        "cci": round(cci, 1),
        "adx": round(adx_val, 1),
        "supertrend_dir": int(st_dir),
        "atr": atr,
        # Donchian(20) orta hat + önceki barın orta hattı (donchian_adx giriş modu — 2026-10-07)
        "donch_mid": round((max(highs[-20:]) + min(lows[-20:])) / 2.0, 6) if len(highs) >= 20 else None,
        "donch_mid_prev": round((max(highs[-21:-1]) + min(lows[-21:-1])) / 2.0, 6) if len(highs) >= 21 else None,
        "trend": trend,
        "action": action,
        "score": score,
        "htf_trend": htf_trend,
        "updated_at": time.time(),
    }


_LAST_FETCH_FAIL_LOG: Dict[str, float] = {}


def _sync_fetch_candles_for_symbol(fx_sym: str, yf_sym: str) -> Optional[Dict[str, Any]]:
    """Yahoo 5m mum verisi çeker. query1 başarısızsa query2 host'u denenir (datacenter IP'lerde
    futures uçları (GC=F) FX uçlarından yavaş/instabil — tek host + kısa timeout sembolü sessizce
    öldürüyordu: altın günlerce HOLD'da kaldı, log bile yazmıyordu)."""
    last_err: Optional[Exception] = None
    for host in ("query1", "query2"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{yf_sym}?interval=5m&range=2d"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                result = data["chart"]["result"][0]
                quote = result["indicators"]["quote"][0]
                opens = [o for o in quote.get("open", []) if o is not None]
                highs = [h for h in quote.get("high", []) if h is not None]
                lows = [l for l in quote.get("low", []) if l is not None]
                closes = [c for c in quote.get("close", []) if c is not None]
                if len(closes) >= 15:
                    _CLOSES_CACHE[fx_sym] = closes[-250:]
                    return _compute_technical_indicators(closes, highs, lows, opens, fx_sym)
        except Exception as exc:
            last_err = exc
            continue
    now = time.time()
    if now - _LAST_FETCH_FAIL_LOG.get(fx_sym, 0.0) > 300.0:
        _LAST_FETCH_FAIL_LOG[fx_sym] = now
        logger.warning("Yahoo veri hattı hatası: %s (%s) — %s", fx_sym, yf_sym, last_err)
    return None


def _sync_fetch_all_technical_data() -> Dict[str, Dict[str, Any]]:
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        future_map = {
            executor.submit(_sync_fetch_candles_for_symbol, fx, yf): fx
            for fx, yf in YAHOO_SYMBOL_MAP.items()
        }
        # Sürüm notu: as_completed(timeout=6.0) kullanılıyordu — yavaş bir sembol (GC=F)
        # zaman aşımını yakıp kalan sembollerin taze verisini de kaybettiriyordu.
        # Her fetch kendi urlopen timeout'uyla sınırlı olduğundan dış sınır gereksiz.
        for fut in concurrent.futures.as_completed(future_map):
            fx = future_map[fut]
            try:
                tech = fut.result()
                if tech:
                    results[fx] = tech
            except Exception:
                pass
    return results


def _sync_fetch_live_rates() -> Dict[str, float]:
    """Fetch real-world live FX rates from ECB/Frankfurter and fallback feeds."""
    rates_map: Dict[str, float] = {}
    try:
        req = urllib.request.Request(
            "https://api.frankfurter.app/latest?from=USD",
            headers={"User-Agent": "ScalperGlobal-Forex/1.0"},
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            r = data.get("rates", {})
            if "EUR" in r and r["EUR"] > 0:
                rates_map["EURUSD"] = round(1.0 / float(r["EUR"]), 5)
            if "GBP" in r and r["GBP"] > 0:
                rates_map["GBPUSD"] = round(1.0 / float(r["GBP"]), 5)
            if "JPY" in r and r["JPY"] > 0:
                rates_map["USDJPY"] = round(float(r["JPY"]), 3)
            if "CHF" in r and r["CHF"] > 0:
                rates_map["USDCHF"] = round(float(r["CHF"]), 5)
            if "AUD" in r and r["AUD"] > 0:
                rates_map["AUDUSD"] = round(1.0 / float(r["AUD"]), 5)
            if "CAD" in r and r["CAD"] > 0:
                rates_map["USDCAD"] = round(float(r["CAD"]), 5)
            if "NZD" in r and r["NZD"] > 0:
                rates_map["NZDUSD"] = round(1.0 / float(r["NZD"]), 5)
    except Exception:
        pass
    return rates_map


async def _refresh_live_rates_if_needed():
    """Update live prices and technical indicators cache asynchronously."""
    global _LAST_LIVE_FETCH_TIME, _LIVE_PRICES_CACHE, _TECHNICAL_CACHE, _LAST_TECH_FETCH_TIME
    now = time.time()

    # 1. Update Technical Indicators from Yahoo Finance candles every 15s
    if now - _LAST_TECH_FETCH_TIME > 15.0 or not _TECHNICAL_CACHE:
        _LAST_TECH_FETCH_TIME = now
        try:
            fresh_tech = await asyncio.to_thread(_sync_fetch_all_technical_data)
            if fresh_tech:
                # Bu turda BAŞARISIZ olan semboller (`_TECH_STALE_SEC`'ten eski) cache'ten
                # tahliye edilir: DXY dahil. Aksi halde DX-Y.NYB fetch'i bir kez
                # başarısız olunca `get_dxy_regime` sonsuza kadar son değeri döndürüp
                # rejimi donduruk bırakıyordu (#10). Tahliye edilen sembolün tick'i
                # varsayılana düşer (HOLD) ve veri gelince yeniden dolar.
                expired = [s for s in _TECHNICAL_CACHE if _tech_is_stale(s, now)]
                for s in expired:
                    _TECHNICAL_CACHE.pop(s, None)
                _TECHNICAL_CACHE.update(fresh_tech)
                mt5_connected = _MT5_STATE.get("connected") and (now - _MT5_STATE.get("last_ping", 0.0) < 60.0)
                for sym, tech in fresh_tech.items():
                    # MT5 köprüsü bağlı ve canlı broker kotasyonları akıyorsa,
                    # Yahoo vadeli (GC=F vb.) fiyatı broker spot fiyatının üzerine yazılmamalıdır.
                    if not (mt5_connected and sym in _LIVE_PRICES_CACHE):
                        _LIVE_PRICES_CACHE[sym] = tech["price"]
            # Korelasyon matrisi yalnızca bayatladığında yenilenir (varsayılan 30 dk)
            _FX_CORR.maybe_refresh(_CLOSES_CACHE)
        except Exception:
            pass

    # 2. Update ECB Frankfurter rates every 20s as robust fallback
    if now - _LAST_LIVE_FETCH_TIME > 20.0 or not _LIVE_PRICES_CACHE:
        _LAST_LIVE_FETCH_TIME = now
        try:
            fresh_fx = await asyncio.to_thread(_sync_fetch_live_rates)
            if fresh_fx:
                for sym, p in fresh_fx.items():
                    if sym not in _LIVE_PRICES_CACHE:
                        _LIVE_PRICES_CACHE[sym] = p
        except Exception:
            pass


async def _generate_realistic_ticks() -> Dict[str, Dict[str, Any]]:
    """Maintain live bid/ask/spread rates grounded in real live market technical indicators."""
    global _LAST_CACHE_TIME, _TICK_CACHE
    await _refresh_live_rates_if_needed()
    now = time.time()

    # Emekliye ayrılan semboller (USOIL/ETHUSD/SPX500) sıcak-reload sonrası
    # cache'te kalabiliyordu: `get_forex_radar` `ticks.items()` üzerinden
    # gittiği için hayalet satır olarak listede görünüyordu. Motor döngüsü
    # zaten yalnız FOREX_SYMBOLS üzerinde döndüğünden bu bir İŞLEM kararı
    # değil, liste temizliğidir; kaynağında kesiyoruz.
    universe = {item["symbol"] for item in FOREX_SYMBOLS}
    for stale in [s for s in _TICK_CACHE if s not in universe]:
        _TICK_CACHE.pop(stale, None)

    for item in FOREX_SYMBOLS:
        sym = item["symbol"]
        pip = item["pip_size"]
        digits = item["digits"]

        tech = _TECHNICAL_CACHE.get(sym)
        if tech and _tech_is_stale(sym, now):
            # Bayat gösterge: sinyal skoru/ATR güvenilmez (bkz. #5). Bu sembol için
            # gösterge varsayılanına düşülür (aşağıdaki `else` dalı → HOLD/50);
            # fiyat yine canlı kalır ve bir sonraki başarılı fetch'te düzelir.
            tech = None
        live_p = _LIVE_PRICES_CACHE.get(sym) or (tech["price"] if tech else item["default_price"])

        spread_pips = _LIVE_SPREAD_PIPS.get(sym) or (
            1.2 if item["category"] == "major" else (2.5 if item["category"] == "commodity" else (12.0 if item["category"] == "crypto" else 3.0))
        )
        spread_val = spread_pips * pip

        bid_p = round(live_p - spread_val / 2.0, digits)
        ask_p = round(live_p + spread_val / 2.0, digits)

        if tech:
            score = tech["score"]
            trend = tech["trend"]
            action = tech.get("action", "BUY" if trend == "BULLISH" else ("SELL" if trend == "BEARISH" else "HOLD"))
            rsi = tech["rsi"]
            macd_verdict = tech["macd_verdict"]
            cmo = tech.get("cmo", 0.0)
            cci = tech.get("cci", 0.0)
            adx = tech.get("adx", 25.0)
            st_dir = int(tech.get("supertrend_dir", 0))
            change_pct = tech["change_pct"]
            high_p = round(max(tech["high"], ask_p), digits)
            low_p = round(min(tech["low"], bid_p), digits)
            atr_val = tech["atr"]
        else:
            score = 50.0
            trend = "NEUTRAL"
            action = "HOLD"
            rsi = 50.0
            macd_verdict = "NÖTR (Veri Bekleniyor)"
            cmo = 0.0
            cci = 0.0
            adx = 25.0
            st_dir = 0
            change_pct = 0.0
            high_p = round(live_p * 1.002, digits)
            low_p = round(live_p * 0.998, digits)
            atr_val = 15.0 * pip

        _TICK_CACHE[sym] = {
            "symbol": sym,
            "display": item["display"],
            "name": item["name"],
            "category": item["category"],
            "tv_symbol": item["tv_symbol"],
            "bid": bid_p,
            "ask": ask_p,
            # `price` = orta fiyat. Frontend grafik/mum tüketicileri bu alanı
            # bekliyor (radar ucu da aynı anahtarı yayınlar); eksik olduğunda
            # `undefined` mum `close`una yazılıp grafiği patlatıyordu.
            "price": round(live_p, digits),
            "spread_pips": spread_pips,
            "change_pct": change_pct,
            "high": high_p,
            "low": low_p,
            "digits": digits,
            "pip_size": pip,
            "score": score,
            "trend": trend,
            "action": action,
            "rsi": rsi,
            "macd_verdict": macd_verdict,
            "cmo": cmo,
            "cci": cci,
            "adx": adx,
            "supertrend_dir": st_dir,
            "atr": atr_val,
            "volatility": "HIGH" if ("XAU" in sym or "GOLD" in sym) else "NORMAL",
            "updated_at": now,
        }

    return _TICK_CACHE


class LotCalculatorRequest(BaseModel):
    account_balance: float = Field(10000.0, ge=1.0, description="Account balance in USD")
    risk_percentage: float = Field(10.0, ge=0.1, le=10.0, description="Pozisyon hacmi risk bütçesi (% bakiye)")
    stop_loss_pips: float = Field(25.0, ge=1.0, description="Stop loss distance in pips")
    symbol: str = Field("EURUSD", description="Forex pair")


@router.get("/symbols")
async def list_forex_symbols():
    """Return all configured forex pairs and commodities."""
    return {"symbols": FOREX_SYMBOLS}


@router.get("/sessions")
async def get_market_sessions():
    """Return active global forex trading sessions."""
    sessions = _get_market_sessions()
    active_count = sum(1 for s in sessions if s["active"])
    return {
        "sessions": sessions,
        "active_sessions_count": active_count,
        "is_overlap": active_count >= 2,
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@router.get("/tickers")
async def get_forex_tickers(category: Optional[str] = None):
    """Return live tickers with bid/ask, spreads and daily changes."""
    ticks = await _generate_realistic_ticks()
    results = list(ticks.values())
    if category:
        results = [t for t in results if t["category"] == category]
    return {
        "tickers": results,
        "sessions": _get_market_sessions(),
        "timestamp": time.time(),
    }


_KLINES_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_KLINES_CACHE_TTL = 4.0  # 4 sn in-memory kline önbellek (Yahoo hızlandırıcı)
# Vadeli↔spot baz farkı eşikleri (bkz. `_fetch_forex_klines` son-bar bloğu):
# `_KLINE_BASIS_SHIFT_REL` üzerindeki fark normal tick değil, veri kaynağı baz
# farkı sayılır ve tüm seri kaydırılır; `_KLINE_MAX_TICK_REL` üzerindeki fark ise
# uçuk/bad tick kabul edilip yok sayılır (seri kirletilmez).
_KLINE_BASIS_SHIFT_REL = 0.0015   # %0.15 — bunun üstü baz farkı → tüm seriyi kaydır
_KLINE_MAX_TICK_REL = 0.15        # %15 — bunun üstü bad tick → hiç uygulama

# MT5 (broker) mum önbelleği: köprü, panelin BAKTIĞI (sembol, periyot) çiftleri
# için broker'ın gerçek OHLC'sini push eder. Anahtar `"SYMBOL|interval"`.
# Bu kaynak kullanılırsa geçmiş + canlı AYNI broker kotasyonudur → vadeli/spot
# baz farkı SIFIR olur (bkz. _KLINE_BASIS_SHIFT_REL, XAUUSD GC=F sorunu).
_MT5_CANDLES_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_MT5_CANDLES_TTL = 30.0  # Köprü ~1.5 sn'de bir push eder; 30 sn bayat toleransı
# Panelin son bakılan forex (sembol, periyot) çiftleri: köprüye "ne çekeceğini"
# söylemek için. TTL dolan çiftler düşer (bant genişliği korunur).
_FOREX_VIEWED: Dict[Tuple[str, str], float] = {}
_FOREX_VIEWED_TTL = 120.0
_MT5_WATCH_MAX = 12  # Köprüye tek turda istenebilecek azami çift


def _note_forex_viewed(symbol: str, interval: str) -> None:
    """Panel bu (sembol, periyot) mumlarını istedi → köprüye izletilecekler listesine ekle."""
    sym = str(symbol or "").replace("/", "").replace("_", "").replace("-", "").strip().upper()
    if not sym or not interval:
        return
    _FOREX_VIEWED[(sym, interval)] = time.time()


def _get_forex_watch() -> List[Dict[str, str]]:
    """Son `_FOREX_VIEWED_TTL` içinde bakılan çiftler (bayat olanlar budanır)."""
    now = time.time()
    out: List[Dict[str, str]] = []
    for (sym, tf), ts in list(_FOREX_VIEWED.items()):
        if now - ts > _FOREX_VIEWED_TTL:
            _FOREX_VIEWED.pop((sym, tf), None)
            continue
        out.append({"symbol": sym, "interval": tf})
    return out[:_MT5_WATCH_MAX]


def _fetch_mt5_candles(clean_sym: str, interval: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    """Köprüden taze gelen broker mumlarını döndür (yoksa/bayatsa `None`)."""
    entry = _MT5_CANDLES_CACHE.get(f"{clean_sym}|{interval}")
    if not entry:
        return None
    ts, bars = entry
    if not bars or (time.time() - ts) > _MT5_CANDLES_TTL:
        return None
    return bars[-limit:]



def _fetch_forex_klines(symbol: str, interval: str = "5m", limit: int = 250) -> List[Dict[str, Any]]:
    clean_sym = symbol.replace("/", "").replace("_", "").replace("-", "").strip().upper()
    alias_map = {
        "GOLD": "XAUUSD",
        "ALTIN": "XAUUSD",
        "SILVER": "XAGUSD",
        "GUMUS": "XAGUSD",
        "BTC": "BTCUSD",
        "ETH": "ETHUSD",
    }
    clean_sym = alias_map.get(clean_sym, clean_sym)

    yf_sym = YAHOO_SYMBOL_MAP.get(clean_sym)
    if not yf_sym:
        for k, v in YAHOO_SYMBOL_MAP.items():
            if k.upper() == clean_sym:
                yf_sym = v
                clean_sym = k
                break
    if not yf_sym:
        yf_sym = f"{clean_sym}=X"

    cache_key = f"{clean_sym}:{interval}"
    now = time.time()
    if cache_key in _KLINES_CACHE:
        cached_ts, cached_bars = _KLINES_CACHE[cache_key]
        if now - cached_ts < _KLINES_CACHE_TTL and cached_bars:
            return cached_bars[-limit:]

    # 1) MT5 (BROKER) KAYNAĞI — ÖNCELİKLİ (2026-10-07, kullanıcı isteği):
    # Köprü, panelin baktığı çiftler için broker'ın GERÇEK XAUUSD/EURUSD mumlarını
    # push eder. Bu kaynak hem geçmiş hem canlı olduğu için vadeli↔spot baz farkı
    # SIFIR olur (aşağıdaki basis-shift bloğuna hiç gerek kalmaz) ve grafik, işlem
    # gören fiyatla birebir aynı olur. Köprü yoksa/bayatsa Yahoo'ya düşülür.
    mt5_bars = _fetch_mt5_candles(clean_sym, interval, limit)
    if mt5_bars:
        return mt5_bars

    interval_map = {
        "1m": ("1m", "2d"),
        "5m": ("5m", "5d"),
        "15m": ("15m", "10d"),
        "30m": ("30m", "20d"),
        "1h": ("60m", "60d"),
        "60m": ("60m", "60d"),
        "4h": ("60m", "120d"),
        "240m": ("60m", "120d"),
        "1d": ("1d", "1y"),
        "D": ("1d", "1y"),
    }
    yf_interval, yf_range = interval_map.get(interval, ("5m", "5d"))

    bars: List[Dict[str, Any]] = []
    digits = 5
    if clean_sym in ("USDJPY", "GBPJPY", "EURJPY"):
        digits = 3
    elif clean_sym in ("XAUUSD", "NAS100", "US30", "SPX500", "BTCUSD", "ETHUSD", "USOIL"):
        digits = 2

    for host in ("query1", "query2"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{yf_sym}?interval={yf_interval}&range={yf_range}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                res = data["chart"]["result"][0]
                timestamps = res.get("timestamp", [])
                quote = res["indicators"]["quote"][0]
                opens = quote.get("open", [])
                highs = quote.get("high", [])
                lows = quote.get("low", [])
                closes = quote.get("close", [])
                volumes = quote.get("volume", [0] * len(timestamps))

                for i, t in enumerate(timestamps):
                    if i >= len(opens) or i >= len(highs) or i >= len(lows) or i >= len(closes):
                        continue
                    o, h, l, c = opens[i], highs[i], lows[i], closes[i]
                    v = volumes[i] if i < len(volumes) and volumes[i] is not None else 0
                    if None not in (o, h, l, c):
                        bars.append({
                            "time": int(t),
                            "open": round(float(o), digits),
                            "high": round(float(h), digits),
                            "low": round(float(l), digits),
                            "close": round(float(c), digits),
                            "volume": float(v) if v else 0.0,
                        })
                if bars:
                    break
        except Exception:
            continue

    if interval in ("4h", "240m") and bars:
        resampled = []
        groups: Dict[int, List[Dict[str, Any]]] = {}
        for b in bars:
            bucket = (b["time"] // 14400) * 14400
            if bucket not in groups:
                groups[bucket] = []
            groups[bucket].append(b)
        for bucket in sorted(groups.keys()):
            gbars = groups[bucket]
            resampled.append({
                "time": bucket,
                "open": gbars[0]["open"],
                "high": max(x["high"] for x in gbars),
                "low": min(x["low"] for x in gbars),
                "close": gbars[-1]["close"],
                "volume": sum(x.get("volume", 0) for x in gbars),
            })
        bars = resampled

    if bars:
        live_tick = _LIVE_PRICES_CACHE.get(clean_sym)
        if live_tick and live_tick > 0 and len(bars) > 0:
            last_bar = bars[-1]
            live_close = round(float(live_tick), digits)
            # VADELİ ↔ SPOT BAZ FARKI (2026-10-07): XAUUSD geçmişi Yahoo `GC=F`
            # (COMEX vadeli altın) ile çekilirken canlı fiyat MT5 spot kotasyonudur.
            # İkisi arasında sürekli bir baz farkı vardır (ör. vadeli 4135 / spot
            # 4108 → ~%0.6). Eskiden YALNIZ son mumun close/high/low'u canlı fiyata
            # çekiliyordu; bu, düz seyreden seride tek mumda ~26$'lik SAHTE bir
            # flash-crash çubuğu üretiyor, Bollinger/MACD'yi de tek barda patlatıyordu.
            # Çözüm: fark küçükse (normal tick) yalnız son mum güncellenir; fark baz
            # farkı kadar büyükse (ama uçuk/bad-tick değilse) TÜM seri aynı delta ile
            # kaydırılır → mum şekilleri korunur, seviye spota hizalanır.
            ref_close = float(last_bar["close"])
            delta = live_close - ref_close
            rel = abs(delta) / ref_close if ref_close > 0 else 0.0
            if rel > _KLINE_BASIS_SHIFT_REL and rel <= _KLINE_MAX_TICK_REL:
                shift = round(delta, digits)
                for b in bars:
                    b["open"] = round(float(b["open"]) + shift, digits)
                    b["high"] = round(float(b["high"]) + shift, digits)
                    b["low"] = round(float(b["low"]) + shift, digits)
                    b["close"] = round(float(b["close"]) + shift, digits)
            elif rel <= _KLINE_MAX_TICK_REL:
                last_bar["close"] = live_close
                last_bar["high"] = max(last_bar["high"], live_close)
                last_bar["low"] = min(last_bar["low"], live_close)
            # rel > MAX_TICK_REL → uçuk/bad tick; seriyi kirletmemek için yok say.

        _KLINES_CACHE[cache_key] = (now, bars)
        return bars[-limit:]

    if cache_key in _KLINES_CACHE:
        return _KLINES_CACHE[cache_key][1][-limit:]
    return []


@router.get("/klines")
async def get_forex_klines(
    symbol: str = Query(..., description="Forex symbol, e.g. EURUSD, XAUUSD"),
    interval: str = Query("5m", description="Candle interval (1m, 5m, 15m, 30m, 1h, 4h, 1d)"),
    limit: int = Query(250, ge=10, le=1000, description="Max candle count"),
):
    """Return historical and live candlestick data for Lightweight Charts."""
    # Görüntüleme takibi: köprüye "bu çifti brokertan çek" demek için ve WS canlı
    # yayınına almak için. `_note_forex_viewed` bayat çiftleri TTL ile budar.
    _note_forex_viewed(symbol, interval)
    try:
        from app.ws_live_candles import note_viewed as _ws_note_viewed
        _ws_note_viewed(symbol, interval)
    except Exception:
        pass
    loop = asyncio.get_running_loop()
    bars = await loop.run_in_executor(None, _fetch_forex_klines, symbol, interval, limit)
    clean_sym = symbol.replace("/", "").replace("_", "").replace("-", "").strip().upper()
    meta = next((s for s in FOREX_SYMBOLS if s["symbol"] == clean_sym), None)
    current_price = bars[-1]["close"] if bars else (meta.get("default_price", 0.0) if meta else 0.0)
    return {
        "symbol": clean_sym,
        "interval": interval,
        "count": len(bars),
        "candles": bars,
        "current_price": current_price,
        "meta": meta,
    }


def _evaluate_signal_gate(
    sym: str,
    cand: Dict[str, Any],
    current_utc_hour: int,
    dxy_regime: Optional[Dict[str, Any]],
    has_open_position: bool = False,
) -> Dict[str, Any]:
    """Bir radar adayının otonom giriş kapılarından geçip geçmediğini değerlendirir.

    Amaç: panelde "algoritma güçlü sinyal buluyor mu?" sorusunun cevabı, otonom
    motorun GERÇEK giriş kararıyla aynı olsun. Ayrı bir eşik koymak paneli
    yalancı yapardı — kullanıcı "AL" görüp motordan işlem beklerken motor sessiz
    kalırdı. Bu yüzden kapı sırası `_forex_auto_paper_loop` ile birebir aynıdır.

    Sıra önemlidir: ilk düşen kapı `blocked_by` olur ve `primary_blocker` ile
    kullanıcıya "neden işlem yok" tek cümleyle söylenir.

    DİKKAT: Burada durum DEĞİŞTİRİLMEZ (soğuma sayacı güncellenmez, log
    basılmaz) — uç nokta salt okunur kalmalı; aksi halde panel her 3 saniyede
    bir soğuma kalkanını yeniden başlatıp motoru kilitleyebilirdi.
    """
    reasons: List[str] = []

    # NOT: `_AUTO_SETTINGS.allowed_symbols` (varsayılan: XAUUSD + BTCUSD) burada
    # KAPIDIR — o kısıt yalnızca özel BTC+Altın izleme sayfasına aittir. Genel
    # forex radarı tüm majörleri/emtiaları tarar; aksi halde panel 15 sembolü
    # listeler ama 13'ünü "izin yok" diye eler ve radar işe yaramaz hale gelirdi.
    direction = cand.get("action", "")
    if direction not in ("BUY", "SELL"):
        reasons.append("direction")

    if _AUTO_SETTINGS.dxy_filter_enabled:
        veto = dxy_entry_veto(sym, direction, dxy_regime)
        if veto == "dxy_conflict":
            reasons.append("dxy")

    gate = major_entry_gate_decision(
        sym, current_utc_hour, float(cand.get("atr_pips", 0.0)),
        _AUTO_SETTINGS.major_session_filter,
        _AUTO_SETTINGS.major_session_start_utc, _AUTO_SETTINGS.major_session_end_utc,
        _AUTO_SETTINGS.major_min_atr_pips,
    )
    if gate:
        reasons.append(gate)

    effective_max_spread = (
        max(50.0, _AUTO_SETTINGS.max_spread_pips * 10) if ("BTC" in sym or "ETH" in sym)
        else _AUTO_SETTINGS.max_spread_pips
    )
    if cand.get("spread_pips", 99.0) > effective_max_spread:
        reasons.append("spread")

    is_commodity = ("XAU" in sym or "GOLD" in sym or "OIL" in sym)
    if sym == "BTCUSD":
        req_score = _AUTO_SETTINGS.btc_min_score if _AUTO_SETTINGS.btc_min_score > 0 else _AUTO_SETTINGS.min_score
    else:
        req_score = 78.0 if is_commodity else _AUTO_SETTINGS.min_score
    # DXY nötr rejimde zayıf semboller (altın/JPY/CHF) +5.0 ekstra puan ister.
    if _AUTO_SETTINGS.dxy_filter_enabled and dxy_entry_veto(sym, direction, dxy_regime) == "dxy_strict_neutral":
        req_score += 5.0
    if cand.get("score", 0.0) < req_score:
        reasons.append("score")

    if _AUTO_SETTINGS.adx_filter_enabled and float(cand.get("adx", 25.0)) < _AUTO_SETTINGS.adx_min:
        reasons.append("adx")

    st_dir = int(cand.get("supertrend_dir", 0))
    if _AUTO_SETTINGS.supertrend_filter_enabled and st_dir != 0:
        if (direction == "BUY" and st_dir < 0) or (direction == "SELL" and st_dir > 0):
            reasons.append("supertrend")

    if _AUTO_SETTINGS.correlation_guard:
        bias = get_usd_bias(sym, direction)
        if bias != "USD_NEUTRAL":
            corr_positions = [
                (str(p.get("symbol", "")).upper(), get_usd_bias(p.get("symbol", ""), p.get("direction", "BUY")))
                for p in list(_MT5_STATE.get("open_positions", [])) + list(_AUTO_STATE.get("open_positions", []))
            ]
            # Motor kapısı bekleyen OPEN_ORDER'ları da korelogramaya katar
            # (:2992-2997). Radar bunları atladığı için, motor bir emri kuyruğa
            # alıp radar bir sonraki taramada ikinci aynı-bias girişi
            # değerlendirdiğinde radar "STRONG sinyal" gösterip motorun
            # korelasyonda engelleyeceği işlemi işaret edebiliyordu (#8). Panel
            # göstergesi motor kararına uysun diye aynı küme kurulur.
            for c in _MT5_STATE.get("pending_commands", []):
                if c.get("action") == "OPEN_ORDER":
                    corr_positions.append((
                        str(c.get("symbol", "")).upper(),
                        get_usd_bias(c.get("symbol", ""), c.get("direction", "BUY")),
                    ))
            ok, _why = _FX_CORR.cluster_check(sym, bias, corr_positions)
            if not ok:
                reasons.append("correlation")

    if has_open_position:
        reasons.append("open_position")

    ready = len(reasons) == 0
    market_blockers = [r for r in reasons if r in _MARKET_BLOCKERS]

    # Sıralama: piyasa kalitesi engelleri ÖNCE. Aksi halde "izin listesinde
    # değil" gibi bir panel ayarı, "ölü piyasa / zayıf trend" gibi gerçek
    # piyasa gerekçesini maskeler ve kullanıcı sembolü ekleyince sinyal
    # geleceğini sanar (oysa EUR/USD skor 96 ama ATR tabanının altında).
    reasons_sorted = market_blockers + [r for r in reasons if r not in _MARKET_BLOCKERS]

    return {
        "signal_ready": ready,
        "gate_passed": not market_blockers,
        "market_blockers": market_blockers,
        "blocked_by": reasons_sorted,
        "primary_blocker": reasons_sorted[0] if reasons_sorted else None,
        "required_score": round(req_score, 1),
    }


# Kapı kodu → kullanıcıya gösterilecek tek cümlelik Türkçe gerekçe.
# Panelde "neden sinyal yok" sorusunun cevabı; jargonsuz ve eylem odaklı.
_GATE_LABELS: Dict[str, str] = {
    "direction": "Yön belirsiz (ne AL ne SAT)",
    "score": "Radar skoru giriş eşiğinin altında",
    "spread": "Spread limitin üzerinde",
    "dxy": "Dolar endeksi (DXY) rejimiyle çelişiyor",
    "major_session": "Majör seans penceresi dışında (Asya chop'u)",
    "major_min_atr": "Volatilite tabanının altında (ölü piyasa)",
    "adx": "Trend gücü zayıf (ADX kalkanı)",
    "supertrend": "SuperTrend yönüyle çelişiyor",
    "correlation": "Korelasyon kalkanı: aynı yönde yoğunlaşma",
    "open_position": "Bu sembolde zaten açık pozisyon var",
}
# Piyasa kalitesi engelleri. `open_position` BURADA DEĞİL: o piyasanın değil,
# mevcut durumun sonucu. Ayrım kritik — kullanıcı "sinyal yok"u "piyasa kötü"
# sanmasın, "bu parite şu an giriş kalitesinde değil" ile "zaten pozisyonum
# var"ı ayırt edebilsin.
_MARKET_BLOCKERS = frozenset({
    "direction", "score", "spread", "adx", "supertrend",
    "dxy", "major_session", "major_min_atr", "correlation",
})


@router.get("/radar")
async def get_forex_radar():
    """Forex radar taraması: gerçek göstergelerle güçlü işlem sinyalleri.

    İki katmanlı sonuç döner:
      - `signals`   → tüm kapıları geçen, motorun gerçekten işlem açacağı
                      adaylar ("güçlü sinyal"). Bu liste boşsa piyasada şu an
                      giriş kalitesinde fırsat yok demektir.
      - `candidates` → tüm tarama (skora göre sıralı), her biri hangi kapıda
                      takıldığı bilgisiyle. Panel bunu "izleme" olarak gösterir.

    Kritik ayrım: `score` yönlü bir güç puanıdır ve HOLD durumunda da 50-58
    bandında döner. Bu yüzden "güçlü" etiketi skora değil, kapıların geçilmesine
    bağlanır — aksi halde yönsüz piyasada 20 sembol "güçlü sinyal" gibi listelenir.
    """
    ticks = await _generate_realistic_ticks()
    dxy_regime = get_dxy_regime()
    current_utc_hour = datetime.datetime.now(datetime.timezone.utc).hour

    # Açık pozisyonu olan semboller (MT5 + paper + bekleyen emirler) — motorun
    # anti-duplicate kapısıyla aynı kaynak.
    active_syms = {str(p.get("symbol", "")).upper() for p in _MT5_STATE.get("open_positions", [])}
    active_syms |= {str(p.get("symbol", "")).upper() for p in _AUTO_STATE.get("open_positions", [])}
    active_syms |= {
        str(c.get("symbol", "")).upper()
        for c in _MT5_STATE.get("pending_commands", [])
        if c.get("action") == "OPEN_ORDER"
    }

    candidates = []
    for sym, t in ticks.items():
        sym_u = sym.upper()
        score = t.get("score", 45.0)
        trend = t.get("trend", "NEUTRAL")
        action = t.get("action", "BUY" if trend == "BULLISH" else ("SELL" if trend == "BEARISH" else "HOLD"))
        spread = t.get("spread_pips", 1.5)
        atr_pips = round(t.get("atr", 0.001) / t["pip_size"], 1) if t.get("pip_size", 0) > 0 else 15.0
        st_dir = int(t.get("supertrend_dir", 0))

        spec = get_symbol_trading_specs(
            sym,
            base_sl=_AUTO_SETTINGS.sl_pips,
            base_tp=_AUTO_SETTINGS.tp_pips,
            atr_pips=atr_pips,
        )

        base = {
            "symbol": sym,
            "display": t["display"],
            "name": t["name"],
            "category": t["category"],
            "price": t["ask"],
            "bid": t["bid"],
            "ask": t["ask"],
            "spread_pips": spread,
            "score": score,
            "trend": trend,
            "action": action,
            "rsi_15m": t.get("rsi", 50.0),
            "macd_verdict": t.get("macd_verdict", "NÖTR (Beklemede)"),
            "cmo": t.get("cmo", 0.0),
            "cci": t.get("cci", 0.0),
            "adx": t.get("adx", 25.0),
            "supertrend_dir": st_dir,
            "htf_trend": t.get("htf_trend", "NEUTRAL"),
            "pip_target": spec["tp_pips"],
            "stop_loss_pips": spec["sl_pips"],
            "risk_reward": f"1:{round(spec['tp_pips'] / spec['sl_pips'], 2)}" if spec["sl_pips"] > 0 else "1:1.83",
            "atr_pips": atr_pips,
            "tv_symbol": t["tv_symbol"],
        }

        gate = _evaluate_signal_gate(
            sym_u, base, current_utc_hour, dxy_regime,
            has_open_position=sym_u in active_syms,
        )
        base.update(gate)
        base["has_open_position"] = bool(sym_u in active_syms)
        base["blocker_text"] = _GATE_LABELS.get(gate["primary_blocker"] or "", "")
        # Sinyal gücü kademesi. Kademe piyasa kalitesini (gate_passed) ve
        # kullanıcının yapabileceği eylemi ayrı gösterir — panelde rozet bu.
        if gate["signal_ready"]:
            base["tier"] = "STRONG"          # motor şu an işlem açabilir
        elif gate["gate_passed"]:
            # Piyasa onaylı; engel yalnızca mevcut açık pozisyon.
            base["tier"] = "ACTIVE"
        elif all(r in ("major_session", "major_min_atr") for r in gate["blocked_by"]) and action in ("BUY", "SELL"):
            # Kalite kapıları temiz; yalnızca zamanlama (seans/volatilite) kapalı.
            base["tier"] = "WATCH"
        else:
            base["tier"] = "WAIT"

        candidates.append(base)

    # Sıralama: güçlü sinyaller önce, sonra skor. Panelin ilk gördüğü satır
    # her zaman en yüksek kaliteli aday olur.
    tier_rank = {"STRONG": 0, "ACTIVE": 1, "WATCH": 2, "WAIT": 3}
    candidates.sort(key=lambda x: (tier_rank.get(x["tier"], 9), -x["score"]))

    signals = [c for c in candidates if c["tier"] == "STRONG" and not c.get("has_open_position")]

    return {
        "candidates": candidates,
        # `signals` = motora göre şu an işlem açılabilecek adaylar (radarın özü).
        "signals": signals,
        "active_symbols": list(active_syms),
        "scan_note": _radar_scan_note(candidates, current_utc_hour),
        "sessions": _get_market_sessions(),
        "dxy": dxy_regime,
        "thresholds": {
            "min_score": _AUTO_SETTINGS.min_score,
            "btc_min_score": _AUTO_SETTINGS.btc_min_score,
            "commodity_min_score": 78.0,
            "max_spread_pips": _AUTO_SETTINGS.max_spread_pips,
            "adx_filter_enabled": _AUTO_SETTINGS.adx_filter_enabled,
            "adx_min": _AUTO_SETTINGS.adx_min,
            "supertrend_filter_enabled": _AUTO_SETTINGS.supertrend_filter_enabled,
            "major_session_filter": _AUTO_SETTINGS.major_session_filter,
            "major_session_utc": f"{_AUTO_SETTINGS.major_session_start_utc:02d}:00–{_AUTO_SETTINGS.major_session_end_utc:02d}:00 UTC",
            "major_min_atr_pips": _AUTO_SETTINGS.major_min_atr_pips,
        },
        "total": len(candidates),
        "updated_at": time.time(),
    }


def _radar_scan_note(candidates: List[Dict[str, Any]], utc_hour: int) -> str:
    """Tarama durumunu tek cümleyle özetler — panelde canlı durum satırı.

    Sinyal YOKKEN en sık nedeni söyler; "piyasa kötü" ile "ayarın kapalı"yı
    ayırır ki kullanıcı ne yapacağını bilsin (sembolü aç ya da bekle).
    """
    if not candidates:
        return "Tarama başladı: mum verisi bekleniyor."

    strong = [c for c in candidates if c["tier"] == "STRONG"]
    if strong:
        names = ", ".join(c["display"] for c in strong[:3])
        extra = f" (+{len(strong) - 3} daha)" if len(strong) > 3 else ""
        return f"{len(strong)} güçlü sinyal: {names}{extra}"

    counts: Dict[str, int] = {}
    for c in candidates:
        key = c.get("primary_blocker") or "ready"
        counts[key] = counts.get(key, 0) + 1
    top_key, top_n = max(counts.items(), key=lambda kv: kv[1])

    return (
        f"Şu an giriş kalitesinde sinyal yok — en yaygın engel: "
        f"{_GATE_LABELS.get(top_key, top_key)} ({top_n} sembol)."
    )


# ============================================================================
# BTC-GOLD SAYFASI — ANLIK OTOMATİK YORUM (kural tabanlı, insan-okur Türkçe)
# Frontend 60 sn'de bir /btc-gold/comment çağırır; gösterge cache'inden
# 3-5 cümlelik sade bir piyasa yorumu sentezlenir (LLM çağrısı yok → hızlı+ücretsiz).
# ============================================================================

def _adx_trend_words(adx: float) -> str:
    if adx >= 40:
        return "çok güçlü"
    if adx >= 30:
        return "güçlü"
    if adx >= 20:
        return "belirginleşen"
    if adx >= 15:
        return "zayıf"
    return "çok zayıf (yatay baskı)"


def _strength_label(score: float) -> str:
    if score >= 90:
        return "ÇOK GÜÇLÜ"
    if score >= 80:
        return "GÜÇLÜ"
    if score >= 70:
        return "İLIMLI"
    if score >= 60:
        return "ZAYIF"
    return "BELİRSİZ"


def _price_position_note(price: float, high: float, low: float) -> str:
    band = high - low
    if band <= 0:
        return ""
    pos = (price - low) / band
    if pos >= 0.85:
        return "fiyat gün içi zirvesine yakın"
    if pos <= 0.15:
        return "fiyat gün içi dibine yakın"
    if pos >= 0.6:
        return "fiyat gün bandının üst yarısında"
    if pos <= 0.4:
        return "fiyat gün bandının alt yarısında"
    return "fiyat gün bandının ortasında nefes alıyor"


def _human_symbol_comment(symbol: str, tick: Dict[str, Any], min_score: float,
                          dxy_regime: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Tek sembol için 3-5 cümlelik sade Türkçe yorum sentezler.

    Kaynak: teknik göstergeler (RSI/CCI/CMO/ADX/SuperTrend/ATR), motor skoru,
    giriş eşiği (min_score / btc_min_score), gün içi fiyat bandı ve DXY rejimi.
    """
    score = float(tick.get("score", 50.0))
    trend = str(tick.get("trend", "NEUTRAL"))
    action = str(tick.get("action", "HOLD"))
    rsi = float(tick.get("rsi", 50.0))
    cci = float(tick.get("cci", 0.0))
    cmo = float(tick.get("cmo", 0.0))
    adx = float(tick.get("adx", 20.0))
    st_dir = int(tick.get("supertrend_dir", 0))
    atr = float(tick.get("atr", 0.0))
    pip_size = float(tick.get("pip_size", 0.1))
    atr_pips = atr / pip_size if pip_size > 0 else 0.0
    price = float(tick.get("ask", 0.0) or tick.get("bid", 0.0))
    high = float(tick.get("high", 0.0) or price)
    low = float(tick.get("low", 0.0) or price)
    vol = str(tick.get("volatility", "NORMAL"))

    yon = "yukarı" if trend == "BULLISH" else ("aşağı" if trend == "BEARISH" else "yatay")
    adx_w = _adx_trend_words(adx)
    st_yon = {1: "yukarı", -1: "aşağı", 0: "kararsız"}.get(st_dir, "kararsız")

    sentences: List[str] = []

    # 1) Trend cümlesi
    if adx >= 25 and trend != "NEUTRAL":
        sentences.append(f"Trend {adx_w} (ADX {adx:.0f}) ve yönü {yon}; SuperTrend {st_yon} yönünü onaylıyor.")
    elif trend != "NEUTRAL":
        sentences.append(
            f"Trend {yon} yönünde ama gücü henüz zayıf (ADX {adx:.0f}) — teyit gelmeden riskli."
        )
    else:
        sentences.append(f"Trend gücü zayıf (ADX {adx:.0f}) — piyasa yatay sıkışmada, yön arıyor.")

    # 2) Momentum cümlesi (RSI ana; CCI/CMO kısa vade)
    if rsi >= 70:
        momentum = f"aşırı alım bölgesinde (RSI {rsi:.1f}) — tepe riski var"
    elif rsi >= 55:
        momentum = f"momentum alıcıların elinde (RSI {rsi:.1f})"
    elif rsi <= 30:
        momentum = f"aşırı satım bölgesinde (RSI {rsi:.1f}) — dip bölgesi"
    elif rsi <= 45:
        momentum = f"momentum satıcıların elinde (RSI {rsi:.1f})"
    else:
        momentum = f"momentum nötr (RSI {rsi:.1f})"

    short_neutral = abs(cci) < 30 and abs(cmo) < 5
    if short_neutral and 45 <= rsi < 70:
        momentum += f"; ama kısa vadeli göstergeler nötrleşmiş (CCI {cci:.0f}, CMO {cmo:+.1f}) — piyasa nefes alıyor"
    elif cci >= 100:
        momentum += f"; CCI {cci:.0f} ile güçlü momentum teyidi var"
    elif cci <= -100:
        momentum += f"; CCI {cci:.0f} ile satış baskısı teyitli"
    sentences.append(f"Momentum tarafında {momentum}.")

    # 3) Fiyat konumu
    pos_note = _price_position_note(price, high, low)
    if pos_note:
        sentences.append(f"{pos_note[0].upper()}{pos_note[1:]} (gün bandı {low:,.0f} – {high:,.0f}).")

    # 4) Karar cümlesi — motor eşiğiyle karşılaştır
    if action in ("BUY", "SELL") and score >= min_score:
        marj = score - min_score
        if short_neutral or vol == "HIGH":
            risk = "girişte kısa bir bekleme/tolerans bölgesi iyi olur"
        elif rsi >= 70 or rsi <= 30:
            risk = "aşırı uç göstergelere karşı lot küçük tutulmalı"
        else:
            risk = "sinyal taze, plan doğrultusunda işlem edilebilir"
        sentences.append(
            f"{action} sinyali geçerli: skor {score:.1f}, giriş eşiğini {marj:.1f} puan marjla aşıyor — {risk}."
        )
    elif action in ("BUY", "SELL"):
        sentences.append(
            f"{action} adayı var ama skor {score:.1f}, giriş eşiği {min_score:.0f}'in altında — "
            "henüz işlem değil, izlenmeye devam."
        )
    else:
        sentences.append(f"Sinyal yok (HOLD): skor {score:.1f}, yön belirsiz — beklemek en doğru hamle.")

    # 5) Bağlam notu — DXY (XAU/BTC muaf ama rejim uyumu bilgi değeri taşır)
    if dxy_regime:
        regime = dxy_regime.get("regime", "USD_NEUTRAL")
        dxy_trend = dxy_regime.get("trend", "NEUTRAL")
        if regime == "USD_WEAK":
            uyum = "dolar zayıflığı USD karşıtı bu sembolü destekliyor" if not symbol.startswith("USD") \
                else "dolar zayıflığı bu sembole baskı yapıyor"
        elif regime == "USD_STRONG":
            uyum = "dolar güçleniyor, USD karşıtı semboller için ters rüzgar" if not symbol.startswith("USD") \
                else "dolar güçleniyor, bu sembolü destekliyor"
        else:
            uyum = "dolar sıkışık rejimde, belirleyici değil"
        sentences.append(f"DXY {regime.replace('USD_', '')} ({dxy_trend}): {uyum}.")

    # 6) Volatilite uyarısı
    if vol == "HIGH" and atr_pips > 0:
        sentences.append(f"Volatilite yüksek (ATR {atr_pips:.0f} pip) — stop mesafesi ve lot boyu buna göre planlanmalı.")

    return {
        "symbol": symbol,
        "display": tick.get("display", symbol),
        "action": action,
        "score": round(score, 1),
        "strength_label": _strength_label(score),
        "comment": " ".join(sentences),
    }


@router.get("/btc-gold/comment")
async def get_btc_gold_auto_comment():
    """BTC-Gold sayfası için anlık otomatik yorum.

    Frontend 60 sn'de bir çağırır. Her çağrıda güncel gösterge cache'inden
    insan-okur yorum üretilir; ayrı bir LLM çağrısı yapılmaz.
    """
    ticks = await _generate_realistic_ticks()
    dxy = get_dxy_regime()
    sessions = _get_market_sessions()
    active_sessions = [s["name"] for s in sessions if s.get("active")]
    mt5_ok = bool(_MT5_STATE.get("connected") and (time.time() - _MT5_STATE.get("last_ping", 0.0) < 60.0))

    symbols_out: Dict[str, Any] = {}
    for sym in ("XAUUSD", "BTCUSD"):
        tick = ticks.get(sym) or _TECHNICAL_CACHE.get(sym)
        if not tick:
            symbols_out[sym] = {
                "symbol": sym,
                "display": sym,
                "action": "HOLD",
                "score": 0.0,
                "strength_label": "BELİRSİZ",
                "comment": "Veri hattı henüz hazır değil — birkaç saniye sonra tekrar denenecek.",
            }
            continue
        min_score = _AUTO_SETTINGS.btc_min_score if sym == "BTCUSD" else _AUTO_SETTINGS.min_score
        symbols_out[sym] = _human_symbol_comment(sym, tick, float(min_score), dxy)

    # Genel piyasa notu (sayfa üstü tek satır)
    dxy_note = ""
    if dxy:
        regime = dxy.get("regime", "USD_NEUTRAL")
        if regime == "USD_WEAK":
            dxy_note = f"Dolar zayıf (DXY {dxy.get('trend', '')}) — altın ve BTC lehine rüzgar."
        elif regime == "USD_STRONG":
            dxy_note = f"Dolar güçlü (DXY {dxy.get('trend', '')}) — altın ve BTC için ters rüzgar."
        else:
            dxy_note = "Dolar sıkışık — yönlü baskı yok."
    session_note = f"Aktif seans: {', '.join(active_sessions)}." if active_sessions else "Seanslar arasında geçiş — likidite düşük olabilir."
    source_note = "Fiyat kaynağı: MT5 canlı köprü." if mt5_ok else "Fiyat kaynağı: Yahoo/Binance veri hattı (MT5 köprüsü kapalı)."

    return {
        "interval_sec": 60,
        "generated_at": time.time(),
        "market_note": " ".join(x for x in (dxy_note, session_note, source_note) if x),
        "symbols": symbols_out,
    }


@router.post("/calculate-lot")
async def calculate_lot_size(req: LotCalculatorRequest):
    """Calculate standard, mini, and micro lot sizes based on capital risk with hard ceilings."""
    risk_amount_usd = req.account_balance * (req.risk_percentage / 100.0)

    spec = get_symbol_trading_specs(req.symbol, base_sl=req.stop_loss_pips)
    pip_val_standard_lot = spec["pip_val"]
    eff_sl_pips = spec["sl_pips"]

    total_risk_per_standard_lot = eff_sl_pips * pip_val_standard_lot
    recommended_lots = risk_amount_usd / total_risk_per_standard_lot if total_risk_per_standard_lot > 0 else 0.0

    standard_lots = round(recommended_lots, 2)
    mini_lots = round(recommended_lots * 10, 2)
    micro_lots = round(recommended_lots * 100, 2)

    # Lot tavanı ve broker sınırları
    is_gold = ("XAU" in req.symbol.upper() or "GOLD" in req.symbol.upper())
    is_crypto = ("BTC" in req.symbol.upper() or "ETH" in req.symbol.upper())
    is_oil = ("USOIL" in req.symbol.upper() or "OIL" in req.symbol.upper() or "WTI" in req.symbol.upper() or "XTI" in req.symbol.upper())
    is_index = ("NAS" in req.symbol.upper() or "USTEC" in req.symbol.upper() or "US30" in req.symbol.upper() or "SPX" in req.symbol.upper())
    if is_index:
        lot_ceiling = 50.0
        safe_lots = round(max(0.10, min(standard_lots, lot_ceiling)), 2)
    elif is_oil:
        lot_ceiling = 1.0
        safe_lots = round(max(0.50, min(standard_lots, lot_ceiling)), 2)
    elif is_gold:
        lot_ceiling = min(HARD_MAX_GOLD_LOT, _AUTO_SETTINGS.max_gold_lot)
        safe_lots = round(max(0.01, min(standard_lots, lot_ceiling)), 2)
    elif is_crypto:
        lot_ceiling = 50.0
        safe_lots = round(max(0.01, min(standard_lots, lot_ceiling)), 2)
    else:
        lot_ceiling = min(HARD_MAX_FOREX_LOT, _AUTO_SETTINGS.max_forex_lot)
        safe_lots = round(max(0.01, min(standard_lots, lot_ceiling)), 2)

    return {
        "symbol": req.symbol,
        "account_balance": req.account_balance,
        "risk_percentage": req.risk_percentage,
        "risk_amount_usd": round(risk_amount_usd, 2),
        "stop_loss_pips": eff_sl_pips,
        "standard_lots": standard_lots,
        "safe_capped_lots": safe_lots,
        "mini_lots": mini_lots,
        "micro_lots": micro_lots,
        "units": int(safe_lots * 100_000),
    }


# ============================================================================
# OTONOM FOREX PAPER TRADE SCALPING MOTORU (M1 / M5 Dynamic Exit & Risk Engine)
# ============================================================================

class ForexAutoPaperSettings(BaseModel):
    enabled: bool = False
    balance: float = Field(10000.0, ge=50.0, description="Demo bakiye (USD)")
    risk_per_trade_pct: float = Field(10.0, ge=0.1, le=20.0, description="Pozisyon hacmi risk bütçesi (% bakiye)")
    max_open_positions: int = Field(99, ge=1, le=99, description="Aynı anda maksimum açık işlem (2026-10-07 kullanıcı kararı: 99 — slot rekabeti kaldırıldı; 60g replay'de XAU/BTC kâr potansiyeli 99 slotta ~3x)")
    max_positions_per_symbol: int = Field(3, ge=1, le=5, description="Aynı sembolde aynı yönde maksimum açık işlem (Piramitleme)")
    min_score: float = Field(75.0, ge=50.0, le=98.0, description="Minimum sinyal radar skoru (7 günlük replay A/B ile 75.0'e ayarlandı)")
    tp_pips: float = Field(20.0, ge=5.0, le=120.0, description="Kâr al mesafesi (pip - Favorable 1:2.5 R:R)")
    sl_pips: float = Field(8.0, ge=4.0, le=60.0, description="Zarar durdur mesafesi (pip - Sıkı Scalper SL)")
    breakeven_pips: float = Field(14.0, ge=2.0, le=50.0, description="Başabaş kilit tetik mesafesi")
    breakeven_usd: float = Field(1.0, ge=0.5, le=10.0, description="Başabaş kilit tetikleme net kârı ($)")
    gold_be_lock_ratio: float = Field(0.6, ge=0.1, le=1.0, description="Altın (XAUUSD) BE kâr kilitleme oranı — BE anındaki kârın bu oranındaki mesafe kilitlenir (2026-10-06 2×30g replay: %40→%60 her pencerede ~+$750, maxDD düşer)")
    trailing_stop_pips: float = Field(20.0, ge=4.0, le=60.0, description="İz süren stop mesafesi (pip)")
    session_filter: bool = Field(False, description="Seans filtresi (False: Asya ve tüm seanslarda kesintisiz işlem açılır)")
    max_spread_pips: float = Field(10.0, ge=0.5, le=15.0, description="Maksimum izin verilen spread (pip) — 2026-10-07 kullanıcı kararı: 3.0→10.0 (raw hesapta gerçek spreadler 0.1-2.1 pip; kısıt artık filtre değil sigorta)")
    max_forex_lot: float = Field(10.0, ge=0.01, le=HARD_MAX_FOREX_LOT, description="Maksimum Forex lot tavanı")
    max_gold_lot: float = Field(10.0, ge=0.01, le=HARD_MAX_GOLD_LOT, description="Maksimum Altın (XAUUSD) lot tavanı")
    gold_cooldown_sec: float = Field(60.0, ge=HARD_MIN_GOLD_COOLDOWN_SEC, le=900.0, description="Altın (XAUUSD) kapanış sonrası soğuma süresi (min 60 sn)")
    dxy_filter_enabled: bool = Field(True, description="DXY (ABD Dolar Endeksi) rejim filtresi: pozisyon DXY rejimiyle çelişiyorsa giriş veto edilir")
    correlation_guard: bool = Field(True, description="Pariteler arası korelasyon kalkanı: |ρ|>=0.85 aynı yönlü çakışma ve yüksek korelasyonlu küme girişlerini sınırlar")
    atr_exit_enabled: bool = Field(True, description="ATR bazlı dinamik çıkış motoru: TP ≈ 1.4x ATR mesafesine çekilir (TP'ye ulaşamama sorunu)")
    partial_tp_enabled: bool = Field(True, description="Kısmi kâr alma: ilk hedefte %50 pozisyon kapatılır, SL başabaş kârına çekilir")
    adx_filter_enabled: bool = Field(False, description="ADX trend gücü kalkanı (2026-10-06 30g replay: tüm eğri tarandı, KAPALI en iyi — +$3.935/maxDD $189; seans+minATR+EV kapıları chop kontrolünü devraldı. Panelden tekrar açılabilir)")
    adx_min: float = Field(28.0, ge=0.0, le=50.0, description="ADX minimum trend gücü eşiği (yalnız adx_filter_enabled=True iken etkin)")
    supertrend_filter_enabled: bool = Field(True, description="SuperTrend yön teyidi: giriş yalnızca SuperTrend yönüyle aynı tarafta açılır")
    ev_guard_enabled: bool = Field(True, description="Sembol EV kalkanı: zaman penceresinde sermaye yakan semboller otomatik dinlenmeye alınır")
    require_mt5_connection: bool = Field(True, description="MT5 köprüsü bağlı değilken YENİ işlem açılmaz (paper'a sessiz kayma + gerçek MT5 pozisyonunun yanlışlıkla kapanması biter — #7). False yapılırsa eski davranış: köprü yokken paper motoru devreye girer.")
    ev_window_hours: float = Field(24.0, ge=1.0, le=72.0, description="EV kalkanı geriye dönük bakış penceresi (saat)")
    ev_min_trades: int = Field(10, ge=3, le=50, description="EV kararı için pencerede gereken minimum işlem sayısı (yumuşatıldı: 8 → 10)")
    ev_max_win_rate: float = Field(45.0, ge=0.0, le=100.0, description="Kronik kaybeden eşiği: pencere WR'si bunun altındaysa ve net zarardaysa sembol dinlenir (42 → 35 → 45: 2026-10-06 30g replay A/B kararı)")
    ev_loss_risk_mult: float = Field(3.0, ge=0.5, le=20.0, description="Akut kayıp eşiği: pencere zararı işlem-başı risk bütçesinin bu katını aşarsa sembol dinlenir (yumuşatıldı: 2x → 3x)")
    major_session_filter: bool = Field(True, description="Majör FX seans filtresi: majörler yalnız belirlenen UTC saat penceresinde işlem açılır (Asya seansı chop'u — 30g replay: +$427 iyileşme)")
    major_session_start_utc: int = Field(7, ge=0, le=23, description="Majör seans penceresi başlangıcı (UTC, dahil) — 07:00 London açık")
    major_session_end_utc: int = Field(20, ge=1, le=24, description="Majör seans penceresi bitişi (UTC, dahil değil) — 20:00 NY öğleden sonra")
    major_min_atr_pips: float = Field(4.0, ge=0.0, le=50.0, description="Majörler minimum ATR (pip) tabanı — ölü piyasa filtresi (30g replay: WR %63→%68; 0 = kapalı)")
    crypto_sl_atr_mult: float = Field(1.5, ge=0.0, le=5.0, description="Kripto kategorisi özel SL ATR çarpanı (0 = global 1.1×ATR; 2026-10-06 replay: BTC −$30→+$58, maxDD $161→$142)")
    crypto_tp_enabled: bool = Field(False, description="Kriptoda sabit TP emri (False = kapalı; 2026-10-06 30g replay: TP kapalıyken BTC −$55.70→−$18.02, kazanç trailing/BE ile koşturulur)")
    btc_min_score: float = Field(76.0, ge=0.0, le=98.0, description="BTCUSD özel giriş skor eşiği (0 = global min_score; süpürme: 76 noktası)")
    loss_streak_limit: int = Field(3, ge=0, le=10, description="Seri-SL sigortası: aynı sembolde bu kadar ardışık tam-SL kaybında yeni girişler durur (0 = kapalı; 2026-10-07 kullanıcı önerisi + replay: 3)")
    loss_streak_cooldown_sec: float = Field(300.0, ge=0.0, le=3600.0, description="Seri-SL tetiklenince sembolün yeni giriş soğuma penceresi (saniye; normal altın/BTC cooldown'undan BAĞIMSIZ — kullanıcı önerisi: 300 = 5 dk)")
    chandelier_atr_mult: float = Field(1.2, ge=0.0, le=5.0, description="Chandelier kâr kilidi: BE sonrası trailing, kâr tepesinden bu ATR katı geri verilince kilitler (0 = sabit pip trail; 2026-10-07 replay: 1.2 → 30g +$29/%10g +$6, 'kazandığını geri verme' tavanı. Kâr-tepesi takibi BE/TP'yi beklemeden erken kilitler)")
    blocked_hours_utc: List[int] = Field(default_factory=list, description="İşlem yapılmasın istenen UTC saatleri (varsayılan: boş — zayıf saat kalkanı kaldırıldı)")
    allowed_symbols: List[str] = Field(
        default_factory=lambda: ["XAUUSD", "BTCUSD", "GBPJPY", "EURJPY"],
        description="İşleme izin verilen pariteler (2026-10-07 kalibre kapsam: XAU+BTC klasik, GBPJPY/EURJPY donchian modu; 28/28 FX çifti klasik sinyalle 30g replay'de negatif — majör/kros genişlemesi panelden yapılmaz, replay kanıtı ister)",
    )
    mode_symbols: List[str] = Field(
        default_factory=lambda: ["XAUUSD", "BTCUSD", "GBPJPY", "EURJPY"],
        description="Donchian+ADX giriş modunun AKTİF olduğu semboller",
    )
    mode_exclusive: List[str] = Field(
        default_factory=lambda: ["GBPJPY", "EURJPY"],
        description="YALNIZ donchian_adx moduyla işlem açılan semboller (klasik skor sinyali bu çiftlerde replay'de kanıtlanmış negatif beklentiye sahip — kapalı kalır)",
    )


class ClosePositionRequest(BaseModel):
    id: str


class ToggleAutoPaperRequest(BaseModel):
    enabled: bool


# Engine In-Memory State
_AUTO_PAPER_LOCK = asyncio.Lock()
_AUTO_PAPER_TASK: Optional[asyncio.Task] = None
_LAST_SESSION_BLOCK_LOG_TIME = 0.0
_LAST_BLOCKED_HOUR_LOG_TIME = 0.0
_LAST_SCAN_PULSE_TIME = 0.0
_LAST_CANDIDATE_LOG_TIME: Dict[str, float] = {}
_LAST_DATA_GAP_LOG: Dict[str, float] = {}
_LAST_SYMBOL_ENTRY_TIME: Dict[str, float] = {}

_AUTO_SETTINGS = ForexAutoPaperSettings()

# IC Markets MT5 Durumu (Global Köprü Paylaşımı)
_MT5_STATE: Dict[str, Any] = {
    "connected": False,
    "last_ping": 0.0,
    "auto_trade": True,
    "account": {
        "login": 53077151,
        "name": "ERKAN ERDEM",
        "server": "ICMarketsSC-Demo",
        "balance": 1000.0,
        "equity": 1000.0,
        "margin": 0.0,
        "free_margin": 1000.0,
        "leverage": 5000,
        "currency": "USD",
    },
    "open_positions": [],
    "closed_deals": [],
    "pending_commands": [],
}

# Seri-SL sigortası durumu (yalnız dict mutasyonu kullanılır — döngü içinde yeniden
# atama yok, bu yüzden `global` bildirimi gerekmez; bkz. globals-shadow regresyon testi)
_SYMBOL_LOSS_STREAK: Dict[str, int] = {}
_SYMBOL_LOSS_COOLDOWN_UNTIL: Dict[str, float] = {}
# Donchian+ADX mod durumu (yalnız dict mutasyonu — global bildirimi gerekmez)
_DONCHIAN_STATE: Dict[str, Dict[str, Any]] = {}
# EV kalkanı kesim zamanı: reset anından ÖNCE kapanan işlemler EV penceresine girmez
# (kural seti değişince eski sicil yeni kuralları suçlamasın — kullanıcı isteği 2026-10-07).
# 0.0 = reset yok. Sadece endpoint'te atanır → orada `global` bildirimi zorunlu.
_EV_RESET_AT_TS: float = 0.0
# Temiz-sayfa (arşiv + sıfırdan başla) kesim zamanı: resetten önce kapanan işlemler
# rapor/KPI/CSV/panel listelerinde görünmez; eski veriler arşive alınır (kullanıcı
# isteği 2026-10-07: "başarı hesaplamaları da sıfırdan olsun"). Bakiyeye DOKUNULMAZ.
_LEDGER_RESET_AT_TS: float = 0.0


def _ledger_archive_dir() -> str:
    """Arşiv dosyası için yazılabilir dizin: env → /data (Docker volume) → repo outputs → tmp."""
    cands = [
        os.environ.get("FOREX_LEDGER_ARCHIVE_DIR") or "",
        "/data",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "outputs"),
        tempfile.gettempdir(),
    ]
    for c in cands:
        if not c:
            continue
        try:
            os.makedirs(c, exist_ok=True)
            probe = os.path.join(c, ".write_probe")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return c
        except Exception:
            continue
    return tempfile.gettempdir()

_AUTO_STATE: Dict[str, Any] = {
    "enabled": False,
    "balance": 10000.0,
    "initial_balance": 10000.0,
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "realized_pnl_usd": 0.0,
    "realized_pnl_pips": 0.0,
    "open_positions": [],
    "closed_trades": [],
    "decision_logs": [],
    "last_scan_time": 0.0,
    "last_status": "Durduruldu",
}


def _log_auto_decision(category: str, message: str, symbol: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
    """Kayıt defterine otonom karar gerekçesi ekler (şeffaf izleme)."""
    # Mükerrer ardışık logları engelle
    if _AUTO_STATE["decision_logs"]:
        if _AUTO_STATE["decision_logs"][0].get("message") == message:
            return

    now_ts = time.time()
    now_dt = datetime.datetime.fromtimestamp(now_ts, TZ_UTC3)
    log_item = {
        "id": f"LOG-{int(now_ts * 1000) % 1000000}",
        "time": now_dt.strftime("%H:%M:%S UTC+3"),
        "created_at_ts": now_ts,
        "category": category,
        "symbol": symbol,
        "message": message,
        "metadata": metadata or {},
    }
    _AUTO_STATE["decision_logs"].insert(0, log_item)
    if len(_AUTO_STATE["decision_logs"]) > 120:
        _AUTO_STATE["decision_logs"] = _AUTO_STATE["decision_logs"][:120]


async def _close_position_internal(pos_id: str, reason: str, exit_price: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Açık pozisyonu kapatır ve muhasebeleştirir."""
    async with _AUTO_PAPER_LOCK:
        open_list = _AUTO_STATE["open_positions"]
        target = None
        for p in open_list:
            if p["id"] == pos_id:
                target = p
                break
        if not target:
            return None

        open_list.remove(target)

        pip_size = target["pip_size"]
        cur_p = exit_price if exit_price is not None else target["current_price"]
        direction = target["direction"]

        # Final PnL hesaplama
        if direction == "BUY":
            pnl_pips = (cur_p - target["entry_price"]) / pip_size
        else:
            pnl_pips = (target["entry_price"] - cur_p) / pip_size

        # Pip başına USD değeri sembol spec'inden alınır — BTCUSD/ETHUSD/NAS100/USOIL
        # için pip_val 1.0'dır; sabit 10.0 kullanmak paper PnL'i 10 kat şişiriyordu.
        pip_usd_val = get_symbol_trading_specs(target["symbol"])["pip_val"]
        # Kalan bacak: bakiye/realized bu kadarıyla güncellenir (kısmi bacak
        # döngüde `apply_partial_take_profit` sırasında zaten kredilenmişti).
        remaining_pnl_usd = round(pnl_pips * target["lots"] * pip_usd_val, 2)
        remaining_pnl_pips = round(pnl_pips, 1)
        # Kapanış KAYDI ise toplamı göstermelidir: aksi halde rapor kârı eksik,
        # hatta kazanan işlem LOSS görünürdü (P1). Kayıt = kısmi + kalan.
        partial_usd = float(target.get("partial_realized_usd", 0.0))
        partial_pips = float(target.get("partial_realized_pips", 0.0))
        pnl_usd = round(remaining_pnl_usd + partial_usd, 2)
        pnl_pips = round(remaining_pnl_pips + partial_pips, 1)

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_time = time.time()
        open_ts = target.get("opened_at_ts", now_time)
        dur_sec = max(1, int(now_time - open_ts))
        dur_human = f"{dur_sec // 60} dk {dur_sec % 60} sn" if dur_sec >= 60 else f"{dur_sec} sn"

        reason_titles = {
            "TP_HIT": "🎯 Kâr Al (TP)",
            "SL_HIT": "🛑 Zarar Kes (SL)",
            "BE_HIT": "🛡️ Başabaş (BE)",
            "TRAILING_HIT": "📈 İz Süren (Trailing)",
            "MANUAL": "✋ Manuel Kapatma",
            "REVERSAL_FLIP": "🔄 Trend Dönüşü (Flip Reversal)",
            "SEANS16": "🕒 Seans Kapanışı (16:00 UTC)",
        }
        human_reason = reason_titles.get(reason, reason)
        # Bakiye YALNIZ kalan bacakla ilerler: kısmi kâr döngüde kredilenmişti,
        # `pnl_usd` ise kayıt için toplamı taşıyor (yukarıya bkz.).
        bal_after = round(_AUTO_STATE["balance"] + remaining_pnl_usd, 2)

        now_dt = datetime.datetime.fromtimestamp(now_time, TZ_UTC3)
        closed_item = {
            **target,
            "exit_price": cur_p,
            "exit_time": now_dt.strftime("%Y-%m-%d %H:%M:%S UTC+3"),
            "exit_time_iso": now_dt.isoformat(),
            "closed_at_ts": now_time,
            "duration_sec": dur_sec,
            "duration_human": dur_human,
            "exit_reason": reason,
            "exit_reason_title": human_reason,
            "pnl_usd": pnl_usd,
            "pnl_pips": pnl_pips,
            "balance_after": bal_after,
            "outcome": "WIN" if pnl_usd >= 0 else "LOSS",
        }

        _AUTO_STATE["balance"] = bal_after
        _AUTO_STATE["realized_pnl_usd"] = round(_AUTO_STATE["realized_pnl_usd"] + remaining_pnl_usd, 2)
        _AUTO_STATE["realized_pnl_pips"] = round(_AUTO_STATE["realized_pnl_pips"] + remaining_pnl_pips, 1)
        _AUTO_STATE["total_trades"] += 1
        if pnl_usd >= 0:
            _AUTO_STATE["wins"] += 1
        else:
            _AUTO_STATE["losses"] += 1

        _AUTO_STATE["closed_trades"].insert(0, closed_item)
        if len(_AUTO_STATE["closed_trades"]) > 1000:
            _AUTO_STATE["closed_trades"] = _AUTO_STATE["closed_trades"][:1000]

        # Seri-SL sigortası: sembolün ardışık tam-SL kayıplarını izle (kullanıcı kuralı:
        # N ardışık SL zararı → sembol kısa süre yeni giriş almaz, normal cooldown'dan bağımsız)
        streak_sym = target.get("symbol", "").upper()
        new_streak, streak_tripped = loss_streak_on_close(
            _SYMBOL_LOSS_STREAK.get(streak_sym, 0),
            reason,
            pnl_usd,
            _AUTO_SETTINGS.loss_streak_limit,
        )
        _SYMBOL_LOSS_STREAK[streak_sym] = new_streak
        if streak_tripped:
            _SYMBOL_LOSS_COOLDOWN_UNTIL[streak_sym] = time.time() + _AUTO_SETTINGS.loss_streak_cooldown_sec
            _log_auto_decision(
                "GATE",
                f"🌡️ [{target.get('display', streak_sym)}] {_AUTO_SETTINGS.loss_streak_limit} ardışık SL kaybı tamamlandı — sembol {_AUTO_SETTINGS.loss_streak_cooldown_sec:.0f} sn serbest soğumaya alındı (açık pozisyon yönetimi sürer, süre bitince normal değerlendirme).",
                symbol=streak_sym,
            )

        _log_auto_decision(
            "EXIT",
            f"{target.get('display', target.get('symbol', ''))} {human_reason} ile kapandı: ${pnl_usd:+.2f} ({pnl_pips:+.1f} pip)",
            symbol=target["symbol"],
            metadata={"pnl_usd": pnl_usd, "pnl_pips": pnl_pips, "reason": reason},
        )

        # Altın veya BTC pozisyonu kapandığında 60 saniye soğuma sayacını başlat
        sym_closed = target.get("symbol", "").upper()
        if "XAU" in sym_closed or "GOLD" in sym_closed:
            global _LAST_GOLD_EXIT_TIME
            _LAST_GOLD_EXIT_TIME = time.time()
        if "BTC" in sym_closed:
            global _LAST_BTC_EXIT_TIME
            _LAST_BTC_EXIT_TIME = time.time()

        # MT5 Köprüsü bağlıysa ve otomatik iletim aktifse, MT5'teki açık pozisyonu da otomatik kapat
        if _MT5_STATE.get("connected") and _MT5_STATE.get("auto_trade"):
            sym_target = target["symbol"].upper()
            target_ticket = target.get("mt5_ticket")
            for mpos in list(_MT5_STATE.get("open_positions", [])):
                t_id = mpos.get("ticket")
                # KAYIT MT5'ten gelmiyorsa (paper pozisyonu — `mt5_ticket` yok) MT5'e
                # DOKUNMA. Eskiden `not target_ticket` dalı sembol adı eşleşen HER MT5
                # pozisyonunu kapatıyordu; köprü düşüp motor paper açtığında o paper
                # kaydı, geri gelen köprüdeki gerçek pozisyonları siliyordu (#7).
                if target_ticket is None:
                    continue
                should_close = (t_id == target_ticket)
                if should_close and t_id:
                    already_closing = any(c.get("ticket") == t_id for c in _MT5_STATE.get("pending_commands", []))
                    if not already_closing:
                        _MT5_STATE["pending_commands"].append({
                            "id": f"CMD-CLOSE-{t_id}",
                            "action": "CLOSE_ORDER",
                            "ticket": t_id,
                        })
                        _log_auto_decision(
                            "EXIT",
                            f"🛑 [MT5 Senkron Kapatma]: {target['display']} Bilet #{t_id} kapatma emri iletildi ({human_reason})",
                            symbol=target["symbol"],
                        )

        return closed_item


def _gold_scan_note(gold_tick: Dict[str, Any], now_ts: float) -> str:
    """XAU/USD tarama özeti — insan-okur tek cümle.

    Yalnızca RAPORLAMA amaçlıdır: giriş döngüsündeki kapı zincirini etkilemez.
    Sembol soğuması ve bekleyen emir dahil bilinen kapıları özetler; emir
    kuyruğa alınana kadar "işlem açılıyor" demez.
    """
    global _LAST_GOLD_EXIT_TIME
    action = str(gold_tick.get("action", "HOLD"))
    if action not in ("BUY", "SELL"):
        return "yön teyidi oluşmadı — gözlemde"
    reasons: List[str] = []
    active_count = len(_MT5_STATE.get("open_positions", [])) if _MT5_STATE.get("connected") else len(_AUTO_STATE.get("open_positions", []))
    if active_count >= _AUTO_SETTINGS.max_open_positions:
        reasons.append("pozisyon limiti dolu")
    if _LAST_GOLD_EXIT_TIME > 0:
        if _LAST_GOLD_EXIT_TIME > now_ts:
            _LAST_GOLD_EXIT_TIME = now_ts
        time_since_gold = max(0.0, now_ts - _LAST_GOLD_EXIT_TIME)
        cd_left = max(0.0, min(_AUTO_SETTINGS.gold_cooldown_sec, _AUTO_SETTINGS.gold_cooldown_sec - time_since_gold))
        if cd_left > 0:
            reasons.append(f"son kapanıştan sonra soğuma bekleniyor ({int(cd_left)} sn)")
    if any(c.get("action") == "OPEN_ORDER" and str(c.get("symbol", "")).upper() == "XAUUSD"
           for c in _MT5_STATE.get("pending_commands", [])):
        reasons.append("gönderilen emrin işlem görmesi bekleniyor")
    last_sym_gold = _LAST_SYMBOL_ENTRY_TIME.get("XAUUSD", 0.0)
    if last_sym_gold > now_ts:
        _LAST_SYMBOL_ENTRY_TIME["XAUUSD"] = now_ts
        last_sym_gold = now_ts
    sym_cd_left = max(0.0, min(_AUTO_SETTINGS.gold_cooldown_sec, _AUTO_SETTINGS.gold_cooldown_sec - max(0.0, now_ts - last_sym_gold)))
    if sym_cd_left > 0:
        reasons.append("son girişten sonra sembol soğuması bekleniyor")
    if _AUTO_SETTINGS.ev_guard_enabled:
        ev_stats = _collect_symbol_ev("XAUUSD", now_ts, _AUTO_SETTINGS.ev_window_hours * 3600.0)
        ev_balance = float(_MT5_STATE.get("account", {}).get("balance", _AUTO_STATE["balance"])) if _MT5_STATE.get("connected") else float(_AUTO_STATE["balance"])
        ev_floor = ev_balance * (_AUTO_SETTINGS.risk_per_trade_pct / 100.0) * _AUTO_SETTINGS.ev_loss_risk_mult
        if ev_guard_decision(ev_stats, _AUTO_SETTINGS.ev_min_trades, _AUTO_SETTINGS.ev_max_win_rate, ev_floor):
            reasons.append("son kayıplar nedeniyle dinleniyor")
    bias = get_usd_bias("XAUUSD", action)
    if _AUTO_SETTINGS.correlation_guard and bias != "USD_NEUTRAL":
        corr_positions = [
            (str(p.get("symbol", "")).upper(), get_usd_bias(str(p.get("symbol", "")), str(p.get("direction", "BUY"))))
            for p in list(_MT5_STATE.get("open_positions", [])) + list(_AUTO_STATE.get("open_positions", []))
        ]
        corr_ok, _corr_reason = _FX_CORR.cluster_check("XAUUSD", bias, corr_positions)
        if not corr_ok:
            reasons.append("benzer pozisyon nedeniyle korelasyon bekliyor")
    gold_open = [p for p in (list(_MT5_STATE.get("open_positions", [])) + list(_AUTO_STATE.get("open_positions", [])))
                 if str(p.get("symbol", "")).upper() == "XAUUSD"]
    if gold_open and active_count < _AUTO_SETTINGS.max_open_positions:
        reasons.append("zaten açık pozisyon var")
    spread = float(gold_tick.get("spread_pips", 2.5))
    if spread > _AUTO_SETTINGS.max_spread_pips:
        reasons.append(f"spread çok geniş ({spread:.1f} pip)")
    if float(gold_tick.get("score", 0.0)) < 78.0:
        reasons.append(f"sinyal skoru yetersiz ({float(gold_tick.get('score', 0.0)):.0f})")
    if _AUTO_SETTINGS.adx_filter_enabled and float(gold_tick.get("adx", 25.0)) < _AUTO_SETTINGS.adx_min:
        reasons.append(f"trend gücü zayıf (ADX {float(gold_tick.get('adx', 0.0)):.0f})")
    st = int(gold_tick.get("supertrend_dir", 0))
    if _AUTO_SETTINGS.supertrend_filter_enabled and ((action == "BUY" and st < 0) or (action == "SELL" and st > 0)):
        reasons.append("grafik yönü sinyalle ters")
    if reasons:
        return "işlem bekliyor: " + " + ".join(reasons[:2])
    return "✅ temel şartlar uygun — giriş değerlendiriliyor"


def _btc_scan_note(btc_tick: Dict[str, Any], now_ts: float) -> str:
    """BTC/USD tarama özeti — insan-okur tek temiz cümle.

    Yalnızca RAPORLAMA amaçlıdır: giriş döngüsündeki kapı zincirini özetler.
    Sembol soğuması, spread, skor ve açık pozisyon durumunu özetler.
    """
    action = str(btc_tick.get("action", "HOLD"))
    if action not in ("BUY", "SELL"):
        return "yön teyidi oluşmadı — gözlemde"
    reasons: List[str] = []
    active_count = len(_MT5_STATE.get("open_positions", [])) if _MT5_STATE.get("connected") else len(_AUTO_STATE.get("open_positions", []))
    if active_count >= _AUTO_SETTINGS.max_open_positions:
        reasons.append("pozisyon limiti dolu")
    if any(c.get("action") == "OPEN_ORDER" and str(c.get("symbol", "")).upper() == "BTCUSD"
           for c in _MT5_STATE.get("pending_commands", [])):
        reasons.append("gönderilen emrin işlem görmesi bekleniyor")
    global _LAST_BTC_EXIT_TIME
    if _LAST_BTC_EXIT_TIME > 0:
        if _LAST_BTC_EXIT_TIME > now_ts:
            _LAST_BTC_EXIT_TIME = now_ts
        time_since_btc = max(0.0, now_ts - _LAST_BTC_EXIT_TIME)
        cd_left = max(0.0, min(60.0, 60.0 - time_since_btc))
        if cd_left > 0:
            reasons.append(f"son kapanıştan sonra soğuma bekleniyor ({int(cd_left)} sn)")
    last_sym_btc = _LAST_SYMBOL_ENTRY_TIME.get("BTCUSD", 0.0)
    if last_sym_btc > now_ts:
        _LAST_SYMBOL_ENTRY_TIME["BTCUSD"] = now_ts
        last_sym_btc = now_ts
    sym_cd_left = max(0.0, min(60.0, 60.0 - max(0.0, now_ts - last_sym_btc)))
    if sym_cd_left > 0:
        reasons.append(f"son girişten sonra sembol soğuması bekleniyor ({int(sym_cd_left)} sn)")
    btc_open = [p for p in (list(_MT5_STATE.get("open_positions", [])) + list(_AUTO_STATE.get("open_positions", [])))
                if str(p.get("symbol", "")).upper() == "BTCUSD"]
    if btc_open and active_count < _AUTO_SETTINGS.max_open_positions:
        reasons.append("zaten açık pozisyon var")
    spread = float(btc_tick.get("spread_pips", 12.0))
    eff_spread_limit = max(50.0, _AUTO_SETTINGS.max_spread_pips * 10)
    if spread > eff_spread_limit:
        reasons.append(f"spread geniş ({spread:.1f}p > {eff_spread_limit:.0f}p)")
    score = float(btc_tick.get("score", 0.0))
    req_score = _AUTO_SETTINGS.btc_min_score if _AUTO_SETTINGS.btc_min_score > 0 else _AUTO_SETTINGS.min_score
    if score < req_score:
        reasons.append(f"sinyal skoru yetersiz ({score:.0f} < {req_score:.0f})")
    if _AUTO_SETTINGS.adx_filter_enabled and float(btc_tick.get("adx", 25.0)) < _AUTO_SETTINGS.adx_min:
        reasons.append(f"trend gücü zayıf (ADX {float(btc_tick.get('adx', 0.0)):.0f})")
    st = int(btc_tick.get("supertrend_dir", 0))
    if _AUTO_SETTINGS.supertrend_filter_enabled and ((action == "BUY" and st < 0) or (action == "SELL" and st > 0)):
        reasons.append("grafik yönü sinyalle ters")
    if reasons:
        return "işlem bekliyor: " + " + ".join(reasons[:2])
    return "✅ temel şartlar uygun — giriş değerlendiriliyor"



async def _forex_auto_paper_loop():
    """Arka plan otonom forex scalper izleme ve işlem açma döngüsü."""
    global _LAST_SESSION_BLOCK_LOG_TIME, _LAST_SCAN_PULSE_TIME, _LAST_GOLD_EXIT_TIME, _LAST_BTC_EXIT_TIME, _LAST_BLOCKED_HOUR_LOG_TIME
    last_loop_error_log_ts = 0.0
    logger.info("Forex Otonom Scalper Döngüsü Başlatıldı.")
    _AUTO_STATE["last_status"] = "Çalışıyor (Canlı Piyasa Taranıyor)"

    while _AUTO_STATE["enabled"]:
        try:
            await asyncio.sleep(1.5)
            ticks = await _generate_realistic_ticks()
            sessions = _get_market_sessions()
            now_ts = time.time()
            _AUTO_STATE["last_scan_time"] = now_ts

            # ---------------------------------------------------------------
            # 1. AÇIK POZİSYONLARI GÜNCELLE & SL/TP/TRAILING/BE DENETLE
            # ---------------------------------------------------------------
            positions_to_close = []
            async with _AUTO_PAPER_LOCK:
                for pos in _AUTO_STATE["open_positions"]:
                    sym = pos["symbol"]
                    t = ticks.get(sym)
                    if not t:
                        continue

                    pip_size = pos["pip_size"]
                    digits = pos["digits"]
                    direction = pos["direction"]
                    entry_p = pos["entry_price"]

                    # Alış pozisyonu Bid fiyatından, Satış pozisyonu Ask fiyatından kapatılır
                    cur_p = t["bid"] if direction == "BUY" else t["ask"]
                    pos["current_price"] = cur_p

                    atr_pips = round(t.get("atr", 0.001) / pip_size, 1) if pip_size > 0 else 15.0
                    spec = get_symbol_trading_specs(
                        sym,
                        base_be=_AUTO_SETTINGS.breakeven_pips,
                        base_trail=_AUTO_SETTINGS.trailing_stop_pips,
                        atr_pips=atr_pips,
                    )
                    eff_be_pips = spec["be_pips"]
                    eff_trail_pips = spec["trail_pips"]

                    # PnL hesapla — pip başına USD değeri sembol spec'inden alınır
                    # (BTCUSD/ETHUSD/endeks/petrol için pip_val 1.0; sabit 10.0 → 10x hatalıydı)
                    pip_usd_val = spec["pip_val"]
                    if direction == "BUY":
                        pnl_pips = (cur_p - entry_p) / pip_size
                    else:
                        pnl_pips = (entry_p - cur_p) / pip_size

                    pos["pnl_pips"] = round(pnl_pips, 1)
                    pos["pnl_usd"] = round(pnl_pips * pos["lots"] * pip_usd_val, 2)
                    # Chandelier kâr kilidi için tepe takibi (girişten beri en iyi pip)
                    if pnl_pips > float(pos.get("mfe_pips", 0.0) or 0.0):
                        pos["mfe_pips"] = round(pnl_pips, 1)

                    # (a0) KISMİ KÂR ALMA (Partial TP): İlk hedefte lot'un yarısı
                    # kapatılır; kalan pozisyonda SL başabaş üstü net kâra kilitlenir.
                    if _AUTO_SETTINGS.partial_tp_enabled:
                        realized_partial = apply_partial_take_profit(pos, pnl_pips, pip_usd_val)
                        if realized_partial:
                            _AUTO_STATE["balance"] = round(_AUTO_STATE["balance"] + realized_partial, 2)
                            _AUTO_STATE["realized_pnl_usd"] = round(_AUTO_STATE["realized_pnl_usd"] + realized_partial, 2)
                            _log_auto_decision(
                                "PROTECT",
                                f"{pos['display']} 💰 Kısmi Kâr Alındı: ${realized_partial:+.2f} (kalan {pos['lots']} lot, SL başabaş kârına kilitli).",
                                symbol=sym,
                                metadata={"partial_usd": realized_partial, "remaining_lots": pos["lots"]},
                            )

                    # (a) BAŞABAŞ (BREAKEVEN) DENETİMİ (Volatilite ve R Tabanlı Dinamik Eşik)
                    lots = float(pos.get("lots", 0.05))
                    pip_val = spec["pip_val"]
                    dollar_per_pip = max(0.0001, lots * pip_val)
                    pips_for_1usd = max(0.5, round(1.0 / dollar_per_pip, 1))

                    if not pos.get("breakeven_activated"):
                        is_gold_pos = ("XAU" in sym or "GOLD" in sym)
                        is_crypto_pos = ("BTC" in sym)
                        cand_be = calculate_breakeven_target(
                            pnl_pips=pnl_pips,
                            pnl_usd=pos.get("pnl_usd", 0.0),
                            lots=lots,
                            pip_val=pip_val,
                            pip_size=pip_size,
                            digits=digits,
                            direction=direction,
                            entry_price=entry_p,
                            current_price=cur_p,
                            current_sl=pos.get("sl_price", 0.0),
                            sl_pips=spec.get("sl_pips", _AUTO_SETTINGS.sl_pips),
                            atr_pips=atr_pips,
                            eff_be_pips=eff_be_pips,
                            is_gold=is_gold_pos,
                            is_crypto=is_crypto_pos,
                            gold_be_lock_ratio=_AUTO_SETTINGS.gold_be_lock_ratio,
                        )
                        if cand_be is not None:
                            pos["sl_price"] = cand_be
                            pos["breakeven_activated"] = True
                            _log_auto_decision(
                                "PROTECT",
                                f"{pos['display']} Başabaş (BE) kilitlendi: Net Kâr ${pos['pnl_usd']:+.2f} (+{pnl_pips:.1f} pip). Stop seviyesi {pos['sl_price']} yapıldı (Dinamik Risk/Volatilite Koruması).",
                                symbol=sym,
                            )
                            # MT5 açık biletlerinde de Stop Loss'u başabaş seviyesine çek
                            if _MT5_STATE.get("connected") and _MT5_STATE.get("auto_trade"):
                                mt5_pos_id = pos.get("mt5_ticket")
                                for mpos in _MT5_STATE.get("open_positions", []):
                                    m_t = mpos.get("ticket")
                                    # Paper kaydı (mt5_ticket yok) MT5 biletiyle eşleşemez → dokunma (#7).
                                    if mt5_pos_id and m_t == mt5_pos_id:
                                        if m_t:
                                            _MT5_STATE["pending_commands"].append({
                                                "id": f"CMD-MODIFY-{m_t}-BE",
                                                "action": "MODIFY_SLTP",
                                                "ticket": m_t,
                                                "sl": pos["sl_price"],
                                                "tp": mpos.get("tp_price", 0.0),
                                            })
                                            _log_auto_decision("PROTECT", f"🛡️ [MT5] {sym} Bilet #{m_t} Başabaş Stopu {pos['sl_price']} olarak kilitlendi.", symbol=sym)

                    # (b) İZ SÜREN STOP (TRAILING STOP) DENETİMİ
                    # Sembole ve volatiliteye (ATR) göre trailing mesafesi
                    # BE kilitlendikten sonra VEYA pnl_pips >= eff_trail_pips olduğunda fiyatı arkasından takip et
                    if pos.get("breakeven_activated") or pnl_pips >= eff_trail_pips:
                        chand_mult = float(_AUTO_SETTINGS.chandelier_atr_mult or 0.0)
                        pos_mfe = float(pos.get("mfe_pips", 0.0) or 0.0)
                        updated_trail = False
                        if chand_mult > 0 and atr_pips > 0 and pos_mfe > 0:
                            # Chandelier: kâr tepesinden chand_mult×ATR geri verilince kilit
                            # (replay: 1.2 → 30g +$29 / 10g +$6; "kazandığını geri verme" tavanı)
                            cand_pips = pos_mfe - (chand_mult * atr_pips)
                            if direction == "BUY":
                                cand_sl = round(entry_p + (cand_pips * pip_size), digits)
                                # Trailing SL asla 1$ Breakeven seviyesinin altına inmez!
                                cand_sl = max(cand_sl, round(entry_p + (pips_for_1usd * pip_size), digits))
                                if cand_sl > pos["sl_price"] and cand_sl > entry_p:
                                    pos["sl_price"] = cand_sl
                                    pos["trailing_activated"] = True
                                    updated_trail = True
                            else:
                                cand_sl = round(entry_p - (cand_pips * pip_size), digits)
                                cand_sl = min(cand_sl, round(entry_p - (pips_for_1usd * pip_size), digits))
                                if (pos["sl_price"] == 0 or cand_sl < pos["sl_price"]) and cand_sl < entry_p:
                                    pos["sl_price"] = cand_sl
                                    pos["trailing_activated"] = True
                                    updated_trail = True
                        else:
                            trail_dist = eff_trail_pips * pip_size
                            if direction == "BUY":
                                cand_sl = round(cur_p - trail_dist, digits)
                                # Trailing SL asla 1$ Breakeven seviyesinin altına inmez!
                                min_safe_sl = round(entry_p + (pips_for_1usd * pip_size), digits)
                                cand_sl = max(cand_sl, min_safe_sl)
                                if cand_sl > pos["sl_price"] and cand_sl > entry_p:
                                    pos["sl_price"] = cand_sl
                                    pos["trailing_activated"] = True
                                    updated_trail = True
                            else:
                                cand_sl = round(cur_p + trail_dist, digits)
                                # Trailing SL asla 1$ Breakeven seviyesinin üstüne çıkmaz!
                                min_safe_sl = round(entry_p - (pips_for_1usd * pip_size), digits)
                                cand_sl = min(cand_sl, min_safe_sl)
                                if (pos["sl_price"] == 0 or cand_sl < pos["sl_price"]) and cand_sl < entry_p:
                                    pos["sl_price"] = cand_sl
                                    pos["trailing_activated"] = True
                                    updated_trail = True

                        # MT5 açık biletinde de Stop Loss seviyesini dinamik olarak yukarı sür
                        if updated_trail and _MT5_STATE.get("connected") and _MT5_STATE.get("auto_trade"):
                            # Yalnız bu pozisyonun bağlı olduğu MT5 bileti güncellenir;
                            # paper kaydı (mt5_ticket yok) MT5'e dokunamaz (#7).
                            trail_ticket = pos.get("mt5_ticket")
                            for mpos in _MT5_STATE.get("open_positions", []):
                                if trail_ticket and mpos.get("ticket") == trail_ticket:
                                    t_id = mpos.get("ticket")
                                    if t_id:
                                        _MT5_STATE["pending_commands"].append({
                                            "id": f"CMD-MODIFY-{t_id}-TR",
                                            "action": "MODIFY_SLTP",
                                            "ticket": t_id,
                                            "sl": pos["sl_price"],
                                            "tp": mpos.get("tp_price", 0.0),
                                        })

                    # (c) KÂR AL (TAKE PROFIT) KONTROLÜ — tp_price=0 (TP'siz mod, örn. kripto) asla tetiklenmez
                    # MT5'te TP bir LİMİT emridir: seviyeye ulaşınca o seviyeden
                    # dolar, daha iyisinden değil. Eskiden çıkış fiyatı olarak
                    # gap-sonrası `cur_p` yazılıyor ve paper TP kârları sistematik
                    # iyimser çıkıyordu (P2). SL bir STOP emridir ve kötü fiyattan
                    # dolabileceği için orada `cur_p` (daha kötü) bilinçli korunur.
                    if pos["tp_price"] > 0 and direction == "BUY" and cur_p >= pos["tp_price"]:
                        positions_to_close.append((pos["id"], "TP_HIT", pos["tp_price"]))
                    elif pos["tp_price"] > 0 and direction == "SELL" and cur_p <= pos["tp_price"]:
                        positions_to_close.append((pos["id"], "TP_HIT", pos["tp_price"]))

                    # (d) ZARAR DURDUR (STOP LOSS) KONTROLÜ
                    elif direction == "BUY" and cur_p <= pos["sl_price"]:
                        reason = "BE_HIT" if pos["breakeven_activated"] and pos["pnl_pips"] >= 0 else "SL_HIT"
                        positions_to_close.append((pos["id"], reason, cur_p))
                    elif direction == "SELL" and cur_p >= pos["sl_price"]:
                        reason = "BE_HIT" if pos["breakeven_activated"] and pos["pnl_pips"] >= 0 else "SL_HIT"
                        positions_to_close.append((pos["id"], reason, cur_p))
                    # (e) Donchian modu seans-flat (araştırma: NY öğleden sonrası negatif;
                    #     XAU/BTC muaf — onlarda mod ek akış olarak 24h çalışır)
                    elif (sym in {s.upper() for s in (_AUTO_SETTINGS.mode_symbols or [])}
                          and "XAU" not in sym and "BTC" not in sym
                          and datetime.datetime.now(datetime.timezone.utc).hour == 16):
                        positions_to_close.append((pos["id"], "SEANS16", cur_p))

            # Pozisyonları kapat
            for pid, rsn, p_exit in positions_to_close:
                await _close_position_internal(pid, rsn, p_exit)

            # ---------------------------------------------------------------
            # 2. YENİ İŞLEM FIRSATLARI DEĞERLENDİRME & GİRİŞ (IC MARKETS MT5)
            # ---------------------------------------------------------------
            active_count = len(_MT5_STATE.get("open_positions", [])) if _MT5_STATE.get("connected") else len(_AUTO_STATE.get("open_positions", []))
            if active_count >= _AUTO_SETTINGS.max_open_positions:
                if now_ts - _LAST_SCAN_PULSE_TIME > 30.0:
                    _LAST_SCAN_PULSE_TIME = now_ts
                    _log_auto_decision(
                        "GATE",
                        f"Maksimum açık pozisyon limitine ulaşıldı ({active_count}/{_AUTO_SETTINGS.max_open_positions}). Yeni emir beklemede.",
                    )
                continue

            # Seans Filtresi Kontrolü
            active_names = [s["name"] for s in sessions if s["active"]]
            any_session_active = len(active_names) > 0
            if _AUTO_SETTINGS.session_filter and not any_session_active:
                if now_ts - _LAST_SESSION_BLOCK_LOG_TIME > 120:
                    _LAST_SESSION_BLOCK_LOG_TIME = now_ts
                    _log_auto_decision(
                        "GATE",
                        "Hafta sonu Forex piyasası kapalı. Yeni seans açılışı bekleniyor.",
                    )
                continue

            # Zayıf Saat Kalkanı: Geçmiş işlem verisinde istatistiksel kayıp üreten
            # UTC saatlerinde (varsayılan 05:00 ve 15:00) yeni işlem açılmaz.
            # Açık pozisyon yönetimi (BE/trailing/TP/SL) aynen devam eder.
            current_utc_hour = datetime.datetime.now(datetime.timezone.utc).hour
            if is_entry_hour_blocked(current_utc_hour, _AUTO_SETTINGS.blocked_hours_utc):
                if now_ts - _LAST_BLOCKED_HOUR_LOG_TIME > 120.0:
                    _LAST_BLOCKED_HOUR_LOG_TIME = now_ts
                    _log_auto_decision(
                        "GATE",
                        f"⏰ Zayıf Saat Kalkanı: UTC {current_utc_hour:02d}:00 saati geçmiş veride istatistiksel kayıp üretiyor. Yeni işlem girişleri bu saat boyunca kapalı.",
                    )
                continue

            # Radar Sinyallerini Al
            radar_res = await get_forex_radar()
            candidates = radar_res.get("candidates", [])
            dxy_regime = radar_res.get("dxy")

            # Donchian+ADX giriş modu (2026-10-07 kalibrasyonu): mode_symbols için radar
            # adayına EK aday üretir; mode_exclusive sembollerin klasik adayları düşürülür.
            _mode_syms = {s.upper() for s in (_AUTO_SETTINGS.mode_symbols or [])}
            _mode_excl = {s.upper() for s in (_AUTO_SETTINGS.mode_exclusive or [])}
            if _mode_excl:
                candidates = [c for c in candidates if str(c.get("symbol", "")).upper() not in _mode_excl]
            if _mode_syms:
                for _m_sym in _mode_syms:
                    _m_t = ticks.get(_m_sym)
                    _m_tech = _TECHNICAL_CACHE.get(_m_sym) or {}
                    if not _m_t or not _m_tech or _m_tech.get("donch_mid") is None:
                        continue
                    _m_price = (_m_t.get("bid", 0.0) + _m_t.get("ask", 0.0)) / 2.0 or _m_tech.get("price", 0.0)
                    _m_pip_size = _m_tech.get("pip_size") or next((i["pip_size"] for i in FOREX_SYMBOLS if i["symbol"] == _m_sym), 0.0001)
                    if _m_price <= 0 or _m_pip_size <= 0:
                        continue
                    _m_now = datetime.datetime.now(datetime.timezone.utc)
                    _m_day = _m_now.toordinal()
                    _m_st = _DONCHIAN_STATE.setdefault(_m_sym, {"prev_close": None, "prev_mid": None, "day": _m_day, "counts": {}})
                    if _m_st["day"] != _m_day:
                        _m_st["day"] = _m_day
                        _m_st["counts"] = {}
                    _m_action = donchian_adx_entry(
                        prev_close=_m_st["prev_close"], prev_mid=_m_st["prev_mid"],
                        close=_m_price, mid=float(_m_tech["donch_mid"]),
                        adx=float(_m_tech.get("adx", 25.0)), adx_min=18.0,
                        day=_m_day, day_counts=_m_st["counts"], max_per_day=2,
                        hour_utc=_m_now.hour, is_jpy=("JPY" in _m_sym.upper()),
                    )
                    _m_st["prev_close"] = _m_price
                    _m_st["prev_mid"] = float(_m_tech["donch_mid"])
                    # Görünürlük: mod ne beklediğini 30 dk'da bir insan-okur cümleyle söyler;
                    # kapsam dışıysa bunu da açıkça yazar (sessiz blok yok).
                    _m_not_allowed = _m_sym not in {s.upper() for s in (_AUTO_SETTINGS.allowed_symbols or [])}
                    _m_wait_throttled = now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{_m_sym}_donch_wait", 0.0) > 1800.0
                    if _m_wait_throttled:
                        _LAST_CANDIDATE_LOG_TIME[f"{_m_sym}_donch_wait"] = now_ts
                        _m_disp = _m_t["display"] if _m_t else _m_sym
                        _m_side = "üstünde" if _m_price > float(_m_tech["donch_mid"]) else "altında"
                        if _m_not_allowed:
                            _log_auto_decision(
                                "SCAN",
                                f"⚠️ [{_m_disp}] Donchian modu aktif AMA sembol panel kapsamında değil (allowed_symbols) — işlem için panele eklenmeli.",
                                symbol=_m_sym,
                            )
                        else:
                            _m_adx_txt = f"ADX {float(_m_tech.get('adx', 0)):.0f}"
                            _m_wait = ("fiyat orta hattın üstüne dönüp yeniden kırılınca SAT" if _m_price <= float(_m_tech["donch_mid"]) else "fiyat orta hattın altına sarkıp yeniden kırılınca AL")
                            _log_auto_decision(
                                "SCAN",
                                f"🎯 [{_m_disp}] Donchian modu bekliyor: fiyat orta hattın {_m_side} ({_m_price:.3f} / orta {float(_m_tech['donch_mid']):.3f}), {_m_adx_txt} → {_m_wait}. Klasik sinyaller bu çiftte yok sayılır.",
                                symbol=_m_sym,
                            )
                    if _m_action:
                        _m_st["counts"][_m_action] = _m_st["counts"].get(_m_action, 0) + 1
                        _m_atr = float(_m_tech.get("atr", 0.0))
                        _m_item = next((i for i in FOREX_SYMBOLS if i["symbol"] == _m_sym), None)
                        candidates = [c for c in candidates if str(c.get("symbol", "")).upper() != _m_sym] + [{
                            "symbol": _m_sym,
                            "display": _m_item["display"] if _m_item else _m_sym,
                            "action": _m_action,
                            "score": 200.0,
                            "spread_pips": _LIVE_SPREAD_PIPS.get(_m_sym, 2.0),
                            "atr_pips": round(_m_atr / _m_pip_size, 1) if _m_pip_size > 0 else 15.0,
                            "adx": float(_m_tech.get("adx", 25.0)),
                            "supertrend_dir": int(_m_tech.get("supertrend_dir", 0)),
                            "entry_source": "donchian",
                        }]
                        _log_auto_decision(
                            "SCAN",
                            f"🎯 [{_m_item['display'] if _m_item else _m_sym}] Donchian kırılımı: {_m_action} adayı (ADX {_m_tech.get('adx', 0):.0f}) — değerlendiriliyor.",
                            symbol=_m_sym,
                        )

            # Periyodik Canlı Tarama Özeti (Her 15 saniyede bir Decision Stream'e düşer)
            if now_ts - _LAST_SCAN_PULSE_TIME > 15.0 and candidates:
                _LAST_SCAN_PULSE_TIME = now_ts
                active_str = ", ".join(active_names) if active_names else "24/5 Açık"
                top_3 = ", ".join([f"{c['display']} (Skor:{c['score']:.0f} {c['action']})" for c in candidates[:3]])
                _log_auto_decision(
                    "SCAN",
                    f"🔍 Radar Taraması: {len(candidates)} parite analiz edildi. [Öncü: {top_3}] (Seanslar: {active_str})",
                )
                # XAU/USD tarama özeti: her taramada altının durumu tek temiz cümleyle stream'e düşer
                gold_tick = ticks.get("XAUUSD")
                if gold_tick:
                    if gold_tick.get("macd_verdict") == "NÖTR (Veri Bekleniyor)":
                        gold_msg = "🔍 [XAU/USD] Piyasa verisi alınamıyor — sinyal üretilemiyor"
                    else:
                        gold_action = str(gold_tick.get("action", "HOLD"))
                        gold_signal = (
                            f"Sinyal: {gold_action} (skor {gold_tick.get('score', 0.0):.0f})"
                            if gold_action in ("BUY", "SELL") else "Sinyal: yok"
                        )
                        tech_gold = _TECHNICAL_CACHE.get("XAUUSD") or {}
                        gold_st = "BOĞA" if int(gold_tick.get("supertrend_dir", 0)) > 0 else "AYI"
                        gold_msg = (
                            f"🔍 [XAU/USD] {gold_tick.get('bid', 0.0):.2f}$ | {gold_signal} | "
                            f"HTF: {tech_gold.get('htf_trend', '-')} | SuperTrend: {gold_st} | "
                            f"Durum: {_gold_scan_note(gold_tick, now_ts)}"
                        )
                    _log_auto_decision("SCAN", gold_msg, symbol="XAUUSD")

                # BTC/USD tarama özeti: her taramada BTC durumu da Altın gibi detaylı stream'e düşer
                btc_tick = ticks.get("BTCUSD")
                if btc_tick:
                    if btc_tick.get("macd_verdict") == "NÖTR (Veri Bekleniyor)":
                        btc_msg = "🔍 [BTC/USD] Piyasa verisi alınamıyor — sinyal üretilemiyor"
                    else:
                        btc_action = str(btc_tick.get("action", "HOLD"))
                        btc_signal = (
                            f"Sinyal: {btc_action} (skor {btc_tick.get('score', 0.0):.0f})"
                            if btc_action in ("BUY", "SELL") else "Sinyal: yok"
                        )
                        tech_btc = _TECHNICAL_CACHE.get("BTCUSD") or {}
                        btc_st = "BOĞA" if int(btc_tick.get("supertrend_dir", 0)) > 0 else "AYI"
                        btc_msg = (
                            f"🔍 [BTC/USD] {btc_tick.get('bid', 0.0):.1f}$ | {btc_signal} | "
                            f"HTF: {tech_btc.get('htf_trend', '-')} | SuperTrend: {btc_st} | "
                            f"Durum: {_btc_scan_note(btc_tick, now_ts)}"
                        )
                    _log_auto_decision("SCAN", btc_msg, symbol="BTCUSD")

            # Veri hattı görünürlüğü: mum verisi alınamayan semboller HOLD'da sessizce kalır.
            # Sessiz arıza olmasın — panelde sembol başına 5 dk'da bir görünür yapılır.
            for t_item in ticks.values():
                sym_item = t_item.get("symbol", "").upper()
                if sym_item in _AUTO_SETTINGS.allowed_symbols and t_item.get("macd_verdict") == "NÖTR (Veri Bekleniyor)":
                    if now_ts - _LAST_DATA_GAP_LOG.get(sym_item, 0.0) > 300.0:
                        _LAST_DATA_GAP_LOG[sym_item] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"📡 [{t_item['display']}] Veri Hattı: Yahoo mum verisi alınamıyor — bu sembol sinyal üretemiyor (veri gelince otomatik devam eder).",
                            symbol=sym_item,
                        )

            mt5_active_syms = {p.get("symbol", "").upper() for p in _MT5_STATE.get("open_positions", [])}
            auto_active_syms = {p.get("symbol", "").upper() for p in _AUTO_STATE.get("open_positions", [])}
            pending_mt5_syms = {c.get("symbol", "").upper() for c in _MT5_STATE.get("pending_commands", []) if c.get("action") == "OPEN_ORDER"}
            all_active_syms = mt5_active_syms | auto_active_syms | pending_mt5_syms

            for cand in candidates:
                sym = cand["symbol"].upper()
                # Kapsam kapısı kesindir: güçlü sinyal bile allowed_symbols dışına işlem açamaz
                # (2026-10-07 kalibrasyonu: 28/28 FX çifti klasik sinyalle negatif — bypass yok).
                if sym not in _AUTO_SETTINGS.allowed_symbols:
                    continue

                # Seri-SL Soğuması: sembol ardışık tam-SL kayıplarından sonra kısa süre
                # YENİ giriş almaz (flip dahil); açık pozisyon yönetimi aynen sürer.
                if _AUTO_SETTINGS.loss_streak_limit > 0:
                    ser_cd_until = _SYMBOL_LOSS_COOLDOWN_UNTIL.get(sym, 0.0)
                    if now_ts < ser_cd_until:
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_seri", 0.0) > 30.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_seri"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"🌡️ [{cand['display']}] Seri-SL Soğuması: {_AUTO_SETTINGS.loss_streak_limit} ardışık SL kaybı — {int(ser_cd_until - now_ts)} sn yeni giriş yok (süre bitince sembol normal değerlendirilir).",
                                symbol=sym,
                            )
                        continue

                # 1. Zaten açık pozisyon veya bekleyen MT5 emri var mı? (Anti-Duplicate & Position Reversal/Flip)
                new_action = cand.get("action", "")  # "BUY" or "SELL"
                if new_action not in ("BUY", "SELL"):
                    continue

                if sym in all_active_syms:
                    existing_dirs = set()
                    matching_auto = [p for p in _AUTO_STATE.get("open_positions", []) if p.get("symbol", "").upper() == sym]
                    matching_mt5 = [p for p in _MT5_STATE.get("open_positions", []) if p.get("symbol", "").upper() == sym]
                    matching_pending = [c for c in _MT5_STATE.get("pending_commands", []) if c.get("action") == "OPEN_ORDER" and c.get("symbol", "").upper() == sym]

                    for p in matching_auto:
                        existing_dirs.add(p.get("direction", "").upper())
                    for p in matching_mt5:
                        existing_dirs.add(p.get("direction", "").upper())
                    for c in matching_pending:
                        existing_dirs.add(c.get("direction", "").upper())

                    opposite_dirs = {d for d in existing_dirs if d != new_action}

                    if opposite_dirs:
                        # (b) ZIT yönlü pozisyon varsa (örn: BUY açıkken SELL sinyali geldiyse veya tersi):
                        # Ve sinyal yeterince güçlüyse (skor >= min_score ve spread uygunsa)
                        effective_spread_limit = max(50.0, _AUTO_SETTINGS.max_spread_pips * 10) if ("BTC" in sym or "ETH" in sym) else _AUTO_SETTINGS.max_spread_pips
                        if cand.get("score", 0.0) >= _AUTO_SETTINGS.min_score and cand.get("spread_pips", 99.0) <= effective_spread_limit:
                            old_dir_str = "/".join(opposite_dirs)
                            _log_auto_decision(
                                "REVERSAL",
                                f"🔄 [{cand['display']}] TREND DÖNÜŞÜ (FLIP): Açık {old_dir_str} pozisyonu kapatılıyor -> Yeni {new_action} açılıyor! (Skor: {cand['score']:.1f})",
                                symbol=sym,
                            )
                            # Önce açık auto-paper ZIT pozisyonunu kapat
                            for ap in matching_auto:
                                if ap.get("direction", "").upper() in opposite_dirs:
                                    t_sym = ticks.get(sym)
                                    exit_p = (t_sym["bid"] if ap.get("direction") == "BUY" else t_sym["ask"]) if t_sym else None
                                    await _close_position_internal(ap["id"], "REVERSAL_FLIP", exit_p)

                            # MT5 açık ZIT pozisyonu varsa kapatma komutu ilet
                            for mp in matching_mt5:
                                if mp.get("direction", "").upper() in opposite_dirs:
                                    t_id = mp.get("ticket")
                                    if t_id:
                                        _MT5_STATE["pending_commands"].append({
                                            "id": f"CMD-CLOSE-{t_id}-FLIP",
                                            "action": "CLOSE_ORDER",
                                            "ticket": t_id,
                                        })

                            # Eski ZIT yöndeki bekleyen emirler varsa temizle
                            _MT5_STATE["pending_commands"] = [
                                c for c in _MT5_STATE.get("pending_commands", [])
                                if not (c.get("action") == "OPEN_ORDER" and c.get("symbol", "").upper() == sym and c.get("direction") != new_action)
                            ]

                            # Anında ters yöne geçebilmek için sembol soğumasını sıfırla
                            _LAST_SYMBOL_ENTRY_TIME[sym] = 0.0
                            if "XAU" in sym or "GOLD" in sym:
                                _LAST_GOLD_EXIT_TIME = 0.0

                            # Döngü devam eder ve aşağıda yeni new_action (BUY/SELL) emrini açar!
                        else:
                            # Zıt yönlü ama skor eşiğini henüz aşmamışsa mevcut işlemi bozma
                            continue

                    elif new_action in existing_dirs:
                        # (a) Aynı yönlü pozisyon zaten açıksa (örn: BUY açıkken tekrar BUY)
                        same_dir_count = sum(1 for p in matching_auto if p.get("direction", "").upper() == new_action) + \
                                         sum(1 for p in matching_mt5 if p.get("direction", "").upper() == new_action) + \
                                         sum(1 for c in matching_pending if c.get("direction", "").upper() == new_action)

                        max_pyr = _AUTO_SETTINGS.max_positions_per_symbol  # Varsayılan: 3
                        if same_dir_count >= max_pyr:
                            if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_max_pyr", 0) > 40.0:
                                _LAST_CANDIDATE_LOG_TIME[f"{sym}_max_pyr"] = now_ts
                                _log_auto_decision(
                                    "SCAN",
                                    f"[{cand['display']}] Tarandı: Skor {cand['score']:.1f} ({new_action}) fakat bu yönde maksimum {max_pyr} pozisyon zaten açık ({same_dir_count}/{max_pyr}). Yeni giriş pas geçildi.",
                                    symbol=sym,
                                )
                            continue

                        # KRİTİK KÂRLILIK KURALI: Yalnızca KÂRDAKİ Pozisyona Ekleme Yap (Winning Pyramiding)
                        # Mevcut açık pozisyonların toplam kârı >= +0.20$ olmalı!
                        # Zarardaki pozisyona maliyet düşürme (averaging down) KESİNLİKLE ENGELLENİR!
                        existing_pnl_usd = sum(p.get("pnl_usd", 0.0) for p in matching_auto if p.get("direction", "").upper() == new_action) + \
                                           sum(float(getattr(p, "profit", p.get("pnl_usd", 0.0))) for p in matching_mt5 if p.get("direction", "").upper() == new_action)
                        if existing_pnl_usd < 0.20:
                            if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_pyr_loss", 0) > 30.0:
                                _LAST_CANDIDATE_LOG_TIME[f"{sym}_pyr_loss"] = now_ts
                                _log_auto_decision(
                                    "GATE",
                                    f"[{cand['display']}] Piramitleme Kalkanı: Mevcut açık {same_dir_count} pozisyon henüz kârda değil (${existing_pnl_usd:+.2f}). Zarara ekleme engellendi (Kazanana ekleme kuralı).",
                                    symbol=sym,
                                )
                            continue

                        # 1 dakika (60 sn) aralık denetimi
                        last_entry_ts = _LAST_SYMBOL_ENTRY_TIME.get(sym, 0.0)
                        time_since_entry = now_ts - last_entry_ts
                        if time_since_entry < 60.0:
                            rem_sec = int(60.0 - time_since_entry)
                            if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_same_cd", 0) > 20.0:
                                _LAST_CANDIDATE_LOG_TIME[f"{sym}_same_cd"] = now_ts
                                _log_auto_decision(
                                    "SCAN",
                                    f"[{cand['display']}] Tarandı: Skor {cand['score']:.1f} ({new_action}) - Aynı yönde ek pozisyon için 1 dk kuralı ({same_dir_count}/{max_pyr} açık, {rem_sec} sn kaldı).",
                                    symbol=sym,
                                )
                            continue

                        # 60 saniye dolduysa ve count < 3 ise ve pozisyon kârdaysa: Aynı yönde ekleme onaylandı!
                        _log_auto_decision(
                            "SCAN",
                            f"[{cand['display']}] 📈 KÂRDA EK POZİSYON ONAYLANDI: Skor {cand['score']:.1f} ({new_action}) | Mevcut Kâr: ${existing_pnl_usd:+.2f} ({same_dir_count + 1}/{max_pyr}. pozisyon).",
                            symbol=sym,
                        )

                is_gold = ("XAU" in sym or "GOLD" in sym)

                # 2. Ons Altın (XAUUSD) Özel Soğuma Koruması
                # İlk start verildiğinde veya henüz kapanış olmadığında (<= 0) soğuma kalkanı dikkate alınmaz
                if is_gold and _LAST_GOLD_EXIT_TIME > 0:
                    if _LAST_GOLD_EXIT_TIME > now_ts:
                        _LAST_GOLD_EXIT_TIME = now_ts
                    time_since_gold_exit = max(0.0, now_ts - _LAST_GOLD_EXIT_TIME)
                    if time_since_gold_exit < _AUTO_SETTINGS.gold_cooldown_sec:
                        remaining_cd = int(min(_AUTO_SETTINGS.gold_cooldown_sec, max(0.0, _AUTO_SETTINGS.gold_cooldown_sec - time_since_gold_exit)))
                        if remaining_cd > 0 and (now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_gold_cd", 0) > 30.0):
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_gold_cd"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}] Ons Altın Soğuma Kalkanı: Kapanıştan sonra {remaining_cd} sn bekleniyor (min {_AUTO_SETTINGS.gold_cooldown_sec:.0f} sn kuralı).",
                                symbol=sym,
                            )
                        continue

                # 2b. Bitcoin (BTCUSD) Özel Soğuma Koruması (Kullanıcı kararı: 60 sn)
                # İlk start verildiğinde veya henüz kapanış olmadığında (<= 0) soğuma kalkanı dikkate alınmaz
                is_btc = ("BTC" in sym)
                if is_btc and _LAST_BTC_EXIT_TIME > 0:
                    if _LAST_BTC_EXIT_TIME > now_ts:
                        _LAST_BTC_EXIT_TIME = now_ts
                    time_since_btc_exit = max(0.0, now_ts - _LAST_BTC_EXIT_TIME)
                    if time_since_btc_exit < 60.0:
                        remaining_btc_cd = int(min(60.0, max(0.0, 60.0 - time_since_btc_exit)))
                        if remaining_btc_cd > 0 and (now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_btc_cd", 0) > 20.0):
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_btc_cd"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}] Bitcoin Soğuma Kalkanı: Kapanıştan sonra {remaining_btc_cd} sn bekleniyor (min 60 sn kuralı).",
                                symbol=sym,
                            )
                        continue

                # 3. Sembol Soğuma Süresi
                sym_cd = _AUTO_SETTINGS.gold_cooldown_sec if is_gold else 60.0
                last_sym_time = _LAST_SYMBOL_ENTRY_TIME.get(sym, 0.0)
                if last_sym_time > now_ts:
                    _LAST_SYMBOL_ENTRY_TIME[sym] = now_ts
                    last_sym_time = now_ts
                time_since_sym = max(0.0, now_ts - last_sym_time)
                sym_cd_left = max(0.0, min(sym_cd, sym_cd - time_since_sym))
                if sym_cd_left > 0:
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_symcd", 0) > 30.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_symcd"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}] Sembol Soğuma Kalkanı: Son girişten sonra {int(sym_cd_left)} sn bekleniyor (min {sym_cd:.0f} sn kuralı).",
                            symbol=sym,
                        )
                    continue

                # 3b. Sembol EV Kalkanı — son pencerede sermaye yakan semboller dinlenir
                # (Kullanıcı kararı: XAUUSD ve BTCUSD özel modda 24 saatlik EV kilidi yerine 60 sn soğuma uygulanır)
                if _AUTO_SETTINGS.ev_guard_enabled and sym not in ("XAUUSD", "BTCUSD"):
                    ev_balance = float(_MT5_STATE.get("account", {}).get("balance", _AUTO_STATE["balance"])) if _MT5_STATE.get("connected") else float(_AUTO_STATE["balance"])
                    ev_risk_usd = ev_balance * (_AUTO_SETTINGS.risk_per_trade_pct / 100.0)
                    ev_stats = _collect_symbol_ev(sym, now_ts, _AUTO_SETTINGS.ev_window_hours * 3600.0)
                    if ev_guard_decision(ev_stats, _AUTO_SETTINGS.ev_min_trades,
                                         _AUTO_SETTINGS.ev_max_win_rate,
                                         ev_risk_usd * _AUTO_SETTINGS.ev_loss_risk_mult):
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_ev", 0) > 60.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_ev"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}] Sembol EV Kalkanı: Son {ev_stats['n']} işlemde ${ev_stats['net']:+.2f} "
                                f"(WR %{ev_stats['win_rate']:.0f}) — sembol {_AUTO_SETTINGS.ev_window_hours:.0f} saatlik pencere boyunca dinlenmeye alındı.",
                                symbol=sym,
                            )
                        continue

                # 4. DXY (ABD Dolar Endeksi) Rejim Filtresi
                # Pozisyon DXY rejimiyle çelişiyorsa veto; zayıf semboller nötr rejimde ekstra skor ister.
                direction = cand.get("action", "")  # BUY or SELL
                if direction not in ("BUY", "SELL"):
                    continue

                weak_symbol_score_bump = 0.0
                if _AUTO_SETTINGS.dxy_filter_enabled:
                    veto_reason = dxy_entry_veto(sym, direction, dxy_regime)
                    if veto_reason == "dxy_conflict":
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_dxy", 0) > 30.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_dxy"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}] DXY Kalkanı: {direction} yönü dolar rejimiyle ({dxy_regime.get('regime')}) çelişiyor. İşlem engellendi.",
                                symbol=sym,
                            )
                        continue
                    if veto_reason == "dxy_strict_neutral":
                        weak_symbol_score_bump = 5.0

                # (Eski "USD Korelasyon Kalkanı" kaldırıldı — kullanıcı kararı.
                # Kaba USD-yön sayacı yerine 5b'deki gerçek Pearson korelasyon kalkanı koruyor.)
                # 5b. Parite Korelasyon Kalkanı (FX Correlation Cluster Guard)
                # |ρ|>=0.85 aynı USD bias'lı çakışma ve yüksek korelasyonlu küme girişlerini sınırlar.
                cand_usd_bias = get_usd_bias(sym, direction)
                if _AUTO_SETTINGS.correlation_guard and cand_usd_bias != "USD_NEUTRAL":
                    corr_positions: List[tuple] = []
                    for p in list(_MT5_STATE.get("open_positions", [])) + list(_AUTO_STATE.get("open_positions", [])):
                        corr_positions.append((
                            str(p.get("symbol", "")).upper(),
                            get_usd_bias(p.get("symbol", ""), p.get("direction", "BUY")),
                        ))
                    for c in _MT5_STATE.get("pending_commands", []):
                        if c.get("action") == "OPEN_ORDER":
                            corr_positions.append((
                                str(c.get("symbol", "")).upper(),
                                get_usd_bias(c.get("symbol", ""), c.get("direction", "BUY")),
                            ))
                    corr_ok, corr_reason = _FX_CORR.cluster_check(sym, cand_usd_bias, corr_positions)
                    if not corr_ok:
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_fxcorr", 0) > 30.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_fxcorr"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}] Korelasyon Kalkanı: {cand_usd_bias} yönlü yüksek korelasyonlu açık pozisyon var ({corr_reason}). Aynı teze ikinci kapıdan giriş engellendi.",
                                symbol=sym,
                            )
                        continue

                # 5c. Majör FX güçlendirme kapıları (seans penceresi + volatilite tabanı;
                # 2026-10-07 doğrulama: filtre kâr ediyor — Asya girişlerinin gölge defteri −$5.939)
                gate_reason = major_entry_gate_decision(
                    sym, current_utc_hour, float(cand.get("atr_pips", 0.0)),
                    _AUTO_SETTINGS.major_session_filter,
                    _AUTO_SETTINGS.major_session_start_utc, _AUTO_SETTINGS.major_session_end_utc,
                    _AUTO_SETTINGS.major_min_atr_pips,
                )
                if gate_reason:
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_major", 0) > 30.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_major"] = now_ts
                        reason_str = ("Majör Seans Filtresi: UTC saat penceresi dışında (Asya seansı chop riski)."
                                      if gate_reason == "major_session" else
                                      f"Majör Volatilite Tabanı: ATR {float(cand.get('atr_pips', 0.0)):.1f}p < "
                                      f"{_AUTO_SETTINGS.major_min_atr_pips:.1f}p — ölü piyasa.")
                        _log_auto_decision("GATE", f"[{cand['display']}] {reason_str} İşlem engellendi.", symbol=sym)
                    continue

                # 6. Spread Filtresi
                effective_max_spread = max(50.0, _AUTO_SETTINGS.max_spread_pips * 10) if ("BTC" in sym or "ETH" in sym) else _AUTO_SETTINGS.max_spread_pips
                if cand["spread_pips"] > effective_max_spread:
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_spread", 0) > 25.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_spread"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}] Tarandı: Spread engeli ({cand['spread_pips']:.1f}p > {effective_max_spread:.1f}p limit). İşlem engellendi.",
                            symbol=sym,
                        )
                    continue

                # 7. Skor Eşiği (Ons Altın ve Emtialar için min 78.0 yüksek teyit)
                # DXY nötr rejimdeki zayıf semboller (XAUUSD/USDJPY/USDCHF) +5.0 ekstra skor ister.
                is_commodity = is_gold or ("OIL" in sym or "USOIL" in sym)
                if sym == "BTCUSD":
                    # Paneldeki btc_min_score ayarı varsa doğrudan BTC'ye özel eşik olarak çalışır
                    req_score = _AUTO_SETTINGS.btc_min_score if _AUTO_SETTINGS.btc_min_score > 0 else _AUTO_SETTINGS.min_score
                else:
                    req_score = 78.0 if is_commodity else _AUTO_SETTINGS.min_score
                req_score += weak_symbol_score_bump
                if cand["score"] < req_score:
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_score", 0) > 25.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_score"] = now_ts
                        _log_auto_decision(
                            "SCAN",
                            f"[{cand['display']}] Tarandı: Skor yetersiz ({cand['score']:.1f} < {req_score:.0f} eşik) | Yön: {cand['action']} | Spread: {cand['spread_pips']:.1f}p | Beklemede.",
                            symbol=sym,
                        )
                    continue

                # 7b. ADX Trend Gücü Kalkanı — çalkantılı/yönsüz piyasada trend girişi yapılmaz
                adx_val = float(cand.get("adx", 25.0))
                if _AUTO_SETTINGS.adx_filter_enabled and adx_val < _AUTO_SETTINGS.adx_min:
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_adx", 0) > 30.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_adx"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}] ADX Kalkanı: Trend gücü yetersiz (ADX {adx_val:.1f} < {_AUTO_SETTINGS.adx_min:.0f}) — piyasa yönsüz. İşlem engellendi.",
                            symbol=sym,
                        )
                    continue

                # 7c. SuperTrend Yön Teyidi — giriş yalnızca SuperTrend tarafıyla uyumlu açılır
                st_dir = int(cand.get("supertrend_dir", 0))
                if _AUTO_SETTINGS.supertrend_filter_enabled and st_dir != 0:
                    if (direction == "BUY" and st_dir < 0) or (direction == "SELL" and st_dir > 0):
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_st", 0) > 30.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_st"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}] SuperTrend Teyidi: {direction} yönü SuperTrend yönüyle ({'BOĞA' if st_dir > 0 else 'AYI'}) çelişiyor. İşlem engellendi.",
                                symbol=sym,
                            )
                        continue

                # 8. Dinamik Lot & Sert Lot Tavanı (Hard Lot Cap)
                t = ticks.get(sym)
                if not t:
                    continue

                atr_pips = round(t.get("atr", 0.001) / t["pip_size"], 1) if t.get("pip_size", 0) > 0 else 15.0
                spec = get_symbol_trading_specs(
                    sym,
                    base_sl=_AUTO_SETTINGS.sl_pips,
                    base_tp=_AUTO_SETTINGS.tp_pips,
                    base_be=_AUTO_SETTINGS.breakeven_pips,
                    base_trail=_AUTO_SETTINGS.trailing_stop_pips,
                    atr_pips=atr_pips,
                )
                sl_pips = spec["sl_pips"]
                tp_pips = spec["tp_pips"]
                pip_val = spec["pip_val"]

                # ATR bazlı dinamik çıkış motoru: TP'yi volatiliteye çeker,
                # SL'e volatilite nefes payı ekler (gürültü stoplarını azaltır).
                first_target_pips = 0.0
                if _AUTO_SETTINGS.atr_exit_enabled:
                    if _AUTO_SETTINGS.crypto_sl_atr_mult > 0 and ("BTC" in sym or "ETH" in sym):
                        # Kripto özel stop genişliği: 1.1×ATR kriptoda dar kalıyor (2026-10-06 replay kazananı)
                        atr_levels = get_atr_exit_levels(
                            atr_pips, spec["sl_pips"], spec["tp_pips"],
                            sl_atr_mult=_AUTO_SETTINGS.crypto_sl_atr_mult)
                    else:
                        atr_levels = get_atr_exit_levels(atr_pips, spec["sl_pips"], spec["tp_pips"])
                    sl_pips = atr_levels["sl_pips"]
                    tp_pips = atr_levels["tp_pips"]
                    if _AUTO_SETTINGS.partial_tp_enabled:
                        first_target_pips = atr_levels["first_target_pips"]
                if str(cand.get("entry_source", "")) == "donchian" and atr_pips > 0:
                    # Donchian modu çıkışları (replay ile birebir): SL 2×ATR, TP 4×ATR, kısmi kâr yok
                    sl_pips = round(2.0 * atr_pips, 1)
                    tp_pips = round(4.0 * atr_pips, 1)
                    first_target_pips = 0.0

                active_bal = float(_MT5_STATE.get("account", {}).get("balance", _AUTO_STATE["balance"])) if _MT5_STATE.get("connected") else float(_AUTO_STATE["balance"])
                risk_usd = active_bal * (_AUTO_SETTINGS.risk_per_trade_pct / 100.0)
                raw_calc_lots = round(risk_usd / (sl_pips * pip_val), 2)

                # Dinamik Lot & Risk Hesaplama (Modalda belirlenen risk yüzdesine göre)
                is_index = ("NAS" in sym or "USTEC" in sym or "US30" in sym or "SPX" in sym)
                is_oil = ("USOIL" in sym or "OIL" in sym or "WTI" in sym or "XTI" in sym)
                is_crypto = ("BTC" in sym or "ETH" in sym)
                if is_crypto and not _AUTO_SETTINGS.crypto_tp_enabled:
                    # Kriptoda sabit TP kapalı (2026-10-06 30g replay kazananı: BTC −$55.70→−$18.02):
                    # kazanç BE kilidi + trailing ile koşturulur, TP emri kurulmaz.
                    tp_pips = 0.0

                if is_index:
                    lot_ceiling = 50.0
                    mt5_lots = max(0.10, min(round(raw_calc_lots * 10) / 10, lot_ceiling))
                elif is_oil:
                    # Petrol: replay'de doğrulanan muhafazakâr profil (0.50–1.0 lot; 2026-10-06).
                    # 50.0 tavan, replay'de test edilmeyen 50x risk alirdi — asla geri yükseltme!
                    lot_ceiling = 1.0
                    mt5_lots = max(0.50, min(raw_calc_lots, lot_ceiling))
                elif is_gold:
                    lot_ceiling = min(HARD_MAX_GOLD_LOT, _AUTO_SETTINGS.max_gold_lot)
                    mt5_lots = max(0.01, min(raw_calc_lots, lot_ceiling))
                elif is_crypto:
                    lot_ceiling = 50.0
                    mt5_lots = max(0.01, min(raw_calc_lots, lot_ceiling))
                else:
                    lot_ceiling = min(HARD_MAX_FOREX_LOT, _AUTO_SETTINGS.max_forex_lot)
                    mt5_lots = max(0.01, min(raw_calc_lots, lot_ceiling))
                mt5_lots = round(mt5_lots, 2)

                # 8b. Risk Normalizasyonu: ATR ile genişleyen SL'de lot tavanı risk
                # bütçesini aşabilir (gerçek örnek: US30 0.20 lot × 81.7 pip = %1.6).
                # Lot bütçeye çekilir; kategori minimumu bile sert sınırı aşıyorsa pas.
                mt5_lots, risk_skip = apply_risk_normalization(sym, mt5_lots, sl_pips, pip_val, risk_usd)
                if risk_skip:
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_risk", 0) > 30.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_risk"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}] Risk Kalkanı: SL {sl_pips:.0f}p ile en küçük mümkün lot bile "
                            f"{_AUTO_SETTINGS.risk_per_trade_pct:.1f}% bütçenin 2 katını aşıyor. İşlem pas geçildi.",
                            symbol=sym,
                        )
                    continue

                entry_p = t["ask"] if direction == "BUY" else t["bid"]

                # IC Markets MT5 bağlıysa doğrudan MT5 emir kuyruğuna ekle
                if _MT5_STATE.get("connected") and _MT5_STATE.get("auto_trade"):
                    cmd_id = f"CMD-{int(time.time() * 1000) % 1000000}"
                    # Çıkış planı: köprünün dynamic-exits spec'iyle BİREBİR değerler (ATR'siz,
                    # base_sl=8 default — 2 pencere replay kazananı A davranışı). Değerler pozisyon
                    # bazlı cmd ile taşınır → köprü kendi spec kopyasından ikinci kez hesaplamaz
                    # (çift-kaynak drift kapanır); ileride BE/Trail'i canlıdan değiştirmek tek satır.
                    spec_exits = get_symbol_trading_specs(
                        sym, base_sl=8.0,
                        base_be=_AUTO_SETTINGS.breakeven_pips,
                        base_trail=_AUTO_SETTINGS.trailing_stop_pips)
                    _MT5_STATE["pending_commands"].append({
                        "id": cmd_id,
                        "action": "OPEN_ORDER",
                        "symbol": sym,
                        "direction": direction,
                        "lots": mt5_lots,
                        "sl_pips": sl_pips,
                        "tp_pips": tp_pips,
                        # Pozisyon bazlı çıkış planı: köprü BE/Trail'i motorun gönderdiği değerlerle
                        # yönetsin (köprünün kendi spec kopyası ikinci kez hesap yapmaz)
                        "be_pips": spec_exits["be_pips"],
                        "trail_pips": spec_exits["trail_pips"],
                        "be_lock_ratio": _AUTO_SETTINGS.gold_be_lock_ratio if is_gold else 0.40,
                        "partial_pips": first_target_pips,
                        "comment": f"Scalper MT5 {cand['score']:.0f}",
                    })
                else:
                    # MT5 bağlı değil. Varsayılan olarak forekste PAPER'e düşmeyiz:
                    # forex kısmı MT5 köprüsü üzerinden demo hesabı yönetir (kullanıcı
                    # kararı 2026-10-07). Kilit olmadan, köprü geçici düştüğünde motor
                    # sessizce paper pozisyon açıyor; sonra o kayıt `mt5_ticket`
                    # taşımadığı için (aşağıda) aynı semboldeki GERÇEK MT5
                    # pozisyonlarını kapatabiliyordu (#7). Panelden kapatılabilir.
                    if _AUTO_SETTINGS.require_mt5_connection:
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_mt5off", 0) > 60.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_mt5off"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}] MT5 köprüsü bağlı değil — yeni işlem açılmadı "
                                f"(paper'a sessiz kayma engellendi).",
                                symbol=sym,
                            )
                        continue
                    # MT5 bağlı değilse Paper Engine sanal pozisyon havuzuna ekle
                    sl_dist = sl_pips * spec["pip_size"]
                    tp_dist = tp_pips * spec["pip_size"]
                    pos_item = {
                        "id": f"FX-{int(time.time() * 1000) % 1000000}",
                        "symbol": sym,
                        "display": cand["display"],
                        "direction": direction,
                        "lots": mt5_lots,
                        "entry_price": entry_p,
                        "current_price": entry_p,
                        "sl_price": round(entry_p - sl_dist if direction == "BUY" else entry_p + sl_dist, spec["digits"]),
                        "tp_price": round(entry_p + tp_dist if direction == "BUY" else entry_p - tp_dist, spec["digits"]),
                        "initial_sl_price": round(entry_p - sl_dist if direction == "BUY" else entry_p + sl_dist, spec["digits"]),
                        "breakeven_activated": False,
                        "trailing_activated": False,
                        "partial_taken": False,
                        "partial_target_pips": first_target_pips,
                        "partial_realized_usd": 0.0,
                        "initial_lots": mt5_lots,
                        "opened_at_ts": now_ts,
                        "open_time": datetime.datetime.fromtimestamp(now_ts, TZ_UTC3).strftime("%H:%M:%S UTC+3"),
                        "pnl_usd": 0.0,
                        "pnl_pips": 0.0,
                        "pip_size": spec["pip_size"],
                        "digits": spec["digits"],
                        "score": cand["score"],
                        "strategy": "M1_M5_RADAR_SCALPER",
                    }
                    async with _AUTO_PAPER_LOCK:
                        _AUTO_STATE["open_positions"].append(pos_item)

                _LAST_SYMBOL_ENTRY_TIME[sym] = now_ts

                actual_risk_usd = round(mt5_lots * sl_pips * pip_val, 2)
                _log_auto_decision(
                    "ENTRY",
                    f"⚡ [İŞLEM AÇILDI]: {mt5_lots} Lot {direction} {sym} @ {entry_p} | TP: +{tp_pips}p | SL: -{sl_pips}p | Risk: ${actual_risk_usd:.2f} (Skor: {cand['score']:.0f})",
                    symbol=sym,
                    metadata={"lots": mt5_lots, "direction": direction, "score": cand["score"], "risk_usd": actual_risk_usd},
                )

                # Döngü başına en fazla 1 işlem aç (ani yığılmayı önle)
                break

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Forex otonom döngü hatası: %s", exc)
            # Çökmeyi panel karar akışına da taşı — sunucu konsolu tek başına
            # sessiz arıza gizler (2026-10-06 XAU sessiz giriş sorunu dersi).
            err_ts = time.time()
            if err_ts - last_loop_error_log_ts > 60.0:
                last_loop_error_log_ts = err_ts
                _log_auto_decision(
                    "SYSTEM",
                    f"⚠️ Tarama döngüsünde beklenmeyen hata: {exc} — 3 sn içinde yeniden deneniyor.",
                )
            await asyncio.sleep(3.0)

    _AUTO_STATE["last_status"] = "Durduruldu"
    logger.info("Forex Otonom Scalper Döngüsü Durduruldu.")


@router.get("/auto-paper/status")
async def get_forex_auto_paper_status():
    """IC Markets MT5 Otonom Scalper sistem durumu, canlı MT5 pozisyonları ve hesap metrikleri."""
    is_mt5_conn = _MT5_STATE.get("connected", False)
    mt5_acc = _MT5_STATE.get("account", {})

    if is_mt5_conn:
        balance = float(mt5_acc.get("balance", 1000.0))
        active_positions_source = _MT5_STATE.get("open_positions", [])
        closed_deals_source = _MT5_STATE.get("closed_deals", [])
    else:
        balance = float(_AUTO_STATE.get("balance", 10000.0))
        active_positions_source = _AUTO_STATE.get("open_positions", [])
        closed_deals_source = _AUTO_STATE.get("closed_trades", [])

    # Pozisyonları ve Kapanan İşlemleri Güvenli Formatla Normalize Et
    normalized_positions = []
    for p in active_positions_source:
        pnl = float(p.get("pnl_usd", p.get("profit", 0.0)))
        normalized_positions.append({
            **p,
            "pnl_usd": round(pnl, 2),
            "pnl_pips": float(p.get("pnl_pips", 0.0)),
        })

    normalized_deals = []
    # #2: status sayıları da pozisyon bazlı olsun (rapor/CSV ile aynı payda) —
    # kısmi kapanış satırları birleştirilir.
    for d in _merge_partial_close_rows(list(closed_deals_source)):
        # #1: net sonuç = profit + commission + swap (MT5 bakiyesiyle uzlaşır).
        pnl = _deal_net_pnl_usd(d)
        t_id = d.get("ticket") or d.get("id") or 0
        normalized_deals.append({
            "id": d.get("id") or f"MT5-{t_id}",
            "ticket": t_id,
            "symbol": d.get("symbol", ""),
            "display": d.get("display", d.get("symbol", "")),
            "direction": d.get("direction", "BUY"),
            "lots": float(d.get("lots", 0.01)),
            "entry_price": d.get("price", d.get("entry_price", 0.0)),
            "exit_price": d.get("price", d.get("exit_price", 0.0)),
            "open_time": d.get("open_time", d.get("time", "")),
            "exit_time": d.get("exit_time", d.get("time", "")),
            "exit_reason": d.get("exit_reason", "MT5 Kapanış"),
            "exit_reason_title": d.get("exit_reason_title", "IC Markets MT5"),
            "pnl_usd": pnl,
            "pnl_pips": float(d.get("pnl_pips", 0.0)),
            "outcome": "WIN" if pnl >= 0 else "LOSS",
        })

    open_pnl_usd = round(sum(p["pnl_usd"] for p in normalized_positions), 2)
    equity = float(mt5_acc.get("equity", round(balance + open_pnl_usd, 2))) if is_mt5_conn else round(balance + open_pnl_usd, 2)

    # Realized PnL ve Kazanma Oranı
    # Sınıflama tüm uçlarda AYNI: kapanış kaydı (:2255), paper sayaçları (:2262),
    # rapor (:3559) ve CSV (:3700) "pnl >= 0 → WIN" der. Burada eskiden kesin
    # `> 0` / `< 0` vardı; tam 0.00'a yuvarlanan bir başabaş çıkışı raporda WIN,
    # status'ta ne win ne loss sayılıyor ve `wins + losses != total_trades`
    # oluyordu. Tek kural: WIN = pnl >= 0, LOSS = pnl < 0.
    # Temiz-sayfa kesimi: resetten önce kapanan işlemler status KPI'larına girmez.
    if _LEDGER_RESET_AT_TS:
        normalized_deals = [d for d in normalized_deals if (_deal_ts(d) or 0.0) >= _LEDGER_RESET_AT_TS]
    wins = sum(1 for d in normalized_deals if d["pnl_usd"] >= 0)
    losses = sum(1 for d in normalized_deals if d["pnl_usd"] < 0)
    total_trades = len(normalized_deals)
    realized_usd = round(sum(d["pnl_usd"] for d in normalized_deals), 2) if is_mt5_conn else _AUTO_STATE["realized_pnl_usd"]
    win_rate = round((wins / total_trades * 100.0), 1) if total_trades > 0 else 0.0

    # Pip KPI'ları (eskiden sabit 0.0 dönüyordu, oysa pnl_pips her kayıtta mevcut).
    # Pip ölçeği SEMBOL BAŞINA farklıdır (EURUSD 0.0001, XAUUSD 0.1, endeks 1 puan,
    # BTC 1 USD); bu yüzden çok sembollü bir defterin pip toplamı farklı birimleri
    # toplar. Toplam yine verilir ama `pnl_pips_mixed_scale` bayrağıyla birlikte
    # döner; panel bu durumda "≈" ile işaretler.
    realized_pips = round(sum(float(d.get("pnl_pips", 0.0)) for d in normalized_deals), 1)
    open_pips = round(sum(float(p.get("pnl_pips", 0.0)) for p in normalized_positions), 1)
    all_pip_symbols = {str(d.get("symbol", "")).upper() for d in normalized_deals} | {
        str(p.get("symbol", "")).upper() for p in normalized_positions
    }
    pnl_pips_mixed_scale = len({s for s in all_pip_symbols if s}) > 1

    return {
        "status": _AUTO_STATE["last_status"],
        "enabled": _AUTO_STATE["enabled"],
        "balance": balance,
        "equity": equity,
        "open_pnl_usd": open_pnl_usd,
        "open_pnl_pips": open_pips,
        "realized_pnl_usd": realized_usd,
        "realized_pnl_pips": realized_pips,
        "pnl_pips_mixed_scale": pnl_pips_mixed_scale,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "settings": _AUTO_SETTINGS.model_dump(),
        "open_positions": normalized_positions,
        "closed_trades": normalized_deals,
        "decision_logs": _AUTO_STATE["decision_logs"][:60],
        "sessions": _get_market_sessions(),
        "dxy": get_dxy_regime(),
        "correlations": _FX_CORR.snapshot(),
        "correlations_updated_at": _FX_CORR.last_updated,
        "symbol_ev": {
            s: _collect_symbol_ev(s, time.time(), _AUTO_SETTINGS.ev_window_hours * 3600.0)
            for s in _AUTO_SETTINGS.allowed_symbols
        },
        "last_scan_time": _AUTO_STATE["last_scan_time"],
        "mt5_account": mt5_acc,
        "mt5_connected": is_mt5_conn,
    }


@router.post("/auto-paper/toggle")
async def toggle_forex_auto_paper(req: ToggleAutoPaperRequest):
    """Otonom scalper'ı başlatır veya durdurur."""
    global _AUTO_PAPER_TASK, _LAST_GOLD_EXIT_TIME, _LAST_BTC_EXIT_TIME
    _AUTO_STATE["enabled"] = req.enabled
    _AUTO_SETTINGS.enabled = req.enabled
    _MT5_STATE["auto_trade"] = req.enabled

    if req.enabled:
        # Kapsam boşsa KALİBRE ODAK setine düş (2026-10-07): tüm FX evrenini otomatik
        # açmak, 30g replay'de 28/28 negatif çıkan çiftleri motor başlangıcında sessizce
        # devreye alırdı. Kapsam genişletmesi bilinçli panel seçimi gerektirir.
        if not _AUTO_SETTINGS.allowed_symbols:
            _AUTO_SETTINGS.allowed_symbols = ["XAUUSD", "BTCUSD", "GBPJPY", "EURJPY"]
        # İlk start verildiğinde soğuma kalkanını dikkate almaması için sıfırla
        _LAST_GOLD_EXIT_TIME = 0.0
        _LAST_BTC_EXIT_TIME = 0.0
        _LAST_SYMBOL_ENTRY_TIME.clear()
        if _AUTO_PAPER_TASK is None or _AUTO_PAPER_TASK.done():
            _AUTO_PAPER_TASK = asyncio.create_task(_forex_auto_paper_loop())
            _log_auto_decision("SYSTEM", "IC Markets MT5 Otonom Scalper kullanıcı tarafından ETKİNLEŞTİRİLDİ (Soğuma kalkanı temizlendi, hazır).")
    else:
        if _AUTO_PAPER_TASK and not _AUTO_PAPER_TASK.done():
            _AUTO_PAPER_TASK.cancel()
            _AUTO_PAPER_TASK = None
        _AUTO_STATE["last_status"] = "Durduruldu"
        _log_auto_decision("SYSTEM", "IC Markets MT5 Otonom Scalper kullanıcı tarafından DURDURULDU.")

    return {
        "enabled": _AUTO_STATE["enabled"],
        "status": _AUTO_STATE["last_status"],
        "message": "Otonom Forex Scalper durumu güncellendi.",
    }


@router.post("/auto-paper/settings")
async def update_forex_auto_paper_settings(new_settings: ForexAutoPaperSettings):
    """Otonom scalper risk ve filtre parametrelerini günceller."""
    global _AUTO_SETTINGS
    # Çalışma durumunu koru (motorun durdurulup başlatılması toggle endpoint'iyle yönetilir)
    new_settings.enabled = _AUTO_STATE["enabled"]
    _AUTO_SETTINGS = new_settings

    _log_auto_decision(
        "SYSTEM",
        f"Parametreler güncellendi: Risk: %{new_settings.risk_per_trade_pct}, SL: {new_settings.sl_pips}p, TP: {new_settings.tp_pips}p, BE: {new_settings.breakeven_pips}p, Trailing: {new_settings.trailing_stop_pips}p, Min Skor: {new_settings.min_score}",
    )
    return {"status": "ok", "settings": _AUTO_SETTINGS.model_dump()}


def _parse_reset_cutoff(value: str, now_ts: float) -> float:
    """Kesim zamanı metnini epoch'a çevirir (saf fonksiyon — test edilebilir).

    Kabul edilen biçimler (hepsi UTC+3 yerel saat varsayılır): epoch saniye,
    "YYYY-MM-DD", "YYYY-MM-DD HH:MM", "YYYY-MM-DD HH:MM:SS" ve ISO "T" ayraçlı
    varyantları. Geleceğe ait kesim reddedilir (ValueError).
    """
    v = str(value).strip()
    if not v:
        raise ValueError("Kesim zamanı boş olamaz.")
    if v.replace(".", "", 1).isdigit():
        ts = float(v)
    else:
        ts = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                ts = datetime.datetime.strptime(v, fmt).replace(tzinfo=TZ_UTC3).timestamp()
                break
            except ValueError:
                continue
        if ts is None:
            raise ValueError(f"Kesim zamanı anlaşılamadı: {value!r} (ör. '2026-10-07 07:10').")
    if ts > now_ts + 60.0:
        raise ValueError("Kesim zamanı gelecekte olamaz.")
    return ts


@router.post("/auto-paper/reset-symbol-guards")
async def reset_forex_symbol_guards(cutoff: Optional[str] = None):
    """Temiz sayfa: sembol kalkanlarını sıfırlar + eski işlemleri arşive alır.

    Kullanıcı senaryosu (2026-10-07): kural seti değişti (chandelier + seri-SL +
    yeni ayarlar); eski dönemde biriken (1) kayıp sicili EV kalkanının sembolleri
    eski performansıyla cezalandırmaması, (2) işlem geçmişi de rapor/KPI/CSV'de
    sıfırdan sayılmaya başlaması için arşive alınmalı — her sembol temiz sayfayla
    başlar. EV kalkanı kalıcı bir sayaç değil, kapanmış işlemlerden her taramada
    yeniden hesaplanır (köprü bağlıyken MT5 son-300-deal kaynağı) — bu yüzden
    restart yetmez; kesim zamanı işaretleriyle resetten önceki işlemler hem EV
    penceresine hem rapor/KPI/CSV'ye hiç alınmaz. Bakiyeye DOKUNULMAZ.

    `cutoff` (opsiyonel, UTC+3): "şimdi" yerine verilen saatten önce kapananlar
    arşive kalkar, sonraki işlemler raporda kalır (örn. deploy sonrası biriken
    yeni-dönem işlemlerini korumak için: ?cutoff=2026-10-07 07:10). Verilmezse
    tam temiz sayfa (tümü arşive). Seri-SL sayaçları yalnız tam temiz sayfada
    sıfırlanır — kesimli resette kısa vadeli canlı sayaca dokunulmaz.
    """
    global _EV_RESET_AT_TS, _LEDGER_RESET_AT_TS
    now_ts = time.time()
    full_reset = cutoff is None or not str(cutoff).strip()
    if full_reset:
        reset_ts = now_ts
    else:
        try:
            reset_ts = _parse_reset_cutoff(cutoff, now_ts)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    before = {
        s: _collect_symbol_ev(s, now_ts, _AUTO_SETTINGS.ev_window_hours * 3600.0)
        for s in _AUTO_SETTINGS.allowed_symbols
    }

    # --- Arşiv: mevcut rapor görünümünden kesim öncesini ayır
    # (MT5 deal'leri varsa onlar, yoksa paper defteri)
    merged_view = _merge_partial_close_rows(list(_MT5_STATE.get("closed_deals", []))) or list(
        _AUTO_STATE.get("closed_trades", [])
    )
    archived_view = [t for t in merged_view if (_deal_ts(t) or 0.0) < reset_ts]
    counters_before = {
        "total_trades": _AUTO_STATE.get("total_trades", 0),
        "wins": _AUTO_STATE.get("wins", 0),
        "losses": _AUTO_STATE.get("losses", 0),
        "realized_pnl_usd": _AUTO_STATE.get("realized_pnl_usd", 0.0),
    }
    archive_meta: Dict[str, Any] = {"count": len(archived_view), "path": None}
    if archived_view:
        try:
            stamp = datetime.datetime.fromtimestamp(now_ts, TZ_UTC3).strftime("%Y%m%d_%H%M%S")
            archive_path = os.path.join(
                _ledger_archive_dir(), f"forex_ledger_arşiv_{stamp}.json"
            )
            with open(archive_path, "w", encoding="utf-8") as f:
                json.dump({
                    "archived_at": datetime.datetime.fromtimestamp(now_ts, TZ_UTC3).isoformat(),
                    "cutoff": datetime.datetime.fromtimestamp(reset_ts, TZ_UTC3).strftime("%Y-%m-%d %H:%M:%S UTC+3"),
                    "reason": "Kural seti yenilendi (chandelier + seri-SL + yeni ayarlar) — kesim öncesi sicil arşive alındı.",
                    "counters_before": counters_before,
                    "trades": archived_view,
                }, f, ensure_ascii=False)
            archive_meta["path"] = archive_path
        except Exception as exc:
            _log_auto_decision("SYSTEM", f"⚠️ İşlem arşivi dosyaya yazılamadı (bellek kopyası yine de tutuluyor): {exc}")

    # --- Kesim + sayaç durumları
    _EV_RESET_AT_TS = reset_ts
    _LEDGER_RESET_AT_TS = reset_ts
    if full_reset:
        _SYMBOL_LOSS_STREAK.clear()
        _SYMBOL_LOSS_COOLDOWN_UNTIL.clear()
    # Paper defteri: kesim sonrası kapananlar kalır, sayaçlar onlardan yeniden hesaplanır
    kept_paper = [t for t in _AUTO_STATE.get("closed_trades", []) if (_deal_ts(t) or 0.0) >= reset_ts]
    _AUTO_STATE["closed_trades"] = kept_paper
    _AUTO_STATE["total_trades"] = len(kept_paper)
    _AUTO_STATE["wins"] = sum(1 for t in kept_paper if float(t.get("pnl_usd", 0.0) or 0.0) >= 0)
    _AUTO_STATE["losses"] = len(kept_paper) - _AUTO_STATE["wins"]
    _AUTO_STATE["realized_pnl_usd"] = round(sum(float(t.get("pnl_usd", 0.0) or 0.0) for t in kept_paper), 2)
    _AUTO_STATE["realized_pnl_pips"] = round(sum(float(t.get("pnl_pips", 0.0) or 0.0) for t in kept_paper), 1)
    _AUTO_STATE["archived_trades"] = archived_view
    _AUTO_STATE["archived_at"] = now_ts
    _AUTO_STATE["archived_path"] = archive_meta["path"]

    cut_human = datetime.datetime.fromtimestamp(reset_ts, TZ_UTC3).strftime("%Y-%m-%d %H:%M:%S UTC+3")
    _log_auto_decision(
        "SYSTEM",
        (f"🧹 Temiz sayfa: {archive_meta['count']} eski işlem arşive alındı — EV kalkanı + seri-SL sayaçları sıfırlandı, rapor/KPI'lar sıfırdan saymaya başladı (bakiye korunur)."
         if full_reset else
         f"🧹 Kesimli arşiv: {cut_human} öncesindeki {archive_meta['count']} işlem arşive alındı — sonraki işlemler raporda kaldı; EV kalkanı da bu kesimden değerlendirir (bakiye ve seri-SL sayaçları korunur)."),
    )
    return {
        "status": "ok",
        "reset_at": datetime.datetime.fromtimestamp(now_ts, TZ_UTC3).strftime("%Y-%m-%d %H:%M:%S UTC+3"),
        "cutoff": None if full_reset else cut_human,
        "ev_before_reset": before,
        "archived_count": archive_meta["count"],
        "kept_paper_count": len(kept_paper),
        "archive_path": archive_meta["path"],
        "counters_before": counters_before,
        "note": ("EV kalkanı ve rapor/KPI'lar artık yalnız kesim sonrası kapanan işlemlerle hesaplanır; "
                 + ("seri-SL sayaçları sıfırlandı; " if full_reset else "seri-SL sayaçlarına dokunulmadı; ")
                 + "eski işlemler arşivde (bellek + JSON dosyası). Bakiye değişmedi."),
    }


@router.get("/auto-paper/archived-ledger")
async def get_forex_archived_ledger(limit: int = 500):
    """Arşive alınmış eski işlem defterini döner (temiz-sayfa resetinden önceki kayıtlar)."""
    archived = list(_AUTO_STATE.get("archived_trades", []))
    return {
        "archived_at": _AUTO_STATE.get("archived_at"),
        "archived_path": _AUTO_STATE.get("archived_path"),
        "count": len(archived),
        "trades": archived[: max(1, min(int(limit), 1000))],
    }


@router.post("/auto-paper/close-position")
async def close_forex_position_manually(req: ClosePositionRequest):
    """Belirli bir açık pozisyonu veya MT5 biletini kapatır."""
    ticket = None
    try:
        raw = req.id.replace("#", "").replace("FX-", "").replace("CMD-CLOSE-", "").strip()
        if raw.isdigit():
            ticket = int(raw)
    except Exception:
        pass

    if ticket:
        cmd_id = f"CMD-CLOSE-{ticket}"
        _MT5_STATE["pending_commands"].append({
            "id": cmd_id,
            "action": "CLOSE_ORDER",
            "ticket": ticket,
        })
        _log_auto_decision("EXIT", f"🛑 [IC Markets MT5] Bilet #{ticket} kapatma emri iletildi.")
        return {"status": "closed", "ticket": ticket}

    res = await _close_position_internal(req.id, "MANUAL")
    if not res:
        raise HTTPException(status_code=404, detail="Pozisyon bulunamadı veya zaten kapalı.")
    return {"status": "closed", "position": res}


@router.post("/auto-paper/reset")
async def reset_forex_auto_paper():
    """IC Markets MT5 Scalper günlüklerini sıfırlar."""
    async with _AUTO_PAPER_LOCK:
        _AUTO_STATE["decision_logs"] = []
        _AUTO_STATE["closed_trades"] = []
        _AUTO_STATE["realized_pnl_usd"] = 0.0
        _AUTO_STATE["realized_pnl_pips"] = 0.0
        _AUTO_STATE["wins"] = 0
        _AUTO_STATE["losses"] = 0
        _AUTO_STATE["total_trades"] = 0
        _AUTO_STATE["balance"] = 10000.0

    _log_auto_decision("SYSTEM", "IC Markets MT5 Scalper günlükleri ve karar akışı sıfırlandı.")
    bal = float(_MT5_STATE.get("account", {}).get("balance", 1000.0)) if _MT5_STATE.get("connected") else float(_AUTO_STATE["balance"])
    return {"status": "reset", "balance": bal}


# Rapor sayfasının dönem ön ayarları. "all" sınırsızdır; "custom" iki tarih ister.
_FOREX_REPORT_PERIODS = ("all", "today", "yesterday", "last12h", "this_week", "this_month", "custom")

# Zarar yokken kâr faktörü matematiksel olarak sonsuzdur. JSON `Infinity`
# taşıyamadığı için tek bir nöbetçi sabit kullanılır; panel `>= _PF_INFINITE`
# görünce "∞" yazar (reports/page.tsx). Sabiti tek yerde tutmak, eşiğin
# backend ve panel arasında ayrışmasını engeller.
_PF_INFINITE = 999.0


def _deal_net_pnl_usd(deal: Dict[str, Any]) -> float:
    """Bir kapanış kaydının NET USD sonucu = profit + komisyon + swap (#1).

    MT5 hesabının bakiyesi tam olarak bu üçünün toplamı kadar hareket eder;
    köprü `commission`/`swap`'i ayrı alanlara yazar (mt5_bridge.py:998-999) ama
    backend bunları hiç okumuyordu → paneldeki "realize kâr" MT5 bakiyesinden
    sistematik iyimser kalıyordu (deal başına komisyon işlem sayısıyla birikir).

    Paper kayıtlarında `commission`/`swap` alanı yoktur (0.0) ve `pnl_usd` zaten
    net olduğundan sonuç değişmez. Grafik/kapanış öncesi kayıtlar da güvenli.
    """
    profit = float(deal.get("profit", deal.get("pnl_usd", 0.0)) or 0.0)
    commission = float(deal.get("commission", 0.0) or 0.0)
    swap = float(deal.get("swap", 0.0) or 0.0)
    return round(profit + commission + swap, 2)


def _merge_partial_close_rows(deals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aynı pozisyona ait kısmi kapanış satırlarını TEK işleme birleştirir (#2).

    MT5'te kısmi kâr almayı köprü kendisi yapar (`execute_close_partial`) ve her
    bacak ayrı bir DEAL_ENTRY_OUT üretir; köprü her OUT deal için `id="MT5-{pos_id}"`
    taşıyan bir satır basar. Yani tek fiziksel pozisyon rapora 2+ satır olarak
    düşüyordu → `total_trades`/`win_rate` paydası ve `avg_*` şişiyordu.

    Birleştirme: `id` (veya `ticket`) bazında; miktarlar toplanır (`lots`,
    `profit`/`pnl_usd`, `commission`, `swap`), zaman/en son çıkış korunur. Sıra
    ilk görülme sırasıdır. Tek satırlık pozisyonlar aynen geçer.
    """
    merged: Dict[Any, Dict[str, Any]] = {}
    order: List[Any] = []
    passthrough: List[Dict[str, Any]] = []
    for d in deals or []:
        key = d.get("id") or d.get("ticket")
        if key is None:
            passthrough.append(d)
            continue
        if key not in merged:
            merged[key] = dict(d)
            order.append(key)
            continue
        base = merged[key]
        for field in ("lots", "profit", "pnl_usd", "commission", "swap"):
            if field in base or field in d:
                base[field] = round(float(base.get(field, 0.0) or 0.0) + float(d.get(field, 0.0) or 0.0), 2)
        # Kapanış zamanı: en son (en yeni) bacak.
        new_t = _deal_ts(d) or 0.0
        old_t = _deal_ts(base) or 0.0
        if new_t >= old_t:
            for field in ("exit_time", "exit_time_iso", "closed_at_ts", "exit_price", "exit_reason", "exit_reason_title"):
                if field in d:
                    base[field] = d[field]
        # Sınıflama toplam net sonuca göre yeniden yazılır.
        base["outcome"] = "WIN" if _deal_net_pnl_usd(base) >= 0 else "LOSS"
    return [merged[k] for k in order] + passthrough

# MT5 köprüsü en fazla son 300 kapanan anlaşmayı gönderir (mt5_bridge.py:
# `for d in reversed(out_deals[-300:])`). Bu yüzden raporun `period="all"`
# seçeneği gerçek "tüm geçmiş" DEĞİL, köprünün dönen penceresidir. Liste tam
# 300'e ulaştıysa pencere doymuş demektir; panel bunu kullanıcıya bildirir ki
# kartlar MT5 bakiyesiyle uzlaşmadığında sebebi görünür olsun.
_MT5_DEAL_WINDOW = 300


def _parse_deal_ts(value: Any) -> Optional[float]:
    """Kapanmış bir işlemin zaman damgasını epoch saniyeye çevirir.

    Kaynaklar karışık biçim gönderir ve üçü de gerçek veridir:
      - `closed_at_ts`       → epoch saniye/ms (paper defteri)
      - `exit_time_iso`      → "2026-10-06T14:33:12+03:00" (paper defteri)
      - `exit_time`          → "2026-10-06 14:33:12 UTC+3" (MT5 köprüsü)
    Eski `_collect_symbol_ev` yalnız ikinci biçimi okuyor ve "UTC+3" damgasını
    UTC sanıyordu (3 saatlik kayma). Burada damga adı okunur; damgasız değer
    UTC kabul edilir. Çözülemeyen değer `None` döner — çağıran onu penceresi
    belli bir dönemde DIŞARIDA bırakır (uydurma zaman üretmek yerine).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        num = float(value)
        if num <= 0:
            return None
        return num / 1000.0 if num > 10_000_000_000 else num
    text = str(value).strip()
    if not text or text == "-":
        return None
    try:
        if text.endswith("UTC+3"):
            dt = datetime.datetime.strptime(text[:-5].strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ_UTC3)
            return dt.timestamp()
        if text.endswith("UTC"):
            dt = datetime.datetime.strptime(text[:-3].strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
            return dt.timestamp()
        dt = datetime.datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _deal_ts(deal: Dict[str, Any]) -> Optional[float]:
    """İşlem kaydının kapanış zamanı: `closed_at_ts` → `exit_time_iso` → `exit_time`."""
    ts = _parse_deal_ts(deal.get("closed_at_ts"))
    if ts is not None:
        return ts
    return _parse_deal_ts(deal.get("exit_time_iso") or deal.get("exit_time"))


def _resolve_report_window(
    period: str,
    date_from: Optional[str],
    date_to: Optional[str],
    now_ts: float,
) -> Tuple[Optional[float], Optional[float]]:
    """Dönem adını (başlangıç, bitiş) epoch penceresine çevirir; sınırsız uç `None`.

    Tüm sınırlar UTC+3 (Türkiye) gününe göredir — raporda gösterilen saatlerle
    aynı takvim. `this_week` haftanın ilk günü PAZARTESİ kabul eder (TR kuralı).
    """
    if period not in _FOREX_REPORT_PERIODS:
        period = "all"
    now3 = datetime.datetime.fromtimestamp(now_ts, TZ_UTC3)
    midnight = now3.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == "all":
        return None, None
    if period == "today":
        return midnight.timestamp(), None
    if period == "yesterday":
        return (midnight - datetime.timedelta(days=1)).timestamp(), midnight.timestamp()
    if period == "last12h":
        return now_ts - 12 * 3600, None
    if period == "this_week":
        return (midnight - datetime.timedelta(days=midnight.weekday())).timestamp(), None
    if period == "this_month":
        return midnight.replace(day=1).timestamp(), None

    # custom: verilen tarihler UTC+3 gün sınırlarına genişletilir (bitiş DAHİL).
    start_ts = None
    end_ts = None
    if date_from:
        try:
            d = datetime.datetime.strptime(str(date_from).strip()[:10], "%Y-%m-%d").replace(tzinfo=TZ_UTC3)
            start_ts = d.timestamp()
        except Exception:
            start_ts = None
    if date_to:
        try:
            d = datetime.datetime.strptime(str(date_to).strip()[:10], "%Y-%m-%d").replace(tzinfo=TZ_UTC3)
            end_ts = d.timestamp() + 86400.0 - 0.001
        except Exception:
            end_ts = None
    return start_ts, end_ts


def _deal_in_window(ts: Optional[float], start_ts: Optional[float], end_ts: Optional[float]) -> bool:
    """Pencere içi testi. Zamanı çözülemeyen işlem sınırlı pencerede DIŞARIDA kalır."""
    if start_ts is None and end_ts is None:
        return True
    if ts is None:
        return False
    if start_ts is not None and ts < start_ts:
        return False
    if end_ts is not None and ts > end_ts:
        return False
    return True


@router.get("/auto-paper/trades")
async def get_forex_trades_report(
    symbol: Optional[str] = None,
    outcome: Optional[str] = None,
    reason: Optional[str] = None,
    search: Optional[str] = None,
    period: str = "all",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 500,
):
    """Forex Otonom Scalper ayrıntılı işlem raporları, filtreleme ve performans analitiği.

    KPI kartları **sembol + dönem** kapsamına bağlıdır: panelde "EUR/USD" ve
    "Bugün" seçiliyken kazanma oranı tüm arşivin değil, o dilimin oranıdır.
    `outcome` / `reason` / `search` yalnız TABLOYU süzer; KPI'ya girmez —
    yoksa "Sadece Kaybedenler" seçildiğinde kazanma oranı tanım gereği %0
    görünür ve kart anlamsızlaşırdı. Bu ayrım yanıtta `kpi_scope` ile bildirilir.
    """
    # MT5 Deals önceliklidir; yoksa auto_state geçmişi kullanılır
    all_closed = _merge_partial_close_rows(list(_MT5_STATE.get("closed_deals", []))) or list(_AUTO_STATE.get("closed_trades", []))

    # Temiz-sayfa kesimi (arşiv+reset sonrası): rapor yalnız reset sonrası kapananları gösterir
    archived_before_reset = 0
    if _LEDGER_RESET_AT_TS:
        kept_closed = [t for t in all_closed if (_deal_ts(t) or 0.0) >= _LEDGER_RESET_AT_TS]
        archived_before_reset = len(all_closed) - len(kept_closed)
        all_closed = kept_closed

    now_ts = time.time()
    start_ts, end_ts = _resolve_report_window(period, date_from, date_to, now_ts)
    period_active = start_ts is not None or end_ts is not None

    # --- KPI kapsamı: sembol + dönem (tablo filtreleri hariç) ---
    kpi_scope = all_closed
    if symbol and symbol != "ALL":
        kpi_scope = [t for t in kpi_scope if t.get("symbol") == symbol or t.get("display") == symbol]
    if period_active:
        kpi_scope = [t for t in kpi_scope if _deal_in_window(_deal_ts(t), start_ts, end_ts)]

    filtered = kpi_scope

    if outcome and outcome != "ALL":
        outcome_upper = str(outcome).upper()
        filtered = [t for t in filtered if str(t.get("outcome", "")).upper() == outcome_upper]

    if reason and reason != "ALL":
        filtered = [t for t in filtered if reason.lower() in str(t.get("exit_reason", "")).lower() or reason.lower() in str(t.get("exit_reason_title", "")).lower()]

    if search:
        s_low = search.lower()
        filtered = [
            t for t in filtered
            if s_low in str(t.get("id", "")).lower()
            or s_low in str(t.get("ticket", "")).lower()
            or s_low in str(t.get("symbol", "")).lower()
            or s_low in str(t.get("display", "")).lower()
            or s_low in str(t.get("exit_reason", "")).lower()
        ]

    # Performans Analitiği (Sembol + Dönem kapsamı; tablo filtreleri hariç)
    total_trades = len(kpi_scope)
    wins = [t for t in kpi_scope if _deal_net_pnl_usd(t) >= 0]
    losses = [t for t in kpi_scope if _deal_net_pnl_usd(t) < 0]

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = round((win_count / total_trades * 100.0), 1) if total_trades > 0 else 0.0

    gross_profit = round(sum(_deal_net_pnl_usd(t) for t in wins), 2)
    gross_loss = round(abs(sum(_deal_net_pnl_usd(t) for t in losses)), 2)

    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 2)
    elif gross_profit > 0:
        # Zarar hiç yokken PF matematiksel olarak sonsuzdur; JSON `Infinity`
        # yazamadığı için nöbetçi değer kullanılır. Panel bu değeri "∞" olarak
        # gösterir (reports/page.tsx: `profit_factor >= _PF_INFINITE ? "∞"`),
        # yani 999 gerçek bir faktör gibi görünmez. Sabit tek yerde tanımlı ki
        # eşik iki tarafta ayrışmasın (`_is_infinite_pf` ile aynı değer).
        profit_factor = _PF_INFINITE
    else:
        profit_factor = 0.0

    total_pnl_usd = round(sum(_deal_net_pnl_usd(t) for t in kpi_scope), 2)
    total_pnl_pips = round(sum(float(t.get("pnl_pips", 0.0)) for t in kpi_scope), 1)
    # Pip ölçeği sembol başına farklı (forex 0.0001 / altın 0.1 / endeks puanı /
    # BTC 1 USD). Birden çok sembol kapsanıyorsa toplam birimi karışıktır; panel
    # bunu "≈" ile işaretler, sayıyı gizlemez.
    pnl_pips_mixed_scale = len({str(t.get("symbol", "")).upper() for t in kpi_scope if t.get("symbol")}) > 1
    total_lots = round(sum(float(t.get("lots", 0.0)) for t in kpi_scope), 2)

    avg_trade_usd = round(total_pnl_usd / total_trades, 2) if total_trades > 0 else 0.0
    avg_win_usd = round(gross_profit / win_count, 2) if win_count > 0 else 0.0
    avg_loss_usd = round(gross_loss / loss_count, 2) if loss_count > 0 else 0.0

    max_win_usd = max([_deal_net_pnl_usd(t) for t in wins], default=0.0)
    max_loss_usd = min([_deal_net_pnl_usd(t) for t in losses], default=0.0)

    # Açık Pozisyonlar (MT5 veya Auto) — sembol filtresi burada da geçerlidir,
    # yoksa "EUR/USD" seçiliyken altın pozisyonunun yüzen K/Z'si karta sızardı.
    open_positions = list(_MT5_STATE.get("open_positions", [])) or list(_AUTO_STATE.get("open_positions", []))
    if symbol and symbol != "ALL":
        open_positions = [
            p for p in open_positions
            if p.get("symbol") == symbol or p.get("display") == symbol
        ]
    open_pnl_usd = round(sum(float(p.get("pnl_usd", p.get("profit", 0.0))) for p in open_positions), 2)
    acc_bal = float(_MT5_STATE.get("account", {}).get("balance", _AUTO_STATE["balance"]))
    acc_eq = float(_MT5_STATE.get("account", {}).get("equity", round(acc_bal + open_pnl_usd, 2)))

    return {
        "kpi": {
            "total_trades": total_trades,
            "wins": win_count,
            "losses": loss_count,
            "win_rate": win_rate,
            "total_pnl_usd": total_pnl_usd,
            "total_pnl_pips": total_pnl_pips,
            "pnl_pips_mixed_scale": pnl_pips_mixed_scale,
            "gross_profit_usd": gross_profit,
            "gross_loss_usd": gross_loss,
            "profit_factor_infinite": profit_factor >= _PF_INFINITE,
            "profit_factor": profit_factor,
            "avg_trade_usd": avg_trade_usd,
            "avg_win_usd": avg_win_usd,
            "avg_loss_usd": avg_loss_usd,
            "max_win_usd": max_win_usd,
            "max_loss_usd": max_loss_usd,
            "total_lots": total_lots,
            "balance": acc_bal,
            "equity": acc_eq,
            "open_positions_count": len(open_positions),
            "open_pnl_usd": open_pnl_usd,
        },
        # KPI'nın neyi kapsadığını arayüz söyler: kartların altındaki
        # "Sembol: X · Dönem: Y" satırı buradan beslenir, böylece kullanıcı
        # kazananların filtresinin KPI'ya girmediğini görsel olarak da görür.
        "kpi_scope": {
            "symbol": symbol or "ALL",
            "period": period if period in _FOREX_REPORT_PERIODS else "all",
            "date_from": date_from,
            "date_to": date_to,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "archived_total": len(all_closed),
            # Temiz-sayfa kesimi: arşiv kararı sonrası raporların sıfırdan başladığı an
            "ledger_reset_at": _LEDGER_RESET_AT_TS or None,
            "archived_before_reset": archived_before_reset,
            # `period="all"` MT5'te köprünün son 300 anlaşmalık dönen penceresidir
            # (bkz. _MT5_DEAL_WINDOW). "tüm geçmiş" ile karıştırılmasın diye
            # pencerenin doyup dolmadığı açıkça bildirilir.
            "mt5_deal_window": _MT5_DEAL_WINDOW if _MT5_STATE.get("closed_deals") else None,
            "mt5_deal_window_full": bool(_MT5_STATE.get("closed_deals")) and len(_MT5_STATE.get("closed_deals", [])) >= _MT5_DEAL_WINDOW,
        },
        "trades": filtered[:limit],
        "total_filtered": len(filtered),
        "open_positions": open_positions,
    }


@router.get("/auto-paper/export-csv")
async def export_forex_trades_csv(
    symbol: Optional[str] = None,
    outcome: Optional[str] = None,
):
    """Forex scalper işlem geçmişini Excel uyumlu UTF-8 CSV olarak dışa aktarır."""
    # #2: kısmi kapanış satırları pozisyon bazında birleştirilir (rapordaki ile aynı).
    trades = _merge_partial_close_rows(list(_MT5_STATE.get("closed_deals", []))) or list(_AUTO_STATE.get("closed_trades", []))
    # Temiz-sayfa kesimi: resetten önce kapananlar CSV'ye de girmez (raporla aynı payda)
    if _LEDGER_RESET_AT_TS:
        trades = [t for t in trades if (_deal_ts(t) or 0.0) >= _LEDGER_RESET_AT_TS]
    if symbol and symbol != "ALL":
        trades = [t for t in trades if t.get("symbol") == symbol or t.get("display") == symbol]
    if outcome and outcome != "ALL":
        trades = [t for t in trades if str(t.get("outcome", "")).upper() == str(outcome).upper()]

    output = io.StringIO()
    # UTF-8 BOM yaz (Excel'in Türkçe karakterleri düzgün açması için)
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')

    # Başlık Satırı
    writer.writerow([
        "Bilet No",
        "Parite",
        "Sembol",
        "İşlem Yönü",
        "Lot",
        "Radar Skoru",
        "Giriş Fiyatı",
        "Açılış Zamanı (UTC)",
        "Çıkış Fiyatı",
        "Kapanış Zamanı (UTC)",
        "İşlem Süresi",
        "Çıkış Nedeni",
        "Zarar Durdur (SL)",
        "Kâr Al (TP)",
        "Kâr/Zarar (Pip)",
        "Net Getiri (USD)",
        "Bakiye Sonrası (USD)",
        "Sonuç",
    ])

    for tr in trades:
        # #1: CSV net sonucu gösterir (profit + commission + swap), panel KPI ile aynı.
        pnl = _deal_net_pnl_usd(tr)
        pips = float(tr.get("pnl_pips", 0.0))
        t_id = tr.get("id") or (f"#{tr['ticket']}" if tr.get("ticket") else "-")
        writer.writerow([
            t_id,
            tr.get("display", tr.get("symbol", "")),
            tr.get("symbol", ""),
            tr.get("direction", ""),
            tr.get("lots", 0.0),
            tr.get("score", "-"),
            tr.get("entry_price", "-"),
            tr.get("open_time", "-"),
            tr.get("exit_price", "-"),
            tr.get("exit_time", "-"),
            tr.get("duration_human", f"{tr.get('duration_sec', 0)} sn" if tr.get("duration_sec") else "-"),
            tr.get("exit_reason_title", tr.get("exit_reason", "IC Markets MT5")),
            tr.get("sl_price", "-"),
            tr.get("tp_price", "-"),
            f"{pips:+.1f}",
            f"{pnl:+.2f}",
            tr.get("balance_after", "-"),
            "KAZANÇ (WIN)" if pnl >= 0 else "KAYIP (LOSS)",
        ])

    csv_data = output.getvalue().encode("utf-8-sig")
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"forex_scalper_raporu_{now_str}.csv"

    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/csv; charset=utf-8",
        },
    )


# ============================================================================
# IC MARKETS META-TRADER 5 (MT5) BRIDGE HUB & REST API
# ============================================================================


class MT5SyncRequest(BaseModel):
    account: Dict[str, Any] = Field(default_factory=dict)
    positions: List[Dict[str, Any]] = Field(default_factory=list)
    deals: List[Dict[str, Any]] = Field(default_factory=list)
    ticks: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    # Köprünün broker'dan çektiği mumlar: { "XAUUSD|5m": [ {time,open,high,low,close}, ... ] }
    candles: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    version: str = "1.0.0"


class MT5ManualOrderRequest(BaseModel):
    symbol: str = "EURUSD"
    direction: str = "BUY"
    lots: float = Field(0.01, ge=0.01, le=10.0)
    sl_pips: Optional[float] = 15.0
    tp_pips: Optional[float] = 25.0
    comment: Optional[str] = "Scalper Manual"


class MT5CloseRequest(BaseModel):
    ticket: int


class MT5ToggleAutoRequest(BaseModel):
    auto_trade: bool


@router.post("/mt5/sync")
async def sync_mt5_bridge(req: MT5SyncRequest):
    """Windows MT5 köprüsünden gelen canlı veriyi alır ve bekleyen emirleri iletir."""
    now_ts = time.time()
    _MT5_STATE["connected"] = True
    _MT5_STATE["last_ping"] = now_ts

    if req.account:
        _MT5_STATE["account"].update(req.account)
    _MT5_STATE["open_positions"] = req.positions

    # Broker mumlarını önbelleğe al (panel grafiği bu veriyi Yahoo yerine kullanır →
    # geçmiş + canlı AYNI broker kotasyonu, baz farkı yok). Anahtar "SYMBOL|interval".
    if req.candles:
        now_c = time.time()
        for ckey, cbar_list in req.candles.items():
            key_up = str(ckey).upper().replace("/", "").replace("_", "").replace("-", "").strip()
            # Beklenen biçim "XAUUSD|5m"; köprü sembolü zaten normalize eder.
            if "|" not in key_up:
                continue
            parts = key_up.split("|", 1)
            sym_part = parts[0].replace(" ", "")
            tf_part = parts[1].strip()
            if not sym_part or not tf_part:
                continue
            clean: List[Dict[str, Any]] = []
            for b in (cbar_list or []):
                try:
                    t = int(b.get("time", 0))
                    o = float(b.get("open", 0.0)); h = float(b.get("high", 0.0))
                    l = float(b.get("low", 0.0)); c = float(b.get("close", 0.0))
                except (TypeError, ValueError):
                    continue
                if t <= 0 or not all(math.isfinite(v) for v in (o, h, l, c)) or c <= 0:
                    continue
                clean.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 0.0})
            if clean:
                clean.sort(key=lambda x: x["time"])
                _MT5_CANDLES_CACHE[f"{sym_part}|{tf_part}"] = (now_c, clean)

    # MT5 canlı tick fiyatlarını entegre et
    if req.ticks:
        for sym_code, tick_dict in req.ticks.items():
            sym_up = str(sym_code).upper()
            live_val = tick_dict.get("ask") or tick_dict.get("last") or tick_dict.get("bid")
            if live_val and live_val > 0:
                _LIVE_PRICES_CACHE[sym_up] = float(live_val)
            # Köprüden GERÇEK spread (pip) — panel varsayım yerine broker gerçekliğini kullanır
            bid_v = tick_dict.get("bid")
            ask_v = tick_dict.get("ask")
            if bid_v and ask_v and float(ask_v) > float(bid_v) > 0:
                app_sym = _MT5_TO_APP_SYMBOLS.get(sym_up, sym_up)
                pip_size = get_symbol_trading_specs(app_sym)["pip_size"]
                if pip_size > 0:
                    spread_pips = (float(ask_v) - float(bid_v)) / pip_size
                    if 0.0 < spread_pips <= 100.0:
                        _LIVE_SPREAD_PIPS[app_sym] = round(spread_pips, 2)

    if req.deals:
        _MT5_STATE["closed_deals"] = req.deals
        is_first_sync = len(_LAST_CLOSED_DEAL_IDS) == 0
        for d in req.deals:
            deal_id = d.get("ticket") or d.get("id")
            if deal_id and deal_id not in _LAST_CLOSED_DEAL_IDS:
                _LAST_CLOSED_DEAL_IDS.add(deal_id)
                d_sym = str(d.get("symbol", "")).upper()
                if "XAU" in d_sym or "GOLD" in d_sym:
                    deal_time = float(d.get("time", 0)) if isinstance(d.get("time"), (int, float)) else 0.0
                    # İlk senkronizasyonda eski geçmiş deals için false cooldown başlatma; sadece son 180s içinde kapananlar için başlat
                    if not is_first_sync or (deal_time > 0 and (now_ts - deal_time < _AUTO_SETTINGS.gold_cooldown_sec)):
                        global _LAST_GOLD_EXIT_TIME
                        _LAST_GOLD_EXIT_TIME = now_ts
                if "BTC" in d_sym:
                    deal_time = float(d.get("time", 0)) if isinstance(d.get("time"), (int, float)) else 0.0
                    if not is_first_sync or (deal_time > 0 and (now_ts - deal_time < 60.0)):
                        global _LAST_BTC_EXIT_TIME
                        _LAST_BTC_EXIT_TIME = now_ts

    # Bekleyen emirleri al ve boşalt
    commands = list(_MT5_STATE["pending_commands"])
    _MT5_STATE["pending_commands"].clear()

    return {
        "status": "ok",
        "server_time": now_ts,
        "auto_trade": _MT5_STATE["auto_trade"],
        "commands": commands,
        # Köprüye "panelde bakılan mumları broker'dan çek ve bir sonraki turda
        # `candles` olarak gönder" talimatı (bayat çiftler TTL ile düşer).
        "candle_watch": _get_forex_watch(),
        "settings": {
            "breakeven_pips": _AUTO_SETTINGS.breakeven_pips,
            "trailing_stop_pips": _AUTO_SETTINGS.trailing_stop_pips,
            "sl_pips": _AUTO_SETTINGS.sl_pips,
            "tp_pips": _AUTO_SETTINGS.tp_pips,
            "max_open_positions": _AUTO_SETTINGS.max_open_positions,
            "max_forex_lot": _AUTO_SETTINGS.max_forex_lot,
            "max_gold_lot": _AUTO_SETTINGS.max_gold_lot,
            "gold_cooldown_sec": _AUTO_SETTINGS.gold_cooldown_sec,
            "atr_exit_enabled": _AUTO_SETTINGS.atr_exit_enabled,
            "partial_tp_enabled": _AUTO_SETTINGS.partial_tp_enabled,
            "gold_be_lock_ratio": _AUTO_SETTINGS.gold_be_lock_ratio,
            "dxy_filter_enabled": _AUTO_SETTINGS.dxy_filter_enabled,
            "correlation_guard": _AUTO_SETTINGS.correlation_guard,
        },
    }


@router.get("/mt5/status")
async def get_mt5_bridge_status():
    """IC Markets MT5 köprüsü bağlantı durumunu ve canlı hesap verisini döner."""
    now_ts = time.time()
    # 10 saniye boyunca köprüden ping gelmezse çevrimdışı say
    is_alive = _MT5_STATE["connected"] and (now_ts - _MT5_STATE["last_ping"] < 10.0)
    _MT5_STATE["connected"] = is_alive

    enriched_positions = []
    for p in _MT5_STATE.get("open_positions", []):
        pos = dict(p)
        prot = pos.get("protection")
        if not prot or prot == "NORMAL":
            if pos.get("trailing_activated"):
                prot = "TRAILING"
            elif pos.get("breakeven_activated"):
                prot = "BREAKEVEN"
            else:
                dir_ = pos.get("direction", "BUY")
                entry_p = float(pos.get("entry_price", 0.0))
                sl_p = float(pos.get("sl_price", 0.0))
                if sl_p > 0 and entry_p > 0:
                    if dir_ == "BUY":
                        if sl_p > entry_p + 0.0006:
                            prot = "TRAILING"
                        elif sl_p >= entry_p - 0.0001:
                            prot = "BREAKEVEN"
                    else:
                        if sl_p < entry_p - 0.0006:
                            prot = "TRAILING"
                        elif sl_p <= entry_p + 0.0001:
                            prot = "BREAKEVEN"
        prot = prot or "NORMAL"
        pos["protection"] = prot
        pos["protection_label"] = (
            "İz Süren Stop (Trailing)" if prot == "TRAILING"
            else ("Başabaş (BE)" if prot == "BREAKEVEN" else "Sabit SL")
        )
        pos["breakeven_activated"] = prot in ("BREAKEVEN", "TRAILING")
        pos["trailing_activated"] = prot == "TRAILING"
        enriched_positions.append(pos)

    return {
        "connected": is_alive,
        "last_ping_seconds_ago": round(now_ts - _MT5_STATE["last_ping"], 1) if _MT5_STATE["last_ping"] > 0 else None,
        "auto_trade": _MT5_STATE["auto_trade"],
        "account": _MT5_STATE["account"],
        "open_positions": enriched_positions,
        "closed_deals": _MT5_STATE["closed_deals"][:50],
        "pending_commands_count": len(_MT5_STATE["pending_commands"]),
    }


@router.post("/mt5/order")
async def send_mt5_order(req: MT5ManualOrderRequest):
    """MT5 köprüsüne yeni bir piyasa emri iletir."""
    is_gold = ("XAU" in req.symbol.upper() or "GOLD" in req.symbol.upper())
    is_crypto = ("BTC" in req.symbol.upper() or "ETH" in req.symbol.upper())
    is_oil = ("USOIL" in req.symbol.upper() or "OIL" in req.symbol.upper() or "WTI" in req.symbol.upper() or "XTI" in req.symbol.upper())
    is_index = ("NAS" in req.symbol.upper() or "USTEC" in req.symbol.upper() or "US30" in req.symbol.upper() or "SPX" in req.symbol.upper())
    if is_index:
        lot_cap = 50.0
        actual_lots = round(max(0.10, min(req.lots, lot_cap)), 2)
    elif is_oil:
        lot_cap = 1.0
        actual_lots = round(max(0.50, min(req.lots, lot_cap)), 2)
    elif is_gold:
        lot_cap = min(HARD_MAX_GOLD_LOT, _AUTO_SETTINGS.max_gold_lot)
        actual_lots = round(max(0.01, min(req.lots, lot_cap)), 2)
    elif is_crypto:
        lot_cap = 50.0
        actual_lots = round(max(0.01, min(req.lots, lot_cap)), 2)
    else:
        lot_cap = min(HARD_MAX_FOREX_LOT, _AUTO_SETTINGS.max_forex_lot)
        actual_lots = round(max(0.01, min(req.lots, lot_cap)), 2)

    cmd_id = f"CMD-{int(time.time() * 1000) % 1000000}"
    cmd = {
        "id": cmd_id,
        "action": "OPEN_ORDER",
        "symbol": req.symbol.upper(),
        "direction": req.direction.upper(),
        "lots": actual_lots,
        "sl_pips": req.sl_pips,
        "tp_pips": req.tp_pips,
        "comment": req.comment or "Scalper Agent",
    }
    _MT5_STATE["pending_commands"].append(cmd)
    _log_auto_decision("ENTRY", f"🚀 [MT5 Manuel Emir Kuyruğa Alındı]: {actual_lots} Lot {req.direction} {req.symbol} (Limit: {lot_cap})", symbol=req.symbol)
    return {"status": "queued", "command": cmd}


@router.post("/mt5/close")
async def close_mt5_position(req: MT5CloseRequest):
    """MT5 köprüsüne belirli bir açık bileti kapatma emri iletir."""
    cmd_id = f"CMD-CLOSE-{req.ticket}"
    cmd = {
        "id": cmd_id,
        "action": "CLOSE_ORDER",
        "ticket": req.ticket,
    }
    _MT5_STATE["pending_commands"].append(cmd)
    _log_auto_decision("EXIT", f"🛑 [MT5 Kapatma Kuyruğa Alındı]: Bilet #{req.ticket}")
    return {"status": "queued", "ticket": req.ticket}


@router.post("/mt5/close-all")
async def close_all_mt5_positions():
    """Tüm açık MT5 pozisyonlarını tek seferde kapatma emri kuyruğa alır."""
    cmd_id = f"CMD-CLOSE-ALL-{int(time.time()*1000)%10000}"
    cmd = {
        "id": cmd_id,
        "action": "CLOSE_ALL",
    }
    _MT5_STATE["pending_commands"].append(cmd)
    _log_auto_decision("EXIT", "🛑 [MT5 Toplu Kapatma Kuyruğa Alındı]: Tüm açık MT5 pozisyonları kapatılıyor")
    return {"status": "queued", "command_id": cmd_id}


@router.post("/mt5/toggle-auto")
async def toggle_mt5_auto_trading(req: MT5ToggleAutoRequest):
    """Sinyallerin doğrudan MT5'e otomatik iletilmesini açar veya kapatır."""
    _MT5_STATE["auto_trade"] = req.auto_trade
    state_str = "ETKİNLEŞTİRİLDİ" if req.auto_trade else "DURDURULDU"
    _log_auto_decision("SYSTEM", f"⚡ IC Markets MT5 Otomatik Emir İletimi: {state_str}")
    return {"status": "ok", "auto_trade": _MT5_STATE["auto_trade"]}


@router.get("/news")
async def get_macro_forex_news(
    refresh: bool = False,
    stars: Optional[int] = None,
    country: Optional[str] = None,
    symbol: Optional[str] = None,
):
    """Investing.com 2 ve 3 Yıldızlı Makro Ekonomik Takvim Olaylarını 'Ne Olursa Ne Olur' senaryosuyla döner."""
    try:
        from app.forex_news import get_forex_news, FALLBACK_EVENTS
        items = await get_forex_news(force_refresh=refresh)
        
        # Filtreleme
        if stars is not None:
            items = [x for x in items if x.get("stars") == stars]
        if country:
            c_upper = country.upper()
            items = [x for x in items if x.get("country", "").upper() == c_upper or x.get("currency", "").upper() == c_upper]
        if symbol:
            s_upper = symbol.upper()
            items = [x for x in items if any(s_upper in str(sym).upper() for sym in x.get("affected_symbols", []))]

        upcoming_5m = [x for x in items if x.get("is_within_5m")]

        return {
            "status": "ok",
            "count": len(items),
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "Investing.com & Küresel Makro Akış (2 & 3 Yıldız)",
            "upcoming_5m_count": len(upcoming_5m),
            "upcoming_5m_alerts": upcoming_5m,
            "news": items,
        }
    except Exception as exc:
        logger.warning("Forex haberleri getirme hatası: %s", exc)
        try:
            from app.forex_news import FALLBACK_EVENTS
            fallback = FALLBACK_EVENTS
        except Exception:
            fallback = []
        return {
            "status": "ok",
            "count": len(fallback),
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "Yedek Makro Senaryo Akışı",
            "news": fallback,
        }

