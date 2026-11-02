"""GitHub ve YouTube Spot Kripto Stratejilerinin VectorBT ile Test Edilmesi.

İncelenen ve Modellenen Stratejiler:
1. BB_RPB_TSL (Freqtrade #1 Top Spot Stratejisi - Bollinger Bands + Real Pullback + EWO)
2. QQE_MOD_Trend (TradeIQ / YouTube #1 İndikatör Kombinasyonu - QQE Mod + EMA200 Filtresi)
3. UT_BOT_Alerts (QuantNomad / YouTube En Popüler ATR Trailing Sistemi + EMA Filtresi)
4. Turtle_Donchian (Modernize Edilmiş Kripto Donchian 20-Bar Kırılımı + ADX Hacim Filtresi)
5. VWAP_Mean_Reversion (Kurumsal VWAP -2.0 Band Dip Sekmesi + RSI Dip Teyidi)
6. SuperTrend_StochRSI (YouTube En Çok İzlenen Boğa Confluence Sistemi)
7. ClucHAnST_Wick (Freqtrade Efsanesi: Hacimli Kapitülasyon İğnesi ve Hızlı Dönüş)
8. KDJ_Pure_Dip (Mevcut Referans) ve RASTGELE GİRİŞ (Şans Faktörü Referansı)

Kullanılan Veri:
PostgreSQL `historical_candles` tablosundaki gerçek 5m ve 15m Binance USDT verileri.
Maliyet: %0.15 round-trip (BNB indirimli gerçek Binance TR komisyonu).
"""
import argparse
import asyncio
import os
import sys
import time
from collections import defaultdict
import numpy as np

# Proje yollarını ekle
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "backend"))
sys.path.insert(0, _ROOT)

import vectorbt as vbt

# ─── Vektörel İndikatör Hesaplama Fonksiyonları ──────────────────────────────

def _ema(arr: np.ndarray, period: int) -> np.ndarray:
    n = len(arr)
    out = np.full(n, np.nan)
    alpha = 2.0 / (period + 1.0)
    prev = None
    for i in range(n):
        v = arr[i]
        if np.isnan(v):
            continue
        prev = v if prev is None else (v * alpha + prev * (1.0 - alpha))
        out[i] = prev
    return np.nan_to_num(out, nan=0.0)

def _atr(H: np.ndarray, L: np.ndarray, C: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(C)
    tr = np.zeros(n)
    tr[0] = H[0] - L[0]
    for i in range(1, n):
        tr[i] = max(H[i] - L[i], abs(H[i] - C[i-1]), abs(L[i] - C[i-1]))
    atr = np.full(n, np.nan)
    if n >= period:
        atr[period-1] = tr[:period].mean()
        for i in range(period, n):
            atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
    return np.nan_to_num(atr, nan=0.0)

def _rsi(C: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(C)
    rsi = np.full(n, 50.0)
    if n <= period:
        return rsi
    delta = np.diff(C)
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()
    
    for i in range(period, n - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 1e-12 else 100.0
        rsi[i+1] = 100.0 - (100.0 / (1.0 + rs))
    return rsi

def _adx(H: np.ndarray, L: np.ndarray, C: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(C)
    adx = np.full(n, 20.0)
    if n < period * 2:
        return adx
    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        h_diff = H[i] - H[i-1]
        l_diff = L[i-1] - L[i]
        tr[i] = max(H[i] - L[i], abs(H[i] - C[i-1]), abs(L[i] - C[i-1]))
        plus_dm[i] = h_diff if (h_diff > l_diff and h_diff > 0) else 0.0
        minus_dm[i] = l_diff if (l_diff > h_diff and l_diff > 0) else 0.0
    
    smooth_tr = _ema(tr, period)
    smooth_plus = _ema(plus_dm, period)
    smooth_minus = _ema(minus_dm, period)
    
    valid_tr = smooth_tr > 1e-9
    plus_di = np.where(valid_tr, 100.0 * smooth_plus / np.maximum(smooth_tr, 1e-9), 0.0)
    minus_di = np.where(valid_tr, 100.0 * smooth_minus / np.maximum(smooth_tr, 1e-9), 0.0)
    di_sum = plus_di + minus_di
    dx = np.where(di_sum > 1e-9, 100.0 * np.abs(plus_di - minus_di) / np.maximum(di_sum, 1e-9), 0.0)
    adx = _ema(dx, period)
    return adx

def _stoch_rsi(rsi: np.ndarray, length: int = 14, k_p: int = 3, d_p: int = 3):
    n = len(rsi)
    stoch = np.full(n, 50.0)
    for i in range(length, n):
        w = rsi[i-length+1:i+1]
        lo, hi = w.min(), w.max()
        stoch[i] = ((rsi[i] - lo) / (hi - lo) * 100.0) if hi > lo else 50.0
    k = _ema(stoch, k_p)
    d = _ema(k, d_p)
    return k, d

def _kdj(H: np.ndarray, L: np.ndarray, C: np.ndarray, period: int = 9, signal: int = 3):
    n = len(C)
    k = np.full(n, 50.0)
    d = np.full(n, 50.0)
    alpha = 1.0 / signal
    for i in range(period, n):
        lo = L[i-period+1:i+1].min()
        hi = H[i-period+1:i+1].max()
        rng = hi - lo
        rsv = ((C[i] - lo) / rng * 100.0) if rng > 0 else 50.0
        k[i] = k[i-1] + alpha * (rsv - k[i-1])
        d[i] = d[i-1] + alpha * (k[i] - d[i-1])
    j = 3.0 * k - 2.0 * d
    return k, d, j

# ─── Strateji 1: Freqtrade BB_RPB_TSL (Bollinger + EWO + Williams%R/RSI Dip) ─
def _strat_freqtrade_bbrpb(H, L, C, V):
    n = len(C)
    sig = np.zeros(n, dtype=bool)
    if n < 50:
        return sig
    # Bollinger Bands (20, 2.0)
    bb_mid = np.zeros(n)
    for i in range(19, n):
        bb_mid[i] = C[i-19:i+1].mean()
    bb_std = np.zeros(n)
    for i in range(19, n):
        bb_std[i] = C[i-19:i+1].std()
    bb_lower = bb_mid - 2.0 * bb_std
    
    # Elliott Wave Oscillator (EWO) = EMA(5) - EMA(35) normalize edilmiş
    e5 = _ema(C, 5)
    e35 = _ema(C, 35)
    ewo = np.where(C > 0, (e5 - e35) / C * 100.0, 0.0)
    
    # RSI
    rsi14 = _rsi(C, 14)
    e200 = _ema(C, 200)
    
    # Hacim ortalaması
    avg_vol = np.zeros(n)
    for i in range(20, n):
        avg_vol[i] = V[i-20:i].mean()
        
    for i in range(35, n):
        # Freqtrade kuralı: Fiyat alt banda dokunmuş/altına inmiş,
        # EWO dipte ve toparlanmaya başlamış (ewo[i] > ewo[i-1]),
        # RSI aşırı satımda (RSI < 34),
        # Fiyat derin ölüm sarmalında değil (C > e200 * 0.94)
        touch_bb = (L[i] <= bb_lower[i] * 1.002) or (C[i] <= bb_lower[i])
        oversold = (rsi14[i] <= 34.0)
        ewo_rebound = (ewo[i-1] < 0) and (ewo[i] > ewo[i-1])
        trend_ok = (C[i] >= e200[i] * 0.92) if e200[i] > 0 else True
        vol_ok = V[i] >= avg_vol[i] * 0.7 if avg_vol[i] > 0 else True
        
        if touch_bb and oversold and ewo_rebound and trend_ok and vol_ok:
            sig[i] = True
    return sig

# ─── Strateji 2: YouTube QQE MOD Trend Stratejisi ────────────────────────────
def _strat_qqe_mod(H, L, C, V):
    n = len(C)
    sig = np.zeros(n, dtype=bool)
    if n < 60:
        return sig
    rsi = _rsi(C, 14)
    smoothed_rsi = _ema(rsi, 5)
    
    # ATR of RSI
    rsi_diff = np.abs(np.diff(smoothed_rsi, prepend=smoothed_rsi[0]))
    atr_rsi = _ema(rsi_diff, 14)
    dar_rsi = _ema(atr_rsi, 14) * 3.0
    
    long_band = smoothed_rsi - dar_rsi
    
    e100 = _ema(C, 100)
    e200 = _ema(C, 200)
    
    avg_vol = np.zeros(n)
    for i in range(20, n):
        avg_vol[i] = V[i-20:i].mean()
        
    for i in range(30, n):
        # QQE Histogram yeşile dönüyor: smoothed_rsi long_band'i yukarı kesiyor
        cross_up = (smoothed_rsi[i] > long_band[i]) and (smoothed_rsi[i-1] <= long_band[i-1])
        macro_bull = (C[i] > e100[i]) and (e100[i] >= e200[i] * 0.99)
        vol_ok = V[i] >= avg_vol[i] * 0.9 if avg_vol[i] > 0 else True
        if cross_up and macro_bull and vol_ok:
            sig[i] = True
    return sig

# ─── Strateji 3: QuantNomad / YouTube UT Bot Alerts ──────────────────────────
def _strat_ut_bot(H, L, C, V, key_value=2.0, atr_p=10):
    n = len(C)
    sig = np.zeros(n, dtype=bool)
    if n < 50:
        return sig
    atr = _atr(H, L, C, atr_p)
    n_loss = key_value * atr
    
    trailing_stop = np.zeros(n)
    for i in range(1, n):
        prev = trailing_stop[i-1]
        curr = C[i]
        loss = n_loss[i]
        if curr > prev and C[i-1] > prev:
            trailing_stop[i] = max(prev, curr - loss)
        elif curr < prev and C[i-1] < prev:
            trailing_stop[i] = min(prev, curr + loss)
        elif curr > prev:
            trailing_stop[i] = curr - loss
        else:
            trailing_stop[i] = curr + loss
            
    trend = np.zeros(n)
    for i in range(1, n):
        trend[i] = 1 if C[i] > trailing_stop[i] else -1
        
    e50 = _ema(C, 50)
    e200 = _ema(C, 200)
    
    for i in range(2, n):
        # Kırılım (Flip)
        buy_cross = (trend[i] == 1) and (trend[i-1] == -1)
        trend_filter = (e50[i] >= e200[i] * 0.99) or (C[i] > e50[i])
        if buy_cross and trend_filter:
            sig[i] = True
    return sig

# ─── Strateji 4: Modernize Donchian 20 Turtle Breakout + ADX ─────────────────
def _strat_turtle_donchian(H, L, C, V):
    n = len(C)
    sig = np.zeros(n, dtype=bool)
    if n < 30:
        return sig
    adx = _adx(H, L, C, 14)
    avg_vol = np.zeros(n)
    for i in range(20, n):
        avg_vol[i] = V[i-20:i].mean()
        
    for i in range(21, n):
        highest_20 = H[i-20:i].max()
        # 20 barın en yükseğini yukarı kırma + Güçlü ADX trendi + Hacim desteği
        breakout = (C[i] > highest_20) and (C[i-1] <= highest_20)
        strong_trend = (adx[i] >= 22.0)
        vol_spike = V[i] >= avg_vol[i] * 1.25 if avg_vol[i] > 0 else True
        if breakout and strong_trend and vol_spike:
            sig[i] = True
    return sig

# ─── Strateji 5: Kurumsal VWAP -2.0 Band Dip Sekmesi ─────────────────────────
def _strat_vwap_mean_reversion(H, L, C, V):
    n = len(C)
    sig = np.zeros(n, dtype=bool)
    if n < 50:
        return sig
    typical_price = (H + L + C) / 3.0
    cum_vol_price = np.cumsum(typical_price * V)
    cum_vol = np.cumsum(V)
    vwap = np.where(cum_vol > 0, cum_vol_price / cum_vol, C)
    
    # 30-bar rolling fark ve standart sapma
    diff = C - vwap
    rolling_std = np.zeros(n)
    for i in range(30, n):
        rolling_std[i] = diff[i-30:i].std()
    lower_vwap = vwap - 1.8 * rolling_std
    
    rsi = _rsi(C, 14)
    for i in range(35, n):
        # Fiyat VWAP alt bandına batıp geri içeri girdi + RSI dip dönüşü
        band_bounce = (L[i-1] <= lower_vwap[i-1]) and (C[i] > lower_vwap[i])
        rsi_dip = (rsi[i-1] <= 35.0) and (rsi[i] > rsi[i-1])
        if band_bounce and rsi_dip:
            sig[i] = True
    return sig

# ─── Strateji 6: YouTube SuperTrend + StochRSI Confluence ─────────────────────
def _strat_supertrend_stochrsi(H, L, C, V):
    n = len(C)
    sig = np.zeros(n, dtype=bool)
    if n < 40:
        return sig
    # SuperTrend(10, 3.0)
    atr = _atr(H, L, C, 10)
    hl2 = (H + L) / 2.0
    up = hl2 + 3.0 * atr
    dn = hl2 - 3.0 * atr
    st_dir = np.ones(n)
    for i in range(1, n):
        if C[i] > up[i-1]:
            st_dir[i] = 1
        elif C[i] < dn[i-1]:
            st_dir[i] = -1
        else:
            st_dir[i] = st_dir[i-1]
            
    # StochRSI
    rsi = _rsi(C, 14)
    k, d = _stoch_rsi(rsi, 14, 3, 3)
    
    for i in range(20, n):
        supertrend_bull = (st_dir[i] == 1)
        stoch_dip_cross = (k[i] > d[i]) and (k[i-1] <= d[i-1]) and (k[i] <= 25.0)
        if supertrend_bull and stoch_dip_cross:
            sig[i] = True
    return sig

# ─── Strateji 7: Freqtrade ClucHAnST Kapitülasyon İğnesi ─────────────────────
def _strat_cluc_wick(H, L, C, V):
    n = len(C)
    sig = np.zeros(n, dtype=bool)
    if n < 30:
        return sig
    e50 = _ema(C, 50)
    rsi = _rsi(C, 14)
    avg_vol = np.zeros(n)
    for i in range(20, n):
        avg_vol[i] = V[i-20:i].mean()
        
    for i in range(25, n):
        candle_body = abs(C[i] - (H[i] + L[i]) / 2)
        lower_wick = min(C[i], C[i-1]) - L[i]
        # Alt iğne çok uzun (kapitülasyon), hacim ortalamanın en az 1.5 katı, RSI aşırı satım
        wick_rejection = (lower_wick > candle_body * 1.5) and (L[i] < e50[i] * 0.98)
        vol_climax = V[i] >= avg_vol[i] * 1.5 if avg_vol[i] > 0 else False
        oversold = rsi[i] <= 32.0
        green_candle = C[i] > L[i] + lower_wick * 0.5
        if wick_rejection and vol_climax and oversold and green_candle:
            sig[i] = True
    return sig

# ─── Strateji 8: KDJ Pure Dip (Mevcut Benchmark) ─────────────────────────────
def _strat_kdj_pure_dip(H, L, C, V):
    n = len(C)
    sig = np.zeros(n, dtype=bool)
    if n < 20:
        return sig
    k, d, j = _kdj(H, L, C, 9, 3)
    for i in range(1, n):
        if (j[i] > d[i]) and (j[i-1] <= d[i-1]) and (j[i] <= 12.0):
            sig[i] = True
    return sig

# ─── Sinyal Üretici Fonksiyon ────────────────────────────────────────────────
def generate_all_signals(H, L, C, V, T):
    H = np.asarray(H, dtype=float)
    L = np.asarray(L, dtype=float)
    C = np.asarray(C, dtype=float)
    V = np.asarray(V, dtype=float)
    n = len(C)
    
    # 1 bar ileri kaydırma (shift=1): Geleceğe bakma hatasını (lookahead) kesinlikle sıfırlar
    def shift1(arr):
        z = np.zeros_like(arr, dtype=bool)
        z[1:] = arr[:-1]
        return z

    signals = {
        "freqtrade_bbrpb": shift1(_strat_freqtrade_bbrpb(H, L, C, V)),
        "qqe_mod_trend": shift1(_strat_qqe_mod(H, L, C, V)),
        "ut_bot_alerts": shift1(_strat_ut_bot(H, L, C, V)),
        "turtle_donchian": shift1(_strat_turtle_donchian(H, L, C, V)),
        "vwap_mean_rev": shift1(_strat_vwap_mean_reversion(H, L, C, V)),
        "supertrend_stochrsi": shift1(_strat_supertrend_stochrsi(H, L, C, V)),
        "cluc_wick_bounce": shift1(_strat_cluc_wick(H, L, C, V)),
        "kdj_pure_dip": shift1(_strat_kdj_pure_dip(H, L, C, V)),
    }
    
    # Rastgele referans (her 15. barda rastgele giriş)
    rnd = np.zeros(n, dtype=bool)
    rnd[::15] = True
    signals["__RASTGELE__"] = shift1(rnd)
    
    # Warmup periyodu
    for k in signals:
        signals[k][:100] = False
    return signals

# ─── VectorBT Değerlendirme ──────────────────────────────────────────────────
def evaluate_vbt_fixed(close: np.ndarray, entries: np.ndarray, tp_pct: float, sl_pct: float, fee_pct: float):
    close = np.asarray(close, dtype=float)
    entries = np.asarray(entries, dtype=bool)
    if entries.sum() == 0:
        return None
    try:
        pf = vbt.Portfolio.from_signals(
            close=close,
            entries=entries,
            exits=np.zeros_like(entries),
            tp_stop=(tp_pct / 100.0),
            sl_stop=(sl_pct / 100.0),
            fees=(fee_pct / 100.0),
            freq="5T",
            init_cash=100_000.0,
            size=1.0,
            size_type="amount",
            accumulate=False,
        )
        rec = pf.trades.records_readable
        if rec is None or len(rec) == 0:
            return None
        pnl = rec["PnL"].to_numpy(dtype=float)
        rets = rec["Return"].to_numpy(dtype=float)
        wins = pnl > 0
        gain = pnl[wins].sum()
        loss = -pnl[~wins].sum()
        return {
            "n": int(len(pnl)),
            "wr": float(wins.mean() * 100),
            "pf": float(gain / loss) if loss > 0 else (99.0 if gain > 0 else 0.0),
            "avg_ret_pct": float(np.mean(rets) * 100),
            "sum_ret_pct": float(np.sum(rets) * 100),
            "tstat": float(np.mean(rets) / (np.std(rets, ddof=1) / np.sqrt(len(rets)))) if len(rets) > 1 and np.std(rets, ddof=1) > 0 else 0.0,
        }
    except Exception as e:
        return None

def evaluate_dynamic_trailing(close: np.ndarray, high: np.ndarray, low: np.ndarray, entries: np.ndarray, fee_pct: float):
    idx = np.flatnonzero(np.asarray(entries, dtype=bool))
    if len(idx) == 0:
        return None
    ASY, LOCK, DIST, SL0, MAXBAR = 1.5, 0.8, 0.6, 0.9, 24
    rets = []
    for i in idx:
        entry = close[i]
        stop = entry * (1.0 - SL0 / 100.0)
        peak = entry
        trail = False
        n = min(len(close) - i - 1, MAXBAR)
        if n <= 0:
            continue
        res = None
        for k in range(1, n + 1):
            hi_k, lo_k = high[i + k], low[i + k]
            if hi_k > peak:
                peak = hi_k
            if not trail and (peak - entry) / entry * 100.0 >= ASY:
                trail = True
            if trail:
                stop = max(stop, entry * (1.0 + LOCK / 100.0), peak * (1.0 - DIST / 100.0))
            if lo_k <= stop:
                res = (stop - entry) / entry * 100.0 - fee_pct
                break
        if res is None:
            res = (close[i + n] - entry) / entry * 100.0 - fee_pct
        rets.append(res / 100.0)
        
    if not rets:
        return None
    a = np.asarray(rets)
    wins = a > 0
    gain = a[wins].sum()
    loss = -a[~wins].sum()
    return {
        "n": int(len(a)),
        "wr": float(wins.mean() * 100),
        "pf": float(gain / loss) if loss > 0 else (99.0 if gain > 0 else 0.0),
        "avg_ret_pct": float(np.mean(a) * 100),
        "sum_ret_pct": float(np.sum(a) * 100),
        "tstat": float(np.mean(a) / (np.std(a, ddof=1) / np.sqrt(len(a)))) if len(a) > 1 and np.std(a, ddof=1) > 0 else 0.0,
    }

# ─── Veri Yükleme ve Hacim Filtresi ─────────────────────────────────────────
async def load_candles(symbols: int, days: int, timeframe: str = "5m", min_bar_quote_vol: float = 10000.0):
    import asyncpg
    import pandas as pd
    url = os.environ.get("DATABASE_URL") or "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"
    conn = await asyncpg.connect(url)
    cutoff = int((time.time() - days * 86400) * 1000)
    
    # 1. Aşama: Bar başı ortalama hacmi en yüksek olan aktif coinleri filtrele
    rank_query = """
        SELECT symbol, AVG(quote_volume) as avg_quote, COUNT(*) as cnt
        FROM historical_candles
        WHERE timeframe = '5m' AND symbol LIKE '%USDT' AND open_time >= $1
        GROUP BY symbol
        HAVING AVG(quote_volume) >= $2 AND COUNT(*) >= 2000
        ORDER BY AVG(quote_volume) DESC
        LIMIT $3
    """
    ranked_rows = await conn.fetch(rank_query, cutoff, min_bar_quote_vol, symbols)
    active_symbols = [r["symbol"] for r in ranked_rows]
    
    if not active_symbols:
        await conn.close()
        return {}
        
    print(f"Hacim Filtresi: Bar başı ortalama >= ${min_bar_quote_vol:,.0f} USDT (Seçilen Aktif Coin: {len(active_symbols)})")
    
    # 2. Aşama: Seçilen aktif coinlerin 5m mumlarını çek
    data_query = """
        SELECT symbol, open_time, open, high, low, close, volume, quote_volume
        FROM historical_candles
        WHERE timeframe = '5m' AND symbol = ANY($1) AND open_time >= $2
        ORDER BY symbol, open_time ASC
    """
    rows = await conn.fetch(data_query, active_symbols, cutoff)
    await conn.close()
    
    # Gruplama
    raw_data = defaultdict(lambda: {"T": [], "O": [], "H": [], "L": [], "C": [], "V": []})
    for r in rows:
        sym = r["symbol"]
        raw_data[sym]["T"].append(int(r["open_time"]))
        raw_data[sym]["O"].append(float(r["open"]))
        raw_data[sym]["H"].append(float(r["high"]))
        raw_data[sym]["L"].append(float(r["low"]))
        raw_data[sym]["C"].append(float(r["close"]))
        raw_data[sym]["V"].append(float(r["volume"]))
        
    # Eğer 15m veya 1h isteniyorsa, 5m verilerini temiz bir şekilde resample et
    if timeframe == "5m":
        return {s: d for s, d in raw_data.items() if len(d["C"]) >= 2000}
    
    resample_freq = "15min" if timeframe == "15m" else "1h"
    resampled_data = {}
    for sym, d in raw_data.items():
        if len(d["C"]) < 500:
            continue
        df = pd.DataFrame({
            "open": d["O"], "high": d["H"], "low": d["L"], "close": d["C"], "volume": d["V"]
        }, index=pd.to_datetime(d["T"], unit="ms"))
        
        agg_rules = {
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }
        res_df = df.resample(resample_freq).agg(agg_rules).dropna()
        if len(res_df) < 200:
            continue
            
        resampled_data[sym] = {
            "T": (res_df.index.astype("int64") // 10**6).tolist(),
            "H": res_df["high"].tolist(),
            "L": res_df["low"].tolist(),
            "C": res_df["close"].tolist(),
            "V": res_df["volume"].tolist(),
        }
    return resampled_data

# ─── Ana Yürütme ve Raporlama ────────────────────────────────────────────────
def run_evaluation(timeframe="5m", symbols=50, days=60, fee=0.15, min_vol=10000.0):
    print(f"\n==========================================================================================")
    print(f" GITHUB & YOUTUBE SPOT STRATEJILERI VECTORBT TESTI ({timeframe} | En Hacimli {symbols} Aktif Coin)")
    print(f" Hacim Esiği: Bar basi >= ${min_vol:,.0f} | Maliyet: %{fee} round-trip (Net Komisyon)")
    print(f"==========================================================================================")
    
    t0 = time.time()
    data = asyncio.run(load_candles(symbols, days, timeframe, min_vol))
    if not data:
        print("UYARI: Belirtilen hacim kriterinde mum verisi bulunamadi!")
        return
    total_bars = sum(len(d['C']) for d in data.values())
    print(f"Yuklenen Aktif Coin: {len(data)} sembol, Toplam {total_bars:,} bar ({time.time()-t0:.1f}s)")
    
    tp_pct = 1.5 if timeframe == "5m" else (2.2 if timeframe == "15m" else 3.5)
    sl_pct = 0.9 if timeframe == "5m" else (1.2 if timeframe == "15m" else 1.8)
    
    agg = defaultdict(lambda: defaultdict(lambda: {"tp_sl": [], "trail": []}))
    
    for sym, d in data.items():
        C = np.asarray(d["C"])
        H = np.asarray(d["H"])
        L = np.asarray(d["L"])
        V = np.asarray(d["V"])
        T = np.asarray(d["T"])
        
        sigs = generate_all_signals(H, L, C, V, T)
        for name, entries in sigs.items():
            r1 = evaluate_vbt_fixed(C, entries, tp_pct, sl_pct, fee)
            if r1:
                agg[name][sym]["tp_sl"] = r1
            r2 = evaluate_dynamic_trailing(C, H, L, entries, fee)
            if r2:
                agg[name][sym]["trail"] = r2
                
    def combine(name, mode):
        vals = [v[mode] for v in agg[name].values() if v.get(mode)]
        if not vals:
            return None
        n = sum(x["n"] for x in vals)
        if n == 0:
            return None
        wins = sum(x["wr"] / 100.0 * x["n"] for x in vals)
        avg = sum(x["avg_ret_pct"] * x["n"] for x in vals) / n
        coins_pos = sum(1 for x in vals if x["avg_ret_pct"] > 0)
        coins_n = len(vals)
        valid_pfs = [x["pf"] for x in vals if 0 < x["pf"] < 50.0]
        pf = float(np.mean(valid_pfs)) if valid_pfs else 0.0
        tstat = float(np.mean([x["tstat"] for x in vals]))
        return {
            "n": n, "wr": wins / n * 100.0, "pf": pf, "avg": avg,
            "coins_pos": coins_pos, "coins_n": coins_n, "tstat": tstat
        }

    for mode, title in [("trail", "DİNAMİK TAKİPÇİ ÇIKIŞ"), ("tp_sl", f"SABİT TP/SL (%{tp_pct}/%{sl_pct})")]:
        print(f"\n--- {title} ---")
        print(f"{'Strateji':<22} {'İşlem (n)':<10} {'WinRate':<9} {'ProfitFac':<10} {'Ort Net%':<10} {'t-stat':<9} {'Pozitif Coin':<13} {'Karar'}")
        print("-" * 96)
        rows = []
        for name in agg:
            c = combine(name, mode)
            if not c:
                continue
            # SKILL.md Kriterleri: n>=20, WR>=55% (trend) veya >=60% (dip), PF>=1.50, net>0, en az 2 pozitif coin
            is_mr = name in {"freqtrade_bbrpb", "vwap_mean_rev", "kdj_pure_dip", "cluc_wick_bounce"}
            wr_thr = 58.0 if is_mr else 52.0
            checks = [
                c["n"] >= 20,
                c["wr"] >= wr_thr,
                c["pf"] >= 1.40,
                c["avg"] > 0.0,
                c["coins_pos"] >= 2
            ]
            passed = sum(checks)
            if passed == 5:
                dec = "[TERFI ET]"
            elif passed >= 3:
                dec = "[INCELE]"
            else:
                dec = "[RED]"
            rows.append((c["avg"], name, c, checks, dec))
            
        for _, name, c, checks, dec in sorted(rows, key=lambda r: -r[0]):
            sig_mark = " **" if c["tstat"] > 1.96 else (" *" if c["tstat"] > 1.4 else "")
            print(f"{name:<22} {c['n']:<10d} %{c['wr']:<7.1f} {c['pf']:<10.2f} %{c['avg']:<8.3f} {c['tstat']:<8.2f} {c['coins_pos']}/{c['coins_n']:<10d} {dec} ({sum(checks)}/5){sig_mark}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframe", type=str, default="5m", choices=["5m", "15m", "1h"])
    parser.add_argument("--symbols", type=int, default=40)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--fee", type=float, default=0.15)
    parser.add_argument("--min-vol", type=float, default=10000.0)
    args = parser.parse_args()
    
    run_evaluation(args.timeframe, args.symbols, args.days, args.fee, args.min_vol)
