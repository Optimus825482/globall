"""LLM GÜVEN KALİBRASYONU betiğinin saf parçaları (2026-11-09).

Neden burada test var: betiğin veri okuma kısmı PostgreSQL'e bağlı ve yerelde
LLM karar kaydı YOK (LLM sunucuda çalışıyor). Bu yüzden saf hesaplama
fonksiyonları sentetik veriyle kilitleniyor ki sunucuda ilk koşuda sürpriz olmasın.

Kilitlenen davranış:
  1. `_rows_to_series`: confidence/100 → olasılık, shadow_pips>0 → isabet,
     R = shadow_pips/sl_pips (sl yoksa 0.0, çökme yok). Geçersiz satır atılır.
  2. `_suggest_threshold`: kalibre olasılığın break-even'ı İLK aştığı ham güveni
     döndürür; hiç aşmıyorsa 100 + "gerektirmiyor" gerekçesi.
  3. Aşırı güvenli sentetik veride: kalibrasyon Brier'ı düşürür ve önerilen eşik
     taban oranın üstüne çıkar (yani "daha yüksek güven iste" der).
  4. Yetersiz örnekte eğri KURULMAZ (sahte eğri yok).
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import llm_calibration as mod  # noqa: E402  (mantık burada; CLI ince sarmalayıcı)
from app import ml_probability as mp  # noqa: E402


def row(conf, pips, sl=100.0):
    return {"confidence": conf, "shadow_pips": pips, "sl_pips": sl}


class TestRowsToSeries(unittest.TestCase):
    def test_basic_mapping(self):
        probs, hits, rs = mod.rows_to_series([
            row(80, +150.0, 100.0),
            row(40, -100.0, 100.0),
        ])
        self.assertEqual(probs, [0.8, 0.4])
        self.assertEqual(hits, [1, 0])
        self.assertEqual(rs, [1.5, -1.0])

    def test_missing_sl_is_safe(self):
        probs, hits, rs = mod.rows_to_series([row(70, +50.0, sl=None)])
        self.assertEqual(rs, [0.0], "sl yoksa R=0 (çökme yok)")
        self.assertEqual(hits, [1])

    def test_invalid_rows_skipped(self):
        probs, hits, rs = mod.rows_to_series([
            {"confidence": None, "shadow_pips": 10, "sl_pips": 100},
            {"confidence": 60, "shadow_pips": None, "sl_pips": 100},
            row(60, +10.0),
        ])
        self.assertEqual(len(probs), 1)
        self.assertEqual(probs[0], 0.6)

    def test_probability_clamped(self):
        probs, _, _ = mod.rows_to_series([row(150, 1.0), row(-20, 1.0)])
        self.assertEqual(probs, [1.0, 0.0])


class TestSuggestThreshold(unittest.TestCase):
    def test_first_crossing(self):
        cal = {"fitted": True, "x_thresholds": [0.2, 0.5, 0.8],
               "y_thresholds": [0.10, 0.30, 0.70]}
        out = mod.suggest_threshold(cal, break_even=0.45)
        self.assertEqual(out["suggested_min_confidence"], 80)
        self.assertAlmostEqual(out["calibrated_at_that_point"], 0.70, places=4)

    def test_no_crossing_means_no_edge(self):
        cal = {"fitted": True, "x_thresholds": [0.2, 0.9], "y_thresholds": [0.1, 0.2]}
        out = mod.suggest_threshold(cal, break_even=0.6)
        self.assertEqual(out["suggested_min_confidence"], 100)
        self.assertIn("GEREKTİRMİYOR", out["reason"])

    def test_unfitted_curve(self):
        out = mod.suggest_threshold({"fitted": False}, break_even=0.5)
        self.assertIsNone(out["suggested_min_confidence"])


class TestOverconfidentScenario(unittest.TestCase):
    """Panelin gözlemini taklit et: yüksek güven, düşük isabet."""

    def _rows(self, n=600, seed=3):
        import random
        rnd = random.Random(seed)
        rows = []
        for _ in range(n):
            conf = rnd.choice([45, 50, 62, 68, 75])          # hep "yüksek" güven
            won = rnd.random() < 0.37                         # gerçek isabet %37
            rows.append(row(conf, (+100.0 if won else -100.0), 100.0))
        return rows

    def test_calibration_improves_brier(self):
        probs, hits, _ = mod.rows_to_series(self._rows())
        cal = mp.fit_calibration(probs, hits)
        self.assertTrue(cal["fitted"])
        self.assertLess(cal["metrics_calibrated"]["brier"], cal["metrics_raw"]["brier"],
                        "izotonik eğri aşırı güveni düzeltmeli")
        self.assertLess(cal["metrics_calibrated"]["ece"], cal["metrics_raw"]["ece"])

    def test_threshold_above_base_rate(self):
        probs, hits, _ = mod.rows_to_series(self._rows())
        cal = mp.fit_calibration(probs, hits)
        base = sum(hits) / len(hits)
        # R oranı 1:1 → break-even 0.5; gerçek isabet ~0.37
        out = mod.suggest_threshold(cal, break_even=0.5)
        self.assertEqual(out["suggested_min_confidence"], 100,
                         "isabet break-even'ın altındaysa hiçbir güven düzeyi onay gerektirmemeli")
        self.assertLess(base, 0.5)

    def test_insufficient_samples_no_curve(self):
        probs, hits, _ = mod.rows_to_series(self._rows(n=20))
        cal = mp.fit_calibration(probs, hits)
        self.assertFalse(cal["fitted"])
        self.assertIn("yetersiz", cal["reason"])


if __name__ == "__main__":
    unittest.main()
