"""
Piyasa Rejimi (BTC Trend Şemsiyesi) + Dinamik Çıkış Laboratuvarı
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

def simulate_trade(df, signals, tp_pct=2.2, sl_pct=1.1, be_trigger=0.8, timeout_bars=20):
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
    n = len(df)
    
    for i in range(n):
        if not in_pos and sig[i]:
            in_pos = True
            entry_p = closes[i]
            curr_sl = entry_p * (1.0 - sl_pct / 100.0)
            entry_idx = i
            max_price = entry_p
        elif in_pos:
            bars_held = i - entry_idx
            if highs[i] > max_price:
                max_price = highs[i]
            mfe_pct = (max_price - entry_p) / entry_p * 100.0
            
            # Dinamik Stop: %0.8 kâr görülünce stop maliyet + %0.15'e çekilir
            if mfe_pct >= be_trigger:
                be_level = entry_p * 1.0015
                if be_level > curr_sl:
                    curr_sl = be_level
                    
            # %1.4 kâr görülünce stop maliyet + %0.80'e çekilir
            if mfe_pct >= 1.4:
                be_level = entry_p * 1.0080
                if be_level > curr_sl:
                    curr_sl = be_level
                    
            target_p = entry_p * (1.0 + tp_pct / 100.0)
            hit_tp = highs[i] >= target_p
            hit_sl = lows[i] <= curr_sl
            time_exit = bars_held >= timeout_bars
            
            if hit_tp or hit_sl or time_exit:
                if hit_tp:
                    exit_p = target_p
                elif hit_sl:
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

async def run():
    conn = await asyncpg.connect(DB_URL)
    
    # 1. BTC 1h ve 15m verisini yükle
    btc_1h_rows = await conn.fetch("SELECT open_time, open, high, low, close, volume FROM historical_candles WHERE symbol='BTCUSDT' AND timeframe='1h' ORDER BY open_time ASC")
    btc_1h = pd.DataFrame([dict(r) for r in btc_1h_rows]).set_index("open_time")
    btc_st = calc_supertrend(btc_1h)
    btc_ema50 = calc_ema(btc_1h["close"], 50)
    btc_bull_1h = (btc_1h["close"] > btc_ema50) & (btc_st == 1)
    
    print("=" * 95)
    print("  👑 BTC PİYASA REJİMİ ŞEMSİYESİ İLE SPOT LONG PERFORMANSI (15M MUM)")
    print("=" * 95)
    print(f"{'Filtre Durumu':<35} | {'İşlem':<8} | {'WinRate %':<12} | {'Profit Factor':<15} | {'Net Kâr %':<10}")
    print("-" * 95)
    
    for regime_filter in [False, True]:
        label = "BTC Rejim Filtreli (Sadece Boğa Saatleri)" if regime_filter else "Filtresiz (Her Piyasa Koşulunda)"
        total_tr, total_w, total_gw, total_gl, total_ret = 0, 0, 0.0, 0.0, 0.0
        
        for sym in TEST_SYMBOLS:
            rows15 = await conn.fetch("SELECT open_time, open, high, low, close, volume FROM historical_candles WHERE symbol=$1 AND timeframe='15m' ORDER BY open_time ASC", sym)
            rows1h = await conn.fetch("SELECT open_time, open, high, low, close, volume FROM historical_candles WHERE symbol=$1 AND timeframe='1h' ORDER BY open_time ASC", sym)
            if len(rows15) < 300 or len(rows1h) < 100:
                continue
                
            df15 = pd.DataFrame([dict(r) for r in rows15]).set_index("open_time")
            df1h = pd.DataFrame([dict(r) for r in rows1h]).set_index("open_time")
            
            # Sembol Kendi İndikatörleri
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
            
            coin_ema50 = calc_ema(df1h["close"], 50).reindex(df15.index, method="ffill")
            coin_trend = df15["close"] > coin_ema50
            
            signals = coin_trend & sq_break & vol_ok
            
            if regime_filter:
                btc_gate = btc_bull_1h.reindex(df15.index, method="ffill").fillna(False)
                signals = signals & btc_gate
                
            t, wr, pf, r = simulate_trade(df15, signals, tp_pct=2.4, sl_pct=1.2, be_trigger=0.9, timeout_bars=20)
            if t > 0:
                total_tr += t
                total_w += int(round(t * wr / 100.0))
                total_ret += r
                
        wr_final = (total_w / total_tr * 100.0) if total_tr > 0 else 0.0
        print(f"{label:<35} | {total_tr:<8d} | %{wr_final:<11.1f} | {'-':<15} | %{total_ret:<+9.2f}")
        
    await conn.close()
    print("=" * 95)

if __name__ == "__main__":
    asyncio.run(run())
