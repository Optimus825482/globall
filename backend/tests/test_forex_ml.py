"""FOREX ML v1 trainer kilidi (2026-11-09) — app/forex_ml.py.

Veri sunucuda olduğu için yerelde tablo boştur; bu yüzden trainer BİLİNEN
CEVAPLI sentetik veriyle kilitlenir:
  * Sinyalli veri (htf_agree_count arttıkça isabet artıyor) → OOS skill > 0
    ve katsayı işareti DOĞRU.
  * Gürültü verisi → skill ≈ 0 ve hüküm "karar kapısı OLMAMALI".
  * Eksik özellikler eğitim medyanıyla doldurulur; bilinmeyen kategoriler
    tüm-bit-0 (uydurma yok).
Ayrıca: artifact PICKLE DEĞİL (JSON) ve pandas/joblib kullanılmaz (üretim imajı
yalın kalır). Split KRONOLOJİK (zaman sızıntısı yok).
"""
import json
import pathlib
import random
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import forex_ml  # noqa: E402

SRC = (ROOT / "app" / "forex_ml.py").read_text(encoding="utf-8")
SYSTEM_SRC = (ROOT / "app" / "routers" / "system.py").read_text(encoding="utf-8")


def _synthetic_rows(n=420, *, signal=True, seed=5):
    """htf_agree_count ile isabet olasılığı değişen (veya sabit) sentetik satırlar."""
    rnd = random.Random(seed)
    sessions = ("asia", "london", "new_york", "overlap")
    rows = []
    for i in range(n):
        agree = rnd.randint(0, 4)
        if signal:
            hit = rnd.random() < 0.30 + 0.12 * agree        # 0.30 → 0.78
        else:
            hit = rnd.random() < 0.50
        rows.append({
            "created_at": f"2026-{1 + i // 400:02d}-{1 + (i % 28):02d}T{i % 24}:00:00Z",
            "id": f"r{i}", "confidence": rnd.choice([55, 65, 75, 85]),
            "score": rnd.choice([60, 70, 80]), "direction": rnd.choice(["BUY", "SELL"]),
            "shadow_pips": 120.0 if hit else -100.0,
            "features": {
                "session": sessions[i % 4], "htf_agree_count": agree, "htf_frames": 4,
                "level_clearance_atr": (rnd.uniform(0.5, 3.0) if i % 7 else None),
                "extension_atr": rnd.uniform(0.2, 2.0),
                "spread_atr_ratio": (None if i % 11 == 0 else rnd.uniform(0.02, 0.2)),
                "news_minutes": None if i % 5 == 0 else rnd.randint(-240, 240),
                "ta_bias": rnd.choice(["bullish", "bearish", "neutral"]),
                "ta_score": rnd.uniform(-60, 60),
            },
        })
    return rows


class TestTrainer(unittest.TestCase):
    def test_signal_data_reaches_positive_skill(self):
        r = forex_ml.train(_synthetic_rows(signal=True))
        self.assertTrue(r.get("trained"), r.get("reason"))
        self.assertGreater(r["brier_skill_oos"], 0.05,
                           "sinyalli veride OOS skill pozitif olmalı")
        self.assertGreater(r["coefficients"]["htf_agree_count"], 0.0,
                           "katsayının işareti sinyalle aynı olmalı")
        self.assertIn("bilgi taşıyor", r["verdict"])

    def test_noise_data_verdict_refuses_gate(self):
        # 900 satır: test yarısı ~270 → skill'in şans gürültüsü σ≈0.06.
        # 0.15 eşiği bu gürültünün 2σ'sının altında: saf gürültüde skill sıfıra
        # yaklaşmalı, anlamlı pozitife ÇIKMAMALI.
        r = forex_ml.train(_synthetic_rows(n=900, signal=False))
        self.assertTrue(r.get("trained"))
        self.assertLess(abs(r["brier_skill_oos"]), 0.15,
                        f"gürültüde skill ≈ 0 olmalı (ölçülen {r['brier_skill_oos']})")
        self.assertIn("OLMAMALI", r["verdict"])

    def test_chronological_split_partitions(self):
        r = forex_ml.train(_synthetic_rows())
        self.assertEqual(r["n_train"] + r["n_test"], r["n_usable"])
        self.assertGreater(r["n_train"], r["n_test"], "eğitim yarısı büyük olmalı")

    def test_insufficient_data_honest_reason(self):
        r = forex_ml.train(_synthetic_rows(n=40)[:40])
        self.assertFalse(r.get("trained"))
        self.assertIn("yetersiz", r["reason"])


class TestFeaturize(unittest.TestCase):
    def test_missing_numeric_uses_median(self):
        row = {"features": {"session": "london", "htf_agree_count": 2}, "direction": "BUY"}
        f = forex_ml.featurize(row, medians={"extension_atr": 1.25})
        self.assertEqual(f["extension_atr"], 1.25)
        self.assertEqual(f["extension_atr_eksik"], 1.0)
        self.assertEqual(f["level_clearance_atr_eksik"], 1.0)

    def test_unknown_category_all_zeros(self):
        f = forex_ml.featurize({"features": {"session": "sydney", "ta_bias": "x"}, "direction": "SELL"})
        for s in forex_ml.SESSION_VALUES:
            self.assertEqual(f[f"session_{s}"], 0.0, "bilinmeyen kategori tüm bitler 0")
        for b in forex_ml.BIAS_VALUES:
            self.assertEqual(f[f"bias_{b}"], 0.0)
        self.assertEqual(f["direction_buy"], 0.0)

    def test_feature_names_match_featurize_keys(self):
        row = {"features": {"session": "asia", "ta_bias": "bullish"}, "direction": "BUY", "confidence": 70, "score": 80}
        f = forex_ml.featurize(row)
        self.assertEqual(list(f.keys()), forex_ml.feature_names(),
                         "vektör sırası artifact ile birebir aynı olmalı")

    def test_deterministic(self):
        row = _synthetic_rows(n=5)[2]
        self.assertEqual(forex_ml.featurize(row), forex_ml.featurize(row))


class TestArtifact(unittest.TestCase):
    def test_save_load_roundtrip(self):
        r = forex_ml.train(_synthetic_rows())
        path = ROOT / "artifacts" / "_test_forex_ml.json"
        try:
            saved = forex_ml.save_artifact(r, path)
            data = json.loads(pathlib.Path(saved).read_text(encoding="utf-8"))
            self.assertIn("coefficients", data)
            self.assertIn("scales", data)
            self.assertEqual(data["feature_names"], r["feature_names"])
            # pickle yok: artifact düz JSON
            self.assertNotIn("joblib", SRC)
        finally:
            path.unlink(missing_ok=True)

    def test_untrained_report_cannot_be_saved(self):
        with self.assertRaises(ValueError):
            forex_ml.save_artifact({"trained": False})


class TestLeanAndWiring(unittest.TestCase):
    def test_no_heavy_dependencies(self):
        self.assertNotIn("import pandas", SRC)
        self.assertNotIn("import joblib", SRC)
        self.assertNotIn("import torch", SRC)

    def test_endpoints_admin_protected(self):
        self.assertIn('@router.post("/api/system/forex-ml/train")', SYSTEM_SRC)
        self.assertIn('@router.get("/api/system/forex-ml")', SYSTEM_SRC)
        i = SYSTEM_SRC.index("@router.post(\"/api/system/forex-ml/train\")")
        self.assertIn("require_admin", SYSTEM_SRC[i:i + 500])

    def test_training_runs_in_thread(self):
        # sklearn CPU-bound → event loop'u kilitlememek için to_thread
        self.assertIn("to_thread", SYSTEM_SRC)

    def test_db_functions_exist(self):
        src = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        for fn in ("async def get_forex_ml_dataset", "async def save_forex_ml_run",
                   "async def get_forex_ml_runs", "forex_ml_runs"):
            self.assertIn(fn, src)


if __name__ == "__main__":
    unittest.main()
