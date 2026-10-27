#!/usr/bin/env python3
"""MT5 GERCEK tick verisini uygulamanin PostgreSQL'ine yazar; sonra oradan okur.

Neden: replay/analiz bugune kadar dosya tabanli JSON onbelleklerle calisiyordu
(outputs/replay_cache_*.json) ve bu onbellekler Yahoo 5m mumlarindan uretiliyordu.
Uygulamanin veritabani ise zaten PostgreSQL (DB_BACKEND=postgres, scalper_global).
Istenen: veri MT5'ten alinip DB'ye yazilsin, analiz DB'den okusun.

Iki mod:
  ingest (varsayilan)  MT5 tick -> O/H/L/C barlar + GERCEK spread -> PostgreSQL
                          barlar  -> historical_candles          (upsert_market_candles)
                          spread  -> mt5_spread_profile         (upsert_mt5_spread_profiles)
  export               PostgreSQL -> replay harness'in bekledigi JSON bicimi
                          --out        bar onbellegi {SYM: [[ts,o,h,l,c], ...]}
                          --spread-out {"symbols": {SYM: {"avg_pips": N, "p95_pips": N}}}

Bar bicimi motorla birebir: [ts_utc_SANIYE, o, h, l, c] (orta fiyat = (bid+ask)/2).
DB'de open_time MILISANIYE'dir; export'ta saniyeye cevrilir.

Kullanim:
    PY312="C:\\Users\\erkan\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"

    # 1) MT5 -> Postgres (USTEC = NAS100'un MT5 adi; sembol adlari otomatik cevrilir)
    "$PY312" scripts/mt5_to_postgres.py ingest --days 90 --tf 15m \
        --symbols XAUUSD,BTCUSD,USTEC,US30,USDCHF

    # 2) Postgres -> replay JSON
    "$PY312" scripts/mt5_to_postgres.py export --tf 15m \
        --out outputs/replay_cache_db_15m.json --spread-out outputs/fx_spread_db_15m.json

NOT: `python` bir PyManager shim'i; shebang'i olan dosyalarda MetaTrader5 import
edilemez. Python 3.12'yi TAM YOLLA cagir.
"""
from __future__ import annotations

import argparse
import asyncio
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
sys.path.insert(0, os.path.join(ROOT, "backend"))

TF_SEC = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}
# MT5 broker adi -> uygulamanin kanonik adi (replay ve canli kod kanonik bekler)
MT5_TO_CANON = {"USTEC": "NAS100"}

_PIP_CACHE: dict = {}


def pip_size_of(symbol: str) -> float:
    """Broker sembolu -> canli pip_size (app.routers.forex.get_symbol_trading_specs).

    Sabit tablo YAZMA: XAUUSD canlida 0.1, BTCUSD/US30/NAS100 1.0 — elle yazilan
    0.01/0.1 degerleri spread'i 10x sisirir.
    """
    if not _PIP_CACHE:
        try:
            from app.routers import forex
            syms = (list(forex.FOREX_SYMBOLS) if isinstance(forex.FOREX_SYMBOLS, dict)
                    else [x.get("symbol") for x in forex.FOREX_SYMBOLS])
            for s in syms:
                try:
                    _PIP_CACHE[s] = float(forex.get_symbol_trading_specs(s)["pip_size"])
                except Exception:
                    pass
        except Exception as e:
            print(f"[UYARI] canli pip_size tablosu okunamadi ({e}) — guvenli varsayilan 0.0001")
    sym = MT5_TO_CANON.get(symbol.upper(), symbol.upper())
    return _PIP_CACHE.get(sym, 0.0001)


def server_offset_s() -> int:
    """Broker saat offset'i (sn); BTCUSD 24/7 aktigi icin canli referans."""
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
    """Tick'leri gun dilimleriyle AKISLI ceker; tick listesini bellekte tutmaz.

    Her dilim aninda barlara indirgenir (kova: O/H/L/C + tick sayaci) ve spread
    icin nokta-cinsinden Counter tutulur. 90 gun ~42M tick tek listede 2 GB+
    bellek yiyordu; bu yol barlar + Counter kadar yer kullanir.

    Dondurur: (bars: list[list], tick_count_per_bar: dict, spread_counter: Counter, n_tick: int)
    """
    from collections import Counter
    buckets: dict = {}   # kova_ts(sn) -> [o,h,l,c,adet]
    hist = Counter()     # round((ask-bid)/pip, 2) -> adet
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
                    buckets[key] = [mid, mid, mid, mid, 1]
                else:
                    if mid > b[1]:
                        b[1] = mid
                    if mid < b[2]:
                        b[2] = mid
                    b[3] = mid
                    b[4] += 1
                if ask > bid:
                    hist[round((ask - bid) / pip, 2)] += 1
            n_total += len(ticks)
        i += chunk_days
        if i % 10 == 0:
            print(f"    {symbol}: {i} gun islendi ({n_total:,} tick, {len(buckets):,} kova)")
        del ticks
    keys = sorted(buckets)
    bars = [[float(k), buckets[k][0], buckets[k][1], buckets[k][2], buckets[k][3]] for k in keys]
    counts = {k: buckets[k][4] for k in keys}
    return bars, counts, hist, n_total


def spread_from_hist(hist, pip: float) -> dict:
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
        "sample_count": total,
        "avg_pips": round(avg, 4),
        "p50_pips": round(p50 if p50 is not None else avg, 4),
        "p95_pips": round(p95 if p95 is not None else avg, 4),
        "pip_size": pip,
    }


# ---------------------------------------------------------------- ingest

def cmd_ingest(args) -> int:
    from app import database as db

    if not mt5.initialize():
        print("[HATA] MT5 initialize basarisiz:", mt5.last_error())
        return 1
    off = server_offset_s()
    print(f"[MT5] terminal hazir | sunucu offset = {off}s ({off/3600:.1f}h)")

    tf_sec = TF_SEC[args.tf]
    total_bars = total_spreads = 0
    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        mt5.symbol_select(sym, True)
        t0 = time.time()
        pip = pip_size_of(sym)
        bars, counts, hist, n_tick = fetch_stream(sym, args.days, off, pip, tf_sec)
        if not bars:
            print(f"  {sym:8s} TICK YOK (err={mt5.last_error()})")
            continue
        canon = MT5_TO_CANON.get(sym.upper(), sym.upper())

        # --- barlar -> historical_candles (open_time/close_time/fetched_at: ms)
        now_ms = int(time.time() * 1000)
        rows = []
        for b in bars:
            o_ms = int(b[0] * 1000)
            rows.append({
                "symbol": canon, "timeframe": args.tf,
                "open_time": o_ms, "close_time": o_ms + tf_sec * 1000 - 1,
                "open": b[1], "high": b[2], "low": b[3], "close": b[4],
                "volume": float(counts.get(int(b[0]), 0)),   # tick sayisi (vekil)
                "quote_volume": None, "trade_count": int(counts.get(int(b[0]), 0)),
                "source": "mt5_icmarkets_tick", "fetched_at": now_ms,
            })
        written = 0
        for i in range(0, len(rows), args.batch):
            written += asyncio.run(db.upsert_market_candles(rows[i:i + args.batch]))
        total_bars += written

        # --- spread -> mt5_spread_profile
        sp = spread_from_hist(hist, pip)
        if sp:
            sp.update({"symbol": canon, "timeframe": args.tf,
                       "measured_from": float(bars[0][0] * 1000),
                       "measured_to": float(bars[-1][0] * 1000),
                       "source": "mt5_icmarkets_tick"})
            total_spreads += asyncio.run(db.upsert_mt5_spread_profiles([sp]))

        f = dt.datetime.fromtimestamp(bars[0][0], dt.timezone.utc)
        g = dt.datetime.fromtimestamp(bars[-1][0], dt.timezone.utc)
        print(f"  {sym:8s} -> {canon:8s} {n_tick:>11,} tick -> {written:>6,} {args.tf} bar DB  | "
              f"{f:%m-%d %H:%M} -> {g:%m-%d %H:%M} | "
              f"spread avg={sp.get('avg_pips')}p p95={sp.get('p95_pips')}p | {time.time()-t0:.0f}s")
        del hist, counts

    mt5.shutdown()
    print(f"[OK] DB yazildi: {total_bars:,} bar (historical_candles) + "
          f"{total_spreads} spread profili (mt5_spread_profile)")
    return 0


# ---------------------------------------------------------------- ingest-rates (2026-10-28)

def fetch_rates_chunked(symbol: str, tf_name: str, start: dt.datetime, end: dt.datetime,
                        offset: int, chunk_days: int = 20) -> list:
    """copy_rates_range'i gun dilimleriyle ceker (terminal maxbars ~100k siniri).

    Dondurur: [[ts_utc_sn, o, h, l, c, tick_volume, spread_points], ...] (sirali, tekil).
    """
    tf_attr = {"1m": "TIMEFRAME_M1", "3m": "TIMEFRAME_M3", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15",
               "30m": "TIMEFRAME_M30", "1h": "TIMEFRAME_H1"}[tf_name]
    tf = getattr(mt5, tf_attr)
    seen: dict = {}
    cur = start
    while cur < end:
        nxt = min(cur + dt.timedelta(days=chunk_days), end)
        rates = mt5.copy_rates_range(symbol, tf, cur + dt.timedelta(seconds=offset), nxt + dt.timedelta(seconds=offset))
        if rates is not None:
            for r in rates:
                t = int(r["time"]) - offset
                seen[t] = [float(t), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                           float(r["tick_volume"]), float(r["spread"])]
        cur = nxt
    return [seen[k] for k in sorted(seen)]


def cmd_ingest_rates(args) -> int:
    """MT5 MUM (copy_rates) -> historical_candles; spread profili barin acilis spread'inden.

    Tick modu (ingest) 100 gun x 21 parite icin saatler surer; mum modu dakikalar.
    Spread: MT5 mum kaydindaki `spread` (nokta) alani -> pip; ortalama/p50/p95.
    """
    from app import database as db
    from collections import Counter

    if not mt5.initialize():
        print("[HATA] MT5 initialize basarisiz:", mt5.last_error())
        return 1
    off = server_offset_s()
    start = dt.datetime.strptime(args.start, "%Y-%m-%d")
    end = dt.datetime.strptime(args.end, "%Y-%m-%d")
    tf_sec = TF_SEC[args.tf]
    total_bars = total_spreads = 0
    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        mt5.symbol_select(sym, True)
        t0 = time.time()
        info = mt5.symbol_info(sym)
        point = float(getattr(info, "point", 0.0) or 0.0)
        pip = pip_size_of(sym)
        bars = fetch_rates_chunked(sym, args.tf, start, end, off)
        if not bars:
            print(f"  {sym:8s} MUM YOK (err={mt5.last_error()})")
            continue
        canon = MT5_TO_CANON.get(sym.upper(), sym.upper())
        now_ms = int(time.time() * 1000)
        rows = []
        hist = Counter()
        for b in bars:
            o_ms = int(b[0] * 1000)
            rows.append({
                "symbol": canon, "timeframe": args.tf,
                "open_time": o_ms, "close_time": o_ms + tf_sec * 1000 - 1,
                "open": b[1], "high": b[2], "low": b[3], "close": b[4],
                "volume": b[5], "quote_volume": None, "trade_count": int(b[5]),
                "source": "mt5_icmarkets_rates", "fetched_at": now_ms,
            })
            if point > 0 and pip > 0 and b[6] > 0:
                hist[round(b[6] * point / pip, 2)] += 1
        written = 0
        for i in range(0, len(rows), args.batch):
            written += asyncio.run(db.upsert_market_candles(rows[i:i + args.batch]))
        total_bars += written
        sp = spread_from_hist(hist, pip)
        if sp:
            sp.update({"symbol": canon, "timeframe": args.tf,
                       "measured_from": float(bars[0][0] * 1000), "measured_to": float(bars[-1][0] * 1000),
                       "source": "mt5_icmarkets_rates"})
            total_spreads += asyncio.run(db.upsert_mt5_spread_profiles([sp]))
        f = dt.datetime.fromtimestamp(bars[0][0], dt.timezone.utc)
        g = dt.datetime.fromtimestamp(bars[-1][0], dt.timezone.utc)
        print(f"  {sym:8s} -> {canon:8s} {written:>7,} {args.tf} bar DB | {f:%m-%d %H:%M} -> {g:%m-%d %H:%M} | "
              f"spread avg={sp.get('avg_pips')}p p95={sp.get('p95_pips')}p | {time.time()-t0:.0f}s", flush=True)
    mt5.shutdown()
    print(f"[OK] DB yazildi: {total_bars:,} bar (historical_candles, mt5_icmarkets_rates) + {total_spreads} spread profili")
    return 0


# ---------------------------------------------------------------- export

def cmd_export(args) -> int:
    from app import database as db

    syms = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
            if args.symbols else asyncio.run(db.get_market_symbols(args.tf)))
    if not syms:
        print(f"[HATA] DB'de {args.tf} icin bar yok — once `ingest` kosun.")
        return 1

    data = {}
    for sym in syms:
        rows = asyncio.run(db.get_market_candles(sym, args.tf, args.start_ms, args.end_ms))
        if not rows:
            print(f"  {sym:8s} DB'de yok — atlandi")
            continue
        data[sym] = [[r["open_time"] / 1000.0, r["open"], r["high"], r["low"], r["close"]]
                     for r in rows]
        print(f"  {sym:8s} {len(rows):>6,} bar okundu")

    out_path = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    print(f"[OK] {len(data)} sembol -> {out_path} ({sum(len(v) for v in data.values()):,} bar)")

    if args.spread_out:
        prof = asyncio.run(db.get_mt5_spread_profiles(args.tf))
        if not prof:
            # Spread tick-duzeyi bir olcumdur (bara bagli degil); profil baska bir
            # TF altinda olculmus olabilir — hepsini al, sembol basina tekrari at.
            prof = asyncio.run(db.get_mt5_spread_profiles())
        fresh = {k: {"avg_pips": v["avg_pips"], "p50_pips": v["p50_pips"],
                     "p95_pips": v["p95_pips"], "pip_size": v["pip_size"],
                     "n": v["sample_count"]} for k, v in prof.items()}
        sp_path = args.spread_out if os.path.isabs(args.spread_out) else os.path.join(ROOT, args.spread_out)
        os.makedirs(os.path.dirname(sp_path), exist_ok=True)
        with open(sp_path, "w", encoding="utf-8") as fh:
            json.dump({"symbols": fresh}, fh, ensure_ascii=False, indent=1)
        print(f"[OK] {len(fresh)} spread profili -> {sp_path}")
    return 0


def cmd_derive(args) -> int:
    """DB'deki 5m barlari Nx zaman dilimine indirger ve DB'ye geri yazar.

    Harness `--interval` ile --cache birlikte KULLANILINCA yeniden ornekleme
    YAPMAZ (sessizce 5m kosar). Bu yuzden M15/M30/H1 gercek barlari onceden
    turetilmeli. Burada kaynak DB'nin kendisi (5m), hedef de DB.
    """
    from app import database as db
    sec = TF_SEC[args.tf]
    if sec <= 300:
        print(f"[HATA] --tf {args.tf} 5m'den turetilemez (en az 15m).")
        return 2
    syms = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
            if args.symbols else asyncio.run(db.get_market_symbols(args.src_tf)))
    total = 0
    for sym in syms:
        rows = asyncio.run(db.get_market_candles(sym, args.src_tf))
        if not rows:
            print(f"  {sym:8s} {args.src_tf} DB'de yok — atlandi")
            continue
        out, cur, o, h, l, c, vol = [], None, 0.0, 0.0, 0.0, 0.0, 0.0
        for r in rows:
            key = int(r["open_time"] // (sec * 1000)) * (sec * 1000)
            if key != cur:
                if cur is not None:
                    out.append((cur, o, h, l, c, vol))
                cur, o, h, l, c = key, r["open"], r["high"], r["low"], r["close"]
                vol = float(r.get("volume") or 0)
            else:
                h = max(h, r["high"]); l = min(l, r["low"]); c = r["close"]
                vol += float(r.get("volume") or 0)
        if cur is not None:
            out.append((cur, o, h, l, c, vol))
        now_ms = int(time.time() * 1000)
        payload = [{"symbol": sym, "timeframe": args.tf, "open_time": k,
                    "close_time": k + sec * 1000 - 1, "open": o, "high": h, "low": l,
                    "close": c, "volume": vol, "quote_volume": None,
                    "trade_count": None, "source": f"mt5_icmarkets_tick_{args.src_tf}_downsampled",
                    "fetched_at": now_ms} for (k, o, h, l, c, vol) in out]
        w = 0
        for i in range(0, len(payload), args.batch):
            w += asyncio.run(db.upsert_market_candles(payload[i:i + args.batch]))
        total += w
        print(f"  {sym:8s} {len(rows):>6,} {args.src_tf} -> {w:>6,} {args.tf} bar DB")
    print(f"[OK] turetildi: {total:,} bar ({args.tf})")
    return 0


def main():
    ap = argparse.ArgumentParser(description="MT5 tick -> PostgreSQL -> replay JSON")
    sub = ap.add_subparsers(dest="cmd")

    p_in = sub.add_parser("ingest", help="MT5 tick'lerini DB'ye yaz")
    p_in.add_argument("--days", type=int, default=90)
    p_in.add_argument("--tf", default="5m", choices=sorted(TF_SEC))
    p_in.add_argument("--symbols", required=True,
                      help="Virgulle ayrilmis MT5 adlari (NAS100 icin USTEC)")
    p_in.add_argument("--batch", type=int, default=2000, help="Upsert parti boyutu")
    p_in.set_defaults(func=cmd_ingest)

    p_ir = sub.add_parser("ingest-rates", help="MT5 MUMLARINI (copy_rates) DB'ye yaz — tick moduna gore dakikalar")
    p_ir.add_argument("--start", required=True, help="UTC baslangic YYYY-MM-DD")
    p_ir.add_argument("--end", required=True, help="UTC bitis YYYY-MM-DD (dahil degil)")
    p_ir.add_argument("--tf", default="5m", choices=["1m", "3m", "5m", "15m", "30m", "1h"])
    p_ir.add_argument("--symbols", required=True, help="Virgulle ayrilmis MT5 adlari")
    p_ir.add_argument("--batch", type=int, default=5000)
    p_ir.set_defaults(func=cmd_ingest_rates)

    p_dv = sub.add_parser("derive", help="DB'deki 5m barlardan M15/M30/H1 turet")
    p_dv.add_argument("--tf", default="15m", choices=sorted(TF_SEC))
    p_dv.add_argument("--src-tf", default="5m", choices=sorted(TF_SEC))
    p_dv.add_argument("--symbols", default="", help="Bos ise DB'deki tum semboller")
    p_dv.add_argument("--batch", type=int, default=2000)
    p_dv.set_defaults(func=cmd_derive)

    p_ex = sub.add_parser("export", help="DB'den replay JSON'u uret")
    p_ex.add_argument("--tf", default="5m", choices=sorted(TF_SEC))
    p_ex.add_argument("--symbols", default="", help="Bos ise DB'deki tum semboller")
    p_ex.add_argument("--start-ms", type=int, default=None)
    p_ex.add_argument("--end-ms", type=int, default=None)
    p_ex.add_argument("--out", required=True)
    p_ex.add_argument("--spread-out", default="")
    p_ex.set_defaults(func=cmd_export)

    args = ap.parse_args()
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
