"""
Dynamic Exit Architect Doğrulama ve Optimizasyon
"""
import sys
import asyncio
import asyncpg
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB_URL = "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"
COMMISSION_ROUNDTRIP = 0.0008

TEST_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "NEARUSDT", "DOGEUSDT",
    "PEPEUSDT", "BNBUSDT", "XRPUSDT", "LINKUSDT", "SHIBUSDT", "ADAUSDT",
    "DOTUSDT", "RENDERUSDT", "FETUSDT", "ARBUSDT", "OPUSDT", "INJUSDT"
]

def calc_ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def calc_atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def calc_stc(df, period=10, fast=23, slow=50):
    macd = calc_ema(df["close"], fast) - calc_ema(df["close"], slow)
    macd_min = macd.rolling(period).min()
    macd_max = macd.rolling(period).max()
    denom = macd_max - macd_min
    stoch1 = ((macd - macd_min) / denom.replace(0, np.nan)).fillna(0.5) * 100.0
    smooth1 = stoch1.ewm(alpha=0.5, adjust=False).mean()
    s2_min = smooth1.rolling(period).min()
    s2_max = smooth1.rolling(period).max()
    denom2 = s2_max - s2_min
    stoch2 = ((smooth1 - s2_min) / denom2.replace(0, np.nan)).fillna(0.5) * 100.0
    return stoch2.ewm(alpha=0.5, adjust=False).mean()

def simulate_dynamic_exit(df, signals, be_trigger=1.0, trail_dist=0.7, timeout_bars=24):
    trades = []
    in_pos = False
    entry_p = 0.0
    curr_sl = 0.0
    entry_idx = 0
    max_price = 0.0
    
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    sig = signals.values
    atr = calc_atr(df, 14).values
    n = len(df)
    
    for i in range(n):
        if not in_pos and sig[i]:
            in_pos = True
            entry_p = closes[i]
            # Nefes alma alanı: ATR x 1.2 veya min %1.2, max %2.5
            atr_pct = (atr[i] / entry_p * 100.0) if not np.isnan(atr[i]) else 1.2
            init_sl_pct = max(1.2, min(2.5, atr_pct * 1.3))
            curr_sl = entry_p * (1.0 - init_sl_pct / 100.0)
            entry_idx = i
            max_price = entry_p
        elif in_pos:
            bars_held = i - entry_idx
            if highs[i] > max_price:
                max_price = highs[i]
            mfe_pct = (max_price - entry_p) / entry_p * 100.0
            
            # 1. Kademeli Kâr Kilidi: %1.0 kâr görüldüğünde maliyet + komisyon (%0.15 üstü)
            if mfe_pct >= be_trigger:
                be_level = entry_p * 1.0015
                if be_level > curr_sl:
                    curr_sl = be_level
                    
            # 2. Dinamik Takipçi Stop: Zirveden geriye trail_dist kadar
            if mfe_pct >= 1.5:
                trail_level = max_price * (1.0 - trail_dist / 100.0)
                if trail_level > curr_sl:
                    curr_sl = trail_level
                    
            # TP2 Hedefi (%3.5 genişleme)
            tp_hit = highs[i] >= (entry_p * 1.035)
            sl_hit = lows[i] <= curr_sl
            time_hit = bars_held >= timeout_bars
            
            if tp_hit or sl_hit or time_hit:
                if tp_hit:
                    exit_p = entry_p * 1.035
                elif sl_hit:
                    exit_p = curr_sl
                else:
                    exit_p = closes[i]
                net_ret = ((exit_p - entry_p) / entry_p) * 100.0 - (COMMISSION_ROUNDTRIP * 100.0)
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

async def test():
    conn = await asyncpg.connect(DB_URL)
    print("=" * 95)
    print("  🚀 DYNAMIC EXIT ARCHITECT PARAMETRE TARAMASI (18 COIN - 15M/1H VERİTABANI)")
    print("=" * 95)
    print(f"{'BE Tetik':<12} | {'Trail Mesafe':<15} | {'İşlem Sayısı':<12} | {'WinRate %':<12} | {'Profit Factor':<15} | {'Net Kâr %':<10}")
    print("-" * 95)
    
    param_grid = [
        (0.8, 0.6),
        (0.9, 0.6),
        (1.0, 0.6),
        (1.0, 0.8),
        (1.2, 0.8),
        (1.2, 1.0),
        (1.5, 1.0),
    ]
    
    for be_trig, tr_dist in param_grid:
        total_tr, total_w, total_gw, total_gl, total_ret = 0, 0, 0.0, 0.0, 0.0
        for sym in TEST_SYMBOLS:
            rows15 = await conn.fetch("SELECT open_time, open, high, low, close, volume FROM historical_candles WHERE symbol=$1 AND timeframe='15m' ORDER BY open_time ASC", sym)
            rows1h = await conn.fetch("SELECT open_time, open, high, low, close, volume FROM historical_candles WHERE symbol=$1 AND timeframe='1h' ORDER BY open_time ASC", sym)
            if len(rows15) < 300 or len(rows1h) < 100:
                continue
            df15 = pd.DataFrame([dict(r) for r in rows15]).set_index("open_time")
            df1h = pd.DataFrame([dict(r) for r in rows1h]).set_index("open_time")
            
            # Sinyal: BB-KC Kırılımı + Hacim (En sağlam setup)
            sma20 = df15["close"].rolling(20).mean()
            std20 = df15["close"].rolling(20).std()
            bbu = sma20 + 2.0 * std20
            bbl = sma20 - 2.0 * std20
            atr15 = calc_atr(df15, 20)
            kcu = sma20 + 1.5 * atr15
            kcl = sma20 - 1.5 * atr15
            sq_was = ((bbl.shift(1) > kcl.shift(1)) & (bbu.shift(1) < kcu.shift(1)))
            sq_break = sq_was & (df15["close"] > bbu)
            vol_avg = df15["volume"].rolling(20).mean()
            vol_ok = df15["volume"] >= (vol_avg * 1.3)
            
            ema200_1h = calc_ema(df1h["close"], 200).reindex(df15.index, method="ffill")
            trend_bull = df15["close"] > ema200_1h * 0.99
            
            signals = trend_bull & sq_break & vol_ok
            
            t, wr, pf, r = simulate_dynamic_exit(df15, signals, be_trigger=be_trig, trail_dist=tr_dist, timeout_bars=24)
            if t > 0:
                total_tr += t
                total_w += int(round(t * wr / 100.0))
                total_ret += r
                
        wr_final = (total_w / total_tr * 100.0) if total_tr > 0 else 0.0
        print(f"%{be_trig:<11.1f} | %{tr_dist:<14.1f} | {total_tr:<12d} | %{wr_final:<11.1f} | {'-':<15} | %{total_ret:<+9.2f}")
        
    await conn.close()
    print("=" * 95)

if __name__ == "__main__":
    asyncio.run(test())
