"""ÇIKIŞ GEOMETRİSİ sözleşmesi — spec MUTLAKA ATR ile üretilmeli (2026-11-12)

DERS (kendi yanlış teşhisim)
---------------------------
İlk bakışta "motorun geometrisi bozuk" sandım: 21-AI'de XAU 195/60 (R:R 0,31),
BTC 840/60 (0,07) görünüyordu. A/B koşusu **tavan açık/kapalı birebir aynı** çıktı
(6936 işlem, PF 1,20, net 80.153 $ — iki pencerede de) → motor zaten doğruydu.

GERÇEK KÖK NEDEN: motor spec'i `get_symbol_trading_specs(sym, atr_pips=...)` ile
üretiyor (TP ATR ile GENİŞLER); benim 21-AI bağlantım spec'i **ATR'siz** çağırıyordu
→ TP tabanda (FX 20 / XAU-BTC 60 pip) kalıp R:R'yi çökertiyordu.

Bu testler sözleşmeyi kilitler:
  * ATR ile üretilen spec, ATR'siz spec'ten GENİŞ TP verir (yüksek ATR'de).
  * `get_atr_exit_levels` genişletilmiş spec ile R:R'yi rr_floor civarında tutar.
  * ATR'siz spec + yüksek ATR kombinasyonu R:R'yi çökertir (uyarı: bu kombinasyon
    üretimde KULLANILMAMALI — test bunu belge olarak tutuyor).
"""
from __future__ import annotations

import pytest

from app.routers import forex


@pytest.mark.parametrize("sym,atr_pips", [("XAUUSD", 130.0), ("BTCUSD", 560.0)])
def test_spec_atr_ile_genisler(sym, atr_pips):
    """ATR verilince TP/SL büyümeli — motorun canlı yolu bu."""
    duz = forex.get_symbol_trading_specs(sym)
    genis = forex.get_symbol_trading_specs(sym, atr_pips=atr_pips)
    assert genis["sl_pips"] >= duz["sl_pips"]
    assert genis["tp_pips"] >= duz["tp_pips"]
    assert genis["tp_pips"] > duz["tp_pips"] or genis["sl_pips"] > duz["sl_pips"]


@pytest.mark.parametrize("sym,atr_pips", [("XAUUSD", 130.0), ("EURUSD", 12.0)])
def test_motor_yolu_rr_tabanini_korur(sym, atr_pips):
    """Motor yolu: spec ATR ile üretilir → get_atr_exit_levels R:R'yi rr_floor'da tutar."""
    spec = forex.get_symbol_trading_specs(sym, atr_pips=atr_pips)
    lv = forex.get_atr_exit_levels(atr_pips, spec["sl_pips"], spec["tp_pips"],
                                   sl_atr_mult=1.5, rr_floor=1.5)
    rr = lv["tp_pips"] / max(lv["sl_pips"], 1e-9)
    assert rr >= 1.35, f"{sym}: motor yolu R:R {rr:.2f} — rr_floor korunmalı"


def test_atrsiz_spec_yuksek_atrde_rr_COKERTIR():
    """BELGE TESTİ: ATR'siz spec + yüksek ATR → R:R çöker. Bu kombinasyon HATA kaynağıydı
    (21-AI 2026-11-12). Üretimde spec her zaman atr_pips ile üretilmeli."""
    spec = forex.get_symbol_trading_specs("XAUUSD")      # ATR YOK
    lv = forex.get_atr_exit_levels(130.0, spec["sl_pips"], spec["tp_pips"], sl_atr_mult=1.5)
    rr = lv["tp_pips"] / max(lv["sl_pips"], 1e-9)
    assert rr < 0.5, "beklenen kusur profili: 195/60 ≈ 0,31"


def test_FX_dalinda_ATR_genislemesi_YOK():
    """BELGE TESTİ (açık konu): XAU/BTC dalları spec SL/TP'sini ATR ile genişletiyor,
    GENEL FX dalı genişletmiyor → yüksek ATR'de FX'te SL büyür ama TP 20 pip'te kalır
    (USDJPY ATR 27 → motor yolu R:R ≈ 0,49). A/B ile ölçülmeden DEĞİŞTİRİLMEMELİ."""
    duz = forex.get_symbol_trading_specs("USDJPY")
    genis = forex.get_symbol_trading_specs("USDJPY", atr_pips=27.0)
    assert (duz["sl_pips"], duz["tp_pips"]) == (genis["sl_pips"], genis["tp_pips"])
    lv = forex.get_atr_exit_levels(27.0, genis["sl_pips"], genis["tp_pips"], sl_atr_mult=1.5)
    assert lv["tp_pips"] / lv["sl_pips"] < 1.0


def test_atr_yoksa_passthrough():
    lv = forex.get_atr_exit_levels(None, 8.0, 20.0)
    assert lv["sl_pips"] == 8.0 and lv["tp_pips"] == 20.0
