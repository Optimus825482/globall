"""GEOMETRİ GÖLGESİ kilitleri (2026-11-09) — app/geometry_shadow.py.

Kilitlenen davranış:
  1. Hedef **ATR × çarpan**, olasılıktan BAĞIMSIZ; [min, max] aralığına kırpılır.
  2. ATR okunamazsa hedef üretilmez (`skipped`) — uydurma yok.
  3. Değerlendirme gerçek değerlendirmenin `_first_stop_or_target_bar` sözleşmesini
     kullanır (enjekte edilir) → belirsizlik kuralı birebir aynı.
  4. TARGET_HIT → exit=+hedef, net=hedef−maliyet; STOPPED_OUT → exit=−SL, net=−SL−maliyet.
  5. **KRİTİK:** daha dar SL, gerçek geometride TP'ye ulaşan bir işlemi
     stop edebilir — gölge gerçekten FARKLI sonuç üretir (karşı-olgusal değil, ölçüm).
  6. EXPIRED → son mumun kapanışı; PENDING → henüz çözülmemiş.
  7. Kapalıyken (`GEOMETRY_SHADOW_ENABLED=0`) `skipped=disabled`.
  8. Belirsiz bar (high ≥ hedef iken SL) `intrabar_ambiguous=True`.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import geometry_shadow as gs  # noqa: E402
from app.config import config  # noqa: E402
# GERÇEK yürüyüş fonksiyonu — gölge testi üretim sözleşmesine karşı koşsun.
from app.routers.velocity import _first_stop_or_target_bar  # noqa: E402

COST = 0.35
NOW = 10_000_000
DUE = 9_000_000          # NOW > DUE → "süre doldu" kabul edilir


def bar(t_ms, o, h, l, c, v=1.0):
    return [t_ms, o, h, l, c, v]


class _Cfg(unittest.TestCase):
    def setUp(self):
        self._orig = {k: getattr(config, k) for k in (
            "GEOMETRY_SHADOW_ENABLED", "GEOMETRY_SHADOW_SL_PCT", "GEOMETRY_SHADOW_ATR_MULT",
            "GEOMETRY_SHADOW_TARGET_MIN", "GEOMETRY_SHADOW_TARGET_MAX")}

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(config, k, v)


class TestTargetFromAtr(_Cfg):
    def test_atr_multiple(self):
        config.GEOMETRY_SHADOW_ATR_MULT = 4.0
        self.assertAlmostEqual(gs.target_pct_for(0.5), 2.0, places=4)
        self.assertAlmostEqual(gs.target_pct_for(1.0), 4.0, places=4)

    def test_clamped_both_sides(self):
        config.GEOMETRY_SHADOW_TARGET_MIN = 0.4
        config.GEOMETRY_SHADOW_TARGET_MAX = 6.0
        self.assertAlmostEqual(gs.target_pct_for(0.01), 0.4, places=4)   # aşırı küçük
        self.assertAlmostEqual(gs.target_pct_for(5.0), 6.0, places=4)    # aşırı büyük

    def test_invalid_atr_returns_none(self):
        for bad in (None, 0, -1, "abc", float("nan"), float("inf")):
            self.assertIsNone(gs.target_pct_for(bad), f"{bad!r} → None beklenir")


class TestEvaluate(_Cfg):
    def _run(self, window, *, entry=100.0, atr=0.5, now_ms=NOW, due_ms=DUE):
        return gs.evaluate(window=window, entry=entry, atr_pct=atr, cost_pct=COST,
                           first_hit_fn=_first_stop_or_target_bar,
                           now_ms=now_ms, due_ms=due_ms)

    def test_target_hit_economics(self):
        # ATR 0.5 → hedef %2.0 (102.0), SL %0.9 (99.1); bar high 102.5 → TP
        out = self._run([bar(1, 100, 102.5, 99.5, 102.0)])
        self.assertEqual(out["status_reason"], "TARGET_HIT")
        self.assertAlmostEqual(out["target_pct"], 2.0, places=4)
        self.assertAlmostEqual(out["exit_pct"], 2.0, places=4)
        self.assertAlmostEqual(out["net_pct"], 2.0 - COST, places=4)

    def test_stop_loss_economics(self):
        # bar low 98.9 → SL %0.9 (99.1) vurulur
        out = self._run([bar(1, 100, 100.4, 98.9, 99.0)])
        self.assertEqual(out["status_reason"], "STOPPED_OUT")
        self.assertAlmostEqual(out["exit_pct"], -0.9, places=4)
        self.assertAlmostEqual(out["net_pct"], -0.9 - COST, places=4)

    def test_narrow_stop_stops_what_wide_stop_survives(self):
        """ÇEKİRDEK TEST: gölge (SL %0.9) gerçek (%1.5) hayatta kalırken stop olur."""
        window = [
            bar(1, 100, 100.5, 99.0, 99.2),   # gölge SL 99.1 vurulur, gerçek SL 98.5 HAYIR
            bar(2, 99.2, 102.5, 99.1, 102.3),  # gerçek TP 102.4 → TARGET_HIT
        ]
        shadow = self._run(window)
        real_hit, real_bar = _first_stop_or_target_bar(window, 100.0, 2.4, 1.5)
        self.assertEqual(real_hit, "take_profit", "gerçek geometri TP'ye ulaşmalı")
        self.assertEqual(shadow["status_reason"], "STOPPED_OUT",
                         "dar SL daha önce stop olmalı — gölge FARKLI sonuç üretmeli")
        self.assertEqual(shadow["hit_sec"], 59, "ilk mumun kapanışına kadar ~59 sn")

    def test_expired_uses_last_close(self):
        out = self._run([bar(1, 100, 100.2, 99.8, 100.1),
                         bar(2, 100.1, 100.3, 99.9, 100.6)], now_ms=DUE + 1)
        self.assertEqual(out["status_reason"], "MAX_HORIZON_EXPIRED")
        self.assertAlmostEqual(out["exit_pct"], 0.6, places=3)
        self.assertAlmostEqual(out["net_pct"], 0.6 - COST, places=3)

    def test_pending_when_open(self):
        out = self._run([bar(1, 100, 100.2, 99.8, 100.1)], now_ms=1, due_ms=10_000_000)
        self.assertEqual(out["status_reason"], "PENDING")
        self.assertIsNone(out["net_pct"])

    def test_ambiguous_flag(self):
        # Aynı barda hem TP (102.0) hem SL (99.1) aşılıyor → muhafazakâr SL + bayrak
        out = self._run([bar(1, 100, 103.0, 98.0, 100.0)])
        self.assertEqual(out["status_reason"], "STOPPED_OUT")
        self.assertTrue(out["intrabar_ambiguous"])

    def test_invalid_entry_skipped(self):
        out = gs.evaluate(window=[bar(1, 100, 101, 99, 100)], entry=0, atr_pct=0.5,
                          cost_pct=COST, first_hit_fn=_first_stop_or_target_bar,
                          now_ms=NOW, due_ms=DUE)
        self.assertIn("skipped", out)
        self.assertIsNone(out["status_reason"])

    def test_summary_fields_present(self):
        out = self._run([bar(1, 100, 102.5, 99.5, 102.0)])
        for key in ("variant", "enabled", "sl_pct", "atr_mult", "target_pct",
                    "bars", "status_reason", "net_pct"):
            self.assertIn(key, out)


class TestWiring(_Cfg):
    """Kablolama kilidi: gölge HEM ölçüm döngüsünde HEM yeniden ölçümde yazılmalı.

    (Kaynak düzeyinde kontrol — bu iki yazım noktası elle düzenlenen bölgeler;
    gölge bloğu sessizce silinirse veri toplanmaz ve kimse fark etmez.)
    """

    def test_shadow_attached_in_both_evaluation_paths(self):
        src = pathlib.Path(ROOT, "app", "routers", "velocity.py").read_text(encoding="utf-8")
        # NOT: `shadow_details["shadow_geometry"]` içinde `details["shadow_geometry"]`
        # alt-dizge olarak da geçer → o sayım yanıltıcı. Çağrı sayısını say.
        self.assertEqual(
            src.count("geometry_shadow.evaluate("), 2,
            "iki değerlendirme yolu da (ölçüm döngüsü + yeniden ölçüm) gölgeyi hesaplamalı")
        self.assertIn("first_hit_fn=_first_stop_or_target_bar", src,
                      "gölge, gerçek TP/SL yürüyüşünü kullanmalı (belirsizlik sözleşmesi aynı)")


class TestDisabled(_Cfg):
    def test_disabled_returns_skipped(self):
        config.GEOMETRY_SHADOW_ENABLED = False
        out = gs.evaluate(window=[bar(1, 100, 102, 99, 101)], entry=100.0, atr_pct=0.5,
                          cost_pct=COST, first_hit_fn=_first_stop_or_target_bar,
                          now_ms=NOW, due_ms=DUE)
        self.assertEqual(out["skipped"], "disabled")
        self.assertNotIn("status_reason", out)


if __name__ == "__main__":
    unittest.main()
