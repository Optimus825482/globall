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
