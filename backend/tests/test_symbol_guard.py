"""SEMBOL KORUMASI (kara liste) kilitleri (2026-11-09 → 2026-11-10 düzeltildi).

Gerekçe (ölçüldü): AUD kümesi (2026-11-09, 276 işlem/7 gün): n=19, ortalama **−6.11 USD**,
**t=−4.12**.

**2026-11-10 DERS — SEMBOL BLOKLAMAK YANLIŞ ÇIKTI (kilit bu yüzden geri alındı):**
60 günlük broker defterinde "kötü sembol" görünen USDJPY/USDCHF/GBPUSD negatifliği o
paritelerden değil, **artık işlem açmayan iki kanaldan** geliyordu: `Scalper MT5`
(09-30→10-08, 1218 işlem, −0.088R) ve `FVG` (10-17→10-27, isabet %39.7, −0.224R).
Yalnız canlı kanallar (10-29 sonrası) ölçüldüğünde aynı pariteler nötr/pozitif:
USDCHF +0.043R, GBPUSD +0.067R. Kanıtlı kenar ise şurada: **USTEC×RADAR +0.198R (t=5.28)**,
**US30×RADAR +0.117R (t=2.74)**, **XAUUSD×RADAR +0.223R (t=2.72)**; canlı sızıntı
**FRS/fırsat taraması −0.183R (t=−2.51)** ve **XRPUSD −0.116R (isabet %22.9)**.

Kilitlenen davranış:
  1. Varsayılan kara liste = AUD kümesi (kanal ayrımından bağımsız, tek meşru gerekçe).
  2. Sembol listesine "kötü sembol" gerekçesiyle ekleme YAPILMAMALI — önce kanal ayrımı
     yapılmalı (ölü/aktif kanal ayrımı test edilir: `test_channel_confound_lesson_locked`).
  3. Koruması `continue` ile işlemi AÇMAZ ve **risk kapısından ÖNCE** çalışır.
  4. Liste boşaltılırsa koruma tamamen kapanır.
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
    def test_default_blocked_symbols_is_aud_only(self):
        m = ForexAutoPaperSettings()
        self.assertEqual(sorted(m.blocked_symbols), ["AUDCAD", "AUDNZD", "AUDUSD"])

    def test_description_carries_evidence_and_caveat(self):
        desc = ForexAutoPaperSettings.model_fields["blocked_symbols"].description
        self.assertIn("t=-4.12", desc, "AUD ölçüm kanıtı korunmalı")
        self.assertIn("KANAL AYRIMI", desc, "kanal/confound dersi açıklamada kalmalı")

    def test_empty_list_disables_guard(self):
        m = ForexAutoPaperSettings(blocked_symbols=[])
        self.assertEqual(m.blocked_symbols, [])


class TestChannelConfoundLesson(unittest.TestCase):
    """2026-11-10 dersi: sembol yasağından ÖNCE ölü/aktif kanal ayrımı yapılmalı."""

    def test_live_edges_are_documented(self):
        desc = ForexAutoPaperSettings.model_fields["blocked_symbols"].description
        for token in ("USTEC", "+0.198R", "FRS", "-0.183R"):
            self.assertIn(token, desc, f"{token} kanal ölçümü açıklamada olmalı")

    def test_no_measured_symbols_were_added(self):
        """Geçici eklenen 5 parite geri alındı; tekrar eklenirse kanal ayrımı istenir."""
        blocked = {s.upper() for s in ForexAutoPaperSettings().blocked_symbols}
        for sym in ("USDJPY", "USDCHF", "GBPUSD", "GBPJPY", "EURJPY"):
            self.assertNotIn(sym, blocked,
                             f"{sym} blok listesinde: 2026-11-10 ölçümü bunun yanlış olduğunu "
                             f"gösterdi (kanal confound) — önce kanal ayrımı yapılmalı")


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
