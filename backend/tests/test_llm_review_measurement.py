"""LLM onay katmanı ölçümü: kontrollü keşif, rastgele-veto kontrolü, Brier/AUC kalibrasyonu, fail-open metrikleri."""
import asyncio
import json

import pytest

from app import llm_trade_review as ltr
from app.routers import llm_review as lr


# ----------------------------------------------------------------------------- kontrollü keşif

def test_exploration_passes_only_blocked_vetoes_and_respects_probability():
    blocked = {"blocked": True, "applied": "blocked", "reason": "Haber yakın"}
    p, ex = ltr.apply_exploration(blocked, 10.0, 0.05)              # %10 olasılık, çekilen 0.05 → keşif
    assert ex and not p["blocked"] and p["applied"] == "explore_pass" and "Kontrollü keşif" in p["reason"]
    p2, ex2 = ltr.apply_exploration(blocked, 10.0, 0.5)             # çekilen yüksek → veto kalır
    assert not ex2 and p2 is blocked
    assert not ltr.apply_exploration(blocked, 0.0, 0.0)[1]          # %0: kapalı
    allowed = {"blocked": False, "applied": "allowed", "reason": ""}
    assert ltr.apply_exploration(allowed, 100.0, 0.0) == (allowed, False)
    fc = {"blocked": True, "applied": "fail_closed", "reason": "LLM yok"}
    assert ltr.apply_exploration(fc, 100.0, 0.0) == (fc, False)     # fail-closed keşif değildir


def test_recent_veto_rate_defaults_then_tracks():
    ltr._recent_vetoes.clear()
    assert ltr.recent_veto_rate() == ltr.DEFAULT_VETO_RATE
    for i in range(20):
        ltr._recent_vetoes.append(1 if i < 5 else 0)
    assert ltr.recent_veto_rate() == pytest.approx(0.25)
    ltr._recent_vetoes.clear()


def _run_review(monkeypatch, verdict, rng_values, explore_pct=50.0):
    from app import database
    flags, saved = [], []

    async def fake_save(rec):
        saved.append(rec)
        return 1

    async def fake_flags(rid, e, c):
        flags.append((rid, e, c))

    async def fake_dossier(ctx):
        return {}

    async def fake_ask(d, t):
        return verdict, "m"

    monkeypatch.setattr(database, "save_llm_review", fake_save)
    monkeypatch.setattr(database, "set_llm_review_flags", fake_flags)
    monkeypatch.setattr(ltr, "build_dossier", fake_dossier)
    monkeypatch.setattr(ltr, "ask_llm", fake_ask)
    ltr._cache.clear()
    ltr._recent_vetoes.clear()
    it = iter(rng_values)
    ctx = {"symbol": "XAUUSD", "direction": "BUY", "cand": {}, "mode": "veto", "fail_open": True, "min_confidence": 55,
           "timeout_sec": 5, "explore_pct": explore_pct, "rng": lambda: next(it)}
    res = asyncio.run(ltr.review_entry(ctx))
    return res, saved, flags


def test_review_entry_explores_vetoed_trade_and_records_flags(monkeypatch):
    reject = {"decision": "REJECT", "confidence": 80, "summary": "x", "reasons": [], "risks": [], "checks": {"mtf_uyum": "olumsuz"}}
    res, saved, flags = _run_review(monkeypatch, reject, [0.01, 0.01])      # keşif çekimi 0.01 (<%50), kontrol çekimi 0.01 (<0.2)
    assert not res["blocked"] and res["applied"] == "explore_pass" and res["exploration"]
    assert saved[0]["decision"] == "REJECT" and saved[0]["applied"] == "explore_pass"
    assert flags == [(1, 1, 1)]


def test_review_entry_keeps_veto_when_not_explored(monkeypatch):
    reject = {"decision": "REJECT", "confidence": 80, "summary": "x", "reasons": [], "risks": [], "checks": {"mtf_uyum": "olumsuz"}}
    res, _saved, flags = _run_review(monkeypatch, reject, [0.9, 0.9])
    assert res["blocked"] and not res["exploration"] and flags == []        # bayrak yok: ne keşif ne kontrol


# ----------------------------------------------------------------------------- kalibrasyon

def row(dec="APPROVE", conf=70, pips=10.0, **kw):
    base = {"decision": dec, "confidence": conf, "shadow_status": "TP" if pips > 0 else "SL", "shadow_pips": pips, "applied": "allowed"}
    base.update(kw)
    return base


def test_auc_perfect_random_and_single_class():
    assert lr.auc_score([(0.9, 1), (0.8, 1), (0.2, 0), (0.1, 0)]) == 1.0
    assert lr.auc_score([(0.5, 1), (0.5, 0)]) == 0.5
    assert lr.auc_score([(0.9, 1), (0.8, 1)]) is None


def test_calibration_informative_model_has_positive_skill():
    rows = []
    for i in range(40):                                     # yüksek güven → kazanç, düşük güven → kayıp
        rows.append(row("APPROVE", 90 if i % 2 == 0 else 55, 10.0 if i % 2 == 0 else -8.0))
    c = lr.calibration_deep(rows)
    assert c["n"] == 40 and c["auc"] == 1.0 and c["brier_skill"] > 0 and c["usable"] and not c["saturated"]


def test_calibration_saturated_confidence_is_flagged_useless():
    rows = [row("APPROVE", 90, 10.0 if i % 3 else -8.0) for i in range(40)]        # hepsi %90: sinyal yok
    c = lr.calibration_deep(rows)
    assert c["saturated"] and not c["usable"] and "işe yaramaz" in c["note"]


def test_calibration_reject_uses_inverse_and_excludes_voided_and_errors():
    rows = [row("REJECT", 80, -10.0) for _ in range(12)] + [row("APPROVE", 60, 5.0, applied="reject_voided")] + [{"decision": "HATA"}]
    c = lr.calibration_deep(rows)
    assert c["n"] == 12 and c["base_rate"] == 0.0                         # red, kaybeden çıktı: p_kazanç = 0.2, y=0
    assert lr.calibration_deep([row() for _ in range(3)])["note"].startswith("Yetersiz")


# ----------------------------------------------------------------------------- veto değeri / kontrol

def test_veto_value_requires_samples_then_compares_to_random_control():
    few = lr.veto_value([row("APPROVE", 70, 5.0), row("REJECT", 70, -5.0)])
    assert "Yetersiz" in few["verdict"]
    rows = []
    for i in range(30):                                     # LLM: reddedilenler kaybeder (−8), geçenler kazanır (+9)
        rows.append(row("REJECT", 70, -8.0 + (i % 3), control_veto=int(i % 2 == 0)))
        rows.append(row("APPROVE", 70, 9.0 - (i % 3), control_veto=int(i % 2 == 1)))
    v = lr.veto_value(rows)
    assert v["llm"]["edge_pips"] >= 14.5 and abs(v["random_control"]["edge_pips"]) < 3
    assert "anlamlı" in v["verdict"]
    noise = [row("REJECT" if i % 2 else "APPROVE", 70, (5.0 if i % 4 < 2 else -5.0), control_veto=i % 2) for i in range(60)]
    assert "kanıtlanmadı" in lr.veto_value(noise)["verdict"]


def test_veto_value_exploration_outcomes():
    rows = [row("REJECT", 70, 6.0, exploration=1, applied="explore_pass"), row("REJECT", 70, -4.0, exploration=1, applied="explore_pass")]
    assert lr.veto_value(rows)["exploration"] == {"n": 2, "mean_pips": 1.0}


# ----------------------------------------------------------------------------- fail-open

def test_fail_stats_rate_alert_and_outcomes():
    rows = [row(applied="fail_open", decision="HATA", pips=-3.0) for _ in range(4)] + [row(pips=5.0) for _ in range(6)]
    f = lr.fail_stats(rows)
    assert f["fail_count"] == 4 and f["fail_rate"] == 0.4 and f["alert"] and f["fail_mean_pips"] == -3.0 and f["normal_mean_pips"] == 5.0
    ok = lr.fail_stats([row(pips=5.0) for _ in range(12)])
    assert not ok["alert"] and ok["fail_count"] == 0
    assert lr.fail_stats([])["fail_rate"] == 0.0


def test_summarize_includes_new_sections():
    s = lr.summarize([row() for _ in range(3)])
    assert {"calibration_deep", "veto_value", "fail_stats"} <= set(s)


def test_summarize_reports_floating_results_for_unfinished_decisions():
    rows = [{"decision": "REJECT", "applied": "blocked", "symbol": "NZDUSD", "shadow_status": "IZLENIYOR", "shadow_pips": -2.1},
            {"decision": "REJECT", "applied": "blocked", "symbol": "NZDUSD", "shadow_status": "IZLENIYOR", "shadow_pips": -3.3},
            {"decision": "REJECT", "applied": "blocked", "symbol": "USDCAD", "shadow_status": "IZLENIYOR", "shadow_pips": 1.0},
            {"decision": "APPROVE", "applied": "allowed", "symbol": "XAUUSD", "shadow_status": "IZLENIYOR", "shadow_pips": 25.0},
            {"decision": "APPROVE", "applied": "reject_voided", "symbol": "XAUUSD", "shadow_status": "IZLENIYOR", "shadow_pips": 9.0},
            {"decision": "REJECT", "applied": "blocked", "symbol": "X", "shadow_status": "IZLENIYOR", "shadow_pips": None}]
    s = lr.summarize(rows)
    assert s["rejected_stats"]["closed"] == 0                                   # hiçbiri stop/hedefe değmedi
    assert s["floating"]["rejected"] == {"n": 3, "winning": 1, "losing": 2, "sum_pips": -4.4}
    assert s["floating"]["approved"] == {"n": 1, "winning": 1, "losing": 0, "sum_pips": 25.0}   # geçersiz red dışlanır
    assert s["tracking"] == 6


def test_latency_stats_percentiles_and_timeouts():
    rows = [{"latency_ms": 1000 * i, "error": None} for i in range(1, 11)] + [{"latency_ms": 25000, "error": "TimeoutError: x"}]
    s = lr.latency_stats(rows)
    assert s["n"] == 11 and s["p50_ms"] == 6000 and s["max_ms"] == 25000 and s["timeouts"] == 1 and s["timeout_rate"] == pytest.approx(1 / 11, abs=0.001)
    assert lr.latency_stats([])["n"] == 0 and "latency" in lr.summarize(rows)


def test_features_csv_flattens_features_and_outcomes(monkeypatch):
    from app import database
    rows = [{"id": 1, "created_at": 1.0, "symbol": "XAUUSD", "direction": "BUY", "strategy_label": "Radar", "score": 80, "decision": "APPROVE",
             "confidence": 70, "applied": "allowed", "exploration": 0, "control_veto": 1, "sl_pips": 8, "tp_pips": 12,
             "shadow_status": "TP", "shadow_pips": 12.0, "mfe_pips": 13, "mae_pips": -2,
             "features": '{"session": "londra", "htf_agree_count": 4, "hard_flags": ["haber_15dk", "spread_atr_yuksek"]}', "path": "[1,2]"},
            {"id": 2, "features": None, "path": None}]

    async def fake(since_ts=0.0, limit=5000):
        return rows

    monkeypatch.setattr(database, "list_llm_review_dataset", fake)
    resp = asyncio.run(lr.llm_review_features_csv(days=30))
    text = resp.body.decode("utf-8")
    head, first = text.lstrip("\ufeff").splitlines()[:2]
    assert "f_session" in head and "f_hard_flags" in head and "shadow_pips" in head
    assert "londra" in first and "haber_15dk|spread_atr_yuksek" in first and ";TP;" in first
    assert resp.headers["content-disposition"].endswith("veri-seti.csv")


def test_exit_ab_endpoint_uses_recorded_paths(monkeypatch):
    from app import database
    rows = [{"path": json.dumps([5, 12, 4, -1, 6, 26]), "sl_pips": 10, "tp_pips": 25}, {"path": None, "sl_pips": 10, "tp_pips": 25}]

    async def fake(since_ts=0.0, limit=5000):
        return rows

    monkeypatch.setattr(database, "list_llm_review_dataset", fake)
    out = asyncio.run(lr.llm_review_exit_ab(days=30))
    assert out["n"] == 1 and out["means_pips"]["baseline"] == 25.0 and not out["decisive"]
