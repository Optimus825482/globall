"""kombo_tarama.py testleri (sentetik barlar).

Calistirma (repo kokunden):  python -m unittest scripts.test_kombo_tarama
"""
import json
import os
import sys
import unittest
from unittest import mock

import numpy as np

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import kombo_tarama as kt  # noqa: E402

T0 = kt.ts_of("2026-07-22")   # egitim penceresi icinde, gun basi
TF = 900


def _doc(n=120, sym="BTCUSD", spread=2.0, slip=1.0, atr=10.0, t0=T0, tf=TF):
    """Duz barlar (100), sabit ATR, sinyalsiz tek strateji 's1'."""
    return {
        "sym": sym, "tf": "m15", "tf_sec": tf, "n": n,
        "t": [t0 + tf * i for i in range(n)],
        "o": [100.0] * n, "h": [100.0] * n, "l": [100.0] * n, "c": [100.0] * n,
        "pip_size": kt.pip_size(sym), "spread_pips": spread, "slip_pips": slip,
        "atr14": [atr] * n, "side": {"s1": [0] * n}, "atr_eff": {}, "hatalar": {},
    }


def _bar(doc, i, o=None, h=None, l=None, c=None):
    for k, v in (("o", o), ("h", h), ("l", l), ("c", c)):
        if v is not None:
            doc[k][i] = float(v)


def _ctx(doc, risk=2.0):
    veri = kt.veri_hazirla(doc)
    return kt.Pencere(veri, doc["t"][0], doc["t"][-1] + TF, "x", risk)


def _sim(doc, sl=1.5, tp=2.0, be=False, risk=2.0, strat="s1"):
    ctx = _ctx(doc, risk)
    k = ctx.nidx[strat]
    sig = ctx.side[k]
    src = np.full(ctx.m, ctx.atr_id[strat], dtype=np.int16)
    return ctx, kt.islemler(ctx, sig, src, sl, tp, be)


class StratejiListesiTest(unittest.TestCase):
    """sinyal_uret varsayilan evreni kombo_* eklenti stratejilerini bilesen olarak almamali."""

    def test_strateji_listesi(self):
        self.assertEqual(kt.strateji_listesi(["ut_bot", "kombo_1", "btc_nr7_kirilim", "kombo_17"]),
                         ["ut_bot", "btc_nr7_kirilim"])

    def test_sinyal_uret_kombo_haric(self):
        import tempfile
        import types
        from unittest import mock
        n = 80
        bars = [[1782079200 + 300 * i, 100.0, 101.0, 99.0, 100.5] for i in range(n)]
        cagrilan = []
        sahte = types.ModuleType("replay_strateji_gunluk")
        sahte._BARS, sahte._SERIES = {}, {}
        sahte.STRATEGIES = {"ut_bot": {}, "kombo_1": {}, "btc_nr7_kirilim": {}, "kombo_2": {}}
        sahte.bars_of = lambda sym, b: b
        sahte.wk = types.SimpleNamespace(atr=lambda b, k: [1.0] * len(b))

        def series_for(sym, strat, b):
            cagrilan.append(strat)
            return {"atr": [1.0] * len(b)}
        sahte.series_for = series_for
        sahte.side_for = lambda strat, s, b, i: 1 if i == 70 else 0
        with tempfile.TemporaryDirectory() as d,                 mock.patch.dict(sys.modules, {"replay_strateji_gunluk": sahte}),                 mock.patch.object(kt, "cache_yukle", lambda sym, tf: {sym: bars}),                 mock.patch.object(kt, "log", lambda msg: None):
            path = kt.sinyal_uret("XAUUSD", "m5", out_dir=d)
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        self.assertEqual(cagrilan, ["ut_bot", "btc_nr7_kirilim"])
        self.assertEqual(sorted(doc["side"]), ["btc_nr7_kirilim", "ut_bot"])
        # acik istek: kombo adi verilirse uretilir (filtre yalniz varsayilan evrende)
        cagrilan.clear()
        with tempfile.TemporaryDirectory() as d,                 mock.patch.dict(sys.modules, {"replay_strateji_gunluk": sahte}),                 mock.patch.object(kt, "cache_yukle", lambda sym, tf: {sym: bars}),                 mock.patch.object(kt, "log", lambda msg: None):
            kt.sinyal_uret("XAUUSD", "m5", stratejiler=["kombo_1"], out_dir=d)
        self.assertEqual(cagrilan, ["kombo_1"])


class IlkIsabetTest(unittest.TestCase):
    def test_kaba_kuvvetle_ayni(self):
        rng = np.random.default_rng(1)
        for m in (1, 2, 7, 64, 333):
            x = rng.normal(size=m)
            lo, hi = kt.seyrek_tablo(x, True), kt.seyrek_tablo(x, False)
            start = rng.integers(0, m + 1, size=200)
            lev = rng.normal(size=200) * 1.5
            got_lo = kt.ilk_isabet(lo, start, lev, True)
            got_hi = kt.ilk_isabet(hi, start, lev, False)
            for s, L, a, b in zip(start, lev, got_lo, got_hi):
                exp_lo = next((j for j in range(s, m) if x[j] <= L), m)
                exp_hi = next((j for j in range(s, m) if x[j] >= L), m)
                self.assertEqual(a, exp_lo)
                self.assertEqual(b, exp_hi)


class SimulatorTest(unittest.TestCase):
    # BTCUSD: pip 1, birim 1 USD; spread 2 (yarim 1), kayma 1; ATR 10; sl 1.5 -> mesafe 15
    # long sinyal i=70 -> giris bar 71 acilis 100 -> dolum 102; SL 87; TP 132; 1R 117
    # lot = floor(20 / 15 / 0.01) * 0.01 = 1.33

    def test_ayni_barda_once_sl(self):
        d = _doc()
        d["side"]["s1"][70] = 1
        _bar(d, 72, h=140, l=80)
        _ctx_, (i, ex, pnl) = _sim(d)
        self.assertEqual(list(i), [70])
        self.assertEqual(list(ex), [72])
        # cikis 87 - 1 (yarim spread) - 1 (kayma) = 85 -> -17 pip
        self.assertAlmostEqual(pnl[0], 1.33 * -17, places=6)

    def test_tp(self):
        d = _doc()
        d["side"]["s1"][70] = 1
        _bar(d, 72, h=140, l=95)
        _c, (i, ex, pnl) = _sim(d)
        self.assertEqual(list(ex), [72])
        # TP 132 - 1 yarim spread = 131 -> +29 pip (TP'de kayma yok)
        self.assertAlmostEqual(pnl[0], 1.33 * 29, places=6)

    def test_short_giris_sonraki_acilis_spread_kayma(self):
        d = _doc()
        d["side"]["s1"][70] = -1
        _bar(d, 71, o=101)           # giris acilisi 101 -> dolum 101 - 1 - 1 = 99
        _c, (i, ex, pnl) = _sim(d)
        # cikis yok -> pencere sonu kapanis 100 + 1 (yarim spread) = 101 -> short: 99 - 101 = -2 pip
        self.assertEqual(list(ex), [d["n"] - 1])
        self.assertAlmostEqual(pnl[0], 1.33 * -2, places=6)

    # short ayna: sinyal i=70 -> giris bar 71 acilis 100 -> dolum 98; SL 113; TP 68; 1R 83
    def test_short_ayni_barda_once_sl(self):
        d = _doc()
        d["side"]["s1"][70] = -1
        _bar(d, 72, h=120, l=60)        # SL ve TP ayni barda -> once SL
        _c, (i, ex, pnl) = _sim(d)
        self.assertEqual(list(ex), [72])
        # cikis 113 + 1 + 1 = 115 -> 98 - 115 = -17 pip
        self.assertAlmostEqual(pnl[0], 1.33 * -17, places=6)

    def test_short_tp(self):
        d = _doc()
        d["side"]["s1"][70] = -1
        _bar(d, 72, h=105, l=60)
        _c, (i, ex, pnl) = _sim(d)
        self.assertEqual(list(ex), [72])
        # TP 68 + 1 (yarim spread) = 69 -> +29 pip
        self.assertAlmostEqual(pnl[0], 1.33 * 29, places=6)

    def test_short_sl_bosluk_acilistan(self):
        d = _doc()
        d["side"]["s1"][70] = -1
        _bar(d, 73, o=130, h=140, l=125, c=135)   # SL 113'un ustunde acilis
        _c, (i, ex, pnl) = _sim(d)
        self.assertEqual(list(ex), [73])
        self.assertAlmostEqual(pnl[0], 1.33 * (98 - (130 + 2)), places=6)

    def test_short_basabas(self):
        d = _doc()
        d["side"]["s1"][70] = -1
        _bar(d, 72, h=105, l=80)          # 1R (83) gorulur, TP (68) / SL (113) yok
        for j in range(73, 80):
            _bar(d, j, o=90, h=90, l=90, c=90)
        _bar(d, 76, o=90, h=99, l=88)     # dolum (98) ustu -> basabas
        _bar(d, 80, o=90, h=95, l=60)     # basabassiz TP burada
        _c, (i, ex, pnl) = _sim(d, be=True)
        self.assertEqual(list(ex), [76])
        self.assertAlmostEqual(pnl[0], 1.33 * (98 - (98 + 2)), places=6)   # -2 pip (maliyet)
        _c, (i, ex, pnl) = _sim(d, be=False)
        self.assertEqual(list(ex), [80])
        self.assertAlmostEqual(pnl[0], 1.33 * 29, places=6)

    def test_short_basabas_bosluk_ve_ayni_bar(self):
        d = _doc()
        d["side"]["s1"][70] = -1
        _bar(d, 72, h=99, l=80)           # 1R ve dolum ustu ayni barda -> henuz etkin degil
        for j in (73, 74):
            _bar(d, j, o=95, h=95, l=95, c=95)
        _bar(d, 75, o=105, h=106, l=104)  # basabas seviyesi (98) ustunde bosluklu acilis
        _c, (i, ex, pnl) = _sim(d, be=True)
        self.assertEqual(list(ex), [75])
        self.assertAlmostEqual(pnl[0], 1.33 * (98 - (105 + 2)), places=6)

    def test_sl_bosluk_acilistan(self):
        d = _doc()
        d["side"]["s1"][70] = 1
        _bar(d, 73, o=70, h=72, l=60, c=65)    # SL 87'nin altinda acilis
        _c, (i, ex, pnl) = _sim(d)
        self.assertEqual(list(ex), [73])
        self.assertAlmostEqual(pnl[0], 1.33 * (70 - 2 - 102), places=6)

    def test_basabas(self):
        d = _doc()
        d["side"]["s1"][70] = 1
        _bar(d, 72, h=120, l=95)        # 1R (117) gorulur, TP (132) yok
        _bar(d, 73, o=110, h=110, l=101)  # dolum (102) altina -> basabas
        _bar(d, 80, h=140, l=99)        # basabassiz TP burada
        _c, (i, ex, pnl) = _sim(d, be=True)
        self.assertEqual(list(ex), [73])
        self.assertAlmostEqual(pnl[0], 1.33 * (102 - 2 - 102), places=6)   # -2 pip (maliyet)
        _c, (i, ex, pnl) = _sim(d, be=False)
        self.assertEqual(list(ex), [80])
        self.assertAlmostEqual(pnl[0], 1.33 * 29, places=6)

    def test_basabas_ayni_barda_etkin_degil(self):
        d = _doc()
        d["side"]["s1"][70] = 1
        _bar(d, 72, h=120, l=101)       # 1R ve dolum altina ayni barda -> stop henuz kaydirilmadi
        for j in (73, 74):
            _bar(d, j, o=105, h=105, l=105, c=105)
        _bar(d, 75, o=105, h=140, l=104)  # TP
        _c, (i, ex, pnl) = _sim(d, be=True)
        self.assertEqual(list(ex), [75])

    def test_tek_pozisyon(self):
        d = _doc()
        for i in (70, 71, 75, 80, 90):
            d["side"]["s1"][i] = 1
        _bar(d, 80, h=140, l=95)        # ilk islem bar 80'de TP
        _c, (i, ex, pnl) = _sim(d)
        # 71, 75 acik pozisyon sirasinda atlanir; 80 (cikis bari kapanisi) yeni islem acabilir
        self.assertEqual(list(i), [70, 80])

    def test_degisken_atr(self):
        d = _doc()
        d["side"]["s1"][70] = 1
        eff = [10.0] * d["n"]
        eff[70] = 20.0                  # sinyal barinda ezilmis ATR -> mesafe 30, SL 72
        d["atr_eff"]["s1"] = eff
        _bar(d, 72, h=101, l=80)        # 87 kirilir ama 72 kirilmaz
        ctx, (i, ex, pnl) = _sim(d)
        self.assertEqual(ctx.atr_id["s1"], 1)
        self.assertEqual(list(ex), [d["n"] - 1])

    def test_atr_yoksa_sinyal_yok_sayilir(self):
        d = _doc()
        d["atr14"][70] = None
        d["side"]["s1"][70] = 1
        d["side"]["s1"][72] = 1
        _c, (i, ex, pnl) = _sim(d)
        self.assertEqual(list(i), [72])


class MetrikTest(unittest.TestCase):
    def test_gunluk_sifirlama_hedef_iflas(self):
        pnl = np.array([300.0, 250.0, -400.0, -350.0, 100.0])
        gun = np.array([1, 1, 2, 2, 3])
        m = kt.metrikler(pnl, gun)
        self.assertEqual(m["hedef_gun"], 1)
        self.assertEqual(m["iflas_gun"], 1)
        self.assertEqual(m["islem_gun"], 3)
        self.assertAlmostEqual(m["net"], -100.0)
        self.assertAlmostEqual(m["pf"], round(650 / 750, 4))
        self.assertAlmostEqual(m["maxdd"], 750.0)
        self.assertAlmostEqual(m["wr"], 0.6)
        self.assertIsNone(m["skor"])          # < 40 islem

    def test_skor(self):
        pnl = np.array([20.0, -10.0] * 30)    # 60 islem, PF 2
        m = kt.metrikler(pnl, np.zeros(60, dtype=int))
        self.assertAlmostEqual(m["skor"], 2.0 * 60 / 80)
        m = kt.metrikler(np.array([20.0, -10.0] * 50), np.zeros(100, dtype=int))
        self.assertAlmostEqual(m["skor"], 2.0)

    def test_gun_cikis_gununden(self):
        d = _doc(n=200, t0=kt.ts_of("2026-07-22") + 86400 - 80 * TF)   # bar 80 = ertesi gun 00:00
        d["side"]["s1"][70] = 1
        _bar(d, 85, h=140, l=95)
        ctx, (i, ex, pnl) = _sim(d)
        self.assertEqual(ctx.gun[ex[0]], (kt.ts_of("2026-07-22") + 86400) // 86400)


class BirlestirmeTest(unittest.TestCase):
    def test_or(self):
        sig, src = kt.kombo_birlestir("or", [0, 1, 0, -1], [1, -1, -1, 1], src_a=3, src_b=5)
        self.assertEqual(list(sig), [1, 1, -1, -1])
        self.assertEqual(list(src), [5, 3, 5, 3])

    def test_and(self):
        sig, _ = kt.kombo_birlestir("and", [1, 0, 1, -1], [1, 1, 0, -1], n=1)
        self.assertEqual(list(sig), [1, 0, 0, -1])
        sig, _ = kt.kombo_birlestir("and", [1, 0, 0, 0, 0], [0, 0, 1, 0, 0], n=3)
        self.assertEqual(list(sig), [0, 0, 1, 0, 0])
        sig, _ = kt.kombo_birlestir("and", [1, 0, 0, 0], [0, 0, 0, 1], n=3)
        self.assertEqual(list(sig), [0, 0, 0, 0])      # pencere [1,3] -> a disarida
        sig, _ = kt.kombo_birlestir("and", [1, 0, 0], [0, 0, -1], n=3)
        self.assertEqual(list(sig), [0, 0, 0])         # zit yon

    def test_and_src_tetikleyen(self):
        sig, src = kt.kombo_birlestir("and", [1, 0, 0], [0, 0, 1], n=3, src_a=1, src_b=2)
        self.assertEqual(list(sig), [0, 0, 1])
        self.assertEqual(src[2], 2)

    def test_sonra(self):
        sig, src = kt.kombo_birlestir("sonra", [1, 0, 0, 0, 0, 0], [0, 0, 0, 1, 1, 0], n=3, src_b=4)
        self.assertEqual(list(sig), [0, 0, 0, 1, 0, 0])
        self.assertEqual(src[3], 4)
        sig, _ = kt.kombo_birlestir("sonra", [0, 1], [0, 1], n=3)
        self.assertEqual(list(sig), [0, 0])            # ayni bar sayilmaz (a once gelmeli)
        sig, _ = kt.kombo_birlestir("sonra", [1, -1, 0], [0, 0, 1], n=3)
        self.assertEqual(list(sig), [0, 0, 0])         # en son a yonu gecerli
        sig, _ = kt.kombo_birlestir("sonra", [1, -1, 0], [0, 0, -1], n=3)
        self.assertEqual(list(sig), [0, 0, -1])

    def test_cikis_varyantlari_tekrarsiz(self):
        v = kt.cikis_varyantlari()
        self.assertEqual(len(v), 4 * 4 * 2 - 4)
        self.assertNotIn((1.5, 1.0, True), v)
        self.assertIn((1.5, 1.0, False), v)
        self.assertIn((1.5, 1.5, True), v)

    def test_basabas_tp1_etkisiz(self):
        d = _doc()
        d["side"]["s1"][70] = 1
        _bar(d, 72, h=118, l=95)
        _bar(d, 73, h=100, l=60)
        _c, r1 = _sim(d, tp=1.0, be=True)
        _c, r2 = _sim(d, tp=1.0, be=False)
        for a, b in zip(r1, r2):
            np.testing.assert_array_equal(a, b)

    def test_tek(self):
        sig, src = kt.kombo_birlestir("tek", [0, 1, -1], src_a=2)
        self.assertEqual(list(sig), [0, 1, -1])
        self.assertEqual(list(src), [2, 2, 2])

    def test_uzay_boyutu(self):
        names = [f"s{k}" for k in range(5)]
        u = kt.asama_a_uzayi(names, and_n=(1, 3), sonra_n=(3,))
        self.assertEqual(len(u), 5 + 10 + 20 + 20)
        self.assertEqual(len({kt.kombo_adi(k) for k in u}), len(u))
        k = u[-1]
        self.assertEqual(set(k), {"tip", "a", "b", "n", "filtre", "sl_atr", "tp_r", "basabas"})


class FiltreTest(unittest.TestCase):
    def test_seans_giris_saati(self):
        t = np.array([T0 + 6 * 3600 + 30 * 60, T0 + 6 * 3600 + 45 * 60, T0 + 19 * 3600 + 45 * 60,
                      T0 + 12 * 3600 + 45 * 60])
        n = len(t)
        m = kt.filtre_maskeleri(t, np.ones(n), np.ones(n), np.ones(n), np.ones(n), np.ones(n), TF)
        self.assertEqual(list(m["seans_07_20"][0]), [False, True, False, True])
        self.assertEqual(list(m["seans_13_20"][0]), [False, False, False, True])
        self.assertEqual(list(m["seans_00_07"][0]), [True, False, False, False])  # 19:45 -> giris 20:00

    def test_htf_ema200(self):
        n = 4 * 300
        t = T0 + TF * np.arange(n)
        c = 100.0 + 0.01 * np.arange(n)
        ema = kt.htf_ema(t, c, TF)
        self.assertTrue(np.isnan(ema[4 * 199 + 2]))     # 200 saat dolmadan
        self.assertFalse(np.isnan(ema[4 * 199 + 3]))    # 200. saat tamamlandi
        m = kt.filtre_maskeleri(t, c, c, c, c, np.ones(n), TF)
        L, S = m["htf_ema200"]
        self.assertFalse(L[100] or S[100])
        self.assertTrue(L[-1])
        self.assertFalse(S[-1])
        # saat ici guncellenmez: saat ortasindaki bar onceki saatin EMA'sini kullanir
        self.assertEqual(ema[4 * 250 + 1], ema[4 * 250 - 1])

    def test_htf_ema_nedensel(self):
        n = 4 * 260
        t = T0 + TF * np.arange(n)
        c = 100.0 + np.sin(np.arange(n) / 7.0)
        e1 = kt.htf_ema(t, c, TF)
        c2 = c.copy()
        c2[900:] += 50
        e2 = kt.htf_ema(t, c2, TF)
        np.testing.assert_array_equal(e1[:900], e2[:900])

    def test_atr_rejim(self):
        up = np.arange(1, 201, dtype=float)
        p = kt.atr_yuzdelik(up)
        self.assertTrue(np.isnan(p[98]))
        self.assertEqual(p[150], 100.0)
        dn = up[::-1].copy()
        self.assertEqual(kt.atr_yuzdelik(dn)[150], 1.0)
        n = 200
        t = T0 + TF * np.arange(n)
        one = np.ones(n)
        m = kt.filtre_maskeleri(t, one, one, one, one, up, TF)
        self.assertTrue(m["atr_yuksek"][0][150] and not m["atr_dusuk"][0][150])
        m = kt.filtre_maskeleri(t, one, one, one, one, dn, TF)
        self.assertTrue(m["atr_dusuk"][0][150] and not m["atr_yuksek"][0][150])

    def test_atr_yuzdelik_nedensel(self):
        rng = np.random.default_rng(5)
        a = rng.uniform(1, 10, 400)
        a[:3] = np.nan
        full = kt.atr_yuzdelik(a)
        for k in (100, 101, 150, 257, 399):
            np.testing.assert_array_equal(kt.atr_yuzdelik(a[:k]), full[:k])
        self.assertGreater(np.nanmax(full), 50)
        self.assertLess(np.nanmin(full), 50)       # dejenere degil

    def test_adx_nedensel(self):
        rng = np.random.default_rng(6)
        c = 100 + np.cumsum(rng.normal(0, 1, 400))
        h, l = c + rng.uniform(0, 1, 400), c - rng.uniform(0, 1, 400)
        full = kt.adx_seri(h, l, c)
        for k in (40, 60, 123, 300, 399):
            np.testing.assert_array_equal(kt.adx_seri(h[:k], l[:k], c[:k]), full[:k])

    def test_filtre_maskeleri_nedensel(self):
        rng = np.random.default_rng(7)
        n = 4 * 260
        t = T0 + TF * np.arange(n)
        c = 100 + np.cumsum(rng.normal(0, 0.3, n))
        o = np.concatenate(([c[0]], c[:-1]))
        h, l = np.maximum(o, c) + 0.1, np.minimum(o, c) - 0.1
        atr = rng.uniform(0.2, 1.0, n)
        full = kt.filtre_maskeleri(t, o, h, l, c, atr, TF)
        # cok sayida kesim noktasi + buyuk yukari/asagi sicrama: esik (20/25, %50) gecisleri
        # yakalanir; bar k ve sonrasi degisir, k'dan onceki maske degerleri ayni kalmali
        for k in range(120, n - 1, 5):
            jump = 30.0 if (k // 5) % 2 else -30.0
            h2, l2, c2, atr2 = h.copy(), l.copy(), c.copy(), atr.copy()
            c2[k:] += jump
            h2[k:] += jump + 1
            l2[k:] += jump - 1
            atr2[k:] *= 9
            part = kt.filtre_maskeleri(t, o, h2, l2, c2, atr2, TF)
            for ad, (L, S) in full.items():
                np.testing.assert_array_equal(part[ad][0][:k], L[:k], err_msg=f"{ad} k={k}")
                np.testing.assert_array_equal(part[ad][1][:k], S[:k], err_msg=f"{ad} k={k}")

    def test_adx(self):
        n = 200
        c = 100.0 + np.arange(n, dtype=float)           # guclu trend
        a = kt.adx_seri(c + 0.5, c - 0.5, c)
        self.assertTrue(np.isnan(a[10]))
        self.assertGreater(a[-1], 25)
        c2 = 100.0 + np.where(np.arange(n) % 2 == 0, 0.5, -0.5)   # yatay testere
        a2 = kt.adx_seri(c2 + 0.6, c2 - 0.6, c2)
        self.assertLess(a2[-1], 20)
        t = T0 + TF * np.arange(n)
        m = kt.filtre_maskeleri(t, c, c + 0.5, c - 0.5, c, np.ones(n), TF)
        self.assertTrue(m["adx_ge20"][0][-1] and m["adx_ge25"][0][-1] and not m["adx_lt20"][0][-1])

    def test_filtre_yonlu(self):
        sig = np.array([1, -1, 1, -1], dtype=np.int8)
        L = np.array([True, True, False, False])
        S = np.array([False, True, True, False])
        self.assertEqual(list(kt.filtre_uygula(sig, (L, S))), [1, -1, 0, 0])


class PencereTest(unittest.TestCase):
    def _veri(self):
        t0 = kt.ts_of(kt.TRAIN[0]) - 200 * TF
        n = int((kt.ts_of(kt.TEST[1]) + 50 * TF - t0) // TF)
        d = _doc(n=n, t0=t0)
        return d, kt.veri_hazirla(d)

    def test_pencere_bolme(self):
        d, veri = self._veri()
        tr0, tr1 = kt.ts_of(kt.TRAIN[0]), kt.ts_of(kt.TRAIN[1])
        p = kt.Pencere(veri, tr0, tr1, "egitim", 2.0)
        self.assertEqual(p.start, kt.PAD)
        self.assertEqual(int(p.t[p.start]), tr0)
        self.assertLess(int(p.t[-1]), tr1)
        self.assertEqual(int(p.t[-1]), tr1 - TF)
        te = kt.Pencere(veri, kt.ts_of(kt.TEST[0]), kt.ts_of(kt.TEST[1]), "test", 2.0)
        self.assertEqual(int(te.t[te.start]), kt.ts_of(kt.TEST[0]))
        self.assertLess(int(te.t[-1]), kt.ts_of(kt.TEST[1]))

    def test_pencere_sonu_zorla_kapanis_ve_pad_islemsiz(self):
        d, _ = self._veri()
        tr0, tr1 = kt.ts_of(kt.TRAIN[0]), kt.ts_of(kt.TRAIN[1])
        k_end = (tr1 - d["t"][0]) // TF          # test penceresinin ilk bari
        d["side"]["s1"][k_end - 10] = 1          # egitimin son barlari
        d["side"]["s1"][(tr0 - d["t"][0]) // TF - 5] = 1   # PAD icinde -> islem yok
        _bar(d, k_end + 5, h=200, l=99)          # TP egitim disinda (testte)
        veri = kt.veri_hazirla(d)
        p = kt.Pencere(veri, tr0, tr1, "egitim", 2.0)
        sig, src = kt.kombo_sinyali(p, kt.kombo("tek", "s1"))
        i, ex, pnl = kt.islemler(p, sig, src, 1.5, 2.0, False)
        self.assertEqual(len(i), 1)
        self.assertEqual(int(p.t[ex[0]]), tr1 - TF)   # pencere sonunda kapandi, test bari kullanilmadi
        self.assertAlmostEqual(pnl[0], 1.33 * (100 - 1 - 102), places=6)


class LotBirimTest(unittest.TestCase):
    def test_birim_deger(self):
        self.assertAlmostEqual(kt.birim_deger("EURUSD"), 10.0)
        self.assertAlmostEqual(kt.birim_deger("XAUUSD"), 10.0)
        self.assertAlmostEqual(kt.birim_deger("BTCUSD"), 1.0)
        self.assertAlmostEqual(kt.birim_deger("USDJPY", 1 / 150.0), 1000.0 / 150.0)
        self.assertAlmostEqual(kt.birim_deger("USDCAD", 1 / 1.4), 10.0 / 1.4)

    def test_kur(self):
        a, b = kt.ts_of(kt.TRAIN[0]), kt.ts_of(kt.TRAIN[1])
        data = {"USDJPY": [[a - 900, 0, 0, 0, 100.0], [a, 0, 0, 0, 150.0], [a + 900, 0, 0, 0, 150.0],
                           [b, 0, 0, 0, 200.0]],
                "USDCHF": [[a, 0, 0, 0, 0.8]], "NZDUSD": [[a, 0, 0, 0, 0.6]]}
        self.assertAlmostEqual(kt.kur_hesapla("USDJPY", a, b, data), 1 / 150.0)
        self.assertAlmostEqual(kt.kur_hesapla("GBPJPY", a, b, data), 1 / 150.0)
        self.assertAlmostEqual(kt.kur_hesapla("USDCHF", a, b, data), 1 / 0.8)
        self.assertAlmostEqual(kt.kur_hesapla("NZDUSD", a, b, data), 1.0)
        self.assertAlmostEqual(kt.kur_hesapla("BTCUSD", a, b, data), 1.0)

    def test_lot(self):
        self.assertAlmostEqual(float(kt.lot_hesapla(50, 25, 10.0)), 0.2)
        self.assertAlmostEqual(float(kt.lot_hesapla(50, 21, 10.0)), 0.23)    # 0.238 -> 0.23
        self.assertAlmostEqual(float(kt.lot_hesapla(1, 1000, 10.0)), 0.01)   # alt sinir
        self.assertAlmostEqual(float(kt.lot_hesapla(1e6, 1, 10.0)), 50.0)    # ust sinir

    def test_pip_maliyet(self):
        self.assertEqual(kt.pip_size("USDJPY"), 0.01)
        self.assertEqual(kt.pip_size("EURUSD"), 0.0001)
        self.assertEqual(kt.maliyet("BTCUSD"), (5.0, 10.0))
        self.assertEqual(kt.maliyet("XAUUSD"), (2.5, 2.0))
        self.assertEqual(kt.maliyet("EURUSD", {"EURUSD": 1.8}), (1.8, 1.0))
        self.assertEqual(kt.risk_varsayilan("EURUSD"), 5.0)
        self.assertEqual(kt.risk_varsayilan("XAUUSD"), 10.0)

    def test_fx_pnl_usd(self):
        # USDJPY: pip 0.01, kur 1/150 -> birim 6.667 USD; risk %5 = 50 USD
        d = _doc(sym="USDJPY", spread=1.0, slip=1.0, atr=0.2)
        d["side"]["s1"][70] = 1
        for k in ("o", "h", "l", "c"):
            d[k] = [150.0] * d["n"]
        _bar(d, 72, h=151, l=149.9)
        veri = kt.veri_hazirla(d)
        ctx = kt.Pencere(veri, d["t"][0], d["t"][-1] + TF, "x", 5.0, kur=1 / 150.0)
        sig, src = kt.kombo_sinyali(ctx, kt.kombo("tek", "s1"))
        i, ex, pnl = kt.islemler(ctx, sig, src, 1.5, 2.0, False)
        # dolum 150 + 0.005 + 0.01 = 150.015; SL mesafe 0.3 = 30 pip; TP 150.615 -> cikis 150.61
        birim = 1000.0 / 150.0
        lot = np.floor(50.0 / (30 * birim) / 0.01 + 1e-9) * 0.01
        self.assertAlmostEqual(pnl[0], lot * (150.61 - 150.015) / 0.01 * birim, places=6)


class WalkForwardTest(unittest.TestCase):
    def _sentetik(self, seed=0, zehir=False):
        rng = np.random.default_rng(seed)
        t0 = kt.ts_of(kt.TRAIN[0]) - 100 * TF
        n = int((kt.ts_of(kt.TEST[1]) - t0) // TF)
        c = 50000.0 + np.cumsum(rng.normal(0, 40, n))
        o = np.concatenate(([c[0]], c[:-1]))
        h = np.maximum(o, c) + rng.uniform(0, 40, n)
        l = np.minimum(o, c) - rng.uniform(0, 40, n)
        sides = {s: np.where(rng.random(n) < 0.02, rng.choice([-1, 1], n), 0) for s in ("a", "b", "c")}
        t = t0 + TF * np.arange(n)
        # degisken ATR (atr_yuksek/atr_dusuk maskeleri dejenere olmasin): yavas dalga + gurultu
        atr_v = 80.0 * (1.0 + 0.6 * np.sin(np.arange(n) / 150.0)) + rng.uniform(0, 20, n)
        if zehir:   # test penceresini tamamen degistir: egitim sonuclari ayni kalmali
            k = int(np.searchsorted(t, kt.ts_of(kt.TEST[0])))
            c[k:] = c[k:] * 3 + rng.normal(0, 500, n - k)
            o[k:], h[k:], l[k:] = c[k:], c[k:] + 300, c[k:] - 300
            atr_v[k:] = rng.uniform(5, 500, n - k)          # ATR yuzdeligi / ADX de degisir
            for s in sides:
                sides[s][k:] = rng.choice([-1, 0, 1], n - k)
        atr = [None] + atr_v[1:].tolist()
        doc = {"sym": "BTCUSD", "tf": "m15", "tf_sec": TF, "n": n, "t": t.tolist(),
               "o": o.tolist(), "h": h.tolist(), "l": l.tolist(), "c": c.tolist(),
               "pip_size": 1.0, "spread_pips": 5.0, "slip_pips": 10.0, "atr14": atr,
               "side": {s: v.tolist() for s, v in sides.items()}, "atr_eff": {}, "hatalar": {}}
        return kt.veri_hazirla(doc)

    def test_siralama_yalniz_egitim_dizileri_alir(self):
        veri = self._sentetik()
        gercek = kt.egitim_sirala
        gorulen = []

        def kayit(ctx, *a, **kw):
            gorulen.append((int(ctx.t.min()), int(ctx.t.max()), ctx.side.shape, ctx.ad))
            return gercek(ctx, *a, **kw)

        with mock.patch.object(kt, "egitim_sirala", side_effect=kayit):
            doc = kt.tara_veri(veri, top_b=3, ilerleme=False)
        self.assertEqual(len(gorulen), 1)
        tmin, tmax, shape, ad = gorulen[0]
        self.assertEqual(ad, "egitim")
        self.assertLess(tmax, kt.ts_of(kt.TEST[0]))
        self.assertLess(tmax, kt.ts_of(kt.TRAIN[1]))
        self.assertGreaterEqual(tmin, kt.ts_of(kt.TRAIN[0]) - kt.PAD * TF)
        self.assertTrue(doc["test_okundu"])
        self.assertTrue(all("test" in r and "train" in r for r in doc["train_top"]))

    def test_test_verisi_degisse_de_egitim_siralamasi_ayni(self):
        d1 = kt.tara_veri(self._sentetik(zehir=False), top_b=8, ilerleme=False)
        d2 = kt.tara_veri(self._sentetik(zehir=True), top_b=8, ilerleme=False)
        self.assertGreater(len(d1["train_top"]), 0)
        self.assertEqual([r["ad"] for r in d1["train_top"]], [r["ad"] for r in d2["train_top"]])
        self.assertEqual([r["train"] for r in d1["train_top"]], [r["train"] for r in d2["train_top"]])
        self.assertNotEqual([r["test"] for r in d1["train_top"]], [r["test"] for r in d2["train_top"]])

    def test_kombo_tanimi_json(self):
        import json
        doc = kt.tara_veri(self._sentetik(), top_b=2, ilerleme=False, max_kombo=60)
        self.assertLessEqual(doc["stage_a"] + doc["stage_b"], 60)
        s = json.dumps(doc)
        k = json.loads(s)["train_top"][0]["kombo"]
        self.assertEqual(set(k), {"tip", "a", "b", "n", "filtre", "sl_atr", "tp_r", "basabas"})
        self.assertIn(k["tip"], ("tek", "or", "and", "sonra"))


if __name__ == "__main__":
    unittest.main()
