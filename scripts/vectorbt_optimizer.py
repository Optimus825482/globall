#!/usr/bin/env python3
"""VectorBT Destekli Çoklu-Strateji ve Parametre Optimizasyon Motoru.

Desteklenen Stratejiler:
    - ema: Klasik Hızlı/Yavaş EMA Kesişimi
    - wavetrend: WaveTrend (WT1/WT2 dip kesişimi ve aşırı satım dönüşü)
    - zlmacd: Zero-Lag MACD (DEMA tabanlı gecikmesiz kesişim)
    - kombo: WaveTrend + ZL-MACD Hibrit Teyitli Strateji
    - supertrend: ATR Tabanlı SuperTrend Yön + Geri Çekilme
    - stochrsi: Stokastik RSI (<20 Aşırı Satım K/D Kesişimi)
    - bb_squeeze: Bollinger Bandı Sıkışması ve Hacimli Patlama
    - btc_master: Bitcoin'e Özel Kuantum Çoklu-Gösterge Hibriti (WT + SuperTrend + StochRSI + ZL-MACD)

Kullanım:
    python scripts/vectorbt_optimizer.py --symbol BTCUSD --strategy btc_master --top 5
    python scripts/vectorbt_optimizer.py --symbol BTCUSD --strategy supertrend --top 5
    python scripts/vectorbt_optimizer.py --symbol BTCUSD --strategy stochrsi --top 5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import vectorbt as vbt


def load_candles_from_cache(cache_path: str, symbol: str) -> pd.DataFrame:
    """Replay önbelleğinden veya JSON dosyasından barları yükler ve DataFrame yapar."""
    if not os.path.exists(cache_path):
        raise FileNotFoundError(f"Önbellek dosyası bulunamadı: {cache_path}")

    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if symbol not in data:
        available = list(data.keys())[:15]
        raise ValueError(f"Sembol '{symbol}' önbellekte yok. Mevcut semboller: {available}")

    raw_bars = data[symbol]
    if not raw_bars:
        raise ValueError(f"'{symbol}' için bar verisi boş.")

    cols = ["timestamp", "open", "high", "low", "close"]
    if len(raw_bars[0]) >= 6:
        cols.append("volume")
        records = [b[:6] for b in raw_bars]
    else:
        records = [b[:5] for b in raw_bars]

    df = pd.DataFrame(records, columns=cols)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df.set_index("datetime").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df


def calc_dema(series: pd.Series, span: int) -> pd.Series:
    """Zero-Lag için Çift Üstel Hareketli Ortalama (DEMA)."""
    e1 = series.ewm(span=span, adjust=False).mean()
    e2 = e1.ewm(span=span, adjust=False).mean()
    return 2.0 * e1 - e2


def calc_zlmacd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series]:
    """Zero-Lag MACD ve Sinyal hattı."""
    f_dema = calc_dema(series, fast)
    s_dema = calc_dema(series, slow)
    macd = f_dema - s_dema
    sig = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig


def calc_wavetrend(df: pd.DataFrame, ch_len: int = 10, avg_len: int = 21, sig_len: int = 4) -> tuple[pd.Series, pd.Series]:
    """LazyBear WaveTrend osilatörü (WT1 ve WT2)."""
    ap = (df["high"] + df["low"] + df["close"]) / 3.0
    esa = ap.ewm(span=ch_len, adjust=False).mean()
    dev = (ap - esa).abs().ewm(span=ch_len, adjust=False).mean()
    ci = (ap - esa) / (0.015 * dev.replace(0, np.nan))
    wt1 = ci.ewm(span=avg_len, adjust=False).mean()
    wt2 = wt1.rolling(sig_len).mean()
    return wt1, wt2


def calc_stochrsi(series: pd.Series, rsi_period: int = 14, stoch_period: int = 14, k_period: int = 3, d_period: int = 3) -> tuple[pd.Series, pd.Series]:
    """Stokastik RSI (K ve D hatları)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(span=rsi_period, adjust=False).mean()
    avg_loss = loss.ewm(span=rsi_period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    stoch_min = rsi.rolling(stoch_period).min()
    stoch_max = rsi.rolling(stoch_period).max()
    stoch_rsi = (rsi - stoch_min) / (stoch_max - stoch_min).replace(0, np.nan) * 100.0
    k = stoch_rsi.rolling(k_period).mean()
    d = k.rolling(d_period).mean()
    return k, d


def calc_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    """ATR Tabanlı SuperTrend Göstergesi (+1 Boğa, -1 Ayı)."""
    hl2 = (df["high"] + df["low"]) / 2.0
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    basic_upper = hl2 + (multiplier * atr)
    basic_lower = hl2 - (multiplier * atr)

    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    n = len(df)
    trend = np.ones(n, dtype=int)

    c_vals = df["close"].values
    bu_vals = basic_upper.values
    bl_vals = basic_lower.values
    fu_vals = basic_upper.values.copy()
    fl_vals = basic_lower.values.copy()

    for i in range(1, n):
        if bu_vals[i] < fu_vals[i - 1] or c_vals[i - 1] > fu_vals[i - 1]:
            fu_vals[i] = bu_vals[i]
        else:
            fu_vals[i] = fu_vals[i - 1]

        if bl_vals[i] > fl_vals[i - 1] or c_vals[i - 1] < fl_vals[i - 1]:
            fl_vals[i] = bl_vals[i]
        else:
            fl_vals[i] = fl_vals[i - 1]

        if trend[i - 1] == 1:
            trend[i] = -1 if c_vals[i] < fl_vals[i] else 1
        else:
            trend[i] = 1 if c_vals[i] > fu_vals[i] else -1

    return pd.Series(trend, index=df.index)


def calc_bollinger(series: pd.Series, window: int = 20, num_std: float = 2.0) -> tuple[pd.Series, pd.Series]:
    """Bollinger %B ve Bandwidth (Genişlik)."""
    sma = series.rolling(window).mean()
    std = series.rolling(window).std()
    upper = sma + (num_std * std)
    lower = sma - (num_std * std)
    pct_b = (series - lower) / (upper - lower).replace(0, np.nan)
    bandwidth = (upper - lower) / sma
    return pct_b, bandwidth


def optimize_btc_master_vbt(df: pd.DataFrame, top_n: int = 10) -> dict:
    """Bitcoin İçin Özel Geliştirilmiş Çoklu-Gösterge Kuantum Hibriti.

    Bileşenler:
    1. Trend: EMA 100/200 + SuperTrend Yönü
    2. Momentum Tetikleyici: WaveTrend VEYA StochRSI Dip Dönüşü
    3. Hız & Güç Teyidi: Zero-Lag MACD Pozitifliği
    """
    tp_sl_pairs = [
        (0.012, 0.008),  # 1.50 R
        (0.015, 0.010),  # 1.50 R
        (0.020, 0.010),  # 2.00 R
        (0.025, 0.012),  # 2.08 R
        (0.030, 0.015),  # 2.00 R
    ]
    ema_filters = [50, 100, 200]
    st_multipliers = [2.0, 3.0]
    wt_oversolds = [-40, -35, -30]

    close = df["close"]
    wt1, wt2 = calc_wavetrend(df, ch_len=10, avg_len=21)
    stoch_k, stoch_d = calc_stochrsi(close)
    macd, macd_sig = calc_zlmacd(close, fast=10, slow=24, signal=9)

    wt_cross_up = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1))
    stoch_cross_up = (stoch_k > stoch_d) & (stoch_k.shift(1) <= stoch_d.shift(1)) & (stoch_k <= 25)
    macd_bull = macd > macd_sig

    total_combinations = len(ema_filters) * len(st_multipliers) * len(wt_oversolds) * len(tp_sl_pairs)
    print(f"\n[VectorBT - BTC MASTER Kuantum] Optimizasyon Başlıyor...")
    print(f"Toplam Parametre Kombinasyonu: {total_combinations:,}")
    print(f"Veri Boyutu: {len(df):,} bar")

    start_time = time.time()
    all_results = []

    for st_mult in st_multipliers:
        st_trend = calc_supertrend(df, period=10, multiplier=st_mult)
        st_bull = st_trend == 1

        for ema_len in ema_filters:
            ema_val = close.ewm(span=ema_len, adjust=False).mean()
            trend_up = (close > ema_val) & st_bull

            for wt_os in wt_oversolds:
                # WaveTrend dip dönüşü VEYA StochRSI dip dönüşü, Trend yukarı, ZL-MACD pozitif
                dip_turn = (wt_cross_up & (wt1 <= wt_os)) | stoch_cross_up
                entries = dip_turn & trend_up & macd_bull
                exits = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1))

                for tp, sl in tp_sl_pairs:
                    pf = vbt.Portfolio.from_signals(
                        close=close,
                        entries=entries,
                        exits=exits,
                        tp_stop=tp,
                        sl_stop=sl,
                        fees=0.0002,
                        freq="15m" if len(df) > 500 else "1m",
                    )
                    t_count = pf.trades.count()
                    if t_count < 3:
                        continue

                    s_val = float(pf.sharpe_ratio())
                    if np.isnan(s_val):
                        s_val = 0.0

                    all_results.append({
                        "parameters": {
                            "trend_ema": ema_len,
                            "supertrend_mult": st_mult,
                            "wt_oversold": wt_os,
                            "tp_pct": round(tp * 100, 2),
                            "sl_pct": round(sl * 100, 2),
                        },
                        "total_return_pct": round(float(pf.total_return()) * 100, 2),
                        "sharpe_ratio": round(s_val, 3),
                        "max_drawdown_pct": round(float(pf.max_drawdown()) * 100, 2),
                        "win_rate_pct": round(float(pf.trades.win_rate()) * 100, 2) if not np.isnan(pf.trades.win_rate()) else 0.0,
                        "trade_count": int(t_count),
                    })

    elapsed = time.time() - start_time
    print(f"[VectorBT - BTC MASTER Kuantum] Tamamlandı! Süre: {elapsed:.2f} saniye")

    all_results.sort(key=lambda x: (x["sharpe_ratio"], x["total_return_pct"]), reverse=True)
    return {
        "status": "success",
        "strategy": "BTC Master (WT + SuperTrend + StochRSI + ZL-MACD)",
        "elapsed_sec": round(elapsed, 3),
        "total_combinations": total_combinations,
        "top_results": all_results[:top_n],
    }


def optimize_supertrend_vbt(df: pd.DataFrame, top_n: int = 10) -> dict:
    """SuperTrend Trend Takibi ve Pullback Optimizasyonu."""
    periods = [7, 10, 14]
    multipliers = [1.5, 2.0, 3.0]
    tp_sl_pairs = [
        (0.015, 0.010),
        (0.020, 0.012),
        (0.025, 0.015),
        (0.030, 0.015),
    ]

    total_combinations = len(periods) * len(multipliers) * len(tp_sl_pairs)
    print(f"\n[VectorBT - SuperTrend] Optimizasyon Başlıyor...")
    start_time = time.time()
    close = df["close"]
    all_results = []

    for p in periods:
        for m in multipliers:
            st = calc_supertrend(df, period=p, multiplier=m)
            # Supertrend yeşile döndüğünde giriş
            entries = (st == 1) & (st.shift(1) == -1)
            exits = (st == -1) & (st.shift(1) == 1)

            for tp, sl in tp_sl_pairs:
                pf = vbt.Portfolio.from_signals(
                    close=close,
                    entries=entries,
                    exits=exits,
                    tp_stop=tp,
                    sl_stop=sl,
                    fees=0.0002,
                    freq="15m" if len(df) > 500 else "1m",
                )
                t_count = pf.trades.count()
                if t_count < 3:
                    continue

                s_val = float(pf.sharpe_ratio()) if not np.isnan(pf.sharpe_ratio()) else 0.0
                all_results.append({
                    "parameters": {"period": p, "multiplier": m, "tp_pct": round(tp * 100, 2), "sl_pct": round(sl * 100, 2)},
                    "total_return_pct": round(float(pf.total_return()) * 100, 2),
                    "sharpe_ratio": round(s_val, 3),
                    "max_drawdown_pct": round(float(pf.max_drawdown()) * 100, 2),
                    "win_rate_pct": round(float(pf.trades.win_rate()) * 100, 2) if not np.isnan(pf.trades.win_rate()) else 0.0,
                    "trade_count": int(t_count),
                })

    elapsed = time.time() - start_time
    print(f"[VectorBT - SuperTrend] Tamamlandı! Süre: {elapsed:.2f} saniye")
    all_results.sort(key=lambda x: (x["sharpe_ratio"], x["total_return_pct"]), reverse=True)
    return {"status": "success", "strategy": "SuperTrend", "elapsed_sec": round(elapsed, 3), "top_results": all_results[:top_n]}


def optimize_stochrsi_vbt(df: pd.DataFrame, top_n: int = 10) -> dict:
    """Stokastik RSI Dip Kesişimleri ve TP/SL."""
    os_levels = [15, 20, 25]
    tp_sl_pairs = [(0.012, 0.008), (0.015, 0.010), (0.020, 0.012), (0.025, 0.015)]
    trend_emas = [50, 100]

    close = df["close"]
    k, d = calc_stochrsi(close)
    cross_up = (k > d) & (k.shift(1) <= d.shift(1))
    cross_down = (k < d) & (k.shift(1) >= d.shift(1))

    start_time = time.time()
    all_results = []

    for ema_len in trend_emas:
        ema_val = close.ewm(span=ema_len, adjust=False).mean()
        trend_up = close > ema_val

        for os_lvl in os_levels:
            entries = cross_up & (k <= os_lvl) & trend_up
            exits = cross_down

            for tp, sl in tp_sl_pairs:
                pf = vbt.Portfolio.from_signals(
                    close=close, entries=entries, exits=exits, tp_stop=tp, sl_stop=sl, fees=0.0002,
                    freq="15m" if len(df) > 500 else "1m"
                )
                t_count = pf.trades.count()
                if t_count < 3:
                    continue
                s_val = float(pf.sharpe_ratio()) if not np.isnan(pf.sharpe_ratio()) else 0.0
                all_results.append({
                    "parameters": {"trend_ema": ema_len, "stoch_oversold": os_lvl, "tp_pct": round(tp * 100, 2), "sl_pct": round(sl * 100, 2)},
                    "total_return_pct": round(float(pf.total_return()) * 100, 2),
                    "sharpe_ratio": round(s_val, 3),
                    "max_drawdown_pct": round(float(pf.max_drawdown()) * 100, 2),
                    "win_rate_pct": round(float(pf.trades.win_rate()) * 100, 2) if not np.isnan(pf.trades.win_rate()) else 0.0,
                    "trade_count": int(t_count),
                })

    elapsed = time.time() - start_time
    all_results.sort(key=lambda x: (x["sharpe_ratio"], x["total_return_pct"]), reverse=True)
    return {"status": "success", "strategy": "StochRSI", "elapsed_sec": round(elapsed, 3), "top_results": all_results[:top_n]}


def optimize_wavetrend_vbt(df: pd.DataFrame, top_n: int = 10) -> dict:
    channel_lens = [8, 10, 12]
    avg_lens = [18, 21, 24]
    os_levels = [-60, -50, -40]
    tp_sl_pairs = [(0.010, 0.008), (0.015, 0.010), (0.020, 0.012), (0.025, 0.015), (0.030, 0.015)]

    total_combinations = len(channel_lens) * len(avg_lens) * len(os_levels) * len(tp_sl_pairs)
    start_time = time.time()
    close = df["close"]
    all_results = []

    for ch in channel_lens:
        for avg in avg_lens:
            wt1, wt2 = calc_wavetrend(df, ch_len=ch, avg_len=avg)
            cross_up = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1))
            cross_down = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1))

            for os_lvl in os_levels:
                entries = cross_up & (wt1 <= os_lvl)
                exits = cross_down

                for tp, sl in tp_sl_pairs:
                    pf = vbt.Portfolio.from_signals(
                        close=close, entries=entries, exits=exits, tp_stop=tp, sl_stop=sl, fees=0.0002,
                        freq="15m" if len(df) > 500 else "1m"
                    )
                    t_count = pf.trades.count()
                    if t_count < 3:
                        continue
                    s_val = float(pf.sharpe_ratio()) if not np.isnan(pf.sharpe_ratio()) else 0.0
                    all_results.append({
                        "parameters": {"channel": ch, "average": avg, "oversold": os_lvl, "tp_pct": round(tp * 100, 2), "sl_pct": round(sl * 100, 2)},
                        "total_return_pct": round(float(pf.total_return()) * 100, 2),
                        "sharpe_ratio": round(s_val, 3),
                        "max_drawdown_pct": round(float(pf.max_drawdown()) * 100, 2),
                        "win_rate_pct": round(float(pf.trades.win_rate()) * 100, 2) if not np.isnan(pf.trades.win_rate()) else 0.0,
                        "trade_count": int(t_count),
                    })

    elapsed = time.time() - start_time
    all_results.sort(key=lambda x: (x["sharpe_ratio"], x["total_return_pct"]), reverse=True)
    return {"status": "success", "strategy": "WaveTrend", "elapsed_sec": round(elapsed, 3), "top_results": all_results[:top_n]}


def optimize_zlmacd_vbt(df: pd.DataFrame, top_n: int = 10) -> dict:
    fasts = [8, 10, 12]
    slows = [21, 26, 30]
    signals = [7, 9]
    tp_sl_pairs = [(0.010, 0.008), (0.015, 0.010), (0.020, 0.012), (0.025, 0.015)]

    start_time = time.time()
    close = df["close"]
    all_results = []

    for f in fasts:
        for s in slows:
            for sig in signals:
                macd, macd_sig = calc_zlmacd(close, fast=f, slow=s, signal=sig)
                entries = (macd > macd_sig) & (macd.shift(1) <= macd_sig.shift(1))
                exits = (macd < macd_sig) & (macd.shift(1) >= macd_sig.shift(1))

                for tp, sl in tp_sl_pairs:
                    pf = vbt.Portfolio.from_signals(
                        close=close, entries=entries, exits=exits, tp_stop=tp, sl_stop=sl, fees=0.0002,
                        freq="15m" if len(df) > 500 else "1m"
                    )
                    t_count = pf.trades.count()
                    if t_count < 5:
                        continue
                    s_val = float(pf.sharpe_ratio()) if not np.isnan(pf.sharpe_ratio()) else 0.0
                    all_results.append({
                        "parameters": {"fast": f, "slow": s, "signal": sig, "tp_pct": round(tp * 100, 2), "sl_pct": round(sl * 100, 2)},
                        "total_return_pct": round(float(pf.total_return()) * 100, 2),
                        "sharpe_ratio": round(s_val, 3),
                        "max_drawdown_pct": round(float(pf.max_drawdown()) * 100, 2),
                        "win_rate_pct": round(float(pf.trades.win_rate()) * 100, 2) if not np.isnan(pf.trades.win_rate()) else 0.0,
                        "trade_count": int(t_count),
                    })

    elapsed = time.time() - start_time
    all_results.sort(key=lambda x: (x["sharpe_ratio"], x["total_return_pct"]), reverse=True)
    return {"status": "success", "strategy": "ZeroLag MACD", "elapsed_sec": round(elapsed, 3), "top_results": all_results[:top_n]}


def optimize_kombo_vbt(df: pd.DataFrame, top_n: int = 10) -> dict:
    tp_sl_pairs = [(0.012, 0.008), (0.015, 0.010), (0.020, 0.012), (0.025, 0.015), (0.030, 0.015)]
    os_levels = [-55, -45, -35]
    ema_filters = [50, 100, 200]

    close = df["close"]
    wt1, wt2 = calc_wavetrend(df, ch_len=10, avg_len=21)
    macd, macd_sig = calc_zlmacd(close, fast=10, slow=24, signal=9)

    wt_cross_up = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1))
    macd_bull = macd > macd_sig

    start_time = time.time()
    all_results = []

    for ema_len in ema_filters:
        ema_trend = close.ewm(span=ema_len, adjust=False).mean()
        trend_up = close > ema_trend

        for os_lvl in os_levels:
            entries = wt_cross_up & (wt1 <= os_lvl) & macd_bull & trend_up
            exits = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1))

            for tp, sl in tp_sl_pairs:
                pf = vbt.Portfolio.from_signals(
                    close=close, entries=entries, exits=exits, tp_stop=tp, sl_stop=sl, fees=0.0002,
                    freq="15m" if len(df) > 500 else "1m"
                )
                t_count = pf.trades.count()
                if t_count < 3:
                    continue
                s_val = float(pf.sharpe_ratio()) if not np.isnan(pf.sharpe_ratio()) else 0.0
                all_results.append({
                    "parameters": {"trend_ema": ema_len, "wt_oversold": os_lvl, "tp_pct": round(tp * 100, 2), "sl_pct": round(sl * 100, 2)},
                    "total_return_pct": round(float(pf.total_return()) * 100, 2),
                    "sharpe_ratio": round(s_val, 3),
                    "max_drawdown_pct": round(float(pf.max_drawdown()) * 100, 2),
                    "win_rate_pct": round(float(pf.trades.win_rate()) * 100, 2) if not np.isnan(pf.trades.win_rate()) else 0.0,
                    "trade_count": int(t_count),
                })

    elapsed = time.time() - start_time
    all_results.sort(key=lambda x: (x["sharpe_ratio"], x["total_return_pct"]), reverse=True)
    return {"status": "success", "strategy": "Kombo (WaveTrend + ZL-MACD + EMA)", "elapsed_sec": round(elapsed, 3), "top_results": all_results[:top_n]}


def main():
    parser = argparse.ArgumentParser(description="VectorBT Gelişmiş Çoklu-Strateji Optimizasyon Motoru")
    parser.add_argument("--symbol", default="BTCUSD", help="Analiz edilecek sembol (ör: BTCUSD, XAUUSD, US30)")
    parser.add_argument("--strategy", default="btc_master",
                        choices=["ema", "wavetrend", "zlmacd", "kombo", "supertrend", "stochrsi", "btc_master"],
                        help="Optimizasyon stratejisi")
    parser.add_argument("--cache", default="outputs/forex_replay_21d.json", help="Bar verisi JSON önbellek yolu")
    parser.add_argument("--top", type=int, default=5, help="Raporlanacak en iyi sonuç sayısı")
    parser.add_argument("--out", default=None, help="Sonuç JSON kayıt dosyası (opsiyonel)")
    args = parser.parse_args()

    print(f"==================================================")
    print(f"   VECTORBT GELİŞMİŞ STRATEJİ OPTİMİZATÖRÜ        ")
    print(f"==================================================")
    print(f"Hedef Sembol: {args.symbol}")
    print(f"Strateji:     {args.strategy.upper()}")
    print(f"Kaynak Veri:  {args.cache}")

    df = load_candles_from_cache(args.cache, args.symbol)

    if args.strategy == "btc_master":
        res = optimize_btc_master_vbt(df, top_n=args.top)
    elif args.strategy == "supertrend":
        res = optimize_supertrend_vbt(df, top_n=args.top)
    elif args.strategy == "stochrsi":
        res = optimize_stochrsi_vbt(df, top_n=args.top)
    elif args.strategy == "wavetrend":
        res = optimize_wavetrend_vbt(df, top_n=args.top)
    elif args.strategy == "zlmacd":
        res = optimize_zlmacd_vbt(df, top_n=args.top)
    elif args.strategy == "kombo":
        res = optimize_kombo_vbt(df, top_n=args.top)
    else:
        # Default fallback
        res = optimize_kombo_vbt(df, top_n=args.top)

    print(f"\n--- EN İYİ {res['strategy']} KOMBİNASYONLARI (Sharpe Sıralı) ---")
    header = f"{'Sıra':<5} {'Parametreler':<52} {'Toplam Kâr':<12} {'Sharpe':<8} {'MaxDD':<8} {'İsabet':<8} {'İşlem':<6}"
    print(header)
    print("-" * len(header))
    for i, item in enumerate(res["top_results"], 1):
        p = item["parameters"]
        param_str = " | ".join(f"{k}:{v}" for k, v in p.items())
        print(f"#{i:<4} {param_str:<52} %{item['total_return_pct']:<11} {item['sharpe_ratio']:<8} %{item['max_drawdown_pct']:<7} %{item['win_rate_pct']:<7} {item['trade_count']:<6}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)
        print(f"\nSonuçlar kaydedildi: {args.out}")


if __name__ == "__main__":
    main()
