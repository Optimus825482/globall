import unittest

from app.freqai_features import compute_adaptive_regime_features


class TestFreqAIFeatures(unittest.TestCase):
    def test_empty_or_small_data(self):
        res = compute_adaptive_regime_features([])
        self.assertEqual(res["regime_class"], "RANGE")
        self.assertEqual(res["vol_spike_ratio"], 1.0)

    def test_trending_up_detection(self):
        # Sürekli yükselen barlar
        closes = [100.0 + i * 2.0 for i in range(25)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        vols = [1000.0] * 24 + [2500.0]

        res = compute_adaptive_regime_features(closes, highs, lows, vols)
        self.assertEqual(res["regime_class"], "TRENDING")
        self.assertGreaterEqual(res["trend_persistence_ratio"], 0.7)
        self.assertGreater(res["vol_spike_ratio"], 2.0)
        self.assertGreater(res["momentum_atr_ratio"], 0.0)

    def test_range_flat_detection(self):
        # Yatay dalgalanan barlar
        closes = [100.0, 100.2, 100.1, 100.3, 100.0, 100.2, 100.1, 100.2, 100.1, 100.0] * 2
        highs = [c + 0.2 for c in closes]
        lows = [c - 0.2 for c in closes]
        vols = [1000.0] * len(closes)

        res = compute_adaptive_regime_features(closes, highs, lows, vols)
        self.assertEqual(res["regime_class"], "RANGE")

    def test_panic_crash_detection(self):
        # Sert düşüş ve dev hacim patlaması
        closes = [100.0] * 15 + [98.0, 95.0, 90.0, 85.0, 78.0]
        highs = [c + 0.5 for c in closes]
        lows = [c - 2.0 for c in closes]
        vols = [1000.0] * 15 + [2000.0, 3000.0, 5000.0, 7000.0, 10000.0]

        res = compute_adaptive_regime_features(closes, highs, lows, vols)
        self.assertEqual(res["regime_class"], "PANIC")
        self.assertLessEqual(res["trend_persistence_ratio"], 0.2)
        self.assertGreater(res["vol_spike_ratio"], 2.0)


if __name__ == "__main__":
    unittest.main()
