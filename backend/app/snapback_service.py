"""S2/S6 Snapback Dip Avcısı Servisi (Oversold Dip-Hunter).

KÖKEN:
    2026-10-06 tarihli mRSI kripto spot backtest ve 10 coin × 9000 saatlik
    replay kanıtı:
    - OOS (Boğa): 10/10 coin pozitif, %68.5 WR, +%8.6 net getiri.
    - S6 BTC Kalkanı (BTC > EMA200 1H) ile birleştiğinde ayı hasarını nötrler.

MANTIK:
    1) Zaman Dilimi: 1H
    2) Giriş Kuralı: RSI(7) < 20 VE RSI(14) < 30 (Aşırı Satım Panik Dibi)
    3) Kalkan Kuralı: BTC > EMA200 (1H)
    4) Çıkış Kuralı: RSI(7) > 50 (Hızlı V-dönüşü kâr alımı)
    5) Stop-Loss: Giriş - 1.5 × ATR(14)
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.config import config
from app.macro_sentiment_service import get_btc_compass
from app.technical_analysis import _atr, _ema, _rsi_series

logger = logging.getLogger("scalper.snapback")

_SNAPBACK_CACHE: tuple[float, List[dict]] | None = None
CACHE_TTL = 60.0  # 1 dakika önbellek


def compute_wilder_rsi_1h(closes: List[float], period: int) -> Optional[float]:
    """1H Wilder RSI son değerini hesaplar."""
    if len(closes) < period + 1:
        return None
    series = _rsi_series(closes, period=period)
    return series[-1] if series else None


async def scan_snapback_candidates(symbols: Optional[List[str]] = None) -> List[dict]:
    """1H barlar üzerinde S2/S6 Snapback aşırı satım dip fırsatlarını tarar."""
    global _SNAPBACK_CACHE
    now = time.time()
    if _SNAPBACK_CACHE and (now - _SNAPBACK_CACHE[0]) < CACHE_TTL:
        return _SNAPBACK_CACHE[1]

    from app.binance_tr_public import klines as fetch_klines, trading_symbols

    if not symbols:
        try:
            raw_syms = await trading_symbols()
            symbols = [s for s in raw_syms if s.endswith(config.QUOTE_ASSET)][:30]
        except Exception:
            symbols = []
        if not symbols:
            symbols = [f"{c}{config.QUOTE_ASSET}" for c in ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "SUI"]]

    # BTC Pusulası ve 1H EMA200 Kalkanı
    btc_compass = await get_btc_compass()
    is_btc_bull = bool(btc_compass.get("is_btc_above_ema200", True))
    is_btc_panic = bool(btc_compass.get("is_btc_panic", False))

    candidates: List[dict] = []

    for sym in symbols:
        try:
            raw = await fetch_klines(sym, "1h", 120)
            if not raw or len(raw) < 35:
                continue

            closes = [float(b[4]) for b in raw]
            highs = [float(b[2]) for b in raw]
            lows = [float(b[3]) for b in raw]

            rsi7 = compute_wilder_rsi_1h(closes, 7)
            rsi14 = compute_wilder_rsi_1h(closes, 14)
            atr14 = _atr(highs, lows, closes, 14)

            if rsi7 is None or rsi14 is None or atr14 is None:
                continue

            # S2 Kuralı: RSI7 < 20 ve RSI14 < 30
            if rsi7 < 20.0 and rsi14 < 30.0:
                c_now = closes[-1]
                sl_price = round(c_now - 1.5 * atr14, 4)
                sl_pct = round((1.5 * atr14 / c_now) * 100.0, 2)

                # Kalite Skoru: Ne kadar derine indiyse o kadar güçlü V-sekme potansiyeli
                # 0 - 100 ölçeğinde
                depth_score = round(min(100.0, (20.0 - rsi7) * 2.5 + (30.0 - rsi14) * 1.5 + 50.0), 1)

                is_shielded = is_btc_bull and not is_btc_panic
                grade = "A+" if is_shielded else "B"

                candidates.append({
                    "symbol": sym,
                    "strategy": "S2_SNAPBACK",
                    "grade": grade,
                    "close": c_now,
                    "rsi7": round(rsi7, 2),
                    "rsi14": round(rsi14, 2),
                    "atr14": round(atr14, 4),
                    "stop_loss_price": sl_price,
                    "stop_loss_pct": sl_pct,
                    "exit_condition": "RSI(7) > 50 (Bar Kapanışı)",
                    "depth_score": depth_score,
                    "btc_regime_shield": "PROTECTED" if is_shielded else "UNPROTECTED",
                    "detected_at": now,
                })
        except Exception as exc:
            logger.debug("Snapback tarama hatası (%s): %s", sym, exc)

    # Derinlik skoruna göre sırala
    candidates.sort(key=lambda x: x["depth_score"], reverse=True)
    _SNAPBACK_CACHE = (now, candidates)
    return candidates


def get_cached_snapback_candidates() -> List[dict]:
    """Önbellekteki son snapback adaylarını döner."""
    if _SNAPBACK_CACHE and (time.time() - _SNAPBACK_CACHE[0]) < CACHE_TTL:
        return _SNAPBACK_CACHE[1]
    return []
