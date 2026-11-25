"""Pozisyon gözetimi: kapanış saati (DST), olay riski, beyaz listeli eylem doğrulama, MAE/MFE istatistiği."""
from datetime import datetime, timezone

import pytest

from app import position_supervisor as ps
from app.routers.portfolio_risk import summarize_gate_log


def ts(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp()


CFG = {"event_window_min": 10, "flat_before_close_min": 30}


# ----------------------------------------------------------------------------- New York kapanışı

def test_ny_offset_follows_us_dst():
    assert ps.ny_utc_offset_hours(datetime(2026, 7, 1, tzinfo=timezone.utc)) == -4        # yaz
    assert ps.ny_utc_offset_hours(datetime(2026, 12, 1, tzinfo=timezone.utc)) == -5       # kış
    assert ps.ny_utc_offset_hours(datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc)) == -5   # DST'den hemen önce
    assert ps.ny_utc_offset_hours(datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)) == -4    # 2. Pazar Mart 02:00 EST
    assert ps.ny_utc_offset_hours(datetime(2026, 11, 1, 5, 59, tzinfo=timezone.utc)) == -4
    assert ps.ny_utc_offset_hours(datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)) == -5


def test_minutes_to_weekly_close():
    # 30 Ekim 2026 Cuma, DST (EDT): kapanış 21:00 UTC
    assert ps.minutes_to_weekly_close(ts(2026, 10, 30, 20, 30)) == pytest.approx(30.0)
    assert ps.minutes_to_weekly_close(ts(2026, 10, 30, 21, 30)) > 6 * 24 * 60            # kapanış geçti → gelecek hafta
    # kış (EST): kapanış 22:00 UTC
    assert ps.minutes_to_weekly_close(ts(2026, 12, 4, 21, 30)) == pytest.approx(30.0)
    # Pazartesi 00:00 UTC → ~4 gün 21-22 saat sonra
    assert 4 * 1440 < ps.minutes_to_weekly_close(ts(2026, 10, 26, 0, 0)) < 5 * 1440


# ----------------------------------------------------------------------------- olay + değerlendirme

def ev(title="NFP", currency="USD", stars=3, minutes=5, now=None):
    now = now or ts(2026, 10, 28, 12, 0)
    return {"title": title, "currency": currency, "stars": stars,
            "date_iso": datetime.fromtimestamp(now + minutes * 60, timezone.utc).isoformat()}


def position(**kw):
    base = {"ticket": 7, "symbol": "XAUUSD", "direction": "BUY", "lots": 0.05, "entry_price": 4000.0, "current_price": 4004.0,
            "sl_price": 3990.0, "tp_price": 4020.0, "pnl_pips": 40.0, "pnl_usd": 20.0, "open_ts": ts(2026, 10, 28, 11, 0)}
    base.update(kw)
    return base


NOW = ts(2026, 10, 28, 12, 0)


def test_next_event_filters_currency_stars_and_window():
    assert ps.next_event([ev()], "XAUUSD", NOW, 10)["minutes"] == 5.0
    assert ps.next_event([ev(currency="EUR")], "XAUUSD", NOW, 10) is None           # altın için yalnız USD
    assert ps.next_event([ev(currency="EUR")], "EURUSD", NOW, 10) is not None
    assert ps.next_event([ev(stars=2)], "XAUUSD", NOW, 10) is None
    assert ps.next_event([ev(minutes=40)], "XAUUSD", NOW, 10) is None
    assert ps.next_event([ev(minutes=-3)], "XAUUSD", NOW, 10) is None               # geçmiş


def test_profitable_position_before_event_gets_breakeven_action():
    f = ps.assess(position(), NOW, [ev()], CFG)
    assert [x["kind"] for x in f] == ["event_risk"] and f[0]["action"] == "breakeven"


def test_losing_or_already_safe_position_is_only_flagged():
    losing = ps.assess(position(pnl_pips=-20, current_price=3998.0), NOW, [ev()], CFG)
    assert losing[0]["action"] == "flag" and "gevşetilmez" in losing[0]["detail"]
    safe = ps.assess(position(sl_price=4001.0), NOW, [ev()], CFG)
    assert safe[0]["action"] == "flag" and "başabaşta" in safe[0]["detail"]


def test_weekend_and_missing_sl_findings():
    fri = ts(2026, 10, 30, 20, 40)                       # kapanışa 20 dk
    kinds = [x["kind"] for x in ps.assess(position(sl_price=0), fri, [], CFG)]
    assert kinds == ["no_sl", "weekend_risk"]
    assert not ps.assess(position(symbol="BTCUSD", sl_price=3990.0), fri, [], CFG)           # kripto hafta sonu işlem görür
    assert not ps.assess(position(), ts(2026, 10, 30, 19, 0), [], CFG)                       # 2 saat var: erken


# ----------------------------------------------------------------------------- beyaz liste

def test_validate_action_whitelist_and_tighten_only():
    p = position()
    assert ps.validate_action(p, {"action": "hold"})["ok"]
    assert not ps.validate_action(p, {"action": "add_position"})["ok"]                      # ekleme yok
    assert not ps.validate_action(p, {"action": "widen_stop"})["ok"]
    assert ps.validate_action(p, {"action": "partial_close", "pct": 50})["pct"] == 50
    assert not ps.validate_action(p, {"action": "partial_close", "pct": 70})["ok"]
    assert not ps.validate_action(p, {"action": "partial_close"})["ok"]
    be = ps.validate_action(p, {"action": "move_sl_to_breakeven"})
    assert be["ok"] and be["sl"] == 4000.0
    assert not ps.validate_action(position(sl_price=4001.0), {"action": "move_sl_to_breakeven"})["ok"]    # zaten kârda: gevşetme/aynı
    assert not ps.validate_action(position(current_price=3995.0), {"action": "move_sl_to_breakeven"})["ok"]   # zararda anlamsız
    sell = position(direction="SELL", entry_price=4000.0, current_price=3995.0, sl_price=4010.0)
    assert ps.validate_action(sell, {"action": "move_sl_to_breakeven"})["sl"] == 4000.0


def test_build_command_only_protective():
    cmd = ps.build_command(position(), "breakeven")
    assert cmd["action"] == "MODIFY_SLTP" and cmd["sl"] == 4000.0 and cmd["tp"] == 4020.0 and cmd["ticket"] == 7
    assert "tp_action" not in cmd
    no_tp = ps.build_command(position(tp_price=0), "breakeven")
    assert no_tp["tp_action"] == "cancel"
    assert ps.build_command(position(), "close")["action"] == "CLOSE_ORDER"
    assert ps.build_command(position(), "add") is None and ps.build_command(position(ticket=None), "close") is None
    assert ps.build_command(position(sl_price=4001.0), "breakeven") is None                  # zaten güvenli


def test_parse_proposals_takes_last_per_ticket_from_reasoning():
    text = ('Düşünüyorum {"ticket": 7, "action": "close", "reason": "taslak"} … '
            'Sonuç: {"ticket": 7, "action": "hold", "pct": null, "reason": "kısa"} {"ticket": 8, "action": "partial_close", "pct": 50, "reason": "x"}')
    props = {p["ticket"]: p for p in ps.parse_proposals(text)}
    assert props[7]["action"] == "hold" and props[8]["pct"] == 50 and len(props) == 2
    assert ps.parse_proposals("öneri yok") == []


def test_position_view_has_r_multiple_and_event_minutes():
    v = ps.position_view(position(), NOW, [ev(minutes=15)], CFG, {"mfe_pips": 55, "mae_pips": -8})
    assert v["r_kati"] == 0.4 and v["olaya_dakika"] == 15.0 and v["mfe_pip"] == 55 and v["acik_dakika"] == 60.0
    assert ps.position_view(position(sl_price=0), NOW, [], CFG)["r_kati"] is None


# ----------------------------------------------------------------------------- MAE/MFE

def test_excursion_stats_winners_mae_and_time_to_mfe():
    rows = []
    for i in range(10):
        rows.append({"closed_at": 1, "last_pnl_pips": 20, "mae_pips": -(2 + i), "mfe_pips": 25, "open_ts": 1000, "mfe_ts": 1000 + 600 * (1 + i % 2)})
    for i in range(5):
        rows.append({"closed_at": 1, "last_pnl_pips": -10, "mae_pips": -12, "mfe_pips": 3 + i, "open_ts": 1000, "mfe_ts": 1100})
    rows.append({"closed_at": None, "last_pnl_pips": 5, "mae_pips": -1, "mfe_pips": 6, "open_ts": 1000})
    s = ps.excursion_stats(rows)
    assert (s["n_closed"], s["n_open"], s["winners"], s["losers"]) == (15, 1, 10, 5)
    assert s["winner_mae_p80_pips"] == 9 and s["suggested_time_stop_minutes"] == pytest.approx(15.0)    # medyan MFE süresi 10 dk × 1.5
    assert s["loser_mfe_median_pips"] == 5 and s["edge_ratio"] is not None and "<30" in s["sample_note"]
    assert ps.excursion_stats([])["n_closed"] == 0


def test_gate_log_summary():
    rows = [{"decision": "block", "enforced": 0, "symbol": "XAUUSD", "reasons": [{"code": "heat"}, {"code": "cost_r"}], "mult": 1},
            {"decision": "block", "enforced": 1, "symbol": "XAUUSD", "reasons": [{"code": "heat"}], "mult": 1},
            {"decision": "allow", "enforced": 0, "symbol": "EURUSD", "reasons": [], "mult": 0.5}]
    s = summarize_gate_log(rows)
    assert (s["would_block"], s["blocked_enforced"], s["size_reduced"]) == (2, 1, 1)
    assert s["by_reason"] == {"heat": 2, "cost_r": 1} and s["by_symbol"] == {"XAUUSD": 2}


# ----------------------------------------------------------------------------- tez-geçersizleşme (1.5)

def _bars(closes, hi=0.5):
    return [{"time": i, "open": c, "high": c + hi, "low": c - hi, "close": c} for i, c in enumerate(closes)]


def test_structure_broken_both_directions():
    up = _bars([100 + i * 0.1 for i in range(30)])
    assert not ps.structure_broken(up, "BUY") and not ps.structure_broken(up, "SELL")
    crash = up + _bars([90.0])                                       # son kapanış önceki 20 mumun en düşüğünün çok altında
    assert ps.structure_broken(crash, "BUY") and not ps.structure_broken(crash, "SELL")
    spike = up + _bars([120.0])
    assert ps.structure_broken(spike, "SELL") and not ps.structure_broken(spike, "BUY")
    assert not ps.structure_broken(_bars([1, 2, 3]), "BUY")          # yetersiz veri


def test_invalidation_findings_rules():
    P = position()
    clean = {"atr_ratio": 1.0, "htf_break": False, "usd_bias": "USD_SHORT", "dxy_regime": "USD_WEAK", "minutes_open": 20, "progress": 0.6}
    assert ps.invalidation_findings(P, clean, CFG) == []
    bad = {"atr_ratio": 2.4, "htf_break": True, "usd_bias": "USD_SHORT", "dxy_regime": "USD_STRONG", "minutes_open": 90, "progress": 0.1}
    kinds = {f["kind"] for f in ps.invalidation_findings(P, bad, CFG)}
    assert kinds == {"invalidation:atr_spike", "invalidation:yapi_kirilimi", "invalidation:dxy_ters", "invalidation:ilerleme_yok"}
    assert all(f["action"] == "flag" for f in ps.invalidation_findings(P, bad, CFG))                      # yalnız işaret, eylem yok
    assert ps.invalidation_findings(P, {**clean, "usd_bias": "USD_LONG", "dxy_regime": "USD_WEAK"}, CFG)[0]["kind"] == "invalidation:dxy_ters"
    assert not ps.invalidation_findings(P, {**clean, "usd_bias": "USD_NEUTRAL", "dxy_regime": "USD_WEAK"}, CFG)
    assert not ps.invalidation_findings(P, {**clean, "minutes_open": 90, "progress": 0.5}, CFG)            # ilerleme var
    assert ps.invalidation_findings(P, {**clean, "minutes_open": 90, "progress": -0.5}, CFG)[0]["kind"] == "invalidation:ilerleme_yok"


# ----------------------------------------------------------------------------- AI Pozisyon Doktoru (tighten_sl, start_trailing, partial_close, apply)

def test_validate_and_build_tighten_sl():
    p = position(entry_price=4000.0, current_price=4004.0, sl_price=3990.0, tp_price=4020.0)
    # 50% of (4004 - 3990) = 7 → 3997.0
    v = ps.validate_action(p, {"action": "tighten_sl", "pct": 50})
    assert v["ok"] and v["action"] == "tighten_sl" and v["sl"] == 3997.0 and v["pct"] == 50
    # clamping: pct 99 → 70, pct 5 → 25, invalid → 50
    assert ps.validate_action(p, {"action": "tighten_sl", "pct": 99})["pct"] == 70
    assert ps.validate_action(p, {"action": "tighten_sl", "pct": 5})["pct"] == 25
    assert ps.validate_action(p, {"action": "tighten_sl", "pct": "bad"})["pct"] == 50
    # SELL
    sell = position(direction="SELL", entry_price=4000.0, current_price=3996.0, sl_price=4010.0)
    vs = ps.validate_action(sell, {"action": "tighten_sl", "pct": 50})
    assert vs["ok"] and vs["sl"] == 4003.0
    # missing SL rejected
    assert not ps.validate_action(position(sl_price=0), {"action": "tighten_sl", "pct": 50})["ok"]
    # command preserves TP
    cmd = ps.build_command(p, "tighten_sl", {"pct": 50})
    assert cmd["action"] == "MODIFY_SLTP" and cmd["sl"] == 3997.0 and cmd["tp"] == 4020.0 and "tp_action" not in cmd


def test_validate_and_build_start_trailing():
    p = position(entry_price=4000.0, current_price=4004.0, sl_price=3990.0, tp_price=4020.0)
    v = ps.validate_action(p, {"action": "start_trailing"})
    assert v["ok"] and v["action"] == "start_trailing" and v["cancel_tp"] is True
    assert 4000.0 < v["sl"] < 4004.0
    cmd = ps.build_command(p, "start_trailing")
    assert cmd["action"] == "MODIFY_SLTP" and cmd["sl"] == v["sl"] and cmd["tp"] == 0.0 and cmd["tp_action"] == "cancel"
    # losing position cannot start trailing
    assert not ps.validate_action(position(current_price=3995.0), {"action": "start_trailing"})["ok"]
    # SELL in profit
    sell = position(direction="SELL", entry_price=4000.0, current_price=3995.0, sl_price=4010.0)
    vs = ps.validate_action(sell, {"action": "start_trailing"})
    assert vs["ok"] and 3995.0 < vs["sl"] < 4000.0


def test_build_command_partial_close():
    p = position(lots=0.10)
    cmd = ps.build_command(p, "partial_close", {"pct": 50})
    assert cmd["action"] == "CLOSE_PARTIAL" and cmd["ticket"] == 7 and cmd["volume"] == 0.05
    # min lot guard: 0.01 lot * 50% = 0.005 → rounds to 0.01 == lots (not < lots) → None
    assert ps.build_command(position(lots=0.01), "partial_close", {"pct": 50}) is None
    # invalid pct → None
    assert ps.build_command(p, "partial_close", {"pct": 70}) is None


def test_get_supervisor_status():
    class S:
        position_supervisor_mode = "act"
        position_supervisor_llm_enabled = True
        position_supervisor_llm_cooldown_min = 20

    st = ps.get_supervisor_status(S())
    assert st["mode"] == "act" and st["llm_enabled"] is True and st["cooldown_min"] == 20
    assert "last_run_ts" in st and "last_llm_ts" in st and "recent_actions" in st and "open_findings" in st


def test_review_positions_apply_and_panic_close_guard(monkeypatch):
    import asyncio
    from app import database, llm_analysis
    from app import forex_news
    from app.routers import forex as fx

    p = position(ticket=42, symbol="XAUUSD", direction="BUY", lots=0.10, entry_price=4000.0, current_price=4004.0, sl_price=3990.0, tp_price=4020.0)
    monkeypatch.setitem(fx._MT5_STATE, "open_positions", [p])
    pending = []
    monkeypatch.setitem(fx._MT5_STATE, "pending_commands", pending)

    async def fake_news(force_refresh=False):
        return []

    async def fake_exc(since_ts=0):
        return []

    logged = []

    async def fake_log(ev):
        logged.append(ev)

    async def fake_stream(ctx, msgs, **kw):
        yield {"event": "delta", "data": {"text": '{"ticket": 42, "action": "tighten_sl", "pct": 50, "reason": "yapı zayıfladı"}'}}

    monkeypatch.setattr(forex_news, "get_forex_news", fake_news)
    monkeypatch.setattr(database, "list_position_excursions", fake_exc)
    monkeypatch.setattr(database, "log_supervisor_event", fake_log)
    monkeypatch.setattr(llm_analysis, "stream_chat", fake_stream)
    monkeypatch.setattr(fx, "_log_auto_decision", lambda *a, **kw: None)

    class S:
        position_supervisor_mode = "act"
        position_supervisor_llm_enabled = True
        position_supervisor_llm_cooldown_min = 15

    res = asyncio.run(ps.review_positions(S(), timeout=10.0, tickets=[42], extra_findings_by_ticket={42: [{"kind": "invalidation:dxy_ters", "detail": "DXY ters"}]}, apply=True))
    assert res["applied_count"] == 1
    assert len(pending) == 1 and pending[0]["action"] == "MODIFY_SLTP" and pending[0]["sl"] == 3997.0

    # Panic-close guard: close with 0 extra findings & 0 assess close findings → downgraded to tighten_sl (50%)
    pending.clear()

    async def fake_stream_close(ctx, msgs, **kw):
        yield {"event": "delta", "data": {"text": '{"ticket": 42, "action": "close", "pct": null, "reason": "panik"}'}}

    monkeypatch.setattr(llm_analysis, "stream_chat", fake_stream_close)
    res2 = asyncio.run(ps.review_positions(S(), timeout=10.0, tickets=[42], extra_findings_by_ticket={42: []}, apply=True))
    assert res2["applied_count"] == 1
    assert pending[0]["action"] == "MODIFY_SLTP" and pending[0]["sl"] == 3997.0
    ps._APPLIED_ACTIONS_BY_TICKET.clear()


def test_apply_proposals_and_duplicate_rejection(monkeypatch):
    import asyncio
    from app import database
    from app.routers import forex as fx

    ps._APPLIED_ACTIONS_BY_TICKET.clear()
    p1 = position(ticket=101, symbol="XAUUSD", direction="BUY", lots=0.10, entry_price=4000.0, current_price=4006.0, sl_price=3990.0, tp_price=4020.0)
    p2 = position(ticket=102, symbol="EURUSD", direction="BUY", lots=0.10, entry_price=1.1000, current_price=1.1050, sl_price=1.0950, tp_price=1.1150)
    monkeypatch.setitem(fx._MT5_STATE, "open_positions", [p1, p2])
    pending = []
    monkeypatch.setitem(fx._MT5_STATE, "pending_commands", pending)

    logged = []

    async def fake_log(ev):
        logged.append(ev)

    monkeypatch.setattr(database, "log_supervisor_event", fake_log)
    monkeypatch.setattr(fx, "_log_auto_decision", lambda *a, **kw: None)

    class S:
        position_supervisor_mode = "act"
        position_supervisor_llm_enabled = True
        position_supervisor_llm_cooldown_min = 15

    res = asyncio.run(
        ps.apply_proposals(
            [
                {"ticket": 101, "action": "move_sl_to_breakeven", "reason": "kârı koru"},
                {"ticket": 102, "action": "partial_close", "pct": 50, "reason": "yarı kâr al"},
                {"ticket": 102, "action": "hold", "reason": "bekle"},
                {"ticket": 999, "action": "close", "reason": "yok"},
            ],
            S(),
        )
    )
    assert res["ok"] is True
    assert res["applied_count"] == 2
    assert res["skipped_count"] == 2
    assert len(pending) == 2
    assert pending[0]["action"] == "MODIFY_SLTP" and pending[0]["ticket"] == 101 and pending[0]["sl"] == 4000.0
    assert pending[1]["action"] == "CLOSE_PARTIAL" and pending[1]["ticket"] == 102 and pending[1]["volume"] == 0.05
    assert len(logged) == 2 and all(ev["kind"] == "llm_applied" and ev["mode"] == "act" for ev in logged)

    # Clear pending queue (simulating EA consumed commands) and attempt duplicate re-apply
    pending.clear()
    dup = asyncio.run(
        ps.apply_proposals(
            [
                {"ticket": 101, "action": "move_sl_to_breakeven", "reason": "tekrar"},
                {"ticket": 102, "action": "partial_close", "pct": 50, "reason": "tekrar"},
            ],
            S(),
        )
    )
    assert dup["applied_count"] == 0
    assert dup["skipped_count"] == 2
    assert all("daha önce uygulandı" in s["reason"] for s in dup["skipped"])
    assert len(pending) == 0

    # Status exposes applied_by_ticket + open_positions + open_positions_count
    st = ps.get_supervisor_status(S())
    assert "101" in st["applied_by_ticket"] and "102" in st["applied_by_ticket"]
    assert st["open_positions_count"] == 2 and len(st["open_positions"]) == 2
    ps._APPLIED_ACTIONS_BY_TICKET.clear()


def test_review_positions_dedups_already_applied_action(monkeypatch):
    import asyncio
    from app import database, forex_news, llm_analysis
    from app.routers import forex as fx

    ps._APPLIED_ACTIONS_BY_TICKET.clear()
    p = position(ticket=201, symbol="XAUUSD", direction="BUY", lots=0.10, entry_price=4000.0, current_price=4006.0, sl_price=3990.0, tp_price=4020.0)
    monkeypatch.setitem(fx._MT5_STATE, "open_positions", [p])
    pending = []
    monkeypatch.setitem(fx._MT5_STATE, "pending_commands", pending)

    async def fake_news(force_refresh=False):
        return []

    async def fake_exc(since_ts=0):
        return []

    async def fake_log(ev):
        return None

    captured_ctx = []

    async def fake_stream(ctx, msgs, **kw):
        captured_ctx.append(ctx)
        yield {"event": "delta", "data": {"text": '{"ticket": 201, "action": "move_sl_to_breakeven", "pct": null, "reason": "başabaşa çek"}'}}

    monkeypatch.setattr(forex_news, "get_forex_news", fake_news)
    monkeypatch.setattr(database, "list_position_excursions", fake_exc)
    monkeypatch.setattr(database, "log_supervisor_event", fake_log)
    monkeypatch.setattr(llm_analysis, "stream_chat", fake_stream)
    monkeypatch.setattr(fx, "_log_auto_decision", lambda *a, **kw: None)

    class S:
        position_supervisor_mode = "act"
        position_supervisor_llm_enabled = True
        position_supervisor_llm_cooldown_min = 15

    # 1st review with apply=True applies move_sl_to_breakeven and records it
    r1 = asyncio.run(ps.review_positions(S(), timeout=10.0, apply=True))
    assert r1["applied_count"] == 1
    assert len(pending) == 1
    assert captured_ctx[0]["pozisyonlar"][0]["daha_once_uygulananlar"] == []

    # 2nd review after queue drains: LLM sees daha_once_uygulananlar and even if it repeats, backend downgrades to hold
    pending.clear()
    r2 = asyncio.run(ps.review_positions(S(), timeout=10.0, apply=True))
    assert captured_ctx[1]["pozisyonlar"][0]["daha_once_uygulananlar"] == ["move_sl_to_breakeven"]
    assert r2["applied_count"] == 0
    assert len(pending) == 0
    assert len(r2["proposals"]) == 1
    prop2 = r2["proposals"][0]
    assert prop2["action"] == "hold"
    assert prop2["already_applied"] is True
    assert prop2["applied"] is True
    assert prop2["original_action"] == "move_sl_to_breakeven"
    assert "daha önce uygulandı" in prop2["reason"]

    # tighten_sl respects 1800s cooldown; hold/no_op are never blocked
    ps._record_applied_action(201, "tighten_sl", sl=3997.0, pct=50, cmd_action="MODIFY_SLTP", ts=1000.0)
    assert ps.is_action_already_applied(201, "tighten_sl", now=2000.0) is True
    assert ps.is_action_already_applied(201, "tighten_sl", now=2801.0) is False
    assert ps.is_action_already_applied(201, "hold", now=2000.0) is False
    ps._prune_applied_actions(set())
    assert ps._APPLIED_ACTIONS_BY_TICKET == {}


def test_summarize_supervisor_log():
    from app.routers.portfolio_risk import summarize_supervisor_log

    rows = [
        {"symbol": "XAUUSD", "kind": "llm_proposal", "action": "hold", "mode": "proposal_only"},
        {"symbol": "XAUUSD", "kind": "llm_applied", "action": "komut:MODIFY_SLTP", "mode": "act"},
        {"symbol": "EURUSD", "kind": "llm_proposal", "action": "komut:CLOSE_PARTIAL", "mode": "act"},
    ]
    s = summarize_supervisor_log(rows)
    assert s["total"] == 3
    assert s["applied_count"] == 2
    assert s["proposal_count"] == 2
    assert s["by_symbol"] == {"XAUUSD": 2, "EURUSD": 1}
    assert s["by_action"]["komut:MODIFY_SLTP"] == 1
