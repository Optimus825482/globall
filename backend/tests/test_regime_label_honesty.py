"""REJİM SINIFLANDIRICI ETİKET DÜRÜSTLÜĞÜ (2026-11-09).

BULGU: `hmm_regime_classifier` GERÇEK bir HMM değil — üç el yazımı eşik skoru
(ADX, vol_ratio, ortalama getiri) normalize edilip "olasılık" diye sunuluyordu.
Panelde "HMM Rejimi (Olasılık %X)" yazması SAHTE KESİNLİKTİ.

ÖLÇÜM (aynı tur): `hmmlearn` (gerçek Gaussian HMM) bariz iki rejimli sentetik
seride 4 farklı kurulumda da ayrıştıramadı → tak-çalıştır değil. Bu yüzden
etiketi düzeltmek, gerçek modeli körlemesine takmaktan doğru olan.

Kilitlenen davranış:
  1. Kullanıcı metni "HMM Rejimi" DEMEZ → "Rejim (eşik tabanlı)".
  2. Sonuç modelinde `method` alanı var ve "heuristic_thresholds".
  3. Gerçek HMM takılmadıkça (hmmlearn importu yokken) etiket iddialı olamaz.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai_trading_suite.hmm_regime_classifier import evaluate_hmm_regime  # noqa: E402

SRC = (ROOT / "app" / "ai_trading_suite" / "hmm_regime_classifier.py").read_text(encoding="utf-8")
CHAT = (ROOT / "app" / "routers" / "forex_chat.py").read_text(encoding="utf-8")


class TestHonestLabel(unittest.TestCase):
    def test_verdict_does_not_claim_hmm(self):
        for vol, adx in ((1.0, 18.0), (4.0, 30.0), (1.5, 22.0)):
            r = evaluate_hmm_regime("XAUUSD", [0.001, -0.002, 0.0015], volatility_ratio=vol, adx=adx)
            self.assertNotIn("HMM", r.verdict, f"metin HMM iddia etmemeli: {r.verdict}")
            self.assertIn("eşik tabanlı", r.verdict)

    def test_method_field_declares_heuristic(self):
        r = evaluate_hmm_regime("XAUUSD", [0.001], volatility_ratio=1.0, adx=20)
        self.assertEqual(r.method, "heuristic_thresholds")

    def test_method_matches_reality(self):
        """Gerçek HMM (hmmlearn) entegre edilmedikçe method 'gaussian_hmm' olamaz."""
        try:
            import hmmlearn  # noqa: F401
            has_lib = True
        except Exception:
            has_lib = False
        r = evaluate_hmm_regime("XAUUSD", [0.001], volatility_ratio=1.0, adx=20)
        if not has_lib:
            self.assertEqual(r.method, "heuristic_thresholds")
        if "import hmmlearn" not in SRC:
            self.assertNotEqual(r.method, "gaussian_hmm", "'HMM' adı ancak gerçek modelle kullanılabilir")

    def test_panel_text_does_not_say_hmm(self):
        self.assertNotIn('f"HMM Rejim=', CHAT)
        self.assertIn("(eşik)", CHAT)


if __name__ == "__main__":
    unittest.main()
