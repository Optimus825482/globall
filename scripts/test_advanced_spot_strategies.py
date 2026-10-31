"""
Binance TR Spot Varlıklar İçin Gelişmiş Gösterge ve Strateji Kombinasyonları Test Laboratuvarı
Test Edilen 7 Farklı Strateji Kombinasyonu:
1. KDJ Dip + EMA 50 Bounce (Mevcut Şampiyon)
2. SuperTrend + WaveTrend (WT) Dip Kesişimi
3. Bollinger Bant Sıkışması + VWAP Kırılımı
4. KDJ + RSI Çift Osilatör Dip Confluence
5. Zero-Lag MACD + EMA 20/50 Altın Momentum
6. Schaff Trend Cycle (STC) + ATR Trailing Stop
7. Fisher Transform + Donchian Kanalı Sıçraması
"""
import sys
import json
import time
import math
import numpy as np
import pandas as pd
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

SPOT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT",
    "DOTUSDT", "DOGEUSDT", "PEPEUSDT", "SHIBUSDT", "OPUSDT"
]

COMMISSION_RATE = 0.0004 # %0.04 standart Binance TR spot komisyonu

def fetch_binance_klines(symbol: str, interval: str = "5m", limit: int = 1000) -> pd.DataFrame:
    """Binance Public API'den geçmiş mumları çeker."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    
    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"
    ])
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df[["time", "open", "high", "low", "close", "volume"]]

# ─── TEKNİK GÖSTERGE YARDIMCILARI ──────────────────────────────────────────────

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))

def calc_kdj(df: pd.DataFrame, period: int = 9, signal: int = 3):
    low_min = df["low"].rolling(period).min()
    high_max = df["high"].rolling(period).max()
    rsv = ((df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)) * 100.0
    rsv = rsv.fillna(50.0)
    
    k = pd.Series(50.0, index=df.index)
    d = pd.Series(50.0, index=df.index)
    alpha = 1.0 / signal
    
    k_vals = [50.0]
    d_vals = [50.0]
    rsv_vals = rsv.values
    for r in rsv_vals:
        k_val = (1.0 - alpha) * k_vals[-1] + alpha * r
        d_val = (1.0 - alpha) * d_vals[-1] + alpha * k_val
        k_vals.append(k_val)
        d_vals.append(d_val)
    
    k_series = pd.Series(k_vals[1:], index=df.index)
    d_series = pd.Series(d_vals[1:], index=df.index)
    j_series = 3.0 * k_series - 2.0 * d_series
    return k_series, d_series, j_series

def calc_supertrend(df: pd.DataFrame, period: int = 10, factor: float = 3.0):
    atr = calc_atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2.0
    upper_basic = hl2 + (factor * atr)
    lower_basic = hl2 - (factor * atr)
    
    upper_band = upper_basic.copy()
    lower_band = lower_basic.copy()
    direction = pd.Series(1, index=df.index)
    
    c = df["close"].to_numpy().copy()
    ub = upper_basic.to_numpy().copy()
    lb = lower_basic.to_numpy().copy()
    dir_arr = np.ones(len(df))
    
    for i in range(1, len(df)):
        if np.isnan(atr.iloc[i]):
            continue
        if lb[i] > lb[i-1] or c[i-1] < lb[i-1]:
            lb[i] = lb[i]
        else:
            lb[i] = lb[i-1]
            
        if ub[i] < ub[i-1] or c[i-1] > ub[i-1]:
            ub[i] = ub[i]
        else:
            ub[i] = ub[i-1]
            
        if dir_arr[i-1] == 1:
            if c[i] < lb[i]:
                dir_arr[i] = -1
            else:
                dir_arr[i] = 1
        else:
            if c[i] > ub[i]:
                dir_arr[i] = 1
            else:
                dir_arr[i] = -1
                
    return pd.Series(dir_arr, index=df.index)

def calc_wavetrend(df: pd.DataFrame, n1: int = 10, n2: int = 21):
    ap = (df["high"] + df["low"] + df["close"]) / 3.0
    esa = ap.ewm(span=n1, adjust=False).mean()
    d = (ap - esa).abs().ewm(span=n1, adjust=False).mean()
    ci = (ap - esa) / (0.015 * d.replace(0, np.nan))
    tci = ci.ewm(span=n2, adjust=False).mean()
    wt1 = tci
    wt2 = wt1.rolling(4).mean()
    return wt1, wt2

def calc_bollinger_vwap(df: pd.DataFrame, period: int = 20, mult: float = 2.0):
    sma = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    upper = sma + (mult * std)
    lower = sma - (mult * std)
    bandwidth = (upper - lower) / sma
    
    cum_vol = df["volume"].cumsum()
    cum_vp = (df["close"] * df["volume"]).cumsum()
    vwap = cum_vp / cum_vol.replace(0, np.nan)
    return upper, lower, bandwidth, vwap

def calc_zlmacd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
    # Zero Lag EMA
    def zlema(s, p):
        lag = int((p - 1) / 2)
        return (s + (s - s.shift(lag))).ewm(span=p, adjust=False).mean()
    
    zl_fast = zlema(df["close"], fast)
    zl_slow = zlema(df["close"], slow)
    zl_macd = zl_fast - zl_slow
    zl_signal = zl_macd.ewm(span=signal, adjust=False).mean()
    zl_hist = zl_macd - zl_signal
    return zl_macd, zl_signal, zl_hist

def calc_stc(df: pd.DataFrame, period: int = 10, fast: int = 23, slow: int = 50):
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

def calc_fisher(df: pd.DataFrame, period: int = 10):
    med = (df["high"] + df["low"]) / 2.0
    med_min = med.rolling(period).min()
    med_max = med.rolling(period).max()
    raw = ((med - med_min) / (med_max - med_min).replace(0, np.nan)).fillna(0.5)
    raw = 0.66 * (2.0 * raw - 1.0) + 0.33 * 0.0 # simple smooth
    raw = raw.clip(-0.999, 0.999)
    fish = 0.5 * np.log((1.0 + raw) / (1.0 - raw))
    fish = fish.ewm(span=5, adjust=False).mean()
    return fish

# ─── GERİYE DÖNÜK TEST SİMÜLATÖRÜ (BACKTEST ENGINE) ───────────────────────────

def simulate_spot_strategy(df: pd.DataFrame, signals: pd.Series, tp_pct: float = 2.0, sl_pct: float = 1.2):
    """
    Spot simülasyonu: 1 sinyal varken işlem açılır, TP/SL veya max 48 bar sonra kapanır.
    Komisyon: Giriş + çıkış toplam %0.08 spot kesintisi.
    """
    trades = []
    in_pos = False
    entry_p = 0.0
    entry_idx = 0
    
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    sig_arr = signals.values
    
    for i in range(len(df)):
        if not in_pos and sig_arr[i]:
            in_pos = True
            entry_p = closes[i]
            entry_idx = i
        elif in_pos:
            target_p = entry_p * (1.0 + (tp_pct / 100.0))
            stop_p = entry_p * (1.0 - (sl_pct / 100.0))
            
            # Bar içi tepe/dip kontrolü
            hit_tp = highs[i] >= target_p
            hit_sl = lows[i] <= stop_p
            time_exit = (i - entry_idx) >= 48 # 48 bar timeout
            
            if hit_tp or hit_sl or time_exit:
                exit_p = target_p if hit_tp else (stop_p if hit_sl else closes[i])
                gross_ret = ((exit_p - entry_p) / entry_p) * 100.0
                net_ret = gross_ret - (COMMISSION_RATE * 200.0) # net komisyon düşülmüş %
                trades.append({
                    "entry_p": entry_p,
                    "exit_p": exit_p,
                    "ret_pct": net_ret,
                    "win": net_ret > 0,
                    "bars": i - entry_idx
                })
                in_pos = False
                
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "total_return": 0.0, "profit_factor": 0.0, "max_dd": 0.0}
        
    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    win_rate = (len(wins) / len(trades)) * 100.0
    total_ret = sum(t["ret_pct"] for t in trades)
    
    gross_gains = sum(t["ret_pct"] for t in wins) if wins else 0.0
    gross_losses = abs(sum(t["ret_pct"] for t in losses)) if losses else 0.001
    profit_factor = gross_gains / gross_losses
    
    # Drawdown
    equity = [0.0]
    for t in trades:
        equity.append(equity[-1] + t["ret_pct"])
    peak = -999999
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd:
            max_dd = dd
            
    return {
        "trades": len(trades),
        "win_rate": round(win_rate, 1),
        "total_return": round(total_ret, 2),
        "profit_factor": round(profit_factor, 2),
        "max_dd": round(max_dd, 2)
    }

# ─── 7 STRATEJİ SİNYAL ÜRETİCİLERİ ─────────────────────────────────────────────

def generate_signals(df: pd.DataFrame, strat_name: str, tf: str) -> pd.Series:
    close = df["close"]
    signals = pd.Series(False, index=df.index)
    
    if strat_name == "KDJ_EMA50":
        # 1. KDJ Dip Sıçraması + EMA 50 Desteği
        k, d, j = calc_kdj(df, 9, 3)
        ema50 = calc_ema(close, 50)
        dist_ema = (close - ema50) / ema50
        dip = (j.shift(1) <= 15.0) & (j > d) & (j.shift(1) <= d.shift(1))
        at_ema = (dist_ema >= -0.012) & (dist_ema <= 0.015) & (close >= ema50 * 0.99)
        signals = dip & at_ema

    elif strat_name == "SUPERTREND_WAVETREND":
        # 2. SuperTrend Boğada WaveTrend Dip Kesişimi
        st = calc_supertrend(df, 10, 3.0)
        wt1, wt2 = calc_wavetrend(df, 10, 21)
        wt_cross = (wt1.shift(1) <= wt2.shift(1)) & (wt1 > wt2) & (wt1.shift(1) <= -40.0)
        signals = (st == 1) & wt_cross

    elif strat_name == "BOLLINGER_VWAP_EXPANSION":
        # 3. Bollinger Alt Bant Sıçraması + VWAP Kırılımı
        upper, lower, bw, vwap = calc_bollinger_vwap(df, 20, 2.0)
        bounce_lower = (df["low"].shift(1) <= lower.shift(1)) & (close > lower)
        cross_vwap = (close.shift(1) <= vwap.shift(1)) & (close > vwap)
        signals = bounce_lower | (cross_vwap & (close > vwap))

    elif strat_name == "KDJ_RSI_CONFLUENCE":
        # 4. KDJ + RSI Çift Aşırı Satım Dip Confluence
        k, d, j = calc_kdj(df, 9, 3)
        rsi = calc_rsi(close, 14)
        j_dip = (j.shift(1) <= 18.0) & (j > j.shift(1))
        rsi_dip = (rsi <= 35.0)
        signals = j_dip & rsi_dip

    elif strat_name == "ZLMACD_EMA_MOMENTUM":
        # 5. Zero-Lag MACD Sıfır Kesişimi + EMA 20/50 Trend
        macd, sig, hist = calc_zlmacd(df, 12, 26, 9)
        ema20 = calc_ema(close, 20)
        ema50 = calc_ema(close, 50)
        zl_up = (hist.shift(1) <= 0) & (hist > 0)
        trend_bull = ema20 >= ema50
        signals = zl_up & trend_bull

    elif strat_name == "STC_SCHAFF_CYCLE":
        # 6. Schaff Trend Cycle (STC) Dip Dönüşü
        stc = calc_stc(df, 10, 23, 50)
        stc_up = (stc.shift(1) <= 25.0) & (stc > 25.0)
        signals = stc_up

    elif strat_name == "FISHER_DONCHIAN":
        # 7. Fisher Transform Ekstrem Dip + Donchian Sıçraması
        fish = calc_fisher(df, 10)
        fish_up = (fish.shift(1) <= -1.2) & (fish > fish.shift(1))
        signals = fish_up

    return signals.fillna(False)

# ─── ANA ÇALIŞTIRMA VE TEST MATRİSİ ──────────────────────────────────────────

def run_all_tests():
    print("=" * 80)
    print("  🚀 BINANCE TR SPOT YENİ GÖSTERGE & STRATEJİ KOMBİNASYONLARI LABORATUVARI")
    print("=" * 80)
    print(f"Test Edilen Coinler ({len(SPOT_SYMBOLS)}): {', '.join(SPOT_SYMBOLS)}")
    print("Zaman Dilimleri: 5m ve 15m")
    print("Komisyon: %0.04 (Maker/Taker spot kesintisi dahil)")
    print("-" * 80 + "\n")
    
    STRATEGIES_TO_TEST = [
        ("KDJ_EMA50", "KDJ Dip + EMA 50 Desteği"),
        ("SUPERTREND_WAVETREND", "SuperTrend Boğa + WaveTrend Dip"),
        ("BOLLINGER_VWAP_EXPANSION", "Bollinger Sıkışması + VWAP Kırılımı"),
        ("KDJ_RSI_CONFLUENCE", "KDJ + RSI Çift Dip Confluence"),
        ("ZLMACD_EMA_MOMENTUM", "Zero-Lag MACD + EMA20/50 Momentum"),
        ("STC_SCHAFF_CYCLE", "Schaff Trend Cycle (STC 25 Kırılımı)"),
        ("FISHER_DONCHIAN", "Fisher Transform Dip Sıçraması"),
    ]
    
    all_results = []
    
    for tf, (tp, sl) in [("5m", (2.0, 1.2)), ("15m", (3.0, 1.8))]:
        print(f"\n==================== [ZAMAN DİLİMİ: {tf} | TP: %{tp} | SL: %{sl}] ====================")
        for sym in SPOT_SYMBOLS:
            try:
                df = fetch_binance_klines(sym, interval=tf, limit=1000)
                if len(df) < 200:
                    continue
            except Exception as e:
                print(f"⚠️ {sym} veri çekilemedi: {e}")
                continue
                
            for strat_code, strat_name in STRATEGIES_TO_TEST:
                sigs = generate_signals(df, strat_code, tf)
                sig_count = sigs.sum()
                if sig_count < 2:
                    continue
                    
                perf = simulate_spot_strategy(df, sigs, tp_pct=tp, sl_pct=sl)
                if perf["trades"] >= 3:
                    res_item = {
                        "symbol": sym,
                        "timeframe": tf,
                        "strategy_code": strat_code,
                        "strategy_name": strat_name,
                        "trades": perf["trades"],
                        "win_rate": perf["win_rate"],
                        "total_return": perf["total_return"],
                        "profit_factor": perf["profit_factor"],
                        "max_dd": perf["max_dd"]
                    }
                    all_results.append(res_item)
                    
    # Sonuçları Kâr ve Başarı Oranına Göre Sırala
    df_res = pd.DataFrame(all_results)
    if df_res.empty:
        print("Sonuç üretilemedi.")
        return
        
    print("\n" + "=" * 90)
    print("                    🏆 EN İYİ 15 STRATEJİ & COIN KOMBİNASYONU (KÂRLILIK SIRALI)")
    print("=" * 90)
    top_picks = df_res.sort_values(by="total_return", ascending=False).head(15)
    
    fmt = "{:<8} {:<5} {:<32} {:<8} {:<10} {:<12} {:<8} {:<8}"
    print(fmt.format("Sembol", "TF", "Strateji Kombinasyonu", "İşlem", "Win Rate", "Net Kâr (%)", "PF", "Max DD"))
    print("-" * 90)
    for _, row in top_picks.iterrows():
        sign = "+" if row["total_return"] > 0 else ""
        print(fmt.format(
            row["symbol"],
            row["timeframe"],
            row["strategy_name"][:32],
            row["trades"],
            f"%{row['win_rate']:.1f}",
            f"{sign}%{row['total_return']:.2f}",
            f"{row['profit_factor']:.2f}",
            f"%{row['max_dd']:.2f}"
        ))
        
    print("\n" + "=" * 90)
    print("             📊 STRATEJİLERİN GENEL ORTALAMA PERFORMANSI (TÜM COİNLERDE)")
    print("=" * 90)
    strat_summary = df_res.groupby("strategy_name").agg({
        "trades": "sum",
        "win_rate": "mean",
        "total_return": "mean",
        "profit_factor": "mean",
        "max_dd": "mean"
    }).sort_values(by="win_rate", ascending=False)
    
    fmt_s = "{:<35} {:<10} {:<12} {:<14} {:<10}"
    print(fmt_s.format("Strateji", "Top. İşlem", "Ort. WinRate", "Ort. Net Kâr", "Ort. PF"))
    print("-" * 90)
    for strat, row in strat_summary.iterrows():
        sign = "+" if row["total_return"] > 0 else ""
        print(fmt_s.format(
            strat[:35],
            int(row["trades"]),
            f"%{row['win_rate']:.1f}",
            f"{sign}%{row['total_return']:.2f}",
            f"{row['profit_factor']:.2f}"
        ))

    # Sonuçları JSON'a kaydet
    out_file = Path("outputs/spot_new_strategies_benchmark.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Tüm detaylı test logları '{out_file}' dosyasına kaydedildi!")

if __name__ == "__main__":
    run_all_tests()
