#!/usr/bin/env python3
"""MT5 → CSV ihracı (vectorbt taraması için) — 2026-11-10

Zaman damgaları **UTC**'ye çevrilir (MT5 sunucu saati UTC+2/3 → `symbol_info().time` ile
ölçülen ofset çıkarılır). Böylece vectorbt'te `freq` doğru verilir ve gün/seans gruplaması
kaymaz (bkz. çapraz-varlık turunda yaşanan ızgara uyuşmazlığı).

Çıktı: `outputs/vbt_data/<SEMBOL>_<TF>.csv` — kolonlar: ts_utc,open,high,low,close,volume
Kullanim:
    python scripts/vbt_export_mt5.py --tfs 1h,1d --years 5
    python scripts/vbt_export_mt5.py --tfs 5m,30m --years 0.5
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 yok — Python 3.12'yi tam yolla cagirin.")
    raise SystemExit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "outputs", "vbt_data")
TFS = {"5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15, "30m": mt5.TIMEFRAME_M30,
       "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1}
ALIAS = {"NAS100": "USTEC", "US100": "USTEC"}


def offset_h(sym: str) -> int:
    i = mt5.symbol_info(sym)
    return int(round((int(i.time) - time.time()) / 3600.0)) if i and i.time else 2


def export(sym: str, tf: str, years: float) -> int:
    broker = ALIAS.get(sym.upper(), sym.upper())
    if mt5.symbol_info(broker) is None:
        print(f"  {sym}: terminalde yok ({broker})")
        return 0
    off = offset_h(broker)
    rows: dict[int, tuple] = {}
    end = dt.datetime.now()
    days = int(years * 365.25)
    step = 30 if tf in ("5m", "15m", "30m") else 180
    i = 0
    while i < days:
        b_end = end - dt.timedelta(days=i)
        b_start = max(b_end - dt.timedelta(days=step), end - dt.timedelta(days=days))
        r = mt5.copy_rates_range(broker, TFS[tf], b_start, b_end)
        if r is not None and len(r):
            for x in r:
                rows[int(x["time"]) - off * 3600] = (float(x["open"]), float(x["high"]),
                                                     float(x["low"]), float(x["close"]),
                                                     float(x["tick_volume"]))
        i += step
    if not rows:
        print(f"  {sym}: veri yok")
        return 0
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{sym.upper()}_{tf}.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("ts_utc,open,high,low,close,volume\n")
        for ts in sorted(rows):
            o, h, l, c, v = rows[ts]
            f.write(f"{dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()},"
                    f"{o},{h},{l},{c},{v}\n")
    print(f"  {sym:<8} {len(rows):>7} bar → {os.path.relpath(path, ROOT)} (ofset {off}h)")
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="MT5 barlarını vectorbt için CSV'ye yaz")
    ap.add_argument("--symbols", default="EURUSD,GBPUSD,USDJPY,XAUUSD,US30,NAS100,BTCUSD")
    ap.add_argument("--tfs", default="1h,1d")
    ap.add_argument("--years", type=float, default=5.0)
    args = ap.parse_args()
    if not mt5.initialize():
        print(f"[HATA] MT5 initialize basarisiz: {mt5.last_error()}")
        return 2
    for tf in [t.strip() for t in args.tfs.split(",") if t.strip()]:
        if tf not in TFS:
            print(f"[ATLA] bilinmeyen tf: {tf}")
            continue
        print(f"TF={tf} ({args.years} yıl)")
        for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
            export(sym, tf, args.years)
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
