"""
SPOT GÖSTERGE KOMBİNASYON LABORATUVARI v2 — Rehber Göstergeleri Geniş Tarama
=============================================================================
Kaynak araştırma: GOSTERGELER.HTML (TradingView gösterge rehberi),
ALTCOIN_REHBERI.HTML (oyun kitabı kombinasyonları),
KRIPTO_ALGO_SISTEMLER.HTML (backtest doğrulama kuralları).

YENİ 13 KOMBİNASYON (7 baz şampiyon + 13 yeni = 20 strateji):
  Mean-Reversion (Dip Dönüş, WR eşiği %60):
    8.  Connors RSI(3) < 15 + EMA200 Trend Filtresi
    9.  MFI(14) < 20 Dönüşü + EMA50 (hacim teyitli dip)
    10. StochRSI(14,14,3,3) K>D Yukarı Kesişim + EMA200
    11. Williams %R < -90 Dönüşü + Bull Bear Power Yükselişi
    12. CCI(20) < -100 Toparlanma Kesişimi + EMA50
    13. Ultimate Oscillator(7,14,28) < 30 Dönüşü
  Trend / Kırılım (WR eşiği %55):
    14. Donchian(20) Kırılımı + ADX(14) > 25
    15. Bollinger-Keltner Sıkışması + Üst Bant Kırılımı (TTM Squeeze)
    16. Vortex +VI > -VI Kesişimi + ADX > 20
    17. Awesome Oscillator Sıfır Kesişimi + MFI > 50
    18. Günlük VWAP Geri Kazanımı + OBV > OBV-EMA21
    19. EMA20 Pullback + Elder Force Index(13) Sıfır Üstü Kesişimi
    20. Hull MA(21) Yön Dönüşü + Choppiness(14) < 61.8

BACKTEST DİSİPLİNİ (KRIPTO_ALGO_SISTEMLER.HTML kuralları):
  - Look-ahead yok: sinyal bar kapanışında üretim, giriş SONRAKİ bar açılışından.
  - Muhafazakar eşleşme: aynı barda TP ve SL ikisi de değiyorsa SL kabul edilir.
  - Gap koruması: açılış stopun altındaysa/fiyat üstündeyse açılıştan dolum.
  - %0.08 round-trip komisyon net kârdan düşülür.
  - Zaman aşımı: 48 bar sonunda kalan pozisyon bar kapanışından kapatılır.
  - Split-half: ilk/son 500 bar net kâr ayrı raporlanır (rejim bağımlılık testi).
  - Deneme sayısı (N) beyan edilir + E[max] çoklu test uyarısı.
"""
import sys
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from test_advanced_spot_strategies import (
    fetch_binance_klines, SPOT_SYMBOLS as BASE_SYMBOLS,
    calc_ema, calc_atr, calc_rsi, calc_kdj, calc_supertrend, calc_wavetrend,
    calc_bollinger_vwap, calc_zlmacd, calc_stc, calc_fisher, generate_signals,
)

sys.stdout.reconfigure(encoding="utf-8")

COMMISSION_PCT = 0.08  # round-trip spot komisyonu (%)

EXTENDED_SYMBOLS = [
    "NEARUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "RENDERUSDT", "FETUSDT", "ARBUSDT", "INJUSDT"
]
ALL_SYMBOLS = BASE_SYMBOLS + EXTENDED_SYMBOLS

TIMEFRAMES = [
    ("5m", (1.5, 0.9)),   # Hızlı Scalp
    ("15m", (2.2, 1.2)),  # Standart Trend
    ("1h", (4.0, 2.0)),   # Swing Momentum
]

# Strateji sınıflandırması: kazanç oranı eşiği (dip dönüş %60, trend %55)
MR_GATE = 60.0
TREND_GATE = 55.0
STRATEGY_META = {
    # baz şampiyonlar
    "KDJ_EMA50":              ("KDJ Dip + EMA50 Desteği", MR_GATE),
    "SUPERTREND_WAVETREND":   ("SuperTrend Boğa + WaveTrend Dip", MR_GATE),
    "BOLLINGER_VWAP_EXPANSION": ("Bollinger Alt Bant + VWAP Kırılımı", MR_GATE),
    "KDJ_RSI_CONFLUENCE":     ("KDJ + RSI Çift Dip Confluence", MR_GATE),
    "ZLMACD_EMA_MOMENTUM":    ("Zero-Lag MACD + EMA20/50 Momentum", TREND_GATE),
    "STC_SCHAFF_CYCLE":       ("Schaff Trend Cycle 25 Kırılımı", TREND_GATE),
    "FISHER_DONCHIAN":        ("Fisher Transform Dip Sıçraması", MR_GATE),
    # yeni kombinasyonlar
    "CONNORS_RSI3_EMA200":    ("Connors RSI(3)<15 + EMA200 Trend", MR_GATE),
    "MFI_TURNUP_EMA50":       ("MFI(14)<20 Dönüş + EMA50", MR_GATE),
    "STOCHRSI_KD_EMA200":     ("StochRSI K>D Kesişim + EMA200", MR_GATE),
    "WPR_BBP_TURN":           ("Williams %R<-90 + BBP Yükselişi", MR_GATE),
    "CCI_RECOVERY_EMA50":     ("CCI(20)<-100 Toparlanma + EMA50", MR_GATE),
    "UO_TURNUP":              ("Ultimate Osc<30 Dönüşü", MR_GATE),
    "DONCHIAN_BREAKOUT_ADX":  ("Donchian(20) Kırılım + ADX>25", TREND_GATE),
    "BB_KC_SQUEEZE_BREAK":    ("BB-KC Sıkışma + Üst Bant Kırılımı", TREND_GATE),
    "VORTEX_CROSS_ADX":       ("Vortex +VI>-VI Kesişim + ADX>20", TREND_GATE),
    "AO_ZEROCROSS_MFI50":     ("Awesome Osc Sıfır Kes + MFI>50", TREND_GATE),
    "VWAP_RECLAIM_OBV":       ("VWAP Geri Kazanım + OBV>EMA21", TREND_GATE),
    "EMA20_PULLBACK_EFI":     ("EMA20 Pullback + EFI(13) Sıfır Kes", TREND_GATE),
    "HULL_TURN_CHOP":         ("Hull MA(21) Dönüş + Chop<61.8", TREND_GATE),
}

# ─── YENİ GÖSTERGE YARDIMCILARI (GOSTERGELER.HTML formülleri) ─────────────────

def calc_wma(s: pd.Series, n: int) -> pd.Series:
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)

def calc_hma(s: pd.Series, n: int) -> pd.Series:
    half = max(2, n // 2)
    sq = max(2, int(math.sqrt(n)))
    return calc_wma(2.0 * calc_wma(s, half) - calc_wma(s, n), sq)

def calc_mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    rmf = tp * df["volume"]
    delta = tp.diff()
    pos = rmf.where(delta > 0, 0.0).rolling(n).sum()
    neg = rmf.where(delta < 0, 0.0).rolling(n).sum()
    return (100.0 - 100.0 / (1.0 + pos / neg.replace(0, np.nan))).fillna(50.0)

def calc_stochrsi(df: pd.DataFrame, rsi_len=14, stoch_len=14, k=3, d=3):
    rsi = calc_rsi(df["close"], rsi_len)
    lo = rsi.rolling(stoch_len).min()
    hi = rsi.rolling(stoch_len).max()
    st = ((rsi - lo) / (hi - lo).replace(0, np.nan)) * 100.0
    kk = st.rolling(k).mean()
    dd = kk.rolling(d).mean()
    return kk, dd

def calc_wpr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    hh = df["high"].rolling(n).max()
    ll = df["low"].rolling(n).min()
    return -100.0 * (hh - df["close"]) / (hh - ll).replace(0, np.nan)

def calc_bbp(df: pd.DataFrame, n: int = 13) -> pd.Series:
    ema = calc_ema(df["close"], n)
    return (df["high"] - ema) + (df["low"] - ema)

def calc_cci(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    sma = tp.rolling(n).mean()
    md = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - sma) / (0.015 * md.replace(0, np.nan))

def calc_uo(df: pd.DataFrame, p1=7, p2=14, p3=28) -> pd.Series:
    pc = df["close"].shift(1)
    bp = df["close"] - pd.concat([df["low"], pc], axis=1).min(axis=1)
    tr = pd.concat([df["high"], pc], axis=1).max(axis=1) - pd.concat([df["low"], pc], axis=1).min(axis=1)
    def avg(p):
        return bp.rolling(p).sum() / tr.rolling(p).sum().replace(0, np.nan)
    a1, a2, a3 = avg(p1), avg(p2), avg(p3)
    return 100.0 * (4.0 * a1 + 2.0 * a2 + a3) / 7.0

def _true_range(df: pd.DataFrame) -> pd.Series:
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

def calc_adx(df: pd.DataFrame, n: int = 14):
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = _true_range(df)
    atr = tr.ewm(alpha=1.0 / n, adjust=False).mean()
    pdi = 100.0 * plus_dm.ewm(alpha=1.0 / n, adjust=False).mean() / atr.replace(0, np.nan)
    mdi = 100.0 * minus_dm.ewm(alpha=1.0 / n, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100.0 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.ewm(alpha=1.0 / n, adjust=False).mean()
    return adx, pdi, mdi

def calc_vortex(df: pd.DataFrame, n: int = 14):
    tr_sum = _true_range(df).rolling(n).sum()
    vm_p = (df["high"] - df["low"].shift(1)).abs().rolling(n).sum()
    vm_m = (df["low"] - df["high"].shift(1)).abs().rolling(n).sum()
    return vm_p / tr_sum.replace(0, np.nan), vm_m / tr_sum.replace(0, np.nan)

def calc_ao(df: pd.DataFrame, fast=5, slow=34) -> pd.Series:
    hl2 = (df["high"] + df["low"]) / 2.0
    return hl2.rolling(fast).mean() - hl2.rolling(slow).mean()

def calc_obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0.0)
    return (direction * df["volume"]).cumsum()

def calc_efi(df: pd.DataFrame, n: int = 13) -> pd.Series:
    return (df["close"].diff() * df["volume"]).ewm(span=n, adjust=False).mean()

def calc_chop(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tr_sum = _true_range(df).rolling(n).sum()
    rng = (df["high"].rolling(n).max() - df["low"].rolling(n).min()).replace(0, np.nan)
    return 100.0 * np.log10(tr_sum / rng) / np.log10(n)

def calc_vwap_daily(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    day = df["time"].dt.floor("1D")
    cum_v = df["volume"].groupby(day).cumsum()
    cum_vp = (tp * df["volume"]).groupby(day).cumsum()
    return cum_vp / cum_v.replace(0, np.nan)

def calc_keltner(df: pd.DataFrame, n=20, atr_n=20, mult=1.5):
    basis = calc_ema(df["close"], n)
    atr = calc_atr(df, atr_n)
    return basis + mult * atr, basis - mult * atr

# ─── YENİ STRATEJİ SİNYAL ÜRETİCİLERİ ─────────────────────────────────────────

def generate_signals_v2(df: pd.DataFrame, code: str) -> pd.Series:
    close = df["close"]
    sig = pd.Series(False, index=df.index)

    if code == "CONNORS_RSI3_EMA200":
        rsi3 = calc_rsi(close, 3)
        ema200 = calc_ema(close, 200)
        sig = (rsi3 < 15.0) & (close > ema200)

    elif code == "MFI_TURNUP_EMA50":
        mfi = calc_mfi(df, 14)
        ema50 = calc_ema(close, 50)
        sig = (mfi.shift(1) <= 20.0) & (mfi > mfi.shift(1)) & (close > ema50)

    elif code == "STOCHRSI_KD_EMA200":
        kk, dd = calc_stochrsi(df, 14, 14, 3, 3)
        ema200 = calc_ema(close, 200)
        sig = (kk.shift(1) < 20.0) & (kk > dd) & (kk.shift(1) <= dd.shift(1)) & (close > ema200)

    elif code == "WPR_BBP_TURN":
        wpr = calc_wpr(df, 14)
        bbp = calc_bbp(df, 13)
        sig = (wpr.shift(1) <= -90.0) & (wpr > wpr.shift(1)) & (bbp > bbp.shift(1))

    elif code == "CCI_RECOVERY_EMA50":
        cci = calc_cci(df, 20)
        ema50 = calc_ema(close, 50)
        sig = (cci.shift(1) <= -100.0) & (cci > cci.shift(1)) & (close > ema50)

    elif code == "UO_TURNUP":
        uo = calc_uo(df, 7, 14, 28)
        sig = (uo.shift(1) <= 30.0) & (uo > uo.shift(1))

    elif code == "DONCHIAN_BREAKOUT_ADX":
        hh = df["high"].rolling(20).max().shift(1)
        adx, _, _ = calc_adx(df, 14)
        breakout = (close > hh) & (close.shift(1) <= hh.shift(1))
        sig = breakout & (adx > 25.0)

    elif code == "BB_KC_SQUEEZE_BREAK":
        upper, lower, _, _ = calc_bollinger_vwap(df, 20, 2.0)
        kc_up, kc_lo = calc_keltner(df, 20, 20, 1.5)
        squeeze = (upper < kc_up) & (lower > kc_lo)
        squeeze_recent = squeeze.shift(1).rolling(5).max().fillna(0).astype(bool)
        brk = (close > upper) & (close.shift(1) <= upper.shift(1))
        sig = squeeze_recent & brk

    elif code == "VORTEX_CROSS_ADX":
        vip, vim = calc_vortex(df, 14)
        adx, _, _ = calc_adx(df, 14)
        sig = (vip.shift(1) <= vim.shift(1)) & (vip > vim) & (adx > 20.0)

    elif code == "AO_ZEROCROSS_MFI50":
        ao = calc_ao(df, 5, 34)
        mfi = calc_mfi(df, 14)
        sig = (ao.shift(1) <= 0.0) & (ao > 0.0) & (mfi > 50.0)

    elif code == "VWAP_RECLAIM_OBV":
        vwap = calc_vwap_daily(df)
        obv = calc_obv(df)
        obv_ema = calc_ema(obv, 21)
        reclaim = (close.shift(1) <= vwap.shift(1)) & (close > vwap)
        sig = reclaim & (obv > obv_ema)

    elif code == "EMA20_PULLBACK_EFI":
        ema20 = calc_ema(close, 20)
        ema50 = calc_ema(close, 50)
        efi = calc_efi(df, 13)
        touch = (df["low"] <= ema20 * 1.005) & (close >= ema20)
        efi_up = (efi.shift(1) <= 0.0) & (efi > 0.0)
        sig = (ema20 > ema50) & touch & efi_up

    elif code == "HULL_TURN_CHOP":
        hull = calc_hma(close, 21)
        chop = calc_chop(df, 14)
        turn_up = (hull.shift(1) <= hull.shift(2)) & (hull > hull.shift(1))
        sig = turn_up & (close > hull) & (chop < 61.8)

    return sig.fillna(False)

# ─── MUHAFAZAKAR BACKTEST MOTORU ──────────────────────────────────────────────

def simulate_conservative(df: pd.DataFrame, signals: pd.Series,
                          tp_pct: float, sl_pct: float, max_bars: int = 48):
    """Giriş sonraki bar açılışından; aynı barda çift eşleşmede SL öncelikli; gap farkında."""
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    sig = signals.values
    n = len(df)

    trades = []
    pos = False
    entry = 0.0
    entry_idx = -1

    for i in range(n):
        if pos and i >= entry_idx:
            target = entry * (1.0 + tp_pct / 100.0)
            stop = entry * (1.0 - sl_pct / 100.0)
            gap_up = opens[i] >= target
            gap_dn = opens[i] <= stop
            hit_sl = lows[i] <= stop
            hit_tp = highs[i] >= target
            timeout = (i - entry_idx) >= max_bars
            if gap_dn:
                exit_p = opens[i]          # açılış stopun altında → daha kötü fiyat
                reason = "sl"
            elif gap_up:
                exit_p = opens[i]
                reason = "tp"
            elif hit_sl:
                exit_p = stop              # aynı barda ikisi de değdiyse SL öncelikli
                reason = "sl"
            elif hit_tp:
                exit_p = target
                reason = "tp"
            elif timeout:
                exit_p = closes[i]
                reason = "time"
            else:
                exit_p = None
            if exit_p is not None:
                gross = (exit_p - entry) / entry * 100.0
                net = gross - COMMISSION_PCT
                trades.append({"net": net, "win": net > 0, "reason": reason})
                pos = False

        if (not pos) and (i < n - 1) and sig[i]:
            pos = True
            entry = opens[i + 1]
            entry_idx = i + 1

    if pos:
        gross = (closes[-1] - entry) / entry * 100.0
        trades.append({"net": gross - COMMISSION_PCT, "win": (gross - COMMISSION_PCT) > 0, "reason": "eod"})

    if not trades:
        return {"trades": 0, "wins": 0, "net_total": 0.0, "gross_gain": 0.0,
                "gross_loss": 0.0, "pf": 0.0, "max_dd": 0.0}

    nets = np.array([t["net"] for t in trades])
    wins = int((nets > 0).sum())
    gg = float(nets[nets > 0].sum())
    gl = float(abs(nets[nets <= 0].sum()))
    pf = gg / gl if gl > 0 else 99.9
    eq = np.concatenate([[0.0], np.cumsum(nets)])
    peak = np.maximum.accumulate(eq)
    max_dd = float((peak - eq).max())
    return {"trades": len(trades), "wins": wins, "net_total": round(float(nets.sum()), 2),
            "gross_gain": round(gg, 2), "gross_loss": round(gl, 2),
            "pf": round(pf, 2), "max_dd": round(max_dd, 2)}

# ─── ANA TEST MATRİSİ ─────────────────────────────────────────────────────────

def run_lab():
    all_strats = list(STRATEGY_META.keys())
    print("=" * 100)
    print("  🔬 SPOT GÖSTERGE KOMBİNASYON LABORATUVARI v2 — REHBER GÖSTERGELERİ GENİŞ TARAMA")
    print("=" * 100)
    print(f"Coinler ({len(ALL_SYMBOLS)}): {', '.join(ALL_SYMBOLS)}")
    print(f"Stratejiler: {len(all_strats)} (7 baz şampiyon + 13 yeni kombinasyon)")
    print("Zaman dilimleri: 5m (TP1.5/SL0.9) | 15m (TP2.2/SL1.2) | 1h (TP4.0/SL2.0) — 1000 bar/coin")
    print("Motor: giriş sonraki bar açılışından, çift eşleşmede SL öncelikli, %0.08 round-trip komisyon, 48 bar timeout")
    n_configs = len(all_strats) * len(TIMEFRAMES)
    print(f"⚠️  Çoklu test uyarısı: N={n_configs} strateji-konfigürasyon denenecek; "
          f"E[max] ≈ √(2·ln N) = {math.sqrt(2 * math.log(n_configs)):.2f} — şansa bağlı iyi görünenler olabilir.")
    print("-" * 100)

    rows = []  # per (strat, tf, coin)
    fetch_fail = 0
    for tf, (tp, sl) in TIMEFRAMES:
        print(f"\n▶ Zaman dilimi {tf} işleniyor (TP %{tp} / SL %{sl})...")
        for sym in ALL_SYMBOLS:
            try:
                df = fetch_binance_klines(sym, interval=tf, limit=1000)
                if len(df) < 400:
                    fetch_fail += 1
                    continue
            except Exception as e:
                print(f"   ⚠️ {sym} veri hatası: {e}")
                fetch_fail += 1
                continue
            for code in all_strats:
                if code in {"KDJ_EMA50", "SUPERTREND_WAVETREND", "BOLLINGER_VWAP_EXPANSION",
                            "KDJ_RSI_CONFLUENCE", "ZLMACD_EMA_MOMENTUM", "STC_SCHAFF_CYCLE",
                            "FISHER_DONCHIAN"}:
                    sigs = generate_signals(df, code, tf)
                else:
                    sigs = generate_signals_v2(df, code)
                if int(sigs.sum()) < 1:
                    continue
                full = simulate_conservative(df, sigs, tp, sl)
                half1 = simulate_conservative(df.iloc[:500].reset_index(drop=True),
                                              sigs.iloc[:500].reset_index(drop=True), tp, sl)
                half2 = simulate_conservative(df.iloc[500:].reset_index(drop=True),
                                              sigs.iloc[500:].reset_index(drop=True), tp, sl)
                rows.append({
                    "timeframe": tf, "symbol": sym, "strategy_code": code,
                    "strategy_name": STRATEGY_META[code][0], "wr_gate": STRATEGY_META[code][1],
                    "signals": int(sigs.sum()),
                    "trades": full["trades"], "wins": full["wins"],
                    "win_rate": round(100.0 * full["wins"] / full["trades"], 1) if full["trades"] else 0.0,
                    "net_total": full["net_total"], "pf": full["pf"], "max_dd": full["max_dd"],
                    "gross_gain": full["gross_gain"], "gross_loss": full["gross_loss"],
                    "half1_net": half1["net_total"], "half2_net": half2["net_total"],
                })

    if not rows:
        print("❌ Hiç sonuç üretilmedi.")
        return

    res = pd.DataFrame(rows)

    # ── Strateji × TF toplu değerlendirme ──
    agg = res.groupby(["timeframe", "strategy_code"]).apply(lambda g: pd.Series({
        "strategy_name": g["strategy_name"].iloc[0],
        "wr_gate": g["wr_gate"].iloc[0],
        "trades": int(g["trades"].sum()),
        "win_rate": round(100.0 * g["wins"].sum() / max(1, g["wins"].sum() + (g["trades"].sum() - g["wins"].sum())), 1),
        "net_total": round(g["net_total"].sum(), 2),
        "pf": round(g["gross_gain"].sum() / g["gross_loss"].sum(), 2) if g["gross_loss"].sum() > 0 else 99.9,
        "coins_positive": int((g["net_total"] > 0).sum()),
        "coins_traded": int((g["trades"] > 0).sum()),
        "avg_dd": round(g["max_dd"].mean(), 2),
        "half1_net": round(g["half1_net"].sum(), 2),
        "half2_net": round(g["half2_net"].sum(), 2),
    }), include_groups=False).reset_index()

    agg = agg.sort_values("pf", ascending=False)
    eligible = agg[agg["trades"] >= 20]

    print("\n" + "=" * 100)
    print("  📊 STRATEJİ × ZAMAN DİLİMİ TOPLU SONUÇLAR (≥20 işlem şartıyla sıralı, PF'ye göre)")
    print("=" * 100)
    hdr = f"{'TF':<5} {'Strateji':<38} {'İşlem':>6} {'WR%':>6} {'PF':>6} {'Net%':>8} {'+Coin':>6} {'DD%':>6} {'H1%':>8} {'H2%':>8}"
    print(hdr)
    print("-" * 100)
    for _, r in eligible.iterrows():
        h1 = f"{r['half1_net']:+.1f}" if r["half1_net"] else "—"
        h2 = f"{r['half2_net']:+.1f}" if r["half2_net"] else "—"
        print(f"{r['timeframe']:<5} {r['strategy_name'][:38]:<38} {r['trades']:>6} {r['win_rate']:>6.1f} "
              f"{r['pf']:>6.2f} {r['net_total']:>+8.2f} {r['coins_positive']:>3}/{r['coins_traded']:<2} "
              f"{r['avg_dd']:>6.2f} {h1:>8} {h2:>8}")

    # ── Kabul kriterleri (Hard Guardrails) ──
    print("\n" + "=" * 100)
    print("  🚦 KABUL KRİTERLERİ KONTROLÜ (skill Hard Guardrails: ≥20 işlem, WR eşiği, PF≥1.5, Net>0, ≥3 coin)")
    print("=" * 100)
    promoted = []
    for _, r in eligible.iterrows():
        checks = {
            "işlem≥20": r["trades"] >= 20,
            "WR": r["win_rate"] >= r["wr_gate"],
            "PF≥1.5": r["pf"] >= 1.5,
            "Net>0": r["net_total"] > 0,
            "≥3 coin": r["coins_positive"] >= 3,
        }
        passed = all(checks.values())
        flags = " ".join("✅" if v else "❌" for v in checks.values())
        robust = "SAĞLAM" if (r["half1_net"] > 0 and r["half2_net"] > 0) else "rejime-bağımlı"
        status = "🎉 TERFİ ADAYI" if passed else "—"
        print(f"{status:<14} {r['timeframe']:<4} {r['strategy_name'][:40]:<40} {flags}  "
              f"(WR {r['win_rate']:.1f}/{r['wr_gate']:.0f}, PF {r['pf']:.2f}, Net {r['net_total']:+.2f}%, "
              f"split-half: {robust})")
        if passed:
            promoted.append((r["timeframe"], r["strategy_code"], r))

    # ── En iyi coin kombinasyonları ──
    print("\n" + "=" * 100)
    print("  🏆 EN İYİ 15 COİN × STRATEJİ KOMBİNASYONU (≥6 işlem, net kâra göre)")
    print("=" * 100)
    top_coins = res[res["trades"] >= 6].sort_values("net_total", ascending=False).head(15)
    for _, r in top_coins.iterrows():
        print(f"{r['symbol']:<11} {r['timeframe']:<4} {r['strategy_name'][:40]:<40} "
              f"İşlem {r['trades']:>3}  WR %{r['win_rate']:>5.1f}  PF {r['pf']:>5.2f}  "
              f"Net {r['net_total']:>+7.2f}%  DD %{r['max_dd']:.2f}")

    if not promoted:
        print("\nℹ️ Bu turda tüm kriterleri geçen (TERFİ ADAYI) kombinasyon yok. "
              "Kısmen geçenler 'YENİDEN TEST ET' havuzuna düşer (parametre aralığı daraltma önerisi aşağıda).")
        # kısmi geçenler: 4/5 kriter
        partial = []
        for _, r in eligible.iterrows():
            checks = [r["trades"] >= 20, r["win_rate"] >= r["wr_gate"], r["pf"] >= 1.5,
                      r["net_total"] > 0, r["coins_positive"] >= 3]
            if sum(checks) >= 4:
                partial.append((sum(checks), r))
        partial.sort(key=lambda x: (-x[0], -x[1]["pf"]))
        if partial:
            print("\n  Kısmen geçenler (4/5 kriter) — YENİDEN TEST havuzu:")
            for score, r in partial[:8]:
                missing = [n for n, v in zip(["işlem", "WR", "PF", "Net", "coin"], [
                    r["trades"] >= 20, r["win_rate"] >= r["wr_gate"], r["pf"] >= 1.5,
                    r["net_total"] > 0, r["coins_positive"] >= 3]) if not v]
                print(f"   {r['timeframe']:<4} {r['strategy_name'][:42]:<42} Eksik: {','.join(missing)} "
                      f"(WR {r['win_rate']:.1f}, PF {r['pf']:.2f}, Net {r['net_total']:+.2f}%)")
    else:
        print(f"\n✅ {len(promoted)} kombinasyon tüm sert kriterleri geçti: " +
              ", ".join(f"{c[1]}({c[0]})" for c in promoted))

    # ── JSON çıktısı ──
    out = {
        "meta": {
            "generated_at": pd.Timestamp.now().isoformat(),
            "symbols": ALL_SYMBOLS, "fetch_failures": fetch_fail,
            "timeframes": {tf: {"tp": tp, "sl": sl} for tf, (tp, sl) in TIMEFRAMES},
            "commission_pct": COMMISSION_PCT,
            "engine": "next-bar-open entry, SL-priority same-bar, 48-bar timeout, gap-aware",
            "n_strategy_configs": n_configs,
            "multiple_testing_note": f"E[max]≈sqrt(2*ln N)={math.sqrt(2*math.log(n_configs)):.2f} (N={n_configs})",
        },
        "strategy_aggregates": agg.to_dict(orient="records"),
        "per_coin_results": rows,
    }
    out_file = Path("outputs/spot_indicator_combos_lab_v2.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n💾 Detaylı log kaydedildi: {out_file}")

if __name__ == "__main__":
    run_lab()
