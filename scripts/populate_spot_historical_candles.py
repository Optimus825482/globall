"""
Binance Spot Varlıklar İçin Geniş Tarihsel Veri Çekme ve Yerel PostgreSQL'e Depolama Aracı.
Tüm ana spot varlıklar için 5m, 15m ve 1h zaman dilimlerinde 3.000 - 5.000 mum çeker ve
`historical_candles` tablosuna ON CONFLICT DO UPDATE ile kalıcı olarak kaydeder.
"""
import sys
import time
import json
import asyncio
import asyncpg
import urllib.request
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

SPOT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "NEARUSDT", "DOGEUSDT",
    "PEPEUSDT", "BNBUSDT", "XRPUSDT", "LINKUSDT", "SHIBUSDT", "ADAUSDT",
    "DOTUSDT", "RENDERUSDT", "FETUSDT", "ARBUSDT", "OPUSDT", "INJUSDT"
]

TIMEFRAMES = {
    "5m": 4000,   # ~14 gün yüksek çözünürlüklü scalp verisi
    "15m": 3000,  # ~31 gün standart trend verisi
    "1h": 2000    # ~83 gün makro trend verisi
}

DB_URL = "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"

def fetch_chunk(symbol: str, interval: str, limit: int = 1000, end_time: int = None) -> list:
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    if end_time:
        url += f"&endTime={end_time}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"    [!] Çekme hatası ({symbol} {interval}): {e}")
        return []

async def download_and_store():
    conn = await asyncpg.connect(DB_URL)
    print("=" * 80)
    print("  📥 SPOT TARİHSEL VERİ TOPLAMA & YEREL VERİTABANINA DEPOLAMA BAŞLATILDI")
    print("=" * 80)
    print(f"Hedef Sembol Sayısı: {len(SPOT_SYMBOLS)}")
    print(f"Hedef Zaman Dilimleri: {list(TIMEFRAMES.keys())}")
    print("Hedef Tablo: public.historical_candles\n")

    total_inserted = 0
    start_all = time.time()

    for sym in SPOT_SYMBOLS:
        print(f"\n🪙 {sym} Verileri Çekiliyor:")
        for tf, target_bars in TIMEFRAMES.items():
            all_klines = {}
            end_time = None
            
            # Sayfalı geriye doğru çekim (1000'er bar)
            while len(all_klines) < target_bars:
                limit = min(1000, target_bars - len(all_klines) + 50)
                chunk = fetch_chunk(sym, tf, limit=limit, end_time=end_time)
                if not chunk:
                    break
                
                for k in chunk:
                    all_klines[int(k[0])] = k
                
                # En eski mumun open_time - 1 ms
                first_open = int(chunk[0][0])
                if end_time == first_open - 1:
                    break # daha eski veri yok
                end_time = first_open - 1
                time.sleep(0.08) # rate-limit saygısı
                
            bars_list = sorted(all_klines.values(), key=lambda x: int(x[0]))
            now_ts = time.time() * 1000.0

            # Batch insert formatı
            records = [
                (
                    sym,
                    tf,
                    int(k[0]),                                # open_time
                    int(k[6]),                                # close_time
                    float(k[1]),                              # open
                    float(k[2]),                              # high
                    float(k[3]),                              # low
                    float(k[4]),                              # close
                    float(k[5]),                              # volume
                    float(k[7]),                              # quote_volume
                    int(k[8]),                                # trade_count
                    "binance_spot_historical_lab",           # source
                    now_ts                                    # fetched_at
                )
                for k in bars_list
            ]

            if records:
                await conn.executemany("""
                    INSERT INTO historical_candles (
                        symbol, timeframe, open_time, close_time, open, high, low, close,
                        volume, quote_volume, trade_count, source, fetched_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    ON CONFLICT (symbol, timeframe, open_time) DO UPDATE
                    SET close = EXCLUDED.close,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        volume = EXCLUDED.volume,
                        quote_volume = EXCLUDED.quote_volume,
                        trade_count = EXCLUDED.trade_count,
                        fetched_at = EXCLUDED.fetched_at
                """, records)
                
                total_inserted += len(records)
                dt_start = datetime.fromtimestamp(bars_list[0][0] / 1000, tz=timezone.utc).strftime("%d/%m %H:%M")
                dt_end = datetime.fromtimestamp(bars_list[-1][0] / 1000, tz=timezone.utc).strftime("%d/%m %H:%M")
                print(f"  └─ {tf:3s}: {len(records):4d} mum kaydedildi ({dt_start} -> {dt_end})")
            else:
                print(f"  └─ {tf:3s}: Veri alınamadı!")

    await conn.close()
    elapsed = time.time() - start_all
    print("\n" + "=" * 80)
    print(f"  ✅ TÜM VERİLER BAŞARIYLA YEREL VERİTABANINA DEPOLANDI!")
    print(f"  Toplam İşlenen / Güncellenen Mum: {total_inserted:,}")
    print(f"  Toplam Süre: {elapsed:.1f} saniye")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(download_and_store())
