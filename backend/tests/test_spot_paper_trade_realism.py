"""Spot Monitor paper-trade simülatörü — gerçekçilik ve AI kapı testleri.

Bu testler üç kanıtlanmış kusuru kilitler:

1. **Muhafazakâr bariyer sırası.** 60 saniyelik taramada TP ve SL arasına sığan
   hareketlerde hangisinin önce vurulduğu bilinemez. Simülatör önceden TP'yi
   önce kontrol ediyordu (iyimser sapma). Artık ikisi de aşılmışsa SL kazanır —
   `.agents/skills/spot-strategy-lab/SKILL.md` §1.3 kuralı.
2. **Gap-down modeli.** SL'de `exit_price = stop_p` yazmak, stop seviyesinin
   altında açılan bir barda kaybı olduğundan az gösteriyordu.
3. **AI kapıları + gerçek göstergeler.** `qlib`/`jesse` sabit `rsi=55.0` ve
   `atr=price*0.015` ile çağrılıyordu; skorlar bilgi taşımıyor ve hiçbiri
   işlemi engellemiyordu.
"""
from __future__ import annotations

import asyncio
import pytest

from app import spot_monitor
from app.spot_monitor import (
    COMMISSION_SCHEDULES,
    _atr_percentiles,
    _break_even_wr,
    _clamp_with_atr,
    _one_way_fee,
    _round_trip_cost_pct,
)


# ─── ÜCRET MATEMATİĞİ ──────────────────────────────────────────────────────────

def test_fee_schedules_cover_both_bnb_states():
    """BNB indirimli ve standart ücret senaryoları tanımlı olmalı."""
    assert set(COMMISSION_SCHEDULES) == {"bnb", "base"}
    assert COMMISSION_SCHEDULES["bnb"]["one_way"] == 0.00075
    assert COMMISSION_SCHEDULES["base"]["one_way"] == 0.00100


def test_bnb_round_trip_is_015_pct(monkeypatch):
    """BNB modunda round-trip %0.15 — lab sonuçlarının varsayımı."""
    monkeypatch.setattr(spot_monitor, "FEE_MODE", "bnb")
    assert _round_trip_cost_pct() == pytest.approx(0.15, abs=1e-9)


def test_base_round_trip_is_020_pct(monkeypatch):
    """Standart modda round-trip %0.20 — BNB kullanmayan kullanıcının gerçeği."""
    monkeypatch.setattr(spot_monitor, "FEE_MODE", "base")
    assert _round_trip_cost_pct() == pytest.approx(0.20, abs=1e-9)


def test_unknown_fee_mode_falls_back_to_bnb(monkeypatch):
    monkeypatch.setattr(spot_monitor, "FEE_MODE", "yok-boyle-bir-sey")
    assert _one_way_fee() == COMMISSION_SCHEDULES["bnb"]["one_way"]


@pytest.mark.parametrize(
    "tp,sl,cost,expected",
    [
        # 5m canlı varsayılan
        (1.4, 0.9, 0.08, 42.61),
        (1.4, 0.9, 0.15, 45.65),
        (1.4, 0.9, 0.20, 47.83),
        # 15m
        (2.2, 1.1, 0.08, 35.76),
        (2.2, 1.1, 0.20, 39.39),
        # 1h
        (3.2, 1.6, 0.08, 35.00),
        (3.2, 1.6, 0.20, 37.50),
        # Optimizer'ın squeeze önerisi
        (1.0, 1.5, 0.15, 66.00),
        (1.0, 1.5, 0.20, 68.00),
    ],
)
def test_break_even_wr_matches_cost_model(tp, sl, cost, expected):
    """Basabas WR = (SL+maliyet) / (TP+SL).

    Yüksek kazanma oranı tek başına kâr değildir — eşiği TP/SL asimetrisi
    ve maliyet belirler.
    """
    assert _break_even_wr(tp, sl, cost) == pytest.approx(expected, abs=0.02)


def test_break_even_wr_rises_with_cost():
    """Maliyet arttıkça basabas eşiği yükselmeli (edge daralır)."""
    assert _break_even_wr(1.4, 0.9, 0.20) > _break_even_wr(1.4, 0.9, 0.15)
    assert _break_even_wr(1.4, 0.9, 0.15) > _break_even_wr(1.4, 0.9, 0.08)


def test_better_payoff_ratio_lowers_break_even_wr():
    """Ödeme oranı iyileştikçe (TP büyür / SL küçülür) basabas WR düşer.

    TP1.4/SL0.9 (1.56:1) → %45.65. TP1.0/SL1.5 (0.67:1) → %66.00.
    Optimizer geniş stopu SEÇTİĞİ için basabas eşiği YÜKSELDİ; kazancı
    gözlenen WR'nin (OOS %66.1) de yükselmesinden geliyor, eşiğin
    düşmesinden değil.
    """
    assert _break_even_wr(1.0, 1.5, 0.15) > _break_even_wr(1.4, 0.9, 0.15)


# ─── SQUEEZE BREAKOUT OVERRIDE ─────────────────────────────────────────────────

def test_squeeze_breakout_has_5m_override_from_optimizer():
    """spot_tpsl_optimizer.json çıktısı koda girmiş olmalı: TP 1.0 / SL 1.5."""
    strat = next(s for s in spot_monitor.ACTIVE_STRATEGIES if s["code"] == "squeeze_breakout")
    override = strat["tp_sl_override"]["5m"]
    assert override["tp_pct"] == 1.0
    assert override["sl_pct"] == 1.5


def _expectancy(wr: float, tp_pct: float, sl_pct: float, cost_pct: float) -> float:
    """İşlem başına beklenen net getiri (% olarak, pozisyon büyüklüğüne göre).

    Kazanç TP−maliyet, kayıp SL+maliyet. wr 0-1 arası.
    """
    net_win = max(tp_pct - cost_pct, 0.0)
    net_loss = sl_pct + cost_pct
    return wr * net_win - (1.0 - wr) * net_loss


def test_squeeze_override_edge_is_cost_sensitive():
    """Optimizer önerisinin kârlılığı ücret senaryosuna BAĞIMLI olmalı.

    OOS WR %66.1 ve basabas %66.0 neredeyse üst üste. Sonuç:
      %0.08 maliyette  → +0.073/birim  (kârlı)
      %0.15 maliyette  → +0.003/birim  (başabaş — edge'in tamamı komisyona gidiyor)
      %0.20 maliyette  → -0.047/birim  (ZARARLI)

    Yani optimizer'ın TP1.0/SL1.5 sonucu "kesin düzeltme" değil; yalnızca
    BNB indirimi altında ve sıfıra yakın bir edge. Bu yüzden kod bu override'ı
    uygular AMA ücret modu da yapılandırılabilir olmak zorundadır.
    """
    wr = 0.661
    cheap = _expectancy(wr, 1.0, 1.5, 0.08)
    bnb = _expectancy(wr, 1.0, 1.5, 0.15)
    base = _expectancy(wr, 1.0, 1.5, 0.20)

    assert cheap > 0, "lab maliyetinde pozitif olmalı"
    assert abs(bnb) < 0.02, "BNB indiriminde başabaşa çok yakın olmalı"
    assert base < 0, "standart ücrette zarara dönmeli"

    # Gerçekten bu sıralamada mı, aritmetiği kilitliyoruz
    assert cheap > bnb > base


def test_overridden_geometry_breaks_boundary_mixed_status():
    """Optimizer'ın TP1.0/SL1.5 önerisi sınırdadır: OOS PF 1.47 (kârlı) ama
    basabas WR ile neredeyse eşit. Bu, öneriyi 'uygula ve izle' konumunda tutar,
    'güvenli' değil.
    """
    be_bnb = _break_even_wr(1.0, 1.5, 0.15)
    assert be_bnb == pytest.approx(66.0, abs=0.1)
    # OOS WR %66.1 — basabas %66.0'ın hemen üstünde, marj %0.1 puan
    assert 0.0 < (66.1 - be_bnb) < 1.0


def test_strategy_override_map_is_built_from_active_strategies():
    """STRATEGY_TPSL_OVERRIDE, ACTIVE_STRATEGIES ile senkron kalmalı."""
    assert spot_monitor.STRATEGY_TPSL_OVERRIDE["squeeze_breakout"]["5m"]["tp_pct"] == 1.0


# ─── ATR TABANLI HEDEF ÖLÇEKLEME ───────────────────────────────────────────────

def test_atr_percentiles_returns_nonzero_for_moving_series():
    """Hareket eden seride ATR yüzdesi SIFIRDAN BÜYÜK olmalı.

    Regresyon: ilk sürümde ardışık fark yerine `window[j] - window[:-1][j]`
    yazılmıştı; bu her zaman 0'a eşit olduğu için ATR yüzdesi daima 0
    dönüyordu ve ATR-kısıtı hiç devreye girmiyordu (sessiz no-op).
    """
    closes = [100.0 + (i % 7) * 0.5 for i in range(120)]
    median, p75 = _atr_percentiles(closes)
    assert median > 0.0, "hareket eden seride medyan ATR yüzdesi 0 olmamalı"
    assert p75 > 0.0
    assert median <= p75


def test_atr_percentiles_scale_with_volatility():
    """Daha oynak seri daha yüksek ATR yüzdesi üretmeli."""
    calm = [100.0 + (i % 3) * 0.01 for i in range(120)]
    wild = [100.0 + (i % 3) * 2.00 for i in range(120)]
    calm_m, _ = _atr_percentiles(calm)
    wild_m, _ = _atr_percentiles(wild)
    assert wild_m > calm_m > 0.0


def test_atr_percentiles_empty_series_is_safe():
    assert _atr_percentiles([]) == (0.0, 0.0)
    assert _atr_percentiles([100.0]) == (0.0, 0.0)


def test_atr_percentiles_flat_series_is_zero():
    """Sabit fiyatta volatilite yok → ATR yüzdesi 0 (ve kısıt devre dışı kalır)."""
    assert _atr_percentiles([100.0] * 60) == (0.0, 0.0)


def test_clamp_is_not_silently_disabled_by_zero_atr():
    """ATR yüzdesi 0 dönerse kısıt sessizce devre dışı kalır — bunu kilitle.

    p75=0 iken `_clamp_with_atr` no-op olmalı (guard'ı kanıtlıyor), ve
    `_atr_percentiles` gerçek seride 0 DÖNMEMELİ (yukarıdaki test).
    """
    tp, sl, note = _clamp_with_atr(1.0, 1.5, 0.05, 0.0, 0.0)
    assert (tp, sl) == (1.0, 1.5)
    assert note == ""


def test_atr_clamp_is_disabled_by_default():
    """ATR kısıtı VALİDE EDİLMEDİĞİ için canlı taramada kapalı olmalı.

    Canlı veriyle denendiğinde 8 sembolün 7'sinde tetikleniyordu — yani
    "nadir güvenlik ağı" değil, sürekli aktif bir TP/SL değiştiricisi.
    Parametreleri tahminle seçildi, walk-forward yok. Açık bırakmak, araştırma
    raporunun uyardığı "doğrulanmamış parametre" tuzağı olurdu.
    """
    assert spot_monitor.ATR_CLAMP_ENABLED is False
    tp, sl, note = _clamp_with_atr(1.4, 0.9, 5.0, 0.02, 0.025)
    assert (tp, sl) == (1.4, 0.9), "kapalıyken hiçbir koşulda değiştirmemeli"
    assert note == ""


def test_atr_clamp_works_when_explicitly_enabled():
    """Mekanizma doğru çalışmalı — açıldığında test edilebilir olmalı."""
    tp, sl, note = _clamp_with_atr(1.4, 0.9, 0.20, 0.038, 0.053, enabled=True)
    assert tp < 1.4 and sl < 0.9
    assert "ATR-kisit" in note


def test_atr_clamp_triggers_only_on_volatility_explosion():
    """Açıkken yalnızca ATR, p75'in 1.5 KATINI aşınca çalışmalı."""
    tp, sl, note = _clamp_with_atr(1.4, 0.9, 0.055, 0.038, 0.053, enabled=True)
    assert (tp, sl) == (1.4, 0.9), "p75 civarında kısıt uygulanmamalı"
    assert note == ""


def test_atr_clamp_is_noop_when_atr_normal():
    """Volatilite normal seviyedeyse kanıtlanmış TP/SL geometrisi KORUNMALI."""
    tp, sl, note = _clamp_with_atr(
        tp_pct=1.0, sl_pct=1.5,
        atr_pct_now=0.015, atr_median=0.02, atr_p75=0.025,
        enabled=True,
    )
    assert (tp, sl) == (1.0, 1.5)
    assert note == ""


def test_atr_clamp_tightening_is_bounded():
    """Daraltma asla %25'i aşmamalı — hedef komisyon gürültüsüne inmemeli.

    Ölçeksiz oran (p75/atr_now) ile TP 1.40 → 0.72'ye düşüyordu; bu,
    kanıtlanmış geometriyi bozar ve hedefi basabas eşiğinin içine sokar.
    """
    tp, sl, _ = _clamp_with_atr(1.4, 0.9, 100.0, 0.001, 0.002, enabled=True)
    assert tp >= 1.4 * 0.75 - 1e-9, f"TP {tp} %25'ten fazla daraltılmamalı"
    assert sl >= 0.9 * 0.75 - 1e-9


def test_atr_clamp_only_tightens_never_widens():
    """Kısıt asla hedefi BÜYÜTMEMELİ — aşağı yönlü kısıt stratejiyi bozar."""
    for atr_now in (0.001, 0.01, 0.03, 0.10, 0.5, 5.0):
        tp, sl, _ = _clamp_with_atr(1.0, 1.5, atr_now, 0.02, 0.025, enabled=True)
        assert tp <= 1.0 + 1e-9
        assert sl <= 1.5 + 1e-9


def test_atr_clamp_respects_floor():
    """Aşırı daralma hedefleri işe yaramaz seviyeye indirmemeli."""
    tp, sl, _ = _clamp_with_atr(0.5, 0.5, 100.0, 0.001, 0.002, enabled=True)
    assert tp >= 0.3
    assert sl >= 0.2


def test_atr_clamp_disabled_on_degenerate_inputs():
    """Sıfır/eksik ATR dağılımında kısıt devre dışı kalmalı, çökmemeli."""
    for args in ((0.05, 0.0, 0.0), (0.05, 0.02, 0.0), (0.0, 0.02, 0.025)):
        tp, sl, note = _clamp_with_atr(1.0, 1.5, *args, enabled=True)
        assert (tp, sl) == (1.0, 1.5)
        assert note == ""


# ─── AI KAPILARI ───────────────────────────────────────────────────────────────

def test_ai_gate_thresholds_are_sane():
    """Kapı eşikleri makul aralıkta — 'her şeyi reddet' noktasına çekilmemeli."""
    gate = spot_monitor.AI_GATE
    assert 0 < gate["min_octobot_consensus_pct"] <= 100
    assert 0 <= gate["min_qlib_alpha"] <= 100
    assert gate["require_jesse_rr"] >= 1.0
    assert isinstance(gate["block_fomo_trap"], bool)
    assert 0.0 <= gate["min_ml_hit_probability"] <= 1.0


def test_ai_gate_defaults_to_shadow_mode():
    """Heuristik skorlar varsayılan olarak işlemi ENGELLEMEMELİ.

    ai_trading_suite'teki 42 modül öğrenen model değil, elle yazılmış kural
    motoru. Doğrulanmamış eşiklerle işlem engellemek, örneklemi yok edip
    sistemi sahte bir "AI" anlatısına bağlar. 'enforce' bilinçli bir seçim
    olmalı, varsayılan değil.
    """
    assert spot_monitor.AI_GATE["mode"] == "shadow"


def test_ai_suite_contains_no_trained_model():
    """Regresyon: ai_trading_suite modülleri GERÇEKTEN model eğitmiyor.

    Bu bir 'kusur' tespiti değil, bir belge: adlarında OctoBot/Qlib/Jesse/FinRL
    geçen 42 modülün tamamı deterministik kural motorudur. Hiçbiri ML
    kütüphanesi import etmez. Bu test, birinin sessizce 'AI' diye kural
    motoru ekleyip gerçek model varmış gibi sunmasını engeller.
    """
    import pathlib
    import re

    suite_dir = pathlib.Path(spot_monitor.__file__).parent / "ai_trading_suite"
    ml_imports = re.compile(
        r"\b(import\s+torch|import\s+tensorflow|from\s+sklearn|import\s+sklearn"
        r"|import\s+lightgbm|import\s+xgboost|from\s+transformers|import\s+catboost)"
    )
    offenders = []
    for py in suite_dir.glob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        if ml_imports.search(text):
            offenders.append(py.name)
    assert offenders == [], f"ai_trading_suite içinde ML kütüphanesi kullanan modül: {offenders}"


def test_real_ml_model_is_ml_forecast():
    """Gerçek öğrenen bileşen ml_forecast olmalı — ve gerçekten eğitiyor olmalı."""
    import inspect
    src = inspect.getsource(spot_monitor.ml_forecast)
    assert "HistGradientBoosting" in src, "gerçek ML eğitimi olmalı"
    assert "joblib.dump" in src, "model diske yazılmalı"


def test_ml_predict_returns_none_without_artifact(monkeypatch):
    """Artifact yoksa predict_target None dönmeli — uydurma değer ÜRETMEMELİ.

    ML-05 notu: eskiden tüm özellikler None olsa bile model sayı üretiyordu
    (hit_probability 0.9987). Bu, kapıyı anlamsız kılardı.
    """
    monkeypatch.setattr(spot_monitor.ml_forecast, "load_model", lambda: None)
    assert spot_monitor.ml_forecast.predict_target("BTCUSDT", {"rsi": 50}) is None


def test_ml_predict_rejects_incomplete_features(monkeypatch):
    """Zorunlu özellikler eksikse None dönmeli (sessiz uydurma yok)."""
    fake = {"horizons": {"5": {"reg": None, "clf": None}},
            "symbol_codes": {"BTCUSDT": 1}, "trained_at": "x"}
    monkeypatch.setattr(spot_monitor.ml_forecast, "load_model", lambda: fake)
    assert spot_monitor.ml_forecast.predict_target("BTCUSDT", {}) is None
    assert spot_monitor.ml_forecast.predict_target("BTCUSDT", {"rsi": 50}) is None


def test_qlib_receives_real_rsi_not_constant():
    """qlib kapısı gerçek RSI ile beslenmeli; sabit 55.0 kalmamalı.

    Sabit RSI her sembol/zaman dilimi için aynı momentum faktörünü üretiyordu,
    yani skor ayırt edici bilgi taşımıyordu.
    """
    from app.ai_trading_suite import evaluate_qlib_alpha

    low = evaluate_qlib_alpha("BTCUSDT", 100.0, {"rsi": 20.0, "volume_ratio": 1.0, "atr": 1.0})
    high = evaluate_qlib_alpha("BTCUSDT", 100.0, {"rsi": 80.0, "volume_ratio": 1.0, "atr": 1.0})
    assert low.alpha_score != high.alpha_score
    assert high.alpha_score > low.alpha_score


def test_jesse_high_vol_mode_widens_stop():
    """Yüksek volatilite modunda stop daha geniş olmalı (gerçek ATR geçilmeli)."""
    from app.ai_trading_suite import evaluate_jesse_risk

    normal = evaluate_jesse_risk("BTCUSDT", 100.0, atr=1.5, volatility_mode="NORMAL")
    high = evaluate_jesse_risk("BTCUSDT", 100.0, atr=1.5, volatility_mode="HIGH")
    assert high.optimized_sl < normal.optimized_sl


def test_jesse_rr_is_computed_from_atr_not_constant_price_fraction():
    """Farklı ATR girdileri farklı R:R üretmeli (önceden hep aynıydı)."""
    from app.ai_trading_suite import evaluate_jesse_risk

    a = evaluate_jesse_risk("BTCUSDT", 100.0, atr=1.0)
    b = evaluate_jesse_risk("BTCUSDT", 100.0, atr=3.0)
    # R:R her ikisinde de tp1_mult/sl_mult oranıdır; ölçek değişimi onu
    # değiştirmez ama sl/tp MUTLAK seviyeleri değişmeli.
    assert a.optimized_tp1 != b.optimized_tp1
    assert a.optimized_sl != b.optimized_sl


# ─── REDDEDİLEN SİNYAL KAYDI ───────────────────────────────────────────────────

def test_rejected_signals_list_exists():
    assert isinstance(spot_monitor._rejected_signals, list)


def test_rejected_list_is_cleared_at_scan_start(monkeypatch):
    """Her taramada liste sıfırlanmalı — 'son taramanın' redlerini gösterir."""
    spot_monitor._rejected_signals.append({"symbol": "ESKI", "reasons": ["test"]})

    async def fake_conn():
        raise RuntimeError("DB yok — tarama burada durur")

    monkeypatch.setattr(spot_monitor, "get_db_conn", fake_conn)
    with pytest.raises(RuntimeError):
        asyncio.run(spot_monitor.run_single_scan())
    assert spot_monitor._rejected_signals == []


# ─── MUHAFAZAKÂR BARIYER SIRASI (motor seviyesi) ──────────────────────────────

class _FakeRow(dict):
    """asyncpg Record taklidi — update_open_signals_pnl sözlük gibi okur."""
    def __getitem__(self, k):
        return dict.__getitem__(self, k)


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.updates = []

    async def fetch(self, *a, **kw):
        return self._rows

    async def execute(self, sql, *args):
        self.updates.append((sql, args))


def _open_row(entry, target=None, stop=None, mfe=0.0, trailing=False, peak=None):
    from datetime import datetime, timezone
    return _FakeRow(
        id=1, symbol="BTCTRY", timeframe="5m", entry_price=entry,
        target_price=target, stop_price=stop,
        detected_at=datetime.now(timezone.utc),
        mfe_pct=mfe, mae_pct=0.0, status="OPEN",
        trade_size_try=500.0, commission_try=None, pnl_pct=0.0,
        net_pnl_try=0.0, details="{}",
        trailing_active=trailing, peak_price=peak,
    )


def _run_pnl(row, price, monkeypatch):
    """update_open_signals_pnl'i tek bir sahte satırla çalıştırır."""
    conn = _FakeConn([row])
    monkeypatch.setattr(spot_monitor, "_fetch_all_prices", lambda: {"BTCTRY": price})
    # Dynamic Exit Architect'in stop'u yukarı çekmesini engelle: MFE 0 kalsın
    monkeypatch.setattr(spot_monitor, "TRADE_SIZE_TRY", 500.0)
    asyncio.run(spot_monitor.update_open_signals_pnl(conn))
    return conn


# ─── ZİRVE TAKİPÇİ STOP (TP YOK) ──────────────────────────────────────────────

def test_no_take_profit_is_written_on_scan(monkeypatch):
    """Sinyal kaydında TP hedefi ARTIK ÜRETİLMEMELİ.

    `run_single_scan` target_p = None yazar; INSERT ise şemadaki NOT NULL'u
    karşılamak için entry_price'a düşer. Gerçek karar `update_open_signals_pnl`
    içinde, fiyat bariyeri olarak yalnızca stop kontrol edilir.
    """
    import inspect
    src = inspect.getsource(spot_monitor.run_single_scan)
    assert "target_p = None" in src, "TP hedefi üretilmemeli"
    assert "trailing" in inspect.getsource(spot_monitor.update_open_signals_pnl).lower()


def test_trailing_constants_match_spec():
    """Kullanıcı spec'i: %1.5'te devreye gir, %0.8 kilitle, %0.6 geriden takip et."""
    assert spot_monitor.TRAIL_ACTIVATE_PCT == 1.5
    assert spot_monitor.TRAIL_LOCK_PCT == 0.8
    assert spot_monitor.TRAIL_DISTANCE_PCT == 0.6


def test_trailing_not_active_before_activation_threshold(monkeypatch):
    """Kâr %1.5'in altındayken takipçi DEVREDE OLMAMALI, ilk stop korunmalı."""
    row = _open_row(entry=100.0, stop=99.0, mfe=1.2)
    conn = _run_pnl(row, price=101.2, monkeypatch=monkeypatch)
    sql, args = conn.updates[-1]
    # stop_price hâlâ 99 (sadece trailing yukarı çeker)
    assert args[3] == pytest.approx(99.0), "aktivasyon öncesi stop değişmemeli"
    assert bool(args[4]) is False, "trailing_active False kalmalı"


def test_trailing_activates_at_threshold(monkeypatch):
    """Kâr %1.5'e ulaşınca takipçi devreye girmeli."""
    row = _open_row(entry=100.0, stop=99.0, mfe=1.5)
    conn = _run_pnl(row, price=101.5, monkeypatch=monkeypatch)
    args = conn.updates[-1][1]
    assert bool(args[4]) is True, "trailing_active True olmalı"


def test_trailing_locks_min_profit_on_activation(monkeypatch):
    """Devreye girdiği anda stop en az maliyet + %0.8'e çekilmeli."""
    row = _open_row(entry=100.0, stop=99.0, mfe=1.5)
    conn = _run_pnl(row, price=101.5, monkeypatch=monkeypatch)
    stop = conn.updates[-1][1][3]
    assert stop >= 100.8 - 1e-9, f"kilit 100.8 olmalıydı, {stop} geldi"


def test_trailing_follows_peak_at_06_pct(monkeypatch):
    """Zirve yükseldikçe stop, zirvenin %0.6 gerisinden gelmeli."""
    # Zirve %3'te: 103.0 * 0.994 = 102.382
    row = _open_row(entry=100.0, stop=99.0, mfe=3.0, peak=103.0)
    conn = _run_pnl(row, price=102.5, monkeypatch=monkeypatch)
    stop = conn.updates[-1][1][3]
    expected = 103.0 * (1.0 - 0.6 / 100.0)
    assert stop == pytest.approx(expected, abs=0.01), f"beklenen {expected:.3f}, gelen {stop}"


def test_trailing_never_moves_down(monkeypatch):
    """Zirve geri çekilse bile stop ASLA düşmemeli (ratchet).

    Fiyat stop'un ÜSTÜNDE tutulur ki açık-kalan dal çalışsın ve kaydedilen
    yeni stop okunabilsin.
    """
    # Yüksek bir stop zaten kayıtlı, zirve düşük → yeniden hesap onu DÜŞÜRMEMELİ
    row = _open_row(entry=100.0, stop=102.0, mfe=3.0, peak=101.0, trailing=True)
    conn = _run_pnl(row, price=102.5, monkeypatch=monkeypatch)
    sql, args = conn.updates[-1]
    assert "trailing_active" in sql, "açık-kalan dal çalışmalıydı"
    stop = args[3]
    assert stop >= 102.0 - 1e-9, f"stop geri gitmemeli, {stop} geldi"


def test_trailing_exit_above_entry_is_win(monkeypatch):
    """Takipçi devredeyken stop'un altına inilirse ve stop maliyetin üstündeyse WIN_TRAILING."""
    row = _open_row(entry=100.0, stop=101.0, mfe=2.0, peak=102.0, trailing=True)
    conn = _run_pnl(row, price=100.9, monkeypatch=monkeypatch)
    status, exit_price = conn.updates[-1][1][0], conn.updates[-1][1][1]
    assert status == "WIN_TRAILING"
    assert exit_price > 100.0


def test_trailing_exit_below_entry_is_loss(monkeypatch):
    """Stop maliyetin altındaysa (takipçi devredeyken gap-down) kayıp sayılmalı."""
    row = _open_row(entry=100.0, stop=99.0, mfe=0.0, trailing=False)
    conn = _run_pnl(row, price=98.0, monkeypatch=monkeypatch)
    assert conn.updates[-1][1][0] == "LOSS_SL"


def test_time_expiry_skipped_while_trailing_active(monkeypatch):
    """Takipçi devredeyken süre aşımı UYGULANMAMALI — kazananı kesmemek amaçtır."""
    from datetime import datetime, timezone, timedelta
    row = _open_row(entry=100.0, stop=101.0, mfe=2.0, peak=102.0, trailing=True)
    # 5m için süre aşımı 60 dk; pozisyonu 5 saat öncesine taşı
    row["detected_at"] = datetime.now(timezone.utc) - timedelta(hours=5)
    conn = _run_pnl(row, price=101.5, monkeypatch=monkeypatch)
    flat = " ".join(str(a) for a in conn.updates[-1][1])
    assert "WIN_EXPIRED" not in flat and "EXPIRED" not in flat, \
        "takipçi aktifken süre aşımı kapatmamalı"


def test_time_expiry_still_applies_when_not_trailing(monkeypatch):
    """Takipçi devrede değilken süre aşımı çalışmalı (likidite kilidi koruması)."""
    from datetime import datetime, timezone, timedelta
    row = _open_row(entry=100.0, stop=90.0, mfe=0.3)
    row["detected_at"] = datetime.now(timezone.utc) - timedelta(hours=5)
    conn = _run_pnl(row, price=100.3, monkeypatch=monkeypatch)
    flat = " ".join(str(a) for a in conn.updates[-1][1])
    assert "EXPIRED" in flat


def test_peak_price_is_persisted_and_advances(monkeypatch):
    """peak_price kaydedilmeli ve MFE yükseldikçe ilerlemeli."""
    row = _open_row(entry=100.0, stop=99.0, mfe=2.0, peak=101.0)
    conn = _run_pnl(row, price=102.0, monkeypatch=monkeypatch)
    args = conn.updates[-1][1]
    peak = args[5]
    assert peak == pytest.approx(102.0), f"zirve 102 olmalıydı, {peak} geldi"


def test_gap_down_fills_below_stop(monkeypatch):
    """Fiyat stop'un ALTINDA açıldıysa dolum stop fiyatından değil, daha kötü olmalı.

    GERÇEK iyimserlik kaynağı budur: 60 sn'lik taramada büyük bir düşüş
    stop fiyatından kapatılırsa kayıp olduğundan küçük görünür.
    """
    row = _open_row(entry=100.0, stop=99.0)
    conn = _run_pnl(row, price=97.0, monkeypatch=monkeypatch)
    assert conn.updates
    args = conn.updates[-1][1]
    status, exit_price = args[0], args[1]
    assert status == "LOSS_SL"
    assert exit_price == pytest.approx(97.0), (
        f"gap-down'da dolum 97 olmalıydı, {exit_price} geldi (stop fiyatından kapatma iyimser)"
    )


def test_gap_down_loss_is_larger_than_stop_distance(monkeypatch):
    """Gap-down modeli kaybı gerçek büyüklüğünde göstermeli, stop mesafesinde değil."""
    row = _open_row(entry=100.0, stop=99.0)
    conn = _run_pnl(row, price=97.0, monkeypatch=monkeypatch)
    net = conn.updates[-1][1][6]  # net_pnl_try
    assert net < -14.0, f"gap-down kaybı -14'ün altında olmalıydı, {net} geldi"


def test_normal_stop_still_fills_at_stop_price(monkeypatch):
    """Gap yoksa (fiyat stop'un hemen altında) dolum yine stop fiyatı olmalı."""
    row = _open_row(entry=100.0, stop=99.0)
    conn = _run_pnl(row, price=98.99, monkeypatch=monkeypatch)
    args = conn.updates[-1][1]
    assert args[0] == "LOSS_SL"
    assert args[1] == pytest.approx(98.99)


def test_no_barrier_hit_keeps_position_open(monkeypatch):
    """Stop'a değilse pozisyon AÇIK kalmalı, kapanış yazılmamalı."""
    row = _open_row(entry=100.0, stop=90.0)
    conn = _run_pnl(row, price=100.5, monkeypatch=monkeypatch)
    sql, args = conn.updates[-1]
    flat = " ".join(str(a) for a in args)
    assert "WIN_TP" not in flat
    assert "LOSS_SL" not in flat
    assert "WIN_EXPIRED" not in flat
    assert "SET pnl_pct" in sql

