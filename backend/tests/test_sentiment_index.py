"""Bileşik sentiment endeksi — ağa çıkmayan sözleşme testleri (2026-11-12)

Kilitlenen davranışlar:
  * Merkez 0: + LONG, − SHORT (işaret kuralı tek yerde)
  * Eksik bileşen "nötr" SAYILMAZ — ağırlığı düşer, `coverage` ve `missing` raporlanır
  * Tek bileşen varsa skor o bileşendir (seyreltme yok)
  * Perakende TERS okunur (kalabalık long → negatif skor)
  * Ekonomik veri 24 saat penceresi + yaş ağırlığı (eski veri daha az etkiler)
  * Bantlar: |skor| < nötr bandı → "DENGELİ"
"""
from __future__ import annotations

import pytest

from app import sentiment_index as si


# ---------------------------------------------------------------- saf yardımcılar
@pytest.mark.parametrize("sym,base,quote", [
    ("EURUSD", "EUR", "USD"), ("GBPJPY", "GBP", "JPY"), ("USDCHF", "USD", "CHF"),
    # XAU bir para birimi değil: altın dalı `is_index_like`/XAU ön kontrolünde ele alınır.
    ("XAUUSD", None, None), ("NAS100", None, None), ("BTCUSD", None, None),
])
def test_parca_ayrimi(sym, base, quote):
    assert si.split_symbol(sym) == (base, quote)


def test_endeks_ve_kripto_tanima():
    assert si.is_index_like("US30") and si.is_index_like("NAS100") and si.is_index_like("DE40")
    assert not si.is_index_like("EURUSD")
    assert si.is_crypto("BTCUSD") and si.is_crypto("ETHUSD")
    assert not si.is_crypto("EURUSD")


def test_olcek_doyuma_oturmuyor_ama_sinirli():
    """tanh ölçek: büyük hareket ±100'e yaklaşır, kelepçe gibi sabitlenmez."""
    small = si._scaled(0.1, 0.5)
    big = si._scaled(2.0, 0.5)
    assert small is not None and big is not None
    assert 0 < small < big <= 100.0
    assert si._scaled(-2.0, 0.5) < 0
    assert si._scaled(None, 0.5) is None


# ---------------------------------------------------------------- bileşenler
SI_FN = {
    "takvim": "_component_calendar", "cot": "_component_cot",
    "kuresel": "_component_global", "perakende": "_component_retail",
}


def _fake(monkeypatch, scores: dict) -> None:
    """Bileşen fonksiyonlarını sabit skorlarla değiştir (ağ yok).

    `monkeypatch` ZORUNLU: düz `setattr` modül fonksiyonunu kalıcı eziyor ve
    sonraki testler sahte bileşenlerle koşuyor (bu testlerin ilk hâlinde tam bu
    hata yakalandı — imza bilerek monkeypatch alıyor).
    """
    for name, val in scores.items():
        if val is None:
            monkeypatch.setattr(si, SI_FN[name],
                                lambda s, _n=name: (None, {"available": False, "reason": "test"}))
        else:
            monkeypatch.setattr(si, SI_FN[name],
                                lambda s, _v=val: (_v, {"available": True, "detail": "test"}))


def test_isaret_kurali_ve_agirlikli_ortalama(monkeypatch):
    _fake(monkeypatch, {"takvim": 100.0, "cot": -100.0, "kuresel": None, "perakende": None})
    out = si.summarize("EURUSD")
    # ağırlıklar 0.35 vs 0.20 → (35 - 20)/0.55 = +27.3
    assert out["score"] > 0
    assert 20 < out["score"] < 35
    assert out["coverage"] == pytest.approx((0.35 + 0.20) / 1.0, abs=1e-3)
    assert set(out["missing"]) == {"kuresel", "perakende"}


def test_eksik_bilesen_notr_sayilmaz(monkeypatch):
    """Yalnız tek bileşen varsa skor ONUN skorudur (0'a çekilmez)."""
    _fake(monkeypatch, {"takvim": None, "cot": None, "kuresel": 80.0, "perakende": None})
    out = si.summarize("XAUUSD")
    assert out["score"] == pytest.approx(80.0, abs=1e-6)
    assert out["coverage"] == pytest.approx(0.25, abs=1e-3)
    assert out["score"] != 0.0


def test_perakende_ters_yon(monkeypatch):
    # gerçek fonksiyon, sahte summary ile
    monkeypatch.setattr("app.retail_sentiment.summary",
                        lambda sym=None: {"available": True, "symbol": "EURUSD",
                                          "long_pct": 88.0, "positions": 10000,
                                          "thin_sample": False})
    score, meta = si._component_retail("EURUSD")
    assert score is not None and score < -50   # %88 long → güçlü SHORT tarafta
    assert meta["available"] is True


def test_perakende_ince_orneklem_yarilanir(monkeypatch):
    monkeypatch.setattr("app.retail_sentiment.summary",
                        lambda sym=None: {"available": True, "symbol": "EURUSD",
                                          "long_pct": 88.0, "positions": 50,
                                          "thin_sample": True})
    score, meta = si._component_retail("EURUSD")
    assert score is not None and abs(score) == pytest.approx(38.0, abs=1e-6)
    assert meta["thin_sample"] is True


def test_nor_tr_bant_etiketi(monkeypatch):
    _fake(monkeypatch, {"takvim": 5.0, "cot": None, "kuresel": None, "perakende": None})
    out = si.summarize("EURUSD")
    assert "DENGELİ" in out["label"]


def test_guclu_egilim_etiketi(monkeypatch):
    _fake(monkeypatch, {"takvim": 90.0, "cot": None, "kuresel": None, "perakende": None})
    assert "LONG" in si.summarize("EURUSD")["label"]
    _fake(monkeypatch, {"takvim": -90.0, "cot": None, "kuresel": None, "perakende": None})
    assert "SHORT" in si.summarize("EURUSD")["label"]


# ---------------------------------------------------------------- takvim bileşeni
def _event(currency: str, side_bullish: bool, age_h: float, title: str = "ABD Enflasyon"):
    import datetime as dt
    ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=age_h)
    return {
        "currency": currency,
        "title": title,
        "date_iso": ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "actual": "3.0%", "forecast": "2.0%", "previous": "2.5%",
        "affected_symbols": ["EURUSD"],
    }


def test_takvim_yas_agirligi_eski_veriyi_zayiflatir(monkeypatch):
    """Aynı yönde iki olay: taze olan skoru daha çok çeker."""
    import app.forex_news as fn
    monkeypatch.setattr(fn, "evaluate_event_outcome",
                        lambda *a, **k: {"side": "bullish", "label_tr": "olumlu"})
    monkeypatch.setattr(fn, "map_symbols_for_event", lambda cur, title: ["EURUSD"])
    fresh = si.refresh_calendar([_event("EUR", True, 0.5)], force=True)
    score_fresh, _ = si._component_calendar("EURUSD")
    old = si.refresh_calendar([_event("EUR", True, 23.0)], force=True)
    score_old, meta_old = si._component_calendar("EURUSD")
    assert fresh and old
    assert score_fresh is not None and score_old is not None
    assert score_fresh > score_old        # taze veri daha güçlü
    assert meta_old["age_hours"] > 20


def test_takvim_pencere_disi_olay_yok_sayilir(monkeypatch):
    import app.forex_news as fn
    monkeypatch.setattr(fn, "evaluate_event_outcome",
                        lambda *a, **k: {"side": "bullish"})
    si.refresh_calendar([_event("EUR", True, 48.0)], force=True)   # 24s dışı
    score, meta = si._component_calendar("EURUSD")
    assert score is None and meta["available"] is False
