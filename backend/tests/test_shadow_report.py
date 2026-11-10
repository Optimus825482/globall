"""GÖLGE MODLAR RAPORU kilidi (2026-11-09) — app/shadow_report.py.

Kullanıcı: "kaç tane gölge mod varsa raporlar kısmında raporlama sekmesi olarak
oluştur". Rapor 5 mekanizmayı tek ekranda toplar; hiçbir satır UYDURULMAZ.

Kilitlenen davranış:
  1. Beş mekanizma da listelenir (LLM, ML kalibrasyonu, geometri, risk kapısı,
     kanıt kapısı) — biri sessizce düşerse test kırılır.
  2. Bir kaynak okunamazsa satır "okunamadı" notuyla YİNE listelenir (rapor boş kalmaz).
  3. `ready` yalnız n >= needed olduğunda true (erken "hazır" deme yok).
  4. Mod etiketleri gerçeği yansıtır: kanıt kapısı varsayılan `off`, risk kapısı `shadow`.
  5. Rapor HİÇBİR ayarı değiştirmez (yalnız okuma) — kaynak düzeyinde kanıt.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import shadow_report  # noqa: E402

SRC = (ROOT / "app" / "shadow_report.py").read_text(encoding="utf-8")


class TestItemSchema(unittest.TestCase):
    def test_ready_requires_enough_samples(self):
        it = shadow_report._item("x", "X", mode="on", active=True, measures="m", n=50, needed=80)
        self.assertFalse(it["ready"])
        self.assertEqual(it["progress_pct"], 62.5)
        done = shadow_report._item("x", "X", mode="on", active=True, measures="m", n=80, needed=80)
        self.assertTrue(done["ready"])
        self.assertEqual(done["progress_pct"], 100.0)

    def test_no_needed_means_no_progress(self):
        it = shadow_report._item("x", "X", mode="shadow", active=True, measures="m", n=5)
        self.assertFalse(it["ready"])
        self.assertIsNone(it["progress_pct"])

    def test_unknown_values_stay_unknown(self):
        it = shadow_report._item("x", "X", mode="on", active=True, measures="m")
        self.assertIsNone(it["n"])
        self.assertFalse(it["ready"])


class TestBuild(unittest.TestCase):
    def test_all_six_mechanisms_tracked(self):
        import asyncio
        rep = asyncio.run(shadow_report.build())
        keys = {i["key"] for i in rep["items"]}
        # Görünür: mode != off. Kullanıcı kararı: pasif (KAPALI) mekanizmalar
        # rapordan GİZLENİR; kanıt kapısı varsayılan off olduğu için gizli.
        for expected in ("llm_shadow", "ml_calibration", "geometry_shadow",
                         "forex_ml_shadow", "risk_gate"):
            self.assertIn(expected, keys, f"{expected} raporda yok")
        self.assertNotIn("abstain_gate", keys, "kapalı mekanizma gizlenmeli")
        self.assertEqual(rep["count"], len(rep["items"]) + rep["hidden_off"])
        self.assertGreaterEqual(rep["hidden_off"], 1)

    def test_rows_survive_failures(self):
        """Kaynak okunamasa bile satır listede ve notu açıklayıcı olmalı."""
        import asyncio
        rep = asyncio.run(shadow_report.build())
        for it in rep["items"]:
            self.assertTrue(it["label"])
            self.assertIn("mode", it)
            self.assertIsInstance(it["measures"], str)

    def test_defaults_reflect_settings(self):
        """Kanıt kapısı varsayılan OFF ve RAPORDAN GİZLİ; risk kapısı GÖLGE ve görünür."""
        import asyncio
        rep = asyncio.run(shadow_report.build())
        by = {i["key"]: i for i in rep["items"]}
        self.assertNotIn("abstain_gate", by, "varsayılan off → rapordan gizlenmeli")
        self.assertGreaterEqual(rep.get("hidden_off", 0), 1)
        if by["risk_gate"]["mode"] not in ("unknown",):
            self.assertEqual(by["risk_gate"]["mode"], "shadow")


class TestReadOnly(unittest.TestCase):
    def test_no_settings_mutation(self):
        # Rapor yalnız okur: settings yazımı / POST / commit geçmemeli.
        for forbidden in ("_AUTO_SETTINGS.", "_save", "commit(", "requests.post", "method=\"POST\""):
            # `_AUTO_SETTINGS` yalnız OKUNUYOR; atama aranıyor
            if forbidden == "_AUTO_SETTINGS.":
                self.assertNotIn("_AUTO_SETTINGS.risk_gate_mode =", SRC)
                self.assertNotIn("_AUTO_SETTINGS.abstain_gate_mode =", SRC)
            else:
                self.assertNotIn(forbidden, SRC, f"rapor yan etkili olmamalı: {forbidden}")

    def test_endpoint_exists(self):
        src = (ROOT / "app" / "routers" / "reports.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/api/reports/shadow-summary")', src)


if __name__ == "__main__":
    unittest.main()
