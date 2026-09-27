import ast
import asyncio
import os
import sqlite3
import pathlib
import unittest
from unittest.mock import AsyncMock, patch


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _backend_sources():
    """Combined source of main + extracted router modules (post-split layout)."""
    app_dir = ROOT / "app"
    files = [app_dir / "main.py", app_dir / "api_common.py", app_dir / "state.py"]
    files += sorted((app_dir / "routers").glob("*.py"))
    return "\n".join(p.read_text(encoding="utf-8") for p in files)


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _compose_service_env(service: str) -> dict:
    """Bir servisin `environment` bloğunu YORUM satırlarından arındırılmış
    halde döndürür.

    Neden YAML parse etmiyoruz: `PyYAML` test suite'ine yeni bir bağımlılık
    getirirdi ve bu kontrol `docker compose config` olmadan koşamazdı. Compose
    dosyası düz ve girintili olduğu için, yorumları (`#`) atıp bloğu
    kapsayıcı girintisine kadar okumak yeterlidir — hem bağımlılıksız hem de
    dosyanın YORUMUNDA geçen `${VAR:-}` metinlerini yanlışlıkla eşleştirme
    riski yoktur (2026-09-27'de tam olarak bu hata testi kırmıştı).
    """
    lines = (ROOT.parent / "docker-compose.yaml").read_text(encoding="utf-8").splitlines()
    start = f"  {service}:"
    try:
        i = next(n for n, line in enumerate(lines) if line.rstrip() == start)
    except StopIteration:
        raise AssertionError(f"compose'ta servis yok: {service}")
    env: dict = {}
    in_env = False
    for line in lines[i + 1:]:
        if line and not line.startswith("    "):
            break                                  # servisin altındaki blok bitti
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if stripped == "environment:":
            in_env = True
            continue
        if in_env and indent <= 4 and stripped.endswith(":"):
            in_env = False                         # expose:/healthcheck: geldi
        if in_env and indent >= 6 and ":" in stripped:
            key, _, value = stripped.partition(":")
            env[key.strip()] = value.strip()
    return env


class RegressionContracts(unittest.TestCase):
    def test_open_position_payloads_are_sorted_newest_first(self):
        source = _backend_sources()

        self.assertIn('"entry_time": pos.get("entry_time")', source)
        self.assertGreaterEqual(
            source.count(
                'sort(key=lambda item: float(item.get("entry_time") or 0), reverse=True)'
            ),
            2,
        )

    def test_price_watch_intent_resolves_explicit_and_conversation_symbol(self):
        from app.main import _price_watch_symbol
        from app.config import config

        # 2026-09-26 (Global örneği): kullanıcının yazdığı sembol deployment'ın
        # quote'süyle eşleşir. Sabit "DODOTRY" Global'da hiçbir regex'e
        # uymaz ve fonksiyon None döner — yani test Global'da yanlış olurdu.
        sym = f"DODO{config.QUOTE_ASSET}"

        self.assertEqual(
            _price_watch_symbol([{"role": "user", "content": f"{sym} fiyatı izle"}]),
            sym,
        )
        self.assertEqual(
            _price_watch_symbol([
                {"role": "user", "content": f"{sym} ne durumda?"},
                {"role": "user", "content": "fiyatı canlı izle"},
            ]),
            sym,
        )
        self.assertIsNone(
            _price_watch_symbol([{"role": "user", "content": f"{sym} analiz et"}])
        )

    def test_strategy_chat_has_live_analysis_and_price_sse_contract(self):
        source = _backend_sources()
        self.assertIn('"live_analysis_contract"', source)
        self.assertIn("event: price", source)
        self.assertIn("watch_completed", source)
        self.assertIn("failed_breakout", source)

    def test_market_analysis_avoids_repetitive_disclaimer_language(self):
        llm_source = (ROOT / "app" / "llm_analysis.py").read_text(encoding="utf-8")
        main_source = _backend_sources()
        self.assertIn("tekrarlayan sorumluluk uyarıları ekleme", llm_source)
        self.assertIn("kullanıcı istemedikçe sorumluluk veya garanti uyarısı yazma", main_source)
        self.assertNotIn("Bu kısa akış tek başına al/sat kararı değildir", main_source)

    def test_portfolio_replay_has_exact_flawless_victory_profiles(self):
        from scripts.run_portfolio_backtest import pine_profile

        self.assertEqual(pine_profile("v1")["bb_period"], 21)
        self.assertIsNone(pine_profile("v1")["stop_pct"])
        self.assertEqual(pine_profile("v2")["stop_pct"], 0.06604)
        self.assertEqual(pine_profile("v2")["tp_pct"], 0.02328)
        self.assertEqual(pine_profile("v3")["mfi_period"], 16)
        self.assertEqual(pine_profile("v3")["buy_mfi_max"], 59.0)
        self.assertEqual(pine_profile("v3")["sell_rsi_min"], 69.0)
        self.assertEqual(pine_profile("v3")["sell_mfi_min"], 69.0)
        self.assertEqual(pine_profile("v3")["stop_pct"], 0.08882)
        self.assertEqual(pine_profile("v3")["tp_pct"], 0.02317)



    def test_portfolio_replay_reads_normalized_historical_candles(self):
        from scripts.run_portfolio_backtest import rows_to_series

        series = rows_to_series([
            {"open_time": 1_000_000, "close_time": 1_299_999, "open": 100.0, "high": 103.0,
             "low": 99.0, "close": 102.0, "volume": 12.0},
            {"open_time": 1_300_000, "close_time": 1_599_999, "open": 102.0, "high": 104.0,
             "low": 101.0, "close": 103.0, "volume": 15.0},
        ])

        self.assertEqual(series["opens"], [100.0, 102.0])
        self.assertEqual(series["closes"], [102.0, 103.0])
        self.assertEqual(series["times"], [1299, 1599])

    def test_portfolio_replay_historical_db_uses_requested_window_and_warmup(self):
        from scripts.run_portfolio_backtest import load_market

        start_ts, end_ts, days = 2_000_000, 2_100_000, 1
        cached_rows = [{"open_time": 1_000_000, "close_time": 1_299_999,
                        "open": 100.0, "high": 103.0, "low": 99.0,
                        "close": 102.0, "volume": 12.0}]

        async def exercise():
            with patch("scripts.run_portfolio_backtest.database.get_market_candles",
                       new=AsyncMock(return_value=cached_rows)) as get_candles:
                loaded = await load_market(["BTCTRY"], days, "historical-db", start_ts, end_ts)
            return loaded, get_candles.await_args.args

        loaded, call_args = asyncio.run(exercise())
        self.assertEqual(call_args, ("BTCTRY", "5m", start_ts * 1000 - days * 86400 * 1000, end_ts * 1000))
        self.assertEqual(loaded[0][0], "BTCTRY")
        self.assertEqual(loaded[0][1]["closes"], [102.0])

    def test_portfolio_replay_historical_cache_and_mtm_cost_contracts(self):
        source = (ROOT / "scripts" / "run_portfolio_backtest.py").read_text(encoding="utf-8")
        self.assertIn('args.data_source == "historical-db"', source)
        self.assertIn('"historical_cached_requested_symbols"', source)
        self.assertIn("liquidation_fill = mark_price", source)
        self.assertIn("exit_fee = marked_value * config.COMMISSION_PCT", source)

    def test_portfolio_profit_lock_arms_only_after_the_trigger(self):
        from scripts.run_portfolio_backtest import arm_profit_lock

        position = {"entry": 100.0}
        self.assertFalse(arm_profit_lock(position, 100.49, 0.005, 0.0035))
        self.assertNotIn("profit_lock_stop", position)
        self.assertTrue(arm_profit_lock(position, 100.50, 0.005, 0.0035))
        self.assertAlmostEqual(position["profit_lock_stop"], 100.35)
        self.assertFalse(arm_profit_lock(position, 101.0, 0.005, 0.0035))

    def test_portfolio_replay_supports_an_experimental_risk_stop(self):
        source = (ROOT / "scripts" / "run_portfolio_backtest.py").read_text(encoding="utf-8")
        self.assertIn("args.risk_stop_pct is not None", source)
        self.assertIn('"risk_stop_pct": stop_pct', source)

    def test_alert_trigger_uses_a_boolean_false_for_postgres(self):
        source = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        # Postgres-only backend: alert rearm must use a real SQL boolean.
        self.assertIn('armed_false = "FALSE"', source)
        self.assertIn("ELSE {armed_false} END", source)

    def test_tts_normalizes_turkish_market_numbers(self):
        from app.main import _speech_text
        spoken = _speech_text("-0.719 · %0.147 · 1283x · 5m · 1h · 12.18 😀")
        self.assertIn("eksi 0 virgül 719", spoken)
        self.assertIn("yüzde 0 virgül 147", spoken)
        self.assertIn("1283 kat", spoken)
        self.assertIn("5 dakika", spoken)
        self.assertIn("1 saat", spoken)
        self.assertIn("12 virgül 18", spoken)
        self.assertNotIn("😀", spoken)



    def test_backtest_fill_model_charges_round_trip_costs(self):
        # Backtest kaldırıldı (2026-09-06); kontrat artık uygulanmıyor.
        self.assertTrue(True)

    def test_backtest_has_explicit_microstructure_and_spread_contract(self):
        # Backtest kaldırıldı (2026-09-06); kontrat artık uygulanmıyor.
        self.assertTrue(True)

    def test_custom_exit_policy_is_not_forced_to_use_tp_sl(self):
        # Backtest kaldırıldı (2026-09-06); kontrat artık uygulanmıyor.
        self.assertTrue(True)

    def test_llm_exit_creates_symbol_reentry_lock(self):
        source = (ROOT / "app" / "analyzer.py").read_text(encoding="utf-8")
        self.assertIn("LLM_REENTRY_COOLDOWN_SEC", source)
        self.assertIn("LLM_REENTRY_MIN_MOVE_PCT", source)
        self.assertIn("rearm_required_pct", source)
        self.assertIn("atr_pct_at_exit", source)
        self.assertIn("except (TypeError, ValueError)", source)
        self.assertIn("LLM_REENTRY_BLOCKED", source)
        self.assertIn("requires_fresh_setup", source)

    def test_llm_entry_has_overextension_and_microstructure_gate(self):
        source = _backend_sources()
        self.assertIn("_llm_entry_quality_gate", source)
        self.assertIn("overbought_rsi", source)
        self.assertIn("negative_orderflow", source)
        self.assertIn("spread_above_entry_limit", source)
        self.assertIn("symbol_loss_streak", source)
        self.assertIn("symbol_negative_net_expectancy", source)
        self.assertIn('"spread_above_entry_limit"', source)
        self.assertIn('"negative_orderflow"', source)

    def test_llm_entry_gate_rejects_biotry_like_overbought_setup(self):
        from app.main import _llm_entry_quality_gate

        snapshot = {
            "data_ready": True,
            "price": 1.203,
            "trend": {"alignment": "bullish"},
            "momentum": {"rsi_14": 95, "stochastic": {"k": 96}, "mfi_14": 83},
            "oscillators": {"values": {"cci_20": 253}},
            "liquidity": {"spread_pct": 0.166, "orderflow_imbalance": -0.399},
            "channels": {"bollinger": {"upper": 1.202}},
        }
        ok, reasons = _llm_entry_quality_gate(snapshot, {
            "trades": 4, "current_loss_streak": 3, "expectancy_net_pnl": -0.5,
        })
        self.assertFalse(ok)
        self.assertIn("overbought_rsi", reasons)
        self.assertIn("negative_orderflow", reasons)
        self.assertIn("symbol_loss_streak", reasons)


    def test_llm_system_prompt_has_trade_manager_rules(self):
        source = (ROOT / "app" / "llm_analysis.py").read_text(encoding="utf-8")
        self.assertIn("TRADE_MANAGER_RULES", source)
        self.assertIn("cooldown ve sembolün dinamik re-arm", source)

    def test_entry_policy_endpoint_exposes_auditable_contract(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn('@app.get("/api/llm/entry-policy")', source)
        self.assertIn('"policy_version": "scalper-trade-manager-v2"', source)


    def test_llm_reentry_cooldown_is_shorter_after_profit(self):
        source = (ROOT / "app" / "analyzer.py").read_text(encoding="utf-8")
        config_source = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
        self.assertIn('LLM_PROFIT_REENTRY_COOLDOWN_SEC', source)
        self.assertIn('float(trade.get("pnl") or 0.0) > 0', source)
        self.assertIn('str(5 * 60)', config_source)
        self.assertIn('str(30 * 60)', config_source)

    def test_alert_can_trigger_gated_paper_entry(self):
        source = (ROOT / "app" / "alerting.py").read_text(encoding="utf-8")
        main_source = _backend_sources()
        self.assertIn('on_paper_trigger=None', source)
        self.assertIn('"auto_paper_trade" in channels', source)
        self.assertIn('on_paper_trigger=auto_open_from_alert', main_source)
        self.assertIn('"source": "market_alert"', main_source)
        self.assertIn('"auto_paper_trade"', main_source)

    def test_health_defaults_to_postgres(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn('os.getenv("DB_BACKEND", "postgres")', source)

    def test_postgres_backup_is_custom_format_and_validated(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn('async def _create_postgres_backup()', source)
        self.assertIn('"--format=custom"', source)
        self.assertIn('"--no-acl"', source)
        self.assertIn('backup_file.read(5) != b"PGDMP"', source)
        self.assertIn('["pg_restore", "--list", path]', source)
        self.assertIn('headers={"X-Backup-Format": "postgresql-custom", "X-Backup-Verified": "PGDMP"}', source)

    def test_settings_uses_validated_postgres_backup_route(self):
        source = (ROOT.parent / "frontend" / "app" / "settings" / "page.tsx").read_text(encoding="utf-8")
        self.assertIn('`${API_BASE}/api/postgres/backup`', source)
        self.assertIn('Sunucunun ürettiği dosya geçerli PostgreSQL custom-format yedeği değil', source)

    def test_production_entrypoint_is_postgres_only(self):
        source = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn('${DB_BACKEND:-postgres}', source)
        self.assertIn('DATABASE_URL', source)
        self.assertIn('exit 1', source)

    def test_default_skill_uses_postgres_boolean_literal(self):
        source = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        # 2026-09-04: veri katmanı postgres-only; SQLite literal'i kalmamalı.
        self.assertIn('enabled_literal = "TRUE"', source)
        self.assertNotIn('enabled_literal = "1"', source)
        self.assertIn('VALUES(?,?,{enabled_literal},?)', source)

    def test_postgres_migration_retries_transient_connection_failures(self):
        source = (ROOT / "scripts" / "run_postgres_migration.py").read_text(encoding="utf-8")
        self.assertIn('_MAX_ATTEMPTS = 20', source)
        self.assertIn('for attempt in range(1, _MAX_ATTEMPTS + 1)', source)
        self.assertIn('await asyncio.sleep(_RETRY_SLEEP_SEC)', source)
        self.assertIn('"LockNotAvailableError"', source)
        self.assertIn('pg_advisory_lock', source)
        self.assertIn('schema_sha256', source)
        self.assertIn('PostgreSQL migration bağlantı/kilit beklemesi tükendi', source)

    def test_compose_forces_postgres_backend(self):
        source = (ROOT.parent / "docker-compose.yaml").read_text(encoding="utf-8")
        self.assertIn("DB_BACKEND: postgres", source)

    def test_compose_passes_runtime_strategy_and_llm_configuration(self):
        source = (ROOT.parent / "docker-compose.yaml").read_text(encoding="utf-8")
        # 2026-09-27 (TR örneği bu repodan kaldırıldı): LLM_ENCRYPTION_KEY
        # artık yalnız Global yolundan gelir ve ZORUNLU. `:-${LLM_ENCRYPTION_KEY:?...}`
        # yedeği bilinçli olarak KALDIRILDI — Coolify Bash'ı kendi parser'ıyla
        # değerlendirip hata metnini değer olarak yazıyor, yani yedek yol
        # sessizce sahte bir anahtar üretiyordu (2026-09-27 deploy kazası).
        # Aynı desen POSTGRES_PASSWORD, PGPASSWORD ve VAPID_PRIVATE_KEY'de vardı;
        # `test_compose_secrets_have_no_tr_placeholder_fallback` hepsini kapsar.
        self.assertIn("LLM_ENCRYPTION_KEY: ${LLM_ENCRYPTION_KEY_GLOBAL:?", source)
        self.assertIn("TOP_GAINERS_AUTO_ACTIVATE: ${TOP_GAINERS_AUTO_ACTIVATE:-true}", source)
        self.assertIn("TOP_GAINERS_LIMIT: ${TOP_GAINERS_LIMIT:-10}", source)
        self.assertIn("TOP_GAINERS_REFRESH_SEC: ${TOP_GAINERS_REFRESH_SEC:-600}", source)
        self.assertIn("NEXT_PUBLIC_VAPID_PUBLIC_KEY: ${NEXT_PUBLIC_VAPID_PUBLIC_KEY_GLOBAL:-}", source)

        dockerfile = (ROOT.parent / "frontend" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ARG NEXT_PUBLIC_VAPID_PUBLIC_KEY", dockerfile)
        self.assertIn("ENV NEXT_PUBLIC_VAPID_PUBLIC_KEY=${NEXT_PUBLIC_VAPID_PUBLIC_KEY}", dockerfile)
        self.assertNotIn("DB_BACKEND: ${DB_BACKEND:-postgres}", source)
        # Global örneğinin postgres'i `postgres_global`; TR'ninkini gösteren
        # `@postgres:5432/` artık YANLIŞ hedef olurdu (servis yok → konteyner
        # "dependency failed" ile düşer). DB adı da `scalper_global`.
        self.assertIn("@postgres_global:5432/${POSTGRES_DB_GLOBAL:-scalper_global}", source)
        self.assertNotIn("@postgres:5432/${POSTGRES_DB:-scalper}", source)
        self.assertNotIn("DATABASE_URL:-postgresql://", source)

    def test_dynamic_top_gainer_monitor_and_symbol_activity_are_scheduled(self):
        source = _backend_sources()
        config_source = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
        self.assertIn('async def refresh_top_gainer_symbols()', source)
        self.assertIn('async def refresh_symbol_activity()', source)
        self.assertIn('_start_background(symbol_activity_loop, "symbol-activity")', source)
        self.assertIn('_start_background(top_gainers_refresh_loop, "top-gainers-monitor")', source)
        self.assertNotIn('asyncio.create_task(top_gainers_refresh_loop()', source)
        self.assertIn('@app.get("/api/market/top-gainers")', source)
        self.assertIn('SYMBOL_ACTIVITY_REFRESH_SEC', config_source)
        self.assertIn('SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT', config_source)
        self.assertIn('SYMBOL_ACTIVITY_FILTER_ENABLED', config_source)
        self.assertIn('SYMBOL_ACTIVITY_STATUS', config_source)
        self.assertIn('TOP_GAINERS_LIMIT = max(1, min(50', config_source)
        self.assertIn('TOP_GAINERS_REFRESH_SEC = max(60', config_source)
        self.assertIn('source": "binance_tr_public_24h_ticker"', source)
        # 2026-09-26 (Global örneği): sembol evreni artık `trading_symbols()`
        # argsız çağrılır — quote, deployment'ın config.QUOTE_ASSET'i olur
        # (TR→TRY, Global→USDT). Sabit `"TRY"` literal'i Global'da HİÇBİR
        # sembol döndürür ve aktivite/mutabakat sessizce boş kalırdı. Test
        # hâlâ "sembol evreni bu borsanın quote'süyle sorgulanıyor"
        # sözleşmesini korur, yalnız ifadesi yeni imzaya uyar.
        self.assertIn('known_try = set(await trading_symbols())', source)
        self.assertNotIn('trading_symbols("TRY")', source,
                         "sembol evreni sabit TRY'ye bağlanmamalı")


    def test_compose_has_bounded_shutdown_and_postgres_startup_grace(self):
        source = (ROOT.parent / "docker-compose.yaml").read_text(encoding="utf-8")
        # 4 servis kaldı (postgres_global, backend_global, frontend_global,
        # gateway_global) → her birinde `stop_grace_period` olmalı.
        self.assertGreaterEqual(source.count("stop_grace_period:"), 4)
        postgres = source[source.index("  postgres_global:"):source.index("  backend_global:")]
        self.assertIn("start_period: 30s", postgres)
        self.assertIn("retries: 12", postgres)

    def test_compose_overrides_dockerfile_hardcoded_ports(self):
        # 2026-09-27 ikinci gizli hata: her iki Dockerfile portu DÜZ yazıyor
        # (backend 8004, frontend 3004) ama Global stack 8005/3005 konuşuyor.
        # Override kalkarsa uvicorn 8004'te açılır, healthcheck 8005'e gider ve
        # konteyner açılmadan ölür — parola düzeltilseydi deploy YİNE düşerdi.
        # Bağımlılık: nginx-global/default.conf ve healthcheck'ler 8005/3005.
        source = (ROOT.parent / "docker-compose.yaml").read_text(encoding="utf-8")
        self.assertIn('"--port", "8005"', source)
        self.assertIn('PORT: "3005"', source)
        nginx = (ROOT.parent / "nginx-global" / "default.conf").read_text(encoding="utf-8")
        self.assertIn("backend_global:8005", nginx)
        self.assertIn("frontend_global:3005", nginx)

    def test_tr_services_are_absent_from_compose(self):
        # 2026-09-27: TR örneği ayrı repo/konteynere taşındı. Bu repo Global
        # ağırlıklı olduğu için TR'nin postgres'i bir host'ta iki stack'i
        # ~10.7 GB'a çıkarıyordu. Servis adları yanlışlıkla geri gelirse
        # deploy sessizce iki kez aynı DB'ye bağlanmaya çalışır.
        source = (ROOT.parent / "docker-compose.yaml").read_text(encoding="utf-8")
        for retired in (
            "\n  postgres:\n",
            "\n  backend:\n",
            "\n  frontend:\n",
            "\n  gateway:\n",
            "\n  db-backup:\n",
        ):
            self.assertNotIn(retired, source, f"{retired.strip()} TR'ye ait, kaldırılmalı")
        self.assertNotIn("scalper_postgres_data:", source)
        self.assertNotIn("scalper_data:", source)

    def test_compose_vapid_key_pair_has_no_placeholder_fallback(self):
        # 2026-09-27: `VAPID_PRIVATE_KEY: ${VAPID_PRIVATE_KEY_GLOBAL:-${VAPID_PRIVATE_KEY:-}}`
        # idi. Coolify bu iç içe varsayılanı çözmedi ve ham `${VAPID_PRIVATE_KEY:-}`
        # metnini değer olarak yazdı → private "geçersiz" sayılır, public/private
        # eşleşmez ve abonelikler SESSİZCE ölür. Boş bırakmak push'u kapatır
        # (görünür), yanlış anahtar ise bozar (görünmez) — yedeği kaldırıldı.
        #
        # NOT: kontrol YORUM satırlarına değil, `environment:` bloğunun gövdesine
        # bakar. Dosyanın kendi açıklama metni `${VAPID_PRIVATE_KEY:-}` kelimesini
        # içerir; tüm dosyada aramak testi kendi yorumu yüzünden kırılırdı.
        env = _compose_service_env("backend_global")
        self.assertEqual("${VAPID_PRIVATE_KEY_GLOBAL:-}", env["VAPID_PRIVATE_KEY"])

    def test_compose_secrets_have_no_tr_placeholder_fallback(self):
        # 2026-09-27 deploy kazasının kökü: Coolify Bash sözdizimini kendi
        # parser'ıyla değerlendirip `${VAR:?mesaj}` hata METNİNİ değer olarak
        # yazdı. postgres'e giden parola bu yüzden "POSTGRES_PASSWORD must
        # be set" idi. Her sır için aynı desen YOK; eksik değişken AÇIK hata
        # vermeli. `:-` (varsayılanlı) yasak, `:?` (zorunlu) veya düz değer olmalı.
        for service in ("postgres_global", "backend_global", "db-backup-global"):
            for name, value in _compose_service_env(service).items():
                if "PASSWORD" in name or "ENCRYPTION" in name or "SECRET" in name:
                    with self.subTest(service=service, name=name):
                        self.assertNotIn(":-", str(value),
                                         f"{name} TR yedeği taşıyor; Coolify onu çözemez")
        # LLM anahtarı olmadan LLM ayarları şifrelenmez ama HATA da fırlatmaz —
        # sessiz veri bozulması. Bu yüzden zorunlu (`:?`) olmalı.
        llm_key = _compose_service_env("backend_global")["LLM_ENCRYPTION_KEY"]
        self.assertIn(":?", llm_key)
        self.assertNotIn(":-", llm_key)

    def test_vapid_generation_hint_matches_accepted_format(self):
        # `app/vapid.py:58-77` base64url 32 bayt bekler; PEM üreten bir ipucu
        # kullanıcıyı anahtarı üretip reddettirirdi (sessiz push ölümü).
        source = (ROOT.parent / "docker-compose.yaml").read_text(encoding="utf-8")
        start = source.index("python - <<'PY'")
        end = source.index("\n        #   PY", start)   # yorum bloğunun gerçek sonu
        hint = source[start:end]
        self.assertIn("private_numbers().private_value.to_bytes(32", hint)
        self.assertIn('rstrip("=")', hint)
        self.assertNotIn("private_pem", hint)

    def test_symbol_activity_is_enforced_at_the_writer_boundary(self):
        source = (ROOT / "app" / "analyzer.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        opening = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_open_position_unlocked"
        )
        opening_source = ast.get_source_segment(source, opening)
        self.assertIsNotNone(opening_source)
        self.assertIn("symbol in config.PASSIVE_SYMBOLS", opening_source)
        self.assertIn('"action": "BUY_BLOCKED"', opening_source)
        self.assertIn('"symbol_activity:passive"', opening_source)

    def test_symbol_activity_does_not_overwrite_configured_scan_symbols(self):
        combined = _backend_sources()
        tree = ast.parse(combined)
        refresh = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "refresh_symbol_activity")
        refresh_source = ast.get_source_segment(combined, refresh)
        self.assertIsNotNone(refresh_source)
        self.assertNotIn("config.SYMBOLS = universe", refresh_source)
        self.assertIn("configured paper-trading scan universe", refresh_source)



class StrategyReplayBehavior(unittest.IsolatedAsyncioTestCase):


    def test_llm_market_scan_uses_fast_hot_cache_defaults(self):
        source = _backend_sources()
        config_source = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
        self.assertIn('["5m", "15m", "1h"]', source)
        self.assertIn('LLM_MARKET_SCAN_CACHE_SEC', config_source)
        self.assertIn('"scan_mode": "fast_hot_cache"', source)
        self.assertIn('"fresh"', source)

    def test_main_has_one_reconcile_function(self):
        tree = ast.parse(_backend_sources())
        names = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        self.assertEqual(names.count("reconcile_portfolio"), 1)
        self.assertEqual(names.count("reconcile_portfolio_state"), 1)

    def test_radar_has_interval_and_lock(self):
        source = _backend_sources()
        self.assertIn("async with _radar_lock", source)
        self.assertIn("await asyncio.sleep(config.GAINER_RADAR_INTERVAL_SEC)", source)

    def test_concurrent_position_open_is_serialized(self):
        from app.analyzer import ScalpAnalyzer

        analyzer = ScalpAnalyzer(None)
        self.assertIsInstance(analyzer._open_position_lock, asyncio.Lock)

    def test_websocket_runtime_isolated_module(self):
        from app.ws_runtime import ConnectionManager

        manager = ConnectionManager()
        self.assertEqual(manager.active_connections, [])


    def test_get_trades_contract_supports_filter_and_offset(self):
        from app import database

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.executescript("""
            CREATE TABLE trades(id INTEGER PRIMARY KEY, symbol TEXT, strategy TEXT, side TEXT,
              entry_price REAL, exit_price REAL, quantity REAL, pnl REAL, pnl_pct REAL,
              entry_time REAL, exit_time REAL, commission REAL, reason TEXT, entry_context TEXT,
              max_favorable_pct REAL, max_adverse_pct REAL, hold_seconds REAL, trade_id TEXT);
        """)

        async def run(operation):
            return operation(conn)

        async def flow():
            await database.save_trade({"symbol": "BTCTRY", "strategy": "MOMENTUM", "exit_time": 3, "pnl": 1.0})
            await database.save_trade({"symbol": "ETHTRY", "strategy": "MOMENTUM", "exit_time": 2, "pnl": 2.0})
            rows = await database.get_trades(limit=1, offset=1, strategy="MOMENTUM")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["symbol"], "ETHTRY")

        with patch("app.database._run_db", new=run):
            asyncio.run(flow())


if __name__ == "__main__":
    unittest.main()
