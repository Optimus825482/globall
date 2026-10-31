"""
SPOT GÖSTERGE KOMBİNASYON LABORATUVARI v5 — KALAN AİLELER (Hacim Profili, Regresyon
Kanalları, Akıllı Para Endeksleri, Heikin-Ashi, Divergence)
==============================================================================
Motor aynı: sonraki bar açılış girişi, SL öncelikli çift eşleşme, gap koruması,
%0.08 round-trip komisyon, 48 bar timeout, split-half rejim kontrolü.
Kriterler: ≥20 işlem, WR≥%60 (dip) / %55 (trend), PF≥1.5, Net>0, ≥3 coin pozitif.

YENİ 16 KOMBİNASYON:
  Mean-Reversion (dip dönüş):
   1.  Hacim Profili VAL sekmeleri (200 bar / 24 satır / %70 VA) + RSI<40
   2.  Hacim Profili POC geri kazanımı + OBV > EMA21
   3.  Zarf snapback: EMA20 alt zarfı (-%2) delinip bar içinde geri kapanış + RSI<40
   4.  Doğrusal Regresyon(100) alt -2σ kanal sekmesi + RSI yükseliyor
   5.  Standart Hata Bandı(21) alt bandı geri kazanımı
   6.  RSI boğa uyumsuzluğu (fiyat 20-bar dip, RSI öncekinden yüksek) + RSI<40
   7.  NVI akıllı para rejimi (> EMA255) + RSI(3)<20
   8.  CVI birikim rejimi (> EMA21) + EMA200 üstü + RSI(3)<15
   9.  PVT > EMA(PVT,21) kesişimi + EMA50
   10. Chaikin Osilatörü(3,10) sıfır üstü dönüşü + EMA50
  Trend / Kırılım:
   11. Donchian(20) orta çizgi kesişimi + SuperTrend boğa (trend devamı)
   12. Turtle Donchian(55) üst kırılımı + ADX>20 (1h odaklı)
   13. Coppock Eğrisi sıfır üstü kesişimi (1h odaklı)
   14. Heikin-Ashi 2 ardışık yeşil mum + EMA50 üstü
   15. TSI + TRIX aynı anda sinyal kesişimi (çift yumuşatılmış momentum mutabakatı)
   16. Zaman-çapalı RVOL (aynı saat ortalama hacmine göre >2x) + EMA20 üstü kesişim
"""
import sys
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from test_advanced_spot_strategies import fetch_binance_klines
from test_indicator_combos_lab import (
    simulate_conservative, calc_ema, calc_rsi, calc_wma, calc_obv, calc_adx,
    calc_supertrend, ALL_SYMBOLS, TIMEFRAMES, COMMISSION_PCT,
)
from test_indicator_combos_lab_v3 import calc_rvol, calc_vol_osc, calc_tsi, calc_trix

sys.stdout.reconfigure(encoding="utf-8")

MR_GATE, TREND_GATE = 60.0, 55.0
STRATEGY_META = {
    "VPROFILE_VAL_BOUNCE":   ("Hacim Profili VAL Sekmesi + RSI<40", MR_GATE),
    "VPROFILE_POC_RECLAIM":  ("Hacim Profili POC Geri Kazanımı + OBV", MR_GATE),
    "ENVELOPE_SNAPBACK":     ("Zarf -%2 Snapback + RSI<40", MR_GATE),
    "REGRESSION_LOWER_BOUNCE": ("LinReg(100) -2σ Kanal Sekmesi", MR_GATE),
    "SE_BAND_BOUNCE":        ("Standart Hata Bandı Alt Geri Kazanım", MR_GATE),
    "RSI_BULL_DIVERGENCE":   ("RSI Boğa Uyumsuzluğu (20-bar dip)", MR_GATE),
    "NVI_SMART_MONEY_DIP":   ("NVI Rejimi + RSI(3)<20", MR_GATE),
    "CVI_ACCUM_DIP":         ("CVI Birikim Rejimi + RSI(3)<15", MR_GATE),
    "PVT_EMA_CROSS":         ("PVT > EMA21 Kesişimi + EMA50", MR_GATE),
    "CHAIKIN_OSC_TURN":      ("Chaikin Osc(3,10) Sıfır Dönüşü + EMA50", MR_GATE),
    "DONCHIAN_MID_CONT":     ("Donchian(20) Orta Kes + SuperTrend Boğa", TREND_GATE),
    "TURTLE_DONCHIAN55":     ("Turtle Donchian(55) Kırılımı + ADX>20", TREND_GATE),
    "COPPOCK_ZERO_TURN":     ("Coppock Eğrisi Sıfır Üstü Kesişim", TREND_GATE),
    "HA_TWO_GREEN_FLIP":     ("Heikin-Ashi 2 Yeşil + EMA50", TREND_GATE),
    "TSI_TRIX_CONFLUENCE":   ("TSI + TRIX Çift Sinyal Kesişimi", TREND_GATE),
    "RVOL_TOD_SPIKE":        ("Zaman-Çapalı RVOL>2x + EMA20 Kes", TREND_GATE),
}

# ─── YENİ GÖSTERGE YARDIMCILARI ───────────────────────────────────────────────

def calc_volume_profile(df: pd.DataFrame, lookback=200, rows=24, va_pct=0.70):
    """Kayan hacim profili: son `lookback` barın tipik fiyatı 24 fiyat satırına bölünür.
    POC = en yüksek hacimli satır merkezi; VAH/VAL = %70 hacim alanının sınırları."""
    lows = df["low"].values
    highs = df["high"].values
    tp = ((df["high"] + df["low"] + df["close"]) / 3.0).values
    vol = df["volume"].values
    n = len(df)
    poc = np.full(n, np.nan)
    vah = np.full(n, np.nan)
    val = np.full(n, np.nan)
    for i in range(lookback, n):
        s = i - lookback + 1
        lo, hi = lows[s:i + 1].min(), highs[s:i + 1].max()
        if hi <= lo:
            continue
        edges = np.linspace(lo, hi, rows + 1)
        centers = (edges[:-1] + edges[1:]) / 2.0
        bins = np.clip(np.digitize(tp[s:i + 1], edges) - 1, 0, rows - 1)
        vols = np.zeros(rows)
        np.add.at(vols, bins, vol[s:i + 1])
        total = vols.sum()
        if total <= 0:
            continue
        p = int(np.argmax(vols))
        acc = vols[p]
        lo_i, hi_i = p, p
        while acc < va_pct * total and (lo_i > 0 or hi_i < rows - 1):
            below = vols[lo_i - 1] if lo_i > 0 else -1.0
            above = vols[hi_i + 1] if hi_i < rows - 1 else -1.0
            if above >= below:
                hi_i += 1
                acc += vols[hi_i]
            else:
                lo_i -= 1
                acc += vols[lo_i]
        poc[i] = centers[p]
        vah[i] = centers[hi_i]
        val[i] = centers[lo_i]
    idx = df.index
    return pd.Series(poc, index=idx), pd.Series(vah, index=idx), pd.Series(val, index=idx)

def calc_linreg_value(close: pd.Series, n: int) -> pd.Series:
    """Her barda son N-bar regresyon doğrusunun o bardaki değeri + residüel σ."""
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()
    def fit(w):
        y_mean = w.mean()
        b = ((x - x_mean) * (w - y_mean)).sum() / denom
        a = y_mean - b * x_mean
        y_hat = a + b * x
        return a + b * (n - 1), float(np.sqrt(((w - y_hat) ** 2).sum() / max(1, n - 2)))
    vals = close.rolling(n).apply(lambda w: fit(w)[0], raw=True)
    sig = close.rolling(n).apply(lambda w: fit(w)[1], raw=True)
    return vals, sig

def calc_adl(df: pd.DataFrame) -> pd.Series:
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / (df["high"] - df["low"]).replace(0, np.nan)
    return (mfm * df["volume"]).fillna(0.0).cumsum()

def calc_pvt(df: pd.DataFrame) -> pd.Series:
    return (((df["close"] - df["close"].shift(1)) / df["close"].shift(1)) * df["volume"]).fillna(0.0).cumsum()

def calc_nvi(df: pd.DataFrame) -> pd.Series:
    pct = df["close"].pct_change().fillna(0.0)
    return 1000.0 + (pct.where(df["volume"] < df["volume"].shift(1), 0.0) * 100.0).cumsum()

def calc_cvi(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0.0)
    return (direction * df["volume"]).cumsum()

def calc_coppock(close: pd.Series, long_roc=14, short_roc=11, wma_n=10) -> pd.Series:
    return calc_wma(close.pct_change(long_roc) * 100.0 + close.pct_change(short_roc) * 100.0, wma_n)

def calc_heikin_ashi(df: pd.DataFrame):
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(df)
    ho = np.zeros(n)
    hc = (o + h + l + c) / 4.0
    ho[0] = o[0]
    for i in range(1, n):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2.0
    return pd.Series(ho, index=df.index), pd.Series(hc, index=df.index)

def calc_rvol_tod(df: pd.DataFrame, min_hist=10) -> pd.Series:
    """Zaman-çapalı RVOL: bar hacmi / aynı saat-of-gün önceki barların genişleyen ortalaması."""
    hour = df["time"].dt.floor("1h")
    hist = df.groupby(hour)["volume"].transform(lambda s: s.shift(1).expanding(min_periods=min_hist).mean())
    return df["volume"] / hist.replace(0, np.nan)

def calc_rsi_bull_divergence(df: pd.DataFrame, lookback=20) -> pd.Series:
    """Basitleştirilmiş boğa uyumsuzluğu: fiyat lookback-bar dip yaparken RSI önceki
    dip dokunuşundaki RSI'dan yüksekse + RSI yukarı dönüyorsa. (Yaklaşık algılama:
    önceki dip RSI'ı, dip dokunuşu barlarındaki RSI'ın ffill'i ile alınır.)"""
    low = df["low"]
    rsi = calc_rsi(df["close"], 14)
    at_low = low == low.rolling(lookback).min()
    rsi_at_low = rsi.where(at_low).ffill()
    new_low = low <= low.rolling(lookback).min()
    return new_low & (rsi > rsi_at_low.shift(1)) & (rsi > rsi.shift(1)) & (rsi < 40.0)

# ─── SİNYAL ÜRETİCİLERİ ───────────────────────────────────────────────────────

def generate_signals_v5(df: pd.DataFrame, code: str) -> pd.Series:
    close = df["close"]
    sig = pd.Series(False, index=df.index)

    if code in ("VPROFILE_VAL_BOUNCE", "VPROFILE_POC_RECLAIM"):
        poc, vah, val = calc_volume_profile(df, 200, 24, 0.70)
        rsi = calc_rsi(close, 14)
        obv = calc_obv(df)
        if code == "VPROFILE_VAL_BOUNCE":
            sig = (close.shift(1) <= val.shift(1)) & (close > val) & (rsi < 40.0)
        else:
            sig = (close.shift(1) <= poc.shift(1)) & (close > poc) & (obv > calc_ema(obv, 21))

    elif code == "ENVELOPE_SNAPBACK":
        env_lo = calc_ema(close, 20) * 0.98
        rsi = calc_rsi(close, 14)
        pierced = df["low"] < env_lo
        closed_back = close > env_lo
        sig = pierced & closed_back & (rsi < 40.0) & (close.shift(1) > env_lo.shift(1))

    elif code == "REGRESSION_LOWER_BOUNCE":
        reg, sig_res = calc_linreg_value(close, 100)
        lower = reg - 2.0 * sig_res
        rsi = calc_rsi(close, 14)
        sig = (df["low"] <= lower) & (close > lower) & (rsi > rsi.shift(1)) & (rsi < 45.0)

    elif code == "SE_BAND_BOUNCE":
        reg, se = calc_linreg_value(close, 21)
        lower = reg - 2.0 * se
        sig = (close.shift(1) <= lower.shift(1)) & (close > lower)

    elif code == "RSI_BULL_DIVERGENCE":
        sig = calc_rsi_bull_divergence(df, 20)

    elif code == "NVI_SMART_MONEY_DIP":
        nvi = calc_nvi(df)
        nvi_regime = nvi > calc_ema(nvi, 255)
        sig = nvi_regime & (calc_rsi(close, 3) < 20.0)

    elif code == "CVI_ACCUM_DIP":
        cvi = calc_cvi(df)
        accum = cvi > calc_ema(cvi, 21)
        sig = accum & (close > calc_ema(close, 200)) & (calc_rsi(close, 3) < 15.0)

    elif code == "PVT_EMA_CROSS":
        pvt = calc_pvt(df)
        sig = (pvt.shift(1) <= calc_ema(pvt, 21).shift(1)) & (pvt > calc_ema(pvt, 21)) & (close > calc_ema(close, 50))

    elif code == "CHAIKIN_OSC_TURN":
        adl = calc_adl(df)
        osc = adl.ewm(span=3, adjust=False).mean() - adl.ewm(span=10, adjust=False).mean()
        sig = (osc.shift(1) <= 0.0) & (osc > 0.0) & (close > calc_ema(close, 50))

    elif code == "DONCHIAN_MID_CONT":
        mid = (df["high"].rolling(20).max() + df["low"].rolling(20).min()) / 2.0
        st = calc_supertrend(df, 10, 3.0)
        sig = (close.shift(1) <= mid.shift(1)) & (close > mid) & (st == 1)

    elif code == "TURTLE_DONCHIAN55":
        hh = df["high"].rolling(55).max().shift(1)
        adx, _, _ = calc_adx(df, 14)
        sig = (close > hh) & (close.shift(1) <= hh.shift(1)) & (adx > 20.0)

    elif code == "COPPOCK_ZERO_TURN":
        copp = calc_coppock(close, 14, 11, 10)
        sig = (copp.shift(1) <= 0.0) & (copp > 0.0)

    elif code == "HA_TWO_GREEN_FLIP":
        ho, hc = calc_heikin_ashi(df)
        green = hc > ho
        two_green = green & green.shift(1) & (~green).shift(2)
        sig = two_green & (close > calc_ema(close, 50))

    elif code == "TSI_TRIX_CONFLUENCE":
        tsi, tsig = calc_tsi(close, 25, 13, 13)
        trix, xsig = calc_trix(close, 18, 9)
        tsi_up = (tsi.shift(1) <= tsig.shift(1)) & (tsi > tsig)
        trix_up = (trix.shift(1) <= xsig.shift(1)) & (trix > xsig)
        sig = tsi_up & trix_up & (close > calc_ema(close, 50))

    elif code == "RVOL_TOD_SPIKE":
        rvol = calc_rvol_tod(df, 10)
        ema20 = calc_ema(close, 20)
        sig = (rvol > 2.0) & (close > ema20) & (close.shift(1) <= ema20.shift(1))

    return sig.fillna(False)

# ─── ANA ÇALIŞTIRMA ───────────────────────────────────────────────────────────

def run_lab_v5():
    all_strats = list(STRATEGY_META.keys())
    n_configs = len(all_strats) * len(TIMEFRAMES)
    print("=" * 100)
    print("  🔬 SPOT GÖSTERGE KOMBİNASYON LABORATUVARI v5 — KALAN AİLELER (TUR 4)")
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
                    sigs = generate_signals_v5(df, code)
                except Exception as e:
                    print(f"   ⚠️ {code}@{sym}: {e}")
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

    top = res[res["trades"] >= 6].sort_values("net_total", ascending=False).head(12)
    print("\n🏆 EN İYİ 12 COİN × STRATEJİ (≥6 işlem):")
    for _, r in top.iterrows():
        print(f"  {r['symbol']:<11} {r['timeframe']:<4} {r['strategy_name'][:38]:<38} "
              f"İşlem {r['trades']:>3}  WR %{r['win_rate']:>5.1f}  PF {r['pf']:>5.2f}  Net {r['net_total']:>+7.2f}%")

    out = {
        "meta": {"generated_at": pd.Timestamp.now().isoformat(), "round": "v5-kalan-aileler",
                 "symbols": ALL_SYMBOLS, "n_strategy_configs": n_configs,
                 "timeframes": {tf: {"tp": tp, "sl": sl} for tf, (tp, sl) in TIMEFRAMES},
                 "commission_pct": COMMISSION_PCT},
        "strategy_aggregates": agg.to_dict(orient="records"),
        "per_coin_results": rows,
    }
    out_file = Path("outputs/spot_indicator_combos_lab_v5.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n💾 Detaylı log: {out_file}")
    return promoted

if __name__ == "__main__":
    run_lab_v5()
