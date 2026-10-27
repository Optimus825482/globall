"""fx_aile stratejileri: sentetik sinyal + look-ahead + eklenti alanlari testleri.

Calistirma (repo kokunden):  python -m unittest scripts.strategies.test_fx_aile
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

_spec = importlib.util.spec_from_file_location("fx_aile_under_test", os.path.join(os.path.dirname(__file__), "fx_aile.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)
STRATS = mod.STRATEGIES

T0 = int(datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc).timestamp())
TF = 900
NAMES = {"fx_londra_aralik", "fx_ema200_rsi_geri", "fx_bb_donus_m30", "fx_donchian_gunluk"}
PAIRS = {"EURUSD", "GBPUSD", "USDJPY", "USDCAD", "USDCHF", "GBPJPY", "EURJPY", "NZDUSD"}


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


def random_walk(n, seed, t0=T0):
    rnd = random.Random(seed)
    bars, c = [], 100.0
    drift_dir = 1
    for i in range(n):
        if i % 120 == 0:
            drift_dir = rnd.choice([-1, 1])
        o = c
        c = max(1.0, o + drift_dir * 0.15 + rnd.gauss(0, 0.6))
        bars.append(mk(i, o, c, pad=rnd.uniform(0.05, 0.5), t0=t0))
    return bars


class ShapeTest(unittest.TestCase):
    def test_registry_and_spread_gate_fields(self):
        self.assertEqual(set(STRATS), NAMES)
        for name, st in STRATS.items():
            self.assertEqual(st["symbols"], PAIRS, name)
            self.assertEqual(st["spread_min_mult"], 8.0, name)
            self.assertTrue(callable(st["series"]) and callable(st["side"]))
        self.assertEqual((STRATS["fx_londra_aralik"]["sl_atr"], STRATS["fx_londra_aralik"]["tp_r"]), (1.0, 2.0))
        self.assertEqual((STRATS["fx_ema200_rsi_geri"]["sl_atr"], STRATS["fx_ema200_rsi_geri"]["tp_r"]), (2.5, 1.5))
        self.assertEqual((STRATS["fx_bb_donus_m30"]["sl_atr"], STRATS["fx_bb_donus_m30"]["tp_r"]), (2.0, 1.0))
        self.assertEqual((STRATS["fx_donchian_gunluk"]["sl_atr"], STRATS["fx_donchian_gunluk"]["tp_r"]), (2.0, 0.0))


class LondraTest(unittest.TestCase):
    def _day(self, closes_by_slot, pad_by_slot=None, base_pad=0.5, day_offset=96):
        """Ilk gun (96 bar) duz 100; ikinci gunde slot->kapanis esle (varsayilan 100)."""
        bars = [mk(i, 100.0, 100.0, pad=base_pad) for i in range(day_offset)]
        prev = 100.0
        for k in range(96):
            c = closes_by_slot.get(k, 100.0)
            pad = (pad_by_slot or {}).get(k, base_pad)
            bars.append(mk(day_offset + k, prev, c, pad=pad))
            prev = c
        return bars

    @staticmethod
    def slot(h, m):
        return h * 4 + m // 15

    def test_signals_once_per_direction_with_range_sl(self):
        slot = self.slot
        # aralik 07:00-08:00 high 100.5 / low 99.5 (yukseklik 1.0 ~ ATR 1.0 -> >= 0.8*ATR)
        bars = self._day({slot(8, 15): 102.0, slot(8, 30): 103.0, slot(9, 0): 97.0, slot(9, 15): 96.0})
        base = 96
        s = series_of("fx_londra_aralik", bars)
        sg = STRATS["fx_londra_aralik"]["side"]
        self.assertEqual(sg(s, bars, base + slot(8, 0)), 0)  # 08:00 bari araligin icinde kapanir
        self.assertEqual(sg(s, bars, base + slot(8, 15)), 1)
        self.assertEqual(sg(s, bars, base + slot(8, 30)), 0)  # ayni yon ikinci kez yok
        self.assertEqual(sg(s, bars, base + slot(9, 0)), -1)  # ters yon bagimsiz
        self.assertEqual(sg(s, bars, base + slot(9, 15)), 0)
        i = base + slot(8, 15)
        half = (100.5 - 99.5) / 2
        self.assertGreaterEqual(s["atr"][i], half)
        self.assertAlmostEqual(s["atr"][i], max(half, wk.atr(bars, 14)[i]))

    def test_wide_range_sets_sl_from_range(self):
        slot = self.slot
        bars = self._day({})
        j = 96 + slot(7, 30)
        bars[j] = eng.Bar(bars[j].t, 100.0, 110.0, 90.0, 100.0)
        k = 96 + slot(8, 30)
        bars[k] = eng.Bar(bars[k].t, 100.0, 112.0, 100.0, 111.0)
        s = series_of("fx_londra_aralik", bars)
        self.assertEqual(STRATS["fx_londra_aralik"]["side"](s, bars, k), 1)
        self.assertAlmostEqual(s["atr"][k], 10.0)  # (110-90)/2

    def test_narrow_range_below_08_atr_blocks(self):
        slot = self.slot
        # gun oncesi ve 07:00 oncesi bar araliklari genis (pad 3 -> TR 6): ATR ~6; aralik 0.1 << 0.8*ATR
        pads = {k: 3.0 for k in range(0, slot(7, 0))}
        pads.update({slot(7, 0): 0.05, slot(7, 15): 0.05, slot(7, 30): 0.05, slot(7, 45): 0.05})
        bars = self._day({slot(8, 15): 102.0}, pad_by_slot=pads, base_pad=3.0)
        # 07:00-08:00 barlari duz 100, pad 0.05 -> aralik 0.1
        s = series_of("fx_londra_aralik", bars)
        i = 96 + slot(8, 15)
        self.assertEqual(STRATS["fx_londra_aralik"]["side"](s, bars, i), 0)
        # ayni gun, ayni kirilim ama aralik ATR'ye gore yeterli: sinyal
        bars2 = self._day({slot(8, 15): 102.0}, base_pad=0.5)
        self.assertEqual(side_at("fx_londra_aralik", bars2, i), 1)

    def test_no_signal_outside_window(self):
        slot = self.slot
        bars = self._day({slot(12, 0): 105.0, slot(5, 0): 105.0})
        s = series_of("fx_londra_aralik", bars)
        for i in (96 + slot(12, 0), 96 + slot(5, 0)):  # 12:00 bari 12:15'te kapanir (pencere disi); 05:00 aralik oncesi
            self.assertEqual(STRATS["fx_londra_aralik"]["side"](s, bars, i), 0)
        # 11:45 bari 12:00'de kapanir: pencere icinde
        bars = self._day({slot(11, 45): 105.0})
        self.assertEqual(side_at("fx_londra_aralik", bars, 96 + slot(11, 45)), 1)


def trend_end_at(sign, dips, rec, end_hour=12, n_pre=320, seed=1):
    """Yukselen (sign=+1) ya da dusen trend, `dips` bar geri cekilme, `rec` bar sert donus; son bar end_hour:00 UTC acilisli."""
    n = n_pre + dips + rec
    end = int(datetime(2026, 7, 10, end_hour, 0, tzinfo=timezone.utc).timestamp())
    t0 = end - (n - 1) * TF
    rnd = random.Random(seed)
    bars, c = [], 100.0 if sign > 0 else 500.0
    for _ in range(n_pre):
        o = c
        c = o + sign * 0.3 + rnd.uniform(-0.05, 0.05)
        bars.append(mk(len(bars), o, c, t0=t0))
    for _ in range(dips):
        o = c
        c = o - sign * 0.3
        bars.append(mk(len(bars), o, c, t0=t0))
    for _ in range(rec):
        o = c
        c = o + sign * 0.8
        bars.append(mk(len(bars), o, c, t0=t0))
    return bars


class RsiGeriTest(unittest.TestCase):
    def test_buy_and_sell(self):
        b = trend_end_at(1, 10, 1)
        s = series_of("fx_ema200_rsi_geri", b)
        i = len(b) - 1
        self.assertLess(s["rsi"][i - 1], 50)
        self.assertGreaterEqual(s["rsi"][i], 50)
        self.assertEqual(STRATS["fx_ema200_rsi_geri"]["side"](s, b, i), 1)
        b = trend_end_at(-1, 10, 1)
        self.assertEqual(side_at("fx_ema200_rsi_geri", b, len(b) - 1), -1)

    def test_no_signal_without_cross_or_outside_session_or_low_adx(self):
        b = trend_end_at(1, 10, 2)  # 50 kesisi bir onceki barda oldu: bu barda kesis yok
        self.assertEqual(side_at("fx_ema200_rsi_geri", b, len(b) - 1), 0)
        b = trend_end_at(1, 10, 1, end_hour=3)  # seans disi
        self.assertEqual(side_at("fx_ema200_rsi_geri", b, len(b) - 1), 0)
        b = trend_end_at(1, 10, 1, end_hour=20)  # 20:00 acilisli bar seans disi ([7, 20))
        self.assertEqual(side_at("fx_ema200_rsi_geri", b, len(b) - 1), 0)
        b = trend_end_at(1, 10, 1)
        s = series_of("fx_ema200_rsi_geri", b)
        s["adx"] = [10.0] * len(b)
        self.assertEqual(STRATS["fx_ema200_rsi_geri"]["side"](s, b, len(b) - 1), 0)

    def test_requires_ema200_side(self):
        b = trend_end_at(1, 10, 1)
        s = series_of("fx_ema200_rsi_geri", b)
        s["ema200"] = [1e9] * len(b)  # fiyat EMA200 altinda -> BUY yok
        self.assertEqual(STRATS["fx_ema200_rsi_geri"]["side"](s, b, len(b) - 1), 0)


def flat_then(closes_tail, n_flat=60, end_hour=12):
    """Dar salinimli rastgele yatay seri (ADX dusuk; mukemmel duz seri ADX=100 uretir), ardindan verilen kapanislar; son bar end_hour:00 UTC acilisli."""
    n = n_flat + len(closes_tail)
    end = int(datetime(2026, 7, 10, end_hour, 0, tzinfo=timezone.utc).timestamp())
    t0 = end - (n - 1) * TF
    rnd = random.Random(5)
    bars, c = [], 100.0
    for i in range(n_flat):
        o = c
        c = 100.0 + rnd.uniform(-0.1, 0.1)
        bars.append(mk(i, o, c, pad=rnd.uniform(0.05, 0.15), t0=t0))
    for x in closes_tail:
        o = c
        c = x
        bars.append(mk(len(bars), o, c, t0=t0))
    return bars


class BbDonusTest(unittest.TestCase):
    @staticmethod
    def _low_adx(b):
        # Sert tek-bar sapma ADX'i yapay yukseltir; ADX kapisini ayri test etmek icin sabit dusuk deger verilir.
        s = series_of("fx_bb_donus_m30", b)
        s["adx"] = [10.0] * len(b)
        return s

    def test_reversal_both_ways(self):
        sd = STRATS["fx_bb_donus_m30"]["side"]
        b = flat_then([103.0, 100.0])  # ust bant disi, sonra bant ici -> SELL
        s = self._low_adx(b)
        i = len(b) - 1
        self.assertGreater(b[i - 1].close, s["bb_up"][i - 1])
        self.assertTrue(s["bb_lo"][i] <= b[i].close <= s["bb_up"][i])
        self.assertEqual(sd(s, b, i), -1)
        b = flat_then([97.0, 100.0])  # alt bant disi, sonra bant ici -> BUY
        self.assertEqual(sd(self._low_adx(b), b, len(b) - 1), 1)

    def test_natural_low_adx_signal(self):
        # ADX'i gercek hesapla gecen bir durum: kucuk tasma (sert sapma yok), ADX < 20
        b = flat_then([99.75, 100.0])
        s = series_of("fx_bb_donus_m30", b)
        i = len(b) - 1
        self.assertLess(s["adx"][i], 20)
        self.assertEqual(STRATS["fx_bb_donus_m30"]["side"](s, b, i), 1)

    def test_no_signal_when_next_bar_stays_outside_or_adx_high_or_session(self):
        sd = STRATS["fx_bb_donus_m30"]["side"]
        b = flat_then([103.0, 104.0])  # ikinci bar da bant disinda: donus yok
        self.assertEqual(sd(self._low_adx(b), b, len(b) - 1), 0)
        b = flat_then([103.0, 100.0])
        s = self._low_adx(b)
        s["adx"] = [30.0] * len(b)
        self.assertEqual(sd(s, b, len(b) - 1), 0)
        b = flat_then([103.0, 100.0], end_hour=22)  # seans disi
        self.assertEqual(sd(self._low_adx(b), b, len(b) - 1), 0)
        b = flat_then([103.0, 100.0], end_hour=20)  # 20:00 acilisli bar seans disi ([7, 20))
        self.assertEqual(sd(self._low_adx(b), b, len(b) - 1), 0)


def long_trend(sign, n_bars, end_hour=12):
    """Surekli 15dk barlar (hafta sonu dahil); stabil trend."""
    rnd = random.Random(3)
    bars, c = [], 1000.0 if sign > 0 else 5000.0
    for i in range(n_bars):
        o = c
        c = o + sign * 0.5 + rnd.uniform(-0.05, 0.05)
        bars.append(mk(i, o, c))
    return bars


class DonchianTest(unittest.TestCase):
    def test_breakout_both_ways_and_flat(self):
        n = 96 * 70
        self.assertEqual(side_at("fx_donchian_gunluk", long_trend(1, n), n - 1), 1)
        self.assertEqual(side_at("fx_donchian_gunluk", long_trend(-1, n), n - 1), -1)
        flat = [mk(i, 100.0, 100.0 + (0.05 if i % 2 else -0.05)) for i in range(n)]
        self.assertEqual(side_at("fx_donchian_gunluk", flat, n - 1), 0)

    def test_requires_adx_and_daily_side(self):
        n = 96 * 70
        bars = long_trend(1, n)
        s = series_of("fx_donchian_gunluk", bars)
        sd = STRATS["fx_donchian_gunluk"]["side"]
        self.assertEqual(sd(s, bars, n - 1), 1)
        s2 = dict(s, adx=[10.0] * n)
        self.assertEqual(sd(s2, bars, n - 1), 0)
        s3 = dict(s, dema=[1e9] * n)  # kapanis gunluk EMA altinda -> BUY yok
        self.assertEqual(sd(s3, bars, n - 1), 0)

    def test_daily_ema_uses_only_closed_days(self):
        n = 96 * 70
        bars = long_trend(1, n)
        s = series_of("fx_donchian_gunluk", bars)
        day_of = lambda i: bars[i].t // 86400
        # ayni gun icindeki tum barlar ayni degeri okur
        last_day = day_of(n - 1)
        vals = {s["dema"][i] for i in range(n) if day_of(i) == last_day}
        self.assertEqual(len(vals), 1)
        # dema = onceki kapanmis gunlerin EMA(50)'si: elle hesapla
        days = wk.resample(bars, 86400)
        manual = wk.ema([d.close for d in days], 50)
        k = [j for j, d in enumerate(days) if d.t == last_day * 86400][0]
        self.assertAlmostEqual(vals.pop(), manual[k - 1])
        # bugunun (kismi) barlarini bozmak dema'yi degistirmez
        bars2 = list(bars)
        for i in range(n):
            if day_of(i) == last_day:
                x = bars[i]
                bars2[i] = eng.Bar(x.t, x.open, x.high + 500, x.low - 500, x.close + 300)
        s2 = series_of("fx_donchian_gunluk", bars2)
        i = n - 1
        self.assertEqual(s["dema"][i], s2["dema"][i])
        # ilk 50 kapanmis gunden once EMA yok
        self.assertIsNone(s["dema"][96 * 40])


class LookAheadTest(unittest.TestCase):
    """Kisa seri ile uzun seri (ek gelecek barlar) icin her i'de ayni karar + ayni etkin atr."""

    def _check(self, name, n_short, n_ext, seeds=(7, 11)):
        total_signals = 0
        for seed in seeds:
            long_b = random_walk(n_short + n_ext, seed)
            short_b = long_b[:n_short]
            alt_future = random_walk(n_ext, seed + 100)
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

    def test_londra(self):
        self.assertGreater(self._check("fx_londra_aralik", 1700, 700), 0)

    def test_rsi_geri(self):
        self.assertGreater(self._check("fx_ema200_rsi_geri", 1700, 700), 0)

    def test_bb_donus(self):
        self.assertGreater(self._check("fx_bb_donus_m30", 1700, 700), 0)

    def test_donchian(self):
        # gunluk EMA(50) icin >50 kapanmis gun gerekir: 5800 bar ~ 60 gun, uzatma 1400 bar
        self.assertGreater(self._check("fx_donchian_gunluk", 5800, 1400, seeds=(7,)), 0)

    def _mid_day_cuts(self, name, long_b, days, slots=(30, 33, 40), alt_seed=None):
        """Kesim gun ICINDE (varsayilan 07:30, 08:15, 10:00 UTC; Londra penceresi 07-12): kisa seri (kismi son gun)
        ile uzun seri, kesimden onceki TUM barlarda ayni karar ve ayni etkin atr vermeli."""
        sd = STRATS[name]["side"]
        s_long = series_of(name, long_b)
        compared = signals = 0
        for day in days:
            for slot in slots:
                cut = day * 96 + slot
                short_b = long_b[:cut]
                s_short = series_of(name, short_b)
                futures = [(long_b, s_long)]
                if alt_seed is not None:
                    alt = random_walk(len(long_b) - cut, alt_seed + cut)
                    alt = [eng.Bar(short_b[-1].t + (k + 1) * TF, x.open, x.high, x.low, x.close) for k, x in enumerate(alt)]
                    alt_b = short_b + alt
                    futures.append((alt_b, series_of(name, alt_b)))
                for longer, s_l in futures:
                    for i in range(cut):
                        a, c = sd(s_short, short_b, i), sd(s_l, longer, i)
                        self.assertEqual(a, c, f"{name} day {day} slot {slot} i={i}")
                        self.assertEqual(s_short["atr"][i], s_l["atr"][i], f"{name} atr day {day} slot {slot} i={i}")
                        signals += abs(a)
                        compared += 1
        self.assertGreater(compared, 0)
        return signals

    def test_londra_mid_day_cut(self):
        # Belirgin kesimler: 07:30 (aralik olusurken), 08:15 (ilk aday bar sonrasi), 10:00 (pencere ortasi)
        long_b = random_walk(96 * 26, 21)
        self.assertGreater(self._mid_day_cuts("fx_londra_aralik", long_b, range(2, 25), alt_seed=900), 0)
        # Yogun tarama: 07:00-12:45 arasi her 15 dk'lik kesim (ilk aday bar ve ardindaki tum durumlar)
        self._mid_day_cuts("fx_londra_aralik", random_walk(96 * 26, 25), range(2, 25), slots=range(28, 52))

    def test_londra_cut_exact_state_cases(self):
        """Kesim araligin ortasinda iken ayni gunun sonraki barlari, kisa seride aralik kararini degistirmemeli."""
        long_b = random_walk(96 * 8, 33)
        # 07:30 kesiminde (aralik bitmemis) kisa seri hicbir 07:30 oncesi bar icin sinyal uretmemeli
        sd = STRATS["fx_londra_aralik"]["side"]
        for day in range(1, 7):
            cut = day * 96 + 30
            s_short = series_of("fx_londra_aralik", long_b[:cut])
            for i in range(day * 96, cut):
                self.assertEqual(sd(s_short, long_b[:cut], i), 0)

    def test_rsi_geri_mid_day_cut(self):
        long_b = random_walk(96 * 26, 22)
        self.assertGreater(self._mid_day_cuts("fx_ema200_rsi_geri", long_b, range(5, 25, 2), alt_seed=800), 0)

    def test_bb_donus_mid_day_cut(self):
        long_b = random_walk(96 * 26, 23)
        self._mid_day_cuts("fx_bb_donus_m30", long_b, range(3, 25, 2), alt_seed=700)

    def test_donchian_mid_day_cut(self):
        long_b = random_walk(96 * 66, 24)
        self._mid_day_cuts("fx_donchian_gunluk", long_b, (58, 60, 62), alt_seed=600)

    def test_donchian_partial_last_day_cut(self):
        """Kesim gun ortasinda olsa da (kismi son gun) onceki barlarin karari degismez."""
        long_b = random_walk(6000, 5)
        cut = 5800 + 37  # gun ortasi
        short_b = long_b[:cut]
        s_s, s_l = series_of("fx_donchian_gunluk", short_b), series_of("fx_donchian_gunluk", long_b)
        sd = STRATS["fx_donchian_gunluk"]["side"]
        for i in range(cut):
            self.assertEqual(sd(s_s, short_b, i), sd(s_l, long_b, i), i)
            self.assertEqual(s_s["dema"][i], s_l["dema"][i], i)


if __name__ == "__main__":
    unittest.main()
