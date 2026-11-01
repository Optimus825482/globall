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
