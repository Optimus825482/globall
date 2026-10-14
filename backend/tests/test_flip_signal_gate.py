"""Zıt sinyal (flip) kapısı testleri — 2026-10-14 kullanıcı kararı.

Kural: açık pozisyon varken zıt yönde sinyal geldiğinde
  * flip_ignore_min_score=True (varsayılan) → skor eşiği aranmaz, anında flip
  * flip_ignore_min_score=False → skor >= min_score koşulu geri gelir
  * spread (maliyet) kapısı HER İKİ durumda da çalışır — atlanmaz
"""
import os

os.environ.setdefault("FOREX_SETTINGS_DISABLE_PERSIST", "1")

from app.routers.forex import ForexAutoPaperSettings


def _gate_ok(settings: ForexAutoPaperSettings, score: float, spread_pips: float,
             spread_limit: float) -> bool:
    """Ana döngüdeki flip kapısının birebir kopyası (forex.py ~5998)."""
    score_gate_ok = bool(settings.flip_ignore_min_score) or score >= settings.min_score
    return score_gate_ok and spread_pips <= spread_limit


class TestFlipScoreGate:
    def test_default_ignores_min_score(self):
        s = ForexAutoPaperSettings()
        assert s.flip_ignore_min_score is True

    def test_low_score_still_flips_when_ignoring(self):
        """Skor 0 olsa bile flip yapılır (kullanıcı kararı: koşulsuz flip)."""
        s = ForexAutoPaperSettings(flip_ignore_min_score=True, min_score=75.0)
        # spread makul, skor eşik çok altında
        assert _gate_ok(s, score=10.0, spread_pips=2.0, spread_limit=10.0) is True

    def test_low_score_blocks_flip_when_not_ignoring(self):
        """Ayar kapalıysa eski davranış: düşük skorlu zıt sinyal flip YAPMAZ."""
        s = ForexAutoPaperSettings(flip_ignore_min_score=False, min_score=75.0)
        assert _gate_ok(s, score=10.0, spread_pips=2.0, spread_limit=10.0) is False

    def test_high_score_passes_gate_either_way(self):
        s_on = ForexAutoPaperSettings(flip_ignore_min_score=True)
        s_off = ForexAutoPaperSettings(flip_ignore_min_score=False)
        for s in (s_on, s_off):
            assert _gate_ok(s, score=80.0, spread_pips=2.0, spread_limit=10.0) is True


class TestFlipSpreadGateAlwaysOn:
    """Maliyet kapısı (spread) asla atlanmaz — ayar ne olursa olsun."""

    def test_wide_spread_blocks_flip_when_ignoring_score(self):
        s = ForexAutoPaperSettings(flip_ignore_min_score=True, min_score=75.0)
        # spread limit 10.0 pip; gelen 25.0 pip → flip OLMAZ
        assert _gate_ok(s, score=90.0, spread_pips=25.0, spread_limit=10.0) is False

    def test_wide_spread_blocks_flip_when_not_ignoring_score(self):
        s = ForexAutoPaperSettings(flip_ignore_min_score=False, min_score=75.0)
        assert _gate_ok(s, score=90.0, spread_pips=25.0, spread_limit=10.0) is False

    def test_crypto_widened_spread_limit_still_caps(self):
        """BTC/ETH'de limit 10x genişler ama yine de sınırdır."""
        s = ForexAutoPaperSettings(flip_ignore_min_score=True)
        assert _gate_ok(s, score=90.0, spread_pips=400.0, spread_limit=500.0) is True
        assert _gate_ok(s, score=90.0, spread_pips=600.0, spread_limit=500.0) is False
