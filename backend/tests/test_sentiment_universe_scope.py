"""Sentiment yüzeyleri SİSTEM EVRENİYLE sınırlı mı? (2026-11-12)

Erkan: "sadece sistemde olan semboller altın ve btc için gösterelim" + LLM'in
fırsat taramasında/sohbetinde ilgili sembolün sentiment'i görünsün.

Kilitlenen davranışlar:
  * `_system_universe()` Ayarlar'daki `allowed_symbols`'tan gelir; XAUUSD ve
    BTCUSD **her hâlükârda** içindedir.
  * `sentiment_table` verilen listeyle sınırlıdır (88 Myfxbook sembolü sızmaz),
    bilinmeyen/bozuk adları atlar, perakende verisi yoksa bunu None bırakır.
  * `sentiment_lines_for` her satır için tek satır metin üretir.
"""
from __future__ import annotations

import pytest

from app import context_extras as cx
from app.routers.system import _system_universe


def test_evren_altin_ve_btc_icerir():
    u = set(_system_universe())
    assert "XAUUSD" in u and "BTCUSD" in u
    assert len(u) >= 5


def test_evren_ayarlardan_gelir():
    from app.routers import forex as fx

    u = set(_system_universe())
    allowed = {str(s).upper() for s in (fx._AUTO_SETTINGS.allowed_symbols or [])}
    assert u <= allowed | {"XAUUSD", "BTCUSD"}


def test_tablo_verilen_listeyle_sinirli(monkeypatch):
    monkeypatch.setattr("app.sentiment_index.summarize",
                        lambda s: {"symbol": s, "score": 10.0, "label": "LONG eğilim",
                                   "coverage": 1.0})
    monkeypatch.setattr("app.retail_sentiment.summary",
                        lambda s=None: {"available": True, "symbol": s, "long_pct": 66.0,
                                        "crowded": None})
    rows = cx.sentiment_table(["XAUUSD", "BTCUSD", "EURUSD"], max_n=2)
    assert [r["symbol"] for r in rows] == ["XAUUSD", "BTCUSD"]   # max_n kesiyor


def test_tablo_perakende_yoksa_none(monkeypatch):
    monkeypatch.setattr("app.sentiment_index.summarize",
                        lambda s: {"symbol": s, "score": -20.0, "label": "SHORT eğilim",
                                   "coverage": 0.25})
    monkeypatch.setattr("app.retail_sentiment.summary",
                        lambda s=None: {"available": False, "reason": "kapsam dışı"})
    row = cx.sentiment_table(["NAS100"])[0]
    assert row["retail_long_pct"] is None and row["score"] == -20.0


def test_metin_satiri_uretir(monkeypatch):
    monkeypatch.setattr("app.sentiment_index.summarize",
                        lambda s: {"symbol": s, "score": 55.0, "label": "LONG eğilim (belirgin)",
                                   "coverage": 1.0})
    monkeypatch.setattr("app.retail_sentiment.summary",
                        lambda s=None: {"available": True, "symbol": s, "long_pct": 88.0,
                                        "crowded": "LONG"})
    line = cx.sentiment_lines_for(["EURUSD"])[0]
    assert "EURUSD" in line and "+55" in line and "KALABALIK LONG" in line
