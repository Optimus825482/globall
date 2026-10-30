"""Portföy riski, risk kapısı günlüğü, pozisyon gözetimi ve MAE/MFE raporu (araştırma raporu: Alan 1 ve 3)."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from app import database, portfolio_risk, position_supervisor
from app.api_common import rate_limit

router = APIRouter(prefix="/api", tags=["portfolio-risk"])


def summarize_gate_log(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Saf fonksiyon: günlükten 'engellerdi / engelledi' özeti ve sebep dağılımı."""
    would, enforced, reduced = 0, 0, 0
    by_reason: Dict[str, int] = {}
    by_symbol: Dict[str, int] = {}
    for r in rows:
        if r.get("decision") == "block":
            would += 1
            if r.get("enforced"):
                enforced += 1
            by_symbol[r.get("symbol") or "?"] = by_symbol.get(r.get("symbol") or "?", 0) + 1
            for reason in r.get("reasons") or []:
                code = reason.get("code") if isinstance(reason, dict) else str(reason)
                by_reason[code] = by_reason.get(code, 0) + 1
        elif float(r.get("mult") or 1.0) < 1.0:
            reduced += 1
    return {"entries_logged": len(rows), "would_block": would, "blocked_enforced": enforced, "size_reduced": reduced,
            "by_reason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1])),
            "by_symbol": dict(sorted(by_symbol.items(), key=lambda kv: -kv[1]))}


@router.get("/portfolio/risk")
async def portfolio_risk_snapshot():
    from app.routers import forex as fx
    return await portfolio_risk.snapshot(fx._AUTO_SETTINGS)


@router.get("/portfolio/stress")
async def portfolio_stress():
    """Açık pozisyonlara anlık şoklar: zarar (% özsermaye) ve şok sonrası marj seviyesi."""
    from app.routers import forex as fx
    st = fx._MT5_STATE
    acct = dict(st.get("account") or {})
    equity = float(acct.get("equity") or acct.get("balance") or 0.0)
    return {"equity": equity, "margin_used": acct.get("margin"),
            "scenarios": portfolio_risk.stress_test(list(st.get("open_positions") or []), equity, float(acct.get("margin") or 0.0),
                                                   lambda s: fx.get_symbol_trading_specs(s)),
            "limits": {"loss_pct": portfolio_risk.STRESS_LOSS_LIMIT_PCT, "margin_floor_pct": portfolio_risk.STRESS_MARGIN_FLOOR_PCT},
            "note": "Şok büyüklükleri ve eşikler tasarım örneğidir; MT5 stop-out seviyesini kendi brokerınızdan doğrulayın."}


@router.get("/portfolio/montecarlo")
async def portfolio_montecarlo(days: int = Query(90, ge=7, le=365), risk_pct: float = Query(1.0, ge=0.1, le=10.0),
                               dd_limit_pct: float = Query(10.0, ge=1.0, le=50.0)):
    """Kapanmış pozisyonların R sonuçlarında blok bootstrap: maksimum düşüş dağılımı."""
    rows = await database.list_position_excursions(since_ts=time.time() - days * 86400)
    r_values = [float(r["last_pnl_pips"]) / float(r["sl_pips"]) for r in rows
                if r.get("closed_at") and r.get("last_pnl_pips") is not None and r.get("sl_pips")]
    return portfolio_risk.monte_carlo_drawdown(r_values, risk_pct=risk_pct, dd_limit_pct=dd_limit_pct)


@router.get("/portfolio/sizing")
async def portfolio_sizing(symbol: str, sl_pips: float = Query(..., gt=0), base_risk_pct: float = Query(0.5, ge=0.05, le=5.0)):
    """Boyut önerisi: temel risk × drawdown çarpanı, kalan ısı bütçesi ve (örneklem varsa) kesirli Kelly tavanı."""
    from app.routers import forex as fx
    snap = await portfolio_risk.snapshot(fx._AUTO_SETTINGS)
    spec = fx.get_symbol_trading_specs(symbol.upper())
    equity = float((snap["account"] or {}).get("equity") or 0.0)
    rows = await database.list_position_excursions(since_ts=time.time() - 90 * 86400)
    closed = [r for r in rows if r.get("closed_at") and r.get("last_pnl_pips") is not None]
    wins = sum(1 for r in closed if float(r["last_pnl_pips"]) > 0)
    win_avg = [float(r["last_pnl_pips"]) for r in closed if float(r["last_pnl_pips"]) > 0]
    loss_avg = [abs(float(r["last_pnl_pips"])) for r in closed if float(r["last_pnl_pips"]) <= 0]
    rr = (sum(win_avg) / len(win_avg)) / (sum(loss_avg) / len(loss_avg)) if win_avg and loss_avg else 1.5
    edge = {"wins": wins, "n": len(closed), "rr": rr} if closed else None
    return portfolio_risk.sizing_suggestion(symbol.upper(), sl_pips, float(spec.get("pip_val") or 0), equity, snap["drawdown"]["mult"],
                                            snap["risk_budget_remaining_usd"], base_risk_pct, edge)


@router.get("/portfolio/gate-log")
async def portfolio_gate_log(days: int = Query(7, ge=1, le=90), limit: int = Query(200, ge=1, le=1000)):
    rows = await database.list_risk_gate_log(since_ts=time.time() - days * 86400, limit=limit)
    return {"days": days, "summary": summarize_gate_log(rows), "entries": rows[:100]}


@router.get("/positions/excursions")
async def positions_excursions(days: int = Query(30, ge=1, le=365)):
    rows = await database.list_position_excursions(since_ts=time.time() - days * 86400)
    return {"days": days, "stats": position_supervisor.excursion_stats(rows), "rows": rows[:100]}


@router.get("/positions/supervisor-log")
async def positions_supervisor_log(days: int = Query(7, ge=1, le=90), limit: int = Query(200, ge=1, le=1000)):
    rows = await database.list_supervisor_events(since_ts=time.time() - days * 86400, limit=limit)
    return {"days": days, "count": len(rows), "events": rows}


@router.post("/positions/llm-review")
async def positions_llm_review():
    """LLM'e açık pozisyonlar için ÖNERİ yaptırır. Öneriler beyaz listeyle doğrulanır ve UYGULANMAZ."""
    if not rate_limit("positions_llm_review", rate_per_sec=0.05, burst=2):
        raise HTTPException(status_code=429, detail="Çok sık istendi, biraz bekleyin")
    from app.routers import forex as fx
    try:
        return await position_supervisor.review_positions(fx._AUTO_SETTINGS)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM önerisi alınamadı: {type(exc).__name__}")
