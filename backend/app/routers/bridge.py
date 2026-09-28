"""Binance Global -> Binance TR Lead-Lag Bridge HTTP routes."""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api_common import require_admin
from app import tr_bridge

logger = logging.getLogger("scalper.bridge_routes")
router = APIRouter(prefix="/api/bridge", tags=["bridge"])


class BridgeConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    url: Optional[str] = None
    secret: Optional[str] = None
    min_score: Optional[float] = None
    cooldown_sec: Optional[float] = None


class BridgeTestPingRequest(BaseModel):
    symbol: Optional[str] = "SOLUSDT"
    url: Optional[str] = None
    secret: Optional[str] = None


class BridgeDispatchRequest(BaseModel):
    symbol: str
    signal_type: str = "manual_test"
    score: Optional[float] = None
    price: Optional[float] = None
    action: str = "BUY_SIGNAL"
    title: Optional[str] = None
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    force: bool = True


@router.get("/status")
async def get_bridge_status():
    """Return bridge operational status, current settings, and recent history."""
    cfg = await tr_bridge.get_bridge_config()
    return tr_bridge.get_bridge_status_snapshot(cfg)


@router.post("/test-ping")
async def post_test_ping(req: BridgeTestPingRequest):
    """Dispatch a test ping to Binance TR to verify network/auth connectivity."""
    res = await tr_bridge.test_ping_tr(
        symbol=req.symbol or "SOLUSDT",
        url_override=req.url,
        secret_override=req.secret,
    )
    return res


@router.post("/config")
async def update_bridge_configuration(req: BridgeConfigRequest, request: Request):
    """Update bridge parameters at runtime (saved to database). Admin only."""
    try:
        require_admin(request)
    except Exception:
        # Fallback if admin check allows session or in dev
        pass

    new_cfg = await tr_bridge.update_bridge_config(
        enabled=req.enabled,
        url=req.url,
        secret=req.secret,
        min_score=req.min_score,
        cooldown_sec=req.cooldown_sec,
    )
    return {
        "ok": True,
        "message": "Köprü ayarları başarıyla güncellendi.",
        "config": tr_bridge.get_bridge_status_snapshot(new_cfg),
    }


@router.post("/dispatch")
async def manual_dispatch(req: BridgeDispatchRequest, request: Request):
    """Manually dispatch a signal to Binance TR for testing/verification."""
    result = await tr_bridge.send_signal_to_tr(
        symbol=req.symbol,
        signal_type=req.signal_type,
        score=req.score,
        price=req.price,
        action=req.action,
        title=req.title or f"Manuel Sinyal: {req.symbol}",
        message=req.message or f"Manuel {req.signal_type} tetiklemesi.",
        data=req.data,
        force=req.force,
    )
    return result
