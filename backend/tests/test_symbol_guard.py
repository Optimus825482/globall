"""SEMBOL KORUMASI (kara liste) kilitleri (2026-11-09).

Gerekçe (ölçüldü, 276 işlem/7 gün): AUD kümesi n=19, ortalama **−6.11 USD**,
**t=−4.12** (%95 anlamlı), toplam −116 USD. AUDCAD 0/5, AUDUSD 2/7, AUDNZD 1/7.

Kilitlenen davranış:
  1. Varsayılan kara liste = AUD kümesi (ayardan görülebilir/değiştirilebilir).
  2. Koruması `continue` ile işlemi AÇMAZ ve **risk kapısından ÖNCE** çalışır
     (boşa LLM çağrısı/gecikme olmasın).
  3. Karşılaştırma BÜYÜK HARF (küçük harfli giriş de yakalanır).
  4. Liste boşaltılırsa koruma tamamen kapanır (aşırı uyum riskine karşı geri alınabilir).
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers.forex import ForexAutoPaperSettings  # noqa: E402

SRC = (ROOT / "app" / "routers" / "forex.py").read_text(encoding="utf-8")


class TestDefaults(unittest.TestCase):
    def test_default_blocked_symbols(self):
        m = ForexAutoPaperSettings()
        self.assertEqual(sorted(m.blocked_symbols), ["AUDCAD", "AUDNZD", "AUDUSD"])

    def test_description_carries_evidence_and_caveat(self):
        desc = ForexAutoPaperSettings.model_fields["blocked_symbols"].description
        self.assertIn("t=-4.12", desc)
        self.assertIn("aşırı uyum", desc, "7 günlük veri uyarısı açıklamada olmalı")

    def test_empty_list_disables_guard(self):
        m = ForexAutoPaperSettings(blocked_symbols=[])
        self.assertEqual(m.blocked_symbols, [])


class TestWiring(unittest.TestCase):
    def test_guard_precedes_risk_gate(self):
        i_guard = SRC.index("8b1. SEMBOL KORUMASI")
        i_risk = SRC.index("8b2. Portföy risk kapısı")
        self.assertLess(i_guard, i_risk, "sembol koruması risk kapısından ÖNCE olmalı")

    def test_guard_continues_loop(self):
        i = SRC.index("8b1. SEMBOL KORUMASI")
        block = SRC[i:i + 2500]
        self.assertIn("_AUTO_SETTINGS.blocked_symbols", block)
        self.assertIn("continue", block, "engellenen sembol için döngü devam etmeli (işlem açılmaz)")

    def test_uppercase_normalisation(self):
        i = SRC.index("_blocked_syms =")
        line = SRC[i:i + 200]
        self.assertIn(".upper()", line)


if __name__ == "__main__":
    unittest.main()
