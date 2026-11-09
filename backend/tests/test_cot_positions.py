"""COT POZİSYONLANMA kilitleri (2026-11-09) — app/cot_positions.py.

Kilitlenen davranış:
  1. `parse_rows` doğru net/%-OI hesaplar; ÇAPRAZ KUR satırlarını atar
     (EUR/GBP XRATE gibi satırlar EUR sayılmamalı — çift sayım olurdu).
  2. Geçersiz/eksik OI satırı atılır (sıfıra bölme yok).
  3. `bias` tanh ölçeğinde ve işareti doğru; NEUTRAL bandı çalışır.
  4. `crowding_pct` mutlak pozisyonun tarihsel yüzdeliği; %90 eşiği `crowded`.
  5. `change_wow_pct` yalnız önceki hafta varsa hesaplanır.
  6. `divergence`: sıcak para ile gerçek para ZIT yöndeyse True.
  7. `load_artifact`: yok/bozuk → None (uydurma yok); mtime değişince yeniden okur.
  8. `summary`/`bias`: tazelik (`stale`) doğru; bilinmeyen kur → None.
  9. Dosyada OLMAYAN para birimi (NZD) `unavailable` listesinde, uydurulmaz.
"""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import cot_positions as cot  # noqa: E402

EUR = "EURO FX - CHICAGO MERCANTILE EXCHANGE"
JPY = "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE"
XRT = "EURO FX/BRITISH POUND XRATE - CHICAGO MERCANTILE EXCHANGE"


def row(market, date, oi, lev_l, lev_s, am_l=None, am_s=None, dl=0, ds=0):
    return {
        "Market_and_Exchange_Names": market,
        "Report_Date_as_YYYY-MM-DD": date,
        "Open_Interest_All": str(oi),
        "Lev_Money_Positions_Long_All": str(lev_l),
        "Lev_Money_Positions_Short_All": str(lev_s),
        "Asset_Mgr_Positions_Long_All": "" if am_l is None else str(am_l),
        "Asset_Mgr_Positions_Short_All": "" if am_s is None else str(am_s),
        "Dealer_Positions_Long_All": str(dl),
        "Dealer_Positions_Short_All": str(ds),
    }


class TestParseRows(unittest.TestCase):
    def test_net_and_pct(self):
        parsed = cot.parse_rows([row(EUR, "2026-11-03", 1000, 300, 100, 50, 250)])
        self.assertEqual(len(parsed), 1)
        r = parsed[0]
        self.assertEqual(r["currency"], "EUR")
        self.assertEqual(r["lev_net"], 200)
        self.assertAlmostEqual(r["lev_net_pct"], 20.0, places=3)
        self.assertEqual(r["asset_mgr_net"], -200)
        self.assertAlmostEqual(r["asset_mgr_net_pct"], -20.0, places=3)

    def test_cross_rate_excluded(self):
        parsed = cot.parse_rows([row(XRT, "2026-11-03", 1000, 300, 100),
                                 row(EUR, "2026-11-03", 1000, 300, 100)])
        self.assertEqual([r["currency"] for r in parsed], ["EUR"],
                         "çapraz kur EUR'u ikinci kez saymamalı")

    def test_invalid_or_zero_oi_skipped(self):
        parsed = cot.parse_rows([
            row(EUR, "2026-11-03", 0, 10, 5),        # OI 0 → at
            row(EUR, "2026-10-27", 1000, "", 5),     # lev long boş → at
            row(EUR, "2026-10-20", 1000, 10, 5),     # geçerli
        ])
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["date"], "2026-10-20")

    def test_sorted_by_currency_then_date(self):
        parsed = cot.parse_rows([
            row(JPY, "2026-11-03", 100, 10, 5),
            row(EUR, "2026-11-03", 100, 10, 5),
            row(EUR, "2026-10-27", 100, 10, 5),
        ])
        self.assertEqual([(r["currency"], r["date"]) for r in parsed],
                         [("EUR", "2026-10-27"), ("EUR", "2026-11-03"), ("JPY", "2026-11-03")])


class TestStats(unittest.TestCase):
    def _series(self, values):
        """lev_net_pct değerlerinden yapay seri (OI=1000 sabit)."""
        out = []
        for i, pct in enumerate(values):
            lev_net = pct * 10.0  # %OI = lev_net/1000*100 → lev_net = pct*10
            out.append({"currency": "EUR", "date": f"2026-01-{i+1:02d}",
                        "open_interest": 1000.0, "lev_long": lev_net, "lev_short": 0.0,
                        "lev_net": lev_net, "lev_net_pct": pct,
                        "asset_mgr_net": None, "asset_mgr_net_pct": None,
                        "dealer_net": None})
        return out

    def test_bias_sign_and_scale(self):
        pos = cot.compute_currency_stats(self._series([15.0]))
        self.assertGreater(pos["bias"], 0.7)
        self.assertEqual(pos["stance"], "LONG")
        neg = cot.compute_currency_stats(self._series([-15.0]))
        self.assertLess(neg["bias"], -0.7)
        self.assertEqual(neg["stance"], "SHORT")

    def test_neutral_band(self):
        flat = cot.compute_currency_stats(self._series([1.0]))
        self.assertEqual(flat["stance"], "NEUTRAL")
        self.assertLess(abs(flat["bias"]), cot.NEUTRAL_BAND)

    def test_crowding_is_percentile_of_absolute(self):
        # Tarihsel |değerler| 1..10; son değer 10 → yüzdelik ~%95-100 → crowded
        series = self._series([float(v) for v in range(1, 11)])
        stats = cot.compute_currency_stats(series)
        self.assertGreaterEqual(stats["crowding_pct"], cot.CROWDED_PERCENTILE)
        self.assertTrue(stats["crowded"])
        # Son değer ortada ise crowded OLMAMALI
        mid = cot.compute_currency_stats(self._series([1, 2, 3, 4, 5, 3, 4, 5, 4, 4]))
        self.assertFalse(mid["crowded"])

    def test_change_wow_none_on_single_point(self):
        self.assertIsNone(cot.compute_currency_stats(self._series([5.0]))["change_wow_pct"])
        d = cot.compute_currency_stats(self._series([5.0, 8.0]))
        self.assertAlmostEqual(d["change_wow_pct"], 3.0, places=3)

    def test_divergence_detected(self):
        series = self._series([-9.0])
        series[-1]["asset_mgr_net_pct"] = 16.5   # zıt yön → True
        self.assertTrue(cot.compute_currency_stats(series)["divergence"])
        series[-1]["asset_mgr_net_pct"] = -3.0   # aynı yön → False
        self.assertFalse(cot.compute_currency_stats(series)["divergence"])
        series[-1]["asset_mgr_net_pct"] = None   # veri yok → None
        self.assertIsNone(cot.compute_currency_stats(series)["divergence"])


class TestArtifactAndReading(unittest.TestCase):
    def _artifact(self):
        parsed = cot.parse_rows([
            row(EUR, "2026-10-27", 1000, 100, 50, 80, 20),
            row(EUR, "2026-11-03", 1000, 300, 100, 50, 250),
            row(JPY, "2026-11-03", 500, 20, 120, 200, 10),
        ])
        return cot.build_artifact(parsed)

    def test_report_date_is_max(self):
        self.assertEqual(self._artifact()["report_date"], "2026-11-03")

    def test_unavailable_lists_nzd(self):
        self.assertIn("NZD", self._artifact()["unavailable"])

    def test_load_missing_and_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            cot.reset_cache()
            self.assertIsNone(cot.load_artifact(str(pathlib.Path(tmp) / "yok.json")))
            bad = pathlib.Path(tmp) / "bad.json"
            bad.write_text("{ bozuk", encoding="utf-8")
            self.assertIsNone(cot.load_artifact(str(bad)))

    def test_load_valid_and_mtime_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            cot.reset_cache()
            path = pathlib.Path(tmp) / "cot.json"
            path.write_text(json.dumps(self._artifact()), encoding="utf-8")
            first = cot.load_artifact(str(path), max_age_seconds=0)
            self.assertIsNotNone(first)
            self.assertIn("EUR", first["currencies"])
            # İçeriği değiştir + mtime'ı ilerlet → yeniden okunmalı
            import os
            import time
            new = self._artifact()
            new["report_date"] = "2026-11-10"
            path.write_text(json.dumps(new), encoding="utf-8")
            os.utime(path, (time.time() + 5, time.time() + 5))
            again = cot.load_artifact(str(path), max_age_seconds=0)
            self.assertEqual(again["report_date"], "2026-11-10")

    def test_bias_helper_and_unknown_currency(self):
        art = self._artifact()
        eur = cot.bias("EUR", artifact=art)
        self.assertIsNotNone(eur)
        self.assertEqual(eur["stance"], "LONG")     # lev_net_pct +20
        self.assertIsNone(cot.bias("NZD", artifact=art), "olmayan kur None dönmeli")

    def test_summary_without_artifact(self):
        # ORTAMDAN BAĞIMSIZ olmalı: repo'da gerçek artefakt varsa bile bu test
        # "yok" senaryosunu ölçmeli → COT_ARTIFACT_PATH'i var olmayan yola çek.
        import os
        prev = os.environ.get("COT_ARTIFACT_PATH")
        os.environ["COT_ARTIFACT_PATH"] = str(pathlib.Path(tempfile.gettempdir()) / "cot_yok_12345.json")
        cot.reset_cache()
        try:
            s = cot.summary(artifact=None)
            self.assertFalse(s["available"], "artefakt yokken available=False olmalı")
            self.assertTrue(s["stale"])
        finally:
            if prev is None:
                os.environ.pop("COT_ARTIFACT_PATH", None)
            else:
                os.environ["COT_ARTIFACT_PATH"] = prev
            cot.reset_cache()

    def test_summary_with_artifact(self):
        s = cot.summary(artifact=self._artifact())
        self.assertTrue(s["available"])
        self.assertEqual(s["report_date"], "2026-11-03")
        self.assertIn("EUR", s["currencies"])


if __name__ == "__main__":
    unittest.main()
