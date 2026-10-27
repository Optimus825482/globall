"""fx_ozgun stratejileri: sentetik sinyal + look-ahead testleri.

Calistirma (repo kokunden):  python -m unittest scripts.strategies.test_fx_ozgun
"""
import importlib.util
import math
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

_spec = importlib.util.spec_from_file_location("fx_ozgun_under_test", os.path.join(os.path.dirname(__file__), "fx_ozgun.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)
STRATS = mod.STRATEGIES

T0 = int(datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc).timestamp())  # Carsamba 00:00 UTC
TF = 900
NAMES = {"fx_seans_devri", "fx_pdh_pdl_supurme", "fx_para_gucu", "fx_doji_kumesi", "fx_adr_tukenis"}
PAIRS = {"EURUSD", "GBPUSD", "USDJPY", "USDCAD", "USDCHF", "GBPJPY", "EURJPY", "NZDUSD"}
ALL21 = ["CADCHF", "CADJPY", "CHFJPY", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD", "GBPCAD",
         "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD", "NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD", "USDCAD", "USDCHF", "USDJPY"]


def slot(h, m=0):
    return h * 4 + m // 15


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


def random_walk(n, seed, t0=T0, step=0.15, sd=0.6):
    rnd = random.Random(seed)
    bars, c = [], 100.0
    drift_dir = 1
    for i in range(n):
        if i % 120 == 0:
            drift_dir = rnd.choice([-1, 1])
        o = c
        c = max(1.0, o + drift_dir * step + rnd.gauss(0, sd))
        bars.append(mk(i, o, c, pad=rnd.uniform(0.05, 0.5), t0=t0))
    return bars


def flat_days(n_days, price=100.0, pad=0.5):
    """n_days tam gun (96 bar) duz fiyat; high = price+pad, low = price-pad (aralik 2*pad, ATR 2*pad)."""
    return [mk(i, price, price, pad=pad) for i in range(n_days * 96)]


def put(bars, idx, o, h, l, c):
    bars[idx] = eng.Bar(bars[idx].t, o, h, l, c)


class ShapeTest(unittest.TestCase):
    def test_registry_and_spread_gate_fields(self):
        self.assertEqual(set(STRATS), NAMES)
        for name, st in STRATS.items():
            self.assertEqual(st["symbols"], PAIRS, name)
            self.assertEqual(st["spread_min_mult"], 8.0, name)
            self.assertTrue(callable(st["series"]) and callable(st["side"]))
        want = {"fx_seans_devri": (1.5, 2.0), "fx_pdh_pdl_supurme": (1.0, 1.5), "fx_para_gucu": (2.0, 1.5),
                "fx_doji_kumesi": (1.0, 2.0), "fx_adr_tukenis": (1.0, 1.0)}
        for k, v in want.items():
            self.assertEqual((STRATS[k]["sl_atr"], STRATS[k]["tp_r"]), v, k)

    def test_docstring_has_originality_sentences(self):
        self.assertEqual(mod.__doc__.count("Neden ozgun"), 5)


# ------------------------------------------------------------------ gun istatistikleri
class DayStatsTest(unittest.TestCase):
    def test_previous_day_is_closed_day_only_and_sunday_stub_ignored(self):
        # Carsamba 01-Tem: gun 0, 1; Cuma = gun 2 (03-Tem). Pazar mini-gunu (21-24 UTC) yuksek 150.
        fri = [mk(i, 100.0, 100.0, pad=0.5, t0=T0 + 2 * 86400) for i in range(96)]  # H100.5 L99.5
        sun_t0 = T0 + 4 * 86400 + 21 * 3600
        sun = [eng.Bar(sun_t0 + k * TF, 100.0, 150.0, 90.0, 100.0) for k in range(12)]
        mon_t0 = T0 + 5 * 86400
        mon = [mk(k, 100.0, 100.0, pad=0.2, t0=mon_t0) for k in range(10)]
        b = fri + sun + mon
        pdh, pdl, _adr, dhi, dlo = mod._day_stats(b, TF)
        self.assertIsNone(pdh[0])  # onceki dolu gun yok
        self.assertEqual(pdh[len(fri) + len(sun) + 3], 100.5)  # Pazar stub'i atlanir -> Cuma
        self.assertEqual(pdl[len(fri) + len(sun) + 3], 99.5)
        self.assertEqual(dhi[len(fri) + len(sun) + 3], 100.2)  # gunun kendi (acik) yuksegi
        # Cuma icinde: kendi gunu onceki gun sayilmaz
        self.assertIsNone(pdh[50])

    def test_adr_is_mean_of_previous_14_closed_days(self):
        days = []
        for d in range(16):
            pad = 0.5 + 0.1 * d
            days += [mk(d * 96 + k, 100.0, 100.0, pad=pad) for k in range(96)]
        _p, _l, adr, _h, _lo = mod._day_stats(days, TF)
        self.assertIsNone(adr[13 * 96 + 5])  # 13 kapanmis gun
        want = sum(2 * (0.5 + 0.1 * d) for d in range(0, 14)) / 14.0  # gun 14 baslarken 0..13
        self.assertAlmostEqual(adr[14 * 96 + 5], want)
        want2 = sum(2 * (0.5 + 0.1 * d) for d in range(1, 15)) / 14.0
        self.assertAlmostEqual(adr[15 * 96 + 5], want2)


# ------------------------------------------------------------------ seans devri
def devri_day(london=0.25, dip=None, pull_extra=None, drop_slot=None):
    """2 duz gun + 3. gun: 07-09 Londra (8 bar, her biri 'london' kadar), 09-13 duz (102 civari)."""
    b = flat_days(3, pad=0.5)
    base = 2 * 96
    c = 100.0
    for k in range(8):
        o = c
        c = o + london
        put(b, base + slot(7) + k, o, max(o, c) + 0.1, min(o, c) - 0.1, c)
    top = c
    for k in range(16):
        idx = base + slot(9) + k
        put(b, idx, top, top + 0.1, top - 0.1, top)
    if dip is not None:  # (bar_idx_in_window, low)
        k, low = dip
        idx = base + slot(9) + k
        put(b, idx, top, top + 0.1, low, top)
    for k in range(slot(13), 96):
        put(b, base + k, top, top + 0.1, top - 0.1, top)
    if drop_slot is not None:
        idx = base + drop_slot
        put(b, idx, 100.0, 100.0, 100.0, 100.0)
    return b, base, top


class SeansDevriTest(unittest.TestCase):
    def test_buy_after_london_up_move_with_shallow_pullback(self):
        b, base, top = devri_day(london=0.25, dip=(3, 101.4))  # hareket 2.0, geri cekilme 0.6 <= 1.0
        s = series_of("fx_seans_devri", b)
        sd = STRATS["fx_seans_devri"]["side"]
        sigs = [i for i in range(len(b)) if sd(s, b, i)]
        self.assertEqual(sigs, [base + slot(12, 45)])  # 13:00'da kapanan bar -> giris 13:00 barinin acilisi
        self.assertEqual(sd(s, b, base + slot(12, 45)), 1)
        self.assertAlmostEqual(top, 102.0)

    def test_sell_mirror(self):
        b, base, top = devri_day(london=-0.25, dip=None)
        # asagi hareket: 09-13 penceresi icinde hafif toparlanma (tepe 98.6: 0.6 <= 1.0)
        idx = base + slot(9) + 5
        put(b, idx, top, top + 0.6, top - 0.1, top)
        self.assertEqual(side_at("fx_seans_devri", b, base + slot(12, 45)), -1)

    def test_deep_pullback_blocks(self):
        b, base, top = devri_day(london=0.25, dip=(3, 100.9))  # geri cekilme 1.1 > 0.5*2.0
        self.assertEqual(side_at("fx_seans_devri", b, base + slot(12, 45)), 0)
        b, base, top = devri_day(london=0.25, dip=(3, 101.05))  # 0.95 <= 1.0 -> serbest
        self.assertEqual(side_at("fx_seans_devri", b, base + slot(12, 45)), 1)

    def test_small_london_move_blocks(self):
        b, base, top = devri_day(london=0.05)  # hareket 0.4 < 1.0*ATR (~0.9)
        self.assertEqual(side_at("fx_seans_devri", b, base + slot(12, 45)), 0)

    def test_incomplete_windows_block_and_no_other_bar_signals(self):
        b, base, top = devri_day(london=0.25)
        b2 = list(b)
        del b2[base + slot(8)]  # Londra penceresinde eksik bar
        self.assertEqual(sum(abs(v) for v in
                             (STRATS["fx_seans_devri"]["side"](series_of("fx_seans_devri", b2), b2, i)
                              for i in range(len(b2)))), 0)
        b3 = list(b)
        del b3[base + slot(10)]  # 09-13 penceresinde eksik bar
        self.assertEqual(sum(abs(STRATS["fx_seans_devri"]["side"](series_of("fx_seans_devri", b3), b3, i))
                             for i in range(len(b3))), 0)

    def test_at_most_one_signal_per_day(self):
        b, base, top = devri_day(london=0.25)
        s = series_of("fx_seans_devri", b)
        self.assertEqual(sum(abs(s["sig"][i]) for i in range(len(b))), 1)


# ------------------------------------------------------------------ PDH/PDL supurme
def sweep_world():
    """Gun 0-1 duz (H100.5 L99.5; ATR 1.0); gun 1'de PDH'yi 101.0'a, PDL'yi 99.0'a cikaran bar; gun 2 hedef."""
    b = flat_days(3, pad=0.5)
    put(b, 96 + slot(2), 100.0, 101.0, 99.0, 100.0)  # gun 1: PDH=101.0 PDL=99.0 (gun 2 icin)
    return b


class PdhPdlTest(unittest.TestCase):
    def test_sell_on_pdh_sweep_with_variable_sl(self):
        b = sweep_world()
        i = 2 * 96 + slot(10)
        put(b, i, 100.0, 101.5, 100.0, 100.8)  # fitil 0.5 >= 0.1*ATR, kapanis PDH(101.0) altinda
        s = series_of("fx_pdh_pdl_supurme", b)
        self.assertEqual(STRATS["fx_pdh_pdl_supurme"]["side"](s, b, i), -1)
        a = wk.atr(b, 14)[i]
        self.assertAlmostEqual(s["atr"][i], (101.5 - 100.8) + 0.3 * a)
        self.assertAlmostEqual(s["atr"][i - 1], wk.atr(b, 14)[i - 1])

    def test_buy_on_pdl_sweep_mirror(self):
        b = sweep_world()
        i = 2 * 96 + slot(14)
        put(b, i, 100.0, 100.0, 98.4, 99.3)
        s = series_of("fx_pdh_pdl_supurme", b)
        self.assertEqual(STRATS["fx_pdh_pdl_supurme"]["side"](s, b, i), 1)
        a = wk.atr(b, 14)[i]
        self.assertAlmostEqual(s["atr"][i], (99.3 - 98.4) + 0.3 * a)

    def test_no_signal_cases(self):
        b = sweep_world()
        i = 2 * 96 + slot(10)
        # kapanis PDH ustunde (kirilim, sahte degil)
        x = list(b)
        put(x, i, 100.0, 101.8, 100.0, 101.4)
        self.assertEqual(side_at("fx_pdh_pdl_supurme", x, i), 0)
        # fitil cok kisa (0.05 < 0.1*ATR)
        x = list(b)
        put(x, i, 100.0, 101.05, 100.0, 100.8)
        self.assertEqual(side_at("fx_pdh_pdl_supurme", x, i), 0)
        # seans disi (03:00)
        x = list(b)
        j = 2 * 96 + slot(3)
        put(x, j, 100.0, 101.5, 100.0, 100.8)
        self.assertEqual(side_at("fx_pdh_pdl_supurme", x, j), 0)
        # seans siniri: 19:45 bari icinde, 20:00 bari disinda
        x = list(b)
        put(x, 2 * 96 + slot(19, 45), 100.0, 101.5, 100.0, 100.8)
        put(x, 2 * 96 + slot(20), 100.0, 101.5, 100.0, 100.8)
        self.assertEqual(side_at("fx_pdh_pdl_supurme", x, 2 * 96 + slot(19, 45)), -1)
        self.assertEqual(side_at("fx_pdh_pdl_supurme", x, 2 * 96 + slot(20)), 0)
        # hem PDH hem PDL supurmesi -> belirsiz
        x = list(b)
        put(x, i, 100.0, 101.5, 98.5, 100.0)
        self.assertEqual(side_at("fx_pdh_pdl_supurme", x, i), 0)

    def test_previous_day_excludes_current_day(self):
        # ayni gunun kendi yuksegi PDH olmaz: gun 1'de (kendi PDH'si = gun 0) fitil/kapanis
        b = flat_days(2, pad=0.5)
        i = 96 + slot(10)
        put(b, i, 100.0, 100.9, 100.0, 100.3)  # gun 0 PDH=100.5 -> 0.4 >= 0.1*ATR, kapanis altinda
        self.assertEqual(side_at("fx_pdh_pdl_supurme", b, i), -1)
        # sonraki bar ayni gunun yuksegine (100.9) dokunsa da PDH hala 100.5
        put(b, i + 1, 100.3, 100.7, 100.0, 100.4)
        self.assertEqual(side_at("fx_pdh_pdl_supurme", b, i + 1), -1)


# ------------------------------------------------------------------ para gucu
V_BUY = {"EUR": 3e-4, "GBP": 2e-4, "CAD": 5e-5, "CHF": 4e-5, "NZD": 3e-5, "JPY": -1e-4, "USD": -2e-4}


def fx21_from_drifts(v, n=288, overrides=None, t0=T0, tf=TF):
    """Her parite: log-getiri/bar = v[taban] - v[karsi]. overrides: {(parite, k): log-getiri} o barin getirisini degistirir."""
    data = {}
    for p in ALL21:
        c = 1.0
        rows = []
        for k in range(n):
            o = c
            r = v[p[:3]] - v[p[3:]]
            if overrides and (p, k) in overrides:
                r = overrides[(p, k)]
            c = o * math.exp(r)
            rows.append([float(t0 + k * tf), o, max(o, c) * 1.00001, min(o, c) * 0.99999, c])
        data[p] = rows
    return data


def bars_of_rows(rows):
    return [eng.Bar(int(r[0]), r[1], r[2], r[3], r[4]) for r in rows]


class Fx21Mixin:
    def setUp(self):
        self._old = mod._FX21_LOADER

    def tearDown(self):
        mod._FX21_LOADER = self._old

    def set_data(self, data):
        mod._FX21_LOADER = lambda tf_name: data


class ParaGucuTest(Fx21Mixin, unittest.TestCase):
    I = 96 + slot(10)  # Persembe 10:00 (saat kovasinin ilk bari)

    def test_buy_when_base_strongest_and_quote_weakest(self):
        data = fx21_from_drifts(V_BUY)
        self.set_data(data)
        b = bars_of_rows(data["EURUSD"])
        s = series_of("fx_para_gucu", b)
        sd = STRATS["fx_para_gucu"]["side"]
        self.assertEqual(sd(s, b, self.I), 1)
        self.assertEqual(sd(s, b, self.I + 1), 0)  # ayni saat kovasinda tekrar yok
        self.assertEqual(sd(s, b, self.I + 3), 0)
        self.assertEqual(sd(s, b, self.I + 4), 1)  # 11:00 kovasi
        self.assertEqual(sd(s, b, 96 + slot(5)), 0)  # seans disi

    def test_sell_mirror_and_other_pair(self):
        v = {k: -x for k, x in V_BUY.items()}  # USD en guclu, EUR en zayif -> EURUSD SELL
        data = fx21_from_drifts(v)
        self.set_data(data)
        b = bars_of_rows(data["EURUSD"])
        self.assertEqual(side_at("fx_para_gucu", b, self.I), -1)
        # GBPJPY: GBP (2 numara, zayifta) taban -> bottom2 (v ters: GBP -2e-4 ikinci en zayif); JPY (+1e-4)
        # quote ranking: USD,CAD,.. -> JPY orta -> sinyal yok
        data2 = fx21_from_drifts(V_BUY)
        self.set_data(data2)
        b = bars_of_rows(data2["GBPJPY"])
        self.assertEqual(side_at("fx_para_gucu", b, self.I), 1)  # GBP top2, JPY bottom2
        b = bars_of_rows(data2["USDJPY"])
        self.assertEqual(side_at("fx_para_gucu", b, self.I), 0)  # USD & JPY ikisi de zayif: taban top2 degil

    def test_middle_ranked_currency_blocks(self):
        v = dict(V_BUY)
        v["USD"], v["NZD"] = 3.5e-5, -2e-4  # USD artik orta; NZD en zayif
        data = fx21_from_drifts(v)
        self.set_data(data)
        b = bars_of_rows(data["EURUSD"])
        self.assertEqual(side_at("fx_para_gucu", b, self.I), 0)

    def test_own_three_bar_return_must_agree(self):
        # EURUSD'nin son 3 bari asagi (guc siralamasi 24 bar toplaminda hala EUR guclu, USD zayif)
        ov = {("EURUSD", self.I - 2): -4e-4, ("EURUSD", self.I - 1): -4e-4, ("EURUSD", self.I): -4e-4}
        data = fx21_from_drifts(V_BUY, overrides=ov)
        self.set_data(data)
        b = bars_of_rows(data["EURUSD"])
        self.assertEqual(side_at("fx_para_gucu", b, self.I), 0)

    def test_uses_only_bars_up_to_current_time_from_other_pairs(self):
        data = fx21_from_drifts(V_BUY)
        self.set_data(data)
        b = bars_of_rows(data["EURUSD"])
        ref = series_of("fx_para_gucu", b)["sig"]
        # diger paritelerin I'dan sonraki barlari tamamen ters: I ve oncesi degismez
        alt = {p: [r[:] for r in rows] for p, rows in data.items()}
        for p, rows in alt.items():
            if p != "EURUSD":
                for r in rows[self.I + 1:]:
                    r[4] = r[1] = 5.0
                    r[2], r[3] = 5.1, 4.9
        self.set_data(alt)
        got = series_of("fx_para_gucu", b)["sig"]
        self.assertEqual(ref[:self.I + 1], got[:self.I + 1])

    def test_unidentified_pair_and_unsupported_interval_raise(self):
        data = fx21_from_drifts(V_BUY)
        self.set_data(data)
        b = bars_of_rows(data["EURUSD"])
        bad = [eng.Bar(x.t, x.open, x.high, x.low, x.close * 1.01) for x in b]
        with self.assertRaises(ValueError):
            STRATS["fx_para_gucu"]["series"](bad, [x.close for x in bad])
        odd = [mk(i, 100.0, 100.0, tf=600) for i in range(50)]
        with self.assertRaises(ValueError):
            STRATS["fx_para_gucu"]["series"](odd, [x.close for x in odd])

    def test_default_loader_reads_cache_file_format(self):
        path = os.path.join(os.path.dirname(SCRIPTS), "outputs", "replay_cache_fx21_m15.json")
        if not os.path.exists(path):
            self.skipTest("onbellek yok")
        data = mod._default_fx21_loader("m15")
        self.assertEqual(len(data), 21)
        self.assertEqual(len(data["EURUSD"][0]), 5)


# ------------------------------------------------------------------ doji kumesi
def doji_world(extra=None, n_ctx=30, start_h=8):
    """Gun 2, start_h:00'dan baslayan n_ctx baglam bari (govdeli, aralik 1.0), sonra 3 doji; sonraki indeks dondurulur."""
    t0 = T0 + 2 * 86400 + start_h * 3600
    b = []
    for k in range(n_ctx):
        if k % 2 == 0:
            b.append(eng.Bar(t0 + k * TF, 100.0, 101.0, 100.0, 100.8))
        else:
            b.append(eng.Bar(t0 + k * TF, 100.8, 100.8, 99.8, 100.0))
    return b, t0


def add_dojis(b, t0, n=3, lo=99.9, hi=100.9):
    for j in range(n):
        k = len(b)
        b.append(eng.Bar(t0 + k * TF, 100.4, hi, lo, 100.45))
    return b


class DojiKumesiTest(unittest.TestCase):
    def test_buy_breakout_with_cluster_stop(self):
        b, t0 = doji_world()
        add_dojis(b, t0)
        k = len(b)
        b.append(eng.Bar(t0 + k * TF, 100.4, 102.2, 100.3, 102.0))  # govde 1.6/aralik 1.9, kapanis > 100.9
        s = series_of("fx_doji_kumesi", b)
        sd = STRATS["fx_doji_kumesi"]["side"]
        self.assertEqual(sd(s, b, k), 1)
        self.assertAlmostEqual(s["atr"][k], 102.0 - 99.9)  # kume dibi (2.1) >= 1.0*ATR
        self.assertEqual(sd(s, b, k - 1), 0)

    def test_sell_mirror_and_min_atr_stop(self):
        b, t0 = doji_world()
        add_dojis(b, t0, lo=100.3, hi=100.5)  # dar kume
        k = len(b)
        b.append(eng.Bar(t0 + k * TF, 100.4, 100.45, 99.85, 99.9))  # govde 0.5/aralik 0.6 (>= 0.6 oldugundan sinir)
        s = series_of("fx_doji_kumesi", b)
        a = wk.atr(b, 14)[k]
        self.assertEqual(STRATS["fx_doji_kumesi"]["side"](s, b, k), -1)
        self.assertAlmostEqual(s["atr"][k], max(100.5 - 99.9, 1.0 * a))
        self.assertAlmostEqual(s["atr"][k], a)  # kume stopu (0.6) ATR'den kisa -> ATR

    def test_no_signal_cases(self):
        def run(brk, n_doji=3, start_h=8):
            b, t0 = doji_world(start_h=start_h)
            add_dojis(b, t0, n=n_doji)
            k = len(b)
            b.append(eng.Bar(t0 + k * TF, *brk))
            return side_at("fx_doji_kumesi", b, k)
        good = (100.4, 102.2, 100.3, 102.0)
        self.assertEqual(run(good), 1)
        self.assertEqual(run(good, n_doji=2), 0)  # kume 3'ten kisa
        self.assertEqual(run((100.4, 102.2, 100.3, 100.8)), 0)  # kapanis kume yuksegi (100.9) icinde
        self.assertEqual(run((100.4, 102.6, 100.3, 101.2)), 0)  # govde 0.8/aralik 2.3 < 0.6
        self.assertEqual(run((102.0, 102.2, 100.3, 100.95)), 0)  # kume disinda ama ters renk (kirmizi) kirilim
        self.assertEqual(run(good, start_h=21), 0)  # kirilim bari 05:15 UTC (seans disi)

    def test_cluster_breaks_on_non_doji(self):
        b, t0 = doji_world()
        add_dojis(b, t0, n=2)
        k = len(b)
        b.append(eng.Bar(t0 + k * TF, 100.0, 101.0, 100.0, 100.8))  # govdeli bar kumeyi bozar
        add_dojis(b, t0, n=1)
        k = len(b)
        b.append(eng.Bar(t0 + k * TF, 100.4, 102.2, 100.3, 102.0))
        self.assertEqual(side_at("fx_doji_kumesi", b, k), 0)


# ------------------------------------------------------------------ ADR tukenisi
def adr_world(n_days=15):
    """n_days duz gun (aralik 1.0 -> ADR 1.0), sonra hedef gun: 10:00'a kadar duz 100, sonra dusus."""
    b = flat_days(n_days, pad=0.5)
    base = n_days * 96
    b += [mk(base + k, 100.0, 100.0, pad=0.5) for k in range(96)]
    return b, base


def drop_day(b, base):
    """10:00-10:30 arasi 99, 98, 97 kapanis; 10:45 bari yesil, dip kapanisa yakin kapanir."""
    put(b, base + slot(10), 100.0, 100.0, 98.9, 99.0)
    put(b, base + slot(10, 15), 99.0, 99.0, 97.9, 98.0)
    put(b, base + slot(10, 30), 98.0, 98.0, 96.9, 97.0)
    put(b, base + slot(10, 45), 96.95, 97.15, 96.9, 97.1)  # yesil, kapanis - dip kapanis = 0.1
    # sonrasi: 97.1'de duz
    for k in range(slot(11), 96):
        put(b, base + k, 97.1, 97.2, 97.0, 97.1)
    return b


class AdrTukenisTest(unittest.TestCase):
    def test_buy_at_day_low_exhaustion_with_clipped_distance(self):
        b, base = adr_world()
        drop_day(b, base)
        i = base + slot(10, 45)
        s = series_of("fx_adr_tukenis", b)
        sd = STRATS["fx_adr_tukenis"]["side"]
        self.assertEqual(sd(s, b, i), 1)
        a = wk.atr(b, 14)[i]
        hi, lo, c = 100.5, 96.9, 97.1
        sl0 = (c - lo) + 0.3 * a
        mid = abs(c - (hi + lo) / 2)
        want = min(max(mid, 0.8 * sl0), 2.5 * sl0)
        self.assertAlmostEqual(s["atr"][i], want)
        self.assertGreaterEqual(mid / sl0, 0.8)  # bu senaryoda ust sinira takilmiyor
        # gunde yon basina 1: sonraki esdeger bar tekrar BUY vermez
        put(b, i + 1, 97.1, 97.25, 96.95, 97.15)
        s = series_of("fx_adr_tukenis", b)
        self.assertEqual(sd(s, b, i + 1), 0)

    def test_upper_clip(self):
        b, base = adr_world()
        # cok genis gun: 100 -> 90 dususu; dibe yakin yesil bar -> orta nokta cok uzak -> 2.5*SL0
        put(b, base + slot(10), 100.0, 100.0, 89.9, 90.0)
        put(b, base + slot(10, 15), 89.95, 90.2, 89.9, 90.1)
        i = base + slot(10, 15)
        s = series_of("fx_adr_tukenis", b)
        self.assertEqual(STRATS["fx_adr_tukenis"]["side"](s, b, i), 1)
        a = wk.atr(b, 14)[i]
        sl0 = (90.1 - 89.9) + 0.3 * a
        self.assertAlmostEqual(s["atr"][i], 2.5 * sl0)

    def test_sell_at_day_high_mirror(self):
        b, base = adr_world()
        put(b, base + slot(10), 100.0, 101.1, 100.0, 101.0)
        put(b, base + slot(10, 15), 101.0, 102.1, 101.0, 102.0)
        put(b, base + slot(10, 30), 102.0, 103.1, 102.0, 103.0)
        put(b, base + slot(10, 45), 103.05, 103.1, 102.85, 102.9)  # kirmizi, tepe kapanisa 0.1
        i = base + slot(10, 45)
        s = series_of("fx_adr_tukenis", b)
        self.assertEqual(STRATS["fx_adr_tukenis"]["side"](s, b, i), -1)

    def test_no_signal_cases(self):
        b, base = adr_world()
        drop_day(b, base)
        i = base + slot(10, 45)
        # kirmizi bar (ters renk degil, dibe dogru devam)
        x = list(b)
        put(x, i, 97.25, 97.25, 96.9, 97.1)
        self.assertEqual(side_at("fx_adr_tukenis", x, i), 0)
        # kapanis dip kapanisindan 0.2*ATR'den uzak
        x = list(b)
        put(x, i, 96.95, 98.0, 96.9, 97.9)
        self.assertEqual(side_at("fx_adr_tukenis", x, i), 0)
        # 14 kapanmis gun yok -> ADR yok
        b2, base2 = adr_world(n_days=13)
        drop_day(b2, base2)
        self.assertEqual(side_at("fx_adr_tukenis", b2, base2 + slot(10, 45)), 0)
        # gun araligi < 1.2*ADR (kisa dusus)
        b3, base3 = adr_world()
        put(b3, base3 + slot(10), 100.0, 100.0, 99.5, 99.55)
        put(b3, base3 + slot(10, 15), 99.55, 99.65, 99.5, 99.6)
        self.assertEqual(side_at("fx_adr_tukenis", b3, base3 + slot(10, 15)), 0)
        # seans disi (03:45'te ayni desen)
        b4, base4 = adr_world()
        put(b4, base4 + slot(3, 30), 100.0, 100.0, 96.9, 97.0)
        put(b4, base4 + slot(3, 45), 96.95, 97.15, 96.9, 97.1)
        self.assertEqual(side_at("fx_adr_tukenis", b4, base4 + slot(3, 45)), 0)


# ------------------------------------------------------------------ look-ahead
def cut_points(sides, n_cuts=150):
    """Sinyal tasiyan bolge uzerinde ~n_cuts kesim noktasi: yarisi duzgun aralikli, yarisi sinyal barlarindan (+ onceki bar)."""
    sig = [i for i, v in enumerate(sides) if v != 0]
    if not sig:  # sinyalsiz tohum: yine de tum aralikta duzgun aralikli kesimler
        return sorted({1 + (len(sides) - 2) * j // (n_cuts - 1) for j in range(n_cuts)})
    lo, hi = max(1, sig[0] - 3), len(sides) - 1
    half = n_cuts // 2
    even = [lo + (hi - lo) * j // max(1, half - 1) for j in range(half)]
    pick = [sig[(len(sig) - 1) * j // max(1, n_cuts - half - 1)] for j in range(n_cuts - half)] if len(sig) > 1 else sig
    near = [i - 1 for i in pick if i - 1 >= lo]  # sinyalsiz komsu bar da sinanir
    return sorted(set(even) | set(pick) | set(near[::2]))


def prefix_check(tc, name, b, n_cuts=150, setter=None, full_data=None, trunc=None):
    """Cok-kesim on-ek kontrolu: ~n_cuts kesim k icin side(series(b[:k+1]), k) == side(series(b), k) ve etkin atr[k] esit.
    1-bar sizintilar yalniz kesim barinda gorunur; bu yuzden cok sayida kesim gerekir.
    Capraz seri varsa (setter/full_data/trunc): her kesimde diger seriler de t <= b[k].t ile kirpilir."""
    sd = STRATS[name]["side"]
    if setter is not None:
        setter(full_data)
    s_full = series_of(name, b)
    sides = [sd(s_full, b, i) for i in range(len(b))]
    cuts = cut_points(sides, n_cuts)
    tc.assertGreaterEqual(len(cuts), min(n_cuts // 2, 30), name)
    for k in cuts:
        if setter is not None:
            setter(trunc(full_data, b[k].t))
        s_k = series_of(name, b[:k + 1])
        tc.assertEqual(sd(s_k, b[:k + 1], k), sides[k], f"{name} on-ek kesim k={k}")
        tc.assertEqual(s_k["atr"][k], s_full["atr"][k], f"{name} on-ek atr k={k}")
    if setter is not None:
        setter(full_data)
    return sum(1 for k in cuts if sides[k] != 0)  # sinyal tasiyan kesim sayisi


class LookAheadTest(unittest.TestCase):
    """Kisa seri ile uzun seri (ek gelecek barlar) icin her i'de ayni karar + ayni etkin atr."""

    def _check(self, name, n_short, n_ext, seeds=(7, 11), n_cuts=150, **kw):
        total_signals = psig = 0
        sd = STRATS[name]["side"]
        for seed in seeds:
            long_b = random_walk(n_short + n_ext, seed, **kw)
            psig += prefix_check(self, name, long_b, n_cuts=n_cuts)
            short_b = long_b[:n_short]
            alt_future = random_walk(n_ext, seed + 100, **kw)
            alt_future = [eng.Bar(short_b[-1].t + (k + 1) * TF, x.open, x.high, x.low, x.close)
                          for k, x in enumerate(alt_future)]
            s_short = series_of(name, short_b)
            for longer in (long_b, short_b + alt_future):
                s_long = series_of(name, longer)
                for i in range(len(short_b)):
                    a, c = sd(s_short, short_b, i), sd(s_long, longer, i)
                    self.assertEqual(a, c, f"{name} seed {seed} i={i}")
                    self.assertEqual(s_short["atr"][i], s_long["atr"][i], f"{name} atr i={i}")
                    total_signals += abs(a)
        self.assertGreater(psig, 0, f"{name}: on-ek kontrolu sinyal tasiyan kesim icermiyor")
        return total_signals

    def _mid_day_cuts(self, name, long_b, days, slots, alt_seed=None):
        """Kesim gun ICINDE: kisa (kismi son gun) ve uzun seri kesimden onceki TUM barlarda ayni karar/atr vermeli."""
        sd = STRATS[name]["side"]
        s_long = series_of(name, long_b)
        compared = signals = 0
        for day in days:
            for sl in slots:
                cut = day * 96 + sl
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
                        self.assertEqual(a, c, f"{name} day {day} slot {sl} i={i}")
                        self.assertEqual(s_short["atr"][i], s_l["atr"][i], f"{name} atr day {day} slot {sl} i={i}")
                        signals += abs(a)
                        compared += 1
        self.assertGreater(compared, 0)
        return signals

    # ---- seans devri (13:00 karari; kesim 07:30, 09:00, 12:45, 13:00 dolayinda)
    def test_seans_devri(self):
        self.assertGreater(self._check("fx_seans_devri", 96 * 60, 96 * 20, seeds=(7, 11, 13), step=0.5, sd=0.35), 0)

    def test_seans_devri_mid_day_cut(self):
        long_b = random_walk(96 * 70, 31, step=0.5, sd=0.35)
        sig = self._mid_day_cuts("fx_seans_devri", long_b, range(15, 66, 5),
                                 slots=(30, 36, 44, 51, 52, 53), alt_seed=500)
        self.assertGreater(sig, 0)

    def test_pdh_pdl_supurme(self):
        self.assertGreater(self._check("fx_pdh_pdl_supurme", 96 * 20, 96 * 8), 0)

    def test_pdh_pdl_mid_day_cut(self):
        long_b = random_walk(96 * 30, 32)
        sig = self._mid_day_cuts("fx_pdh_pdl_supurme", long_b, range(5, 28, 3), slots=(1, 28, 40, 79, 80), alt_seed=510)
        self.assertGreater(sig, 0)

    def test_doji_kumesi(self):
        self.assertGreater(self._check("fx_doji_kumesi", 96 * 40, 96 * 10, seeds=(7, 11, 13, 17), step=0.02, sd=0.3), 0)

    def test_doji_kumesi_mid_day_cut(self):
        long_b = random_walk(96 * 40, 33, step=0.02, sd=0.3)
        sig = self._mid_day_cuts("fx_doji_kumesi", long_b, range(5, 38, 3), slots=(1, 30, 45, 79), alt_seed=520)
        self.assertGreater(sig, 0)

    def test_adr_tukenis(self):
        self.assertGreater(self._check("fx_adr_tukenis", 96 * 70, 96 * 20, seeds=(7, 11, 13), step=0.4, sd=0.5), 0)

    def test_adr_tukenis_mid_day_cut(self):
        long_b = random_walk(96 * 75, 34, step=0.4, sd=0.5)
        sig = self._mid_day_cuts("fx_adr_tukenis", long_b, range(40, 72, 4), slots=(1, 30, 45, 60, 79), alt_seed=530)
        self.assertGreater(sig, 0)


# ------------------------------------------------------------------ para gucu look-ahead (capraz seri)
def fx21_random(n, seed, cut=None, seed2=None, t0=T0, tf=TF):
    """21 pariteli rastgele rejimler. k >= cut sonrasi baska tohumla (farkli gelecek). k < cut kismi cut'tan bagimsiz."""
    rnd = random.Random(seed)
    rnd2 = random.Random(seed2 if seed2 is not None else seed)
    cur = sorted({p[k:k + 3] for p in ALL21 for k in (0, 3)})
    close = {p: 1.0 for p in ALL21}
    rows = {p: [] for p in ALL21}
    v = {}
    for k in range(n):
        rr = rnd if (cut is None or k < cut) else rnd2
        if k % 60 == 0:
            v = {c: rr.gauss(0, 2e-4) for c in cur}
        for p in ALL21:
            o = close[p]
            c = o * math.exp(v[p[:3]] - v[p[3:]] + rr.gauss(0, 3e-4))
            close[p] = c
            rows[p].append([float(t0 + k * tf), o, max(o, c) * 1.0001, min(o, c) * 0.9999, c])
    return rows


class ParaGucuLookAheadTest(Fx21Mixin, unittest.TestCase):
    def test_cross_series_truncation_and_perturbation(self):
        name = "fx_para_gucu"
        sd = STRATS[name]["side"]
        total = 0
        for seed in (3, 5):
            n_long, cut = 96 * 12, 96 * 7 + 41  # kesim gun ortasi (10:15)
            full = fx21_random(n_long, seed)
            alt = fx21_random(n_long, seed, cut=cut, seed2=seed + 1000)  # kesimden sonrasi farkli
            short = {p: rows[:cut] for p, rows in full.items()}
            for p in ("EURUSD", "GBPJPY", "NZDUSD"):
                own_short = bars_of_rows(short[p])
                self.set_data(short)
                s_ref = series_of(name, own_short)
                ref = [sd(s_ref, own_short, i) for i in range(cut)]
                total += sum(abs(v) for v in ref)
                for label, data, own in (
                        ("diger pariteler tam", full, own_short),
                        ("diger pariteler alternatif gelecek", alt, own_short),
                        ("kendi uzun, diger tam", full, bars_of_rows(full[p])),
                        ("kendi uzun, diger alternatif", alt, bars_of_rows(alt[p]))):
                    # kendi uzun + alternatif: kesimden sonrasi kendi de alternatif; kesim oncesi ayni olmali
                    self.set_data(data)
                    s_v = series_of(name, own)
                    for i in range(cut):
                        self.assertEqual(ref[i], sd(s_v, own, i), f"{label} {p} seed {seed} i={i}")
        self.assertGreater(total, 0)

    def test_many_cut_prefix_cross_series(self):
        """Cok-kesim on-ek: her kesim k'da hem kendi seri hem TUM diger pariteler t <= b[k].t ile kirpilir."""
        name = "fx_para_gucu"
        psig = 0
        trunc = lambda d, t: {q: [r for r in rows if r[0] <= t] for q, rows in d.items()}
        for seed, pairs in ((3, ("EURUSD", "GBPJPY")), (5, ("NZDUSD", "EURUSD"))):
            full = fx21_random(96 * 12, seed)
            for p in pairs:
                psig += prefix_check(self, name, bars_of_rows(full[p]), n_cuts=150,
                                     setter=self.set_data, full_data=full, trunc=trunc)
        self.assertGreater(psig, 0)


if __name__ == "__main__":
    unittest.main()
