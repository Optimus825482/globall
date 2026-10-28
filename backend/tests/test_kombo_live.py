"""Kombo (M5) demo ölçüm kolu — forex.py canlı bağlantı testleri (2026-10-28).

Saf port testleri `test_kombo_m5.py`'de; burada kayıt/etiket/risk/kota/sinyal günlüğü/
radar satırları ve emir etiketi (KMB1/KMB4/KMB9) doğrulanır.
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import kombo_m5 as km  # noqa: E402
from app.routers import forex  # noqa: E402


class KomboRegistryTests(unittest.TestCase):
    def test_registry_and_tags(self):
        self.assertEqual(forex.strategy_name_for("kombo_m5"), forex.KOMBO_STRATEGY)
        self.assertEqual(forex.strategy_comment_tag("kombo_m5"), "KMB")
        self.assertEqual(forex.strategy_display_label("KMB4"), forex.KOMBO_LABEL)
        self.assertEqual(forex.strategy_display_label("KOMBO_M5"), forex.KOMBO_LABEL)
        self.assertIn("kombo_m5", forex._CLOSED_BAR_ARM_SOURCES)
        self.assertEqual(forex.strategy_from_mt5_deal({"strategy_tag": "KMB9 73"}), forex.KOMBO_STRATEGY)
        self.assertEqual(forex.strategy_from_mt5_deal({"comment": "KMB1 55"}), forex.KOMBO_STRATEGY)
        # Combo3 etiketi kombo ile karışmamalı
        self.assertEqual(forex.strategy_from_mt5_deal({"strategy_tag": "CMB3 50"}), forex.COMBO3_STRATEGY)

    def test_candidate_comment_tag_prefers_override(self):
        self.assertEqual(forex.candidate_comment_tag({"entry_source": "kombo_m5", "strategy_tag_override": "KMB4"}), "KMB4")
        self.assertEqual(forex.candidate_comment_tag({"entry_source": "kombo_m5"}), "KMB")
        self.assertEqual(forex.candidate_comment_tag({"entry_source": "combo3_m5"}), "CMB3")
        self.assertEqual(forex.candidate_comment_tag({"entry_source": "squeeze_kc", "strategy_tag_override": ""}), "SQZKC")

    def test_supertrend_filter_exempts_kombo(self):
        old = forex._AUTO_SETTINGS.supertrend_filter_enabled
        forex._AUTO_SETTINGS.supertrend_filter_enabled = True
        try:
            self.assertFalse(forex.supertrend_blocks_entry("kombo_m5", "BUY", -1))
            self.assertTrue(forex.supertrend_blocks_entry("", "BUY", -1))
        finally:
            forex._AUTO_SETTINGS.supertrend_filter_enabled = old

    def test_settings_defaults(self):
        cfg = forex.ForexAutoPaperSettings()
        self.assertTrue(cfg.kombo_enabled)
        self.assertFalse(cfg.combo3_enabled)  # ikisi aynı XAUUSD slotu için yarışmasın
        self.assertEqual(cfg.kombo_symbols, ["XAUUSD"])
        self.assertEqual(cfg.kombo_risk_pct, 2.0)
        self.assertEqual(cfg.kombo_max_per_day, 0)
        self.assertEqual([k["ad"] for k in cfg.kombo_tanimlar], ["kombo_1", "kombo_4", "kombo_9"])
        self.assertEqual([k["tag"] for k in cfg.kombo_tanimlar], ["KMB1", "KMB4", "KMB9"])

    def test_effective_risk_overrides_gold_budget_only_for_kombo(self):
        cfg = forex.ForexAutoPaperSettings(risk_gold_pct=10.0, kombo_risk_pct=2.5, combo3_risk_pct=1.0)
        self.assertEqual(forex.effective_risk_pct("XAUUSD", "kombo_m5", cfg), 2.5)
        self.assertEqual(forex.effective_risk_pct("XAUUSD", "combo3_m5", cfg), 1.0)
        self.assertEqual(forex.effective_risk_pct("XAUUSD", "s3_5m", cfg), 10.0)


class KomboQuotaAndJournalTests(unittest.TestCase):
    def test_commit_arm_quota_is_per_kombo(self):
        forex._KOMBO_DAY_STATE["XAUUSD"] = {"day": 1, "counts": {}, "consumed": {}}
        try:
            forex._commit_arm_quota({"_arm_quota": {"kind": "kombo", "symbol": "XAUUSD", "action": "BUY", "bar_time": 500, "ad": "kombo_1"}})
            forex._commit_arm_quota({"_arm_quota": {"kind": "kombo", "symbol": "XAUUSD", "action": "BUY", "bar_time": 500, "ad": "kombo_9"}})
            forex._commit_arm_quota({"_arm_quota": {"kind": "kombo", "symbol": "XAUUSD", "action": "SELL", "bar_time": 800, "ad": "kombo_1"}})
            st = forex._KOMBO_DAY_STATE["XAUUSD"]
            self.assertEqual(st["counts"]["kombo_1"], {"BUY": 1, "SELL": 1})
            self.assertEqual(st["counts"]["kombo_9"], {"BUY": 1})
            self.assertEqual(st["consumed"], {"kombo_1": 800, "kombo_9": 500})
        finally:
            forex._KOMBO_DAY_STATE.pop("XAUUSD", None)

    def test_signal_journal_dedupes_and_persists(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "kombo.jsonl")
            old_path, old_log, old_seen = forex._KOMBO_SIGNAL_LOG_PATH, list(forex._KOMBO_SIGNAL_LOG), set(forex._KOMBO_SIGNAL_SEEN)
            forex._KOMBO_SIGNAL_LOG_PATH = path
            forex._KOMBO_SIGNAL_LOG.clear()
            forex._KOMBO_SIGNAL_SEEN.clear()
            try:
                rec = {"ts": 1.0, "symbol": "XAUUSD", "ad": "kombo_4", "tag": "KMB4", "action": "SELL", "bar_time": 900,
                       "close": 4000.0, "sl_pips": 30.0, "tp_pips": 60.0, "durum": "aday"}
                self.assertTrue(forex._record_kombo_signal(rec))
                self.assertFalse(forex._record_kombo_signal(dict(rec)))          # aynı bar → tek kayıt
                self.assertTrue(forex._record_kombo_signal({**rec, "ad": "kombo_1", "tag": "KMB1"}))  # başka kombo aynı bar
                with open(path, encoding="utf-8") as fh:
                    rows = [json.loads(x) for x in fh if x.strip()]
                self.assertEqual(len(rows), 2)
                forex._KOMBO_SIGNAL_LOG.clear()
                forex._KOMBO_SIGNAL_SEEN.clear()
                self.assertEqual(len(forex._load_kombo_signal_log()), 2)
                self.assertFalse(forex._record_kombo_signal(rec))  # diskten yüklenen de dedupe'a girer
            finally:
                forex._KOMBO_SIGNAL_LOG_PATH = old_path
                forex._KOMBO_SIGNAL_LOG.clear()
                forex._KOMBO_SIGNAL_LOG.extend(old_log)
                forex._KOMBO_SIGNAL_SEEN.clear()
                forex._KOMBO_SIGNAL_SEEN.update(old_seen)

    def test_signal_summary_joins_slippage_by_tag_and_bar(self):
        signals = [
            {"ad": "kombo_1", "tag": "KMB1", "action": "BUY", "bar_time": 100, "durum": "aday"},
            {"ad": "kombo_1", "tag": "KMB1", "action": "SELL", "bar_time": 200, "durum": "aday"},
            {"ad": "kombo_9", "tag": "KMB9", "action": "BUY", "bar_time": 100, "durum": "kota"},
        ]
        slip = [{"strategy_tag": "KMB1", "signal_bar_time": 100}, {"strategy_tag": "CMB3", "signal_bar_time": 200}]
        s = forex.kombo_signal_summary(signals, slip)
        self.assertEqual(s["kombo_1"]["sinyal"], 2)
        self.assertEqual(s["kombo_1"]["emir"], 1)
        self.assertEqual(s["kombo_1"]["BUY"], 1)
        self.assertEqual(s["kombo_9"]["emir"], 0)
        self.assertEqual(s["kombo_9"]["durum"], {"kota": 1})


class KomboScanRowsTests(unittest.TestCase):
    def test_scan_rows_one_per_kombo_without_data(self):
        old_fn = forex._s3_bars_for
        old_state = dict(forex._KOMBO_STATE)
        old_enabled = forex._AUTO_SETTINGS.kombo_enabled
        forex._s3_bars_for = lambda sym, interval, limit=260: None
        forex._KOMBO_STATE.clear()
        forex._AUTO_SETTINGS.kombo_enabled = True
        try:
            ticks = {"XAUUSD": {"display": "Altın", "bid": 100.0, "ask": 100.1, "spread_pips": 1.0}}
            rows = [r for r in forex._scan_now_strategy_rows(ticks, {}) if r.get("strategy") == forex.KOMBO_STRATEGY]
            self.assertEqual(len(rows), 1)
            self.assertIn("Veri yok", str(rows[0]))
        finally:
            forex._s3_bars_for = old_fn
            forex._KOMBO_STATE.clear()
            forex._KOMBO_STATE.update(old_state)
            forex._AUTO_SETTINGS.kombo_enabled = old_enabled

    def test_scan_rows_list_each_kombo_when_state_present(self):
        old_state = dict(forex._KOMBO_STATE)
        old_enabled = forex._AUTO_SETTINGS.kombo_enabled
        forex._AUTO_SETTINGS.kombo_enabled = True
        forex._KOMBO_STATE["XAUUSD"] = {
            "decs": [{"ad": "kombo_4", "tag": "KMB4", "action": "SELL", "sl_pips": 25.0, "tp_pips": 50.0, "atr": 1.7, "close": 4001.5}],
            "bar_time": 12345, "bars": 600, "close": 4001.5,
        }
        try:
            ticks = {"XAUUSD": {"display": "Altın", "bid": 4001.0, "ask": 4001.3, "spread_pips": 3.0}}
            rows = [r for r in forex._scan_now_strategy_rows(ticks, {}) if r.get("strategy") == forex.KOMBO_STRATEGY]
            self.assertEqual(len(rows), 3)
            txt = " | ".join(str(r) for r in rows)
            self.assertIn("kombo_4 (KMB4): SELL adayı", txt)
            self.assertIn("kombo_1 (KMB1): sinyal yok", txt)
            self.assertIn("kombo_9 (KMB9): sinyal yok", txt)
        finally:
            forex._KOMBO_STATE.clear()
            forex._KOMBO_STATE.update(old_state)
            forex._AUTO_SETTINGS.kombo_enabled = old_enabled


class KomboTechTests(unittest.TestCase):
    def test_tech_for_uses_600_bars_and_survives_bad_definition(self):
        old_fn = forex._s3_bars_for
        old_defs = list(forex._AUTO_SETTINGS.kombo_tanimlar)
        seen = {}

        def fake_bars(sym, interval, limit=260):
            seen["limit"] = limit
            seen["interval"] = interval
            return None

        forex._s3_bars_for = fake_bars
        try:
            self.assertIsNone(forex._kombo_tech_for("XAUUSD"))
            self.assertEqual(seen["limit"], forex._KOMBO_BAR_LIMIT)
            self.assertEqual(seen["interval"], "5m")
            self.assertGreaterEqual(forex._KOMBO_BAR_LIMIT, 600)  # EMA200 tohumu için ≥ 600 bar (parite testi)
            # geçersiz tanım → ValueError yutulur, kol sessiz kalır
            bars = [{"time": 1_700_000_000 + i * 300, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0 + (i % 7) * 0.1}
                    for i in range(700)]
            forex._s3_bars_for = lambda sym, interval, limit=260: bars
            forex._AUTO_SETTINGS.kombo_tanimlar = [{"ad": "x", "tag": "KMBX", "tanim": {"tip": "xor", "a": "ut_bot", "b": "combo3"}}]
            tech = forex._kombo_tech_for("XAUUSD")
            self.assertIsNotNone(tech)
            self.assertEqual(tech["decs"], [])
            self.assertEqual(tech["bars"], 700)
        finally:
            forex._s3_bars_for = old_fn
            forex._AUTO_SETTINGS.kombo_tanimlar = old_defs


if __name__ == "__main__":
    unittest.main()
