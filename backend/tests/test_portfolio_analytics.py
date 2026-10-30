"""Portföy analitiği: hücre kenarı (Beta-Binomial), strateji tahsisi, ENB, çıkış A/B, confluence özellikleri."""
import json
import random
from datetime import datetime, timezone

import pytest

from app import portfolio_analytics as pa


def ts(h):
    return datetime(2026, 10, 28, h, 0, tzinfo=timezone.utc).timestamp()


def row(strat="RADAR", sym="XAUUSD", pips=10.0, sl=10.0, h=9, closed=1000.0):
    return {"strategy_tag": strat, "symbol": sym, "last_pnl_pips": pips, "sl_pips": sl, "open_ts": ts(h), "closed_at": closed}


# ----------------------------------------------------------------------------- seans + hücre

def test_session_buckets():
    assert [pa.session_of(ts(h)) for h in (3, 9, 15, 22)] == ["asya", "londra", "ny", "gece"]
    assert pa.session_of(None) == "bilinmiyor"


def test_cell_stats_shrinks_hides_small_cells_and_ranks_by_lower_bound():
    rows = [row(pips=10.0) for _ in range(40)] + [row(pips=-10.0) for _ in range(10)]                    # RADAR/XAU/londra: 40/50
    rows += [row("EAP", "EURUSD", pips=10.0, h=15) for _ in range(5)]                                     # küçük hücre (n=5)
    rows += [row("EAP", "GBPUSD", pips=10.0 if i % 2 else -10.0, h=15) for i in range(40)]                 # 50% hücre
    s = pa.cell_stats(rows)
    names = {(c["strategy"], c["symbol"]) for c in s["cells"]}
    assert ("RADAR", "XAUUSD") in names and ("EAP", "GBPUSD") in names and ("EAP", "EURUSD") not in names    # n<30 raporlanmaz
    top = s["cells"][0]
    assert (top["strategy"], top["symbol"]) == ("RADAR", "XAUUSD") and top["p_raw"] == 0.8
    assert top["p_lower"] < top["p_shrunk"] < top["p_raw"]                                                 # büzülme + alt sınır
    assert s["n_cells_total"] == 3 and "sahte keşif" in s["note"]
    assert pa.cell_stats([])["cells"] == []


def test_cell_lookup_matches_session():
    s = pa.cell_stats([row(h=9) for _ in range(35)])
    assert pa.cell_lookup(s, "RADAR", "XAUUSD", ts(10))["n"] == 35
    assert pa.cell_lookup(s, "RADAR", "XAUUSD", ts(15)) is None                                           # farklı seans


# ----------------------------------------------------------------------------- tahsis

def test_allocation_bounds_sample_cap_and_ranking():
    rows = [row("GOOD", pips=10.0 if i % 4 else -10.0, closed=1000.0 + i) for i in range(60)]
    rows += [row("BAD", pips=-10.0 if i % 4 else 10.0, closed=1000.0 + i) for i in range(60)]
    rows += [row("NEW", pips=20.0, closed=2000.0 + i) for i in range(5)]
    out = {s["strategy"]: s for s in pa.strategy_allocation(rows)["strategies"]}
    assert out["GOOD"]["suggested_weight"] > 1.0 and out["BAD"]["suggested_weight"] == 0.5                  # taban: kapatma yok
    assert out["NEW"]["suggested_weight"] <= 1.0 and out["NEW"]["n_eff"] < 30                              # az örneklem: ≤1
    assert all(0.5 <= s["suggested_weight"] <= 1.5 for s in out.values())
    assert pa.strategy_allocation([])["strategies"] == []


# ----------------------------------------------------------------------------- ENB

def _walk(seed, n=120):
    rng = random.Random(seed)
    return [rng.gauss(0, 1) for _ in range(n)]


def test_enb_detects_stacked_same_direction_positions():
    base = _walk(1)
    noise = lambda s: [b + 0.1 * x for b, x in zip(base, _walk(s))]                                         # noqa: E731
    stacked = {"EURUSD": noise(2), "GBPUSD": noise(3), "AUDUSD": noise(4), "NZDUSD": noise(5)}
    r = pa.effective_bets(stacked, {k: 1.0 for k in stacked})
    assert r["enb"] < 2.0 and r["warning"] and len(r["clusters"]) == 1 and len(r["clusters"][0]) == 4
    indep = {f"S{i}": _walk(10 + i) for i in range(4)}
    r2 = pa.effective_bets(indep, {k: 1.0 for k in indep})
    assert r2["enb"] > 3.0 and not r2["warning"] and r2["clusters"] == []


def test_enb_direction_sign_hedges_correlated_pair():
    base = _walk(1)
    two = {"EURUSD": base, "GBPUSD": [b + 0.05 * x for b, x in zip(base, _walk(2))]}
    long_long = pa.effective_bets(two, {"EURUSD": 1.0, "GBPUSD": 1.0})
    long_short = pa.effective_bets(two, {"EURUSD": 1.0, "GBPUSD": -1.0})
    assert long_long["avg_signed_corr"] > 0.9 and long_short["avg_signed_corr"] < -0.9                    # yığılma vs hedge
    assert long_long["clusters"] == [["EURUSD", "GBPUSD"]] and long_short["clusters"] == []
    assert pa.effective_bets({"A": [1.0] * 5}, {})["note"].startswith("En az 2")


# ----------------------------------------------------------------------------- çıkış varyantları

def test_exit_variants_on_known_paths():
    # 1R=10, TP=25. Yol: +12 (1R) sonra geri 0'a düşer, sonra +26'ya çıkar
    path = [5, 12, 4, -1, 6, 26]
    v = pa.simulate_exit_variants(path, 10, 25)
    assert v["baseline"] == 25.0                          # SL'ye değmeden TP
    assert v["be_1r"] == 0.0                              # +1R sonrası stop girişe çekildi: -1'de BE'den çıktı
    assert v["partial_1r"] == pytest.approx(5.0)          # yarı +5 kilitlendi, kalan BE'de 0
    assert v["trail_1r"] == 2.0                           # best 12 → stop 2; 4'ten -1'e düşünce stop 2'den çıkış


def test_exit_variants_stop_loss_and_no_tp_modes():
    assert pa.simulate_exit_variants([-3, -11], 10, 25)["baseline"] == -10.0
    assert pa.simulate_exit_variants([3, 8, 9], 10, 0)["baseline"] == 9                                      # TP yok: son değer
    assert pa.simulate_exit_variants([], 10, 25) == {} and pa.simulate_exit_variants([1], 0, 25) == {}
    # kısmi kâr + TP: 12'de yarı kilit(5), sonra 25 TP → 5 + 12.5
    assert pa.simulate_exit_variants([12, 25], 10, 25)["partial_1r"] == pytest.approx(17.5)


def test_compare_variants_requires_samples_and_reports_differences():
    rows = [{"path": json.dumps([5, 12, 4, -1, 6, 26]), "sl_pips": 10, "tp_pips": 25} for _ in range(3)]
    c = pa.compare_variants(rows)
    assert c["n"] == 3 and not c["decisive"] and c["means_pips"]["baseline"] == 25.0
    assert c["vs_baseline"]["be_1r"] == -25.0 and "yetersiz" in c["note"]
    assert pa.compare_variants(rows * 11)["decisive"]
    assert pa.compare_variants([{"path": "bozuk"}])["n"] == 0


# ----------------------------------------------------------------------------- özellikler

def _analysis(**kw):
    base = {"price": 100.0, "atr": 1.0, "bias": "BUY", "score": 3.0,
            "frames": {"15m": {"score": 2, "atr": 0.5}, "1h": {"score": 3, "atr": 1.0, "ema20": 99.0}, "4h": {"score": 2}, "1d": {"score": 1}},
            "levels": {"resistances": [{"price": 103.0}], "supports": [{"price": 98.0}]}}
    base.update(kw)
    return base


def test_entry_features_clean_setup_has_no_flags():
    f = pa.entry_features("BUY", _analysis(), spread_pips=2.0, pip_size=0.01, news_minutes=None, now=ts(9))
    assert f["htf_agree_count"] == 4 and f["level_clearance_atr"] == 3.0 and f["extension_atr"] == 1.0
    assert f["spread_atr_ratio"] == pytest.approx(0.02) and f["session"] == "londra" and f["hard_flags"] == []


def test_entry_features_flags_traps():
    a = _analysis(frames={"15m": {"score": -2}, "1h": {"score": -3, "atr": 1.0, "ema20": 95.0}, "4h": {"score": -1}, "1d": {"score": -1}},
                  levels={"resistances": [{"price": 100.3}], "supports": []})
    f = pa.entry_features("BUY", a, spread_pips=30.0, pip_size=0.01, news_minutes=10, now=ts(9))
    assert set(f["hard_flags"]) == {"asiri_uzama_3atr", "karsi_seviye_0.5atr", "ust_dilim_uyumsuz", "spread_atr_yuksek", "haber_15dk"}
    s = pa.entry_features("SELL", _analysis(), 2.0, 0.01, None, ts(9))                                      # SELL: karşı seviye = destek
    assert s["level_clearance_atr"] == 2.0
