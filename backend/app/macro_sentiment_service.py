"""Macro market sentiment and BTC compass service.

Combines Alternative.me Crypto Fear and Greed Index with real-time BTC 5m/15m
directional momentum to calculate the global market regime and provide a systemic
safety gate (BTC Compass Gate) for Master Surge and LLM chat/assistant.
"""

import asyncio
import json
import logging
import time

from app.config import config
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

FNG_URL = "https://api.alternative.me/fng/"
FNG_CACHE_TTL = 900.0  # 15 dakika (Günde 1 kez güncellenir)
BTC_CACHE_TTL = 30.0   # 30 saniye BTC pusulası tazeleme
BTC_1H_TTL = 300.0     # 5 dakika 1H EMA200 tazeleme

_FNG_CACHE: tuple[float, dict] | None = None
_BTC_COMPASS_CACHE: tuple[float, dict] | None = None
_BTC_1H_EMA_CACHE: tuple[float, dict] | None = None


def _fetch_fng_sync(timeout: float = 3.5) -> dict | None:
    try:
        req = Request(FNG_URL, headers={"User-Agent": "ScalperAgent/4.0"})
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("data") or []
            if items and isinstance(items[0], dict):
                return {
                    "score": int(items[0].get("value") or 50),
                    "classification": str(items[0].get("value_classification") or "Neutral"),
                    "updated_at": time.time(),
                }
    except Exception as exc:
        logger.debug("Fear & Greed çekimi başarısız: %s", exc)
    return None


async def get_fear_and_greed() -> dict:
    """Korku ve Açgözlülük İndeksini döner (15 dk TTL önbellekli)."""
    global _FNG_CACHE
    now = time.time()
    if _FNG_CACHE and (now - _FNG_CACHE[0]) < FNG_CACHE_TTL:
        return _FNG_CACHE[1]

    data = await asyncio.to_thread(_fetch_fng_sync)
    if not data:
        data = {"score": 50, "classification": "Neutral", "updated_at": now}

    _FNG_CACHE = (now, data)
    return data


async def get_btc_compass() -> dict:
    """Bitcoin'in anlık kısa vadeli yönünü, piyasa stres seviyesini ve 1H EMA200 rejimini ölçer."""
    global _BTC_COMPASS_CACHE, _BTC_1H_EMA_CACHE
    now = time.time()
    if _BTC_COMPASS_CACHE and (now - _BTC_COMPASS_CACHE[0]) < BTC_CACHE_TTL:
        return _BTC_COMPASS_CACHE[1]

    from app.binance_tr_public import klines as fetch_klines
    btc_5m_ret = 0.0
    btc_15m_ret = 0.0
    btc_trend_state = "SIDEWAYS"
    is_panic = False
    btc_fetch_error = False

    # BTC referans sembolü oyaladığımız borsanın quote'süne göre (TR→BTCTRY,
    # Global→BTCUSDT).
    btc_symbol = f"BTC{config.QUOTE_ASSET}"

    try:
        # BTC referans 5m klines
        k5 = await fetch_klines(btc_symbol, "5m", 6)
        if k5 and len(k5) >= 4:
            c_now = float(k5[-1][4])
            c_prev1 = float(k5[-2][4])
            c_prev3 = float(k5[-4][4])
            btc_5m_ret = round(((c_now - c_prev1) / c_prev1) * 100.0, 2)
            btc_15m_ret = round(((c_now - c_prev3) / c_prev3) * 100.0, 2)

            if btc_15m_ret <= -1.0 or (btc_5m_ret <= -0.7 and btc_15m_ret <= -0.8):
                btc_trend_state = "PANIC_DUMP"
                is_panic = True
            elif btc_15m_ret < -0.4:
                btc_trend_state = "BEARISH_PRESSURE"
            elif btc_15m_ret > 0.6:
                btc_trend_state = "STRONG_BULLISH"
            elif btc_15m_ret > 0.2:
                btc_trend_state = "MILD_BULLISH"
            else:
                btc_trend_state = "SIDEWAYS"
        else:
            btc_fetch_error = True
    except Exception as exc:
        logger.debug("BTC pusula hesabı hatası: %s", exc)
        btc_fetch_error = True

    # 1H BTC EMA200 Makro Rejim Kalkanı (5 dk TTL)
    btc_1h_data: dict = {"btc_1h_close": None, "btc_1h_ema200": None, "is_btc_above_ema200": True}
    if _BTC_1H_EMA_CACHE and (now - _BTC_1H_EMA_CACHE[0]) < BTC_1H_TTL:
        btc_1h_data = _BTC_1H_EMA_CACHE[1]
    else:
        try:
            k1h = await fetch_klines(btc_symbol, "1h", 210)
            if k1h and len(k1h) >= 200:
                closes_1h = [float(b[4]) for b in k1h]
                from app.technical_analysis import _ema
                ema200_val = _ema(closes_1h, 200)
                c_last = closes_1h[-1]
                btc_1h_data = {
                    "btc_1h_close": round(c_last, 2),
                    "btc_1h_ema200": round(ema200_val, 2) if ema200_val else None,
                    "is_btc_above_ema200": bool(c_last > ema200_val) if ema200_val else True,
                }
                _BTC_1H_EMA_CACHE = (now, btc_1h_data)
        except Exception as exc:
            logger.debug("BTC 1H EMA200 hesabı hatası: %s", exc)

    result = {
        "btc_symbol": btc_symbol,
        "btc_5m_change_pct": btc_5m_ret,
        "btc_15m_change_pct": btc_15m_ret,
        "btc_trend_state": btc_trend_state,
        "is_btc_panic": is_panic,
        "is_panic_dump": is_panic,
        "btc_1h_close": btc_1h_data.get("btc_1h_close"),
        "btc_1h_ema200": btc_1h_data.get("btc_1h_ema200"),
        "is_btc_above_ema200": btc_1h_data.get("is_btc_above_ema200", True),
        "is_macro_bull_regime": btc_1h_data.get("is_btc_above_ema200", True) and not is_panic,
        "fetch_error": btc_fetch_error,
        "updated_at": now,
    }
    _BTC_COMPASS_CACHE = (now, result)
    return result


def get_cached_btc_compass(max_age_sec: float | None = None) -> dict | None:
    """Bellekteki son BTC pusulasını senkron döner (TTL'li).

    `unified_signals.enrich_candidates` cache sözlüğüne doğrudan bakmak yerine
    BUNU çağırır (bulgu #67 ile aynı sınıf: TTL'siz okuma).
    """
    if not _BTC_COMPASS_CACHE:
        return None
    age = time.time() - _BTC_COMPASS_CACHE[0]
    ttl = float(max_age_sec if max_age_sec is not None else BTC_CACHE_TTL)
    if ttl > 0 and age >= ttl:
        return None
    return _BTC_COMPASS_CACHE[1]


async def get_macro_sentiment() -> dict:
    """Tüm makro duygu ve BTC koruma durumunu tek özet nesnede birleştirir."""
    fng = await get_fear_and_greed()
    btc = await get_btc_compass()

    score = fng.get("score", 50)
    classification = fng.get("classification", "Neutral")
    is_panic = btc.get("is_btc_panic", False)
    is_above_ema200 = btc.get("is_btc_above_ema200", True)
    btc_ema200_val = btc.get("btc_1h_ema200")

    # Piyasa Stres Seviyesi & Makro Rejim Kalkanı
    if is_panic or score <= 20:
        stress_level = "HIGH_RISK"
        allow_new_longs = False  # BTC panik düşüşündeyse alım kapalı
        desc = "Piyasa yüksek stres veya panik satış altında. Bitcoin ani düşüşte; yeni altcoin alımları durduruldu."
    elif not is_above_ema200:
        stress_level = "BEAR_REGIME"
        allow_new_longs = False  # BTC 1H EMA200 altındayken agresif breakout longları engellenir
        ema_str = f"({btc_ema200_val:.1f})" if btc_ema200_val else ""
        desc = f"Bitcoin 1H EMA200 {ema_str} altında (Ayı Rejimi). Rejim kalkanı aktif; sermaye koruması devrede."
    elif score >= 75:
        stress_level = "OVERHEATED"
        allow_new_longs = True
        desc = "Piyasa aşırı açgözlülük bölgesinde. Coşku yüksek ancak direnç seviyelerinde kâr realizasyonu olasılığı var."
    else:
        stress_level = "HEALTHY"
        allow_new_longs = True
        desc = f"Genel piyasa dengeli ({classification} - Skor {score}). Bitcoin 1H EMA200 üzerinde ve destekleyici."

    return {
        "fear_and_greed_score": score,
        "fear_and_greed_class": classification,
        "btc_trend_state": btc.get("btc_trend_state", "SIDEWAYS"),
        "btc_15m_change_pct": btc.get("btc_15m_change_pct", 0.0),
        "is_btc_panic": is_panic,
        "is_btc_above_ema200": is_above_ema200,
        "btc_1h_ema200": btc_ema200_val,
        "is_macro_bull_regime": is_above_ema200 and not is_panic,
        "regime_shield_active": not is_above_ema200 or is_panic,
        "market_stress_level": stress_level,
        "allow_new_longs": allow_new_longs,
        "summary": desc,
        "updated_at": time.time(),
    }


def get_cached_macro_sentiment() -> dict | None:
    """Bellekteki son makro duygu ve BTC durumunu senkron döner (varsa)."""
    now = time.time()
    if not _FNG_CACHE and not _BTC_COMPASS_CACHE:
        return None

    fng_val = _FNG_CACHE[1] if (_FNG_CACHE and (now - _FNG_CACHE[0]) < FNG_CACHE_TTL) else {"score": 50, "classification": "Neutral"}
    btc_val = _BTC_COMPASS_CACHE[1] if (_BTC_COMPASS_CACHE and (now - _BTC_COMPASS_CACHE[0]) < BTC_CACHE_TTL) else {
        "btc_trend_state": "SIDEWAYS", "btc_15m_change_pct": 0.0, "is_btc_panic": False, "is_panic_dump": False, "is_btc_above_ema200": True
    }

    score = fng_val.get("score", 50)
    classification = fng_val.get("classification", "Neutral")
    is_panic = bool(btc_val.get("is_btc_panic", btc_val.get("is_panic_dump", False)))
    is_above_ema200 = bool(btc_val.get("is_btc_above_ema200", True))
    btc_ema200_val = btc_val.get("btc_1h_ema200")

    if is_panic or score <= 20:
        stress_level = "HIGH_RISK"
        allow_new_longs = False
    elif not is_above_ema200:
        stress_level = "BEAR_REGIME"
        allow_new_longs = False
    elif score >= 75:
        stress_level = "OVERHEATED"
        allow_new_longs = True
    else:
        stress_level = "HEALTHY"
        allow_new_longs = True

    return {
        "fear_and_greed_score": score,
        "fear_and_greed_class": classification,
        "btc_trend_state": btc_val.get("btc_trend_state", "SIDEWAYS"),
        "btc_15m_change_pct": btc_val.get("btc_15m_change_pct", 0.0),
        "is_btc_panic": is_panic,
        "is_btc_above_ema200": is_above_ema200,
        "btc_1h_ema200": btc_ema200_val,
        "is_macro_bull_regime": is_above_ema200 and not is_panic,
        "regime_shield_active": not is_above_ema200 or is_panic,
        "market_stress_level": stress_level,
        "allow_new_longs": allow_new_longs,
        "summary": "Makro önbellek özeti",
        "updated_at": now,
    }
