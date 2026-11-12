"""Health, memory and migration system routes."""
import asyncio
from pathlib import Path
import os
import time
import logging
from functools import partial

from fastapi import APIRouter, HTTPException, Request

from app.config import config
from app import ml_shadow, session_windows, cot_positions, forex_news, geometry_shadow, market_pulse  # gölge kalibrasyon sayaçları + cross-asset nabız
from app import retail_sentiment  # perakende konumlanma (Myfxbook, bağlam)
from app import database
from app.state import market, analyzer
from app.api_common import _start_background, _background_tasks, rate_limit
from app import memory_service
from app import migration_monitor
from app.embedding_worker import worker as embedding_worker, trade_document, signal_document
from app.memory_service import build_document
from app.ws_runtime import ws_manager
import math
import json
from app.binance_tr_public import klines as fetch_klines
from app.technical_analysis import calculate_snapshot
from app import llm_analysis
from app.api_common import _main_pg_pool

logger = logging.getLogger("scalper.system")
router = APIRouter()


_embedding_backfill = {"status": "idle", "queued": 0, "message": None}
_embedding_repair = {"status": "idle", "queued": 0, "message": None}

@router.get("/health")
async def health():
    # 2026-09-26 (deploy düzeltmesi): bu uç container healthcheck'inin
    # hedefi. Önceden TÜM semboller için `market.data_freshness()` çağırıyordu
    # (310 sembol × senkron sözlük/len hesabı) ve ayrıca `analyzer.positions`
    # ile `market.symbols` üzerinde tam tarama yapıyordu. Açılışta history
    # backfill'i event loop'u meşgul ettiği için bu uç zaman aşımına
    # uğruyor, container "unhealthy" oluyor ve Coolify deploy'u başarısız
    # sayıyordu.
    #
    # Liveness SÖZLEŞMESİ: bu uç SADECE sürecin ayakta olduğunu ve
    # market akışının bağlı olup olmadığını bildirir. "Piyasa taze mi"
    # sorusu bir hazırlık (readiness) sorusudur ve `/api/system/health`
    # (kimlik doğrulamalı) ile `market.data_freshness` üzerinden verilir.
    # Liveness, tazelik KOŞULU üzerinden karar verirse, veri geciktiğinde
    # yeniden başlatma tetiklenir — bu da aracın kurtarılmasını engeller.
    return {
        "status": "alive",
        "mode": "paper", "market_data": f"{config.EXCHANGE}_public",
        "market_running": bool(getattr(market, "running", False)),
        "history_loaded": bool(getattr(market, "history_loaded", False)),
        "tracked_symbols": len(getattr(market, "symbols", ()) or ()),
        # G-30: /health kimlik doğrulamasız bir yoldur; açık pozisyon sembolleri
        # (hangi sembollerde pozisyon var) sızdırılmamalı. Yalnız sayı verilir;
        # sembol listesi kimlik doğrulamalı /api/positions'tan alınır.
        "open_position_count": len(getattr(analyzer, "positions", {}) or {}),
    }

@router.get("/api/system/health")
async def system_health():
    now_ms = time.time() * 1000
    ages = [max(0.0, (now_ms - float(t.get("timestamp", now_ms))) / 1000) for t in market.tickers.values() if t.get("timestamp")]
    vector_status = "not_checked_until_postgres_backend_is_enabled"
    db_status = "postgres_not_configured"
    if _main_pg_pool():
        try:
            async with _main_pg_pool().acquire() as conn:
                await conn.fetchval("SELECT 1")
                vector_status = bool(await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"))
                db_status = "postgres_healthy"
        except Exception as exc:
            db_status = f"postgres_error:{type(exc).__name__}"
            vector_status = False
    try:
        llm_active = bool(await database.get_active_llm_config())
        llm_error = None
    except Exception as exc:
        llm_active = False
        llm_error = f"{type(exc).__name__}: {exc}"
    freshness = {symbol: market.data_freshness(symbol, "5m")
                 for symbol in market.symbols}
    fresh_count = sum(1 for value in freshness.values()
                      if value["ticker"]["fresh"] and value["kline"]["fresh"])
    market_degraded = market.running and bool(market.symbols) and fresh_count == 0
    overall_degraded = (db_status.startswith("postgres_") and db_status != "postgres_healthy") or llm_error or market_degraded
    # MAX_OPEN_POSITIONS=0 "sınırsız" demektir; analyzer float("inf") döndürür ve
    # JSON bunu temsil edemez (allow_nan=False) → API'ye null olarak çıkar.
    _max_open_raw = analyzer.max_open_positions()
    max_open_json = None if isinstance(_max_open_raw, float) and not math.isfinite(_max_open_raw) else _max_open_raw
    real_sell_enabled = os.getenv("ENABLE_REAL_BINANCE_SELL", "0").strip().lower() in {"1", "true", "yes", "on"}
    # GÖLGE KALİBRASYON (2026-11-09): karar değiştirmeyen ölçüm katmanı.
    # "Kalibre olsaydı kaç girişten çekimser kalırdı" sayacı; artefakt yoksa
    # `artifact_loaded=False` görünür ve ham olasılıkla çalıştığı anlaşılır.
    # Yalnız bellek sayaçları — DB/disk okuması YOK.
    ml_calibration_shadow = ml_shadow.counters()
    return {"status": "degraded" if overall_degraded else "ok", "generated_at": time.time(), "market": {"symbols": len(market.symbols), "tickers": len(market.tickers), "fresh_symbols": fresh_count, "max_ticker_age_sec": max(ages) if ages else None, "timeframes": market.timeframes, "rest_last_event_at": market.rest_last_event_at, "rest_error": market.rest_last_error, "ws_last_event_at": market.ws_last_event_at, "ws_error": market.ws_last_error, "ws_generation": market.connection_generation, "session": session_windows.describe()}, "portfolio": {"open_positions": len(analyzer.positions), "max_open_positions": max_open_json, "pending_paper_orders": len(analyzer.pending_orders)}, "database": {"backend": "postgres", "status": db_status, "postgres_configured": bool(os.getenv("DATABASE_URL", "").strip()), "vector_extension": vector_status}, "embedding": embedding_worker.snapshot(), "websocket_clients": len(ws_manager.active_connections), "llm": {"configured": bool(os.getenv("LLM_ENCRYPTION_KEY", "").strip()), "active": llm_active, "error": llm_error}, "safety": {"paper_only": not real_sell_enabled, "paper_trading_core": True, "real_sell_enabled": real_sell_enabled, "memory_content_untrusted": True, "tool_audit_enabled": True}, "ml_calibration": ml_calibration_shadow, "cross_asset_pulse": market_pulse.cached_summary(), "retail_sentiment": retail_sentiment.summary(), "cot": cot_positions.summary(), "economic_calendar_source": forex_news.investing_block_state(), "geometry_shadow": geometry_shadow.params()}

@router.get("/api/memory/status")
async def memory_status():
    persistent = {"documents": 0, "embedded": 0}
    if _main_pg_pool():
        async with _main_pg_pool().acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) AS documents, COUNT(*) FILTER (WHERE embedding_status='ready') AS embedded FROM memory_documents")
            persistent = {"documents": int(row["documents"]), "embedded": int(row["embedded"])}
    return {"enabled": bool(_main_pg_pool()), "backend": os.getenv("DB_BACKEND", "postgres"), "worker": embedding_worker.snapshot(), "persistent": persistent, "backfill": dict(_embedding_backfill), "repair": dict(_embedding_repair), "message": None if _main_pg_pool() else "PostgreSQL memory backend aktif değil"}

@router.post("/api/memory/backfill")
async def memory_backfill(request: Request = None):
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    if not _main_pg_pool(): raise HTTPException(status_code=503, detail="PostgreSQL memory backend aktif değil")
    if _embedding_backfill["status"] == "running": return {"ok": False, **_embedding_backfill}
    _embedding_backfill.update({"status": "running", "queued": 0, "message": "Kayıtlar embedding kuyruğuna alınıyor"})
    async def enqueue_existing():
        try:
            queued = 0
            async with _main_pg_pool().acquire() as conn:
                trades = [dict(row) for row in await conn.fetch("SELECT * FROM trades ORDER BY id")]
                signals = [dict(row) for row in await conn.fetch("SELECT * FROM signals ORDER BY id")]
            for trade in trades:
                doc = trade_document("historical", trade.get("symbol") or "unknown", trade, {"action": "HISTORICAL_TRADE", "timestamp": trade.get("exit_time")})
                queued += int(await embedding_worker.enqueue_persistent(doc))
            for signal in signals:
                queued += int(await embedding_worker.enqueue_persistent(signal_document(signal)))
            _embedding_backfill.update({"status": "completed", "queued": queued, "message": "Embedding kuyruğu hazır; worker kayıtları işliyor"})
        except Exception as exc:
            _embedding_backfill.update({"status": "error", "message": str(exc)})
    _start_background(enqueue_existing, "embedding-backfill", single_pass=True)
    return {"ok": True, **_embedding_backfill}

@router.post("/api/memory/repair-historical")
async def repair_historical_memory(request: Request = None):
    """Rebuild historical trade memory without inventing unavailable market data."""
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    if not _main_pg_pool(): raise HTTPException(status_code=503, detail="PostgreSQL memory backend aktif değil")
    if _embedding_repair["status"] == "running": return {"ok": False, **_embedding_repair}
    _embedding_repair.update({"status": "running", "queued": 0, "message": "Tarihsel snapshot'lar onarılıyor"})
    async def repair():
        try:
            queued = 0
            async with _main_pg_pool().acquire() as conn:
                trades = [dict(row) for row in await conn.fetch("SELECT * FROM trades ORDER BY id")]
                for trade in trades:
                    context = trade.get("entry_context")
                    if isinstance(context, str):
                        try: context = json.loads(context)
                        except json.JSONDecodeError: context = {}
                    context = context if isinstance(context, dict) else {}
                    technical = context.get("technical") if isinstance(context.get("technical"), dict) else {}
                    # Reconstruct OHLCV-based indicators around the original
                    # entry time. Order-book fields remain explicitly unknown.
                    try:
                        entry_ms = int(float(trade.get("entry_time") or 0) * 1000)
                        symbol = str(trade.get("symbol") or "").upper()
                        rows_5m = await fetch_klines(symbol, "5m", 300, max(0, entry_ms - 300 * 5 * 60 * 1000))
                        rows_1d = await fetch_klines(symbol, "1d", 250, max(0, entry_ms - 250 * 86400 * 1000))
                        def pack(rows):
                            return {"opens": [float(r[1]) for r in rows], "highs": [float(r[2]) for r in rows], "lows": [float(r[3]) for r in rows], "closes": [float(r[4]) for r in rows], "volumes": [float(r[5]) for r in rows]}
                        rebuilt = calculate_snapshot(symbol, float(trade.get("entry_price") or 0), {"5m": pack(rows_5m), "1d": pack(rows_1d)}, {"source": "historical_reconstruction", "spread_pct": None, "bid_qty": 0, "ask_qty": 0}, 0, float(trade.get("entry_price") or 0) * float(trade.get("quantity") or 0), "5m")
                        technical = rebuilt if rebuilt.get("data_ready") else technical
                    except Exception as exc:
                        _embedding_repair["message"] = f"Bazı kayıtlar yeniden hesaplanamadı: {exc}"
                    liquidity = technical.get("liquidity") if isinstance(technical.get("liquidity"), dict) else {}
                    missing = [key for key in ("spread_pct", "orderbook_depth_try", "orderflow_imbalance") if liquidity.get(key) in (None, 0, 0.0)]
                    technical["liquidity"] = {**liquidity, "spread_pct": None, "orderbook_depth_try": None, "depth_multiplier": None, "orderflow_imbalance": None, "source": "historical_reconstruction", "missing_fields": missing}
                    context["technical"] = technical
                    context["data_provenance"] = "historical_reconstruction"
                    context["data_quality"] = {"missing_fields": missing, "note": "Historical order-book data was not available; no values were estimated."}
                    trade["entry_context"] = context
                    source_id = str(trade.get("id"))
                    await conn.execute("DELETE FROM memory_embeddings WHERE memory_document_id IN (SELECT id FROM memory_documents WHERE source_type='trade_historical' AND source_id=$1)", source_id)
                    await conn.execute("DELETE FROM memory_documents WHERE source_type='trade_historical' AND source_id=$1", source_id)
                    doc = trade_document("historical", trade.get("symbol") or "unknown", trade, {"action": "HISTORICAL_TRADE", "timestamp": trade.get("exit_time")})
                    queued += int(await embedding_worker.enqueue_persistent(doc))
            _embedding_repair.update({"status": "completed", "queued": queued, "message": "Eksik tarihsel likidite alanları tahmin edilmeden yeniden embedding kuyruğuna alındı"})
        except Exception as exc:
            _embedding_repair.update({"status": "error", "message": str(exc)})
    _start_background(repair, "historical-memory-repair", single_pass=True)
    return {"ok": True, **_embedding_repair}

@router.get("/api/migration/status")
async def migration_status():
    return dict(migration_monitor.state)

@router.post("/api/migration/start")
async def migration_start(payload: dict = None, request: Request = None):
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    body = payload or {}
    source = str(body.get("source") or os.getenv("MIGRATION_SOURCE_PATH") or "legacy-pasif")
    if migration_monitor.state["status"] == "running": return {"ok": False, "message": "Migration zaten çalışıyor"}
    # V-21: SQLite migration kalıcı olarak kaldırıldı → 410 Gone (400 "bad
    # request" kullanıcıyı girdiyi düzeltmeye çalıştırıyordu).
    try: info = migration_monitor.inspect_source(source)
    except Exception as exc: raise HTTPException(status_code=410, detail=str(exc))
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url: raise HTTPException(status_code=503, detail="DATABASE_URL tanımlı değil")
    migration_monitor.state.update({"source":info, "status":"queued", "phase":"queued", "progress":0, "message":"Migration kuyruğa alındı"})
    _start_background(partial(migration_monitor.run, source, database_url), "legacy-migration-check", single_pass=True)
    return {"ok":True, "source":info}

@router.post("/api/memory/retrieve")
async def memory_retrieve(payload: dict = None, request: Request = None):
    # G-13: her çağrı ücretli/uzak bir embedding + vektör arama + log yazımı
    # yapıyordu; admin kapısı ve hız sınırı yoktu. İkisi de eklendi.
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    if not rate_limit("memory-retrieve", rate_per_sec=1.0, burst=5):
        raise HTTPException(status_code=429, detail="Hafıza sorgusu çok sık çağrıldı; lütfen bekleyin")
    if not _main_pg_pool(): raise HTTPException(status_code=503, detail="PostgreSQL memory backend aktif değil")
    body = payload or {}
    text = str(body.get("query", "")).strip()
    if not text: raise HTTPException(status_code=400, detail="query gerekli")
    embedded = await llm_analysis.embedding(text, body.get("model_id"))
    if embedded.get("status") == "disabled":
        return {"query": text, "results": [], "count": 0, "status": "disabled", "message": embedded.get("error", "Embedding modeli aktif değil")}
    if embedded.get("status") != "ok": raise HTTPException(status_code=502, detail=embedded.get("error", "Embedding üretilemedi"))
    requested_symbol = str(body.get("symbol")).strip().upper() if body.get("symbol") else None
    async with _main_pg_pool().acquire() as conn:
        rows = await memory_service.retrieve(conn, embedded["vector"], limit=body.get("limit", 8), layer=body.get("layer"), symbol=requested_symbol, strategy=body.get("strategy"), timeframe=body.get("timeframe"), model_id=embedded.get("model_id"), query_text=text)
        await conn.execute("INSERT INTO memory_retrieval_logs(query_scope,query_text_hash,filters,model_id,result_ids,latency_ms) VALUES($1,$2,$3::jsonb,$4,$5::jsonb,$6)", body.get("scope", "memory"), memory_service.content_hash(text), json.dumps({k: body.get(k) for k in ("layer", "symbol", "strategy", "timeframe") if body.get(k) is not None}), embedded.get("model_id"), json.dumps([r.get("id") for r in rows]), None)
    return {"query": text, "results": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# API GECİKME ÖLÇÜMÜ (2026-10-30) — Ayarlar → Sistem Sağlığı
# ---------------------------------------------------------------------------
@router.get("/api/system/latency")
async def system_latency(request: Request):
    """Uç nokta başına gecikme istatistikleri (bellekte, yeniden başlatınca sıfırlanır).

    Yalnız yönetici. Yanıt: `routes` (p95'e göre azalan), `slow_requests`
    (eşik üstü son istekler) ve anlık `db_ping_ms` (`SELECT 1` gidiş-dönüşü).
    """
    from app.security import require_admin
    from app import latency_stats

    require_admin(request)
    snap = latency_stats.snapshot()
    db_ms = None
    pool = _main_pg_pool()
    if pool:
        try:
            t0 = time.perf_counter()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        except Exception as exc:  # pragma: no cover - ağ/DB hatası
            snap["db_error"] = f"{type(exc).__name__}"
    snap["db_ping_ms"] = db_ms
    return snap


@router.post("/api/system/llm-calibration")
async def llm_calibration_run(request: Request, days: int = 60,
                             min_samples: int | None = None, save: bool = True):
    """LLM güven kalibrasyonunu çalıştır (Ayarlar panelindeki düğme).

    Mantık `app/llm_calibration.py` (CLI ile AYNI kod). Yalnız ÖLÇÜM üretir ve
    artefakt yazar; `llm_review_min_confidence` ayarını DEĞİŞTİRMEZ — kullanıcı
    öneriyi görüp kendi uygular. Admin yetkisi gerekir.
    """
    from app.security import require_admin
    from app import llm_calibration

    require_admin(request)
    try:
        report = await llm_calibration.run(
            max(0, int(days or 0)), min_samples=min_samples,
            save=(llm_calibration.DEFAULT_ARTIFACT if save else None))
    except RuntimeError as exc:  # DATABASE_URL yok
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # DB erişimi/şema
        raise HTTPException(status_code=500, detail=f"kalibrasyon başarısız: {type(exc).__name__}")
    return report


@router.get("/api/system/cot")
async def cot_status():
    """COT artefaktının durumu (panel göstergesi): rapor tarihi + bayat mı?

    Admin gerekmez (kişisel veri yok, yalnız kamuya açık CFTC özeti).
    """
    from app import cot_fetch

    return {
        "summary": cot_positions.summary(),
        "age_days": cot_fetch.artifact_age_days(),
        "stale": cot_fetch.is_stale(),
        "stale_after_days": cot_fetch.STALE_AFTER_DAYS,
    }


def _system_universe() -> list[str]:
    """Sistemin GERÇEK işlem evreni (Ayarlar > Auto Paper allowed_symbols).

    Kartlar/LLM yüzeyleri yalnız bu sembolleri gösterir: kullanıcı "sistemde
    olmayan pariteyi neden gösteriyorsun" demesin. Evren okunamazsa güvenli
    çekirdek (XAUUSD + BTCUSD + majörler) döner.
    """
    try:
        from app.routers import forex as fx
        syms = [str(s).upper() for s in (fx._AUTO_SETTINGS.allowed_symbols or [])]  # noqa: SLF001
        if syms:
            # Altın ve BTC her hâlükârda listede olsun (Erkan: "altın ve btc")
            for must in ("XAUUSD", "BTCUSD"):
                if must not in syms:
                    syms.append(must)
            return syms
    except Exception:  # noqa: BLE001
        pass
    return ["XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "US30", "NAS100"]


@router.get("/api/system/retail-sentiment")
async def retail_sentiment_status(symbol: str | None = None, symbols: str = "",
                                   limit: int = 12, refresh: bool = False):
    """Perakende konumlanma (Myfxbook topluluk outlook) — ana sayfa tablosu + LLM bağlamı.

    BAĞLAMDIR, KAPI DEĞİL: karar akışını değiştirmez (COT/seans ile aynı sınıf).
    Tur aralığı **15 dk** (ücretsiz kota 100 istek/24s → 96). İstek yolu ağa çıkmaz;
    tazeleme arka planda yapılır. `refresh=true` yalnız ölçüm/panel için.

    Dönen satır, Myfxbook tablosunun aynısını besler: topluluk trendi (short/long),
    popülerlik (açık pozisyon payı), ortalama short/long giriş fiyatı ve **fiyata
    uzaklık (pip, işaretli)**, güncel fiyat.
    """
    from app import retail_sentiment as rs

    if refresh:
        await asyncio.to_thread(rs.refresh_blocking, True)
    else:
        await rs.hydrate_if_empty()   # ilk yüklemede "veri yok" demesin (DB'den)
        rs.ensure_fresh_async()
    s = rs.summary(symbol)
    # Hangi semboller gösterilecek: sistem evreni (XAUUSD + BTCUSD dahil) ya da açık liste
    syms = ([x.strip().upper() for x in symbols.split(",") if x.strip()]
            if symbols.strip() else _system_universe())
    all_rows = (rs._state.get("rows") or {})  # noqa: SLF001
    # YALNIZ SİSTEM EVRENİ (Erkan 2026-11-12): kullanıcı "sistemde olmayan pariteyi
    # neden gösteriyorsun" demesin. Myfxbook'ta 88 sembol var; kartta 14'ü görünür.
    # Evrende olup Myfxbook'ta olmayan sembol (endeksler) satır olarak EKLENMEZ —
    # zaten kapsam dışı; uydurma yok.
    rows = sorted((all_rows[s] for s in syms if s in all_rows),
                  key=lambda r: -int(r.get("total_positions") or 0))[: max(1, min(int(limit), 50))]
    # Popülerlik çubuğu evren İÇİNDE anlamlı olsun (88 sembolün en kalabalığına göre değil)
    max_pos = max((int(r.get("total_positions") or 0) for r in rows), default=0) or 1

    # Güncel fiyat: canlı tick önbelleği (WS/köprü). Yoksa uzaklık hesaplanmaz —
    # 0 yazıp "başabaş" gibi göstermek yanıltıcı olurdu.
    from app.routers import forex as fx

    # Fiyat: canlı tick önbelleği → yoksa son kapanış (köprü sessizken tablo boş kalmasın).
    _syms = [str(r["symbol"]) for r in rows]
    _last: dict = {}
    try:
        _last = await database.get_last_close_prices(_syms)
    except Exception:  # noqa: BLE001
        _last = {}

    items = []
    for r in rows:
        sym = str(r["symbol"])
        price = float(fx._LIVE_PRICES_CACHE.get(sym) or _last.get(sym) or 0.0)  # noqa: SLF001
        price_is_live = bool(fx._LIVE_PRICES_CACHE.get(sym))  # noqa: SLF001
        try:
            pip = float(fx.get_symbol_trading_specs(sym)["pip_size"])
        except Exception:  # noqa: BLE001
            pip = 0.0001
        alp = float(r.get("avg_long_price") or 0.0)
        asp = float(r.get("avg_short_price") or 0.0)
        items.append({
            "symbol": sym,
            "long_pct": float(r["long_pct"]),
            "short_pct": float(r["short_pct"]),
            "positions": int(r.get("total_positions") or 0),
            # Popülerlik çubuğu: en kalabalık pariteye göre pay (0-1)
            "popularity": round(int(r.get("total_positions") or 0) / max_pos, 4),
            "crowded": ("LONG" if float(r["long_pct"]) >= rs.RET_SENT_CROWD_PCT
                        else ("SHORT" if float(r["short_pct"]) >= rs.RET_SENT_CROWD_PCT
                              else None)),
            "price": price or None,
            "price_is_live": price_is_live,
            "avg_long_price": alp or None,
            "avg_short_price": asp or None,
            # İşaret kuralı Myfxbook ile aynı: KÂR yönü pozitif.
            # long kârda = fiyat ortalamanın ÜSTÜNDE; short kârda = fiyat ALTINDA.
            "dist_long_pips": (round((price - alp) / pip, 1) if (price and alp) else None),
            "dist_short_pips": (round((asp - price) / pip, 1) if (price and asp) else None),
            "long_volume": float(r.get("long_volume") or 0.0),
            "short_volume": float(r.get("short_volume") or 0.0),
        })
    return {"summary": s, "items": items}


@router.get("/api/system/sentiment-index")
async def sentiment_index_status(symbols: str = "", limit: int = 12):
    """BİLEŞİK SENTIMENT ENDEKSİ — parite başına −100 (SHORT) … +100 (LONG), merkez 0.

    Dört kanal birleşir: açıklanmış ekonomik veri (takvim), CFTC pozisyonlanması (COT),
    küresel nabız (DXY/10Y/VIX/S&P), perakende kalabalığı (Myfxbook, TERS yön).
    Ağırlıklar `sentiment_index.WEIGHTS`, kapsam şeffaf (`coverage`, `missing`).

    BAĞLAMDIR, KAPI DEĞİL: karar akışını değiştirmez.
    """
    from app import sentiment_index as si

    await asyncio.to_thread(_warm_sentiment_inputs)
    syms = ([s.strip().upper() for s in symbols.split(",") if s.strip()]
            if symbols.strip() else _system_universe())
    items = []
    for s in syms[: max(1, min(int(limit), 40))]:
        try:
            r = si.summarize(s)
        except Exception as exc:  # noqa: BLE001 — tek sembol tüm listeyi düşürmesin
            items.append({"symbol": s, "score": 0.0, "label": "hesaplanamadı",
                          "coverage": 0.0, "missing": [], "components": {},
                          "error": f"{type(exc).__name__}: {exc}"})
            continue
        items.append({
            "symbol": r["symbol"],
            "score": r["score"],
            "label": r["label"],
            "coverage": r["coverage"],
            "missing": r["missing"],
            "note": r["note"],
            "components": {
                k: {"score": v["score"], "detail": v.get("detail"), "available": v["available"],
                    **({"events": v.get("events")} if v.get("events") is not None else {}),
                    **({"long_pct": v.get("long_pct")} if v.get("long_pct") is not None else {})}
                for k, v in r["components"].items()
            },
        })
    return {"items": items, "weights": si.WEIGHTS,
            "neutral_band": si.NEUTRAL_BAND, "strong_band": si.STRONG_BAND}


def _warm_sentiment_inputs() -> None:
    """Takvim yön kanıtı + perakende belleğini senkron bağlamda ısıtır.

    Takvim: `get_forex_news()` asenkron ve önbellekli olduğu için burada kendi
    döngümüzle bir kez çağrılır (5 dk önbellek → ek yük yok). Hata olsa bile
    endeks çalışır: `takvim` bileşeni "veri yok" diye işaretlenir, nötr SAYILMAZ.
    """
    try:
        from app import forex_news_bias as nb
        from app import sentiment_index as si
        from app.forex_news import get_forex_news
        if not _has_running_loop():
            events = asyncio.run(get_forex_news())
            if events:
                # 30 dk ticaret filtresi önbelleği (radar kapısı kullanır)
                nb.refresh_biases(events, time.time(), window_sec=1800.0)
                # 24s yaş-ağırlıklı sentiment bileşeni
                si.refresh_calendar(events, time.time())
    except Exception as exc:  # noqa: BLE001
        logger.debug("sentiment takvim ısıtma atlandı: %s", exc)
    try:
        from app import retail_sentiment as rs
        rs.warm_sync()
    except Exception:  # noqa: BLE001
        pass


def _has_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


@router.get("/api/system/forex-ml")
async def forex_ml_status():
    """Forex ML veri seti + son eğitim koşuları (Ayarlar > Forex ML sekmesi)."""
    from app import database
    runs = await database.get_forex_ml_runs(limit=10)
    dataset = await database.get_forex_ml_dataset()
    art_path = Path(__file__).resolve().parents[2] / "artifacts" / "forex_ml.json"
    artifact = None
    try:
        import json as _json
        if art_path.exists():
            artifact = _json.loads(art_path.read_text(encoding="utf-8")).get("metrics")
    except Exception:  # noqa: BLE001
        artifact = None
    return {"dataset_n": len(dataset), "runs": runs, "artifact_metrics": artifact,
            "min_rows": 120, "test_fraction": 0.30}


@router.post("/api/system/forex-ml/train")
async def forex_ml_train(request: Request, min_rows: int = 120, save: bool = True):
    """Forex ML modelini eğit + OOS test et + kaydet (Ayarlar > Forex ML > Eğit).

    Veri sunucu DB'sinde olduğu için eğitim SUNUCUDA koşar (yerelde tablo boştur).
    Yalnız sklearn kullanır; artifact JSON'dur (pickle yok). Karar kapısı DEĞİL:
    OOS skill <= 0 ise rapor "kapı olmamalı" der.
    """
    from app.security import require_admin
    from app import forex_ml

    require_admin(request)
    # `forex_ml.run` ASYNC'tir → to_thread'e verilirse coroutine nesnesi döner ve
    # FastAPI serialization'da 500 verir (2026-11-10 vakası). Doğrudan await edilir.
    report = await forex_ml.run(min_rows=max(60, int(min_rows or 120)), save=bool(save))
    return report


@router.post("/api/system/cot-refresh")
async def cot_refresh(request: Request, years: str = "", keep_zip: bool = False):
    """COT pozisyonlanma raporunu indir ve artefaktı yaz (Ayarlar panelindeki düğme).

    Mantık `app/cot_fetch.py` — CLI ve otomatik tazeleme döngüsüyle AYNI kod.
    NEDEN GEREKLİ: `cot_positions` yalnız artefakt OKUR; indirme yalnız elle
    çalıştırılan bir betikti. LLM bağlamına bağlandıktan sonra üretimde artefakt
    hiç üretilmediği için LLM sürekli "COT verisi yok" diyordu (2026-11-09).
    Admin yetkisi gerekir.
    """
    from app.security import require_admin
    from app import cot_fetch

    require_admin(request)
    year_list = [int(y) for y in str(years or "").replace(" ", "").split(",") if y.strip().isdigit()]
    # İndirme bloklayıcı (urllib) → event loop'u kilitlememek için thread'e ver.
    return await asyncio.to_thread(cot_fetch.refresh, years=year_list or None, keep_zip=keep_zip)


@router.post("/api/system/latency/reset")
async def system_latency_reset(request: Request):
    from app.security import require_admin
    from app import latency_stats

    require_admin(request)
    latency_stats.reset()
    return {"status": "reset"}


# ── RUTİN KAYIT DEFTERİ (2026-11-10) ─────────────────────────────────────────
# Sunucu tarafı rutinler (DB-only): gölge/kapsam/kalibrasyon anlık görüntüleri.
# MT5 isteyen ölçüm probları sunucuda KOŞMAZ (terminal yok) → köprü makinesinde koşulur;
# burada "yerel gerekli" olarak raporlanır.

# 2026-11-12: sayfa `/api/system/routines` çağırıyordu ama yol `/system/routines`
# idi → "API 404". Diğer tüm uçlar `/api/...` altında; iki yol birlikte açılır
# (eski yol korunur, kimse kırılmaz).
@router.get("/api/system/routines")
@router.get("/system/routines")
async def list_routines(request: Request):
    """Rutin listesi + son çalıştırma durumu (panel görünümü)."""
    from app.routines.base import all_routines
    from app import database
    out = []
    for spec in all_routines():
        last = await database.get_routine_runs(spec.name, limit=1)
        row = last[0] if last else None
        out.append({
            "name": spec.name,
            "description": spec.description,
            "interval_sec": spec.interval_sec,
            "requires_mt5": spec.requires_mt5,
            "output_note": spec.output_note,
            "tags": spec.tags,
            "last_run_ts": row["started_ts"] if row else None,
            "last_ok": bool(row["ok"]) if row else None,
            "last_duration_ms": row["duration_ms"] if row else None,
            "last_result": row["result"] if row else None,
        })
    return {"count": len(out), "routines": out}


@router.post("/api/system/routines/{name}/run")
@router.post("/system/routines/{name}/run")
async def run_routine(name: str, request: Request):
    """Bir rutini elle koştur (vade beklemeden)."""
    from app.routines.base import run_once, get
    if get(name) is None:
        raise HTTPException(status_code=404, detail=f"rutin yok: {name}")
    return await run_once(name, force=True)


@router.get("/system/agents")
async def list_agent_charters():
    """Ajan sözleşmeleri (condor AGENT.md deseni): hangi uzman ne zaman, neyi YAPMAZ.

    LLM istemine giren yönlendirme tablosunun aynısı — panelde görünür olsun diye açıldı.
    """
    from app import agent_charters
    return {"count": len(agent_charters.CHARTERS), "agents": agent_charters.all_charters()}


@router.get("/system/arms")
async def list_signal_arms():
    """Sinyal kolları (dosya tabanlı, `signal()` sözleşmesi) — panel/denetim görünümü.

    Sözleşme: çıktı +1/−1/0; **0 = yeni sinyal yok, pozisyon KAPATMAZ**; `signal()` saf.
    """
    from app.arms.base import all_arms
    return {"count": len(all_arms()), "arms": [
        {"name": a.name, "description": a.description, "timeframe": a.timeframe,
         "symbols": a.symbols, "vectorized": a.vectorized, "evidence": a.evidence, "tags": a.tags}
        for a in all_arms()]}
