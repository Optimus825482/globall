"""TOKYO SABAHI DRİFTİ kolu kilitleri (2026-11-10).

Kanıt: `docs/FX_YENI_SINYAL_AILESI_ARASTIRMASI_2026-11-10.md` — 5 yıl H1, 1.290
gözlem/sembol/saat, trend demean edilmiş, maliyet düşülmüş: 01:00 UTC LONG
GBPUSD +2.38p (t=10.7), USDJPY +2.57p (t=6.4), EURUSD +1.47p (t=7.3).

Kilitlenen davranış:
  1. Varsayılanlar: açık, 3 FX majörü (XAUUSD BİLİNÇLİ dışarıda — 5c likidite kuralı).
  2. Kanal kimliği: `TKYO` yorum etiketi + strateji adı + panel etiketi (defter ayrımı).
  3. Pencere/günde-bir giriş disiplini: saat dışında/ikinci çağrıda aday ÜRETİLMEZ.
  4. `soft_bypass` YALNIZ sinyal-kalitesi kapılarını atlar; **risk kapıları (spread,
     korelasyon, günlük zarar kesici, lot bütçesi) ATLANMAZ** — kaynak taramasıyla kilitli.
  5. Çıkış `hold_minutes` ile mevcut EoD zaman-stopuna bağlı (yeni çıkış kodu yok).
"""
import datetime as dt
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers import forex as fx  # noqa: E402

SRC = (ROOT / "app" / "routers" / "forex.py").read_text(encoding="utf-8")


def _tick(sym="GBPUSD", atr=12.0, spread=0.8):
    return {"symbol": sym, "display": sym, "bid": 1.30, "ask": 1.3001, "pip_size": 0.0001,
            "atr_pips": atr, "spread_pips": spread, "adx": 12.0, "supertrend_dir": -1,
            "score": 10.0}


class _Clock:
    """`fx.datetime` yerine geçen modül shim'i: `now()` sabit, GERİ KALANI gerçek modüle
    delege (aksi halde `_log_auto_decision` içindeki `datetime.datetime.fromtimestamp` kırılır)."""

    def __init__(self, when: dt.datetime):
        self._when = when

        class _DT(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return when
        self._dt = _DT

    @property
    def datetime(self):
        return self._dt

    def __getattr__(self, name):
        return getattr(dt, name)


class TestDefaults(unittest.TestCase):
    def test_enabled_by_default_with_measured_basket(self):
        m = fx.ForexAutoPaperSettings()
        self.assertTrue(m.tokyo_drift_enabled)
        # Ölçülen dörtlü (2026-11-10): XAUUSD kullanıcı isteğiyle eklendi
        self.assertEqual(sorted(m.tokyo_drift_symbols), ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"])

    def test_window_defaults(self):
        m = fx.ForexAutoPaperSettings()
        self.assertEqual(m.tokyo_drift_entry_hour_utc, 1, "00:00 rollover saatidir, 01:00 ölçüldü")
        self.assertEqual(m.tokyo_drift_hold_min, 60)
        self.assertGreaterEqual(m.tokyo_drift_window_min, 1)

    def test_description_carries_evidence(self):
        desc = fx.ForexAutoPaperSettings.model_fields["tokyo_drift_enabled"].description
        for token in ("+2.38p", "t=10.7", "RİSK KAPILARI"):
            self.assertIn(token, desc, f"{token} açıklamada olmalı (kanıt/kapı politikası)")


class TestChannelIdentity(unittest.TestCase):
    def test_comment_tag(self):
        self.assertEqual(fx.strategy_comment_tag("tokyo_drift"), "TKYO")

    def test_strategy_name_and_label(self):
        self.assertEqual(fx.strategy_name_for("tokyo_drift"), fx.TOKYO_DRIFT_STRATEGY)
        self.assertIn("Tokyo", fx.strategy_display_label("TOKYO_DRIFT"))


class TestCandidateBuilder(unittest.TestCase):
    def setUp(self):
        fx._TOKYO_DRIFT_LAST_DAY.clear()
        self._orig_dt = fx.datetime
        self._orig_state = fx._AUTO_STATE.get("open_positions")
        fx._AUTO_STATE["open_positions"] = []

    def tearDown(self):
        fx.datetime = self._orig_dt
        fx._AUTO_STATE["open_positions"] = self._orig_state or []
        fx._TOKYO_DRIFT_LAST_DAY.clear()

    def _at(self, day=10, hour=1, minute=1):
        # 2026-11-10 bir Salı (hafta içi)
        fx.datetime = _Clock(dt.datetime(2026, 11, day, hour, minute, tzinfo=dt.timezone.utc))

    def test_disabled_yields_nothing(self):
        self._at()
        fx._AUTO_SETTINGS.tokyo_drift_enabled = False
        try:
            self.assertEqual(fx._tokyo_drift_candidates({"GBPUSD": _tick()}, 1794274026.0), [])
        finally:
            fx._AUTO_SETTINGS.tokyo_drift_enabled = True

    def test_outside_window_yields_nothing(self):
        self._at(hour=5)
        self.assertEqual(fx._tokyo_drift_candidates({"GBPUSD": _tick()}, 1794274026.0), [])

    def test_weekend_yields_nothing(self):
        self._at(day=14)  # 2026-11-14 Cumartesi
        self.assertEqual(fx._tokyo_drift_candidates({"GBPUSD": _tick()}, 1794274026.0), [])

    def test_inside_window_builds_long_with_time_exit(self):
        self._at()
        now_ts = 1794274026.0
        cands = fx._tokyo_drift_candidates({"GBPUSD": _tick()}, now_ts)
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertEqual(c["action"], "BUY", "ölçülen yön LONG")
        self.assertEqual(c["entry_source"], "tokyo_drift")
        self.assertEqual(c["hold_minutes"], fx._AUTO_SETTINGS.tokyo_drift_hold_min)
        self.assertGreater(c["sl_pips_override"], 0.0)
        self.assertEqual(c["tp_pips_override"], 0.0, "sabit TP yok (zaman çıkışı)")
        self.assertTrue(c["soft_bypass"])

    def test_once_per_window_per_day(self):
        self._at()
        now_ts = 1794274026.0
        self.assertEqual(len(fx._tokyo_drift_candidates({"GBPUSD": _tick()}, now_ts)), 1)
        self.assertEqual(fx._tokyo_drift_candidates({"GBPUSD": _tick()}, now_ts + 60), [],
                         "aynı pencere ikinci kez açılmaz")

    def test_second_window_same_day_is_allowed(self):
        """GBPUSD 01:00 BUY + 13:00 SELL: aynı gün İKİ ayrı pencere açılabilmeli."""
        self._at(minute=1)
        ts = 1794274026.0
        first = fx._tokyo_drift_candidates({"GBPUSD": _tick()}, ts)
        self.assertEqual([c["action"] for c in first], ["BUY"])
        self._at(hour=13, minute=1)          # aynı gün, ikinci pencere
        second = fx._tokyo_drift_candidates({"GBPUSD": _tick()}, ts)
        self.assertEqual([c["action"] for c in second], ["SELL"],
                         "13:00 penceresi SHORT (ölçüm: demean −1.05p, t=−2.7)")

    def test_symbol_outside_radar_universe_still_trades(self):
        """Kol, radar evrenine (`allowed_symbols`) BAĞLI OLMAMALI — 2026-11-10 bulgusu:
        EURUSD kod varsayılanındaki listede yoktu ve kol sessizce hiç işlem açmıyordu."""
        self._at()
        old_allowed = list(fx._AUTO_SETTINGS.allowed_symbols)
        fx._AUTO_SETTINGS.allowed_symbols = ["GBPUSD"]      # EURUSD radar evreninin DIŞINDA
        try:
            cands = fx._tokyo_drift_candidates({"EURUSD": _tick("EURUSD")}, 1794274026.0)
            self.assertEqual([c["action"] for c in cands], ["BUY"],
                             "radar evreninde olmayan sembolde de kol işlem açmalı")
        finally:
            fx._AUTO_SETTINGS.allowed_symbols = old_allowed

    def test_eurusd_short_window(self):
        self._at(hour=14, minute=1)
        cands = fx._tokyo_drift_candidates({"EURUSD": _tick("EURUSD")}, 1794274026.0)
        self.assertEqual([c["action"] for c in cands], ["SELL"])
        self.assertEqual(cands[0]["entry_source"], "tokyo_drift")

    def test_blocked_symbol_excluded(self):
        self._at()
        old = list(fx._AUTO_SETTINGS.blocked_symbols)
        fx._AUTO_SETTINGS.blocked_symbols = ["GBPUSD"]
        try:
            self.assertEqual(fx._tokyo_drift_candidates({"GBPUSD": _tick()}, 1794274026.0), [])
        finally:
            fx._AUTO_SETTINGS.blocked_symbols = old

    def test_open_position_blocks_reentry(self):
        self._at()
        fx._AUTO_STATE["open_positions"] = [{"symbol": "GBPUSD"}]
        self.assertEqual(fx._tokyo_drift_candidates({"GBPUSD": _tick()}, 1794274026.0), [])


class TestWiring(unittest.TestCase):
    def test_injected_into_candidate_flow(self):
        self.assertIn("candidates = candidates + _tokyo_drift_candidates(ticks, now_ts)", SRC)

    def test_soft_bypass_only_on_signal_quality_gates(self):
        for gate in ('if cand["score"] < req_score and not _news_bypass and not _soft_bypass:',
                     'and not _news_bypass and not _soft_bypass):',
                     'if (not _soft_bypass) and supertrend_blocks_entry(',
                     'and not _news_bypass and not _soft_bypass:'):
            self.assertIn(gate, SRC, f"yumuşak kapı beklenen biçimde değil: {gate}")

    def test_risk_gates_are_not_bypassed(self):
        """Spread/EV kapıları soft_bypass GÖRMEMELİ (satır bazında kaynak taraması)."""
        risk_lines = [
            'if cand["spread_pips"] > effective_max_spread:',
            'if _AUTO_SETTINGS.ev_guard_enabled and not _ev_exempt:',
        ]
        for line in risk_lines:
            hits = [ln for ln in SRC.splitlines() if ln.strip() == line]
            self.assertEqual(len(hits), 1, f"risk kapısı bulunamadı (ya da çoklu): {line}")
            self.assertNotIn("_soft_bypass", hits[0],
                             f"risk/safety kapısına soft_bypass eklenmiş — YASAK: {line}")

    def test_gold_session_gate_bypassed_only_for_this_arm(self):
        """XAU 01:00'de işlem açabilsin diye 5c kapısı YALNIZ _soft_bypass ile atlanır."""
        hits = [ln for ln in SRC.splitlines()
                if "is_gold or is_index_cand) and not (7 <= current_utc_hour < 20)" in ln]
        self.assertEqual(len(hits), 1, "5c seans likidite kapısı bulunamadı")
        self.assertIn("and not _soft_bypass:", hits[0],
                      "5c kapısı zaman kolunda atlanmalı (XAU 01:00 ölçümü pozitif)")

    def test_exit_uses_existing_time_stop(self):
        self.assertIn('"hold_minutes": hold', SRC)
        self.assertIn('positions_to_close.append((pos["id"], "EOD_TIME", cur_p))', SRC)


if __name__ == "__main__":
    unittest.main()
