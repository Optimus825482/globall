"""OLASILIK KALİBRASYONU kilitleri (2026-11-09) — app/ml_probability.py.

Kilitlenen davranış:
  1. Brier / log-loss / ECE matematiksel olarak doğru (elle hesapla eşleşir).
  2. ECE aşırı güveni YAKALAR (ham %90 diyen ama %60 tutan model → büyük ECE).
  3. Yetersiz örnekte eğri KURULMAZ (`fitted=False`) — sahte eğri üretilmez.
  4. İzotonik eğri tekdüze (monoton) ve aşırı güveni düzeltir
     (kalibre Brier < ham Brier).
  5. Eğri yoksa `apply_calibration` ham değeri AYNEN döndürür ve çekimserlik
     UYGULANMAZ (nötr davranış; canlı yol bozulmaz).
  6. Başabaş olasılık RR'den doğru türetilir (RR=1.5 → %40) ve çekimserlik
     eşiğin altında TRUE döner.
  7. Walk-forward bölme zamana göre ve örtüşmesizdir.
  8. Etiketi bilinmeyen satırlar ATILIR (uydurma etiket yok).
  9. Durum kaydet/yükle turu ve bozuk dosya fail-safe davranışı.
"""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ml_probability as mp  # noqa: E402


class TestMetrics(unittest.TestCase):
    def test_brier_known_values(self):
        # (1.0,1) ve (0.0,0) → hata 0; (0.5,1) → 0.25
        self.assertAlmostEqual(mp.brier_score([1.0, 0.0], [1, 0]), 0.0, places=9)
        self.assertAlmostEqual(mp.brier_score([0.5], [1]), 0.25, places=9)
        self.assertAlmostEqual(mp.brier_score([0.5, 0.5], [1, 0]), 0.25, places=9)

    def test_brier_empty_is_none(self):
        self.assertIsNone(mp.brier_score([], []))

    def test_log_loss_known_values(self):
        self.assertAlmostEqual(mp.log_loss([0.999999], [1]), 1e-06, places=6)
        # p=0.5 → ln2
        self.assertAlmostEqual(mp.log_loss([0.5], [1]), 0.693147, places=5)
        # kesin yanlış tahmin cezalandırılır (0/1 kırpma sayesinde sonsuz değil)
        self.assertGreater(mp.log_loss([0.0], [1]), 10.0)

    def test_ece_perfectly_calibrated_is_small(self):
        # Her kovada güven == doğruluk: 0.2 → %20, 0.8 → %80
        probs, hits = [], []
        for conf, wins in ((0.2, 2), (0.8, 8)):
            for i in range(10):
                probs.append(conf)
                hits.append(1 if i < wins else 0)
        self.assertLess(mp.ece(probs, hits), 1e-9)

    def test_ece_detects_overconfidence(self):
        # Model hep %90 diyor ama yalnız %60 tutuyor → ECE ≈ 0.30
        probs = [0.9] * 100
        hits = [1] * 60 + [0] * 40
        self.assertAlmostEqual(mp.ece(probs, hits), 0.30, places=6)

    def test_reliability_gap_sign(self):
        rows = mp.reliability_bins([0.9] * 10, [1] * 6 + [0] * 4)
        self.assertEqual(len(rows), 1)
        self.assertLess(rows[0]["gap"], 0)  # accuracy < confidence → aşırı güvenli
        self.assertEqual(rows[0]["samples"], 10)


class TestFit(unittest.TestCase):
    def _overconfident(self, n=400, seed=7):
        """Ham olasılık sürekli %85-95 diyen ama gerçek isabet ~%60 olan veri."""
        import random

        rnd = random.Random(seed)
        probs, hits = [], []
        for _ in range(n):
            raw = rnd.uniform(0.85, 0.95)
            # gerçek isabet olasılığı sabit ~0.60 → ham değer aşırı güvenli
            hits.append(1 if rnd.random() < 0.60 else 0)
            probs.append(raw)
        return probs, hits

    def test_insufficient_samples_never_fits(self):
        probs = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.95]
        hits = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
        cal = mp.fit_calibration(probs, hits)
        self.assertFalse(cal["fitted"])
        self.assertIn("yetersiz", cal["reason"])
        self.assertEqual(cal["x_thresholds"], [])

    def test_isotonic_is_monotonic(self):
        probs, hits = self._overconfident()
        cal = mp.fit_calibration(probs, hits)
        self.assertTrue(cal["fitted"])
        ys = cal["y_thresholds"]
        self.assertEqual(ys, sorted(ys), "izotonik eğri tekdüze olmalı")

    def test_calibration_improves_brier_and_ece(self):
        probs, hits = self._overconfident()
        cal = mp.fit_calibration(probs, hits)
        self.assertTrue(cal["fitted"])
        raw_brier = cal["metrics_raw"]["brier"]
        cal_brier = cal["metrics_calibrated"]["brier"]
        self.assertLess(cal_brier, raw_brier)
        self.assertLess(cal["metrics_calibrated"]["ece"], cal["metrics_raw"]["ece"])

    def test_apply_without_state_is_identity(self):
        self.assertAlmostEqual(mp.apply_calibration(0.73, None), 0.73, places=9)
        self.assertAlmostEqual(mp.apply_calibration(0.73, {"fitted": False}), 0.73, places=9)
        self.assertIsNone(mp.apply_calibration(None, None))
        # sınır dışı girdi kırpılır
        self.assertAlmostEqual(mp.apply_calibration(1.7, None), 1.0, places=9)
        self.assertAlmostEqual(mp.apply_calibration(-0.2, None), 0.0, places=9)

    def test_apply_is_monotonic_and_bounded(self):
        probs, hits = self._overconfident()
        cal = mp.fit_calibration(probs, hits)
        seq = [mp.apply_calibration(x / 20, cal) for x in range(21)]
        self.assertEqual(seq, sorted(seq))
        self.assertTrue(all(0.0 <= v <= 1.0 for v in seq))

    def test_overconfident_curve_shrinks_probability(self):
        probs, hits = self._overconfident()
        cal = mp.fit_calibration(probs, hits)
        out = mp.apply_calibration(0.90, cal)
        self.assertLess(out, 0.80, f"aşırı güvenli 0.90 → {out} olmalı (daha düşük)")


class TestAbstention(unittest.TestCase):
    def test_break_even_from_reward_risk(self):
        self.assertAlmostEqual(mp.break_even_probability(1.5), 0.4, places=6)
        self.assertAlmostEqual(mp.break_even_probability(1.0), 0.5, places=6)
        self.assertAlmostEqual(mp.break_even_probability(3.0), 0.25, places=6)
        # geçersiz RR → varsayılana düşer (sıfıra bölme yok)
        self.assertAlmostEqual(mp.break_even_probability(0), 1 / (1 + mp.DEFAULT_REWARD_RISK), places=6)

    def test_should_abstain_below_threshold(self):
        self.assertTrue(mp.should_abstain(0.30, 0.40))
        self.assertFalse(mp.should_abstain(0.55, 0.40))
        self.assertFalse(mp.should_abstain(None, 0.40))
        self.assertFalse(mp.should_abstain(0.10, None))  # eşik yok → çekimser kalma

    def test_decide_without_calibration_keeps_raw(self):
        d = mp.decide(0.62, state=None, reward_risk=1.5)
        self.assertEqual(d["raw_probability"], 0.62)
        self.assertAlmostEqual(d["probability"], 0.62, places=9)
        self.assertFalse(d["calibrated"])
        self.assertEqual(d["threshold"], 0.4)
        self.assertFalse(d["abstain"])

    def test_decide_flags_abstention_after_calibration(self):
        cal = {"fitted": True, "x_thresholds": [0.0, 1.0], "y_thresholds": [0.2, 0.2], "samples": 120}
        d = mp.decide(0.90, state=cal, reward_risk=1.5)
        self.assertTrue(d["abstain"], "kalibre 0.20 < eşik 0.40 → çekimser")
        self.assertTrue(d["calibrated"])


class TestDataHelpers(unittest.TestCase):
    def test_rows_to_series_mapping(self):
        rows = [
            {"ml_hit_probability": 0.8, "touched_target": True},
            {"ml_hit_probability": 0.7, "touched_target": False},
            {"ml_hit_probability": 0.6, "win": True},
            {"ml_hit_probability": 0.5, "outcome": "LOSS_SL"},
            {"ml_hit_probability": 0.9, "outcome": "WIN_TP"},
            {"ml_hit_probability": 0.55},                      # sonuç yok → at
            {"touched_target": True},                           # tahmin yok → at
            {"ml_hit_probability": None, "win": True},           # tahmin yok → at
        ]
        probs, hits = mp.rows_to_series(rows)
        self.assertEqual(probs, [0.8, 0.7, 0.6, 0.5, 0.9])
        self.assertEqual(hits, [1, 0, 1, 0, 1])

    def test_walk_forward_split_no_overlap(self):
        rows = [{"ml_hit_probability": 0.5, "touched_target": True, "evaluated_at": t}
                for t in (10, 20, 30, 40, 50, 60)]
        train, test = mp.split_walk_forward(rows)
        self.assertTrue(train and test)
        train_ts = {r["evaluated_at"] for r in train}
        test_ts = {r["evaluated_at"] for r in test}
        self.assertFalse(train_ts & test_ts, "eğitim ve test zaman olarak örtüşmemeli")
        self.assertTrue(max(train_ts) <= min(test_ts))

    def test_build_from_rows_end_to_end(self):
        import random

        rnd = random.Random(11)
        rows = []
        for i in range(300):
            hit = rnd.random() < 0.6
            rows.append({
                "ml_hit_probability": rnd.uniform(0.85, 0.95),
                "touched_target": hit,
                "evaluated_at": 1_700_000_000 + i * 60,
            })
        cal = mp.build_from_rows(rows)
        self.assertTrue(cal["fitted"])
        self.assertGreaterEqual(cal["samples"], 300)
        self.assertIsNotNone(cal["metrics_calibrated"]["brier"])


class TestPersistence(unittest.TestCase):
    def test_save_load_roundtrip(self):
        cal = {"fitted": True, "x_thresholds": [0.2, 0.8], "y_thresholds": [0.1, 0.7],
               "samples": 100, "metrics_raw": {}, "metrics_calibrated": {}, "bins": []}
        with tempfile.TemporaryDirectory() as tmp:
            path = str(pathlib.Path(tmp) / "calib.json")
            self.assertTrue(mp.save_state(path, cal))
            loaded = mp.load_state(path)
            self.assertEqual(loaded["x_thresholds"], [0.2, 0.8])
            self.assertEqual(loaded["samples"], 100)

    def test_load_missing_or_corrupt_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(mp.load_state(str(pathlib.Path(tmp) / "yok.json")))
            bad = pathlib.Path(tmp) / "bad.json"
            bad.write_text("{ bozuk", encoding="utf-8")
            self.assertIsNone(mp.load_state(str(bad)))
            # geçerli JSON ama beklenen şekil yok
            odd = pathlib.Path(tmp) / "odd.json"
            odd.write_text(json.dumps({"x": 1}), encoding="utf-8")
            self.assertIsNone(mp.load_state(str(odd)))

    def test_store_state_and_summary(self):
        cal = {"fitted": True, "bins": [
            {"bin": 0, "gap": 0.01}, {"bin": 1, "gap": -0.25}, {"bin": 2, "gap": 0.10}]}
        mp.store_state(cal)
        self.assertIsNotNone(mp.current_calibration())
        top = mp.summary_for_ui(mp.current_calibration(), limit=2)
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0]["gap"], -0.25, "en büyük mutlak sapma önce gelmeli")
        mp.store_state(None)  # diğer testleri kirletme
        self.assertIsNone(mp.current_calibration())


if __name__ == "__main__":
    unittest.main()
