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
import csv
import datetime
import hmac
import io
import json
import logging
import math
import os
import random
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Response, Request, Body
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
    # 2026-10-16: klasik radar, 18 krosun 7 günlük MT5 M5 testinde tek kalın eşleşme.
    # AUDCAD n=130, net +56.40, PF 1.42. Diğer kroslar eşiği (net>0, PF>=1.2, n>=8) geçemedi.
    {
        "symbol": "AUDCAD",
        "display": "AUD/CAD",
        "name": "Australian Dollar / Canadian Dollar",
        "category": "cross",
        "base": "AUD",
        "quote": "CAD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:AUDCAD",
        "default_price": 0.91000,
    },
    # Ek kros pariteleri (31 sembol IC Markets tam evreni)
    {
        "symbol": "CHFJPY",
        "display": "CHF/JPY",
        "name": "Swiss Franc / Japanese Yen",
        "category": "cross",
        "base": "CHF",
        "quote": "JPY",
        "pip_size": 0.01,
        "digits": 3,
        "tv_symbol": "FX:CHFJPY",
        "default_price": 191.930,
    },
    {
        "symbol": "CADJPY",
        "display": "CAD/JPY",
        "name": "Canadian Dollar / Japanese Yen",
        "category": "cross",
        "base": "CAD",
        "quote": "JPY",
        "pip_size": 0.01,
        "digits": 3,
        "tv_symbol": "FX:CADJPY",
        "default_price": 111.560,
    },
    {
        "symbol": "AUDJPY",
        "display": "AUD/JPY",
        "name": "Australian Dollar / Japanese Yen",
        "category": "cross",
        "base": "AUD",
        "quote": "JPY",
        "pip_size": 0.01,
        "digits": 3,
        "tv_symbol": "FX:AUDJPY",
        "default_price": 109.980,
    },
    {
        "symbol": "NZDJPY",
        "display": "NZD/JPY",
        "name": "New Zealand Dollar / Japanese Yen",
        "category": "cross",
        "base": "NZD",
        "quote": "JPY",
        "pip_size": 0.01,
        "digits": 3,
        "tv_symbol": "FX:NZDJPY",
        "default_price": 89.580,
    },
    {
        "symbol": "EURGBP",
        "display": "EUR/GBP",
        "name": "Euro / British Pound",
        "category": "cross",
        "base": "EUR",
        "quote": "GBP",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:EURGBP",
        "default_price": 0.84430,
    },
    {
        "symbol": "EURCHF",
        "display": "EUR/CHF",
        "name": "Euro / Swiss Franc",
        "category": "cross",
        "base": "EUR",
        "quote": "CHF",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:EURCHF",
        "default_price": 0.92700,
    },
    {
        "symbol": "EURCAD",
        "display": "EUR/CAD",
        "name": "Euro / Canadian Dollar",
        "category": "cross",
        "base": "EUR",
        "quote": "CAD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:EURCAD",
        "default_price": 1.59460,
    },
    {
        "symbol": "EURAUD",
        "display": "EUR/AUD",
        "name": "Euro / Australian Dollar",
        "category": "cross",
        "base": "EUR",
        "quote": "AUD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:EURAUD",
        "default_price": 1.61750,
    },
    {
        "symbol": "EURNZD",
        "display": "EUR/NZD",
        "name": "Euro / New Zealand Dollar",
        "category": "cross",
        "base": "EUR",
        "quote": "NZD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:EURNZD",
        "default_price": 1.98580,
    },
    {
        "symbol": "GBPCHF",
        "display": "GBP/CHF",
        "name": "British Pound / Swiss Franc",
        "category": "cross",
        "base": "GBP",
        "quote": "CHF",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:GBPCHF",
        "default_price": 1.09780,
    },
    {
        "symbol": "GBPAUD",
        "display": "GBP/AUD",
        "name": "British Pound / Australian Dollar",
        "category": "cross",
        "base": "GBP",
        "quote": "AUD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:GBPAUD",
        "default_price": 1.91580,
    },
    {
        "symbol": "GBPCAD",
        "display": "GBP/CAD",
        "name": "British Pound / Canadian Dollar",
        "category": "cross",
        "base": "GBP",
        "quote": "CAD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:GBPCAD",
        "default_price": 1.88860,
    },
    {
        "symbol": "GBPNZD",
        "display": "GBP/NZD",
        "name": "British Pound / New Zealand Dollar",
        "category": "cross",
        "base": "GBP",
        "quote": "NZD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:GBPNZD",
        "default_price": 2.35210,
    },
    {
        "symbol": "AUDNZD",
        "display": "AUD/NZD",
        "name": "Australian Dollar / New Zealand Dollar",
        "category": "cross",
        "base": "AUD",
        "quote": "NZD",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:AUDNZD",
        "default_price": 1.22780,
    },
    {
        "symbol": "AUDCHF",
        "display": "AUD/CHF",
        "name": "Australian Dollar / Swiss Franc",
        "category": "cross",
        "base": "AUD",
        "quote": "CHF",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:AUDCHF",
        "default_price": 0.57300,
    },
    {
        "symbol": "NZDCHF",
        "display": "NZD/CHF",
        "name": "New Zealand Dollar / Swiss Franc",
        "category": "cross",
        "base": "NZD",
        "quote": "CHF",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:NZDCHF",
        "default_price": 0.46670,
    },
    {
        "symbol": "CADCHF",
        "display": "CAD/CHF",
        "name": "Canadian Dollar / Swiss Franc",
        "category": "cross",
        "base": "CAD",
        "quote": "CHF",
        "pip_size": 0.0001,
        "digits": 5,
        "tv_symbol": "FX:CADCHF",
        "default_price": 0.58130,
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

# Radar tarama evreni (2026-10-08): L30 replay'de (33 sembol, klasik profil,
# gerçek p95 spread) pozitif çıkan 7 sembol. FX majör/kros'ta Radar 30 gün
# boyunca spread maliyetiyle zararda olduğu için taramadan çıkarıldı; grafik,
# teknik rapor ve emekli kayıt uyumluluğu FOREX_SYMBOLS üzerinden sürer.
# Motora sinyal üretilen liste budur — işlem kapısı (allowed_symbols) ayrıca
# devrede olduğundan buradaki genişlik tek başına risk açmaz.
RADAR_SCAN_SYMBOLS = {
    "XAUUSD", "US30", "BTCUSD", "GBPUSD", "AUDUSD", "AUDCAD",
}


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
# Endeks (US30/NAS100) için hard tavan. IC Markets bu sembollerde 1 lot'u 1
# kontrat olarak sunar ve fiyat 1$ kazandırdığında risk 1$ = büyük değil,
# AMA US30'da 0.20 lot × 81.7 pip = %1.6 risk göstergesiyle ölçüldü.
HARD_MAX_INDEX_LOT = 50.0
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

# TP-İPTAL CANLI VARSAYILANI (2026-10-09 kararı): Dört bağımsız replay penceresinde
# (IS/OOS/OOS2/F1) net kazancı artıran (+$65…+$215/pencere) ve maxDD'yi düşüren TEK
# işaret-tutarlı mekanizma "trailing aktifken sabit TP'yi çek" (V03) çıktı. ADX-rejimli
# dinamik trailing ve TP-ratchet pencereler arası işaret değiştirdiği için EKLENMEDİ.
# Bu yüzden canlı için VARSAYILAN AÇIK. Geri almak: FOREX_TP_CANCEL_ON_TRAIL=false.
# Kanıt: outputs/exit_sweep/FINDINGS.md + PREREG_V18_F1.md.
FOREX_TP_CANCEL_ON_TRAIL_DEFAULT = (
    os.getenv("FOREX_TP_CANCEL_ON_TRAIL", "true").strip().lower() == "true"
)

_LAST_GOLD_EXIT_TIME = 0.0
_LAST_XAU_RADAR_SIGNAL_BAR: Dict[str, int] = {}
_LAST_BTC_EXIT_TIME = 0.0
_LAST_SYMBOL_LOSS_TIME: Dict[str, float] = {}
_LAST_SYMBOL_EXIT_TIME: Dict[str, float] = {}
_LAST_SYMBOL_EXIT_DIR: Dict[str, str] = {}
_LAST_RADAR_SIGNAL_BAR: Dict[str, int] = {}
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
    # XBRUSD (Brent) USOIL'a eşlenir. NOT (2026-10-10 denetim P2-7): köprü tarafı
    # XBRUSD→UKOIL diyor, ama UKOIL uygulama evreninde YOK (FOREX_SYMBOLS'te girdisi
    # yok, panelde display'i yok). UKOIL'a eşlemek, spec'i "OIL" alt-dizesiyle
    # çalışsa bile display/rapor tarafında tanınmayan bir sembol üretirdi.
    # Bu yüzden bilinçli olarak USOIL'a sabitlendi; evren invariant'ı korunur:
    # bu haritanın ÜRETTİĞİ her ad FOREX_SYMBOLS'te bulunmalı.
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
    # 2026-10-10 denetim P2-7: broker'ın kendi kısa adları. Köprü `to_app_symbol`
    # bilinmeyen kısa adı olduğu gibi geçirir (eski davranış korunur); tam eşitlik
    # kullanan motor yolları bu dörtlüyü burada kanonikleştirir.
    "BTC": "BTCUSD",
    "WTI": "USOIL",
    "USOUSD": "USOIL",
    "WTICRUDE": "USOIL",
    "BRENT": "USOIL",
    "CRUDE": "USOIL",
    # Köprü XBRUSD/UKOUSD'yi UKOIL'a çevirir; UKOIL uygulama evreninde yok →
    # bilinmeyen sembol sızmasın diye burada USOIL'a kanonikleştirilir.
    "UKOIL": "USOIL",
    "UKOUSD": "USOIL",
    # DXY'nin MT5 adı brokera göre değişir. Altın bu haritayla DXY'ye bağlanmaz.
    "USDX": "DXY",
    "USDIDX": "DXY",
    "DOLLARIDX": "DXY",
    "DXY": "DXY",
    "DXY_Z6": "DXY",
    "DXY_H7": "DXY",
    "DXY_M7": "DXY",
    "DXY_U7": "DXY",
}


def canonical_symbol(symbol: str) -> str:
    """Broker sembolünü uygulama sembolüne normalize eder (2026-10-10 denetim P2-7).

    Motorun kritik dalları TAM eşitlik kullanır (`sym == "BTCUSD"`, `"BTC" in sym`).
    Broker sonekli ad gönderirse (`BTCUSD.m`, `XAUUSD.a`, `US30.cash`) bu dallar
    sessizce düşer: BTC soğuması, btc_min_score, EV muafiyeti, seri-SL ve spread
    tavanı hiç uygulanmaz. Köprü artık normalize ediyor; burası da eski köprü
    sürümleri ve doğrudan API çağrıları için aynı garantiyi verir.
    """
    s = str(symbol or "").upper().replace("/", "").strip()
    if not s:
        return ""
    if s in _MT5_TO_APP_SYMBOLS:
        return _MT5_TO_APP_SYMBOLS[s]
    base = s.split(".")[0].split("+")[0].split("-")[0].replace("#", "").strip()
    if base.startswith("DXY_") or (base.startswith("DXY") and len(base) <= 6):
        return "DXY"
    return _MT5_TO_APP_SYMBOLS.get(base, base or s)


# Tik → kapanmış kovalar. Açık kova göstergeye girmez.
_CLOSED_TICK_BARS: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
_OPEN_TICK_BUCKET: Dict[Tuple[str, int], Dict[str, float]] = {}
_PRICE_TS: Dict[str, float] = {}
_PRICE_SOURCE: Dict[str, str] = {}
_TICK_MISMATCH: Dict[str, float] = {}
_PENDING_FLIP: Dict[str, Dict[str, Any]] = {}
_CLOSED_BAR_ARM_SOURCES = frozenset({"s3_5m", "s3_15m", "squeeze_kc", "london_breakout"})
COMMODITY_MIN_SCORE = 78.0
_TICK_BAR_CAP = 400
_MIN_CLOSED_BARS_5M = 30


def _token_equal(provided: str, secret: str) -> bool:
    if not provided or not secret:
        return False
    a = provided.encode("utf-8")
    b = secret.encode("utf-8")
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def _configured_mt5_secret() -> str:
    """Paylaşılan sır. Kaynakta sabit yedek yok; boşsa köprü kapalıdır."""
    for key in ("MT5_BRIDGE_TOKEN", "FOREX_MT5_SYNC_TOKEN", "BINANCE_TR_BRIDGE_SECRET"):
        val = os.getenv(key, "").strip()
        if val:
            return val
    return ""


def _mt5_sync_authorized(request: Any) -> bool:
    secret = _configured_mt5_secret()
    if not secret or request is None:
        return False
    headers = getattr(request, "headers", None) or {}
    provided = ""
    try:
        provided = (
            headers.get("x-bridge-token")
            or headers.get("X-Bridge-Token")
            or headers.get("x-bridge-secret")
            or headers.get("X-Bridge-Secret")
            or ""
        )
    except Exception:
        provided = ""
    return _token_equal(str(provided), secret)


def _non_demo_live_blocked(server: Any) -> bool:
    """Development iken demo olmayan MT5 hesabına emir yazılmaz."""
    try:
        from app.config import PRODUCTION_MODE
    except Exception:
        return False
    if PRODUCTION_MODE:
        return False
    text = str(server or "").strip()
    if not text:
        return False
    return "demo" not in text.lower()


def _fold_tick_into_bucket(sym: str, bucket_sec: int, ts: float, price: float) -> None:
    key = (sym, bucket_sec)
    start = int(ts // bucket_sec) * bucket_sec
    cur = _OPEN_TICK_BUCKET.get(key)
    if cur is None or int(cur.get("time", -1)) != start:
        if cur is not None:
            closed = _CLOSED_TICK_BARS.setdefault(key, [])
            closed.append({
                "time": int(cur["time"]),
                "open": float(cur["open"]),
                "high": float(cur["high"]),
                "low": float(cur["low"]),
                "close": float(cur["close"]),
            })
            if len(closed) > _TICK_BAR_CAP:
                del closed[:-_TICK_BAR_CAP]
        _OPEN_TICK_BUCKET[key] = {
            "time": start, "open": price, "high": price, "low": price, "close": price,
        }
        return
    cur["high"] = max(float(cur["high"]), price)
    cur["low"] = min(float(cur["low"]), price)
    cur["close"] = price


def _note_mt5_tick(sym: str, bid: Optional[float], ask: Optional[float], ts: float) -> None:
    """Kanonic sembole tik yazar. default_price buraya girmez."""
    app = canonical_symbol(sym)
    if not app:
        return
    bid_f = float(bid) if bid and float(bid) > 0 else 0.0
    ask_f = float(ask) if ask and float(ask) > 0 else 0.0
    mid = (bid_f + ask_f) / 2.0 if bid_f > 0 and ask_f > 0 else (ask_f or bid_f)
    if mid <= 0:
        return
    _LIVE_PRICES_CACHE[app] = mid
    _PRICE_TS[app] = float(ts)
    _PRICE_SOURCE[app] = "mt5_tick"
    for bucket in (60, 300, 900):
        _fold_tick_into_bucket(app, bucket, float(ts), mid)


def _closed_tick_bars(sym: str, bucket_sec: int) -> List[Dict[str, Any]]:
    return list(_CLOSED_TICK_BARS.get((canonical_symbol(sym), bucket_sec), []))


def _broker_bars_utc_offset(raw: List[Dict[str, Any]], now_bucket: int, bucket_sec: int) -> int:
    """MT5 copy_rates zamanları broker sunucu saatindeyse (UTC+2/+3) farkı (sn) bulur."""
    max_opened = 0
    for bar in raw:
        try:
            t = int(bar.get("time", 0))
            if t > max_opened:
                max_opened = t
        except (TypeError, ValueError):
            continue
    if max_opened > now_bucket + int(bucket_sec):
        off = int(round((max_opened - now_bucket) / 1800.0) * 1800)
        if 0 < off <= 14 * 3600:
            return off
    return 0


def _closed_broker_bars(sym: str, interval: str, bucket_sec: int) -> List[Dict[str, Any]]:
    """Köprüden gelen kapanmış mumlar. Oluşan kova göstergeye girmez."""
    raw = _fetch_mt5_candles(canonical_symbol(sym), interval, 1000)
    if not raw:
        return []
    now_bucket = int(time.time() // int(bucket_sec)) * int(bucket_sec)
    offset = _broker_bars_utc_offset(raw, now_bucket, int(bucket_sec))
    closed: List[Dict[str, Any]] = []
    for bar in raw:
        try:
            opened = int(bar.get("time", 0)) - offset
            close_px = float(bar.get("close", 0.0))
        except (TypeError, ValueError):
            continue
        if opened <= 0 or opened >= now_bucket or close_px <= 0:
            continue
        if offset:
            item = dict(bar)
            item["time"] = opened
            closed.append(item)
        else:
            closed.append(bar)
    return closed


def _bars_have_gap(bars: List[Dict[str, Any]], bucket_sec: int) -> bool:
    recent = bars[-6:] if len(bars) > 6 else bars
    times = [int(b.get("time", 0)) for b in recent]
    for prev, nxt in zip(times, times[1:]):
        if nxt - prev > bucket_sec:
            return True
    return False


def _verify_tick_bars_against_bridge(sym: str, interval: str, bars: List[Dict[str, Any]]) -> None:
    """Köprü mumu yalnız tik türevinin kapanışını doğrular; kaynak olmaz."""
    app = canonical_symbol(sym)
    if not bars:
        return
    mt5_bars = _fetch_mt5_candles(app, interval, 40)
    if not mt5_bars:
        _TICK_MISMATCH.pop(app, None)
        return
    bucket_sec = 900 if str(interval).lower() in ("15m", "15") else 300
    now_bucket = int(time.time() // bucket_sec) * bucket_sec
    offset = _broker_bars_utc_offset(mt5_bars, now_bucket, bucket_sec)
    by_time = {(int(b.get("time", 0)) - offset): b for b in mt5_bars}
    last = bars[-1]
    other = by_time.get(int(last.get("time", 0)))
    if not other:
        return
    px = float(last.get("close") or 0.0)
    ref = float(other.get("close") or 0.0)
    if px <= 0 or ref <= 0:
        return
    if abs(ref - px) / px > 0.002:
        _TICK_MISMATCH[app] = time.time()
    else:
        _TICK_MISMATCH.pop(app, None)


def required_entry_score(symbol: str, weak_bump: float = 0.0) -> float:
    """Panel kapısı ve motor aynı eşiği okur. Emtia tabanı tek sabittir."""
    sym = str(symbol or "").upper()
    if sym == "BTCUSD":
        base = _AUTO_SETTINGS.btc_min_score if _AUTO_SETTINGS.btc_min_score > 0 else _AUTO_SETTINGS.min_score
    else:
        is_commodity = ("XAU" in sym or "GOLD" in sym or "OIL" in sym or "USOIL" in sym)
        base = COMMODITY_MIN_SCORE if is_commodity else _AUTO_SETTINGS.min_score
    return float(base) + float(weak_bump or 0.0)


def supertrend_blocks_entry(
    entry_source: Any,
    direction: str,
    st_dir: int,
    *,
    news_bypass: bool = False,
) -> bool:
    """SuperTrend istisnası tek yerde: EAP, S3 ve Squeeze kendi yönünü taşır."""
    if not _AUTO_SETTINGS.supertrend_filter_enabled or news_bypass:
        return False
    src = str(entry_source or "")
    if src == "ema_adx_pullback" or src.startswith("s3_") or src == "squeeze_kc":
        return False
    if int(st_dir or 0) == 0:
        return False
    if direction == "BUY" and int(st_dir) < 0:
        return True
    if direction == "SELL" and int(st_dir) > 0:
        return True
    return False


def entry_data_blocked(tick: Optional[Dict[str, Any]]) -> Optional[str]:
    """Spread yok, default/günlük kur, bayat tik veya 5m boşluğu girişi kapatır.

    Alan hiç yoksa (eski birim testi) kesmez. Radar her tikte alanı yazar.
    """
    if not tick:
        return "veri"
    if "source" in tick and tick.get("source") != "mt5_tick":
        return "veri"
    if tick.get("price_placeholder"):
        return "veri"
    if tick.get("tick_mismatch"):
        return "veri"
    if tick.get("spread_known") is False:
        return "spread"
    if "age_sec" in tick:
        age = tick.get("age_sec")
        try:
            age_f = float(age) if age is not None else None
        except (TypeError, ValueError):
            age_f = None
        if age_f is None or age_f > _TECH_STALE_SEC:
            return "bayat"
    if tick.get("bar_gap"):
        return "bar_gap"
    return None


def _order_entry_arms(
    radar_rows: List[Dict[str, Any]],
    arm_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Sembol başına kol listesi. Kapanmış bar kolları canlı kesişimin önünde.

    Aynı öncelikte mevcut döngü sırası (eklenme sırası) korunur. Skor 200 yazılmaz.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    seq = 0
    for row in list(radar_rows or []):
        item = dict(row)
        item["_seq"] = seq
        seq += 1
        grouped.setdefault(str(item.get("symbol", "")).upper(), []).append(item)
    for row in list(arm_rows or []):
        item = dict(row)
        item["_seq"] = seq
        seq += 1
        grouped.setdefault(str(item.get("symbol", "")).upper(), []).append(item)
    ordered: List[Dict[str, Any]] = []
    for _sym, rows in grouped.items():
        rows.sort(key=lambda r: (
            0 if str(r.get("entry_source") or "") in _CLOSED_BAR_ARM_SOURCES else 1,
            int(r.get("_seq", 0)),
        ))
        ordered.extend(rows)
    return ordered


def _commit_arm_quota(cand: Dict[str, Any]) -> None:
    """Sayaç yalnız emir kuyruğa (veya paper kayda) girince, mum başına bir kez."""
    meta = cand.get("_arm_quota") or {}
    if not meta or meta.get("done"):
        return
    kind = str(meta.get("kind") or "")
    sym = str(meta.get("symbol") or "")
    action = str(meta.get("action") or "")
    bar_time = meta.get("bar_time")
    if kind == "donchian":
        st = _DONCHIAN_STATE.get(sym)
        if st is not None and action:
            st["counts"][action] = int(st["counts"].get(action, 0)) + 1
            st["consumed_bar"] = bar_time
    elif kind == "ema":
        st = _EMA_ADX_STATE.get(sym)
        if st is not None and action:
            st["counts"][action] = int(st["counts"].get(action, 0)) + 1
            st["consumed_bar"] = bar_time
    elif kind == "lb":
        st = _LB_STATE.get(sym)
        if st is not None and action:
            st["counts"][action] = int(st["counts"].get(action, 0)) + 1
            st["consumed_bar"] = bar_time
    elif kind == "ls":
        st = _LS_STATE.get(sym)
        if st is not None:
            st["entered"] = True
            st["consumed_bar"] = bar_time
    elif kind == "squeeze":
        st = _SQUEEZE_KC_DAY_STATE.get(sym)
        day_key = str(meta.get("day_key") or "")
        if st is not None and day_key:
            st["counts"][day_key] = int(st["counts"].get(day_key, 0)) + 1
            st["consumed_bar"] = bar_time
    elif kind == "s3":
        st = _S3_DAY_STATE.get(str(meta.get("key") or ""))
        action_key = str(meta.get("action_key") or "")
        if st is not None and action_key:
            st["counts"][action_key] = int(st["counts"].get(action_key, 0)) + 1
            st["consumed_bar"] = bar_time
    meta["done"] = True


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
    # 2026-10-08 Radar-evreni replay pozitifleri (S3 akışı + köprü mum izleme)
    "NZDJPY": "NZDJPY=X",
    "AUDNZD": "AUDNZD=X",
    # 2026-10-08 London Breakout replay pozitifleri (L30; Asya kutusu kırılımı)
    "GBPCHF": "GBPCHF=X",
    "EURCAD": "EURCAD=X",
    "CHFJPY": "CHFJPY=X",
    "CADJPY": "CADJPY=X",
    "GBPNZD": "GBPNZD=X",
    "GBPAUD": "GBPAUD=X",
    "GBPCAD": "GBPCAD=X",
    "AUDCAD": "AUDCAD=X",
    "EURAUD": "EURAUD=X",
    "CADCHF": "CADCHF=X",
    "AUDCHF": "AUDCHF=X",
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
    Veri yoksa None döner. Majörlerde bu, veto (giriş yok) demektir.
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
        # Canlı DXY seviyesi (BTC-Gold sayfasındaki dinamik DXY progress bar'ı için).
        # Endeksin MUTLAK değeri, rejim yorumundan ayrıdır: kullanıcı "değeri de
        # yazalım" dedi, yalnız "USD_WEAK" etiketi yetmiyordu.
        "price": float(tech.get("price", 0.0) or 0.0),
        "updated_at": tech.get("updated_at", 0.0),
    }


def dxy_entry_veto(symbol: str, direction: str, dxy: Optional[Dict[str, Any]]) -> Optional[str]:
    """DXY rejimine göre giriş denetimi (saf fonksiyon — test edilebilir).

    Dönen değer:
    - None: İzin var. Majörde DXY verisi yoksa None DEĞİL, "dxy_no_data" döner.
    - "dxy_no_data": MT5'te DXY yok / rejim yok ve sembol majör. Giriş yok.
      Altın ve DXY_EXEMPT semboller bu vetoya girmez.
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
        if str(symbol).upper() in FX_MAJORS_SET:
            return "dxy_no_data"
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


# Sembol EV kalkanı muafiyet ve sıfırlama durumu (yalnız dict mutasyonu)
_SYMBOL_EV_OVERRIDE_UNTIL: Dict[str, float] = {}
_SYMBOL_EV_RESET_AT_TS: Dict[str, float] = {}


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
            # EV reset kesimi: global veya sembol bazlı reset anından önce kapanan işlemler sicile girmez —
            # sembol, reset sonrasındaki davranışıyla değerlendirilir.
            sym_reset_ts = max(_EV_RESET_AT_TS, _SYMBOL_EV_RESET_AT_TS.get(sym, 0.0))
            if sym_reset_ts and float(ts) < sym_reset_ts:
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


# Köprü kapanış nedenleri serbest metindir (scripts/mt5_bridge.py: MT5 anlaşma
# yorumundan "[sl …]" / "[tp …]" / "[be …]" okunur, yoksa ham yorum taşınır).
# Seri-SL sayacı kanonik token bekler; eşleme TEK yerde durur ki köprü metni
# değişse de canlı kapanış beslemesi aynı kuralı uygulasın.
_BROKER_REASON_TOKENS = (
    ("SL_HIT", ("[sl", "sl ", "sl_", "sl]", "sl_hit", "zarar durdur", "zarar kes", "zarar", "stop loss", "stop out", "[so", "so ")),
    ("TP_HIT", ("[tp", "tp ", "tp_", "tp]", "tp_hit", "kâr al", "kar al", "take profit")),
    ("BE_HIT", ("[be", "be ", "be_", "be]", "be_hit", "başabaş", "basabas")),
    ("TRAILING_HIT", ("trailing", "süren")),
)


def normalize_close_reason(reason: Any) -> str:
    """Kapanış nedenini kanonik token'a çevirir (saf fonksiyon — test edilebilir).

    Canlı MT5 modunda kapanışlar panel motorundan değil köprüden gelir; neden
    alanı Türkçe başlık ("🛑 Zarar Durdur (SL)") ya da ham MT5 yorumudur
    ("Scalper Close" / "Scalper Partial"). Seri-SL sigortası `SL_HIT` beklediği
    için bu eşleme olmadan canlı kapanışlar sayaca hiç girmez.
    Eşleşme yoksa "" döner → sayaç değişmez (manuel/kısmi kapanışlar sayılmaz).
    """
    text = str(reason or "").strip().lower()
    if not text:
        return ""
    for token, needles in _BROKER_REASON_TOKENS:
        if any(n in text for n in needles):
            return token
    return ""


def feed_loss_streak_from_deal(symbol: Any, reason: Any, pnl_usd: Any, direction: Optional[str] = None) -> bool:
    """Köprüden gelen kapanmış işlemi seri-SL sayacına besler (CANLI MT5 yolu).

    Canlı modda pozisyonlar `_MT5_STATE`'te tutulur ve kapanışları panele köprü
    `deals` akışıyla düşer — `_close_position_internal` bu yollardan GEÇMEZ.
    Hem sembol geneli hem de işlem yönü (BUY / SELL) bazında ardışık zararları izler.
    3 ardışık zararda sembol ve ilgili yön 5 dakika soğumaya alınır.

    Döner: True → soğuma penceresi tetiklendi (yeni girişler kısa süre durur).
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return False
    sym = _MT5_TO_APP_SYMBOLS.get(sym, sym)
    limit = int(_AUTO_SETTINGS.loss_streak_limit)
    norm_reason = normalize_close_reason(reason)
    pnl = float(pnl_usd or 0.0)

    # 1. Sembol Geneli Seri
    streak, tripped = loss_streak_on_close(
        _SYMBOL_LOSS_STREAK.get(sym, 0),
        norm_reason,
        pnl,
        limit,
    )
    _SYMBOL_LOSS_STREAK[sym] = streak
    now_t = time.time()
    cd_duration = float(_AUTO_SETTINGS.loss_streak_cooldown_sec)

    if tripped:
        _SYMBOL_LOSS_COOLDOWN_UNTIL[sym] = now_t + cd_duration
        _log_auto_decision(
            "GATE",
            f"🌡️ [{sym}] {limit} ardışık SL kaybı (canlı MT5 kapanışı) — sembol "
            f"{cd_duration:.0f} sn serbest soğumaya alındı "
            f"(açık pozisyon yönetimi sürer, süre bitince normal değerlendirme).",
            symbol=sym,
        )

    # 2. Yön Bazlı Seri (BUY / SELL)
    dir_up = str(direction or "").upper().strip()
    dir_tripped = False
    if dir_up in ("BUY", "SELL"):
        dir_key = (sym, dir_up)
        d_streak, dir_tripped = loss_streak_on_close(
            _SYMBOL_DIR_LOSS_STREAK.get(dir_key, 0),
            norm_reason,
            pnl,
            limit,
        )
        _SYMBOL_DIR_LOSS_STREAK[dir_key] = d_streak
        if dir_tripped:
            _SYMBOL_DIR_LOSS_COOLDOWN_UNTIL[dir_key] = now_t + cd_duration
            _log_auto_decision(
                "GATE",
                f"🌡️ [{sym} {dir_up}] {limit} ardışık {dir_up} kaybı — bu yönde "
                f"{cd_duration:.0f} sn yeni işlem açılmayacak.",
                symbol=sym,
            )

    return tripped or dir_tripped


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


# EMA+ADX geri-çekilme skalpi (2026-10-08 canlıya alım — replay kanıtı):
#   XAUUSD 5m SL 1.5×ATR / TP 2.0×ATR: 60g +$184.56 (PF 1.33, n=227, WR %83.7) ve
#   bağımsız pencere Temmuz 1-15 +$153.90 (PF 2.31, n=87, WR %89.7) → iki pencerede
#   de pozitif. Kayıtta `EMA_ADX_PULLBACK_M5`, logda "EMA+ADX Geri Çekilme (M5)".
EMA_ADX_PULLBACK_STRATEGY = "EMA_ADX_PULLBACK_M5"
EMA_ADX_PULLBACK_LABEL = "EMA+ADX Geri Çekilme (M5)"
LONDON_BREAKOUT_STRATEGY = "LONDON_BREAKOUT"
LONDON_BREAKOUT_LABEL = "London Breakout (Asya Kutusu)"
# London Sign = NY-açılışı sign-momentum (Seeck 2026 uyarlaması). 2026-10-12 replay
# kazananı (XAUUSD+US30, 5 pencere hepsi pozitif; slip 2p/bacakta PF 1.76): 13:30-14:00
# sign penceresi → 14:00-14:30 giriş, SL 1.5×ATR, TP yok (chandelier), EoD kapanış.
LONDON_SIGN_STRATEGY = "LONDON_SIGN"
LONDON_SIGN_LABEL = "London Sign (NY Açılışı Momentum)"
# S3 = Supertrend+RSI pullback (goose AI strateji #3; L30 replay: XAU 5m +90/PF 2.09,
# XAU 15m +58/PF 3.08, BTC 15m +59/PF 6.63 — 2026-10-08 kullanıcı kararı canlıya alındı)
S3_PULLBACK_STRATEGY = "S3_SUPERTREND_RSI"
S3_PULLBACK_LABEL = "S3 Supertrend+RSI"
# Keltner/TTM Squeeze kırılımı (John Carter) — M15 kolu. 2026-10-14 kullanıcı kararı canlıya
# alındı. Kanıt (MT5 gerçek tick → PostgreSQL kanonik hattı, gerçek spread profili):
#   standalone M15: OOS 09-07→10-07 n=97 WR %74.2 net +$143.93 PF 1.74 maxDD $53.83;
#                     IS 08-01→09-07 n=123 WR %72.4 net +$77.65 PF 1.47 maxDD $54.66;
#                     2× spread'de de iki pencere pozitif (+$140.79 / +$51.93).
#   defter testi (`--combined`, klasik radar YANINDA, canlının GERÇEK bayrakları:
#   st-filter+muafiyet / major-min-atr 2.5 / max-open 99 / chandelier 0.3 + kol
#   sırası & sembol-bazlı YERİNDEN ETME paritesi): dört hücrede de net ARTAR,
#   maxDD hiç bozulmaz → OOS 1× +$3483.27→+$3565.89 (Δ+82.62, DD ±0) ·
#   OOS 2× +$2557.10→+$2735.02 (Δ+177.92, DD −4.40) · IS 1× +$5301.11→+$5490.92
#   (Δ+189.81, DD ±0) · IS 2× +$4694.36→+$4799.28 (Δ+104.92, DD −4.55).
#   Artefakt: outputs/skc_ab_*.json (koşum: scripts/_run_skc_ab.sh).
# Kapsam: kanıtlanan 5 sembol (aşağıdaki SQUEEZE_KC_SYMBOLS).
SQUEEZE_KC_STRATEGY = "SQUEEZE_KC_M15"
SQUEEZE_KC_LABEL = "Keltner Squeeze Kırılımı (M15)"


def strategy_name_for(entry_source: Any) -> str:
    """Giriş kaynağından işlem kaydına yazılacak strateji kimliğini türetir.

    Kayıt/repor/CSV'de hangi algoritmanın işlemi açtığı görünür olsun (kullanıcı
    isteği 2026-10-08). Öncelik: mod → donchian → klasik radar.
    """
    src = str(entry_source or "").strip().lower()
    if src == "ema_adx_pullback":
        return EMA_ADX_PULLBACK_STRATEGY
    if src.startswith("s3_"):
        return S3_PULLBACK_STRATEGY
    if src == "donchian":
        return "DONCHIAN_ADX"
    if src == "london_breakout":
        return LONDON_BREAKOUT_STRATEGY
    if src == "london_sign":
        return LONDON_SIGN_STRATEGY
    if src == "squeeze_kc":
        return SQUEEZE_KC_STRATEGY
    return "M1_M5_RADAR_SCALPER"


def strategy_comment_tag(entry_source: Any) -> str:
    """MT5 emir yorumu için KISA strateji etiketi (MT5 yorum sınırı 31 karakter).

    Kapanan işlemlerin `comment` alanı köprüden geri gelir; bu etiket sayesinde
    MT5 geçmişinde/işlem kaydında işlemin hangi stratejiye ait olduğu okunur.
    """
    src = str(entry_source or "").strip().lower()
    if src == "ema_adx_pullback":
        return "EAP-M5"
    if src.startswith("s3_"):
        return "S3" if src == "s3_5m" else "S3F"  # S3=5m, S3F=15m (flip/four-hour değil!)
    if src == "donchian":
        return "DONCH"
    if src == "london_breakout":
        return "LBRK"
    if src == "london_sign":
        return "LSGN"
    if src == "squeeze_kc":
        return "SQZKC"
    return "RADAR"


def strategy_display_label(code_or_source: Any) -> str:
    """Strateji kodundan veya giriş kaynağından insan-okur Türkçe etiket türetir."""
    s = str(code_or_source or "").strip()
    u = s.upper()
    if u in ("EMA_ADX_PULLBACK", "EMA_ADX_PULLBACK_M5", "EAP", "EAP-M5") or "EMA_ADX" in u or "EAP" in u:
        return "EMA+ADX Pullback (M5)"
    if u in ("S3_SUPERTREND_RSI", "S3", "S3_5M", "S3_15M") or "S3" in u:
        if "15" in u or "S3F" in u:
            return "S3 SuperTrend+RSI (M15)"
        return "S3 SuperTrend+RSI (M5)"
    if u in ("DONCHIAN_ADX", "DONCHIAN", "DONCH") or "DONCH" in u:
        return "Donchian ADX Kırılımı"
    if u in ("SQUEEZE_KC_M15", "SQZKC", "SQUEEZE_KC") or "SQUEEZE_KC" in u or "SQZKC" in u:
        return "Keltner Squeeze Kırılımı (M15)"
    if u in ("LONDON_SIGN", "LSGN", "LS") or "LONDON_SIGN" in u:
        return "London Sign (NY Açılışı Momentum)"
    if u in ("LONDON_BREAKOUT", "LBRK", "LB") or "LONDON" in u:
        return "London Breakout"
    if u in ("M1_M5_RADAR_SCALPER", "RADAR", "RADAR_SCALPER") or "RADAR" in u:
        return "M1/M5 Çoklu Radar"
    if u == "MANUAL":
        return "Manuel Giriş"
    if u == "IC_MARKETS_MT5":
        return "IC Markets MT5"
    return s if s else "M1/M5 Çoklu Radar"


def strategy_from_mt5_deal(deal: Dict[str, Any]) -> str:
    """MT5 kapanış kaydından strateji kimliğini çöz (etiket/yorum → tam ad).

    Köprü emir açılışındaki `comment`'i `strategy_tag` olarak taşır. Eski/etiketsiz
    kayıtlar (köprü güncellenmeden önce açılanlar) nötr "IC_MARKETS_MT5" alır.
    """
    src = str(deal.get("strategy") or "").strip()
    if src:
        return src
    raw_tag = str(deal.get("strategy_tag") or deal.get("entry_source") or deal.get("comment") or "").upper().strip()
    if "EAP" in raw_tag or "EMA_ADX" in raw_tag:
        return EMA_ADX_PULLBACK_STRATEGY
    if "S3" in raw_tag:
        return S3_PULLBACK_STRATEGY
    if "DONCH" in raw_tag:
        return "DONCHIAN_ADX"
    if "SQZKC" in raw_tag or "SQUEEZE_KC" in raw_tag:
        return SQUEEZE_KC_STRATEGY
    if "LSGN" in raw_tag or "LONDON_SIGN" in raw_tag:
        return LONDON_SIGN_STRATEGY
    if "LBRK" in raw_tag or "LONDON" in raw_tag:
        return LONDON_BREAKOUT_STRATEGY
    if "RADAR" in raw_tag:
        return "M1_M5_RADAR_SCALPER"
    return "IC_MARKETS_MT5"


def _s3_ema_series(vals: List[float], period: int) -> List[float]:
    """EMA serisi (replay `_ema_series` ile birebir)."""
    if not vals:
        return []
    k = 2.0 / (period + 1.0)
    out = [vals[0]]
    e = vals[0]
    for v in vals[1:]:
        e += k * (v - e)
        out.append(e)
    return out


def _s3_rsi_wilder(closes: List[float], period: int = 14) -> List[Optional[float]]:
    """Wilder RSI serisi (replay `_rsi_wilder` ile birebir; ilk `period` bar None)."""
    out: List[Optional[float]] = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    deltas = [closes[i + 1] - closes[i] for i in range(period)]
    avg_g = sum(max(d, 0.0) for d in deltas) / period
    avg_l = sum(max(-d, 0.0) for d in deltas) / period
    for i in range(period, len(closes)):
        if i > period:
            d = closes[i] - closes[i - 1]
            avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
            avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if avg_l <= 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    return out


def _s3_atr_series(bars: List[Dict[str, Any]], period: int = 14) -> List[float]:
    """ATR serisi (replay `_mini_atr_series` ile birebir; bars = {open,high,low,close})."""
    if not bars:
        return []
    trs: List[float] = []
    prev_c = float(bars[0]["close"])
    for b in bars:
        h, l, c = float(b["high"]), float(b["low"]), float(b["close"])
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
        prev_c = c
    a = sum(trs[:period]) / period
    out = [a] * min(period, len(trs))
    for i in range(period, len(trs)):
        a = (a * (period - 1) + trs[i]) / period
        out.append(a)
    return out


def _s3_wilder_ema_series(vals: List[float], period: int) -> List[float]:
    """Wilder yumuşatmalı EMA — klasik Keltner Kanalı formu (replay `_wilder_ema_series` birebir)."""
    if not vals:
        return []
    k = 1.0 / period
    seed = sum(vals[:period]) / min(period, len(vals))
    out = [seed] * min(period, len(vals))
    e = seed
    for v in vals[period:]:
        e += k * (v - e)
        out.append(e)
    return out


def _squeeze_kc_series_live(bars: List[Dict[str, Any]], period: int = 20,
                            bb_mult: float = 2.0, kc_mult: float = 1.5) -> Dict[str, List[float]]:
    """Bollinger ⊂ Keltner sıkışma serisi + LazyBear momentum (replay `_squeeze_kc_series` birebir).

    `bars` = {open,high,low,close}; dönen seriler bar sayısıyla hizalıdır ve yalnız i ve
    öncesinden türetilir (look-ahead yok). Sıkışma = bb_up < kc_up VE bb_lo > kc_lo.
    """
    n = len(bars)
    if n < period + 1:
        return {}
    closes = [float(b["close"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    bb_up = [0.0] * n
    bb_lo = [0.0] * n
    # SMA(period) ± bb_mult·σ kayan pencere
    s = s2 = 0.0
    for i in range(n):
        s += closes[i]
        s2 += closes[i] * closes[i]
        if i >= period:
            s -= closes[i - period]
            s2 -= closes[i - period] * closes[i - period]
        if i >= period - 1:
            m = s / period
            var = max(0.0, s2 / period - m * m)
            sd = var ** 0.5
            bb_up[i] = m + bb_mult * sd
            bb_lo[i] = m - bb_mult * sd
    # TR → Wilder ATR serisi
    trs: List[float] = []
    prev_c = closes[0]
    for i in range(n):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - prev_c), abs(lows[i] - prev_c)))
        prev_c = closes[i]
    if len(trs) >= period:
        a = sum(trs[:period]) / period
        atr = [a] * period
        for i in range(period, len(trs)):
            a = (a * (period - 1) + trs[i]) / period
            atr.append(a)
        atr = atr[:n]
    else:
        atr = trs[:]
    kc_mid = _s3_wilder_ema_series(closes, period)
    # Momentum = close − (en yüksek high + en düşük low + SMA) / 3, son `period` barda
    mom = [0.0] * n
    for i in range(period - 1, n):
        hi = max(highs[i - period + 1:i + 1])
        lo = min(lows[i - period + 1:i + 1])
        sma = sum(closes[i - period + 1:i + 1]) / period
        mom[i] = closes[i] - (hi + lo + sma) / 3.0
    return {
        "bb_up": bb_up, "bb_lo": bb_lo, "kc_mid": kc_mid,
        "kc_up": [kc_mid[i] + kc_mult * atr[i] for i in range(n)],
        "kc_lo": [kc_mid[i] - kc_mult * atr[i] for i in range(n)],
        "mom": mom,
        # Kapanışlar da döner: sıkışma bırakışını fiyatla karşılaştırırken
        # bar dizisini yeniden okumaya gerek kalmaz (aynı index uzayı).
        "close": closes,
    }


def _squeeze_kc_tech_for(sym: str) -> Optional[Dict[str, Any]]:
    """Keltner Squeeze (M15) gösterge seti — kapanmış barlar, look-ahead yok.

    Bar kaynağı S3/LB/LS ile ortak: önce köprü broker mumları, yoksa Yahoo
    (`_s3_bars_for`). Oluşan son bar diziden çıkarılır (replay `ci-1` disiplini):
    `ci` = kapanmış bar sayısı, karar barı `ci-1` (dizide son eleman).
    """
    bars_full = _s3_bars_for(sym, "15m", limit=260)
    if not bars_full:
        return None
    closed = bars_full
    period = int(_AUTO_SETTINGS.squeeze_kc_period)
    # Replay kapısı `ci < period + 30` → kapanmış bar sayısı yetersizse pas.
    if len(closed) < period + 30:
        return None
    ser = _squeeze_kc_series_live(closed, period,
                                  float(_AUTO_SETTINGS.squeeze_kc_bb_mult),
                                  float(_AUTO_SETTINGS.squeeze_kc_mult))
    if not ser:
        return None
    return {
        "series": ser,
        "bars": len(closed),
        "bar_time": int(closed[-1].get("time", 0)) if closed else 0,
        "updated_at": float(_PRICE_TS.get(canonical_symbol(sym), 0.0) or 0.0),
    }


def squeeze_kc_entry(tech: Optional[Dict[str, Any]], pip_size: float,
                     day_counts: Optional[Dict[str, int]] = None) -> Optional[Dict[str, Any]]:
    """Keltner Squeeze M15 giriş kararı (replay `TUN_ENTRY_MODE == "squeeze_kc"` birebir).

    Kural: bir önceki barda sıkışma vardı (BB ⊂ Keltner) ve bu barda bant dışına
    çıkıldı; kapanış bandın dışında VE LazyBear momentumu aynı işaretli ise giriş.
    SL = |kapanış − KC orta|, TP = `squeeze_kc_tp_r` × SL. Sembol+gün+yön başına
    en çok 2 giriş (replay `MODE_DAY_STATE` sayacı).

    Döner: {"action", "sl_pips", "tp_pips", "mom", "day_key"} ya da None.
    `pip_size <= 0` ise SL hesaplanamaz → `sl_pips: None` döner (çağıran spec
    SL/TP yoluna düşer; replay'in `_mode_atr_exits` fallback'i budur).
    """
    if not tech:
        return None
    ser = tech.get("series") or {}
    n = int(tech.get("bars") or 0)
    j, jp = n - 1, n - 2          # karar barı ve bir öncesi
    if jp < 0 or not ser.get("bb_up"):
        return None
    bb_u, bb_l = ser["bb_up"][j], ser["bb_lo"][j]
    kc_u, kc_l = ser["kc_up"][j], ser["kc_lo"][j]
    if bb_u <= 0 or bb_l <= 0:
        return None
    squeezed_prev = (ser["bb_up"][jp] < ser["kc_up"][jp]) and (ser["bb_lo"][jp] > ser["kc_lo"][jp])
    released = (bb_u >= kc_u) or (bb_l <= kc_l)
    if not (squeezed_prev and released):
        return None
    closes = ser.get("close") or []
    if len(closes) <= j:
        return None
    c = float(closes[j])
    mom = float(ser["mom"][j])
    mom_min = float(_AUTO_SETTINGS.squeeze_kc_mom_min)
    if c >= bb_u and mom >= mom_min:
        action = "BUY"
    elif c <= bb_l and mom <= -mom_min:
        action = "SELL"
    else:
        return None
    day_key = f"{datetime.datetime.now(datetime.timezone.utc).toordinal()}|{action}"
    if day_counts is not None and int(day_counts.get(day_key, 0)) >= 2:
        return None
    sl_pips = round(abs(c - float(ser["kc_mid"][j])) / pip_size, 1) if pip_size > 0 else 0.0
    if sl_pips <= 0:
        return {"action": action, "sl_pips": None, "tp_pips": None,
                "mom": mom, "bb_up": bb_u, "bb_lo": bb_l, "day_key": day_key}
    return {"action": action, "sl_pips": sl_pips,
            "tp_pips": round(float(_AUTO_SETTINGS.squeeze_kc_tp_r) * sl_pips, 1),
            "mom": mom, "bb_up": bb_u, "bb_lo": bb_l, "day_key": day_key}


def _s3_st_dir_series(bars: List[Dict[str, Any]], period: int = 10, mult: float = 3.0) -> List[int]:
    """SuperTrend yön serisi (replay `_st_dir_series` / forex._compute_supertrend ile birebir ratchet)."""
    n = len(bars)
    out = [0] * n
    if n < period + 2:
        return out
    h = [float(b["high"]) for b in bars]
    l = [float(b["low"]) for b in bars]
    c = [float(b["close"]) for b in bars]
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, n)]
    atr_series = []
    atr_val = sum(tr[:period]) / period
    atr_series.append(atr_val)
    for i in range(period, len(tr)):
        atr_val = (atr_val * (period - 1) + tr[i]) / period
        atr_series.append(atr_val)
    hl2 = [(h[i] + l[i]) / 2.0 for i in range(n)]
    direction = 0
    final_upper = 0.0
    final_lower = 0.0
    for i in range(period, n):
        atr_i = atr_series[i - period] if (i - period) < len(atr_series) else atr_series[-1]
        upper = hl2[i] + mult * atr_i
        lower = hl2[i] - mult * atr_i
        prev_close = c[i - 1]
        if i == period:
            final_upper, final_lower = upper, lower
            direction = 1 if c[i] >= hl2[i] else -1
        else:
            # `_compute_supertrend` ile aynı ratchet (yorum birebir diyorsa kod da).
            final_upper = upper if (upper < final_upper or prev_close > final_upper) else final_upper
            final_lower = lower if (lower > final_lower or prev_close < final_lower) else final_lower
            if c[i] > final_upper:
                direction = 1
            elif c[i] < final_lower:
                direction = -1
        out[i] = direction
    return out


def s3_pullback_entry(
    st_dir: int,
    close: float, ema200: float, use_ema200: bool,
    adx: float, adx_min: float,
    rsi_now: Optional[float], rsi_prev: Optional[float], rsi_window: List[Optional[float]],
    rsi_lo: float,
    atr_price: float, pip_size: float,
    day_counts: Dict[str, int], max_per_day: int, action_key: Optional[str] = None,
) -> Optional[str]:
    """S3 (Supertrend+RSI pullback) giriş kararı (saf fonksiyon — replay ile birebir).

    Kural seti (goose AI #3, replay `_entry_mode_candidate` supertrend_rsi bloğu):
      1) Yön: ST(10,3) son kapanmış bar (0 = tanımsız → yok)
      2) EMA200 tarafı: LONG için kapanış EMA200 üstünde, SHORT altında
      3) ADX(14) ≥ eşik
      4) LONG: son 6 barda RSI < 50 sarkması (40 bandını TAMAMEN kırma yok — trend
         bozulur) + önceki bar 50 altında + bu barda 50 üstüne kapanış; SHORT ayna
      Döner: "BUY" / "SELL" / None.
    """
    if atr_price <= 0 or pip_size <= 0:
        return None
    if st_dir == 0:
        return None
    if rsi_now is None:
        return None
    if use_ema200 and ema200 > 0:
        if st_dir > 0 and close <= ema200:
            return None
        if st_dir < 0 and close >= ema200:
            return None
    if adx_min > 0 and adx < adx_min:
        return None
    past_vals = [x for x in (rsi_window or []) if x is not None]
    if st_dir > 0:
        if not any(x < 50.0 for x in past_vals):
            return None
        if rsi_lo > 0 and past_vals and all(x < rsi_lo for x in past_vals):
            return None
        if rsi_prev is not None and rsi_prev >= 50.0:
            return None
        if rsi_now <= 50.0:
            return None
        action = "BUY"
    else:
        if not any(x > 50.0 for x in past_vals):
            return None
        if past_vals and all(x > 100.0 - rsi_lo for x in past_vals):
            return None
        if rsi_prev is not None and rsi_prev <= 50.0:
            return None
        if rsi_now >= 50.0:
            return None
        action = "SELL"
    if max_per_day > 0 and action_key:
        if day_counts.get(action_key, 0) >= max_per_day:
            return None
        day_counts[action_key] = day_counts.get(action_key, 0) + 1
    return action


def ema_adx_pullback_entry(
    ema8: float, ema21: float, ema50: float,
    adx: float, adx_min: float,
    close: float, open_: float, high: float, low: float,
    atr_price: float, touch_atr: float,
    day_counts: Dict[str, int], max_per_day: int,
) -> Optional[str]:
    """EMA+ADX geri-çekilme giriş kararı (saf fonksiyon — replay ile birebir).

    Kural seti (kullanıcı spesifikasyonu 2026-10-08):
      1) EMA dizilimi: 8>21>50 → yalnız LONG ; 8<21<50 → yalnız SHORT
      2) ADX(14) ≥ eşik (trend rejimi)
      3) geri çekilme: bar EMA21'i keser (low≤e21≤high) veya kapanış EMA21'e
         touch_atr×ATR mesafede
      4) onay: kapanış EMA21'in trend tarafında ve bar trend yönünde (BUY: c>o)
    Döner: "BUY" / "SELL" / None. Gün içi yön başına max_per_day limiti.
    """
    if atr_price <= 0 or ema8 <= 0 or ema21 <= 0 or ema50 <= 0 or close <= 0:
        return None
    if adx < adx_min:
        return None
    touched = (low <= ema21 <= high) or (abs(close - ema21) <= touch_atr * atr_price)
    if not touched:
        return None
    if ema8 > ema21 > ema50 and close > ema21 and close > open_:
        action = "BUY"
    elif ema8 < ema21 < ema50 and close < ema21 and close < open_:
        action = "SELL"
    else:
        return None
    if max_per_day > 0 and day_counts.get(action, 0) >= max_per_day:
        return None
    return action


def london_breakout_entry(
    close: float,
    box_hi: float, box_lo: float,
    hour_utc: int,
    box_end_utc: int, entry_end_utc: int,
    day_counts: Dict[str, int], max_per_day: int,
) -> Optional[str]:
    """London Breakout giriş kararı (saf fonksiyon — replay ile birebir).

    Kural (2026-10-08 replay kazananı): Asya kutusu (00:00→box_end UTC) high/low'unun
    DIŞINA tetik penceresinde (box_end→entry_end UTC) kapanış = kırılım yönünde giriş.
    Gün içi yön başına max_per_day limiti (replay spec: 1).
    Döner: "BUY" / "SELL" / None.
    """
    if box_hi <= 0 or box_lo <= 0 or box_hi <= box_lo or close <= 0:
        return None
    if hour_utc < box_end_utc or hour_utc >= entry_end_utc:
        return None
    if close > box_hi:
        action = "BUY"
    elif close < box_lo:
        action = "SELL"
    else:
        return None
    if max_per_day > 0 and day_counts.get(action, 0) >= max_per_day:
        return None
    return action


def sign_window_entry(
    sign_open: float, sign_close: float,
    minute_of_day: int,
    ent_start_min: int, ent_end_min: int,
    day_entered: bool,
) -> Optional[str]:
    """NY-açılışı sign-momentum giriş kararı (saf fonksiyon — replay ile birebir).

    Seeck (2026) Londra/NY-açılışı sign-momentumunun uyarlaması. Kural (2026-10-12
    replay kazananı, XAUUSD+US30): 13:30–14:00 UTC sign penceresinde son kapanış ilk
    kapanıştan YÜKSEKSE BUY, DÜŞÜKSE SELL; 14:00–14:30 UTC giriş penceresinde sembol
    başına günde TEK giriş. SL = 1.5×ATR, sabit TP yok (chandelier trail taşır).

    Pencere karşılaştırması DAKİKA tabanlıdır (saat-tamsayı yetersiz: 14:00→14:30
    aynı saat içinde; `14 >= 14` pencereyi boşaltırdı).

    Döner: "BUY" / "SELL" / None.
    """
    if sign_open <= 0 or sign_close <= 0:
        return None
    if minute_of_day < ent_start_min or minute_of_day >= ent_end_min:
        return None
    if day_entered:
        return None
    if sign_close > sign_open:
        return "BUY"
    if sign_close < sign_open:
        return "SELL"
    return None


# Risk bütçesinin sert tavanı (TEK KAYNAK). Lot normalizasyonu ve kripto/altın
# taban-lot kelepçesi bu aynı çarpanı kullanmak ZORUNDA — ikisi ayrışırsa bütçe
# sessizce aşılır (2026-10-14 olayı: kelepçe koşulsuz uygulanıp tavanı deliyordu).
RISK_HARD_MULT = 2.0


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
    hard_risk = float(risk_usd) * RISK_HARD_MULT
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


def floor_lot_respects_budget(floor_lot: float, sl_pips: float, pip_val: float, risk_usd: float) -> bool:
    """Kategori taban lotu (kripto/altın kelepçesi) bütçe sert tavanına sığıyor mu?

    Saf fonksiyon — 2026-10-14 kelepçe düzeltmesinin tek karar noktası.
    False dönerse kelepçe UYGULANMAZ ve işlem pas geçilir: broker taban lotu,
    ayarlanan bütçenin RISK_HARD_MULT katını bile aşıyorsa o pozisyonun riski
    bütçeyle yönetilemez (bakiyeyi büyütmek veya bütçeyi yükseltmek gerekir).
    """
    if floor_lot <= 0 or sl_pips <= 0 or pip_val <= 0 or risk_usd <= 0:
        return False
    return floor_lot * float(sl_pips) * float(pip_val) <= float(risk_usd) * RISK_HARD_MULT


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
        base_sl_calc = round(base_sl * mult, 1)
        eff_sl_pips = max(base_sl_calc, round(atr_pips * 1.5, 1)) if (atr_pips and atr_pips > 0) else base_sl_calc
        eff_tp_pips = max(round(base_tp * mult, 1), round(eff_sl_pips * 1.83, 1))
        eff_be_pips = max(25.0, round(eff_sl_pips * 0.75, 1))
        eff_trail_pips = max(round(base_trail * mult, 1), round(eff_sl_pips * 1.25, 1))

    elif len(clean_sym) == 6 and clean_sym[3:6] in ("CAD", "CHF", "GBP", "NZD", "AUD", "EUR"):
        quote = clean_sym[3:6]
        pip_size = 0.0001
        mult = 1.0
        digits = 5
        # Quote dövize göre yaklaşık 1 pip ($/lot) değeri:
        # GBP: 10 * GBPUSD (~13.3), CHF: 10 / USDCHF (~12.1), CAD: 10 / USDCAD (~7.1)
        # NZD: 10 * NZDUSD (~5.7), AUD: 10 * AUDUSD (~7.0), EUR: 10 * EURUSD (~11.3)
        pip_vals = {"GBP": 13.3, "CHF": 12.1, "CAD": 7.0, "NZD": 5.7, "AUD": 7.0, "EUR": 11.3}
        pip_val = pip_vals.get(quote, 10.0)
        base_sl_calc = round(base_sl * mult, 1)
        eff_sl_pips = max(base_sl_calc, round(atr_pips * 1.5, 1)) if (atr_pips and atr_pips > 0) else base_sl_calc
        eff_tp_pips = max(round(base_tp * mult, 1), round(eff_sl_pips * 1.83, 1))
        eff_be_pips = max(HARD_MIN_BREAKEVEN_PIPS, round(eff_sl_pips * 0.75, 1))
        eff_trail_pips = max(round(base_trail * mult, 1), round(eff_sl_pips * 1.25, 1))

    else:
        # Standart Forex (EURUSD, GBPUSD, AUDUSD, NZDUSD, USDCAD, USDCHF)
        pip_size = 0.0001        # 1 pip = 0.0001 (10 point)
        mult = 1.0
        digits = 5
        pip_val = 10.0
        base_sl_calc = round(base_sl * mult, 1)
        eff_sl_pips = max(base_sl_calc, round(atr_pips * 1.5, 1)) if (atr_pips and atr_pips > 0) else base_sl_calc
        eff_tp_pips = max(round(base_tp * mult, 1), round(eff_sl_pips * 1.83, 1))
        eff_be_pips = max(HARD_MIN_BREAKEVEN_PIPS, round(eff_sl_pips * 0.75, 1))
        eff_trail_pips = max(round(base_trail * mult, 1), round(eff_sl_pips * 1.25, 1))

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


def resolve_chandelier_atr(
    entry_atr_pips: Optional[float],
    current_atr_pips: Optional[float],
) -> float:
    """Chandelier trailing için kullanılacak ATR'yi seçer (saf fonksiyon — test edilebilir).

    Öncelik GİRİŞ ATR'sidir. Replay trailing'i girişte dondurulmuş ATR ile hesaplar
    (scripts/forex_replay_backtest.py:1828-1830) ve canlı davranışın kanıtlanmış olan bu
    olduğu için canlı da aynısını yapmalıdır. Eski canlı kod her tick CARİ ATR'yi
    kullanıyordu: ATR sıçradığında trailing mesafesi işlem ortasında genişliyor ve
    kazanılan pip geri veriliyordu (2026-10-13 canlı↔replay ayrık analizi).

    Giriş ATR'si yoksa (eski pozisyon / henüz yazılmamış alan) CARİ ATR'ye düşülür;
    ikisi de yoksa 0.0 döner ve çağıran chandelier dalını atlar (sabit pip trail'e düşer).
    """
    for v in (entry_atr_pips, current_atr_pips):
        try:
            f = float(v or 0.0)
        except (TypeError, ValueError):
            f = 0.0
        if f > 0:
            return f
    return 0.0


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
    # 1.5R tabanı korunur; spec TP'nin üstüne çıkılmaz (taban spec'i ezerse spec kazanır).
    eff_tp = min(float(tp_pips), max(min_tp, atr_tp))
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
    mfe_pips: float = 0.0,
    use_mfe_lock: bool = False,
    be_trigger_atr_mult: float = 0.0,
    be_trigger_r_mult: float = 0.0,
    be_trigger_atr_mult_gold: float = 0.0,
    be_trigger_atr_mult_crypto: float = 0.0,
) -> Optional[float]:
    """Volatilite (ATR) ve Risk (R) tabanlı başabaş (Breakeven) hedefi hesaplar.
    
    Tetiklenme kuralı:
      Kâr en az min_be_pips (ör. 0.4*SL veya 0.5*ATR veya eff_be_pips) seviyesine
      ulaşmalı ve net $1.00 minimum güvencesini sağlamalıdır.
      Böylece hesap bakiyesine göre erken boğulma (0.06R stop) engellenir.
    
    Kilitlenme kuralı:
      SL seviyesi giriş fiyatının ötesine taşınır (kârın lock_ratio kadarı veya min $1).
    """
    if pnl_pips <= 0 and not (use_mfe_lock and mfe_pips > 0):
        return None

    # 2026-10-14 (Kol A — canlı↔replay paritesi): replay `pnl_extreme_pips` (bar tepesi)
    # kullanır, canlı ise `pnl_pips` (poll anı). Aynı formül canlıda sistematik olarak
    # daha SIKI kilit üretiyordu. `use_mfe_lock` açıkken tetik ve kilit aynı tepeden okunur.
    ref_pips = max(pnl_pips, mfe_pips) if use_mfe_lock else pnl_pips
    if ref_pips <= 0:
        return None

    dollar_per_pip = max(0.0001, lots * pip_val)
    pips_for_1usd = max(0.5, round(1.0 / dollar_per_pip, 1))
    headroom = 4.0 if is_gold else (25.0 if is_crypto else 3.5)

    # Volatilite & Risk tabanlı tetik eşiği
    # 2026-10-12 DÜZELTME — BE tetiği artık BİRLEŞİM (veya), kümülatif taban (max) DEĞİL.
    #
    # Eski kod tabanları `max(...)` ile birleştiriyordu: BE kilidi bu tabanların EN
    # BÜYÜĞÜNÜ bekliyordu (0.4×SL veya 0.5×ATR — altında 25-37 pip). Sonuç: kâr +10..30
    # pip'e koşan işlem BE'ye hiç kilitlenmiyor, geri dönüşte TAM ATR stopuyla kapanıyordu.
    # Doküman metni ise zaten "veya" diyordu — kod ile niyet çelişiyordu.
    #
    # Kanıt (replay A/B, 4 bağımsız pencere; XAUUSD+BTCUSD, canlı-parite bayrakları,
    # gerçek spread): BE tetik formülü tek değişken olarak tarandı. İşaret-tutarlı sonuç —
    # `max` (eski, canlı) vs birleşim (yeni):
    #   10-08→10-13: +144.16/WR %63.1  →  +318.58/WR %75.7  (DD 148.9 → 58.7)
    #   09-07→10-07: -186.77/WR %61.0  → +3278.73/WR %75.7  (DD 787.0 → 106.7)
    #   08-08→09-07: +708.57/WR %59.4  → +4022.48/WR %75.3  (DD 380.5 → 110.1)
    #   07-15→08-15: +256.23/WR %57.0  → +1916.42/WR %80.5  (DD 600.0 → 97.3)
    # Dört pencerede de hem net hem WR hem maxDD lehine; alt tabanların hiçbiri tek başına
    # suçlu değil, suçlu `max` birleşiminin kendisi (izolasyon merdiveni: max_r, max_atr,
    # max_r_atr, min_r_atr ve dollar(=max($1,eff_be)) hepsi aynı çukura düşer, `usd`/`union`
    # hepsi iyi). Ayrıca CANLI veriyle bağımsız uyum: canlı WR %59.8, eski formülün replay
    # replikası %63.1; replay birleşim varyantı %75.7 — sapmayı kapatan tam bu katman.
    #
    # `be_r_mult` / `be_atr_mult` parametreleri imzada KALIR (çağıran/uyumluluk) ama tetikte
    # artık kullanılmaz: R/ATR tabanları BE'yi geciktirip zarar ürettiği ölçülmüştür.
    min_trigger_pips = pips_for_1usd + headroom
    if eff_be_pips > 0:
        # Birleşim: hangi eşiğe ÖNCE ulaşılırsa BE o zaman kilitlenir (replay varsayılanı).
        min_trigger_pips = min(min_trigger_pips, eff_be_pips)

    # 2026-10-14 (Kol B): ATR/R tabanı — tetiği GECİKTİRİR. 0 = kapalı (mevcut davranış).
    # Neden gerekli: tetik `$1 + headroom` olduğu için pip cinsinden `1/lot` ile ölçekleniyor;
    # XAU 0.05 lot'ta 6 pip = 0.15 ATR'ye düşüyor (ATR ~39.8 pip). UYARI: yalnız tetiği
    # geciktirmek 2026-10-12 replay'inde elendi — kilit tabanı birlikte büyümedikçe kâr etmiyor.
    if be_trigger_atr_mult > 0 and atr_pips > 0:
        min_trigger_pips = max(min_trigger_pips, be_trigger_atr_mult * atr_pips)
    if be_trigger_r_mult > 0 and sl_pips > 0:
        min_trigger_pips = max(min_trigger_pips, be_trigger_r_mult * sl_pips)

    # 2026-10-14 (kullanıcı: "BTC ve XAU'da erken tetiklenmesin") — AİLE-ÖZEL ATR TABANI.
    # Sorun tam olarak bu iki ailede: ATR büyük ama `pips_for_1usd + headroom` küçük olduğu için
    # `min()` tetiği tabana indiriyor (XAU 0.05 lot → 6 pip = 0.15 ATR; BTC 0.05 lot → 45 pip = 0.27 ATR).
    # FX/endekste aynı formül ~1 ATR'ye denk geldiği için o ailelere DOKUNULMAZ.
    if is_gold and be_trigger_atr_mult_gold > 0 and atr_pips > 0:
        min_trigger_pips = max(min_trigger_pips, be_trigger_atr_mult_gold * atr_pips)
    if is_crypto and be_trigger_atr_mult_crypto > 0 and atr_pips > 0:
        min_trigger_pips = max(min_trigger_pips, be_trigger_atr_mult_crypto * atr_pips)

    if ref_pips < min_trigger_pips:
        return None

    # Kilitlenecek pips: kârın belirli oranı, ama en az $1 kâr güvencesi
    lock_ratio = gold_be_lock_ratio if is_gold else 0.40
    locked_pips = max(pips_for_1usd, round(ref_pips * lock_ratio, 1))

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
    bar_times: Optional[List[int]] = None,
) -> Tuple[List[float], List[float], List[float], List[float]]:
    """Resample only complete 15-minute buckets for multi-timeframe analysis."""
    if bar_times is not None and len(bar_times) == len(closes):
        by_time = {int(ts): i for i, ts in enumerate(bar_times)}
        buckets = sorted({(int(ts) // 900) * 900 for ts in bar_times})
        o15, h15, l15, c15 = [], [], [], []
        for bucket in buckets:
            indices = [by_time.get(bucket + offset) for offset in (0, 300, 600)]
            if any(i is None for i in indices):
                continue
            i0, i1, i2 = indices
            o15.append(opens[i0])
            h15.append(max(highs[i0], highs[i1], highs[i2]))
            l15.append(min(lows[i0], lows[i1], lows[i2]))
            c15.append(closes[i2])
        return o15, h15, l15, c15

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
        # Tohum [:period] son elemanı (i-1) ikinci kez eklenmez; güncel gözlem i'dir.
        plus_w = plus_w - plus_w / period + float(plus_dm[i])
        minus_w = minus_w - minus_w / period + float(minus_dm[i])
        tr_w = tr_w - tr_w / period + float(tr[i])
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
    bar_times: Optional[List[int]] = None,
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
    ema8_series = _calc_ema(c, 8)
    ema9_series = _calc_ema(c, 9)
    ema21_series = _calc_ema(c, 21)
    ema50_series = _calc_ema(c, min(len(c), 50))

    ema8 = float(ema8_series[-1])
    ema9 = float(ema9_series[-1])
    ema21 = float(ema21_series[-1])
    ema50 = float(ema50_series[-1])
    last_price = float(c[-1])

    # 2. 15M HTF Trend Filter (Resampled from 5M bars)
    o15, h15, l15, c15 = _resample_5m_to_15m(opens, highs, lows, closes, bar_times)
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

    # S3 kendi RSI yolunu (`_s3_rsi_wilder`) kullanır. Buradaki tek elemanlı
    # RSI listesi dönüş sözlüğüne girmiyordu; ölü seri kaldırıldı.

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
        # Boğa trendinde veya nötrde sağlıklı dipten toparlanma
        if htf_trend == "BULLISH":
            bullish_pts += 20
        elif htf_trend != "BEARISH":
            bullish_pts += 10
    elif 60.0 < rsi <= 70.0:
        # Ayı trendinde veya nötrde tepe düzeltmesi; boğa trendinde momentum devamı
        if htf_trend == "BEARISH":
            bearish_pts += 20
        elif htf_trend == "BULLISH":
            bullish_pts += 15
        else:
            bearish_pts += 10
    elif rsi > 75.0:
        # Aşırı uzama: Asla trende karşı SELL puanı basma! Sadece boğa alımını dondur
        bullish_pts -= 25
    elif rsi < 25.0:
        # Aşırı çöküş: Asla trende karşı BUY puanı basma! Sadece ayı satışını dondur
        bearish_pts -= 25

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
            # Aşırı uzama — trend kovalamayı engelle (asla karşı yöne puan verme)
            bullish_pts -= 15
        elif cmo < -65.0:
            bearish_pts -= 15

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
            # Aşırı uzama — mean reversion riski (asla karşı yöne puan verme)
            bullish_pts -= 10
        elif cci < -200.0:
            bearish_pts -= 10

        if rsi >= 50.0 and cmo > 0.0 and cci > 0.0:
            bullish_pts += 8
        elif rsi <= 50.0 and cmo < 0.0 and cci < 0.0:
            bearish_pts += 8

    # MTF Alignment Verdict & Net Göreli Skorlama
    ltf_bullish = (ema9 > ema21 and last_price >= ema21 * 0.999)
    ltf_bearish = (ema9 < ema21 and last_price <= ema21 * 1.001)

    net_bullish = bullish_pts - bearish_pts
    net_bearish = bearish_pts - bullish_pts

    # 15M Trendi NEUTRAL iken asla yönsüz piyasada işlem açılmaz; net puan farkı en az 10 olmalıdır
    if htf_trend == "BULLISH" and ltf_bullish and net_bullish >= 10:
        trend = "BULLISH"
        action = "BUY" if rsi <= 76.0 else "HOLD"
        score = round(min(96.0, max(60.0, 50.0 + (net_bullish * 0.46))), 1)
        macd_verdict = f"AL (MTF Boğa Uyumu | 15M: {htf_trend} + 5M Net: +{net_bullish})"
    elif htf_trend == "BEARISH" and ltf_bearish and net_bearish >= 10:
        trend = "BEARISH"
        action = "SELL" if rsi >= 24.0 else "HOLD"
        score = round(min(96.0, max(60.0, 50.0 + (net_bearish * 0.46))), 1)
        macd_verdict = f"SAT (MTF Ayı Uyumu | 15M: {htf_trend} + 5M Net: +{net_bearish})"
    else:
        # Choppy, conflicting timeframes, or indecisive market
        trend = "NEUTRAL"
        action = "HOLD"
        score = round(max(50.0, min(58.0, 50.0 + abs(bullish_pts - bearish_pts) * 0.1)), 1)
        macd_verdict = f"NÖTR (MTF/Net Güç Yetersiz | 15M: {htf_trend}, Net Boğa: {net_bullish:+d} - Beklemede)"

    # Evrensel SuperTrend Yön Koruması: ST yönü sinyal yönüyle çelişiyorsa işlem kilitlenir
    direction_guard_reason = ""
    if action in ("BUY", "SELL"):
        expected_st = 1 if action == "BUY" else -1
        if st_dir != 0 and st_dir != expected_st:
            action = "HOLD"
            direction_guard_reason = f"SuperTrend kalkanı: 5M SuperTrend karşı yönde ({'BOĞA' if st_dir > 0 else 'AYI'})"
            macd_verdict = direction_guard_reason

    return {
        "price": last_price,
        "high": float(np.max(h)),
        "low": float(np.min(l)),
        "change_pct": change_pct,
        "ema8": ema8,
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
        # Son barın OHLC'si (EMA+ADX geri-çekilme giriş modu — 2026-10-08): dokunma
        # (EMA21'i kesme) ve onay (bar trend yönünde kapanış) bu bardan okunur.
        "open_last": float(opens[-1]) if opens else last_price,
        "high_last": float(highs[-1]) if highs else float(np.max(h)),
        "low_last": float(lows[-1]) if lows else float(np.min(l)),
        # Donchian(20) orta hat + önceki barın orta hattı (donchian_adx giriş modu — 2026-10-07)
        "donch_mid": round((max(highs[-20:]) + min(lows[-20:])) / 2.0, 6) if len(highs) >= 20 else None,
        "donch_mid_prev": round((max(highs[-21:-1]) + min(lows[-21:-1])) / 2.0, 6) if len(highs) >= 21 else None,
        "trend": trend,
        "action": action,
        "direction_guard_reason": direction_guard_reason,
        "score": score,
        "htf_trend": htf_trend,
        "signal_bar_time": int(bar_times[-1]) if bar_times and len(bar_times) == len(closes) else None,
        "signal_bar_confirmed": bool(bar_times and len(bar_times) == len(closes)),
        "updated_at": time.time(),
    }


_LAST_FETCH_FAIL_LOG: Dict[str, float] = {}


def _sync_fetch_candles_for_symbol(fx_sym: str, yf_sym: str) -> Optional[Dict[str, Any]]:
    """Emekli. Mum ve gösterge artık MT5 tik kovalarından gelir; HTTP yok."""
    del fx_sym, yf_sym
    return None


def _sync_fetch_all_technical_data() -> Dict[str, Dict[str, Any]]:
    """Emekli. Skor yolu `_rebuild_tech_from_ticks` kullanır."""
    return {}


def _sync_fetch_live_rates() -> Dict[str, float]:
    """Emekli. Canlı fiyat yalnız MT5 tikidir; Frankfurter çağrılmaz."""
    return {}


def _rebuild_tech_from_ticks(sym: str) -> None:
    """Skor/RSI/ADX/MACD kapanmış MT5 5m mumundan. Mum kısaysa tik kovası yedek."""
    app = canonical_symbol(sym)
    bars = _closed_broker_bars(app, "5m", 300)
    source = "mt5_candle"
    if len(bars) < _MIN_CLOSED_BARS_5M:
        bars = _closed_tick_bars(app, 300)
        source = "mt5_tick"
        _verify_tick_bars_against_bridge(app, "5m", bars)
    if len(bars) < _MIN_CLOSED_BARS_5M:
        _TECHNICAL_CACHE.pop(app, None)
        return
    opens = [float(b["open"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    closes = [float(b["close"]) for b in bars]
    times = [int(b["time"]) for b in bars]
    tech = _compute_technical_indicators(closes, highs, lows, opens, app, bar_times=times)
    if not tech:
        _TECHNICAL_CACHE.pop(app, None)
        return
    tick_ts = float(_PRICE_TS.get(app, 0.0) or 0.0)
    tech["updated_at"] = tick_ts
    tech["source"] = source
    tech["bar_gap"] = _bars_have_gap(bars, 300)
    _TECHNICAL_CACHE[app] = tech
    _CLOSES_CACHE[app] = closes


async def _refresh_live_rates_if_needed():
    """Göstergeyi MT5 tik kovalarından tazeler. Yahoo ve Frankfurter çağrılmaz."""
    global _LAST_LIVE_FETCH_TIME, _LAST_TECH_FETCH_TIME
    now = time.time()
    if now - _LAST_TECH_FETCH_TIME < 2.0 and _TECHNICAL_CACHE:
        return
    _LAST_TECH_FETCH_TIME = now
    _LAST_LIVE_FETCH_TIME = now
    try:
        for item in FOREX_SYMBOLS:
            _rebuild_tech_from_ticks(item["symbol"])
        _rebuild_tech_from_ticks("DXY")
        expired = [s for s in list(_TECHNICAL_CACHE) if _tech_is_stale(s, now)]
        for s in expired:
            _TECHNICAL_CACHE.pop(s, None)
        _FX_CORR.maybe_refresh(_CLOSES_CACHE)
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
            tech = None
        tick_ts = float(_PRICE_TS.get(sym, 0.0) or 0.0)
        source = _PRICE_SOURCE.get(sym, "yok")
        price_placeholder = source != "mt5_tick" or tick_ts <= 0
        if price_placeholder:
            tech = None
            live_p = float(item["default_price"])
            source = "default"
            tick_ts = 0.0
        else:
            live_p = float(_LIVE_PRICES_CACHE.get(sym) or 0.0)
            if live_p <= 0:
                tech = None
                live_p = float(item["default_price"])
                source = "default"
                price_placeholder = True
                tick_ts = 0.0
        bars5 = _closed_tick_bars(sym, 300)
        bar_gap = bool(tech.get("bar_gap")) if tech else (_bars_have_gap(bars5, 300) if bars5 else False)
        tick_mismatch = sym in _TICK_MISMATCH
        spread_known = (not price_placeholder) and sym in _LIVE_SPREAD_PIPS
        spread_pips = float(_LIVE_SPREAD_PIPS[sym]) if spread_known else 0.0
        spread_val = spread_pips * pip if spread_known else 0.0
        age_sec = (now - tick_ts) if tick_ts > 0 else None

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
            # MACD histogramı (ham, fiyat biriminde). Kokpitteki "MACD Momentum"
            # barı bunu kullanır; ATR'ye bölünerek ölçeksiz hale getirilir —
            # XAU ($) ile BTC ($) histogram büyüklükleri kıyaslanamaz.
            macd_hist_val = float(tech.get("macd_hist", 0.0) or 0.0)
            adx = tech.get("adx", 25.0)
            st_dir = int(tech.get("supertrend_dir", 0))
            change_pct = tech["change_pct"]
            high_p = round(max(tech["high"], ask_p), digits)
            low_p = round(min(tech["low"], bid_p), digits)
            atr_val = tech["atr"]
            direction_guard_reason = str(tech.get("direction_guard_reason", ""))
            signal_bar_time = tech.get("signal_bar_time")
            signal_bar_confirmed = bool(tech.get("signal_bar_confirmed", False))
        else:
            score = 50.0
            trend = "NEUTRAL"
            action = "HOLD"
            rsi = 50.0
            macd_verdict = "NÖTR (Veri Bekleniyor)"
            cmo = 0.0
            cci = 0.0
            macd_hist_val = 0.0
            adx = 0.0
            st_dir = 0
            change_pct = 0.0
            high_p = round(live_p * 1.002, digits)
            low_p = round(live_p * 0.998, digits)
            atr_val = 15.0 * pip
            direction_guard_reason = ""
            signal_bar_time = None
            signal_bar_confirmed = False

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
            "macd_hist": macd_hist_val,
            "cmo": cmo,
            "cci": cci,
            "adx": adx,
            "supertrend_dir": st_dir,
            "direction_guard_reason": direction_guard_reason,
            "signal_bar_time": signal_bar_time,
            "signal_bar_confirmed": signal_bar_confirmed,
            "atr": atr_val,
            "volatility": "HIGH" if ("XAU" in sym or "GOLD" in sym) else "NORMAL",
            "source": "mt5_tick" if source == "mt5_tick" else source,
            "age_sec": None if age_sec is None else round(age_sec, 1),
            "spread_known": spread_known,
            "price_placeholder": price_placeholder,
            "bar_gap": bool(bar_gap or (tech or {}).get("bar_gap")),
            "tick_mismatch": tick_mismatch,
            "updated_at": tick_ts,
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


def _public_ticker_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Katalog varsayılan fiyatı piyasa verisi gibi gösterme."""
    out = dict(row)
    if out.get("source") != "mt5_tick" or out.get("price_placeholder"):
        out["bid"] = None
        out["ask"] = None
        out["price"] = None
        out["high"] = None
        out["low"] = None
        out["source"] = "yok"
        out["error"] = "MT5 tik yok"
    return out


@router.get("/tickers")
async def get_forex_tickers(category: Optional[str] = None):
    """Canlı kotasyon. Fiyat yalnız MT5 tikinden gelir."""
    ticks = await _generate_realistic_ticks()
    results = [_public_ticker_row(t) for t in ticks.values()]
    if category:
        results = [t for t in results if t["category"] == category]
    return {
        "tickers": results,
        "sessions": _get_market_sessions(),
        "timestamp": time.time(),
        "source": "mt5_tick",
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
# Köprüye tek turda istenebilecek azami (sembol, periyot) çifti. 2026-10-14:
# 12 → 24 → 28 (DXY + tüm 14 radar sembolü + S3/Squeeze M15 + açık grafik).
_MT5_WATCH_MAX = 64


def _note_forex_viewed(symbol: str, interval: str) -> None:
    """Panel bu (sembol, periyot) mumlarını istedi → köprüye izletilecekler listesine ekle."""
    sym = str(symbol or "").replace("/", "").replace("_", "").replace("-", "").strip().upper()
    if not sym or not interval:
        return
    _FOREX_VIEWED[(sym, str(interval).strip().lower())] = time.time()


def _get_forex_watch() -> List[Dict[str, str]]:
    """Son `_FOREX_VIEWED_TTL` içinde bakılan çiftler (bayat olanlar budanır).

    Sıra ÖNEMLİ (2026-10-14): panelin ŞU AN baktığı çiftler EN ÖNE konur (kırpma
    tavana takılırsa motor çiftleri kesilir, panel grafiği ASLA açlığa düşmez).
    S3/squeeze_kc motor çiftleri ondan sonra KALICI eklenir: bu motorlar broker
    mumlarıyla sinyal üretir ve panel kapalıyken de çekilmeleri gerekir.
    """
    out: List[Dict[str, str]] = []
    seen: set = set()
    now = time.time()
    # 1) Panelin baktığı çiftler (en taze önce): kullanıcı grafiği açtığı anda
    #    köprü o çifti çekmeye başlar → grafik broker kotasyonuyla canlı akar.
    viewed: List[Tuple[Tuple[str, str], float]] = []
    for (sym, tf), ts in list(_FOREX_VIEWED.items()):
        if now - ts > _FOREX_VIEWED_TTL:
            _FOREX_VIEWED.pop((sym, tf), None)
            continue
        viewed.append(((sym, tf), ts))
    viewed.sort(key=lambda kv: -kv[1])
    for (sym, tf), _ts in viewed:
        if (sym, tf) not in seen:
            seen.add((sym, tf))
            out.append({"symbol": sym, "interval": tf})
    # 2) Karar fonksiyonlarının 5m mumları. Radar, Donchian, EMA, London ve DXY
    #    rejim filtresi bu seriyi okur; tik kovasının dolması beklenmez.
    decision_5m = set(RADAR_SCAN_SYMBOLS) | {"DXY"}
    if _AUTO_SETTINGS.lb_enabled:
        decision_5m.update(str(s).upper() for s in (_AUTO_SETTINGS.lb_symbols or []))
    if _AUTO_SETTINGS.ema_adx_enabled:
        decision_5m.update(str(s).upper() for s in (_AUTO_SETTINGS.ema_adx_symbols or []))
    decision_5m.update(str(s).upper() for s in (_AUTO_SETTINGS.mode_symbols or []))
    for sym in sorted(s for s in decision_5m if s):
        key = (sym, "5m")
        if key not in seen:
            seen.add(key)
            out.append({"symbol": sym, "interval": "5m"})
    # 3) Motorun kalıcı çiftleri (panel kapalıyken de sinyal üretimi için).
    if _AUTO_SETTINGS.s3_enabled:
        for sym in list(_AUTO_SETTINGS.s3_symbols_5m) + list(_AUTO_SETTINGS.s3_symbols_15m):
            s = str(sym).upper()
            for tf in ("5m", "15m"):
                key = (s, tf)
                if key not in seen:
                    seen.add(key)
                    out.append({"symbol": s, "interval": tf})
    if _AUTO_SETTINGS.squeeze_kc_enabled:
        # Keltner Squeeze (M15) da broker mumlarıyla sinyal üretir → panel kapalıyken
        # köprünün bu çiftlerin M15 mumlarını çekmesi gerekir (S3 ile aynı gerekçe).
        for sym in list(_AUTO_SETTINGS.squeeze_kc_symbols or []):
            key = (str(sym).upper(), "15m")
            if key not in seen:
                seen.add(key)
                out.append({"symbol": key[0], "interval": key[1]})
    return out[:_MT5_WATCH_MAX]


def _s3_bars_for(sym: str, interval: str, limit: int = 260) -> Optional[List[Dict[str, Any]]]:
    """London, Squeeze ve S3 barları. Önce kapanmış MT5 mumu, yoksa tik kovası."""
    bucket = 900 if str(interval) in ("15m", "15") else 300
    iv = "15m" if bucket == 900 else "5m"
    min_bars = _MIN_CLOSED_BARS_5M if bucket == 300 else 20
    bars = _closed_broker_bars(sym, iv, bucket)
    if len(bars) < min_bars:
        bars = _closed_tick_bars(sym, bucket)
        _verify_tick_bars_against_bridge(sym, iv, bars)
    if len(bars) < min_bars:
        return None
    return bars[-limit:]


def _s3_resample_15m(bars5: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """5m barları 15m'e birleştirir (replay 15m cache'i ile aynı paradigma:
    3×5m → open ilk, high max, low min, close son)."""
    out: List[Dict[str, Any]] = []
    for i in range(0, len(bars5) - 2, 3):
        chunk = bars5[i:i + 3]
        out.append({
            "time": int(chunk[0]["time"]),
            "open": float(chunk[0]["open"]),
            "high": max(float(b["high"]) for b in chunk),
            "low": min(float(b["low"]) for b in chunk),
            "close": float(chunk[-1]["close"]),
        })
    return out


def _s3_tech_for(sym: str, tf: str) -> Optional[Dict[str, Any]]:
    """S3 gösterge setini hesaplar: ST yön serisi (son kapanmış bar), RSI serisi,
    EMA200, ADX, ATR. Barlar kapanmış barlardır; son bar (formasyon halindeki)
    göstergelere DAHİL EDİLMEZ (look-ahead yok — replay `ci-1` referansı)."""
    bars = _s3_bars_for(sym, tf)
    if not bars or len(bars) < 215:
        return None
    # Tik kovası açık mumu zaten dışarıda bırakır. Son eleman son kapanmış bardır.
    closed = bars
    closes = [float(b["close"]) for b in closed]
    highs = [float(b["high"]) for b in closed]
    lows = [float(b["low"]) for b in closed]
    rsi_s = _s3_rsi_wilder(closes, 14)
    ema_s = _s3_ema_series(closes, 200)
    atr_s = _s3_atr_series(closed, 14)
    st_s = _s3_st_dir_series(closed, 10, 3.0)
    adx_val = _compute_adx(highs, lows, closes, 14)
    return {
        "st_dir": int(st_s[-1]),
        "close": closes[-1],
        "ema200": float(ema_s[-1]),
        "rsi_now": rsi_s[-1],
        "rsi_prev": rsi_s[-2] if len(rsi_s) >= 2 else None,
        "rsi_window": rsi_s[-7:-1],
        "adx": float(adx_val),
        "atr": float(atr_s[-1]),
        "bars": len(closed),
        "bar_time": int(closed[-1].get("time", 0)),
        "updated_at": float(_PRICE_TS.get(canonical_symbol(sym), 0.0) or 0.0),
    }


def _refresh_s3_state(ticks: Dict[str, Dict[str, Any]]) -> None:
    """S3 sembollerinin gösterge setlerini tazeler (motor döngüsünden çağrılır).

    TF başına tek hesap; aday üretimi `_S3_STATE`'i okur. Yahoo düşüşü köprü
    mumlarını korur; iki kaynak da yoksa sembol bu tur sessizce atlanır.
    """
    for tf, syms in (("5m", _AUTO_SETTINGS.s3_symbols_5m), ("15m", _AUTO_SETTINGS.s3_symbols_15m)):
        for sym in {s.upper() for s in (syms or [])}:
            tech = _s3_tech_for(sym, tf)
            if tech:
                _S3_STATE[f"{sym}|{tf}"] = tech


def _refresh_squeeze_kc_state(ticks: Dict[str, Dict[str, Any]]) -> None:
    """Keltner Squeeze (M15) sembollerinin gösterge setlerini tazeler.

    Sembol başına tek hesap; aday üretimi `_SQUEEZE_KC_STATE[sym]`'i okur. Bar
    kaynağı S3 ile ortak (köprü broker mumları, Yahoo fallback); iki kaynak da
    yoksa sembol bu tur sessizce atlanır.
    """
    for sym in {s.upper() for s in (_AUTO_SETTINGS.squeeze_kc_symbols or [])}:
        tech = _squeeze_kc_tech_for(sym)
        if tech:
            _SQUEEZE_KC_STATE[sym] = tech


def _fetch_mt5_candles(clean_sym: str, interval: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    """Köprüden taze gelen broker mumlarını döndür (yoksa/bayatsa `None`)."""
    sym_key = canonical_symbol(clean_sym)
    tf_key = str(interval or "").strip().lower()
    entry = _MT5_CANDLES_CACHE.get(f"{sym_key}|{tf_key}") or _MT5_CANDLES_CACHE.get(f"{sym_key}|{tf_key.upper()}")
    if not entry:
        return None
    ts, bars = entry
    if not bars or (time.time() - ts) > _MT5_CANDLES_TTL:
        return None
    bucket_map = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900,
        "30m": 1800, "1h": 3600, "60m": 3600, "4h": 14400, "240m": 14400,
        "1d": 86400, "d": 86400,
    }
    bucket_sec = bucket_map.get(tf_key, 300)
    now_bucket = (int(time.time()) // bucket_sec) * bucket_sec
    utc_off = _broker_bars_utc_offset(bars, now_bucket, bucket_sec)
    if utc_off:
        shifted = []
        for b in bars[-limit:]:
            bc = dict(b)
            bc["time"] = int(b["time"]) - utc_off
            shifted.append(bc)
        return shifted
    return bars[-limit:]


def _resample_bars(bars: List[Dict[str, Any]], bucket_sec: int) -> List[Dict[str, Any]]:
    """Barları `bucket_sec` saniyelik kovalara birleştirir (open ilk, high max,
    low min, close son, volume toplam). Zaman damgası kovanın başıdır.

    2026-10-14: "3m" için Yahoo 1m → 180 sn; "4h" için 60m → 14400 sn. Yahoo M3
    barı vermediği ve anahtarı `interval_map`'e eklemek tek başına YETMEDİĞİ için
    bu yardımcı ayrıldı (eskiden 4h mantığı gövdeye gömülüydü)."""
    groups: Dict[int, List[Dict[str, Any]]] = {}
    for b in bars:
        bucket = (int(b["time"]) // bucket_sec) * bucket_sec
        groups.setdefault(bucket, []).append(b)
    out: List[Dict[str, Any]] = []
    for bucket in sorted(groups.keys()):
        gbars = groups[bucket]
        out.append({
            "time": bucket,
            "open": gbars[0]["open"],
            "high": max(x["high"] for x in gbars),
            "low": min(x["low"] for x in gbars),
            "close": gbars[-1]["close"],
            "volume": sum(x.get("volume", 0) for x in gbars),
        })
    return out



# Grafik periyodu → saniye. 1m/5m/15m doğrudan tik kovasıdır.
# 3m, 1m kovalarından; 30m ve üstü 5m kovalarından tam kova birleştirilir.
_KLINE_NATIVE_SEC = {"1m": 60, "5m": 300, "15m": 900}
_KLINE_FROM_1M = {"3m": 180}
_KLINE_FROM_5M = {"30m": 1800, "1h": 3600, "60m": 3600, "4h": 14400, "240m": 14400, "1d": 86400, "D": 86400}


def _clean_forex_chart_symbol(symbol: str) -> str:
    raw = str(symbol or "").replace("/", "").replace("_", "").replace("-", "").strip().upper()
    alias = {
        "GOLD": "XAUUSD",
        "ALTIN": "XAUUSD",
        "SILVER": "XAGUSD",
        "GUMUS": "XAGUSD",
        "BTC": "BTCUSD",
        "ETH": "ETHUSD",
    }
    return canonical_symbol(alias.get(raw, raw))


def _closed_full_buckets(bars: List[Dict[str, Any]], bucket_sec: int, source_sec: int) -> List[Dict[str, Any]]:
    """Kaynak mumları tam kova dolunca birleştirir. Eksik kova kapanmış sayılmaz."""
    need = max(1, int(bucket_sec) // int(source_sec))
    grouped = _resample_bars(bars, bucket_sec)
    # _resample_bars kısmi kovayı da yazar. Tam dolu olanları kaynak sayıdan seç.
    by_time: Dict[int, List[Dict[str, Any]]] = {}
    for b in bars:
        start = (int(b["time"]) // bucket_sec) * bucket_sec
        by_time.setdefault(start, []).append(b)
    full_times = {t for t, group in by_time.items() if len(group) >= need}
    return [b for b in grouped if int(b["time"]) in full_times]


def _forex_klines_from_ticks(
    symbol: str, interval: str = "5m", limit: int = 250,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Mum serisi yalnız MT5 tik kovalarından. Kısa geçmiş boş seri ve hata döner."""
    clean = _clean_forex_chart_symbol(symbol)
    iv = str(interval or "5m")
    if iv in _KLINE_NATIVE_SEC:
        source_sec = _KLINE_NATIVE_SEC[iv]
        closed = _closed_tick_bars(clean, source_sec)
        min_bars = 20 if source_sec == 900 else _MIN_CLOSED_BARS_5M
    elif iv in _KLINE_FROM_1M:
        source_sec = 60
        raw = _closed_tick_bars(clean, source_sec)
        min_bars = _MIN_CLOSED_BARS_5M
        closed = _closed_full_buckets(raw, _KLINE_FROM_1M[iv], source_sec) if len(raw) >= min_bars else []
    elif iv in _KLINE_FROM_5M:
        source_sec = 300
        raw = _closed_tick_bars(clean, source_sec)
        min_bars = _MIN_CLOSED_BARS_5M
        closed = _closed_full_buckets(raw, _KLINE_FROM_5M[iv], source_sec) if len(raw) >= min_bars else []
    else:
        return [], "Periyot tik kovasında yok"

    has_tick = _PRICE_SOURCE.get(clean) == "mt5_tick"
    if iv in _KLINE_NATIVE_SEC and len(closed) < min_bars:
        if not closed and not has_tick:
            return [], "MT5 tik yok"
        return [], "MT5 tik geçmişi kısa"
    if iv not in _KLINE_NATIVE_SEC and not closed:
        raw_there = bool(_closed_tick_bars(clean, source_sec))
        if not raw_there and not has_tick:
            return [], "MT5 tik yok"
        return [], "MT5 tik geçmişi kısa"

    bars = [{
        "time": int(b["time"]),
        "open": float(b["open"]),
        "high": float(b["high"]),
        "low": float(b["low"]),
        "close": float(b["close"]),
        "volume": float(b.get("volume") or 0.0),
    } for b in closed]
    if iv in _KLINE_NATIVE_SEC:
        forming = _OPEN_TICK_BUCKET.get((clean, source_sec))
        if forming:
            bars.append({
                "time": int(forming["time"]),
                "open": float(forming["open"]),
                "high": float(forming["high"]),
                "low": float(forming["low"]),
                "close": float(forming["close"]),
                "volume": 0.0,
            })
    return bars[-limit:], None


def _fetch_forex_klines(symbol: str, interval: str = "5m", limit: int = 250) -> List[Dict[str, Any]]:
    """Grafik mumları. Önce MT5 broker mum önbelleği (varsa daha derin geçmiş), yoksa tik kovası."""
    _note_forex_viewed(symbol, interval)
    clean_sym = _clean_forex_chart_symbol(symbol)
    bars, err = _forex_klines_from_ticks(symbol, interval, limit)
    broker = _fetch_mt5_candles(clean_sym, interval, limit)
    if broker and (err or len(broker) > len(bars)):
        return broker
    return bars


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
    clean_sym = _clean_forex_chart_symbol(symbol)
    bars, err = _forex_klines_from_ticks(symbol, interval, limit)
    source = "mt5_tick" if bars else "yok"
    # Tik kovası sunucu açılınca birikir; 5m için 30 kapanmış bar ~2,5 saat sürer.
    # Köprü aynı anda MT5 geçmiş mumunu (copy_rates) gönderir. Broker mum serisi
    # tik kovasından daha derinse (veya tik geçmişi kısaysa) grafik onu gösterir.
    broker = _fetch_mt5_candles(clean_sym, interval, limit)
    if broker and (err or len(broker) > len(bars)):
        bars = broker
        err = None
        source = "mt5_candle"
    elif err == "MT5 tik yok":
        err = "MT5 geçmişi bekleniyor"
    meta = next((s for s in FOREX_SYMBOLS if s["symbol"] == clean_sym), None)
    live = _LIVE_PRICES_CACHE.get(clean_sym) if _PRICE_SOURCE.get(clean_sym) == "mt5_tick" else None
    current_price = float(live) if live else (bars[-1]["close"] if bars else None)
    return {
        "symbol": clean_sym,
        "interval": interval,
        "count": len(bars),
        "candles": bars,
        "current_price": current_price,
        "source": source if bars or live else "yok",
        "error": err,
        "meta": meta,
    }


def _evaluate_signal_gate(
    sym: str,
    cand: Dict[str, Any],
    current_utc_hour: int,
    dxy_regime: Optional[Dict[str, Any]],
    has_open_position: bool = False,
    news_bias: Optional[Dict[str, Any]] = None,
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

    veto = None
    if _AUTO_SETTINGS.dxy_filter_enabled:
        veto = dxy_entry_veto(sym, direction, dxy_regime)
        if veto in ("dxy_conflict", "dxy_no_data"):
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
    if cand.get("spread_known") is False or cand.get("spread_pips", 99.0) > effective_max_spread:
        reasons.append("spread")

    weak_bump = 5.0 if veto == "dxy_strict_neutral" else 0.0
    req_score = required_entry_score(sym, weak_bump)
    if cand.get("score", 0.0) < req_score:
        reasons.append("score")

    if _AUTO_SETTINGS.adx_filter_enabled and float(cand.get("adx", 0.0)) < _AUTO_SETTINGS.adx_min:
        reasons.append("adx")

    st_dir = int(cand.get("supertrend_dir", 0))
    if supertrend_blocks_entry(cand.get("entry_source", ""), direction, st_dir):
        reasons.append("supertrend")

    data_reason = entry_data_blocked(cand)
    if data_reason and data_reason not in reasons:
        reasons.append(data_reason)

    if news_bias and _AUTO_SETTINGS.news_bias_block_opposing:
        nb_dir = int(news_bias.get("dir", 0) or 0)
        if nb_dir != 0:
            dir_sign = 1 if direction == "BUY" else (-1 if direction == "SELL" else 0)
            if dir_sign != 0 and dir_sign == -nb_dir:
                reasons.append("news_opposing")

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
    "classic_scope": "Klasik radar bu sembolde kapalı (yalnız XAU, BTC, US30, AUD, AUDCAD)",
    "news_opposing": "Ekonomik takvim verisine zıt yön (30 dk koruma aktif)",
}
# Piyasa kalitesi engelleri. `open_position` BURADA DEĞİL: o piyasanın değil,
# mevcut durumun sonucu. Ayrım kritik — kullanıcı "sinyal yok"u "piyasa kötü"
# sanmasın, "bu parite şu an giriş kalitesinde değil" ile "zaten pozisyonum
# var"ı ayırt edebilsin.
_MARKET_BLOCKERS = frozenset({
    "direction", "score", "spread", "adx", "supertrend",
    "dxy", "major_session", "major_min_atr", "correlation",
    "veri", "bayat", "bar_gap", "news_opposing",
})

# PERFORMANS (2026-10-08): /radar yanıtı için kısa TTL'li önbellek. Birden çok
# sayfa/modal aynı ucu 1.5–4 sn aralıklarla dövdüğü için her istek tam tarama
# yapıyordu. (now_ts, response) ikilisi tutulur; TTL taze ise aynı yanıt döner.
_RADAR_CACHE: Optional[Tuple[float, Dict[str, Any]]] = None
_RADAR_CACHE_TTL = 2.0

# PERFORMANS (2026-10-08): /auto-paper/status yanıtı için 1 sn TTL'li önbellek
# (aşağıda kullanılır; tanım, /radar önbelleğiyle aynı blokta tutulur).
_STATUS_CACHE: Optional[Tuple[float, Dict[str, Any]]] = None
_STATUS_CACHE_TTL = 1.0


@router.get("/radar")
async def get_forex_radar(use_cache: bool = True):
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

    Tarama evreni (RADAR_SCAN_SYMBOLS): 2026-10-08 L30 Radar replay'i (33 sembol,
    klasik profil PF 0.99) sembol bazına indirildiğinde yalnız 7 sembol pozitif
    çıktı (XAUUSD +$1374, US30 +$501, BTCUSD +$165, GBPUSD +$43, AUDUSD +$26,
    NZDJPY +$26, AUDNZD +$10); 24+ FX majör/kros sistematik negatifti. Bu yüzden
    radar yalnız kanıtlı evrende döner.

    PERFORMANS (2026-10-08): 2 sn TTL'li sunucu içi önbellek. Ana sayfa, radar
    sayfası, BTC+Altın, MetaMobil ve uygulama içi radar modalı aynı ucu
    farklı aralıklarla dövüyordu; her istek tam tarama + kapı değerlendirmesi
    yapıyordu. Önbellek 2 sn'den taze ise aynısı döner. Otonom motor döngüsü
    `use_cache=False` ile çağırır — işlem kararı daima taze veriyle alınır.
    """
    # --- PERFORMANS: kısa TTL'li yanıt önbelleği ---
    now_ts = time.time()
    global _RADAR_CACHE
    if use_cache:
        cached = _RADAR_CACHE
        if cached is not None and now_ts - cached[0] < _RADAR_CACHE_TTL:
            return cached[1]

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

    # Ekonomik takvim 30 dk yön kanıtı (haber besleyicisi)
    _nb_mod = None
    try:
        from app.forex_news import get_forex_news
        from app import forex_news_bias as _bias_engine
        _cal_events = await get_forex_news()
        _bias_engine.refresh_biases(_cal_events, now_ts, window_sec=1800.0)
        _nb_mod = _bias_engine
    except Exception:
        _nb_mod = None

    candidates = []
    for sym, t in ticks.items():
        sym_u = sym.upper()
        if sym_u not in RADAR_SCAN_SYMBOLS:
            continue
        score = t.get("score", 45.0)
        trend = t.get("trend", "NEUTRAL")
        action = t.get("action", "BUY" if trend == "BULLISH" else ("SELL" if trend == "BEARISH" else "HOLD"))
        spread = t.get("spread_pips", 1.5)
        atr_pips = round(t.get("atr", 0.001) / t["pip_size"], 1) if t.get("pip_size", 0) > 0 else 15.0
        st_dir = int(t.get("supertrend_dir", 0))

        # Haber yönü desteği ve zıt yön uyarısı (30 dk besleyici)
        news_bias_slot = _nb_mod.bias_for(sym_u) if _nb_mod else {"dir": 0, "hits": 0, "events": []}
        nb_dir = int(news_bias_slot.get("dir", 0) or 0)
        news_info = {
            "has_active_news": False,
            "alignment": "NEUTRAL",
            "badge": "",
            "remaining_min": 0.0,
            "event_title": "",
            "events_count": int(news_bias_slot.get("hits", 0) or 0),
        }
        if nb_dir != 0 and action in ("BUY", "SELL"):
            ev0 = (news_bias_slot.get("events") or [{}])[0]
            ev_title = ev0.get("title") or "Ekonomik Veri"
            rem_min = float(news_bias_slot.get("remaining_min", 0.0) or (ev0.get("remaining_min", 0.0) or 0.0))
            act_dir = 1 if action == "BUY" else -1
            if act_dir == nb_dir:
                score = min(98.0, round(score + 10.0, 1))
                news_info = {
                    "has_active_news": True,
                    "alignment": "SUPPORTIVE",
                    "badge": f"🔥 {ev_title}: {action} Desteği ({rem_min:.0f} dk)",
                    "remaining_min": rem_min,
                    "event_title": ev_title,
                    "events_count": int(news_bias_slot.get("hits", 0) or 1),
                }
            elif act_dir == -nb_dir:
                score = max(30.0, round(score - 15.0, 1))
                news_info = {
                    "has_active_news": True,
                    "alignment": "OPPOSING",
                    "badge": f"⚠️ {ev_title}: Zıt Yön Uyarısı ({rem_min:.0f} dk)",
                    "remaining_min": rem_min,
                    "event_title": ev_title,
                    "events_count": int(news_bias_slot.get("hits", 0) or 1),
                }

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
            "news_info": news_info,
            "rsi_5m": t.get("rsi", 50.0),
            "rsi_15m": t.get("rsi", 50.0),
            "source": t.get("source", "yok"),
            "age_sec": t.get("age_sec"),
            "spread_known": t.get("spread_known", False),
            "price_placeholder": bool(t.get("price_placeholder")),
            "bar_gap": bool(t.get("bar_gap")),
            "tick_mismatch": bool(t.get("tick_mismatch")),
            "macd_verdict": t.get("macd_verdict", "NÖTR (Beklemede)"),
            # Ham MACD histogramı: kokpit "MACD Momentum" barı bunu ATR'ye
            # bölerek gösterir (bkz. tick sözlüğü — aynı alan, aynı birim).
            "macd_hist": float(t.get("macd_hist", 0.0) or 0.0),
            # Ham ATR (fiyat birimi): kokpit yön barı MACD histogramını bununla
            # bölüp ölçeksizleştirir (bkz. tick sözlüğü — aynı alan, aynı birim).
            "atr": float(t.get("atr", 0.0) or 0.0),
            "cmo": t.get("cmo", 0.0),
            "cci": t.get("cci", 0.0),
            "adx": t.get("adx", 25.0),
            "supertrend_dir": st_dir,
            "htf_trend": t.get("htf_trend", "NEUTRAL"),
            "direction_guard_reason": t.get("direction_guard_reason", ""),
            "signal_bar_time": t.get("signal_bar_time"),
            "signal_bar_confirmed": bool(t.get("signal_bar_confirmed", False)),
            "pip_target": spec["tp_pips"],
            "stop_loss_pips": spec["sl_pips"],
            "risk_reward": f"1:{round(spec['tp_pips'] / spec['sl_pips'], 2)}" if spec["sl_pips"] > 0 else "1:1.83",
            "atr_pips": atr_pips,
            "tv_symbol": t["tv_symbol"],
        }

        gate = _evaluate_signal_gate(
            sym_u, base, current_utc_hour, dxy_regime,
            has_open_position=sym_u in active_syms,
            news_bias=news_bias_slot,
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
        base["skor_gecti"] = (
            "score" not in gate["blocked_by"] and action in ("BUY", "SELL")
        )
        base["motor_acar"] = bool(gate["signal_ready"])
        # 2026-10-16 13-sembol / 7 gün MT5 replay: klasik para XAU/BTC/US30/AUD'da.
        # GBPUSD klasik −5…−26; panel STRONG dese bile motor bu dördün dışında açmaz.
        if sym_u not in CANLI_CLASSIC_SYMBOLS:
            base["motor_acar"] = False
            base["primary_blocker"] = "classic_scope"
            base["blocker_text"] = _GATE_LABELS["classic_scope"]
        if base["tier"] == "STRONG" and not base["motor_acar"]:
            base["tier"] = "WAIT"

        candidates.append(base)

    # Sıralama: güçlü sinyaller önce, sonra skor. Panelin ilk gördüğü satır
    # her zaman en yüksek kaliteli aday olur.
    tier_rank = {"STRONG": 0, "ACTIVE": 1, "WATCH": 2, "WAIT": 3}
    candidates.sort(key=lambda x: (tier_rank.get(x["tier"], 9), -x["score"]))

    signals = [c for c in candidates if c["tier"] == "STRONG" and not c.get("has_open_position")]

    response = {
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
            "commodity_min_score": COMMODITY_MIN_SCORE,
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
    _RADAR_CACHE = (now_ts, response)
    return response


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
        f"{_GATE_LABELS.get(top_key, top_key)} ({top_n} sembol). "
        f"Tarama evreni {len(candidates)} kanıtlı sembol (L30 replay pozitifleri)."
    )


# ============================================================================
# BTC-GOLD SAYFASI — ANLIK OTOMATİK YORUM (kural tabanlı, insan-okur Türkçe)
# Frontend 60 sn'de bir /btc-gold/comment çağırır; gösterge cache'inden
# 2-4 cümlelik düz Türkçe bir piyasa yorumu sentezlenir (LLM çağrısı yok → hızlı+ücretsiz).
# ============================================================================

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


def _human_symbol_comment(symbol: str, tick: Dict[str, Any], min_score: float) -> Dict[str, Any]:
    """Tek sembol için kısa, düz Türkçe yorum sentezler (LLM yok).

    Kullanıcı geri bildirimi (2026-10-13): önceki metin jargondan geçilmiyordu
    ("MTF Ayı Uyumu", "belirginleşen trend", "momentum teyidi"...). Arayüzün
    sade dil kuralı burada da geçerli: her cümle TEK bir şey söyler ve
    operatörün karar verirken sorduğu soruya cevap verir.

    Cümle sırası sabit: yön → güç → göstergeler (RSI/SuperTrend) → karar.
    DXY rejimi sayfanın kendi "Piyasa Notu" şeridinde zaten yazıyor ve bu iki
    enstrüman DXY'den tasarım gereği muaf olduğu için burada tekrarlanmaz.
    """
    score = float(tick.get("score", 50.0))
    trend = str(tick.get("trend", "NEUTRAL"))
    action = str(tick.get("action", "HOLD"))
    rsi = float(tick.get("rsi", 50.0))
    adx = float(tick.get("adx", 20.0))
    st_dir = int(tick.get("supertrend_dir", 0))

    # Sade karşılıklar — "BULLISH/BEARISH" ve "yukarı 1 / aşağı -1" operatöre
    # teknik tabir; ekranda düz Türkçe istendi.
    if trend == "BULLISH":
        trend_txt = "fiyat yükseliş eğiliminde"
    elif trend == "BEARISH":
        trend_txt = "fiyat düşüş eğiliminde"
    else:
        trend_txt = "fiyat belirgin bir yöne gitmiyor"

    if adx >= 40:
        guc_txt, guc_kisa = f"trend çok güçlü (ADX {adx:.0f})", "Trend çok güçlü"
    elif adx >= 25:
        guc_txt, guc_kisa = f"trend güçlü (ADX {adx:.0f})", "Trend güçlü"
    elif adx >= 20:
        guc_txt, guc_kisa = f"trend henüz güçleniyor (ADX {adx:.0f})", "Trend güçleniyor"
    elif adx >= 15:
        guc_txt, guc_kisa = f"trend zayıf (ADX {adx:.0f})", "Trend zayıf"
    else:
        guc_txt, guc_kisa = f"piyasa yatay, trend yok (ADX {adx:.0f})", "Piyasa yatay"

    sentences: List[str] = [
        f"Şu an {trend_txt}; {guc_txt}.",
    ]

    # 2) Gösterge yorumu — RSI tek başına, SuperTrend tek başına. Skor/kapı
    #    cümlesi zaten üstteki "Anlık Motor Durumu" şeridinde yazıyor, burada
    #    tekrar edilmez.
    if rsi >= 70:
        sentences.append(f"RSI {rsi:.0f} ile alım tarafı fazla ısınmış; yukarıdan almak riskli.")
    elif rsi >= 55:
        sentences.append(f"RSI {rsi:.0f} — alıcılar güçlü.")
    elif rsi <= 30:
        sentences.append(f"RSI {rsi:.0f} ile satış tarafı fazla soğumuş; tepki alımı gelebilir.")
    elif rsi <= 45:
        sentences.append(f"RSI {rsi:.0f} — satıcılar güçlü.")
    else:
        sentences.append(f"RSI {rsi:.0f} — alıcı ile satıcı dengede.")

    if st_dir > 0:
        sentences.append("SuperTrend al yönünü gösteriyor.")
    elif st_dir < 0:
        sentences.append("SuperTrend sat yönünü gösteriyor.")

    # 3) Karar — motor eşiğiyle karşılaştırılır; eşik SAYISI kapı zincirinde var.
    if action == "BUY" and score >= min_score:
        sentences.append("Alış sinyali giriş eşiğini geçti; kurallar uygun olduğunda işlem açılabilir.")
    elif action == "SELL" and score >= min_score:
        sentences.append("Satış sinyali giriş eşiğini geçti; kurallar uygun olduğunda işlem açılabilir.")
    elif action in ("BUY", "SELL"):
        yon_txt = "alış" if action == "BUY" else "satış"
        sentences.append(f"{yon_txt.capitalize()} yönü var ama puan giriş eşiğinin altında; şimdilik izlemede.")
    else:
        sentences.append("Şu an yön yok; beklemek doğru.")

    return {
        "symbol": symbol,
        "display": tick.get("display", symbol),
        "action": action,
        "score": round(score, 1),
        "trend_label": guc_kisa,
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
        tick = ticks.get(sym) or {}
        if not tick or tick.get("source") != "mt5_tick" or tick.get("price_placeholder"):
            symbols_out[sym] = {
                "symbol": sym,
                "display": sym,
                "action": "HOLD",
                "score": 0.0,
                "strength_label": "BELİRSİZ",
                "comment": "MT5 tik yok — fiyat gösterilmiyor.",
                "error": "MT5 tik yok",
            }
            continue
        min_score = _AUTO_SETTINGS.btc_min_score if sym == "BTCUSD" else _AUTO_SETTINGS.min_score
        symbols_out[sym] = _human_symbol_comment(sym, tick, float(min_score))

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
    source_note = "Fiyat kaynağı: MT5 tik." if mt5_ok else "Fiyat kaynağı: MT5 tik yok."

    return {
        "interval_sec": 60,
        "generated_at": time.time(),
        "market_note": " ".join(x for x in (dxy_note, session_note, source_note) if x),
        # Dinamik DXY panosu (2026-10-13): sayfa üstündeki notun ÜSTÜNE progress bar
        # + sayısal değer olarak çizilir. `None` ise frontend bileşeni hiç göstermez
        # (DXY fetch'i başarısızsa tire/yanlış değer göstermek yerine gizlenir).
        "dxy": dxy,
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
        lot_ceiling = min(HARD_MAX_INDEX_LOT, _AUTO_SETTINGS.max_index_lot)
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

# --- CANLI SABİTLER: kod içinde tanımlı, sunucudaki ayar dosyası EZEMEZ (2026-10-13) ---
# Neden sabit: gömülü canlı sunucuda `forex_auto_settings.json` (Docker `/data` birimi)
# bu iki değerin ESKİ halini tutuyordu ve kod varsayılanını maskeliyordu; panelde de
# düzenlenecek alan YOK (chandelier `trailing_stop_pips`'ten ayrı bir alan, `ls_symbols`
# ise hiç panelde değil). Yani tek geçerli kontrol noktası kod. Aşağıdaki değerler
# `ForexAutoPaperSettings` varsayılanı olur VE açılışta kalıcı dosyadan yüklenen değerlerin
# üzerine zorlanır — böylece sunucu eski dosyayla açılsa bile canlı bu değerleri kullanır.
#
# chandelier_atr_mult = 0.3: kâr tepesinden 0.3×GİRİŞ ATR'si geri verilince kilit.
#   4 bağımsız pencerede kazanan (W1 +26%, W2 +7%, W3 +8%, W4 +11%; PF ↑, maxDD ↓),
#   2-pip kaymada korunuyor. XAU+BTC replay: chand0.3 $4305.70/PF 1.87 vs en iyi
#   sabit-pip $3950.88/1.80; chand1.2 (eski canlı değer) $3863 — sabit-pipten KÖTÜ.
#   Analiz: docs/FX_2026-10-13_TRAILING_BE_ANALIZ.md
# ls_symbols = XAUUSD + US30 + NAS100: LS kolunun işlem açabildiği evren. NAS100
#   (= MT5 'USTEC') üç pencerede de pozitif ve XAU/US30 pnl'ini düşürmüyor.
CANLI_CHANDELIER_ATR_MULT = 0.3
CANLI_LS_SYMBOLS = ("XAUUSD", "US30", "NAS100")
# Keltner Squeeze (M15) canlı sembol sabiti — kanıt 5 kanonik sembolde toplandı
CANLI_SQUEEZE_KC_SYMBOLS = ("XAUUSD", "BTCUSD", "US30", "NAS100", "USDCHF")
# Klasik radar emir evreni: XAU, BTC, US30, AUDUSD, AUDCAD
CANLI_CLASSIC_SYMBOLS = ("XAUUSD", "BTCUSD", "US30", "AUDUSD", "AUDCAD")
# Aynı pencere: S3 −12.85 (PF 0.90), London Sign −40.16 (PF 0.27, WR %37.5).
# Dosya ve panel bu iki anahtarı geri açamasın diye zorlanır.
CANLI_S3_ENABLED = False
CANLI_LS_ENABLED = False


def _apply_canli_sabitler(settings: "ForexAutoPaperSettings") -> "ForexAutoPaperSettings":
    """Ayar dosyasını EZEREK canlı sabitleri zorlar (yukarıdaki gerekçe).

    Hem açılışta (kalıcı dosya yüklendikten sonra) hem de panel/POST ile ayar
    kaydedildiğinde çağrılır; gövdede bu alanlar gelse bile sabit kazanır.
    Değer değiştirmek için koddaki sabit düzenlenir.
    """
    settings.chandelier_atr_mult = CANLI_CHANDELIER_ATR_MULT
    settings.ls_symbols = list(CANLI_LS_SYMBOLS)
    settings.squeeze_kc_symbols = list(CANLI_SQUEEZE_KC_SYMBOLS)
    settings.s3_enabled = CANLI_S3_ENABLED
    settings.ls_enabled = CANLI_LS_ENABLED
    # AUDCAD klasik listede. Ayar dosyası eski 10'lu listeyi taşısa da kapı açık kalsın.
    _allowed = [str(s).upper() for s in (settings.allowed_symbols or [])]
    if "AUDCAD" not in _allowed:
        settings.allowed_symbols = list(settings.allowed_symbols or []) + ["AUDCAD"]
    return settings


class ForexAutoPaperSettings(BaseModel):
    enabled: bool = False
    balance: float = Field(10000.0, ge=50.0, description="Demo bakiye (USD)")
    risk_per_trade_pct: float = Field(2.0, ge=0.1, le=20.0, description="Pozisyon hacmi risk bütçesi (% bakiye). 2026-10-14: 5→2. Kanıt: ReportHistory-53077151 (308 işlem) işlem başına 1R riski medyan %9.94 bakiye (ayar %5), 148 işlem >%10; bakiye 140.77→tepe 306.19→41.16 (−%87 tepe dibi). Bütçe aşımının kaynağı taban-lot kelepçesiydi (aşağıda sınırlandı). Panelden ayarlanabilir.")
    max_open_positions: int = Field(99, ge=1, le=99, description="Aynı anda maksimum açık işlem (2026-10-07 kullanıcı kararı: 99 — slot rekabeti kaldırıldı; 60g replay'de XAU/BTC kâr potansiyeli 99 slotta ~3x)")
    max_positions_per_symbol: int = Field(1, ge=1, le=5, description="Aynı sembolde aynı yönde maksimum açık işlem (Varsayılan 1: Tek güvenli scalper pozisyonu)")
    min_score: float = Field(75.0, ge=50.0, le=98.0, description="Minimum sinyal radar skoru (7 günlük replay A/B ile 75.0'e ayarlandı)")
    flip_ignore_min_score: bool = Field(True, description="Zıt sinyal flip'inde skor eşiğini yoksay (2026-10-14 kullanıcı kararı: 'herhangi bir stratejiden zıt sinyal gelirse açık işlem kapanıp yeni sinyalle açılsın'). True = açık pozisyon varken zıt yönde sinyal GELDİĞİ anında flip (skor eşiği aranmaz). Spread/maliyet kapısı, korelasyon kalkanı, seri-SL soğuması, risk normalizasyonu ve lot bütçesi korunur — bunlar risk kapısıdır, atlanmaz.")
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
    max_index_lot: float = Field(2.0, ge=0.10, le=HARD_MAX_INDEX_LOT, description="Maksimum Endeks (US30/NAS100) lot tavanı — 2026-10-14 kullanıcı kararı: US30'da diğer sembollere göre aşırı lot açılıyordu (50.0 hard tavan), 2.0'a çekildi. IC Markets endeks kontratlarında 1 lot = 1 kontrat; pip değeri yüksek olduğundan risk hızlı büyür.")
    gold_cooldown_sec: float = Field(60.0, ge=HARD_MIN_GOLD_COOLDOWN_SEC, le=900.0, description="Altın (XAUUSD) kapanış sonrası soğuma süresi (min 60 sn)")
    btc_cooldown_sec: float = Field(60.0, ge=0.0, le=900.0, description="BTCUSD kapanış sonrası soğuma süresi (sn). 2026-10-10 denetim P1-6: flip'te bu sayaç sıfırlanır; panelden ayarlanabilir hale getirildi (0 = kapalı)")
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
    major_min_atr_pips: float = Field(2.5, ge=0.0, le=50.0, description="Majörler minimum ATR (pip) tabanı — ölü piyasa filtresi (0 = kapalı; 2026-10-08 kullanıcı kararı: 4.0 → 2.5 — GBPUSD 3.6p / AUDUSD 1.7p majörleri 'ölü piyasa' diye eliyordu, FX'te işlem açılmıyordu)")
    crypto_sl_atr_mult: float = Field(1.5, ge=0.0, le=5.0, description="Kripto kategorisi özel SL ATR çarpanı (0 = global 1.1×ATR; 2026-10-06 replay: BTC −$30→+$58, maxDD $161→$142. 2026-10-10 denetim A/B teyidi: 32g izole BTC 1.5× = +$396 / 1.1× = +$298 → 1.5× KORUNUR)")
    crypto_tp_enabled: bool = Field(False, description="Kriptoda sabit TP emri (False = kapalı; 2026-10-06 30g replay: TP kapalıyken BTC −$55.70→−$18.02. 2026-10-10 denetim A/B teyidi: TP kapalı +$396 / TP açık +$311 → KAPALI KORUNUR; kazanç BE/trailing ile koşturulur)")
    btc_min_score: float = Field(76.0, ge=0.0, le=98.0, description="BTCUSD özel giriş skor eşiği (0 = global min_score; süpürme: 76 noktası)")
    # --- 2026-10-10 BTCUSD denetimi (P0-3): BTC'nin kayıp-uyarlamalı freni yoktu ---
    btc_ev_exempt: bool = Field(False, description="BTCUSD'yi EV kalkanından MUAF tut (eski davranış). False = BTC de 24 saatlik EV penceresiyle dinlenir (2026-10-10 denetim P0-3: muafiyet kaldırıldı; XAU muafiyeti ayrıca korunur)")
    btc_net_negative_guard_enabled: bool = Field(False, description="BTC'ye özel net-negatif pencere freni: son pencerede net zarar + yeterli işlem varsa BTC yeni giriş almaz (ardışık-SL'e bağlı değil). 2026-10-10 denetim A/B: 32g replay'de fren net PnL'i DÜŞÜRDÜ (+$373 → +$222) ve iki pencerede de negatif → varsayılan KAPALI; mekanizma korunuyor, kanıt gelirse açılır")
    btc_net_negative_window_hours: float = Field(6.0, ge=1.0, le=48.0, description="BTC net-negatif freni geriye dönük pencere (saat)")
    btc_net_negative_min_trades: int = Field(6, ge=3, le=50, description="BTC net-negatif freni için pencerede gereken minimum işlem sayısı")
    btc_net_negative_usd: float = Field(0.0, ge=-1000.0, le=0.0, description="BTC net-negatif freni eşiği (USD): pencere net'i bunun altındaysa BTC dinlenir (0.0 = herhangi bir net zarar)")
    crypto_risk_clamp_enabled: bool = Field(True, description="Kripto/altında risk-skip bypass'ı yerine lotu kategori tabanına SABİTLE (risk asla artmaz; eski davranış aşırı lotu kullanıyordu — 2026-10-10 denetim P0-4)")
    loss_streak_limit: int = Field(3, ge=0, le=10, description="Seri-SL sigortası: aynı sembolde bu kadar ardışık tam-SL kaybında yeni girişler durur (0 = kapalı; 2026-10-07 kullanıcı önerisi + replay: 3)")
    loss_streak_cooldown_sec: float = Field(300.0, ge=0.0, le=3600.0, description="Seri-SL tetiklenince sembolün yeni giriş soğuma penceresi (saniye; normal altın/BTC cooldown'undan BAĞIMSIZ — kullanıcı önerisi: 300 = 5 dk)")
    chandelier_atr_mult: float = Field(CANLI_CHANDELIER_ATR_MULT, ge=0.0, le=5.0, description="Chandelier kâr kilidi: BE sonrası trailing, kâr tepesinden (bu kat × GİRİŞ ATR'si) geri verilince kilitler (0 = sabit pip trail). 2026-10-13: köprüye (scripts/mt5_bridge.py) port edildi — motor bu değeri /mt5/sync ile köprüye gönderir, canlı iz süren stop artık buradan yönetilir. **Bu değer canlı SABİT: `CANLI_CHANDELIER_ATR_MULT` (forex.py) — sunucudaki ayar dosyası ve panel gövdesi EZEMEZ.** 1.2→0.3 sıkma 4 bağımsız pencerede kazanıyor (W1 +26%, W2 +7%, W3 +8%, W4 +11%; PF artıyor, maxDD düşüyor) ve 2-pip kaymada korunuyor. Doğrudan XAU+BTC replay (2026-07-15→08-15): chand0.3 net $4305.70 / PF 1.87 / DD $79.49 vs en iyi sabit-pip $3950.88 / 1.80; 2-pip kaymada $2538.31/1.47 vs $2218.56/1.39. 15dk bar çözünürlüğünde yön korunuyor (etki ~%36 küçülür) → 0.05 yerine 0.3. Analiz: docs/FX_2026-10-13_TRAILING_BE_ANALIZ.md")
    tp_cancel_on_trail: bool = Field(FOREX_TP_CANCEL_ON_TRAIL_DEFAULT, description="Trailing aktifleşince sabit TP emri İPTAL edilir (uzun trendi TP'ye takılmadan koşturur; 2026-10-09 4 pencere A/B IS/OOS/OOS2/F1: +$201/+$215/+$65/+$170, maxDD düşüyor — canlı VARSAYILAN AÇIK). Geri alma: FOREX_TP_CANCEL_ON_TRAIL=false. MT5 tarafında MODIFY_SLTP tp_action='cancel' ile uygulanır. Risk: kâr geri verilirse trailing/BE yakalar — sert gap'te stop yine tek koruma")
    # ── 2026-10-14: BE/trail denetim kolları (ReportHistory-53077151) ────────────
    # Hepsinin varsayılanı MEVCUT DAVRANIŞI BİREBİR KORUR (kapalı/0). Yalnız replay
    # A/B kanıtı geçen kol açılır. Ölçüm: 1R medyan 1.34 ATR iken kazanan çıkış
    # +0.16 R (0.21 ATR); kazananların %54 tepe kârı BE/trail kilidiyle geri verilmiş.
    be_lock_from_mfe: bool = Field(False, description="BE kilidi ANLIK kâr yerine MFE (tepe) üzerinden hesaplanır — replay paritesi. Canlı `pnl_pips` (poll anı) kullanırken replay `pnl_extreme_pips` (bar tepesi) kullanıyordu; bu sapma canlıda sistematik olarak DAHA SIKI kilit üretiyordu. Açıkken tetik ve kilit aynı tepeden okunur (replay ile birebir).")
    be_trigger_atr_mult: float = Field(0.0, ge=0.0, le=5.0, description="BE tetiğine ATR tabanı ekler: tetik = max(min($1+headroom, eff_be), bu kat × giriş ATR'si). 0 = kapalı (mevcut davranış). Amaç: XAU'da tetiğin 0.15 ATR'ye düşmesini engellemek. UYARI: 2026-10-12 dokümanında yalnız-tetik geciktirme (min_r_atr) replay'de ELENDİ — kilit tabanı birlikte büyümedikçe işe yaramıyor; kanıt olmadan açılmaz.")
    be_trigger_r_mult: float = Field(0.0, ge=0.0, le=5.0, description="BE tetiğine R tabanı ekler: tetik = max(min($1+headroom, eff_be), bu kat × giriş SL'i). 0 = kapalı (mevcut davranış).")
    chandelier_gate_independent: bool = Field(False, description="Chandelier, BE kilidini BEKLEMEDEN kurulur (MFE > mult×giriş ATR'si olur olmaz). Şu an kapı `BE aktif` şartına bağlı olduğu için XAU'da MFE > 0.75 ATR (diğerlerinde 0.50 ATR) altındaki tüm hareketlerde chandelier ölü kalıyor; ölçülen tepe medyanı 0.63 ATR. **Replay W1 OOS: net +3904→+4510 (+%15.5), PF 1.62→1.73, WR %74.0→%78.8.**")
    be_trigger_atr_mult_gold: float = Field(0.75, ge=0.0, le=5.0, description="XAUUSD'ye ÖZEL BE tetik tabanı (× giriş ATR'si). Kullanıcı talebi (2026-10-14): altında erken tetiklenmesin. XAU 0.05 lot'ta tetik 6 pip = 0.15 ATR'ye düşüyordu; 0.75 → ~30 pip = 0.75 ATR'de kilitlenir. 0 = kapalı. **2026-10-14 KULLANICI KARARI: risk kabul edilerek 0.75 AÇILDI.** Ölçüm uyarısı: W1 OOS'ta tetiği geciktiren genel kol (minratr) net +3904→+675'e düşürdü (PF 1.62→1.08, SL zararı −6278→−8755) — yani erken BE tam-SL olacak işlemleri küçük kâra çeviriyordu. Bu değer o riske rağmen açıldı; geri alma: 0.0.")
    be_trigger_atr_mult_crypto: float = Field(0.50, ge=0.0, le=5.0, description="BTCUSD/ETHUSD'ye ÖZEL BE tetik tabanı (× giriş ATR'si). BTC 0.05 lot'ta tetik 45 pip = 0.27 ATR'ye düşüyordu; 0.50 → ~83 pip = 0.50 ATR. 0 = kapalı. **2026-10-14 KULLANICI KARARI: risk kabul edilerek 0.50 AÇILDI.** Geri alma: 0.0.")
    # ── 2026-10-14: EKONOMİK TAKVİM YÖN KANITI (kullanıcı talebi) ──────────────
    # "Açıklanan veri bu sembolde BUY yönünü destekliyorsa filtreler kaldırılıp
    #  işlem açılsın; karşıt yöndeyse radar sinyali engellensin."
    # Anahtar VARSAYILAN KAPALI: bu bir strateji değişikliğidir ve proje kuralı
    # gereği OOS replay kanıtı olmadan aktive edilmez. Açıldığında:
    #   * karşıt yön  → sinyal ENGELLENİR (risk AZALTICI)
    #   * destek yönü → YUMUŞAK filtreler atlanır (major seans/min-ATR, skor, ADX, SuperTrend)
    # ASLA atlanmayanlar: spread, korelasyon kalkanı, seri-SL, soğuma, EV kalkanı,
    # lot/risk bütçesi, maks pozisyon. Bunlar sinyal filtresi değil MALİYET/RİSK
    # kapılarıdır; atlamak hesabı riske atar.
    news_bias_enabled: bool = Field(False, description="Ekonomik takvim yön kanıtını otonom girişte kullan (2026-10-14 kullanıcı talebi). Yalnız AÇIKLANMIŞ olaylar kullanılır (actual dolu) — beklentiyle spekülasyon YAPILMAZ. Varsayılan KAPALI; kanıt olmadan açılmaz.")
    news_bias_block_opposing: bool = Field(True, description="Takvim yönü sinyalin TERSİyse işlemi engelle (yalnız news_bias_enabled açıkken). Risk AZALTICI yön.")
    news_bias_bypass_filters: bool = Field(False, description="Takvim yönü sinyali DESTEKLİYORSA yumuşak filtreleri atla (major seans/min-ATR, skor eşiği, ADX, SuperTrend). MALİYET/RİSK kapıları (spread, korelasyon, seri-SL, soğuma, EV, lot bütçesi, maks pozisyon) ASLA atlanmaz. Varsayılan KAPALI — bu bir strateji değişikliğidir, OOS replay kanıtı ister.")
    news_bias_window_sec: float = Field(900.0, ge=60.0, le=3600.0, description="Açıklamadan sonra yönün geçerli sayıldığı pencere (saniye; varsayılan 900 = 15 dk)")
    blocked_hours_utc: List[int] = Field(default_factory=list, description="İşlem yapılmasın istenen UTC saatleri (varsayılan: boş — zayıf saat kalkanı kaldırıldı)")
    allowed_symbols: List[str] = Field(
        default_factory=lambda: ["XAUUSD", "BTCUSD", "GBPJPY", "EURJPY", "US30", "NAS100",
                                 "GBPUSD", "AUDUSD", "USDJPY", "USDCHF", "AUDCAD"],
        description="İşleme izin verilen pariteler. DEĞİŞMEZ: allowed_symbols ⊆ FOREX_SYMBOLS (test_forex_auto_paper ile kilitli).",
    )
    mode_symbols: List[str] = Field(
        default_factory=lambda: ["XAUUSD", "GBPJPY", "EURJPY", "NAS100", "CHFJPY", "USDJPY"],
        description="Donchian+ADX giriş modunun AKTİF olduğu semboller (JPY krosları ve endeksler).",
    )
    mode_exclusive: List[str] = Field(
        default_factory=lambda: ["GBPJPY", "EURJPY", "CHFJPY"],
        description="YALNIZ donchian_adx moduyla işlem açılan semboller (klasik skor sinyali bu çiftlerde replay'de kanıtlanmış negatif beklentiye sahip — kapalı kalır)",
    )
    donchian_adx_min: float = Field(18.0, ge=0.0, le=60.0, description="Donchian+ADX modu ADX(14) eşiği (2026-10-10 denetim P2-9: kodda sabitti, diğer akışlar ayardan okuyordu — kalibre değer 18.0 korunur)")
    donchian_max_per_day: int = Field(2, ge=0, le=20, description="Donchian+ADX modu: yön başına günde azami giriş (2026-10-10 denetim P2-9: kodda sabitti — kalibre değer 2 korunur; 0 = sınırsız)")
    ema_adx_symbols: List[str] = Field(
        default_factory=lambda: ["XAUUSD", "NAS100"],
        description="EMA+ADX geri-çekilme skalpi (M5) akışının AKTİF olduğu semboller (2026-10-08: XAUUSD 5m; 60g +$184.56 + Tem15 +$153.90 iki bağımsız pencerede pozitif). Klasik ve donchian akışları bu sembollerde KORUNUR (üç akış birlikte). 2026-10-13: NAS100 (= MT5 'USTEC') eklendi — izole 2-pencere pozitif (W1 +$3.25 n33, W2 +$71.00 n37 WR %89.2).",
    )
    ema_adx_enabled: bool = Field(True, description="EMA+ADX geri-çekilme (M5) akışı: EMA8/21/50 dizilimi + ADX + EMA21 geri çekilmesi + trend yönünde onay barı")
    ema_adx_adx_min: float = Field(25.0, ge=0.0, le=60.0, description="EMA+ADX: ADX(14) trend gücü eşiği (spec: 25)")
    ema_adx_touch_atr: float = Field(0.30, ge=0.0, le=2.0, description="EMA+ADX: barın EMA21'e 'değmiş' sayılma toleransı (× ATR)")
    ema_adx_sl_atr: float = Field(1.5, ge=0.5, le=5.0, description="EMA+ADX: SL (× ATR(14)) — 48h RR süpürmesinde optimal bant")
    ema_adx_tp_atr: float = Field(2.0, ge=0.0, le=6.0, description="EMA+ADX: TP (× ATR(14)); 0 = sabit TP yok (trailing'e bırakılır)")
    ema_adx_max_per_day: int = Field(0, ge=0, le=20, description="EMA+ADX: yön başına günde azami giriş (0 = sınırsız, spec)")
    s3_enabled: bool = Field(False, description="S3 (Supertrend+RSI pullback). **Canlı SABİT KAPALI: `CANLI_S3_ENABLED` — ayar dosyası ve panel EZEMEZ.** 2026-10-16 13-sembol 7 gün MT5 replay: 64 işlem, WR %53.1, net −12.85, PF 0.90. Kol kodda durur; yeniden açmak için sabiti değiştir.")
    s3_symbols_5m: List[str] = Field(default_factory=lambda: ["XAUUSD"], description="S3 5m kolu (TP yok + ST-flip çıkışı; L30: XAU +$90.04 PF 2.09). 2026-10-12: AUDNZD DÜŞÜRÜLDÜ — FOREX_SYMBOLS'te değildi (tick yok → hayalet), izole 2-pencere replay'de OOS n=74 < 100 ve net −$61.09 → kanıt yok")
    s3_symbols_15m: List[str] = Field(default_factory=lambda: ["XAUUSD", "BTCUSD", "US30", "GBPUSD"], description="S3 15m kolu (TP 2.0×ATR; L30: XAU +$58.12 PF 3.08, BTC +$59.28 PF 6.63, US30 +$133.54 PF 4.82; 2026-10-08 7-sembol evren: stflip +$279.54 PF 3.13 / tp2 +$278.97 PF 3.12 — GBPUSD +$29.65 eklendi; USTEC 0 işlem — pullback deseni oluşmuyor)")
    s3_adx_min: float = Field(25.0, ge=0.0, le=60.0, description="S3: ADX(14) trend gücü eşiği (spec: 25)")
    s3_rsi_lo: float = Field(40.0, ge=0.0, le=50.0, description="S3: pullback bandı alt sınırı (son 6 bar TAMAMEN bu bandın altına inerse trend bozulmuş sayılır)")
    s3_sl_atr: float = Field(1.5, ge=0.5, le=5.0, description="S3: SL (× ATR(14)) — replay spec")
    s3_tp_atr_15m: float = Field(2.0, ge=0.0, le=6.0, description="S3 15m kol: TP (× ATR(14)); 5m kolu TP'sizdir (ST-flip + BE/trailing)")
    s3_max_per_day: int = Field(0, ge=0, le=20, description="S3: sembol+TF+yön başına günde azami giriş (0 = sınırsız)")
    lb_enabled: bool = Field(True, description="London Breakout akışı: Asya kutusu (00:00→box_end UTC) high/low kırılımı, Londra penceresinde tetik. L30 replay pozitif 19 sembolde açık (2026-10-08)")
    lb_symbols: List[str] = Field(
        default_factory=lambda: ["XAUUSD", "GBPUSD", "USDJPY", "BTCUSD", "USDCHF", "US30"],
        description="London Breakout sembolleri (2026-10-08 L30 replay pozitifleri; GBPJPY −$11 hariç tutuldu — çift donchian-exclusive). Panelden doğrulanmış kârlı kroslar (AUDCAD, EURCAD, GBPAUD, GBPCAD, EURAUD, AUDJPY, NZDUSD, EURNZD, AUDNZD, GBPNZD) eklenebilir.",
    )
    lb_box_end_utc: int = Field(7, ge=0, le=12, description="London Breakout: Asya kutusu bitiş saati (UTC); 00:00'dan bu saate kadar high/low")
    lb_entry_end_utc: int = Field(11, ge=1, le=18, description="London Breakout: tetik penceresi bitiş saati (UTC); box_end'den bu saate kadar kutu dışına kapanış arar")
    lb_sl_box_frac: float = Field(0.5, ge=0.1, le=1.0, description="London Breakout: SL = kutu yüksekliği × bu oran (süpürme: 0.4 en iyi PF ama 0.5 default spec)")
    lb_tp_r: float = Field(1.5, ge=0.5, le=5.0, description="London Breakout: TP = SL × bu R katı")
    lb_max_per_day: int = Field(1, ge=1, le=5, description="London Breakout: sembol+yön başına günde azami giriş (replay spec: 1)")
    ls_enabled: bool = Field(False, description="London Sign. **Canlı SABİT KAPALI: `CANLI_LS_ENABLED` — ayar dosyası ve panel EZEMEZ.** 2026-10-16 13-sembol 7 gün MT5 replay: 16 işlem, WR %37.5, net −40.16, PF 0.27 (US30 tek başına −23). Kol kodda durur; yeniden açmak için sabiti değiştir.")
    ls_symbols: List[str] = Field(
        default_factory=lambda: list(CANLI_LS_SYMBOLS),
        description="London Sign sembolleri. **Bu liste canlı SABİT: `CANLI_LS_SYMBOLS` (forex.py) — sunucudaki ayar dosyası ve panel gövdesi EZEMEZ.** 2026-10-12 replay: XAUUSD +$182 (WR %91.8 n49) ve US30 +$74 (WR %90 n30) — 60g pencerede iki pozitif. FX majörlerinde NEGATİF (USDJPY/GBPUSD/GBPJPY) → kapsam dışı. BTCUSD nötr/negatif (WR %54) → kapsam dışı. 2026-10-13: NAS100 (= MT5 'USTEC') eklendi — üç pencerede de pozitif (W1 +$83 n21 WR %86, W2 +$58 n25 WR %80, W3 +$43 n10 WR %90); canlı LS defterine eklenince XAU/US30 pnl'i BİREBİR sabit kalıp üstüne +$107/+$58/+$43 ekliyor; slip 2p'de WR sabit %85.7.",
    )
    ls_sign_start_utc: int = Field(13, ge=0, le=23, description="London Sign: sign penceresi başlangıç saati (UTC)")
    ls_sign_start_min: int = Field(30, ge=0, le=59, description="London Sign: sign penceresi başlangıç dakikası (UTC)")
    ls_sign_end_utc: int = Field(14, ge=0, le=23, description="London Sign: sign penceresi bitiş saati (UTC)")
    ls_sign_end_min: int = Field(0, ge=0, le=59, description="London Sign: sign penceresi bitiş dakikası (UTC)")
    ls_entry_start_utc: int = Field(14, ge=0, le=23, description="London Sign: giriş penceresi başlangıç saati (UTC)")
    ls_entry_start_min: int = Field(0, ge=0, le=59, description="London Sign: giriş penceresi başlangıç dakikası (UTC)")
    ls_entry_end_utc: int = Field(14, ge=0, le=23, description="London Sign: giriş penceresi bitiş saati (UTC)")
    ls_entry_end_min: int = Field(30, ge=0, le=59, description="London Sign: giriş penceresi bitiş dakikası (UTC)")
    ls_sl_atr: float = Field(1.5, ge=0.5, le=5.0, description="London Sign: SL (× ATR(14)) — replay spec")
    ls_hold_hours: float = Field(3.0, ge=0.0, le=24.0, description="London Sign: girişten bu saat sonra zorla kapat (EoD); 0 = kapatma. Replay: 3h (14:30+3h=17:30 UTC)")
    squeeze_kc_enabled: bool = Field(True, description="Keltner/TTM Squeeze kırılımı (M15) akışı: BB(20,2)⊂Keltner(20,1.5) sıkışması bırakılınca bant-dışı kapanış + LazyBear momentum teyidi; SL = |kapanış − KC orta|, TP = 2R. 2026-10-14 canlıya alındı — kanonik DB hattında standalone M15 iki pencerede pozitif (OOS n=97 +$143.93 PF 1.74 / IS n=123 +$77.65 PF 1.47, 2× spread'e dayanıyor) ve --combined defter testinde neti düşürmüyor (dört hücrede Δ+68..+205, maxDD bozulmuyor).")
    squeeze_kc_symbols: List[str] = Field(
        default_factory=lambda: list(CANLI_SQUEEZE_KC_SYMBOLS),
        description="Keltner Squeeze (M15) sembolleri. **Bu liste canlı SABİT: `CANLI_SQUEEZE_KC_SYMBOLS` (forex.py) — sunucudaki ayar dosyası ve panel gövdesi EZEMEZ.** Kanıt 5 sembolde: XAUUSD (tek başına +$83.90 OOS / +$52.06 IS), BTCUSD, US30, NAS100, USDCHF — hepsi iki pencerede pozitif; GBPJPY/EURJPY/GBPUSD/AUDUSD/USDJPY işaret döndürdüğü için kapsam dışı.",
    )
    squeeze_kc_period: int = Field(20, ge=5, le=100, description="Squeeze KC: BB/Keltner periyodu (spec 20)")
    squeeze_kc_bb_mult: float = Field(2.0, ge=0.5, le=5.0, description="Squeeze KC: Bollinger std-dev çarpanı (spec 2.0)")
    squeeze_kc_mult: float = Field(1.5, ge=0.5, le=5.0, description="Squeeze KC: Keltner ATR çarpanı (spec 1.5)")
    squeeze_kc_mom_min: float = Field(0.0, ge=0.0, le=100.0, description="Squeeze KC: momentum |.| onay eşiği (0 = kapalı, spec)")
    squeeze_kc_tp_r: float = Field(2.0, ge=0.0, le=6.0, description="Squeeze KC: TP = SL × bu R katı (0 = TP yok, trailing)")


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


def _enforce_universe_invariant(settings: "ForexAutoPaperSettings") -> List[str]:
    """`allowed_symbols ⊆ FOREX_SYMBOLS` — hayalet parite kilidi (2026-10-12).

    Tick ÜRETİMİ yalnız `FOREX_SYMBOLS` üyeleri için yapılır (bkz.
    `_generate_realistic_ticks`); işlem akışlarının hepsi `ticks.get(sym)` kapısından
    geçer. Dolayısıyla `allowed_symbols`'te olup `FOREX_SYMBOLS`'te olmayan bir çift
    panelde 'seçili' görünür ama ASLA aday/işlem üretemez. 2026-10-12'de 13 kros tam
    bu yüzden hayaletti; sessizce geri sızmalarını engellemek için temizlenir.
    Döndürür: atılan semboller (karar günlüğüne yazılır).
    """
    universe = {item["symbol"] for item in FOREX_SYMBOLS}
    phantoms = [s for s in (settings.allowed_symbols or []) if str(s).upper() not in universe]
    if phantoms:
        settings.allowed_symbols = [
            s for s in (settings.allowed_symbols or []) if str(s).upper() in universe
        ]
    return phantoms


_dropped_phantoms = _enforce_universe_invariant(_AUTO_SETTINGS)
if _dropped_phantoms:
    logger.warning(
        "Forex ayarları: FOREX_SYMBOLS'te olmayan pariteler allowed_symbols'ten atıldı "
        "(hayalet-işlem kilidi): %s", _dropped_phantoms,
    )

# --- 2026-10-10 denetim P1-5: ayar kalıcılığı + birleştirme (merge) -----------------
# Eskiden _AUTO_SETTINGS yalnız bellekti (restart'ta panel config'i koda dönüyordu) ve
# POST /auto-paper/settings TÜM nesneyi değiştiriyordu (eksik alan → sessiz varsayılan
# sıfırlaması, ör. btc_min_score). Artık: (a) ayarlar diske yazılır ve startup'ta yüklenir,
# (b) endpoint kısmi gövdeyi mevcut ayarların üzerine birleştirir.
_FOREX_SETTINGS_FILE = os.environ.get("FOREX_SETTINGS_FILE") or ""


def _settings_store_path() -> str:
    """Ayar dosyası yolu: env → /data (Docker volume) → repo outputs → tmp."""
    cands = [
        _FOREX_SETTINGS_FILE,
        "/data",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "outputs"),
        tempfile.gettempdir(),
    ]
    for c in cands:
        if not c:
            continue
        try:
            os.makedirs(c, exist_ok=True)
            return os.path.join(c, "forex_auto_settings.json")
        except Exception:
            continue
    return os.path.join(tempfile.gettempdir(), "forex_auto_settings.json")


def load_persisted_settings() -> Optional[Dict[str, Any]]:
    """Diske yazılmış ayarları döner (yoksa None). Bilinmeyen anahtarlar yok sayılır."""
    try:
        p = _settings_store_path()
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def persist_settings(settings: "ForexAutoPaperSettings") -> bool:
    """Ayarları diske yazar (atomik). Başarısızlık motoru DURDURMAZ, yalnız loglanır."""
    # Test koşumunda diske yazma/yükleme yapılmaz (testler arası durum sızmasını önler).
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("FOREX_SETTINGS_DISABLE_PERSIST"):
        return False
    try:
        p = _settings_store_path()
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings.model_dump(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True
    except Exception as exc:
        try:
            _log_auto_decision("SYSTEM", f"⚠️ Ayarlar diske yazılamadı (bellek-içi kalır): {exc}")
        except Exception:
            pass
        return False


def merge_settings_payload(payload: Dict[str, Any]) -> "ForexAutoPaperSettings":
    """Kısmi ayar gövdesini mevcut ayarların üzerine birleştirir (P1-5).

    - Bilinen alanlar mevcut değerin üzerine yazılır.
    - Bilinmeyen anahtarlar yok sayılır (ileri/geri uyum).
    - `enabled` çalışma durumundan gelir (toggle ile yönetilir), gövdeden EZİLMEZ.
    - Eksik alanlar mevcut değeri KORUR (eski "tüm nesne değiştir" davranışının tersi).
    """
    cur = _AUTO_SETTINGS.model_dump()
    fields = set(ForexAutoPaperSettings.model_fields.keys())
    unknown = [k for k in payload.keys() if k not in fields]
    for k, v in payload.items():
        if k in fields and k != "enabled":
            cur[k] = v
    cur["enabled"] = _AUTO_STATE.get("enabled", cur.get("enabled", False))
    merged = ForexAutoPaperSettings(**cur)
    _phantoms = _enforce_universe_invariant(merged)
    if _phantoms:
        try:
            _log_auto_decision(
                "SYSTEM",
                f"⚠️ allowed_symbols'ten hayalet pariteler atıldı (FOREX_SYMBOLS'te yok, "
                f"işlem açamazlar): {_phantoms}",
            )
        except Exception:
            pass
    if unknown:
        try:
            _log_auto_decision("SYSTEM", f"ℹ️ Bilinmeyen ayar anahtarları yok sayıldı: {unknown}")
        except Exception:
            pass
    # Canlı sabitler gövdeden gelse bile kazanır (tek kontrol noktası kod).
    _apply_canli_sabitler(merged)
    return merged


# Startup: kalıcı ayarları yükle (varsa). Başarısızsa varsayılanlarla devam.
# Test ortamında atlanır (diskteki artık dosya testleri kirletmesin).
try:
    if not (os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("FOREX_SETTINGS_DISABLE_PERSIST")):
        _persisted = load_persisted_settings()
        if _persisted:
            _known = {k: v for k, v in _persisted.items()
                      if k in ForexAutoPaperSettings.model_fields}
            _AUTO_SETTINGS = ForexAutoPaperSettings(**_known)
            _dropped_phantoms = _enforce_universe_invariant(_AUTO_SETTINGS)
            if _dropped_phantoms:
                logger.warning(
                    "Kalıcı forex ayarlarında hayalet pariteler bulundu ve atıldı "
                    "(FOREX_SYMBOLS'te yok): %s", _dropped_phantoms,
                )
except Exception as _exc:  # pragma: no cover - savunmacı
    _AUTO_SETTINGS = ForexAutoPaperSettings()

# Canlı sabitleri (en üstteki `CANLI_*`) kalıcı dosya yüklendikten SONRA zorla:
# sunucudaki forex_auto_settings.json eski chandelier/ls_symbols değerlerini tutsa bile
# canlı bunları kullansın (dosya kod sabitini maskeliyordu).
_apply_canli_sabitler(_AUTO_SETTINGS)
logger.info(
    "[FX SABİT] chandelier_atr_mult=%.2f, ls_symbols=%s, klasik=%s, s3=%s, ls=%s "
    "(kod sabiti — ayar dosyası/panel ezemez)",
    _AUTO_SETTINGS.chandelier_atr_mult,
    _AUTO_SETTINGS.ls_symbols,
    list(CANLI_CLASSIC_SYMBOLS),
    _AUTO_SETTINGS.s3_enabled,
    _AUTO_SETTINGS.ls_enabled,
)

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
_SYMBOL_DIR_LOSS_STREAK: Dict[Tuple[str, str], int] = {}
_SYMBOL_DIR_LOSS_COOLDOWN_UNTIL: Dict[Tuple[str, str], float] = {}
# Donchian+ADX mod durumu (yalnız dict mutasyonu — global bildirimi gerekmez)
_DONCHIAN_STATE: Dict[str, Dict[str, Any]] = {}
# EMA+ADX geri-çekilme (M5) mod durumu: gün + yön başına giriş sayacı
# (yalnız dict mutasyonu — global bildirimi gerekmez; bkz. globals-shadow testi)
_EMA_ADX_STATE: Dict[str, Dict[str, Any]] = {}
# S3 (Supertrend+RSI pullback) mod durumu: sembol+TF → gösterge seti.
# Göstergeler `_MT5_CANDLES_CACHE` broker mumlarından (yoksa Yahoo fallback) hesaplanır.
_S3_STATE: Dict[str, Dict[str, Any]] = {}
# S3 gün içi giriş sayaçları — `_S3_STATE`'ten AYRI: `_refresh_s3_state` gösterge
# dict'ini her turda değiştirdiği için sayaçlar aynı dict'te tutulursa silinir.
_S3_DAY_STATE: Dict[str, Dict[str, Any]] = {}
# London Breakout mod durumu: sembol → {"day", "box_hi", "box_lo", "counts"}.
# Kutu, tetik penceresine girişte (00:00→box_end) bir kez hesaplanır; gün değişince sıfırlanır.
_LB_STATE: Dict[str, Dict[str, Any]] = {}
# London Sign durumu: {sym: {"day": <ordinal>, "sign_open": f, "sign_close": f, "entered": bool}}.
# Sign penceresinde ilk/son kapanış bir kez hesaplanır; gün değişince sıfırlanır.
_LS_STATE: Dict[str, Dict[str, Any]] = {}
# Keltner Squeeze (M15) durumu: sembol → gösterge seti (BB/KC serileri + momentum).
# Göstergeler S3/LB/LS ile ortak broker mumlarından (fallback Yahoo) hesaplanır; gün
# sayaçları ayrı tutulur (gösterge dict'i her turda tazelenir).
_SQUEEZE_KC_STATE: Dict[str, Dict[str, Any]] = {}
_SQUEEZE_KC_DAY_STATE: Dict[str, Dict[str, Any]] = {}
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


_LAST_LOG_MSG_TIME: Dict[str, float] = {}


def _log_auto_decision(
    category: str,
    message: str,
    symbol: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    strategy: Optional[str] = None,
    strategy_label: Optional[str] = None,
):
    """Kayıt defterine otonom karar gerekçesi ekler (şeffaf izleme)."""
    now_ts = time.time()
    # Mükerrer ardışık logları engelle
    if _AUTO_STATE["decision_logs"]:
        if _AUTO_STATE["decision_logs"][0].get("message") == message:
            return

    # Çok sık tekrarlanan birebir aynı tarama mesajlarını engelle (en az 12 sn)
    if category == "SCAN":
        if now_ts - _LAST_LOG_MSG_TIME.get(message, 0.0) < 12.0:
            return
        _LAST_LOG_MSG_TIME[message] = now_ts

    now_dt = datetime.datetime.fromtimestamp(now_ts, TZ_UTC3)
    meta = dict(metadata or {})
    strat = strategy or meta.get("strategy")
    strat_lbl = strategy_label or meta.get("strategy_label")

    # Strateji belirtilmemişse mesaj içeriğinden otomatik tespit et
    if not strat:
        msg_u = message.upper()
        if "LONDON" in msg_u or "LBRK" in msg_u or "ASYA KUTUSU" in msg_u or "LONDRA" in msg_u:
            strat = LONDON_BREAKOUT_STRATEGY
            strat_lbl = LONDON_BREAKOUT_LABEL
        elif "S3" in msg_u or "SUPERTREND" in msg_u:
            strat = S3_PULLBACK_STRATEGY
            strat_lbl = S3_PULLBACK_LABEL
        elif "EMA_ADX" in msg_u or "EMA+ADX" in msg_u or "EAP" in msg_u or "EMA8" in msg_u:
            strat = EMA_ADX_PULLBACK_STRATEGY
            strat_lbl = EMA_ADX_PULLBACK_LABEL
        elif "DONCHIAN" in msg_u or "DONCH" in msg_u:
            strat = "DONCHIAN_ADX"
            strat_lbl = "Donchian ADX Kırılımı"
        elif "RADAR" in msg_u or "TARAMASI" in msg_u or "PARİTE" in msg_u:
            strat = "M1_M5_RADAR_SCALPER"
            strat_lbl = "M1/M5 Çoklu Radar"

    if strat and not strat_lbl:
        strat_lbl = strategy_display_label(strat)

    log_item = {
        "id": f"LOG-{int(now_ts * 1000) % 1000000}",
        "time": now_dt.strftime("%H:%M:%S UTC+3"),
        "created_at_ts": now_ts,
        "category": category,
        "symbol": symbol,
        "strategy": strat,
        "strategy_label": strat_lbl,
        "message": message,
        "metadata": meta,
    }
    _AUTO_STATE["decision_logs"].insert(0, log_item)
    if len(_AUTO_STATE["decision_logs"]) > 500:
        _AUTO_STATE["decision_logs"] = _AUTO_STATE["decision_logs"][:500]


def get_all_symbol_ev_status(now_ts: Optional[float] = None) -> Dict[str, Any]:
    """Tüm Forex sembollerinin canlı EV Kalkanı durumunu, bloke nedenlerini ve muafiyetlerini hesaplar."""
    if now_ts is None:
        now_ts = time.time()

    is_mt5_conn = bool(_MT5_STATE.get("connected"))
    ev_balance = float(_MT5_STATE.get("account", {}).get("balance", _AUTO_STATE["balance"])) if is_mt5_conn else float(_AUTO_STATE["balance"])
    ev_risk_usd = ev_balance * (_AUTO_SETTINGS.risk_per_trade_pct / 100.0)
    risk_floor = ev_risk_usd * _AUTO_SETTINGS.ev_loss_risk_mult
    window_sec = _AUTO_SETTINGS.ev_window_hours * 3600.0

    closed_source = list(_MT5_STATE.get("closed_deals", [])) if is_mt5_conn else list(_AUTO_STATE.get("closed_trades", []))

    # Sembol havuzu: FOREX_SYMBOLS + allowed_symbols + muafiyetli olanlar + kapalı işlemi olanlar
    symbols_set = {str(item.get("symbol", "")).upper() for item in FOREX_SYMBOLS if item.get("symbol")}
    symbols_set.update(str(s).upper() for s in _AUTO_SETTINGS.allowed_symbols)
    symbols_set.update(str(s).upper() for s in _SYMBOL_EV_OVERRIDE_UNTIL.keys())
    symbols_set.update(str(s).upper() for s in _SYMBOL_EV_RESET_AT_TS.keys())
    for d in closed_source:
        s = str(d.get("symbol", "")).upper().replace("/", "").replace("-", "").strip()
        if s:
            symbols_set.add(s)

    symbols_list: List[Dict[str, Any]] = []
    blocked_symbols: List[Dict[str, Any]] = []
    overridden_symbols: List[Dict[str, Any]] = []

    for sym in sorted(symbols_set):
        stats = _collect_symbol_ev(sym, now_ts, window_sec, source=closed_source)
        override_until = _SYMBOL_EV_OVERRIDE_UNTIL.get(sym, 0.0)
        is_overridden = now_ts < override_until
        # 2026-10-10 denetim P0-3: muafiyet gerçek kuralla hizalı — XAU her zaman muaf;
        # BTC yalnız btc_ev_exempt=True ise muaf (varsayılan False → BTC EV penceresiyle dinlenir).
        is_exempt_symbol = (sym == "XAUUSD") or (sym == "BTCUSD" and _AUTO_SETTINGS.btc_ev_exempt)

        raw_blocked = ev_guard_decision(
            stats,
            _AUTO_SETTINGS.ev_min_trades,
            _AUTO_SETTINGS.ev_max_win_rate,
            risk_floor,
        ) if not is_exempt_symbol else False

        is_effectively_blocked = raw_blocked and not is_overridden and _AUTO_SETTINGS.ev_guard_enabled

        disp = sym
        item_meta = next((i for i in FOREX_SYMBOLS if i.get("symbol") == sym), None)
        if item_meta and item_meta.get("display"):
            disp = item_meta["display"]
        elif len(sym) == 6:
            disp = f"{sym[:3]}/{sym[3:]}"

        reason = "Normal (İşleme Açık)"
        if is_exempt_symbol:
            reason = "Özel Kural (EV kalkanından muaf)"
        elif is_overridden:
            rem_m = max(1, int((override_until - now_ts) / 60))
            reason = f"Kullanıcı Tarafından Muaf Tutuldu (~{rem_m} dk kaldı)"
        elif raw_blocked:
            n = stats["n"]
            net = stats["net"]
            wr = stats["win_rate"]
            if net <= -abs(risk_floor):
                reason = f"Akut Kayıp: Net ${net:+.2f} (Eşik: -${abs(risk_floor):.2f})"
            elif wr < _AUTO_SETTINGS.ev_max_win_rate:
                reason = f"Düşük Başarı Oranı: %{wr:.0f} (Hedef min %{_AUTO_SETTINGS.ev_max_win_rate:.0f})"
            else:
                reason = "EV Kalkanı Tetiklendi"

        sym_obj = {
            "symbol": sym,
            "display": disp,
            "is_blocked": is_effectively_blocked,
            "raw_blocked": raw_blocked,
            "is_overridden": is_overridden,
            "override_until": override_until if is_overridden else None,
            "override_until_str": datetime.datetime.fromtimestamp(override_until, TZ_UTC3).strftime("%H:%M:%S UTC+3") if is_overridden else None,
            "override_remaining_sec": max(0, int(override_until - now_ts)) if is_overridden else 0,
            "n": stats["n"],
            "wins": stats["wins"],
            "losses": stats["n"] - stats["wins"],
            "win_rate": stats["win_rate"],
            "net_usd": stats["net"],
            "reason": reason,
            "is_exempt_symbol": is_exempt_symbol,
            "is_allowed": sym in _AUTO_SETTINGS.allowed_symbols,
        }

        symbols_list.append(sym_obj)
        if is_effectively_blocked:
            blocked_symbols.append(sym_obj)
        if is_overridden:
            overridden_symbols.append(sym_obj)

    # Sıralama: Önce bloke olanlar, sonra muaf olanlar, sonra işlem sayısı çok olanlar
    symbols_list.sort(key=lambda x: (not x["is_blocked"], not x["is_overridden"], -x["n"], x["net_usd"]))

    return {
        "enabled": _AUTO_SETTINGS.ev_guard_enabled,
        "window_hours": _AUTO_SETTINGS.ev_window_hours,
        "min_trades": _AUTO_SETTINGS.ev_min_trades,
        "max_win_rate": _AUTO_SETTINGS.ev_max_win_rate,
        "loss_risk_mult": _AUTO_SETTINGS.ev_loss_risk_mult,
        "risk_loss_floor_usd": round(risk_floor, 2),
        "account_balance": round(ev_balance, 2),
        "blocked_count": len(blocked_symbols),
        "overridden_count": len(overridden_symbols),
        "total_symbols": len(symbols_list),
        "blocked_symbols": blocked_symbols,
        "overridden_symbols": overridden_symbols,
        "symbols": symbols_list,
    }


# ============================================================================
# SEMBOL KAPISI ANLIK GÖRÜNÜMÜ (2026-10-10) — kokpit paneli için
# ============================================================================
# NEDEN: /forex/btc-gold kokpiti BTC'nin "neden işlem açmadığını" yalnız
# `_btc_scan_note` (karar akışına düşen tek satır) + EV listesiyle gösteriyordu.
# Operatör 18 kapılı zincirin hangi halkada takıldığını göremiyordu ve her
# panel eklentisi kuralı YENİDEN yazma riski taşıyordu.
#
# SÖZLEŞME: bu fonksiyon karar VERMEZ, yalnız ÖLÇER. Dönen kapılar döngüdeki
# (`_forex_auto_paper_loop`) kapı zinciriyle aynı sırada ve aynı yardımcı
# fonksiyonlarla (`ev_guard_decision`, `dxy_entry_veto`, `_FX_CORR.cluster_check`,
# `get_usd_bias`, `_collect_symbol_ev`) hesaplanır. Tek fark: burada HİÇBİR
# durum mutasyona uğramaz (`_LAST_BTC_EXIT_TIME` düzeltmesi gibi yan etkiler
# kopya üzerinde yapılır) — panel her 3 sn'de çağırır.
#
# Sınır: piramitleme/spread/skor kapıları döngüde ADAY bazlıdır (aday yoksa
# değerlendirilmez); burada "aday yoksa" bilgisi `action` alanından okunur ve
# o kapılar `na` (veri yok) olarak işaretlenir — yanlış "geçti" göstermektense
# "değerlendirilemedi" demek dürüsttür.
_GATE_ORDER: List[Tuple[str, str]] = [
    ("scope", "Kapsam (allowed_symbols)"),
    ("loss_streak", "Seri-SL Sigortası"),
    ("cooldown", "Sembol/BTC Soğuması"),
    ("ev_shield", "EV Kalkanı (Kayıp-Uyarlamalı)"),
    ("net_negative", "BTC Net-Negatif Freni"),
    ("dxy", "DXY Rejim Filtresi"),
    ("correlation", "Korelasyon Kalkanı"),
    ("position_limit", "Pozisyon Limitleri"),
    ("spread", "Spread Filtresi"),
    ("score", "Skor Eşiği"),
    ("adx", "ADX Trend Gücü"),
    ("supertrend", "SuperTrend Yön Teyidi"),
]


def _gate(key: str, status: str, detail: str) -> Dict[str, Any]:
    """Tek kapı kaydı. status: pass | block | na | off"""
    label = next((lbl for k, lbl in _GATE_ORDER if k == key), key)
    return {"key": key, "label": label, "status": status, "detail": detail}


def get_symbol_gate_snapshot(
    symbol: str,
    tick: Optional[Dict[str, Any]] = None,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """Bir sembolün giriş kapılarının ANLIK durumu + açık pozisyon özeti.

    Salt-okunur: motordaki hiçbir sayacı/zaman damgasını değiştirmez.
    """
    if now_ts is None:
        now_ts = time.time()
    sym = str(symbol or "").upper().strip()
    gates: List[Dict[str, Any]] = []

    is_gold = "XAU" in sym or "GOLD" in sym
    is_btc = sym == "BTCUSD"
    tick = tick or _TICK_CACHE.get(sym) or {}
    action = str(tick.get("action", "HOLD")).upper()
    if action not in ("BUY", "SELL"):
        action = ""

    # --- 0. Kapsam
    if sym in _AUTO_SETTINGS.allowed_symbols:
        gates.append(_gate("scope", "pass", "Sembol kapsam içinde"))
    else:
        gates.append(_gate("scope", "block", "Sembol allowed_symbols DIŞINDA — hiçbir sinyal işleme dönüşmez"))

    # --- 1. Seri-SL (sembol geneli + yön bazlı)
    if _AUTO_SETTINGS.loss_streak_limit <= 0:
        gates.append(_gate("loss_streak", "off", "Seri-SL sigortası kapalı (loss_streak_limit=0)"))
    else:
        limit = int(_AUTO_SETTINGS.loss_streak_limit)
        sym_until = float(_SYMBOL_LOSS_COOLDOWN_UNTIL.get(sym, 0.0))
        sym_streak = int(_SYMBOL_LOSS_STREAK.get(sym, 0))
        dir_until = 0.0
        dir_streak = 0
        if action:
            dir_until = float(_SYMBOL_DIR_LOSS_COOLDOWN_UNTIL.get((sym, action), 0.0))
            dir_streak = int(_SYMBOL_DIR_LOSS_STREAK.get((sym, action), 0))
        if now_ts < max(sym_until, dir_until):
            if dir_until > sym_until:
                detail = f"{action} yönünde {dir_streak}/{limit} ardışık kayıp — {int(dir_until - now_ts)} sn kaldı"
            else:
                detail = f"Sembolde {sym_streak}/{limit} ardışık kayıp — {int(sym_until - now_ts)} sn kaldı"
            gates.append(_gate("loss_streak", "block", detail))
        else:
            gates.append(_gate("loss_streak", "pass", f"Sayaç {sym_streak}/{limit} (kayıp serisi yok)"))

    # --- 2. Soğumalar (BTC özel + sembol geneli)
    _btc_cd = float(_AUTO_SETTINGS.btc_cooldown_sec)
    _btc_exit = float(_LAST_BTC_EXIT_TIME or 0.0)
    sym_last = float(_LAST_SYMBOL_ENTRY_TIME.get(sym, 0.0))
    sym_cd = float(_AUTO_SETTINGS.gold_cooldown_sec) if is_gold else 60.0
    btc_left = 0.0
    if is_btc and _btc_cd > 0 and _btc_exit > 0:
        btc_left = max(0.0, _btc_cd - max(0.0, now_ts - min(_btc_exit, now_ts)))
    sym_left = max(0.0, min(sym_cd, sym_cd - max(0.0, now_ts - min(sym_last, now_ts)))) if sym_last else 0.0
    if btc_left > 0 or sym_left > 0:
        parts = []
        if btc_left > 0:
            parts.append(f"BTC kapanış soğuması {int(btc_left)} sn")
        if sym_left > 0:
            parts.append(f"son girişten {int(sym_left)} sn")
        gates.append(_gate("cooldown", "block", " + ".join(parts)))
    else:
        cd_txt = f"BTC {_btc_cd:.0f} sn" if is_btc else f"sembol {sym_cd:.0f} sn"
        gates.append(_gate("cooldown", "pass", f"Soğuma yok ({cd_txt} kuralı)"))

    # --- 3. EV kalkanı
    if not _AUTO_SETTINGS.ev_guard_enabled:
        gates.append(_gate("ev_shield", "off", "EV kalkanı kapalı (ev_guard_enabled=False)"))
    elif sym == "XAUUSD":
        gates.append(_gate("ev_shield", "off", "XAUUSD TASARIM GEREĞİ muaf"))
    elif is_btc and _AUTO_SETTINGS.btc_ev_exempt:
        gates.append(_gate("ev_shield", "off", "BTC muaf (btc_ev_exempt=True — eski davranış)"))
    else:
        is_mt5_conn = bool(_MT5_STATE.get("connected"))
        ev_bal = float(_MT5_STATE.get("account", {}).get("balance", _AUTO_STATE["balance"])) if is_mt5_conn else float(_AUTO_STATE["balance"])
        risk_floor = ev_bal * (_AUTO_SETTINGS.risk_per_trade_pct / 100.0) * _AUTO_SETTINGS.ev_loss_risk_mult
        stats = _collect_symbol_ev(sym, now_ts, _AUTO_SETTINGS.ev_window_hours * 3600.0)
        overridden = now_ts < _SYMBOL_EV_OVERRIDE_UNTIL.get(sym, 0.0)
        blocked = ev_guard_decision(stats, _AUTO_SETTINGS.ev_min_trades,
                                    _AUTO_SETTINGS.ev_max_win_rate, risk_floor)
        base = (f"Son {int(_AUTO_SETTINGS.ev_window_hours)}s: {stats['n']} işlem, "
                f"net ${stats['net']:+.2f}, WR %{stats['win_rate']:.0f}")
        if overridden:
            gates.append(_gate("ev_shield", "off", f"Operatör muafiyeti aktif — {base}"))
        elif blocked:
            reason = (f"akut kayıp (eşik -${abs(risk_floor):.2f})" if stats["net"] <= -abs(risk_floor)
                      else f"WR %{stats['win_rate']:.0f} < %{_AUTO_SETTINGS.ev_max_win_rate:.0f}")
            gates.append(_gate("ev_shield", "block", f"{reason} — {base}"))
        else:
            need = max(0, int(_AUTO_SETTINGS.ev_min_trades) - int(stats["n"]))
            tail = f" — tetik için {need} işlem daha gerekli" if need else ""
            gates.append(_gate("ev_shield", "pass", f"{base}{tail}"))

    # --- 4. BTC net-negatif freni
    if not is_btc:
        gates.append(_gate("net_negative", "off", "Yalnız BTCUSD için tanımlı"))
    elif not _AUTO_SETTINGS.btc_net_negative_guard_enabled:
        gates.append(_gate("net_negative", "off", "Fren kapalı (btc_net_negative_guard_enabled=False)"))
    else:
        wh = float(_AUTO_SETTINGS.btc_net_negative_window_hours)
        stats = _collect_symbol_ev(sym, now_ts, wh * 3600.0)
        n_ok = stats["n"] >= int(_AUTO_SETTINGS.btc_net_negative_min_trades)
        net_bad = stats["net"] < float(_AUTO_SETTINGS.btc_net_negative_usd)
        base = f"Son {wh:.0f}s: {stats['n']} işlem, net ${stats['net']:+.2f}"
        if n_ok and net_bad:
            gates.append(_gate("net_negative", "block", f"{base} — BTC yeni giriş almıyor"))
        else:
            gates.append(_gate("net_negative", "pass", f"{base} (eşik: {int(_AUTO_SETTINGS.btc_net_negative_min_trades)} işlem)"))

    # --- 5. DXY
    dxy = get_dxy_regime()
    if not _AUTO_SETTINGS.dxy_filter_enabled:
        gates.append(_gate("dxy", "off", "DXY filtresi kapalı"))
    elif action:
        veto = dxy_entry_veto(sym, action, dxy)
        regime = (dxy or {}).get("regime", "—")
        if veto == "dxy_conflict":
            gates.append(_gate("dxy", "block", f"{action} yönü dolar rejimiyle ({regime}) çelişiyor"))
        elif veto == "dxy_no_data":
            gates.append(_gate("dxy", "block", "DXY verisi yok — majör parite girişi engellendi"))
        elif veto == "dxy_strict_neutral":
            gates.append(_gate("dxy", "pass", f"Nötr rejim ({regime}) — skor eşiğine +5.0 ek yük"))
        else:
            gates.append(_gate("dxy", "pass", f"Rejim {regime} ile uyumlu"))
    else:
        gates.append(_gate("dxy", "na", "Yön teyidi yok — DXY kapısı değerlendirilemedi"))

    # --- 6. Korelasyon
    if not _AUTO_SETTINGS.correlation_guard:
        gates.append(_gate("correlation", "off", "Korelasyon kalkanı kapalı"))
    elif action:
        bias = get_usd_bias(sym, action)
        if bias == "USD_NEUTRAL":
            gates.append(_gate("correlation", "off", "USD_NEUTRAL — kalkan kapsamı dışı"))
        else:
            corr_positions: List[tuple] = []
            for p in list(_MT5_STATE.get("open_positions", [])) + list(_AUTO_STATE.get("open_positions", [])):
                corr_positions.append((str(p.get("symbol", "")).upper(),
                                       get_usd_bias(p.get("symbol", ""), p.get("direction", "BUY"))))
            for c in _MT5_STATE.get("pending_commands", []):
                if c.get("action") == "OPEN_ORDER":
                    corr_positions.append((str(c.get("symbol", "")).upper(),
                                           get_usd_bias(c.get("symbol", ""), c.get("direction", "BUY"))))
            ok, reason = _FX_CORR.cluster_check(sym, bias, corr_positions)
            if ok:
                gates.append(_gate("correlation", "pass", f"{bias} — çakışan küme yok"))
            else:
                gates.append(_gate("correlation", "block", f"{bias} çakışması: {reason}"))
    else:
        gates.append(_gate("correlation", "na", "Yön teyidi yok — korelasyon kapısı değerlendirilemedi"))

    # --- 7. Pozisyon limitleri (açık/kuyruk)
    mt5_open = list(_MT5_STATE.get("open_positions", []))
    auto_open = list(_AUTO_STATE.get("open_positions", []))
    pending = [c for c in _MT5_STATE.get("pending_commands", []) if c.get("action") == "OPEN_ORDER"]
    active_count = len(mt5_open) if _MT5_STATE.get("connected") else len(auto_open)
    sym_open = [p for p in mt5_open + auto_open if str(p.get("symbol", "")).upper() == sym]
    sym_pending = [c for c in pending if str(c.get("symbol", "")).upper() == sym]
    max_open = int(_AUTO_SETTINGS.max_open_positions)
    if active_count >= max_open:
        gates.append(_gate("position_limit", "block", f"Açık pozisyon tavanı dolu ({active_count}/{max_open})"))
    elif sym_pending:
        gates.append(_gate("position_limit", "block",
                           f"{sym} için gönderilmiş emrin işlem görmesi bekleniyor ({len(sym_pending)} adet)"))
    elif sym_open:
        max_pyr = int(_AUTO_SETTINGS.max_positions_per_symbol)
        gates.append(_gate("position_limit", "block",
                           f"{sym} açık pozisyon var ({len(sym_open)}/{max_pyr}) — yalnız kârda piramitleme"))
    else:
        gates.append(_gate("position_limit", "pass", f"{active_count}/{max_open} açık, {sym} için engel yok"))

    # --- 8. Spread
    spread = float(tick.get("spread_pips", 0.0) or 0.0)
    eff_max_spread = max(50.0, _AUTO_SETTINGS.max_spread_pips * 10) if ("BTC" in sym or "ETH" in sym) else float(_AUTO_SETTINGS.max_spread_pips)
    if spread <= 0:
        gates.append(_gate("spread", "na", "Spread verisi yok"))
    elif spread > eff_max_spread:
        gates.append(_gate("spread", "block", f"{spread:.1f}p > {eff_max_spread:.1f}p limit"))
    else:
        gates.append(_gate("spread", "pass", f"{spread:.1f}p / {eff_max_spread:.1f}p"))

    # --- 9. Skor
    score = float(tick.get("score", 0.0) or 0.0)
    req_score = required_entry_score(sym)
    thr_lbl = f"{'btc_min_score' if sym == 'BTCUSD' else 'min_score'} {req_score:.0f}"
    if score <= 0:
        gates.append(_gate("score", "na", "Skor verisi yok"))
    elif score < req_score:
        gates.append(_gate("score", "block", f"{score:.1f} < {req_score:.0f} ({thr_lbl})"))
    else:
        gates.append(_gate("score", "pass", f"{score:.1f} ≥ {req_score:.0f} ({thr_lbl})"))

    # --- 10. ADX
    adx = float(tick.get("adx", 0.0) or 0.0)
    if not _AUTO_SETTINGS.adx_filter_enabled:
        gates.append(_gate("adx", "off", f"ADX kalkanı kapalı (ADX {adx:.0f})"))
    elif adx < float(_AUTO_SETTINGS.adx_min):
        gates.append(_gate("adx", "block", f"ADX {adx:.0f} < {_AUTO_SETTINGS.adx_min:.0f} — trend gücü zayıf"))
    else:
        gates.append(_gate("adx", "pass", f"ADX {adx:.0f} ≥ {_AUTO_SETTINGS.adx_min:.0f}"))

    # --- 11. SuperTrend (yalnız klasik/radar adayı için geçerli; s3/EAP kendi yön motorunu taşır)
    st_dir = int(tick.get("supertrend_dir", 0) or 0)
    if not _AUTO_SETTINGS.supertrend_filter_enabled:
        gates.append(_gate("supertrend", "off", "SuperTrend teyidi kapalı"))
    elif not action or st_dir == 0:
        gates.append(_gate("supertrend", "na", "Yön teyidi yok — teyit kapısı değerlendirilemedi"))
    elif supertrend_blocks_entry("", action, st_dir):
        gates.append(_gate("supertrend", "block",
                           f"{action} yönü SuperTrend ({'BOĞA' if st_dir > 0 else 'AYI'}) ile ters"))
    else:
        gates.append(_gate("supertrend", "pass",
                           f"{action} yönü SuperTrend ({'BOĞA' if st_dir > 0 else 'AYI'}) ile uyumlu"))

    # --- Özet: ilk BLOKE eden kapı = operatörün görmek istediği tek cümle
    first_block = next((g for g in gates if g["status"] == "block"), None)
    if not _AUTO_STATE["enabled"]:
        verdict = "Otonom motor DURDURULDU — kapılar değerlendirilmiyor"
        verdict_level = "stopped"
    elif first_block:
        verdict = f"Takıldığı kapı: {first_block['label']} — {first_block['detail']}"
        verdict_level = "blocked"
    elif not action:
        verdict = "Tüm kapılar açık; ancak yön teyidi (BUY/SELL) oluşmadı — gözlemde"
        verdict_level = "idle"
    else:
        verdict = f"Tüm kapılar açık — {action} sinyali işleme hazır"
        verdict_level = "ready"

    return {
        "symbol": sym,
        "generated_at": now_ts,
        "action": action,
        "verdict": verdict,
        "verdict_level": verdict_level,
        "blocking_gate": (first_block["key"] if first_block else None),
        "gates": gates,
        "open_positions": [
            {
                "ticket": p.get("ticket"),
                "direction": str(p.get("direction", "")).upper(),
                "lots": float(p.get("lots", 0.0) or 0.0),
                "entry_price": float(p.get("entry_price", p.get("price", 0.0)) or 0.0),
                "current_price": float(p.get("current_price", 0.0) or 0.0),
                "sl_price": float(p.get("sl_price", 0.0) or 0.0),
                "tp_price": float(p.get("tp_price", 0.0) or 0.0),
                "pnl_usd": float(p.get("pnl_usd", p.get("profit", 0.0)) or 0.0),
                "pnl_pips": float(p.get("pnl_pips", 0.0) or 0.0),
                "breakeven_activated": bool(p.get("breakeven_activated")),
                "trailing_activated": bool(p.get("trailing_activated")),
                "open_time": p.get("open_time", ""),
                "strategy_label": strategy_display_label(p.get("entry_source") or p.get("strategy")),
            }
            for p in (mt5_open + auto_open)
            if str(p.get("symbol", "")).upper() == sym
        ],
        "settings": {
            # Not: skor EŞİKLERİ buraya konmaz — motorda BTC için btc_min_score,
            # XAU için SABİT 78.0 geçerlidir. Kokpit ikisini de kapı cümlesinden
            # okur ("50.8 < 78 (min_score 78)"), böylece eşik iki yerde tutulmaz.
            "gold_cooldown_sec": float(_AUTO_SETTINGS.gold_cooldown_sec),
            "btc_min_score": float(_AUTO_SETTINGS.btc_min_score),
            "btc_cooldown_sec": float(_AUTO_SETTINGS.btc_cooldown_sec),
            "btc_ev_exempt": bool(_AUTO_SETTINGS.btc_ev_exempt),
            "btc_net_negative_guard_enabled": bool(_AUTO_SETTINGS.btc_net_negative_guard_enabled),
            "crypto_sl_atr_mult": float(_AUTO_SETTINGS.crypto_sl_atr_mult),
            "crypto_tp_enabled": bool(_AUTO_SETTINGS.crypto_tp_enabled),
            "crypto_risk_clamp_enabled": bool(_AUTO_SETTINGS.crypto_risk_clamp_enabled),
            "loss_streak_limit": int(_AUTO_SETTINGS.loss_streak_limit),
            "max_positions_per_symbol": int(_AUTO_SETTINGS.max_positions_per_symbol),
            "supertrend_filter_enabled": bool(_AUTO_SETTINGS.supertrend_filter_enabled),
            "adx_filter_enabled": bool(_AUTO_SETTINGS.adx_filter_enabled),
        },
    }


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
            "EOD_TIME": "⏰ Zaman Sınırı (EoD)",
            "S3_ST_FLIP": "🧭 S3 SuperTrend Dönüşü",
        }
        human_reason = reason_titles.get(reason, reason)
        # Bakiye YALNIZ kalan bacakla ilerler: kısmi kâr döngüde kredilenmişti,
        # `pnl_usd` ise kayıt için toplamı taşıyor (yukarıya bkz.).
        bal_after = round(_AUTO_STATE["balance"] + remaining_pnl_usd, 2)

        now_dt = datetime.datetime.fromtimestamp(now_time, TZ_UTC3)
        _strat = target.get("strategy") or strategy_name_for(target.get("entry_source"))
        _strat_lbl = target.get("strategy_label") or strategy_display_label(_strat)

        closed_item = {
            **target,
            "strategy": _strat,
            "strategy_label": _strat_lbl,
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

        # Seri-SL sigortası: sembol ve yön ardışık kayıplarını izle
        streak_sym = target.get("symbol", "").upper()
        streak_dir = target.get("direction", "").upper()
        feed_loss_streak_from_deal(streak_sym, reason, pnl_usd, streak_dir)

        _log_auto_decision(
            "EXIT",
            f"{target.get('display', target.get('symbol', ''))} [{_strat_lbl}] {human_reason} ile kapandı: ${pnl_usd:+.2f} ({pnl_pips:+.1f} pip)",
            symbol=target["symbol"],
            strategy=_strat,
            strategy_label=_strat_lbl,
            metadata={"pnl_usd": pnl_usd, "pnl_pips": pnl_pips, "reason": reason, "strategy": _strat, "strategy_label": _strat_lbl},
        )

        # Pozisyon kapandı: durum değişti, `/status` önbelleği bayat kalmasın.
        _invalidate_status_cache()

        # Tüm semboller için evrensel çıkış zamanı ve yönü
        sym_closed = target.get("symbol", "").upper()
        now_exit_ts = time.time()
        _LAST_SYMBOL_EXIT_TIME[sym_closed] = now_exit_ts
        _LAST_SYMBOL_EXIT_DIR[sym_closed] = target.get("direction", "").upper()

        # Zararlı kapanış veya stop durumunda sembol bazlı soğuma kaydı (Seri Kayıp Kalkanı)
        if reason in ("SL_HIT", "BE_HIT", "Scalper Close") or pnl_usd < 0:
            _LAST_SYMBOL_LOSS_TIME[sym_closed] = now_exit_ts

        # Altın veya BTC pozisyonu kapandığında geriye uyumluluk sayacını başlat
        if "XAU" in sym_closed or "GOLD" in sym_closed:
            global _LAST_GOLD_EXIT_TIME
            _LAST_GOLD_EXIT_TIME = now_exit_ts
        if "BTC" in sym_closed:
            global _LAST_BTC_EXIT_TIME
            _LAST_BTC_EXIT_TIME = now_exit_ts

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
        return str(gold_tick.get("direction_guard_reason") or "yön teyidi oluşmadı — gözlemde")
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
    if float(gold_tick.get("score", 0.0)) < required_entry_score("XAUUSD"):
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
        # 2026-10-10 denetim P2-6: 60 sn sabit kodluydu; panelden ayarlanan
        # btc_cooldown_sec farklıysa panel yanlış süre gösteriyordu.
        _btc_note_cd = float(_AUTO_SETTINGS.btc_cooldown_sec)
        time_since_btc = max(0.0, now_ts - _LAST_BTC_EXIT_TIME)
        cd_left = max(0.0, min(_btc_note_cd, _btc_note_cd - time_since_btc))
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



def _build_modify_sltp_cmd(cmd_id: str, ticket: int, pos: Dict[str, Any],
                           mirror_tp: float) -> Dict[str, Any]:
    """Paper SL güncellemesini MT5 MODIFY_SLTP komutuna çevirir (tek yol, tek semantik).

    Kural: paper tarafında `tp_price=0` ise (TP iptal edilmiş/tp'siz mod) köprüye
    explicit `tp_action="cancel"` gider — çıplak `tp=0` köprüde "mevcut TP'yi koru"
    demektir ve iptal sessizce kaybolurdu. Aksi hâlde TP aynası (`mirror_tp`)
    aynen taşınır. Bu fonksiyon, bir pozisyonun TP'si bir kez iptal edildikten
    sonra sonraki SL güncellemelerinin TP'yi geri diriltmemesini de garanti eder.
    """
    tp_now = float(pos.get("tp_price", 0.0) or 0.0)
    cmd: Dict[str, Any] = {
        "id": cmd_id,
        "action": "MODIFY_SLTP",
        "ticket": ticket,
        "sl": pos["sl_price"],
        "tp": float(mirror_tp or 0.0) if tp_now > 0 else 0.0,
    }
    if tp_now <= 0:
        cmd["tp_action"] = "cancel"
    return cmd


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
                    # GİRİŞ ATR'si — chandelier paritesi. Replay trailing'i girişte
                    # dondurulmuş ATR ile hesaplar (forex_replay_backtest.py:1828);
                    # canlı eskiden her tick CARİ ATR'yi kullanıyordu, bu yüzden ATR
                    # sıçradığında trailing mesafesi işlem ortasında genişleyip kazanılan
                    # pip'i geri veriyordu (canlı↔replay ayrık). Alan ilk turda yazılır,
                    # pozisyon ömrü boyunca sabit kalır; kalıcılık yoksa cari ATR'ye düşülür.
                    if atr_pips > 0 and not pos.get("entry_atr_pips"):
                        pos["entry_atr_pips"] = atr_pips
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

                    # (a-) S3 5m kol ST-flip çıkışı: stratejinin kendi yön motoru (ST 10,3)
                    # tersine döndüyse pozisyon tutulmaz (replay --st-flip-exit kanıtı).
                    # MT5 biletli pozisyonda da CLOSE_ORDER komutu kuyruğa girer.
                    if str(pos.get("entry_source", "")) == "s3_5m" and _AUTO_SETTINGS.s3_enabled:
                        _s3_flip_tech = _S3_STATE.get(f"{sym}|5m")
                        if _s3_flip_tech:
                            _s3_st = int(_s3_flip_tech.get("st_dir", 0))
                            if _s3_st != 0 and ((direction == "BUY" and _s3_st < 0) or (direction == "SELL" and _s3_st > 0)):
                                positions_to_close.append((pos["id"], "S3_ST_FLIP", cur_p))
                                _log_auto_decision(
                                    "EXIT",
                                    f"🧭 [{pos.get('display', sym)}] {S3_PULLBACK_LABEL} ST-flip çıkışı: SuperTrend yönü tersine döndü "
                                    f"({'BOĞA' if _s3_st > 0 else 'AYI'}) — pozisyon kapatılıyor.",
                                    symbol=sym,
                                )
                                continue

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
                            # 2026-10-14 kollar — varsayılanları mevcut davranışı korur.
                            mfe_pips=float(pos.get("mfe_pips", 0.0) or 0.0),
                            use_mfe_lock=bool(_AUTO_SETTINGS.be_lock_from_mfe),
                            be_trigger_atr_mult=float(_AUTO_SETTINGS.be_trigger_atr_mult),
                            be_trigger_r_mult=float(_AUTO_SETTINGS.be_trigger_r_mult),
                            be_trigger_atr_mult_gold=float(_AUTO_SETTINGS.be_trigger_atr_mult_gold),
                            be_trigger_atr_mult_crypto=float(_AUTO_SETTINGS.be_trigger_atr_mult_crypto),
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
                                            _MT5_STATE["pending_commands"].append(
                                                _build_modify_sltp_cmd(
                                                    f"CMD-MODIFY-{m_t}-BE", m_t, pos,
                                                    mpos.get("tp_price", 0.0),
                                                )
                                            )
                                            _log_auto_decision("PROTECT", f"🛡️ [MT5] {sym} Bilet #{m_t} Başabaş Stopu {pos['sl_price']} olarak kilitlendi.", symbol=sym)

                    # (b) İZ SÜREN STOP (TRAILING STOP) DENETİMİ
                    # Sembole ve volatiliteye (ATR) göre trailing mesafesi
                    # BE kilitlendikten sonra VEYA pnl_pips >= eff_trail_pips olduğunda fiyatı arkasından takip et
                    #
                    # 2026-10-14 (Kol C): kapı `chandelier_gate_independent` ile BE'den
                    # bağımsızlaştırılabilir. Açıkken chandelier, MFE > mult×giriş ATR'si olur
                    # olmaz kurulur (BE beklemez) — aksi hâlde XAU'da MFE > 0.75 ATR altındaki
                    # tüm hareketlerde ölü kalıyor (ölçülen tepe medyanı 0.63 ATR).
                    _chand_indep_armed = False
                    if bool(_AUTO_SETTINGS.chandelier_gate_independent):
                        _cm_gate = float(_AUTO_SETTINGS.chandelier_atr_mult or 0.0)
                        _ca_gate = resolve_chandelier_atr(pos.get("entry_atr_pips"), atr_pips)
                        _mf_gate = float(pos.get("mfe_pips", 0.0) or 0.0)
                        _chand_indep_armed = (_cm_gate > 0 and _ca_gate > 0
                                              and _mf_gate > _cm_gate * _ca_gate)
                    if pos.get("breakeven_activated") or pnl_pips >= eff_trail_pips or _chand_indep_armed:
                        chand_mult = float(_AUTO_SETTINGS.chandelier_atr_mult or 0.0)
                        pos_mfe = float(pos.get("mfe_pips", 0.0) or 0.0)
                        # Replay paritesi: trailing GİRİŞ ATR'siyle hesaplanır, cari ATR ile
                        # değil. Alan yoksa (eski pozisyon / ilk tur yazılmamış) cari ATR'ye düş.
                        chand_atr = resolve_chandelier_atr(pos.get("entry_atr_pips"), atr_pips)
                        updated_trail = False
                        if chand_mult > 0 and chand_atr > 0 and pos_mfe > 0:
                            # Chandelier: kâr tepesinden chand_mult×ATR(giriş) geri verilince kilit
                            cand_pips = pos_mfe - (chand_mult * chand_atr)
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

                        # (b2) TP İPTALİ — trailing devreye girdiğinde sabit TP emri çekilir
                        # (V03 "no_tp_on_trail_live" mekanizması; canlı VARSAYILAN AÇIK).
                        # Neden: TP kazananı erken kesiyordu; TP silinince trend koşusu
                        # trailing/BE kilidiyle taşınır (2026-10-09 4 pencere A/B IS/OOS/OOS2/F1:
                        # +$201/+$215/+$65/+$170, işaret-tutarlı tek mekanizma; ADX-trail ve
                        # TP-ratchet pencereler arası işaret değiştirdiği için EKLENMEDİ).
                        # tp_price=0 yapılınca (c) TP_HIT dalı bir daha ateşlemez (kripto TP'siz
                        # moduyla aynı semantik). Beklemede olan bir tur önce kuyruğa girmiş MT5
                        # MODIFY_SLTP komutunda hâlâ eski tp duruyorsa, aşağıdaki cancel komutu onu
                        # sırayla geçersiz kılar. Kapsam: forex/MT5 motorundaki TÜM semboller
                        # (chandelier VE sabit-pip trail, ikisi de `updated_trail` set eder).
                        # Kripto (BTCUSD/ETHUSD) zaten TP'siz açılır (crypto_tp_enabled=False)
                        # → etkisiz; ayrı auto_paper motoru TP-ratchet kullanır, dokunulmadı.
                        if (updated_trail and _AUTO_SETTINGS.tp_cancel_on_trail
                                and float(pos.get("tp_price", 0.0) or 0.0) > 0):
                            pos["tp_price"] = 0.0
                            _log_auto_decision(
                                "PROTECT",
                                f"{pos['display']} 🎯 Sabit TP iptal edildi — trailing aktif, kazanç "
                                f"trailing/BE kilidiyle taşınacak (kâr +{pnl_pips:.1f} pip).",
                                symbol=sym,
                            )

                        # MT5 açık biletinde de Stop Loss seviyesini dinamik olarak yukarı sür
                        if updated_trail and _MT5_STATE.get("connected") and _MT5_STATE.get("auto_trade"):
                            # Yalnız bu pozisyonun bağlı olduğu MT5 bileti güncellenir;
                            # paper kaydı (mt5_ticket yok) MT5'e dokunamaz (#7).
                            trail_ticket = pos.get("mt5_ticket")
                            for mpos in _MT5_STATE.get("open_positions", []):
                                if trail_ticket and mpos.get("ticket") == trail_ticket:
                                    t_id = mpos.get("ticket")
                                    if t_id:
                                        # TP iptal edildiyse ayna değeri (mpos tp_price) KULLANILMAZ;
                                        # explicit cancel semantiği taşınır (bkz. _build_modify_sltp_cmd).
                                        _MT5_STATE["pending_commands"].append(
                                            _build_modify_sltp_cmd(
                                                f"CMD-MODIFY-{t_id}-TR", t_id, pos,
                                                mpos.get("tp_price", 0.0),
                                            )
                                        )

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
                    # (f) EoD ZAMAN-STOPU (London Sign spec): pozisyon taşıma süresi
                    #     `hold_minutes`ı aştıysa bar kapanışı beklenmeden kapatılır.
                    #     Swap/gece riskini keser; SL/TP/trail önce değerlendirildiği için
                    #     yalnız "hiçbiri tetiklenmediyse" devreye girer.
                    elif int(pos.get("hold_minutes", 0) or 0) > 0 and \
                            (now_ts - float(pos.get("opened_at_ts", now_ts) or now_ts)) >= \
                            int(pos.get("hold_minutes", 0) or 0) * 60.0:
                        positions_to_close.append((pos["id"], "EOD_TIME", cur_p))

            # Pozisyonları kapat
            for pid, rsn, p_exit in positions_to_close:
                await _close_position_internal(pid, rsn, p_exit)

            # S3 5m ST-flip: MT5 yoluyla açılmış pozisyonlar (paper kaydı yok) da
            # aynı çıkış kuralına tabidir — pozisyon `strategy_tag` (emir yorumu)
            # "S3" ile başlıyorsa ST yön tersine döndüğünde CLOSE_ORDER kuyruğa girer.
            if _AUTO_SETTINGS.s3_enabled and _MT5_STATE.get("connected"):
                for mpos in list(_MT5_STATE.get("open_positions", [])):
                    m_sym = str(mpos.get("symbol", "")).upper()
                    m_tag = str(mpos.get("strategy_tag", "") or "").strip().upper()
                    if not m_tag.startswith("S3") or "S3F" in m_tag:
                        continue
                    m_t = mpos.get("ticket")
                    if not m_t:
                        continue
                    already_closing = any(
                        c.get("ticket") == m_t and c.get("action") == "CLOSE_ORDER"
                        for c in _MT5_STATE.get("pending_commands", [])
                    )
                    if already_closing:
                        continue
                    _s3_m_tech = _S3_STATE.get(f"{m_sym}|5m")
                    if not _s3_m_tech:
                        continue
                    _s3_m_st = int(_s3_m_tech.get("st_dir", 0))
                    m_dir = str(mpos.get("direction", "")).upper()
                    if _s3_m_st != 0 and ((m_dir == "BUY" and _s3_m_st < 0) or (m_dir == "SELL" and _s3_m_st > 0)):
                        _MT5_STATE["pending_commands"].append({
                            "id": f"CMD-CLOSE-{m_t}-S3FLIP",
                            "action": "CLOSE_ORDER",
                            "ticket": m_t,
                        })
                        _log_auto_decision(
                            "EXIT",
                            f"🧭 [MT5] {mpos.get('display', m_sym)} Bilet #{m_t} {S3_PULLBACK_LABEL} ST-flip çıkışı: "
                            f"SuperTrend tersine döndü ({'BOĞA' if _s3_m_st > 0 else 'AYI'}).",
                            symbol=m_sym,
                        )

            # London Sign EoD zaman-stopu — MT5 yoluyla açılmış (paper kaydı olmayan)
            # pozisyonlar için: emir yorumu "LSGN" ile başlıyorsa ve pozisyon
            # ls_hold_hours'ı aştıysa CLOSE_ORDER kuyruğa girer (paper yolunun (f) dalıyla
            # aynı semantik). `open_ts` köprüden taşınır (broker sunucu zamanı düzeltilmiş).
            if _AUTO_SETTINGS.ls_enabled and _MT5_STATE.get("connected"):
                _ls_hold_sec = float(_AUTO_SETTINGS.ls_hold_hours) * 3600.0
                if _ls_hold_sec > 0:
                    for mpos in list(_MT5_STATE.get("open_positions", [])):
                        m_sym = str(mpos.get("symbol", "")).upper()
                        m_tag = str(mpos.get("strategy_tag", "") or "").strip().upper()
                        if not m_tag.startswith("LSGN"):
                            continue
                        m_t = mpos.get("ticket")
                        m_open_ts = float(mpos.get("open_ts", 0) or 0)
                        if not m_t or m_open_ts <= 0:
                            continue
                        if m_open_ts > now_ts + 600:
                            m_open_ts -= max(0.0, round((m_open_ts - now_ts) / 3600.0) * 3600.0)
                        if now_ts - m_open_ts < _ls_hold_sec:
                            continue
                        already_closing = any(
                            c.get("ticket") == m_t and c.get("action") == "CLOSE_ORDER"
                            for c in _MT5_STATE.get("pending_commands", [])
                        )
                        if already_closing:
                            continue
                        _MT5_STATE["pending_commands"].append({
                            "id": f"CMD-CLOSE-{m_t}-EOD",
                            "action": "CLOSE_ORDER",
                            "ticket": m_t,
                        })
                        _log_auto_decision(
                            "EXIT",
                            f"⏰ [MT5] {mpos.get('display', m_sym)} Bilet #{m_t} {LONDON_SIGN_LABEL} EoD çıkışı: "
                            f"taşıma süresi {_AUTO_SETTINGS.ls_hold_hours:.1f} saati aştı.",
                            symbol=m_sym,
                        )

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

            # Radar Sinyallerini Al — işlem kararı taze veriyle alınır (önbellek yok).
            radar_res = await get_forex_radar(use_cache=False)
            candidates = radar_res.get("candidates", [])
            dxy_regime = radar_res.get("dxy")
            arm_rows: List[Dict[str, Any]] = []
            _opened_cycle: set = set()

            # Donchian+ADX giriş modu (2026-10-07 kalibrasyonu): mode_symbols için radar
            # adayına EK aday üretir; mode_exclusive sembollerin klasik adayları düşürülür.
            _mode_syms = {s.upper() for s in (_AUTO_SETTINGS.mode_symbols or [])}
            _mode_excl = {s.upper() for s in (_AUTO_SETTINGS.mode_exclusive or [])}
            _classic_ok = {s.upper() for s in CANLI_CLASSIC_SYMBOLS}
            # Klasik adaylar yalnız kanıtlı dörtlüde kalır. Diğer kollar (EMA, Squeeze,
            # London Breakout, Donchian) kendi sembol listeleriyle aşağıda eklenir.
            candidates = [
                c for c in candidates
                if str(c.get("symbol", "")).upper() in _classic_ok
            ]
            if _mode_excl:
                candidates = [c for c in candidates if str(c.get("symbol", "")).upper() not in _mode_excl]
            if _mode_syms:
                for _m_sym in _mode_syms:
                    _m_t = ticks.get(_m_sym)
                    _m_tech = _TECHNICAL_CACHE.get(_m_sym) or {}
                    if not _m_t or not _m_tech or _m_tech.get("donch_mid") is None or not _m_tech.get("signal_bar_confirmed"):
                        continue
                    _m_bar = int(_m_tech.get("signal_bar_time") or 0)
                    _m_price = float(_m_tech.get("price") or 0.0)
                    _m_pip_size = _m_tech.get("pip_size") or next((i["pip_size"] for i in FOREX_SYMBOLS if i["symbol"] == _m_sym), 0.0001)
                    if _m_price <= 0 or _m_pip_size <= 0 or _m_bar <= 0:
                        continue
                    _m_now = datetime.datetime.now(datetime.timezone.utc)
                    _m_day = _m_now.toordinal()
                    _m_st = _DONCHIAN_STATE.setdefault(_m_sym, {"prev_close": None, "prev_mid": None, "day": _m_day, "counts": {}, "cursor_bar": 0})
                    if _m_st["day"] != _m_day:
                        _m_st["day"] = _m_day
                        _m_st["counts"] = {}
                    if int(_m_st.get("consumed_bar") or 0) == _m_bar:
                        continue
                    if int(_m_st.get("cursor_bar") or 0) != _m_bar:
                        if _m_st.get("cursor_close") is not None:
                            _m_st["prev_close"] = _m_st.get("cursor_close")
                            _m_st["prev_mid"] = _m_st.get("cursor_mid")
                        _m_st["cursor_bar"] = _m_bar
                        _m_st["cursor_close"] = _m_price
                        _m_st["cursor_mid"] = float(_m_tech["donch_mid"])
                    _m_action = donchian_adx_entry(
                        prev_close=_m_st["prev_close"], prev_mid=_m_st["prev_mid"],
                        close=_m_price, mid=float(_m_tech["donch_mid"]),
                        adx=float(_m_tech.get("adx", 0.0)), adx_min=float(_AUTO_SETTINGS.donchian_adx_min),
                        day=_m_day, day_counts=_m_st["counts"], max_per_day=int(_AUTO_SETTINGS.donchian_max_per_day),
                        hour_utc=_m_now.hour, is_jpy=("JPY" in _m_sym.upper()),
                    )
                    if _m_action:
                        _m_atr = float(_m_tech.get("atr", 0.0))
                        _m_item = next((i for i in FOREX_SYMBOLS if i["symbol"] == _m_sym), None)
                        arm_rows.append({
                            "symbol": _m_sym,
                            "display": _m_item["display"] if _m_item else _m_sym,
                            "action": _m_action,
                            "score": float(_m_tech.get("score") or 0.0),
                            "spread_pips": float(_m_t.get("spread_pips", 0.0) or 0.0),
                            "atr_pips": round(_m_atr / _m_pip_size, 1) if _m_pip_size > 0 else 15.0,
                            "adx": float(_m_tech.get("adx", 0.0)),
                            "supertrend_dir": int(_m_tech.get("supertrend_dir", 0)),
                            "entry_source": "donchian",
                            "signal_bar_time": _m_bar,
                            "signal_bar_confirmed": True,
                            "_arm_quota": {"kind": "donchian", "symbol": _m_sym, "action": _m_action, "bar_time": _m_bar},
                        })
                        _log_auto_decision(
                            "SCAN",
                            f"🎯 [{_m_item['display'] if _m_item else _m_sym}] Donchian kırılımı: {_m_action} adayı (ADX {_m_tech.get('adx', 0):.0f}) — değerlendiriliyor.",
                            symbol=_m_sym,
                            strategy="DONCHIAN_ADX",
                            strategy_label="Donchian ADX Kırılımı",
                        )
                    else:
                        # Görünürlük: mod ne beklediğini 25 sn'de bir insan-okur cümleyle söyler;
                        # kapsam dışıysa bunu da açıkça yazar (sessiz blok yok).
                        _m_not_allowed = _m_sym not in {s.upper() for s in (_AUTO_SETTINGS.allowed_symbols or [])}
                        _m_wait_throttled = now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{_m_sym}_donch_wait", 0.0) > 25.0
                        if _m_wait_throttled:
                            _LAST_CANDIDATE_LOG_TIME[f"{_m_sym}_donch_wait"] = now_ts
                            _m_disp = _m_t["display"] if _m_t else _m_sym
                            _m_side = "üstünde" if _m_price > float(_m_tech["donch_mid"]) else "altında"
                            if _m_not_allowed:
                                _log_auto_decision(
                                    "SCAN",
                                    f"⚠️ [{_m_disp}] Donchian modu aktif AMA sembol panel kapsamında değil (allowed_symbols) — işlem için panele eklenmeli.",
                                    symbol=_m_sym,
                                    strategy="DONCHIAN_ADX",
                                    strategy_label="Donchian ADX Kırılımı",
                                )
                            else:
                                # 2026-10-10 denetim P2-1: log gerçek kapıyı söylemeli — eskiden
                                # None dönüşü her zaman "orta hat kesişimi bekleniyor" diye yazılıyor,
                                # ADX-altı/seans/gün-limiti gerçek sebepken yanıltıyordu.
                                # Ayrıca log ADX varsayılanı (0) karar varsayılanıyla (25.0) çelişiyordu.
                                _m_adx_val = float(_m_tech.get("adx", 25.0))
                                _m_adx_txt = f"ADX {_m_adx_val:.0f}"
                                _m_hour = datetime.datetime.now(datetime.timezone.utc).hour
                                _m_is_jpy = ("JPY" in _m_sym.upper())
                                _m_session_ok = (0 <= _m_hour < 16) if _m_is_jpy else (7 <= _m_hour < 16)
                                if _m_adx_val < 18.0:
                                    _m_wait = f"ADX {_m_adx_val:.0f} < 18 eşiği — trend gücü yetersiz"
                                elif not _m_session_ok:
                                    _m_wait = f"seans dışı (UTC {_m_hour}; pencere {'00-16' if _m_is_jpy else '07-16'})"
                                elif _m_st["counts"].get("BUY", 0) >= 2 and _m_st["counts"].get("SELL", 0) >= 2:
                                    _m_wait = "günlük yön limiti doldu (2+2)"
                                else:
                                    _m_wait = ("fiyat orta hattın üstüne dönüp yeniden kırılınca SAT" if _m_price <= float(_m_tech["donch_mid"]) else "fiyat orta hattın altına sarkıp yeniden kırılınca AL")
                                _log_auto_decision(
                                    "SCAN",
                                    f"🎯 [{_m_disp}] Donchian modu bekliyor: fiyat orta hattın {_m_side} ({_m_price:.3f} / orta {float(_m_tech['donch_mid']):.3f}), {_m_adx_txt} → {_m_wait}.",
                                    symbol=_m_sym,
                                    strategy="DONCHIAN_ADX",
                                    strategy_label="Donchian ADX Kırılımı",
                                )

            # EMA+ADX geri-çekilme (M5) akışı (2026-10-08 canlıya alım — XAUUSD):
            # klasik + donchian akışları KORUNUR; bu üçüncü bir aday kaynağıdır.
            if _AUTO_SETTINGS.ema_adx_enabled:
                for _e_sym in {s.upper() for s in (_AUTO_SETTINGS.ema_adx_symbols or [])}:
                    _e_tech = _TECHNICAL_CACHE.get(_e_sym) or {}
                    _e_t = ticks.get(_e_sym)
                    if not _e_t or not _e_tech or not _e_tech.get("ema21") or not _e_tech.get("signal_bar_confirmed"):
                        continue
                    _e_bar = int(_e_tech.get("signal_bar_time") or 0)
                    _e_price = float(_e_tech.get("price") or 0.0)
                    _e_open = float(_e_tech.get("open_last") or 0.0)
                    _e_high = float(_e_tech.get("high_last") or 0.0)
                    _e_low = float(_e_tech.get("low_last") or 0.0)
                    _e_item = next((i for i in FOREX_SYMBOLS if i["symbol"] == _e_sym), None)
                    _e_pip_size = _e_tech.get("pip_size") or (_e_item["pip_size"] if _e_item else 0.0001)
                    if _e_price <= 0 or _e_open <= 0 or _e_high <= 0 or _e_low <= 0 or _e_pip_size <= 0 or _e_bar <= 0:
                        continue
                    _e_now = datetime.datetime.now(datetime.timezone.utc)
                    _e_day = _e_now.toordinal()
                    _e_st = _EMA_ADX_STATE.setdefault(_e_sym, {"day": _e_day, "counts": {}})
                    if _e_st["day"] != _e_day:
                        _e_st["day"] = _e_day
                        _e_st["counts"] = {}
                    if int(_e_st.get("consumed_bar") or 0) == _e_bar:
                        continue
                    _e_atr = float(_e_tech.get("atr", 0.0))
                    _e_action = ema_adx_pullback_entry(
                        ema8=float(_e_tech.get("ema8", 0.0)),
                        ema21=float(_e_tech.get("ema21", 0.0)),
                        ema50=float(_e_tech.get("ema50", 0.0)),
                        adx=float(_e_tech.get("adx", 0.0)),
                        adx_min=float(_AUTO_SETTINGS.ema_adx_adx_min),
                        close=_e_price,
                        open_=_e_open,
                        high=_e_high,
                        low=_e_low,
                        atr_price=_e_atr,
                        touch_atr=float(_AUTO_SETTINGS.ema_adx_touch_atr),
                        day_counts=_e_st["counts"],
                        max_per_day=int(_AUTO_SETTINGS.ema_adx_max_per_day),
                    )
                    _e_disp = _e_t.get("display", _e_sym)
                    _e_allowed = _e_sym in {s.upper() for s in (_AUTO_SETTINGS.allowed_symbols or [])}
                    if _e_action:
                        arm_rows.append({
                            "symbol": _e_sym,
                            "display": _e_disp,
                            "action": _e_action,
                            "score": float(_e_tech.get("score") or 0.0),
                            "spread_pips": float(_e_t.get("spread_pips", 0.0) or 0.0),
                            "atr_pips": round(_e_atr / _e_pip_size, 1) if _e_pip_size > 0 else 15.0,
                            "adx": float(_e_tech.get("adx", 0.0)),
                            "supertrend_dir": int(_e_tech.get("supertrend_dir", 0)),
                            "entry_source": "ema_adx_pullback",
                            "strategy": EMA_ADX_PULLBACK_STRATEGY,
                            "signal_bar_time": _e_bar,
                            "signal_bar_confirmed": True,
                            "_arm_quota": {"kind": "ema", "symbol": _e_sym, "action": _e_action, "bar_time": _e_bar},
                        })
                        _log_auto_decision(
                            "SCAN",
                            f"📐 [{_e_disp}] {EMA_ADX_PULLBACK_LABEL}: {_e_action} adayı "
                            f"(ADX {_e_tech.get('adx', 0):.0f}, EMA dizilimi "
                            f"{'boğa' if _e_action == 'BUY' else 'ayı'}, EMA21 geri çekilmesi onaylı) — değerlendiriliyor.",
                            symbol=_e_sym,
                            strategy=EMA_ADX_PULLBACK_STRATEGY,
                            strategy_label=EMA_ADX_PULLBACK_LABEL,
                        )
                    else:
                        # Görünürlük: akış ne beklediğini 25 sn'de bir insan-okur cümleyle söyler.
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{_e_sym}_eap_wait", 0.0) > 25.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{_e_sym}_eap_wait"] = now_ts
                            if not _e_allowed:
                                _log_auto_decision(
                                    "SCAN",
                                    f"⚠️ [{_e_disp}] {EMA_ADX_PULLBACK_LABEL} aktif AMA sembol panel kapsamında değil (allowed_symbols) — işlem için panele eklenmeli.",
                                    symbol=_e_sym,
                                    strategy=EMA_ADX_PULLBACK_STRATEGY,
                                    strategy_label=EMA_ADX_PULLBACK_LABEL,
                                )
                            else:
                                _e8 = float(_e_tech.get("ema8", 0.0)); _e21 = float(_e_tech.get("ema21", 0.0)); _e50 = float(_e_tech.get("ema50", 0.0))
                                if _e8 > _e21 > _e50:
                                    _e_trend_txt, _e_wait = "boğa dizilimi", "fiyat EMA21'e geri çekilip yeşil kapanışla dönünce AL"
                                elif _e8 < _e21 < _e50:
                                    _e_trend_txt, _e_wait = "ayı dizilimi", "fiyat EMA21'e geri çekilip kırmızı kapanışla dönünce SAT"
                                else:
                                    _e_trend_txt, _e_wait = "dizilim yok", "EMA8/21/50 diziliminin netleşmesi bekleniyor"
                                _log_auto_decision(
                                    "SCAN",
                                    f"📐 [{_e_disp}] {EMA_ADX_PULLBACK_LABEL} bekliyor: {_e_trend_txt}, "
                                    f"ADX {_e_tech.get('adx', 0):.0f} (eşik {_AUTO_SETTINGS.ema_adx_adx_min:.0f}) → {_e_wait}.",
                                    symbol=_e_sym,
                                    strategy=EMA_ADX_PULLBACK_STRATEGY,
                                    strategy_label=EMA_ADX_PULLBACK_LABEL,
                                )

            # S3 (Supertrend+RSI pullback) akışı (2026-10-08 canlıya alım — kullanıcı kararı):
            # L30 replay temiz koşum: XAU 5m +$90.04 PF 2.09, XAU 15m +$58.12 PF 3.08,
            # BTC 15m +$59.28 PF 6.63. Klasik/donchian/EAP akışları KORUNUR; bu dördüncü
            # aday kaynağıdır. Göstergeler köprü broker mumlarından (fallback Yahoo).
            if _AUTO_SETTINGS.s3_enabled:
                _refresh_s3_state(ticks)
                for _s_tf, _s_syms, _s_src in (
                    ("5m", _AUTO_SETTINGS.s3_symbols_5m, "s3_5m"),
                    ("15m", _AUTO_SETTINGS.s3_symbols_15m, "s3_15m"),
                ):
                    for _s_sym in {s.upper() for s in (_s_syms or [])}:
                        _s_tech = _S3_STATE.get(f"{_s_sym}|{_s_tf}")
                        _s_t = ticks.get(_s_sym)
                        if not _s_tech or not _s_t:
                            continue
                        _s_item = next((i for i in FOREX_SYMBOLS if i["symbol"] == _s_sym), None)
                        _s_pip = _s_item["pip_size"] if _s_item else 0.0001
                        if _s_pip <= 0:
                            continue
                        _s_now = datetime.datetime.now(datetime.timezone.utc)
                        _s_day = _s_now.toordinal()
                        _s_key = f"{_s_sym}|{_s_tf}"
                        _s_st = _S3_DAY_STATE.setdefault(_s_key, {"day": _s_day, "counts": {}})
                        if _s_st["day"] != _s_day:
                            _s_st["day"] = _s_day
                            _s_st["counts"] = {}
                        _s_bar = int(_s_tech.get("bar_time") or 0)
                        if _s_bar and int(_s_st.get("consumed_bar") or 0) == _s_bar:
                            continue
                        _s_counts = dict(_s_st.get("counts") or {})
                        _s_action = s3_pullback_entry(
                            st_dir=int(_s_tech.get("st_dir", 0)),
                            close=float(_s_tech.get("close", 0.0)),
                            ema200=float(_s_tech.get("ema200", 0.0)),
                            use_ema200=True,
                            adx=float(_s_tech.get("adx", 0.0)),
                            adx_min=float(_AUTO_SETTINGS.s3_adx_min),
                            rsi_now=_s_tech.get("rsi_now"),
                            rsi_prev=_s_tech.get("rsi_prev"),
                            rsi_window=list(_s_tech.get("rsi_window") or []),
                            rsi_lo=float(_AUTO_SETTINGS.s3_rsi_lo),
                            atr_price=float(_s_tech.get("atr", 0.0)),
                            pip_size=float(_s_pip),
                            day_counts=_s_counts,
                            max_per_day=int(_AUTO_SETTINGS.s3_max_per_day),
                            action_key=_s_src,
                        )
                        _s_disp = _s_t.get("display", _s_sym)
                        _s_allowed = _s_sym in {s.upper() for s in (_AUTO_SETTINGS.allowed_symbols or [])}
                        if _s_action:
                            _s_score_src = _TECHNICAL_CACHE.get(_s_sym) or {}
                            arm_rows.append({
                                "symbol": _s_sym,
                                "display": _s_disp,
                                "action": _s_action,
                                "score": float(_s_score_src.get("score") or _s_t.get("score") or 0.0),
                                "spread_pips": float(_s_t.get("spread_pips", 0.0) or 0.0),
                                "atr_pips": round(float(_s_tech.get("atr", 0.0)) / _s_pip, 1) if _s_pip > 0 else 15.0,
                                "adx": float(_s_tech.get("adx", 0.0)),
                                "supertrend_dir": int(_s_tech.get("st_dir", 0)),
                                "entry_source": _s_src,
                                "strategy": S3_PULLBACK_STRATEGY,
                                "s3_tf": _s_tf,
                                "signal_bar_time": _s_bar,
                                "signal_bar_confirmed": True,
                                "_arm_quota": {
                                    "kind": "s3", "symbol": _s_sym, "action": _s_action,
                                    "key": _s_key, "action_key": _s_src, "bar_time": _s_bar,
                                },
                            })
                            _log_auto_decision(
                                "SCAN",
                                f"🧭 [{_s_disp}] {S3_PULLBACK_LABEL} ({_s_tf}): {_s_action} adayı "
                                f"(ST {'BOĞA' if int(_s_tech.get('st_dir', 0)) > 0 else 'AYI'}, "
                                f"RSI {float(_s_tech.get('rsi_now') or 0):.1f}→50 geçişi, "
                                f"ADX {float(_s_tech.get('adx', 0)):.0f}) — değerlendiriliyor.",
                                symbol=_s_sym,
                                strategy=S3_PULLBACK_STRATEGY,
                                strategy_label=strategy_display_label(_s_src),
                            )
                        else:
                            if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{_s_key}_s3_wait", 0.0) > 25.0:
                                _LAST_CANDIDATE_LOG_TIME[f"{_s_key}_s3_wait"] = now_ts
                                if not _s_allowed:
                                    _log_auto_decision(
                                        "SCAN",
                                        f"⚠️ [{_s_disp}] {S3_PULLBACK_LABEL} ({_s_tf}) aktif AMA sembol panel kapsamında değil (allowed_symbols) — işlem için panele eklenmeli.",
                                        symbol=_s_sym,
                                        strategy=S3_PULLBACK_STRATEGY,
                                        strategy_label=strategy_display_label(_s_src),
                                    )
                                else:
                                    _s_dir_txt = "BOĞA" if int(_s_tech.get("st_dir", 0)) > 0 else ("AYI" if int(_s_tech.get("st_dir", 0)) < 0 else "tanımsız")
                                    _log_auto_decision(
                                        "SCAN",
                                        f"🧭 [{_s_disp}] {S3_PULLBACK_LABEL} ({_s_tf}) bekliyor: ST {_s_dir_txt}, "
                                        f"RSI {float(_s_tech.get('rsi_now') or 0):.1f} → {'50 üstüne yeşil kapanışta AL' if int(_s_tech.get('st_dir', 0)) > 0 else '50 altına kapanışta SAT' if int(_s_tech.get('st_dir', 0)) < 0 else 'ST yönü netleşmeli'}.",
                                        symbol=_s_sym,
                                        strategy=S3_PULLBACK_STRATEGY,
                                        strategy_label=strategy_display_label(_s_src),
                                    )

            # London Breakout akışı (2026-10-08 canlıya alım — kullanıcı kararı):
            # Asya kutusu (00:00→box_end UTC) high/low kırılımı, tetik penceresinde
            # kutu-dışı kapanışta giriş. SL = kutu × frac, TP = SL × R. L30 replay:
            # 19 sembol pozitif; XAU +$39, GBPCHF +$31, EURCAD +$30 (BE'li profil).
            # Kutu/mum köprü broker verisinden (fallback Yahoo) — S3 bar kaynağı ortak.
            if _AUTO_SETTINGS.lb_enabled:
                _lb_now = datetime.datetime.now(datetime.timezone.utc)
                _lb_day = _lb_now.toordinal()
                _lb_hour = _lb_now.hour
                _lb_allowed = {s.upper() for s in (_AUTO_SETTINGS.allowed_symbols or [])}
                for _lb_sym in {s.upper() for s in (_AUTO_SETTINGS.lb_symbols or [])}:
                    _lb_t = ticks.get(_lb_sym)
                    _lb_item = next((i for i in FOREX_SYMBOLS if i["symbol"] == _lb_sym), None)
                    if not _lb_t or not _lb_item:
                        continue
                    _lb_pip = _lb_item["pip_size"]
                    _lb_disp = _lb_t.get("display", _lb_sym)
                    _lb_st = _LB_STATE.setdefault(_lb_sym, {"day": _lb_day, "box_hi": 0.0, "box_lo": 0.0, "counts": {}})
                    if _lb_st["day"] != _lb_day:
                        _lb_st["day"] = _lb_day
                        _lb_st["box_hi"] = 0.0
                        _lb_st["box_lo"] = 0.0
                        _lb_st["counts"] = {}
                    # Kutu 00:00→box_end UTC penceresinde veya sunucu 07:00 UTC sonrası yeniden
                    # başlatıldığında geçmiş barlardan doldurulur.
                    _lb_bars_now = _s3_bars_for(_lb_sym, "5m", limit=220)
                    if _lb_hour < _AUTO_SETTINGS.lb_box_end_utc or float(_lb_st.get("box_hi") or 0.0) <= 0.0:
                        if _lb_bars_now and len(_lb_bars_now) >= 10:
                            _lb_box = [b for b in _lb_bars_now
                                       if datetime.datetime.fromtimestamp(b["time"], datetime.timezone.utc).toordinal() == _lb_day
                                       and datetime.datetime.fromtimestamp(b["time"], datetime.timezone.utc).hour < _AUTO_SETTINGS.lb_box_end_utc]
                            if len(_lb_box) >= 6:
                                _lb_st["box_hi"] = max(float(b["high"]) for b in _lb_box)
                                _lb_st["box_lo"] = min(float(b["low"]) for b in _lb_box)
                        if _lb_hour < _AUTO_SETTINGS.lb_box_end_utc:
                            continue
                    _lb_last = _lb_bars_now[-1] if _lb_bars_now else None
                    _lb_close = float(_lb_last["close"]) if _lb_last else 0.0
                    _lb_bar = int(_lb_last["time"]) if _lb_last else 0
                    if _lb_bar and int(_lb_st.get("consumed_bar") or 0) == _lb_bar:
                        continue
                    _lb_action = london_breakout_entry(
                        close=_lb_close,
                        box_hi=float(_lb_st.get("box_hi") or 0.0),
                        box_lo=float(_lb_st.get("box_lo") or 0.0),
                        hour_utc=_lb_hour,
                        box_end_utc=int(_AUTO_SETTINGS.lb_box_end_utc),
                        entry_end_utc=int(_AUTO_SETTINGS.lb_entry_end_utc),
                        day_counts=_lb_st["counts"],
                        max_per_day=int(_AUTO_SETTINGS.lb_max_per_day),
                    )
                    if _lb_action:
                        _lb_box_h = float(_lb_st["box_hi"]) - float(_lb_st["box_lo"])
                        _lb_sl_pips = (_lb_box_h * float(_AUTO_SETTINGS.lb_sl_box_frac)) / _lb_pip if _lb_pip > 0 else 10.0
                        _lb_tp_pips = _lb_sl_pips * float(_AUTO_SETTINGS.lb_tp_r)
                        _lb_tech = _TECHNICAL_CACHE.get(_lb_sym) or {}
                        _lb_atr = float(_lb_tech.get("atr", 0.0))
                        arm_rows.append({
                            "symbol": _lb_sym,
                            "display": _lb_disp,
                            "action": _lb_action,
                            "score": float(_lb_tech.get("score") or _lb_t.get("score") or 0.0),
                            "spread_pips": float(_lb_t.get("spread_pips", 0.0) or 0.0),
                            "atr_pips": round(_lb_atr / _lb_pip, 1) if _lb_pip > 0 else 15.0,
                            "adx": float(_lb_tech.get("adx", 0.0)),
                            "supertrend_dir": int(_lb_tech.get("supertrend_dir", 0)),
                            "entry_source": "london_breakout",
                            "strategy": LONDON_BREAKOUT_STRATEGY,
                            "sl_pips_override": round(_lb_sl_pips, 1),
                            "tp_pips_override": round(_lb_tp_pips, 1),
                            "signal_bar_time": _lb_bar,
                            "signal_bar_confirmed": True,
                            "_arm_quota": {"kind": "lb", "symbol": _lb_sym, "action": _lb_action, "bar_time": _lb_bar},
                        })
                        _log_auto_decision(
                            "SCAN",
                            f"🌅 [{_lb_disp}] {LONDON_BREAKOUT_LABEL}: {_lb_action} adayı — Asya kutusu "
                            f"{float(_lb_st['box_lo']):.5g}–{float(_lb_st['box_hi']):.5g} kırıldı "
                            f"(SL {_lb_sl_pips:.1f} pip, TP {_lb_tp_pips:.1f} pip) — değerlendiriliyor.",
                            symbol=_lb_sym,
                            strategy=LONDON_BREAKOUT_STRATEGY,
                            strategy_label=LONDON_BREAKOUT_LABEL,
                        )
                    else:
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{_lb_sym}_lb_wait", 0.0) > 25.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{_lb_sym}_lb_wait"] = now_ts
                            if _lb_sym not in _lb_allowed:
                                _log_auto_decision(
                                    "SCAN",
                                    f"⚠️ [{_lb_disp}] {LONDON_BREAKOUT_LABEL} aktif AMA sembol panel kapsamında değil (allowed_symbols) — işlem için panele eklenmeli.",
                                    symbol=_lb_sym,
                                    strategy=LONDON_BREAKOUT_STRATEGY,
                                    strategy_label=LONDON_BREAKOUT_LABEL,
                                )
                            else:
                                _lb_box_h_pips = ((float(_lb_st.get("box_hi", 0)) - float(_lb_st.get("box_lo", 0))) / _lb_pip) if _lb_pip > 0 else 0.0
                                if _lb_hour < _AUTO_SETTINGS.lb_box_end_utc:
                                    _lb_status = f"Asya kutusu oluşuyor (00:00–{_AUTO_SETTINGS.lb_box_end_utc:02d}:00 UTC, kutu: {_lb_box_h_pips:.1f}p)"
                                elif _lb_hour < _AUTO_SETTINGS.lb_entry_end_utc:
                                    _lb_status = f"Kutu [{float(_lb_st.get('box_lo', 0)):.5g}–{float(_lb_st.get('box_hi', 0)):.5g}] ({_lb_box_h_pips:.1f}p) kırılımı taranıyor"
                                else:
                                    _lb_status = f"Günün tetik penceresi kapandı ({_AUTO_SETTINGS.lb_entry_end_utc:02d}:00 UTC)"
                                _log_auto_decision(
                                    "SCAN",
                                    f"🌅 [{_lb_disp}] {LONDON_BREAKOUT_LABEL} bekliyor: Fiyat {float(_lb_t.get('bid', 0)):.5g} | {_lb_status}.",
                                    symbol=_lb_sym,
                                    strategy=LONDON_BREAKOUT_STRATEGY,
                                    strategy_label=LONDON_BREAKOUT_LABEL,
                                )

            # London Sign akışı (2026-10-12 canlıya alım — kullanıcı kararı):
            # NY açılışı sign-momentum (Seeck 2026 uyarlaması). 13:30-14:00 UTC sign
            # penceresinde son kapanış ilk kapanıştan yüksekse BUY, düşükse SELL;
            # 14:00-14:30 giriş penceresinde sembol başına günde TEK giriş. SL 1.5×ATR,
            # sabit TP YOK (chandelier trail taşır). Replay 2026-10-12: XAUUSD+US30 beş
            # pencerenin beşinde pozitif (60g +$256 PF 2.16 WR %89.5; slip 2p/bacakta PF 1.76).
            # Bar kaynağı S3/LB ile ortak (köprü broker mumları, fallback Yahoo).
            if _AUTO_SETTINGS.ls_enabled:
                _ls_now = datetime.datetime.now(datetime.timezone.utc)
                _ls_day = _ls_now.toordinal()
                _ls_min = _ls_now.hour * 60 + _ls_now.minute
                _ls_allowed = {s.upper() for s in (_AUTO_SETTINGS.allowed_symbols or [])}
                _ls_sig_lo = int(_AUTO_SETTINGS.ls_sign_start_utc) * 60 + int(_AUTO_SETTINGS.ls_sign_start_min)
                _ls_sig_hi = int(_AUTO_SETTINGS.ls_sign_end_utc) * 60 + int(_AUTO_SETTINGS.ls_sign_end_min)
                _ls_ent_lo = int(_AUTO_SETTINGS.ls_entry_start_utc) * 60 + int(_AUTO_SETTINGS.ls_entry_start_min)
                _ls_ent_hi = int(_AUTO_SETTINGS.ls_entry_end_utc) * 60 + int(_AUTO_SETTINGS.ls_entry_end_min)
                for _ls_sym in {s.upper() for s in (_AUTO_SETTINGS.ls_symbols or [])}:
                    _ls_t = ticks.get(_ls_sym)
                    _ls_item = next((i for i in FOREX_SYMBOLS if i["symbol"] == _ls_sym), None)
                    if not _ls_t or not _ls_item:
                        continue
                    _ls_pip = _ls_item["pip_size"]
                    _ls_disp = _ls_t.get("display", _ls_sym)
                    _ls_st = _LS_STATE.setdefault(_ls_sym, {"day": _ls_day, "sign_open": 0.0, "sign_close": 0.0, "entered": False})
                    if _ls_st["day"] != _ls_day:
                        _ls_st["day"] = _ls_day
                        _ls_st["sign_open"] = 0.0
                        _ls_st["sign_close"] = 0.0
                        _ls_st["entered"] = False
                    # Sign penceresi: ilk ve son kapanış toplanır (gün içi bir kez).
                    if _ls_sig_lo <= _ls_min < _ls_sig_hi:
                        _ls_bars = _s3_bars_for(_ls_sym, "5m", limit=220)
                        if _ls_bars and len(_ls_bars) >= 6:
                            _ls_sb = [b for b in _ls_bars
                                      if datetime.datetime.fromtimestamp(b["time"], datetime.timezone.utc).toordinal() == _ls_day
                                      and _ls_sig_lo <= (datetime.datetime.fromtimestamp(b["time"], datetime.timezone.utc).hour * 60
                                                         + datetime.datetime.fromtimestamp(b["time"], datetime.timezone.utc).minute) < _ls_sig_hi]
                            if _ls_sb:
                                _ls_st["sign_open"] = float(_ls_sb[0]["open"])
                                _ls_st["sign_close"] = float(_ls_sb[-1]["close"])
                        continue
                    if _ls_ent_lo <= _ls_min < _ls_ent_hi:
                        _ls_action = sign_window_entry(
                            sign_open=float(_ls_st.get("sign_open") or 0.0),
                            sign_close=float(_ls_st.get("sign_close") or 0.0),
                            minute_of_day=_ls_min,
                            ent_start_min=_ls_ent_lo,
                            ent_end_min=_ls_ent_hi,
                            day_entered=bool(_ls_st.get("entered")),
                        )
                        if _ls_action and not _ls_st.get("entered"):
                            _ls_tech = _TECHNICAL_CACHE.get(_ls_sym) or {}
                            _ls_atr = float(_ls_tech.get("atr", 0.0))
                            _ls_sl_pips = (float(_AUTO_SETTINGS.ls_sl_atr) * _ls_atr / _ls_pip) if _ls_pip > 0 else 0.0
                            _ls_bar = int(_ls_tech.get("signal_bar_time") or 0)
                            if _ls_sl_pips > 0 and int(_ls_st.get("consumed_bar") or 0) != _ls_bar:
                                arm_rows.append({
                                    "symbol": _ls_sym,
                                    "display": _ls_disp,
                                    "action": _ls_action,
                                    "score": float(_ls_tech.get("score") or _ls_t.get("score") or 0.0),
                                    "spread_pips": float(_ls_t.get("spread_pips", 0.0) or 0.0),
                                    "atr_pips": round(_ls_atr / _ls_pip, 1) if _ls_pip > 0 else 15.0,
                                    "adx": float(_ls_tech.get("adx", 0.0)),
                                    "supertrend_dir": int(_ls_tech.get("supertrend_dir", 0)),
                                    "entry_source": "london_sign",
                                    "strategy": LONDON_SIGN_STRATEGY,
                                    "strategy_label": LONDON_SIGN_LABEL,
                                    "sl_pips_override": round(_ls_sl_pips, 1),
                                    "tp_pips_override": 0.0,
                                    "hold_minutes": int(float(_AUTO_SETTINGS.ls_hold_hours) * 60),
                                    "signal_bar_time": _ls_bar,
                                    "signal_bar_confirmed": bool(_ls_tech.get("signal_bar_confirmed")),
                                    "_arm_quota": {"kind": "ls", "symbol": _ls_sym, "action": _ls_action, "bar_time": _ls_bar},
                                })
                                _ls_sign_txt = "+" if _ls_action == "BUY" else "-"
                                _log_auto_decision(
                                    "SCAN",
                                    f"🌆 [{_ls_disp}] {LONDON_SIGN_LABEL}: {_ls_action} adayı — NY açılışı "
                                    f"sign {_ls_sign_txt} (kapanış {float(_ls_st['sign_close']):.5g} vs açılış "
                                    f"{float(_ls_st['sign_open']):.5g}), SL {_ls_sl_pips:.1f} pip, TP yok (trail) — değerlendiriliyor.",
                                    symbol=_ls_sym,
                                    strategy=LONDON_SIGN_STRATEGY,
                                    strategy_label=LONDON_SIGN_LABEL,
                                )
                    else:
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{_ls_sym}_ls_wait", 0.0) > 25.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{_ls_sym}_ls_wait"] = now_ts
                            if _ls_sym not in _ls_allowed:
                                _log_auto_decision(
                                    "SCAN",
                                    f"⚠️ [{_ls_disp}] {LONDON_SIGN_LABEL} aktif AMA sembol panel kapsamında değil (allowed_symbols) — işlem için panele eklenmeli.",
                                    symbol=_ls_sym,
                                    strategy=LONDON_SIGN_STRATEGY,
                                    strategy_label=LONDON_SIGN_LABEL,
                                )
                            elif _ls_min < _ls_sig_lo:
                                _ls_status = f"Sign penceresi bekleniyor ({_AUTO_SETTINGS.ls_sign_start_utc:02d}:{_AUTO_SETTINGS.ls_sign_start_min:02d}–{_AUTO_SETTINGS.ls_sign_end_utc:02d}:{_AUTO_SETTINGS.ls_sign_end_min:02d} UTC)"
                            elif _ls_min < _ls_ent_lo:
                                _ls_status = "Sign toplanıyor; 14:00–14:30 UTC girişi bekleniyor"
                            elif _ls_min < _ls_ent_hi:
                                _ls_status = "Giriş penceresi açık — sign yönü bekleniyor"
                            else:
                                _ls_status = f"Günün penceresi kapandı (giriş {_ls_ent_hi // 60:02d}:{_ls_ent_hi % 60:02d} UTC)"
                            _log_auto_decision(
                                "SCAN",
                                f"🌆 [{_ls_disp}] {LONDON_SIGN_LABEL} bekliyor: Fiyat {float(_ls_t.get('bid', 0)):.5g} | {_ls_status}.",
                                symbol=_ls_sym,
                                strategy=LONDON_SIGN_STRATEGY,
                                strategy_label=LONDON_SIGN_LABEL,
                            )

            # Keltner Squeeze (M15) akışı (2026-10-14 canlıya alım — kullanıcı kararı):
            # BB(20,2) ⊂ Keltner(20,1.5) sıkışması bırakılınca bant-dışı kapanış +
            # LazyBear momentum teyidi; SL = |kapanış − KC orta|, TP = 2R. Kanonik
            # DB hattında standalone M15 iki pencerede pozitif (OOS n=97 +$143.93
            # PF 1.74 / IS n=123 +$77.65 PF 1.47, 2× spread'e dayanıyor) ve
            # `--combined` defter testinde klasik radarın netini düşürmüyor.
            # Bar kaynağı S3/LB/LS ile ortak (köprü broker mumları, fallback Yahoo).
            if _AUTO_SETTINGS.squeeze_kc_enabled:
                _refresh_squeeze_kc_state(ticks)
                _skc_allowed = {s.upper() for s in (_AUTO_SETTINGS.allowed_symbols or [])}
                _skc_day = datetime.datetime.now(datetime.timezone.utc).toordinal()
                for _skc_sym in {s.upper() for s in (_AUTO_SETTINGS.squeeze_kc_symbols or [])}:
                    _skc_tech = _SQUEEZE_KC_STATE.get(_skc_sym)
                    _skc_t = ticks.get(_skc_sym)
                    _skc_item = next((i for i in FOREX_SYMBOLS if i["symbol"] == _skc_sym), None)
                    if not _skc_tech or not _skc_t or not _skc_item:
                        continue
                    _skc_pip = _skc_item["pip_size"]
                    _skc_disp = _skc_t.get("display", _skc_sym)
                    _skc_st = _SQUEEZE_KC_DAY_STATE.setdefault(_skc_sym, {"day": _skc_day, "counts": {}})
                    if _skc_st["day"] != _skc_day:
                        _skc_st["day"] = _skc_day
                        _skc_st["counts"] = {}
                    _skc_bar = int(_skc_tech.get("bar_time") or 0)
                    if _skc_bar and int(_skc_st.get("consumed_bar") or 0) == _skc_bar:
                        continue
                    _skc_dec = squeeze_kc_entry(_skc_tech, float(_skc_pip), _skc_st["counts"])
                    if _skc_dec:
                        _skc_tech5 = _TECHNICAL_CACHE.get(_skc_sym) or {}
                        arm_rows.append({
                            "symbol": _skc_sym,
                            "display": _skc_disp,
                            "action": _skc_dec["action"],
                            "score": float(_skc_tech5.get("score") or _skc_t.get("score") or 0.0),
                            "spread_pips": float(_skc_t.get("spread_pips", 0.0) or 0.0),
                            "atr_pips": round(float(_skc_tech5.get("atr", 0.0)) / _skc_pip, 1) if _skc_pip > 0 else 15.0,
                            "adx": float(_skc_tech5.get("adx", 0.0)),
                            "supertrend_dir": int(_skc_tech5.get("supertrend_dir", 0)),
                            "entry_source": "squeeze_kc",
                            "strategy": SQUEEZE_KC_STRATEGY,
                            "strategy_label": SQUEEZE_KC_LABEL,
                            "sl_pips_override": _skc_dec["sl_pips"],
                            "tp_pips_override": _skc_dec["tp_pips"],
                            "signal_bar_time": _skc_bar,
                            "signal_bar_confirmed": True,
                            "_arm_quota": {
                                "kind": "squeeze", "symbol": _skc_sym, "action": _skc_dec["action"],
                                "day_key": _skc_dec.get("day_key"), "bar_time": _skc_bar,
                            },
                        })
                        _log_auto_decision(
                            "SCAN",
                            f"🌀 [{_skc_disp}] {SQUEEZE_KC_LABEL}: {_skc_dec['action']} adayı — "
                            f"sıkışma bırakışı (kapanış BB {'üst' if _skc_dec['action'] == 'BUY' else 'alt'} "
                            f"bandı dışında), momentum {_skc_dec['mom']:+.5g}, "
                            f"SL {(_skc_dec['sl_pips'] if _skc_dec['sl_pips'] else 0):.1f} pip, "
                            f"TP {(float(_AUTO_SETTINGS.squeeze_kc_tp_r)):.1f}R — değerlendiriliyor.",
                            symbol=_skc_sym,
                            strategy=SQUEEZE_KC_STRATEGY,
                            strategy_label=SQUEEZE_KC_LABEL,
                        )
                    else:
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{_skc_sym}_sqzkc_wait", 0.0) > 25.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{_skc_sym}_sqzkc_wait"] = now_ts
                            if _skc_sym not in _skc_allowed:
                                _log_auto_decision(
                                    "SCAN",
                                    f"⚠️ [{_skc_disp}] {SQUEEZE_KC_LABEL} aktif AMA sembol panel kapsamında değil (allowed_symbols) — işlem için panele eklenmeli.",
                                    symbol=_skc_sym,
                                    strategy=SQUEEZE_KC_STRATEGY,
                                    strategy_label=SQUEEZE_KC_LABEL,
                                )
                            else:
                                _log_auto_decision(
                                    "SCAN",
                                    f"🌀 [{_skc_disp}] {SQUEEZE_KC_LABEL} bekliyor: Fiyat "
                                    f"{float(_skc_t.get('bid', 0)):.5g} | M15'te sıkışma bırakışı ve "
                                    f"momentum teyidi aranıyor.",
                                    symbol=_skc_sym,
                                    strategy=SQUEEZE_KC_STRATEGY,
                                    strategy_label=SQUEEZE_KC_LABEL,
                                )

            candidates = _order_entry_arms(candidates, arm_rows)

            # Periyodik Canlı Tarama Özeti (Her 20 saniyede bir Decision Stream'e düşer)
            if now_ts - _LAST_SCAN_PULSE_TIME > 20.0:
                _LAST_SCAN_PULSE_TIME = now_ts
                active_str = ", ".join(active_names) if active_names else "24/5 Açık"
                if candidates:
                    top_3 = ", ".join([f"{c['display']} ({strategy_display_label(c.get('entry_source'))} Skor:{c['score']:.0f} {c['action']})" for c in candidates[:3]])
                    unique_strats = list(dict.fromkeys([strategy_display_label(c.get("entry_source")) for c in candidates]))
                    strat_summary = " · ".join(unique_strats) if unique_strats else "Radar"
                    scan_msg = f"🔍 Piyasa Taraması: {len(candidates)} parite sinyali | Taranan Stratejiler: [{strat_summary}] [Öncü: {top_3}] (Seanslar: {active_str})"
                else:
                    active_strats = []
                    if _AUTO_SETTINGS.s3_enabled:
                        active_strats.append("S3 SuperTrend")
                    if _AUTO_SETTINGS.lb_enabled:
                        active_strats.append("London Breakout")
                    if _AUTO_SETTINGS.ema_adx_enabled:
                        active_strats.append("EMA+ADX M5")
                    if _AUTO_SETTINGS.ls_enabled:
                        active_strats.append("London Sign")
                    if _AUTO_SETTINGS.squeeze_kc_enabled:
                        active_strats.append("Keltner Squeeze M15")
                    if _AUTO_SETTINGS.mode_symbols:
                        active_strats.append("Donchian ADX")
                    active_strats.append("M1/M5 Çoklu Radar")
                    scan_msg = f"🔍 Piyasa Taraması: {len(_AUTO_SETTINGS.allowed_symbols)} parite taranıyor | Aktif Stratejiler: [{' · '.join(active_strats)}] (Seanslar: {active_str})"

                _log_auto_decision(
                    "SCAN",
                    scan_msg,
                    strategy="M1_M5_RADAR_SCALPER",
                    strategy_label="M1/M5 Çoklu Radar",
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
                    _log_auto_decision(
                        "SCAN",
                        gold_msg,
                        symbol="XAUUSD",
                        strategy="M1_M5_RADAR_SCALPER",
                        strategy_label="M1/M5 Çoklu Radar",
                    )

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
                    _log_auto_decision(
                        "SCAN",
                        btc_msg,
                        symbol="BTCUSD",
                        strategy="M1_M5_RADAR_SCALPER",
                        strategy_label="M1/M5 Çoklu Radar",
                    )

            # Veri hattı görünürlüğü: mum verisi alınamayan semboller HOLD'da sessizce kalır.
            # Sessiz arıza olmasın — panelde sembol başına 5 dk'da bir görünür yapılır.
            for t_item in ticks.values():
                sym_item = t_item.get("symbol", "").upper()
                if sym_item in _AUTO_SETTINGS.allowed_symbols and t_item.get("macd_verdict") == "NÖTR (Veri Bekleniyor)":
                    if now_ts - _LAST_DATA_GAP_LOG.get(sym_item, 0.0) > 300.0:
                        _LAST_DATA_GAP_LOG[sym_item] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"📡 [{t_item['display']}] Veri Hattı: MT5 tik geçmişi kısa veya yok — bu sembol sinyal üretemiyor (tik gelince otomatik devam eder).",
                            symbol=sym_item,
                        )

            mt5_active_syms = {p.get("symbol", "").upper() for p in _MT5_STATE.get("open_positions", [])}
            auto_active_syms = {p.get("symbol", "").upper() for p in _AUTO_STATE.get("open_positions", [])}
            pending_mt5_syms = {c.get("symbol", "").upper() for c in _MT5_STATE.get("pending_commands", []) if c.get("action") == "OPEN_ORDER"}
            all_active_syms = mt5_active_syms | auto_active_syms | pending_mt5_syms

            # 2026-10-14: EKONOMİK TAKVİM YÖN KANITI (kullanıcı talebi).
            # Aday döngüsünden ÖNCE bir kez hesaplanır (her aday için takvim
            # ayrıştırmak israf). `news_bias_enabled` kapalıyken hiç çalışmaz →
            # davranış birebir eski hâli.
            if _AUTO_SETTINGS.news_bias_enabled:
                try:
                    from app.forex_news import get_forex_news
                    from app import forex_news_bias as _nb_mod
                    _cal_events = await get_forex_news()
                    _nb_mod.refresh_biases(_cal_events, now_ts,
                                           float(_AUTO_SETTINGS.news_bias_window_sec))
                except Exception as _nb_exc:
                    _log_auto_decision("SYSTEM", f"⚠️ Takvim yön kanıtı alınamadı: {_nb_exc}")

            for cand in candidates:
                sym = cand["symbol"].upper()
                _c_src = cand.get("entry_source", "")
                _c_strat = strategy_name_for(_c_src)
                _c_strat_lbl = strategy_display_label(_c_src)

                # Kapsam kapısı kesindir: güçlü sinyal bile allowed_symbols dışına işlem açamaz
                # (2026-10-07 kalibrasyonu: 28/28 FX çifti klasik sinyalle negatif — bypass yok).
                if sym not in _AUTO_SETTINGS.allowed_symbols:
                    continue

                new_action = cand.get("action", "")  # "BUY" or "SELL"
                if new_action not in ("BUY", "SELL"):
                    continue
                if sym in _opened_cycle:
                    continue
                _tick_row = ticks.get(sym) or {}
                _data_why = entry_data_blocked(_tick_row)
                if _data_why or _tech_is_stale(sym, now_ts):
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_veri", 0.0) > 30.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_veri"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}][{_c_strat_lbl}] Tik verisi yok, bayat veya 5m kovasinda bosluk — giris acilmadi.",
                            symbol=sym,
                            strategy=_c_strat,
                            strategy_label=_c_strat_lbl,
                        )
                    continue

                # Ana RADAR sinyali yalnızca zaman damgalı, kapanmış M5
                # mumlarından üretilebilir. Stratejiye özel giriş kolları kendi
                # mum doğrulamalarını kullanır ve bu koşuldan etkilenmez.
                if not _c_src and not bool(cand.get("signal_bar_confirmed", False)):
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_unconfirmed", 0.0) > 30.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_unconfirmed"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}][{_c_strat_lbl}] Kapanmış M5 mum zaman damgası yok — BUY/SELL açılmadı.",
                            symbol=sym,
                            strategy=_c_strat,
                            strategy_label=_c_strat_lbl,
                        )
                    continue

                if not _c_src:
                    signal_bar_time = int(cand.get("signal_bar_time") or 0)
                    last_used_bar = int(_LAST_RADAR_SIGNAL_BAR.get(sym, 0) or _LAST_XAU_RADAR_SIGNAL_BAR.get(sym, 0))
                    if signal_bar_time <= last_used_bar:
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_same_bar", 0.0) > 30.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_same_bar"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}][{_c_strat_lbl}] Aynı kapanmış M5 sinyal mumu tekrar kullanılamaz — yeni bar bekleniyor.",
                                symbol=sym,
                                strategy=_c_strat,
                                strategy_label=_c_strat_lbl,
                                metadata={"signal_bar_time": signal_bar_time, "last_used_signal_bar_time": last_used_bar},
                            )
                        continue

                # Evrensel Sembol Bazlı Zarar Soğuması (Tekil Stop Kalkanı - 180s)
                loss_exit_time = _LAST_SYMBOL_LOSS_TIME.get(sym, 0.0)
                if loss_exit_time > 0 and (now_ts - loss_exit_time < 180.0):
                    rem_loss_cd = int(180.0 - (now_ts - loss_exit_time))
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_loss_cd", 0.0) > 30.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_loss_cd"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}][{_c_strat_lbl}] Seri Zarar Kalkanı: Son stop/kayıptan sonra soğuma bekleniyor ({rem_loss_cd} sn).",
                            symbol=sym,
                            strategy=_c_strat,
                            strategy_label=_c_strat_lbl,
                        )
                    continue

                # Whipsaw / Testere Kalkanı (Zıt Yöne Ani Dönüş Koruması - 300s)
                last_exit_dir = _LAST_SYMBOL_EXIT_DIR.get(sym, "")
                last_exit_time = _LAST_SYMBOL_EXIT_TIME.get(sym, 0.0)
                if last_exit_dir and new_action != last_exit_dir and (now_ts - last_exit_time < 300.0):
                    rem_flip_cd = int(300.0 - (now_ts - last_exit_time))
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_flip_cd", 0.0) > 30.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_flip_cd"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}][{_c_strat_lbl}] Testere (Whipsaw) Kalkanı: Zıt yöne ani dönüş engeli ({rem_flip_cd} sn).",
                            symbol=sym,
                            strategy=_c_strat,
                            strategy_label=_c_strat_lbl,
                        )
                    continue

                # Seri-SL ve Yön Bazlı Seri Zarar Soğuması: sembol veya yön ardışık kayıplardan sonra
                # YENİ giriş almaz (flip dahil); açık pozisyon yönetimi aynen sürer.
                if _AUTO_SETTINGS.loss_streak_limit > 0:
                    sym_cd_until = _SYMBOL_LOSS_COOLDOWN_UNTIL.get(sym, 0.0)
                    dir_cd_until = _SYMBOL_DIR_LOSS_COOLDOWN_UNTIL.get((sym, new_action), 0.0)
                    effective_cd = max(sym_cd_until, dir_cd_until)
                    if now_ts < effective_cd:
                        rem_s = int(effective_cd - now_ts)
                        is_dir_only = (effective_cd == dir_cd_until and now_ts >= sym_cd_until)
                        cd_label = f"{new_action} Yönlü Seri Zarar" if is_dir_only else "Seri-SL"
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_{new_action}_seri", 0.0) > 30.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_{new_action}_seri"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"🌡️ [{cand['display']}][{_c_strat_lbl}] {cd_label} Soğuması: {_AUTO_SETTINGS.loss_streak_limit} ardışık kayıp — {rem_s} sn {new_action} yönünde yeni giriş yok (süre bitince normal değerlendirilir).",
                                symbol=sym,
                                strategy=_c_strat,
                                strategy_label=_c_strat_lbl,
                            )
                        continue

                if sym in all_active_syms:
                    _pend_flip = _PENDING_FLIP.get(sym)
                    if _pend_flip and str(_pend_flip.get("direction") or "") == new_action and not _pend_flip.get("close_ok"):
                        continue
                    existing_dirs = set()
                    matching_auto = [p for p in _AUTO_STATE.get("open_positions", []) if p.get("symbol", "").upper() == sym]
                    matching_mt5 = [p for p in _MT5_STATE.get("open_positions", []) if p.get("symbol", "").upper() == sym]
                    if _pend_flip and _pend_flip.get("close_ok") and str(_pend_flip.get("direction") or "") == new_action:
                        matching_mt5 = []
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
                        # 2026-10-14 kullanıcı kararı: flip_ignore_min_score açıkken skor eşiği
                        # ARANMAZ — herhangi bir stratejiden zıt sinyal gelirse anında flip.
                        # Spread (maliyet) kapısı her iki durumda da korunur.
                        effective_spread_limit = max(50.0, _AUTO_SETTINGS.max_spread_pips * 10) if ("BTC" in sym or "ETH" in sym) else _AUTO_SETTINGS.max_spread_pips
                        _score_gate_ok = bool(_AUTO_SETTINGS.flip_ignore_min_score) or cand.get("score", 0.0) >= _AUTO_SETTINGS.min_score
                        if _score_gate_ok and cand.get("spread_pips", 99.0) <= effective_spread_limit:
                            old_dir_str = "/".join(opposite_dirs)
                            _log_auto_decision(
                                "REVERSAL",
                                f"🔄 [{cand['display']}][{_c_strat_lbl}] TREND DÖNÜŞÜ (FLIP): Açık {old_dir_str} pozisyonu kapatılıyor -> Yeni {new_action} açılıyor! (Skor: {cand['score']:.1f})",
                                symbol=sym,
                                strategy=_c_strat,
                                strategy_label=_c_strat_lbl,
                            )
                            # Önce açık auto-paper ZIT pozisyonunu kapat
                            for ap in matching_auto:
                                if ap.get("direction", "").upper() in opposite_dirs:
                                    t_sym = ticks.get(sym)
                                    exit_p = (t_sym["bid"] if ap.get("direction") == "BUY" else t_sym["ask"]) if t_sym else None
                                    await _close_position_internal(ap["id"], "REVERSAL_FLIP", exit_p)

                            _flip_tickets: List[Any] = []
                            for mp in matching_mt5:
                                if mp.get("direction", "").upper() in opposite_dirs:
                                    t_id = mp.get("ticket")
                                    if t_id:
                                        _flip_tickets.append(t_id)
                                        already_closing = any(
                                            c.get("ticket") == t_id and c.get("action") == "CLOSE_ORDER"
                                            for c in _MT5_STATE.get("pending_commands", [])
                                        )
                                        if not already_closing:
                                            _MT5_STATE["pending_commands"].append({
                                                "id": f"CMD-CLOSE-{t_id}-FLIP",
                                                "action": "CLOSE_ORDER",
                                                "ticket": t_id,
                                                "symbol": sym,
                                            })

                            _MT5_STATE["pending_commands"] = [
                                c for c in _MT5_STATE.get("pending_commands", [])
                                if not (c.get("action") == "OPEN_ORDER" and c.get("symbol", "").upper() == sym and c.get("direction") != new_action)
                            ]

                            if _flip_tickets:
                                _PENDING_FLIP[sym] = {
                                    "direction": new_action,
                                    "tickets": list(_flip_tickets),
                                    "close_ok": False,
                                }
                                continue
                            _LAST_SYMBOL_ENTRY_TIME[sym] = 0.0
                        else:
                            # Zıt yönlü ama maliyet kapısı (spread) aşılıyor — mevcut işlemi bozma.
                            # (flip_ignore_min_score açıkken skor asla bu kapıya takılmaz;
                            # yalnızca spread kapısı flip'i engeller — maliyet riski yaratır.)
                            continue

                    elif new_action in existing_dirs:
                        # (a) Aynı yönlü pozisyon zaten açıksa (örn: BUY açıkken tekrar BUY)
                        same_dir_count = sum(1 for p in matching_auto if p.get("direction", "").upper() == new_action) + \
                                         sum(1 for p in matching_mt5 if p.get("direction", "").upper() == new_action) + \
                                         sum(1 for c in matching_pending if c.get("direction", "").upper() == new_action)

                        # 2026-10-10 denetim P2-5: yorum "Varsayılan: 3" diyordu ama alan
                        # varsayılanı 1 (tek güvenli scalper pozisyonu) — yanıltıcı yorum düzeltildi.
                        max_pyr = _AUTO_SETTINGS.max_positions_per_symbol  # Varsayılan: 1 (ayarla 1-5)
                        if same_dir_count >= max_pyr:
                            if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_max_pyr", 0) > 40.0:
                                _LAST_CANDIDATE_LOG_TIME[f"{sym}_max_pyr"] = now_ts
                                _log_auto_decision(
                                    "SCAN",
                                    f"[{cand['display']}][{_c_strat_lbl}] Tarandı: Skor {cand['score']:.1f} ({new_action}) fakat bu yönde maksimum {max_pyr} pozisyon zaten açık ({same_dir_count}/{max_pyr}). Yeni giriş pas geçildi.",
                                    symbol=sym,
                                    strategy=_c_strat,
                                    strategy_label=_c_strat_lbl,
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
                                    f"[{cand['display']}][{_c_strat_lbl}] Piramitleme Kalkanı: Mevcut açık {same_dir_count} pozisyon henüz kârda değil (${existing_pnl_usd:+.2f}). Zarara ekleme engellendi (Kazanana ekleme kuralı).",
                                    symbol=sym,
                                    strategy=_c_strat,
                                    strategy_label=_c_strat_lbl,
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
                                    f"[{cand['display']}][{_c_strat_lbl}] Tarandı: Skor {cand['score']:.1f} ({new_action}) - Aynı yönde ek pozisyon için 1 dk kuralı ({same_dir_count}/{max_pyr} açık, {rem_sec} sn kaldı).",
                                    symbol=sym,
                                    strategy=_c_strat,
                                    strategy_label=_c_strat_lbl,
                                )
                            continue

                        # 60 saniye dolduysa ve count < 3 ise ve pozisyon kârdaysa: Aynı yönde ekleme onaylandı!
                        _log_auto_decision(
                            "SCAN",
                            f"[{cand['display']}][{_c_strat_lbl}] 📈 KÂRDA EK POZİSYON ONAYLANDI: Skor {cand['score']:.1f} ({new_action}) | Mevcut Kâr: ${existing_pnl_usd:+.2f} ({same_dir_count + 1}/{max_pyr}. pozisyon).",
                            symbol=sym,
                            strategy=_c_strat,
                            strategy_label=_c_strat_lbl,
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
                                f"[{cand['display']}][{_c_strat_lbl}] Ons Altın Soğuma Kalkanı: Kapanıştan sonra {remaining_cd} sn bekleniyor (min {_AUTO_SETTINGS.gold_cooldown_sec:.0f} sn kuralı).",
                                symbol=sym,
                                strategy=_c_strat,
                                strategy_label=_c_strat_lbl,
                            )
                        continue

                # 2b. Bitcoin (BTCUSD) Özel Soğuma Koruması (Kullanıcı kararı: 60 sn;
                # 2026-10-10: süre artık panelden ayarlanır — btc_cooldown_sec)
                # İlk start verildiğinde veya henüz kapanış olmadığında (<= 0) soğuma kalkanı dikkate alınmaz
                is_btc = ("BTC" in sym)
                _btc_cd_sec = float(_AUTO_SETTINGS.btc_cooldown_sec)
                if is_btc and _btc_cd_sec > 0 and _LAST_BTC_EXIT_TIME > 0:
                    if _LAST_BTC_EXIT_TIME > now_ts:
                        _LAST_BTC_EXIT_TIME = now_ts
                    time_since_btc_exit = max(0.0, now_ts - _LAST_BTC_EXIT_TIME)
                    if time_since_btc_exit < _btc_cd_sec:
                        remaining_btc_cd = int(min(_btc_cd_sec, max(0.0, _btc_cd_sec - time_since_btc_exit)))
                        if remaining_btc_cd > 0 and (now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_btc_cd", 0) > 20.0):
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_btc_cd"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}][{_c_strat_lbl}] Bitcoin Soğuma Kalkanı: Kapanıştan sonra {remaining_btc_cd} sn bekleniyor ({_btc_cd_sec:.0f} sn kuralı).",
                                symbol=sym,
                                strategy=_c_strat,
                                strategy_label=_c_strat_lbl,
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
                            f"[{cand['display']}][{_c_strat_lbl}] Sembol Soğuma Kalkanı: Son girişten sonra {int(sym_cd_left)} sn bekleniyor (min {sym_cd:.0f} sn kuralı).",
                            symbol=sym,
                            strategy=_c_strat,
                            strategy_label=_c_strat_lbl,
                        )
                    continue

                # 3b. Sembol EV Kalkanı — son pencerede sermaye yakan semboller dinlenir
                # (2026-10-10 denetim P0-3: BTCUSD artık VARSAYILAN olarak muaf DEĞİL — eski
                #  "BTC/XAU 60 sn soğuma" muafiyeti BTC'yi kayıp-uyarlamalı frenden yoksun
                #  bırakıyordu. XAU muafiyeti korunur; BTC istenirse btc_ev_exempt=True ile geri alınır.)
                _ev_exempt = (sym == "XAUUSD") or (sym == "BTCUSD" and _AUTO_SETTINGS.btc_ev_exempt)
                if _AUTO_SETTINGS.ev_guard_enabled and not _ev_exempt:
                    ev_override_until = _SYMBOL_EV_OVERRIDE_UNTIL.get(sym, 0.0)
                    if now_ts < ev_override_until:
                        # Kullanıcı bu sembolü bugün/geçici olarak EV kalkanından muaf tuttu
                        pass
                    else:
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
                                    f"[{cand['display']}][{_c_strat_lbl}] Sembol EV Kalkanı: Son {ev_stats['n']} işlemde ${ev_stats['net']:+.2f} "
                                    f"(WR %{ev_stats['win_rate']:.0f}) — sembol {_AUTO_SETTINGS.ev_window_hours:.0f} saatlik pencere boyunca dinlenmeye alındı.",
                                    symbol=sym,
                                    strategy=_c_strat,
                                    strategy_label=_c_strat_lbl,
                                )
                            continue

                # 3c. BTC net-negatif pencere freni (2026-10-10 denetim P0-3): ardışık-SL'e
                # bağlı olmayan, kayıp-uyarlamalı koruma. BTC EV muafiyeti geri açılsa bile
                # (btc_ev_exempt=True) salınan net-negatif seriyi yakalar.
                if (sym == "BTCUSD" and _AUTO_SETTINGS.btc_net_negative_guard_enabled
                        and now_ts >= _SYMBOL_EV_OVERRIDE_UNTIL.get(sym, 0.0)):
                    _btc_ev = _collect_symbol_ev(
                        sym, now_ts, float(_AUTO_SETTINGS.btc_net_negative_window_hours) * 3600.0)
                    if (_btc_ev.get("n", 0) >= _AUTO_SETTINGS.btc_net_negative_min_trades
                            and _btc_ev.get("net", 0.0) < _AUTO_SETTINGS.btc_net_negative_usd):
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_btcneg", 0) > 60.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_btcneg"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}][{_c_strat_lbl}] BTC Net-Negatif Freni: son "
                                f"{_AUTO_SETTINGS.btc_net_negative_window_hours:.0f} saatte {_btc_ev['n']} işlem, net "
                                f"${_btc_ev['net']:+.2f} (WR %{_btc_ev['win_rate']:.0f}) — BTC yeni giriş almıyor.",
                                symbol=sym,
                                strategy=_c_strat,
                                strategy_label=_c_strat_lbl,
                            )
                        continue

                # 4. DXY (ABD Dolar Endeksi) Rejim Filtresi
                # Pozisyon DXY rejimiyle çelişiyorsa veto; zayıf semboller nötr rejimde ekstra skor ister.
                direction = cand.get("action", "")  # BUY or SELL

                # 2026-10-14: TAKVİM YÖN KANITI (kullanıcı talebi).
                #   karşıt yön  → sinyal engellenir (risk azaltıcı)
                #   destek yönü → yumuşak filtreler atlanır (aşağıdaki 5c/7/7b/7c)
                # Kanıt yoksa (dir=0) veya ayar kapalıysa davranış BİREBİR eskisi.
                _nb_slot: Dict[str, Any] = {"dir": 0, "events": []}
                _dir_sign = 1 if direction == "BUY" else (-1 if direction == "SELL" else 0)
                _news_bypass = False
                if _AUTO_SETTINGS.news_bias_enabled:
                    try:
                        from app import forex_news_bias as _nb_mod
                        _nb_slot = _nb_mod.bias_for(sym)
                    except Exception:
                        _nb_slot = {"dir": 0, "events": []}
                    if _nb_slot.get("dir") and _dir_sign:
                        if _nb_slot["dir"] == -_dir_sign:
                            if _AUTO_SETTINGS.news_bias_block_opposing:
                                if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_news", 0) > 30.0:
                                    _LAST_CANDIDATE_LOG_TIME[f"{sym}_news"] = now_ts
                                    _ev0 = (_nb_slot.get("events") or [{}])[0]
                                    _log_auto_decision(
                                        "GATE",
                                        f"[{cand['display']}][{_c_strat_lbl}] Takvim karşıt yön: "
                                        f"{_ev0.get('title', '')} ({_ev0.get('currency', '')} "
                                        f"{_ev0.get('label', '')}) → {sym} "
                                        f"{'SELL' if _nb_slot['dir'] < 0 else 'BUY'} yönünü destekliyor; "
                                        f"{direction} sinyali engellendi.",
                                        symbol=sym, strategy=_c_strat, strategy_label=_c_strat_lbl,
                                    )
                                continue
                        else:
                            _news_bypass = bool(_AUTO_SETTINGS.news_bias_bypass_filters)
                            if _news_bypass and now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_newsbypass", 0) > 30.0:
                                _LAST_CANDIDATE_LOG_TIME[f"{sym}_newsbypass"] = now_ts
                                _evb = (_nb_slot.get("events") or [{}])[0]
                                _log_auto_decision(
                                    "GATE",
                                    f"[{cand['display']}][{_c_strat_lbl}] Takvim DESTEK: "
                                    f"{_evb.get('title', '')} ({_evb.get('currency', '')} "
                                    f"{_evb.get('label', '')}) → {direction} yönü destekleniyor; "
                                    f"yumuşak filtreler (seans/min-ATR, skor, ADX, SuperTrend) atlandı. "
                                    f"Maliyet/risk kapıları (spread, korelasyon, seri-SL, soğuma, lot bütçesi) AÇIK kaldı.",
                                    symbol=sym, strategy=_c_strat, strategy_label=_c_strat_lbl,
                                )
                if direction not in ("BUY", "SELL"):
                    continue

                weak_symbol_score_bump = 0.0
                if _AUTO_SETTINGS.dxy_filter_enabled:
                    veto_reason = dxy_entry_veto(sym, direction, dxy_regime)
                    if veto_reason in ("dxy_conflict", "dxy_no_data"):
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_dxy", 0) > 30.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_dxy"] = now_ts
                            _dxy_msg = (
                                "DXY Kalkanı: DXY verisi yok — majör parite girişi engellendi."
                                if veto_reason == "dxy_no_data"
                                else f"DXY Kalkanı: {direction} yönü dolar rejimiyle ({(dxy_regime or {}).get('regime', '—')}) çelişiyor. İşlem engellendi."
                            )
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}][{_c_strat_lbl}] {_dxy_msg}",
                                symbol=sym,
                                strategy=_c_strat,
                                strategy_label=_c_strat_lbl,
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
                                f"[{cand['display']}][{_c_strat_lbl}] Korelasyon Kalkanı: {cand_usd_bias} yönlü yüksek korelasyonlu açık pozisyon var ({corr_reason}). Aynı teze ikinci kapıdan giriş engellendi.",
                                symbol=sym,
                                strategy=_c_strat,
                                strategy_label=_c_strat_lbl,
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
                if gate_reason and not _news_bypass:
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_major", 0) > 30.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_major"] = now_ts
                        reason_str = ("Majör Seans Filtresi: UTC saat penceresi dışında (Asya seansı chop riski)."
                                      if gate_reason == "major_session" else
                                      f"Majör Volatilite Tabanı: ATR {float(cand.get('atr_pips', 0.0)):.1f}p < "
                                      f"{_AUTO_SETTINGS.major_min_atr_pips:.1f}p — ölü piyasa.")
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}][{_c_strat_lbl}] {reason_str} İşlem engellendi.",
                            symbol=sym,
                            strategy=_c_strat,
                            strategy_label=_c_strat_lbl,
                        )
                    continue

                # 6. Spread Filtresi
                effective_max_spread = max(50.0, _AUTO_SETTINGS.max_spread_pips * 10) if ("BTC" in sym or "ETH" in sym) else _AUTO_SETTINGS.max_spread_pips
                if cand["spread_pips"] > effective_max_spread:
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_spread", 0) > 25.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_spread"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}][{_c_strat_lbl}] Tarandı: Spread engeli ({cand['spread_pips']:.1f}p > {effective_max_spread:.1f}p limit). İşlem engellendi.",
                            symbol=sym,
                            strategy=_c_strat,
                            strategy_label=_c_strat_lbl,
                        )
                    continue

                # 7. Skor eşiği — panel ile aynı fonksiyon (emtia tabanı tek sabitte).
                req_score = required_entry_score(sym, weak_symbol_score_bump)
                if cand["score"] < req_score and not _news_bypass:
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_score", 0) > 25.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_score"] = now_ts
                        _log_auto_decision(
                            "SCAN",
                            f"[{cand['display']}][{_c_strat_lbl}] Tarandı: Skor yetersiz ({cand['score']:.1f} < {req_score:.0f} eşik) | Yön: {cand['action']} | Spread: {cand['spread_pips']:.1f}p | Beklemede.",
                            symbol=sym,
                            strategy=_c_strat,
                            strategy_label=_c_strat_lbl,
                        )
                    continue

                # 7b. ADX Trend Gücü Kalkanı — çalkantılı/yönsüz piyasada trend girişi yapılmaz
                adx_val = float(cand.get("adx", 25.0))
                if _AUTO_SETTINGS.adx_filter_enabled and adx_val < _AUTO_SETTINGS.adx_min and not _news_bypass:
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_adx", 0) > 30.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_adx"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}][{_c_strat_lbl}] ADX Kalkanı: Trend gücü yetersiz (ADX {adx_val:.1f} < {_AUTO_SETTINGS.adx_min:.0f}) — piyasa yönsüz. İşlem engellendi.",
                            symbol=sym,
                            strategy=_c_strat,
                            strategy_label=_c_strat_lbl,
                        )
                    continue

                # 7c. SuperTrend Yön Teyidi — giriş yalnızca SuperTrend tarafıyla uyumlu açılır
                # İstisna: EMA+ADX geri-çekilme modu KENDİ yön teyidini taşır (EMA8/21/50
                # dizilimi + onay barı); SuperTrend bu moda canlı davranışı replay kanıtından
                # saptırırdı (kanıt EAP-pure koşuldu) → bu aday için ST kapısı atlanır.
                # Aynı istisna S3 için geçerli: ST(10,3) stratejinin KENDİ yön motorudur
                # (replay PURE koşumu kural seti birebir). Keltner Squeeze için de
                # istisna ZORUNLU: kanıt `--combined` kol koşumunda ST filtresi KAPALI
                # alındı (harness varsayılanı TUN_ST_FILTER=False) → canlıda filtre
                # açıkken uygulanırsa test edilen davranıştan sapar.
                st_dir = int(cand.get("supertrend_dir", 0))
                if supertrend_blocks_entry(cand.get("entry_source", ""), direction, st_dir, news_bypass=_news_bypass):
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_st", 0) > 30.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_st"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}][{_c_strat_lbl}] SuperTrend Teyidi: {direction} yönü SuperTrend yönüyle ({'BOĞA' if st_dir > 0 else 'AYI'}) çelişiyor. İşlem engellendi.",
                            symbol=sym,
                            strategy=_c_strat,
                            strategy_label=_c_strat_lbl,
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
                elif _AUTO_SETTINGS.crypto_sl_atr_mult > 0 and ("BTC" in sym or "ETH" in sym):
                    # 2026-10-10 denetim P2-10: `crypto_sl_atr_mult` yalnız ATR çıkış motoru
                    # açıkken uygulanır. Kapatılırsa BTC sessizce `spec["sl_pips"]`'e döner —
                    # kalibre edilmiş kripto stopu kaybolur ve kimse fark etmez. Sessizliği
                    # kaldır: ayar açıkken motor kapalıysa karar akışına uyarı düşer.
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_atr_off", 0.0) > 300.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_atr_off"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}][{_c_strat_lbl}] ⚠️ ATR çıkış motoru KAPALI ama "
                            f"crypto_sl_atr_mult={_AUTO_SETTINGS.crypto_sl_atr_mult} ayarlı — kripto "
                            f"stopu uygulanmıyor, spec SL ({spec['sl_pips']:.0f}p) kullanılıyor.",
                            symbol=sym,
                            strategy=_c_strat,
                            strategy_label=_c_strat_lbl,
                        )
                if str(cand.get("entry_source", "")) == "donchian" and atr_pips > 0:
                    # Donchian modu çıkışları (replay ile birebir): SL 2×ATR, TP 4×ATR, kısmi kâr yok
                    sl_pips = round(2.0 * atr_pips, 1)
                    tp_pips = round(4.0 * atr_pips, 1)
                    first_target_pips = 0.0
                if str(cand.get("entry_source", "")) == "ema_adx_pullback" and atr_pips > 0:
                    # EMA+ADX geri-çekilme modu çıkışları (replay ile birebir): SL 1.5×ATR,
                    # TP 2.0×ATR (0 ise sabit TP yok → BE/trailing), kısmi kâr yok.
                    sl_pips = round(float(_AUTO_SETTINGS.ema_adx_sl_atr) * atr_pips, 1)
                    tp_pips = round(float(_AUTO_SETTINGS.ema_adx_tp_atr) * atr_pips, 1)
                    first_target_pips = 0.0
                if str(cand.get("entry_source", "")).startswith("s3_") and atr_pips > 0:
                    # S3 çıkışları (replay ile birebir): SL 1.5×ATR her iki kol.
                    # 15m kol: TP 2.0×ATR. 5m kol: TP YOK (ST-flip çıkışı + BE/trailing).
                    sl_pips = round(float(_AUTO_SETTINGS.s3_sl_atr) * atr_pips, 1)
                    if str(cand.get("entry_source", "")) == "s3_15m":
                        tp_pips = round(float(_AUTO_SETTINGS.s3_tp_atr_15m) * atr_pips, 1)
                    else:
                        tp_pips = 0.0
                    first_target_pips = 0.0
                if str(cand.get("entry_source", "")) == "london_breakout":
                    # London Breakout çıkışları (replay ile birebir): SL = kutu × frac,
                    # TP = SL × R — aday üretilirken hesaplanıp taşındı (kutu başına sabit).
                    sl_pips = float(cand.get("sl_pips_override") or sl_pips)
                    tp_pips = float(cand.get("tp_pips_override") or tp_pips)
                    first_target_pips = 0.0
                if str(cand.get("entry_source", "")) == "london_sign":
                    # London Sign çıkışları (replay ile birebir): SL = 1.5×ATR, SABİT TP YOK.
                    # TP bilinçli 0 yazılır (override 0 falsy → `or tp_pips` yanlış olurdu);
                    # kazanç chandelier trailing + BE kilidiyle taşınır.
                    sl_pips = float(cand.get("sl_pips_override") or sl_pips)
                    tp_pips = 0.0
                    first_target_pips = 0.0
                if str(cand.get("entry_source", "")) == "squeeze_kc":
                    # Keltner Squeeze çıkışları (replay ile birebir): SL = |kapanış − KC
                    # orta|, TP = 2R. Aday üretilirken hesaplanıp taşındı; pip_size<=0 ise
                    # override None gelir → spec SL/TP yoluna düşülür (replay'in ATR-exit
                    # fallback'i).
                    _skc_ov = cand.get("sl_pips_override")
                    if _skc_ov:
                        sl_pips = float(_skc_ov)
                        tp_pips = float(cand.get("tp_pips_override") or tp_pips)
                        first_target_pips = 0.0

                active_bal = float(_MT5_STATE.get("account", {}).get("balance", _AUTO_STATE["balance"])) if _MT5_STATE.get("connected") else float(_AUTO_STATE["balance"])
                risk_usd = active_bal * (_AUTO_SETTINGS.risk_per_trade_pct / 100.0)

                # Seans Likiditesi Koruması: 16:00 - 20:00 UTC (London Fix sonrası sığ likidite ve NY testeresi)
                # aralığında risk otomatik olarak %50 ölçeklenir
                curr_utc_hour = datetime.datetime.now(datetime.timezone.utc).hour
                if 16 <= curr_utc_hour < 20:
                    risk_usd *= 0.50

                # Komisyon ($7/lot) ve spread tamponlu efektif risk paydası
                comm_per_lot = 7.0 if (len(sym) == 6 and sym[:3].isalpha() and sym[3:].isalpha()) else 0.0
                effective_risk_denom = max(1.0, (sl_pips * pip_val) + comm_per_lot)
                raw_calc_lots = round(risk_usd / effective_risk_denom, 2)

                # Dinamik Lot & Risk Hesaplama (Modalda belirlenen risk yüzdesine göre)
                is_index = ("NAS" in sym or "USTEC" in sym or "US30" in sym or "SPX" in sym)
                is_oil = ("USOIL" in sym or "OIL" in sym or "WTI" in sym or "XTI" in sym)
                is_crypto = ("BTC" in sym or "ETH" in sym)
                if is_crypto and not _AUTO_SETTINGS.crypto_tp_enabled and not str(cand.get("entry_source", "")).startswith("s3_") and str(cand.get("entry_source", "")) != "squeeze_kc":
                    # Kriptoda sabit TP kapalı (2026-10-06 30g replay kazananı: BTC −$55.70→−$18.02):
                    # kazanç BE kilidi + trailing ile koşturulur, TP emri kurulmaz.
                    # İstisna 1: S3 adayı — kanıt koşumda TP'liydi (BTC 15m +$59.28 PF 6.63).
                    # İstisna 2: Keltner Squeeze — kanıt koşumu TP = 2R sabit TP'liydi
                    # (5 sembolün biri BTCUSD); TP sıfırlanırsa test edilen davranıştan sapar.
                    tp_pips = 0.0

                if is_index:
                    lot_ceiling = min(HARD_MAX_INDEX_LOT, _AUTO_SETTINGS.max_index_lot)
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
                    # Cross FX (CAD/CHF/NZD/JPY) paritelerinde aşırı lot birikimini engelleyen 0.75 lot güvenlik tavanı
                    is_cross_fx = len(sym) == 6 and any(k in sym for k in ("CAD", "CHF", "NZD", "AUD"))
                    lot_ceiling = min(0.75 if is_cross_fx else HARD_MAX_FOREX_LOT, _AUTO_SETTINGS.max_forex_lot)
                    mt5_lots = max(0.01, min(raw_calc_lots, lot_ceiling))
                mt5_lots = round(mt5_lots, 2)

                # 8b. Risk Normalizasyonu: ATR ile genişleyen SL'de lot tavanı risk
                # bütçesini aşabilir (gerçek örnek: US30 0.20 lot × 81.7 pip = %1.6).
                # Lot bütçeye çekilir; kategori minimumu bile sert sınırı aşıyorsa pas.
                # Kripto+altın istisnası (2026-10-08 kullanıcı kararı): BTC/XAU'da lot
                # zaten kategori minimumu — geniş ATR SL'i (ör. BTC 339p) skip kapısına
                # takılıp adayları sürekli eziyordu; kripto ve altında pas yok.
                # 2026-10-10 denetim P0-4: skip'i "pas geç" yerine lotu kategori TABANINA
                # SABİTLE — eski davranış aşırı (yüksek-risk) lotu olduğu gibi kullanıyordu.
                mt5_lots, risk_skip = apply_risk_normalization(sym, mt5_lots, sl_pips, pip_val, risk_usd)
                if risk_skip and (is_crypto or is_gold):
                    if _AUTO_SETTINGS.crypto_risk_clamp_enabled:
                        if is_crypto:
                            _floor_lot = 0.01
                        else:
                            _floor_lot = min(HARD_MAX_GOLD_LOT, _AUTO_SETTINGS.max_gold_lot, 0.01)
                        # 2026-10-14 DÜZELTME: kelepçe artık bütçe sert tavanına TABİ.
                        # Önceden `risk_skip` KOŞULSUZ iptal ediliyordu → küçük bakiyede taban
                        # lotun riski bakiyenin %5-20'sine çıkıyordu (ReportHistory-53077151:
                        # medyan %9.94, tepe %14.9 — ayar %5 idi). Taban lot sert tavanı
                        # (RISK_HARD_MULT × bütçe) aşıyorsa işlem PAS geçilir; bütçe delinmez.
                        if floor_lot_respects_budget(_floor_lot, sl_pips, pip_val, risk_usd):
                            mt5_lots = max(0.01, _floor_lot)
                            risk_skip = False
                    else:
                        risk_skip = False  # eski davranış (aşırı lot korunur)
                if risk_skip:
                    if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_risk", 0) > 30.0:
                        _LAST_CANDIDATE_LOG_TIME[f"{sym}_risk"] = now_ts
                        _log_auto_decision(
                            "GATE",
                            f"[{cand['display']}][{_c_strat_lbl}] Risk Kalkanı: SL {sl_pips:.0f}p ile en küçük mümkün lot bile "
                            f"{_AUTO_SETTINGS.risk_per_trade_pct:.1f}% bütçenin 2 katını aşıyor. İşlem pas geçildi.",
                            symbol=sym,
                            strategy=_c_strat,
                            strategy_label=_c_strat_lbl,
                        )
                    continue

                entry_p = t["ask"] if direction == "BUY" else t["bid"]

                # IC Markets MT5 bağlıysa doğrudan MT5 emir kuyruğuna ekle
                if _MT5_STATE.get("connected") and _MT5_STATE.get("auto_trade"):
                    if _non_demo_live_blocked((_MT5_STATE.get("account") or {}).get("server")):
                        if now_ts - _LAST_CANDIDATE_LOG_TIME.get(f"{sym}_nondemo", 0) > 60.0:
                            _LAST_CANDIDATE_LOG_TIME[f"{sym}_nondemo"] = now_ts
                            _log_auto_decision(
                                "GATE",
                                f"[{cand['display']}][{_c_strat_lbl}] Development modunda demo olmayan hesaba emir yazilmadi.",
                                symbol=sym,
                                strategy=_c_strat,
                                strategy_label=_c_strat_lbl,
                            )
                        continue
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
                        "max_positions_per_symbol": _AUTO_SETTINGS.max_positions_per_symbol,
                        # Pozisyon bazlı çıkış planı: köprü BE/Trail'i motorun gönderdiği değerlerle
                        # yönetsin (köprünün kendi spec kopyası ikinci kez hesap yapmaz)
                        "be_pips": spec_exits["be_pips"],
                        "trail_pips": spec_exits["trail_pips"],
                        # Giriş ATR'si (pip) — köprünün chandelier'i GİRİŞ ATR'siyle
                        # hesaplaması için işlemle birlikte taşınır (replay paritesi:
                        # trailing girişte dondurulmuş ATR kullanır).
                        "entry_atr_pips": round(float(atr_pips), 1),
                        "be_lock_ratio": _AUTO_SETTINGS.gold_be_lock_ratio if is_gold else 0.40,
                        "partial_pips": first_target_pips,
                        # Strateji etiketi MT5 emrine gömülür (kapanan deal `comment`'iyle geri
                        # gelir → işlem kaydında hangi strateji olduğu görünür). 31 kr sınırı.
                        "comment": f"{strategy_comment_tag(cand.get('entry_source'))} {cand['score']:.0f}",
                        "strategy": _c_strat,
                        "strategy_label": _c_strat_lbl,
                        "strategy_tag": strategy_comment_tag(cand.get("entry_source")),
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
                                f"[{cand['display']}][{_c_strat_lbl}] MT5 köprüsü bağlı değil — yeni işlem açılmadı "
                                f"(paper'a sessiz kayma engellendi).",
                                symbol=sym,
                                strategy=_c_strat,
                                strategy_label=_c_strat_lbl,
                            )
                        continue
                    # MT5 bağlı değilse Paper Engine sanal pozisyon havuzuna ekle
                    sl_dist = sl_pips * spec["pip_size"]
                    tp_dist = tp_pips * spec["pip_size"]
                    # tp_pips <= 0 = sabit TP YOK (S3 5m / London Sign gibi trail-modları,
                    # canlı MT5 yolu `tp=0.0` yazar = TP'siz). Paper yolunda eskiden
                    # tp_price = entry_price oluyordu → pozisyon açılış anında "TP vuruldu"
                    # sayılıp kapanabiliyordu. MT5 semantiğiyle hizala: TP yoksa tp_price=0.
                    tp_price = (round(entry_p + tp_dist if direction == "BUY" else entry_p - tp_dist, spec["digits"])
                                if tp_pips > 0 else 0.0)
                    pos_item = {
                        "id": f"FX-{int(time.time() * 1000) % 1000000}",
                        "symbol": sym,
                        "display": cand["display"],
                        "direction": direction,
                        "lots": mt5_lots,
                        "entry_price": entry_p,
                        "current_price": entry_p,
                        "sl_price": round(entry_p - sl_dist if direction == "BUY" else entry_p + sl_dist, spec["digits"]),
                        "tp_price": tp_price,
                        "initial_sl_price": round(entry_p - sl_dist if direction == "BUY" else entry_p + sl_dist, spec["digits"]),
                        "breakeven_activated": False,
                        "trailing_activated": False,
                        "partial_taken": False,
                        "partial_target_pips": first_target_pips,
                        "partial_realized_usd": 0.0,
                        "initial_lots": mt5_lots,
                        # Giriş ATR'si (pip) — chandelier trailing paritesi için pozisyonda
                        # SAKLANIR. Replay trailing'i giriş ATR'siyle hesaplar
                        # (forex_replay_backtest.py:1828); canlı eskiden her tick CARİ ATR'yi
                        # kullanıyordu → ATR sıçrayınca trailing mesafesi işlem ortasında
                        # genişleyip kazanılan pip geri veriliyordu. 2026-10-13.
                        "entry_atr_pips": round(float(atr_pips), 1),
                        "opened_at_ts": now_ts,
                        "open_time": datetime.datetime.fromtimestamp(now_ts, TZ_UTC3).strftime("%H:%M:%S UTC+3"),
                        "pnl_usd": 0.0,
                        "pnl_pips": 0.0,
                        "pip_size": spec["pip_size"],
                        "digits": spec["digits"],
                        "score": cand["score"],
                        "entry_source": cand.get("entry_source", ""),
                        "strategy": _c_strat,
                        "strategy_label": _c_strat_lbl,
                        "strategy_tag": strategy_comment_tag(cand.get("entry_source")),
                        # EoD zaman-stopu (dakika): swap/gece taşımadan kapat (London Sign spec).
                        "hold_minutes": int(cand.get("hold_minutes", 0) or 0),
                    }
                    async with _AUTO_PAPER_LOCK:
                        _AUTO_STATE["open_positions"].append(pos_item)
                    _invalidate_status_cache()

                _LAST_SYMBOL_ENTRY_TIME[sym] = now_ts
                _commit_arm_quota(cand)
                _opened_cycle.add(sym)
                if (_PENDING_FLIP.get(sym) or {}).get("close_ok"):
                    _PENDING_FLIP.pop(sym, None)
                if not _c_src:
                    _LAST_RADAR_SIGNAL_BAR[sym] = int(cand.get("signal_bar_time") or 0)
                if sym == "XAUUSD" and not _c_src:
                    _LAST_XAU_RADAR_SIGNAL_BAR[sym] = int(cand.get("signal_bar_time") or 0)

                actual_risk_usd = round(mt5_lots * sl_pips * pip_val, 2)
                _strat_name = strategy_name_for(cand.get("entry_source"))
                _strat_lbl = strategy_display_label(cand.get("entry_source"))
                signal_bar_time = cand.get("signal_bar_time")
                signal_bar_context = ""
                if signal_bar_time:
                    signal_bar_local = datetime.datetime.fromtimestamp(
                        int(signal_bar_time), TZ_UTC3
                    ).strftime("%H:%M:%S UTC+3")
                    st_label = "BOĞA" if int(cand.get("supertrend_dir", 0)) > 0 else (
                        "AYI" if int(cand.get("supertrend_dir", 0)) < 0 else "BELİRSİZ"
                    )
                    signal_bar_context = (
                        f" | Teyit: 15M {cand.get('htf_trend', 'NA')}, "
                        f"5M ST {st_label}, kapanmış mum açılışı {signal_bar_local}"
                    )
                _log_auto_decision(
                    "ENTRY",
                    f"⚡ [İŞLEM AÇILDI] [{_strat_lbl}] {mt5_lots} Lot {direction} {sym} @ {entry_p} | TP: +{tp_pips}p | SL: -{sl_pips}p | Risk: ${actual_risk_usd:.2f} (Skor: {cand['score']:.0f}){signal_bar_context}",
                    symbol=sym,
                    strategy=_strat_name,
                    strategy_label=_strat_lbl,
                    metadata={"lots": mt5_lots, "direction": direction, "score": cand["score"],
                              "risk_usd": actual_risk_usd, "strategy": _strat_name,
                              "strategy_label": _strat_lbl,
                              "entry_source": cand.get("entry_source", ""),
                              "signal_bar_time": cand.get("signal_bar_time"),
                              "signal_bar_confirmed": (
                                  bool(cand.get("signal_bar_confirmed", False))
                                  if not cand.get("entry_source") else None
                              ),
                              "htf_trend": cand.get("htf_trend"),
                              "supertrend_dir": cand.get("supertrend_dir"),
                              "rsi_m5": cand.get("rsi_15m"),
                              "adx": cand.get("adx"),
                              "macd_hist": cand.get("macd_hist"),
                              "direction_guard_reason": cand.get("direction_guard_reason", "")},
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


def _invalidate_status_cache() -> None:
    """`/auto-paper/status` önbelleğini geçersiz kılar.

    Önbellek 1 sn TTL taşır; pozisyon kapatma, emir gönderme, panel açma/kapama ve
    sıfırlama gibi DURUMU DEĞİŞTİREN uçlardan sonra çağrılmalıdır. Aksi halde istemci
    bir sonraki saniyeye kadar bayat veri görür (ör. elle kapatılan pozisyon hâlâ
    "açık" görünür).
    """
    global _STATUS_CACHE
    _STATUS_CACHE = None


# Kokpit kapı-görünümü için hafif önbellek: iki sembol, 2 sn TTL. Snapshot salt
# okumadır ama `_collect_symbol_ev` her çağrıda tüm kapanış defterini tarar;
# kokpit 3 sn'de bir iki sembol için çekerken bu, status ucunun 1 sn TTL
# önbelleğiyle aynı desendir (bkz. /auto-paper/status PERFORMANS notu).
_GATE_SNAPSHOT_CACHE: Dict[str, tuple] = {}
_GATE_SNAPSHOT_TTL = 2.0

# Radar sayfasının periyodik strateji taraması için önbellek (bkz.
# GET /auto-paper/strategy-scan). `_scan_now_strategy_rows` her turda canlı tick +
# teknik gösterge tazeler; sayfa 3 sn'de bir yokladığı için TTL 5 sn tutulur.
# Dict-mutasyonu deseni bilinçli: döngü içinde yeniden atama `global` bildirimi
# gerektirir ve bu dosyada globals-shadow regresyonu test ediliyor.
_STRATEGY_SCAN_CACHE: Dict[str, Any] = {"ts": 0.0, "payload": None}
_STRATEGY_SCAN_TTL = 5.0


@router.get("/auto-paper/gate-snapshot/{symbol}")
async def get_gate_snapshot(symbol: str):
    """Tek sembolün giriş kapısı zincirinin ANLIK durumu (kokpit paneli).

    2026-10-10: /forex/btc-gold kokpiti BTC'nin "neden işlem açmıyor" sorusunu
    kapı-kapı yanıtlar. Salt-okunur: motordaki hiçbir sayacı değiştirmez.
    Döngüdeki kapılarla aynı yardımcı fonksiyonlar kullanıldığı için panel,
    karar akışından kopamaz (ayrı bir kural seti YOK).
    """
    sym = str(symbol or "").upper().replace("/", "").strip()
    if not sym:
        raise HTTPException(status_code=400, detail="Sembol boş olamaz.")
    # Sonekli/alias broker adını kanonikleştir (BTCUSD.m, BTC, GOLD vb.)
    app_sym = canonical_symbol(sym)
    now_ts = time.time()
    cached = _GATE_SNAPSHOT_CACHE.get(app_sym)
    if cached is not None and now_ts - cached[0] < _GATE_SNAPSHOT_TTL:
        return cached[1]
    snap = get_symbol_gate_snapshot(app_sym, tick=_TICK_CACHE.get(app_sym), now_ts=now_ts)
    _GATE_SNAPSHOT_CACHE[app_sym] = (now_ts, snap)
    return snap


@router.get("/auto-paper/status")
async def get_forex_auto_paper_status():
    """IC Markets MT5 Otonom Scalper sistem durumu, canlı MT5 pozisyonları ve hesap metrikleri.

    PERFORMANS (2026-10-08): 1 sn TTL'li sunucu içi önbellek. Bu uç normalizesiz
    onlarca kayıt + EV hesapları içeren büyük bir JSON döner ve ana sayfa,
    portföy, MetaMobil, radar modalı gibi birden çok istemci tarafından saniyede
    birden çok kez çağrılır. Önbellek taze ise aynı yanıt döner.
    """
    now_ts = time.time()
    global _STATUS_CACHE
    cached = _STATUS_CACHE
    if cached is not None and now_ts - cached[0] < _STATUS_CACHE_TTL:
        return cached[1]

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
            # Strateji kimliği (açık pozisyonlar için etiketten çözülür)
            "strategy": strategy_from_mt5_deal(p),
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
            "strategy": strategy_from_mt5_deal(d),
            "entry_source": d.get("entry_source", ""),
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

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    today_midnight = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    today_midnight_ts = today_midnight.timestamp()

    today_deals = [d for d in normalized_deals if (_deal_ts(d) or 0.0) >= today_midnight_ts]
    today_wins = sum(1 for d in today_deals if d["pnl_usd"] >= 0)
    today_losses = sum(1 for d in today_deals if d["pnl_usd"] < 0)
    today_total = len(today_deals)
    today_pnl_usd = round(sum(d["pnl_usd"] for d in today_deals), 2)
    today_pnl_pips = round(sum(float(d.get("pnl_pips", 0.0)) for d in today_deals), 1)
    today_win_rate = round((today_wins / today_total * 100.0), 1) if today_total > 0 else 0.0

    today_gross_profit = round(sum(d["pnl_usd"] for d in today_deals if d["pnl_usd"] >= 0), 2)
    today_gross_loss = round(abs(sum(d["pnl_usd"] for d in today_deals if d["pnl_usd"] < 0)), 2)
    if today_gross_loss > 0:
        today_pf = round(today_gross_profit / today_gross_loss, 2)
    elif today_gross_profit > 0:
        today_pf = _PF_INFINITE
    else:
        today_pf = 0.0

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

    response = {
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
        "daily_pnl": today_pnl_usd,
        "daily_pips": today_pnl_pips,
        "daily_trades": today_total,
        "daily_wins": today_wins,
        "daily_losses": today_losses,
        "daily_win_rate": today_win_rate,
        "today_kpi": {
            "total_trades": today_total,
            "wins": today_wins,
            "losses": today_losses,
            "win_rate": today_win_rate,
            "total_pnl_usd": today_pnl_usd,
            "total_pnl_pips": today_pnl_pips,
            "profit_factor": today_pf,
            "profit_factor_infinite": today_pf >= _PF_INFINITE,
            "gross_profit_usd": today_gross_profit,
            "gross_loss_usd": today_gross_loss,
            "balance": balance,
            "equity": equity,
            "open_positions_count": len(normalized_positions),
            "open_pnl_usd": open_pnl_usd,
        },
        "today_trades": today_deals,
        # Sembol bazlı günlük KPI kartları (portföy sayfası). `today_deals` +
        # açık pozisyonlardan türetilir; kartların TOPLAMI yukarıdaki
        # `today_kpi` ile aynı defterden geldiği için birebir tutar.
        "per_symbol_today": _aggregate_daily_symbol_kpi(
            today_deals, normalized_positions, today_midnight_ts
        ),
        # Sembol bazlı TÜM ZAMANLAR KPI'ları (aynı defter, `min_ts=0` → kesme yok).
        # Bugün ve tüm zamanlar AYNI normalize defterden türetildiği için iki görünüm
        # birbirini tutar; panel ikisini yan yana gösterir (bkz. `per_symbol_today`).
        "per_symbol_all_time": _aggregate_symbol_kpi(
            normalized_deals, normalized_positions, 0.0
        ),
        "settings": _AUTO_SETTINGS.model_dump(),
        "open_positions": normalized_positions,
        "closed_trades": normalized_deals,
        "decision_logs": _AUTO_STATE["decision_logs"][:300],
        "sessions": _get_market_sessions(),
        "dxy": get_dxy_regime(),
        "correlations": _FX_CORR.snapshot(),
        "correlations_updated_at": _FX_CORR.last_updated,
        "symbol_ev": {
            s: _collect_symbol_ev(s, time.time(), _AUTO_SETTINGS.ev_window_hours * 3600.0)
            for s in _AUTO_SETTINGS.allowed_symbols
        },
        "ev_shield": get_all_symbol_ev_status(time.time()),
        "last_scan_time": _AUTO_STATE["last_scan_time"],
        "mt5_account": mt5_acc,
        "mt5_connected": is_mt5_conn,
    }
    _STATUS_CACHE = (now_ts, response)
    return response


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
            _AUTO_SETTINGS.allowed_symbols = ForexAutoPaperSettings().allowed_symbols
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

    _invalidate_status_cache()
    return {
        "enabled": _AUTO_STATE["enabled"],
        "status": _AUTO_STATE["last_status"],
        "message": "Otonom Forex Scalper durumu güncellendi.",
    }


def start_forex_auto_paper():
    """Forex Otonom Scalper motorunu arka planda başlatır."""
    global _AUTO_PAPER_TASK, _AUTO_STATE, _AUTO_SETTINGS, _MT5_STATE, _LAST_GOLD_EXIT_TIME, _LAST_BTC_EXIT_TIME
    _AUTO_STATE["enabled"] = True
    _AUTO_SETTINGS.enabled = True
    _MT5_STATE["auto_trade"] = True
    _invalidate_status_cache()
    if not _AUTO_SETTINGS.allowed_symbols:
        _AUTO_SETTINGS.allowed_symbols = ForexAutoPaperSettings().allowed_symbols
    _LAST_GOLD_EXIT_TIME = 0.0
    _LAST_BTC_EXIT_TIME = 0.0
    _LAST_SYMBOL_ENTRY_TIME.clear()
    if _AUTO_PAPER_TASK is None or _AUTO_PAPER_TASK.done():
        _AUTO_PAPER_TASK = asyncio.create_task(_forex_auto_paper_loop())
        _log_auto_decision("SYSTEM", "Forex Otonom Scalper motoru başlatıldı.")


def stop_forex_auto_paper():
    """Forex Otonom Scalper motorunu durdurur."""
    global _AUTO_PAPER_TASK, _AUTO_STATE, _AUTO_SETTINGS, _MT5_STATE
    _AUTO_STATE["enabled"] = False
    _AUTO_SETTINGS.enabled = False
    _MT5_STATE["auto_trade"] = False
    if _AUTO_PAPER_TASK and not _AUTO_PAPER_TASK.done():
        _AUTO_PAPER_TASK.cancel()
        _AUTO_PAPER_TASK = None
    _AUTO_STATE["last_status"] = "Durduruldu"
    _log_auto_decision("SYSTEM", "Forex Otonom Scalper motoru durduruldu.")


@router.post("/auto-paper/settings")
async def update_forex_auto_paper_settings(payload: Union[ForexAutoPaperSettings, Dict[str, Any]]):
    """Otonom scalper risk ve filtre parametrelerini günceller (P1-5: kısmi birleştirme).

    Gövde tam ya da KISMİ olabilir. Eksik alanlar mevcut değerini KORUR (eskiden tüm
    nesne değiştirildiği için eksik alan sessizce varsayılana sıfırlanıyordu — ör.
    btc_min_score/crypto_sl_atr_mult). Geçerli ayarlar diske yazılır (restart kalıcı).
    """
    global _AUTO_SETTINGS
    try:
        if isinstance(payload, ForexAutoPaperSettings):
            # Tam nesne gövdesi (geriye dönük uyum): mevcut ayarların üzerine birleştir.
            body = payload.model_dump()
            try:
                provided = payload.model_fields_set
            except Exception:
                provided = set(body.keys())
            body = {k: v for k, v in body.items() if k in provided}
            new_settings = merge_settings_payload(body)
        else:
            new_settings = merge_settings_payload(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Ayarlar uygulanamadı: {exc}")
    # Çalışma durumunu koru (motorun durdurulup başlatılması toggle endpoint'iyle yönetilir)
    new_settings.enabled = _AUTO_STATE["enabled"]
    _AUTO_SETTINGS = new_settings
    persist_settings(_AUTO_SETTINGS)

    _log_auto_decision(
        "SYSTEM",
        f"Parametreler güncellendi: Risk: %{new_settings.risk_per_trade_pct}, SL: {new_settings.sl_pips}p, TP: {new_settings.tp_pips}p, BE: {new_settings.breakeven_pips}p, Trailing: {new_settings.trailing_stop_pips}p, Min Skor: {new_settings.min_score}",
    )
    _invalidate_status_cache()
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
        # 2026-10-10 denetim P1-7: YÖN bazlı sayaçlar da temizlenmeli — yoksa
        # "temiz sayfa" sonrası (sembol,yön) soğuması ayakta kalıp girişi reddediyordu.
        _SYMBOL_DIR_LOSS_STREAK.clear()
        _SYMBOL_DIR_LOSS_COOLDOWN_UNTIL.clear()
        _SYMBOL_EV_OVERRIDE_UNTIL.clear()
        _SYMBOL_EV_RESET_AT_TS.clear()
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
                 + ("seri-SL (sembol + yön) sayaçları sıfırlandı; " if full_reset else "seri-SL sayaçlarına dokunulmadı; ")
                 + "eski işlemler arşivde (bellek + JSON dosyası). Bakiye değişmedi."),
    }


# ============================================================================
# MANUEL TARAMA TETİKLEYİCİ (ŞİMDİ TARA)
# ============================================================================

def _scan_now_strategy_rows(ticks: Dict[str, Dict[str, Any]], radar: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Tüm stratejilerin ŞU ANKI durumunu tek turda değerlendirir (salt-okunur).

    Motor döngüsündeki aday üretim felsefesini aynalar: saf giriş fonksiyonları
    çağrılır ama `counts` sayaçları ve `_DONCHIAN_STATE`/`_S3_DAY_STATE`/
    `_LB_STATE`/`_LS_STATE` GÜNCELLENMEZ (kopya üzerinde çalışılır) — manuel tarama
    hiçbir zaman gerçek girişin gün-limitini yakmamalı. Data refresh yine de
    yapılır (taze tick + teknik) ama motor state'ine dokunulmaz.

    Kapsam (2026-10-14): motordaki TÜM giriş kolları taranır — RADAR (klasik skor),
    DONCHIAN_ADX, EMA_ADX_PULLBACK_M5, S3 (5m+15m), LONDON_BREAKOUT, LONDON_SIGN,
    SQUEEZE_KC_M15. Yeni bir kol eklenirse (bkz. `_forex_auto_paper_loop` aday
    üretimi) buraya da eklenmeli; aksi halde kol canlıda çalışır ama radar sayfası
    onu hiç göstermez (LS tam bu yüzden eksik kalmıştı).
    """
    s = _AUTO_SETTINGS
    now = datetime.datetime.now(datetime.timezone.utc)
    day = now.toordinal()
    hour = now.hour
    rows: List[Dict[str, Any]] = []
    allowed = {x.upper() for x in (s.allowed_symbols or [])}

    def _row(strategy: str, sym: str, status: str, action: Optional[str] = None) -> None:
        item = next((i for i in FOREX_SYMBOLS if i["symbol"] == sym), None)
        rows.append({
            "strategy": strategy,
            "strategy_label": strategy_display_label(strategy),
            "symbol": sym,
            "display": (ticks.get(sym, {}) or {}).get("display") or (item["display"] if item else sym),
            "status": status,
            "action": action,
            "panel_kapsaminda": sym in allowed,
        })

    # --- 1) RADAR (klasik çoklu skor taraması) — radar sonucundan özet
    try:
        top = radar.get("candidates", [])[:3]
        if top:
            for c in top:
                _row("RADAR", str(c.get("symbol", "")).upper(),
                     f"{c.get('action')} adayı skor {float(c.get('score', 0)):.0f} ({c.get('tier', '')})",
                     c.get("action"))
        else:
            _row("RADAR", "—", str(radar.get("scan_note") or "Aday yok — eşiklerin üstünde sinyal yok"))
    except Exception as exc:
        _row("RADAR", "—", f"Tarama hatası: {exc}")

    # --- 2) DONCHIAN+ADX modu
    if _mode_syms_now := {x.upper() for x in (s.mode_symbols or [])}:
        for sym in sorted(_mode_syms_now):
            t = ticks.get(sym)
            tech = _TECHNICAL_CACHE.get(sym) or {}
            if not t or tech.get("donch_mid") is None:
                _row("DONCHIAN_ADX", sym, "Veri yok — mum/gösterge bekleniyor")
                continue
            price = (t.get("bid", 0.0) + t.get("ask", 0.0)) / 2.0 or tech.get("price", 0.0)
            mid = float(tech["donch_mid"])
            st_copy = {"day": day, "counts": dict(_DONCHIAN_STATE.get(sym, {}).get("counts", {}))}
            act = donchian_adx_entry(
                prev_close=_DONCHIAN_STATE.get(sym, {}).get("prev_close"),
                prev_mid=_DONCHIAN_STATE.get(sym, {}).get("prev_mid"),
                close=price, mid=mid,
                adx=float(tech.get("adx", 25.0)), adx_min=float(_AUTO_SETTINGS.donchian_adx_min),
                day=day, day_counts=st_copy["counts"], max_per_day=int(_AUTO_SETTINGS.donchian_max_per_day),
                hour_utc=hour, is_jpy=("JPY" in sym),
            )
            if act:
                _row("DONCHIAN_ADX", sym, f"{act} kırılım adayı (ADX {float(tech.get('adx', 0)):.0f})", act)
            else:
                side = "üstünde" if price > mid else "altında"
                _row("DONCHIAN_ADX", sym,
                     f"Fiyat orta hattın {side} ({price:.3f} / orta {mid:.3f}), ADX {float(tech.get('adx', 0)):.0f} — yeniden kırılım bekleniyor")

    # --- 3) EMA+ADX geri-çekilme (M5)
    if s.ema_adx_enabled:
        for sym in sorted({x.upper() for x in (s.ema_adx_symbols or [])}):
            t = ticks.get(sym)
            tech = _TECHNICAL_CACHE.get(sym) or {}
            if not t or not tech.get("ema21"):
                _row(EMA_ADX_PULLBACK_STRATEGY, sym, "Veri yok — mum/gösterge bekleniyor")
                continue
            price = (t.get("bid", 0.0) + t.get("ask", 0.0)) / 2.0 or tech.get("price", 0.0)
            counts = dict(_EMA_ADX_STATE.get(sym, {}).get("counts", {}))
            act = ema_adx_pullback_entry(
                ema8=float(tech.get("ema8", 0.0)), ema21=float(tech.get("ema21", 0.0)),
                ema50=float(tech.get("ema50", 0.0)),
                adx=float(tech.get("adx", 0.0)), adx_min=float(s.ema_adx_adx_min),
                close=price,
                open_=float(tech.get("open_last", 0.0)) or price,
                high=float(tech.get("high_last", 0.0)) or price,
                low=float(tech.get("low_last", 0.0)) or price,
                atr_price=float(tech.get("atr", 0.0)),
                touch_atr=float(s.ema_adx_touch_atr),
                day_counts=counts, max_per_day=int(s.ema_adx_max_per_day),
            )
            e8, e21, e50 = float(tech.get("ema8", 0)), float(tech.get("ema21", 0)), float(tech.get("ema50", 0))
            trend_txt = "boğa dizilimi" if e8 > e21 > e50 else ("ayı dizilimi" if e8 < e21 < e50 else "dizilim yok")
            if act:
                _row(EMA_ADX_PULLBACK_STRATEGY, sym, f"{act} geri-çekilme adayı ({trend_txt}, ADX {float(tech.get('adx', 0)):.0f})", act)
            else:
                _row(EMA_ADX_PULLBACK_STRATEGY, sym, f"{trend_txt}, ADX {float(tech.get('adx', 0)):.0f} (eşik {s.ema_adx_adx_min:.0f}) — EMA21 teması/onay barı bekleniyor")

    # --- 4) S3 (Supertrend+RSI pullback) 5m + 15m
    if s.s3_enabled:
        for tf, syms in (("5m", s.s3_symbols_5m), ("15m", s.s3_symbols_15m)):
            for sym in sorted({x.upper() for x in (syms or [])}):
                t = ticks.get(sym)
                tech = _S3_STATE.get(f"{sym}|{tf}") or _s3_tech_for(sym, tf)
                if not t or not tech:
                    _row(f"S3_{tf.upper()}", sym, f"Veri yok — {tf} mum serisi (≥215 bar) bekleniyor")
                    continue
                counts = dict(_S3_DAY_STATE.get(f"{sym}|{tf}", {}).get("counts", {}))
                act = s3_pullback_entry(
                    st_dir=int(tech.get("st_dir", 0)),
                    close=float(tech.get("close", 0.0)),
                    ema200=float(tech.get("ema200", 0.0)), use_ema200=True,
                    adx=float(tech.get("adx", 0.0)), adx_min=float(s.s3_adx_min),
                    rsi_now=tech.get("rsi_now"), rsi_prev=tech.get("rsi_prev"),
                    rsi_window=list(tech.get("rsi_window") or []),
                    rsi_lo=float(s.s3_rsi_lo),
                    atr_price=float(tech.get("atr", 0.0)),
                    pip_size=next((i["pip_size"] for i in FOREX_SYMBOLS if i["symbol"] == sym), 0.0001),
                    day_counts=counts, max_per_day=int(s.s3_max_per_day),
                )
                st_txt = "▲" if int(tech.get("st_dir", 0)) > 0 else ("▼" if int(tech.get("st_dir", 0)) < 0 else "—")
                if act:
                    _row(f"S3_{tf.upper()}", sym, f"{act} pullback adayı (ST {st_txt}, RSI {float(tech.get('rsi_now', 0)):.0f})", act)
                else:
                    _row(f"S3_{tf.upper()}", sym,
                         f"ST {st_txt}, RSI {float(tech.get('rsi_now', 0) or 0):.0f}, ADX {float(tech.get('adx', 0)):.0f} — pullback dönüşü bekleniyor")

    # --- 5) London Breakout
    if s.lb_enabled:
        for sym in sorted({x.upper() for x in (s.lb_symbols or [])}):
            t = ticks.get(sym)
            if not t:
                _row(LONDON_BREAKOUT_STRATEGY, sym, "Veri yok")
                continue
            st_copy = dict(_LB_STATE.get(sym, {}))
            if st_copy.get("day") != day:
                st_copy = {"day": day, "box_hi": 0.0, "box_lo": 0.0, "counts": {}}
            box_hi, box_lo = float(st_copy.get("box_hi") or 0.0), float(st_copy.get("box_lo") or 0.0)
            if box_hi <= 0.0:
                lb_bars = _s3_bars_for(sym, "5m", limit=220)
                if lb_bars and len(lb_bars) >= 10:
                    lb_box = [
                        b for b in lb_bars
                        if datetime.datetime.fromtimestamp(b["time"], datetime.timezone.utc).toordinal() == day
                        and datetime.datetime.fromtimestamp(b["time"], datetime.timezone.utc).hour < int(s.lb_box_end_utc)
                    ]
                    if len(lb_box) >= 6:
                        box_hi = max(float(b["high"]) for b in lb_box)
                        box_lo = min(float(b["low"]) for b in lb_box)
            counts = dict(st_copy.get("counts", {}))
            act = london_breakout_entry(
                close=float(t.get("ask", 0.0)), box_hi=box_hi, box_lo=box_lo,
                hour_utc=hour, box_end_utc=int(s.lb_box_end_utc), entry_end_utc=int(s.lb_entry_end_utc),
                day_counts=counts, max_per_day=int(s.lb_max_per_day),
            )
            pip = next((i["pip_size"] for i in FOREX_SYMBOLS if i["symbol"] == sym), 0.0001)
            box_p = ((box_hi - box_lo) / pip) if (box_hi > 0 and pip > 0) else 0.0
            if act:
                _row(LONDON_BREAKOUT_STRATEGY, sym,
                     f"{act} kırılım adayı — kutu {box_lo:.5g}–{box_hi:.5g} ({box_p:.1f}p)", act)
            elif hour < int(s.lb_box_end_utc):
                _row(LONDON_BREAKOUT_STRATEGY, sym, f"Asya kutusu oluşuyor (00:00–{int(s.lb_box_end_utc):02d}:00 UTC, kutu: {box_p:.1f}p)")
            elif hour < int(s.lb_entry_end_utc):
                if box_hi <= 0:
                    _row(LONDON_BREAKOUT_STRATEGY, sym, f"Tetik penceresi açık ama kutu henüz ölçülemedi (00:00–{int(s.lb_box_end_utc):02d}:00 UTC barları bekleniyor)")
                else:
                    _row(LONDON_BREAKOUT_STRATEGY, sym, f"Kutu {box_lo:.5g}–{box_hi:.5g} ({box_p:.1f}p) kırılımı taranıyor")
            else:
                _row(LONDON_BREAKOUT_STRATEGY, sym, f"Günün tetik penceresi kapandı ({int(s.lb_entry_end_utc):02d}:00 UTC)")

    # --- 6) London Sign (NY açılışı sign-momentum)
    # 2026-10-13: EKSİK KOL. LS canlıya 2026-10-12'de alındı (6. giriş kolu) ama
    # bu raporlayıcıya eklenmediği için radar sayfası onu hiç taramıyordu —
    # "uygulamadaki tüm tarama sistemleri" derken en yeni kol görünmüyordu.
    # Motorla aynı pencere/sign mantığı; state KOPYA üzerinde okunur.
    if s.ls_enabled:
        ls_min_now = hour * 60 + now.minute
        ls_sig_lo = int(s.ls_sign_start_utc) * 60 + int(s.ls_sign_start_min)
        ls_sig_hi = int(s.ls_sign_end_utc) * 60 + int(s.ls_sign_end_min)
        ls_ent_lo = int(s.ls_entry_start_utc) * 60 + int(s.ls_entry_start_min)
        ls_ent_hi = int(s.ls_entry_end_utc) * 60 + int(s.ls_entry_end_min)
        for sym in sorted({x.upper() for x in (s.ls_symbols or [])}):
            t = ticks.get(sym)
            if not t:
                _row(LONDON_SIGN_STRATEGY, sym, "Veri yok")
                continue
            st_copy = dict(_LS_STATE.get(sym, {}))
            if st_copy.get("day") != day:
                st_copy = {"day": day, "sign_open": 0.0, "sign_close": 0.0, "entered": False}
            sign_open = float(st_copy.get("sign_open") or 0.0)
            sign_close = float(st_copy.get("sign_close") or 0.0)
            act = sign_window_entry(
                sign_open=sign_open, sign_close=sign_close,
                minute_of_day=ls_min_now,
                ent_start_min=ls_ent_lo, ent_end_min=ls_ent_hi,
                day_entered=bool(st_copy.get("entered")),
            )
            pip = next((i["pip_size"] for i in FOREX_SYMBOLS if i["symbol"] == sym), 0.0001)
            atr = float((_TECHNICAL_CACHE.get(sym) or {}).get("atr", 0.0))
            sl_pips = (float(s.ls_sl_atr) * atr / pip) if (atr > 0 and pip > 0) else 0.0
            # Pencere sırası motorla birebir: `act` yalnız giriş penceresi içinde
            # dolu olabilir (sign_window_entry pencere dışında None döner), bu yüzden
            # giriş penceresi dalı act'i de kapsar. Her sembol için TEK satır yazılır.
            if ls_min_now < ls_sig_lo:
                _row(LONDON_SIGN_STRATEGY, sym,
                     f"Sign penceresi bekleniyor ({int(s.ls_sign_start_utc):02d}:{int(s.ls_sign_start_min):02d}–"
                     f"{int(s.ls_sign_end_utc):02d}:{int(s.ls_sign_end_min):02d} UTC)")
            elif ls_min_now < ls_ent_lo:
                _row(LONDON_SIGN_STRATEGY, sym,
                     f"Sign toplanıyor (şimdiye kadar {sign_close:.5g} vs {sign_open:.5g}) — "
                     f"giriş penceresi {int(s.ls_entry_start_utc):02d}:{int(s.ls_entry_start_min):02d} UTC'de açılıyor")
            elif ls_min_now < ls_ent_hi:
                # Motorun 5191-5192 satırları: ATR yoksa giriş yok (SL hesaplanamaz),
                # `entered` geri alınır ve aday ÜRETİLMEZ. Rapor da aday göstermemeli.
                if sl_pips <= 0:
                    _row(LONDON_SIGN_STRATEGY, sym,
                         "Giriş penceresi açık ama ATR yok — SL hesaplanamaz, motor pas geçer")
                elif st_copy.get("entered"):
                    _row(LONDON_SIGN_STRATEGY, sym, "Giriş penceresi açık — bugünkü giriş yapıldı (günde tek)")
                elif act:
                    _row(LONDON_SIGN_STRATEGY, sym,
                         f"{act} adayı — NY açılışı sign {'+' if act == 'BUY' else '−'} "
                         f"(kapanış {sign_close:.5g} vs açılış {sign_open:.5g}), "
                         f"SL {sl_pips:.1f}p, TP yok (chandelier trail)", act)
                elif sign_open <= 0 or sign_close <= 0:
                    _row(LONDON_SIGN_STRATEGY, sym, "Giriş penceresi açık ama sign ölçülemedi (mum serisi bekleniyor)")
                else:
                    _row(LONDON_SIGN_STRATEGY, sym,
                         f"Giriş penceresi açık — sign nötr (kapanış {sign_close:.5g} = açılış {sign_open:.5g}), yön yok")
            else:
                _row(LONDON_SIGN_STRATEGY, sym,
                     f"Günün penceresi kapandı (giriş bitişi {int(s.ls_entry_end_utc):02d}:{int(s.ls_entry_end_min):02d} UTC)")

    # --- 7) Keltner Squeeze (M15)
    # 2026-10-14: canlıya alınan 6. kol. LS ile aynı ders — kol motora yazılıp
    # raporlayıcıya eklenmezse radar sayfası onu hiç göstermez. Gösterge seti
    # motordan okunur, yoksa burada hesaplanır (state KOPYA üzerinde okunur).
    if s.squeeze_kc_enabled:
        for sym in sorted({x.upper() for x in (s.squeeze_kc_symbols or [])}):
            t = ticks.get(sym)
            tech = _SQUEEZE_KC_STATE.get(sym) or _squeeze_kc_tech_for(sym)
            pip = next((i["pip_size"] for i in FOREX_SYMBOLS if i["symbol"] == sym), 0.0001)
            if not t or not tech:
                _row(SQUEEZE_KC_STRATEGY, sym, "Veri yok — M15 mum serisi bekleniyor")
                continue
            st_copy = dict(_SQUEEZE_KC_DAY_STATE.get(sym, {}))
            if st_copy.get("day") != day:
                st_copy = {"day": day, "counts": {}}
            counts = dict(st_copy.get("counts", {}))
            act = squeeze_kc_entry(tech, float(pip or 0.0), counts)
            ser = tech.get("series") or {}
            mom_last = float((ser.get("mom") or [0.0])[-1])
            if act:
                _row(SQUEEZE_KC_STRATEGY, sym,
                     f"{act['action']} sıkışma kırılım adayı (momentum {act['mom']:+.5g}, "
                     f"SL {float(act.get('sl_pips') or 0):.1f}p, TP {float(s.squeeze_kc_tp_r):.1f}R)",
                     act["action"])
            else:
                _row(SQUEEZE_KC_STRATEGY, sym,
                     f"Sıkışma bırakışı bekleniyor (momentum {mom_last:+.5g})")

    return rows


async def _build_strategy_scan_payload() -> Dict[str, Any]:
    """Tüm strateji kollarının anlık durumunu tek turda toplar (salt-okunur).

    `scan-now` ucu bunu POST (manuel, log düşer) ve GET (radar sayfası periyodik
    yoklaması, log yazmaz) için ortak kullanır. Log ayrımı kritiktir: sayfa her
    birkaç saniyede yoklarsa karar akışı "kullanıcı tarama başlattı" satırlarıyla
    dolardı.
    """
    now_ts = time.time()
    await _refresh_live_rates_if_needed()
    ticks = await _generate_realistic_ticks()
    radar_res = await get_forex_radar()
    rows = _scan_now_strategy_rows(ticks, radar_res)
    candidates_count = sum(1 for r in rows if r.get("action"))
    sessions = _get_market_sessions()
    active_names = [x["name"] for x in sessions if x.get("active")]
    blocked = is_entry_hour_blocked(datetime.datetime.now(datetime.timezone.utc).hour,
                                    _AUTO_SETTINGS.blocked_hours_utc)
    return {
        "status": "ok",
        "scanned_at": datetime.datetime.fromtimestamp(now_ts, TZ_UTC3).strftime("%Y-%m-%d %H:%M:%S UTC+3"),
        "scanned_at_ts": now_ts,
        "total_rows": len(rows),
        "candidates_count": candidates_count,
        "sessions_active": active_names,
        "entry_hour_blocked": blocked,
        "motor_enabled": bool(_AUTO_STATE.get("enabled")),
        "rows": rows,
    }


@router.post("/auto-paper/scan-now")
async def trigger_forex_manual_scan():
    """Manuel strateji taraması: tüm stratejileri sırayla tek turda değerlendirir.

    Salt-okunur raporlayıcı — motor döngüsünü (`_forex_auto_paper_loop`) ve hiçbir
    sayaç/state'i değiştirmez; giriş kararları yine motorun kendi turunda
    verilir. Panelin "Şimdi Tara" butonu radar/S3/LB/LS/Donchian/EAP'nin o anki
    durumunu insan-okur satırlarla görür.
    """
    payload = await _build_strategy_scan_payload()
    _AUTO_STATE["last_scan_time"] = payload["scanned_at_ts"]
    _log_auto_decision(
        "MANUAL",
        (f"🖐️ Kullanıcı manuel tarama başlattı: {payload['total_rows']} strateji-kolu tarandı, "
         f"{payload['candidates_count']} canlı aday "
         f"(seanslar: {', '.join(payload['sessions_active']) if payload['sessions_active'] else 'kapalı'})."),
    )
    # Manuel tur önbelleği bayatlatır: sayfanın periyodik yoklaması bir sonraki
    # turda taze sonucu görmeli (aksi halde buton "hiçbir şey değişmedi" gibi durur).
    _STRATEGY_SCAN_CACHE["ts"] = 0.0
    _STRATEGY_SCAN_CACHE["payload"] = None
    return payload


@router.get("/auto-paper/strategy-scan")
async def get_forex_strategy_scan():
    """Radar sayfasının periyodik strateji taraması (GET, önbellekli, logsuz).

    2026-10-13: Radar sayfası eskiden yalnız kendi klasik skor taramasını
    (`/radar`) gösteriyordu; S3 / London Breakout / London Sign / Donchian / EAP
    kolları yalnız "Şimdi Tara" butonuna basılınca görünürdü. Kullanıcı isteği:
    uygulamadaki TÜM tarama sistemleri radar sayfasında taransın. Bu uç aynı
    salt-okunur raporu döner; TTL önbelleği ile sayfa 3 sn'de bir yoklasa bile
    motor döngüsünü yormaz ve karar akışına log basmaz.
    """
    now_ts = time.time()
    cached_ts = float(_STRATEGY_SCAN_CACHE["ts"] or 0.0)
    cached_payload = _STRATEGY_SCAN_CACHE["payload"]
    if cached_payload is not None and now_ts - cached_ts < _STRATEGY_SCAN_TTL:
        return cached_payload
    payload = await _build_strategy_scan_payload()
    _STRATEGY_SCAN_CACHE["ts"] = now_ts
    _STRATEGY_SCAN_CACHE["payload"] = payload
    return payload


# ============================================================================
# SEMBOL EV KALKANI YÖNETİMİ & MANUEL İPTAL/MUAFIYET UÇ NOKTALARI
# ============================================================================
class EVShieldOverrideRequest(BaseModel):
    symbol: Optional[str] = None
    action: Optional[str] = "bypass_today"  # "bypass_today", "bypass_24h", "reset_history", "restore"
    hours: Optional[float] = 24.0

    class Config:
        extra = "allow"


@router.get("/auto-paper/ev-shield")
@router.get("/ev-shield")
async def get_forex_ev_shield_status():
    """Tüm Forex sembollerinin canlı EV Kalkanı durumunu, bloke nedenlerini ve muafiyetlerini döner."""
    return get_all_symbol_ev_status(time.time())


@router.post("/auto-paper/ev-shield/override")
@router.post("/ev-shield/override")
async def override_forex_ev_shield(
    req: Optional[EVShieldOverrideRequest] = None,
    symbol: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    hours: Optional[float] = Query(24.0),
):
    """Belirli bir sembol için EV Kalkanını geçici olarak devre dışı bırakır, geçmişini sıfırlar veya eski haline getirir."""
    req_symbol = (req.symbol if req and req.symbol else symbol) or ""
    req_action = (req.action if req and req.action else action) or "bypass_today"
    req_hours = (req.hours if req and req.hours is not None else hours) or 24.0

    req_action = str(req_action or "bypass_today").lower()
    sym = str(req_symbol or "").upper().replace("/", "").replace("-", "").strip()
    if not sym:
        raise HTTPException(status_code=400, detail="Geçersiz sembol.")

    now_ts = time.time()
    disp = sym
    item_meta = next((i for i in FOREX_SYMBOLS if i.get("symbol") == sym), None)
    if item_meta and item_meta.get("display"):
        disp = item_meta["display"]
    elif len(sym) == 6:
        disp = f"{sym[:3]}/{sym[3:]}"

    if req_action in ("bypass_today", "today"):
        now_dt = datetime.datetime.fromtimestamp(now_ts, TZ_UTC3)
        end_of_day = now_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        override_until = end_of_day.timestamp()
        _SYMBOL_EV_OVERRIDE_UNTIL[sym] = override_until
        rem_hours = max(0.1, (override_until - now_ts) / 3600.0)
        msg = f"🛡️ [{disp}] EV Kalkanı bugün sonuna kadar ({end_of_day.strftime('%H:%M')} UTC+3, ~{rem_hours:.1f} saat) iptal edildi. Sembol işleme açıldı."
        _log_auto_decision("MANUAL", msg, symbol=sym)
        return {"success": True, "action": req_action, "symbol": sym, "override_until": override_until, "message": msg}

    elif req_action in ("bypass_24h", "override_hours"):
        h = max(1.0, float(req_hours or 24.0))
        override_until = now_ts + (h * 3600.0)
        _SYMBOL_EV_OVERRIDE_UNTIL[sym] = override_until
        msg = f"🛡️ [{disp}] EV Kalkanı {h:.0f} saat boyunca kullanıcı tarafından muaf tutuldu. Sembol işleme açıldı."
        _log_auto_decision("MANUAL", msg, symbol=sym)
        return {"success": True, "action": req_action, "symbol": sym, "override_until": override_until, "message": msg}

    elif req_action in ("reset_history", "reset"):
        _SYMBOL_EV_RESET_AT_TS[sym] = now_ts
        _SYMBOL_EV_OVERRIDE_UNTIL.pop(sym, None)
        msg = f"🔄 [{disp}] EV geçmiş işlem sicili sıfırlandı. Sembol yeni bir başlangıçla değerlendirilecek."
        _log_auto_decision("MANUAL", msg, symbol=sym)
        return {"success": True, "action": req_action, "symbol": sym, "reset_at": now_ts, "message": msg}

    elif req_action in ("restore", "cancel_override", "enable"):
        _SYMBOL_EV_OVERRIDE_UNTIL.pop(sym, None)
        msg = f"🛡️ [{disp}] EV Kalkanı muafiyeti kaldırıldı. Normal koruma kuralları tekrar devrede."
        _log_auto_decision("MANUAL", msg, symbol=sym)
        return {"success": True, "action": req_action, "symbol": sym, "message": msg}

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Bilinmeyen eylem: {req_action}. (Desteklenenler: bypass_today, bypass_24h, reset_history, restore)",
        )


@router.post("/auto-paper/ev-shield/reset-all")
@router.post("/ev-shield/reset-all")
async def reset_all_forex_ev_shields():
    """Tüm sembollerin EV kalkanı muafiyetlerini ve sicillerini sıfırlar / serbest bırakır."""
    now_ts = time.time()
    for s in _AUTO_SETTINGS.allowed_symbols:
        _SYMBOL_EV_RESET_AT_TS[s] = now_ts
        _SYMBOL_EV_OVERRIDE_UNTIL.pop(s, None)
    msg = "🔄 Tüm sembollerin EV kalkanı sicili sıfırlandı; tüm pariteler temiz sayfayla işleme açıldı."
    _log_auto_decision("MANUAL", msg)
    return {"success": True, "message": msg}


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
    _invalidate_status_cache()
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
    _invalidate_status_cache()
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
            for field in ("exit_time", "exit_time_iso", "closed_at_ts", "time", "exit_price", "exit_reason", "exit_reason_title"):
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
    """İşlem kaydının kapanış zamanı: `closed_at_ts` → `time` → `time_msc` → `exit_time_iso` → `exit_time` → `close_time`."""
    ts = _parse_deal_ts(deal.get("closed_at_ts"))
    if ts is not None:
        return ts
    ts = _parse_deal_ts(deal.get("time"))
    if ts is not None:
        return ts
    ts = _parse_deal_ts(deal.get("time_msc"))
    if ts is not None:
        return ts
    ts = _parse_deal_ts(deal.get("exit_time_iso") or deal.get("exit_time"))
    if ts is not None:
        return ts
    return _parse_deal_ts(deal.get("close_time"))


def _divide_or_zero(numerator: float, denominator: float) -> float:
    """Sıfıra bölmede 0.0 döner (KPI toplayıcılarının ortak kuralı)."""
    return round(numerator / denominator, 2) if denominator else 0.0


def _kpi_bucket_begin(sym: str, display: str) -> Dict[str, Any]:
    """Tek sembolün KPI kovasını sıfır değerlerle açar (bkz. `_finalize_kpi_buckets`)."""
    key = (sym or "").upper() or "?"
    return {
        "symbol": key,
        "display": display or key,
        "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
        "pnl_usd": 0.0, "pnl_pips": 0.0,
        "gross_profit_usd": 0.0, "gross_loss_usd": 0.0,
        "profit_factor": 0.0, "profit_factor_infinite": False,
        "avg_pnl_usd": 0.0,
        "best_trade_usd": 0.0, "worst_trade_usd": 0.0,
        "open_count": 0, "open_pnl_usd": 0.0,
        "last_exit_ts": None, "last_exit_time": "",
        "last_exit_reason": "",
    }


def _finalize_kpi_buckets(buckets: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Kova sözlüğünü türetilmiş oranlarla kapatıp sıralı listeye çevirir.

    Sıra: net USD azalan (en kârlı sembol üstte), eşitlikte sembol adı.
    """
    out: List[Dict[str, Any]] = []
    for b in buckets.values():
        b["win_rate"] = round(b["wins"] / b["trades"] * 100.0, 1) if b["trades"] else 0.0
        b["avg_pnl_usd"] = _divide_or_zero(b["pnl_usd"], b["trades"])
        if b["gross_loss_usd"] > 0:
            b["profit_factor"] = round(b["gross_profit_usd"] / b["gross_loss_usd"], 2)
        elif b["gross_profit_usd"] > 0:
            # Hiç zarar yokken PF matematiksel olarak sonsuzdur; JSON `Infinity`
            # taşıyamadığı için tek nöbetçi sabit kullanılır (bkz. `_PF_INFINITE`).
            b["profit_factor"] = _PF_INFINITE
            b["profit_factor_infinite"] = True
        out.append(b)
    out.sort(key=lambda x: (-x["pnl_usd"], x["symbol"]))
    return out


def _accumulate_kpi_deals(
    buckets: Dict[str, Dict[str, Any]],
    deals: List[Dict[str, Any]],
    min_ts: float,
) -> None:
    """Kapanan işlemleri kovalara işler; `min_ts`'ten eski olanlar atlanır.

    Sınıflama tüm uçlarla AYNI: `pnl >= 0` → WIN (bkz. status KPI bloğu ve
    `_deal_net_pnl_usd`). Açık pozisyonlar `trades`/`win_rate` paydasına
    GİRMEZ (henüz sonucu yok) — yalnız `open_*` alanlarında sayılır.
    """
    for d in deals or []:
        ts = _deal_ts(d) or 0.0
        if ts < min_ts:
            continue
        pnl = _deal_net_pnl_usd(d)
        key = str(d.get("symbol", "")).upper() or "?"
        b = buckets.get(key)
        if b is None:
            b = _kpi_bucket_begin(key, str(d.get("display", "")))
            buckets[key] = b
        elif not b["display"] and d.get("display"):
            b["display"] = str(d.get("display"))
        b["trades"] += 1
        if pnl >= 0:
            b["wins"] += 1
            b["gross_profit_usd"] = round(b["gross_profit_usd"] + pnl, 2)
        else:
            b["losses"] += 1
            b["gross_loss_usd"] = round(b["gross_loss_usd"] + abs(pnl), 2)
        b["pnl_usd"] = round(b["pnl_usd"] + pnl, 2)
        b["pnl_pips"] = round(b["pnl_pips"] + float(d.get("pnl_pips", 0.0) or 0.0), 1)
        b["best_trade_usd"] = round(max(b["best_trade_usd"], pnl), 2)
        b["worst_trade_usd"] = round(min(b["worst_trade_usd"], pnl), 2)
        if ts > (b["last_exit_ts"] or 0.0):
            b["last_exit_ts"] = ts
            b["last_exit_time"] = str(d.get("exit_time") or d.get("time") or "")
            b["last_exit_reason"] = str(
                d.get("exit_reason_title") or d.get("exit_reason") or ""
            )


def _accumulate_kpi_open(
    buckets: Dict[str, Dict[str, Any]],
    open_positions: List[Dict[str, Any]],
) -> None:
    """Açık pozisyonları kovaya `open_count`/`open_pnl_usd` olarak ekler.

    Kapanmamış bir pozisyonun sonucu henüz yoktur; kazanma oranına
    girmez (payda şişmesin). Yalnız anlık K/Z gösterilir.
    """
    for p in open_positions or []:
        sym = str(p.get("symbol", "")).upper() or "?"
        b = buckets.get(sym)
        if b is None:
            b = _kpi_bucket_begin(sym, str(p.get("display", "")))
            buckets[sym] = b
        b["open_count"] += 1
        b["open_pnl_usd"] = round(
            b["open_pnl_usd"] + float(p.get("pnl_usd", p.get("profit", 0.0)) or 0.0), 2
        )


def _aggregate_symbol_kpi(
    deals: List[Dict[str, Any]],
    open_positions: List[Dict[str, Any]],
    min_ts: float,
) -> List[Dict[str, Any]]:
    """Kapanan işlemleri SEMBOL BAZINDA gruplayıp KPI kartı verisi üretir.

    Neden backend'de: aynı defterden status `today_kpi`'yi hesaplıyor; sembol
    kırılımı da onu üreten yerden gelmezse iki sayı kaynağı ayrışır ve kartların
    toplamı üstteki KPI ile tutmaz. Tek kaynak burasıdır.

    `min_ts=0` → TÜM ZAMANLAR (portföy sayfasının "tüm zamanlar" şeridi);
    `min_ts=gün başı` → yalnız günün kapananları. İki çağrı AYNI defteri
    kullandığı için bugün ve tüm zamanlar sayıları birbirini tutar.
    """
    buckets: Dict[str, Dict[str, Any]] = {}
    _accumulate_kpi_deals(buckets, deals, min_ts)
    _accumulate_kpi_open(buckets, open_positions)
    return _finalize_kpi_buckets(buckets)


def _aggregate_daily_symbol_kpi(
    deals: List[Dict[str, Any]],
    open_positions: List[Dict[str, Any]],
    min_ts: float,
) -> List[Dict[str, Any]]:
    """Günün kapanan işlemlerini SEMBOL BAZINDA gruplayıp KPI kartı verisi üretir.

    `_aggregate_symbol_kpi`'nın ince sarmalayıcısı — adı çağrı yerinde
    "günlük" niyetini korur (status `per_symbol_today`) ve mevcut testler
    bu adı doğrudan çağırır.
    """
    return _aggregate_symbol_kpi(deals, open_positions, min_ts)


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
    strategy: Optional[str] = None,
    period: str = "all",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 500,
    date: Optional[str] = None,
):
    """Forex Otonom Scalper ayrıntılı işlem raporları, filtreleme ve performans analitiği.

    KPI kartları **sembol + dönem** kapsamına bağlıdır: panelde "EUR/USD" ve
    "Bugün" seçiliyken kazanma oranı tüm arşivin değil, o dilimin oranıdır.
    `outcome` / `reason` / `search` yalnız TABLOYU süzer; KPI'ya girmez —
    yoksa "Sadece Kaybedenler" seçildiğinde kazanma oranı tanım gereği %0
    görünür ve kart anlamsızlaşırdı. Bu ayrım yanıtta `kpi_scope` ile bildirilir.
    """
    if date:
        date_from = date.strip()
        date_to = date.strip()
        period = "custom"
    # MT5 Deals önceliklidir; yoksa auto_state geçmişi kullanılır
    all_closed = _merge_partial_close_rows(list(_MT5_STATE.get("closed_deals", []))) or list(_AUTO_STATE.get("closed_trades", []))

    # Her kapalı işleme strateji ve strateji etiketi alanlarını enjekte et
    for t in all_closed:
        if not t.get("strategy"):
            t["strategy"] = strategy_from_mt5_deal(t)
        if not t.get("strategy_label"):
            t["strategy_label"] = strategy_display_label(t.get("strategy"))

    # Temiz-sayfa kesimi (arşiv+reset sonrası): rapor yalnız reset sonrası kapananları gösterir
    archived_before_reset = 0
    if _LEDGER_RESET_AT_TS:
        kept_closed = [t for t in all_closed if (_deal_ts(t) or 0.0) >= _LEDGER_RESET_AT_TS]
        archived_before_reset = len(all_closed) - len(kept_closed)
        all_closed = kept_closed

    now_ts = time.time()
    start_ts, end_ts = _resolve_report_window(period, date_from, date_to, now_ts)
    period_active = start_ts is not None or end_ts is not None

    # --- KPI kapsamı: sembol + dönem + strateji (tablo filtreleri hariç) ---
    kpi_scope = all_closed
    if symbol and symbol != "ALL":
        kpi_scope = [t for t in kpi_scope if t.get("symbol") == symbol or t.get("display") == symbol]
    if period_active:
        kpi_scope = [t for t in kpi_scope if _deal_in_window(_deal_ts(t), start_ts, end_ts)]
    if strategy and strategy != "ALL":
        strat_q = strategy.strip()
        kpi_scope = [
            t for t in kpi_scope
            if t.get("strategy") == strat_q
            or t.get("strategy_label") == strat_q
            or strat_q.lower() in str(t.get("strategy", "")).lower()
            or strat_q.lower() in str(t.get("strategy_label", "")).lower()
        ]

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
            or s_low in str(t.get("strategy", "")).lower()
            or s_low in str(t.get("strategy_label", "")).lower()
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
    for p in open_positions:
        if not p.get("strategy"):
            p["strategy"] = strategy_from_mt5_deal(p)
        if not p.get("strategy_label"):
            p["strategy_label"] = strategy_display_label(p.get("strategy"))

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
            "strategy": strategy or "ALL",
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
        "available_strategies": [
            {"code": "ALL", "label": "Tüm Stratejiler"},
            {"code": "EMA_ADX_PULLBACK_M5", "label": "EMA+ADX Pullback (M5)"},
            {"code": "S3_SUPERTREND_RSI", "label": "S3 SuperTrend+RSI"},
            {"code": "DONCHIAN_ADX", "label": "Donchian ADX Kırılımı"},
            {"code": "LONDON_BREAKOUT", "label": "London Breakout (M5)"},
            {"code": "LONDON_SIGN", "label": "NY Sign Momentum"},
            {"code": "SQUEEZE_KC_M15", "label": "Keltner Squeeze (M15)"},
            {"code": "M1_M5_RADAR_SCALPER", "label": "M1/M5 Çoklu Radar"},
            {"code": "MANUAL", "label": "Manuel Giriş"},
            {"code": "IC_MARKETS_MT5", "label": "IC Markets MT5"},
        ],
        "trades": filtered[:limit],
        "total_filtered": len(filtered),
        "open_positions": open_positions,
    }


@router.get("/auto-paper/export-csv")
async def export_forex_trades_csv(
    symbol: Optional[str] = None,
    outcome: Optional[str] = None,
    strategy: Optional[str] = None,
):
    """Forex scalper işlem geçmişini Excel uyumlu UTF-8 CSV olarak dışa aktarır."""
    # #2: kısmi kapanış satırları pozisyon bazında birleştirilir (rapordaki ile aynı).
    trades = _merge_partial_close_rows(list(_MT5_STATE.get("closed_deals", []))) or list(_AUTO_STATE.get("closed_trades", []))
    for tr in trades:
        if not tr.get("strategy"):
            tr["strategy"] = strategy_from_mt5_deal(tr)
        if not tr.get("strategy_label"):
            tr["strategy_label"] = strategy_display_label(tr.get("strategy"))
    # Temiz-sayfa kesimi: resetten önce kapananlar CSV'ye de girmez (raporla aynı payda)
    if _LEDGER_RESET_AT_TS:
        trades = [t for t in trades if (_deal_ts(t) or 0.0) >= _LEDGER_RESET_AT_TS]
    if symbol and symbol != "ALL":
        trades = [t for t in trades if t.get("symbol") == symbol or t.get("display") == symbol]
    if outcome and outcome != "ALL":
        trades = [t for t in trades if str(t.get("outcome", "")).upper() == str(outcome).upper()]
    if strategy and strategy != "ALL":
        strat_q = strategy.strip()
        trades = [
            t for t in trades
            if t.get("strategy") == strat_q
            or t.get("strategy_label") == strat_q
            or strat_q.lower() in str(t.get("strategy", "")).lower()
        ]

    output = io.StringIO()
    # UTF-8 BOM yaz (Excel'in Türkçe karakterleri düzgün açması için)
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')

    # Başlık Satırı
    writer.writerow([
        "Bilet No",
        "Parite",
        "Sembol",
        "Strateji",
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
        strat_display = tr.get("strategy_label") or strategy_display_label(strategy_from_mt5_deal(tr))
        writer.writerow([
            t_id,
            tr.get("display", tr.get("symbol", "")),
            tr.get("symbol", ""),
            strat_display,
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
    # 2026-10-10 denetim P0-1: köprü emir sonuçlarını (başarı/hata) geri bildirir.
    # [{cmd_id, action, symbol, success, retcode, error}] — motor reddedilen emri artık görür.
    command_results: List[Dict[str, Any]] = Field(default_factory=list)
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
async def sync_mt5_bridge(req: MT5SyncRequest, request: Request = None):
    """Windows MT5 köprüsünden gelen canlı veriyi alır ve bekleyen emirleri iletir.

    Kimlik paylaşılan köprü sırasıdır (oturum değil). Sır yoksa veya başlık
    uyuşmazsa durum değişmez: connected yazılmaz, emir kuyruğu boşalmaz.
    """
    global _LAST_TECH_FETCH_TIME
    now_ts = time.time()
    if not _mt5_sync_authorized(request):
        raise HTTPException(status_code=401, detail="Köprü doğrulanamadı")
    _MT5_STATE["connected"] = True
    _MT5_STATE["last_ping"] = now_ts

    if req.account:
        _MT5_STATE["account"].update(req.account)
    _MT5_STATE["open_positions"] = req.positions

    # Broker mumlarını önbelleğe al (panel grafiği + sinyal motoru bu veriyi kullanır →
    # geçmiş + canlı AYNI broker kotasyonu, baz farkı yok). Anahtar "SYMBOL|interval" (interval küçük harf).
    if req.candles:
        now_c = time.time()
        for ckey, cbar_list in req.candles.items():
            raw_key = str(ckey or "").strip()
            # Beklenen biçim "XAUUSD|5m"; köprü sembolü zaten normalize eder.
            if "|" not in raw_key:
                continue
            parts = raw_key.split("|", 1)
            sym_part = parts[0].upper().replace("/", "").replace("_", "").replace("-", "").replace(" ", "").strip()
            tf_part = parts[1].strip().lower()
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
                _MT5_CANDLES_CACHE[f"{canonical_symbol(sym_part)}|{tf_part}"] = (now_c, clean)
        _LAST_TECH_FETCH_TIME = 0.0

    # MT5 canlı tick fiyatlarını entegre et
    if req.ticks:
        for sym_code, tick_dict in req.ticks.items():
            sym_up = str(sym_code).upper()
            bid_v = tick_dict.get("bid")
            ask_v = tick_dict.get("ask")
            _note_mt5_tick(sym_up, bid_v, ask_v or tick_dict.get("last"), now_ts)
            if bid_v and ask_v and float(ask_v) > float(bid_v) > 0:
                app_sym = canonical_symbol(sym_up)
                pip_size = get_symbol_trading_specs(app_sym)["pip_size"]
                if pip_size > 0:
                    spread_pips = (float(ask_v) - float(bid_v)) / pip_size
                    # 2026-10-10 denetim P2-3: sabit 100.0 tavanı BTC'de (pip_size=1.0)
                    # gerçek >$100 spread'i reddedip sentetik 12.0'a düşürüyordu. Kripto
                    # için tavanı genişlet; yine de bariz veri hatasını (>10.000) ele.
                    _spread_ceiling = 10000.0 if ("BTC" in app_sym.upper() or "ETH" in app_sym.upper()) else 100.0
                    if 0.0 < spread_pips <= _spread_ceiling:
                        _LIVE_SPREAD_PIPS[app_sym] = round(spread_pips, 2)

    if req.deals:
        # Her deal'e strateji kimliği yazılır (köprü `strategy_tag`'inden çözülür):
        # status/rapor/CSV hepsi aynı kaynaktan okusun diye tek noktada zenginleştirilir.
        _enriched_deals: List[Dict[str, Any]] = []
        for _d in req.deals:
            try:
                _dd = dict(_d)
            except (TypeError, ValueError):
                continue
            _dd["strategy"] = strategy_from_mt5_deal(_dd)
            _enriched_deals.append(_dd)
        _MT5_STATE["closed_deals"] = _enriched_deals
        is_first_sync = len(_LAST_CLOSED_DEAL_IDS) == 0
        newly_closed_deals: List[Dict[str, Any]] = []
        for d in _enriched_deals:
            deal_id = d.get("ticket") or d.get("id")
            if deal_id and deal_id not in _LAST_CLOSED_DEAL_IDS:
                _LAST_CLOSED_DEAL_IDS.add(deal_id)
                newly_closed_deals.append(d)
                d_sym = str(d.get("symbol", "")).upper()
                deal_time = float(d.get("time", 0)) if isinstance(d.get("time", 0), (int, float)) else 0.0
                if "XAU" in d_sym or "GOLD" in d_sym:
                    # İlk senkronizasyonda eski geçmiş deals için false cooldown başlatma; sadece son 180s içinde kapananlar için başlat
                    if not is_first_sync or (deal_time > 0 and (now_ts - deal_time < _AUTO_SETTINGS.gold_cooldown_sec)):
                        global _LAST_GOLD_EXIT_TIME
                        _LAST_GOLD_EXIT_TIME = now_ts
                if "BTC" in d_sym:
                    if not is_first_sync or (deal_time > 0 and (now_ts - deal_time < 60.0)):
                        global _LAST_BTC_EXIT_TIME
                        _LAST_BTC_EXIT_TIME = now_ts

        # Seri-SL sigortası (CANLI MT5 yolu): kapanan her işlem sayaca girer.
        #   - İlk senkronizasyonda geçmiş penceresi (300 deal) topluca beslenirse
        #     sahte seri/soğuma doğar → o tur atlanır.
        #   - Yalnız son 15 dk'da kapananlar sayılır (gecikmeli görünen eski deal
        #     seriyi bozmasın).
        #   - Kronolojik sırayla beslenir: kısmi bacaklar aynı senkronda toplu
        #     gelir; ters sıra SL'i kazanca çevirip seriyi yanlış sıfırlardı.
        if not is_first_sync:
            for d in sorted(newly_closed_deals,
                            key=lambda x: (_deal_ts(x) or float(x.get("time", 0) or 0.0) or 0.0)):
                feed_loss_streak_from_deal(
                    d.get("symbol"),
                    d.get("exit_reason") or d.get("exit_reason_title"),
                    _deal_net_pnl_usd(d),
                    d.get("direction"),
                )

    # 2026-10-10 denetim P0-1: köprü emir sonuçlarını işle. Eskiden başarısız emir
    # yalnız köprü konsoluna yazılıyor, motor onu "açıldı" sanıyordu. Şimdi:
    #   - başarısız OPEN_ORDER → 60 sn giriş soğumasını GERİ AÇ (yeniden denemeye izin ver)
    #   - başarılı OPEN_ORDER → bekleyen komutları kesin temizle
    #   - başarısız CLOSE_ORDER → sembolü aşırı soğutmamak için exit saatini geri al
    # (Retcode/success alanları olmayan eski köprü sürümleriyle geriye dönük uyumlu.)
    if req.command_results:
        for _cr in req.command_results:
            try:
                _cr_action = str(_cr.get("action", "")).upper()
                _cr_sym = str(_cr.get("symbol", "")).upper()
                _cr_ok = bool(_cr.get("success", False))
                _cr_err = _cr.get("error") or _cr.get("retcode")
                _cr_ticket = _cr.get("ticket")
                if not _cr_ok:
                    if _cr_action == "OPEN_ORDER" and _cr_sym:
                        _LAST_SYMBOL_ENTRY_TIME.pop(_cr_sym, None)
                    _log_auto_decision(
                        "SYSTEM",
                        f"❌ MT5 emri BAŞARISIZ: {_cr_action} {_cr_sym} — {_cr_err} "
                        f"(soğuma geri açıldı, yeniden denenecek).",
                        symbol=_cr_sym or None,
                    )
                else:
                    if _cr_action == "CLOSE_ORDER" and _cr_ticket is not None:
                        _cr_ticket_s = str(_cr_ticket)
                        for _pf_sym, _pf in list(_PENDING_FLIP.items()):
                            tickets = {str(t) for t in (_pf.get("tickets") or [])}
                            if _cr_ticket_s in tickets:
                                done = {str(t) for t in (_pf.get("done") or [])}
                                done.add(_cr_ticket_s)
                                _pf["done"] = list(done)
                                if tickets and done >= tickets:
                                    _pf["close_ok"] = True
                    _log_auto_decision(
                        "SYSTEM",
                        f"✅ MT5 emri uygulandı: {_cr_action} {_cr_sym}"
                        + (f" (retcode {_cr.get('retcode')})" if _cr.get("retcode") is not None else ""),
                        symbol=_cr_sym or None,
                    )
            except Exception as _cr_exc:  # pragma: no cover - savunmacı
                _log_auto_decision("SYSTEM", f"⚠️ Emir sonucu işlenemedi: {_cr_exc}")

    server_name = (_MT5_STATE.get("account") or {}).get("server")
    if _non_demo_live_blocked(server_name):
        _log_auto_decision(
            "SYSTEM",
            "Development modunda demo olmayan hesaba bekleyen emir iletilmedi.",
        )
        commands = []
    else:
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
            "max_positions_per_symbol": _AUTO_SETTINGS.max_positions_per_symbol,
            "max_forex_lot": _AUTO_SETTINGS.max_forex_lot,
            "max_gold_lot": _AUTO_SETTINGS.max_gold_lot,
            "max_index_lot": _AUTO_SETTINGS.max_index_lot,
            "flip_ignore_min_score": _AUTO_SETTINGS.flip_ignore_min_score,
            "gold_cooldown_sec": _AUTO_SETTINGS.gold_cooldown_sec,
            "atr_exit_enabled": _AUTO_SETTINGS.atr_exit_enabled,
            "partial_tp_enabled": _AUTO_SETTINGS.partial_tp_enabled,
            "gold_be_lock_ratio": _AUTO_SETTINGS.gold_be_lock_ratio,
            "dxy_filter_enabled": _AUTO_SETTINGS.dxy_filter_enabled,
            "correlation_guard": _AUTO_SETTINGS.correlation_guard,
            # Trailing aktifleşince köprünün de sabit TP emrini çekmesi için (opt-in).
            # Kapalıyken köprü hiçbir ek MODIFY_SLTP üretmez → canlı davranış aynı kalır.
            "tp_cancel_on_trail": _AUTO_SETTINGS.tp_cancel_on_trail,
            # Chandelier trailing çarpanı — köprü artık tepeye demirlenmiş trailing
            # uygulayabilsin (MFE − kat × giriş ATR'si). 0 = kapalı → köprü eski
            # sabit-pip davranışında kalır (geri alma tek değer).
            "chandelier_atr_mult": _AUTO_SETTINGS.chandelier_atr_mult,
            # 2026-10-14 BE/trail denetim kolları — varsayılanları mevcut davranışı korur.
            # Köprü CURRENT_SETTINGS.update(settings) ile alır; anahtar yoksa `False`/`0.0`
            # varsayılanına düşer, yani eski köprü sürümleri de bozulmaz.
            "be_lock_from_mfe": bool(_AUTO_SETTINGS.be_lock_from_mfe),
            "be_trigger_atr_mult": float(_AUTO_SETTINGS.be_trigger_atr_mult),
            "be_trigger_r_mult": float(_AUTO_SETTINGS.be_trigger_r_mult),
            "chandelier_gate_independent": bool(_AUTO_SETTINGS.chandelier_gate_independent),
            "be_trigger_atr_mult_gold": float(_AUTO_SETTINGS.be_trigger_atr_mult_gold),
            "be_trigger_atr_mult_crypto": float(_AUTO_SETTINGS.be_trigger_atr_mult_crypto),
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
        lot_cap = min(HARD_MAX_INDEX_LOT, _AUTO_SETTINGS.max_index_lot)
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
    _invalidate_status_cache()
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
    _invalidate_status_cache()
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
    _invalidate_status_cache()
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
    """Investing.com 2 ve 3 Yıldızlı Makro Ekonomik Takvim Olaylarını 'Ne Olursa Ne Olur' senaryosuyla döner.
    Her olaya bias_direction (BUY/SELL/NEUTRAL) ve bias_explanation ekler."""
    try:
        from app.forex_news import get_forex_news, FALLBACK_EVENTS
        from app.forex_news_bias import released_biases
        import time as _time
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

        # Yön (bias) zenginleştirmesi — açıklanmış olaylar için
        now_ts = _time.time()
        bias_map = released_biases(items, now_ts, window_sec=1800.0)
        for it in items:
            sym = it.get("symbol") or (it.get("affected_symbols", [""])[0] if it.get("affected_symbols") else "")
            if sym and sym in bias_map:
                b = bias_map[sym]
                b_dir = int(b.get("dir", 0) or 0)
                dir_str = "BUY" if b_dir > 0 else ("SELL" if b_dir < 0 else "NEUTRAL")
                rem_min = float(b.get("remaining_min", 30.0) or 30.0)
                it["bias_direction"] = dir_str
                it["bias_confidence"] = min(100, int(b.get("hits", 1) * 50)) if b_dir != 0 else 0
                it["bias_explanation"] = (
                    f"{b.get('hits', 1)} veri açıklaması doğrultusunda {dir_str} yönü destekleniyor ({rem_min:.0f} dk)."
                    if b_dir != 0 else "Henüz açıklanmamış veya yön belirsiz"
                )
            else:
                it["bias_direction"] = "NEUTRAL"
                it["bias_confidence"] = 0
                it["bias_explanation"] = "Henüz açıklanmamış veya yön belirsiz"

        upcoming_5m = [x for x in items if x.get("is_within_5m")]

        last_sync_ts = 0.0
        try:
            from app import database
            if database:
                last_sync_ts = await database.get_last_economic_calendar_sync()
        except Exception:
            pass

        return {
            "status": "ok",
            "count": len(items),
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_sync_ts": last_sync_ts,
            "source": "Investing.com & Küresel Makro Akış (2 & 3 Yıldız - Veritabanı Önbellekli)",
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

