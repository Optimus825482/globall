"""Tests for read-only Forex diagnostics & losing-trade forensics endpoints."""
import asyncio
import time

from app.routers import forex as fx


def test_diagnostics_today_audit_and_losses_breakdown(monkeypatch):
    now = time.time()
    monkeypatch.setattr(fx, "_MT5_STATE", {
        "connected": True,
        "auto_trade": True,
        "account": {"server": "ICMarketsSC-Demo", "balance": 1000.0, "equity": 985.5},
        "open_positions": [{"symbol": "AUDUSD", "direction": "SELL", "profit": 12.5}],
        "pending_commands": [],
        "closed_deals": [
            {
                "ticket": 101,
                "symbol": "EURUSD",
                "direction": "BUY",
                "strategy": "FIRSAT_TARAMASI",
                "lots": 0.1,
                "pnl_usd": -15.0,
                "reason": "SL",
                "exit_ts": now - 600,
                "entry_ts": now - 1200,
            },
            {
                "ticket": 102,
                "symbol": "EURUSD",
                "direction": "SELL",
                "strategy": "M1_M5_RADAR_SCALPER",
                "lots": 0.1,
                "pnl_usd": 25.0,
                "reason": "TP",
                "exit_ts": now - 300,
                "entry_ts": now - 900,
            },
        ],
    })
    monkeypatch.setattr(fx, "_AUTO_STATE", {
        "decision_logs": [
            {"ts": now - 1200, "category": "ENTRY", "symbol": "EURUSD", "message": "EURUSD BUY açıldı"},
        ],
        "closed_trades": [],
    })

    audit = asyncio.run(fx.get_forex_diagnostics_today_audit(period="today", limit=50))
    assert audit["account"]["connected"] is True
    settings = audit["account"]["settings"]
    assert settings["risk_pct"] is not None
    assert settings["risk_pct"] == fx._AUTO_SETTINGS.risk_per_trade_pct
    for key in ("risk_gold_pct", "risk_index_pct", "risk_crypto_pct", "risk_gate_mode", "proof_scope_enabled"):
        assert key in settings
    assert audit["trades_summary"]["closed_count"] == 2
    assert audit["trades_summary"]["wins"] == 1
    assert audit["trades_summary"]["losses"] == 1
    assert audit["trades_summary"]["net_pnl_usd"] == 10.0

    forensics = audit["losing_trades_forensics"]
    assert forensics["total_losses"] == 1
    assert forensics["total_loss_usd"] == -15.0
    assert forensics["by_symbol"]["EURUSD"]["count"] == 1
    assert forensics["by_strategy"]["FIRSAT_TARAMASI"]["loss_usd"] == -15.0
    assert forensics["trades"][0]["duration_sec"] == 600.0
    assert len(forensics["trades"][0]["recent_decisions"]) == 1

    scans = asyncio.run(fx.get_forex_diagnostics_scans(limit=20))
    assert "opportunity_scan" in scans and "radar_cache" in scans and "ev_shield_blocked" in scans

    losses = asyncio.run(fx.get_forex_diagnostics_losses(period="today", symbol="EURUSD"))
    assert losses["losing_trades_forensics"]["total_losses"] == 1


def test_fetch_db_forensics_uses_valid_schema_columns(monkeypatch):
    from app import forex_diagnostics

    queries = []

    def fake_query(sql, params=()):
        queries.append((sql, params))
        return []

    monkeypatch.setattr(forex_diagnostics, "_query_db_rows", fake_query)
    res = forex_diagnostics._fetch_db_forensics(1000.0, 2000.0, limit=25)
    assert set(res.keys()) == {
        "risk_gate_log",
        "position_supervisor_log",
        "position_reflections",
        "position_excursions",
    }
    assert len(queries) == 4
    sql_map = {q[0].split("FROM ")[1].split()[0]: q for q in queries}

    assert "WHERE ts >= ? ORDER BY ts DESC LIMIT ?" in sql_map["risk_gate_log"][0]
    assert sql_map["risk_gate_log"][1] == (1000.0, 25)

    assert "WHERE ts >= ? ORDER BY ts DESC LIMIT ?" in sql_map["position_supervisor_log"][0]
    assert "created_at" not in sql_map["position_supervisor_log"][0]
    assert sql_map["position_supervisor_log"][1] == (1000.0, 25)

    assert "WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?" in sql_map["position_reflections"][0]
    assert isinstance(sql_map["position_reflections"][1][0], float)
    assert sql_map["position_reflections"][1] == (1000.0, 25)

    assert "COALESCE(closed_at, last_seen, open_ts) >= ? ORDER BY last_seen DESC LIMIT ?" in sql_map["position_excursions"][0]
    assert "updated_at" not in sql_map["position_excursions"][0]
    assert sql_map["position_excursions"][1] == (1000.0, 25)
