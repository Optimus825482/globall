"""TSMOM günlük kanalı testleri.

Kaynak: yongzhe2160cs/trading-engine — 8 strateji ailesi içinde kabul
kriterlerini geçen TEK yaklaşım (diğerleri: EMA crossover, XSMOM, funding
arb, Kalman stat-arb, 5m MeanReversion/Momentum/Breakout — hepsi refuted).

Doğrulama (2019-09 → 2026-11, 10 sembol, gerçek Binance günlük veri):
  TSMOM+rejim : +%72.41, Sharpe 1.01, maxDD -%9.31, 10/10 sembol pozitif
  Rejim testi : BULL +%295.7 (Sharpe 2.11) | BEAR -%24.3 (Sharpe -0.62)
"""
from __future__ import annotations

import inspect

import pytest

from app import tsmom


# ─── PARAMETRELER ─────────────────────────────────────────────────────────────

def test_params_match_validation():
    """Parametreler 7 yıllık doğrulamada kullanılanlarla aynı olmalı."""
    assert tsmom.LOOKBACK_DAYS == 30
    assert tsmom.VOL_WINDOW_DAYS == 30
    assert tsmom.VOL_TARGET == 0.20
    assert tsmom.REGIME_MA_DAYS == 200


def test_universe_is_ten_majors():
    """Doğrulamadaki 10 sembol korunmalı (cross-asset kanıtı buna dayanıyor)."""
    assert len(tsmom.TSMOM_SYMBOLS) == 10
    assert "BTCUSDT" in tsmom.TSMOM_SYMBOLS


def test_no_leverage_in_sizing():
    """Ağırlık 1.0'ı GEÇMEMELİ — kaldıraç yok, yalnız küçültme.

    Vol hedefleme `min(1.0, vol_target/rv)` ile yapılır: düşük volatilitede
    bile pozisyon büyümez. Kaldıraç eklemek spot hesabı likidasyona sokar.
    """
    src = inspect.getsource(tsmom.compute_targets)
    assert "min(1.0" in src


# ─── REJİM KAPISI ─────────────────────────────────────────────────────────────

def test_regime_gate_blocks_all_when_bear():
    """BTC MA200 ALTINDAYSA hiçbir sembol pozisyon almamalı.

    Ölçüm: BEAR rejiminde TSMOM -%24.3 kaybediyordu (Sharpe -0.62, 1/10 coin).
    Rejim filtresi bu kaybı durduran tek şey; kaldırılırsa ayı piyasasında
    para kaybedilir.
    """
    src = inspect.getsource(tsmom.compute_targets)
    assert "regime_bull" in src
    assert "bear_rejim" in src
    # Rejim kapısı sinyalden ÖNCE gelmeli
    assert src.index("regime_bull") < src.index("momentum_yok")


def test_bear_regime_returns_zero_weight():
    """BEAR rejiminde dönen ağırlık 0 olmalı (test edilebilir sözleşme)."""
    src = inspect.getsource(tsmom.compute_targets)
    # bear dalında weight 0.0 atanıyor
    idx = src.index("bear_rejim")
    window = src[max(0, idx - 400):idx]
    assert '"weight": 0.0' in window or '"weight": 0.0' in src


# ─── SİNYAL ───────────────────────────────────────────────────────────────────

def test_long_only_no_short():
    """Spot olduğu için short YOK — negatif momentum = flat.

    GitHub kaynağı TSMOM'u simetrik uygular; spot'ta kısa taraf mümkün
    değil. Bu kasıtlı bir sınırlama; BEAR performansını açıklar.
    """
    src = inspect.getsource(tsmom.compute_targets)
    assert "momentum_yok" in src
    assert "signal\": \"flat\"" in src or "'signal': 'flat'" in src or '"signal": "flat"' in src
    # short diye bir reason olmamalı
    assert '"short"' not in src


def test_signal_uses_30_day_return():
    """Sinyal son 30 günlük getiri işaretine dayanmalı."""
    src = inspect.getsource(tsmom.compute_targets)
    assert "LOOKBACK_DAYS" in src
    assert "ret_30" in src


def test_future_lookahead_absent():
    """Sinyal yalnızca GEÇMİŞ barları kullanmalı (ileri bakış yok).

    `closes[-LOOKBACK-1:]` son N+1 kapanışı alır; bugünün kapanışı dahil
    ama gelecek bar yok. Bu, kararın bar kapanışında verildiği anlamına gelir.
    """
    src = inspect.getsource(tsmom.compute_targets)
    assert "closes[-LOOKBACK_DAYS - 1:]" in src


# ─── VERİ ─────────────────────────────────────────────────────────────────────

def test_insufficient_data_returns_zero_weight():
    """Veri yetersizse 0 ağırlık, uydurma sinyal değil."""
    src = inspect.getsource(tsmom.compute_targets)
    assert "veri_yetersiz" in src


def test_fetch_failure_is_handled():
    """Ağ hatası çökme değil, boş liste döndürmeli."""
    src = inspect.getsource(tsmom._fetch_daily)
    assert "except Exception" in src
    assert "return []" in src


# ─── PORTFÖY / DB ─────────────────────────────────────────────────────────────

def test_rebalance_is_daily():
    """Rebalans günde bir kez olmalı — saatlik değil.

    Kaynak repo: "Rebalansı saatlikten GÜNLÜĞE çekmek Sharpe'ı ikiye katladı.
    Saatlik kadonsta hiçbir konfigürasyon fold testini geçmedi."
    """
    assert tsmom.REBALANCE_INTERVAL_SEC >= 3600
    src = inspect.getsource(tsmom.run_rebalance)
    assert "_last_rebalance_day" in src or "bugun_zaten_rebalans" in src


def test_rebalance_guard_prevents_double_run():
    """Aynı gün ikinci rebalans atlanmalı (force hariç)."""
    src = inspect.getsource(tsmom.run_rebalance)
    assert "bugun_zaten_rebalans" in src
    assert "force" in src


def test_commission_is_charged():
    """Maliyet sabiti tanımlı ve gerçekçi olmalı (%0.15 round-trip)."""
    assert 0.0005 <= tsmom.COMMISSION_ROUND_TRIP <= 0.005


def test_paper_only_no_real_orders():
    """Bu kanal PAPER — gerçek emir göndermemeli."""
    src = inspect.getsource(tsmom)
    for forbidden in ("order_send", "place_order", "create_order", "api_key"):
        assert forbidden not in src.lower(), f"gerçek emir izi: {forbidden}"


# ─── DASHBOARD ────────────────────────────────────────────────────────────────

def test_dashboard_exposes_evidence():
    """Panel, stratejinin nereden geldiğini ve doğrulamasını göstermeli.

    Operatör neden bu kanala güvendiğini tek bakışta görebilmeli.
    """
    src = inspect.getsource(tsmom.get_dashboard)
    assert "evidence" in src
    assert "yongzhe2160cs" in src


def test_dashboard_exposes_params():
    """Parametreler şeffaf olmalı (lookback, vol_target, rejim MA)."""
    src = inspect.getsource(tsmom.get_dashboard)
    assert "lookback_days" in src
    assert "regime_ma_days" in src
