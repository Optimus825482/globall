"""
Gerçekçi Kâr & R:R Optimizasyonu Laboratuvarı:
Hangi R:R (Kâr/Zarar Oranı) ve Çıkış Kuralı 162.000 mumda pozitif net kâr üretiyor?
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

def run_sim(df, sigs, tp_pct, sl_pct, be_pct=None, timeout=20):
    trades = []
    in_pos = False
    entry_p = 0.0
    curr_sl = 0.0
    entry_idx = 0
    max_p = 0.0
    
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    sig = sigs.values
    n = len(df)
    
    for i in range(n):
        if not in_pos and sig[i]:
            in_pos = True
            entry_p = closes[i]
            curr_sl = entry_p * (1.0 - sl_pct / 100.0)
            entry_idx = i
            max_p = entry_p
        elif in_pos:
            bars_held = i - entry_idx
            if highs[i] > max_p:
                max_p = highs[i]
            mfe_pct = (max_p - entry_p) / entry_p * 100.0
            
            if be_pct and mfe_pct >= be_pct:
                be_level = entry_p * 1.0020 # maliyet + %0.20 garanti
                if be_level > curr_sl:
                    curr_sl = be_level
                    
            target_p = entry_p * (1.0 + tp_pct / 100.0)
            hit_tp = highs[i] >= target_p
            hit_sl = lows[i] <= curr_sl
            time_exit = bars_held >= timeout
            
            if hit_tp or hit_sl or time_exit:
                exit_p = target_p if hit_tp else (curr_sl if hit_sl else closes[i])
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

async def test():
    conn = await asyncpg.connect(DB_URL)
    data = {}
    for sym in TEST_SYMBOLS:
        rows = await conn.fetch("SELECT open_time, open, high, low, close, volume FROM historical_candles WHERE symbol=$1 AND timeframe='15m' ORDER BY open_time ASC", sym)
        if len(rows) >= 300:
            df = pd.DataFrame([dict(r) for r in rows]).set_index("open_time")
            data[sym] = df
    await conn.close()
    
    # 4 Güçlü Sinyal Türü
    sig_sets = {}
    for sym, df in data.items():
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
        high_vol = df["volume"] >= (vol_avg * 1.3)
        ema50 = calc_ema(df["close"], 50)
        trend = df["close"] > ema50
        stc = calc_stc(df)
        stc_dip = (stc.shift(1) <= 25.0) & (stc > 25.0)
        
        sig_sets[sym] = {
            "df": df,
            "squeeze_vol": trend & sq_break & high_vol,
            "stc_vol": trend & stc_dip & high_vol,
            "pure_squeeze": sq_break & high_vol
        }
        
    print("=" * 95)
    print("  🎯 TP/SL VE BE OPTİMİZASYON TARAMASI (Squeeze + Hacim Sinyali Üzerinde)")
    print("=" * 95)
    print(f"{'TP %':<8} | {'SL %':<8} | {'BE Tetik %':<12} | {'İşlem':<8} | {'WinRate %':<12} | {'PF':<8} | {'Net Kâr %':<10}")
    print("-" * 95)
    
    configs = [
        (1.2, 0.8, None),
        (1.5, 0.9, None),
        (1.8, 1.0, None),
        (2.0, 1.0, None),
        (2.2, 1.1, None),
        (2.4, 1.2, None),
        (1.8, 1.0, 1.0),
        (2.0, 1.0, 1.1),
        (2.4, 1.2, 1.2),
        (3.0, 1.5, 1.5),
    ]
    
    for tp, sl, be in configs:
        tot_tr, tot_w, tot_gw, tot_gl, tot_ret = 0, 0, 0.0, 0.0, 0.0
        for sym, d in sig_sets.items():
            t, wr, pf, r = run_sim(d["df"], d["squeeze_vol"], tp_pct=tp, sl_pct=sl, be_pct=be, timeout=24)
            if t > 0:
                tot_tr += t
                w_cnt = int(round(t * wr / 100.0))
                tot_w += w_cnt
                tot_ret += r
                tot_gw += w_cnt * tp
                tot_gl += (t - w_cnt) * sl
        f_wr = (tot_w / tot_tr * 100.0) if tot_tr > 0 else 0.0
        f_pf = (tot_gw / tot_gl) if tot_gl > 0 else 0.0
        be_str = f"%{be:.1f}" if be else "YOK"
        print(f"%{tp:<7.1f} | %{sl:<7.1f} | {be_str:<12} | {tot_tr:<8d} | %{f_wr:<11.1f} | {f_pf:<7.2f} | %{tot_ret:<+9.2f}")
        
    print("=" * 95)

if __name__ == "__main__":
    asyncio.run(test())
