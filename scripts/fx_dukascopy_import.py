#!/usr/bin/env python3
"""DUKASCOPY TICK → M1 BAR + GERÇEK SPREAD (2026-11-12)

NEDEN
-----
İki belgelenmiş ölçüm açığı vardı:
  1) MT5 `maxbars=100000` → **M1 sadece ~3 ay**. 5m/15m stratejilerinin (squeeze,
     RVOL) OOS örneklemi bu yüzden zayıf.
  2) `docs/FX_YENI_SINYAL_AILESI_TUR2_2026-11-10.md` §4: "p50 spread ölçümü
     roll/witching/tatil günlerinde YANLIŞ POZİTİF üretir (gerçek spread 2-5×)".
     `fx_build_tick_cache.py` gerçek spread'i ölçüyor ama yalnız terminalde duran
     ~30 günlük tick'ten. Bu yüzden replay'e giren maliyet modeli kısa ve tek
     rejimli bir pencereden geliyordu.

Bu betik Dukascopy'nin **anahtarsız, ücretsiz** datafeed'inden saatlik tick
dosyalarını indirir (`.../{SYM}/{YYYY}/{MM0}/{DD}/{HH}h_ticks.bi5`, LZMA, 20 baytlık
big-endian kayıtlar: ms_offset, ask, bid, ask_vol, bid_vol) ve:

  * M1 barları kurar — O/H/L/C = ORTA fiyat (bid+ask)/2, `historical_candles`'a
    `source='dukascopy_bid'` ile yazar. **FILL-ONLY**: dolu satır EZİLMEZ
    (broker/MT5 verisi her zaman öncelikli) → mevcut seriyi bozmaz, yalnız
    ~3 aylık sınırın GERİSİNİ doldurur.
  * HER DAKİKA için gerçek spread dağılımını `fx_spread_history` tablosuna yazar
    (ortalama / medyan / p90 / maks, PİP cinsinden) → maliyet modeli artık
    varsayım değil ölçüm.

Doğrulanmış erişim (2026-11-12): EURUSD 2026-11-11 10:00 UTC → HTTP 200, 17 KB.
CDN ara sıra 503 döner; bu yüzden yeniden deneme + gecikme var. 0 bayt = piyasa
kapalı (hafta sonu/tatil) → atlanır, hata değil.

Kullanim:
    python scripts/fx_dukascopy_import.py --symbols EURUSD --days 5
    python scripts/fx_dukascopy_import.py --symbols EURUSD,GBPUSD,USDJPY,XAUUSD --start 2025-01-01 --end 2026-11-01
    python scripts/fx_dukascopy_import.py --symbols EURUSD --days 30 --dry-run   # DB'ye yazmaz
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import lzma
import os
import struct
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE = "https://datafeed.dukascopy.com/datafeed"
HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Referer": "https://www.dukascopy.com/",
}
REC = struct.Struct(">IIIff")  # ms_offset, ask, bid, ask_vol, bid_vol

#: Fiyat ölçeği (Dukascopy uint32 fiyat = fiyat * scale). Sembol adından
#: türetilemeyenler için makul bant tablosuyla OTOMATİK tespit edilir.
FAMILY_BAND = {
    "fx": (0.30, 3.00),
    "jpy": (60.0, 400.0),
    "xau": (500.0, 8000.0),
    "xag": (5.0, 120.0),
    "index": (500.0, 300000.0),
}
SCALES = (1e0, 1e1, 1e2, 1e3, 1e4, 1e5)


def family_of(symbol: str) -> str:
    s = symbol.upper()
    if s.startswith(("XAU", "GOLD")):
        return "xau"
    if s.startswith(("XAG", "SILVER")):
        return "xag"
    if "JPY" in s:
        return "jpy"
    if len(s) == 6 and s.isalpha():
        return "fx"
    return "index"


def detect_scale(symbol: str, raw_med: float) -> tuple[float, float]:
    """(scale, pip_size) — ham uint32 medyanından ölçek çıkarır.

    Ölçek sabit tablodan YAZILMAZ: yanlış ölçek fiyatı 10× kaydırır ve spread'i
    sessizce şişirir (`fx_build_tick_cache.py`'deki pip dersi). Bu yüzden aile
    bandına düşen ölçek aranır; birden fazla aday varsa en küçüğü seçilir.
    """
    band = FAMILY_BAND[family_of(symbol)]
    for sc in SCALES:
        price = raw_med / sc
        if band[0] <= price <= band[1]:
            # 5 haneli FX'te pip = 1e-4 (scale 1e5); JPY/XAU 1e3 → 0.01/0.1;
            # endeks 1e1 → 1.0. Hepsi 10/scale kuralına oturuyor.
            return sc, 10.0 / sc
    raise ValueError(f"{symbol}: fiyat ölçeği tespit edilemedi (ham medyan {raw_med:.0f})")


def _get(url: str, tries: int = 4) -> bytes | None:
    """Baytları indirir. 404/0 bayt = veri yok (None). 503 = yeniden dene."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = f"HTTP{e.code}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}"
        time.sleep(0.8 * (i + 1))
    if last:
        _STATS["fail"] += 1
    return None


_STATS = {"fail": 0, "hours": 0, "empty": 0}
_LOCK = threading.Lock()


def tick_hour(symbol: str, hour_start: dt.datetime) -> list[tuple[int, float, float, float, float]] | None:
    """Bir saatlik tick listesi: (ms_epoch, bid, ask, bid_vol, ask_vol). Ham uint."""
    url = (f"{BASE}/{symbol}/{hour_start:%Y}/{hour_start.month - 1:02d}/{hour_start:%d}/"
           f"{hour_start:%H}h_ticks.bi5")
    raw = _get(url)
    with _LOCK:
        _STATS["hours"] += 1
    if not raw:
        with _LOCK:
            _STATS["empty"] += 1
        return None
    try:
        data = lzma.decompress(raw)
    except lzma.LZMAError:
        return None
    base_ms = int(hour_start.timestamp() * 1000)
    out = []
    for off in range(0, len(data) - REC.size + 1, REC.size):
        ms, ask, bid, av, bv = REC.unpack_from(data, off)
        out.append((base_ms + ms, float(bid), float(ask), float(bv), float(av)))
    return out or None


def hours_between(start: dt.datetime, end: dt.datetime) -> list[dt.datetime]:
    out, cur = [], start
    while cur < end:
        out.append(cur)
        cur += dt.timedelta(hours=1)
    return out


def build(symbol: str, ticks: list[tuple[int, float, float, float, float]],
          scale: float, pip: float) -> dict[int, dict]:
    """Tick → {minute_ms: M1 özet}. Fiyatlar ölçeklenmiş (gerçek fiyat)."""
    bars: dict[int, dict] = {}
    for ms, bid_r, ask_r, bv, av in ticks:
        if ask_r <= 0 or bid_r <= 0:
            continue
        bid, ask = bid_r / scale, ask_r / scale
        if ask < bid:  # bozuk kayıt (ters kotasyon) — sessizce atla
            continue
        mid = (bid + ask) / 2.0
        m = (ms // 60_000) * 60_000
        sp = (ask - bid) / pip
        b = bars.get(m)
        if b is None:
            bars[m] = {"o": mid, "h": mid, "l": mid, "c": mid, "ticks": 1,
                       "sp_sum": sp, "sp_max": sp, "sp": [sp], "vol": bv + av}
        else:
            b["c"] = mid
            if mid > b["h"]:
                b["h"] = mid
            if mid < b["l"]:
                b["l"] = mid
            b["ticks"] += 1
            b["sp_sum"] += sp
            if sp > b["sp_max"]:
                b["sp_max"] = sp
            b["sp"].append(sp)
            b["vol"] += bv + av
    return bars


def spread_stats(b: dict) -> tuple[float, float, float, float]:
    sp = sorted(b["sp"])
    n = len(sp)
    p50 = sp[n // 2]
    p90 = sp[min(n - 1, int(n * 0.9))]
    return b["sp_sum"] / n, p50, p90, b["sp_max"]


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


DDL_SPREAD = """
CREATE TABLE IF NOT EXISTS fx_spread_history (
  symbol TEXT NOT NULL,
  open_time BIGINT NOT NULL,
  spread_avg DOUBLE PRECISION NOT NULL,
  spread_p50 DOUBLE PRECISION NOT NULL,
  spread_p90 DOUBLE PRECISION NOT NULL,
  spread_max DOUBLE PRECISION NOT NULL,
  ticks INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'dukascopy_tick',
  fetched_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (symbol, open_time)
)
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Dukascopy tick → M1 bar + gerçek spread")
    ap.add_argument("--symbols", required=True, help="virgüllü (EURUSD,GBPUSD,USDJPY,XAUUSD)")
    ap.add_argument("--days", type=int, default=5, help="bitişten geriye gün (--start ile yok sayılır)")
    ap.add_argument("--start", default="", help="YYYY-MM-DD (dahil, UTC)")
    ap.add_argument("--end", default="", help="YYYY-MM-DD (hariç, UTC; boş = bugün)")
    ap.add_argument("--duka-symbol", default="", help="eşleme: APP:DUKA,APP2:DUKA2 (JP225:JPNIDXJPY)")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true", help="DB'ye yazma, özet bas")
    args = ap.parse_args()

    today = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if args.start:
        start = dt.datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    else:
        start = today - dt.timedelta(days=args.days)
    end = (dt.datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
           if args.end else today)

    mapping = {}
    for pair in args.duka_symbol.split(","):
        if ":" in pair:
            a, b = pair.split(":", 1)
            mapping[a.strip().upper()] = b.strip().upper()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    url = "" if args.dry_run else db_url()
    if not args.dry_run and not url:
        print("[HATA] DATABASE_URL yok (--dry-run kullanın)")
        return 2

    conn = None
    if url:
        import psycopg
        conn = psycopg.connect(url)
        conn.execute(DDL_SPREAD)
        conn.commit()

    hours = hours_between(start, end)
    print(f"Aralık: {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC "
          f"({len(hours)} saat) | semboller: {', '.join(symbols)} | worker={args.workers}")
    if len(hours) * len(symbols) > 5000:
        print(f"[UYARI] {len(hours)*len(symbols)} istek — saat başına ~5-20 KB. "
              "Uzun aralıkta sembol sembol koşun (CDN ara sıra 503 veriyor).")

    total_bars = total_spread = 0
    for sym in symbols:
        duka = mapping.get(sym, sym)
        t0 = time.time()
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            chunks = list(ex.map(lambda h: tick_hour(duka, h), hours))
        ticks: list[tuple[int, float, float, float, float]] = []
        for c in chunks:
            if c:
                ticks.extend(c)
        if not ticks:
            print(f"  {sym:<9} VERİ YOK ({duka}) — sembol adı farklı olabilir "
                  f"(--duka-symbol {sym}:DOGRU_AD)")
            continue
        raw_med = sorted(t[2] for t in ticks[len(ticks) // 2: len(ticks) // 2 + 101])[50] \
            if len(ticks) > 200 else sorted(t[2] for t in ticks)[len(ticks) // 2]
        scale, pip = detect_scale(sym, raw_med)
        bars = build(sym, ticks, scale, pip)
        if not bars:
            print(f"  {sym:<9} tick var ama bar yok — atlandı")
            continue

        step = 60_000
        now_ts = time.time()
        rows_hc = []
        rows_sp = []
        for m, b in bars.items():
            avg, p50, p90, mx = spread_stats(b)
            rows_hc.append((sym, "1m", m, m + step, b["o"], b["h"], b["l"], b["c"],
                            float(b["ticks"]), float(b["vol"]), int(b["ticks"]),
                            "dukascopy_bid", now_ts))
            rows_sp.append((sym, m, avg, p50, p90, mx, int(b["ticks"]), now_ts))

        if conn is not None:
            import psycopg  # noqa: F401
            with conn.cursor() as cur:
                # FILL-ONLY: mevcut (broker/MT5) satır EZİLMEZ — yalnız boşluğu doldurur.
                cur.executemany(
                    "INSERT INTO historical_candles (symbol, timeframe, open_time, close_time, "
                    "open, high, low, close, volume, quote_volume, trade_count, source, fetched_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (symbol, timeframe, open_time) DO NOTHING", rows_hc)
                cur.executemany(
                    "INSERT INTO fx_spread_history (symbol, open_time, spread_avg, spread_p50, "
                    "spread_p90, spread_max, ticks, fetched_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (symbol, open_time) DO UPDATE SET spread_avg=EXCLUDED.spread_avg, "
                    "spread_p50=EXCLUDED.spread_p50, spread_p90=EXCLUDED.spread_p90, "
                    "spread_max=EXCLUDED.spread_max, ticks=EXCLUDED.ticks, "
                    "fetched_at=EXCLUDED.fetched_at", rows_sp)
            conn.commit()
            wrote = conn.execute(
                "SELECT count(*) FROM historical_candles WHERE symbol=%s AND timeframe='1m' "
                "AND source='dukascopy_bid' AND open_time >= %s AND open_time < %s",
                (sym, int(start.timestamp() * 1000), int(end.timestamp() * 1000))).fetchone()[0]
        else:
            wrote = len(rows_hc)

        all_sp = sorted(s["sp"][len(s["sp"]) // 2] for s in bars.values())
        p50_all = all_sp[len(all_sp) // 2]
        # Kilit ölçüm: rollover saati (21-22 UTC) spread'i gün içi medyana göre kaç kat?
        roll = [spread_stats(b)[1] for m, b in bars.items()
                if dt.datetime.fromtimestamp(m / 1000, dt.timezone.utc).hour in (21, 22)]
        ratio = (sorted(roll)[len(roll) // 2] / p50_all) if roll and p50_all > 0 else 0.0
        lo = dt.datetime.fromtimestamp(min(bars) / 1000, dt.timezone.utc)
        hi = dt.datetime.fromtimestamp(max(bars) / 1000, dt.timezone.utc)
        print(f"  {sym:<9} {len(bars):>6} M1 | {lo:%Y-%m-%d} → {hi:%Y-%m-%d} | "
              f"pip={pip:g} | medyan spread {p50_all:.2f}p | roll(21-22) {ratio:.2f}× | "
              f"yazılan {wrote} | {time.time()-t0:.0f}s")
        total_bars += wrote
        total_spread += len(rows_sp)

    if conn is not None:
        conn.close()
    print(f"\nTOPLAM: {total_bars} M1 bar · {total_spread} dakika spread profili")
    print(f"İstek: {_STATS['hours']} saat · boş (piyasa kapalı) {_STATS['empty']} · "
          f"başarısız {_STATS['fail']}")
    if not args.dry_run:
        print("\nSonraki adım: maliyet modelini gerçek spread'le karşılaştır →\n"
              "  SELECT hour, round(avg(spread_p50),2) FROM ("
              "SELECT open_time, extract(hour from to_timestamp(open_time/1000)) hour, spread_p50 "
              "FROM fx_spread_history WHERE symbol='EURUSD') t GROUP BY 1 ORDER BY 1;")
    return 0


if __name__ == "__main__":
    sys.exit(main())
