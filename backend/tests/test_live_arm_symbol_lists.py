"""CANLI KOL SEMBOL LİSTELERİ — ölçümle kilit (2026-11-12)

İKİ ayrı kol, aynı desen: 2026-10-08'de (veya 10-13'te) seçilen sembol listeleri
**yanlış maliyet tablosuyla** (major = 1,2 pip; gerçek 0,1-0,2) kurulmuştu.
Düzeltilmiş maliyet + gerçek UTC saatle iki bağımsız pencerede yeniden ölçüldü.

Bu dosya, listelerin ölçümle aynı yönde kalmasını kilitler: ölçülen negatif bir
sembol eklenirse ya da ölçümle pozitif olan çıkarılırsa test kırılır.

Kaynak: docs/GIRIS_MODU_YENIDEN_TARAMA_2026-11-12.md (§8) ·
        docs/FX_MALIYET_MODELI_DENETIMI_2026-11-12.md
"""
from __future__ import annotations

from app.routers.forex import ForexAutoPaperSettings as S


# ---------------------------------------------------------------- london_breakout
def test_london_breakout_pozitifler_listede():
    syms = set(S().lb_symbols)
    pozitif = {"GBPUSD", "AUDUSD", "XAUUSD", "US30", "NAS100", "BTCUSD"}
    assert pozitif <= syms, f"ölçümle pozitif olup listede olmayan: {pozitif - syms}"


def test_london_breakout_olculen_negatifler_disarida():
    syms = set(S().lb_symbols)
    # Eski yanlış-maliyet listesinden kalmış, iki pencerede de negatif
    assert "USDCHF" not in syms and "USDJPY" not in syms


# ---------------------------------------------------------------- ema_adx_pullback
def test_ema_adx_pozitifler_listede():
    a = S()
    syms = set(a.ema_adx_symbols)
    # İki pencerede de pozitif (IS/OOS $): XAUUSD +20.546/+15.475 ·
    # USDJPY +2.521/+3.003 · NAS100 +1.875/+1.217 · US30 +862/+508
    pozitif = {"XAUUSD", "USDJPY", "NAS100", "US30"}
    assert pozitif <= syms, f"ölçümle pozitif olup listede olmayan: {pozitif - syms}"


def test_ema_adx_olculen_negatifler_disarida():
    syms = set(S().ema_adx_symbols)
    # İki pencerede de negatif — listeye ALINMAMALI
    for sym in ("GBPUSD", "BTCUSD", "USDCHF", "AUDCAD", "AUDUSD", "EURJPY"):
        assert sym not in syms, f"{sym} ölçümde iki pencerede de negatif, listede olmamalı"


def test_ema_adx_acik_ve_parametreler_beklenen():
    a = S()
    assert a.ema_adx_enabled is True
    assert 0.0 <= a.ema_adx_adx_min <= 60.0
    assert 0.0 <= a.ema_adx_touch_atr <= 2.0


def test_iki_kol_listesi_cakismaz_degil_ama_tutarlı():
    """Aynı sembol iki kolda da olabilir (akışlar birlikte çalışır) — bu bir HATA değil.

    Test yalnız listelerin boş olmadığını ve sembol adlarının büyük harf olduğunu kilitler.
    """
    a = S()
    for lst in (a.lb_symbols, a.ema_adx_symbols):
        assert lst and all(s == s.upper() for s in lst)
