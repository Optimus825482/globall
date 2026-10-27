"""replay_strateji_gunluk eklenti yukleyici testleri.

Calistirma (repo kokunden):  python -m unittest scripts.strategies.test_loader
"""
import os
import sys
import tempfile
import textwrap
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import replay_strateji_gunluk as w  # noqa: E402

PLUGIN_SRC = textwrap.dedent('''
    STRATEGIES = {
        "%(name)s": {
            "series": lambda b, closes: {"closes": closes},
            "side": lambda s, b, i: 1,
            "sl_atr": %(sl)s, "tp_r": 3.0,
            "symbols": %(symbols)s,
            "spread_min_mult": %(mult)s,
        },
    }
''')


def _bars(n=80):
    return [[1_700_000_000 + 900 * i, 100.0, 101.0, 99.0, 100.0 + (i % 3) * 0.1] for i in range(n)]


class LoaderTest(unittest.TestCase):
    def setUp(self):
        self._saved_plugins = dict(w.PLUGINS)
        self._saved_active = dict(w.ACTIVE)
        self._saved_spread = dict(w._SPREAD_PROFILE)
        self._saved_series, self._saved_bars = dict(w._SERIES), dict(w._BARS)
        w._SERIES.clear()
        w._BARS.clear()
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        w.PLUGINS.clear()
        w.PLUGINS.update(self._saved_plugins)
        w.ACTIVE.clear()
        w.ACTIVE.update(self._saved_active)
        w._SPREAD_PROFILE.clear()
        w._SPREAD_PROFILE.update(self._saved_spread)
        w._SERIES.clear()
        w._SERIES.update(self._saved_series)
        w._BARS.clear()
        w._BARS.update(self._saved_bars)
        self.tmp.cleanup()

    def _write(self, fname, name="t_plug", sl="1.2", symbols="None", mult="None"):
        with open(os.path.join(self.tmp.name, fname), "w", encoding="utf-8") as fh:
            fh.write(PLUGIN_SRC % {"name": name, "sl": sl, "symbols": symbols, "mult": mult})

    def _use(self, name):
        w.ACTIVE.update({"strategy": name, "sl_atr": 1.5, "tp_r": 2.0})

    def test_loads_plugin_and_skips_test_files(self):
        self._write("a_plug.py", name="t_plug")
        self._write("test_skip.py", name="t_skipped")
        got = w.load_plugins(self.tmp.name)
        self.assertIn("t_plug", got)
        self.assertNotIn("t_skipped", got)
        self.assertIs(got, w.PLUGINS)
        p = w.PLUGINS["t_plug"]
        self.assertEqual((p["sl_atr"], p["tp_r"], p["symbols"], p["spread_min_mult"]), (1.2, 3.0, None, None))

    def test_name_collision_between_plugins_exits(self):
        self._write("a.py", name="dup")
        self._write("b.py", name="dup")
        with self.assertRaises(SystemExit) as cm:
            w.load_plugins(self.tmp.name)
        self.assertIn("eklenti ad cakismasi", str(cm.exception))

    def test_name_collision_with_builtin_exits(self):
        self._write("a.py", name="combo3")
        with self.assertRaises(SystemExit) as cm:
            w.load_plugins(self.tmp.name)
        self.assertIn("eklenti ad cakismasi", str(cm.exception))

    def test_real_plugin_dir_loads_and_strategies_tuple(self):
        w.load_plugins()
        self.assertEqual(w.STRATEGIES[:len(w.BUILTIN_STRATEGIES)], w.BUILTIN_STRATEGIES)
        self.assertEqual(len(w.BUILTIN_STRATEGIES), 14)

    def test_series_and_side_use_plugin_and_add_atr(self):
        self._write("a.py", name="t_plug")
        w.load_plugins(self.tmp.name)
        bars = _bars()
        s = w.series_for("XAUUSD", "t_plug", bars)
        self.assertIn("atr", s)
        self.assertIn("closes", s)
        self.assertEqual(w.side_for("t_plug", s, w.bars_of("XAUUSD", bars), 70), 1)

    def test_candidate_symbols_filter(self):
        self._write("a.py", name="t_plug", symbols="{'XAUUSD'}")
        w.load_plugins(self.tmp.name)
        self._use("t_plug")
        bars = _bars()
        self.assertIsNone(w.candidate("EURUSD", 0, bars, 70, {}, 0.0001))
        cand = w.candidate("XAUUSD", 0, bars, 70, {}, 0.01)
        self.assertIsNotNone(cand)
        self.assertEqual(cand["action"], "BUY")
        self.assertEqual(cand["entry_source"], "t_plug")

    def test_candidate_none_symbols_means_all(self):
        self._write("a.py", name="t_plug", symbols="None")
        w.load_plugins(self.tmp.name)
        self._use("t_plug")
        self.assertIsNotNone(w.candidate("EURUSD", 0, _bars(), 70, {}, 0.0001))

    def test_spread_gate_uses_tech_then_profile_then_default(self):
        self._write("a.py", name="t_plug", mult="3.0")
        w.load_plugins(self.tmp.name)
        self._use("t_plug")
        bars = _bars()
        w._SPREAD_PROFILE.clear()
        # pip_size 0.0001 -> sl_pips cok buyuk; kapi yalniz tech spread buyukse kapanir
        self.assertIsNotNone(w.candidate("EURUSD", 0, bars, 70, {"spread_pips": 1.0}, 0.0001))
        sl = w.candidate("EURUSD", 0, bars, 70, {"spread_pips": 1.0}, 0.0001)["exits"]["sl_pips"]
        # tech spread: sl < 3 * spread -> None ; sl >= 3 * spread -> aday
        self.assertIsNone(w.candidate("EURUSD", 0, bars, 70, {"spread_pips": sl / 3.0 + 1.0}, 0.0001))
        self.assertIsNotNone(w.candidate("EURUSD", 0, bars, 70, {"spread_pips": sl / 3.0 - 1.0}, 0.0001))
        # tech yok -> profil
        w._SPREAD_PROFILE["EURUSD"] = sl / 3.0 + 1.0
        self.assertIsNone(w.candidate("EURUSD", 0, bars, 70, {}, 0.0001))
        # tech yok, profil yok -> 1.5 varsayilan
        w._SPREAD_PROFILE.clear()
        self.assertEqual(w.spread_pips_for("EURUSD", {}), 1.5)
        self.assertEqual(w.spread_pips_for("EURUSD", None), 1.5)
        self.assertIsNotNone(w.candidate("EURUSD", 0, bars, 70, {}, 0.0001))
        # kucuk SL (buyuk pip_size) + varsayilan spread 1.5 * 3 = 4.5 pips -> kapi kapanir
        small = w.candidate("EURUSD", 0, bars, 70, {}, 1.0)
        self.assertIsNone(small)

    def test_spread_gate_off_when_mult_none(self):
        self._write("a.py", name="t_plug", mult="None")
        w.load_plugins(self.tmp.name)
        self._use("t_plug")
        self.assertIsNotNone(w.candidate("EURUSD", 0, _bars(), 70, {"spread_pips": 1e9}, 1.0))


if __name__ == "__main__":
    unittest.main()
