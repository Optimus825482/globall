"""btc_aile stratejileri: sentetik sinyal + look-ahead testleri.

Calistirma (repo kokunden):  python -m unittest scripts.strategies.test_btc_aile
"""
import importlib.util
import os
import random
import sys
import unittest
from datetime import datetime, timezone

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

_spec = importlib.util.spec_from_file_location("btc_aile_under_test", os.path.join(os.path.dirname(__file__), "btc_aile.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)
STRATS = mod.STRATEGIES

T0 = int(datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc).timestamp())
TF = 900


def mk(i, o, c, pad=0.1, t0=T0, tf=TF):
    return eng.Bar(t0 + i * tf, o, max(o, c) + pad, min(o, c) - pad, c)


def series_of(name, bars):
    st = STRATS[name]
    closes = [x.close for x in bars]
    s = st["series"](bars, closes)
    if "atr" not in s:
        s["atr"] = wk.atr(bars, 14)
    return s


def side_at(name, bars, i):
    return STRATS[name]["side"](series_of(name, bars), bars, i)


def trend(n, start=100.0, step=0.5, noise=0.05, seed=1):
    rnd = random.Random(seed)
    bars, c = [], start
    for i in range(n):
        o = c
        c = o + step + rnd.uniform(-noise, noise)
        bars.append(mk(i, o, c))
    return bars


def random_walk(n, seed):
    rnd = random.Random(seed)
    bars, c = [], 100.0
    drift_dir = 1
    for i in range(n):
        if i % 120 == 0:
            drift_dir = rnd.choice([-1, 1])
        o = c
        c = max(1.0, o + drift_dir * 0.15 + rnd.gauss(0, 0.6))
        bars.append(mk(i, o, c, pad=rnd.uniform(0.05, 0.5)))
    return bars


class ShapeTest(unittest.TestCase):
    def test_registry(self):
        self.assertEqual(set(STRATS), {"btc_seans_kirilim", "btc_rsi2_bb_donus", "btc_donchian55_trend",
                                       "btc_keltner_geri_htf", "btc_nr7_kirilim"})
        for st in STRATS.values():
            self.assertEqual(st["symbols"], {"BTCUSD"})
            self.assertTrue(callable(st["series"]) and callable(st["side"]))
        self.assertEqual((STRATS["btc_donchian55_trend"]["tp_r"], STRATS["btc_donchian55_trend"]["sl_atr"]), (0.0, 2.0))
        self.assertEqual((STRATS["btc_rsi2_bb_donus"]["sl_atr"], STRATS["btc_rsi2_bb_donus"]["tp_r"]), (3.0, 1.0))
        self.assertEqual((STRATS["btc_keltner_geri_htf"]["sl_atr"], STRATS["btc_keltner_geri_htf"]["tp_r"]), (2.0, 2.0))
        self.assertEqual((STRATS["btc_nr7_kirilim"]["sl_atr"], STRATS["btc_nr7_kirilim"]["tp_r"]), (1.5, 2.0))
        self.assertEqual((STRATS["btc_seans_kirilim"]["sl_atr"], STRATS["btc_seans_kirilim"]["tp_r"]), (1.0, 2.0))


class SeansTest(unittest.TestCase):
    def _day(self, closes_by_slot, day_offset=96):
        """Ilk gun (96 bar) duz 100; ikinci gunde slot->kapanis esle (varsayilan 100)."""
        bars = [mk(i, 100.0, 100.0, pad=0.5) for i in range(day_offset)]
        prev = 100.0
        for k in range(96):
            c = closes_by_slot.get(k, 100.0)
            hi_pad = 0.5
            bars.append(mk(day_offset + k, prev, c, pad=hi_pad))
            prev = c
        return bars

    def test_signals_once_per_direction_with_range_sl(self):
        slot = lambda h, m: h * 4 + m // 15
        # aralik 13:30-14:30 bar high 100.5 / low 99.5 (duz kapanis 100, pad .5); kirilim 14:45 acilisli barda
        bars = self._day({slot(14, 45): 102.0, slot(15, 0): 103.0, slot(16, 0): 97.0, slot(16, 15): 96.0})
        base = 96
        s = series_of("btc_seans_kirilim", bars)
        sg = STRATS["btc_seans_kirilim"]["side"]
        self.assertEqual(sg(s, bars, base + slot(14, 30)), 0)  # 14:30 bari araligin icinde kapanir
        self.assertEqual(sg(s, bars, base + slot(14, 45)), 1)
        self.assertEqual(sg(s, bars, base + slot(15, 0)), 0)  # ayni yon ikinci kez yok
        self.assertEqual(sg(s, bars, base + slot(16, 0)), -1)  # ters yon bagimsiz
        self.assertEqual(sg(s, bars, base + slot(16, 15)), 0)
        # SL: etkin atr = max(aralik/2, ATR14); aralik 1.0 -> yari 0.5, ATR daha buyuk veya esit
        i = base + slot(14, 45)
        half = (100.5 - 99.5) / 2
        self.assertGreaterEqual(s["atr"][i], half)
        self.assertAlmostEqual(s["atr"][i], max(half, wk.atr(bars, 14)[i]))

    def test_wide_range_sets_sl_from_range(self):
        slot = lambda h, m: h * 4 + m // 15
        bars = self._day({slot(13, 30): 100.0})
        # aralik barlarindan birini genislet: high 110, low 90
        j = 96 + slot(14, 0)
        bars[j] = eng.Bar(bars[j].t, 100.0, 110.0, 90.0, 100.0)
        bars[96 + slot(15, 0)] = eng.Bar(bars[96 + slot(15, 0)].t, 100.0, 112.0, 100.0, 111.0)
        s = series_of("btc_seans_kirilim", bars)
        i = 96 + slot(15, 0)
        self.assertEqual(STRATS["btc_seans_kirilim"]["side"](s, bars, i), 1)
        self.assertAlmostEqual(s["atr"][i], 10.0)  # (110-90)/2

    def test_no_signal_outside_window(self):
        slot = lambda h, m: h * 4 + m // 15
        bars = self._day({slot(20, 0): 105.0, slot(10, 0): 105.0})
        s = series_of("btc_seans_kirilim", bars)
        for i in (96 + slot(20, 0), 96 + slot(10, 0)):
            self.assertEqual(STRATS["btc_seans_kirilim"]["side"](s, bars, i), 0)


class Rsi2Test(unittest.TestCase):
    def test_buy_and_sell(self):
        up = trend(320, step=0.3)
        o = up[-1].close
        for d in (1.0, 1.0, 6.0):  # sert dusus
            c = o - d
            up.append(mk(len(up), o, c))
            o = c
        self.assertEqual(side_at("btc_rsi2_bb_donus", up, len(up) - 1), 1)
        dn = trend(320, start=300.0, step=-0.3)
        o = dn[-1].close
        for d in (1.0, 1.0, 6.0):
            c = o + d
            dn.append(mk(len(dn), o, c))
            o = c
        self.assertEqual(side_at("btc_rsi2_bb_donus", dn, len(dn) - 1), -1)

    def test_no_signal_against_ema200(self):
        dn = trend(320, start=300.0, step=-0.3)
        o = dn[-1].close
        for k in range(3):  # dusen trendde daha sert dusus: BUY yasak
            c = o - 2.0
            dn.append(mk(len(dn), o, c))
            o = c
        self.assertEqual(side_at("btc_rsi2_bb_donus", dn, len(dn) - 1), 0)


class DonchianTest(unittest.TestCase):
    def test_breakout_both_ways_and_flat(self):
        self.assertEqual(side_at("btc_donchian55_trend", trend(300, step=0.5), 299), 1)
        self.assertEqual(side_at("btc_donchian55_trend", trend(300, start=400.0, step=-0.5), 299), -1)
        flat = [mk(i, 100.0, 100.0 + (0.05 if i % 2 else -0.05)) for i in range(300)]
        self.assertEqual(side_at("btc_donchian55_trend", flat, 299), 0)

    def test_requires_adx(self):
        bars = trend(300, step=0.5)
        s = series_of("btc_donchian55_trend", bars)
        s["adx"] = [10.0] * len(bars)
        self.assertEqual(STRATS["btc_donchian55_trend"]["side"](s, bars, 299), 0)


class KeltnerTest(unittest.TestCase):
    def _pullback(self, sign):
        bars = trend(260, start=100.0 if sign > 0 else 500.0, step=0.5 * sign)
        o = bars[-1].close
        c = o - sign * 6.0  # orta bandin diger tarafina geri cekilme
        bars.append(mk(len(bars), o, c))
        o2 = c
        c2 = o2 + sign * 9.0  # yonunde guclu kapanis, son 3 barin extremumunu asar
        bars.append(mk(len(bars), o2, c2))
        return bars

    def test_long_and_short(self):
        b = self._pullback(1)
        self.assertEqual(side_at("btc_keltner_geri_htf", b, len(b) - 1), 1)
        b = self._pullback(-1)
        self.assertEqual(side_at("btc_keltner_geri_htf", b, len(b) - 1), -1)

    def test_no_signal_without_pullback(self):
        b = trend(262, step=0.5)
        self.assertEqual(side_at("btc_keltner_geri_htf", b, len(b) - 1), 0)


class Nr7Test(unittest.TestCase):
    def _bars(self, sign, nr7=True):
        bars = trend(40, start=100.0 if sign > 0 else 300.0, step=0.5 * sign)
        o = bars[-1].close
        c = o + sign * (0.02 if nr7 else 0.5)
        bars.append(mk(len(bars), o, c, pad=0.02 if nr7 else 0.1))
        o = c
        bars.append(mk(len(bars), o, o + sign * 1.0))
        return bars

    def test_breakout_after_nr7(self):
        b = self._bars(1)
        self.assertEqual(side_at("btc_nr7_kirilim", b, len(b) - 1), 1)
        b = self._bars(-1)
        self.assertEqual(side_at("btc_nr7_kirilim", b, len(b) - 1), -1)

    def test_no_signal_without_nr7_or_adx(self):
        b = self._bars(1, nr7=False)
        self.assertEqual(side_at("btc_nr7_kirilim", b, len(b) - 1), 0)
        b = self._bars(1)
        s = series_of("btc_nr7_kirilim", b)
        s["adx"] = [5.0] * len(b)
        self.assertEqual(STRATS["btc_nr7_kirilim"]["side"](s, b, len(b) - 1), 0)


class LookAheadTest(unittest.TestCase):
    """Kisa seri ile uzun seri (ek gelecek barlar) icin her i'de ayni karar + ayni etkin atr."""

    def _check(self, name, seeds=(7, 11)):
        total_signals = 0
        for seed in seeds:
            long_b = random_walk(2400, seed)
            short_b = long_b[:1700]
            # uzun seriyi gercekten farkli bir gelecekle de dene
            alt_future = random_walk(700, seed + 100)
            for k, x in enumerate(alt_future):
                alt_future[k] = eng.Bar(short_b[-1].t + (k + 1) * TF, x.open, x.high, x.low, x.close)
            for longer in (long_b, short_b + alt_future):
                s_short = series_of(name, short_b)
                s_long = series_of(name, longer)
                sd = STRATS[name]["side"]
                for i in range(len(short_b)):
                    a, c = sd(s_short, short_b, i), sd(s_long, longer, i)
                    self.assertEqual(a, c, f"{name} seed {seed} i={i}")
                    self.assertEqual(s_short["atr"][i], s_long["atr"][i], f"{name} atr i={i}")
                    total_signals += abs(a)
        return total_signals

    def test_seans(self):
        self.assertGreater(self._check("btc_seans_kirilim"), 0)

    def test_rsi2(self):
        self._check("btc_rsi2_bb_donus")

    def test_donchian(self):
        self.assertGreater(self._check("btc_donchian55_trend"), 0)

    def test_keltner(self):
        self.assertGreater(self._check("btc_keltner_geri_htf"), 0)

    def test_nr7(self):
        self.assertGreater(self._check("btc_nr7_kirilim"), 0)


if __name__ == "__main__":
    unittest.main()
