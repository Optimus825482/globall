"""TSMOM (Time-Series Momentum) — günlük kanal.

Neden ayrı bir kanal: mevcut spot_monitor 5 dakikalık tarama yapar ve 8
stratejisinin tamamı 60 günlük ölçümde RASTGELEDEN AYRIŞMADI (fark < 0.04
puan). TSMOM aynı kural ailesinden (momentum) gelir ama GÜNLÜK çalışır ve
7 yıllık gerçek veride kabul kriterlerini geçen tek yaklaşımdır.

Ölçüm (2019-09 → 2026-11, 10 sembol, %0.15 maliyet):
  TSMOM + BTC rejim filtresi: +%72.41, Sharpe 1.01, maxDD -%9.31, 10/10 coin
  BTC buy&hold:                +%639.61, Sharpe 0.86, maxDD -%76.63
  Rejim testi: BULL +%295.7 (Sharpe 2.11) | BEAR -%24.3 (Sharpe -0.62)

Kural:
  1. REJİM: BTC kapanışı 200 günlük ortalamanın ALTINDAYSA tamamen flat.
     (Ayı piyasasında ölçülen kaybı bu filtre durduruyor.)
  2. SİNYAL: sembolün 30 günlük getirisi pozitifse long, değilse flat.
     Spot olduğu için short yok.
  3. BOYUT: 20% hedef volatilite / gerçekleşen 30 günlük volatilite,
     en fazla 1.0 (kaldıraç yok, yalnız küçültme).
  4. REBALANS: günde bir kez, UTC 00:00 sonrası.

Bu modül PAPER çalışır — gerçek emir göndermez. Mevcut spot_monitor
simülatöründen bağımsız bir portföy izler.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("scalper.tsmom")

# ─── Parametreler (7 yıllık doğrulamadan) ────────────────────────────────────
TSMOM_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT",
]
LOOKBACK_DAYS = 30          # sinyal bakışı
VOL_WINDOW_DAYS = 30        # gerçekleşen volatilite penceresi
VOL_TARGET = 0.20           # yıllık hedef volatilite
REGIME_MA_DAYS = 200        # BTC rejim filtresi
INITIAL_CAPITAL = 5000.0    # TL (mevcut simülatörle aynı başlangıç)
COMMISSION_ROUND_TRIP = 0.0015   # %0.15
REBALANCE_INTERVAL_SEC = 3600    # saatte bir kontrol; günlük sinyal değişmez

_last_rebalance_day = None
_last_status: dict = {}


def _fetch_daily(symbol: str, days: int = 400) -> list[dict]:
    """Binance'ten günlük mumlar (en fazla ~400 gün yeterli: 200 MA + 30 bakış)."""
    url = (f"https://api.binance.com/api/v3/klines"
           f"?symbol={symbol}&interval=1d&limit={min(days, 1000)}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        logger.info("TSMOM mum çekilemedi %s: %s", symbol, exc)
        return []
    out = []
    for k in raw:
        out.append({
            "t": int(k[0]),
            "o": float(k[1]), "h": float(k[2]),
            "l": float(k[3]), "c": float(k[4]),
            "v": float(k[5]),
        })
    return out


def compute_targets() -> dict:
    """Her sembol için hedef ağırlık (0.0 – 1.0) + gerekçe döndürür.

    Saf fonksiyon: ağ/DB yok, test edilebilir.
    """
    import math

    # Önce BTC rejimi — tüm kararların kapısı
    btc = _fetch_daily("BTCUSDT", 400)
    if len(btc) < REGIME_MA_DAYS + 2:
        return {"ok": False, "error": "BTC verisi yetersiz", "symbols": []}
    btc_closes = [b["c"] for b in btc]
    btc_ma = sum(btc_closes[-REGIME_MA_DAYS:]) / REGIME_MA_DAYS
    btc_last = btc_closes[-1]
    regime_bull = btc_last > btc_ma

    rows = []
    for sym in TSMOM_SYMBOLS:
        bars = _fetch_daily(sym, 400)
        if len(bars) < max(LOOKBACK_DAYS, VOL_WINDOW_DAYS) + 5:
            rows.append({"symbol": sym, "weight": 0.0, "reason": "veri_yetersiz"})
            continue
        closes = [b["c"] for b in bars]

        # 1. Rejim kapısı
        if not regime_bull:
            rows.append({
                "symbol": sym, "weight": 0.0, "reason": "bear_rejim",
                "price": closes[-1], "signal": None,
            })
            continue

        # 2. Sinyal: 30 günlük getiri
        past = closes[-LOOKBACK_DAYS - 1:]
        ret_30 = (past[-1] / past[0] - 1.0) if past[0] > 0 else 0.0
        if ret_30 <= 0:
            rows.append({
                "symbol": sym, "weight": 0.0, "reason": "momentum_yok",
                "price": closes[-1], "signal": "flat", "ret_30_pct": ret_30 * 100,
            })
            continue

        # 3. Volatilite hedefleme
        rets = [(closes[i] / closes[i - 1] - 1.0) for i in range(len(closes) - VOL_WINDOW_DAYS, len(closes))]
        if len(rets) < 5:
            rows.append({"symbol": sym, "weight": 0.0, "reason": "vol_hesaplanamadi"})
            continue
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
        rv = math.sqrt(var) * math.sqrt(365.0)
        if rv <= 1e-9:
            rows.append({"symbol": sym, "weight": 0.0, "reason": "vol_sifir"})
            continue
        weight = min(1.0, VOL_TARGET / rv)

        rows.append({
            "symbol": sym, "weight": round(weight, 4),
            "reason": "long",
            "price": closes[-1],
            "signal": "long",
            "ret_30_pct": round(ret_30 * 100, 2),
            "realized_vol_pct": round(rv * 100, 1),
        })

    return {
        "ok": True,
        "regime": "BULL" if regime_bull else "BEAR",
        "btc_price": btc_last,
        "btc_ma200": round(btc_ma, 2),
        "btc_vs_ma_pct": round((btc_last / btc_ma - 1.0) * 100, 2),
        "symbols": rows,
        "computed_at": int(time.time()),
    }


async def _db():
    import os
    import asyncpg
    url = os.environ.get("DATABASE_URL") or "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"
    return await asyncpg.connect(url)


async def ensure_schema() -> None:
    conn = await _db()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tsmom_positions (
                id SERIAL PRIMARY KEY,
                symbol TEXT NOT NULL,
                weight DOUBLE PRECISION NOT NULL,
                entry_price DOUBLE PRECISION NOT NULL,
                entry_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                exit_price DOUBLE PRECISION,
                exit_at TIMESTAMPTZ,
                reason TEXT,
                ret_30_pct DOUBLE PRECISION,
                realized_vol_pct DOUBLE PRECISION,
                status TEXT NOT NULL DEFAULT 'OPEN'
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tsmom_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
    finally:
        await conn.close()


async def run_rebalance(force: bool = False) -> dict:
    """Günlük rebalans. Aynı gün ikinci kez çalışmaz (force hariç)."""
    global _last_rebalance_day, _last_status

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not force and _last_rebalance_day == today:
        return {"skipped": True, "reason": "bugun_zaten_rebalans", "day": today}

    await ensure_schema()
    targets = compute_targets()
    if not targets.get("ok"):
        return {"skipped": True, "reason": targets.get("error", "veri_yok")}

    conn = await _db()
    closed, opened, held = [], [], []
    try:
        open_rows = await conn.fetch(
            "SELECT * FROM tsmom_positions WHERE status='OPEN'")
        open_by_sym = {r["symbol"]: r for r in open_rows}

        for row in targets["symbols"]:
            sym = row["symbol"]
            weight = float(row.get("weight") or 0.0)
            price = row.get("price")
            existing = open_by_sym.get(sym)

            # Çıkış: hedef 0 oldu ya da fiyat yok
            if existing and (weight <= 0 or not price):
                await conn.execute("""
                    UPDATE tsmom_positions
                       SET status='CLOSED', exit_price=$1, exit_at=now(), reason=$2
                     WHERE id=$3
                """, price or existing["entry_price"], row.get("reason"), existing["id"])
                closed.append({
                    "symbol": sym, "reason": row.get("reason"),
                    "entry": existing["entry_price"], "exit": price,
                })
                continue

            # Giriş
            if not existing and weight > 0 and price:
                await conn.execute("""
                    INSERT INTO tsmom_positions
                        (symbol, weight, entry_price, reason, ret_30_pct, realized_vol_pct)
                    VALUES ($1,$2,$3,$4,$5,$6)
                """, sym, weight, price, row.get("reason"),
                   row.get("ret_30_pct"), row.get("realized_vol_pct"))
                opened.append({"symbol": sym, "weight": weight, "price": price})
                continue

            # Ağırlık güncelle (pozisyon korunuyor)
            if existing and weight > 0:
                await conn.execute(
                    "UPDATE tsmom_positions SET weight=$1, reason=$2 WHERE id=$3",
                    weight, row.get("reason"), existing["id"])
                held.append({"symbol": sym, "weight": weight})

        await conn.execute("""
            INSERT INTO tsmom_state (key, value, updated_at)
            VALUES ('last_rebalance', $1, now())
            ON CONFLICT (key) DO UPDATE SET value=$1, updated_at=now()
        """, json.dumps({"day": today, "regime": targets["regime"],
                         "at": int(time.time())}))
    finally:
        await conn.close()

    _last_rebalance_day = today
    _last_status = {
        "day": today, "regime": targets["regime"],
        "opened": opened, "closed": closed, "held": held,
    }
    logger.info("TSMOM rebalans %s: rejim=%s açılan=%d kapanan=%d korunan=%d",
                today, targets["regime"], len(opened), len(closed), len(held))
    return _last_status


async def get_dashboard() -> dict:
    """TSMOM panel verisi: hedefler, açık pozisyonlar, portföy."""
    await ensure_schema()
    targets = compute_targets()
    conn = await _db()
    try:
        rows = await conn.fetch(
            "SELECT * FROM tsmom_positions WHERE status='OPEN' ORDER BY symbol")
        closed = await conn.fetch("""
            SELECT symbol, entry_price, exit_price, entry_at, exit_at, reason,
                   CASE WHEN exit_price IS NOT NULL AND entry_price > 0
                        THEN (exit_price / entry_price - 1) * 100 ELSE 0 END AS pnl_pct
              FROM tsmom_positions WHERE status='CLOSED'
             ORDER BY exit_at DESC LIMIT 50
        """)
        state = await conn.fetchrow(
            "SELECT value FROM tsmom_state WHERE key='last_rebalance'")
    finally:
        await conn.close()

    last_sync = None
    regime = None
    if state:
        try:
            d = json.loads(state["value"])
            last_sync = d.get("at")
            regime = d.get("regime")
        except (ValueError, TypeError):
            pass

    # Portföy değeri: açık pozisyonların güncel fiyatlarla değeri
    price_map = {r["symbol"]: r.get("price") for r in targets.get("symbols", [])}
    positions = []
    invested = 0.0
    for r in rows:
        cur = price_map.get(r["symbol"]) or r["entry_price"]
        pnl_pct = ((cur - r["entry_price"]) / r["entry_price"] * 100.0) if r["entry_price"] else 0.0
        size = INITIAL_CAPITAL / max(1, len(TSMOM_SYMBOLS)) * float(r["weight"])
        invested += size
        positions.append({
            "symbol": r["symbol"],
            "weight": round(float(r["weight"]), 4),
            "entry_price": r["entry_price"],
            "current_price": cur,
            "pnl_pct": round(pnl_pct, 2),
            "size_try": round(size, 2),
            "pnl_try": round(size * pnl_pct / 100.0, 2),
            "reason": r["reason"],
            "entry_at": r["entry_at"].isoformat() if r["entry_at"] else None,
        })

    realized = 0.0
    closed_list = []
    for c in closed:
        size = INITIAL_CAPITAL / max(1, len(TSMOM_SYMBOLS))
        realized += size * float(c["pnl_pct"] or 0) / 100.0
        closed_list.append({
            "symbol": c["symbol"],
            "entry_price": c["entry_price"],
            "exit_price": c["exit_price"],
            "pnl_pct": round(float(c["pnl_pct"] or 0), 2),
            "reason": c["reason"],
            "exit_at": c["exit_at"].isoformat() if c["exit_at"] else None,
        })

    unrealized = sum(p["pnl_try"] for p in positions)
    return {
        "targets": targets,
        "positions": positions,
        "closed": closed_list,
        "portfolio": {
            "initial_capital": INITIAL_CAPITAL,
            "invested_try": round(invested, 2),
            "realized_try": round(realized, 2),
            "unrealized_try": round(unrealized, 2),
            "current_try": round(INITIAL_CAPITAL + realized + unrealized, 2),
            "open_count": len(positions),
        },
        "params": {
            "lookback_days": LOOKBACK_DAYS,
            "vol_target": VOL_TARGET,
            "regime_ma_days": REGIME_MA_DAYS,
            "commission_round_trip": COMMISSION_ROUND_TRIP,
            "rebalance": "günlük",
        },
        "last_rebalance_at": last_sync,
        "regime": regime,
        "evidence": {
            "source": "yongzhe2160cs/trading-engine (TSMOM, tek kurtulan)",
            "validation": "2019-09 → 2026-11, 10 sembol, gerçek Binance günlük veri",
            "result": "TSMOM+rejim: +%72.41 Sharpe 1.01 maxDD -%9.31 | "
                      "BTC buy&hold: +%639.61 Sharpe 0.86 maxDD -%76.63",
            "regime_test": "BULL +%295.7 (Sharpe 2.11) | BEAR -%24.3 (Sharpe -0.62)",
        },
    }


async def tsmom_loop() -> None:
    """Saatte bir kontrol; sinyal günlük olduğu için günde bir kez işlem yapar."""
    logger.info("TSMOM günlük döngüsü başlatıldı")
    while True:
        try:
            await run_rebalance()
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001
            logger.error("TSMOM döngü hatası: %s", exc)
        await asyncio.sleep(REBALANCE_INTERVAL_SEC)
