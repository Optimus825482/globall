"""London Breakout CANLI sembol listesi — ölçümle kilit (2026-11-12)

NEDEN
-----
2026-10-08'de liste **yanlış maliyet tablosuyla** seçilmişti (major = 1,2 pip;
gerçek 0,1-0,2). Düzeltilmiş maliyet + gerçek UTC saatle iki ayrı pencerede
ölçüm aynı yönde çıktı ve canlı listeyle çelişti.

Ölçüm (NEW defter, PF/net $):
  IS  = son 30 gün · OOS = önceki 30 gün (`--days 60 --window prior`)

  GBPUSD  +3.017 / +2.782     XAUUSD  +670 / +650     US30    +657 / +409
  AUDUSD  +1.831 / +708       NAS100  +298 / +287     BTCUSD  +52  / +52
  USDCHF   −327 / −727  ← CANLIDA VARDI, ÇIKARILDI
  USDJPY   −340 / −148  ← CANLIDA VARDI, ÇIKARILDI

Bu test **listenin ölçümle aynı yönde kalmasını** kilitler: biri USDCHF/USDJPY'yi
geri eklerse ya da ölçümle çelişen bir sembol girerse kırılır. Sembol eklemek
isteyen, önce iki pencerede pozitif olduğunu gösterip burayı günceller.
"""
from __future__ import annotations

from app.routers.forex import ForexAutoPaperSettings


def _lb_symbols() -> list[str]:
    return list(ForexAutoPaperSettings().lb_symbols)


def test_london_breakout_sembolleri_olcumle_uyumlu():
    syms = set(_lb_symbols())
    # İki pencerede POZİTİF olanlar listede olmalı
    pozitif = {"GBPUSD", "AUDUSD", "XAUUSD", "US30", "NAS100", "BTCUSD"}
    assert pozitif <= syms, f"ölçümle pozitif olup listede olmayan: {pozitif - syms}"


def test_olculen_negatif_semboller_listede_degil():
    syms = set(_lb_symbols())
    # İki pencerede NEGATİF (eski yanlış-maliyet listesinden kalmıştı)
    assert "USDCHF" not in syms
    assert "USDJPY" not in syms


def test_london_breakout_acik_ve_parametreler_beklenen():
    a = ForexAutoPaperSettings()
    assert a.lb_enabled is True
    assert a.lb_box_end_utc == 7
    assert a.lb_entry_end_utc == 11
    assert 0.1 <= a.lb_sl_box_frac <= 1.0
    assert 0.5 <= a.lb_tp_r <= 5.0
