"""Lead-Lag Signal Bridge: Binance Global -> Binance TR.

Global (USDT) price movements lead Binance TR (TRY) by several seconds.
This module dispatches high-conviction signals and alerts from Binance Global
to the Binance TR instance on the same server or via public/gateway URL.
"""
from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional, Tuple
import urllib3
from urllib3.util import Timeout

from app.config import config, base_asset_of
from app import database

logger = logging.getLogger("scalper.tr_bridge")

# Dedicated HTTP connection pool with keepalive and short timeouts
_POOL = urllib3.PoolManager(
    maxsize=16,
    timeout=Timeout(connect=2.0, read=3.0),
    retries=False,
)

# In-memory circular buffer for status and observability
_BRIDGE_HISTORY: deque[dict[str, Any]] = deque(maxlen=100)

# Statistics
_STATS: dict[str, Any] = {
    "total_dispatched": 0,
    "total_success": 0,
    "total_failed": 0,
    "total_skipped_cooldown": 0,
    "total_skipped_disabled": 0,
    "total_skipped_score": 0,
    "last_dispatched_at": None,
    "last_success_at": None,
    "last_error": None,
}

# Deduplication / Cooldown tracker: (symbol, signal_type) -> float (timestamp)
_COOLDOWN_MAP: dict[tuple[str, str], float] = {}

# Background task references to prevent garbage collection
_BRIDGE_TASKS: set[asyncio.Task] = set()


def map_to_tr_symbol(symbol: str) -> Tuple[str, str]:
    """Map a Global symbol (e.g. 'SOLUSDT') to base asset ('SOL') and TR symbol ('SOLTRY')."""
    base = base_asset_of(symbol)
    tr_symbol = f"{base}TRY"
    return base, tr_symbol


async def get_bridge_config() -> dict[str, Any]:
    """Fetch current bridge settings from database (runtime override) or config/env."""
    try:
        db_enabled = await database.get_llm_setting("tr_bridge_enabled")
        enabled = (
            str(db_enabled).strip().lower() in ("1", "true", "yes", "on")
            if db_enabled is not None
            else bool(getattr(config, "BINANCE_TR_BRIDGE_ENABLED", True))
        )
    except Exception:
        enabled = bool(getattr(config, "BINANCE_TR_BRIDGE_ENABLED", True))

    try:
        db_url = await database.get_llm_setting("tr_bridge_url")
        url = str(db_url).strip() if db_url else getattr(config, "BINANCE_TR_BRIDGE_URL", "")
    except Exception:
        url = getattr(config, "BINANCE_TR_BRIDGE_URL", "")

    try:
        db_secret = await database.get_llm_setting("tr_bridge_secret")
        secret = str(db_secret).strip() if db_secret else getattr(config, "BINANCE_TR_BRIDGE_SECRET", "")
    except Exception:
        secret = getattr(config, "BINANCE_TR_BRIDGE_SECRET", "")

    try:
        db_min_score = await database.get_llm_setting("tr_bridge_min_score")
        min_score = (
            float(db_min_score)
            if db_min_score is not None
            else float(getattr(config, "BINANCE_TR_BRIDGE_MIN_SCORE", 0.0))
        )
    except Exception:
        min_score = float(getattr(config, "BINANCE_TR_BRIDGE_MIN_SCORE", 0.0))

    try:
        db_cooldown = await database.get_llm_setting("tr_bridge_cooldown_sec")
        cooldown_sec = (
            float(db_cooldown)
            if db_cooldown is not None
            else float(getattr(config, "BINANCE_TR_BRIDGE_COOLDOWN_SEC", 10.0))
        )
    except Exception:
        cooldown_sec = float(getattr(config, "BINANCE_TR_BRIDGE_COOLDOWN_SEC", 10.0))

    return {
        "enabled": enabled,
        "url": url,
        "secret": secret,
        "min_score": min_score,
        "cooldown_sec": cooldown_sec,
    }


async def update_bridge_config(
    *,
    enabled: Optional[bool] = None,
    url: Optional[str] = None,
    secret: Optional[str] = None,
    min_score: Optional[float] = None,
    cooldown_sec: Optional[float] = None,
) -> dict[str, Any]:
    """Persist runtime bridge settings to database."""
    if enabled is not None:
        await database.set_llm_setting("tr_bridge_enabled", "true" if enabled else "false")
    if url is not None:
        await database.set_llm_setting("tr_bridge_url", url.strip())
    if secret is not None:
        await database.set_llm_setting("tr_bridge_secret", secret.strip())
    if min_score is not None:
        await database.set_llm_setting("tr_bridge_min_score", str(float(min_score)))
    if cooldown_sec is not None:
        await database.set_llm_setting("tr_bridge_cooldown_sec", str(float(cooldown_sec)))

    return await get_bridge_config()


def _send_http_request(url: str, secret: str, payload_bytes: bytes, timeout_sec: float) -> Tuple[int, str]:
    """Blocking HTTP request executed in thread pool."""
    headers = {
        "Content-Type": "application/json",
        "X-Bridge-Secret": secret,
        "User-Agent": "ScalperGlobal-LeadLagBridge/1.0",
    }
    timeout = Timeout(connect=min(2.0, timeout_sec), read=timeout_sec)
    resp = _POOL.request("POST", url, body=payload_bytes, headers=headers, timeout=timeout)
    data = resp.data.decode("utf-8", errors="replace")
    return resp.status, data


async def send_signal_to_tr(
    symbol: str,
    signal_type: str,
    *,
    score: Optional[float] = None,
    price: Optional[float] = None,
    action: str = "BUY_SIGNAL",
    title: str = "",
    message: str = "",
    data: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Forward a signal from Binance Global to the Binance TR instance.

    Guaranteed not to raise exceptions; returns delivery result dictionary.
    """
    now = time.time()
    cfg = await get_bridge_config()

    if not cfg["enabled"] and not force:
        _STATS["total_skipped_disabled"] += 1
        return {"ok": False, "skipped": True, "reason": "bridge_disabled"}

    url = cfg["url"]
    if not url:
        _STATS["total_skipped_disabled"] += 1
        return {"ok": False, "skipped": True, "reason": "no_url_configured"}

    # Score threshold check (if score is present and rule applies)
    if score is not None and score < cfg["min_score"] and not force:
        _STATS["total_skipped_score"] += 1
        return {"ok": False, "skipped": True, "reason": "score_below_min"}

    # Cooldown deduplication check
    cooldown_key = (symbol.upper(), signal_type.lower())
    last_dispatched = _COOLDOWN_MAP.get(cooldown_key, 0.0)
    if not force and (now - last_dispatched) < cfg["cooldown_sec"]:
        _STATS["total_skipped_cooldown"] += 1
        return {"ok": False, "skipped": True, "reason": "cooldown_active"}

    base_asset, tr_symbol = map_to_tr_symbol(symbol)
    event_id = str(uuid.uuid4())

    payload = {
        "source": "binance_global",
        "version": "1.0",
        "event_id": event_id,
        "timestamp": now,
        "global_symbol": symbol.upper(),
        "base_asset": base_asset,
        "tr_symbol": tr_symbol,
        "signal_type": signal_type,
        "action": action,
        "score": score,
        "price": price,
        "title": title or f"Global Sinyal: {symbol.upper()}",
        "message": message or f"Binance Global {signal_type} sinyali üretildi.",
        "data": data or {},
    }

    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    timeout_sec = float(getattr(config, "BINANCE_TR_BRIDGE_TIMEOUT", 3.0))

    _STATS["total_dispatched"] += 1
    _STATS["last_dispatched_at"] = now
    _COOLDOWN_MAP[cooldown_key] = now

    start_time = time.monotonic()
    status_code = None
    response_body = ""
    error_msg = None
    ok = False

    try:
        status_code, response_body = await asyncio.to_thread(
            _send_http_request, url, cfg["secret"], payload_bytes, timeout_sec
        )
        ok = 200 <= status_code < 300
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "TR Bridge gönderim hatası [%s -> %s]: %s",
            symbol,
            tr_symbol,
            error_msg,
        )

    latency_ms = round((time.monotonic() - start_time) * 1000, 2)

    if ok:
        _STATS["total_success"] += 1
        _STATS["last_success_at"] = now
        logger.info(
            "TR Bridge sinyal iletildi [%s -> %s] tip=%s skor=%s HTTP=%d (%0.1fms)",
            symbol,
            tr_symbol,
            signal_type,
            str(score),
            status_code,
            latency_ms,
        )
    else:
        _STATS["total_failed"] += 1
        _STATS["last_error"] = error_msg or f"HTTP {status_code}: {response_body[:100]}"
        if not error_msg:
            logger.warning(
                "TR Bridge başarısız yanıt [%s -> %s]: HTTP %d - %s",
                symbol,
                tr_symbol,
                status_code,
                response_body[:100],
            )

    history_item = {
        "event_id": event_id,
        "timestamp": now,
        "global_symbol": symbol.upper(),
        "base_asset": base_asset,
        "tr_symbol": tr_symbol,
        "signal_type": signal_type,
        "score": score,
        "price": price,
        "ok": ok,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "error": error_msg,
    }
    _BRIDGE_HISTORY.append(history_item)

    return {
        "ok": ok,
        "event_id": event_id,
        "global_symbol": symbol.upper(),
        "tr_symbol": tr_symbol,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "error": error_msg,
        "response": response_body[:200] if response_body else None,
    }


def queue_signal_to_tr(
    symbol: str,
    signal_type: str,
    *,
    score: Optional[float] = None,
    price: Optional[float] = None,
    action: str = "BUY_SIGNAL",
    title: str = "",
    message: str = "",
    data: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> Optional[asyncio.Task]:
    """Non-blocking fire-and-forget bridge dispatcher.

    Safe to call from anywhere (sync or async); will never delay caller.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    task = loop.create_task(
        send_signal_to_tr(
            symbol=symbol,
            signal_type=signal_type,
            score=score,
            price=price,
            action=action,
            title=title,
            message=message,
            data=data,
            force=force,
        )
    )
    _BRIDGE_TASKS.add(task)
    task.add_done_callback(_BRIDGE_TASKS.discard)
    return task


async def test_ping_tr(
    *,
    symbol: str = "SOLUSDT",
    url_override: Optional[str] = None,
    secret_override: Optional[str] = None,
) -> dict[str, Any]:
    """Send a diagnostic test ping to the configured Binance TR receiver."""
    cfg = await get_bridge_config()
    target_url = url_override or cfg["url"]
    target_secret = secret_override if secret_override is not None else cfg["secret"]

    if not target_url:
        return {"ok": False, "error": "Hedef URL tanımlanmamış."}

    base_asset, tr_symbol = map_to_tr_symbol(symbol)
    now = time.time()
    payload = {
        "source": "binance_global",
        "version": "1.0",
        "event_id": str(uuid.uuid4()),
        "timestamp": now,
        "global_symbol": symbol.upper(),
        "base_asset": base_asset,
        "tr_symbol": tr_symbol,
        "signal_type": "ping",
        "action": "TEST_PING",
        "score": 99.9,
        "price": 100.0,
        "title": "🧪 Global -> TR Köprü Test Ping",
        "message": "Binance Global test bağlantı isteği.",
        "data": {"test": True},
    }

    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    timeout_sec = max(8.0, float(getattr(config, "BINANCE_TR_BRIDGE_TIMEOUT", 5.0)))
    start = time.monotonic()
    try:
        status_code, body = await asyncio.to_thread(
            _send_http_request, target_url, target_secret, payload_bytes, timeout_sec
        )
        latency = round((time.monotonic() - start) * 1000, 2)
        return {
            "ok": 200 <= status_code < 300,
            "status_code": status_code,
            "latency_ms": latency,
            "target_url": target_url,
            "response": body[:500],
        }
    except Exception as exc:
        latency = round((time.monotonic() - start) * 1000, 2)
        err_text = str(exc)
        if "Read timed out" in err_text:
            err_text = f"Hedef sunucu yanıt vermedi (Zaman Aşımı): {target_url} ({timeout_sec}s). Hedef servisin ayakta olduğundan veya sunucu içi NAT loopback durumundan emin olun."
        elif "Connection refused" in err_text:
            err_text = f"Bağlantı reddedildi: {target_url} adresinde port kapalı veya servis çalışmıyor."
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": latency,
            "target_url": target_url,
            "error": err_text,
        }


def get_bridge_status_snapshot(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return bridge status, metrics, and recent transmissions."""
    secret = cfg.get("secret", "")
    masked_secret = f"{secret[:3]}***{secret[-3:]}" if len(secret) > 6 else ("***" if secret else "")
    return {
        "enabled": cfg["enabled"],
        "url": cfg["url"],
        "secret_configured": bool(secret),
        "masked_secret": masked_secret,
        "min_score": cfg["min_score"],
        "cooldown_sec": cfg["cooldown_sec"],
        "stats": dict(_STATS),
        "recent_history": list(reversed(list(_BRIDGE_HISTORY))),
    }
