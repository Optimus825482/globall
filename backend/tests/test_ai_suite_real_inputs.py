"""21-AI konsensüsü GERÇEK veriyle mi besleniyor? (2026-11-12)

CANLI KUSUR: sohbetin 21-AI aracı motora **sabit girdiler** veriyordu:
4 gösterge hep +0,75/+0,70/+0,85/+0,60 (boğa), rsi=56, price_change=1,4,
volume_ratio=1,9, quant_z=-0,2, uydurma emir defteri, `proposed_action`=BUY.
Sonuç: her sembolde aynı sayılar (Qlib 65,7 · R:R 1,57 · Kelly 863,06) ve
SELL sinyali olan sembolde bile "APPROVED_BUY".

Bu testler o sözleşmeyi kilitler:
  * girdiler sembole göre DEĞİŞİR (rsi, quant_z, yön, gösterge sayısı)
  * gerçek veri yoksa konsensüs ÜRETİLMEZ (ok=False)
  * konsey aracı da sabit girdi kullanmaz
"""
from __future__ import annotations

import pytest

from app.ai_trading_suite import chat_tools as ct


def _fake_analysis(bias="SELL", rsi=23.7, ema20=99.0, ema50=100.0, atr=1.0, price=98.0,
                   macd=-0.2, bbpos=0.15, cci=-85.0, stoch=89.0, supertrend="asagi",
                   score=-4.0):
    return {
        "ok": True, "price": price, "bias": bias, "score": score,
        "frames": {"1h": {"price": price, "ema20": ema20, "ema50": ema50, "rsi": rsi,
                          "adx": 30.0, "atr": atr, "bb_pos": bbpos, "macd_hist": macd}},
        "indicators": {"1h": {"supertrend": {"yon": supertrend},
                              "stoch_rsi": {"k": stoch}, "cci20": cci}},
        "candles": {"1h": [{"close": price} for _ in range(25)]},
    }


def test_girdiler_sembolden_turetilir():
    a_bull = _fake_analysis(bias="BUY", rsi=61.1, ema20=101.0, ema50=100.0, price=102.0,
                            macd=+0.3, bbpos=0.8, cci=60.0, stoch=20.0, supertrend="yukari")
    a_bear = _fake_analysis()
    bull = ct._real_inputs_from_analysis(a_bull)   # noqa: SLF001
    bear = ct._real_inputs_from_analysis(a_bear)   # noqa: SLF001
    assert bull and bear
    assert bull["rsi_value"] != bear["rsi_value"]
    assert bull["proposed_action"] == "BUY" and bear["proposed_action"] == "SELL"
    assert bull["quant_z_score"] > 0 > bear["quant_z_score"]
    assert bull["indicators"] and bear["indicators"]
    # Gösterge işaretleri gerçekten farklı olmalı (sabit +0,75 seti değil)
    bull_sig = [i.signal for i in bull["indicators"]]
    bear_sig = [i.signal for i in bear["indicators"]]
    assert bull_sig != bear_sig


def test_veri_yoksa_konsensus_uretilmez(monkeypatch):
    class _Fail:
        @staticmethod
        def analyze_symbol(sym):
            return {"ok": False}

        @staticmethod
        def run_blocking(fn, *a, **k):
            return {"ok": False}

    import asyncio

    monkeypatch.setattr("app.forex_research.run_blocking",
                        lambda fn, *a, **k: {"ok": False})
    r = asyncio.run(ct.execute_ai_trading_suite_evaluation(
        {"symbol": "EURUSD", "asset_type": "FOREX"}))
    assert r.get("ok") is False and "ÜRETİLMEDİ" in str(r.get("reason"))


def test_sembol_yoksa_hata():
    import asyncio
    r = asyncio.run(ct.execute_ai_trading_suite_evaluation(
        {"symbol": "", "asset_type": "FOREX"}))
    assert r.get("ok") is False


def test_emir_defteri_uydurulmuyor():
    """Kaynakta uydurma bid/ask (price*0.9998 ...) kalmamalı."""
    import inspect
    src = inspect.getsource(ct.execute_ai_trading_suite_evaluation)
    assert "0.9998" not in src and "0.0002" not in src
    assert "orderbook_bids=[]" in src


def test_konsey_araci_sabit_girdi_kullanmaz():
    import inspect
    import re

    src = inspect.getsource(ct.execute_hedge_fund_council)
    # Docstring eski hâli ANLATIYOR (kasıtlı); denetim yalnız KOD gövdesinde.
    doc = ct.execute_hedge_fund_council.__doc__ or ""
    code = src.replace(doc, "")
    code = re.sub(r"#.*", "", code)   # yorumları da at
    for hard in ("macro_score=0.45", "quant_z_score=-0.3", "rsi_value=55.0"):
        assert hard not in code, f"konsey hâlâ sabit girdi kullanıyor: {hard}"
    assert "_real_inputs_from_analysis" in code
