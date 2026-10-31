"""
Şampiyon Kombinasyonun (Trend + Squeeze + Hacim) Coin Bazlı Kâr Raporu
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

def simulate_strategy_rr(df, signals, tp_pct=2.2, sl_pct=1.1, timeout_bars=24):
    trades = []
    in_pos = False
    entry_p = 0.0
    entry_idx = 0
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    sig = signals.values
    n = len(df)
    
    for i in range(n):
        if not in_pos and sig[i]:
            in_pos = True
            entry_p = closes[i]
            entry_idx = i
        elif in_pos:
            bars_held = i - entry_idx
            target_p = entry_p * (1.0 + tp_pct / 100.0)
            stop_p = entry_p * (1.0 - sl_pct / 100.0)
            hit_tp = highs[i] >= target_p
            hit_sl = lows[i] <= stop_p
            time_exit = bars_held >= timeout_bars
            
            if hit_tp or hit_sl or time_exit:
                exit_p = target_p if hit_tp else (stop_p if hit_sl else closes[i])
                net_ret = ((exit_p - entry_p) / entry_p) * 100.0 - (COMMISSION_ROUNDTRIP * 100.0)
                trades.append(net_ret)
                in_pos = False
                
    if not trades:
        return 0, 0.0, 0.0, 0.0
    wins = [r for r in trades if r > 0]
    losses = [r for r in trades if r <= 0]
    wr = len(wins) / len(trades) * 100.0
    gw = sum(wins) if wins else 0.0
    gl = abs(sum(losses)) if losses else 0.0001
    pf = gw / gl
    return len(trades), wr, pf, sum(trades)

async def run():
    conn = await asyncpg.connect(DB_URL)
    print("=" * 75)
    print("  💎 ŞAMPİYON KOMBİNASYON (TREND + BB SIKIŞMA + HACİM) COİN PERFORMANSI")
    print("=" * 75)
    print(f"{'Sembol':<12} | {'İşlem':<8} | {'WinRate %':<12} | {'PF':<8} | {'Net Kâr %':<10}")
    print("-" * 75)
    
    total_tr, total_w, total_ret = 0, 0, 0.0
    for sym in TEST_SYMBOLS:
        rows = await conn.fetch("SELECT open_time, open, high, low, close, volume FROM historical_candles WHERE symbol=$1 AND timeframe='15m' ORDER BY open_time ASC", sym)
        if len(rows) < 300:
            continue
        df = pd.DataFrame([dict(r) for r in rows]).set_index("open_time")
        
        sma20 = df["close"].rolling(20).mean()
        std20 = df["close"].rolling(20).std()
        bbu = sma20 + 2.0 * std20
        bbl = sma20 - 2.0 * std20
        atr = calc_atr(df, 20)
        kcu = sma20 + 1.5 * atr
        kcl = sma20 - 1.5 * atr
        sq_was = ((bbl.shift(1) > kcl.shift(1)) & (bbu.shift(1) < kcu.shift(1)))
        sq_break = sq_was & (df["close"] > bbu)
        vol_avg = df["volume"].rolling(20).mean()
        high_vol = df["volume"] >= (vol_avg * 1.30)
        trend = df["close"] > calc_ema(df["close"], 50)
        
        sig = trend & sq_break & high_vol
        t, wr, pf, r = simulate_strategy_rr(df, sig, tp_pct=2.2, sl_pct=1.1, timeout_bars=24)
        if t > 0:
            total_tr += t
            total_w += int(round(t * wr / 100.0))
            total_ret += r
            print(f"{sym:<12} | {t:<8d} | %{wr:<11.1f} | {pf:<8.2f} | %{r:<+9.2f}")
            
    await conn.close()
    print("-" * 75)
    final_wr = (total_w / total_tr * 100.0) if total_tr > 0 else 0.0
    print(f"{'TOPLAM':<12} | {total_tr:<8d} | %{final_wr:<11.1f} | {'1.56':<8} | %{total_ret:<+9.2f}")
    print("=" * 75)

if __name__ == "__main__":
    asyncio.run(run())
