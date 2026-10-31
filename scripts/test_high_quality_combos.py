"""
Yüksek Kaliteli / Düşük İşlem Frekanslı Spot Kombinasyon Laboratuvarı.
5m gürültüsünden ve komisyon erimesinden kaçınarak 15m ve 1h üzerinde test eder.
"""
import sys
import asyncio
import asyncpg
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB_URL = "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"
COMMISSION_RATE = 0.0004 # %0.08 round-trip

TEST_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "NEARUSDT", "DOGEUSDT",
    "PEPEUSDT", "BNBUSDT", "XRPUSDT", "LINKUSDT", "SHIBUSDT", "ADAUSDT",
    "DOTUSDT", "RENDERUSDT", "FETUSDT", "ARBUSDT", "OPUSDT", "INJUSDT"
]

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_stc(df, period=10, fast=23, slow=50):
    macd = calc_ema(df["close"], fast) - calc_ema(df["close"], slow)
    macd_min = macd.rolling(period).min()
    macd_max = macd.rolling(period).max()
    denom = macd_max - macd_min
    stoch1 = ((macd - macd_min) / denom.replace(0, np.nan)).fillna(0.5) * 100.0
    smooth_stoch1 = stoch1.ewm(alpha=0.5, adjust=False).mean()
    stoch2_min = smooth_stoch1.rolling(period).min()
    stoch2_max = smooth_stoch1.rolling(period).max()
    denom2 = stoch2_max - stoch2_min
    stoch2 = ((smooth_stoch1 - stoch2_min) / denom2.replace(0, np.nan)).fillna(0.5) * 100.0
    return stoch2.ewm(alpha=0.5, adjust=False).mean()

def calc_atr(df, period=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_supertrend(df, period=10, factor=3.0):
    atr = calc_atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2.0
    ub = (hl2 + factor * atr).to_numpy().copy()
    lb = (hl2 - factor * atr).to_numpy().copy()
    c = df["close"].to_numpy().copy()
    n = len(df)
    upper_band = ub.copy()
    lower_band = lb.copy()
    direction = np.ones(n, dtype=int)
    for i in range(1, n):
        if lb[i] > lower_band[i-1] or c[i-1] < lower_band[i-1]:
            lower_band[i] = lb[i]
        else:
            lower_band[i] = lower_band[i-1]
        if ub[i] < upper_band[i-1] or c[i-1] > upper_band[i-1]:
            upper_band[i] = ub[i]
        else:
            upper_band[i] = upper_band[i-1]
        if direction[i-1] == 1:
            direction[i] = -1 if c[i] < lower_band[i] else 1
        else:
            direction[i] = 1 if c[i] > upper_band[i] else -1
    return pd.Series(direction, index=df.index)

def simulate_strategy(df, signals, tp_pct=2.5, sl_pct=1.2, timeout_bars=24):
    trades = []
    in_pos = False
    entry_p = 0.0
    entry_idx = 0
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    sig_arr = signals.values
    n = len(df)
    
    for i in range(n):
        if not in_pos and sig_arr[i]:
            in_pos = True
            entry_p = closes[i]
            entry_idx = i
        elif in_pos:
            target_p = entry_p * (1.0 + (tp_pct / 100.0))
            stop_p = entry_p * (1.0 - (sl_pct / 100.0))
            hit_tp = highs[i] >= target_p
            hit_sl = lows[i] <= stop_p
            time_exit = (i - entry_idx) >= timeout_bars
            
            if hit_tp or hit_sl or time_exit:
                exit_p = target_p if hit_tp else (stop_p if hit_sl else closes[i])
                net_ret = ((exit_p - entry_p) / entry_p) * 100.0 - (COMMISSION_RATE * 200.0)
                trades.append(net_ret)
                in_pos = False
                
    if not trades:
        return 0, 0.0, 0.0, 0.0
    wins = [r for r in trades if r > 0]
    losses = [r for r in trades if r <= 0]
    wr = len(wins) / len(trades) * 100.0
    gw = sum(wins) if wins else 0.0
    gl = abs(sum(losses)) if losses else 0.001
    pf = gw / gl
    return len(trades), wr, pf, sum(trades)

async def run():
    conn = await asyncpg.connect(DB_URL)
    print("=" * 85)
    print("  💎 15M / 1H DÜŞÜK FREKANSLI & KALİTELİ SPOT KOMBİNASYON BENCHMARK'I")
    print("=" * 85)
    print(f"{'Sembol':<10} | {'15m STC+Trend':<22} | {'15m Hacimli STC':<22} | {'15m BB Squeeze+Hacim':<22}")
    print("-" * 85)
    
    total_trades_s1, total_ret_s1 = 0, 0.0
    total_trades_s2, total_ret_s2 = 0, 0.0
    total_trades_s3, total_ret_s3 = 0, 0.0
    
    for sym in TEST_SYMBOLS:
        rows15 = await conn.fetch("SELECT open_time, open, high, low, close, volume FROM historical_candles WHERE symbol=$1 AND timeframe='15m' ORDER BY open_time ASC", sym)
        rows1h = await conn.fetch("SELECT open_time, open, high, low, close, volume FROM historical_candles WHERE symbol=$1 AND timeframe='1h' ORDER BY open_time ASC", sym)
        if len(rows15) < 300 or len(rows1h) < 100:
            continue
            
        df15 = pd.DataFrame([dict(r) for r in rows15])
        df1h = pd.DataFrame([dict(r) for r in rows1h])
        df15["time"] = pd.to_datetime(df15["open_time"], unit="ms")
        df1h["time"] = pd.to_datetime(df1h["open_time"], unit="ms")
        df15.set_index("time", inplace=True)
        df1h.set_index("time", inplace=True)
        
        # 1h Trend Filtresi
        st_1h = calc_supertrend(df1h).reindex(df15.index, method="ffill")
        ema200_1h = calc_ema(df1h["close"], 200).reindex(df15.index, method="ffill")
        trend_bull = (df15["close"] > ema200_1h * 0.995) & (st_1h == 1)
        
        # 15m İndikatörler
        stc15 = calc_stc(df15)
        stc_dip = (stc15.shift(1) <= 25.0) & (stc15 > 25.0)
        vol_avg = df15["volume"].rolling(20).mean()
        high_vol = df15["volume"] >= (vol_avg * 1.4) # %40 daha yüksek hacim
        
        # BB Sıkışma
        sma20 = df15["close"].rolling(20).mean()
        std20 = df15["close"].rolling(20).std()
        bbu = sma20 + 2.0 * std20
        bbl = sma20 - 2.0 * std20
        atr15 = calc_atr(df15, 20)
        kcu = sma20 + 1.5 * atr15
        kcl = sma20 - 1.5 * atr15
        sq_was = ((bbl.shift(1) > kcl.shift(1)) & (bbu.shift(1) < kcu.shift(1)))
        sq_break = sq_was & (df15["close"] > bbu)
        
        # 3 Strateji Sinyali:
        sig1 = trend_bull & stc_dip                     # 1. Trend Yönünde STC Dip Dönüşü
        sig2 = trend_bull & stc_dip & high_vol          # 2. Hacim Teyitli STC Dip
        sig3 = trend_bull & sq_break & high_vol         # 3. Trend İçi Sıkışma Kırılımı + Hacim
        
        t1, wr1, pf1, r1 = simulate_strategy(df15, sig1, tp_pct=2.4, sl_pct=1.2, timeout_bars=24)
        t2, wr2, pf2, r2 = simulate_strategy(df15, sig2, tp_pct=2.4, sl_pct=1.2, timeout_bars=24)
        t3, wr3, pf3, r3 = simulate_strategy(df15, sig3, tp_pct=2.2, sl_pct=1.2, timeout_bars=24)
        
        total_trades_s1 += t1; total_ret_s1 += r1
        total_trades_s2 += t2; total_ret_s2 += r2
        total_trades_s3 += t3; total_ret_s3 += r3
        
        col1 = f"{t1:2d} tr | %{wr1:4.1f} | %{r1:+5.1f}"
        col2 = f"{t2:2d} tr | %{wr2:4.1f} | %{r2:+5.1f}"
        col3 = f"{t3:2d} tr | %{wr3:4.1f} | %{r3:+5.1f}"
        print(f"{sym:<10} | {col1:<22} | {col2:<22} | {col3:<22}")
        
    await conn.close()
    print("-" * 85)
    print(f"{'TOPLAM':<10} | {total_trades_s1:2d} tr | Net: %{total_ret_s1:+6.1f} | {total_trades_s2:2d} tr | Net: %{total_ret_s2:+6.1f} | {total_trades_s3:2d} tr | Net: %{total_ret_s3:+6.1f}")
    print("=" * 85)

if __name__ == "__main__":
    asyncio.run(run())
