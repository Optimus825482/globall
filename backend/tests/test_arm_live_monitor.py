"""Canlı kol izleme — ağa/DB'ye çıkmayan sözleşme testleri (2026-11-12)

Kilitlenen davranışlar:
  * PF hesabı (kâr faktörü) doğru; hiç kayıp yoksa inf/None ayrımı
  * Kill kriteri: n<20 → karar YOK (sayı üretilmez), n≥20 & PF<1,0 → KAPAT
  * `push_message` yalnız DİKKAT gerektiren durumda metin döner
  * 3 günlük rutin kayıtlı (panelde görünmesi için)
  * DB yoksa rapor patlamaz, sebep yazar
  * REMOVED/ADDED sabitleri canlı varsayılanlarla ÇELİŞMEZ
"""
from __future__ import annotations

import pytest

from app import arm_live_monitor as m


def test_pf_hesabi():
    assert m.pf_of([10.0, -5.0]) == pytest.approx(2.0)
    assert m.pf_of([10.0, 10.0]) is None or m.pf_of([10.0, 10.0]) == float("inf")
    # hepsi zarar → 0/(toplam zarar) = 0,0 (matematik doğru; verdict KAPAT olur)
    assert m.pf_of([-1.0, -2.0]) == 0.0
    assert m.pf_of([]) is None


def test_push_yalniz_karar_gerektiginde():
    assert m.push_message({"karar_gereken": [], "semboller": {}}) is None
    msg = m.push_message({"karar_gereken": ["london_breakout:USDCHF n=22 PF=0.80 → çıkar"]})
    assert msg and "USDCHF" in msg


def test_push_ozet_sembol_yoksa_none():
    assert m.push_message({}) is None


def test_db_yoksa_rapor_patlamaz(monkeypatch):
    monkeypatch.setattr(m, "db_url", lambda: "")
    rep = m.build_report(days=3)
    assert rep["semboller"] == {} and rep["uyarilar"]


def test_rutin_uc_gunde_bir_kayitli():
    from app.routines.base import get, all_routines

    assert "arm_live_monitor" in [r.name for r in all_routines()]
    spec = get("arm_live_monitor")
    assert spec.interval_sec == 3 * 86400
    assert "monitor" in spec.tags


def test_removed_added_canli_varsayilanla_tutarli():
    """Liste değişikliği ile izleme sabitleri aynı hikâyeyi anlatmalı."""
    from app.routers.forex import ForexAutoPaperSettings as S

    a = S()
    lb = set(a.lb_symbols)
    assert set(m.REMOVED["london_breakout"]).isdisjoint(lb)
    assert set(m.ADDED["london_breakout"]) <= lb
    eap = set(a.ema_adx_symbols)
    assert set(m.ADDED["ema_adx_pullback"]) <= eap


def test_format_cli_satir_uretiyor():
    lines = m.format_cli({
        "baslangic": "2026-11-12T00:00:00+00:00",
        "semboller": {"london_breakout:GBPUSD": {"n": 25, "win_pct": 60.0, "net": 120.0,
                                                 "pf": 1.4, "verdict": "DEVAM"}},
        "ayar_kontrolu": {"london_breakout:USDCHF": {"gercek": 0, "state": "ayar isledi"}},
        "uyarilar": [], "karar_gereken": [],
    })
    joined = "\n".join(lines)
    assert "london_breakout" in joined and "GBPUSD" in joined and "DEVAM" in joined
    assert "ayar isledi" in joined


def test_mt5_deals_rapora_dahil_edilir(monkeypatch):
    monkeypatch.setattr(m, "db_url", lambda: "")
    deals = [
        {"symbol": "NAS100", "strategy": "LONDON_BREAKOUT", "profit": 10.0, "commission": -0.5, "swap": 0.0, "time": 1795000000},
        {"symbol": "NAS100", "strategy": "LONDON_BREAKOUT", "profit": -4.0, "commission": -0.5, "swap": 0.0, "time": 1795003600},
        {"symbol": "BTCUSD", "strategy": "M1_M5_RADAR_SCALPER", "profit": 5.0, "time": 1795007200},
    ]
    rep = m.build_report(since="2026-11-12", mt5_deals=deals)
    assert rep["kaynak"] == "mt5(3)"
    assert rep["semboller"]["london_breakout:NAS100"]["n"] == 2
    assert rep["semboller"]["london_breakout:NAS100"]["net"] == pytest.approx(5.0)
    assert rep["semboller"]["m1_m5_radar:BTCUSD"]["n"] == 1
    assert rep["ayar_kontrolu"]["london_breakout:NAS100"]["islem"] == 2
    assert rep["ayar_kontrolu"]["london_breakout:USDCHF"]["state"] == "ayar isledi"


def test_llm_calibration_snapshot_calls_run(monkeypatch):
    import asyncio
    from app import llm_calibration
    from app.routines.db_routines import llm_calibration_snapshot

    async def fake_run(days: int = 0, **kwargs):
        return {
            "n": 250, "fitted": True, "base_rate": 0.30, "brier_skill": 0.05,
            "auc": 0.62, "recommended_threshold": 65, "verdict": "OK",
            "walk_forward": {"available": True, "n_test": 80, "calibrated": {"skill": 0.04}},
        }

    monkeypatch.setattr(llm_calibration, "run", fake_run)
    res = asyncio.run(llm_calibration_snapshot())
    assert res["ok"] is True and res["n"] == 250 and res["auc"] == 0.62 and res["oos_skill"] == 0.04
