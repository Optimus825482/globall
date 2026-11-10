"""KANIT KAPSAMI (proof scope) kilitleri (2026-11-10).

NEDEN
-----
Ölçüm zinciri (canlı defter + replay + MFE/ulaşma analizi) şunu gösterdi: sistemin
**pozitif kenarı yalnız üç sembol-kanalında** kanıtlı; geri kalan kümeler negatif
beklentiyle işlem görüyordu ve hiçbir çıkış/hedef/seçicilik ayarı onları kurtarmadı.

Kanıt (canlı defter, 10-29 sonrası, trend/kanal ayrımı yapılmış):
  USTEC×RADAR +0.198R (t=5.28, isabet %95.7) · XAUUSD×RADAR +0.223R (t=2.72)
  US30×RADAR +0.117R (t=2.74) · BTCUSD -0.024R (t=-0.53) = NÖTR → gözlemde tutuldu.
  Kapalı kalanlar: FX majörleri/çaprazlar (RADAR dahil negatif), FRS/LBRK kolları.

Kilitlenen davranış:
  1. Varsayılan: kapsam AÇIK; sembol listesi = kanıtlı üçlü + BTCUSD.
  2. Kapı, sembol korumasından (blocked_symbols) SONRA, kanıt kapısından ÖNCE çalışır.
  3. **Zaman tabanlı kol muaftır** (`soft_bypass`) — Tokyo pencereleri GBPUSD/EURUSD/USDJPY'de
     çalışmaya devam eder.
  4. `proof_scope_enabled=False` kapıyı tamamen kaldırır (geri alınabilir).
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
    def test_scope_enabled_with_proven_symbols(self):
        m = ForexAutoPaperSettings()
        self.assertTrue(m.proof_scope_enabled)
        self.assertEqual(sorted(m.proof_scope_symbols),
                         ["BTCUSD", "NAS100", "US30", "USTEC", "XAUUSD"])

    def test_unproven_symbols_not_in_scope(self):
        m = ForexAutoPaperSettings()
        scope = {s.upper() for s in m.proof_scope_symbols}
        for sym in ("EURUSD", "USDJPY", "GBPUSD", "USDCHF", "USDCAD", "EURJPY", "AUDJPY"):
            self.assertNotIn(sym, scope, f"{sym} kanıtlanmış pozitif kenar listesinde değil")

    def test_description_carries_evidence(self):
        desc = ForexAutoPaperSettings.model_fields["proof_scope_enabled"].description
        for token in ("+0.198R", "t=5.28", "AUC 0.59"):
            self.assertIn(token, desc, f"{token} kanıtı açıklamada olmalı")

    def test_disable_flag_reverts(self):
        m = ForexAutoPaperSettings(proof_scope_enabled=False)
        self.assertFalse(m.proof_scope_enabled)


class TestWiring(unittest.TestCase):
    def test_gate_order(self):
        i_block = SRC.index("8b1. SEMBOL KORUMASI")
        i_scope = SRC.index("8b1c. KANIT KAPSAMI")
        i_abst = SRC.index("8b1b. KANIT KAPISI")
        self.assertLess(i_block, i_scope, "sembol koruması kanıt kapsamından ÖNCE")
        self.assertLess(i_scope, i_abst, "kanıt kapsamı kanıt kapısından ÖNCE")

    def test_scope_exempts_time_based_arm(self):
        i = SRC.index("8b1c. KANIT KAPSAMI")
        block = SRC[i:i + 1800]
        self.assertIn("_soft_bypass", block, "zaman tabanlı kol kapsamdan muaf olmalı")
        self.assertIn("continue", block)

    def test_scope_reads_settings_symbols(self):
        i = SRC.index("8b1c. KANIT KAPSAMI")
        block = SRC[i:i + 1800]
        self.assertIn("_AUTO_SETTINGS.proof_scope_symbols", block)
        self.assertIn("_AUTO_SETTINGS.proof_scope_enabled", block)


if __name__ == "__main__":
    unittest.main()
