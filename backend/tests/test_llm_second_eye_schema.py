"""İKİNCİ GÖZ ŞEMA KAPISI kilitleri (2026-11-09) — app/llm_second_eye.py.

Kilitlenen davranış:
  1. Geçerli karar `schema_ok=True` döner, `schema_issues` boştur.
  2. Şema dışı ama kurtarılabilir alanlar (ör. `confidence: "87"`) NORMALİZE
     edilir, `schema_ok=False` + issue listelenir — karar DÜŞÜRÜLMEZ.
  3. `verdict` sözleşmesi üç değerle sınırlı: DEVAM / FAKE / BELIRSIZ.
     Eş anlamlılar hâlâ eşlenir (ONAY→DEVAM), tanınmayan değer None döner.
  4. `regime` yalnız TRENDING/RANGE/PANIC; başka değer None olur.
  5. Eski alanlar KORUNUR (geriye dönük uyumluluk): verdict, confidence,
     bull_thesis, bear_antithesis, regime, suggested_tp_pct, suggested_sl_pct,
     reasons, trap_evidence, summary.
  6. Fazladan alanlar (extra) yok sayılır, çökme yok.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import llm_second_eye as se  # noqa: E402

ESKI_ALANLAR = {
    "verdict", "confidence", "bull_thesis", "bear_antithesis", "regime",
    "suggested_tp_pct", "suggested_sl_pct", "reasons", "trap_evidence", "summary",
}


class TestSchemaGate(unittest.TestCase):
    def test_valid_payload_is_clean(self):
        payload = {
            "verdict": "DEVAM", "confidence": 82, "bull_thesis": "CVD alim baskisi",
            "bear_antithesis": "Direnç yakın", "regime": "TRENDING",
            "suggested_tp_pct": 1.4, "suggested_sl_pct": 0.6,
            "reasons": ["hacim teyidi", "MTF uyum"], "trap_evidence": [],
            "summary": "Kademeli takipçi uygun",
        }
        normalized, ok, issues = se.validate_verdict(payload)
        self.assertTrue(ok)
        self.assertEqual(issues, [])
        self.assertEqual(normalized["verdict"], "DEVAM")
        self.assertEqual(normalized["confidence"], 82)
        self.assertEqual(normalized["regime"], "TRENDING")

    def test_string_confidence_is_coerced(self):
        # Pydantic lax modda "87" → 87 dönüşümü MEŞRU kabul edilir (LLM'den gelen
        # sayısal string bilgi kaybı değildir), bu yüzden schema_ok True kalır.
        payload = {"verdict": "FAKE", "confidence": "87", "reasons": [], "trap_evidence": []}
        normalized, ok, issues = se.validate_verdict(payload)
        self.assertTrue(ok)
        self.assertEqual(issues, [])
        self.assertEqual(normalized["confidence"], 87)

    def test_confidence_out_of_range_is_clamped(self):
        payload = {"verdict": "DEVAM", "confidence": 250}
        normalized, ok, _ = se.validate_verdict(payload)
        self.assertFalse(ok)
        self.assertEqual(normalized["confidence"], 100)

    def test_invalid_verdict_falls_back_to_belirsiz(self):
        payload = {"verdict": "BELKI", "confidence": 50}
        normalized, ok, _ = se.validate_verdict(payload)
        self.assertFalse(ok)
        self.assertEqual(normalized["verdict"], "BELIRSIZ")

    def test_invalid_regime_becomes_none(self):
        payload = {"verdict": "DEVAM", "confidence": 60, "regime": "trendy"}
        normalized, ok, issues = se.validate_verdict(payload)
        self.assertFalse(ok, "regime deseni ihlal edildi → schema_ok False")
        self.assertTrue(issues)
        self.assertIsNone(normalized["regime"], "geçersiz rejim None'a indirilmeli")

    def test_invalid_tp_sl_are_sanitized(self):
        payload = {"verdict": "DEVAM", "confidence": 60,
                   "suggested_tp_pct": "yuksek", "suggested_sl_pct": 999}
        normalized, ok, _ = se.validate_verdict(payload)
        self.assertFalse(ok)
        self.assertIsNone(normalized["suggested_tp_pct"])
        self.assertEqual(normalized["suggested_sl_pct"], 100.0)

    def test_extra_fields_ignored(self):
        payload = {"verdict": "DEVAM", "confidence": 70, "foo": {"bar": 1}}
        normalized, ok, issues = se.validate_verdict(payload)
        self.assertTrue(ok, "fazladan alan şemayı bozmamalı")
        self.assertNotIn("foo", normalized)


class TestParseVerdictContract(unittest.TestCase):
    def _parse(self, text):
        out = se.parse_verdict(text)
        self.assertIsNotNone(out, f"ayrıştırılamadı: {text!r}")
        return out

    def test_old_fields_preserved(self):
        out = self._parse('{"verdict":"DEVAM","confidence":88,"bull_thesis":"güçlü",'
                          '"regime":"TRENDING","reasons":["a","b"],"summary":"ok"}')
        self.assertTrue(ESKI_ALANLAR.issubset(out.keys()), ESKI_ALANLAR - set(out.keys()))
        self.assertEqual(out["verdict"], "DEVAM")
        self.assertEqual(out["confidence"], 88)

    def test_schema_fields_present(self):
        out = self._parse('{"verdict":"FAKE","confidence":71}')
        self.assertIn("schema_ok", out)
        self.assertIn("schema_issues", out)
        self.assertIn("salvaged", out)
        self.assertTrue(out["schema_ok"])
        self.assertEqual(out["schema_issues"], [])

    def test_alias_still_maps_to_devam(self):
        out = self._parse('{"verdict":"GERCEK","confidence":75}')
        self.assertEqual(out["verdict"], "DEVAM")

    def test_salvaged_text_is_flagged(self):
        # JSON gövdesi YOK; yalnız şema tokenı + yüzde var → kurtarma yolu.
        out = self._parse("Karar: FAKE. Guven %64. Sebep: hacim teyidi yok.")
        self.assertEqual(out["verdict"], "FAKE")
        self.assertTrue(out["salvaged"])
        self.assertEqual(out["confidence"], 64)

    def test_unknown_verdict_returns_none(self):
        self.assertIsNone(se.parse_verdict('{"verdict":"MAYBE_SOON","confidence":50}'))

    def test_root_cause_regression_devam_not_in_text(self):
        """Eski tuzak: "devam etmez" gibi küçük harfli metin DEVAM sayılmamalı."""
        self.assertIsNone(se.parse_verdict("Bu sinyal devam etmez, fake olabilir."))


if __name__ == "__main__":
    unittest.main()
