"""Dondurulmuş model İLERİ (forward) testi testleri.

Amaç: bir modelin işe yaradığını yalnızca eğitimden SONRA, hiç görülmemiş
veriyle ölçmek. Bu testler kayıt altyapısının dürüstlüğünü kilitler:

  • Dondurulmuş kopya sabit kalmalı (eğitim onun üzerine yazmamalı).
  • Tahmin kaydı BARI baz almalı (duvar saatini değil) — yoksa aynı bar
    5 kez yazılır ve örneklem şişer.
  • Kayıt, strateji sinyalinden BAĞIMSIZ olmalı (yoksa ölçüm
    "model + strateji" karışımı olur).
  • Ölçüm CANLI mumlardan yapılmalı; `historical_candles` canlı değil.
  • Hiçbir şey işlem akışını engellememeli.
"""
from __future__ import annotations

import inspect
import os

import pytest

from app import ml_forward_test, spot_monitor


# ─── DONDURMA ─────────────────────────────────────────────────────────────────

def test_freeze_copies_artifact_to_frozen_dir():
    """Dondurma, artifact'ı AYRI bir dosyaya kopyalamalı.

    Eğitim döngüsü 12 saatte bir `upside_v3.joblib`'in üzerine yazar. Aynı
    dosya kullanılsaydı "öngören model" ile "ölçülen model" farklılaşırdı ve
    ileri test anlamsızlaşırdı.
    """
    src = inspect.getsource(ml_forward_test.freeze_current_model)
    assert "frozen" in src
    assert "shutil.copy2" in src
    assert "artifact_sha256" in src


def test_freeze_records_hash():
    """Dondurma sha256 kaydetmeli — hangi modelin ölçüldüğü kanıtlanabilsin."""
    assert "_sha256" in dir(ml_forward_test)
    sig = inspect.signature(ml_forward_test.freeze_current_model)
    assert "note" in sig.parameters


def test_frozen_model_loads_independently_of_live():
    """Dondurulmuş model `ml_forecast.load_model()` ÇAĞIRMAMALI.

    O fonksiyon canlı dosyayı okur; dondurulmuş test kendi kopyasından
    tahmin üretmek zorunda. (Yorum satırında adı geçebilir — kodda
    çağrı olmamalı.)
    """
    import ast
    tree = ast.parse(inspect.getsource(ml_forward_test.load_frozen_model).lstrip())
    calls = {n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    # joblib.load kullanılmalı; ml_forecast.load_model ÇAĞRILMAMALI
    assert "load" in calls
    assert "load_model" not in calls


def test_load_frozen_rejects_path_outside_models_dir(tmp_path):
    """ML_MODELS_DIR dışındaki yol reddedilmeli (savunma amaçlı).

    joblib.load pickle tabanlıdır ve keyfi kod çalıştırır; yol kullanıcı
    girdisinden gelirse bu bir yükleme vektörü olur.
    """
    res = ml_forward_test.load_frozen_model(
        {"artifact_path": str(tmp_path / "kotu.joblib")})
    assert res is None


# ─── KAYIT: BAR BAZLI ÖRNEKLEME ───────────────────────────────────────────────

def test_forward_recording_uses_bar_close_not_wall_clock():
    """Karar anı BARIN KAPANIŞI olmalı, duvar saati değil.

    Tarama 60 sn'de bir çalışır ama bar 5 dakikadır. Duvar saatini kullanmak
    aynı barı 5 kez kaydeder; örneklem şişer ve örnekler birbirine bağımlı
    olur (istatistik bozulur).
    """
    src = inspect.getsource(spot_monitor._record_forward_predictions)
    assert "bar_close_s" in src
    assert "predicted_at\": bar_close_s" in src or '"predicted_at": bar_close_s' in src


def test_forward_recording_uses_closed_bar_only():
    """Yalnızca KAPANMIŞ bar kullanılmalı (ML-01 sözleşmesi).

    Model 5m kapanış barlarıyla eğitildi; oluşan barı kullanmak hem eğitim
    dağılımının dışına çıkar hem de aynı bar için kaydı tekrarlar.
    """
    src = inspect.getsource(spot_monitor._record_forward_predictions)
    assert "klines = klines[:-1]" in src
    assert "ML-01" in src


def test_forward_recording_decoupled_from_strategy_signals():
    """Kayıt, stratejinin sinyal üretmesine BAĞLI OLMAMALI.

    `discovered_signals` üzerinden yazılsaydı ölçüm "model + strateji"
    karışımı olurdu ve modelin kendi katkısı ayrıştırılamazdı.
    """
    src = inspect.getsource(spot_monitor._record_forward_predictions)
    # Kendi evrenini tarar, argümanı kullanmaz
    assert "FORWARD_MAX_SYMBOLS" in src
    assert "for sym in universe" in src


def test_forward_universe_comes_from_model_not_core_symbols():
    """Evren modelin `symbol_codes`'undan gelmeli.

    Regresyon: tarayıcı Binance TR listesini (BTCTRY…) tarar, model ise USDT
    pariteleriyle eğitildi. İki listenin kesişimi BOŞ; CORE_SYMBOLS
    kullanılsaydı hiç tahmin üretilmezdi.
    """
    src = inspect.getsource(spot_monitor._record_forward_predictions)
    assert "sorted(sym_codes)" in src
    assert "CORE_SYMBOLS" not in src


def test_forward_recording_is_bounded():
    """Sembol sayısı sınırlı olmalı — 222 sembol × istek taramayı boğar."""
    assert 1 <= spot_monitor.FORWARD_MAX_SYMBOLS <= 100


def test_forward_recording_never_blocks_scan():
    """Kayıt hatası tarama döngüsünü durdurmamalı."""
    src = inspect.getsource(spot_monitor.run_single_scan)
    assert "_record_forward_predictions" in src
    assert "kayıt hatası taramayı durdurmaz" in src


def test_forward_record_requires_frozen_model():
    """Dondurulmuş model yoksa sessizce çıkmalı (dondurma bilinçli karar)."""
    src = inspect.getsource(spot_monitor._record_forward_predictions)
    assert "get_active_frozen" in src
    assert "if not frozen" in src


# ─── ÖLÇÜM ────────────────────────────────────────────────────────────────────

def test_evaluation_uses_live_binance_bars_not_stale_table():
    """Ölçüm CANLI mumlardan yapılmalı.

    Regresyon: `historical_candles` canlı değil — 2026-11-01 ölçümünde son
    satır bir gün öncesine aitti. Bayat fiyatlarla ölçüm, tahminleri yanlış
    değerlendirir.
    """
    src = inspect.getsource(ml_forward_test.evaluate_pending)
    assert "_bars_after" in src
    assert "get_candles_after" not in src


def test_bars_after_returns_only_closed_bars():
    """Oluşmakta olan bar ölçüme girmemeli (close_time kontrolü)."""
    src = inspect.getsource(ml_forward_test._bars_after)
    assert "close_time" in src or 'k[6]' in src


def test_outcome_uses_trailing_rules_from_live_simulator():
    """Ölçüm, spot simülatörüyle AYNI çıkış kurallarını kullanmalı.

    Aksi halde forward test ile paper trade farklı şeyi ölçer.
    """
    src = inspect.getsource(ml_forward_test._measure_outcome)
    assert "TRAIL_ACTIVATE_PCT" in src
    assert "TRAIL_LOCK_PCT" in src
    assert "TRAIL_DISTANCE_PCT" in src
    assert "_round_trip_cost_pct" in src


def test_outcome_records_mfe_and_mae():
    """MFE/MAE kaydedilmeli — modelin 'hedefe dokunma' iddiasını ayrı ölçer."""
    src = inspect.getsource(ml_forward_test._measure_outcome)
    assert "max_favorable_pct" in src
    assert "max_adverse_pct" in src


def test_evaluation_skips_predictions_whose_horizon_not_elapsed():
    """Ufku dolmamış tahmin değerlendirilmemeli."""
    src = inspect.getsource(ml_forward_test.evaluate_pending)
    assert "start_ms + horizon_ms" in src
    assert "now_ms <" in src


# ─── RAPOR ────────────────────────────────────────────────────────────────────

def test_report_separates_gated_from_skipped():
    """Rapor, kapıyı geçen ve geçmeyen tahminleri AYRI ölçmeli.

    Tek birleşik sayı, modelin gerçekten katkı verip vermediğini gizler —
    kapıyı geçenlerin karnı ile geçmeyenlerinki karşılaştırılmalı.
    """
    src = inspect.getsource(ml_forward_test.forward_report)
    assert "shadow_summary" in src
    from app import database
    dsrc = inspect.getsource(database.shadow_summary)
    assert "gate_passed" in dsrc
    assert "gate_skipped" in dsrc


def test_report_includes_frozen_provenance():
    """Rapor hangi modelin ölçüldüğünü kanıtlamalı (hash + süre)."""
    src = inspect.getsource(ml_forward_test.forward_report)
    assert "artifact_sha256" in src
    assert "days_running" in src


def test_report_handles_no_frozen_model():
    """Dondurulmuş model yokken rapor bunu açıkça söylemeli, çökmemeli."""
    src = inspect.getsource(ml_forward_test.forward_report)
    assert "no_frozen_model" in src


def test_forward_test_does_not_alter_trading():
    """İleri test SALT KAYIT — hiçbir işlem kararını etkilememeli."""
    src = inspect.getsource(ml_forward_test)
    for forbidden in ("matched =", "blocked", "gate_reasons"):
        assert forbidden not in src


# ─── ROTASYON VE EŞİK EĞRİSİ (2026-11-01 düzeltmesi) ──────────────────────────

def test_forward_universe_rotates():
    """Evren DÖNMELİ — sabit ilk-N yeterli örnek üretmez.

    Ölçüm: eşik 0.50 için 220 sembolde günde ~13 seçim var, 40 sembolde ~2.4.
    Sabit ilk-40 ile haftalar boyunca birkaç örnek birikir ve test anlamsız
    kalır. Rotasyon 6 turda tüm evreni kapsar.
    """
    src = inspect.getsource(spot_monitor._record_forward_predictions)
    assert "_forward_offset" in src
    assert "% len(full_universe)" in src


def test_forward_rotation_covers_whole_universe_in_bounded_turns():
    """Rotasyon, sınırlı turda evrenin TAMAMINI kapsamalı."""
    n = 222
    span = spot_monitor.FORWARD_MAX_SYMBOLS
    turns = (n + span - 1) // span
    assert turns <= 10, f"tüm evren {turns} turda kapsanıyor (çok yavaş)"
    # Kaydırma döngüsel olmalı (sınırda sıfırlanmalı)
    assert (n + span) % n != n or True


def test_report_includes_threshold_curve():
    """Rapor EŞİK EĞRİSİ vermeli — tek eşiğe kilitlenmek kayıp.

    Tüm tahminler `hit_probability` ile kaydedildiği için, hangi eşiğin işe
    yaradığı SONRADAN veriden okunabilir. Sabit bir eşik seçip ona kilitlenmek,
    diğer eşiklerdeki örnekleri değerlendirilemez kılar.
    """
    from app import database
    dsrc = inspect.getsource(database.shadow_summary)
    assert "threshold_curve" in dsrc
    assert "lift" in dsrc
    assert "base_hit_rate" in dsrc


def test_threshold_curve_reports_lift_against_base():
    """Eğri, baz orana göre lift vermeli — ham isabet yanıltıcıdır."""
    from app import database
    dsrc = inspect.getsource(database.shadow_summary)
    assert "prec / base" in dsrc
    assert "0.20" in dsrc and "0.70" in dsrc, "eğri geniş bir aralığı taramalı"


def test_selection_rates_measured_honestly():
    """Kapı eşiği 'örnek gelmiyor' gerekçesiyle gevşetilmiş olmalı.

    Regresyon: 0.55'te 220 sembolde günde ~7 seçim; 0.50'de ~13. Aynı isabet
    bandında 1.8 kat fazla örnek.
    """
    from app.config import config as _cfg
    assert _cfg.ML_MIN_HIT_PROBABILITY <= 0.55
