"""Spot Monitor geri besleme döngüsü ve LLM ikinci görüş testleri.

İki parça kilitlenir:

1. **ML geri besleme.** `spot_monitor_signals` içindeki kapanmış paper işlemler
   modelin KENDİ strateji sonuçlarıdır; `ml_forecast` eğitimine girerler.
   Kritik detaylar: yeterli örnek yoksa kaynak atlanır (aşırı uyum kapısı),
   özellikler sinyal ANINDAKİ snapshot'tan gelir, etiket gerçekleşen getiridir
   (MFE değil), ve kronolojik holdout'a sızılmaz.

2. **LLM ikinci görüş.** Forex'teki dossier deseni spot'a uyarlandı; ama
   İŞLEM ENGELLEMEZ, yalnızca kayıt üretir.
"""
from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from app import spot_monitor, spot_llm_review


# ─── SPOT GERİ BESLEME DÖNGÜSÜ ────────────────────────────────────────────────

def _spot_row(i, sym="BTCUSDT", pnl=1.2, status="WIN_TRAILING", with_snapshot=True):
    details = {}
    if with_snapshot:
        details["ml_features"] = {
            "timestamp": 1761991200000 + i * 300000,
            "ret1_pct": 0.1, "ret3_pct": 0.35, "ret5_pct": 0.5, "atr_pct": 1.4,
            "bb_width_pct": 2.1, "rsi": 45.0, "mfi": 52.0, "vol_z": 0.3,
            "linreg_slope10_pct": 0.08, "aroon_up": 60.0, "aroon_down": 30.0,
        }
    return {
        "id": i, "signal_key": f"{sym}-5m-{i}", "symbol": sym, "timeframe": "5m",
        "strategy": "kdj_pure_dip", "status": status, "pnl_pct": pnl,
        "mfe_pct": abs(pnl) * 1.3, "mae_pct": -0.4, "net_pnl_try": pnl * 5,
        "detected_at": "2026-11-01T10:00:00+00:00", "details": details,
    }


def test_spot_samples_empty_below_min_threshold():
    """Eşik altında BOŞ dönmeli — az örnekle öğrenmek aşırı uyum üretir.

    Cılız bir kaynağın modeli saptırmasına izin vermek, hiç öğrenmemekten
    kötüdür; bu yüzden kaynak tamamen atlanır.
    """
    rows = [_spot_row(i) for i in range(20)]
    X, *_ = spot_monitor.ml_forecast.prepare_spot_samples(
        rows, {"BTCUSDT": 0}, min_samples=200)
    assert X.shape[0] == 0


def test_spot_samples_returned_above_threshold():
    """Eşik üstünde örnekler kurulmalı ve özellik şemasıyla uyuşmalı."""
    mf = spot_monitor.ml_forecast
    rows = [_spot_row(i, "BTCUSDT" if i % 2 else "ETHUSDT",
                      1.2 if i % 3 else -0.9) for i in range(250)]
    X, y, y_hit, hids, w, ts = mf.prepare_spot_samples(
        rows, {"BTCUSDT": 0, "ETHUSDT": 1}, min_samples=200)
    assert X.shape == (250, len(mf.FEATURE_NAMES))
    assert len(y) == len(y_hit) == len(hids) == len(w) == len(ts) == 250


def test_spot_samples_drop_rows_without_snapshot():
    """`ml_features` snapshot'ı olmayan satır kurulamaz → elenmeli.

    Sıfır uydurmak modele gürültü enjekte ederdi; journal yolundaki ML-09
    kuralının spot karşılığı budur.
    """
    mf = spot_monitor.ml_forecast
    rows = [_spot_row(i, with_snapshot=False) for i in range(250)]
    X, *_ = mf.prepare_spot_samples(rows, {"BTCUSDT": 0}, min_samples=200)
    assert X.shape[0] == 0


def test_spot_samples_drop_unknown_symbols():
    """Eğitim evreninde olmayan sembol modele giremez (kod eşlemesi yok)."""
    mf = spot_monitor.ml_forecast
    rows = [_spot_row(i, "ZZZUSDT") for i in range(250)]
    X, *_ = mf.prepare_spot_samples(rows, {"BTCUSDT": 0}, min_samples=200)
    assert X.shape[0] == 0


def test_spot_samples_dedupe_by_signal_key():
    """Aynı signal_key tekrar ederse tek örnek sayılmalı."""
    mf = spot_monitor.ml_forecast
    rows = [_spot_row(1) for _ in range(250)]
    X, *_ = mf.prepare_spot_samples(rows, {"BTCUSDT": 0}, min_samples=1)
    assert X.shape[0] == 1


def test_spot_samples_skip_open_positions():
    """Açık pozisyonun sonucu yoktur — eğitime girmemeli."""
    mf = spot_monitor.ml_forecast
    rows = [_spot_row(i, status="OPEN") for i in range(250)]
    X, *_ = mf.prepare_spot_samples(rows, {"BTCUSDT": 0}, min_samples=200)
    assert X.shape[0] == 0


def test_spot_samples_skip_rows_without_pnl():
    """Sonuçlanmamış (pnl None) satır etiketlenemez."""
    mf = spot_monitor.ml_forecast
    rows = [_spot_row(i) for i in range(250)]
    for r in rows:
        r["pnl_pct"] = None
    X, *_ = mf.prepare_spot_samples(rows, {"BTCUSDT": 0}, min_samples=200)
    assert X.shape[0] == 0


def test_spot_hit_label_discriminates():
    """Sınıflandırıcı etiketi AYIRT EDİCİ olmalı — daima 0 olursa model öğrenemez.

    Regresyon: etiket eşiği journal'ınkiyle (5dk → %2.0) ödünç alınmıştı.
    Spot geometrisi kâr %1.5'te takipçiyi devreye sokup %0.8'i kilitlediği
    için işlemlerin neredeyse tamamı %2.0'a ulaşamadan kapanır ve etiket
    DAİMA 0 olurdu — sessiz no-signal. Spot eşiği ayrı tutulur.
    """
    mf = spot_monitor.ml_forecast
    from app.config import config as _cfg
    assert _cfg.ML_SPOT_HIT_TARGET_PCT != _cfg.ML_HIT_TARGET_PCT[5]

    rows = [_spot_row(i, pnl=(2.5 if i % 4 == 0 else (-0.9 if i % 3 == 0 else 0.5)))
            for i in range(400)]
    _, _, y_hit, *_ = mf.prepare_spot_samples(rows, {"BTCUSDT": 0}, min_samples=200)
    pos_rate = float(y_hit.mean())
    assert 0.0 < pos_rate < 1.0, f"etiket ayırt edici değil (pozitif oran {pos_rate})"


def test_spot_hit_threshold_aligns_with_trailing_activation():
    """Spot etiket eşiği, takipçinin devreye girdiği seviyeyle hizalı olmalı.

    İkisi ayrı modüllerde tutuluyor (config ↔ spot_monitor); bu test
    sessiz kaymayı yakalar.
    """
    from app.config import config as _cfg
    assert _cfg.ML_SPOT_HIT_TARGET_PCT == pytest.approx(
        spot_monitor.TRAIL_ACTIVATE_PCT / 100.0, abs=1e-9)


def test_spot_regression_target_is_realized_pnl_not_mfe():
    """Regresyon etiketi işlemin GERÇEKLEŞEN getirisi olmalı.

    `mfe_pct` genelde `pnl_pct`'ten büyüktür; stop'ta kapanan bir işlem
    'yüksek MFE gördüm' gibi görünüp modeli yanıltırdı.
    """
    mf = spot_monitor.ml_forecast
    rows = [_spot_row(i, pnl=1.5) for i in range(250)]
    _, y, *_ = mf.prepare_spot_samples(rows, {"BTCUSDT": 0}, min_samples=200)
    assert float(y[0]) == pytest.approx(0.015, abs=1e-6), "yüzde→kesir çevrilmeli"
    assert float(y[0]) != pytest.approx(float(rows[0]["mfe_pct"]) / 100.0)


def test_spot_weight_is_below_journal_weight():
    """Spot örneği journal'dan düşük ağırlık almalı.

    Journal ölçülmüş LLM tahminidir (pekiştirme); spot satırı stratejinin
    gerçekleşen sonucudur ama tek gözlemdir.
    """
    from app.config import config as _cfg
    assert _cfg.ML_SPOT_SAMPLE_WEIGHT <= _cfg.ML_JOURNAL_SAMPLE_WEIGHT


def test_train_accepts_spot_rows_and_records_count():
    """`train` spot kaynağını kabul etmeli ve sayısını rapora yazmalı."""
    src = inspect.getsource(spot_monitor.ml_forecast.train)
    assert "spot_rows" in src
    assert "prepare_spot_samples" in src
    assert "spot_sample_count" in src


def test_spot_samples_never_leak_into_holdout():
    """Spot geri beslemesi kronolojik kurala tabi olmalı (holdout'a sızmamalı).

    Aksi halde modelin ölçümü kendi eğitim verisini görür ve metrik iyimser
    çıkar — bu projede daha önce yakalanmış bir hata sınıfıdır (ML-02).
    """
    src = inspect.getsource(spot_monitor.ml_forecast.train)
    assert "spot_mask" in src
    assert "spot_ts <= train_cutoff_ms" in src


def test_run_ml_training_passes_spot_rows():
    """Eğitim döngüsü spot kaynağını gerçekten okumalı ve iletmeli."""
    import app.main as main_mod
    src = inspect.getsource(main_mod.run_ml_training)
    assert "get_spot_training_samples" in src
    assert "spot_rows" in src
    # Spot okuması başarısız olsa bile eğitim durmamalı
    assert "except Exception" in src


def test_signal_details_persist_ml_feature_snapshot():
    """Sinyal kaydı `details.ml_features` taşımalı — geri beslemenin tek kaynağı.

    İşlem kapandığında bar verisi kaymış olur; özellikler sinyal anında
    yakalanmazsa o örnek sonsuza dek kurtarılamaz.
    """
    src = inspect.getsource(spot_monitor.run_single_scan)
    assert '"ml_features": ml_features' in src
    assert "ml_features = {" in src


# ─── LLM İKİNCİ GÖRÜŞ (kayıt amaçlı, engellemesiz) ────────────────────────────

def test_spot_llm_review_never_blocks():
    """Spot LLM incelemesi işlemi ENGELLEMEMELİ — yalnızca kayıt üretmeli.

    Doğrulanmamış bir yargıcı işlem akışına bağlamak ölçülmüş kanıta aykırı:
    22 özellikli AI kapı dürüst walk-forward'da bazı yenemedi (-0.25% vs
    -0.13%). Önce gölge kayıt, sonra kapı.
    """
    src = inspect.getsource(spot_monitor._attach_llm_reviews)
    assert "llm_review" in src
    assert "blocked" not in src


def test_attach_reviews_returns_zero_for_empty_input():
    """Boş kuyrukta hızlı çıkmalı (DB/LLM çağrısı yapılmamalı)."""
    spot_monitor._pending_reviews.clear()
    assert asyncio.run(spot_monitor._attach_llm_reviews([])) == 0


def test_review_queue_is_deduped():
    """Aynı sinyal kuyruğa iki kez girmemeli (mükerrer LLM çağrısı = para)."""
    spot_monitor._pending_reviews.clear()
    spot_monitor._queue_llm_reviews([1, 2, 2, 3, 1])
    assert spot_monitor._pending_reviews == [1, 2, 3]
    spot_monitor._pending_reviews.clear()


def test_review_queue_does_not_block_scan_loop():
    """Kuyruk tarama döngüsünü BLOKE ETMEMELİ.

    LLM çağrısı 12 sn'ye kadar sürer ve tarama 60 sn'de bir çalışır. Aynı anda
    5 pozisyon kapanırsa seri inceleme döngüyü doldurur ve fiyat takibi
    (asıl iş) gecikir. Bu yüzden kapanış yolu yalnızca KUYRUĞA yazar; gerçek
    inceleme ayrı adımda, sınırlı sayıda yapılır.
    """
    src = inspect.getsource(spot_monitor.run_single_scan)
    # Tarama içinde çağrı kuyruklama olmalı, inceleme değil
    assert "_queue_llm_reviews(closed_ids)" in src
    assert "await _attach_llm_reviews" not in src


def test_review_batch_is_bounded_per_cycle():
    """Her turda sınırlı sayıda inceleme yapılmalı (gecikme tavanı)."""
    assert 1 <= spot_monitor.SPOT_LLM_MAX_REVIEWS_PER_SCAN <= 10


def test_background_loop_drains_queue_outside_scan():
    """Kuyruk boşaltma tarama döngüsünün içinde, tarama SONRASI olmalı."""
    src = inspect.getsource(spot_monitor.spot_monitor_background_loop)
    assert "_attach_llm_reviews" in src
    # Tarama çağrısından sonra gelmeli
    assert src.index("run_single_scan") < src.index("_attach_llm_reviews")


def test_dossier_declares_no_take_profit():
    """Dossier `tp_pct: None` + trailing açıklaması taşımalı.

    Forex istemindeki kripto notuyla aynı gerekçe: LLM'in 'hedef eksik'
    diye olumsuz yargı vermesini engellemek.
    """
    d = spot_llm_review.build_spot_dossier({
        "symbol": "BTCTRY", "timeframe": "5m", "entry_price": 100.0,
        "sl_pct": 0.9, "rsi": 45.0, "atr_pct": 1.2,
    })
    assert d["tp_pct"] is None
    assert "takipçi" in d["exit_model"].lower()


def test_system_prompt_warns_about_missing_tp():
    """İstem, TP'sizliğin eksiklik OLMADIĞINI açıkça söylemeli."""
    p = spot_llm_review.SYSTEM_PROMPT
    assert "SABİT KÂR HEDEFİ" in p or "hedef" in p.lower()
    assert "EKSİKLİK" in p.upper() or "eksiklik" in p


def test_dossier_omits_none_fields():
    """None alanlar istemi şişirmemeli — yalnızca dolu göstergeler kalmalı."""
    d = spot_llm_review.build_spot_dossier({"symbol": "BTCTRY", "rsi": 45.0})
    assert d["gostergeler"], "rsi dolu olduğu için bölüm boş olmamalı"
    assert all(v is not None for v in d["gostergeler"].values())
    assert "adx" not in d["gostergeler"]


def test_dossier_includes_ml_block_only_when_present():
    """Gerçek ML tahmini varsa dossier'e girmeli (en değerli bağlam)."""
    without = spot_llm_review.build_spot_dossier({"symbol": "BTCTRY"})
    assert "ml_modeli" not in without
    with_ml = spot_llm_review.build_spot_dossier(
        {"symbol": "BTCTRY", "ml_hit_probability": 0.71, "ml_target_pct": 1.9})
    assert with_ml["ml_modeli"]["hedefe_dokunma_olasiligi"] == pytest.approx(0.71)


def test_dossier_includes_closed_trade_result():
    """Kapanan işlem bağlamı (sonuç + net TL) LLM'e verilmeli."""
    d = spot_llm_review.build_spot_dossier({
        "symbol": "BTCTRY",
        "recent_results": {"sonuc": "WIN_TRAILING", "net_pnl_try": 12.4, "pnl_pct": 2.1},
    })
    assert d["sembol_gecmisi"]["net_pnl_try"] == pytest.approx(12.4)


def test_parse_review_accepts_valid_json():
    out = spot_llm_review._parse_review(
        'İnceleme: {"verdict":"TEMKIN","confidence":0.6,'
        '"gerekce":"RSI yuksek","risk":"gec giris"}')
    assert out["verdict"] == "TEMKIN"
    assert out["confidence"] == pytest.approx(0.6)


def test_parse_review_extracts_json_from_prose():
    """Model JSON'u düz metne gömerse de çıkarılmalı."""
    out = spot_llm_review._parse_review(
        'Degerlendirmem: ```json\n{"verdict":"ONAY","confidence":0.8,'
        '"gerekce":"trend uyumlu","risk":"dusuk"}\n``` bitti.')
    assert out["verdict"] == "ONAY"


@pytest.mark.parametrize("text", [
    "",
    "JSON yok",
    '{"verdict":"BILINMEYEN"}',
    '{"confidence":0.5}',
    "{bozuk json",
    "[]",
])
def test_parse_review_rejects_bad_responses(text):
    """Bozuk/eksik LLM yanıtı None dönmeli — uydurma karar üretilmemeli."""
    assert spot_llm_review._parse_review(text) is None


def test_parse_review_clamps_confidence():
    """0-1 dışı güven değeri kırpılmalı, çökmemeli."""
    out = spot_llm_review._parse_review(
        '{"verdict":"ONAY","confidence":7.5,"gerekce":"x","risk":"y"}')
    assert out["confidence"] == pytest.approx(1.0)


def test_review_signal_returns_none_on_llm_failure(monkeypatch):
    """LLM hatası işlemi durdurmamalı; inceleme sessizce None olmalı."""
    async def boom(*a, **kw):
        raise RuntimeError("LLM yok")
        yield  # pragma: no cover

    monkeypatch.setattr(spot_llm_review.llm_analysis, "stream_chat", boom)
    assert asyncio.run(spot_llm_review.review_signal({"symbol": "BTCTRY"})) is None


def test_review_signal_returns_none_on_timeout(monkeypatch):
    """Zaman aşımı da sessiz None olmalı — inceleme bonus, zorunluluk değil."""
    async def slow(*a, **kw):
        await asyncio.sleep(5)
        yield  # pragma: no cover

    monkeypatch.setattr(spot_llm_review.llm_analysis, "stream_chat", slow)
    assert asyncio.run(spot_llm_review.review_signal({"symbol": "BTCTRY"},
                                                    timeout=0.05)) is None


def test_review_signal_parses_streamed_deltas(monkeypatch):
    """Akış delta'ları birleştirilip ayrıştırılmalı (chat() değil stream_chat)."""
    async def stream(snapshot, messages, **kw):
        yield {"event": "delta", "data": {"text": '{"verdict":"KARSI",'}}
        yield {"event": "delta", "data": {"text": '"confidence":0.9,'}}
        yield {"event": "delta", "data": {"text": '"gerekce":"hacimsiz","risk":"fakeout"}'}}
        yield {"event": "done", "data": {"model": "test-model"}}

    monkeypatch.setattr(spot_llm_review.llm_analysis, "stream_chat", stream)
    res = asyncio.run(spot_llm_review.review_signal({"symbol": "BTCTRY"}))
    assert res["verdict"] == "KARSI"
    assert res["model"] == "test-model"
    assert "at" in res


# ─── EĞİTİM METRİKLERİ: AUC, PRECISION, LIFT ──────────────────────────────────

def test_metrics_report_auc_and_lift_not_accuracy():
    """Eğitim metrikleri AUC + precision + lift raporlamalı.

    Regresyon: yalnızca accuracy raporlanıyordu. Hedef oranı %3 olan dengesiz
    veride "daima 0" demek %96 doğruluk verir; model tam olarak bunu yapıyordu
    (acc=0.9965) ve rapor "model bozuk" izlenimi veriyordu. Oysa AUC 0.88.
    Doğru okuma seçicilik: kaç seçti, kaçı tuttu, baz oranın kaç katı.
    """
    src = inspect.getsource(spot_monitor.ml_forecast.train)
    assert "model_auc" in src
    assert "precision_at_gate" in src
    assert "lift_at_gate" in src
    assert "roc_auc_score" in src
    # Accuracy yanıltıcı olduğu için not düşülmüş olmalı
    assert "YANILTICI" in src or "yaniltici" in src.lower()


def test_gate_probability_config_exists():
    """Kapı olasılık eşiği config'te tanımlı olmalı ve makul aralıkta."""
    from app.config import config as _cfg
    assert 0.05 <= _cfg.ML_MIN_HIT_PROBABILITY <= 0.95


def test_lookback_and_bar_limit_were_raised():
    """Lookback ve bar sınırı ölçüme dayalı yükseltilmiş olmalı.

    Ölçüm (2026-11-01): DB'de 222 sembol × ~9.150 bar (5m), 41.9 gün kapsıyor.
    Eski 10 gün / 3.000 bar ayarı bunun yalnızca dörtte birini kullanıyordu.
    """
    from app.config import config as _cfg
    assert _cfg.ML_TRAIN_LOOKBACK_DAYS >= 30
    assert _cfg.ML_MAX_BARS_PER_SYMBOL >= 10000
