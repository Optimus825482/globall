"""
SPOT GÖSTERGE KOMBİNASYON LABORATUVARI v3 — ARŞİV DERİN TARAMA TURU 2
======================================================================
GOSTERGELER.HTML arşivinden v2'de taranmamış göstergelerle 18 yeni kombinasyon.
Motor v2 ile aynı: sonraki bar açılış girişi, SL öncelikli, %0.08 komisyon,
48 bar timeout, split-half rejim kontrolü. Kriterler: ≥20 işlem, WR≥%60 (dip)
/%55 (trend), PF≥1.5, Net>0, ≥3 coin pozitif.

YENİ 18 KOMBİNASYON:
  Mean-Reversion (dip dönüş):
   1.  Connors RSI(3,2,100) bileşik < 20 + EMA200
   2.  TRIX(18) sinyal üstü kesişim (negatif bölgeden) + EMA50
   3.  TSI(25,13) sinyal kesişimi (TSI<-20 derin aşırı satım) + EMA200
   4.  RCI(9) -80 üstü dönüş + RCI(26) > -20 (RCI şerit teyidi)
   5.  CMO(20) < -50 derin dönüşü + EMA200
   6.  Bollinger %B < 0.05 + RSI(14) < 35 yükseliş confluence
   7.  Mass Index şişkinlik sönümü (>27 → <26.5) + EMA50 yönü
   8.  KAMA(10,2,30) yön dönüşü + Choppiness < 55
   9.  Klinger(34,55) negatif bölgede sinyal kesişimi + EMA200
   10. CMF(20) < -0.20 dönüşü + EMA50
   11. DPO(21) döngü dibi dönüşü (p10) + EMA50
  Trend / Kırılım:
   12. Ichimoku Tenkan>Kijun kesişimi + bulut üstü kapanış
   13. SuperTrend boğa çevrimi + RVOL > 1.3 (hacim teyitli trend başlangıcı)
   14. Aroon(25) Up>70 & Down<30 güç geçişi + EMA50
   15. PSAR boğa çevrimi + ADX(14) > 20
   16. Envelope(EMA20, %2) üst kırılım + RVOL > 1.5
   17. LinReg Eğim(14) sıfır üstü dönüş + Volume Osc > 0 + EMA50
   18. BB-KC Sıkışma Kırılımı + RVOL > 1.3 (v2 şampiyonunun hacim teyitli iyileştirmesi)
"""
import sys
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from test_advanced_spot_strategies import fetch_binance_klines
from test_indicator_combos_lab import (
    simulate_conservative, calc_ema, calc_atr, calc_rsi, calc_supertrend,
    calc_bollinger_vwap, calc_keltner, calc_chop, calc_adx, calc_cci,
    ALL_SYMBOLS, TIMEFRAMES, COMMISSION_PCT,
)

sys.stdout.reconfigure(encoding="utf-8")

MR_GATE, TREND_GATE = 60.0, 55.0
STRATEGY_META = {
    "CRSI_COMPOSITE_EMA200":  ("Connors RSI(3,2,100)<20 + EMA200", MR_GATE),
    "TRIX_SIGNAL_TURN":       ("TRIX(18) Negatiften Sinyal Kes + EMA50", MR_GATE),
    "TSI_OSR_SIGNAL_CROSS":   ("TSI(25,13)<-20 Sinyal Kes + EMA200", MR_GATE),
    "RCI9_DEEP_TURN":         ("RCI(9) -80 Dönüş + RCI(26) Teyidi", MR_GATE),
    "CMO_DEEP_TURN_EMA200":   ("CMO(20)<-50 Dönüş + EMA200", MR_GATE),
    "PCTB_RSI_CONFLUENCE":    ("Boll %B<0.05 + RSI<35 Yükseliş", MR_GATE),
    "MASS_INDEX_REVERSAL":    ("Mass Index Şişkinlik Sönümü + EMA50", MR_GATE),
    "KAMA_TURN_CHOP":         ("KAMA Dönüşü + Chop<55", MR_GATE),
    "KLINGER_OSR_CROSS":      ("Klinger Negatiften Sinyal Kes + EMA200", MR_GATE),
    "CMF_OSR_TURN_EMA50":     ("CMF(20)<-0.20 Dönüş + EMA50", MR_GATE),
    "DPO_DEEP_TURN":          ("DPO(21) Döngü Dibi + EMA50", MR_GATE),
    "ICHIMOKU_TK_CLOUD":      ("Ichimoku TK Kesişim + Bulut Üstü", TREND_GATE),
    "SUPERTREND_FLIP_RVOL":   ("SuperTrend Çevrim + RVOL>1.3", TREND_GATE),
    "AROON_POWER_EMA50":      ("Aroon Up>70/Down<30 + EMA50", TREND_GATE),
    "PSAR_FLIP_ADX":          ("PSAR Boğa Çevrimi + ADX>20", TREND_GATE),
    "ENVELOPE_BREAK_RVOL":    ("Envelope %2 Üst Kırılım + RVOL>1.5", TREND_GATE),
    "LINREG_SLOPE_TURN_VOL":  ("LinReg Eğim Dönüşü + VolOsc>0", TREND_GATE),
    "SQUEEZE_VOL_CONFIRM":    ("BB-KC Sıkışma + RVOL>1.3 (v2+)", TREND_GATE),
}

# ─── YENİ GÖSTERGE YARDIMCILARI ───────────────────────────────────────────────

def _streak(close: pd.Series) -> pd.Series:
    out = []
    s = 0
    for d in close.diff():
        if d > 0:
            s = s + 1 if s > 0 else 1
        elif d < 0:
            s = s - 1 if s < 0 else -1
        else:
            s = 0
        out.append(s)
    return pd.Series(out, index=close.index, dtype=float)

def calc_crsi(close: pd.Series, rsi_p=3, streak_p=2, rank_p=100) -> pd.Series:
    r1 = calc_rsi(close, rsi_p)
    r2 = calc_rsi(_streak(close), streak_p)
    roc1 = close.pct_change() * 100.0
    pr = roc1.rolling(rank_p + 1).apply(lambda x: (x[:-1] < x[-1]).mean() * 100.0, raw=True)
    return (r1 + r2 + pr) / 3.0

def calc_trix(close: pd.Series, n=18, sig=9) -> pd.Series:
    e1 = close.ewm(span=n, adjust=False).mean()
    e2 = e1.ewm(span=n, adjust=False).mean()
    e3 = e2.ewm(span=n, adjust=False).mean()
    trix = e3.pct_change() * 100.0
    signal = trix.ewm(span=sig, adjust=False).mean()
    return trix, signal

def calc_tsi(close: pd.Series, long=25, short=13, sig=13) -> pd.Series:
    m = close.diff()
    num = m.ewm(span=long, adjust=False).mean().ewm(span=short, adjust=False).mean()
    den = m.abs().ewm(span=long, adjust=False).mean().ewm(span=short, adjust=False).mean()
    tsi = 100.0 * num / den.replace(0, np.nan)
    return tsi, tsi.ewm(span=sig, adjust=False).mean()

def calc_rci(s: pd.Series, n=9) -> pd.Series:
    def rci_w(w):
        ranks = np.empty(n)
        ranks[np.argsort(np.argsort(w))] = np.arange(1, n + 1)
        d = ranks - np.arange(1, n + 1)
        return (1.0 - 6.0 * np.sum(d ** 2) / (n * (n * n - 1))) * 100.0
    return s.rolling(n).apply(rci_w, raw=True)

def calc_cmo(close: pd.Series, n=20) -> pd.Series:
    delta = close.diff()
    su = delta.where(delta > 0, 0.0).rolling(n).sum()
    sd = (-delta.where(delta < 0, 0.0)).rolling(n).sum()
    return 100.0 * (su - sd) / (su + sd).replace(0, np.nan)

def calc_mass_index(df: pd.DataFrame, ema_n=9, sum_n=25) -> pd.Series:
    rng = df["high"] - df["low"]
    e1 = rng.ewm(span=ema_n, adjust=False).mean()
    e2 = e1.ewm(span=ema_n, adjust=False).mean()
    return (e1 / e2.replace(0, np.nan)).rolling(sum_n).sum()

def calc_kama(close: pd.Series, er_p=10, fast=2, slow=30) -> pd.Series:
    change = (close - close.shift(er_p)).abs()
    vol = close.diff().abs().rolling(er_p).sum()
    er = (change / vol.replace(0, np.nan)).fillna(0.0)
    fsc, ssc = 2.0 / (fast + 1), 2.0 / (slow + 1)
    sc = (er * (fsc - ssc) + ssc) ** 2
    kama = np.full(len(close), np.nan)
    kama[er_p] = close.iloc[er_p]
    c = close.values
    for i in range(er_p + 1, len(close)):
        kama[i] = kama[i - 1] + sc.iloc[i] * (c[i] - kama[i - 1])
    return pd.Series(kama, index=close.index)

def calc_klinger(df: pd.DataFrame, fast=34, slow=55, sig=13) -> pd.Series:
    hlc = df["high"] + df["low"] + df["close"]
    trend = np.sign(hlc.diff()).fillna(0.0)
    dm = (df["high"] - df["low"]).values
    t = trend.values
    cm = np.zeros(len(df))
    for i in range(len(df)):
        if i == 0:
            cm[i] = dm[i]
        elif t[i] == t[i - 1]:
            cm[i] = cm[i - 1] + dm[i]
        else:
            cm[i] = dm[i - 1] + dm[i]
    vf = df["volume"] * (2.0 * ((dm / np.where(cm == 0, np.nan, cm)) - 1.0)) * t * 100.0
    vf = pd.Series(vf, index=df.index).fillna(0.0)
    ko = vf.ewm(span=fast, adjust=False).mean() - vf.ewm(span=slow, adjust=False).mean()
    return ko, ko.ewm(span=sig, adjust=False).mean()

def calc_cmf(df: pd.DataFrame, n=20) -> pd.Series:
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / (df["high"] - df["low"]).replace(0, np.nan)
    mfv = (mfm * df["volume"]).fillna(0.0)
    return mfv.rolling(n).sum() / df["volume"].rolling(n).sum().replace(0, np.nan)

def calc_dpo(close: pd.Series, n=21) -> pd.Series:
    return close.shift(n // 2 + 1) - close.rolling(n).mean()

def calc_ichimoku(df: pd.DataFrame, conv=9, base=26, spanb=52):
    def hh(p): return df["high"].rolling(p).max()
    def ll(p): return df["low"].rolling(p).min()
    tenkan = (hh(conv) + ll(conv)) / 2.0
    kijun = (hh(base) + ll(base)) / 2.0
    span_a = ((tenkan + kijun) / 2.0).shift(base)
    span_b = (hh(spanb) + ll(spanb)) / 2.0
    cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
    return tenkan, kijun, cloud_top

def calc_psar(df: pd.DataFrame, af_step=0.02, af_max=0.2):
    h, l = df["high"].values, df["low"].values
    n = len(df)
    psar = np.full(n, np.nan)
    bull = np.ones(n, dtype=bool)
    af, ep, sar = af_step, h[0], l[0]
    trend_up = True
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if trend_up:
            sar = min(sar, l[i - 1], l[i - 2] if i >= 2 else l[i - 1])
            if l[i] < sar:
                trend_up, sar, ep, af = False, ep, l[i], af_step
            elif h[i] > ep:
                ep, af = h[i], min(af + af_step, af_max)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i >= 2 else h[i - 1])
            if h[i] > sar:
                trend_up, sar, ep, af = True, ep, h[i], af_step
            elif l[i] < ep:
                ep, af = l[i], min(af + af_step, af_max)
        psar[i], bull[i] = sar, trend_up
    return pd.Series(psar, index=df.index), pd.Series(bull, index=df.index)

def calc_aroon(df: pd.DataFrame, n=25):
    idx = np.arange(len(df))
    def aroon_up_win(w): return 100.0 * (np.argmax(w)) / (len(w) - 1)
    def aroon_dn_win(w): return 100.0 * (np.argmin(w)) / (len(w) - 1)
    up = df["high"].rolling(n + 1).apply(aroon_up_win, raw=True)
    dn = df["low"].rolling(n + 1).apply(aroon_dn_win, raw=True)
    return up, dn

def calc_rvol(df: pd.DataFrame, n=20) -> pd.Series:
    return df["volume"] / df["volume"].rolling(n).mean().replace(0, np.nan)

def calc_vol_osc(df: pd.DataFrame, fast=5, slow=10) -> pd.Series:
    f = df["volume"].ewm(span=fast, adjust=False).mean()
    s = df["volume"].ewm(span=slow, adjust=False).mean()
    return (f - s) / s.replace(0, np.nan) * 100.0

def calc_linreg_slope(close: pd.Series, n=14) -> pd.Series:
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()
    def slope_w(w):
        b = ((x - x_mean) * (w - w.mean())).sum() / denom
        return b / w.mean() * 100.0
    return close.rolling(n).apply(slope_w, raw=True)

# ─── SİNYAL ÜRETİCİLERİ ───────────────────────────────────────────────────────

def generate_signals_v3(df: pd.DataFrame, code: str) -> pd.Series:
    close = df["close"]
    sig = pd.Series(False, index=df.index)

    if code == "CRSI_COMPOSITE_EMA200":
        crsi = calc_crsi(close, 3, 2, 100)
        sig = (crsi < 20.0) & (close > calc_ema(close, 200))

    elif code == "TRIX_SIGNAL_TURN":
        trix, tr_sig = calc_trix(close, 18, 9)
        sig = (trix.shift(1) < tr_sig.shift(1)) & (trix > tr_sig) & (trix.shift(1) < 0.0) & (close > calc_ema(close, 50))

    elif code == "TSI_OSR_SIGNAL_CROSS":
        tsi, ts_sig = calc_tsi(close, 25, 13, 13)
        sig = (tsi.shift(1) < ts_sig.shift(1)) & (tsi > ts_sig) & (tsi.shift(1) < -20.0) & (close > calc_ema(close, 200))

    elif code == "RCI9_DEEP_TURN":
        rci9 = calc_rci(close, 9)
        rci26 = calc_rci(close, 26)
        sig = (rci9.shift(1) <= -80.0) & (rci9 > rci9.shift(1)) & (rci26 > -20.0)

    elif code == "CMO_DEEP_TURN_EMA200":
        cmo = calc_cmo(close, 20)
        sig = (cmo.shift(1) <= -50.0) & (cmo > cmo.shift(1)) & (close > calc_ema(close, 200))

    elif code == "PCTB_RSI_CONFLUENCE":
        upper, lower, _, _ = calc_bollinger_vwap(df, 20, 2.0)
        pctb = (close - lower) / (upper - lower).replace(0, np.nan)
        rsi = calc_rsi(close, 14)
        sig = (pctb.shift(1) < 0.05) & (rsi < 35.0) & (rsi > rsi.shift(1))

    elif code == "MASS_INDEX_REVERSAL":
        mi = calc_mass_index(df, 9, 25)
        sig = (mi.shift(2) > 27.0) & (mi < 26.5) & (close > calc_ema(close, 50))

    elif code == "KAMA_TURN_CHOP":
        kama = calc_kama(close, 10, 2, 30)
        chop = calc_chop(df, 14)
        turn = (kama.shift(1) <= kama.shift(2)) & (kama > kama.shift(1))
        sig = turn & (close > kama) & (chop < 55.0)

    elif code == "KLINGER_OSR_CROSS":
        ko, ko_sig = calc_klinger(df, 34, 55, 13)
        sig = (ko.shift(1) < ko_sig.shift(1)) & (ko > ko_sig) & (ko.shift(1) < 0.0) & (close > calc_ema(close, 200))

    elif code == "CMF_OSR_TURN_EMA50":
        cmf = calc_cmf(df, 20)
        sig = (cmf.shift(1) <= -0.20) & (cmf > cmf.shift(1)) & (close > calc_ema(close, 50))

    elif code == "DPO_DEEP_TURN":
        dpo = calc_dpo(close, 21)
        deep = dpo < dpo.rolling(200).quantile(0.10)
        sig = deep & (dpo > dpo.shift(1)) & (close > calc_ema(close, 50))

    elif code == "ICHIMOKU_TK_CLOUD":
        tenkan, kijun, cloud_top = calc_ichimoku(df, 9, 26, 52)
        tk_cross = (tenkan.shift(1) <= kijun.shift(1)) & (tenkan > kijun)
        sig = tk_cross & (close > cloud_top)

    elif code == "SUPERTREND_FLIP_RVOL":
        st = calc_supertrend(df, 10, 3.0)
        rvol = calc_rvol(df, 20)
        flip = (st.shift(1) == -1) & (st == 1)
        sig = flip & (rvol > 1.3)

    elif code == "AROON_POWER_EMA50":
        up, dn = calc_aroon(df, 25)
        sig = (up.shift(1) <= 70.0) & (up > 70.0) & (dn < 30.0) & (close > calc_ema(close, 50))

    elif code == "PSAR_FLIP_ADX":
        _, bull = calc_psar(df)
        adx, _, _ = calc_adx(df, 14)
        flip = (bull.shift(1) == False) & (bull == True)
        sig = flip & (adx > 20.0)

    elif code == "ENVELOPE_BREAK_RVOL":
        ema20 = calc_ema(close, 20)
        env_up = ema20 * 1.02
        rvol = calc_rvol(df, 20)
        brk = (close > env_up) & (close.shift(1) <= env_up.shift(1))
        sig = brk & (rvol > 1.5)

    elif code == "LINREG_SLOPE_TURN_VOL":
        slope = calc_linreg_slope(close, 14)
        vo = calc_vol_osc(df, 5, 10)
        sig = (slope.shift(1) <= 0.0) & (slope > 0.0) & (vo > 0.0) & (close > calc_ema(close, 50))

    elif code == "SQUEEZE_VOL_CONFIRM":
        upper, lower, _, _ = calc_bollinger_vwap(df, 20, 2.0)
        kc_up, kc_lo = calc_keltner(df, 20, 20, 1.5)
        squeeze = (upper < kc_up) & (lower > kc_lo)
        squeeze_recent = squeeze.shift(1).rolling(5).max().fillna(0).astype(bool)
        brk = (close > upper) & (close.shift(1) <= upper.shift(1))
        rvol = calc_rvol(df, 20)
        sig = squeeze_recent & brk & (rvol > 1.3)

    return sig.fillna(False)

# ─── ANA ÇALIŞTIRMA ───────────────────────────────────────────────────────────

def run_lab_v3():
    all_strats = list(STRATEGY_META.keys())
    n_configs = len(all_strats) * len(TIMEFRAMES)
    print("=" * 100)
    print("  🔬 SPOT GÖSTERGE KOMBİNASYON LABORATUVARI v3 — ARŞİV DERİN TARAMA TURU 2")
    print("=" * 100)
    print(f"Yeni stratejiler: {len(all_strats)} | Coinler: {len(ALL_SYMBOLS)} | TF matrisi: {[tf for tf, _ in TIMEFRAMES]}")
    print(f"⚠️  Çoklu test uyarısı: N={n_configs}; E[max] ≈ √(2·ln N) = {math.sqrt(2 * math.log(n_configs)):.2f}")
    print("-" * 100)

    rows = []
    for tf, (tp, sl) in TIMEFRAMES:
        print(f"\n▶ TF {tf} (TP %{tp}/SL %{sl}) işleniyor...")
        for sym in ALL_SYMBOLS:
            try:
                df = fetch_binance_klines(sym, interval=tf, limit=1000)
                if len(df) < 400:
                    continue
            except Exception as e:
                print(f"   ⚠️ {sym}: {e}")
                continue
            for code in all_strats:
                sigs = generate_signals_v3(df, code)
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
    print(f"{'TF':<5} {'Strateji':<40} {'İşlm':>5} {'WR%':>6} {'PF':>6} {'Net%':>8} {'+Coin':>6} {'H1':>8} {'H2':>8}")
    print("-" * 100)
    for _, r in eligible.iterrows():
        print(f"{r['timeframe']:<5} {r['strategy_name'][:40]:<40} {r['trades']:>5} {r['win_rate']:>6.1f} "
              f"{r['pf']:>6.2f} {r['net_total']:>+8.2f} {r['coins_positive']:>3}/{r['coins_traded']:<2} "
              f"{r['half1_net']:>+8.2f} {r['half2_net']:>+8.2f}")

    print("\n" + "=" * 100)
    print("  🚦 KABUL KRİTERLERİ (≥20 işlem, WR eşiği, PF≥1.5, Net>0, ≥3 coin)")
    print("=" * 100)
    promoted = []
    for _, r in eligible.iterrows():
        checks = {
            "işlem": r["trades"] >= 20, "WR": r["win_rate"] >= r["wr_gate"], "PF": r["pf"] >= 1.5,
            "Net": r["net_total"] > 0, "coin": r["coins_positive"] >= 3,
        }
        passed = all(checks.values())
        flags = " ".join("✅" if v else "❌" for v in checks.values())
        robust = "SAĞLAM" if (r["half1_net"] > 0 and r["half2_net"] > 0) else "rejime-bağımlı"
        if passed:
            promoted.append((r["timeframe"], r["strategy_code"], r))
            print(f"🎉 TERFİ ADAYI  {r['timeframe']:<4} {r['strategy_name'][:42]:<42} {flags} "
                  f"(WR {r['win_rate']:.1f}/{r['wr_gate']:.0f}, PF {r['pf']:.2f}, Net {r['net_total']:+.2f}%, {robust})")

    if not promoted:
        print("ℹ️ Bu turda tüm kriterleri geçen kombinasyon yok.")
        partial = []
        for _, r in eligible.iterrows():
            c = [r["trades"] >= 20, r["win_rate"] >= r["wr_gate"], r["pf"] >= 1.5, r["net_total"] > 0, r["coins_positive"] >= 3]
            if sum(c) >= 4:
                partial.append((sum(c), r))
        partial.sort(key=lambda x: (-x[0], -x[1]["pf"]))
        if partial:
            print("\n  Kısmen geçenler (4/5) — YENİDEN TEST havuzu:")
            for score, r in partial[:8]:
                missing = [n for n, v in zip(["işlem", "WR", "PF", "Net", "coin"], [
                    r["trades"] >= 20, r["win_rate"] >= r["wr_gate"], r["pf"] >= 1.5,
                    r["net_total"] > 0, r["coins_positive"] >= 3]) if not v]
                print(f"   {r['timeframe']:<4} {r['strategy_name'][:42]:<42} Eksik: {','.join(missing)} "
                      f"(WR {r['win_rate']:.1f}, PF {r['pf']:.2f}, Net {r['net_total']:+.2f}%)")

    # En iyi coin kombinasyonları
    top = res[res["trades"] >= 6].sort_values("net_total", ascending=False).head(12)
    print("\n🏆 EN İYİ 12 COİN × STRATEJİ (≥6 işlem):")
    for _, r in top.iterrows():
        print(f"  {r['symbol']:<11} {r['timeframe']:<4} {r['strategy_name'][:38]:<38} "
              f"İşlem {r['trades']:>3}  WR %{r['win_rate']:>5.1f}  PF {r['pf']:>5.2f}  Net {r['net_total']:>+7.2f}%")

    out = {
        "meta": {
            "generated_at": pd.Timestamp.now().isoformat(), "round": "v3-arsiv-derin-tarama",
            "symbols": ALL_SYMBOLS,
            "timeframes": {tf: {"tp": tp, "sl": sl} for tf, (tp, sl) in TIMEFRAMES},
            "commission_pct": COMMISSION_PCT, "n_strategy_configs": n_configs,
        },
        "strategy_aggregates": agg.to_dict(orient="records"),
        "per_coin_results": rows,
    }
    out_file = Path("outputs/spot_indicator_combos_lab_v3.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n💾 Detaylı log: {out_file}")
    return promoted

if __name__ == "__main__":
    run_lab_v3()
