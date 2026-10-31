"""
15m TF NEDEN ÖLDÜ? — PİYASA REJİMİ KIRILIMI ANALİZİ
====================================================
Üç hipotez test edilir (KRIPTO_ALGO_SISTEMLER.HTML disipliniyle, trade-detaylı):
 H1 Ölçek uyumsuzluğu: TP2.2/SL1.2, 15m volatilitesine göre kaç ATR? Çıkışların
    yüzde kaçı timeout ile kapanıyor? (5m/1h ile karşılaştırma)
 H2 Volatilite rejimi: BTC ATR% tercillerinde (düşük/orta/yüksek) 15m sonuçları.
 H3 Dominans rejimi: BTC dominans vekili (BTC / eşit-ağırlıklı alt sepeti, 12s yön)
    yükselirken (BTC kaçışı) 15m dip alımları düşen bıçak mı oluyor?

Stratejiler: v2-v5 laboratuvarlarından 15m'de en çok işlem üreten 10 temsilci.
Tüm ticaret listesi trade-detaylı toplanır (giriş zamanı, çıkış sebebi, net).
Kurtarma testi: havuz sinyalleri favorable kovalara filtrelenip split-half ile
tutarlılık kontrolü yapılır (filtre aynı veride seçildiği için in-sample notu düşülür).
"""
import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd

from test_advanced_spot_strategies import fetch_binance_klines
from test_indicator_combos_lab import (
    simulate_conservative, ALL_SYMBOLS, fetch_klines_range, generate_signals as gen_v2,
)
from test_indicator_combos_lab_v3 import generate_signals_v3
from test_indicator_combos_lab_v4 import generate_signals_v4

sys.stdout.reconfigure(encoding="utf-8")

TP, SL = 2.2, 1.2  # 15m standart kademe

STRATS = [
    ("KDJ_RSI_CONFLUENCE", "v2", "KDJ+RSI Çift Dip"),
    ("BOLLINGER_VWAP_EXPANSION", "v2", "BB Alt Bant + VWAP"),
    ("ZLMACD_EMA_MOMENTUM", "v2", "Zero-Lag MACD"),
    ("VWAP_RECLAIM_OBV", "v3", "VWAP Geri Kazanım+OBV"),
    ("KAMA_TURN_CHOP", "v3", "KAMA Dönüşü+Chop"),
    ("MCGINLEY_CROSS", "v4", "McGinley Kesişim"),
    ("PSAR_FLIP_ADX", "v3", "PSAR Çevrim+ADX"),
    ("PCTB_RSI_CONFLUENCE", "v3", "Boll %B+RSI"),
    ("CONNORS_RSI3_EMA200", "v2", "Connors RSI3+EMA200"),
    ("HA_TWO_GREEN_FLIP", "v4", "Heikin-Ashi 2 Yeşil"),
]

TFS = {"5m": (1.5, 0.9), "15m": (2.2, 1.2), "1h": (4.0, 2.0)}


def simulate_detail(df: pd.DataFrame, signals: pd.Series, tp_pct: float, sl_pct: float, max_bars=48):
    """simulate_conservative ile aynı motor; trade listesi döndürür (sebep, bar, net, idx)."""
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
                exit_p, reason = opens[i], "sl"
            elif gap_up:
                exit_p, reason = opens[i], "tp"
            elif hit_sl:
                exit_p, reason = stop, "sl"
            elif hit_tp:
                exit_p, reason = target, "tp"
            elif timeout:
                exit_p, reason = closes[i], "time"
            else:
                exit_p = None
            if exit_p is not None:
                gross = (exit_p - entry) / entry * 100.0
                trades.append({"idx": entry_idx, "reason": reason, "bars": i - entry_idx,
                               "net": gross - 0.08})
                pos = False
        if (not pos) and (i < n - 1) and sig[i]:
            pos = True
            entry = opens[i + 1]
            entry_idx = i + 1
    return trades


def fetch_all():
    data = {}  # {tf: {sym: df}}
    for tf in TFS:
        data[tf] = {}
        for sym in ALL_SYMBOLS:
            try:
                data[tf][sym] = fetch_klines_range(sym, interval=tf, total=1500)
            except Exception as e:
                print(f"⚠️ {sym} {tf}: {e}")
    return data


def build_regimes(btc15: pd.DataFrame):
    """BTC 15m barlarına hizalı rejim değişkenleri."""
    close = btc15["close"]
    atr = (close.diff().abs().combine_first((btc15["high"] - btc15["low"])))
    tr = pd.concat([btc15["high"] - btc15["low"],
                    (btc15["high"] - close.shift(1)).abs(),
                    (btc15["low"] - close.shift(1)).abs()], axis=1).max(axis=1)
    atr_pct = (tr.rolling(14).mean() / close * 100.0)
    vol_rank = atr_pct.rolling(750).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True)
    tercile = pd.Series(np.where(vol_rank.isna(), np.nan,
                                 np.where(vol_rank < 0.33, 0, np.where(vol_rank < 0.66, 1, 2))), index=btc15.index)

    ema200 = close.ewm(span=200, adjust=False).mean()
    trend = np.where(close > ema200, "BTC>EMA200", "BTC<EMA200")

    return atr_pct, tercile, trend


def dominance_proxy(btc15: pd.DataFrame, alt_data: dict):
    """Dominans vekili: (BTC normalize) / (eşit-ağırlıklı alt sepeti normalize).
    12h (48 bar) yönü: yükseliyor → BTC kaçışı (dominans artışı), düşüyor → alt mevsimi yönü."""
    btc_norm = (btc15["close"] / btc15["close"].iloc[0]).reset_index(drop=True)
    alts = [sym for sym in alt_data if sym != "BTCUSDT" and len(alt_data[sym]) >= 1000]
    idx = pd.DatetimeIndex(btc15["time"])
    basket = np.zeros(len(btc15))
    cnt = 0
    for sym in alts:
        df = alt_data[sym].set_index("time")
        df = df[~df.index.duplicated()]
        norm = df["close"] / df["close"].iloc[0]
        aligned = norm.reindex(idx, method="ffill").fillna(1.0)
        basket += aligned.values
        cnt += 1
    basket /= max(1, cnt)
    ratio = btc_norm / basket
    prev = ratio.shift(48)
    dom_dir = np.where(prev.isna(), "DOM n/a",
                       np.where(ratio > prev, "DOM↑ (BTC kaçışı)",
                                np.where(ratio < prev, "DOM↓ (alt güçleniyor)", "DOM yatay")))
    return pd.Series(dom_dir), ratio


def main():
    print("=" * 105)
    print("  🔬 15m TF ÖLÜM ANALİZİ — çıkış anatomisi + volatilite rejimi + dominans vekili")
    print("=" * 105)
    print("Veri çekiliyor (5m/15m/1h × 18 coin × 1500 bar)...")
    data = fetch_all()
    n15 = min(len(d) for d in data["15m"].values())
    print(f"Veri hazır: {len(data['15m'])} coin, min {n15} bar/TF\n")

    # ── H1: Çıkış anatomisi ve ATR ölçeği (TF karşılaştırması) ──
    print("=" * 105)
    print("  H1 — ÇIKIŞ ANATOMİSİ (10 strateji havuzu, aynı pencere)")
    print("=" * 105)
    pooled = {tf: [] for tf in TFS}
    atr_scale = {}
    for tf, (tp, sl) in TFS.items():
        for sym, df in data[tf].items():
            if len(df) < 800:
                continue
            d = df.tail(1000).reset_index(drop=True)
            tr = pd.concat([d["high"] - d["low"], (d["high"] - d["close"].shift(1)).abs(),
                            (d["low"] - d["close"].shift(1)).abs()], axis=1).max(axis=1)
            atr_scale.setdefault(tf, []).append(float((tr.rolling(14).mean() / d["close"] * 100.0).median()))
            for code, ver, _ in STRATS:
                sigs = gen_v2(d, code, tf) if ver == "v2" else (
                    generate_signals_v3(d, code) if ver == "v3" else generate_signals_v4(d, code))
                if int(sigs.sum()) < 1:
                    continue
                pooled[tf].extend(simulate_detail(d, sigs, tp, sl))

    fmt = "{:<6} {:>7} {:>8} {:>8} {:>9} {:>9} {:>10} {:>10}"
    print(fmt.format("TF", "İşlem", "TP%", "SL%", "TIME%", "Ort.bar", "Ort.net%", "Medyan ATR%"))
    print("-" * 80)
    for tf in TFS:
        tr = pooled[tf]
        if not tr:
            continue
        cnt = len(tr)
        tp_p = 100 * sum(1 for t in tr if t["reason"] == "tp") / cnt
        sl_p = 100 * sum(1 for t in tr if t["reason"] == "sl") / cnt
        tm_p = 100 * sum(1 for t in tr if t["reason"] == "time") / cnt
        avg_bars = np.mean([t["bars"] for t in tr])
        avg_net = np.mean([t["net"] for t in tr])
        med_atr = float(np.median(atr_scale[tf]))
        print(fmt.format(tf, cnt, f"{tp_p:.1f}", f"{sl_p:.1f}", f"{tm_p:.1f}",
                         f"{avg_bars:.1f}", f"{avg_net:+.3f}", f"{med_atr:.3f}"))
    print("\n→ TP/SL'nin ATR katı: " + ", ".join(
        f"{tf}: TP≈{dict(zip(TFS.keys(), [1.5, 2.2, 4.0]))[tf] / np.median(atr_scale[tf]):.1f}xATR, "
        f"SL≈{dict(zip(TFS.keys(), [0.9, 1.2, 2.0]))[tf] / np.median(atr_scale[tf]):.1f}xATR" for tf in TFS))

    # ── Rejim değişkenleri (15m BTC) ──
    btc_full = data["15m"]["BTCUSDT"].reset_index(drop=True)
    atr_pct, tercile, trend = build_regimes(btc_full)
    dom_dir, ratio = dominance_proxy(btc_full, data["15m"])
    terr_labels = {0: "VOL-düşük", 1: "VOL-orta", 2: "VOL-yüksek"}

    print("\n" + "=" * 105)
    print("  H2+H3 — 15m REJİM KOVALARI (10 strateji × tüm coinler havuzu, giriş anındaki rejim)")
    print("=" * 105)
    tagged = []
    for sym, df in data["15m"].items():
        if len(df) < 1000:
            continue
        d = df.tail(1000).reset_index(drop=True)
        # rejim dizisini bu coine hizala (zaman bazlı ffill, tam 1500-bar BTC penceresi)
        t_map = pd.Series(range(len(btc_full)), index=btc_full["time"])
        pos = d["time"].map(t_map).ffill().fillna(0).astype(int).values
        for code, ver, _ in STRATS:
            sigs = gen_v2(d, code, "15m") if ver == "v2" else (
                generate_signals_v3(d, code) if ver == "v3" else generate_signals_v4(d, code))
            if int(sigs.sum()) < 1:
                continue
            for t in simulate_detail(d, sigs, TP, SL):
                i = t["idx"]
                if pos[i] >= len(btc_full):
                    continue
                tagged.append({**t, "sym": sym, "strat": code,
                               "vol": terr_labels.get(tercile.iloc[pos[i]], "n/a"),
                               "dom": dom_dir.iloc[pos[i]], "trend": trend[pos[i]]})

    tag = pd.DataFrame(tagged)
    if tag.empty:
        print("❌ Etiketli işlem yok.")
        return

    def agg(g):
        wins = (g["net"] > 0).sum()
        gain = g.loc[g["net"] > 0, "net"].sum()
        loss = abs(g.loc[g["net"] <= 0, "net"].sum())
        return pd.Series({"işlem": len(g), "WR%": round(100 * wins / len(g), 1),
                          "PF": round(gain / loss, 2) if loss > 0 else 99.9,
                          "Net%": round(g["net"].sum(), 2)})

    print("\n── Volatilite tercili (BTC 15m ATR% sıra-yüzdesi) ──")
    print(tag.groupby("vol").apply(agg, include_groups=False).to_string())
    print("\n── Dominans vekili yönü (BTC/sepet, 12s değişim) ──")
    print(tag.groupby("dom").apply(agg, include_groups=False).to_string())
    print("\n── BTC trend (15m EMA200) ──")
    print(tag.groupby("trend").apply(agg, include_groups=False).to_string())
    print("\n── Kesişim: vol tercili × dominans yönü ──")
    print(tag.groupby(["vol", "dom"]).apply(agg, include_groups=False).to_string())

    # ── Kurtarma testi: havuz sinyallerini favorable kovaya filtrele ──
    print("\n" + "=" * 105)
    print("  KURTARMA TESTİ — havuz sinyalleri favorable rejim kovasına filtrelenir (split-half)")
    print("=" * 105)
    tab_vol = tag.groupby("vol").apply(agg, include_groups=False)
    tab_dom = tag.groupby("dom").apply(agg, include_groups=False)
    MIN_TR = 100
    cand_vol = tab_vol[(tab_vol.index != "n/a") & (tab_vol["işlem"] >= MIN_TR)]
    cand_dom = tab_dom[(tab_dom.index != "DOM n/a") & (tab_dom["işlem"] >= MIN_TR)]
    favorable = {"vol": cand_vol["Net%"].idxmax() if len(cand_vol) else None,
                 "dom": cand_dom["Net%"].idxmax() if len(cand_dom) else None}
    print(f"Favori kovalar (in-sample seçim, ≥{MIN_TR} işlem): vol={favorable['vol']}, dom={favorable['dom']}")

    def pool_sim(filter_fn=None, half=None):
        """Havuz: aynı coinde stratejilerin sinyal birleşimi, coin başına tek pozisyon."""
        out = []
        lo, hi = (0, 500) if half == 1 else ((500, 1000) if half == 2 else (0, 1000))
        for sym, df in data["15m"].items():
            if len(df) < 1000:
                continue
            d = df.tail(1000).reset_index(drop=True)
            t_map = pd.Series(range(len(btc_full)), index=btc_full["time"])
            pos = d["time"].map(t_map).ffill().fillna(0).astype(int).values
            union = pd.Series(False, index=d.index)
            for code, ver, _ in STRATS:
                sigs = gen_v2(d, code, "15m") if ver == "v2" else (
                    generate_signals_v3(d, code) if ver == "v3" else generate_signals_v4(d, code))
                union = union | sigs.fillna(False)
            if filter_fn is not None:
                mask = np.array([filter_fn(pos[i]) for i in range(len(d))])
                union = union & pd.Series(mask, index=d.index)
            union.iloc[:lo] = False
            union.iloc[hi:] = False
            out.extend(simulate_detail(d, union, TP, SL))
        return out

    for half, half_name in [(None, "tam"), (1, "ilk-yarı"), (2, "son-yarı")]:
        un = pool_sim(None, half)
        def fav(i):
            v = terr_labels.get(tercile.iloc[i], "n/a")
            dm = dom_dir.iloc[i] if i < len(dom_dir) else "DOM n/a"
            return (v != "n/a" and v == favorable["vol"]) and (dm != "DOM n/a" and dm == favorable["dom"])
        fl = pool_sim(fav, half)
        def stats(tr):
            if not tr:
                return "işlem yok"
            g = pd.DataFrame(tr)
            wins = (g["net"] > 0).sum()
            gain = g.loc[g["net"] > 0, "net"].sum()
            loss = abs(g.loc[g["net"] <= 0, "net"].sum())
            return f"{len(g)} işlem, WR %{100 * wins / len(g):.1f}, PF {gain / loss:.2f}, Net {g['net'].sum():+.1f}%"
        print(f"[{half_name:<8}] filtresiz: {stats(un)}")
        print(f"[{half_name:<8}] filtreli: {stats(fl)}")

    # ── JSON ──
    out_file = Path("outputs/spot_15m_regime_analysis.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    tag.to_json(out_file, orient="records", force_ascii=False, indent=1)
    print(f"\n💾 Trade-detaylı log: {out_file}")

if __name__ == "__main__":
    main()
