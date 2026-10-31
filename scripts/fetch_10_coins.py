import json
import time
import urllib.request
import os

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT", "DOGEUSDT", "XRPUSDT", "LINKUSDT", "NEARUSDT", "SUIUSDT"]
INTERVALS = ["15m", "5m"]
LIMIT = 1000

cache_5m = {}
cache_15m = {}

for interval, cache_dict in [("15m", cache_15m), ("5m", cache_5m)]:
    print(f"\n--- {interval.upper()} BARLARI İNDİRİLİYOR ---")
    for sym in COINS:
        url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={LIMIT}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw_klines = json.loads(resp.read().decode())
            formatted_bars = []
            for k in raw_klines:
                t_sec = float(k[0]) / 1000.0
                formatted_bars.append([t_sec, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
            cache_dict[sym] = formatted_bars
            cache_dict[sym.replace("USDT", "USD")] = formatted_bars
            print(f"  {sym:<10} ({interval}): {len(formatted_bars)} bar tamam.")
        except Exception as exc:
            print(f"  {sym:<10} ({interval}) Hata: {exc}")
        time.sleep(0.1)

os.makedirs("outputs", exist_ok=True)
with open("outputs/crypto_cache_15m.json", "w", encoding="utf-8") as f:
    json.dump(cache_15m, f)
with open("outputs/crypto_cache_5m.json", "w", encoding="utf-8") as f:
    json.dump(cache_5m, f)

print("\n10 Kripto varlık için 5m ve 15m barları outputs/ dizinine kaydedildi!")
