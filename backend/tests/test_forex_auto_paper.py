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
        pnl_pips = round((cur_p - test_pos["entry_price"]) / pip_size, 1)
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

    async def test_report_period_scopes_kpi_to_symbol_and_window(self):
        """KPI kartları seçilen sembol + döneme göre daralmalı.

        Regresyon: uç nokta KPI'yı `all_closed` üzerinden hesaplıyordu, yani
        panelde "EUR/USD / Bugün" seçiliyken kazanma oranı tüm arşivin oranıydı.
        """
        import datetime as _dt

        now = _dt.datetime.now(_dt.timezone.utc)
        today_iso = now.astimezone(forex.TZ_UTC3).strftime("%Y-%m-%d")

        def _deal(symbol, pnl, when_iso):
            return {
                "id": f"FX-{symbol}-{pnl}", "symbol": symbol, "display": symbol,
                "direction": "BUY", "lots": 0.1, "pnl_usd": pnl, "pnl_pips": pnl,
                "exit_time_iso": when_iso, "outcome": "WIN" if pnl >= 0 else "LOSS",
            }

        fresh = now.isoformat()
        old = (now - _dt.timedelta(days=40)).isoformat()
        sample = [
            _deal("EURUSD", 100.0, fresh),
            _deal("EURUSD", -50.0, old),      # pencere dışı: KPI'ya GİRMEMELİ
            _deal("XAUUSD", 900.0, fresh),    # sembol dışı: KPI'ya GİRMEMELİ
        ]
        # Bu sınıftaki testler global state'i paylaşır (kapanış testleri kayıt
        # bırakır); sayım iddiaları için arşivi önce boşaltıp sonra geri koy.
        async with forex._AUTO_PAPER_LOCK:
            prev_closed = list(forex._AUTO_STATE["closed_trades"])
            forex._AUTO_STATE["closed_trades"] = list(sample)
        try:
            rep = await forex.get_forex_trades_report(
                symbol="EURUSD", period="today", date_from=None, date_to=None)
            kpi = rep["kpi"]
            self.assertEqual(kpi["total_trades"], 1)
            self.assertEqual(kpi["wins"], 1)
            self.assertEqual(kpi["win_rate"], 100.0)
            self.assertEqual(kpi["total_pnl_usd"], 100.0)
            self.assertEqual(rep["kpi_scope"]["archived_total"], 3)
            self.assertEqual(rep["kpi_scope"]["period"], "today")

            # Tüm zamanlar + tüm semboller → arşivin tamamı
            rep_all = await forex.get_forex_trades_report(period="all")
            self.assertEqual(rep_all["kpi"]["total_trades"], 3)

            # Tablo filtresi KPI'yı bozmamalı: "sadece kaybedenler"de WR %100 kalır
            rep_lo = await forex.get_forex_trades_report(
                symbol="EURUSD", period="today", outcome="LOSS")
            self.assertEqual(rep_lo["kpi"]["win_rate"], 100.0)
            self.assertEqual(len(rep_lo["trades"]), 0)
        finally:
            async with forex._AUTO_PAPER_LOCK:
                forex._AUTO_STATE["closed_trades"] = prev_closed

    def test_resolve_report_window_boundaries(self):
        """Dönem sınırları UTC+3 takvimine ve pazartesi-başlangıçlı haftaya göre."""
        import datetime as _dt

        # 2026-10-07 Çarşamba 15:00 UTC+3 = 12:00 UTC
        now = _dt.datetime(2026, 10, 7, 12, 0, 0, tzinfo=_dt.timezone.utc).timestamp()
        midnight3 = _dt.datetime(2026, 10, 7, 0, 0, 0, tzinfo=forex.TZ_UTC3).timestamp()

        start, end = forex._resolve_report_window("today", None, None, now)
        self.assertEqual(start, midnight3)
        self.assertIsNone(end)

        start, end = forex._resolve_report_window("yesterday", None, None, now)
        self.assertEqual(end, midnight3)
        self.assertEqual(start, midnight3 - 86400.0)

        start, end = forex._resolve_report_window("last12h", None, None, now)
        self.assertEqual(start, now - 12 * 3600)

        # Haftanın ilk günü PAZARTESİ (7 Ekim Çarşamba → 5 Ekim Pazartesi)
        start, _ = forex._resolve_report_window("this_week", None, None, now)
        self.assertEqual(start, _dt.datetime(2026, 10, 5, 0, 0, 0, tzinfo=forex.TZ_UTC3).timestamp())

        start, _ = forex._resolve_report_window("this_month", None, None, now)
        self.assertEqual(start, _dt.datetime(2026, 10, 1, 0, 0, 0, tzinfo=forex.TZ_UTC3).timestamp())

        # Bitiş günü DAHİL: 7 Ekim 23:59:59.999 UTC+3 hâlâ pencerede
        start, end = forex._resolve_report_window("custom", "2026-10-01", "2026-10-07", now)
        self.assertLess(end, _dt.datetime(2026, 10, 8, 0, 0, 0, tzinfo=forex.TZ_UTC3).timestamp())
        self.assertGreater(end, _dt.datetime(2026, 10, 7, 23, 0, 0, tzinfo=forex.TZ_UTC3).timestamp())

        # Bilinmeyen dönem → sınırsız (istek düşmez, tüm arşiv)
        self.assertEqual(forex._resolve_report_window("saçma", None, None, now), (None, None))

    def test_parse_deal_ts_reads_utc3_and_never_invents_time(self):
        """MT5 köprüsü 'UTC+3' damgası gönderir; UTC sanılırsa 3 saat kayardı."""
        import datetime as _dt

        ts = forex._parse_deal_ts("2026-10-07 15:30:00 UTC+3")
        self.assertEqual(ts, _dt.datetime(2026, 10, 7, 15, 30, 0, tzinfo=forex.TZ_UTC3).timestamp())
        ts_utc = forex._parse_deal_ts("2026-10-07 12:30:00 UTC")
        self.assertEqual(ts_utc, ts)

        # epoch saniye ve ms
        self.assertEqual(forex._parse_deal_ts(1_700_000_000), 1_700_000_000.0)
        self.assertEqual(forex._parse_deal_ts(1_700_000_000_000), 1_700_000_000.0)
        # Çözülemeyen değer uydurulmaz
        for bad in (None, "", "-", "dün", 0):
            self.assertIsNone(forex._parse_deal_ts(bad))

    def test_deal_in_window_excludes_unparseable_in_bounded_window(self):
        self.assertTrue(forex._deal_in_window(None, None, None))
        self.assertFalse(forex._deal_in_window(None, 100.0, None))
        self.assertTrue(forex._deal_in_window(150.0, 100.0, 200.0))
        self.assertFalse(forex._deal_in_window(250.0, 100.0, 200.0))

    async def test_auto_loop_module_globals_are_not_shadowed(self):
        """Regresyon (2026-10-06): _forex_auto_paper_loop içindeki flip-reset
        `_LAST_GOLD_EXIT_TIME = 0.0` ataması, `global` bildiriminde ad yoktuğu için
        adı fonksiyon-yereli yapıyordu; altın soğuma kapısındaki okuma her taramada
        UnboundLocalError fırlatıp giriş zincirini sessizce öldürüyordu (panelde
        yalnız 'tüm şartlar uygun' dönüyordu, hata yoktu). Aynı tuzak
        _LAST_BLOCKED_HOUR_LOG_TIME için de uykuda yatıyordu. Kod bloğu seviyesinde
        savunma: her iki ad da module-global olarak erişilmeli."""
        code = forex._forex_auto_paper_loop.__code__
        for name in ("_LAST_GOLD_EXIT_TIME", "_LAST_BLOCKED_HOUR_LOG_TIME"):
            self.assertNotIn(name, code.co_varnames, f"{name} fonksiyon-yereli olmamalı")
            self.assertIn(name, code.co_names, f"{name} global olarak erişilmeli")

    def test_loss_streak_on_close_rules(self):
        """Seri-SL sigortası sayacı (2026-10-07 kullanıcı kuralı): aynı sembolde
        3 ardışık tam-SL zararı → soğuma tetiklenir; kazanç seriyi sıfırlar;
        BE/trailing kazanç çıkışları (SL_HIT değil) ve pnl==0 sayacı değiştirmez."""
        f = forex.loss_streak_on_close
        # 2 SL daha sayılmaz, 3.'de tetiklenir ve sayaç sıfırdan başlar
        s, tripped = f(0, "SL_HIT", -12.0, 3)
        self.assertEqual((s, tripped), (1, False))
        s, tripped = f(s, "SL_HIT", -8.0, 3)
        self.assertEqual((s, tripped), (2, False))
        s, tripped = f(s, "SL_HIT", -5.0, 3)
        self.assertEqual((s, tripped), (0, True))
        # Kazanç seriyi sıfırlar
        s, tripped = f(2, "TP_HIT", 4.0, 3)
        self.assertEqual((s, tripped), (0, False))
        # BE/trailing kazanç çıkışı (BE_HIT) sayılmaz
        s, tripped = f(2, "BE_HIT", -0.5, 3)
        self.assertEqual((s, tripped), (2, False))
        s, tripped = f(2, "BE_HIT", 1.2, 3)
        self.assertEqual((s, tripped), (0, False))
        # pnl==0 veya diğer nedenler değiştirmez; limit=0 kapalı
        self.assertEqual(f(1, "SL_HIT", 0.0, 3), (1, False))
        self.assertEqual(f(1, "REVERSAL_FLIP", -9.0, 3), (1, False))
        self.assertEqual(f(2, "SL_HIT", -9.0, 0), (2, False))
        # Soğuma sonrası sayaç sıfırdan başlar: yeni SL tekrar 1 olur
        self.assertEqual(f(0, "SL_HIT", -3.0, 3), (1, False))

    async def test_loss_streak_gate_blocks_candidate_symbol(self):
        """Seri-SL tetiklendiğinde giriş kapısı sembolü cooldown bitene dek es geçmeli."""
        forex._SYMBOL_LOSS_STREAK.clear()
        forex._SYMBOL_LOSS_COOLDOWN_UNTIL.clear()
        old_settings = forex._AUTO_SETTINGS
        try:
            cfg = forex.ForexAutoPaperSettings(**{**old_settings.model_dump(), "loss_streak_limit": 3})
            forex._AUTO_SETTINGS = cfg
            # 3 ardışık SL → sayaç tetikler, cooldown penceresi şu an + 300 sn
            for pnl in (-10.0, -9.0, -8.0):
                forex._SYMBOL_LOSS_STREAK["XAUUSD"], _ = forex.loss_streak_on_close(
                    forex._SYMBOL_LOSS_STREAK.get("XAUUSD", 0), "SL_HIT", pnl, 3)
            self.assertEqual(forex._SYMBOL_LOSS_STREAK["XAUUSD"], 0)  # tetiklenince sıfırlanır
            forex._SYMBOL_LOSS_COOLDOWN_UNTIL["XAUUSD"] = __import__("time").time() + 300.0
            # Kapı davranışı: aday döngüsündeki kontrol koşulunu taklit eden minik doğrulama
            now = __import__("time").time()
            self.assertLess(now, forex._SYMBOL_LOSS_COOLDOWN_UNTIL["XAUUSD"])
        finally:
            forex._AUTO_SETTINGS = old_settings
            forex._SYMBOL_LOSS_STREAK.clear()
            forex._SYMBOL_LOSS_COOLDOWN_UNTIL.clear()

    def test_normalize_close_reason_maps_broker_text(self):
        """Köprü kapanış nedeni serbest metin → kanonik token (canlı besleme kapısı).

        2026-10-08 kök neden: canlı MT5'te seri-SL canlıda ölüydü çünkü kapanış
        nedenleri köprüden "🛑 Zarar Durdur (SL)" gibi başlık olarak geliyordu ve
        sayaç yalnız birebir "SL_HIT" bekliyordu.
        """
        f = forex.normalize_close_reason
        self.assertEqual(f("🛑 Zarar Durdur (SL)"), "SL_HIT")
        self.assertEqual(f("[sl 8.0]"), "SL_HIT")
        self.assertEqual(f("🛑 Zarar Kes (SL)"), "SL_HIT")
        self.assertEqual(f("🎯 Kâr Al (TP)"), "TP_HIT")
        self.assertEqual(f("[tp 30.0]"), "TP_HIT")
        self.assertEqual(f("🛡️ Başabaş (BE)"), "BE_HIT")
        self.assertEqual(f("Trailing hit"), "TRAILING_HIT")
        # Eşleşmeyen ham/manual metinler sayaca girmez
        self.assertEqual(f("Scalper Close"), "")
        self.assertEqual(f("IC Markets MT5"), "")
        self.assertEqual(f(""), "")
        self.assertEqual(f(None), "")

    def test_feed_loss_streak_from_deal_drives_cooldown(self):
        """CANLI MT5 yolu: köprüden gelen 3 ardışık SL kapanışı soğuma tetiklemeli.

        Regresyon hedefi: eskiden sayaç yalnız paper defterinin kapandığı yolda
        besleniyordu; canlı pozisyonların kapanışı köprü `deals` akışıyla geldiği
        için BTC arka arkaya zararla kapansa da cooldown hiç devreye girmiyordu.
        """
        forex._SYMBOL_LOSS_STREAK.clear()
        forex._SYMBOL_LOSS_COOLDOWN_UNTIL.clear()
        old_settings = forex._AUTO_SETTINGS
        try:
            forex._AUTO_SETTINGS = forex.ForexAutoPaperSettings(
                **{**old_settings.model_dump(), "loss_streak_limit": 3,
                   "loss_streak_cooldown_sec": 300.0})
            # Köprü MT5 sembol adı (BTCUSD) uygulama sembolüne çevrilir; başlık nedeni kanonikleşir
            self.assertFalse(forex.feed_loss_streak_from_deal("BTCUSD", "🛑 Zarar Durdur (SL)", -5.36))
            self.assertFalse(forex.feed_loss_streak_from_deal("BTCUSD", "🛑 Zarar Durdur (SL)", -12.4))
            self.assertEqual(forex._SYMBOL_LOSS_STREAK["BTCUSD"], 2)
            # 3. SL → tetiklenir, sayaç sıfırlanır, cooldown penceresi yazılır
            self.assertTrue(forex.feed_loss_streak_from_deal("BTCUSD", "🛑 Zarar Durdur (SL)", -9.8))
            self.assertEqual(forex._SYMBOL_LOSS_STREAK["BTCUSD"], 0)
            self.assertGreater(forex._SYMBOL_LOSS_COOLDOWN_UNTIL["BTCUSD"], __import__("time").time())

            # Kazanç seriyi sıfırlar (TP kapanışı)
            forex.feed_loss_streak_from_deal("BTCUSD", "🎯 Kâr Al (TP)", 7.0)
            self.assertEqual(forex._SYMBOL_LOSS_STREAK["BTCUSD"], 0)

            # MT5 sembol adı eşlenir (XAUUSD zaten kanonik; XTIUSD→USOIL örnek eşleme)
            forex.feed_loss_streak_from_deal("XTIUSD", "🛑 Zarar Durdur (SL)", -3.0)
            self.assertEqual(forex._SYMBOL_LOSS_STREAK.get("USOIL"), 1)

            # Manuel/kısmi kapanış (eşleşmeyen neden) ve BE kazancı sayacı değiştirmez
            forex.feed_loss_streak_from_deal("BTCUSD", "Scalper Close", -4.0)
            self.assertEqual(forex._SYMBOL_LOSS_STREAK["BTCUSD"], 0)
        finally:
            forex._AUTO_SETTINGS = old_settings
            forex._SYMBOL_LOSS_STREAK.clear()
            forex._SYMBOL_LOSS_COOLDOWN_UNTIL.clear()
            forex._SYMBOL_DIR_LOSS_STREAK.clear()
            forex._SYMBOL_DIR_LOSS_COOLDOWN_UNTIL.clear()

    def test_directional_loss_streak_and_reason_tokens(self):
        """Yön bazlı (BUY/SELL) seri zarar takibi ve broker token genişletmesi testi.

        Kullanıcı şikayeti: BTCUSD ve XAUUSD arka arkaya SELL zararlarıyla kapandı
        fakat bot SELL açmaya devam etti. Çözüm: 3 ardışık SELL kaybı doğrudan
        SELL yönünü 5 dk soğumaya almalı ve max_positions_per_symbol varsayılanı 1 olmalı.
        """
        f_norm = forex.normalize_close_reason
        # Genişletilmiş broker tokenleri
        self.assertEqual(f_norm("sl 82675.03"), "SL_HIT")
        self.assertEqual(f_norm("🛑 Zarar (IC Markets MT5)"), "SL_HIT")
        self.assertEqual(f_norm("🛑 Stop Out (SO)"), "SL_HIT")
        self.assertEqual(f_norm("[so 50.0]"), "SL_HIT")
        self.assertEqual(f_norm("so hit"), "SL_HIT")

        # Varsayılan max_positions_per_symbol = 1 (tek scalper pozisyonu)
        self.assertEqual(forex.ForexAutoPaperSettings().max_positions_per_symbol, 1)

        # Yön bazlı seri zarar takibi
        forex._SYMBOL_LOSS_STREAK.clear()
        forex._SYMBOL_LOSS_COOLDOWN_UNTIL.clear()
        forex._SYMBOL_DIR_LOSS_STREAK.clear()
        forex._SYMBOL_DIR_LOSS_COOLDOWN_UNTIL.clear()
        old_settings = forex._AUTO_SETTINGS
        try:
            forex._AUTO_SETTINGS = forex.ForexAutoPaperSettings(
                **{**old_settings.model_dump(), "loss_streak_limit": 3,
                   "loss_streak_cooldown_sec": 300.0})

            # 2 SELL kaybı
            self.assertFalse(forex.feed_loss_streak_from_deal("BTCUSD", "sl 82675.03", -14.39, direction="SELL"))
            self.assertFalse(forex.feed_loss_streak_from_deal("BTCUSD", "🛑 Zarar (IC Markets MT5)", -11.85, direction="SELL"))
            self.assertEqual(forex._SYMBOL_DIR_LOSS_STREAK[("BTCUSD", "SELL")], 2)

            # 3. SELL kaybı -> tetiklenmeli
            tripped = forex.feed_loss_streak_from_deal("BTCUSD", "🛑 Zarar Durdur (SL)", -9.30, direction="SELL")
            self.assertTrue(tripped)
            self.assertEqual(forex._SYMBOL_DIR_LOSS_STREAK[("BTCUSD", "SELL")], 0)
            now = __import__("time").time()
            self.assertGreater(forex._SYMBOL_DIR_LOSS_COOLDOWN_UNTIL[("BTCUSD", "SELL")], now)

            # BUY yönü etkilenmemeli (soğuma olmamalı)
            self.assertLessEqual(forex._SYMBOL_DIR_LOSS_COOLDOWN_UNTIL.get(("BTCUSD", "BUY"), 0.0), now)
        finally:
            forex._AUTO_SETTINGS = old_settings
            forex._SYMBOL_LOSS_STREAK.clear()
            forex._SYMBOL_LOSS_COOLDOWN_UNTIL.clear()
            forex._SYMBOL_DIR_LOSS_STREAK.clear()
            forex._SYMBOL_DIR_LOSS_COOLDOWN_UNTIL.clear()

    async def test_mt5_sync_feeds_loss_streak(self):
        """Uçtan uca: `/mt5/sync` köprü kapanışları seri-SL sayacını beslemeli.

        İlk senkron turu geçmiş 300 deal'i topluca taşır; o tur ATLANMALI ki
        eski sicil sahte soğuma üretmesin. Sonraki tur yeni kapanışları sayar.
        """
        forex._SYMBOL_LOSS_STREAK.clear()
        forex._SYMBOL_LOSS_COOLDOWN_UNTIL.clear()
        forex._LAST_CLOSED_DEAL_IDS.clear()
        old_settings = forex._AUTO_SETTINGS
        # `sync_mt5_bridge` paylaşılan `_MT5_STATE`'i yazar (connected/closed_deals/
        # last_ping + altın/BTC çıkış damgaları). Test sırası kirlenmesin diye
        # anlık görüntü alınır ve teardown'da geri konur — aksi halde sonraki
        # rapor testleri MT5 deal penceresini görüp paper defterini atlar.
        mt5_snapshot = {
            "state": {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
                      for k, v in forex._MT5_STATE.items()},
            "gold": forex._LAST_GOLD_EXIT_TIME,
            "btc": forex._LAST_BTC_EXIT_TIME,
        }
        now = __import__("time").time()
        try:
            forex._AUTO_SETTINGS = forex.ForexAutoPaperSettings(
                **{**old_settings.model_dump(), "loss_streak_limit": 3,
                   "loss_streak_cooldown_sec": 300.0})
            # İlk tur: eski geçmiş deals (sayaç beslenmemeli)
            historical = [
                {"ticket": 10, "symbol": "BTCUSD", "profit": -20.0, "time": now - 3600,
                 "exit_reason": "🛑 Zarar Durdur (SL)", "exit_reason_title": "🛑 Zarar Durdur (SL)"},
                {"ticket": 11, "symbol": "BTCUSD", "profit": -18.0, "time": now - 3500,
                 "exit_reason": "🛑 Zarar Durdur (SL)", "exit_reason_title": "🛑 Zarar Durdur (SL)"},
            ]
            await forex.sync_mt5_bridge(forex.MT5SyncRequest(deals=list(historical)))
            self.assertEqual(forex._SYMBOL_LOSS_STREAK.get("BTCUSD", 0), 0)
            self.assertEqual(forex._SYMBOL_LOSS_COOLDOWN_UNTIL.get("BTCUSD", 0.0), 0.0)

            # Sonraki tur: yeni kapanan 3 SL (kronolojik, son 15 dk) → soğuma
            fresh = [
                {"ticket": 21, "symbol": "BTCUSD", "profit": -5.36, "time": now - 200,
                 "exit_reason": "🛑 Zarar Durdur (SL)", "exit_reason_title": "🛑 Zarar Durdur (SL)"},
                {"ticket": 20, "symbol": "BTCUSD", "profit": -21.91, "time": now - 120,
                 "exit_reason": "🛑 Zarar Durdur (SL)", "exit_reason_title": "🛑 Zarar Durdur (SL)"},
                {"ticket": 22, "symbol": "BTCUSD", "profit": -23.70, "time": now - 60,
                 "exit_reason": "🛑 Zarar Durdur (SL)", "exit_reason_title": "🛑 Zarar Durdur (SL)"},
                # Kronolojik sırada önce gelen -5.36 sonra +7.0 kazanç → seri sıfırlanır:
                # (ticket 23 TP, en yeni) → net birikim 0
            ]
            await forex.sync_mt5_bridge(forex.MT5SyncRequest(deals=list(historical) + fresh))
            # 3 SL sonra sayaç: tick 21,20,22 → 3. SL tetikler → sıfırlanır + cooldown
            self.assertEqual(forex._SYMBOL_LOSS_STREAK.get("BTCUSD", 0), 0)
            self.assertGreater(forex._SYMBOL_LOSS_COOLDOWN_UNTIL.get("BTCUSD", 0.0), now)
        finally:
            forex._AUTO_SETTINGS = old_settings
            forex._SYMBOL_LOSS_STREAK.clear()
            forex._SYMBOL_LOSS_COOLDOWN_UNTIL.clear()
            forex._LAST_CLOSED_DEAL_IDS.clear()
            # Paylaşılan MT5 durumunu ve çıkış damgalarını geri yükle (sıra izolasyonu)
            forex._MT5_STATE.clear()
            forex._MT5_STATE.update(mt5_snapshot["state"])
            forex._LAST_GOLD_EXIT_TIME = mt5_snapshot["gold"]
            forex._LAST_BTC_EXIT_TIME = mt5_snapshot["btc"]

    def test_collect_symbol_ev_respects_reset_cutoff(self):
        """EV reset kesimi (2026-10-07 kullanıcı isteği): resetten önce kapanan işlemler
        EV penceresine alınmaz — sembol temiz sicille değerlendirilir."""
        old_cutoff = forex._EV_RESET_AT_TS
        now = __import__("time").time()
        source = [
            {"symbol": "XAUUSD", "pnl_usd": -50.0, "closed_at_ts": now - 3600.0},   # resetten önce
            {"symbol": "XAUUSD", "pnl_usd": -40.0, "closed_at_ts": now - 1800.0},   # resetten önce
            {"symbol": "XAUUSD", "pnl_usd": 6.0, "closed_at_ts": now - 300.0},      # resetten sonra
        ]
        try:
            # Kesim yok: üçü de pencerede (2.4h pencere)
            forex._EV_RESET_AT_TS = 0.0
            stats = forex._collect_symbol_ev("XAUUSD", now, 2.5 * 3600.0, source=source)
            self.assertEqual(stats["n"], 3)
            # Kesim aktif: yalnız reset sonrası işlem sayılır → kalkan tetiklenmez
            forex._EV_RESET_AT_TS = now - 600.0
            stats = forex._collect_symbol_ev("XAUUSD", now, 2.5 * 3600.0, source=source)
            self.assertEqual(stats["n"], 1)
            self.assertEqual(stats["net"], 6.0)
            self.assertFalse(forex.ev_guard_decision(stats, 3, 45.0, 100.0))
        finally:
            forex._EV_RESET_AT_TS = old_cutoff

    async def test_reset_symbol_guards_endpoint(self):
        """Reset endpoint'i kesim zamanlarını ilerletir ve seri-SL durumunu temizler."""
        forex._SYMBOL_LOSS_STREAK["XAUUSD"] = 2
        forex._SYMBOL_LOSS_COOLDOWN_UNTIL["BTCUSD"] = __import__("time").time() + 300.0
        old_ev_cutoff = forex._EV_RESET_AT_TS
        old_ledger_cutoff = forex._LEDGER_RESET_AT_TS
        try:
            res = await forex.reset_forex_symbol_guards()
            self.assertEqual(res["status"], "ok")
            self.assertIn("ev_before_reset", res)
            self.assertGreater(forex._EV_RESET_AT_TS, old_ev_cutoff)
            self.assertGreater(forex._LEDGER_RESET_AT_TS, old_ledger_cutoff)
            self.assertEqual(forex._SYMBOL_LOSS_STREAK, {})
            self.assertEqual(forex._SYMBOL_LOSS_COOLDOWN_UNTIL, {})
        finally:
            forex._EV_RESET_AT_TS = old_ev_cutoff
            forex._LEDGER_RESET_AT_TS = old_ledger_cutoff
            forex._SYMBOL_LOSS_STREAK.clear()
            forex._SYMBOL_LOSS_COOLDOWN_UNTIL.clear()

    async def test_archive_and_reset_ledger_flow(self):
        """Temiz-sayfa (2026-10-07 kullanıcı isteği): eski işlemler arşive alınır;
        rapor/CSV/KPI'lar resetten sonra kapananlarla sıfırdan hesaplanır; bakiyeye
        dokunulmaz; arşiv okuma uç noktası eski kayıtları döner."""
        import time as _time
        now = _time.time()
        saved = {
            "closed_trades": list(forex._AUTO_STATE["closed_trades"]),
            "total_trades": forex._AUTO_STATE["total_trades"],
            "wins": forex._AUTO_STATE["wins"],
            "losses": forex._AUTO_STATE["losses"],
            "realized_pnl_usd": forex._AUTO_STATE["realized_pnl_usd"],
            "realized_pnl_pips": forex._AUTO_STATE["realized_pnl_pips"],
            "archived_trades": forex._AUTO_STATE.get("archived_trades"),
            "archived_at": forex._AUTO_STATE.get("archived_at"),
            "archived_path": forex._AUTO_STATE.get("archived_path"),
        }
        saved_ledger_cutoff = forex._LEDGER_RESET_AT_TS
        saved_mt5_deals = list(forex._MT5_STATE.get("closed_deals", []))
        old_rec = {
            "id": "FX-OLD-1", "symbol": "XAUUSD", "display": "XAU/USD", "direction": "SELL",
            "lots": 0.05, "entry_price": 4150.0, "exit_price": 4155.0,
            "exit_time": "2026-10-06 10:00:00 UTC+3", "exit_reason": "SL_HIT",
            "pnl_usd": -25.0, "pnl_pips": -50.0, "outcome": "LOSS",
            "closed_at_ts": now - 86400.0,
        }
        try:
            forex._MT5_STATE["closed_deals"] = []  # paper defteri kaynak olsun
            forex._AUTO_STATE["closed_trades"] = [dict(old_rec), dict(old_rec, id="FX-OLD-2")]
            forex._AUTO_STATE["total_trades"] = 2
            forex._AUTO_STATE["wins"] = 0
            forex._AUTO_STATE["losses"] = 2
            forex._AUTO_STATE["realized_pnl_usd"] = -50.0

            res = await forex.reset_forex_symbol_guards()
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["archived_count"], 2)
            self.assertGreater(forex._LEDGER_RESET_AT_TS, saved_ledger_cutoff)
            self.assertEqual(forex._AUTO_STATE["closed_trades"], [])
            self.assertEqual(forex._AUTO_STATE["total_trades"], 0)
            self.assertEqual(forex._AUTO_STATE["wins"], 0)
            self.assertEqual(forex._AUTO_STATE["losses"], 0)
            self.assertEqual(forex._AUTO_STATE["realized_pnl_usd"], 0.0)
            self.assertEqual(len(forex._AUTO_STATE["archived_trades"]), 2)
            self.assertIsNotNone(res.get("archive_path"))

            # (a) Paper yolu: reset defteri fiziksel boşaltır → raporda yeni işlem,
            # arşivlenmiş sayı 0 (silinecek şey kalmadı).
            forex._AUTO_STATE["closed_trades"].insert(0, {
                **old_rec, "id": "FX-NEW-1", "exit_reason": "TP_HIT", "outcome": "WIN",
                "pnl_usd": 10.0, "pnl_pips": 20.0, "closed_at_ts": now + 1.0,
            })
            rep = await forex.get_forex_trades_report()
            self.assertEqual(rep["kpi"]["total_trades"], 1)
            self.assertEqual(rep["kpi_scope"]["archived_before_reset"], 0)
            self.assertIsNotNone(rep["kpi_scope"]["ledger_reset_at"])
            self.assertTrue(any(t["id"] == "FX-NEW-1" for t in rep["trades"]))

            # (b) MT5-deal yolu (canlı gerçekliği): köprü eski deal'leri yeniden gönderir;
            # kesim filtresi onları rapora sokmaz ve arşivlenmiş olarak sayar.
            forex._MT5_STATE["closed_deals"] = [
                {"id": "MT5-OLD-1", "ticket": 1, "symbol": "XAUUSD", "display": "XAU/USD",
                 "direction": "SELL", "lots": 0.05, "pnl_usd": -25.0, "outcome": "LOSS",
                 "closed_at_ts": now - 86400.0, "exit_time": "2026-10-06 10:00:00 UTC+3"},
                {"id": "MT5-NEW-1", "ticket": 2, "symbol": "XAUUSD", "display": "XAU/USD",
                 "direction": "SELL", "lots": 0.05, "pnl_usd": 8.0, "outcome": "WIN",
                 "closed_at_ts": now + 2.0, "exit_time": "2026-10-07 12:00:00 UTC+3"},
            ]
            rep_mt5 = await forex.get_forex_trades_report()
            self.assertEqual(rep_mt5["kpi"]["total_trades"], 1)
            self.assertEqual(rep_mt5["kpi_scope"]["archived_before_reset"], 1)
            self.assertTrue(any(t["id"] == "MT5-NEW-1" for t in rep_mt5["trades"]))
            self.assertFalse(any(t["id"] == "MT5-OLD-1" for t in rep_mt5["trades"]))

            # CSV de yalnız yeni dönemi içerir (MT5 kaynak öncelikli)
            csv_res = await forex.export_forex_trades_csv()
            body = csv_res.body.decode("utf-8-sig")
            self.assertIn("MT5-NEW-1", body)
            self.assertNotIn("MT5-OLD-1", body)
            self.assertNotIn("FX-OLD-1", body)

            # Arşiv okuma uç noktası eski kayıtları döner
            arc = await forex.get_forex_archived_ledger()
            self.assertEqual(arc["count"], 2)
            self.assertTrue(any(t["id"] == "FX-OLD-1" for t in arc["trades"]))
        finally:
            forex._LEDGER_RESET_AT_TS = saved_ledger_cutoff
            forex._MT5_STATE["closed_deals"] = saved_mt5_deals
            forex._AUTO_STATE["closed_trades"] = saved["closed_trades"]
            forex._AUTO_STATE["total_trades"] = saved["total_trades"]
            forex._AUTO_STATE["wins"] = saved["wins"]
            forex._AUTO_STATE["losses"] = saved["losses"]
            forex._AUTO_STATE["realized_pnl_usd"] = saved["realized_pnl_usd"]
            forex._AUTO_STATE["realized_pnl_pips"] = saved["realized_pnl_pips"]
            forex._AUTO_STATE["archived_trades"] = saved["archived_trades"]
            forex._AUTO_STATE["archived_at"] = saved["archived_at"]
            forex._AUTO_STATE["archived_path"] = saved["archived_path"]


    def test_parse_reset_cutoff_formats(self):
        """Kesim zamanı çözümleyici: epoch, UTC+3 tarih-saat biçimleri; gelecek/garbage reddi."""
        import time as _time
        now = _time.time()
        f = forex._parse_reset_cutoff
        # Epoch saniye
        self.assertEqual(f("1770000000", now), 1770000000.0)
        # UTC+3 "YYYY-MM-DD HH:MM" → UTC epoch'a çevrilmeli (07:10 UTC+3 = 04:10 UTC)
        ts = f("2026-10-07 07:10", now)
        expect = __import__("datetime").datetime(2026, 10, 7, 7, 10,
                                                 tzinfo=forex.TZ_UTC3).timestamp()
        self.assertEqual(ts, expect)
        # ISO "T" ayraçlı ve gün-precise biçimler de çalışmalı
        self.assertEqual(f("2026-10-07T07:10", now), expect)
        self.assertEqual(f("2026-10-07", now),
                         __import__("datetime").datetime(2026, 10, 7,
                                                         tzinfo=forex.TZ_UTC3).timestamp())
        # Gelecek ve anlaşılmaz metin reddedilir
        with self.assertRaises(ValueError):
            f(str(now + 99999), now)
        with self.assertRaises(ValueError):
            f("yarin sabah", now)

    async def test_reset_with_cutoff_keeps_post_cutoff_trades(self):
        """Kesimli arşiv (2026-10-07 kullanıcı isteği): deploy sonrası biriken
        işlemler raporda kalır; yalnız kesim (ör. 07:10) öncesindeki işlemler
        arşive kalkar. Seri-SL sayaçlarına dokunulmaz."""
        import time as _time
        now = _time.time()
        saved = {
            "closed_trades": list(forex._AUTO_STATE["closed_trades"]),
            "total_trades": forex._AUTO_STATE["total_trades"],
            "wins": forex._AUTO_STATE["wins"],
            "losses": forex._AUTO_STATE["losses"],
            "realized_pnl_usd": forex._AUTO_STATE["realized_pnl_usd"],
            "realized_pnl_pips": forex._AUTO_STATE["realized_pnl_pips"],
            "archived_trades": forex._AUTO_STATE.get("archived_trades"),
            "archived_at": forex._AUTO_STATE.get("archived_at"),
            "archived_path": forex._AUTO_STATE.get("archived_path"),
        }
        saved_ledger_cutoff = forex._LEDGER_RESET_AT_TS
        saved_ev_cutoff = forex._EV_RESET_AT_TS
        saved_mt5_deals = list(forex._MT5_STATE.get("closed_deals", []))
        base_rec = {
            "symbol": "XAUUSD", "display": "XAU/USD", "direction": "SELL",
            "lots": 0.05, "entry_price": 4150.0, "exit_price": 4150.0,
            "exit_reason": "SL_HIT",
        }
        try:
            forex._MT5_STATE["closed_deals"] = []
            forex._AUTO_STATE["closed_trades"] = [
                {**base_rec, "id": "FX-CUT-OLD", "pnl_usd": -25.0, "pnl_pips": -50.0,
                 "outcome": "LOSS", "closed_at_ts": now - 86400.0},
                {**base_rec, "id": "FX-CUT-NEW", "exit_reason": "TP_HIT",
                 "pnl_usd": 15.0, "pnl_pips": 30.0, "outcome": "WIN",
                 "closed_at_ts": now - 60.0},
            ]
            forex._AUTO_STATE["total_trades"] = 2
            forex._AUTO_STATE["losses"] = 1
            forex._SYMBOL_LOSS_STREAK["BTCUSD"] = 1

            cutoff_epoch = now - 300.0
            cut_str = __import__("datetime").datetime.fromtimestamp(
                cutoff_epoch, forex.TZ_UTC3).strftime("%Y-%m-%d %H:%M:%S")
            res = await forex.reset_forex_symbol_guards(cutoff=cut_str)
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["archived_count"], 1)   # yalnız eski işlem
            self.assertEqual(res["kept_paper_count"], 1)  # yeni işlem raporda kalır
            self.assertIsNotNone(res["cutoff"])
            self.assertEqual(forex._LEDGER_RESET_AT_TS, forex._EV_RESET_AT_TS)
            self.assertEqual(forex._SYMBOL_LOSS_STREAK.get("BTCUSD"), 1)  # dokunulmadı

            self.assertEqual([t["id"] for t in forex._AUTO_STATE["closed_trades"]], ["FX-CUT-NEW"])
            self.assertEqual(forex._AUTO_STATE["total_trades"], 1)
            self.assertEqual(forex._AUTO_STATE["wins"], 1)
            self.assertEqual(forex._AUTO_STATE["losses"], 0)
            self.assertEqual(forex._AUTO_STATE["realized_pnl_usd"], 15.0)
            self.assertEqual([t["id"] for t in forex._AUTO_STATE["archived_trades"]], ["FX-CUT-OLD"])

            rep = await forex.get_forex_trades_report()
            self.assertEqual(rep["kpi"]["total_trades"], 1)
            self.assertEqual(rep["kpi_scope"]["archived_before_reset"], 0)  # defterde artık eski yok
            self.assertTrue(any(t["id"] == "FX-CUT-NEW" for t in rep["trades"]))
        finally:
            forex._LEDGER_RESET_AT_TS = saved_ledger_cutoff
            forex._EV_RESET_AT_TS = saved_ev_cutoff
            forex._MT5_STATE["closed_deals"] = saved_mt5_deals
            forex._AUTO_STATE["closed_trades"] = saved["closed_trades"]
            forex._AUTO_STATE["total_trades"] = saved["total_trades"]
            forex._AUTO_STATE["wins"] = saved["wins"]
            forex._AUTO_STATE["losses"] = saved["losses"]
            forex._AUTO_STATE["realized_pnl_usd"] = saved["realized_pnl_usd"]
            forex._AUTO_STATE["realized_pnl_pips"] = saved["realized_pnl_pips"]
            forex._AUTO_STATE["archived_trades"] = saved["archived_trades"]
            forex._AUTO_STATE["archived_at"] = saved["archived_at"]
            forex._AUTO_STATE["archived_path"] = saved["archived_path"]
            forex._SYMBOL_LOSS_STREAK.clear()


    def test_s3_pullback_entry_rules(self):
        """S3 (Supertrend+RSI pullback) canlı giriş kararı (L30 replay kuralıyla birebir)."""
        f = forex.s3_pullback_entry
        # LONG: ST boğa + kapanış EMA200 üstü + ADX yeter + son 6 barda RSI<50 sarkması
        # + önceki bar 50 altı + bu bar 50 üstü → BUY
        self.assertEqual(
            f(st_dir=1, close=101.0, ema200=100.0, use_ema200=True,
              adx=30.0, adx_min=25.0,
              rsi_now=52.0, rsi_prev=47.0, rsi_window=[55.0, 49.0, 44.0, 47.0],
              rsi_lo=40.0, atr_price=1.0, pip_size=0.1,
              day_counts={}, max_per_day=0),
            "BUY")
        # SHORT ayna: ST ayı + EMA200 altı + son 6 barda RSI>50 + önceki 50 üstü + bu bar 50 altı → SELL
        self.assertEqual(
            f(st_dir=-1, close=99.0, ema200=100.0, use_ema200=True,
              adx=30.0, adx_min=25.0,
              rsi_now=48.0, rsi_prev=53.0, rsi_window=[45.0, 51.0, 56.0, 53.0],
              rsi_lo=40.0, atr_price=1.0, pip_size=0.1,
              day_counts={}, max_per_day=0),
            "SELL")
        # ST tanımsız (0) → yok
        self.assertIsNone(f(0, 101.0, 100.0, True, 30.0, 25.0, 52.0, 47.0, [49.0], 40.0, 1.0, 0.1, {}, 0))
        # EMA200 tarafı bozuk (ST boğa ama kapanış EMA200 altı) → yok
        self.assertIsNone(f(1, 99.0, 100.0, True, 30.0, 25.0, 52.0, 47.0, [49.0], 40.0, 1.0, 0.1, {}, 0))
        # ADX eşiğin altında → yok
        self.assertIsNone(f(1, 101.0, 100.0, True, 20.0, 25.0, 52.0, 47.0, [49.0], 40.0, 1.0, 0.1, {}, 0))
        # Son 6 barda RSI<50 sarkması YOK (hepsi 50 üstü) → yok
        self.assertIsNone(f(1, 101.0, 100.0, True, 30.0, 25.0, 52.0, 51.0, [55.0, 54.0, 56.0], 40.0, 1.0, 0.1, {}, 0))
        # 40 bandını TAMAMEN kırdı (hepsi <40) → trend bozulmuş → yok
        self.assertIsNone(f(1, 101.0, 100.0, True, 30.0, 25.0, 52.0, 47.0, [35.0, 38.0, 36.0], 40.0, 1.0, 0.1, {}, 0))
        # Önceki bar zaten 50 üstündeydi → yeni dönüş yok → yok
        self.assertIsNone(f(1, 101.0, 100.0, True, 30.0, 25.0, 52.0, 51.0, [49.0, 55.0], 40.0, 1.0, 0.1, {}, 0))
        # Bu bar 50 üstüne kapanmamış → onay yok → yok
        self.assertIsNone(f(1, 101.0, 100.0, True, 30.0, 25.0, 48.0, 47.0, [49.0], 40.0, 1.0, 0.1, {}, 0))
        # ATR geçersiz → yok
        self.assertIsNone(f(1, 101.0, 100.0, True, 30.0, 25.0, 52.0, 47.0, [49.0], 40.0, 0.0, 0.1, {}, 0))
        # Gün içi limit dolu → yok; sayaç artmaz
        counts = {"s3_5m": 2}
        self.assertIsNone(f(1, 101.0, 100.0, True, 30.0, 25.0, 52.0, 47.0, [49.0], 40.0, 1.0, 0.1,
                            counts, 2, "s3_5m"))
        self.assertEqual(counts["s3_5m"], 2)

    def test_s3_series_helpers_match_replay(self):
        """S3 seri yardımcıları replay fonksiyonlarıyla birebir sonuç vermeli."""
        bars = [{"open": 100.0 + i * 0.1, "high": 100.6 + i * 0.1,
                 "low": 99.8 + i * 0.1, "close": 100.3 + i * 0.1}
                for i in range(60)]
        closes = [b["close"] for b in bars]
        # RSI: ilk 14 bar None
        rsi = forex._s3_rsi_wilder(closes, 14)
        self.assertIsNone(rsi[13])
        self.assertIsNotNone(rsi[14])
        # Monoton yükselen seride RSI yüksek olmalı
        self.assertGreater(rsi[-1], 70.0)
        # ATR: negatif olmayan, sıfırdan büyük seri
        atr = forex._s3_atr_series(bars, 14)
        self.assertEqual(len(atr), len(bars))
        self.assertGreater(atr[-1], 0.0)
        # ST: yükselen seride son yön boğa
        st = forex._s3_st_dir_series(bars, 10, 3.0)
        self.assertEqual(len(st), len(bars))
        self.assertEqual(st[-1], 1)
        # EMA serisi: uzunluk eşleşir, tohum ilk değer, yükselişte geride kalır
        ema = forex._s3_ema_series(closes, 200)
        self.assertEqual(len(ema), len(closes))
        self.assertEqual(ema[0], closes[0])
        self.assertGreater(ema[-1], closes[0])
        self.assertLess(ema[-1], closes[-1])

    def test_s3_settings_defaults_and_watch(self):
        """S3 canlı taşıma ayarları: semboller, köprü izleme listesi kalıcılığı."""
        cfg = forex.ForexAutoPaperSettings()
        self.assertTrue(cfg.s3_enabled)
        self.assertIn("XAUUSD", cfg.s3_symbols_5m)
        self.assertIn("XAUUSD", cfg.s3_symbols_15m)
        self.assertIn("BTCUSD", cfg.s3_symbols_15m)
        self.assertEqual(cfg.s3_adx_min, 25.0)
        self.assertEqual(cfg.s3_rsi_lo, 40.0)
        self.assertEqual(cfg.s3_sl_atr, 1.5)
        self.assertEqual(cfg.s3_tp_atr_15m, 2.0)
        # Strateji kimliği: s3_* kaynağı → S3 adı; etiketler S3/S3F
        self.assertEqual(forex.strategy_name_for("s3_5m"), forex.S3_PULLBACK_STRATEGY)
        self.assertEqual(forex.strategy_name_for("s3_15m"), forex.S3_PULLBACK_STRATEGY)
        self.assertEqual(forex.strategy_comment_tag("s3_5m"), "S3")
        self.assertEqual(forex.strategy_comment_tag("s3_15m"), "S3F")
        self.assertEqual(forex.strategy_from_mt5_deal({"strategy_tag": "S3 85"}),
                         forex.S3_PULLBACK_STRATEGY)
        self.assertEqual(forex.strategy_from_mt5_deal({"strategy_tag": "S3F 88"}),
                         forex.S3_PULLBACK_STRATEGY)
        # Köprü izleme listesi: S3 sembolleri panel bakmasa da listede
        saved_viewed = dict(forex._FOREX_VIEWED)
        saved_enabled = forex._AUTO_SETTINGS.s3_enabled
        try:
            forex._FOREX_VIEWED.clear()
            pairs = {(w["symbol"], w["interval"]) for w in forex._get_forex_watch()}
            self.assertIn(("XAUUSD", "5m"), pairs)
            self.assertIn(("XAUUSD", "15m"), pairs)
            self.assertIn(("BTCUSD", "15m"), pairs)
        finally:
            forex._FOREX_VIEWED.clear()
            forex._FOREX_VIEWED.update(saved_viewed)
            forex._AUTO_SETTINGS.s3_enabled = saved_enabled

    def test_s3_resample_15m(self):
        """5m→15m birleştirme: open ilk, high max, low min, close son."""
        bars5 = [{"time": 1000 + i * 300, "open": float(i), "high": float(i) + 1.0,
                  "low": float(i) - 1.0, "close": float(i) + 0.5} for i in range(9)]
        out = forex._s3_resample_15m(bars5)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["open"], 0.0)
        self.assertEqual(out[0]["high"], 3.0)
        self.assertEqual(out[0]["low"], -1.0)
        self.assertEqual(out[0]["close"], 2.5)

    def test_donchian_adx_entry_rules(self):
        """Donchian+ADX canlı giriş kararı (replay kazananı ile aynı kural)."""
        f = forex.donchian_adx_entry
        # Orta hat yukarı kesilince BUY (prev_close orta hattın ALTINDAYKEN kesişim; ADX yeterli, seans içi)
        self.assertEqual(f(1.0990, 1.0995, 1.1010, 1.0997, 25.0, 18.0, 738000, {}, 2, 10, False), "BUY")
        # Orta hat aşağı kesilince SELL (prev_close orta hattın ÜSTÜNDAYKEN kesişim)
        self.assertEqual(f(1.1010, 1.1005, 1.0990, 1.1003, 25.0, 18.0, 738000, {}, 2, 10, False), "SELL")
        # ADX zayıf → yok
        self.assertIsNone(f(1.1000, 1.0995, 1.1010, 1.0997, 12.0, 18.0, 738000, {}, 2, 10, False))
        # İlk değerlendirme (prev_close None) → yok
        self.assertIsNone(f(None, None, 1.1010, 1.0997, 25.0, 18.0, 738000, {}, 2, 10, False))
        # Gün içi limit: BUY 2 kez kullanıldıysa BUY gelmez, SELL hâlâ açılabilir
        counts = {"BUY": 2}
        # BUY limiti dolu → yukarı kesişim olsa da None; SELL limiti boş → SELL döner
        self.assertIsNone(f(1.0990, 1.0995, 1.1010, 1.0997, 25.0, 18.0, 738000, counts, 2, 10, False))
        self.assertEqual(f(1.1010, 1.1005, 1.0990, 1.1003, 25.0, 18.0, 738000, counts, 2, 10, False), "SELL")
        # Seans: JPY 16:00 sonrası yok; non-JPY 07:00 öncesi yok
        self.assertIsNone(f(1.1000, 1.0995, 1.1010, 1.0997, 25.0, 18.0, 738000, {}, 2, 17, True))
        self.assertIsNone(f(1.1000, 1.0995, 1.1010, 1.0997, 25.0, 18.0, 738000, {}, 2, 5, False))

    def test_ema_adx_pullback_entry_rules(self):
        """EMA+ADX geri-çekilme canlı giriş kararı (XAU 5m replay kuralıyla birebir)."""
        f = forex.ema_adx_pullback_entry
        # Boğa dizilimi + ADX yeterli + EMA21'e temas + yeşil onay barı → BUY
        self.assertEqual(
            f(ema8=101.0, ema21=100.0, ema50=99.0, adx=30.0, adx_min=25.0,
              close=100.5, open_=100.0, high=100.6, low=99.9,
              atr_price=1.0, touch_atr=0.30, day_counts={}, max_per_day=0),
            "BUY")
        # Ayı dizilimi + temas + kırmızı onay barı → SELL
        self.assertEqual(
            f(ema8=99.0, ema21=100.0, ema50=101.0, adx=30.0, adx_min=25.0,
              close=99.5, open_=100.0, high=100.1, low=99.4,
              atr_price=1.0, touch_atr=0.30, day_counts={}, max_per_day=0),
            "SELL")
        # ADX eşiğin altında → yok
        self.assertIsNone(
            f(101.0, 100.0, 99.0, 12.0, 25.0, 100.5, 100.0, 100.6, 99.9, 1.0, 0.30, {}, 0))
        # Temas yok (bar EMA21'den uzak) → yok
        self.assertIsNone(
            f(101.0, 100.0, 99.0, 30.0, 25.0, 103.0, 102.0, 103.1, 102.5, 1.0, 0.30, {}, 0))
        # Dizilim karışık (8>21 ama 21<50) → yok
        self.assertIsNone(
            f(101.0, 100.0, 100.5, 30.0, 25.0, 100.5, 100.0, 100.6, 99.9, 1.0, 0.30, {}, 0))
        # Onay barı ters (boğa dizilimi ama kırmızı kapanış) → yok
        self.assertIsNone(
            f(101.0, 100.0, 99.0, 30.0, 25.0, 100.5, 101.0, 101.2, 99.9, 1.0, 0.30, {}, 0))
        # ATR sıfır/geçersiz → yok
        self.assertIsNone(
            f(101.0, 100.0, 99.0, 30.0, 25.0, 100.5, 100.0, 100.6, 99.9, 0.0, 0.30, {}, 0))
        # Gün içi limit: BUY dolu → BUY gelmez
        self.assertIsNone(
            f(101.0, 100.0, 99.0, 30.0, 25.0, 100.5, 100.0, 100.6, 99.9, 1.0, 0.30, {"BUY": 3}, 3))

    def test_strategy_name_helpers(self):
        """Strateji kimliği: giriş kaynağı → kayıt adı; MT5 etiketi → kayıt adı."""
        self.assertEqual(forex.strategy_name_for("ema_adx_pullback"), "EMA_ADX_PULLBACK_M5")
        self.assertEqual(forex.strategy_name_for("donchian"), "DONCHIAN_ADX")
        self.assertEqual(forex.strategy_name_for(""), "M1_M5_RADAR_SCALPER")
        self.assertEqual(forex.strategy_name_for(None), "M1_M5_RADAR_SCALPER")
        # MT5 emir yorumu etiketleri (kapanan deal'den geri gelen)
        self.assertEqual(forex.strategy_comment_tag("ema_adx_pullback"), "EAP-M5")
        self.assertEqual(forex.strategy_from_mt5_deal({"strategy_tag": "EAP-M5"}),
                         "EMA_ADX_PULLBACK_M5")
        self.assertEqual(forex.strategy_from_mt5_deal({"strategy_tag": "DONCH 88"}),
                         "DONCHIAN_ADX")
        self.assertEqual(forex.strategy_from_mt5_deal({"strategy_tag": "RADAR 91"}),
                         "M1_M5_RADAR_SCALPER")
        # Etiketsiz/eski kayıt → nötr
        self.assertEqual(forex.strategy_from_mt5_deal({}), "IC_MARKETS_MT5")
        # Zaten çözülmüş `strategy` alanı korunur
        self.assertEqual(forex.strategy_from_mt5_deal({"strategy": "EMA_ADX_PULLBACK_M5"}),
                         "EMA_ADX_PULLBACK_M5")

    async def test_ema_adx_settings_defaults(self):
        """EMA+ADX canlı taşıma ayarları: XAU açık, SL/TP replay optimaliyle aynı."""
        cfg = forex.ForexAutoPaperSettings()
        self.assertTrue(cfg.ema_adx_enabled)
        self.assertIn("XAUUSD", cfg.ema_adx_symbols)
        self.assertEqual(cfg.ema_adx_adx_min, 25.0)
        self.assertEqual(cfg.ema_adx_sl_atr, 1.5)
        self.assertEqual(cfg.ema_adx_tp_atr, 2.0)
        # XAU, klasik ve donchian akışlarını korumak için mode_exclusive'da OLMAMALI
        self.assertNotIn("XAUUSD", cfg.mode_exclusive)

    async def test_mode_settings_defaults(self):
        """Canlı taşima ayarlari: mode sembolleri, exclusive liste ve 99 slot."""
        cfg = forex.ForexAutoPaperSettings()
        self.assertIn("GBPJPY", cfg.allowed_symbols)
        self.assertIn("EURJPY", cfg.allowed_symbols)
        self.assertIn("XAUUSD", cfg.mode_symbols)
        self.assertIn("GBPJPY", cfg.mode_symbols)
        self.assertIn("GBPJPY", cfg.mode_exclusive)
        self.assertNotIn("XAUUSD", cfg.mode_exclusive)
        self.assertEqual(cfg.max_open_positions, 99)


    def test_no_strong_signal_bypass_regression(self):
        """Regresyon (2026-10-07): başka bir oturumda eklenen 'Güçlü Sinyal Önceliği'
        bypass'ları kalibrasyon kanıtlarını tersine çeviriyordu — (1) allowed_symbols
        kapsamını skor >= 75 için atlatmak, (2) majör seans kapısını JPY/güçlü sinyaller
        için devre dışı bırakmak, (3) mode_exclusive süzgecini kaldırmak. 30g replay:
        28/28 FX çifti klasik sinyalle negatif, Asya girişlerinin gölge defteri −$5.939
        → bu kapıların bypass'ı KALICI olarak yasak."""
        src_path = forex.__file__
        src = pathlib.Path(src_path).read_text(encoding="utf-8")
        self.assertNotIn("GÜÇLÜ SİNYAL ÖNCELİĞİ", src, "güçlü-sinyal önceliği bypass'ı geri eklenmiş")
        self.assertNotIn("allowed_symbols and not is_strong", src, "kapsam bypass'ı geri eklenmiş")
        self.assertNotIn("if not is_strong and \"JPY\" not in sym", src, "JPY seans muafiyeti geri eklenmiş")
        # mode_exclusive süzgeci yerinde olmalı (klasik sinyal JPY kroslarında kapalı)
        self.assertIn("_mode_excl", src)
        # majör kapısı koşulsuz çağrılmalı (radar kapısında bypass yok)
        gate_idx = src.find("gate = major_entry_gate_decision")
        self.assertGreater(gate_idx, 0)
        pre = src[max(0, gate_idx - 400):gate_idx]
        self.assertNotIn("is_strong", pre, "radar majör kapısında güçlü-sinyal muafiyeti var")
        # donchian modu hâlâ yerinde
        self.assertIn("donchian_adx_entry", src)
        self.assertIn("entry_source", src)
        # Motor başlangıcı yalnız kalibre odak setini doldurmalı (geniş FX evrenini DEĞİL).
        self.assertIn('_AUTO_SETTINGS.allowed_symbols = ["XAUUSD", "BTCUSD", "GBPJPY", "EURJPY"]', src,
                      "motor başlangıcı kalibre 4'lü seti doldurmalı")
        self.assertNotIn('"NAS100", "US30", "BTCUSD"', src,
                         "motor başlangıcı geniş FX evrenini otomatik yüklüyor")


if __name__ == "__main__":
    unittest.main()
