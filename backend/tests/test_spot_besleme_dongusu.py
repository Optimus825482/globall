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


# ─── ÖLÇÜLMÜŞ STRATEJİ ELEMESİ (2026-11-01) + VBT DOĞRULAMALI GENİŞLEME ──────

def test_measured_out_strategies_stay_out():
    """7 strateji 60 günlük ölçümle KALDIRILDI ve geri gelmemeli.

    60 GÜNLÜK ölçüm (40 sembol × 1.65M bar, gerçek vectorbt, %0.15 maliyet):
      strateji              n      WR     PF    ort%   rastgeleye fark
      kdj_pure_dip         559   43.1%  0.91  -0.116      +0.031 ANLAMLI
      zlmacd_momentum    11826   38.6%  0.71  -0.135      +0.012 gürültü
      rvol_tod_spike      5345   38.0%  0.74  -0.137      +0.010 gürültü
      stc_cycle           4877   39.0%  0.72  -0.140      +0.007 gürültü
      supertrend_pullback 36599  39.1%  0.70  -0.137      +0.010 gürültü
      linreg_slope_turn  27224   39.2%  0.70  -0.140      +0.007 gürültü
      squeeze_breakout    1279   37.9%  0.70  -0.147      +0.000 gürültü
      ema_bounce         23118   37.7%  0.67  -0.154      -0.007 gürültü
      --- rastgele ---   52840   39.4%  0.69  -0.147      referans

    Kaldırılanların 7'si de rastgele girişten ayrışmıyordu. Sonrasında (2026-11-02+
    VBT doğrulamalı entegrasyonlarla) 15 stratejiye genişletildi; bu 7 hâlâ dışarıda.
    """
    codes = {s["code"] for s in spot_monitor.ACTIVE_STRATEGIES}
    for gone in ("squeeze_breakout", "zlmacd_momentum", "stc_cycle", "supertrend_pullback",
                 "linreg_slope_turn", "rvol_tod_spike", "ema_bounce"):
        assert gone not in codes, f"{gone} ölçümle elenmişti, geri gelmiş"
    assert "kdj_pure_dip" in codes


def test_active_strategy_roster_is_integrated_set():
    """VBT doğrulaması geçen 15 strateji kayıtlı olmalı (2026-11-03 itibarıyla)."""
    expected = {"dual_vol_break", "gk_vol_expansion", "buy_flow_dominance", "cmo_accel_break",
                "kaufman_er_trend", "multi_factor_alpha", "vp_vah_breakout", "vfi_zero_break",
                "nw_kernel_envelope", "cluc_wick_bounce", "cvd_absorption_wick", "turtle_donchian",
                "ttm_squeeze_fired", "vwap_mean_rev", "kdj_pure_dip"}
    assert {s["code"] for s in spot_monitor.ACTIVE_STRATEGIES} == expected


def test_removed_strategies_are_gone_from_code():
    """Kaldırılan stratejilerin kod izi kalmamalı (tarama kuralları dahil)."""
    src = inspect.getsource(spot_monitor.run_single_scan)
    for code in ("squeeze_breakout", "zlmacd_momentum", "stc_cycle",
                 "ema_bounce", "supertrend_pullback", "linreg_slope_turn",
                 "rvol_tod_spike"):
        assert f'strategy_code = "{code}"' not in src, f"{code} hâlâ taramada"


def test_strategy_toggle_defaults_all_enabled():
    """AKTİF/PASİF anahtarları (kalıcı) geri geldi: hiçbiri varsayılan pasif olmamalı.

    Paneldeki aç/kapa düğmeleri `set_strategy_enabled` ile DB'ye yazılır; koda
    gömülü varsayılan her strateji için AKTİF'tir (kullanıcı raporu 2026-11-04:
    "tarama yapmıyor" — kapatma listesi değil, NameError'dı; bu test yalnızca
    varsayılanın doğru olduğunu kilitler).
    """
    assert spot_monitor.DEFAULT_DISABLED_STRATEGIES == set()
    assert not hasattr(spot_monitor, "WATCHLIST_STRATEGIES")


def test_run_single_scan_defines_opens_before_dual_vol():
    """2026-11-04 NameError regresyonu: 2bec23a2 `_dual_vol_break(opens, ...)` ve
    `_gk_vol_expansion(opens, ...)` çağrılarını ekledi ama klines paketleme bloğunda
    `opens` tanımını unuttu → her tarama NameError ile çöküyor, last_scan_time hiç
    güncellenmiyordu (kullanıcı raporu: "Spot Monitor tarama yapmıyor"). Tanım,
    ilk kullanımdan ÖNCE bulunmalı."""
    src = inspect.getsource(spot_monitor.run_single_scan)
    idx_def = src.find("opens = [float(k[1])")
    idx_use = src.find("_dual_vol_break(opens")
    assert idx_def != -1, "run_single_scan içinde opens tanımı yok — tarama NameError ile çöker"
    assert idx_use != -1, "_dual_vol_break çağrısı kaybolmuş"
    assert idx_def < idx_use, "opens tanımı kullanımından sonra geliyor"


def test_dual_vol_and_gk_strategies_run_on_synthetic_klines():
    """Strateji fonksiyonları opens/highs/lows/closes ile beslenmeli; sorunsuz dönmeli.

    Her iki fonksiyon içte try/except ile None döner — bu test argüman sırasının
    yanlış geçilmesini (None) yakalar; NameError ise çağrı yerinde oluştuğu için
    yukarıdaki kaynak testi kilitler.
    """
    import random

    from app.technical_analysis import _dual_vol_break, _gk_vol_expansion

    rng = random.Random(7)
    n = 120
    opens_, highs, lows, closes, volumes = [], [], [], [], []
    px = 100.0
    for i in range(n):
        drift = 0.0 if i < n - 5 else 1.5   # son barlarda kırılım
        o = px
        c = px + drift + rng.uniform(-0.2, 0.2)
        h = max(o, c) + rng.uniform(0.05, 0.4)
        l = min(o, c) - rng.uniform(0.05, 0.4)
        opens_.append(o); highs.append(h); lows.append(l); closes.append(c); volumes.append(rng.uniform(100, 200))
        px = c
    dv = _dual_vol_break(opens_, highs, lows, closes)
    gk = _gk_vol_expansion(opens_, highs, lows, closes, volumes)
    assert isinstance(dv, dict) and "signal" in dv, "dual_vol_break None döndü (opens sırası bozuk olabilir)"
    assert isinstance(gk, dict) and "signal" in gk, "gk_vol_expansion None döndü (opens sırası bozuk olabilir)"


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
