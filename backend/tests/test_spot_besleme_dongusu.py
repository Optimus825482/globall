"""Spot pozisyon yaşam döngüsü: yeterince bekleme + dinamik skorlar.

Kullanıcı gözlemi (2026-11-01):
  1. "Panelde OctoBot/Qlib/Vibe değerleri GİRİŞ ANINDAKI değerler, dinamik
     güncellenmiyor" — doğru: `details` sinyal anında donuyordu.
  2. "Konu uzun ya da kısa beklemek değil, YETERİNCE beklemek" — doğru:
     ölçüm tutma süresinin monoton olmadığını gösterdi.
"""
from __future__ import annotations

import inspect

import pytest

from app import spot_monitor


# ─── YETERİNCE BEKLEME ────────────────────────────────────────────────────────

def test_time_management_constants_exist():
    """Erken çıkış ve azami tutma eşikleri tanımlı olmalı."""
    assert set(spot_monitor.EARLY_EXIT_MINUTES) == {"5m", "15m", "1h"}
    assert set(spot_monitor.MAX_HOLD_MINUTES) == {"5m", "15m", "1h"}


def test_max_hold_is_greater_than_early_exit():
    """Azami tutma, erken çıkıştan UZUN olmalı.

    'Yeterince bekleme' iki sınır arasında bir banttır: erken çıkış tez
    tutmadığında, azami tutma ise hiçbir koşulda beklemenin tavanı.
    İkisi ters sırada olursa erken çıkış hiç çalışmaz.
    """
    for tf in ("5m", "15m", "1h"):
        assert spot_monitor.MAX_HOLD_MINUTES[tf] > spot_monitor.EARLY_EXIT_MINUTES[tf]


def test_early_exit_requires_no_progress_AND_no_momentum():
    """Erken çıkış için hem kâr hem momentum YOKLUĞU aranmalı.

    Yalnızca süreye bakmak "kısa vade" tuzağıdır; yalnızca kâra bakmak
    kazananı erken keser. İkisi birlikte 'tez tutmadı' demektir.
    """
    src = inspect.getsource(spot_monitor.update_open_signals_pnl)
    assert "EARLY_EXIT_MIN_PROGRESS_PCT" in src
    assert "rsi_now" in src
    assert "stalled" in src


def test_early_exit_is_skipped_while_trailing_active():
    """Takipçi devredeyken (tez ÇALIŞTI) zaman baskısı olmamalı."""
    src = inspect.getsource(spot_monitor.update_open_signals_pnl)
    assert "elif not trailing_active:" in src


def test_stalled_positions_get_distinct_status():
    """Tez tutmayan işlem ayrı durumla kapanmalı (EXPIRED ile karışmasın).

    Ayrım önemli: 'süre doldu' ile 'momentum yok' farklı teşhislerdir ve
    strateji değerlendirmesinde farklı okunur.
    """
    src = inspect.getsource(spot_monitor.update_open_signals_pnl)
    assert '"STALLED"' in src
    assert "momentum_yok" in src


# ─── DİNAMİK SKORLAR ──────────────────────────────────────────────────────────

def test_live_snapshot_uses_current_bars():
    """Canlı gösterge anlık görüntüsü GÜNCEL mumlardan hesaplanmalı."""
    src = inspect.getsource(spot_monitor._live_indicator_snapshot)
    assert "_fetch_klines" in src
    assert "_rsi" in src
    assert "_adx" in src


def test_live_snapshot_is_cached():
    """Sembol başına önbellek olmalı — her panel yenilemesinde istek atılmamalı."""
    assert spot_monitor.LIVE_IND_TTL_SEC > 0
    src = inspect.getsource(spot_monitor._live_indicator_snapshot)
    assert "_live_ind_cache" in src


def test_live_snapshot_returns_none_on_failure():
    """Ağ hatasında None dönmeli; panel girişteki değerlere düşebilmeli."""
    src = inspect.getsource(spot_monitor._live_indicator_snapshot)
    assert "except Exception" in src
    assert "return None" in src


def test_dashboard_recomputes_only_for_open_positions():
    """Canlı hesap YALNIZCA açık pozisyonlar için yapılmalı.

    Kapalı işlemlerin değerleri tarihsel kayıttır; yeniden hesaplamak
    geçmişi bugüne göre yeniden yazmak olur.
    """
    src = inspect.getsource(spot_monitor.get_spot_monitor_dashboard)
    assert 'if r["status"] == "OPEN":' in src
    assert "_live_indicator_snapshot" in src


def test_dashboard_exposes_entry_scores_for_comparison():
    """Giriş değerleri ayrı tutulmalı — canlı ile karşılaştırılabilsin."""
    src = inspect.getsource(spot_monitor.get_spot_monitor_dashboard)
    assert '"entry_scores"' in src
    assert '"indicators_live"' in src


def test_dashboard_exposes_live_rsi_and_adx():
    """Canlı RSI/ADX panel için dışa verilmeli."""
    src = inspect.getsource(spot_monitor.get_spot_monitor_dashboard)
    assert '"live_rsi"' in src
    assert '"live_adx"' in src


# ─── ÖLÇÜLMÜŞ STRATEJİ ELEMESİ (2026-11-01) ───────────────────────────────────

def test_loss_making_strategies_disabled_by_default():
    """Rastgeleden kötü 5 strateji VARSAYILAN kapalı olmalı.

    Ölçüm (8 sembol × 1000 gerçek 5m bar, takipçi çıkışı, %0.15 maliyet):
      squeeze_breakout    n=15  PF 1.82  +0.226%   TUT
      rvol_tod_spike      n=5   PF 1.23  +0.047%   TUT
      --- rastgele ---    n=648 PF 0.42  -0.285%   referans
      stc_cycle           n=62  PF 0.58
      linreg_slope_turn   n=55  PF 0.40
      zlmacd_momentum     n=229 PF 0.30
      supertrend_pullback n=49  PF 0.26
      ema_bounce          n=44  PF 0.25

    Kapalı olanların 5'i de rastgeleden KÖTÜ ya da ona eşit. Açık tutmak
    "daha çok sinyal = daha çok fırsat" yanılgısıdır: her işlem komisyon
    öder ve beklentisi negatiftir.
    """
    for code in ("ema_bounce", "supertrend_pullback", "zlmacd_momentum",
                 "linreg_slope_turn", "stc_cycle"):
        assert code in spot_monitor.DEFAULT_DISABLED_STRATEGIES, f"{code} kapatılmalıydı"


def test_profitable_strategies_stay_enabled():
    """Ölçümde kârlı çıkan stratejiler kapatılmamalı."""
    for code in ("squeeze_breakout", "rvol_tod_spike", "kdj_pure_dip"):
        assert code not in spot_monitor.DEFAULT_DISABLED_STRATEGIES, f"{code} açık kalmalıydı"


def test_disabled_set_is_subset_of_active():
    """Kapatma listesi tanımlı stratejilerden oluşmalı (yazım hatası koruması)."""
    assert spot_monitor.DEFAULT_DISABLED_STRATEGIES <= spot_monitor.ACTIVE_STRATEGY_CODES


def test_db_settings_override_defaults():
    """DB'de kayıt varsa varsayılanı EZMELİ — operatör panelden açabilsin."""
    src = inspect.getsource(spot_monitor._ensure_strategy_settings)
    assert "DEFAULT_DISABLED_STRATEGIES" in src
    # DB güncellemesi varsayılandan SONRA gelmeli
    assert src.index("DEFAULT_DISABLED_STRATEGIES") < src.index("_strategy_enabled.update({r[")


def test_early_exit_dead_rule_documented_as_measured_failure():
    """'Ölü işlem' kuralı denendi ve KAYBETTİRDİ — kod bunu belgelemeli.

    Ölçüm: erken çıkışı 15 dk'da sıkılaştırmak PF 0.61 → 0.26 yaptı, çünkü
    kazanan işlemlerin çoğu da ilk 15-30 dk'da kâr göstermiyor. Eşik bu yüzden
    etkisiz (9999) bırakıldı. Test, birinin bunu "unutulmuş ayar" sanıp
    'düzeltmesini' engeller.
    """
    assert all(v >= 9999 for v in spot_monitor.EARLY_EXIT_DEAD_MINUTES.values())
    src = inspect.getsource(spot_monitor)
    assert "DENENDİ ve KALDIRILDI" in src or "kötüleştirdi" in src
