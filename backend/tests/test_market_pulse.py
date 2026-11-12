"""KÜRESEL VARLIK NABZI — bilinen-cevaplı sentetik testler (2026-11-09).

`market_pulse` LLM'e VIX/DXY/ABD 10Y/altın/petrol/SPX cross-asset bağlamı
verir. Kanal: her yorum kuralı ölçülen SAYIYA bağlıdır; veri yoksa satır
"veri yok"tur, nötr sanılmaz ve uydurulmaz — bu sözleşme testlerle kilitli.

AĞ YOK: `app.market_pulse._fetch_candles` mock'lanır (mock yoksa test paketi
Yahoo'ya çıkmaz — üretim imajı testleri izole kalmalı).
"""
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import market_pulse as mp  # noqa: E402


def _candles(closes, step=86400):
    t0 = 1700000000
    return [{"time": t0 + i * step, "open": c, "high": c, "low": c, "close": c}
            for i, c in enumerate(closes)]


def _row(last, prev):
    """Tek varlık satırı — gerçek `pulse` hesabıyla aynı aritmetik."""
    return {"label": "x", "available": True, "last": last, "prev": prev,
            "chg_pct": (last / prev - 1.0) * 100.0, "chg_abs": last - prev}


class TestChangeRow(unittest.TestCase):
    def test_known_answer_change_pct(self):
        # 90 → 100 = %+11.11 (5 günlük pencere, son kapanış dahil değil kuralı YOK:
        # pencere `len(closes) - 1 - 5` ile İLK kapanıştan geriye sayılır).
        row = mp._change_row(_candles([90.0] * 6 + [100.0]))
        self.assertEqual(row["last"], 100.0)
        self.assertAlmostEqual(row["chg_pct"], 11.111, places=2)

    def test_short_series_returns_none(self):
        # 6 kapanıştan az bar → pencere kurulamaz → None (uydurma yok).
        self.assertIsNone(mp._change_row(_candles([1.0] * 4)))

    def test_zero_prev_guard(self):
        self.assertIsNone(mp._change_row(_candles([0.0] * 7)))


class TestInterpretRules(unittest.TestCase):
    """Yorum kuralları deterministiktir — aynı sayı → aynı cümle."""

    def test_vix_stress_band(self):
        self.assertIn("STRES rejimi", mp._vix_note(27.5, 10.0))

    def test_vix_calm_band(self):
        self.assertIn("sakin rejim", mp._vix_note(13.0, -2.0))

    def test_dxy_strong_pressure(self):
        self.assertIn("GÜÇLÜ baskı", mp._dxy_note(1.5))

    def test_rate_note_bps(self):
        # 4.75 → 4.88 = +0.13 pp = +13 baz puan, yön yukarı.
        note = mp._rate_note(2.7, 0.13)
        self.assertIn("+13 baz puan", note)
        self.assertIn("yükseliyor", note)

    def test_gold_and_dxy_together_yields_safe_haven_note(self):
        rows = {"dxy": _row(102.5, 101.0), "gold": _row(2680.0, 2650.0)}
        notes = mp._interpret(rows)
        self.assertTrue(any("BİRLİKTE yükseliyor" in n for n in notes))

    def test_vix_up_and_spx_down_yields_risk_off_note(self):
        rows = {"vix": _row(24.0, 20.0), "spx": _row(6000.0, 6100.0)}
        notes = mp._interpret(rows)
        self.assertTrue(any("DARALIYOR" in n for n in notes))

    def test_no_cross_note_without_both_sides(self):
        # Tek tarafın verisi varsa çapraz okuma KURULMAZ (sessiz boşluk kuralı).
        rows = {"gold": _row(2680.0, 2650.0)}
        notes = mp._interpret(rows)
        self.assertFalse(any("BİRLİKTE" in n for n in notes))


class TestPulse(unittest.TestCase):
    def setUp(self):
        mp.reset_cache()

    def _full_fake(self, ticker):
        return _candles([90.0] * 6 + [100.0])

    def test_full_data(self):
        with mock.patch.object(mp, "_fetch_candles", side_effect=self._full_fake):
            s = mp.summary()
        self.assertTrue(s["available"])
        self.assertEqual(len(s["assets"]), len(mp.ASSETS))
        self.assertFalse(s.get("partial"))
        self.assertTrue(s["notes"])  # her varlık için en az bir yorum satırı

    def test_partial_data_is_flagged_and_missing_rows_say_veri_yok(self):
        def fake(ticker):
            return [] if ticker == "^VIX" else self._full_fake(ticker)

        with mock.patch.object(mp, "_fetch_candles", side_effect=fake):
            s = mp.summary()
            lines = mp.compact_lines()
        self.assertTrue(s["available"])
        self.assertTrue(s["partial"])
        self.assertIn("vix", s["missing"])
        self.assertFalse(s["assets"]["vix"]["available"])
        self.assertTrue(any("VIX" in l and "veri yok" in l for l in lines))

    def test_all_failed_fail_closed(self):
        with mock.patch.object(mp, "_fetch_candles", return_value=[]):
            s = mp.summary()
        self.assertFalse(s["available"])
        self.assertEqual(s["notes"], [])
        self.assertIn("uydurulmaz", s["reason"])
        self.assertTrue(any("nabzı" in l for l in mp.compact_lines()))

    def test_cache_prevents_second_fetch(self):
        with mock.patch.object(mp, "_fetch_candles",
                               side_effect=self._full_fake) as f:
            mp.summary()
            n1 = f.call_count
            mp.summary()
            self.assertEqual(f.call_count, n1)  # TTL içinde yeniden istek YOK
            mp.summary(force=True)
            self.assertGreater(f.call_count, n1)

    def test_cached_summary_never_touches_network(self):
        # reset sonrası health yolu "ısınma" der; pulse çağırıp AĞA ÇIKMAZ.
        s = mp.cached_summary()
        self.assertFalse(s["available"])
        self.assertTrue(s["warming"])
        with mock.patch.object(mp, "_fetch_candles", side_effect=self._full_fake):
            mp.summary()
        self.assertFalse(mp.cached_summary().get("warming"))

    def test_us10y_line_uses_percent_format(self):
        def fake(ticker):
            return _candles([4.75] * 6 + [4.88]) if ticker == "^TNX" else self._full_fake(ticker)

        with mock.patch.object(mp, "_fetch_candles", side_effect=fake):
            lines = mp.compact_lines()
        self.assertTrue(any("ABD 10Y verim %4.88" in l for l in lines),
                        f"10Y satırı yüzde biçiminde olmalı: {lines}")

    def test_reset_cache(self):
        with mock.patch.object(mp, "_fetch_candles",
                               side_effect=self._full_fake) as f:
            mp.summary()
            mp.reset_cache()
            mp.summary()
            self.assertEqual(f.call_count, len(mp.ASSETS) * 2)


class TestContextWiring(unittest.TestCase):
    """Tek uygulama kuralı: context_extras nabzı market_pulse'dan alır."""

    def test_cross_asset_lines_delegates_to_market_pulse(self):
        src = (ROOT / "app" / "context_extras.py").read_text(encoding="utf-8")
        self.assertIn("mp.compact_lines()", src)
        self.assertIn('"kuresel_varlik_nabzi": cross_asset_block()', src)

    def test_health_uses_cached_summary(self):
        src = (ROOT / "app" / "routers" / "system.py").read_text(encoding="utf-8")
        self.assertIn("market_pulse.cached_summary()", src)
        self.assertNotIn("market_pulse.summary()", src)  # health AĞA ÇIKMAZ

    def test_macro_context_contains_pulse_block(self):
        from app import context_extras as cx
        with mock.patch.object(mp, "summary",
                               return_value={"available": False,
                                             "reason": "test: yok"}):
            ctx = cx.macro_context("EURUSD")
        self.assertEqual(
            set(ctx),
            {"seans_ve_likidite", "cot_pozisyonlanma",
             "istatistiksel_dogrulama", "kuresel_varlik_nabzi",
             "perakende_konumlanma"})
        self.assertFalse(ctx["kuresel_varlik_nabzi"]["available"])
        self.assertIn("uydurulmaz", ctx["kuresel_varlik_nabzi"]["note"])

    def test_compact_lines_includes_pulse(self):
        from app import context_extras as cx
        with mock.patch.object(mp, "summary", return_value={
            "available": True, "assets": {},
            "notes": ["VIX 20.65: normal-üstü gerginlik"],
        }):
            lines = cx.cross_asset_lines()
        self.assertTrue(any("VIX 20.65" in l for l in lines))


if __name__ == "__main__":
    unittest.main()
