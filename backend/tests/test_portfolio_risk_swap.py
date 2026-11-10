"""TAŞIMA (SWAP) MALİYETİ + VETO kilitleri (2026-11-10).

ÖLÇÜM (canlı hesap, gerçek deal geçmişiyle doğrulandı):
  GBPJPY uzun **+1.14 pip/gün kredi**, kısa **−2.29 pip/gün maliyet** (20p stop'un %11'i;
  çarşamba ×3 → %17) · USDJPY uzun +0.83 · EURUSD kısa +0.14 (gürültü).
  Sunucu saati UTC+2 → **rollover 22:00 UTC**.
`symbol_info().swap_long/short` POINTS modunda **point**; **1 pip = 10 point** (ölçüldü).

Kilitlenen davranış:
  1. `direction_swap_pips` yönü doğru eşler; bilinmeyen modda **None** (uydurma yok).
  2. `expected_swap_pips` = P(rollover) × günlük swap, P = tutuş/24 (şeffaf varsayım).
  3. `cost_r` **swap'ı içerir** (maliyet negatifse kredi sayılır).
  4. Yön aleyhine beklenen taşıma eşiği aşarsa `swap_veto` sebebi üretilir (0 = kapalı).
  5. Boru hattı: köprü `_swap_catalog` → `/mt5/sync` `swaps` → risk ctx → `cost_r`.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import portfolio_risk as pr  # noqa: E402

SRC_PR = (ROOT / "app" / "portfolio_risk.py").read_text(encoding="utf-8")
SRC_FX = (ROOT / "app" / "routers" / "forex.py").read_text(encoding="utf-8")
SRC_BRIDGE = (pathlib.Path(ROOT).parent / "scripts" / "mt5_bridge.py").read_text(encoding="utf-8")


class TestSwapMath(unittest.TestCase):
    def test_direction_mapping(self):
        ctx = {"direction": "BUY", "swap_long_pips": 1.14, "swap_short_pips": -2.29}
        self.assertAlmostEqual(pr.direction_swap_pips(ctx), 1.14)
        ctx["direction"] = "SELL"
        self.assertAlmostEqual(pr.direction_swap_pips(ctx), -2.29)

    def test_unknown_is_none_not_zero(self):
        self.assertIsNone(pr.direction_swap_pips({"direction": "BUY",
                                                 "swap_long_pips": None, "swap_short_pips": None}))
        self.assertIsNone(pr.direction_swap_pips({"direction": "?"}))
        self.assertEqual(pr.expected_swap_pips(None, 4.0), 0.0, "bilinmeyen swap maliyeti 0 sayılır")

    def test_expected_probability_scales_with_hold(self):
        self.assertAlmostEqual(pr.expected_swap_pips(-2.29, 0.0), 0.0)
        self.assertAlmostEqual(pr.expected_swap_pips(-2.29, 12.0), -1.145, places=3)
        self.assertAlmostEqual(pr.expected_swap_pips(-2.29, 48.0), -2.29, places=3,
                               msg="24 saatten uzun tutuşta tek rollover (çarpan yok)")

    def test_credit_is_negative_cost(self):
        self.assertAlmostEqual(pr.expected_swap_pips(1.14, 24.0), 1.14, places=3)


class TestCostIntegration(unittest.TestCase):
    def _cfg(self, **over):
        cfg = {"mode": "shadow", "cost_r_max": 0.25, "stop_spread_mult": 8.0,
               "swap_cost_enabled": True, "swap_hold_hours": 4.0, "swap_veto_pips": 0.5}
        cfg.update(over)
        return cfg

    def _ctx(self, **over):
        ctx = {"symbol": "GBPJPY", "direction": "SELL", "lots": 0.1, "sl_pips": 20.0,
               "spread_pips": 1.5, "pip_size": 0.01, "pip_val": 1.0, "comm_per_lot": 3.5,
               "entry_price": 190.0, "swap_long_pips": 1.14, "swap_short_pips": -2.29}
        ctx.update(over)
        return ctx

    def test_cost_r_includes_swap_sign(self):
        no_swap = pr.evaluate_entry(self._ctx(swap_long_pips=None, swap_short_pips=None),
                                    self._cfg(), {"equity": 10_000}, [], {}, lambda s: {"pip_size": 0.01, "pip_val": 1.0}, pr.STATE)
        with_swap = pr.evaluate_entry(self._ctx(), self._cfg(), {"equity": 10_000}, [], {},
                                      lambda s: {"pip_size": 0.01, "pip_val": 1.0}, pr.STATE)
        self.assertGreater(with_swap["metrics"]["cost_r"], no_swap["metrics"]["cost_r"],
                           "kısa yönde NEGATİF swap = MALİYET → cost_r artmalı")
        # kredi yönünde maliyet düşmeli
        credit = pr.evaluate_entry(self._ctx(direction="BUY"), self._cfg(), {"equity": 10_000}, [], {},
                                   lambda s: {"pip_size": 0.01, "pip_val": 1.0}, pr.STATE)
        self.assertLess(credit["metrics"]["cost_r"], no_swap["metrics"]["cost_r"],
                        "uzun yönde POZİTİF swap = KREDİ → cost_r azalmalı")
        self.assertLess(with_swap["metrics"]["swap_pips_expected"], 0.0)

    def test_veto_below_threshold_with_short_hold(self):
        """4 saatlik tutuşta beklenen taşıma -0.38 pip → 0.5 eşiğinin ALTINDA (veto yok)."""
        res = pr.evaluate_entry(self._ctx(), self._cfg(), {"equity": 10_000}, [], {},
                                lambda s: {"pip_size": 0.01, "pip_val": 1.0}, pr.STATE)
        self.assertNotIn("swap_veto", [r["code"] for r in res["reasons"]])

    def test_veto_fires_on_overnight_hold(self):
        """Gece tutuşunda (8s) beklenen taşıma -0.76 pip → veto tetiklenir."""
        res = pr.evaluate_entry(self._ctx(), self._cfg(swap_hold_hours=8.0), {"equity": 10_000}, [], {},
                                lambda s: {"pip_size": 0.01, "pip_val": 1.0}, pr.STATE)
        self.assertIn("swap_veto", [r["code"] for r in res["reasons"]])

    def test_credit_direction_no_veto(self):
        res = pr.evaluate_entry(self._ctx(direction="BUY"), self._cfg(), {"equity": 10_000}, [], {},
                                lambda s: {"pip_size": 0.01, "pip_val": 1.0}, pr.STATE)
        codes = [r["code"] for r in res["reasons"]]
        self.assertNotIn("swap_veto", codes, "taşıma KREDİ iken veto olmamalı")

    def test_veto_disabled(self):
        res = pr.evaluate_entry(self._ctx(), self._cfg(swap_veto_pips=0.0), {"equity": 10_000}, [], {},
                                lambda s: {"pip_size": 0.01, "pip_val": 1.0}, pr.STATE)
        self.assertNotIn("swap_veto", [r["code"] for r in res["reasons"]])

    def test_swap_cost_can_be_disabled(self):
        res = pr.evaluate_entry(self._ctx(), self._cfg(swap_cost_enabled=False), {"equity": 10_000}, [], {},
                                lambda s: {"pip_size": 0.01, "pip_val": 1.0}, pr.STATE)
        self.assertIsNone(res["metrics"].get("swap_pips_day"))
        self.assertNotIn("swap_veto", [r["code"] for r in res["reasons"]])


class TestWiring(unittest.TestCase):
    def test_bridge_sends_catalog(self):
        self.assertIn("def _swap_catalog(", SRC_BRIDGE)
        self.assertIn('"swaps": _swap_catalog(', SRC_BRIDGE)
        self.assertIn("SYMBOL_SWAP_MODE_POINTS", SRC_BRIDGE)

    def test_sync_request_has_swaps(self):
        self.assertIn("swaps: Dict[str, Dict[str, Any]]", SRC_FX)

    def test_ctx_passes_swap_fields(self):
        self.assertIn('"swap_long_pips"', SRC_FX)
        self.assertIn('_MT5_STATE.get("swaps")', SRC_FX)

    def test_cost_formula_mentions_swap(self):
        self.assertIn("spread + comm_pips - _swap_exp", SRC_PR)


if __name__ == "__main__":
    unittest.main()
