"""btc_ozgun stratejileri: sentetik sinyal + look-ahead testleri.

Calistirma (repo kokunden):  python -m unittest scripts.strategies.test_btc_ozgun
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

_spec = importlib.util.spec_from_file_location("btc_ozgun_under_test", os.path.join(os.path.dirname(__file__), "btc_ozgun.py"))
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


def shift(bars, k):
    """Seriyi zamanda k bar ileri tasi (gelecek ekleme icin)."""
    return [eng.Bar(x.t + k * TF, x.open, x.high, x.low, x.close) for x in bars]


class ShapeTest(unittest.TestCase):
    def test_registry(self):
        self.assertEqual(set(STRATS), {"btc_saat_profili", "btc_likidite_supurme", "btc_xau_oncu",
                                       "btc_govde_yigini", "btc_verimlilik_rejimi"})
        for st in STRATS.values():
            self.assertEqual(st["symbols"], {"BTCUSD"})
            self.assertTrue(callable(st["series"]) and callable(st["side"]))
        want = {"btc_saat_profili": (1.5, 1.0), "btc_likidite_supurme": (1.0, 2.0), "btc_xau_oncu": (1.5, 1.5),
                "btc_govde_yigini": (1.0, 2.0), "btc_verimlilik_rejimi": (1.5, 1.5)}
        for k, v in want.items():
            self.assertEqual((STRATS[k]["sl_atr"], STRATS[k]["tp_r"]), v, k)

    def test_docstring_has_originality_sentences(self):
        self.assertEqual(mod.__doc__.count("Neden ozgun"), 5)


# ------------------------------------------------------------------ saat profili
def day_bars(n_days, hour_ret, noise_hours=None):
    """n_days gun x 96 bar (m15). hour_ret(d, h) -> o saat kovasinin toplam log-getirisi (4 bara bolunur).
    Diger saatler tam duz (std=0)."""
    bars, c, k = [], 100.0, 0
    for d in range(n_days):
        for h in range(24):
            r = hour_ret(d, h)
            for _ in range(4):
                o = c
                c = o * math.exp(r / 4.0)
                bars.append(mk(k, o, c, pad=0.05))
                k += 1
    return bars


class SaatProfiliTest(unittest.TestCase):
    def test_long_and_short_at_bucket_start(self):
        up = lambda d, h: (0.004 + 0.001 * ((d % 3) - 1)) if h == 10 else 0.0
        bars = day_bars(26, up)
        i = 25 * 96 + 10 * 4  # 26. gun 10:00 ilk bar
        self.assertEqual(side_at("btc_saat_profili", bars, i), 1)
        self.assertEqual(side_at("btc_saat_profili", bars, i + 1), 0)  # kova basinda tek giris
        self.assertEqual(side_at("btc_saat_profili", bars, i + 4), 0)  # sonraki saat (duz, std=0)
        dn = lambda d, h: (-0.004 + 0.001 * ((d % 3) - 1)) if h == 10 else 0.0
        self.assertEqual(side_at("btc_saat_profili", day_bars(26, dn), i), -1)

    def test_needs_min_history_and_tstat(self):
        up = lambda d, h: (0.004 + 0.001 * ((d % 3) - 1)) if h == 10 else 0.0
        short = day_bars(11, up)  # 10 onceki gun var -> n=10, yeterli
        self.assertEqual(side_at("btc_saat_profili", short, 10 * 96 + 40), 1)
        shorter = day_bars(10, up)  # 9 onceki gun -> n<10
        self.assertEqual(side_at("btc_saat_profili", shorter, 9 * 96 + 40), 0)
        # ortalama ~0 (gunler +/-): |t| < 2
        alt = lambda d, h: (0.004 if d % 2 else -0.004) if h == 10 else 0.0
        self.assertEqual(side_at("btc_saat_profili", day_bars(26, alt), 25 * 96 + 40), 0)

    def test_uses_only_past_days(self):
        # bugun (son gun) kova getirisi cok farkli olsa da karar degismez
        base = lambda d, h: (0.004 + 0.001 * ((d % 3) - 1)) if h == 10 else 0.0
        spiky = lambda d, h: (-0.05 if d == 25 else base(d, h)) if h == 10 else 0.0
        i = 25 * 96 + 40
        self.assertEqual(side_at("btc_saat_profili", day_bars(26, base), i), 1)
        self.assertEqual(side_at("btc_saat_profili", day_bars(26, spiky), i), 1)


# ------------------------------------------------------------------ likidite supurme
class LikiditeSupurmeTest(unittest.TestCase):
    def _flat(self, n=40):
        return [mk(i, 100.0, 100.0, pad=0.5) for i in range(n)]  # H100.5 L99.5, ATR=1

    def test_buy_sweep_low_and_reclaim(self):
        b = self._flat()
        b.append(eng.Bar(T0 + 40 * TF, 100.0, 100.0, 98.5, 99.8))  # dip 99.5 -> 98.5 (1.0 >= 0.2*ATR), kapanis ustunde
        i = len(b) - 1
        s = series_of("btc_likidite_supurme", b)
        self.assertEqual(STRATS["btc_likidite_supurme"]["side"](s, b, i), 1)
        a = wk.atr(b, 14)[i]
        self.assertAlmostEqual(s["atr"][i], (99.8 - 98.5) + 0.3 * a)  # SL = supurme ucunun 0.3*ATR otesi
        self.assertAlmostEqual(s["atr"][i - 1], wk.atr(b, 14)[i - 1])  # sinyalsiz barda normal ATR

    def test_sell_mirror(self):
        b = self._flat()
        b.append(eng.Bar(T0 + 40 * TF, 100.0, 101.5, 100.0, 100.2))
        i = len(b) - 1
        s = series_of("btc_likidite_supurme", b)
        self.assertEqual(STRATS["btc_likidite_supurme"]["side"](s, b, i), -1)
        a = wk.atr(b, 14)[i]
        self.assertAlmostEqual(s["atr"][i], (101.5 - 100.2) + 0.3 * a)

    def test_no_signal_cases(self):
        b = self._flat()
        # fitil cok kisa (0.05 < 0.2*ATR)
        x = b + [eng.Bar(T0 + 40 * TF, 100.0, 100.0, 99.45, 99.8)]
        self.assertEqual(side_at("btc_likidite_supurme", x, len(x) - 1), 0)
        # supurme var ama kapanis seviyenin altinda (kirilim, donus degil)
        x = b + [eng.Bar(T0 + 40 * TF, 100.0, 100.0, 98.5, 99.0)]
        self.assertEqual(side_at("btc_likidite_supurme", x, len(x) - 1), 0)
        # hem alt hem ust supurme -> belirsiz
        x = b + [eng.Bar(T0 + 40 * TF, 100.0, 101.5, 98.5, 100.0)]
        self.assertEqual(side_at("btc_likidite_supurme", x, len(x) - 1), 0)


# ------------------------------------------------------------------ XAU oncusu
def xau_rows(n, seed=3, jump_at=(), jump=0.0, jumps=None, t0=T0, tf=TF):
    """XAU m15 satirlari; jump_at+jump (tek deger) ya da jumps={k: log-getiri} ile tek-bar sicramalar."""
    rnd = random.Random(seed)
    rows, c = [], 4000.0
    jm = dict(jumps or {})
    for k in jump_at:
        jm[k] = jump
    for k in range(n):
        o = c
        r = rnd.gauss(0, 0.0008)
        r += jm.get(k, 0.0)
        c = o * math.exp(r)
        rows.append([float(t0 + k * tf), o, max(o, c), min(o, c), c])
    return rows


class XauLoaderMixin:
    def setUp(self):
        self._old = mod._XAU_LOADER

    def tearDown(self):
        mod._XAU_LOADER = self._old

    def set_xau(self, rows):
        mod._XAU_LOADER = lambda tf_name: rows


def btc_flat(n, drift=0.0):
    bars, c = [], 100.0
    for i in range(n):
        o = c
        c = o + drift
        bars.append(mk(i, o, c, pad=0.3))
    return bars


class XauOncuTest(XauLoaderMixin, unittest.TestCase):
    def test_follows_xau_jump_if_btc_has_not_moved(self):
        n = 200
        self.set_xau(xau_rows(n, jump_at={150}, jump=0.03))
        b = btc_flat(n, drift=0.0)  # BTC duz: 12 bar getirisi 0 -> "duz" kabul
        self.assertEqual(side_at("btc_xau_oncu", b, 150), 1)
        self.assertEqual(side_at("btc_xau_oncu", b, 120), 0)
        self.set_xau(xau_rows(n, jump_at={150}, jump=-0.03))
        self.assertEqual(side_at("btc_xau_oncu", b, 150), -1)

    def test_blocked_when_btc_already_moved_same_direction(self):
        n = 200
        self.set_xau(xau_rows(n, jump_at={150}, jump=0.03))
        up = btc_flat(n, drift=0.2)  # BTC zaten yukari
        self.assertEqual(side_at("btc_xau_oncu", up, 150), 0)
        dn = btc_flat(n, drift=-0.2)  # BTC ters yonde -> giris serbest
        self.assertEqual(side_at("btc_xau_oncu", dn, 150), 1)

    def test_future_xau_bar_not_used_and_stale_xau_blocked(self):
        n = 200
        # sicrama BTC bar 150'nin kapanisindan SONRA (xau bar 151) -> bar 150'de sinyal olmamali
        self.set_xau(xau_rows(n, jump_at={151}, jump=0.03))
        b = btc_flat(n)
        self.assertEqual(side_at("btc_xau_oncu", b, 150), 0)
        self.assertEqual(side_at("btc_xau_oncu", b, 151), 1)
        # XAU serisi 151'de biter (piyasa kapali): sonraki BTC barlari bayat XAU ile sinyal uretmez
        self.set_xau(xau_rows(152, jump_at={151}, jump=0.03))
        self.assertEqual(side_at("btc_xau_oncu", b, 151), 1)
        self.assertEqual(side_at("btc_xau_oncu", b, 160), 0)

    def test_unsupported_interval_raises(self):
        self.set_xau(xau_rows(50))
        bars = [mk(i, 100.0, 100.0, tf=600) for i in range(50)]
        with self.assertRaises(ValueError):
            STRATS["btc_xau_oncu"]["series"](bars, [x.close for x in bars])

    def test_default_loader_reads_cache_file_format(self):
        path = os.path.join(os.path.dirname(SCRIPTS), "outputs", "replay_cache_xaubtc_m15.json")
        if not os.path.exists(path):
            self.skipTest("onbellek yok")
        rows = mod._default_xau_loader("m15")
        self.assertGreater(len(rows), 1000)
        self.assertEqual(len(rows[0]), 5)


# ------------------------------------------------------------------ govde yigini
def ramp_bars(base_i, sign=1):
    """100 civarinda 4 bar: (i-3) normal, sonra 3 bar genisleyen aralik + yuksek CLV. sign=-1 ayna."""
    spec = [  # (open, high, low, close) yukari yon
        (100.0, 100.5, 99.5, 100.0),
        (100.0, 101.5, 99.8, 101.2),
        (101.2, 103.4, 100.9, 103.2),
        (103.2, 106.0, 103.0, 105.7),
    ]
    out = []
    for k, (o, h, l, c) in enumerate(spec):
        if sign == 1:
            out.append(eng.Bar(T0 + (base_i + k) * TF, o, h, l, c))
        else:
            out.append(eng.Bar(T0 + (base_i + k) * TF, 200 - o, 200 - l, 200 - h, 200 - c))
    return out


class GovdeYiginiTest(unittest.TestCase):
    def test_buy_sell_and_variable_sl(self):
        flat = [mk(i, 100.0, 100.0, pad=0.5) for i in range(30)]
        b = flat + ramp_bars(30)
        i = len(b) - 1
        s = series_of("btc_govde_yigini", b)
        sd = STRATS["btc_govde_yigini"]["side"]
        self.assertEqual(sd(s, b, i), 1)
        self.assertEqual(sd(s, b, i - 1), 0)
        self.assertAlmostEqual(s["atr"][i], 105.7 - 99.8)  # SL = 3 barin en dusugu
        b = flat + ramp_bars(30, -1)
        s = series_of("btc_govde_yigini", b)
        self.assertEqual(sd(s, b, i), -1)
        self.assertAlmostEqual(s["atr"][i], (200 - 99.8) - (200 - 105.7))

    def test_no_signal_if_range_not_expanding_or_clv_low(self):
        flat = [mk(i, 100.0, 100.0, pad=0.5) for i in range(30)]
        r = ramp_bars(30)
        # son barin araligini daralt: CLV hala yuksek ama aralik genislemiyor
        r[3] = eng.Bar(r[3].t, 103.2, 104.0, 103.1, 103.9)
        self.assertEqual(side_at("btc_govde_yigini", flat + r, len(flat) + 3), 0)
        # ortadaki barin CLV'si dusuk
        r = ramp_bars(30)
        r[2] = eng.Bar(r[2].t, 101.2, 103.4, 100.9, 101.5)
        self.assertEqual(side_at("btc_govde_yigini", flat + r, len(flat) + 3), 0)

    def test_cooldown_ten_bars(self):
        flat = [mk(i, 100.0, 100.0, pad=0.5) for i in range(30)]
        b = flat + ramp_bars(30)
        # 5. ramp bari: 3 ardisik yukselen (i-1, i, i+1) -> cooldown'da bastirilir
        b.append(eng.Bar(T0 + 34 * TF, 105.7, 109.5, 105.5, 109.2))
        s = series_of("btc_govde_yigini", b)
        sd = STRATS["btc_govde_yigini"]["side"]
        self.assertEqual(sd(s, b, 33), 1)
        self.assertEqual(sd(s, b, 34), 0)
        # 8 dar bar, sonra yeni ramp: son sinyal i=33; yeni sinyal i'=33+11=44 (>10 bar) -> serbest
        k = len(b)
        for j in range(8):
            b.append(mk(k + j, 109.2, 109.2, pad=0.2))
        base = len(b)
        for x in ramp_bars(base):
            b.append(eng.Bar(x.t, x.open + 9.2, x.high + 9.2, x.low + 9.2, x.close + 9.2))
        s = series_of("btc_govde_yigini", b)
        self.assertEqual(sd(s, b, len(b) - 1), 1)  # 10 bar gecmis, tekrar serbest


# ------------------------------------------------------------------ verimlilik rejimi
class VerimlilikTest(unittest.TestCase):
    def _osc(self, n, pad=0.02):
        # 100 / 100.5 salinimi: ER ~ 0 (yatay rejim)
        bars, c = [], 100.0
        for i in range(n):
            o = c
            c = 100.5 if i % 2 == 0 else 100.0
            bars.append(mk(i, o, c, pad=pad))
        return bars

    def test_range_regime_fades_edges(self):
        b = self._osc(60)  # i=58 -> c=100.5 (tepe), i=59 -> 100.0 (asagi)
        s = series_of("btc_verimlilik_rejimi", b)
        self.assertLessEqual(s["er"][59], 0.2)
        self.assertEqual(STRATS["btc_verimlilik_rejimi"]["side"](s, b, 59), -1)  # ustte iken asagi donus -> SELL
        b = self._osc(61)  # i=59 dip, i=60 yukari
        s = series_of("btc_verimlilik_rejimi", b)
        self.assertEqual(STRATS["btc_verimlilik_rejimi"]["side"](s, b, 60), 1)

    def test_trend_regime_pullback_to_ema(self):
        bars, c = [], 100.0
        for i in range(60):
            o = c
            c = o + 0.5
            bars.append(mk(i, o, c, pad=0.05))
        e = wk.ema([x.close for x in bars], 20)[-1]
        t = bars[-1].t + TF
        # fitille EMA20'ye degip (low <= ema) ustunde yesil kapanis: geri cekilme + rejim yonunde kapanis
        lc = bars[-1].close
        x = eng.Bar(t, lc, lc + 0.7, e - 0.1, lc + 0.5)
        b = bars + [x]
        s = series_of("btc_verimlilik_rejimi", b)
        i = len(b) - 1
        self.assertGreaterEqual(s["er"][i], 0.6)
        self.assertEqual(STRATS["btc_verimlilik_rejimi"]["side"](s, b, i), 1)
        # EMA'ya hic degmeyen devam barinda sinyal yok
        y = eng.Bar(t, bars[-1].close, bars[-1].close + 0.6, bars[-1].close - 0.05, bars[-1].close + 0.5)
        self.assertEqual(side_at("btc_verimlilik_rejimi", bars + [y], len(bars)), 0)

    def test_trend_regime_short_mirror(self):
        bars, c = [], 200.0
        for i in range(60):
            o = c
            c = o - 0.5
            bars.append(mk(i, o, c, pad=0.05))
        e = wk.ema([x.close for x in bars], 20)[-1]
        lc = bars[-1].close
        x = eng.Bar(bars[-1].t + TF, lc, e + 0.1, lc - 0.7, lc - 0.5)
        b = bars + [x]
        s = series_of("btc_verimlilik_rejimi", b)
        self.assertEqual(STRATS["btc_verimlilik_rejimi"]["side"](s, b, len(b) - 1), -1)

    def test_middle_regime_no_signal(self):
        # ER ~ 0.4 (0.2 < ER < 0.6): ne trend ne yatay
        rnd = random.Random(5)
        bars, c = [], 100.0
        for i in range(80):
            o = c
            c = o + (0.3 if i % 3 else -0.15) + rnd.uniform(-0.02, 0.02)
            bars.append(mk(i, o, c, pad=0.05))
        s = series_of("btc_verimlilik_rejimi", bars)
        self.assertTrue(0.2 < s["er"][79] < 0.6, s["er"][79])
        self.assertEqual(STRATS["btc_verimlilik_rejimi"]["side"](s, bars, 79), 0)


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


class LookAheadTest(XauLoaderMixin, unittest.TestCase):
    """Kisa seri ile uzun seri (ek gelecek barlar) icin her i'de ayni karar + ayni etkin atr."""

    def _prefix_check(self, name, b, n_cuts=150, xau_full=None):
        """Cok-kesim on-ek kontrolu: ~n_cuts kesim k icin side(series(b[:k+1]), k) == side(series(b), k) ve
        etkin atr[k] esit. 1-bar sizintilar yalniz kesim barinda gorunur, bu yuzden cok sayida kesim gerekir.
        Capraz serili stratejide (xau_full) her kesimde XAU da t <= b[k].t ile kirpilir."""
        sd = STRATS[name]["side"]
        if xau_full is not None:
            self.set_xau(xau_full)
        s_full = series_of(name, b)
        sides = [sd(s_full, b, i) for i in range(len(b))]
        cuts = cut_points(sides, n_cuts)
        self.assertGreaterEqual(len(cuts), min(n_cuts // 2, 30), name)
        for k in cuts:
            if xau_full is not None:
                self.set_xau([r for r in xau_full if r[0] <= b[k].t])
            s_k = series_of(name, b[:k + 1])
            self.assertEqual(sd(s_k, b[:k + 1], k), sides[k], f"{name} on-ek kesim k={k}")
            self.assertEqual(s_k["atr"][k], s_full["atr"][k], f"{name} on-ek atr k={k}")
        if xau_full is not None:
            self.set_xau(xau_full)
        return sum(1 for k in cuts if sides[k] != 0)  # sinyal tasiyan kesim sayisi

    def _check(self, name, seeds=(7, 11), n_long=2400, n_short=1700):
        total_signals = psig = 0
        for seed in seeds:
            long_b = random_walk(n_long, seed)
            psig += self._prefix_check(name, long_b)
            short_b = long_b[:n_short]
            alt_future = random_walk(n_long - n_short, seed + 100)
            alt_future = [eng.Bar(short_b[-1].t + (k + 1) * TF, x.open, x.high, x.low, x.close)
                          for k, x in enumerate(alt_future)]
            for longer in (long_b, short_b + alt_future):
                s_short = series_of(name, short_b)
                s_long = series_of(name, longer)
                sd = STRATS[name]["side"]
                for i in range(len(short_b)):
                    a, c = sd(s_short, short_b, i), sd(s_long, longer, i)
                    self.assertEqual(a, c, f"{name} seed {seed} i={i}")
                    self.assertEqual(s_short["atr"][i], s_long["atr"][i], f"{name} atr i={i}")
                    total_signals += abs(a)
        self.assertGreater(psig, 0, f"{name}: on-ek kontrolu sinyal tasiyan kesim icermiyor")
        return total_signals

    def test_saat_profili(self):
        self.assertGreater(self._check("btc_saat_profili", n_long=3600, n_short=2600), 0)

    def test_likidite_supurme(self):
        self.assertGreater(self._check("btc_likidite_supurme"), 0)

    def test_govde_yigini(self):
        self.assertGreater(self._check("btc_govde_yigini"), 0)

    def test_verimlilik_rejimi(self):
        self.assertGreater(self._check("btc_verimlilik_rejimi"), 0)

    def test_xau_oncu_cross_series_truncation(self):
        """BTC ve XAU gelecegi ayri ayri kesilir/degistirilir: gecmis kararlar degismez."""
        name = "btc_xau_oncu"
        sd = STRATS[name]["side"]
        total = 0
        for seed in (7, 11):
            n_long, n_short = 2400, 1700
            long_b = random_walk(n_long, seed)
            short_b = long_b[:n_short]
            cut_t = short_b[-1].t
            jumps = {k: (0.012 if (k // 90) % 2 else -0.012) for k in range(60, n_long, 90)}
            full = xau_rows(n_long, seed=seed, jumps=jumps)
            # alternatif XAU gelecegi: cut_t sonrasi tamamen farkli
            alt = [r[:] for r in full]
            rnd = random.Random(seed + 5)
            for r in alt:
                if r[0] > cut_t:
                    f = math.exp(rnd.gauss(0, 0.02))
                    r[1], r[2], r[3], r[4] = [v * f for v in r[1:5]]
            xau_short = [r for r in full if r[0] <= cut_t]
            self.assertGreater(self._prefix_check(name, long_b, xau_full=full), 0)
            # referans: hem BTC hem XAU kesik
            self.set_xau(xau_short)
            s_ref = series_of(name, short_b)
            ref = [sd(s_ref, short_b, i) for i in range(len(short_b))]
            total += sum(abs(v) for v in ref)
            variants = [
                ("btc kesik, xau tam", short_b, full),
                ("btc kesik, xau alternatif gelecek", short_b, alt),
                ("btc uzun, xau tam", long_b, full),
                ("btc uzun, xau alternatif gelecek", long_b, alt),
            ]
            for label, bb, xx in variants:
                self.set_xau(xx)
                s_v = series_of(name, bb)
                for i in range(len(short_b)):
                    self.assertEqual(ref[i], sd(s_v, bb, i), f"{label} seed {seed} i={i}")
                    self.assertEqual(s_ref["atr"][i], s_v["atr"][i], f"{label} atr i={i}")
        self.assertGreater(total, 0)


if __name__ == "__main__":
    unittest.main()
