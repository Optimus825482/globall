"""Portföy risk katmanı: maruziyet, ısı, drawdown merdiveni, maliyet-R ve kapı kararları (saf fonksiyonlar)."""
import time
from datetime import datetime, timezone

import pytest

from app import portfolio_risk as pr

PRICES = {"EURUSD": 1.10, "GBPUSD": 1.30, "USDJPY": 150.0, "XAUUSD": 4000.0, "BTCUSD": 80000.0}


def specs(sym):
    sym = sym.upper()
    if sym.startswith("XAU"):
        return {"pip_size": 0.1, "pip_val": 10.0}
    if sym.endswith("JPY"):
        return {"pip_size": 0.01, "pip_val": 6.6}
    return {"pip_size": 0.0001, "pip_val": 10.0}


def pos(sym="EURUSD", direction="BUY", lots=0.1, entry=1.10, sl=1.0950, pnl=0.0, ticket=1):
    return {"ticket": ticket, "symbol": sym, "direction": direction, "lots": lots, "entry_price": entry, "sl_price": sl, "pnl_usd": pnl}


# ----------------------------------------------------------------------------- maruziyet

def test_legs_and_contract_sizes():
    assert pr.legs_of("EURJPY") == ("EUR", "JPY") and pr.legs_of("XAUUSD") == ("XAU", "USD") and pr.legs_of("BTCUSD") == ("BTC", "USD")
    assert pr.contract_size("EURUSD") == 100000 and pr.contract_size("XAUUSD") == 100 and pr.contract_size("BTCUSD") == 1


def test_usd_conversion_direct_and_inverse():
    assert pr.usd_per_unit("USD", PRICES) == 1.0 and pr.usd_per_unit("EUR", PRICES) == 1.10
    assert pr.usd_per_unit("JPY", PRICES) == pytest.approx(1 / 150.0)
    assert pr.usd_per_unit("NZD", PRICES) is None


def test_exposure_matrix_nets_legs_across_pairs():
    positions = [pos("EURUSD", "BUY", 0.1), pos("GBPUSD", "BUY", 0.1, ticket=2), pos("XAUUSD", "BUY", 0.1, ticket=3)]
    m = pr.exposure_matrix(positions, PRICES)
    # USD kısa: EURUSD (11000) + GBPUSD (13000) + XAUUSD (0.1*100*4000=40000) satıcı bacağı
    assert m["legs"]["USD"] == pytest.approx(-(11000 + 13000 + 40000))
    assert m["legs"]["EUR"] == pytest.approx(11000) and m["usd_net"] < 0
    sell = pr.exposure_matrix([pos("EURUSD", "SELL", 0.1)], PRICES)
    assert sell["legs"]["EUR"] < 0 < sell["legs"]["USD"]


def test_exposure_reports_missing_prices():
    m = pr.exposure_matrix([pos("AUDUSD", "BUY")], PRICES)
    assert m["missing_prices"] == ["AUDUSD"] and m["legs"] == {}


# ----------------------------------------------------------------------------- ısı

def test_position_risk_and_locked_profit_and_missing_sl():
    risk, no_sl = pr.position_risk_usd(pos(lots=0.1, entry=1.10, sl=1.0950), 0.0001, 10.0)
    assert not no_sl and risk == pytest.approx(50 * 10 * 0.1)                 # 50 pip × $10 × 0.1 lot
    locked, _ = pr.position_risk_usd(pos(entry=1.10, sl=1.1020), 0.0001, 10.0)
    assert locked == 0.0                                                      # stop kâr tarafında
    assert pr.position_risk_usd(pos(sl=0), 0.0001, 10.0)[1] is True


def test_heat_totals_usd_net_and_unlimited_flag():
    positions = [pos("EURUSD", "BUY", 0.1), pos("GBPUSD", "BUY", 0.1, entry=1.30, sl=1.2950, ticket=2), pos("USDJPY", "BUY", 0.1, entry=150, sl=149.5, ticket=3),
                 pos("XAUUSD", "SELL", 0.1, entry=4000, sl=0, ticket=4)]
    h = pr.portfolio_heat(positions, 10000.0, specs)
    assert h["heat_usd"] == pytest.approx(50 + 50 + 50 * 6.6 * 0.1)           # SL'siz altın dahil değil
    assert h["no_sl_tickets"] == [4]
    assert h["usd_net_risk_usd"] == pytest.approx(-50 - 50 + 33)              # EUR/GBP long = USD kısa(-), USDJPY long = USD uzun(+)
    assert h["by_currency"]["USD"] == pytest.approx(h["heat_usd"])


# ----------------------------------------------------------------------------- drawdown

def test_drawdown_ladder_and_limits():
    ok = pr.drawdown_state(10000, 10000, 10000, 10000)
    assert ok["level"] == 0 and ok["mult"] == 1.0 and not ok["kill"]
    assert pr.drawdown_state(9650, 10000, 10000, 10000)["mult"] == 0.75        # %3.5
    assert pr.drawdown_state(9450, 10000, 10000, 10000)["mult"] == 0.5         # %5.5
    assert pr.drawdown_state(9100, 10000, 10000, 10000)["mult"] == 0.25        # %9
    k = pr.drawdown_state(8700, 10000, 10000, 10000)
    assert k["kill"] and k["mult"] == 0.0
    d = pr.drawdown_state(9650, 10000, 10000, 10000, daily_limit_pct=3.0)
    assert d["daily_breach"] and not d["weekly_breach"]


def test_drawdown_hysteresis_keeps_level_until_one_point_below():
    assert pr.drawdown_state(9650, 10000, 10000, 10000, prev_level=0)["level"] == 1       # %3.5 ≥ 3
    assert pr.drawdown_state(9750, 10000, 10000, 10000, prev_level=1)["level"] == 1       # %2.5: histerezis (eşik-1=2)
    assert pr.drawdown_state(9810, 10000, 10000, 10000, prev_level=1)["level"] == 0       # %1.9 < 2 → iner


def test_risk_state_rolls_day_week_and_rolling_peak():
    st = pr.RiskState()
    t0 = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc).timestamp()            # Pazartesi
    assert st.update(10000, t0) and st.day_start == 10000 and st.week_start == 10000 and st.peak == 10000
    st.update(10400, t0 + 3600)
    st.update(10100, t0 + 7200)
    assert st.peak == 10400 and st.day_start == 10000                              # gün başı sabit
    st.update(10050, t0 + 86400)                                                   # Salı
    assert st.day_start == 10050 and st.week_start == 10000
    st.update(9900, t0 + 8 * 86400)                                                # sonraki hafta
    assert st.week_start == 9900
    st.update(9800, t0 + 40 * 86400)                                               # 30 günlük pencere dışına çıkan tepe düşer
    assert st.peak == 9800
    st2 = pr.RiskState()
    st2.load(st.to_json())
    assert st2.peak == st.peak and st2.week_key == st.week_key and st2.loaded


# ----------------------------------------------------------------------------- spread

def test_spread_percentile_needs_samples():
    pr._SPREADS.clear()
    now = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc).timestamp()
    for i in range(10):
        pr.record_spread("XAUUSD", 2.0, now)
    assert pr.spread_percentile("XAUUSD", 9) is None
    for i in range(40):
        pr.record_spread("XAUUSD", 1.0 + i * 0.05, now)
    assert pr.spread_percentile("XAUUSD", 9) == pytest.approx(2.0, abs=0.1) or pr.spread_percentile("XAUUSD", 9) >= 2.0
    pr._SPREADS.clear()


# ----------------------------------------------------------------------------- giriş kapısı

CFG = {"heat_limit_pct": 6.0, "usd_net_limit_pct": 3.0, "daily_loss_pct": 3.0, "weekly_loss_pct": 6.0, "kill_dd_pct": 12.0,
       "cost_r_max": 0.25, "stop_spread_mult": 8.0, "block_losing_adds": True, "kill_switch": False}


def state(equity=10000.0):
    st = pr.RiskState()
    st.update(equity, time.time())
    return st


def gate(ctx=None, cfg=None, positions=None, equity=10000.0, st=None):
    base = {"symbol": "EURUSD", "direction": "BUY", "lots": 0.1, "sl_pips": 30.0, "spread_pips": 0.8, "pip_size": 0.0001, "pip_val": 10.0}
    return pr.evaluate_entry({**base, **(ctx or {})}, {**CFG, **(cfg or {})}, {"equity": equity, "balance": equity},
                             positions or [], PRICES, specs, st or state(equity))


def codes(res):
    return {r["code"] for r in res["reasons"]}


def test_clean_entry_is_allowed():
    r = gate()
    assert r["decision"] == "allow" and r["mult"] == 1.0 and r["metrics"]["cost_r"] == pytest.approx(0.027, abs=0.001)


def test_kill_switch_and_daily_loss_block():
    assert "kill_switch" in codes(gate(cfg={"kill_switch": True}))
    st = state(10000)
    st.day_start = 10500                                                      # günü 10500'de başladı, şimdi 10000 → -%4.8
    assert "daily_loss" in codes(gate(st=st))


def test_heat_limit_counts_new_trade():
    positions = [pos("GBPUSD", "SELL", 0.5, entry=1.30, sl=1.3100, ticket=2)]       # 100 pip × 10 × 0.5 = $500 (%5)
    r = gate(positions=positions)                                                   # yeni: 30 pip × 10 × 0.1 = $30 → %5.3 (<6)
    assert "heat" not in codes(r)
    r2 = gate({"lots": 0.5, "sl_pips": 30.0}, positions=positions)                  # yeni $150 → %6.5
    assert "heat" in codes(r2) and r2["metrics"]["heat_after_pct"] > 6.0


def test_usd_net_risk_limit():
    positions = [pos("GBPUSD", "BUY", 0.3, entry=1.30, sl=1.2950, ticket=2)]        # USD kısa riski $150 (%1.5)
    r = gate({"lots": 0.5, "sl_pips": 30.0}, positions=positions)                   # +$150 → %3.0 sınırda
    assert "usd_net" not in codes(r)
    assert "usd_net" in codes(gate({"lots": 0.8, "sl_pips": 30.0}, positions=positions))
    # ters yön (USD uzun) net riski azaltır
    assert "usd_net" not in codes(gate({"direction": "SELL", "lots": 0.8, "sl_pips": 30.0}, positions=positions))


def test_cost_r_and_stop_spread_and_percentile():
    assert "cost_r" in codes(gate({"sl_pips": 5.0, "spread_pips": 1.5}))             # 0.3R
    assert "stop_vs_spread" in codes(gate({"sl_pips": 10.0, "spread_pips": 2.0}))    # 10 < 8×2
    pr._SPREADS.clear()
    now = time.time()
    hour = datetime.fromtimestamp(now, timezone.utc).hour
    for _ in range(40):
        pr._SPREADS[("EURUSD", hour)].append(0.6)
    assert "spread_pctl" in codes(pr.evaluate_entry(
        {"symbol": "EURUSD", "direction": "BUY", "lots": 0.1, "sl_pips": 30.0, "spread_pips": 1.5, "pip_val": 10.0},
        CFG, {"equity": 10000}, [], PRICES, specs, state(), now=now))
    pr._SPREADS.clear()
    assert "comm" == "comm" and "cost_r" in codes(gate({"sl_pips": 30.0, "spread_pips": 0.8, "comm_per_lot": 700.0}))   # komisyon 70p → 2.4R


def test_losing_add_ban_but_winners_may_pyramid():
    assert "losing_add" in codes(gate(positions=[pos("EURUSD", "BUY", pnl=-12.0)]))
    assert "losing_add" not in codes(gate(positions=[pos("EURUSD", "BUY", pnl=+12.0)]))
    assert "losing_add" not in codes(gate(positions=[pos("EURUSD", "SELL", pnl=-12.0)]))      # karşı yön ekleme değil
    assert "losing_add" not in codes(gate(cfg={"block_losing_adds": False}, positions=[pos("EURUSD", "BUY", pnl=-12.0)]))


def test_positions_without_sl_flag():
    assert "no_sl" in codes(gate(positions=[pos("XAUUSD", "BUY", sl=0, ticket=9)]))


def test_drawdown_multiplier_applies_and_lot_floor():
    st = state(10000)
    st.daily_max = {datetime.now(timezone.utc).strftime("%Y-%m-%d"): 10000.0}
    r = gate(equity=9400, st=st)                                                     # %6 → ×0.5
    assert r["mult"] == 0.5 and r["metrics"]["lots_after_mult"] == pytest.approx(0.05)
    tiny = gate({"lots": 0.01}, equity=9400, st=st)
    assert "lot_floor" in codes(tiny)


def test_adjust_lots_rounds_down_to_step():
    assert pr.adjust_lots(0.10, 0.75) == 0.07 and pr.adjust_lots(0.03, 0.5) == 0.01 and pr.adjust_lots(0.01, 0.5) == 0.0
    assert pr.adjust_lots(100.0, 0.5) == 50.0


def test_settings_cfg_defaults_are_shadow():
    class S:
        pass
    cfg = pr.settings_cfg(S())
    assert cfg["mode"] == "shadow" and cfg["kill_switch"] is False and cfg["heat_limit_pct"] == 6.0


# ----------------------------------------------------------------------------- stres (3.5)

def _p(sym, direction, lots, price, ticket=1):
    return {"ticket": ticket, "symbol": sym, "direction": direction, "lots": lots, "entry_price": price, "current_price": price, "sl_price": 0}


def test_shock_directions():
    assert pr.shock_pct("XAUUSD", "altin_-5") == -5 and pr.shock_pct("EURUSD", "altin_-5") == 0
    assert pr.shock_pct("EURUSD", "usd_+2") == -2 and pr.shock_pct("USDJPY", "usd_+2") == 2 and pr.shock_pct("EURJPY", "usd_+2") == 0
    assert pr.shock_pct("BTCUSD", "btc_-15") == -15
    assert pr.shock_pct("USDJPY", "risk_off") == -3.0          # JPY güçlenir → USDJPY düşer
    assert pr.shock_pct("EURJPY", "risk_off") == -3.0
    assert pr.shock_pct("AUDJPY", "risk_off") == -5.0           # AUD −2, JPY +3


def test_stress_test_losses_and_margin():
    positions = [_p("XAUUSD", "BUY", 0.1, 4000.0), _p("EURUSD", "BUY", 0.1, 1.10, 2), _p("BTCUSD", "BUY", 0.1, 80000.0, 3)]
    out = pr.stress_test(positions, 1000.0, 200.0, specs)
    gold = out["altin_-5"]
    assert gold["pnl_usd"] == pytest.approx(-0.05 * 4000 / 0.1 * 10 * 0.1)           # −$2000 (0.1 lot altın × 200$ düşüş)
    assert gold["breach"] and gold["worst_position"].startswith("XAUUSD")
    assert out["usd_+2"]["pnl_usd"] < 0 and out["btc_-15"]["pnl_usd"] < 0
    assert gold["margin_level_after_pct"] == pytest.approx((1000 + gold["pnl_usd"]) / 200 * 100)     # özsermaye eksiye iner
    gap = out["hafta_sonu_bosluk"]
    assert gap["pnl_usd"] < 0 and "BTCUSD" not in str(gap["worst_position"])          # kripto hafta sonu işlem görür: boşluk yok
    assert pr.stress_test([], 1000.0, 0.0, specs)["altin_-5"]["pnl_usd"] == 0
    safe = pr.stress_test([_p("EURUSD", "SELL", 0.01, 1.10)], 10000.0, 100.0, specs)["usd_+2"]
    assert safe["pnl_usd"] > 0 and not safe["breach"]                                  # USD yükselişi EURUSD short'a kâr


# ----------------------------------------------------------------------------- Monte Carlo (3.6)

def test_monte_carlo_requires_enough_trades_and_is_deterministic():
    assert not pr.monte_carlo_drawdown([1.0] * 30)["ok"]
    rs = [1.5, -1.0, -1.0, 1.5, -1.0, 2.0, -1.0, -1.0, -1.0, 1.0] * 8                   # 80 işlem
    a, b = pr.monte_carlo_drawdown(rs, risk_pct=1.0), pr.monte_carlo_drawdown(rs, risk_pct=1.0)
    assert a == b and a["ok"] and a["dd_p50"] <= a["dd_p90"] <= a["dd_p95"] <= a["dd_p99"]
    higher = pr.monte_carlo_drawdown(rs, risk_pct=3.0)
    assert higher["dd_p95"] > a["dd_p95"] and higher["p_dd_over_limit"] >= a["p_dd_over_limit"]


def test_monte_carlo_all_winners_has_no_drawdown():
    r = pr.monte_carlo_drawdown([1.0] * 60, risk_pct=1.0)
    assert r["dd_p99"] == 0.0 and r["p_dd_over_limit"] == 0.0


# ----------------------------------------------------------------------------- boyut (3.4)

def test_shrunk_win_rate_and_kelly():
    assert pr.shrunk_win_rate_lower(0, 0) < 0.5                                         # önsel 0.5, alt sınır daha düşük
    assert pr.shrunk_win_rate_lower(60, 100) < 0.6                                      # büzülme + alt sınır
    assert pr.shrunk_win_rate_lower(60, 100) > pr.shrunk_win_rate_lower(6, 10)          # daha çok veri → daha yüksek alt sınır
    assert pr.kelly_cap_pct(0.40, 1.5, 0.25, 200) == 0.0                                # p·b − q < 0 → kenar yok
    big = pr.kelly_cap_pct(0.60, 2.0, 0.25, 200)
    small_n = pr.kelly_cap_pct(0.60, 2.0, 0.25, 20)
    assert big > small_n > 0                                                            # az örneklemde kesir 0.15'e iner


def test_sizing_binding_constraint_and_rounding():
    s = pr.sizing_suggestion("EURUSD", 30.0, 10.0, 10000.0, 1.0, 1000.0, base_risk_pct=0.5)
    assert s["binding"] == "temel_risk" and s["lots"] == 0.16 and s["risk_usd"] == pytest.approx(48.0)      # 50$/(30*10)=0.166 → 0.16
    low = pr.sizing_suggestion("EURUSD", 30.0, 10.0, 10000.0, 0.5, 1000.0)
    assert low["lots"] == 0.08                                                          # drawdown ×0.5
    budget = pr.sizing_suggestion("EURUSD", 30.0, 10.0, 10000.0, 1.0, 15.0)
    assert budget["binding"] == "kalan_isi_butcesi" and budget["lots"] == 0.05
    kelly = pr.sizing_suggestion("EURUSD", 30.0, 10.0, 10000.0, 1.0, 1000.0, edge={"wins": 10, "n": 20, "rr": 1.3})
    assert kelly["binding"] == "kesirli_kelly" and kelly["lots"] < s["lots"] and kelly["win_rate_lower"] < 0.5


def test_sizing_rejects_when_min_lot_exceeds_limit():
    r = pr.sizing_suggestion("XAUUSD", 100.0, 10.0, 500.0, 1.0, 1000.0, base_risk_pct=0.25)       # sınır $1.25, min lot riski $10
    assert r["lots"] == 0.0 and "%20" in r["reason"]
    assert pr.sizing_suggestion("EURUSD", 0.0, 10.0, 1000.0, 1.0, 100.0)["lots"] == 0.0
