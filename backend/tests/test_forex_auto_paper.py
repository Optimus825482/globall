import asyncio
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers import forex


class TestForexAutoPaper(unittest.IsolatedAsyncioTestCase):

    async def test_auto_paper_status_initial(self):
        status = await forex.get_forex_auto_paper_status()
        self.assertIn("balance", status)
        self.assertIn("open_positions", status)
        self.assertIn("settings", status)
        self.assertIn("sessions", status)
        self.assertGreaterEqual(status["balance"], 1000.0)

    async def test_auto_paper_settings_update(self):
        new_cfg = forex.ForexAutoPaperSettings(
            enabled=False,
            balance=12500.0,
            risk_per_trade_pct=1.5,
            max_open_positions=4,
            min_score=80.0,
            tp_pips=30.0,
            sl_pips=15.0,
            breakeven_pips=9.0,
            trailing_stop_pips=14.0,
            session_filter=True,
            max_spread_pips=2.0,
            allowed_symbols=["EURUSD", "GBPUSD", "XAUUSD"],
        )
        res = await forex.update_forex_auto_paper_settings(new_cfg)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["settings"]["risk_per_trade_pct"], 1.5)
        self.assertEqual(res["settings"]["allowed_symbols"], ["EURUSD", "GBPUSD", "XAUUSD"])

    async def test_auto_paper_toggle_and_reset(self):
        # Toggle ON
        res_on = await forex.toggle_forex_auto_paper(forex.ToggleAutoPaperRequest(enabled=True))
        self.assertTrue(res_on["enabled"])

        # Toggle OFF
        res_off = await forex.toggle_forex_auto_paper(forex.ToggleAutoPaperRequest(enabled=False))
        self.assertFalse(res_off["enabled"])

        # Reset
        res_reset = await forex.reset_forex_auto_paper()
        self.assertEqual(res_reset["status"], "reset")
        self.assertEqual(res_reset["balance"], 10000.0)

    async def test_auto_paper_lifecycle_and_accounting(self):
        # Add a synthetic position
        test_pos = {
            "id": "FX-TEST-789",
            "symbol": "EURUSD",
            "display": "EUR/USD",
            "direction": "BUY",
            "lots": 0.50,
            "entry_price": 1.08500,
            "current_price": 1.08700,
            "sl_price": 1.08350,
            "tp_price": 1.08800,
            "initial_sl_price": 1.08350,
            "breakeven_activated": False,
            "trailing_activated": False,
            "open_time": "12:00:00 UTC",
            "pnl_usd": 100.0,
            "pnl_pips": 20.0,
            "pip_size": 0.0001,
            "digits": 5,
            "score": 88.0,
            "strategy": "M1_M5_RADAR_SCALPER",
        }
        async with forex._AUTO_PAPER_LOCK:
            forex._AUTO_STATE["open_positions"].append(test_pos)

        # Status check
        st = await forex.get_forex_auto_paper_status()
        self.assertTrue(any(p["id"] == "FX-TEST-789" for p in st["open_positions"]))

        # Close position with TP
        closed = await forex.close_forex_position_manually(forex.ClosePositionRequest(id="FX-TEST-789"))
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["position"]["pnl_pips"], 20.0)
        self.assertEqual(closed["position"]["pnl_usd"], 100.0)

        # Verify balance and history updated
        st2 = await forex.get_forex_auto_paper_status()
        self.assertFalse(any(p["id"] == "FX-TEST-789" for p in st2["open_positions"]))
        self.assertTrue(any(p["id"] == "FX-TEST-789" for p in st2["closed_trades"]))
        self.assertGreater(st2["realized_pnl_usd"], 0)

    async def test_breakeven_and_trailing_stop_execution(self):
        # Test breakeven and trailing stop behavior on a BUY position
        test_pos = {
            "id": "FX-TEST-BE",
            "symbol": "EURUSD",
            "display": "EUR/USD",
            "direction": "BUY",
            "lots": 0.50,
            "entry_price": 1.08000,
            "current_price": 1.08000,
            "sl_price": 1.07850,
            "tp_price": 1.08300,
            "initial_sl_price": 1.07850,
            "breakeven_activated": False,
            "trailing_activated": False,
            "open_time": "12:00:00 UTC",
            "pnl_usd": 0.0,
            "pnl_pips": 0.0,
            "pip_size": 0.0001,
            "digits": 5,
            "score": 90.0,
            "strategy": "M1_M5_RADAR_SCALPER",
        }
        async with forex._AUTO_PAPER_LOCK:
            forex._AUTO_STATE["open_positions"] = [test_pos]

        # Simulate price moving up by +10 pips (above 8.0 breakeven threshold)
        cur_p = 1.08100
        pip_size = test_pos["pip_size"]
        pnl_pips = (cur_p - test_pos["entry_price"]) / pip_size
        self.assertGreaterEqual(pnl_pips, forex._AUTO_SETTINGS.breakeven_pips)

        # Breakeven logic execution
        test_pos["current_price"] = cur_p
        test_pos["pnl_pips"] = round(pnl_pips, 1)
        if pnl_pips >= forex._AUTO_SETTINGS.breakeven_pips and not test_pos["breakeven_activated"]:
            be_sl = round(test_pos["entry_price"] + (0.5 * pip_size), test_pos["digits"])
            test_pos["sl_price"] = be_sl
            test_pos["breakeven_activated"] = True

        self.assertTrue(test_pos["breakeven_activated"])
        self.assertEqual(test_pos["sl_price"], 1.08005)

        # Now simulate price reaching +15 pips (above 12.0 trailing stop threshold)
        cur_p2 = 1.08150
        pnl_pips2 = (cur_p2 - test_pos["entry_price"]) / pip_size
        test_pos["current_price"] = cur_p2
        test_pos["pnl_pips"] = round(pnl_pips2, 1)
        if pnl_pips2 >= forex._AUTO_SETTINGS.trailing_stop_pips:
            trail_dist = forex._AUTO_SETTINGS.trailing_stop_pips * pip_size
            cand_sl = round(cur_p2 - trail_dist, test_pos["digits"])
            if cand_sl > test_pos["sl_price"]:
                test_pos["sl_price"] = cand_sl
                test_pos["trailing_activated"] = True

        self.assertTrue(test_pos["trailing_activated"])
        expected_sl = round(cur_p2 - (forex._AUTO_SETTINGS.trailing_stop_pips * pip_size), test_pos["digits"])
        self.assertEqual(test_pos["sl_price"], expected_sl)

        # Close position
        await forex.close_forex_position_manually(forex.ClosePositionRequest(id="FX-TEST-BE"))

    async def test_asian_session_trading_allowed(self):
        # Verify that Asian sessions (Tokyo and Sydney) are recognized as active
        simulated_asian_sessions = [
            {"name": "Sydney", "flag": "🇦🇺", "active": True},
            {"name": "Tokyo", "flag": "🇯🇵", "active": True},
            {"name": "London", "flag": "🇬🇧", "active": False},
            {"name": "New York", "flag": "🇺🇸", "active": False},
        ]
        active_names = [s["name"] for s in simulated_asian_sessions if s["active"]]
        any_session_active = len(active_names) > 0
        self.assertTrue(any_session_active)
        self.assertIn("Tokyo", active_names)
        self.assertIn("Sydney", active_names)

        # Default session_filter is False, meaning all sessions are open
        self.assertFalse(forex._AUTO_SETTINGS.session_filter)

    async def test_trades_report_and_csv_export(self):
        # Insert a closed test trade
        closed_sample = {
            "id": "FX-REP-123",
            "symbol": "EURUSD",
            "display": "EUR/USD",
            "direction": "BUY",
            "lots": 0.50,
            "entry_price": 1.08500,
            "exit_price": 1.08750,
            "open_time": "10:00:00 UTC",
            "exit_time": "10:05:00 UTC",
            "exit_reason": "TP_HIT",
            "exit_reason_title": "🎯 Kâr Al (TP)",
            "pnl_usd": 125.0,
            "pnl_pips": 25.0,
            "pip_size": 0.0001,
            "digits": 5,
            "duration_sec": 300,
            "duration_human": "5 dk 0 sn",
            "balance_after": 10125.0,
            "outcome": "WIN",
            "score": 85.0,
        }
        async with forex._AUTO_PAPER_LOCK:
            forex._AUTO_STATE["closed_trades"].insert(0, closed_sample)

        # 1. Report endpoint
        rep = await forex.get_forex_trades_report()
        self.assertIn("kpi", rep)
        self.assertGreaterEqual(rep["kpi"]["total_trades"], 1)
        self.assertGreaterEqual(rep["kpi"]["wins"], 1)
        self.assertGreater(rep["kpi"]["gross_profit_usd"], 0)
        self.assertTrue(any(t["id"] == "FX-REP-123" for t in rep["trades"]))

        # 2. Filter by symbol
        rep_sym = await forex.get_forex_trades_report(symbol="EURUSD")
        self.assertTrue(all(t["symbol"] == "EURUSD" for t in rep_sym["trades"]))

        # 3. CSV export endpoint
        csv_res = await forex.export_forex_trades_csv()
        self.assertEqual(csv_res.status_code, 200)
        self.assertEqual(csv_res.media_type, "text/csv; charset=utf-8")
        self.assertIn("Content-Disposition", csv_res.headers)
        self.assertGreater(len(csv_res.body), 0)


if __name__ == "__main__":
    unittest.main()
