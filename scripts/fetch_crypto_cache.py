import json
import time
import urllib.request
import os

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT", "DOGEUSDT"]
INTERVAL = "15m"
LIMIT = 1000

out_data = {}

for sym in SYMBOLS:
    print(f"Fetching {sym} ({INTERVAL}, {LIMIT} bars)...")
    url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={INTERVAL}&limit={LIMIT}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_klines = json.loads(resp.read().decode())
        
        # kline format: [open_time_ms, open, high, low, close, volume, ...]
        formatted_bars = []
        for k in raw_klines:
            t_sec = float(k[0]) / 1000.0
            o = float(k[1])
            h = float(k[2])
            l = float(k[3])
            c = float(k[4])
            v = float(k[5])
            formatted_bars.append([t_sec, o, h, l, c, v])
            
        out_data[sym] = formatted_bars
        # also add short alias without USDT (e.g. BTC, ETH, SOL)
        alias = sym.replace("USDT", "USD")
        out_data[alias] = formatted_bars
        print(f"  -> {sym}: {len(formatted_bars)} bars successfully downloaded.")
    except Exception as exc:
        print(f"  Error fetching {sym}: {exc}")

os.makedirs("outputs", exist_ok=True)
out_path = "outputs/crypto_candles_cache.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out_data, f)

print(f"\nSaved {len(out_data)} symbols to {out_path}!")
