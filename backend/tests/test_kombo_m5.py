"""Kombo XAU (M5) canlı kolu testleri (2026-10-28).

Çalıştırma:  python -m unittest backend.tests.test_kombo_m5   (repo kökü)
             python -m unittest tests.test_kombo_m5           (backend/)

Parite testi (yük taşıyan): outputs/replay_cache_xaubtc_m5.json varsa ve
scripts/replay_strateji_gunluk import edilebiliyorsa, canlı port replay
`scripts/strategies/kombo.py::kombo_serisi` ile karşılaştırılır; yoksa atlanır.
"""
import importlib.util
import json
import math
import os
import pathlib
import random
import sys
import unittest
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import combo3_m5 as c3  # noqa: E402
from app import kombo_m5 as km  # noqa: E402

REPO = ROOT.parent
SCRIPTS = REPO / "scripts"
CACHE = REPO / "outputs" / "replay_cache_xaubtc_m5.json"
T0 = int(datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc).timestamp())


def rastgele_barlar(n=3000, seed=7, t0=T0, tf=300):
    rnd = random.Random(seed)
    out, c = [], 2000.0
    for i in range(n):
        o = c
        c = max(1.0, o + rnd.gauss(0, 1.2) + 0.15 * math.sin(i / 40.0))
        hi = max(o, c) + abs(rnd.gauss(0, 0.6))
        lo = min(o, c) - abs(rnd.gauss(0, 0.6))
        out.append({"time": t0 + i * tf, "open": o, "high": hi, "low": lo, "close": c})
    return out


def tanim_of(ad):
    return next(k["tanim"] for k in km.DEFAULT_KOMBOLAR if k["ad"] == ad)


# ------------------------------------------------------------------ sabitler / API
class KomboApiTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(km.KOMBO_ENTRY_SOURCE, "kombo_m5")
        self.assertEqual(km.KOMBO_STRATEGY, "KOMBO_M5")
        self.assertEqual(km.KOMBO_COMMENT_PREFIX, "KMB")
        self.assertEqual(km.MIN_BARS, 260)
        self.assertEqual(km.KOMBO_TAGS, {"kombo_1": "KMB1", "kombo_4": "KMB4", "kombo_9": "KMB9"})

    def test_default_kombolar_exact(self):
        beklenen = {
            "kombo_1": {"tip": "sonra", "a": "ut_bot", "b": "combo3", "n": 12, "filtre": ["seans_00_07"],
                        "sl_atr": 3.0, "tp_r": 3.0},
            "kombo_4": {"tip": "or", "a": "hma_ao", "b": "tsi_ema50", "n": None, "filtre": ["seans_13_20"],
                        "sl_atr": 1.5, "tp_r": 2.0},
            "kombo_9": {"tip": "sonra", "a": "btc_keltner_geri_htf", "b": "combo3", "n": 3,
                        "filtre": ["atr_yuksek"], "sl_atr": 2.0, "tp_r": 1.0},
        }
        self.assertEqual([k["ad"] for k in km.DEFAULT_KOMBOLAR], ["kombo_1", "kombo_4", "kombo_9"])
        for k in km.DEFAULT_KOMBOLAR:
            self.assertEqual(k["tanim"], beklenen[k["ad"]])
            self.assertEqual(k["tag"], km.KOMBO_TAGS[k["ad"]])
            self.assertLessEqual(len(k["tag"]), 4)
            km.tanim_dogrula(k["tanim"])

    def test_tanim_dogrula_errors(self):
        ok = dict(tanim_of("kombo_1"))
        km.tanim_dogrula(ok)
        km.tanim_dogrula({"tip": "tek", "a": "hma_ao", "filtre": [], "sl_atr": 1.0, "tp_r": 1.0})
        kotu = [
            {**ok, "tip": "and"},                       # canlıda desteklenmeyen tip
            {**ok, "tip": "xyz"},
            {**ok, "a": "kama_cci"},                    # bilinmeyen bileşen
            {**ok, "b": "nope"},
            {**ok, "b": None},                          # sonra için b gerekli
            {**ok, "n": 0},                             # sonra için n >= 1
            {**ok, "n": None},
            {**ok, "filtre": ["htf_ema200"]},           # canlıda desteklenmeyen filtre
            {**ok, "filtre": ["seans_xx"]},
            {**ok, "sl_atr": 0},
            {**ok, "tp_r": -1},
        ]
        for t in kotu:
            with self.assertRaises(ValueError, msg=str(t)):
                km.tanim_dogrula(t)
        with self.assertRaises(ValueError):
            km.tanim_dogrula("degil-dict")

    def test_sl_tp_arithmetic(self):
        self.assertEqual(km.sl_tp_pips(3.0, 3.0, 2.3456, 0.1), (70.4, 211.2))
        self.assertEqual(km.sl_tp_pips(1.5, 2.0, 1.0, 0.1), (15.0, 30.0))
        self.assertIsNone(km.sl_tp_pips(1.5, 2.0, None, 0.1))
        self.assertIsNone(km.sl_tp_pips(1.5, 2.0, 0.0, 0.1))
        self.assertIsNone(km.sl_tp_pips(1.5, 2.0, -1.0, 0.1))
        self.assertIsNone(km.sl_tp_pips(1.5, 2.0, 1.0, 0.0))

    def test_short_series_returns_empty(self):
        bars = rastgele_barlar(km.MIN_BARS - 1)
        self.assertEqual(km.kombo_entries(bars, 0.1), [])
        self.assertEqual(km.kombo_entries([], 0.1), [])
        self.assertEqual(km.kombo_entries(None, 0.1), [])
        self.assertEqual(km.kombo_entries(rastgele_barlar(400), 0.0), [])


# ------------------------------------------------------------------ filtreler / birleştiriciler
class KomboFiltreTests(unittest.TestCase):
    def test_session_hour_uses_entry_bar_open(self):
        # saat = ((t + 300) // 3600) % 24 ; t = bar açılışı
        def t_at(h, m):
            return int(datetime(2026, 7, 1, h, m, tzinfo=timezone.utc).timestamp())
        self.assertEqual(km.seans_saati(t_at(6, 50)), 6)
        self.assertEqual(km.seans_saati(t_at(6, 55)), 7)   # kapanış 07:00 → giriş 07:00
        self.assertEqual(km.seans_saati(t_at(23, 55)), 0)
        times = [t_at(23, 50), t_at(23, 55), t_at(6, 50), t_at(6, 55), t_at(12, 55), t_at(19, 50), t_at(19, 55)]
        m = km.filtre_maskeleri(times, [None] * len(times), ["seans_00_07", "seans_13_20", "seans_07_20"])
        self.assertEqual(m["seans_00_07"][0], [False, True, True, False, False, False, False])
        self.assertEqual(m["seans_13_20"][0], [False, False, False, False, True, True, False])
        self.assertEqual(m["seans_07_20"][0], [False, False, False, True, True, True, False])

    def test_atr_percentile(self):
        atr = [None] + [float(k) for k in range(1, 150)]
        p = km.atr_yuzdelik(atr)
        self.assertIsNone(p[99])           # pencerede None var
        self.assertEqual(p[100], 100.0)     # artan seri: hep en büyük
        atr2 = [5.0] * 99 + [1.0] + [5.0]
        p2 = km.atr_yuzdelik(atr2)
        self.assertEqual(p2[99], 1.0)       # yalnız kendisi <= cur
        self.assertEqual(p2[100], 100.0)
        m = km.filtre_maskeleri([T0] * len(atr2), atr2, ["atr_yuksek", "atr_dusuk"])
        self.assertFalse(m["atr_yuksek"][0][99])
        self.assertTrue(m["atr_dusuk"][0][99])
        self.assertTrue(m["atr_yuksek"][0][100])
        self.assertFalse(m["atr_dusuk"][0][100])
        self.assertFalse(m["atr_yuksek"][0][50])   # None yüzdelik → filtre geçmez
        # pencere 0..98 + son: <= sayısı * 100 / 100
        atr4 = [float(k) for k in range(99)] + [49.0]    # 0..49 (50) + kendisi → 51
        self.assertEqual(km.atr_yuzdelik(atr4)[99], 51.0)
        atr5 = [float(k) for k in range(99)] + [48.5]    # 0..48 (49) + kendisi → 50: ikisi de geçer
        self.assertEqual(km.atr_yuzdelik(atr5)[99], 50.0)
        m5 = km.filtre_maskeleri([T0] * 100, atr5, ["atr_yuksek", "atr_dusuk"])
        self.assertTrue(m5["atr_yuksek"][0][99] and m5["atr_dusuk"][0][99])

    def test_or_prefers_a(self):
        A, B = [0, 1, 0, -1], [-1, -1, 1, 1]
        self.assertEqual(km.birlestir("or", A, B, None, 0), (-1, "b"))
        self.assertEqual(km.birlestir("or", A, B, None, 1), (1, "a"))
        self.assertEqual(km.birlestir("or", A, B, None, 2), (1, "b"))
        self.assertEqual(km.birlestir("or", A, B, None, 3), (-1, "a"))
        self.assertEqual(km.birlestir("tek", A, None, None, 3), (-1, "a"))

    def test_sonra_window_boundary(self):
        n = 3
        # A son sinyali j=5 (+1); karar barı i
        A = [0] * 20
        A[5] = 1
        B = [0] * 20
        for i in range(6, 12):
            B[i] = 1
        self.assertEqual(km.birlestir("sonra", A, B, n, 8)[0], 1)    # j == i - n → geçer
        self.assertEqual(km.birlestir("sonra", A, B, n, 9)[0], 0)    # j == i - n - 1 → geçmez
        self.assertEqual(km.birlestir("sonra", A, B, n, 6)[0], 1)    # j == i - 1
        B2 = [-x for x in B]
        self.assertEqual(km.birlestir("sonra", A, B2, n, 8)[0], 0)   # ters yön
        # A'nın aynı bardaki sinyali sayılmaz (j < i)
        A3 = [0] * 20
        A3[8] = 1
        self.assertEqual(km.birlestir("sonra", A3, B, n, 8)[0], 0)
        # en son A sinyali ters yöndeyse önceki aynı yönlü sinyal kullanılmaz
        A4 = [0] * 20
        A4[5], A4[6] = 1, -1
        self.assertEqual(km.birlestir("sonra", A4, B, n, 8)[0], 0)
        self.assertEqual(km.birlestir("sonra", A, B, n, 8)[1], "b")

    def test_filtrele(self):
        m = {"f": ([True, False], [False, True])}
        self.assertEqual(km.filtrele(1, m, ["f"], 0), 1)
        self.assertEqual(km.filtrele(1, m, ["f"], 1), 0)
        self.assertEqual(km.filtrele(-1, m, ["f"], 1), -1)
        self.assertEqual(km.filtrele(-1, m, [], 0), -1)


# ------------------------------------------------------------------ göstergeler / yan seriler
class KomboSeriTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = rastgele_barlar(3000)

    def test_combo3_series_matches_combo3_sides_last_bar(self):
        g = km.Gostergeler(self.bars[:400])
        seri = g.yon("combo3")
        for k in (200, 250, 300, 399):
            sides = c3.combo3_sides(self.bars[:k + 1])
            beklenen = next((sides[x] for x in ("ut_bot", "donch_vortex", "vortex_adx") if sides[x]), 0)
            self.assertEqual(seri[k], beklenen, k)
            self.assertEqual(g.yon("ut_bot")[k], sides["ut_bot"], k)

    def test_component_side_zero_before_60(self):
        g = km.Gostergeler(self.bars[:500])
        for comp in km.BILESENLER:
            s = g.yon(comp)
            self.assertEqual(len(s), 500)
            self.assertTrue(all(v == 0 for v in s[:km.SIDE_MIN_I]), comp)
            self.assertTrue(set(s) <= {-1, 0, 1}, comp)

    def test_atr_is_combo3_wilder(self):
        g = km.Gostergeler(self.bars[:300])
        self.assertEqual(g.atr14, c3.atr_wilder(self.bars[:300], 14))

    def test_each_kombo_fires_somewhere(self):
        for k in km.DEFAULT_KOMBOLAR:
            sig, atr = km.kombo_side_series(self.bars, k["tanim"])
            self.assertEqual(len(sig), len(self.bars))
            self.assertEqual(len(atr), len(self.bars))
            self.assertTrue(any(sig), f"{k['ad']} sentetik seride hiç ateşlemedi")

    def test_no_look_ahead(self):
        full = self.bars
        for k in km.DEFAULT_KOMBOLAR:
            sig_full, atr_full = km.kombo_side_series(full, k["tanim"])
            for cut in (700, 1500, 2400):
                sig_cut, atr_cut = km.kombo_side_series(full[:cut], k["tanim"])
                self.assertEqual(sig_cut, sig_full[:cut], (k["ad"], cut))
                self.assertEqual(atr_cut, atr_full[:cut], (k["ad"], cut))

    def test_entries_match_series_and_arithmetic(self):
        bars = self.bars
        found = {k["ad"]: 0 for k in km.DEFAULT_KOMBOLAR}
        series = {k["ad"]: km.kombo_side_series(bars, k["tanim"]) for k in km.DEFAULT_KOMBOLAR}
        for i in range(km.MIN_BARS, len(bars), 1):
            if not any(series[a][0][i] for a in found):
                continue
            win = bars[:i + 1]
            got = {d["ad"]: d for d in km.kombo_entries(win, 0.1)}
            for k in km.DEFAULT_KOMBOLAR:
                s = series[k["ad"]][0][i]
                if not s:
                    self.assertNotIn(k["ad"], got)
                    continue
                d = got[k["ad"]]
                found[k["ad"]] += 1
                atr = series[k["ad"]][1][i]
                self.assertEqual(d["action"], "BUY" if s > 0 else "SELL")
                self.assertEqual(d["tag"], k["tag"])
                self.assertEqual(d["bar_time"], bars[i]["time"])
                self.assertEqual(d["close"], bars[i]["close"])
                self.assertAlmostEqual(d["atr"], atr, places=9)
                sl = round(k["tanim"]["sl_atr"] * atr / 0.1, 1)
                self.assertEqual(d["sl_pips"], sl)
                self.assertEqual(d["tp_pips"], round(sl * k["tanim"]["tp_r"], 1))
                self.assertEqual(d["tanim"], k["tanim"])
            if all(v >= 2 for v in found.values()):
                break
        self.assertTrue(all(v >= 1 for v in found.values()), found)

    def test_sl_atr_override(self):
        bars = self.bars
        sig, _ = km.kombo_side_series(bars, tanim_of("kombo_4"))
        i = next(k for k in range(km.MIN_BARS, len(bars)) if sig[k])
        d = next(x for x in km.kombo_entries(bars[:i + 1], 0.1, sl_atr_override=1.0) if x["ad"] == "kombo_4")
        self.assertEqual(d["sl_pips"], round(1.0 * d["atr"] / 0.1, 1))
        self.assertEqual(d["tp_pips"], round(d["sl_pips"] * 2.0, 1))

    def test_custom_kombolar_param(self):
        bars = self.bars
        tanim = {"tip": "tek", "a": "combo3", "n": None, "filtre": [], "sl_atr": 1.0, "tp_r": 1.0}
        sig, _ = km.kombo_side_series(bars, tanim)
        i = next(k for k in range(km.MIN_BARS, len(bars)) if sig[k])
        out = km.kombo_entries(bars[:i + 1], 0.1, kombolar=[{"ad": "x", "tag": "KMBX", "tanim": tanim}])
        self.assertEqual([d["ad"] for d in out], ["x"])
        with self.assertRaises(ValueError):
            km.kombo_entries(bars[:i + 1], 0.1, kombolar=[{"ad": "y", "tag": "KMBY",
                                                            "tanim": {**tanim, "a": "bilinmez"}}])


# ------------------------------------------------------------------ replay paritesi
def _replay_yukle():
    if not CACHE.exists():
        return None, "replay cache yok: " + str(CACHE)
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    os.environ.setdefault("FOREX_SETTINGS_DISABLE_PERSIST", "1")
    try:
        import replay_strateji_gunluk as mod  # noqa: E402
        spec = importlib.util.spec_from_file_location("kombo_ref_for_m5_parity",
                                                      str(SCRIPTS / "strategies" / "kombo.py"))
        ko = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ko)
    except Exception as exc:  # pragma: no cover - ortam bağımlı
        return None, f"replay import edilemedi: {exc!r}"
    return (mod, ko), None


class KomboReplayParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        got, why = _replay_yukle()
        cls.skip_why = why
        if got is None:
            return
        cls.mod, cls.ko = got
        with open(CACHE, encoding="utf-8") as fh:
            raw = json.load(fh)["XAUUSD"]
        cls.b = cls.mod.bars_of("XAUUSD", raw)
        cls.dict_bars = [{"time": int(x[0]), "open": float(x[1]), "high": float(x[2]), "low": float(x[3]),
                          "close": float(x[4])} for x in raw]
        cls.replay = {}
        for k in km.DEFAULT_KOMBOLAR:
            tanim = {**k["tanim"], "basabas": False}
            cls.replay[k["ad"]] = cls.ko.kombo_serisi(tanim, "m5", cls.b, mod=cls.mod)

    def setUp(self):
        if self.skip_why:
            self.skipTest(self.skip_why)

    def test_full_series_parity(self):
        n = len(self.dict_bars)
        for k in km.DEFAULT_KOMBOLAR:
            ref = self.replay[k["ad"]]
            sig, atr = km.kombo_side_series(self.dict_bars, k["tanim"])
            fark = [i for i in range(km.SIDE_MIN_I, n) if sig[i] != ref["sig"][i]]
            adet = sum(1 for i in range(km.SIDE_MIN_I, n) if ref["sig"][i])
            print(f"\n[PARITE tam] {k['ad']}: bar {n}, replay sinyal {adet}, port sinyal "
                  f"{sum(1 for v in sig if v)}, fark {len(fark)}")
            self.assertEqual(fark, [], f"{k['ad']} ilk farklar {fark[:10]}")
            for i in range(km.SIDE_MIN_I, n):
                if sig[i]:
                    self.assertAlmostEqual(atr[i], ref["atr"][i], places=9)

    def test_windowed_parity(self):
        n = len(self.dict_bars)
        start = max(599, n - 3000)
        idx = list(range(start, n, 7))
        for k in km.DEFAULT_KOMBOLAR:
            self.assertGreaterEqual(len(idx), 1)
        stats = {k["ad"]: {"biri": 0, "fark": 0, "replay": 0, "port": 0} for k in km.DEFAULT_KOMBOLAR}
        for i in idx:
            got = {d["ad"]: d for d in km.kombo_entries(self.dict_bars[i - 599:i + 1], pip_size=0.1)}
            for k in km.DEFAULT_KOMBOLAR:
                ad = k["ad"]
                r = self.replay[ad]["sig"][i]
                d = got.get(ad)
                p = 0 if d is None else (1 if d["action"] == "BUY" else -1)
                st = stats[ad]
                st["replay"] += bool(r)
                st["port"] += bool(p)
                if r or p:
                    st["biri"] += 1
                    if r != p:
                        st["fark"] += 1
                if d is not None and r:
                    self.assertAlmostEqual(d["atr"], self.replay[ad]["atr"][i], places=6)
        print(f"\n[PARITE pencere] karar barı {len(idx)} (son 3000 bar, her 7.), pencere 600 bar")
        for ad, st in stats.items():
            oran = st["fark"] / st["biri"] if st["biri"] else 0.0
            print(f"  {ad}: replay {st['replay']} port {st['port']} birinde {st['biri']} "
                  f"fark {st['fark']} oran {oran:.1%}")
            self.assertLessEqual(oran, 0.05, f"{ad}: {st}")


if __name__ == "__main__":
    unittest.main()
