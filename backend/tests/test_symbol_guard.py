"""SEMBOL KORUMASI (kara liste) kilitleri (2026-11-09 → 2026-11-10 güncellendi).

Gerekçe (ölçüldü):
  * AUD kümesi (2026-11-09, 276 işlem/7 gün): n=19, ortalama **−6.11 USD**, **t=−4.12**.
  * **2026-11-10 EKLEME — iki bağımsız kaynak örtüşüyor:**
    - gerçek broker defteri 60 gün / 4315 işlem: USDJPY −0.402R (−2401 USD, isabet %36.8),
      EURJPY −0.474R, GBPJPY −0.269R, USDCHF −0.246R, GBPUSD −0.089R; hepsi pencerenin
      İKİ YARISINDA da negatif (n≥30).
    - replay A/B 30 gün: bu semboller çıkarılınca net −111.156 → **+66.075 USD**, PF 0.70 → 1.50,
      maxDD 113.204 → 8.894 USD.
    - mekanizma: ölçülen maliyet/stop oranı bu paritelerde 0.079-0.146R, kalan sette 0.025-0.038R.

Kilitlenen davranış:
  1. Varsayılan kara liste = AUD kümesi + 2026-11-10 ölçüm kümesi (ayardan değiştirilebilir).
  2. Koruması `continue` ile işlemi AÇMAZ ve **risk kapısından ÖNCE** çalışır.
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

#: 2026-11-10 ölçümüyle eklenen pariteler (gerçek defter + replay örtüşmesi).
MEASURED_2026_11_10 = ["EURJPY", "GBPJPY", "GBPUSD", "USDCHF", "USDJPY"]


class TestDefaults(unittest.TestCase):
    def test_default_blocked_symbols(self):
        m = ForexAutoPaperSettings()
        self.assertEqual(sorted(m.blocked_symbols),
                         ["AUDCAD", "AUDNZD", "AUDUSD"] + MEASURED_2026_11_10)

    def test_measured_set_not_dropped_silently(self):
        """Ölçümle eklenen pariteler sessizce listeden düşmemeli (regresyon kilidi)."""
        blocked = {s.upper() for s in ForexAutoPaperSettings().blocked_symbols}
        for sym in MEASURED_2026_11_10:
            self.assertIn(sym, blocked, f"{sym} ölçümle eklendi; listeden çıkarıldıysa kanıt gerekir")

    def test_description_carries_evidence_and_caveat(self):
        desc = ForexAutoPaperSettings.model_fields["blocked_symbols"].description
        self.assertIn("t=-4.12", desc, "AUD ölçüm kanıtı korunmalı")
        self.assertIn("-0.402R", desc, "2026-11-10 gerçek defter kanıtı açıklamada olmalı")
        self.assertIn("66.075", desc, "replay A/B kanıtı açıklamada olmalı")
        self.assertIn("LİSTEYE ALINMADI", desc, "XAU/BTC'nin neden listede olmadığı yazılmalı")

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
