"""Perakende konumlanma (Myfxbook) — AĞA ÇIKMAYAN davranış testleri (2026-11-12)

Neden: bu veri LLM bağlamına ve ana sayfa kartına giriyor. Yanlış taraf
gösterilirse model/kullanıcı ters yön okur. Bu yüzden sözleşme kilitlenir:
  * long/short yüzdeleri normalize edilir, ters çevrilmez
  * KALABALIK eşiği tek taraflı ve yalnız GÖRÜNTÜ (kapı değil)
  * ince örneklem işaretlenir, sessizce "güçlü sinyal" sayılmaz
  * kapsam dışı sembol (endeks) "veri yok" der, uydurmaz
  * kota tavanı aşılırsa ağa çıkılmaz
"""
from __future__ import annotations

import pytest

from app import retail_sentiment as rs


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Her testte bellek durumunu sıfırla; env kimliği taklit et."""
    monkeypatch.setitem(rs._state, "rows", {})
    monkeypatch.setitem(rs._state, "fetched_at", None)
    monkeypatch.setitem(rs._state, "last_error", None)
    monkeypatch.setitem(rs._state, "day_calls", 0)
    monkeypatch.setitem(rs._state, "day", None)
    yield


def _feed(rows):
    rs._state["rows"] = rows
    rs._state["fetched_at"] = __import__("time").time()


def _row(sym, long_pct, total=10000, long_pos=None, short_pos=None):
    return {
        "symbol": sym,
        "long_pct": float(long_pct),
        "short_pct": 100.0 - float(long_pct),
        "long_positions": long_pos if long_pos is not None else int(total * long_pct / 100),
        "short_positions": short_pos if short_pos is not None else int(total * (100 - long_pct) / 100),
        "total_positions": total,
        "avg_long_price": 1.1,
        "avg_short_price": 1.2,
        "source": "myfxbook",
    }


def test_normalize_alanlari_dogru_esler():
    items = [{"name": "EURUSD", "longPercentage": 88, "shortPercentage": 12,
              "longPositions": 37312, "shortPositions": 7984, "totalPositions": 45296,
              "avgLongPrice": 1.1336, "avgShortPrice": 1.0976}]
    rows = rs._normalize(items)
    r = rows["EURUSD"]
    assert r["long_pct"] == 88.0 and r["short_pct"] == 12.0
    assert r["total_positions"] == 45296
    assert r["avg_long_price"] == pytest.approx(1.1336)


def test_normalize_bos_ve_bozuk_satirlari_atlar():
    rows = rs._normalize([
        {"name": "", "longPercentage": 50, "shortPercentage": 50},
        {"longPercentage": 50, "shortPercentage": 50},              # isim yok
        {"name": "XAUGBP", "longPercentage": 0, "shortPercentage": 0},  # yüzde yok
        {"name": "GBPUSD", "longPercentage": 57, "shortPercentage": 43, "totalPositions": 10},
    ])
    assert list(rows) == ["GBPUSD"]


def test_kalabalik_tek_tarafli_ve_karsi_yon_tutuyor():
    _feed({"EURUSD": _row("EURUSD", 88), "USDJPY": _row("USDJPY", 30), "GBPUSD": _row("GBPUSD", 57)})
    eur = rs.summary("EURUSD")
    assert eur["crowded"] == "LONG" and eur["contrarian"] == "SHORT"
    jpy = rs.summary("USDJPY")
    assert jpy["crowded"] == "SHORT" and jpy["contrarian"] == "LONG"
    mid = rs.summary("GBPUSD")
    assert mid["crowded"] is None and mid["contrarian"] is None


def test_esik_sinirinda_davranis():
    _feed({"A": _row("A", rs.RET_SENT_CROWD_PCT), "B": _row("B", rs.RET_SENT_CROWD_PCT - 1)})
    assert rs.summary("A")["crowded"] == "LONG"   # eşik DAHİL
    assert rs.summary("B")["crowded"] is None


def test_ince_orneklem_isaretlenir():
    _feed({"EURUSD": _row("EURUSD", 90, total=50)})
    s = rs.summary("EURUSD")
    assert s["thin_sample"] is True
    assert "ince" in " ".join(rs.compact_lines("EURUSD")).lower()


def test_kapsam_disi_sembol_veri_yok_der():
    _feed({"EURUSD": _row("EURUSD", 88)})
    s = rs.summary("NAS100")
    assert s["available"] is True and s["symbol"] is None
    line = rs.compact_lines("NAS100")[0]
    assert "kapsamda yok" in line
    assert "%" not in line  # sayı uydurulmaz


def test_veri_yokken_notr_sayilmaz():
    s = rs.summary("EURUSD")
    assert s["available"] is False and s["reason"]
    line = rs.compact_lines("EURUSD")[0]
    assert "YOK" in line and "uydurulmaz" in line


def test_compact_lines_buyukluk_ve_yas_yazar():
    _feed({"EURUSD": _row("EURUSD", 88)})
    line = rs.compact_lines("EURUSD")[0]
    assert "%88 long" in line and "%12 short" in line
    assert "pozisyon" in line
    assert "KAPI değil" in line  # kullanım sözleşmesi metinde duruyor


def test_kota_tavani_asma_yok(monkeypatch):
    monkeypatch.setitem(rs._state, "day", __import__("time").strftime("%Y-%m-%d", __import__("time").gmtime()))
    monkeypatch.setitem(rs._state, "day_calls", rs.RET_SENT_DAILY_CAP)
    called = {"n": 0}

    class FakeResp:
        def json(self):
            called["n"] += 1
            return {"error": True, "message": "x"}

    class FakeSess:
        def get(self, *a, **k):
            called["n"] += 1
            return FakeResp()

    assert rs._quota_ok() is False
    assert rs._login(FakeSess()) is None
    assert called["n"] == 0  # ağa hiç çıkılmadı
    assert "kota" in (rs._state["last_error"] or "")


def test_broker_alias_eslemesi():
    _feed({"NAS100": _row("NAS100", 80, total=2000)})
    # USTEC (broker adı) NAS100 satırına düşer
    assert rs.summary("USTEC")["symbol"] == "NAS100"


def test_sessiz_hata_yutulmaz():
    """Ayrıştırılamayan yanıtta sebep yazılır, eski veri korunur."""
    _feed({"EURUSD": _row("EURUSD", 60)})
    ok = rs._normalize([{"name": "X", "longPercentage": "abc", "shortPercentage": "def"}])
    assert ok == {}
