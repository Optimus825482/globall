"""GÖLGE KALİBRASYON kilitleri (2026-11-09) — app/ml_shadow.py.

Kilitlenen davranış:
  1. Gölge mod KAPALIYKEN hiçbir iş yapılmaz (`observe` → None).
  2. Artefakt YOKKEN ham olasılık korunur, `calibrated=False` işaretlenir
     ("düzeltmiş gibi" davranmaz).
  3. Artefakt VARSA kalibre olasılık uygulanır; çekimserlik eşiğin altında
     YAKALANIR.
  4. **KARAR YOLU DEĞİŞMEZ**: `predict_target` gölge açıkken de kapalıyken de
     AYNI sözlüğü döndürür (gölge yalnız gözlemler).
  5. `observe()` hata durumunda istisna FIRLATMAZ (tahmin yolu düşmez).
  6. Sayaçlar doğru; `reset_counters` sıfırlar.
"""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ml_shadow  # noqa: E402
from app.config import config  # noqa: E402

#: Kasten AŞIRI GÜVENLİ eğri: ham 0.90 → kalibre 0.10 (eşiğin çok altı).
KOTU_EGRI = {
    "fitted": True, "samples": 500, "base_rate": 0.3,
    "x_thresholds": [0.0, 0.5, 1.0], "y_thresholds": [0.05, 0.10, 0.10],
    "metrics_raw": {}, "metrics_calibrated": {}, "bins": [],
}


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_enabled = config.ML_CALIBRATION_SHADOW_ENABLED
        self._orig_artifact = config.ML_CALIBRATION_ARTIFACT
        self._orig_rr = config.ML_CALIBRATION_REWARD_RISK
        ml_shadow._cache.update({"path": None, "mtime": None, "calibration": None, "checked_at": 0.0})
        ml_shadow.reset_counters()

    def tearDown(self):
        config.ML_CALIBRATION_SHADOW_ENABLED = self._orig_enabled
        config.ML_CALIBRATION_ARTIFACT = self._orig_artifact
        config.ML_CALIBRATION_REWARD_RISK = self._orig_rr
        ml_shadow._cache.update({"path": None, "mtime": None, "calibration": None, "checked_at": 0.0})
        ml_shadow.reset_counters()
        self._tmp.cleanup()

    def _write_artifact(self, payload=KOTU_EGRI):
        path = pathlib.Path(self._tmp.name) / "calib.json"
        path.write_text(json.dumps({"calibration": payload, "saved_at": 0}), encoding="utf-8")
        config.ML_CALIBRATION_ARTIFACT = str(path)
        ml_shadow._cache.update({"path": None, "checked_at": 0.0})
        return str(path)


class TestDisabled(_Base):
    def test_disabled_does_nothing(self):
        config.ML_CALIBRATION_SHADOW_ENABLED = False
        self.assertIsNone(ml_shadow.observe(raw_probability=0.9, symbol="X"))
        self.assertEqual(ml_shadow.counters()["observations"], 0)


class TestNoArtifact(_Base):
    def test_missing_artifact_keeps_raw_and_flags(self):
        config.ML_CALIBRATION_SHADOW_ENABLED = True
        config.ML_CALIBRATION_ARTIFACT = str(pathlib.Path(self._tmp.name) / "yok.json")
        ml_shadow._cache.update({"path": None, "checked_at": 0.0})
        d = ml_shadow.observe(raw_probability=0.91, symbol="X")
        self.assertIsNotNone(d)
        self.assertFalse(d["calibrated"], "artefakt yokken calibrated=False olmalı")
        self.assertAlmostEqual(d["probability"], 0.91, places=6)
        c = ml_shadow.counters()
        self.assertEqual(c["observations"], 1)
        self.assertEqual(c["calibrated_observations"], 0)
        self.assertFalse(c["artifact_loaded"])

    def test_corrupt_artifact_does_not_raise(self):
        config.ML_CALIBRATION_SHADOW_ENABLED = True
        bad = pathlib.Path(self._tmp.name) / "bozuk.json"
        bad.write_text("{ bozuk", encoding="utf-8")
        config.ML_CALIBRATION_ARTIFACT = str(bad)
        ml_shadow._cache.update({"path": None, "checked_at": 0.0})
        d = ml_shadow.observe(raw_probability=0.8, symbol="X")   # istisna YOK
        self.assertIsNotNone(d)
        self.assertFalse(d["calibrated"])


class TestWithArtifact(_Base):
    def test_calibration_applied_and_abstain_detected(self):
        config.ML_CALIBRATION_SHADOW_ENABLED = True
        self._write_artifact()
        d = ml_shadow.observe(raw_probability=0.90, symbol="XAUUSD", horizon=5)
        self.assertTrue(d["calibrated"], "artefakt varken calibrated=True olmalı")
        self.assertAlmostEqual(d["probability"], 0.10, places=6)
        self.assertAlmostEqual(d["threshold"], 0.4, places=6)   # RR=1.5 → 1/2.5
        self.assertTrue(d["abstain"], "kalibre 0.10 < eşik 0.40 → çekimser")
        c = ml_shadow.counters()
        self.assertEqual(c["calibrated_observations"], 1)
        self.assertEqual(c["would_abstain"], 1)
        self.assertEqual(c["abstain_rate_pct"], 100.0)
        self.assertAlmostEqual(c["mean_calibrated"], 0.10, places=6)
        self.assertTrue(c["artifact_loaded"])
        self.assertEqual(c["artifact_samples"], 500)

    def test_high_calibrated_probability_does_not_abstain(self):
        config.ML_CALIBRATION_SHADOW_ENABLED = True
        self._write_artifact({"fitted": True, "samples": 300, "base_rate": 0.6,
                              "x_thresholds": [0.0, 1.0], "y_thresholds": [0.7, 0.7]})
        d = ml_shadow.observe(raw_probability=0.30, symbol="X")
        self.assertTrue(d["calibrated"])
        self.assertFalse(d["abstain"])
        self.assertEqual(ml_shadow.counters()["would_abstain"], 0)

    def test_reward_risk_changes_threshold(self):
        config.ML_CALIBRATION_SHADOW_ENABLED = True
        config.ML_CALIBRATION_REWARD_RISK = 3.0          # p* = 0.25
        self._write_artifact()
        d = ml_shadow.observe(raw_probability=0.90, symbol="X")
        self.assertAlmostEqual(d["threshold"], 0.25, places=6)


class TestPredictionPathUnchanged(_Base):
    """EN ÖNEMLİ KİLİT: gölge mod kararı DEĞİŞTİRMEMELİ."""

    def test_predict_target_returns_identical_result(self):
        from app import ml_forecast

        sabit = {"target_pct": 1.234, "hit_probability": 0.91,
                 "quantile": 0.9, "trained_at": "2026-11-09"}
        features = {"atr_pct": 0.5, "ret3_pct": 0.2, "rsi": 55.0}

        with patch.object(ml_forecast, "predict_from_artifact", return_value=dict(sabit)):
            config.ML_CALIBRATION_SHADOW_ENABLED = False
            kapali = ml_forecast.predict_target("XAUUSD", features, 5)
            config.ML_CALIBRATION_SHADOW_ENABLED = True
            self._write_artifact()
            acik = ml_forecast.predict_target("XAUUSD", features, 5)

        self.assertEqual(kapali, sabit)
        self.assertEqual(acik, sabit, "gölge mod sonucu DEĞİŞTİRMEMELİ")
        # ve gerçekten gözlem yapılmış olmalı
        self.assertEqual(ml_shadow.counters()["observations"], 1)

    def test_predict_target_none_is_safe(self):
        from app import ml_forecast
        with patch.object(ml_forecast, "predict_from_artifact", return_value=None):
            self.assertIsNone(ml_forecast.predict_target("XAUUSD", {}, 5))
        self.assertEqual(ml_shadow.counters()["observations"], 0)


if __name__ == "__main__":
    unittest.main()
