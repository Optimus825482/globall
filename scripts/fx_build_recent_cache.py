#!/usr/bin/env python3
"""MT5'ten son N günün 5m/15m mumlarını çekip replay önbelleği üretir.

Bar formatı motorla birebir: [ts_utc, open, high, low, close].
MT5 sunucu saati broker offset'i kadar ileride olabilir; tick'ten UTC'ye indirilir.

Kullanım:
    python scripts/fx_build_recent_cache.py --days 3 --symbols XAUUSD,BTCUSD \
        --out outputs/scalp_cache_3d.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 yok")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TF = {"5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15, "1m": mt5.TIMEFRAME_M1,
      "1h": mt5.TIMEFRAME_H1}


def server_offset_s() -> int:
    """MT5 sunucu saati ile UTC farkı (sn, 30dk'ya yuvarla).

    En taze tick'i olan enstrümanı seç: hafta sonu XAUUSD/EURUSD tick'i donar
    (kapanış), o yüzden sabit probe sırası yanıltıcı offset veriyordu. BTCUSD
    24/7 aktığı için canlı referanstır.
    """
    now = int(time.time())
    best_off, best_gap = 0, 10**9
    for probe in ("BTCUSD", "XAUUSD", "EURUSD", "GBPUSD"):
        ti = mt5.symbol_info_tick(probe)
        if ti and ti.time:
            gap = abs(ti.time - now)
            if gap < best_gap:
                best_gap = gap
                best_off = ti.time - now
    return int(round(best_off / 1800.0) * 1800)


def fetch(symbol: str, tf: str, days: int, offset: int) -> list[list]:
    """Zaman-aralığı bazlı çekim (copy_rates_from_pos 50k bar sonrası sarıyor).

    Broker saat offset'i uygulanır; sonuç UTC zaman damgalı.
    """
    import datetime as _dt
    end_broker = _dt.datetime.now() + _dt.timedelta(seconds=offset)
    start_broker = end_broker - _dt.timedelta(days=days)
    rates = mt5.copy_rates_range(symbol, TF[tf], start_broker, end_broker)
    if rates is None or len(rates) == 0:
        return []
    out = [[float(int(r["time"]) - offset), float(r["open"]),
            float(r["high"]), float(r["low"]), float(r["close"])] for r in rates]
    out.sort(key=lambda b: b[0])
    step = {"5m": 300, "15m": 900, "1m": 60, "1h": 3600}[tf]
    if out and out[-1][0] + step > time.time():
        out = out[:-1]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--symbols", default="XAUUSD,BTCUSD")
    ap.add_argument("--out", default="outputs/scalp_cache_3d.json")
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--start", default="", help="YYYY-MM-DD (UTC) — dahil; verilirse --days yerine pencere filtresi")
    ap.add_argument("--end", default="", help="YYYY-MM-DD (UTC) — dahil (gün sonu)")
    args = ap.parse_args()

    if not mt5.initialize():
        print("[HATA] MT5 initialize başarısız:", mt5.last_error())
        sys.exit(1)
    for s in args.symbols.split(","):
        mt5.symbol_select(s.strip(), True)
    off = server_offset_s()
    print(f"[MT5] sunucu offset = {off}s ({off/3600:.1f}h)")
    # tarih penceresi verildiyse gün farkına çevir (broker offset'i zaten uygulanıyor)
    import datetime as dt
    days = args.days
    t0 = t1 = None
    if args.start:
        t0 = dt.datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()
    if args.end:
        t1 = (dt.datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
              + dt.timedelta(days=1)).timestamp()  # gün sonu (dahil)
    if t0 is not None:
        span = ((t1 or time.time()) - t0) / 86400.0
        days = int(span) + 2   # geriye pay bırak (geri çekim penceresi)
        print(f"[MT5] pencere {args.start} → {args.end or 'now'} (~{span:.1f} gün), çekim {days} gün")
    data = {}
    for s in args.symbols.split(","):
        s = s.strip()
        bars = fetch(s, args.tf, days, off)
        if t0 is not None:
            bars = [b for b in bars if t0 <= b[0] <= (t1 if t1 is not None else 9e18)]
        data[s] = bars
        if bars:
            print(f"  {s}: {len(bars)} bar  "
                  f"{dt.datetime.utcfromtimestamp(bars[0][0]):%Y-%m-%d %H:%M} → "
                  f"{dt.datetime.utcfromtimestamp(bars[-1][0]):%Y-%m-%d %H:%M} UTC")
        else:
            print(f"  {s}: BAR YOK")
    mt5.shutdown()
    os.makedirs(os.path.dirname(os.path.join(ROOT, args.out)), exist_ok=True)
    with open(os.path.join(ROOT, args.out), "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    print(f"[OK] → {args.out}")


if __name__ == "__main__":
    main()
