"""LLM TEHLİKE KAPISI kilitleri (2026-11-10).

Desen: Condor `condor/runtime/danger.py` (MIT) — tehlike **İSİMDEN** sınıflandırılır,
bilinmeyen araç fail-closed (WRITE + onay), gerçek para/canlı işlem araçları LLM yolundan
çalışmaz. Bu dosya hem sınıflandırmayı hem de **kapının dispatch'e gerçekten bağlandığını**
kilitler.

Kilitlenen davranış:
  1. Okuma araçları (`get_*`, `list_*` …) → READ, onay istemez.
  2. Paper emir / alarm / coin aktivasyonu → WRITE, onay ister (para hareketi yok).
  3. Canlı emir/kapatma/kaldıraç/ayar araçları → DANGEROUS; `gate()` RED döner.
  4. Bilinmeyen ad → WRITE + onay (fail-closed) — sessizce geçmez.
  5. Kapı `_dispatch_tool`'un EN BAŞINDA; ilk araç dalından önce.
  6. `llm_danger` **stdlib-only** (app importu yok → döngüsel bağımlılık riski yok).
"""
import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import llm_danger  # noqa: E402

SRC_CHAT = (ROOT / "app" / "routers" / "llm_chat.py").read_text(encoding="utf-8")
SRC_DANGER = (ROOT / "app" / "llm_danger.py").read_text(encoding="utf-8")


class TestClassify(unittest.TestCase):
    def test_read_tools(self):
        for name in ("get_trades", "list_market_alerts", "search_memory", "read_only_sql",
                     "validate_trade_plan", "calculate_trade_economics", "scan_market_snapshots"):
            v = llm_danger.classify(name)
            self.assertEqual(v.tier, llm_danger.READ, name)
            self.assertFalse(v.requires_confirm, name)
            self.assertIsNone(llm_danger.gate(name), f"{name} LLM yolundan geçmeli")

    def test_paper_and_config_are_write(self):
        for name in ("place_paper_order", "cancel_paper_order", "create_market_alert",
                     "activate_coin", "save_research_pattern"):
            v = llm_danger.classify(name)
            self.assertEqual(v.tier, llm_danger.WRITE, name)
            self.assertTrue(v.requires_confirm, name)
            self.assertIsNone(llm_danger.gate(name), "WRITE araçlar panel/denetimle çalışabilir")

    def test_live_money_tools_are_blocked(self):
        for name in ("place_order", "close_position", "close_all_positions", "set_leverage",
                     "update_auto_settings", "mt5_close"):
            v = llm_danger.classify(name)
            self.assertEqual(v.tier, llm_danger.DANGEROUS, name)
            blocked = llm_danger.gate(name)
            self.assertIsNotNone(blocked, f"{name} LLM yolunda ÇALIŞMAMALI")
            self.assertEqual(blocked["error"], "danger_blocked")

    def test_token_based_catch(self):
        """Listede olmasa da isim parçası yakalar (ör. 'place_live_order_now')."""
        for name in ("place_live_order_now", "mt5_order_send", "real_order"):
            self.assertTrue(llm_danger.classify(name).blocked_in_llm, name)

    def test_unknown_fail_closed(self):
        v = llm_danger.classify("frobnicate_everything")
        self.assertEqual(v.tier, llm_danger.WRITE)
        self.assertTrue(v.requires_confirm)
        self.assertIn("fail-closed", v.reason)

    def test_empty_name_is_dangerous(self):
        self.assertTrue(llm_danger.classify("").blocked_in_llm)
        self.assertTrue(llm_danger.classify(None).blocked_in_llm)


class TestSummarize(unittest.TestCase):
    def test_redacts_secrets(self):
        s = llm_danger.summarize("place_paper_order", {"symbol": "BTCUSDT", "api_key": "abc123",
                                                       "note": "x" * 60})
        self.assertIn("symbol=BTCUSDT", s)
        self.assertIn("api_key=***", s)
        self.assertNotIn("abc123", s, "gizli değer özete sızmamalı")
        self.assertIn("…", s, "uzun değer kısaltılmalı")

    def test_empty_args(self):
        self.assertEqual(llm_danger.summarize("get_trades", {}), "get_trades")


class TestWiring(unittest.TestCase):
    def test_gate_is_first_thing_in_dispatch(self):
        i_disp = SRC_CHAT.index("async def _dispatch_tool(name, args):")
        i_gate = SRC_CHAT.index("llm_danger.gate(name)", i_disp)
        i_first_branch = SRC_CHAT.index('if name == "run_ai_trading_suite_evaluation":', i_disp)
        self.assertLess(i_gate, i_first_branch, "kapı ilk araç dalından ÖNCE olmalı")

    def test_blocked_call_is_logged(self):
        i_disp = SRC_CHAT.index("async def _dispatch_tool(name, args):")
        block = SRC_CHAT[i_disp:i_disp + 1600]
        self.assertIn("save_llm_tool_log", block, "engellenen çağrı günlüğe yazılmalı")
        self.assertIn("danger_blocked", block)

    def test_danger_module_is_stdlib_only(self):
        tree = ast.parse(SRC_DANGER)
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        self.assertEqual(mods - {"__future__", "dataclasses", "typing"}, set(),
                         f"llm_danger app modülü import etmemeli: {mods}")


if __name__ == "__main__":
    unittest.main()
