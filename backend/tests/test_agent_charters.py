"""AJAN SÖZLEŞMELERİ (AGENT.md deseni) kilitleri (2026-11-10).

Desen: hummingbot/condor `agents/<rol>/AGENT.md` (MIT) — frontmatter'da `when_to_consult`,
gövdede "You handle / You do NOT handle".

Kilitlenen davranış:
  1. Sözleşme adları `llm_skills` seed adlarıyla BİREBİR eşleşir (yönlendirme kopmasın).
  2. Her sözleşmede `when_to_consult` + `not_for` dolu.
  3. `routing_block()` tüm uzmanları listeler; `charter_block()` yalnız seçili olanların
     "YAPMAZ" satırlarını verir.
  4. İstem enjeksiyonu iki prompt kurucusunda da var; **`analyze()` `selected` referansı
     KULLANMAZ** (2026-11-10'da NameError riski böyle düzeltildi — regresyon kilidi).
"""
import ast
import inspect
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import agent_charters  # noqa: E402
from app import llm_analysis  # noqa: E402
from app.database import (DEFAULT_FOREX_MACRO_SKILL_NAME, DEFAULT_MARKET_DATA_SKILL_NAME,  # noqa: E402
                          DEFAULT_RISK_SKILL_NAME, DEFAULT_SCALPER_SKILL_NAME)

SEED_NAMES = {DEFAULT_SCALPER_SKILL_NAME, DEFAULT_FOREX_MACRO_SKILL_NAME,
              DEFAULT_RISK_SKILL_NAME, DEFAULT_MARKET_DATA_SKILL_NAME}


class TestCharters(unittest.TestCase):
    def test_names_match_seed_skills(self):
        names = {c["name"] for c in agent_charters.CHARTERS}
        self.assertEqual(names, SEED_NAMES, "sözleşme adları llm_skills seed adlarıyla eşleşmeli")

    def test_every_charter_has_scope(self):
        for c in agent_charters.CHARTERS:
            self.assertTrue(c.get("when_to_consult", "").strip(), c["name"])
            self.assertTrue(c.get("not_for", "").strip(), c["name"])

    def test_routing_block_lists_all(self):
        block = agent_charters.routing_block()
        for c in agent_charters.CHARTERS:
            self.assertIn(c["name"], block)

    def test_charter_block_filters_by_selection(self):
        only = agent_charters.CHARTERS[0]["name"]
        block = agent_charters.charter_block([only])
        self.assertIn(only, block)
        self.assertIn("YAPMAZ", block)
        others = [c["name"] for c in agent_charters.CHARTERS[1:]]
        for o in others:
            self.assertNotIn(o, block, "seçili olmayan uzman sınıra girmemeli")

    def test_charter_block_empty_selection(self):
        self.assertEqual(agent_charters.charter_block(None), "")
        self.assertEqual(agent_charters.charter_block([]), "")
        self.assertEqual(agent_charters.charter_block(["bilinmeyen uzman"]), "")


class TestInjection(unittest.TestCase):
    def test_chat_injects_charters(self):
        src = inspect.getsource(llm_analysis.chat)
        self.assertIn("agent_charters.routing_block()", src)
        self.assertIn("agent_charters.charter_block(selected)", src)

    def test_analyze_does_not_reference_selected(self):
        src = inspect.getsource(llm_analysis.analyze)
        self.assertNotIn("charter_block(selected)", src,
                         "analyze() içinde `selected` yok — NameError regresyonu")
        self.assertIn("_charter_routing", src)


if __name__ == "__main__":
    unittest.main()

class TestScopeRegression(unittest.TestCase):
    """2026-11-10 CANLI HATA: `_stream_chat_once` içinde `charter_block(selected)` çağrılıyordu
    ama `selected` o kapsamda yoktu → "forex sohbet hatası: name 'selected' is not defined".
    Bu sınıf, aynı sınıf hatayı (kapsam dışı enjeksiyon) AST ile kilitler."""

    def _functions(self):
        src = (ROOT / "app" / "llm_analysis.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            yield fn, (ast.get_source_segment(src, fn) or "")

    def test_charter_block_selected_has_scope(self):
        bad = []
        for fn, body in self._functions():
            if "charter_block(selected)" not in body:
                continue
            args = [a.arg for a in fn.args.args]
            assigned = {t.id for node in ast.walk(fn) if isinstance(node, ast.Assign)
                        for t in node.targets if isinstance(t, ast.Name)}
            if "selected" not in args and "selected" not in assigned:
                bad.append(f"{fn.name}:{fn.lineno}")
        self.assertEqual(bad, [], f"kapsam dışı `selected` kullanımı: {bad}")

    def test_charter_vars_assigned_where_used(self):
        """`_charter_routing` / `_charter_limits` kullanılan her fonksiyonda ATANMIŞ olmalı."""
        bad = []
        for fn, body in self._functions():
            for var in ("_charter_routing", "_charter_limits"):
                if var in body and f"{var} =" not in body:
                    bad.append(f"{fn.name}:{fn.lineno}:{var}")
        self.assertEqual(bad, [], f"atanmadan kullanılan charter değişkeni: {bad}")

