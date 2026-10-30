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
