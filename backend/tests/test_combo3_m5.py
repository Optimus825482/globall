"""Combo3 (M5) paper-ölçüm kolu testleri (2026-10-28)."""
import json
import math
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import combo3_m5 as c3  # noqa: E402
from app.routers import forex  # noqa: E402


def _bars(closes, spread=0.5, t0=1_700_000_000):
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        out.append({"time": t0 + i * 300, "open": o, "high": max(o, c) + spread, "low": min(o, c) - spread, "close": c})
    return out


class Combo3IndicatorTests(unittest.TestCase):
    def test_atr_wilder_matches_replay_seed(self):
        bars = _bars([100 + math.sin(i / 7.0) * 3 for i in range(80)])
        a = c3.atr_wilder(bars, 14)
        self.assertIsNone(a[13])
        self.assertIsNotNone(a[14])
        self.assertTrue(all(v is not None and v > 0 for v in a[14:]))

    def test_vortex_cross_on_regime_change(self):
        # 40 bar düşüş, sonra 40 bar yükseliş → VI+ VI−'yi yukarı keser
        closes = [200 - i * 0.8 for i in range(40)] + [168 + i * 0.8 for i in range(40)]
        bars = _bars(closes)
        vip, vim = c3.vortex(bars, 14)
        crosses = [i for i in range(15, len(bars)) if c3._cross_up(vip, vim, i)]
        self.assertTrue(crosses, "yükselişe dönüşte VI+ kesişimi bekleniyordu")
        self.assertGreater(crosses[0], 40)

    def test_combo3_entry_buy_on_breakout_and_no_lookahead(self):
        closes = [100 + math.sin(i / 5.0) * 0.4 for i in range(70)] + [100.5 + i * 0.9 for i in range(1, 12)]
        bars = _bars(closes, spread=0.2)
        dec = c3.combo3_entry(bars, 0.1, 1.5, 2.0)
        self.assertIsNotNone(dec)
        self.assertEqual(dec["action"], "BUY")
        self.assertGreater(dec["sl_pips"], 0)
        self.assertAlmostEqual(dec["tp_pips"], round(dec["sl_pips"] * 2.0, 1), places=1)
        self.assertEqual(dec["bar_time"], bars[-1]["time"])
        # Look-ahead yok: sonraki barlar eklenince eski karar değişmemeli
        more = bars + _bars([50.0, 49.0], t0=bars[-1]["time"] + 300)
        again = c3.combo3_entry(more[:len(bars)], 0.1, 1.5, 2.0)
        self.assertEqual(again["action"], "BUY")
        self.assertEqual(again["sl_pips"], dec["sl_pips"])

    def test_combo3_entry_none_when_short_or_flat(self):
        self.assertIsNone(c3.combo3_entry(_bars([100.0] * 30), 0.1))
        self.assertIsNone(c3.combo3_entry(_bars([100.0] * 120, spread=0.0), 0.1))
        self.assertIsNone(c3.combo3_entry(_bars([100 + i * 0.1 for i in range(120)]), 0.0))


class Combo3LiveWiringTests(unittest.TestCase):
    def test_supertrend_filter_exempts_combo3(self):
        old = forex._AUTO_SETTINGS.supertrend_filter_enabled
        forex._AUTO_SETTINGS.supertrend_filter_enabled = True
        try:
            self.assertFalse(forex.supertrend_blocks_entry("combo3_m5", "BUY", -1))
            self.assertTrue(forex.supertrend_blocks_entry("", "BUY", -1))
        finally:
            forex._AUTO_SETTINGS.supertrend_filter_enabled = old

    def test_scan_rows_show_combo3(self):
        closes = [100 + math.sin(i / 5.0) * 0.4 for i in range(70)] + [100.5 + i * 0.9 for i in range(1, 12)]
        bars = _bars(closes, spread=0.2)
        old_fn, old_state = forex._s3_bars_for, dict(forex._COMBO3_STATE)
        old_enabled, old_syms = forex._AUTO_SETTINGS.combo3_enabled, list(forex._AUTO_SETTINGS.combo3_symbols)
        forex._s3_bars_for = lambda sym, interval, limit=260: bars
        forex._COMBO3_STATE.clear()
        forex._AUTO_SETTINGS.combo3_enabled = True   # kalıcı ayar dosyasından bağımsız
        forex._AUTO_SETTINGS.combo3_symbols = ["XAUUSD"]
        try:
            ticks = {"XAUUSD": {"display": "Altın", "bid": 100.0, "ask": 100.1, "spread_pips": 1.0}}
            rows = forex._scan_now_strategy_rows(ticks, {})
            c3_rows = [r for r in rows if r.get("strategy") == forex.COMBO3_STRATEGY]
            self.assertEqual(len(c3_rows), 1)
            self.assertEqual(c3_rows[0].get("symbol"), "XAUUSD")
            self.assertIn("BUY", str(c3_rows[0]))
        finally:
            forex._s3_bars_for = old_fn
            forex._COMBO3_STATE.clear()
            forex._COMBO3_STATE.update(old_state)
            forex._AUTO_SETTINGS.combo3_enabled = old_enabled
            forex._AUTO_SETTINGS.combo3_symbols = old_syms

    def test_settings_defaults_low_risk_gold_only(self):
        cfg = forex.ForexAutoPaperSettings()
        # 2026-10-28 akşam kararı: Kombo kolu açıldı, combo3 varsayılan KAPALI (aynı XAUUSD slotu için yarışmasın)
        self.assertFalse(cfg.combo3_enabled)
        self.assertEqual(cfg.combo3_symbols, ["XAUUSD"])
        self.assertEqual(cfg.combo3_risk_pct, 1.0)
        self.assertEqual(cfg.combo3_sl_atr, 1.5)
        self.assertEqual(cfg.combo3_tp_r, 2.0)

    def test_registry_and_tags(self):
        self.assertEqual(forex.strategy_name_for("combo3_m5"), forex.COMBO3_STRATEGY)
        self.assertEqual(forex.strategy_comment_tag("combo3_m5"), "CMB3")
        self.assertEqual(forex.strategy_display_label("CMB3"), forex.COMBO3_LABEL)
        self.assertIn("combo3_m5", forex._CLOSED_BAR_ARM_SOURCES)
        self.assertEqual(forex.strategy_from_mt5_deal({"strategy_tag": "CMB3 200"}), forex.COMBO3_STRATEGY)

    def test_effective_risk_overrides_gold_budget_only_for_combo3(self):
        cfg = forex.ForexAutoPaperSettings(risk_gold_pct=10.0, combo3_risk_pct=1.5)
        self.assertEqual(forex.effective_risk_pct("XAUUSD", "combo3_m5", cfg), 1.5)
        self.assertEqual(forex.effective_risk_pct("XAUUSD", "s3_5m", cfg), 10.0)
        self.assertEqual(forex.effective_risk_pct("XAUUSD", "", cfg), 10.0)

    def test_slippage_record_and_summary(self):
        cmd = {"symbol": "XAUUSD", "direction": "BUY", "lots": 0.05, "entry_source": "combo3_m5",
               "strategy_tag": "CMB3", "signal_price": 4000.00, "signal_bar_time": 1, "created_ts": 100.0,
               "spread_pips_signal": 1.2}
        res = {"fill_price": 4000.35, "req_price": 4000.20, "spread_pips_exec": 1.5, "latency_ms": 120.0, "exec_ts": 103.5, "ticket": 7}
        rec = c3.slippage_record(cmd, res, 0.1)
        self.assertAlmostEqual(rec["exec_slip_pips"], 1.5, places=2)
        self.assertAlmostEqual(rec["signal_slip_pips"], 3.5, places=2)
        self.assertAlmostEqual(rec["decision_to_fill_sec"], 3.5, places=2)
        sell = c3.slippage_record({**cmd, "direction": "SELL"}, {**res, "fill_price": 3999.9, "req_price": 4000.0}, 0.1)
        self.assertAlmostEqual(sell["exec_slip_pips"], 1.0, places=2)   # SELL'de düşük fill aleyhe
        summ = c3.slippage_summary([rec, sell])
        self.assertEqual(summ["CMB3"]["trades"], 2)
        self.assertEqual(summ["CMB3"]["exec_slip_pips"]["n"], 2)
        self.assertIsNone(c3.slippage_record(cmd, {"req_price": 1.0}, 0.1))

    def test_record_slippage_persists_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "slip.jsonl")
            old_path, old_log = forex._SLIPPAGE_LOG_PATH, list(forex._SLIPPAGE_LOG)
            forex._SLIPPAGE_LOG_PATH = path
            forex._SLIPPAGE_LOG.clear()
            try:
                cr = {"action": "OPEN_ORDER", "symbol": "XAUUSD", "direction": "SELL", "lots": 0.02,
                      "entry_source": "combo3_m5", "strategy_tag": "CMB3", "signal_price": 4010.0,
                      "fill_price": 4009.8, "req_price": 4009.9, "spread_pips_exec": 1.1, "exec_ts": 10.0, "created_ts": 8.0}
                rec = forex._record_slippage(cr, cr)
                self.assertIsNotNone(rec)
                self.assertAlmostEqual(rec["exec_slip_pips"], 1.0, places=2)
                with open(path, encoding="utf-8") as fh:
                    rows = [json.loads(x) for x in fh if x.strip()]
                self.assertEqual(len(rows), 1)
                forex._SLIPPAGE_LOG.clear()
                self.assertEqual(len(forex._load_slippage_log()), 1)
            finally:
                forex._SLIPPAGE_LOG_PATH = old_path
                forex._SLIPPAGE_LOG.clear()
                forex._SLIPPAGE_LOG.extend(old_log)


if __name__ == "__main__":
    unittest.main()
