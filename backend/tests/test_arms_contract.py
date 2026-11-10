"""SİNYAL KOLU SÖZLEŞMESİ kilitleri (2026-11-10).

Desen: hummingbot/condor `agents/<rol>/controllers/` (MIT) — kol dosya olarak tanımlanır,
`signal()` sözleşmesine uyar; replay ve canlı aynı dosyayı kullanır.

Kilitlenen davranış:
  1. Sinyal değerleri yalnız **+1 / −1 / 0**; uzunluk bar sayısıyla aynı.
  2. **`0` "yeni sinyal yok" demektir; pozisyon KAPATMAZ** (sözleşme metni + davranış).
  3. `signal()` **saf**: aynı girdi → aynı çıktı; global durum/yan etki yok.
  4. Kol kaydı benzersiz (sessizce ezilmez) ve keşifle bulunur.
  5. İlk kol `tokyo_window` ölçülmüş pencerelerle uyumlu: 01:00'de LONG, 13:00 GBPUSD ve
     14:00 EURUSD SHORT, hafta sonu sinyal YOK.
"""
import datetime as dt
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.arms import base as ab  # noqa: E402
from app.arms import tokyo_window as tw  # noqa: E402


def _bars(start: dt.datetime, hours: int, step_min: int = 60):
    out = []
    for i in range(hours * (60 // step_min)):
        t = start + dt.timedelta(minutes=i * step_min)
        out.append((t.timestamp(), 1.0, 1.1, 0.9, 1.0))
    return out


class TestContract(unittest.TestCase):
    def test_validate_catches_length_mismatch(self):
        errs = ab.validate_signals([0, 1], n_bars=3, arm_name="x")
        self.assertTrue(any("uzunluk" in e for e in errs))

    def test_validate_catches_bad_values(self):
        errs = ab.validate_signals([0, 2, -3], n_bars=3, arm_name="x")
        self.assertTrue(any("geçersiz" in e for e in errs))

    def test_validate_accepts_contract_values(self):
        self.assertEqual(ab.validate_signals([1, -1, 0, 0], n_bars=4), [])

    def test_registry_rejects_duplicate(self):
        spec = ab.ArmSpec(name="_dup_test", description="t", timeframe="1h", symbols=[], handler=lambda b: [])
        ab.register_arm(spec)
        try:
            with self.assertRaises(ValueError):
                ab.register_arm(spec)
        finally:
            ab._REGISTRY.pop("_dup_test", None)

    def test_discovery_finds_tokyo_window(self):
        names = {a.name for a in ab.all_arms()}
        self.assertIn("tokyo_window", names)
        arm = ab.get_arm("tokyo_window")
        self.assertEqual(arm.timeframe, "1h")
        self.assertTrue(arm.vectorized)
        self.assertIn("t=", arm.evidence, "kanıt notu taşınmalı")


class TestTokyoWindowArm(unittest.TestCase):
    @staticmethod
    def _ts(y, m, d, hh, mm=0):
        return dt.datetime(y, m, d, hh, mm, tzinfo=dt.timezone.utc).timestamp()

    def test_signal_length_and_values(self):
        bars = _bars(dt.datetime(2026, 11, 9, tzinfo=dt.timezone.utc), hours=48)
        series = tw.signal(bars, "GBPUSD")
        self.assertEqual(len(series), len(bars))
        self.assertEqual(ab.validate_signals(series, len(bars), "tokyo_window"), [])

    def test_long_at_0100(self):
        # 2026-11-10 Salı 01:00 UTC
        bars = [(self._ts(2026, 11, 10, 1, 0), 1, 1, 1, 1)]
        self.assertEqual(tw.signal(bars, "GBPUSD"), [1])

    def test_short_windows(self):
        gbp13 = [(self._ts(2026, 11, 10, 13, 0), 1, 1, 1, 1)]
        eur14 = [(self._ts(2026, 11, 10, 14, 0), 1, 1, 1, 1)]
        self.assertEqual(tw.signal(gbp13, "GBPUSD"), [-1])
        self.assertEqual(tw.signal(eur14, "EURUSD"), [-1])

    def test_no_signal_outside_windows(self):
        bars = [(self._ts(2026, 11, 10, 5, 0), 1, 1, 1, 1)]
        self.assertEqual(tw.signal(bars, "GBPUSD"), [0])

    def test_no_signal_after_entry_window(self):
        bars = [(self._ts(2026, 11, 10, 1, 30), 1, 1, 1, 1)]
        self.assertEqual(tw.signal(bars, "GBPUSD"), [0])

    def test_weekend_has_no_signal(self):
        # 2026-11-14 Cumartesi 01:00
        bars = [(self._ts(2026, 11, 14, 1, 0), 1, 1, 1, 1)]
        self.assertEqual(tw.signal(bars, "GBPUSD"), [0])

    def test_unknown_symbol_all_zero(self):
        bars = [(self._ts(2026, 11, 10, 1, 0), 1, 1, 1, 1)]
        self.assertEqual(tw.signal(bars, "AUDNZD"), [0])

    def test_zero_does_not_close(self):
        """Sözleşme: 0 = yeni sinyal yok. Seri kavramsal olarak 'kapat' taşımaz."""
        self.assertEqual(ab.SIGNAL_NONE, 0)
        doc = ab.ArmSpec.__doc__ or ""
        module_doc = (ab.__doc__ or "")
        self.assertIn("KAPATMAZ", module_doc, "sözleşme metni 0'ın kapatmadığını yazmalı")

    def test_crossasset_lag_is_not_registered(self):
        """2026-11-10: çapraz-varlık gecikmesi ÖLÇÜMLE ELENDİ → kayıtlı kol OLMAMALI."""
        names = {a.name for a in ab.all_arms()}
        self.assertNotIn("crossasset_lag", names, "elenen aile kayda girmemeli")
        from app.arms import crossasset_lag as cal
        self.assertIn("ELENDİ", (cal.__doc__ or ""))
        self.assertIn("rho +0.025", cal.EVIDENCE)

    def test_vbt_candidates_are_not_registered(self):
        """2026-11-10: vectorbt adayları 10 yıllık günlükte tutmadı → kayıtlı OLMAMALI."""
        names = {a.name for a in ab.all_arms()}
        for nm in ("donchian_break", "ema_trend_cross", "ibs_reversion"):
            self.assertNotIn(nm, names, f"{nm} elendi ama kayıtlı")
        from app.arms import donchian_break, ema_trend_cross
        self.assertIn("ELENDİ", (donchian_break.__doc__ or ""))
        self.assertIn("10 yıl", donchian_break.EVIDENCE)
        self.assertIn("ELENDİ", (ema_trend_cross.__doc__ or ""))
        from app.arms import ibs_reversion as ibs
        self.assertIn("dolum", ibs.EVIDENCE_DETAIL.lower(), "dolum hassasiyeti yazılı olmalı")

    def test_purity_same_input_same_output(self):
        bars = _bars(dt.datetime(2026, 11, 9, tzinfo=dt.timezone.utc), hours=30)
        first = tw.signal(bars, "EURUSD")
        second = tw.signal(bars, "EURUSD")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
