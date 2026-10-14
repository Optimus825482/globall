#!/usr/bin/env python3
"""MT5 GERCEK tick verisinden replay onbellegi + gercek spread profili uretir.

Neden: replay harness bugune kadar Yahoo 5m mumlarini kullaniyordu; spread ise
MT5 tick'inden alinan tek seferlik "p95" profiliydi. Ikisi de vekil veriydi.
Koprunun baglandigi MT5 terminali gercek bid/ask tick akisini veriyor
(XAUUSD ~14.7M tick/30g) — barlar da spread de oradan turetilmeli.

Bu script:
  1) Her sembolun tick'lerini GUNLUK dilimler halinde ceker (tek buyuk istek
     "Terminal: Call failed" veriyor; dilimleme hem guvenli hem bellek-dostu).
  2) Tick'ten N dakikalik barlari kurar: O/H/L/C = orta fiyat (bid+ask)/2.
     Bar bicimi motorla birebir: [ts_utc, o, h, l, c].
  3) GERCEK spread profilini olcer: (ask-bid)/pip_size, ortalama ve p95.

Kullanim:
    "C:\\...\\Python312\\python.exe" scripts/fx_build_tick_cache.py \
        --days 30 --tf 5m --symbols XAUUSD,GBPUSD \
        --out outputs/replay_cache_tick_5m.json \
        --spread-out outputs/fx_spread_tick.json

NOT: `python` bir PyManager shim'i; shebang'i olan dosyalarda MT5 import edilemez.
Bu yuzden Python 3.12'yi TAM YOLLA cagir.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 yok — Python 3.12'yi tam yolla cagirin.")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TF_SEC = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}

# pip_size CANLI koddan okunur (app.routers.forex.get_symbol_trading_specs).
# Sabit tablo yazmak tuzak: XAUUSD canlida 0.1, BTCUSD/US30/NAS100 1.0 —
# elle yazilan 0.01/0.1 degerleri spread'i 10x sisiriyordu.
_PIP_CACHE: dict = {}


def pip_size_of(symbol: str) -> float:
    """Broker sembolu -> canli pip_size. MT5 adi (USTEC) canli adina cevrilir."""
    if not _PIP_CACHE:
        try:
            sys.path.insert(0, os.path.join(ROOT, "backend"))
            from app.routers import forex
            for s in (list(forex.FOREX_SYMBOLS) if isinstance(forex.FOREX_SYMBOLS, dict)
                      else [x.get("symbol") for x in forex.FOREX_SYMBOLS]):
                try:
                    _PIP_CACHE[s] = float(forex.get_symbol_trading_specs(s)["pip_size"])
                except Exception:
                    pass
        except Exception as e:
            print(f"[UYARI] canli pip_size tablosu okunamadi ({e}) — guvenli varsayilan 0.0001")
    sym = {"USTEC": "NAS100"}.get(symbol.upper(), symbol.upper())
    return _PIP_CACHE.get(sym, 0.0001)


def server_offset_s() -> int:
    """Broker saat offset'i (sn). BTCUSD 24/7 aktigi icin canli referans."""
    now = int(time.time())
    best_off, best_gap = 0, 10 ** 9
    for probe in ("BTCUSD", "XAUUSD", "EURUSD", "GBPUSD"):
        ti = mt5.symbol_info_tick(probe)
        if ti and ti.time:
            gap = abs(ti.time - now)
            if gap < best_gap:
                best_gap, best_off = gap, ti.time - now
    return int(round(best_off / 1800.0) * 1800)


def fetch_stream(symbol: str, days: int, offset: int, pip: float, tf_sec: int,
                 chunk_days: int = 2) -> tuple:
    """Tick'leri gun dilimleriyle AKISLI ceker; tick'leri bellekte tutmaz.

    Her dilim aninda barlara indirgenir (kova sozlugu: O/H/L/C guncellenir) ve
    spread icin nokta-cinsinden Counter tutulur. 90 gun ~42M tick tek listede
    2 GB+ bellek yiyordu; bu yol barlar + Counter kadar yer kullanir.

    Dondurur: (bars: list, spread_counter: Counter, tick_sayisi: int)
    """
    from collections import Counter
    buckets: dict = {}      # kova_ts -> [o,h,l,c]
    hist = Counter()        # round((ask-bid)/pip, 2) -> adet
    n_total = 0
    end = dt.datetime.now()
    i = 0
    while i < days:
        b_end = end - dt.timedelta(days=i)
        b_start = max(b_end - dt.timedelta(days=chunk_days),
                      end - dt.timedelta(days=days))
        ticks = mt5.copy_ticks_range(symbol, b_start, b_end, mt5.COPY_TICKS_ALL)
        if ticks is not None and len(ticks):
            for t in ticks:
                bid, ask = float(t["bid"]), float(t["ask"])
                if bid <= 0 or ask <= 0:
                    last = float(t["last"]) if t["last"] > 0 else (bid or ask)
                    bid = ask = last
                    if bid <= 0:
                        continue
                mid = (bid + ask) / 2.0
                key = int((int(t["time"]) - offset) // tf_sec) * tf_sec
                b = buckets.get(key)
                if b is None:
                    buckets[key] = [mid, mid, mid, mid]
                else:
                    if mid > b[1]:
                        b[1] = mid
                    if mid < b[2]:
                        b[2] = mid
                    b[3] = mid
                if ask > bid:
                    hist[round((ask - bid) / pip, 2)] += 1
            n_total += len(ticks)
        i += chunk_days
        if i % 10 == 0:
            print(f"    {symbol}: {i} gun islendi ({n_total:,} tick, {len(buckets):,} kova)")
        del ticks
    bars = [[float(k), v[0], v[1], v[2], v[3]] for k, v in sorted(buckets.items())]
    return bars, hist, n_total


def spread_from_hist(hist, pip: float, n_total: int) -> dict:
    """Nokta-cinsinden sayactan GERCEK spread yuzdelikleri."""
    total = sum(hist.values())
    if not total:
        return {}
    acc, p50, p95 = 0, None, None
    for val in sorted(hist):
        acc += hist[val]
        if p50 is None and acc >= total * 0.50:
            p50 = val
        if p95 is None and acc >= total * 0.95:
            p95 = val
            break
    avg = sum(v * c for v, c in hist.items()) / total
    return {
        "n": total,
        "avg_pips": round(avg, 4),
        "p50_pips": round(p50 if p50 is not None else avg, 4),
        "p95_pips": round(p95 if p95 is not None else avg, 4),
        "pip_size": pip,
        "note": "MT5 GERCEK tick (ask-bid) olcumu, akan sayac",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--tf", default="5m", choices=sorted(TF_SEC))
    ap.add_argument("--symbols", required=True, help="Virgulle ayrilmis; NAS100 icin MT5 adi USTEC")
    ap.add_argument("--out", required=True, help="Bar onbellegi JSON")
    ap.add_argument("--spread-out", default="", help="Gercek spread profili JSON")
    args = ap.parse_args()

    if not mt5.initialize():
        print("[HATA] MT5 initialize basarisiz:", mt5.last_error())
        sys.exit(1)
    off = server_offset_s()
    print(f"[MT5] terminal hazir | sunucu offset = {off}s ({off/3600:.1f}h)")

    tf_sec = TF_SEC[args.tf]
    data, spreads = {}, {}
    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        mt5.symbol_select(sym, True)
        t0 = time.time()
        pip = pip_size_of(sym)
        bars, hist, n_tick = fetch_stream(sym, args.days, off, pip, tf_sec)
        if not bars:
            print(f"  {sym:8s} TICK YOK (err={mt5.last_error()})")
            data[sym] = []
            continue
        # MT5 adi -> canli ad (USTEC NAS100'un MT5 adidir; replay NAS100 bekler)
        key = {"USTEC": "NAS100"}.get(sym.upper(), sym.upper())
        data[key] = bars
        sp = spread_from_hist(hist, pip, n_tick)
        if sp:
            spreads[key] = sp
        f = dt.datetime.fromtimestamp(bars[0][0], dt.timezone.utc)
        g = dt.datetime.fromtimestamp(bars[-1][0], dt.timezone.utc)
        sp_txt = f"spread avg={sp.get('avg_pips')}p p95={sp.get('p95_pips')}p" if sp else "spread ?"
        print(f"  {sym:8s} {n_tick:>11,} tick -> {len(bars):>6,} {args.tf} bar | "
              f"{f:%m-%d %H:%M} -> {g:%m-%d %H:%M} | {sp_txt} | {time.time()-t0:.0f}s")
        del hist
    mt5.shutdown()

    out_path = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    print(f"[OK] barlar -> {out_path} ({sum(len(v) for v in data.values()):,} bar, {len(data)} sembol)")

    if args.spread_out:
        sp_path = args.spread_out if os.path.isabs(args.spread_out) else os.path.join(ROOT, args.spread_out)
        os.makedirs(os.path.dirname(sp_path), exist_ok=True)
        with open(sp_path, "w", encoding="utf-8") as fh:
            json.dump({"symbols": spreads}, fh, ensure_ascii=False, indent=1)
        print(f"[OK] spread profili -> {sp_path} ({len(spreads)} sembol)")


if __name__ == "__main__":
    main()
