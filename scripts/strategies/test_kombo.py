"""kombo eklentisi testleri: kombo_tarama ile anlambilim esitligi, etkin ATR, look-ahead, yukleyici.

Calistirma (repo kokunden):  python -m unittest scripts.strategies.test_kombo
"""
import importlib.util
import json
import os
import random
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from unittest import mock

import numpy as np

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import ha_supertrend_mt5_7d as eng  # noqa: E402
import kombo_tarama as kt  # noqa: E402  (referans anlambilim)
import replay_strateji_gunluk as w  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

_spec = importlib.util.spec_from_file_location("kombo_under_test", os.path.join(os.path.dirname(__file__), "kombo.py"))
ko = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ko)

T0 = int(datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc).timestamp())


def rastgele_barlar(n=1500, tf=900, seed=7, t0=T0):
    rnd = random.Random(seed)
    out, c = [], 100.0
    for i in range(n):
        o = c
        c = max(1.0, o + rnd.gauss(0, 0.4) + 0.05 * np.sin(i / 40.0))
        hi = max(o, c) + abs(rnd.gauss(0, 0.2))
        lo = min(o, c) - abs(rnd.gauss(0, 0.2))
        out.append(eng.Bar(t0 + i * tf, o, hi, lo, c))
    return out


def yaz_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def ilk_fark(got, ref):
    """Ilk farkli indeks (yoksa None) — buyuk listelerde unittest diff'i (difflib) cok yavas."""
    if len(got) != len(ref):
        return ("uzunluk", len(got), len(ref))
    for i, (x, y) in enumerate(zip(got, ref)):
        if x != y:
            return (i, x, y)
    return None


def rastgele_yon(n, p, seed):
    rnd = random.Random(seed)
    return [rnd.choice((1, -1)) if rnd.random() < p else 0 for _ in range(n)]


def ref_birlestir(tip, A, B, n):
    """kombo_tarama referansi: (sig, src) — src 1 = a, 2 = b."""
    sig, src = kt.kombo_birlestir(tip, np.array(A), None if B is None else np.array(B), n, 1, 2)
    return sig.tolist(), src.tolist()


class SahteSarmalayici:
    """series_for/side_for/wk/_SERIES/_BARS arayuzlu sahte sarmalayici: bilesenler sabit yon + atr."""

    def __init__(self, yonler: dict, atrlar: dict):
        self.yonler, self.atrlar = yonler, atrlar
        self._SERIES, self._BARS = {}, {}
        self.wk = wk
        self.cagri = []

    def series_for(self, sym, strat, bars):
        self.cagri.append((sym, strat))
        self._SERIES[sym] = {"_strat": strat}
        return {"y": self.yonler[strat], "atr": self.atrlar[strat]}

    def side_for(self, strat, s, b, i):
        return s["y"][i]


class BirlestiriciTest(unittest.TestCase):
    """Bar bazli birlestirici == kombo_tarama.kombo_birlestir (yon ve kaynak)."""

    def test_tum_tipler_rastgele_sinyallerle_esit(self):
        m = 600
        for seed in range(6):
            A = rastgele_yon(m, 0.15, seed)
            B = rastgele_yon(m, 0.2, seed + 100)
            durumlar = [("tek", None)] + [("or", None)] + [("and", n) for n in (1, 3, 6)] + \
                       [("sonra", n) for n in (3, 6, 12)]
            for tip, n in durumlar:
                rs, rsrc = ref_birlestir(tip, A, None if tip == "tek" else B, n)
                for i in range(m):
                    y, k = ko.birlestir(tip, A, None if tip == "tek" else B, n, i)
                    self.assertEqual(y, rs[i], (seed, tip, n, i))
                    if y != 0:
                        self.assertEqual({"a": 1, "b": 2}[k], rsrc[i], (seed, tip, n, i, "src"))

    def test_ornek_durumlar(self):
        A = [0, 1, 0, 0, 0, -1, 0, 0]
        B = [0, -1, 0, 1, 0, 0, -1, 1]
        self.assertEqual(ko.birlestir("or", A, B, None, 1), (1, "a"))       # cakismada a oncelikli
        self.assertEqual(ko.birlestir("or", A, B, None, 3), (1, "b"))
        self.assertEqual(ko.birlestir("sonra", A, B, 3, 3), (1, "b"))       # a@1 in [0,2]
        self.assertEqual(ko.birlestir("sonra", A, B, 1, 3), (0, "b"))       # a@1 < i-n=2
        self.assertEqual(ko.birlestir("sonra", A, B, 3, 6), (-1, "b"))      # en son a@5 = -1
        self.assertEqual(ko.birlestir("sonra", A, B, 3, 7), (0, "b"))       # en son a -1, b +1
        self.assertEqual(ko.birlestir("and", A, B, 3, 3), (1, "b"))         # b@3 +1, a@1 +1 in [1,3]
        self.assertEqual(ko.birlestir("and", A, B, 2, 3), (0, "b"))         # pencere [2,3]
        self.assertEqual(ko.birlestir("and", A, B, 2, 6), (-1, "b"))        # b@6 -1, a@5 -1
        self.assertEqual(ko.birlestir("and", A, B, 1, 1), (0, "b"))         # zit yonler


class FiltreTest(unittest.TestCase):
    def test_maskeler_kombo_tarama_ile_esit(self):
        for tf in (300, 900):
            b = rastgele_barlar(n=4000 if tf == 300 else 1500, tf=tf, seed=tf)
            t = [x.t for x in b]
            o, h, l, c = ([getattr(x, k) for x in b] for k in ("open", "high", "low", "close"))
            atr14 = wk.atr(b, 14)
            ref = kt.filtre_maskeleri(np.array(t), np.array(o), np.array(h), np.array(l), np.array(c),
                                      np.array([np.nan if v is None else v for v in atr14]), tf)
            got = ko.filtre_maskeleri(t, h, l, c, atr14, tf)
            self.assertEqual(set(got), set(ko.FILTRELER))
            for ad in ko.FILTRELER:
                for k in (0, 1):
                    self.assertIsNone(ilk_fark(got[ad][k], list(map(bool, ref[ad][k]))), (tf, ad, k))
                if ad == "htf_ema200":
                    self.assertTrue(any(got[ad][0]) and any(got[ad][1]))   # EMA200 H1 gercekten doldu

    def test_filtre_yonlu_uygulanir(self):
        mask = {"f": ([True, False], [False, True])}
        self.assertEqual(ko.filtrele(1, mask, ["f"], 0), 1)
        self.assertEqual(ko.filtrele(-1, mask, ["f"], 0), 0)
        self.assertEqual(ko.filtrele(1, mask, ["f"], 1), 0)
        self.assertEqual(ko.filtrele(-1, mask, ["f"], 1), -1)


class EtkinAtrTest(unittest.TestCase):
    def _seri(self, tip, n=None, filtre=None):
        m = 200
        A = [0] * 60 + rastgele_yon(m - 60, 0.2, 1)
        B = [0] * 60 + rastgele_yon(m - 60, 0.25, 2)
        atr_a = [10.0 + i for i in range(m)]
        atr_b = [1000.0 + i for i in range(m)]
        mod = SahteSarmalayici({"pa": A, "pb": B}, {"pa": atr_a, "pb": atr_b})
        b = rastgele_barlar(n=m, tf=900)
        tanim = {"tip": tip, "a": "pa", "b": None if tip == "tek" else "pb", "n": n, "filtre": filtre or [],
                 "sl_atr": 1.0, "tp_r": 2.0}
        return ko.kombo_serisi(tanim, "m15", b, mod=mod), A, B, atr_a, atr_b

    def test_atr_tetikleyen_bilesenden(self):
        for tip, n in (("tek", None), ("or", None), ("and", 1), ("and", 3), ("sonra", 6)):
            s, A, B, atr_a, atr_b = self._seri(tip, n)
            rs, rsrc = ref_birlestir(tip, A, None if tip == "tek" else B, n)
            self.assertIsNone(ilk_fark(s["sig"], rs), tip)
            say = 0
            for i, y in enumerate(s["sig"]):
                if y:
                    beklenen = atr_a[i] if rsrc[i] == 1 else atr_b[i]
                    self.assertEqual(s["atr"][i], beklenen, (tip, n, i))
                    say += 1
            self.assertGreater(say, 0, tip)
        s, *_ = self._seri("sonra", 6)
        self.assertTrue(all(s["atr"][i] >= 1000 for i, y in enumerate(s["sig"]) if y))   # sonra -> b

    def test_or_cakisma_a_atr(self):
        s, A, B, atr_a, _ = self._seri("or")
        both = [i for i in range(len(A)) if A[i] and B[i]]
        self.assertTrue(both)
        for i in both:
            self.assertEqual(s["sig"][i], A[i])
            self.assertEqual(s["atr"][i], atr_a[i])

    def test_bilesenler_gercek_sembol_onbellegine_dokunmaz(self):
        s, *_ = self._seri("or")
        self.assertTrue(s["sig"])
        mod = SahteSarmalayici({"pa": [0] * 100, "pb": [0] * 100}, {"pa": [1.0] * 100, "pb": [1.0] * 100})
        mod._SERIES["XAUUSD"] = "dokunma"
        ko.kombo_serisi({"tip": "or", "a": "pa", "b": "pb", "n": None, "filtre": [], "sl_atr": 1, "tp_r": 1},
                        "m15", rastgele_barlar(n=100), mod=mod)
        self.assertEqual(mod._SERIES, {"XAUUSD": "dokunma"})          # gecici anahtarlar silindi
        self.assertEqual([c[0] for c in mod.cagri], ["__kombo__pa", "__kombo__pb"])

    def test_tf_uyusmazligi_hata(self):
        mod = SahteSarmalayici({"pa": [0] * 100}, {"pa": [1.0] * 100})
        with self.assertRaises(ValueError):
            ko.kombo_serisi({"tip": "tek", "a": "pa", "filtre": [], "sl_atr": 1, "tp_r": 1}, "m5",
                            rastgele_barlar(n=100, tf=900), mod=mod)


class GercekSarmalayiciTest(unittest.TestCase):
    """Gercek replay_strateji_gunluk ile (yerlesik bilesenler): kombo_tarama hattina esitlik + look-ahead."""

    TANIMLAR = [
        {"tip": "or", "a": "ut_bot", "b": "vortex_adx", "n": None, "filtre": ["atr_dusuk"], "sl_atr": 1.5, "tp_r": 2.0},
        {"tip": "and", "a": "hma_ao", "b": "combo3", "n": 6, "filtre": [], "sl_atr": 1.5, "tp_r": 2.0},
        {"tip": "sonra", "a": "ut_bot", "b": "combo3", "n": 12, "filtre": ["seans_07_20", "adx_ge20"],
         "sl_atr": 3.0, "tp_r": 3.0},
        {"tip": "tek", "a": "donch_vortex", "b": None, "n": None, "filtre": ["htf_ema200"], "sl_atr": 2.0, "tp_r": 1.0},
    ]

    def setUp(self):
        self._s, self._b = dict(w._SERIES), dict(w._BARS)

    def tearDown(self):
        w._SERIES.clear(); w._SERIES.update(self._s)
        w._BARS.clear(); w._BARS.update(self._b)

    def _referans(self, tanim, b):
        raw = [[x.t, x.open, x.high, x.low, x.close] for x in b]
        yon, atr = {}, {}
        for comp in [tanim["a"]] + ([tanim["b"]] if tanim.get("b") else []):
            w._SERIES.pop("REF", None); w._BARS.pop("REF", None)
            s = w.series_for("REF", comp, raw)
            bb = w.bars_of("REF", raw)
            y = [0] * len(b)
            for i in range(kt.SIDE_MIN_I, len(b)):
                v = w.side_for(comp, s, bb, i)
                y[i] = 1 if v and v > 0 else (-1 if v and v < 0 else 0)
            yon[comp], atr[comp] = np.array(y, dtype=np.int8), s["atr"]
        A = yon[tanim["a"]]
        B = yon[tanim["b"]] if tanim.get("b") else None
        sig, src = kt.kombo_birlestir(tanim["tip"], A, B, tanim.get("n"), 1, 2)
        t = np.array([x.t for x in b]); o, h, l, c = (np.array([getattr(x, k) for x in b]) for k in ("open", "high", "low", "close"))
        a14 = wk.atr(b, 14)
        mask = kt.filtre_maskeleri(t, o, h, l, c, np.array([np.nan if v is None else v for v in a14]), 900)
        for f in tanim["filtre"]:
            sig = kt.filtre_uygula(sig, mask[f])
        return sig.tolist(), src.tolist(), atr

    def test_kombo_tarama_hattina_esit(self):
        b = rastgele_barlar(n=1500, tf=900, seed=11)
        for tanim in self.TANIMLAR:
            s = ko.kombo_serisi(tanim, "m15", b, mod=w)
            ref, src, atr = self._referans(tanim, b)
            self.assertIsNone(ilk_fark(s["sig"], ref), tanim)
            self.assertGreater(sum(1 for v in ref if v), 0, tanim)
            for i, y in enumerate(ref):
                if y:
                    comp = tanim["a"] if src[i] == 1 else tanim["b"]
                    self.assertEqual(s["atr"][i], atr[comp][i])

    def test_look_ahead_yok(self):
        b = rastgele_barlar(n=1500, tf=900, seed=5)
        for tanim in self.TANIMLAR:
            tam = ko.kombo_serisi(tanim, "m15", b, mod=w)
            for k in (900, 1100, 1371):
                kes = ko.kombo_serisi(tanim, "m15", b[:k], mod=w)
                self.assertIsNone(ilk_fark(kes["sig"], tam["sig"][:k]), (tanim["tip"], k))
                self.assertIsNone(ilk_fark(kes["atr"], tam["atr"][:k]), (tanim["tip"], k))

    def test_sarmalayici_uzerinden_series_side_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.json")
            yaz_json(p, [{"ad": "kombo_t1", "sym": "XAUUSD", "tf": "m15", "tanim": self.TANIMLAR[0]}])
            defs = ko.yukle(p)
        saved = dict(w.PLUGINS)
        saved_active = dict(w.ACTIVE)
        try:
            w.PLUGINS["kombo_t1"] = {**w._PLUGIN_DEFAULTS, **defs["kombo_t1"]}
            b = rastgele_barlar(n=1500, tf=900, seed=11)
            raw = [[x.t, x.open, x.high, x.low, x.close] for x in b]
            w._SERIES.pop("XAUUSD", None); w._BARS.pop("XAUUSD", None)
            s = w.series_for("XAUUSD", "kombo_t1", raw)
            self.assertIs(w._SERIES["XAUUSD"], s)          # sembol slotunda kombo serisi (bilesen degil)
            self.assertFalse([k for k in w._SERIES if k.startswith("__kombo__")])
            bb = w.bars_of("XAUUSD", raw)
            ref, _src, _atr = self._referans(self.TANIMLAR[0], b)
            self.assertIsNone(ilk_fark([w.side_for("kombo_t1", s, bb, i) for i in range(len(b))], ref))
            i = next(i for i, v in enumerate(ref) if v and i > 200)
            w.ACTIVE.update({"strategy": "kombo_t1", "sl_atr": 1.5, "tp_r": 2.0})
            cand = w.candidate("XAUUSD", 0, raw, i + 1, {}, 0.01)
            self.assertEqual(cand["action"], "BUY" if ref[i] > 0 else "SELL")
            self.assertAlmostEqual(cand["exits"]["sl_pips"], round(1.5 * s["atr"][i] / 0.01, 1))
            self.assertIsNone(w.candidate("BTCUSD", 0, raw, i + 1, {}, 0.01))   # symbols filtresi
        finally:
            w.PLUGINS.clear(); w.PLUGINS.update(saved)
            w.ACTIVE.clear(); w.ACTIVE.update(saved_active)

    def test_sarmalayici_yoksa_acik_hata(self):
        sahte_main = types.ModuleType("__main__")
        with mock.patch.dict(sys.modules, {"__main__": sahte_main}):
            sys.modules.pop("replay_strateji_gunluk", None)
            with self.assertRaises(RuntimeError):
                ko.sarmalayici()
        self.assertIs(sys.modules["replay_strateji_gunluk"], w)
        self.assertIs(ko.sarmalayici(), w)


class YukleyiciTest(unittest.TestCase):
    TANIM = {"tip": "or", "a": "ut_bot", "b": "btc_saat_profili", "n": None, "filtre": ["atr_dusuk"],
             "sl_atr": 1.5, "tp_r": 2.0, "basabas": True}

    def test_dosya_yoksa_bos(self):
        self.assertEqual(ko.yukle(os.path.join(tempfile.gettempdir(), "yok_kombo_xyz.json")), {})

    def test_kucuk_tanim_dosyasi(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.json")
            yaz_json(p, [{"ad": "kombo_1", "sym": "EURJPY", "tf": "m15", "tanim": self.TANIM},
                         {"ad": "kombo_2", "sym": "XAUUSD", "tf": "m5", "tanim": {**self.TANIM, "sl_atr": 3.0, "tp_r": 1.0}}])
            with mock.patch.dict(os.environ, {"KOMBO_TANIM": p}):
                defs = ko.yukle()
        self.assertEqual(list(defs), ["kombo_1", "kombo_2"])
        d1, d2 = defs["kombo_1"], defs["kombo_2"]
        self.assertEqual((d1["sl_atr"], d1["tp_r"], d1["symbols"], d1["spread_min_mult"]), (1.5, 2.0, {"EURJPY"}, 8.0))
        self.assertEqual((d2["sl_atr"], d2["tp_r"], d2["symbols"], d2["spread_min_mult"]), (3.0, 1.0, {"XAUUSD"}, None))
        self.assertTrue(callable(d1["series"]) and callable(d1["side"]))

    def test_gecersiz_tanim_hata(self):
        for bozuk in ({**self.TANIM, "filtre": ["yok"]}, {**self.TANIM, "tip": "xor"},
                      {**self.TANIM, "tip": "and", "n": None}):
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "t.json")
                yaz_json(p, [{"ad": "kombo_1", "sym": "EURJPY", "tf": "m15", "tanim": bozuk}])
                with self.assertRaises(ValueError):
                    ko.yukle(p)

    def test_tanimlar_olustur_sira_tavan_ve_basabas_birlestirme(self):
        def satir(ad, skor, test_pf, test_n=40, **k):
            kombo = {"tip": "or", "a": "x", "b": ad, "n": None, "filtre": [], "sl_atr": 1.5, "tp_r": 2.0,
                     "basabas": False, **k}
            return {"kombo": kombo, "ad": ad + str(k), "train": {"skor": skor}, "test": {"pf": test_pf, "islem": test_n}}
        secim = {"hucreler": {
            "XAUUSD_m5": {"train_top": [satir("p", 2.0, 1.3), satir("q", 1.9, 1.1), satir("p", 1.5, 1.4, basabas=True)]},
            "EURJPY_m15": {"train_top": [satir("r", 1.95, 1.25), satir("s", 1.0, 2.0, test_n=10), satir("u", 0.5, 1.2)]},
        }}
        liste = ko.tanimlar_olustur(secim)
        self.assertEqual([(k["ad"], k["sym"], k["tanim"]["b"]) for k in liste],
                         [("kombo_1", "XAUUSD", "p"), ("kombo_2", "EURJPY", "r"), ("kombo_3", "EURJPY", "u")])
        self.assertEqual(len(liste[0]["kaynak"]), 2)        # basabas-farkli es satir ayni komboya baglandi
        self.assertEqual(len(ko.tanimlar_olustur(secim, max_kombo=2)), 2)


if __name__ == "__main__":
    unittest.main()
