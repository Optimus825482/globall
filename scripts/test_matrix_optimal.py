"""
Optimal R:R ile 8 Strateji ve Kombinasyon Matrisi Testi
"""
import sys
import asyncio
import asyncpg
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB_URL = "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"
COMMISSION_ROUNDTRIP = 0.0008  # %0.08 roundtrip

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

def calc_kdj(df, n=9, m1=3, m2=3):
    low_n = df["low"].rolling(n).min()
    high_n = df["high"].rolling(n).max()
    denom = (high_n - low_n).replace(0, np.nan)
    rsv = ((df["close"] - low_n) / denom).fillna(0.5) * 100.0
    k = rsv.ewm(alpha=1/m1, adjust=False).mean()
    d = k.ewm(alpha=1/m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j

def calc_zlmacd(df, fast=12, slow=26, signal=9):
    def zlema(s, period):
        lag = (period - 1) // 2
        zldata = s + (s - s.shift(lag).fillna(s))
        return calc_ema(zldata, period)
    zl_fast = zlema(df["close"], fast)
    zl_slow = zlema(df["close"], slow)
    zl_line = zl_fast - zl_slow
    zl_sig = calc_ema(zl_line, signal)
    zl_hist = zl_line - zl_sig
    return zl_line, zl_sig, zl_hist

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

async def main():
    conn = await asyncpg.connect(DB_URL)
    data_15m, data_1h = {}, {}
    for sym in TEST_SYMBOLS:
        rows15 = await conn.fetch("SELECT open_time, open, high, low, close, volume FROM historical_candles WHERE symbol=$1 AND timeframe='15m' ORDER BY open_time ASC", sym)
        rows1h = await conn.fetch("SELECT open_time, open, high, low, close, volume FROM historical_candles WHERE symbol=$1 AND timeframe='1h' ORDER BY open_time ASC", sym)
        if len(rows15) >= 300 and len(rows1h) >= 100:
            data_15m[sym] = pd.DataFrame([dict(r) for r in rows15]).set_index("open_time")
            data_1h[sym] = pd.DataFrame([dict(r) for r in rows1h]).set_index("open_time")
    await conn.close()
    
    features = {}
    for sym, df15 in data_15m.items():
        df1h = data_1h[sym]
        ema200_1h = calc_ema(df1h["close"], 200).reindex(df15.index, method="ffill")
        trend_1h = df15["close"] > (ema200_1h * 0.99)
        
        ema20 = calc_ema(df15["close"], 20)
        ema50 = calc_ema(df15["close"], 50)
        st = calc_supertrend(df15)
        stc = calc_stc(df15)
        k, d, j = calc_kdj(df15)
        zl_l, zl_s, zl_hist = calc_zlmacd(df15)
        
        # Volatilite & Hacim
        vol_avg = df15["volume"].rolling(20).mean()
        high_vol = df15["volume"] >= (vol_avg * 1.30)
        
        sma20 = df15["close"].rolling(20).mean()
        std20 = df15["close"].rolling(20).std()
        bbu = sma20 + 2.0 * std20
        bbl = sma20 - 2.0 * std20
        atr = calc_atr(df15, 20)
        kcu = sma20 + 1.5 * atr
        kcl = sma20 - 1.5 * atr
        sq_was = ((bbl.shift(1) > kcl.shift(1)) & (bbu.shift(1) < kcu.shift(1)))
        sq_break = sq_was & (df15["close"] > bbu)
        
        ema50_dist = (df15["low"] - ema50).abs() / ema50
        ema_bounce = (ema50_dist <= 0.006) & (df15["close"] > ema50) & (j <= 35) & (j > j.shift(1))
        stc_dip = (stc.shift(1) <= 25.0) & (stc > 25.0)
        zl_cross = (zl_hist.shift(1) <= 0.0) & (zl_hist > 0.0) & (ema20 >= ema50)
        st_pullback = (st == 1) & (j.shift(1) <= 20.0) & (j > j.shift(1))
        kdj_dip = (j.shift(1) <= 15.0) & (j > j.shift(1))
        
        features[sym] = {
            "df": df15,
            "trend_1h": trend_1h,
            "ema_bounce": ema_bounce,
            "sq_break": sq_break,
            "stc_dip": stc_dip,
            "zl_cross": zl_cross,
            "st_pullback": st_pullback,
            "kdj_dip": kdj_dip,
            "high_vol": high_vol,
            "trend_15m": df15["close"] > ema50
        }
        
    print("=" * 110)
    print("  🏆 BÖLÜM 1: 8 TEKİL STRATEJİNİN AYRI AYRI BENCHMARK'I (15M MUM - 162.000 MUM - TP %2.2 / SL %1.1)")
    print("=" * 110)
    print(f"{'Strateji':<35} | {'İşlem':<8} | {'WinRate %':<12} | {'Profit Factor':<15} | {'Net Kâr %':<12} | {'Durum':<10}")
    print("-" * 110)
    
    singles = [
        ("S1. EMA 50 Sekmesi + KDJ", lambda f: f["ema_bounce"]),
        ("S2. BB-KC Sıkışma Kırılımı", lambda f: f["sq_break"]),
        ("S3. Schaff Trend Cycle (STC)", lambda f: f["stc_dip"]),
        ("S4. Zero-Lag MACD Momentum", lambda f: f["zl_cross"]),
        ("S5. SuperTrend Pullback", lambda f: f["st_pullback"]),
        ("S6. KDJ Ekstrem Dip (J<=15)", lambda f: f["kdj_dip"]),
        ("S7. EMA20/50 Trend + Hacimli STC", lambda f: f["trend_15m"] & f["stc_dip"] & f["high_vol"]),
        ("S8. EMA20/50 Trend + Hacimli Kırılım", lambda f: f["trend_15m"] & f["sq_break"] & f["high_vol"]),
    ]
    
    for label, sig_gen in singles:
        tot_tr, tot_w, tot_gw, tot_gl, tot_ret = 0, 0, 0.0, 0.0, 0.0
        for sym, f in features.items():
            t, wr, pf, r = simulate_strategy_rr(f["df"], sig_gen(f), tp_pct=2.2, sl_pct=1.1, timeout_bars=24)
            if t > 0:
                tot_tr += t
                w_cnt = int(round(t * wr / 100.0))
                tot_w += w_cnt
                tot_ret += r
                tot_gw += w_cnt * 2.2
                tot_gl += (t - w_cnt) * 1.1
        f_wr = (tot_w / tot_tr * 100.0) if tot_tr > 0 else 0.0
        f_pf = (tot_gw / tot_gl) if tot_gl > 0 else 0.0
        status = "✅ KÂRLI" if tot_ret > 0 else "❌ ZARARDA"
        print(f"{label:<35} | {tot_tr:<8d} | %{f_wr:<11.1f} | {f_pf:<15.2f} | %{tot_ret:<+11.2f} | {status:<10}")
        
    print("\n" + "=" * 110)
    print("  🚀 BÖLÜM 2: EN GÜÇLÜ KOMBİNASYONLAR (CONFLUENCE MATRİSİ - BİRLİKTE TEST)")
    print("=" * 110)
    print(f"{'Kombinasyon Adı':<42} | {'İşlem':<8} | {'WinRate %':<12} | {'Profit Factor':<15} | {'Net Kâr %':<12} | {'Rütbe':<10}")
    print("-" * 110)
    
    combos = [
        ("C1. BB Sıkışma + Hacim Patlaması", lambda f: f["sq_break"] & f["high_vol"]),
        ("C2. Trend + BB Sıkışma + Hacim Patlaması", lambda f: f["trend_15m"] & f["sq_break"] & f["high_vol"]),
        ("C3. Makro Trend (1h) + BB Sıkışma + Hacim", lambda f: f["trend_1h"] & f["sq_break"] & f["high_vol"]),
        ("C4. Trend + STC Dip + Hacim", lambda f: f["trend_15m"] & f["stc_dip"] & f["high_vol"]),
        ("C5. ZLMACD Momentum + STC Dip Çift Teyit", lambda f: f["zl_cross"] & (calc_stc(f["df"]) < 40)),
        ("C6. SuperTrend + ZLMACD Momentum", lambda f: f["st_pullback"] & f["zl_cross"]),
        ("C7. Makro 1h Trend + STC Dip Dönüşü", lambda f: f["trend_1h"] & f["stc_dip"]),
        ("C8. Makro 1h Trend + Sıkışma + STC", lambda f: f["trend_1h"] & f["sq_break"] & (calc_stc(f["df"]) > 25)),
    ]
    
    for label, sig_gen in combos:
        tot_tr, tot_w, tot_gw, tot_gl, tot_ret = 0, 0, 0.0, 0.0, 0.0
        for sym, f in features.items():
            t, wr, pf, r = simulate_strategy_rr(f["df"], sig_gen(f), tp_pct=2.2, sl_pct=1.1, timeout_bars=24)
            if t > 0:
                tot_tr += t
                w_cnt = int(round(t * wr / 100.0))
                tot_w += w_cnt
                tot_ret += r
                tot_gw += w_cnt * 2.2
                tot_gl += (t - w_cnt) * 1.1
        f_wr = (tot_w / tot_tr * 100.0) if tot_tr > 0 else 0.0
        f_pf = (tot_gw / tot_gl) if tot_gl > 0 else 0.0
        rank = "🥇 ŞAMPİYON" if tot_ret >= 20.0 else ("🥈 GÜÇLÜ" if tot_ret > 0 else "❌ ELENDİ")
        print(f"{label:<42} | {tot_tr:<8d} | %{f_wr:<11.1f} | {f_pf:<15.2f} | %{tot_ret:<+11.2f} | {rank:<10}")
        
    print("=" * 110)

if __name__ == "__main__":
    asyncio.run(main())
