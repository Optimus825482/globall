"""KAPANIŞ NEDENİ KANONİKLEŞTİRME kilitleri (2026-11-09) — app/trade_reasons.py.

Kilitlenen davranış:
  1. **"SL ama kazanç" imkânsızdır** — kârlı işlem SL_HIT olamaz, onarılır ve
     `contradiction=True` işaretlenir. (Gerçek veride 240 "SL" etiketinden 152'si
     kazançtı; bu modül hepsini onarıyor.)
  2. Zararlı işlem TP_HIT olamaz — aynı mantık kapısı.
  3. Fiyat kanıtı (exit ≈ SL/TP seviyesi) metin kanıtından ÖNCE gelir.
  4. "trailing"/"kısmi" ifadeleri "stop/zarar"dan ÖNCE denenir (ikisini de
     içerebilirler: "İz Süren Stop").
  5. Kanıt yoksa PnL işaretine göre OTHER_WIN/OTHER_LOSS; PnL de yoksa UNKNOWN.
  6. Toplam korunur: her işlem tam bir kod alır (kayıp/çift sayım yok).
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import trade_reasons as tr  # noqa: E402


class TestContradictionRepair(unittest.TestCase):
    def test_sl_label_with_profit_is_repaired(self):
        """GERÇEK VAKA: '🛑 Zarar Durdur (SL)' + pozitif PnL (CSV'de 152 kez)."""
        r = tr.canonical_exit_reason(reason_text="🛑 Zarar Durdur (SL)", pnl_usd=+0.98)
        self.assertNotEqual(r["code"], tr.SL_HIT, "kârlı işlem SL olamaz")
        self.assertEqual(r["code"], tr.OTHER_WIN)
        self.assertTrue(r["contradiction"])
        self.assertEqual(r["source"], "repaired")

    def test_sl_label_with_loss_stays_sl(self):
        r = tr.canonical_exit_reason(reason_text="🛑 Zarar Durdur (SL)", pnl_usd=-1.85)
        self.assertEqual(r["code"], tr.SL_HIT)
        self.assertFalse(r["contradiction"])

    def test_sl_label_with_profit_and_trailing_hint_becomes_trailing(self):
        # Metin hem "SL" hem "Trailing" içeriyor. Trailing ÖNCE denenir → kod
        # baştan TRAILING olur ve kârlı trailing ÇELİŞKİ DEĞİLDİR
        # (`contradiction=False`). Çelişki yalnız "saf SL + kâr" durumunda.
        r = tr.canonical_exit_reason(reason_text="Zarar Durdur (SL) — Trailing", pnl_usd=+3.1)
        self.assertEqual(r["code"], tr.TRAILING)
        self.assertFalse(r["contradiction"])

    def test_tp_label_with_loss_is_repaired(self):
        r = tr.canonical_exit_reason(reason_text="🎯 Kâr Al (TP)", pnl_usd=-2.0)
        self.assertNotEqual(r["code"], tr.TP_HIT)
        self.assertEqual(r["code"], tr.OTHER_LOSS)
        self.assertTrue(r["contradiction"])


class TestEvidencePriority(unittest.TestCase):
    def test_price_evidence_beats_text(self):
        # Metin "SL" diyor ama çıkış fiyatı TP seviyesinde → TP_HIT
        r = tr.canonical_exit_reason(
            reason_text="Zarar Durdur (SL)", pnl_usd=+5.0,
            entry_price=100.0, exit_price=102.0, direction="BUY",
            sl_price=98.5, tp_price=102.0)
        self.assertEqual(r["code"], tr.TP_HIT)
        self.assertEqual(r["source"], "price")

    def test_price_evidence_sl(self):
        r = tr.canonical_exit_reason(
            reason_text="Scalper Close", pnl_usd=-1.5,
            entry_price=100.0, exit_price=98.5, direction="BUY",
            sl_price=98.5, tp_price=102.0)
        self.assertEqual(r["code"], tr.SL_HIT)
        self.assertEqual(r["source"], "price")

    def test_trailing_checked_before_stop(self):
        for text in ("İz Süren Stop (Trailing)", "Trailing stop hit", "Takipçi stop"):
            r = tr.canonical_exit_reason(reason_text=text, pnl_usd=+2.0)
            self.assertEqual(r["code"], tr.TRAILING, text)

    def test_partial_checked_before_stop(self):
        r = tr.canonical_exit_reason(reason_text="Scalper Partial", pnl_usd=+5.09)
        self.assertEqual(r["code"], tr.PARTIAL)

    def test_scalper_close_detected(self):
        r = tr.canonical_exit_reason(reason_text="Scalper Close", pnl_usd=-2.05)
        self.assertEqual(r["code"], tr.SCALPER_CLOSE)

    def test_reversal_and_eod(self):
        self.assertEqual(tr.canonical_exit_reason(reason_text="🔄 Trend Dönüşü", pnl_usd=-1)["code"], tr.REVERSAL)
        self.assertEqual(tr.canonical_exit_reason(reason_text="🌙 Gün Sonu", pnl_usd=-1)["code"], tr.EOD)


class TestFallbacks(unittest.TestCase):
    def test_no_evidence_uses_pnl_sign(self):
        self.assertEqual(tr.canonical_exit_reason(reason_text=None, pnl_usd=+1.0)["code"], tr.OTHER_WIN)
        self.assertEqual(tr.canonical_exit_reason(reason_text=None, pnl_usd=-1.0)["code"], tr.OTHER_LOSS)
        self.assertEqual(tr.canonical_exit_reason(reason_text="bilinmeyen metin", pnl_usd=0.0)["code"], tr.OTHER_WIN)

    def test_no_pnl_is_unknown(self):
        self.assertEqual(tr.canonical_exit_reason(reason_text="", pnl_usd=None)["code"], tr.UNKNOWN)

    def test_helpers(self):
        self.assertTrue(tr.is_stop_like(tr.SL_HIT))
        self.assertTrue(tr.is_stop_like(tr.TRAILING))
        self.assertFalse(tr.is_stop_like(tr.TP_HIT))
        self.assertTrue(tr.is_target_like(tr.OTHER_WIN))
        self.assertFalse(tr.is_target_like(tr.OTHER_LOSS))

    def test_label_present_for_every_code(self):
        for code in (tr.SL_HIT, tr.TP_HIT, tr.TRAILING, tr.PARTIAL, tr.SCALPER_CLOSE,
                     tr.REVERSAL, tr.EOD, tr.MANUAL, tr.OTHER_WIN, tr.OTHER_LOSS, tr.UNKNOWN):
            self.assertIn(code, tr.LABELS)
            self.assertTrue(tr.LABELS[code])


class TestRealWorldDistribution(unittest.TestCase):
    """CSV'de ölçülen dağılımı taklit et: 240 'SL' etiketi, 152 kazanç."""

    def test_240_sl_labels_split_correctly(self):
        wins = [tr.canonical_exit_reason(reason_text="🛑 Zarar Durdur (SL)", pnl_usd=+1.0)
                for _ in range(152)]
        losses = [tr.canonical_exit_reason(reason_text="🛑 Zarar Durdur (SL)", pnl_usd=-1.0)
                  for _ in range(88)]
        self.assertTrue(all(r["code"] != tr.SL_HIT for r in wins), "kazançlar SL kalmamalı")
        self.assertTrue(all(r["code"] == tr.SL_HIT for r in losses), "kayıplar SL kalmalı")
        self.assertEqual(sum(1 for r in wins if r["contradiction"]), 152)


if __name__ == "__main__":
    unittest.main()
