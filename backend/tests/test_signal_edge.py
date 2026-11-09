"""SİNYAL KENARI (IC/kuantil) kilitleri (2026-11-09) — app/signal_edge.py.

Kilitlenen davranış:
  1. IC (Spearman) mükemmel korelasyonda ±1, bağımsız gürültüde ~0.
  2. Eşitliklerde (tie) sıra numarası ORTALAMA alınır (scipy eşdeğeri).
  3. `ic_tstat` yetersiz örnekte None; güçlü IC'de anlamlı.
  4. `quantile_returns` sinyal tahmin ediyorsa TEKDÜZE artan getiri verir.
  5. `monotonicity` bozuk sıralamayı yakalar.
  6. `align_forward_returns` LOOK-AHEAD YAPMAZ: aynı barın getirisi kullanılmaz,
     ufuk dışına taşan sinyaller atılır.
  7. `evaluate` hükmü: zayıf/anlamsız IC'de "KANIT YOK".
"""
import pathlib
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import signal_edge as se  # noqa: E402


class TestRankAndIC(unittest.TestCase):
    def test_rankdata_with_ties(self):
        r = se._rankdata(np.array([10.0, 20.0, 20.0, 30.0]))
        self.assertEqual(list(r), [1.0, 2.5, 2.5, 4.0])

    def test_ic_perfect_positive(self):
        x = np.arange(50, dtype=float)
        self.assertAlmostEqual(se.information_coefficient(x, x), 1.0, places=6)

    def test_ic_perfect_negative(self):
        x = np.arange(50, dtype=float)
        self.assertAlmostEqual(se.information_coefficient(x, -x), -1.0, places=6)

    def test_ic_monotonic_nonlinear_is_one(self):
        x = np.arange(40, dtype=float)
        y = x ** 3  # tekdüze ama doğrusal değil → Spearman 1
        self.assertAlmostEqual(se.information_coefficient(x, y), 1.0, places=6)

    def test_ic_noise_near_zero(self):
        rng = np.random.default_rng(3)
        s = rng.normal(size=2000)
        r = rng.normal(size=2000)
        ic = se.information_coefficient(s, r)
        self.assertLess(abs(ic), 0.06, f"bağımsız gürültüde IC ~0 olmalı, {ic}")

    def test_ic_too_few_points_is_none(self):
        self.assertIsNone(se.information_coefficient([1.0, 2.0], [1.0, 2.0]))
        self.assertIsNone(se.information_coefficient([], []))

    def test_ic_drops_nan_pairs(self):
        s = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
        r = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertAlmostEqual(se.information_coefficient(s, r), 1.0, places=6)

    def test_constant_signal_is_none(self):
        self.assertIsNone(se.information_coefficient([5.0] * 20, list(range(20))))


class TestTstat(unittest.TestCase):
    def test_insufficient_samples(self):
        self.assertEqual(se.ic_tstat(0.2, 3)["t"], None)
        self.assertFalse(se.ic_tstat(0.2, 3)["significant"])

    def test_strong_ic_significant(self):
        # n=100, IC=0.30 → t ≈ atanh(0.3)*sqrt(97) ≈ 0.31*9.85 ≈ 3.05
        t = se.ic_tstat(0.30, 100)
        self.assertGreater(t["t"], 2.5)
        self.assertTrue(t["significant"])

    def test_weak_ic_not_significant(self):
        t = se.ic_tstat(0.01, 100)
        self.assertFalse(t["significant"])


class TestQuantiles(unittest.TestCase):
    def test_monotonic_when_signal_predicts(self):
        rng = np.random.default_rng(11)
        s = rng.normal(size=1000)
        r = s * 0.01 + rng.normal(scale=0.002, size=1000)  # sinyal getiriyi taşıyor
        rows = se.quantile_returns(s, r, 5)
        self.assertEqual(len(rows), 5)
        means = [row["mean_return"] for row in rows]
        self.assertEqual(means, sorted(means), "dilim getirileri artan olmalı")
        self.assertTrue(se.monotonicity(rows)["monotonic"])
        self.assertGreater(rows[-1]["mean_return"], rows[0]["mean_return"])

    def test_no_monotonicity_for_noise(self):
        rng = np.random.default_rng(5)
        rows = se.quantile_returns(rng.normal(size=1000), rng.normal(size=1000), 5)
        self.assertFalse(se.monotonicity(rows)["monotonic"])

    def test_too_few_samples_returns_empty(self):
        self.assertEqual(se.quantile_returns([1, 2, 3], [1, 2, 3], 5), [])


class TestForwardAlignment(unittest.TestCase):
    def test_no_lookahead_and_correct_returns(self):
        prices = [100.0, 110.0, 121.0, 133.1]
        idx, ret = se.align_forward_returns(prices, [0, 1, 2, 3], horizon=1)
        # j=3 → 3+1 veri dışında → atılır
        self.assertEqual(list(idx), [0.0, 1.0, 2.0])
        self.assertAlmostEqual(ret[0], 0.10, places=6)
        self.assertAlmostEqual(ret[1], 0.10, places=6)
        self.assertAlmostEqual(ret[2], 0.10, places=6)

    def test_horizon_two(self):
        prices = [100.0, 110.0, 121.0]
        idx, ret = se.align_forward_returns(prices, [0, 1], horizon=2)
        self.assertEqual(list(idx), [0.0])
        self.assertAlmostEqual(ret[0], 0.21, places=6)

    def test_invalid_indexes_skipped(self):
        prices = [100.0, 110.0, 121.0]
        idx, ret = se.align_forward_returns(prices, [-1, 0, 99, "abc"], horizon=1)
        self.assertEqual(list(idx), [0.0])

    def test_zero_price_skipped(self):
        idx, ret = se.align_forward_returns([0.0, 1.0, 2.0], [0], horizon=1)
        self.assertEqual(len(idx), 0)


class TestEvaluate(unittest.TestCase):
    def test_real_signal_verdict(self):
        rng = np.random.default_rng(21)
        s = rng.normal(size=800)
        r = s * 0.01 + rng.normal(scale=0.002, size=800)
        res = se.evaluate(s, r, 5)
        self.assertGreater(abs(res["ic"]), 0.5)
        self.assertTrue(res["ic_tstat"]["significant"])
        self.assertIn("BİLGİ TAŞIYOR", res["verdict"])

    def test_noise_verdict(self):
        rng = np.random.default_rng(22)
        res = se.evaluate(rng.normal(size=800), rng.normal(size=800), 5)
        self.assertLess(abs(res["ic"]), 0.1)
        self.assertIn("KANIT YOK", res["verdict"])

    def test_reports_counts(self):
        res = se.evaluate([1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6], 3)
        self.assertEqual(res["n"], 6)
        self.assertAlmostEqual(res["ic"], 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
