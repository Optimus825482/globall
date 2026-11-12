"""21-AI konsensüsü + fırsat taraması — canlı kusurların kilitleri (2026-11-12)

CANLI ÇIKTI (Erkan'ın sohbeti) iki kusur gösterdi:
  1. "Konsey=STAND_ASIDE" ile "Karar=APPROVED_BUY, Güven=%100" YAN YANA geliyordu.
     Çekimserlik onay değildir → karar WAIT, güven kelepçeli.
  2. "Nasdaq ve Dow taramaya girmedi" — tarama evreni sabit 18 sembollük listeydi:
     motorun işlem açmadığı pariteler içinde, sistemin endeksleri DIŞINDA; ayrıca
     `OANDA:NAS100USD` TV tarayıcısında veri döndürmüyor (sessiz düşüş).
"""
from __future__ import annotations

import pytest

from app.ai_trading_suite.orchestrator import AITradingSuiteOrchestrator, UnifiedEvaluationRequest


def _req(action: str = "BUY") -> UnifiedEvaluationRequest:
    return UnifiedEvaluationRequest(
        symbol="EURUSD", asset_type="forex", current_price=1.10, atr=0.0010,
        indicators=[], macro_events=[], orderbook_bids=[], orderbook_asks=[],
        proposed_action=action, quant_z_score=0.0, price_change_pct=0.05,
        volume_ratio=1.0, social_buzz=0.5, rsi_value=50.0, trend_slope=0.0)


def _force_council_abstain(orch, monkeypatch):
    """Konseyi çekimser döndürecek sahte nesne (dataclass olmalı: orchestrator asdict çağırıyor)."""
    from dataclasses import dataclass

    @dataclass
    class _C:
        consensus_decision: str = "STAND_ASIDE"

    class _Council:
        def deliberate(self, **kwargs):
            return _C()
    monkeypatch.setattr(orch, "council", _Council())


def _force_reflection_confidence(orch, monkeypatch, conf: float):
    """Yansıma denetimini yüksek güvenle döndür (dataclass: orchestrator asdict çağırıyor)."""
    from dataclasses import dataclass, field

    @dataclass
    class _R:
        final_confidence: float = conf
        final_verdict: str = "APPROVED"
        confidence_penalty: float = 0.0
        trap_detected: str | None = None
        devils_advocate_critique: str = "test"
        initial_verdict: str = "BUY"
        reflection_notes: list = field(default_factory=list)
        symbol: str = "EURUSD"

    monkeypatch.setattr(orch.ai_trader, "audit_trade_proposal", lambda **kw: _R())


def test_konsey_cekimserken_approve_donmez(monkeypatch):
    o = AITradingSuiteOrchestrator()
    _force_council_abstain(o, monkeypatch)
    r = o.evaluate(_req("BUY"))
    assert r.final_verdict == "WAIT", "çekimserlikte APPROVED_* dönmemeli"
    assert "çekimser" in (r.execution_directive or "").lower()


def test_konsey_cekimserken_guven_kelepcelenir(monkeypatch):
    o = AITradingSuiteOrchestrator()
    _force_council_abstain(o, monkeypatch)
    _force_reflection_confidence(o, monkeypatch, 0.95)
    r = o.evaluate(_req("BUY"))
    assert r.confidence_score <= 0.5, "çekimserlikte güven %50'yi aşmamalı"


def test_vetoed_donerse_gerekce_vetodur(monkeypatch):
    """VETOED dönerse gerekçe gerçek bir veto olmalı (çekimserlik 'veto' diye etiketlenmez).

    Not: bu örnekte (SELL + bu girdiler) R:R vetosu devreye giriyor — çekimserlik
    ayrı bir dal; ikisi karışmamalı.
    """
    o = AITradingSuiteOrchestrator()
    _force_council_abstain(o, monkeypatch)
    r = o.evaluate(_req("SELL"))
    if r.final_verdict == "VETOED":
        assert "R:R" in (r.execution_directive or "") or "Veto" in (r.execution_directive or "")
        assert "çekimser" not in (r.execution_directive or "").lower()


# ---------------------------------------------------------------- tarama evreni
def test_tarama_evreni_sistem_evreni():
    from app import forex_research as fr
    from app.routers import forex as fx

    u = fr.scan_universe()
    allowed = {str(x).upper() for x in (fx._AUTO_SETTINGS.allowed_symbols or [])}
    assert u == list(allowed) or set(u) <= allowed | {"XAUUSD", "BTCUSD"}


def test_tarama_evreni_sabit_liste_degil():
    """Eski sabit listede motorun işlem açmadığı pariteler vardı (NZDUSD/USDCAD/AUDJPY)."""
    from app import forex_research as fr

    u = set(fr.scan_universe())
    for disi in ("NZDUSD", "USDCAD", "AUDJPY", "EURGBP", "AUDNZD"):
        assert disi not in u, f"{disi} sistem evreninde değil, taramaya girmemeli"


def test_tv_endeks_eslemeleri_olu_ticker_kullanmaz():
    from app import forex_research as fr

    for sym in ("NAS100", "USTEC", "US30", "JP225", "UK100", "US2000"):
        spec = fr._TV.get(sym)  # noqa: SLF001
        assert spec, f"{sym} için TradingView eşlemesi yok"
        market, ticker = spec
        assert ticker != "OANDA:NAS100USD", "bu ticker CFD tarayıcısında veri döndürmüyor"
