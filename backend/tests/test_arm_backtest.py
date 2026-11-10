"""KOL BACKTESTER çekirdeği kilitleri (2026-11-10).

`scripts/fx_arm_backtest.py` dosya tabanlı kolları ölçer. Çekirdeğin doğruluğu üç
known-answer testiyle kilitlenir:

  1. **Look-ahead YOK:** sinyal bar `i`'de üretilirse giriş **bar i+1'in açılışından**.
  2. **SL önce (muhafazakâr):** aynı barda SL ve TP ikisi de değerse çıkış SL olur.
  3. **Kaydırma kontrolü:** sinyal `shift` bar kaydırılınca işlem kümesi değişir
     (kontrol grubunun gerçekten farklı bir şey ölçtüğünün kanıtı).
"""
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fx_arm_backtest.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("fx_arm_backtest", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # MetaTrader5 importu gerekmez (yalnız CLI'da kullanılır)
    return mod


class TestBuildTrades(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load_module()

    @staticmethod
    def _bars(prices):
        """Sabit ATR'li, tek fiyatlık basit bar serisi (ts, o, h, l, c)."""
        out = []
        for i, (o, h, l, c) in enumerate(prices):
            out.append((1_700_000_000 + i * 3600, o, h, l, c))
        return out

    def test_entry_is_next_bar_open_no_lookahead(self):
        # 25 bar düz (ATR oluşsun), 25. barda sinyal, 26. barda açılış 2.0
        prices = [(1.0, 1.1, 0.9, 1.0)] * 25 + [(2.0, 2.2, 1.9, 2.1)] + [(2.0, 2.1, 1.9, 2.0)] * 2
        bars = self._bars(prices)
        sig = [0] * 25 + [1] + [0] * 2
        trades = self.m.build_trades(bars, sig, atr_mult=1.5, hold_bars=1,
                                     cost_price=0.0, pip=0.0001)
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertEqual(t["entry_idx"], 26, "giriş, sinyalden SONRAKİ bardan olmalı")
        # SL = 1.5 × ATR(14) ≈ 1.5 × 0.2 = 0.30 → 2.0 − 0.30 = 1.70; 26. bar dibi 1.9 → SL yemedi
        self.assertEqual(t["reason"], "TIME")

    def test_sl_first_when_both_touched(self):
        # sinyal barı (25) SAKİN → ATR küçük; GİRİŞ barı (26) geniş → SL ve TP ikisi de değer
        prices = [(1.0, 1.1, 0.9, 1.0)] * 26 + [(1.0, 5.0, 0.1, 1.0)] + [(1.0, 1.0, 1.0, 1.0)] * 2
        bars = self._bars(prices)
        sig = [0] * 25 + [1] + [0] * 3
        trades = self.m.build_trades(bars, sig, atr_mult=1.5, hold_bars=2, tp_r=0.2,
                                     cost_price=0.0, pip=0.0001)
        self.assertTrue(trades)
        self.assertEqual(trades[0]["reason"], "SL", "aynı barda SL ve TP değerse SL kazanır")

    def test_shift_changes_trade_set(self):
        prices = [(1.0 + 0.001 * i, 1.001 + 0.001 * i, 0.999 + 0.001 * i, 1.0 + 0.001 * i) for i in range(42)]
        bars = self._bars(prices)
        sig = [0] * len(bars)
        for i in (25, 30, 35):
            sig[i] = 1
        base = self.m.build_trades(bars, sig, hold_bars=1, cost_price=0.0, pip=0.0001)
        shifted = self.m.build_trades(bars, sig, hold_bars=1, cost_price=0.0, pip=0.0001, shift=2)
        self.assertNotEqual([t["entry_idx"] for t in base], [t["entry_idx"] for t in shifted])

    def test_cost_is_subtracted(self):
        prices = [(1.0, 1.1, 0.9, 1.0)] * 25 + [(1.0, 1.3, 1.0, 1.2)] + [(1.2, 1.3, 1.1, 1.2)] * 2
        bars = self._bars(prices)
        sig = [0] * 25 + [1] + [0] * 2
        free = self.m.build_trades(bars, sig, hold_bars=1, cost_price=0.0, pip=0.0001)
        paid = self.m.build_trades(bars, sig, hold_bars=1, cost_price=0.0002, pip=0.0001)
        self.assertGreater(free[0]["net_pips"], paid[0]["net_pips"], "maliyet düşülmeli")

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            self.m.build_trades([(0, 1, 1, 1, 1)], [0, 1], pip=0.0001)


if __name__ == "__main__":
    unittest.main()
