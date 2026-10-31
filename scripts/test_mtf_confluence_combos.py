"""
Binance Spot MTF Confluence & Kombinasyon Laboratuvarı.
Yerel PostgreSQL `historical_candles` tablosundaki verileri okur.
3 Katmanlı MTF (1h Trend + 15m Dip + 5m Tetik) ve Akıllı Kâr Kilitleme (Breakeven)
modellerini geriye dönük test eder ve karşılaştırmalı quant raporu sunar.
"""
import sys
import json
import time
import asyncio
import asyncpg
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

DB_URL = "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"
COMMISSION_RATE = 0.0004 # %0.04 Maker / %0.04 Taker spot komisyonu

TEST_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "NEARUSDT", "DOGEUSDT",
    "PEPEUSDT", "BNBUSDT", "XRPUSDT", "LINKUSDT", "SHIBUSDT", "ADAUSDT",
    "DOTUSDT", "RENDERUSDT", "FETUSDT", "ARBUSDT", "OPUSDT", "INJUSDT"
]

# ─── TEKNİK İNDİKATÖR FONKSİYONLARI ──────────────────────────────────────────

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_supertrend(df: pd.DataFrame, period: int = 10, factor: float = 3.0) -> pd.Series:
    atr = calc_atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2.0
    upper_basic = hl2 + (factor * atr)
    lower_basic = hl2 - (factor * atr)
    
    c = df["close"].to_numpy().copy()
    ub = upper_basic.to_numpy().copy()
    lb = lower_basic.to_numpy().copy()
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

def calc_stc(df: pd.DataFrame, period: int = 10, fast: int = 23, slow: int = 50) -> pd.Series:
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
    stc = stoch2.ewm(alpha=0.5, adjust=False).mean()
    return stc

def calc_zlmacd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
    def zlema(series, p):
        lag = int((p - 1) / 2)
        diff = series - series.shift(lag)
        return calc_ema(series + diff, p)
    
    zl_fast = zlema(df["close"], fast)
    zl_slow = zlema(df["close"], slow)
    zl_macd = zl_fast - zl_slow
    zl_signal = calc_ema(zl_macd, signal)
    zl_hist = zl_macd - zl_signal
    return zl_macd, zl_signal, zl_hist

def calc_kdj(df: pd.DataFrame, period: int = 9, signal: int = 3):
    low_min = df["low"].rolling(period).min()
    high_max = df["high"].rolling(period).max()
    rsv = ((df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)) * 100.0
    rsv = rsv.fillna(50.0)
    alpha = 1.0 / signal
    
    k_vals = [50.0]
    d_vals = [50.0]
    for r in rsv.values:
        k_val = (1.0 - alpha) * k_vals[-1] + alpha * r
        d_val = (1.0 - alpha) * d_vals[-1] + alpha * k_val
        k_vals.append(k_val)
        d_vals.append(d_val)
        
    k_series = pd.Series(k_vals[1:], index=df.index)
    d_series = pd.Series(d_vals[1:], index=df.index)
    j_series = 3.0 * k_series - 2.0 * d_series
    return k_series, d_series, j_series

def calc_squeeze(df: pd.DataFrame, bb_period: int = 20, bb_mult: float = 2.0, kc_period: int = 20, kc_mult: float = 1.5):
    sma = df["close"].rolling(bb_period).mean()
    std = df["close"].rolling(bb_period).std()
    bb_upper = sma + (bb_mult * std)
    bb_lower = sma - (bb_mult * std)
    
    atr = calc_atr(df, kc_period)
    kc_upper = sma + (kc_mult * atr)
    kc_lower = sma - (kc_mult * atr)
    
    # Sıkışma: BB Keltner'in içinde
    is_squeeze = (bb_lower > kc_lower) & (bb_upper < kc_upper)
    return is_squeeze, bb_upper, bb_lower

# ─── VERİTABANINDAN YÜKLEME ──────────────────────────────────────────────────

async def load_candles_from_db(conn, symbol: str, timeframe: str) -> pd.DataFrame:
    rows = await conn.fetch("""
        SELECT open_time, open, high, low, close, volume, quote_volume
        FROM historical_candles
        WHERE symbol = $1 AND timeframe = $2
        ORDER BY open_time ASC
    """, symbol, timeframe)
    
    if not rows:
        return pd.DataFrame()
        
    df = pd.DataFrame([dict(r) for r in rows])
    df["time"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("time", inplace=True)
    return df

# ─── GELİŞMİŞ SİMÜLASYON MOTORU (BREAKEVEN & DİNAMİK TP KORUMALI) ─────────────

def simulate_combo_strategy(
    df: pd.DataFrame,
    signals: pd.Series,
    tp_pct: float = 1.5,
    sl_pct: float = 0.9,
    use_breakeven: bool = False,
    be_trigger_pct: float = 0.50, # Kâr bu eşiğe ulaşınca stop giriş+komisyona çekilir
    timeout_bars: int = 12
) -> dict:
    trades = []
    in_pos = False
    entry_p = 0.0
    entry_idx = 0
    current_sl = 0.0
    be_activated = False
    
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
            current_sl = entry_p * (1.0 - (sl_pct / 100.0))
            be_activated = False
        elif in_pos:
            target_p = entry_p * (1.0 + (tp_pct / 100.0))
            max_gain_pct = ((highs[i] - entry_p) / entry_p) * 100.0
            
            # ─── BREAKEVEN / KÂR KORUMA KONTROLÜ ───
            if use_breakeven and not be_activated and max_gain_pct >= be_trigger_pct:
                # Stop seviyesini giriş fiyatı + %0.10 (komisyon kurtarma) seviyesine taşı
                current_sl = entry_p * 1.0010
                be_activated = True
                
            hit_tp = highs[i] >= target_p
            hit_sl = lows[i] <= current_sl
            time_exit = (i - entry_idx) >= timeout_bars
            
            if hit_tp or hit_sl or time_exit:
                exit_p = target_p if hit_tp else (current_sl if hit_sl else closes[i])
                gross_ret = ((exit_p - entry_p) / entry_p) * 100.0
                net_ret = gross_ret - (COMMISSION_RATE * 200.0) # round-trip komisyon
                trades.append({
                    "entry_p": entry_p,
                    "exit_p": exit_p,
                    "ret_pct": net_ret,
                    "win": net_ret > 0,
                    "be_saved": be_activated and not hit_tp,
                    "exit_reason": "TP" if hit_tp else ("SL_BE" if be_activated else ("SL" if hit_sl else "TIMEOUT")),
                    "bars": i - entry_idx
                })
                in_pos = False
                
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "total_return": 0.0, "profit_factor": 0.0, "be_saved": 0}
        
    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    win_rate = (len(wins) / len(trades)) * 100.0
    total_ret = sum(t["ret_pct"] for t in trades)
    gross_gains = sum(t["ret_pct"] for t in wins) if wins else 0.0
    gross_losses = abs(sum(t["ret_pct"] for t in losses)) if losses else 0.001
    profit_factor = gross_gains / gross_losses
    be_saved = len([t for t in trades if t["be_saved"]])
    
    return {
        "trades": len(trades),
        "win_rate": round(win_rate, 1),
        "total_return": round(total_ret, 2),
        "profit_factor": round(profit_factor, 2),
        "be_saved": be_saved
    }

# ─── ANA TEST VE KOMBİNASYON MATRİSİ ─────────────────────────────────────────

async def run_matrix():
    conn = await asyncpg.connect(DB_URL)
    print("=" * 85)
    print("  🚀 SPOT MTF KOMBİNASYON & AKILLI KÂR KİLİTLEME (BREAKEVEN) LABORATUVARI")
    print("=" * 85)
    print(f"Veri Kaynağı: Yerel PostgreSQL (historical_candles)")
    print(f"Test Edilen Varlıklar ({len(TEST_SYMBOLS)}): {', '.join(TEST_SYMBOLS[:6])}... ({len(TEST_SYMBOLS)} coin)")
    print("Maliyet: %0.08 Round-trip spot komisyonu düşülmüş NET kârlar")
    print("-" * 85)
    
    models = [
        {"name": "1. Mevcut Sistem (Sabit TP/SL, BE Yok)", "tp": 1.5, "sl": 0.9, "be": False, "be_trig": 0.5},
        {"name": "2. Akıllı Kâr Kilitleme (+%0.5'te Stop=BE)", "tp": 1.5, "sl": 0.9, "be": True, "be_trig": 0.50},
        {"name": "3. Gerçekçi Erken Scalp (+%0.9 TP / +%0.4 BE)", "tp": 0.9, "sl": 0.7, "be": True, "be_trig": 0.40},
        {"name": "4. MTF Trend-Cycle Confluence (1h Trend + 15m STC + 5m ZLMACD)", "tp": 1.2, "sl": 0.8, "be": True, "be_trig": 0.50}
    ]
    
    results_by_model = {m["name"]: [] for m in models}
    
    for sym in TEST_SYMBOLS:
        df5 = await load_candles_from_db(conn, sym, "5m")
        df15 = await load_candles_from_db(conn, sym, "15m")
        df1h = await load_candles_from_db(conn, sym, "1h")
        
        if len(df5) < 500 or len(df15) < 200:
            continue
            
        # 5m İndikatörler
        c5 = df5["close"]
        ema50_5 = calc_ema(c5, 50)
        _, _, zl_hist5 = calc_zlmacd(df5)
        stc5 = calc_stc(df5)
        _, _, j5 = calc_kdj(df5)
        
        # 15m İndikatörler
        stc15 = calc_stc(df15).reindex(df5.index, method="ffill")
        ema50_15 = calc_ema(df15["close"], 50).reindex(df5.index, method="ffill")
        
        # 1h Trend Filtresi
        st_1h = calc_supertrend(df1h).reindex(df5.index, method="ffill") if len(df1h) > 50 else pd.Series(1, index=df5.index)
        ema200_1h = calc_ema(df1h["close"], 200).reindex(df5.index, method="ffill") if len(df1h) > 200 else c5
        macro_bull = (df5["close"] > ema200_1h * 0.99) & (st_1h == 1)
        
        # Sinyal 1: Standart ZLMACD
        sig_zlmacd = (zl_hist5.shift(1) <= 0) & (zl_hist5 > 0)
        
        # Sinyal 4: 3-Katmanlı MTF Confluence (1h Boğa + 15m STC Dip + 5m ZLMACD Tetik)
        sig_mtf_confluence = macro_bull & (stc15 <= 35.0) & sig_zlmacd
        
        # Simülasyonları çalıştır
        res1 = simulate_combo_strategy(df5, sig_zlmacd, tp_pct=1.5, sl_pct=0.9, use_breakeven=False, timeout_bars=12)
        res2 = simulate_combo_strategy(df5, sig_zlmacd, tp_pct=1.5, sl_pct=0.9, use_breakeven=True, be_trigger_pct=0.50, timeout_bars=12)
        res3 = simulate_combo_strategy(df5, sig_zlmacd, tp_pct=0.9, sl_pct=0.7, use_breakeven=True, be_trigger_pct=0.40, timeout_bars=12)
        res4 = simulate_combo_strategy(df5, sig_mtf_confluence, tp_pct=1.2, sl_pct=0.8, use_breakeven=True, be_trigger_pct=0.50, timeout_bars=16)
        
        results_by_model[models[0]["name"]].append(res1)
        results_by_model[models[1]["name"]].append(res2)
        results_by_model[models[2]["name"]].append(res3)
        results_by_model[models[3]["name"]].append(res4)
        
    await conn.close()
    
    print("\n" + "=" * 85)
    print("  📊 MODEL KARŞILAŞTIRMA ÖZETİ (TÜM COINLER GENELİNDE ORTALAMA METRİKLER)")
    print("=" * 85)
    print(f"{'Model Adı':<48} | {'İşlem':<6} | {'Win Rate':<10} | {'PF':<6} | {'Net Kâr':<10}")
    print("-" * 85)
    
    for m in models:
        name = m["name"]
        items = results_by_model[name]
        if not items:
            continue
        tot_trades = sum(it["trades"] for it in items)
        avg_wr = sum(it["win_rate"] for it in items) / len(items) if items else 0.0
        avg_pf = sum(it["profit_factor"] for it in items) / len(items) if items else 0.0
        tot_net = sum(it["total_return"] for it in items)
        tot_be = sum(it["be_saved"] for it in items)
        print(f"{name:<48} | {tot_trades:<6d} | %{avg_wr:<9.1f} | {avg_pf:<6.2f} | %{tot_net:<9.2f}")
    print("=" * 85)

if __name__ == "__main__":
    asyncio.run(run_matrix())
