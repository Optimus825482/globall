"""RUTİN KAYIT DEFTERİ kilitleri (2026-11-10).

Desen: hummingbot/condor `routines/base.py` (MIT). Kilitlenen davranış:
  1. Dekoratörle kayıt + keşif (`discover`) idempotent.
  2. `run_once` hatayı YUTAR (süreç ölmez), sonucu `routine_runs`'a yazar.
  3. Vade dolmadan koşmaz (`force=True` ile zorlanır).
  4. `requires_mt5=True` rutin sunucuda ÇALIŞMAZ (MT5 terminali yok) — atlanır, hata değil.
  5. Sunucu rutinleri DB-only olmalı: `db_routines.py` MetaTrader5 import ETMEZ.
  6. Döngü `main.py`'de `_start_background` ile başlatılır.
"""
import ast
import asyncio
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routines import base as rb  # noqa: E402

SRC_MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
SRC_DB_ROUTINES = (ROOT / "app" / "routines" / "db_routines.py").read_text(encoding="utf-8")


class TestRegistry(unittest.TestCase):
    def test_discovery_finds_db_routines(self):
        names = {r.name for r in rb.all_routines()}
        self.assertIn("shadow_snapshot", names)
        self.assertIn("proof_scope_snapshot", names)

    def test_unknown_routine_reports_error(self):
        out = asyncio.run(rb.run_once("does_not_exist", force=True))
        self.assertFalse(out["ok"])
        self.assertIn("rutin yok", out["error"])

    def test_spec_fields(self):
        spec = rb.get("shadow_snapshot")
        self.assertIsNotNone(spec)
        self.assertGreater(spec.interval_sec, 0)
        self.assertFalse(spec.requires_mt5, "DB-only rutin MT5 istemez")


class TestRunSemantics(unittest.TestCase):
    def setUp(self):
        self.saved: list[tuple] = []

        async def fake_save(name, started_ts, duration_ms, ok, result):
            self.saved.append((name, ok, result))

        async def fake_last(_name):
            return 0.0

        self._p1 = mock.patch("app.database.save_routine_run", fake_save)
        self._p2 = mock.patch("app.database.last_routine_run_ts", fake_last)
        self._p1.start()
        self._p2.start()

    def tearDown(self):
        self._p1.stop()
        self._p2.stop()

    def test_error_is_isolated_and_recorded(self):
        async def boom():
            raise RuntimeError("patladı")

        rb._REGISTRY["_test_boom"] = rb.RoutineSpec(name="_test_boom", description="t",
                                                    interval_sec=1, handler=boom)
        try:
            out = asyncio.run(rb.run_once("_test_boom", force=True))
        finally:
            rb._REGISTRY.pop("_test_boom", None)
        self.assertFalse(out["ok"])
        self.assertIn("patladı", out["result"]["error"])
        self.assertEqual(self.saved[-1][0], "_test_boom")
        self.assertFalse(self.saved[-1][1])

    def test_interval_gate_skips(self):
        async def ok_handler():
            return {"ok": True}

        async def recent(_name):
            return 9e12

        rb._REGISTRY["_test_gate"] = rb.RoutineSpec(name="_test_gate", description="t",
                                                    interval_sec=3600, handler=ok_handler)
        try:
            with mock.patch("app.database.last_routine_run_ts", recent):
                out = asyncio.run(rb.run_once("_test_gate", force=False))
        finally:
            rb._REGISTRY.pop("_test_gate", None)
        self.assertTrue(out.get("skipped"), "vade dolmadan koşmamalı")
        self.assertIn("aralık dolmadı", out["error"])

    def test_requires_mt5_skipped_on_server(self):
        async def ok_handler():
            return {"ok": True}

        rb._REGISTRY["_test_mt5"] = rb.RoutineSpec(name="_test_mt5", description="t",
                                                   interval_sec=1, handler=ok_handler,
                                                   requires_mt5=True)
        try:
            with mock.patch.object(rb, "_mt5_available", lambda: False):
                out = asyncio.run(rb.run_once("_test_mt5", force=True))
        finally:
            rb._REGISTRY.pop("_test_mt5", None)
        self.assertTrue(out.get("skipped"))
        self.assertIn("MT5", out["error"])


class TestWiring(unittest.TestCase):
    def test_loop_started_in_main(self):
        self.assertIn("routine_loop", SRC_MAIN)
        self.assertIn('"routine-loop"', SRC_MAIN)

    def test_db_routines_do_not_import_mt5(self):
        tree = ast.parse(SRC_DB_ROUTINES)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertNotIn("MetaTrader5", [a.name for a in node.names],
                                 "sunucu rutini MT5 import etmemeli")
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn("MetaTrader5", node.module)


if __name__ == "__main__":
    unittest.main()
