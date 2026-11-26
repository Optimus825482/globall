"""Episodic Reflection Loop (TradingAgents / Reflexion-inspired Trade Memory).

After each closed trade, extracts a concise structured lesson (symbol, direction,
strategy, UTC hour, exit reason, PnL, actionable takeaway) into in-memory episodic
store (and `position_reflections` DB table when available). Before new entries,
retrieves the most relevant past lessons for the same symbol/direction/strategy.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("scalper.reflection")

_EPISODIC_STORE: Deque[Dict[str, Any]] = deque(maxlen=200)


def reflect_closed_trade(trade: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a structured post-trade reflection lesson and store it."""
    sym = str(trade.get("symbol") or "UNKNOWN").upper()
    direction = str(trade.get("direction") or "").upper()
    strategy = str(trade.get("strategy") or "UNKNOWN")
    reason = str(trade.get("reason") or "")
    try:
        pnl = float(trade.get("pnl_usd", trade.get("profit", 0.0)) or 0.0)
    except (TypeError, ValueError):
        pnl = 0.0
    exit_ts = float(trade.get("exit_ts") or trade.get("close_time") or time.time())
    hour_utc = int((exit_ts // 3600) % 24)
    outcome = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "FLAT")

    if outcome == "LOSS":
        if "SL" in reason.upper() or "ZARAR" in reason.upper():
            lesson = f"{sym} {direction} ({strategy}, {hour_utc:02d}:00 UTC) SL oldu (${pnl:+.2f}): giriş zamanlaması veya stop mesafesi dar kalmış olabilir."
        else:
            lesson = f"{sym} {direction} ({strategy}, {hour_utc:02d}:00 UTC) zararla kapandı (${pnl:+.2f}, {reason or 'manuel/kapanış'})."
    elif outcome == "WIN":
        lesson = f"{sym} {direction} ({strategy}, {hour_utc:02d}:00 UTC) kârla kapandı (${pnl:+.2f}): yapı ve yön uyumu çalıştı."
    else:
        lesson = f"{sym} {direction} ({strategy}) başabaş kapandı."

    rec = {
        "ts": round(exit_ts, 2),
        "symbol": sym,
        "direction": direction,
        "strategy": strategy,
        "hour_utc": hour_utc,
        "outcome": outcome,
        "pnl_usd": round(pnl, 2),
        "reason": reason,
        "lesson": lesson,
        "ticket": trade.get("ticket"),
    }
    _EPISODIC_STORE.appendleft(rec)
    return rec


def sync_reflections_from_closed_trades(closed_trades: List[Dict[str, Any]]) -> int:
    """Backfill episodic store from MT5 closed trades (deduplicated by ticket)."""
    seen = {r.get("ticket") for r in _EPISODIC_STORE if r.get("ticket") is not None}
    added = 0
    for tr in closed_trades or []:
        if not isinstance(tr, dict):
            continue
        tkt = tr.get("ticket")
        if tkt is not None and tkt in seen:
            continue
        reflect_closed_trade(tr)
        if tkt is not None:
            seen.add(tkt)
        added += 1
    return added


def retrieve_relevant_lessons(
    symbol: str,
    direction: str = "",
    strategy: str = "",
    *,
    limit: int = 3,
) -> Dict[str, Any]:
    """Retrieve the most relevant past reflections for a candidate signal."""
    sym_u = str(symbol or "").upper()
    dir_u = str(direction or "").upper()
    strat_u = str(strategy or "").upper()

    scored: List[tuple[int, Dict[str, Any]]] = []
    for rec in _EPISODIC_STORE:
        score = 0
        if rec["symbol"] == sym_u:
            score += 3
        if dir_u and rec["direction"] == dir_u:
            score += 2
        if strat_u and rec["strategy"].upper() == strat_u:
            score += 1
        if score >= 3:
            scored.append((score, rec))

    scored.sort(key=lambda pair: (-pair[0], -pair[1]["ts"]))
    top = [r for _, r in scored[: max(1, int(limit))]]
    recent_losses = sum(1 for r in top if r["outcome"] == "LOSS")
    caution = len(top) >= 2 and recent_losses == len(top)
    return {
        "symbol": sym_u,
        "direction": dir_u,
        "lessons": top,
        "caution": caution,
        "summary": top[0]["lesson"] if top else "",
    }


def get_reflection_summary(limit: int = 20) -> Dict[str, Any]:
    """Summary snapshot for diagnostics."""
    items = list(_EPISODIC_STORE)[: max(1, int(limit))]
    wins = sum(1 for r in items if r["outcome"] == "WIN")
    losses = sum(1 for r in items if r["outcome"] == "LOSS")
    return {
        "total_stored": len(_EPISODIC_STORE),
        "recent_wins": wins,
        "recent_losses": losses,
        "items": items,
    }
