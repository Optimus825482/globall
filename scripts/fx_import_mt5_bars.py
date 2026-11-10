#!/usr/bin/env python3
"""MT5 → `historical_candles` IMPORT (2026-11-10)

NEDEN
-----
Replay zaten **önce** `historical_candles` (MT5 köprüsü verisi) okuyor; Yahoo yalnız
o sembol DB'de yoksa devreye giren yedek (`--source auto`). Yerelde FX satırı
olmadığı için her koşu 48 MB Yahoo indirmesi + 60 günde ~14 dakika sürüyordu ve
barlar broker'ın değil Yahoo'nun (farklı seans/kesinti davranışı, mid fiyat).

Bu betik MT5 terminalinden **bid tabanlı gerçek barları** çeker ve replay'in
okuduğu tabloya yazar. Sonrasında `--source auto` ağa hiç çıkmaz.

Çıktı şeması `historical_candles` ile birebir: (symbol, timeframe, open_time ms,
close_time ms, o, h, l, c, volume, quote_volume, trade_count, source, fetched_at).
Çakışma anahtarı (symbol, timeframe, open_time) → idempotent (tekrar koşmak zararsız).

Kullanim:
    python scripts/fx_import_mt5_bars.py --days 60 --timeframe 5m
    python scripts/fx_import_mt5_bars.py --days 60 --timeframe 5m --symbols XAUUSD,USDJPY
    python scripts/fx_import_mt5_bars.py --days 90 --timeframe 1m --all-symbols
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 yok — Python 3.12'yi tam yolla cagirin.")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "backend"))

TFS = {"1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15,
       "30m": mt5.TIMEFRAME_M30, "1h": mt5.TIMEFRAME_H1}
SEC = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}


def db_url() -> str:
    u = (os.environ.get("DATABASE_URL") or "").strip()
    if u:
        return u
    try:
        with open(os.path.join(ROOT, "backend", ".env"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("DATABASE_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass
    return ""


def fetch_bars(symbol: str, tf: str, days: int, chunk_days: int = 10) -> list[tuple]:
    """Barları gün dilimleriyle çeker; eksik sembolde boş liste döner."""
    out: list[tuple] = []
    end = dt.datetime.now()
    i = 0
    while i < days:
        b_end = end - dt.timedelta(days=i)
        b_start = max(b_end - dt.timedelta(days=chunk_days), end - dt.timedelta(days=days))
        rates = mt5.copy_rates_range(symbol, TFS[tf], b_start, b_end)
        if rates is not None and len(rates):
            out.extend((int(r["time"]), float(r["open"]), float(r["high"]),
                        float(r["low"]), float(r["close"]),
                        float(r["tick_volume"]), float(r["spread"]), int(r["real_volume"]))
                       for r in rates)
        i += chunk_days
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="MT5 barlarını historical_candles'a yaz")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--timeframe", default="5m", choices=sorted(TFS))
    ap.add_argument("--symbols", default="", help="virgüllü liste (boş = forex evreni)")
    ap.add_argument("--all-symbols", action="store_true", help="FOREX_SYMBOLS tam listesi")
    ap.add_argument("--source-label", default="mt5_local_replay")
    args = ap.parse_args()

    if not mt5.initialize():
        print(f"[HATA] MT5 initialize basarisiz: {mt5.last_error()}")
        return 2
    ai = mt5.account_info()
    if ai:
        print(f"Hesap {ai.login} {ai.server} | equity {ai.equity:.2f} {ai.currency}")

    if args.symbols.strip():
        syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        try:
            from app.routers import forex as fx_mod
            syms = ([s["symbol"] for s in fx_mod.FOREX_SYMBOLS] if args.all_symbols
                    else sorted(set(fx_mod.YAHOO_SYMBOL_MAP)))
        except Exception as exc:  # noqa: BLE001
            print(f"[HATA] sembol evreni okunamadi ({type(exc).__name__}) — --symbols verin")
            mt5.shutdown()
            return 2

    url = db_url()
    if not url:
        print("[HATA] DATABASE_URL yok")
        mt5.shutdown()
        return 2
    import psycopg

    total, skipped, failed = 0, [], []
    # Broker adı eşlemesi: uygulama adı (NAS100) ≠ terminal adı (USTEC).
    # Köprünün kendi tablosu kullanılır ki replay/köprü ile AYNI sembolde yazılsın.
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from mt5_bridge import SYMBOL_ALIAS_MAP  # type: ignore
    except Exception:  # noqa: BLE001
        SYMBOL_ALIAS_MAP = {}

    def broker_names(app_sym: str) -> list[str]:
        return list(SYMBOL_ALIAS_MAP.get(app_sym, [app_sym]))

    with psycopg.connect(url) as conn:
        for sym in syms:
            info = None
            used = sym
            for cand in broker_names(sym):
                if mt5.symbol_info(cand) is not None:
                    used, info = cand, mt5.symbol_info(cand)
                    break
            if info is None:
                skipped.append(sym)
                continue
            if not info.visible:
                mt5.symbol_select(used, True)
            bars = fetch_bars(used, args.timeframe, args.days)
            if not bars:
                failed.append(sym)
                continue
            step = SEC[args.timeframe] * 1000
            rows = [(sym, args.timeframe, t * 1000, t * 1000 + step, o, h, l, c,
                     vol, 0.0, 0, args.source_label, dt.datetime.now().timestamp())
                    for (t, o, h, l, c, vol, _spread, _rv) in bars]
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO historical_candles (symbol, timeframe, open_time, close_time, "
                    "open, high, low, close, volume, quote_volume, trade_count, source, fetched_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (symbol, timeframe, open_time) DO UPDATE SET "
                    "close_time=EXCLUDED.close_time, open=EXCLUDED.open, high=EXCLUDED.high, "
                    "low=EXCLUDED.low, close=EXCLUDED.close, volume=EXCLUDED.volume, "
                    "source=EXCLUDED.source, fetched_at=EXCLUDED.fetched_at", rows)
            conn.commit()
            total += len(rows)
            # Dilimler yeniden-eskiye çekildiği için liste sırası ters; GERÇEK aralık min/max'tan.
            lo = min(b[0] for b in bars)
            hi = max(b[0] for b in bars)
            fmt = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%m-%d %H:%M")
            print(f"  {sym:<9} {len(rows):>6} bar  {fmt(lo)} → {fmt(hi)}")
    mt5.shutdown()
    print(f"\nTOPLAM {total} bar yazıldı | tf={args.timeframe} | gün={args.days} | kaynak={args.source_label}")
    if skipped:
        print(f"atlanan (terminalde yok): {skipped}")
    if failed:
        print(f"veri gelmeyen: {failed}")
    print("\nSonraki adım: replay artık ağa çıkmaz → "
          f"python scripts/forex_replay_backtest.py --days {args.days} --interval {args.timeframe} --chandelier 0.1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
