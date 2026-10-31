"""
Kapsamlı Spot Strateji Laboratuvarı:
1) 8 Tekil Stratejinin Ayrı Ayrı Testi (Yeni Dinamik Çıkış ve Başabaş Motoru ile)
2) 8 Güçlü Confluence Kombinasyonunun Testi (İndikatörlerin Birlikte Çalışması)
162.000 mumluk PostgreSQL 'historical_candles' spot verisi üzerinde çalışır.
"""
import sys
import asyncio
import asyncpg
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB_URL = "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"
COMMISSION_ROUNDTRIP = 0.0008  # %0.08

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

def calc_linreg_slope(df, period=14):
    # Basit doğrusal regresyon eğimi
    x = np.arange(period)
    x_mean = x.mean()
    x_dev = x - x_mean
    x_var = (x_dev ** 2).sum()
    
    def slope_func(y):
        return ((y - y.mean()) * x_dev).sum() / x_var
        
    return df["close"].rolling(period).apply(slope_func, raw=True)

def simulate_with_dynamic_exit(df, signals, tp_pct=1.8, sl_pct=1.1, timeout_bars=16):
    """
    Yeni Dinamik Takipçi Stop ve Başabaş Mimarisini Simüle Eder:
    - BE @ +0.70% -> SL = +0.12%
    - Ratchet @ +1.20% -> SL = +0.60%
    - Trailing @ +1.60% -> Zirvenin -%0.55 altı
    """
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
            
            # Dinamik Kâr Kilidi
            if mfe_pct >= 0.70:
                be_level = entry_p * 1.0012
                if be_level > curr_sl:
                    curr_sl = be_level
            if mfe_pct >= 1.20:
                lock_level = entry_p * 1.0060
                if lock_level > curr_sl:
                    curr_sl = lock_level
            if mfe_pct >= 1.60:
                trail_level = max_price * 0.9945
                if trail_level > curr_sl:
                    curr_sl = trail_level
                    
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
    gl = abs(sum(losses)) if losses else 0.0001
    pf = gw / gl
    return len(trades), wr, pf, sum(trades)

async def run_lab():
    conn = await asyncpg.connect(DB_URL)
    
    # 18 Coin için 15m verisini hafızaya al
    data_15m = {}
    data_1h = {}
    for sym in TEST_SYMBOLS:
        rows15 = await conn.fetch("SELECT open_time, open, high, low, close, volume FROM historical_candles WHERE symbol=$1 AND timeframe='15m' ORDER BY open_time ASC", sym)
        rows1h = await conn.fetch("SELECT open_time, open, high, low, close, volume FROM historical_candles WHERE symbol=$1 AND timeframe='1h' ORDER BY open_time ASC", sym)
        if len(rows15) >= 300 and len(rows1h) >= 100:
            df15 = pd.DataFrame([dict(r) for r in rows15]).set_index("open_time")
            df1h = pd.DataFrame([dict(r) for r in rows1h]).set_index("open_time")
            data_15m[sym] = df15
            data_1h[sym] = df1h
            
    await conn.close()
    
    # İndikatör hesaplamaları
    features = {}
    for sym, df15 in data_15m.items():
        df1h = data_1h[sym]
        
        # 1h Trend Şemsiyesi
        ema50_1h = calc_ema(df1h["close"], 50).reindex(df15.index, method="ffill")
        ema200_1h = calc_ema(df1h["close"], 200).reindex(df15.index, method="ffill")
        st_1h = calc_supertrend(df1h).reindex(df15.index, method="ffill")
        trend_bull = (df15["close"] > ema200_1h * 0.99) & (st_1h == 1)
        
        # 15m İndikatörleri
        ema20 = calc_ema(df15["close"], 20)
        ema50 = calc_ema(df15["close"], 50)
        st_15m = calc_supertrend(df15)
        stc = calc_stc(df15)
        k, d, j = calc_kdj(df15)
        zl_l, zl_s, zl_hist = calc_zlmacd(df15)
        lr_slope = calc_linreg_slope(df15, 14)
        
        # Hacim & Oynaklık
        vol_avg = df15["volume"].rolling(20).mean()
        high_vol = df15["volume"] >= (vol_avg * 1.35)
        rvol_tod = df15["volume"] >= (vol_avg * 1.5)
        
        # BB Sıkışma
        sma20 = df15["close"].rolling(20).mean()
        std20 = df15["close"].rolling(20).std()
        bbu = sma20 + 2.0 * std20
        bbl = sma20 - 2.0 * std20
        atr = calc_atr(df15, 20)
        kcu = sma20 + 1.5 * atr
        kcl = sma20 - 1.5 * atr
        sq_was = ((bbl.shift(1) > kcl.shift(1)) & (bbu.shift(1) < kcu.shift(1)))
        sq_break = sq_was & (df15["close"] > bbu)
        
        # EMA50 Sekmesi
        ema50_dist = (df15["low"] - ema50).abs() / ema50
        ema_bounce = (ema50_dist <= 0.006) & (df15["close"] > ema50) & (j <= 35) & (j > j.shift(1))
        
        # STC Dip
        stc_dip = (stc.shift(1) <= 25.0) & (stc > 25.0)
        
        # ZLMACD Kesişimi
        zl_cross = (zl_hist.shift(1) <= 0.0) & (zl_hist > 0.0) & (ema20 >= ema50)
        
        # KDJ Dip
        kdj_dip = (j.shift(1) <= 20.0) & (j > j.shift(1)) & (k > d)
        
        # SuperTrend Pullback
        st_pullback = (st_15m == 1) & kdj_dip
        
        # LinReg Eğim Dönüşü
        lr_turn = (lr_slope.shift(1) <= 0) & (lr_slope > 0) & (df15["close"] > ema50)
        
        # Ekstrem Dip (J <= 12)
        extreme_dip = (j <= 12.0) & (j > j.shift(1))
        
        features[sym] = {
            "df": df15,
            "trend_bull": trend_bull,
            "ema_bounce": ema_bounce,
            "sq_break": sq_break,
            "stc_dip": stc_dip,
            "zl_cross": zl_cross,
            "st_pullback": st_pullback,
            "lr_turn": lr_turn,
            "rvol_tod": rvol_tod,
            "extreme_dip": extreme_dip,
            "high_vol": high_vol,
            "kdj_dip": kdj_dip
        }
        
    print("=" * 105)
    print("  📊 BÖLÜM 1: 8 TEKİL STRATEJİNİN AYRI AYRI TEST SONUÇLARI (15M SPOT - DİNAMİK EXIT İLE)")
    print("=" * 105)
    print(f"{'Strateji Adı':<32} | {'İşlem':<8} | {'WinRate %':<12} | {'Profit Factor':<15} | {'Net Kâr %':<12} | {'Karar':<10}")
    print("-" * 105)
    
    single_strategies = [
        ("S1. EMA 50 Sekmesi + KDJ", "ema_bounce"),
        ("S2. BB-KC Sıkışma Kırılımı", "sq_break"),
        ("S3. Schaff Trend Cycle (STC)", "stc_dip"),
        ("S4. Zero-Lag MACD Momentum", "zl_cross"),
        ("S5. SuperTrend Pullback", "st_pullback"),
        ("S6. LinReg Eğim Dönüşü", "lr_turn"),
        ("S7. Zaman-Çapalı RVOL Patlaması", "rvol_tod"),
        ("S8. KDJ Saf Ekstrem Dip (J<=12)", "extreme_dip"),
    ]
    
    for label, feat_key in single_strategies:
        all_tr, all_w, all_gw, all_gl, all_ret = 0, 0, 0.0, 0.0, 0.0
        for sym, f in features.items():
            sig = f[feat_key]
            t, wr, pf, r = simulate_with_dynamic_exit(f["df"], sig, tp_pct=1.8, sl_pct=1.1, timeout_bars=16)
            if t > 0:
                all_tr += t
                all_w += int(round(t * wr / 100.0))
                all_ret += r
                w_rets = [1.8 for _ in range(int(round(t * wr / 100.0)))]
                l_rets = [1.1 for _ in range(t - int(round(t * wr / 100.0)))]
                all_gw += sum(w_rets)
                all_gl += sum(l_rets)
        final_wr = (all_w / all_tr * 100.0) if all_tr > 0 else 0.0
        final_pf = (all_gw / all_gl) if all_gl > 0 else 0.0
        verdict = "✅ ONAY" if final_wr >= 50.0 and all_ret > 0 else ("🟡 NÖTR" if final_wr >= 50.0 else "❌ ZAYIF")
        print(f"{label:<32} | {all_tr:<8d} | %{final_wr:<11.1f} | {final_pf:<15.2f} | %{all_ret:<+11.2f} | {verdict:<10}")
        
    print("\n" + "=" * 105)
    print("  🚀 BÖLÜM 2: STRATEJİLERİN BİRBİRLERİYLE KOMBİNASYONLARI (CONFLUENCE MATRİSİ)")
    print("=" * 105)
    print(f"{'Kombinasyon Adı':<38} | {'İşlem':<8} | {'WinRate %':<12} | {'Profit Factor':<15} | {'Net Kâr %':<12} | {'Kalite':<10}")
    print("-" * 105)
    
    combos = [
        ("C1. BB Sıkışma + Hacim Patlaması", lambda f: f["sq_break"] & f["high_vol"]),
        ("C2. STC Dip + Hacim Patlaması", lambda f: f["stc_dip"] & f["high_vol"]),
        ("C3. ZLMACD + SuperTrend Trend Filtresi", lambda f: f["zl_cross"] & (f["df"]["close"] > calc_ema(f["df"]["close"], 50))),
        ("C4. EMA50 Sekmesi + STC Dip Dönüşü", lambda f: f["ema_bounce"] & (calc_stc(f["df"]) <= 35)),
        ("C5. BB Sıkışma + STC Dip (Çift Onay)", lambda f: f["sq_break"] & (calc_stc(f["df"]) > 25)),
        ("C6. LinReg Eğim + KDJ Dip + Hacim", lambda f: f["lr_turn"] & f["kdj_dip"] & f["high_vol"]),
        ("C7. Makro Trend + BB Sıkışma + Hacim", lambda f: f["trend_bull"] & f["sq_break"] & f["high_vol"]),
        ("C8. Makro Trend + STC Dip + ZLMACD", lambda f: f["trend_bull"] & f["stc_dip"] & (f["zl_cross"] | (calc_zlmacd(f["df"])[2] > 0))),
    ]
    
    for label, sig_gen in combos:
        all_tr, all_w, all_gw, all_gl, all_ret = 0, 0, 0.0, 0.0, 0.0
        for sym, f in features.items():
            sig = sig_gen(f)
            t, wr, pf, r = simulate_with_dynamic_exit(f["df"], sig, tp_pct=1.8, sl_pct=1.1, timeout_bars=16)
            if t > 0:
                all_tr += t
                all_w += int(round(t * wr / 100.0))
                all_ret += r
                w_rets = [1.8 for _ in range(int(round(t * wr / 100.0)))]
                l_rets = [1.1 for _ in range(t - int(round(t * wr / 100.0)))]
                all_gw += sum(w_rets)
                all_gl += sum(l_rets)
        final_wr = (all_w / all_tr * 100.0) if all_tr > 0 else 0.0
        final_pf = (all_gw / all_gl) if all_gl > 0 else 0.0
        quality = "💎 ELİT" if (final_wr >= 55.0 and all_ret > 0) else ("⭐ GÜÇLÜ" if all_ret > 0 else ("🟡 NÖTR" if final_wr >= 50.0 else "❌ ELENDİ"))
        print(f"{label:<38} | {all_tr:<8d} | %{final_wr:<11.1f} | {final_pf:<15.2f} | %{all_ret:<+11.2f} | {quality:<10}")
        
    print("=" * 105)

if __name__ == "__main__":
    asyncio.run(run_lab())
