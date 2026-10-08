#!/usr/bin/env python3
"""MT5'ten GECMIS pencere icin replay onbellegi uret (Yahoo 60-gun sinirini asar).

Neden: Yahoo Finance 5m/15m verisi yalnizca ~60 gun geriye gider (Temmuz 1-15
artik yok). Kullanici o pencereyi istiyor. MetaTrader 5 terminalinin broker
gecmisi cok daha uzun tutulur; `copy_rates_range` ile cekilir.

Onemli: MT5 mum zamanlari BROKER sunucu saatindedir (IC Markets = UTC+3).
Yahoo onbellegi UTC oldugu icin ayni sekilde UTC'ye indirilir (offset tick'ten
turetilir, mt5_bridge.py ile ayni mantik).

Bar bicimi motorla birebir: [ts_utc, open, high, low, close] (5 eleman).

Kullanim:
    python -m scripts.fx_build_mt5_cache --start 2026-06-15 --end 2026-07-16 \
        --symbols XAUUSD,BTCUSD,USDJPY --dst outputs/replay_cache_jul_mt5.json
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import os
import sys

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 yok. 'pip install MetaTrader5'")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUCKET_M15 = 900


def server_utc_offset_s() -> int:
    """MT5 sunucu saati ↔ UTC farki (sn, 30 dk'ya yuvarlanmis). mt5_bridge ile ayni."""
    import time
    for probe in ("EURUSD", "XAUUSD", "GBPUSD"):
        t = mt5.symbol_info_tick(probe)
        if t and t.time:
            server_now = int(t.time)
            utc_now = calendar.timegm(time.gmtime())
            if abs(server_now - utc_now) > 36 * 3600:
                continue
            return int(round((server_now - utc_now) / 1800.0) * 1800)
    return 0


def fetch_m5(sym: str, start: dt.datetime, end: dt.datetime, offset: int):
    info = mt5.symbol_info(sym)
    if info is None:
        return None
    if not info.visible:
        mt5.symbol_select(sym, True)
    rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M5, start, end)
    if rates is None or len(rates) == 0:
        return None
    bars = []
    for r in rates:
        t_utc = int(r["time"]) - offset
        bars.append([float(t_utc), float(r["open"]), float(r["high"]),
                     float(r["low"]), float(r["close"])])
    bars.sort(key=lambda b: b[0])
    return bars


def to_m15(bars):
    out = []
    cur_key = None
    o = h = l = c = 0.0
    for b in bars:
        key = int(b[0] // BUCKET_M15) * BUCKET_M15
        if key != cur_key:
            if cur_key is not None:
                out.append([float(cur_key), o, h, l, c])
            cur_key = key
            o, h, l, c = b[1], b[2], b[3], b[4]
        h = max(h, b[2])
        l = min(l, b[3])
        c = b[4]
    if cur_key is not None:
        out.append([float(cur_key), o, h, l, c])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="UTC baslangic (YYYY-MM-DD)")
    ap.add_argument("--end", required=True, help="UTC bitis, dahil degil (YYYY-MM-DD)")
    ap.add_argument("--symbols", required=True, help="Virgullu MT5 sembolleri (XAUUSD,BTCUSD,...)")
    ap.add_argument("--dst", required=True, help="Cikis 5m onbellek yolu")
    ap.add_argument("--dst-m15", default="", help="Cikis 15m onbellek yolu (bos = uretilmez)")
    args = ap.parse_args()

    if not mt5.initialize():
        print(f"[HATA] MT5 init: {mt5.last_error()}")
        sys.exit(1)
    try:
        offset = server_utc_offset_s()
        print(f"[MT5] sunucu↔UTC offset = {offset}s ({offset/3600:.1f}h)")
        start = dt.datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        end = dt.datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        # Broker zaman ekseninde iste: UTC [start,end) -> broker [start+off, end+off)
        b_start = start + dt.timedelta(seconds=offset)
        b_end = end + dt.timedelta(seconds=offset)

        data5 = {}
        for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
            bars = fetch_m5(sym, b_start, b_end, offset)
            if not bars:
                print(f"  {sym:8s} VERI YOK (atlanıyor)")
                continue
            data5[sym] = bars
            f = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
            print(f"  {sym:8s} {len(bars):>6} M5  {f(bars[0][0])} -> {f(bars[-1][0])}")

        os.makedirs(os.path.dirname(os.path.abspath(args.dst)), exist_ok=True)
        with open(args.dst, "w", encoding="utf-8") as fh:
            json.dump(data5, fh)
        print(f"[OK] {len(data5)} sembol (5m) -> {args.dst}")

        if args.dst_m15:
            data15 = {s: to_m15(b) for s, b in data5.items()}
            with open(args.dst_m15, "w", encoding="utf-8") as fh:
                json.dump(data15, fh)
            print(f"[OK] {len(data15)} sembol (15m) -> {args.dst_m15}")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
