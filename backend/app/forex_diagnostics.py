"""Read-only diagnostics & forensics helpers for Forex/MT5 scans, decisions, and losing trades."""
from __future__ import annotations

import datetime
import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("scalper.forex_diagnostics")

TZ_UTC3 = datetime.timezone(datetime.timedelta(hours=3))


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        f = float(val)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def _query_db_rows(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Run a safe read-only DB query; returns [] if DB is unavailable or table is empty."""
    try:
        from app import database
        with database._db_connection() as conn:
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                for k, v in list(d.items()):
                    if isinstance(v, datetime.datetime):
                        d[k] = v.isoformat()
                out.append(d)
            return out
    except Exception as exc:  # noqa: BLE001
        logger.debug("Diagnostics DB query skipped: %s", exc)
        return []


def _fetch_db_forensics(start_ts: Optional[float], end_ts: Optional[float], limit: int = 100) -> Dict[str, Any]:
    """Fetch recent diagnostic rows from PostgreSQL tables for the requested window."""
    lim = max(1, min(500, int(limit)))
    since_ts = float(start_ts) if start_ts is not None else (time.time() - 86400.0)
    since_dt = datetime.datetime.fromtimestamp(since_ts, datetime.timezone.utc)

    risk_gate_rows = _query_db_rows(
        "SELECT * FROM risk_gate_log WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
        (since_ts, lim),
    )
    supervisor_rows = _query_db_rows(
        "SELECT * FROM position_supervisor_log WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?",
        (since_dt, lim),
    )
    reflection_rows = _query_db_rows(
        "SELECT * FROM position_reflections WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?",
        (since_dt, lim),
    )
    excursion_rows = _query_db_rows(
        "SELECT * FROM position_excursions WHERE updated_at >= ? ORDER BY updated_at DESC LIMIT ?",
        (since_ts, lim),
    )
    return {
        "risk_gate_log": risk_gate_rows,
        "position_supervisor_log": supervisor_rows,
        "position_reflections": reflection_rows,
        "position_excursions": excursion_rows,
    }


def _build_scans_snapshot(fx: Any) -> Dict[str, Any]:
    """Collect opportunity scan state, radar cache summary, and EV shield status."""
    from app import opportunity_trades

    opp_state = opportunity_trades.get_auto_scan_state()
    skipped_by_reason: Dict[str, int] = defaultdict(int)
    for item in opp_state.get("skipped") or []:
        raw_reason = str(item.get("reason") or "bilinmeyen").strip()
        if "(" in raw_reason and ":" in raw_reason and raw_reason.index("(") < raw_reason.index(":"):
            reason = raw_reason
        else:
            reason = raw_reason.split(":")[0].strip()
        skipped_by_reason[reason] += 1

    radar_ts = None
    radar_candidates: List[Dict[str, Any]] = []
    rc = getattr(fx, "_RADAR_CACHE", None)
    if isinstance(rc, tuple) and len(rc) >= 2 and isinstance(rc[1], dict):
        radar_ts = rc[0]
        for c in (rc[1].get("candidates") or [])[:25]:
            if not isinstance(c, dict):
                continue
            radar_candidates.append({
                "symbol": c.get("symbol"),
                "direction": c.get("direction") or c.get("action"),
                "score": c.get("score"),
                "hurst_regime": c.get("hurst_regime"),
                "hurst_h": c.get("hurst_h") if c.get("hurst_h") is not None else c.get("hurst"),
                "kalman_zscore": c.get("kalman_zscore"),
                "kalman_overextended": c.get("kalman_overextended"),
                "hmm_regime": c.get("hmm_regime"),
                "hmm_confidence": c.get("hmm_confidence"),
                "macro_alignment": c.get("macro_alignment"),
                "macro_delta": c.get("macro_delta"),
                "macro_note": c.get("macro_note"),
            })

    ev_blocked: List[Dict[str, Any]] = []
    try:
        if hasattr(fx, "get_all_symbol_ev_status"):
            ev_res = fx.get_all_symbol_ev_status(time.time()) or {}
            ev_blocked = [s for s in (ev_res.get("symbols") or []) if s.get("is_blocked")]
    except Exception:  # noqa: BLE001
        pass

    return {
        "opportunity_scan": {
            "enabled": opp_state.get("enabled"),
            "interval_min": opp_state.get("interval_min"),
            "status": opp_state.get("status"),
            "last_run_ts": opp_state.get("last_run_ts"),
            "next_run_ts": opp_state.get("next_run_ts"),
            "duration_sec": opp_state.get("duration_sec"),
            "scanned_count": opp_state.get("scanned_count"),
            "top": opp_state.get("top") or [],
            "opened": opp_state.get("opened") or [],
            "skipped": opp_state.get("skipped") or [],
            "skipped_by_reason": dict(sorted(skipped_by_reason.items(), key=lambda kv: -kv[1])),
            "error": opp_state.get("error"),
        },
        "radar_cache": {
            "cached_ts": radar_ts,
            "candidate_count": len(radar_candidates),
            "candidates": radar_candidates,
        },
        "ev_shield_blocked": ev_blocked,
    }


def _collect_decisions(fx: Any, start_ts: Optional[float], end_ts: Optional[float], limit: int = 200) -> Dict[str, Any]:
    """Filter in-memory auto decision logs for the requested window."""
    logs = list((getattr(fx, "_AUTO_STATE", None) or {}).get("decision_logs") or [])
    filtered: List[Dict[str, Any]] = []
    by_category: Dict[str, int] = defaultdict(int)
    for item in logs:
        ts = _safe_float(item.get("ts") or item.get("timestamp") or item.get("created_at_ts"), 0.0)
        if start_ts is not None and ts > 0 and ts < start_ts:
            continue
        if end_ts is not None and ts > 0 and ts > end_ts:
            continue
        cat = str(item.get("category") or "OTHER").upper()
        by_category[cat] += 1
        filtered.append(item)
        if len(filtered) >= limit:
            break
    return {
        "total": len(filtered),
        "by_category": dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
        "items": filtered,
    }


def _analyze_losing_trades(
    closed_trades: List[Dict[str, Any]],
    decisions: List[Dict[str, Any]],
    fx: Any,
) -> Dict[str, Any]:
    """Build root-cause breakdown for losing trades in the window."""
    losses = [t for t in closed_trades if _safe_float(t.get("pnl_usd", t.get("profit")), 0.0) < 0.0]

    by_strategy: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "loss_usd": 0.0})
    by_symbol: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "loss_usd": 0.0})
    by_reason: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "loss_usd": 0.0})
    by_hour: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "loss_usd": 0.0})
    by_direction: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "loss_usd": 0.0})

    dec_by_sym: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for d in decisions:
        dsym = str(d.get("symbol") or "").upper()
        if dsym:
            dec_by_sym[dsym].append(d)

    enriched: List[Dict[str, Any]] = []
    total_loss = 0.0
    for t in losses:
        pnl = _safe_float(t.get("pnl_usd", t.get("profit")), 0.0)
        total_loss += pnl
        sym = str(t.get("symbol") or "UNKNOWN").upper()
        strat = str(t.get("strategy") or (fx.strategy_from_mt5_deal(t) if hasattr(fx, "strategy_from_mt5_deal") else "UNKNOWN"))
        strat_lbl = str(t.get("strategy_label") or (fx.strategy_display_label(strat) if hasattr(fx, "strategy_display_label") else strat))
        reason = str(t.get("reason") or t.get("exit_reason") or t.get("comment") or "UNKNOWN")
        direction = str(t.get("direction") or t.get("side") or "UNKNOWN").upper()

        exit_ts = _safe_float(t.get("exit_ts") or t.get("close_time") or (fx._deal_ts(t) if hasattr(fx, "_deal_ts") else 0.0), 0.0)
        entry_ts = _safe_float(t.get("entry_ts") or t.get("open_time"), 0.0)
        duration_sec = round(exit_ts - entry_ts, 1) if (exit_ts > 0 and entry_ts > 0 and exit_ts >= entry_ts) else None
        hour_key = datetime.datetime.fromtimestamp(exit_ts, TZ_UTC3).strftime("%H:00") if exit_ts > 0 else "unknown"

        for bucket, key in (
            (by_strategy, strat),
            (by_symbol, sym),
            (by_reason, reason),
            (by_hour, hour_key),
            (by_direction, direction),
        ):
            bucket[key]["count"] += 1
            bucket[key]["loss_usd"] = round(bucket[key]["loss_usd"] + pnl, 2)

        enriched.append({
            "ticket": t.get("ticket") or t.get("position_id") or t.get("id"),
            "symbol": sym,
            "direction": direction,
            "strategy": strat,
            "strategy_label": strat_lbl,
            "lots": _safe_float(t.get("lots") or t.get("volume"), 0.0),
            "entry_price": t.get("entry_price") or t.get("open_price"),
            "exit_price": t.get("exit_price") or t.get("close_price"),
            "pnl_usd": round(pnl, 2),
            "pips": t.get("pips"),
            "reason": reason,
            "comment": t.get("comment"),
            "entry_ts": entry_ts or None,
            "exit_ts": exit_ts or None,
            "duration_sec": duration_sec,
            "recent_decisions": dec_by_sym.get(sym, [])[:5],
        })

    for b in (by_strategy, by_symbol):
        for v in b.values():
            v["avg_loss_usd"] = round(v["loss_usd"] / max(1, v["count"]), 2)

    return {
        "total_losses": len(losses),
        "total_loss_usd": round(total_loss, 2),
        "by_strategy": dict(sorted(by_strategy.items(), key=lambda kv: kv[1]["loss_usd"])),
        "by_symbol": dict(sorted(by_symbol.items(), key=lambda kv: kv[1]["loss_usd"])),
        "by_reason": dict(sorted(by_reason.items(), key=lambda kv: kv[1]["loss_usd"])),
        "by_hour_utc3": dict(sorted(by_hour.items())),
        "by_direction": dict(sorted(by_direction.items(), key=lambda kv: kv[1]["loss_usd"])),
        "trades": sorted(enriched, key=lambda x: x["pnl_usd"]),
    }


def _get_windowed_closed_trades(
    fx: Any,
    period: str = "today",
    date: Optional[str] = None,
    symbol: Optional[str] = None,
    strategy: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], Optional[float], Optional[float]]:
    now_ts = time.time()
    date_from = date.strip() if date else None
    date_to = date.strip() if date else None
    eff_period = "custom" if date else period
    start_ts, end_ts = fx._resolve_report_window(eff_period, date_from, date_to, now_ts)

    mt5_deals = list((getattr(fx, "_MT5_STATE", None) or {}).get("closed_deals") or [])
    all_closed = (
        fx._merge_partial_close_rows(mt5_deals) if (mt5_deals and hasattr(fx, "_merge_partial_close_rows"))
        else list((getattr(fx, "_AUTO_STATE", None) or {}).get("closed_trades") or [])
    )

    out: List[Dict[str, Any]] = []
    for t in all_closed:
        ts = (fx._deal_ts(t) if hasattr(fx, "_deal_ts") else None) or _safe_float(t.get("exit_ts") or t.get("close_time"), 0.0)
        if (start_ts is not None or end_ts is not None) and hasattr(fx, "_deal_in_window"):
            if not fx._deal_in_window(ts, start_ts, end_ts):
                continue
        if symbol and symbol.upper() != "ALL" and str(t.get("symbol") or "").upper() != symbol.upper():
            continue
        strat = t.get("strategy") or (fx.strategy_from_mt5_deal(t) if hasattr(fx, "strategy_from_mt5_deal") else "")
        if strategy and strategy.upper() != "ALL" and strategy.upper() not in str(strat).upper():
            continue
        out.append(t)
    return out, start_ts, end_ts


def build_today_audit(
    fx: Any,
    period: str = "today",
    date: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    """All-in-one read-only forensic snapshot for scans, decisions, and losing trades."""
    closed, start_ts, end_ts = _get_windowed_closed_trades(fx, period=period, date=date)
    decisions = _collect_decisions(fx, start_ts, end_ts, limit=limit)
    scans = _build_scans_snapshot(fx)
    losses = _analyze_losing_trades(closed, decisions["items"], fx)
    db_logs = _fetch_db_forensics(start_ts, end_ts, limit=min(limit, 150))

    wins = [t for t in closed if _safe_float(t.get("pnl_usd", t.get("profit")), 0.0) > 0.0]
    gross_profit = round(sum(_safe_float(t.get("pnl_usd", t.get("profit")), 0.0) for t in wins), 2)
    gross_loss = round(abs(losses["total_loss_usd"]), 2)
    net_pnl = round(gross_profit - gross_loss, 2)
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (None if gross_profit == 0 else 99.0)

    from app import episodic_reflection, quantstats_analytics

    episodic_reflection.sync_reflections_from_closed_trades(closed)
    mt5_st = getattr(fx, "_MT5_STATE", None) or {}
    acc = mt5_st.get("account") or {}
    settings = getattr(fx, "_AUTO_SETTINGS", None)
    bal = _safe_float(acc.get("balance"), 1000.0)
    tearsheet = quantstats_analytics.build_tearsheet(closed, initial_balance=max(100.0, bal - net_pnl))

    return {
        "window": {
            "period": "custom" if date else period,
            "date": date,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "server_ts": round(time.time(), 2),
        },
        "account": {
            "connected": bool(mt5_st.get("connected")),
            "auto_trade": bool(mt5_st.get("auto_trade")),
            "server": acc.get("server"),
            "balance": acc.get("balance"),
            "equity": acc.get("equity"),
            "open_positions_count": len(mt5_st.get("open_positions") or []),
            "pending_commands_count": len(mt5_st.get("pending_commands") or []),
            "settings": {
                "risk_pct": getattr(settings, "risk_pct", None),
                "max_open_positions": getattr(settings, "max_open_positions", None),
                "dxy_filter_enabled": getattr(settings, "dxy_filter_enabled", None),
                "correlation_guard": getattr(settings, "correlation_guard", None),
                "auto_opportunity_scan_enabled": getattr(settings, "auto_opportunity_scan_enabled", None),
                "auto_opportunity_scan_interval_min": getattr(settings, "auto_opportunity_scan_interval_min", None),
            },
        },
        "trades_summary": {
            "open_positions": mt5_st.get("open_positions") or [],
            "closed_count": len(closed),
            "wins": len(wins),
            "losses": losses["total_losses"],
            "win_rate_pct": round(len(wins) / len(closed) * 100.0, 1) if closed else 0.0,
            "net_pnl_usd": net_pnl,
            "gross_profit_usd": gross_profit,
            "gross_loss_usd": gross_loss,
            "profit_factor": pf,
        },
        "tearsheet": tearsheet,
        "scans": scans,
        "meta_filter": __import__("app.meta_label_filter", fromlist=["get_meta_filter_stats"]).get_meta_filter_stats(),
        "episodic_reflections": episodic_reflection.get_reflection_summary(limit=15),
        "decisions": decisions,
        "losing_trades_forensics": losses,
        "db_logs": db_logs,
    }


def build_tearsheet_report(
    fx: Any,
    period: str = "all",
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """Build standalone QuantStats-style tear-sheet JSON for the requested window."""
    from app import quantstats_analytics

    closed, start_ts, end_ts = _get_windowed_closed_trades(fx, period=period, date=date)
    mt5_st = getattr(fx, "_MT5_STATE", None) or {}
    acc = mt5_st.get("account") or {}
    net_pnl = sum(_safe_float(t.get("pnl_usd", t.get("profit")), 0.0) for t in closed)
    bal = _safe_float(acc.get("balance"), 1000.0)
    report = quantstats_analytics.build_tearsheet(closed, initial_balance=max(100.0, bal - net_pnl))
    report["window"] = {"period": "custom" if date else period, "date": date, "start_ts": start_ts, "end_ts": end_ts}
    return report


def build_scans_report(fx: Any, limit: int = 100) -> Dict[str, Any]:
    scans = _build_scans_snapshot(fx)
    since_ts = time.time() - 86400.0
    scans["risk_gate_log"] = _query_db_rows(
        "SELECT * FROM risk_gate_log WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
        (since_ts, max(1, min(300, int(limit)))),
    )
    return scans


def build_losses_report(
    fx: Any,
    period: str = "today",
    date: Optional[str] = None,
    symbol: Optional[str] = None,
    strategy: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    closed, start_ts, end_ts = _get_windowed_closed_trades(
        fx, period=period, date=date, symbol=symbol, strategy=strategy
    )
    decisions = _collect_decisions(fx, start_ts, end_ts, limit=limit)
    losses = _analyze_losing_trades(closed, decisions["items"], fx)
    db_logs = _fetch_db_forensics(start_ts, end_ts, limit=min(limit, 150))
    return {
        "window": {"period": "custom" if date else period, "date": date, "start_ts": start_ts, "end_ts": end_ts},
        "losing_trades_forensics": losses,
        "db_logs": db_logs,
    }
