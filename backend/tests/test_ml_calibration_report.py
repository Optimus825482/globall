"""ML OLASILIK KALİBRASYON RAPORU kilidi (2026-11-09) — app/ml_calibration_report.py.

Neden: kalibrasyon sonucu yalnız sağlık ucunda SAYAÇ olarak görünüyordu; panel
raporu ve CSV ilk kez bu modülle açıldı. Burada SAF hesaplama kilitlenir (DB'ye
bağlı kısım `get_shadow_predictions` ile sunucuda koşar).

Kilitlenen davranış:
  1. Aşırı güvenli sentetik veride **in-sample** kalibrasyon Brier'ı düşürür.
  2. ASIL kanıt out-of-sample: eğri ilk %65'te kurulur, son %35'te ölçülür.
     Rapor bu bölümü ayrı verir (in-sample ECE ~0 bir YANILSAMADIR).
  3. Eşik eğrisi: kapsam + isabet + lift (eşiğe kilitlenmek yerine eğri).
  4. Yetersiz örnekte hüküm VERİLMEZ ("fal bakma" yok).
  5. CSV: başlık sayısı = satır genişliği; kalibre olasılık kolonu ham ile
     aynı satırda; hedef/hedef-vuruldu alanları Türkçe evet/hayır.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ml_calibration_report as mcr  # noqa: E402

SRC = (ROOT / "app" / "routers" / "reports.py").read_text(encoding="utf-8")


def row(prob, exit_pct, *, target=1.0, hit=None, **kw):
    return {"hit_probability": prob, "exit_pct": exit_pct, "target_pct": target,
            "hit_target": (exit_pct > 0) if hit is None else hit,
            "symbol": kw.pop("symbol", "XAUUSD"), "predicted_at": kw.pop("predicted_at", 1_700_000_000.0),
            "horizon_minutes": 60, "gate_passed": True, "status": "evaluated", **kw}


def overconfident_rows(n=900, seed=5, win=0.34):
    import random
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        p = rnd.choice([0.55, 0.62, 0.7, 0.78, 0.85])
        won = rnd.random() < win
        out.append(row(p, (+1.0 if won else -0.6), predicted_at=1_700_000_000.0 + i,
                       symbol=rnd.choice(["XAUUSD", "EURUSD", "BTCUSD"])))
    return out


class TestSummary(unittest.TestCase):
    def test_in_sample_calibration_improves_brier(self):
        r = mcr.summarize_rows(overconfident_rows())
        self.assertTrue(r["fitted"])
        self.assertLess(r["metrics_calibrated"]["brier"], r["metrics_raw"]["brier"],
                        "izotonik eğri aşırı güveni düzeltmeli")
        self.assertLess(r["metrics_calibrated"]["ece"], r["metrics_raw"]["ece"])

    def test_out_of_sample_block_is_the_real_evidence(self):
        r = mcr.summarize_rows(overconfident_rows())
        oos = r["out_of_sample"]
        self.assertTrue(oos["available"])
        self.assertEqual(oos["n_train"] + oos["n_test"], r["samples"])
        self.assertGreater(oos["n_train"], oos["n_test"])
        # test kümesinde ölçülmüş ham metrikler de verilir (karşılaştırma için)
        self.assertIn("brier", oos["raw"])
        self.assertIn("brier", oos["calibrated"])

    def test_insufficient_samples_no_verdict(self):
        r = mcr.summarize_rows(overconfident_rows(n=50))
        self.assertFalse(r["fitted"])
        self.assertIn("yetersiz", r["reason"])
        self.assertNotIn("out_of_sample", r)          # hüküm yok

    def test_break_even_vs_base_rate_reported(self):
        r = mcr.summarize_rows(overconfident_rows())
        self.assertIn("break_even", r)
        self.assertEqual(r["break_even_reachable"], r["base_rate"] >= r["break_even"])

    def test_threshold_curve_has_coverage_and_lift(self):
        r = mcr.summarize_rows(overconfident_rows())
        curve = r["threshold_curve"]
        self.assertTrue(curve)
        for point in curve:
            self.assertIn("coverage", point)
            self.assertGreaterEqual(point["coverage"], 0.0)
            self.assertLessEqual(point["coverage"], 1.0)
        # yüksek eşik → daha düşük kapsam
        with_data = [c for c in curve if c["n"] >= 10]
        if len(with_data) >= 2:
            self.assertLessEqual(with_data[-1]["coverage"], with_data[0]["coverage"])

    def test_invalid_rows_skipped(self):
        rows = [{"hit_probability": None, "exit_pct": 1.0}, {"hit_probability": "x", "exit_pct": 1.0}]
        r = mcr.summarize_rows(rows * 300)
        self.assertEqual(r["samples"], 0)


class TestCsv(unittest.TestCase):
    def test_headers_and_width_match(self):
        rows = overconfident_rows(n=120)
        headers, body = mcr.csv_rows(rows)
        self.assertEqual(len(body), len(rows))
        for r in body:
            self.assertEqual(len(r), len(headers), "satır genişliği başlıkla eşleşmeli")

    def test_derived_columns_present(self):
        headers, body = mcr.csv_rows(overconfident_rows(n=120))
        idx_raw = headers.index("ham_olasilik")
        idx_cal = headers.index("kalibre_olasilik")
        idx_r = headers.index("R")
        idx_hit = headers.index("hedef_vuruldu")
        for r in body:
            self.assertIsNotNone(r[idx_raw])
            self.assertIsNotNone(r[idx_r], "R = cikis/hedef hesaplanmalı")
            self.assertIn(r[idx_hit], ("evet", "hayır"))
            # kalibre kolonu ya sayı ya boş (artefakt yoksa) — çökme yok
            self.assertTrue(r[idx_cal] is None or isinstance(r[idx_cal], float))

    def test_time_is_formatted(self):
        headers, body = mcr.csv_rows(overconfident_rows(n=5))
        idx = headers.index("tahmin_zamani")
        for r in body:
            self.assertRegex(str(r[idx]), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class TestWiring(unittest.TestCase):
    def test_endpoints_exist(self):
        self.assertIn('@router.get("/api/reports/ml-calibration")', SRC)
        self.assertIn('@router.get("/api/reports/ml-calibration/csv")', SRC)

    def test_csv_is_excel_friendly(self):
        self.assertIn('output.write("\\ufeff")', SRC)
        self.assertIn('delimiter=";"', SRC)
        self.assertIn("Content-Disposition", SRC)

    def test_panel_and_csv_share_one_module(self):
        # İki ayrı hesap olsaydı ekran ile indirilen dosya birbirini tutmazdı.
        self.assertEqual(SRC.count("from app import ml_calibration_report as mcr"), 2)

    def test_errors_do_not_500(self):
        i = SRC.index('@router.get("/api/reports/ml-calibration")')
        block = SRC[i:i + 700]
        self.assertIn("except Exception", block)


class TestConfigAccess(unittest.TestCase):
    """`from app import config` YANLIŞ: config bir MODÜL değil, `Config()`
    singleton'ıdır (`app/config.py:1100`). 2026-11-09'da bu hata raporda
    "AttributeError: module 'app.config' has no attribute 'ML_CALIBRATION_ARTIFACT'"
    olarak panele düştü — kullanıcı sıfır rapor gördü.
    """

    def test_report_uses_singleton(self):
        src = (ROOT / "app" / "ml_calibration_report.py").read_text(encoding="utf-8")
        self.assertIn("from app.config import config as _cfg", src)
        self.assertNotIn("from app import config as", src)

    def test_no_module_style_config_usage_anywhere(self):
        hits = []
        for path in (ROOT / "app").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "from app import config as" in text:
                hits.append(path.name)
        self.assertEqual(hits, [], f"config singleton olarak import edilmeli: {hits}")

    def test_artifact_error_is_honest_not_traceback(self):
        """Artefakt yoksa panelde teknik istisna değil, NE YAPILACAĞI yazmalı."""
        rep = mcr._artifact_summary()
        if not rep.get("available"):
            self.assertNotIn("AttributeError", str(rep.get("reason")))
            self.assertIn("artefakt", str(rep.get("reason")).lower())

    def test_partial_samples_explain_remaining(self):
        r = mcr.summarize_rows(overconfident_rows(n=150))
        self.assertFalse(r["fitted"])
        self.assertEqual(r.get("samples_needed"), mcr.MIN_SAMPLES - 150)
        self.assertIn("örnek daha birikince", r["reason"])


if __name__ == "__main__":
    unittest.main()
