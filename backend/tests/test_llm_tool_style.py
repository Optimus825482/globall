"""LLM ARAÇ ŞEMA STİLİ kilitleri (2026-11-10).

Desen: hummingbot/condor `mcp_servers/TOOL_STYLE.md` (MIT) — "imza = şema".
Kurallar (bizim için uyarlanmış):
  1. Her araç `parameters` şemasında `type: "object"` + `properties` taşır.
  2. `additionalProperties: true` + boş `properties` = doğrulanamaz blob → YASAK.
  3. Araç adı `snake_case`, en az 5 karakter, grep'lenebilir (genel kelime yasak).
  4. Mutasyon fiiliyle başlayan adlar (`place_`, `close_`, `create_` …) `llm_danger`'da
     **READ sınıfına düşemez** — tehlike isimden taşınır.
"""
import ast
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import llm_danger  # noqa: E402

SRC = (ROOT / "app" / "routers" / "llm_chat.py").read_text(encoding="utf-8")
MUTATING_PREFIXES = ("place_", "cancel_", "open_", "close_", "create_", "update_", "remove_",
                     "delete_", "activate_", "deactivate_", "save_", "run_", "modify_", "set_")
GENERIC_NAMES = {"grid", "order", "trade", "run", "do", "exec", "action"}


def _tools() -> list[dict]:
    """Kaynaktaki `{"type":"function","function":{...}}` sözlüklerini AST ile çıkar."""
    out: list[dict] = []
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = []
        for k in node.keys:
            keys.append(k.value if isinstance(k, ast.Constant) and isinstance(k.value, str) else None)
        if "function" not in keys:
            continue
        fn = node.values[keys.index("function")]
        if not isinstance(fn, ast.Dict):
            continue
        fkeys = [k.value if isinstance(k, ast.Constant) else None for k in fn.keys]
        if "name" not in fkeys:
            continue
        name_node = fn.values[fkeys.index("name")]
        if not (isinstance(name_node, ast.Constant) and isinstance(name_node.value, str)):
            continue
        params = None
        if "parameters" in fkeys:
            p = fn.values[fkeys.index("parameters")]
            if isinstance(p, ast.Dict):
                params = p
        out.append({"name": name_node.value, "parameters": params})
    return out


class TestToolSchemas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools = _tools()

    def test_tools_found(self):
        self.assertGreater(len(self.tools), 30, "araç tanımları bulunamadı — parser bozulmuş olabilir")

    def test_name_style(self):
        for t in self.tools:
            n = t["name"]
            self.assertRegex(n, r"^[a-z][a-z0-9_]{4,}$", f"ad snake_case ve ≥5 karakter olmalı: {n}")
            self.assertNotIn(n, GENERIC_NAMES, f"genel/ grep'lenemez ad: {n}")

    def test_parameters_are_typed_objects(self):
        bad = []
        for t in self.tools:
            p = t["parameters"]
            if p is None:
                bad.append((t["name"], "parameters yok"))
                continue
            kv = {k.value: v for k, v in zip(p.keys, p.values)
                  if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            typ = kv.get("type")
            has_type_object = isinstance(typ, ast.Constant) and typ.value == "object"
            if not has_type_object:
                bad.append((t["name"], "type=object değil"))
            if "properties" not in kv:
                bad.append((t["name"], "properties yok"))
        self.assertEqual(bad, [], f"şema ihlalleri: {bad}")

    def test_no_unverifiable_blob(self):
        bad = []
        for t in self.tools:
            p = t["parameters"]
            if p is None:
                continue
            kv = {k.value: v for k, v in zip(p.keys, p.values)
                  if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            ap = kv.get("additionalProperties")
            props = kv.get("properties")
            empty_props = isinstance(props, ast.Dict) and len(props.keys) == 0
            if isinstance(ap, ast.Constant) and ap.value is True and empty_props:
                bad.append(t["name"])
        self.assertEqual(bad, [], f"doğrulanamaz blob (additionalProperties+boş properties): {bad}")

    def test_mutating_tools_are_not_classified_read(self):
        bad = []
        for t in self.tools:
            n = t["name"]
            if n.startswith(MUTATING_PREFIXES):
                if llm_danger.classify(n).tier == llm_danger.READ:
                    bad.append(n)
        self.assertEqual(bad, [], f"mutasyon fiilli araç READ sınıfında: {bad}")


class TestDangerConsistency(unittest.TestCase):
    def test_every_tool_has_a_verdict(self):
        for t in _tools():
            v = llm_danger.classify(t["name"])
            self.assertIn(v.tier, (llm_danger.READ, llm_danger.WRITE, llm_danger.DANGEROUS))

    def test_read_tool_names_are_read_prefixes(self):
        """READ sınıfına düşen her araç okuma önekiyle başlamalı (istisna yok)."""
        bad = [t["name"] for t in _tools()
               if llm_danger.classify(t["name"]).tier == llm_danger.READ
               and not t["name"].startswith(llm_danger.READ_PREFIXES)]
        self.assertEqual(bad, [], f"READ sınıfında ama okuma öneki yok: {bad}")


if __name__ == "__main__":
    unittest.main()
