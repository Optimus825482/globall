"""
SPOT GÖSTERGE KOMBİNASYON LABORATUVARI v4 — ARŞİV DERİN TARAMA TURU 3
=====================================================================
GOSTERGELER.HTML arşivinden v2+v3'te taranmamış 20 yeni kombinasyon.
Motor aynı: sonraki bar açılış girişi, SL öncelikli çift eşleşme, gap koruması,
%0.08 round-trip komisyon, 48 bar timeout, split-half rejim kontrolü.
Kriterler: ≥20 işlem, WR≥%60 (dip) / %55 (trend), PF≥1.5, Net>0, ≥3 coin pozitif.

YENİ 20 KOMBİNASYON:
  Mean-Reversion (dip dönüş):
   1.  Düz Stochastic(14,3,3) K>D yukarı kesişim (<20'den) + EMA50
   2.  Connors RSI(2) < 10 ekstrem + EMA200 (kanonik RSI2)
   3.  Relative Vigor Index(10) negatiften sinyal kesişimi + EMA50
   4.  SMI Ergodik(5,20,5) derin dipten sinyal kesişimi + EMA200
   5.  VWAP -1σ sapma bandı geri kazanımı + OBV > EMA21 (institutional seviye MR)
   6.  Günlük Klasik Pivot (P) geri kazanımı + hacim teyidi (yeni kategori: referans seviye)
   7.  Know Sure Thing (KST) negatiften sinyal kesişimi + EMA200
   8.  Balance of Power SMA(14) sıfır üstü dönüşü
   9.  Ease of Movement(14) sıfır üstü kesişim + EMA50
   10. WaveTrend dip + Fisher ekstrem confluence (iki bağımsız osilatör aynı anda)
   11. KDJ J<15 dönüş + MFI<25 dönüş (fiyat+hacim çift aşırı satım)
   12. Alligator hizalanması (lips>teeth>jaw yükselen) + lips üstü kapanış
  Trend / Kırılım:
   13. Choppiness 38.2 altına rejim geçişi (range→trend) + EMA50
   14. Bollinger BandWidth p10 taban sıkışması + üst bant kırılımı (BBW tanımlı squeeze)
   15. Hacim kuruması (VolOsc<-20) sonrası hacimli BB üst kırılımı
   16. SuperTrend boğa + ADX yükseliyor (>20)
   17. Williams Fraktal yüksek kırılımı + RVOL>1.2
   18. RCI Şeridi hizası (9>26>52 hepsi yükselen) + EMA50
   19. Ichimoku Chikou span momentum teyidi + Kijun üstü
   20. McGinley Dynamic yukarı kesişim + MD yükseliyor (düşük whipsaw trend çizgisi)
"""
import sys
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from test_advanced_spot_strategies import fetch_binance_klines
from test_indicator_combos_lab import (
    simulate_conservative, calc_ema, calc_atr, calc_rsi, calc_kdj,
    calc_supertrend, calc_wavetrend, calc_bollinger_vwap, calc_chop, calc_adx,
    calc_vwap_daily, calc_obv, ALL_SYMBOLS, TIMEFRAMES, COMMISSION_PCT,
)
from test_indicator_combos_lab_v3 import calc_rci, calc_rvol, calc_vol_osc

sys.stdout.reconfigure(encoding="utf-8")

MR_GATE, TREND_GATE = 60.0, 55.0
STRATEGY_META = {
    "STOCH_KD_EMA50":         ("Düz Stochastic K>D Kesişim + EMA50", MR_GATE),
    "RSI2_EXTREME_EMA200":    ("Connors RSI(2)<10 Ekstrem + EMA200", MR_GATE),
    "RVI_SIGNAL_CROSS":       ("RVI(10) Negatiften Sinyal Kes + EMA50", MR_GATE),
    "SMI_ERGODIC_TURN":       ("SMI Ergodik Derin Dip Kes + EMA200", MR_GATE),
    "VWAP_DEV_RECLAIM":       ("VWAP -1σ Bandı Geri Kazanım + OBV", MR_GATE),
    "DAILY_PIVOT_RECLAIM":    ("Günlük Pivot P Geri Kazanımı + Hacim", MR_GATE),
    "KST_ZERO_TURN":          ("KST Negatiften Sinyal Kes + EMA200", MR_GATE),
    "BOP_SMA_TURN":           ("Balance of Power SMA Sıfır Dönüşü", MR_GATE),
    "EOM_ZERO_CROSS":         ("Ease of Movement Sıfır Üstü + EMA50", MR_GATE),
    "WT_FISHER_CONFLUENCE":   ("WaveTrend Dip + Fisher Ekstrem Confluence", MR_GATE),
    "KDJ_MFI_CONFLUENCE":     ("KDJ J<15 + MFI<25 Çift Dönüş", MR_GATE),
    "GATOR_ALIGN":            ("Alligator Hizalanması + Lips Üstü", TREND_GATE),
    "CHOP_REGIME_SWITCH":     ("CHOP 38.2 Rejim Geçişi + EMA50", TREND_GATE),
    "BBW_SQUEEZE_BREAK":      ("BBW p10 Taban Sıkışma + Üst Kırılım", TREND_GATE),
    "VOL_DRY_BREAKOUT":       ("Hacim Kuruması Sonrası BB Kırılımı", TREND_GATE),
    "SUPERTREND_ADX_RISING":  ("SuperTrend Boğa + ADX Yükseliyor", TREND_GATE),
    "FRACTAL_BREAK_RVOL":     ("Williams Fraktal Kırılımı + RVOL", TREND_GATE),
    "RCI_RIBBON_ALIGN":       ("RCI Şeridi 9>26>52 Hizası + EMA50", TREND_GATE),
    "CHIKOU_SPAN_CROSS":      ("Ichimoku Chikou Teyidi + Kijun Üstü", TREND_GATE),
    "MCGINLEY_CROSS":         ("McGinley Dynamic Yukarı Kesişim", TREND_GATE),
}

# ─── YENİ GÖSTERGE YARDIMCILARI ───────────────────────────────────────────────

def calc_fisher4(df: pd.DataFrame, period: int = 10) -> pd.Series:
    """Fisher Transform (kanonik: 0.66/0.67 özyinelemeli, yumuşatmasız)."""
    med = (df["high"] + df["low"]) / 2.0
    lo = med.rolling(period).min()
    hi = med.rolling(period).max()
    pos = ((med - lo) / (hi - lo).replace(0, np.nan)).fillna(0.5).values
    vals = np.zeros(len(df))
    fish = np.zeros(len(df))
    for i in range(1, len(df)):
        vals[i] = max(min(0.66 * (2.0 * pos[i] - 0.5) + 0.67 * vals[i - 1], 0.999), -0.999)
        fish[i] = 0.5 * np.log((1 + vals[i]) / (1 - vals[i])) + 0.5 * fish[i - 1]
    return pd.Series(fish, index=df.index)

def calc_stochastic_s(df: pd.DataFrame, k_len=14, k_smooth=3, d_smooth=3):
    raw = ((df["close"] - df["low"].rolling(k_len).min()) /
           (df["high"].rolling(k_len).max() - df["low"].rolling(k_len).min()).replace(0, np.nan)) * 100.0
    k = raw.rolling(k_smooth).mean()
    d = k.rolling(d_smooth).mean()
    return k, d

def calc_rvi(df: pd.DataFrame, n=10, sig=4):
    a = df["close"] - df["open"]
    e = df["high"] - df["low"]
    num = ((a + 2 * a.shift(1) + 2 * a.shift(2) + a.shift(3)) / 6.0).rolling(n).mean()
    den = ((e + 2 * e.shift(1) + 2 * e.shift(2) + e.shift(3)) / 6.0).rolling(n).mean()
    rvi = num / den.replace(0, np.nan)
    signal = (rvi + 2 * rvi.shift(1) + 2 * rvi.shift(2) + rvi.shift(3)) / 6.0
    return rvi, signal

def calc_smi_ergodic(df: pd.DataFrame, fast=5, slow=20, sig=5):
    chg = df["close"].diff()
    smi = 100.0 * (chg.ewm(span=fast, adjust=False).mean().ewm(span=slow, adjust=False).mean() /
                   chg.abs().ewm(span=fast, adjust=False).mean().ewm(span=slow, adjust=False).mean().replace(0, np.nan))
    return smi, smi.ewm(span=sig, adjust=False).mean()

def calc_vwap_dev_band(df: pd.DataFrame):
    """Günlük VWAP ± 1σ (σ = hacim ağırlıklı karesel sapma, gün başı sıfırlanır)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    day = df["time"].dt.floor("1D")
    cv = df["volume"].groupby(day).cumsum()
    vwap = ((tp * df["volume"]).groupby(day).cumsum()) / cv.replace(0, np.nan)
    dev2 = (((tp - vwap) ** 2) * df["volume"]).groupby(day).cumsum()
    sigma = np.sqrt(dev2 / cv.replace(0, np.nan))
    return vwap, sigma

def calc_daily_pivot(df: pd.DataFrame) -> pd.Series:
    """Önceki günün Klasik Pivot'u: P = (H + L + C) / 3 (gün bazında ileri doldurulmuş)."""
    day = df["time"].dt.floor("1D")
    daily = df.groupby(day).agg(h=("high", "max"), l=("low", "min"), c=("close", "last"))
    daily["p"] = (daily["h"] + daily["l"] + daily["c"]) / 3.0
    prev_p = daily["p"].shift(1)
    return day.map(prev_p).astype(float)

def calc_kst(close: pd.Series) -> pd.Series:
    def roc(s, n): return s.pct_change(n) * 100.0
    r1 = roc(close, 10).rolling(10).mean()
    r2 = roc(close, 15).rolling(10).mean()
    r3 = roc(close, 20).rolling(10).mean()
    r4 = roc(close, 30).rolling(15).mean()
    kst = r1 + 2 * r2 + 3 * r3 + 4 * r4
    return kst, kst.rolling(9).mean()

def calc_bop_sma(df: pd.DataFrame, n=14) -> pd.Series:
    bop = (df["close"] - df["open"]) / (df["high"] - df["low"]).replace(0, np.nan)
    return bop.rolling(n).mean()

def calc_eom(df: pd.DataFrame, n=14, divisor=10000.0) -> pd.Series:
    hl2 = (df["high"] + df["low"]) / 2.0
    dist = hl2 - hl2.shift(1)
    box = (df["volume"] / divisor) / (df["high"] - df["low"]).replace(0, np.nan)
    return (dist / box.replace(0, np.nan)).rolling(n).mean()

def _rma(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False).mean()

def calc_alligator(df: pd.DataFrame):
    hl2 = (df["high"] + df["low"]) / 2.0
    jaw = _rma(hl2, 13).shift(8)
    teeth = _rma(hl2, 8).shift(5)
    lips = _rma(hl2, 5).shift(3)
    return jaw, teeth, lips

def calc_bbw_floor(df: pd.DataFrame, bb_len=20, bb_mult=2.0, floor_n=200, q=0.10):
    upper, lower, bw, _ = calc_bollinger_vwap(df, bb_len, bb_mult)
    return bw, bw.rolling(floor_n).quantile(q)

def calc_fractal_highs(df: pd.DataFrame, wings=2) -> pd.Series:
    """Williams yukarı fraktalı: H, ikişer sol/sağ komşusundan yüksek → 2 bar sonra teyitli."""
    h = df["high"].values
    last_fh = np.full(len(df), np.nan)
    cur = np.nan
    for i in range(wings, len(df) - wings):
        w = h[i - wings: i + wings + 1]
        if h[i] == w.max() and (w == h[i]).sum() == 1:
            cur = h[i]
        last_fh[i] = cur  # i+2 teyidi otomatik: fraktal i'de oluştuysa i+2'den itibaren bilinir
    return pd.Series(last_fh, index=df.index)

def calc_mcginley(close: pd.Series, n=14) -> pd.Series:
    c = close.values
    md = np.full(len(c), np.nan)
    md[n] = c[n]
    for i in range(n + 1, len(c)):
        prev = md[i - 1]
        md[i] = prev + (c[i] - prev) / (n * (c[i] / prev) ** 4) if prev > 0 else c[i]
    return pd.Series(md, index=close.index)

# ─── SİNYAL ÜRETİCİLERİ ───────────────────────────────────────────────────────

def generate_signals_v4(df: pd.DataFrame, code: str) -> pd.Series:
    close = df["close"]
    sig = pd.Series(False, index=df.index)

    if code == "STOCH_KD_EMA50":
        k, d = calc_stochastic_s(df, 14, 3, 3)
        sig = (k.shift(1) < 20.0) & (k > d) & (k.shift(1) <= d.shift(1)) & (close > calc_ema(close, 50))

    elif code == "RSI2_EXTREME_EMA200":
        rsi2 = calc_rsi(close, 2)
        sig = (rsi2 < 10.0) & (close > calc_ema(close, 200))

    elif code == "RVI_SIGNAL_CROSS":
        rvi, rsig = calc_rvi(df, 10, 4)
        sig = (rvi.shift(1) < rsig.shift(1)) & (rvi > rsig) & (rvi.shift(1) < 0.0) & (close > calc_ema(close, 50))

    elif code == "SMI_ERGODIC_TURN":
        smi, ssig = calc_smi_ergodic(df, 5, 20, 5)
        sig = (smi.shift(1) < ssig.shift(1)) & (smi > ssig) & (smi.shift(1) < -20.0) & (close > calc_ema(close, 200))

    elif code == "VWAP_DEV_RECLAIM":
        vwap, sigma = calc_vwap_dev_band(df)
        band = vwap - sigma
        obv = calc_obv(df)
        reclaim = (close.shift(1) <= band.shift(1)) & (close > band)
        sig = reclaim & (obv > calc_ema(obv, 21))

    elif code == "DAILY_PIVOT_RECLAIM":
        pivot = calc_daily_pivot(df)
        vol_ok = df["volume"] > df["volume"].rolling(20).mean()
        reclaim = (close.shift(1) <= pivot.shift(1)) & (close > pivot)
        sig = reclaim & vol_ok

    elif code == "KST_ZERO_TURN":
        kst, ksig = calc_kst(close)
        sig = (kst.shift(1) < ksig.shift(1)) & (kst > ksig) & (kst.shift(1) < 0.0) & (close > calc_ema(close, 200))

    elif code == "BOP_SMA_TURN":
        bop = calc_bop_sma(df, 14)
        sig = (bop.shift(1) <= 0.0) & (bop > 0.0) & (bop > bop.shift(1))

    elif code == "EOM_ZERO_CROSS":
        eom = calc_eom(df, 14)
        sig = (eom.shift(1) <= 0.0) & (eom > 0.0) & (close > calc_ema(close, 50))

    elif code == "WT_FISHER_CONFLUENCE":
        wt1, wt2 = calc_wavetrend(df, 10, 21)
        fish = calc_fisher4(df, 10)
        wt_dip = (wt1.shift(1) <= -40.0) & (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1))
        fish_ext = fish < -1.0
        sig = wt_dip & fish_ext

    elif code == "KDJ_MFI_CONFLUENCE":
        _, _, j = calc_kdj(df, 9, 3)
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        rmf = tp * df["volume"]
        delta = tp.diff()
        pos = rmf.where(delta > 0, 0.0).rolling(14).sum()
        neg = rmf.where(delta < 0, 0.0).rolling(14).sum()
        mfi = (100.0 - 100.0 / (1.0 + pos / neg.replace(0, np.nan))).fillna(50.0)
        j_turn = (j.shift(1) <= 15.0) & (j > j.shift(1))
        mfi_turn = (mfi.shift(1) <= 25.0) & (mfi > mfi.shift(1))
        sig = j_turn & mfi_turn

    elif code == "GATOR_ALIGN":
        jaw, teeth, lips = calc_alligator(df)
        aligned = (lips > teeth) & (teeth > jaw) & (lips > lips.shift(1)) & (teeth > teeth.shift(1)) & (jaw > jaw.shift(1))
        sig = aligned & (close > lips) & (close.shift(1) <= lips.shift(1))

    elif code == "CHOP_REGIME_SWITCH":
        chop = calc_chop(df, 14)
        sig = (chop.shift(1) >= 38.2) & (chop < 38.2) & (chop.shift(1) > 45.0) & (close > calc_ema(close, 50))

    elif code == "BBW_SQUEEZE_BREAK":
        bw, floor = calc_bbw_floor(df, 20, 2.0, 200, 0.10)
        upper, lower, _, _ = calc_bollinger_vwap(df, 20, 2.0)
        dry = (bw < floor).shift(1).rolling(5).max().fillna(0).astype(bool)
        brk = (close > upper) & (close.shift(1) <= upper.shift(1))
        sig = dry & brk

    elif code == "VOL_DRY_BREAKOUT":
        vo = calc_vol_osc(df, 5, 10)
        upper, lower, _, _ = calc_bollinger_vwap(df, 20, 2.0)
        dry = (vo < -20.0).shift(1).rolling(5).max().fillna(0).astype(bool)
        brk = (close > upper) & (close.shift(1) <= upper.shift(1))
        sig = dry & brk & (vo > 0.0)

    elif code == "SUPERTREND_ADX_RISING":
        st = calc_supertrend(df, 10, 3.0)
        adx, _, _ = calc_adx(df, 14)
        sig = (st == 1) & (adx > 20.0) & (adx > adx.shift(3))

    elif code == "FRACTAL_BREAK_RVOL":
        fh = calc_fractal_highs(df, 2)
        rvol = calc_rvol(df, 20)
        brk = (close > fh) & (close.shift(1) <= fh.shift(1))
        sig = brk & (rvol > 1.2)

    elif code == "RCI_RIBBON_ALIGN":
        r9, r26, r52 = calc_rci(close, 9), calc_rci(close, 26), calc_rci(close, 52)
        aligned = (r9 > r26) & (r26 > r52) & (r9 > r9.shift(1)) & (r26 > r26.shift(1)) & (r52 > r52.shift(1))
        sig = aligned & (close > calc_ema(close, 50))

    elif code == "CHIKOU_SPAN_CROSS":
        chikou = (close > close.shift(26)) & (close.shift(1) <= close.shift(27))
        hh26 = df["high"].rolling(26).max()
        ll26 = df["low"].rolling(26).min()
        kijun = (hh26 + ll26) / 2.0
        sig = chikou & (close > kijun)

    elif code == "MCGINLEY_CROSS":
        md = calc_mcginley(close, 14)
        sig = (close.shift(1) <= md.shift(1)) & (close > md) & (md > md.shift(1))

    return sig.fillna(False)

# ─── ANA ÇALIŞTIRMA ───────────────────────────────────────────────────────────

def run_lab_v4():
    all_strats = list(STRATEGY_META.keys())
    n_configs = len(all_strats) * len(TIMEFRAMES)
    print("=" * 100)
    print("  🔬 SPOT GÖSTERGE KOMBİNASYON LABORATUVARI v4 — ARŞİV DERİN TARAMA TURU 3")
    print("=" * 100)
    print(f"Yeni stratejiler: {len(all_strats)} | Coinler: {len(ALL_SYMBOLS)} | TF: {[tf for tf, _ in TIMEFRAMES]}")
    print(f"⚠️  Çoklu test uyarısı: N={n_configs}; E[max] ≈ √(2·ln N) = {math.sqrt(2 * math.log(n_configs)):.2f}")
    print("-" * 100)

    rows = []
    for tf, (tp, sl) in TIMEFRAMES:
        print(f"\n▶ TF {tf} (TP %{tp}/SL %{sl})...")
        for sym in ALL_SYMBOLS:
            try:
                df = fetch_binance_klines(sym, interval=tf, limit=1000)
                if len(df) < 400:
                    continue
            except Exception as e:
                print(f"   ⚠️ {sym}: {e}")
                continue
            for code in all_strats:
                try:
                    sigs = generate_signals_v4(df, code)
                except Exception as e:
                    print(f"   ⚠️ {code}@{sym} sinyal hatası: {e}")
                    continue
                if int(sigs.sum()) < 1:
                    continue
                full = simulate_conservative(df, sigs, tp, sl)
                h1 = simulate_conservative(df.iloc[:500].reset_index(drop=True), sigs.iloc[:500].reset_index(drop=True), tp, sl)
                h2 = simulate_conservative(df.iloc[500:].reset_index(drop=True), sigs.iloc[500:].reset_index(drop=True), tp, sl)
                rows.append({
                    "timeframe": tf, "symbol": sym, "strategy_code": code,
                    "strategy_name": STRATEGY_META[code][0], "wr_gate": STRATEGY_META[code][1],
                    "signals": int(sigs.sum()), "trades": full["trades"], "wins": full["wins"],
                    "win_rate": round(100.0 * full["wins"] / full["trades"], 1) if full["trades"] else 0.0,
                    "net_total": full["net_total"], "pf": full["pf"], "max_dd": full["max_dd"],
                    "gross_gain": full["gross_gain"], "gross_loss": full["gross_loss"],
                    "half1_net": h1["net_total"], "half2_net": h2["net_total"],
                })

    if not rows:
        print("❌ Sonuç yok.")
        return
    res = pd.DataFrame(rows)

    agg = res.groupby(["timeframe", "strategy_code"]).apply(lambda g: pd.Series({
        "strategy_name": g["strategy_name"].iloc[0],
        "wr_gate": g["wr_gate"].iloc[0],
        "trades": int(g["trades"].sum()),
        "win_rate": round(100.0 * g["wins"].sum() / max(1, g["trades"].sum()), 1),
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
    print("  📊 STRATEJİ × TF TOPLU SONUÇLAR (≥20 işlem, PF sıralı)")
    print("=" * 100)
    print(f"{'TF':<5} {'Strateji':<42} {'İşlm':>5} {'WR%':>6} {'PF':>6} {'Net%':>8} {'+Coin':>6} {'H1':>8} {'H2':>8}")
    print("-" * 100)
    for _, r in eligible.iterrows():
        print(f"{r['timeframe']:<5} {r['strategy_name'][:42]:<42} {r['trades']:>5} {r['win_rate']:>6.1f} "
              f"{r['pf']:>6.2f} {r['net_total']:>+8.2f} {r['coins_positive']:>3}/{r['coins_traded']:<2} "
              f"{r['half1_net']:>+8.2f} {r['half2_net']:>+8.2f}")

    print("\n" + "=" * 100)
    print("  🚦 KABUL KRİTERLERİ (≥20 işlem, WR eşiği, PF≥1.5, Net>0, ≥3 coin)")
    print("=" * 100)
    promoted = []
    for _, r in eligible.iterrows():
        checks = [r["trades"] >= 20, r["win_rate"] >= r["wr_gate"], r["pf"] >= 1.5,
                  r["net_total"] > 0, r["coins_positive"] >= 3]
        if all(checks):
            promoted.append((r["timeframe"], r["strategy_code"], r))
            robust = "SAĞLAM" if (r["half1_net"] > 0 and r["half2_net"] > 0) else "rejime-bağımlı"
            print(f"🎉 TERFİ ADAYI  {r['timeframe']:<4} {r['strategy_name'][:42]:<42} "
                  f"(WR {r['win_rate']:.1f}/{r['wr_gate']:.0f}, PF {r['pf']:.2f}, Net {r['net_total']:+.2f}%, {robust})")
    if not promoted:
        print("ℹ️ Bu turda tüm kriterleri geçen kombinasyon yok.")
        partial = []
        for _, r in eligible.iterrows():
            c = [r["trades"] >= 20, r["win_rate"] >= r["wr_gate"], r["pf"] >= 1.5, r["net_total"] > 0, r["coins_positive"] >= 3]
            if sum(c) >= 4:
                partial.append((sum(c), r, c))
        partial.sort(key=lambda x: (-x[0], -x[1]["pf"]))
        if partial:
            print("\n  Kısmen geçenler (4/5) — YENİDEN TEST havuzu:")
            for score, r, c in partial[:8]:
                missing = [n for n, v in zip(["işlem", "WR", "PF", "Net", "coin"], c) if not v]
                print(f"   {r['timeframe']:<4} {r['strategy_name'][:42]:<42} Eksik: {','.join(missing)} "
                      f"(WR {r['win_rate']:.1f}, PF {r['pf']:.2f}, Net {r['net_total']:+.2f}%)")

    top = res[res["trades"] >= 6].sort_values("net_total", ascending=False).head(12)
    print("\n🏆 EN İYİ 12 COİN × STRATEJİ (≥6 işlem):")
    for _, r in top.iterrows():
        print(f"  {r['symbol']:<11} {r['timeframe']:<4} {r['strategy_name'][:38]:<38} "
              f"İşlem {r['trades']:>3}  WR %{r['win_rate']:>5.1f}  PF {r['pf']:>5.2f}  Net {r['net_total']:>+7.2f}%")

    out = {
        "meta": {"generated_at": pd.Timestamp.now().isoformat(), "round": "v4-arsiv-turu3",
                 "symbols": ALL_SYMBOLS, "n_strategy_configs": n_configs,
                 "timeframes": {tf: {"tp": tp, "sl": sl} for tf, (tp, sl) in TIMEFRAMES},
                 "commission_pct": COMMISSION_PCT},
        "strategy_aggregates": agg.to_dict(orient="records"),
        "per_coin_results": rows,
    }
    out_file = Path("outputs/spot_indicator_combos_lab_v4.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n💾 Detaylı log: {out_file}")
    return promoted

if __name__ == "__main__":
    run_lab_v4()
