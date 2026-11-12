"""P1-P3 KARAR DESTEK MODÜLLERİNİN KİLİTLERİ (2026-11-09).

Kapsanan:
  P1 `app/regime_break.py`  — change-point (ruptures/PELT)
  P2 `app/ml_probability.py` conformal + Wilson (ikili etikette conformal REDDEDİLDİ)
  P3 `app/hmm_regime.py`    — gerçek 2 durumlu Gaussian HMM (log oynaklık)

Hepsi BİLİNEN CEVAPLI sentetik veriyle sınanır: rastgele seride "kırılma var"
demek ya da şans seviyesinde sınıflama yapmak bu testlerde kırılır.
"""
import math
import pathlib
import random
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import hmm_regime, ml_probability as mp, regime_break  # noqa: E402


def _series(seed=7, n1=200, n2=30, s1=0.20, s2=1.00):
    rnd = random.Random(seed)
    a = [rnd.gauss(100.0, s1) for _ in range(n1)]
    b = [rnd.gauss(100.0, s2) for _ in range(n2)]
    return a + b


class TestRegimeBreak(unittest.TestCase):
    def test_known_answer_break_detected(self):
        if not regime_break.available():
            self.skipTest("ruptures kurulu değil")
        info = regime_break.recent_break(_series())
        self.assertTrue(info["available"])
        self.assertIsNotNone(info["bars_since"])
        # kırılma 200. barda; 230 bar var → 30 bar önce
        self.assertLessEqual(abs(info["bars_since"] - 30), 8, info)

    def test_flat_series_has_no_break(self):
        if not regime_break.available():
            self.skipTest("ruptures kurulu değil")
        rnd = random.Random(3)
        flat = [100.0 + rnd.gauss(0, 0.2) for _ in range(230)]
        info = regime_break.recent_break(flat)
        self.assertTrue(info["available"])
        self.assertFalse(info["broken"], "gürültüde kırılma uydurulmamalı")

    def test_short_series_is_unavailable_not_broken(self):
        info = regime_break.recent_break([100.0] * 10)
        self.assertFalse(info["available"])
        self.assertFalse(info["broken"])

    def test_from_candles_uses_close(self):
        candles = [{"close": c} for c in _series()]
        info = regime_break.from_candles(candles)
        self.assertEqual(info["available"], regime_break.available())

    def test_never_raises_on_garbage(self):
        for bad in (None, [], [None, None], [1, 2, "x"], object()):
            try:
                regime_break.recent_break(bad if isinstance(bad, list) else [])
            except Exception as exc:  # noqa: BLE001
                self.fail(f"istisna fırlattı: {exc}")


class TestConformalAndWilson(unittest.TestCase):
    def test_conformal_quantile_finite_sample_correction(self):
        res = [abs((i % 10) / 10.0) for i in range(100)]     # 0.0..0.9 tekrar
        q = mp.conformal_quantile(res, alpha=0.10)
        self.assertIsNotNone(q)
        self.assertGreaterEqual(q, 0.9 - 1e-9, "sonlu-örnek düzeltmesi üst nicemi seçmeli")

    def test_probability_interval_clamped(self):
        iv = mp.probability_interval(0.95, [0.05] * 50, alpha=0.10)
        self.assertIsNotNone(iv)
        self.assertLessEqual(iv[1], 1.0)
        self.assertGreaterEqual(iv[0], 0.0)

    def test_conformal_saturates_on_binary_labels(self):
        """ÖLÇÜLMÜŞ SINIR: ikili etikette |y-p|<=1 olduğu için aralık [0,1]'e yaklaşır.

        Bu yüzden rapor kararı Wilson aralığıyla veriyor; bu test o kararın
        gerekçesini kilitler (birileri conformal'ı karar kapısı yapmasın).
        """
        res = [abs(h - p) for p, h in ((0.85, 0), (0.55, 1), (0.70, 0), (0.62, 0), (0.78, 1))] * 40
        q = mp.conformal_quantile(res, alpha=0.10)
        self.assertIsNotNone(q)
        self.assertGreater(q, 0.5, "ikili etikette nicem büyük olur → aralık bilgisiz")

    def test_wilson_known_values(self):
        got = mp.hit_rate_interval_wilson([1] * 30 + [0] * 70, alpha=0.10)
        self.assertEqual(got["n"], 100)
        self.assertAlmostEqual(got["hit_rate"], 0.30, places=3)
        self.assertAlmostEqual(got["lo"], 0.231, places=2)
        self.assertAlmostEqual(got["hi"], 0.380, places=2)
        self.assertLess(got["lo"], 0.30)
        self.assertGreater(got["hi"], 0.30)

    def test_wilson_needs_enough_samples(self):
        self.assertIsNone(mp.hit_rate_interval_wilson([1] * 5))


class TestHmmRegime(unittest.TestCase):
    def _calm_panic(self, seed=11):
        rnd = random.Random(seed)
        calm = [rnd.gauss(0.0, 0.0012) for _ in range(400)]
        panic = [rnd.gauss(0.0, 0.0100) for _ in range(200)]
        return calm + panic

    def test_detects_high_volatility_regime(self):
        if not hmm_regime.available():
            self.skipTest("hmmlearn kurulu değil")
        res = hmm_regime.volatility_state(self._calm_panic())
        self.assertTrue(res["available"], res.get("note"))
        self.assertEqual(res["method"], "gaussian_hmm")
        self.assertEqual(res["state"], "high")
        self.assertGreaterEqual(res["prob_high_vol"], 0.6)

    def test_deterministic(self):
        if not hmm_regime.available():
            self.skipTest("hmmlearn kurulu değil")
        a = hmm_regime.volatility_state(self._calm_panic())
        b = hmm_regime.volatility_state(self._calm_panic())
        self.assertEqual(a["prob_high_vol"], b["prob_high_vol"], "random_state sabit olmalı")

    def test_short_series_unavailable(self):
        res = hmm_regime.volatility_state([0.001] * 50)
        self.assertFalse(res["available"])
        self.assertIn("yetersiz", res["note"])

    def test_never_raises(self):
        for bad in (None, [], [None] * 300):
            res = hmm_regime.volatility_state(bad)
            self.assertIn("available", res)

    def test_rolling_log_std_shape(self):
        out = hmm_regime._rolling_log_std([0.001] * 30, 10)
        self.assertEqual(len(out), 20)
        self.assertTrue(all(math.isfinite(v) for v in out))


class TestWiring(unittest.TestCase):
    def test_dossier_carries_p1_and_p3(self):
        src = (ROOT / "app" / "llm_trade_review.py").read_text(encoding="utf-8")
        self.assertIn("from app import regime_break, hmm_regime", src)
        self.assertIn('"oynaklik_rejimi": vol', src)
        self.assertIn('"yapi_kirilmasi": kirilma', src)
        # tek mum çekimi: ikinci ağ çağrısı olmamalı
        self.assertEqual(src.count('run_blocking(forex_research.get_candles, sym, "5m")'), 1)

    def test_report_uses_wilson_not_conformal(self):
        src = (ROOT / "app" / "ml_calibration_report.py").read_text(encoding="utf-8")
        self.assertIn("hit_rate_interval_wilson", src)
        self.assertIn("CONFORMAL REDDEDİLDİ", src)

    def test_ruptures_pinned_in_requirements(self):
        req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("ruptures==", req)


class TestGateRejectionRecorded(unittest.TestCase):
    """P1 KAPI olarak denendi ve REDDEDİLDİ (ölçüm: 24 bar −%17, 48 bar −%60).

    Bu kayıt kodda durmazsa aynı fikir tekrar tekrar önerilir. Kilit, ölçümün
    ve ret gerekçesinin kaynakta kalmasını sağlar.
    """

    def test_module_documents_rejection_with_numbers(self):
        src = (ROOT / "app" / "regime_break.py").read_text(encoding="utf-8")
        self.assertIn("REDDEDİLDİ", src)
        self.assertIn("83,783", src, "24 barın net kaybı yazılı olmalı")
        self.assertIn("40,154", src, "48 barın net kaybı yazılı olmalı")
        self.assertIn("kırılmanın", src.lower())

    def test_replay_flag_warns_not_live(self):
        # replay betiği REPO KÖKÜNDE (`backend/` altında değil)
        src = (ROOT.parent / "scripts" / "forex_replay_backtest.py").read_text(encoding="utf-8")
        self.assertIn("CANLIYA ALINMADI", src)
        # bayrak varsayılan KAPALI kalmalı
        self.assertIn('"--break-gate-bars", type=int, default=0', src)


class TestEvidenceGateP2(unittest.TestCase):
    """P2 KANIT KAPISI: "bu sembolde kenar kanıtlandı mı?" — Wilson alt sınırı
    break-even'ın altındaysa çekimser kal. Canlıda VARSAYILAN KAPALI çünkü ölçüm
    şunu gösterdi: replay defterinde hiç tetiklenmiyor, gerçek defterde TAM
    durdurucu — yani açmak bir İŞ kararı.
    """

    def test_real_ledger_blocks(self):
        """Gerçek defter: 276 işlem, isabet %56.2, break-even %67.2."""
        r = mp.should_abstain_by_evidence({"n": 276, "wins": 155, "gw": 100.0, "gl": 160.0})
        self.assertTrue(r["block"])
        self.assertLess(r["wilson_lo"], r["break_even"])
        self.assertIn("kenar YOK", r["reason"])

    def test_replay_ledger_allows(self):
        """Replay defteri: isabet %86, break-even ~%29 → alt sınır %83."""
        r = mp.should_abstain_by_evidence({"n": 400, "wins": 344, "gw": 100.0, "gl": 40.0})
        self.assertFalse(r["block"])
        self.assertGreaterEqual(r["wilson_lo"], r["break_even"])

    def test_warmup_gives_no_decision(self):
        r = mp.should_abstain_by_evidence({"n": 10, "wins": 6, "gw": 10.0, "gl": 8.0}, min_trades=30)
        self.assertFalse(r["block"])
        self.assertIsNone(r["wilson_lo"])
        self.assertIn("ısınma", r["reason"])

    def test_missing_stats_never_blocks(self):
        for bad in ({}, {"n": 0}, {"n": 50, "wins": 20, "gw": 0, "gl": 0}):
            self.assertFalse(mp.should_abstain_by_evidence(bad)["block"])

    def test_settings_default_off(self):
        from app.routers.forex import ForexAutoPaperSettings
        cfg = ForexAutoPaperSettings()
        # 2026-11-10: varsayilan `shadow` YAPILDI (davranis degismez, yalniz "engellerdi"
        # diye loglar). Karar gerekcesi Field description'inda yazili.
        self.assertEqual(cfg.abstain_gate_mode, "shadow",
                         "kanıt kapısı varsayılan shadow olmalı (bloklamaz, loglar)")
        self.assertEqual(cfg.abstain_gate_min_trades, 30)
        self.assertGreaterEqual(cfg.abstain_gate_window_days, 1.0)

    def test_wiring_shadow_does_not_block(self):
        src = (ROOT / "app" / "routers" / "forex.py").read_text(encoding="utf-8")
        i_guard = src.index("8b1. SEMBOL KORUMASI")
        i_gate = src.index("8b1b. KANIT KAPISI")
        i_risk = src.index("8b2. Portföy risk kapısı")
        self.assertLess(i_guard, i_gate)
        self.assertLess(i_gate, i_risk, "kanıt kapısı risk kapısından ÖNCE olmalı")
        block = src[i_gate:i_risk]
        self.assertIn('if _abst_mode == "enforce":', block)
        self.assertIn("GÖLGE: engellemedi", block)


if __name__ == "__main__":
    unittest.main()
