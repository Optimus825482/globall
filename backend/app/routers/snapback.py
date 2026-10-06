"""Snapback (S2/S6 Dip Avcısı) ve Makro Rejim Kalkanı API Router'ı.

2026-10-06 mRSI / EMA Replay doğrulaması sonucu sisteme kazandırılan
yeni nesil Dip Avcısı ve BTC 1H EMA200 Rejim Kalkanı uçları.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Query

from app.macro_sentiment_service import get_btc_compass, get_macro_sentiment
from app.snapback_service import scan_snapback_candidates

logger = logging.getLogger("scalper.routers.snapback")

router = APIRouter(prefix="/api/signals", tags=["snapback-and-regime"])


@router.get("/snapback")
async def get_snapback_opportunities(
    limit: int = Query(default=10, ge=1, le=50, description="Maksimum aday sayısı")
) -> Dict[str, Any]:
    """1H Wilder RSI (7<20 & 14<30) aşırı satım panik dibi adaylarını listeler.
    
    BTC 1H EMA200 üzerinde olanlar 'A+' kalkanlı, altındakiler 'B' dereceli döner.
    """
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        lim = 10

    candidates = await scan_snapback_candidates()
    btc_compass = await get_btc_compass()

    return {
        "status": "ok",
        "strategy": "S2_S6_SNAPBACK_DIP_HUNTER",
        "macro_shield_active": not btc_compass.get("is_btc_above_ema200", True),
        "btc_1h_close": btc_compass.get("btc_1h_close"),
        "btc_1h_ema200": btc_compass.get("btc_1h_ema200"),
        "count": len(candidates),
        "candidates": candidates[:lim],
    }


@router.get("/macro-regime")
async def get_macro_regime_shield_status() -> Dict[str, Any]:
    """BTC 1H EMA200 Makro Rejim Kalkanı ve Fear & Greed durumunu döner."""
    macro = await get_macro_sentiment()
    return {
        "status": "ok",
        "macro_sentiment": macro,
    }
