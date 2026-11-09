"""COT ÜRETİCİSİ kilidi (2026-11-09) — app/cot_fetch.py.

NEDEN: `cot_positions` yalnız artefakt OKUR; üretim tek bir elle çalıştırılan
betikteydi. LLM bağlamına bağlandıktan sonra bu boşluk görünür oldu: üretimde
artefakt hiç üretilmediği için LLM sürekli "COT pozisyonlanma verisi yok" dedi
(kullanıcı raporu). Artık üretim `app/cot_fetch`'te ve ÜÇ yüzey aynı kodu çağırır:
CLI, panel ucu (`POST /api/system/cot-refresh`) ve otomatik tazeleme döngüsü.

Kilitlenen davranış:
  1. Yerel zip'ten artefakt ÜRETİLEBİLİYOR (ağ olmadan, uçtan uca).
  2. Hata fırlatmaz; çağıran yüzeyler (panel/döngü) çökmez, sözlükte `error` olur.
  3. `is_stale`: yok/bozuk artefakt BAYAT sayılır (sessiz boşluk yok), taze olan değil.
  4. Betik ince sarmalayıcı: mantık `app/cot_fetch` içinde (kopya kod yok).
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest
import zipfile
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import cot_fetch  # noqa: E402

SCRIPT_SRC = (ROOT / "scripts" / "fetch_cot_positions.py").read_text(encoding="utf-8")
SYSTEM_SRC = (ROOT / "app" / "routers" / "system.py").read_text(encoding="utf-8")
MAIN_SRC = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

COLS = ["Market_and_Exchange_Names", "Report_Date_as_YYYY-MM-DD", "Open_Interest_All",
        "Lev_Money_Positions_Long_All", "Lev_Money_Positions_Short_All",
        "Asset_Mgr_Positions_Long_All", "Asset_Mgr_Positions_Short_All",
        "Dealer_Positions_Long_All", "Dealer_Positions_Short_All"]


def _mk_zip(path: pathlib.Path, weeks: int = 3) -> pathlib.Path:
    """Sentetik TFF zip'i: EUR (majör) + çapraz kur (atılmalı) satırları."""
    lines = [",".join(f'"{c}"' for c in COLS)]
    for i in range(weeks):
        d = (date.today() - timedelta(days=7 * (weeks - 1 - i))).isoformat()
        for market, oi, ll, ls in (
            ("EURO FX - CHICAGO MERCANTILE EXCHANGE", 800000, 300000 + i * 5000, 250000),
            ("EURO FX/BRITISH POUND XRATE - CHICAGO MERCANTILE EXCHANGE", 1000, 10, 20),
        ):
            lines.append(f'"{market}","{d}",{oi},{ll},{ls},100000,90000,50000,40000')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("fut_fin_txt.txt", "\n".join(lines))
    return path


class TestRefresh(unittest.TestCase):
    def test_builds_artifact_from_local_zip(self):
        with tempfile.TemporaryDirectory() as d:
            zip_path = _mk_zip(pathlib.Path(d) / "src.zip")
            out = pathlib.Path(d) / "cot.json"
            res = cot_fetch.refresh(source_zip=str(zip_path), out=str(out))
            self.assertTrue(res["ok"], res.get("error"))
            self.assertEqual(res["currencies"], 1, "yalnız majör FX satırı sayılmalı")
            artifact = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("EUR", artifact["currencies"])
            self.assertNotIn("GBP", artifact["currencies"], "çapraz kur satırı atılmalı")
            self.assertTrue(artifact["report_date"])
            self.assertIn("bias", artifact["currencies"]["EUR"])

    def test_missing_source_returns_error_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            res = cot_fetch.refresh(source_zip=str(pathlib.Path(d) / "yok.zip"),
                                    out=str(pathlib.Path(d) / "out.json"))
            self.assertFalse(res["ok"])
            self.assertIn("error", res)

    def test_unparsable_source_returns_error(self):
        with tempfile.TemporaryDirectory() as d:
            bad = pathlib.Path(d) / "bad.zip"
            with zipfile.ZipFile(bad, "w") as z:
                z.writestr("x.txt", "a,b\n1,2\n")
            res = cot_fetch.refresh(source_zip=str(bad), out=str(pathlib.Path(d) / "out.json"))
            self.assertFalse(res["ok"])
            self.assertIn("FX satırı bulunamadı", str(res.get("error")))


class TestStaleness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_env = os.environ.get("COT_ARTIFACT_PATH")
        os.environ["COT_ARTIFACT_PATH"] = str(pathlib.Path(self._tmp.name) / "cot.json")
        from app import cot_positions
        cot_positions.reset_cache()

    def tearDown(self):
        from app import cot_positions
        if self._orig_env is None:
            os.environ.pop("COT_ARTIFACT_PATH", None)
        else:
            os.environ["COT_ARTIFACT_PATH"] = self._orig_env
        cot_positions.reset_cache()
        self._tmp.cleanup()

    def _write(self, report_date: str):
        path = pathlib.Path(os.environ["COT_ARTIFACT_PATH"])
        path.write_text(json.dumps({"report_date": report_date, "currencies": {}, "source": "t"}),
                        encoding="utf-8")
        from app import cot_positions
        cot_positions.reset_cache()

    def test_missing_artifact_is_stale(self):
        from app import cot_positions
        cot_positions.reset_cache()
        self.assertIsNone(cot_fetch.artifact_age_days())
        self.assertTrue(cot_fetch.is_stale(), "artefakt yoksa BAYAT sayılmalı (sessiz boşluk olmasın)")

    def test_fresh_artifact_not_stale(self):
        self._write(date.today().isoformat())
        self.assertFalse(cot_fetch.is_stale())
        self.assertLess(cot_fetch.artifact_age_days(), 1.0)

    def test_old_artifact_is_stale(self):
        self._write((date.today() - timedelta(days=20)).isoformat())
        self.assertTrue(cot_fetch.is_stale())
        self.assertGreater(cot_fetch.artifact_age_days(), 9.0)


class TestWiring(unittest.TestCase):
    def test_script_is_thin_cli_over_shared_module(self):
        self.assertIn("from app import cot_fetch", SCRIPT_SRC)
        self.assertIn("cot_fetch.refresh(", SCRIPT_SRC)
        # Ağ/ayrıştırma mantığı betikte KALMAMALI (kopya üretici = sapma riski)
        self.assertNotIn("urlopen", SCRIPT_SRC)
        self.assertNotIn("zipfile", SCRIPT_SRC)

    def test_panel_endpoint_exists(self):
        self.assertIn('@router.post("/api/system/cot-refresh")', SYSTEM_SRC)
        self.assertIn('@router.get("/api/system/cot")', SYSTEM_SRC)

    def test_auto_refresh_loop_started(self):
        self.assertIn("cot_refresh_background_loop", MAIN_SRC)
        self.assertIn("async def cot_refresh_background_loop", (ROOT / "app" / "cot_fetch.py").read_text(encoding="utf-8"))

    def test_network_work_is_offloaded_from_event_loop(self):
        # İndirme bloklayıcı (urllib) → asyncio.to_thread ile çağrılmalı
        i = SYSTEM_SRC.index('@router.post("/api/system/cot-refresh")')
        block = SYSTEM_SRC[i:i + 1400]
        self.assertIn("to_thread", block)


if __name__ == "__main__":
    unittest.main()
