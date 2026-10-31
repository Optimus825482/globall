"""Spot Monitor Scanner and Portfolio Simulator for Binance TR."""
import asyncio
import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
import asyncpg
from app.config import config
from app.technical_analysis import _kdj, _supertrend, _ema_pullback_bounce, _stc, _zlmacd, _ema, _bb_kc_squeeze

logger = logging.getLogger("scalper.spot_monitor")

# Simülasyon Sabitleri
INITIAL_PORTFOLIO_TRY = 5000.0
TRADE_SIZE_TRY = 300.0
COMMISSION_RATE = 0.0004 # %0.04 Maker/Taker

# Taranacak ana ve hacimli semboller
CORE_SYMBOLS = [
    "BTCTRY", "ETHTRY", "SOLTRY", "AVAXTRY", "NEARTRY", "DOGETRY", 
    "PEPETRY", "BNBTRY", "XRPTRY", "LINKTRY", "SHIBTRY", "ADATRY",
    "DOTTRY", "RENDERTRY", "FETTRY", "ARBTRY", "OPTRY", "INJTRY"
]

TIMEFRAMES = {
    "5m": {"tp_pct": 1.5, "sl_pct": 0.9, "label": "5m Scalp"},
    "15m": {"tp_pct": 2.2, "sl_pct": 1.2, "label": "15m Standart"},
    "1h": {"tp_pct": 4.0, "sl_pct": 2.0, "label": "1h Swing"}
}

# Aktif tarama stratejileri kaydı — run_single_scan() içindeki kurallarla senkron tutulmalı.
# Sıra = run_single_scan() içindeki öncelik sırası (ilk eşleşen kural kazanır).
ACTIVE_STRATEGIES = [
    {
        "code": "ema_bounce",
        "label": "EMA 50 Sekmesi + KDJ Dip",
        "score": 94.0,
        "description": "Ana trend içinde EMA50 desteğine geri çekilme + KDJ dip teyidiyle sekme girişi.",
        "evidence": "Lab şampiyonu: WinRate %83-100",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "squeeze_breakout",
        "label": "BB-KC Sıkışma Kırılımı",
        "score": 93.0,
        "description": "Bollinger bantları Keltner kanalına sıkıştıktan sonra kapanışın üst bandı yukarı kesmesi (volatilite genişleme kırılımı).",
        "evidence": "Lab v2 (5m): WR %56.8, PF 1.74, 13/17 coin pozitif",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "stc_cycle",
        "label": "Schaff Trend Cycle (STC Dip)",
        "score": 92.0,
        "description": "STC'nin 25 seviyesinin altından yukarı kırılmasıyla döngüsel dip dönüş girişi.",
        "evidence": "SOL/LINK şampiyonu: WinRate %64+, PF 2.79",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "zlmacd_momentum",
        "label": "Zero-Lag MACD + Momentum",
        "score": 90.0,
        "description": "ZLMACD histogramının sıfırı yukarı kesmesi + EMA20 ≥ EMA50 trend filtresi.",
        "evidence": "OP şampiyonu: PF 2.17",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "supertrend_pullback",
        "label": "SuperTrend Pullback (KDJ Dip)",
        "score": 88.0,
        "description": "SuperTrend boğa yönündeyken KDJ dip kesişimiyle trend içi geri çekilme girişi.",
        "evidence": "SuperTrend(10, 3.0) dinamik ATR trend filtresi",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "kdj_pure_dip",
        "label": "KDJ Saf Dip (J≤12)",
        "score": 82.0,
        "description": "KDJ J eğrisinin ekstrem aşırı satım bölgesinden (J≤12) yukarı sıçraması.",
        "evidence": "Ekstrem dip yakalayıcı destek kuralı",
        "timeframes": ["5m", "15m", "1h"],
    },
]

_monitor_running = False
_last_scan_time = 0.0
_cached_results = {
    "live_signals": [],
    "summary": {},
    "portfolio": {}
}

async def get_db_conn():
    import os
    db_url = os.environ.get("DATABASE_URL") or "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"
    return await asyncpg.connect(db_url)

def _fetch_klines(symbol: str, interval: str, limit: int = 100) -> list:
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return []

def _fetch_all_prices() -> dict:
    url = "https://api.binance.com/api/v3/ticker/price"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            return {d["symbol"]: float(d["price"]) for d in data if d["symbol"].endswith("TRY")}
    except Exception:
        return {}

def get_active_strategies() -> dict:
    """Panelden görüntülenmek üzere aktif tarama stratejilerini ve tarama parametrelerini döndürür."""
    return {
        "count": len(ACTIVE_STRATEGIES),
        "symbols_count": len(CORE_SYMBOLS),
        "timeframes": [
            {"code": tf, "label": cfg["label"], "tp_pct": cfg["tp_pct"], "sl_pct": cfg["sl_pct"]}
            for tf, cfg in TIMEFRAMES.items()
        ],
        "trade_size_try": TRADE_SIZE_TRY,
        "initial_portfolio_try": INITIAL_PORTFOLIO_TRY,
        "commission_rate": COMMISSION_RATE,
        "strategies": ACTIVE_STRATEGIES,
    }

async def run_single_scan():
    """Tüm sembollerde 3 zaman diliminde KDJ, SuperTrend ve EMA50 taraması yapar."""
    global _cached_results, _last_scan_time
    start_ts = time.time()
    discovered_signals = []

    conn = await get_db_conn()
    try:
        # 1. Eski mükerrer açık kayıtları temizle (aynı sembolde birden fazla OPEN varsa en eskisini tut, fazlalıkları sil)
        await conn.execute("""
            DELETE FROM spot_monitor_signals
            WHERE status = 'OPEN'
              AND id NOT IN (
                  SELECT MIN(id)
                  FROM spot_monitor_signals
                  WHERE status = 'OPEN'
                  GROUP BY symbol
              )
        """)

        # 2. Hangi sembollerde zaten AÇIK pozisyon var?
        existing_open = await conn.fetch("SELECT symbol FROM spot_monitor_signals WHERE status = 'OPEN'")
        open_symbols = {r["symbol"] for r in existing_open}
        max_positions = int(INITIAL_PORTFOLIO_TRY // TRADE_SIZE_TRY)

        for sym in CORE_SYMBOLS:
            # Bu sembolde zaten açık pozisyon varsa yeni işlem açma
            if sym in open_symbols:
                continue
            if len(open_symbols) >= max_positions:
                break

            for tf, tf_cfg in TIMEFRAMES.items():
                if sym in open_symbols:
                    break

                klines = _fetch_klines(sym, tf, limit=100)
                if len(klines) < 65:
                    continue

                highs = [float(k[2]) for k in klines]
                lows = [float(k[3]) for k in klines]
                closes = [float(k[4]) for k in klines]
                price = closes[-1]
                quote_vols = [float(k[7]) for k in klines]
                trades = [int(k[8]) for k in klines]

                # ─── HACİM VE DURAĞANLIK (ÖLÜ TAHTA) FİLTRELERİ ───
                # 1. Durağanlık (Ölü Range): Son 20 barda tepe-dip farkı %0.40 altındaysa saatlerce hareket etmeyen ölü tahta elenir
                recent_range_pct = ((max(highs[-20:]) - min(lows[-20:])) / price) * 100.0
                if recent_range_pct < 0.40:
                    continue

                # 2. Minimum Bar Hacmi: Son 20 bar ortalama TRY hacmi en az 20.000 TL olmalı
                avg_bar_try_vol = sum(quote_vols[-20:]) / 20.0
                if avg_bar_try_vol < 20_000.0:
                    continue

                # 3. Derinlik / İşlem Sayısı: Bar başına en az ortalama 3 trade gerçekleşmiş olmalı
                avg_trades = sum(trades[-20:]) / 20.0
                if avg_trades < 3.0:
                    continue

                # 4. Hacimsiz Sahte Mum Koruması: Sinyal mumunun hacmi, ortalama bar hacminin %30'undan az olmamalı
                if quote_vols[-1] < (avg_bar_try_vol * 0.30):
                    continue

                kdj = _kdj(highs, lows, closes, period=9, signal=3) or {}
                st = _supertrend(highs, lows, closes, period=10, factor=3.0) or {}
                ema = _ema_pullback_bounce(closes, lows, period=50, tolerance_pct=0.010) or {}
                stc = _stc(closes, period=10, fast=23, slow=50) or {}
                zl = _zlmacd(closes, fast=12, slow=26, signal=9) or {}
                sq = _bb_kc_squeeze(highs, lows, closes) or {}
                ema20 = _ema(closes, 20)
                ema50 = _ema(closes, 50)

                j_val = float(kdj.get("j", 50.0))
                dip_buy = bool(kdj.get("dip_buy"))
                st_bull = bool(st.get("bullish"))
                ema_bounce = bool(ema.get("pullback_bounce"))
                dist_ema = ema.get("dist_pct")

                stc_dip = bool(stc.get("dip_buy"))
                stc_val = float(stc.get("stc", 50.0))

                sq_break = bool(sq.get("breakout"))
                sq_bb_up = float(sq.get("bb_upper", 0.0))
                sq_width = float(sq.get("bb_width_pct", 0.0))

                zl_cross = bool(zl.get("bullish_cross"))
                zl_hist = float(zl.get("hist", 0.0))
                trend_bull = bool(ema20 is not None and ema50 is not None and ema20 >= ema50)

                matched = False
                strategy_code = ""
                strategy_label = ""
                score = 70.0
                note = ""

                # 1. EMA 50 Pullback Bounce + KDJ (WinRate %83-%100 Şampiyonu)
                if ema_bounce and (dip_buy or j_val <= 25.0):
                    matched = True
                    strategy_code = "ema_bounce"
                    strategy_label = "EMA 50 Sekmesi + KDJ Dip"
                    score = 94.0
                    note = f"EMA50 desteginde (%{dist_ema}), KDJ J={j_val:.1f}"

                # 2. BB-KC Sıkışma Kırılımı (Lab v2: 5m WR %56.8, PF 1.74, 13/17 coin pozitif,
                #    26 komşu parametreden 23'ü net pozitif — sağlamlık doğrulandı)
                elif sq_break:
                    matched = True
                    strategy_code = "squeeze_breakout"
                    strategy_label = "BB-KC Sıkışma Kırılımı"
                    score = 93.0
                    note = f"Bollinger-Keltner sikismasi sonrasi ust bant kirilimi (BBU={sq_bb_up:.6g}, BBW=%{sq_width:.2f})"

                # 3. Schaff Trend Cycle (STC) Dip Dönüşü (SOL/LINK Şampiyonu WinRate %64+, PF 2.79)
                elif stc_dip:
                    matched = True
                    strategy_code = "stc_cycle"
                    strategy_label = "Schaff Trend Cycle (STC Dip)"
                    score = 92.0
                    note = f"STC 25 altından yukarı kırdı (STC={stc_val:.1f})"

                # 4. Zero-Lag MACD + EMA 20/50 Momentum Sıçraması (OP/AVAX Şampiyonu PF 2.17)
                elif zl_cross and trend_bull:
                    matched = True
                    strategy_code = "zlmacd_momentum"
                    strategy_label = "Zero-Lag MACD + Momentum"
                    score = 90.0
                    note = f"ZLMACD sıfırı yukarı kesti (Hist={zl_hist:.4f}), EMA20>=EMA50"

                # 5. SuperTrend Boğada KDJ Dip Kesişimi
                elif st_bull and dip_buy:
                    matched = True
                    strategy_code = "supertrend_pullback"
                    strategy_label = "SuperTrend Pullback (KDJ Dip)"
                    score = 88.0
                    note = f"SuperTrend Boğada, KDJ J={j_val:.1f} yukarı kesti"

                # 6. KDJ Ekstrem Saf Dip Dönüşü
                elif dip_buy and j_val <= 12.0:
                    matched = True
                    strategy_code = "kdj_pure_dip"
                    strategy_label = "KDJ Saf Dip (J<=12)"
                    score = 82.0
                    note = f"Ekstrem aşırı satım sıçraması J={j_val:.1f}"

                if matched:
                    tp_pct = tf_cfg["tp_pct"]
                    sl_pct = tf_cfg["sl_pct"]
                    target_p = price * (1.0 + (tp_pct / 100.0))
                    stop_p = price * (1.0 - (sl_pct / 100.0))
                    sig_key = f"{sym}-{tf}-{strategy_code}-{int(start_ts)}"

                    discovered_signals.append({
                        "signal_key": sig_key,
                        "symbol": sym,
                        "timeframe": tf,
                        "strategy": strategy_code,
                        "strategy_label": strategy_label,
                        "entry_price": price,
                        "target_price": target_p,
                        "stop_price": stop_p,
                        "score": score,
                        "kdj_j": j_val,
                        "details": {"note": note, "tp_pct": tp_pct, "sl_pct": sl_pct, "range_pct": round(recent_range_pct, 2), "avg_vol_try": round(avg_bar_try_vol, 0)},
                        "detected_at": datetime.now(timezone.utc)
                    })
                    open_symbols.add(sym)
                    break

        for s in discovered_signals:
            await conn.execute("""
                INSERT INTO spot_monitor_signals (
                    signal_key, symbol, timeframe, strategy, strategy_label,
                    entry_price, target_price, stop_price, score, kdj_j, details,
                    trade_size_try, commission_try
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT (signal_key) DO NOTHING
            """, s["signal_key"], s["symbol"], s["timeframe"], s["strategy"], s["strategy_label"],
               s["entry_price"], s["target_price"], s["stop_price"], s["score"], s["kdj_j"],
               json.dumps(s["details"]), TRADE_SIZE_TRY, (TRADE_SIZE_TRY * COMMISSION_RATE * 2))

        # Açık pozisyonların güncel kâr/zarar ve kapanış takibini yap
        await update_open_signals_pnl(conn)
    finally:
        await conn.close()

    _last_scan_time = time.time()
    return len(discovered_signals)

async def update_open_signals_pnl(conn):
    """Açık pozisyonları anlık fiyatlarla denetler, TP veya SL tetiklendiyse kapatır."""
    open_rows = await conn.fetch("SELECT * FROM spot_monitor_signals WHERE status = 'OPEN'")
    if not open_rows:
        return

    prices = _fetch_all_prices()
    now_utc = datetime.now(timezone.utc)

    for row in open_rows:
        sym = row["symbol"]
        curr_p = prices.get(sym)
        if not curr_p:
            continue

        entry_p = row["entry_price"]
        target_p = row["target_price"]
        stop_p = row["stop_price"]
        pnl_pct = ((curr_p - entry_p) / entry_p) * 100.0

        # MFE / MAE güncelleme
        old_mfe = row["mfe_pct"] or 0.0
        old_mae = row["mae_pct"] or 0.0
        new_mfe = max(old_mfe, pnl_pct)
        new_mae = min(old_mae, pnl_pct)

        status = "OPEN"
        exit_price = None
        exit_time = None
        net_try = 0.0
        comm_try = row["commission_try"] or (TRADE_SIZE_TRY * COMMISSION_RATE * 2)

        # TP Hedefine Ulaştı mı?
        if curr_p >= target_p:
            status = "WIN_TP"
            exit_price = target_p
            exit_time = now_utc
            gross_profit = TRADE_SIZE_TRY * ((target_p - entry_p) / entry_p)
            net_try = gross_profit - comm_try

        # Stop-Loss Seviyesine İndi mi?
        elif curr_p <= stop_p:
            status = "LOSS_SL"
            exit_price = stop_p
            exit_time = now_utc
            gross_loss = TRADE_SIZE_TRY * ((stop_p - entry_p) / entry_p)
            net_try = gross_loss - comm_try

        # Süre Aşımı (24 saat geçtiyse ve kapanmadıysa anlık fiyattan realize et)
        elif (now_utc - row["detected_at"]).total_seconds() > 86400:
            status = "EXPIRED"
            exit_price = curr_p
            exit_time = now_utc
            gross_ret = TRADE_SIZE_TRY * (pnl_pct / 100.0)
            net_try = gross_ret - comm_try

        if status != "OPEN":
            await conn.execute("""
                UPDATE spot_monitor_signals
                SET status = $1, exit_price = $2, exit_time = $3,
                    pnl_pct = $4, mfe_pct = $5, mae_pct = $6, net_pnl_try = $7
                WHERE id = $8
            """, status, exit_price, exit_time, pnl_pct, new_mfe, new_mae, net_try, row["id"])
        else:
            # Açık durumu anlık metriklerle güncelle
            await conn.execute("""
                UPDATE spot_monitor_signals
                SET pnl_pct = $1, mfe_pct = $2, mae_pct = $3
                WHERE id = $4
            """, pnl_pct, new_mfe, new_mae, row["id"])

async def get_spot_monitor_dashboard():
    """Frontend arayüzü için anlık sinyalleri, geçmişi, başarı oranını ve 5.000 TL portföy simülasyonunu döndürür."""
    conn = await get_db_conn()
    try:
        # Eski mükerrer açık kayıtları temizle (aynı sembolde birden fazla OPEN varsa en eskisini tut, fazlalıkları sil)
        await conn.execute("""
            DELETE FROM spot_monitor_signals
            WHERE status = 'OPEN'
              AND id NOT IN (
                  SELECT MIN(id)
                  FROM spot_monitor_signals
                  WHERE status = 'OPEN'
                  GROUP BY symbol
              )
        """)

        # 1. Tüm sinyaller
        rows = await conn.fetch("SELECT * FROM spot_monitor_signals ORDER BY detected_at DESC LIMIT 100")
        
        # 2. İstatistikler
        total_signals = len(rows)
        closed_signals = [r for r in rows if r["status"] != "OPEN"]
        open_signals = [r for r in rows if r["status"] == "OPEN"]

        win_count = len([r for r in closed_signals if r["status"] == "WIN_TP"])
        loss_count = len([r for r in closed_signals if r["status"] == "LOSS_SL"])
        win_rate = (win_count / len(closed_signals) * 100.0) if closed_signals else 0.0

        # 3. 5.000 TL Simüle Portföy Büyüklüğü
        # Her işlem 300 TL sabit; kâr/zararlar realized ve unrealized olarak eklenir.
        realized_pnl = sum([r["net_pnl_try"] or 0.0 for r in closed_signals])
        
        # Açık işlemlerin anlık kâr/zararı
        prices = _fetch_all_prices()
        unrealized_pnl = 0.0
        active_items = []

        for r in rows:
            curr_p = prices.get(r["symbol"], r["entry_price"])
            pnl_pct = ((curr_p - r["entry_price"]) / r["entry_price"]) * 100.0 if r["status"] == "OPEN" else (r["pnl_pct"] or 0.0)
            
            if r["status"] == "OPEN":
                comm = r["commission_try"] or (TRADE_SIZE_TRY * COMMISSION_RATE * 2)
                item_net = (TRADE_SIZE_TRY * (pnl_pct / 100.0)) - comm
                unrealized_pnl += item_net

            active_items.append({
                "id": r["id"],
                "symbol": r["symbol"],
                "timeframe": r["timeframe"],
                "strategy": r["strategy"],
                "strategy_label": r["strategy_label"],
                "entry_price": r["entry_price"],
                "current_price": curr_p,
                "target_price": r["target_price"],
                "stop_price": r["stop_price"],
                "score": r["score"],
                "kdj_j": r["kdj_j"],
                "status": r["status"],
                "pnl_pct": round(pnl_pct, 2),
                "mfe_pct": round(r["mfe_pct"] or 0.0, 2),
                "net_pnl_try": round(r["net_pnl_try"] or 0.0, 2) if r["status"] != "OPEN" else round((TRADE_SIZE_TRY * (pnl_pct / 100.0)) - (r["commission_try"] or 0.24), 2),
                "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
                "exit_time": r["exit_time"].isoformat() if r["exit_time"] else None,
                "details": json.loads(r["details"]) if isinstance(r["details"], str) else (r["details"] or {})
            })

        total_portfolio_try = INITIAL_PORTFOLIO_TRY + realized_pnl + unrealized_pnl
        portfolio_growth_pct = ((total_portfolio_try - INITIAL_PORTFOLIO_TRY) / INITIAL_PORTFOLIO_TRY) * 100.0

        open_positions_count = len(open_signals)
        in_positions_try = open_positions_count * TRADE_SIZE_TRY
        free_balance_try = max(0.0, (INITIAL_PORTFOLIO_TRY + realized_pnl) - in_positions_try)

        return {
            "portfolio": {
                "initial_balance_try": INITIAL_PORTFOLIO_TRY,
                "current_balance_try": round(total_portfolio_try, 2),
                "free_balance_try": round(free_balance_try, 2),
                "in_positions_try": round(in_positions_try, 2),
                "realized_pnl_try": round(realized_pnl, 2),
                "unrealized_pnl_try": round(unrealized_pnl, 2),
                "growth_pct": round(portfolio_growth_pct, 2),
                "trade_size_try": TRADE_SIZE_TRY,
                "open_positions_count": open_positions_count
            },
            "metrics": {
                "total_signals": total_signals,
                "closed_count": len(closed_signals),
                "open_count": len(open_signals),
                "win_count": win_count,
                "loss_count": loss_count,
                "win_rate_pct": round(win_rate, 1)
            },
            "signals": active_items,
            "last_scan_time": _last_scan_time
        }
    finally:
        await conn.close()

async def spot_monitor_background_loop():
    """Her 60 saniyede bir çalışan arka plan tarayıcısı."""
    global _monitor_running
    _monitor_running = True
    logger.info("Spot Monitor arka plan tarayıcısı başlatıldı.")
    
    while _monitor_running:
        try:
            await run_single_scan()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Spot monitor döngü hatası: %s", exc)
        await asyncio.sleep(60)

def start_spot_monitor_loop():
    loop = asyncio.get_event_loop()
    loop.create_task(spot_monitor_background_loop())
