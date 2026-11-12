"""MAKRO BAĞLAM + DOĞRULAMA ARTEFAKTI kilidi (2026-11-09).

`cot_positions`, `session_windows`, `edge_validation` modülleri yazılmıştı ama
karar veren yüzeylere BAĞLI DEĞİLDİ (yalnız /api/system/health'te görünüyordu).
Bu test hem hesabı hem BAĞLANTIYI kilitler.

Kilitlenen davranış:
  1. Sembol → para birimi çözümlemesi (CURRENCY_MARKETS değerleri para birimidir;
     USD ayrıca eklenir çünkü TFF raporunda USD'nin kendi satırı yoktur).
  2. COT artefaktı yokken/para birimi bulunamazken "sessiz nötr" YOK:
     "yorum yapılmadı" denir (eksik veriyi nötr sanmak en pahalı hatadır).
  3. Edge doğrulama artefaktı: bölümler birbirini EZMEZ, okuma mtime önbellekli,
     yoksa fail-closed cümle döner.
  4. Bağlantı: işlem dosyası, panel fırsat taraması ve genel sohbet aynı
     `app/context_extras` kaynağını kullanır (tek uygulama kuralı).
"""
import json
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import context_extras as cx  # noqa: E402
from app import edge_validation as ev  # noqa: E402

DOSSIER = (ROOT / "app" / "llm_trade_review.py").read_text(encoding="utf-8")
FOREX_CHAT = (ROOT / "app" / "routers" / "forex_chat.py").read_text(encoding="utf-8")
LLM_CHAT = (ROOT / "app" / "routers" / "llm_chat.py").read_text(encoding="utf-8")


class TestSymbolCurrencies(unittest.TestCase):
    def test_majors(self):
        self.assertEqual(cx.symbol_currencies("EURUSD"), ["EUR", "USD"])
        self.assertEqual(cx.symbol_currencies("GBPJPY"), ["GBP", "JPY"])
        self.assertEqual(cx.symbol_currencies("AUDNZD"), ["AUD"])

    def test_usd_recognised(self):
        # TFF raporunda USD satırı yok ama sembol çözümlemesinde tanınmalı.
        self.assertIn("USD", cx.symbol_currencies("XAUUSD"))
        self.assertIn("USD", cx.symbol_currencies("BTCUSD"))

    def test_non_fx_empty(self):
        self.assertEqual(cx.symbol_currencies("US30"), [])
        self.assertEqual(cx.symbol_currencies("NAS100"), [])

    def test_lowercase_and_separators(self):
        self.assertEqual(cx.symbol_currencies("eur/usd"), ["EUR", "USD"])


class TestSessions(unittest.TestCase):
    def test_block_has_note_and_fields(self):
        b = cx.sessions_block()
        self.assertTrue(b["available"])
        for key in ("label", "liquidity_score", "dead_zone", "market_closed", "note"):
            self.assertIn(key, b)

    def test_note_flags_low_liquidity(self):
        # Hafta sonu/ölü bölge notu veriye bağlı; not her durumda BOŞ olamaz.
        self.assertTrue(cx.sessions_block()["note"].strip())


class TestCotFailClosed(unittest.TestCase):
    def test_missing_artifact_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            missing = pathlib.Path(d) / "yok.json"
            # artefakt yolunu geçici olarak değiştir
            from app import cot_positions
            orig = cot_positions.load_artifact
            cot_positions.load_artifact = lambda *a, **k: None
            cot_positions.reset_cache()
            try:
                b = cx.cot_block("EURUSD")
                self.assertFalse(b["available"])
                self.assertIn("COT", b["reason"])
                lines = [ln for ln in cx.compact_lines("EURUSD") if ln.startswith("COT")]
                self.assertTrue(lines and "indirilmemiş" in lines[0])
            finally:
                cot_positions.load_artifact = orig
                cot_positions.reset_cache()
            self.assertFalse(missing.exists())

    def test_available_artifact_is_honest_about_missing_currency(self):
        """Artefakt varsa ve sembolün para birimi yoksa 'nötr' değil 'yok' denmeli."""
        from app import cot_positions
        orig = cot_positions.summary
        cot_positions.summary = lambda *a, **k: {
            "available": True, "report_date": "2026-11-03", "age_days": 6.0, "stale": False,
            "currencies": {"EUR": {"bias": -0.5, "stance": "SHORT", "crowding_pct": 98.9,
                                   "crowded": True, "lev_net": -100.0, "change_wow_pct": -0.7,
                                   "divergence": False}},
            "unavailable": [],
        }
        try:
            b = cx.cot_block("EURUSD")            # USD satırı artefaktta YOK
            self.assertIn("USD", b["unavailable_for"])
            self.assertIn("USD", b["note"])
            self.assertIn("yorum yapılmadı", b["note"])
            self.assertTrue(b["currencies"]["EUR"]["crowded"])
        finally:
            cot_positions.summary = orig

    def _summary(self, cur, **stats):
        base = {"bias": 0.9, "stance": "LONG", "crowding_pct": 99.0, "crowded": True,
                "lev_net": 100.0, "change_wow_pct": 1.0, "lev_net_pct": 45.0,
                "asset_mgr_net_pct": -20.0}
        base.update(stats)
        return {
            "available": True, "report_date": "2026-11-03", "age_days": 2.0, "stale": False,
            "currencies": {cur: base}, "unavailable": [],
        }

    def test_crowded_and_material_divergence_notes(self):
        from app import cot_positions
        orig = cot_positions.summary
        cot_positions.summary = lambda *a, **k: self._summary("JPY", divergence=True)
        try:
            b = cx.cot_block("GBPJPY")
            self.assertIn("kalabalık LONG", b["note"])
            self.assertIn("ZIT yönde", b["note"], "materyal ayrışma raporda olmalı")
            self.assertIn("+45.0", b["note"], "büyüklük yazılmalı (LLM tartabilsin)")
            self.assertIn("-20.0", b["note"])
        finally:
            cot_positions.summary = orig

    def test_immaterial_divergence_is_not_called_divergence(self):
        """CANLI VAKA (2026-11-09): JPY lev -3.9% vs am +20.9% -> işaretler zıt ama
        lev NÖTR. Eşiksiz sürümde 7 para biriminin 6'sı "ayrışma" diyordu."""
        from app import cot_positions
        orig = cot_positions.summary
        cot_positions.summary = lambda *a, **k: self._summary(
            "JPY", divergence=True, lev_net_pct=-3.9, asset_mgr_net_pct=20.9)
        try:
            b = cx.cot_block("GBPJPY")
            self.assertNotIn("ZIT yönde", b["note"])
            self.assertIn("ayrışma sayılmadı", b["note"])
        finally:
            cot_positions.summary = orig

    def test_materiality_threshold_unit(self):
        from app.cot_positions import is_material_divergence
        self.assertTrue(is_material_divergence({"lev_net_pct": 15.2, "asset_mgr_net_pct": -39.8}))
        self.assertFalse(is_material_divergence({"lev_net_pct": -3.9, "asset_mgr_net_pct": 20.9}))
        self.assertFalse(is_material_divergence({"lev_net_pct": -24.8, "asset_mgr_net_pct": 4.7}))
        self.assertFalse(is_material_divergence({"lev_net_pct": -12.7, "asset_mgr_net_pct": -15.7}))
        self.assertIsNone(is_material_divergence({"lev_net_pct": 20.0, "asset_mgr_net_pct": None}))
        self.assertIsNone(is_material_divergence({}))


class TestEdgeValidationArtifact(unittest.TestCase):
    def _tmp(self):
        return pathlib.Path(tempfile.mkdtemp()) / "edge.json"

    def test_write_merges_sections(self):
        p = self._tmp()
        ev.write_section("significance", {"verdict": "V1", "pvalues": {"spa": 0.4, "n_periods": 750}}, p)
        ev.write_section("cpcv", {"verdict": "V2", "pbo": 0.45, "strategies": [{"name": "c", "psr": 0.86, "dsr": 0.6}]}, p)
        raw = json.loads(p.read_text(encoding="utf-8"))
        self.assertIn("significance", raw)
        self.assertIn("cpcv", raw, "ikinci bölüm birinciyi ezmemeli")

    def test_summary_and_lines(self):
        p = self._tmp()
        ev.write_section("significance", {"verdict": "KENAR YOK", "pvalues": {"spa": 0.394, "n_periods": 750, "size": 0.05},
                                          "mcs_included": ["s1"]}, p)
        s = ev.summary(p)
        self.assertTrue(s["available"])
        self.assertFalse(s["stale"])
        self.assertEqual(s["significance"]["spa_p"], 0.394)
        lines = " ".join(ev.compact_lines(p))
        self.assertIn("KENAR YOK", lines)
        self.assertIn("MCS", lines)

    def test_fail_closed_when_missing(self):
        s = ev.summary(self._tmp())
        self.assertFalse(s["available"])
        lines = ev.compact_lines(self._tmp())
        self.assertTrue(any("KAYIT YOK" in ln for ln in lines))

    def test_stale_flagged(self):
        p = self._tmp()
        ev.write_section("significance", {"verdict": "V", "pvalues": {}}, p)
        raw = json.loads(p.read_text(encoding="utf-8"))
        raw["updated_at"] = time.time() - 40 * 86400        # 40 gün önce
        p.write_text(json.dumps(raw), encoding="utf-8")
        ev.invalidate_cache()
        self.assertTrue(ev.summary(p)["stale"])
        self.assertTrue(any("ESKİMİŞ" in ln for ln in ev.compact_lines(p)))

    def test_cache_invalidated_on_write(self):
        p = self._tmp()
        ev.write_section("significance", {"verdict": "A", "pvalues": {}}, p)
        self.assertEqual(ev.summary(p)["significance"]["verdict"], "A")
        time.sleep(0.01)
        ev.write_section("significance", {"verdict": "B", "pvalues": {}}, p)
        self.assertEqual(ev.summary(p)["significance"]["verdict"], "B")


class TestWiring(unittest.TestCase):
    """Tek uygulama kuralı: üç LLM yüzeyi de context_extras'ı kullanır."""

    def test_trade_dossier_has_macro_block(self):
        self.assertIn("from app import context_extras", DOSSIER)
        self.assertIn('"makro_baglam": macro', DOSSIER)

    def test_panel_opportunity_scan_context(self):
        self.assertIn("from app import context_extras", FOREX_CHAT)
        self.assertIn('ctx["makro_ozet"] = context_extras.compact_lines(focus)', FOREX_CHAT)

    def test_general_chat_context(self):
        self.assertIn("context_extras.macro_context(_focus_sym)", LLM_CHAT)
        self.assertIn("context_extras.macro_context(symbol)", LLM_CHAT)

    def test_empty_research_still_warns_with_macro_present(self):
        """Makro bağlam her yanıtta eklenir; 'araştırma boş' uyarısı SAYIYA değil
        araştırma adımlarının varlığına bakmalı (2026-11-09 regresyonu)."""
        from app.routers import forex_chat
        self.assertIn("uyari", forex_chat.build_context({}))
        ctx = forex_chat.build_context({"ta:XAUUSD": {"yon": "SELL"}})
        self.assertNotIn("uyari", ctx)
        self.assertIn("makro_baglam", ctx)

    def test_macro_context_shape(self):
        # kuresel_varlik_nabzi (2026-11-09) AĞA çıkmaması için mock'lu: shape
        # testi kaynak dizisini değil SÖZLEŞMEYI kilitler.
        with mock.patch("app.market_pulse.summary",
                        return_value={"available": False, "reason": "test"}):
            ctx = cx.macro_context("EURUSD")
        self.assertEqual(set(ctx), {"seans_ve_likidite", "cot_pozisyonlanma",
                                    "istatistiksel_dogrulama", "kuresel_varlik_nabzi",
                                    "perakende_konumlanma"})


if __name__ == "__main__":
    unittest.main()
