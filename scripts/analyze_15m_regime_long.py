"""
15m REJİM KAPISI — UZUN PENCERE DOĞRULAMASI (6000 bar ≈ 62 gün)
================================================================
Kısa pencerede (1500 bar) bulunan kurtarma kapısı — "BTC vol-YÜKSEK tercil +
DOM↑ (12s BTC/sepet yükselişi)" — iki yönlü temiz yarı-bölme testiyle
doğrulanır:
  A→B: kova seçimi YALNIZCA 1. yarıda (0-3000), test 2. yarıda (3000-6000)
  B→A: kova seçimi YALNIZCA 2. yarıda, test 1. yarıda
Ek analizler:
  - Üçlü kırılım (0-2000 / 2000-4000 / 4000-6000) kapılı portföy tutarlılığı
  - Eşik duyarlılığı: vol eşiği {0.50, 0.66, 0.75}, DOM yön penceresi {48, 96 bar}
  - Canlı-feasible varyant: vol rank rolling(500) (canlı tarama 500 bar çeker)
Aynı 10 strateji (kısa pencere analiziyle birebir karşılaştırılabilir).
Karar: entegrasyon kullanıcıda — bu script yalnızca kanıt üretir.
"""
import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd

from test_indicator_combos_lab import fetch_klines_range, generate_signals as gen_v2
from test_indicator_combos_lab_v3 import generate_signals_v3
from test_indicator_combos_lab_v4 import generate_signals_v4

sys.stdout.reconfigure(encoding="utf-8")

TP, SL = 2.2, 1.2
N_BARS = 6000
STRATS = [
    ("KDJ_RSI_CONFLUENCE", "v2"), ("BOLLINGER_VWAP_EXPANSION", "v2"),
    ("ZLMACD_EMA_MOMENTUM", "v2"), ("VWAP_RECLAIM_OBV", "v3"),
    ("KAMA_TURN_CHOP", "v3"), ("MCGINLEY_CROSS", "v4"), ("PSAR_FLIP_ADX", "v3"),
    ("PCTB_RSI_CONFLUENCE", "v3"), ("CONNORS_RSI3_EMA200", "v2"),
    ("HA_TWO_GREEN_FLIP", "v4"),
]
ALL_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "DOGEUSDT",
    "PEPEUSDT", "SHIBUSDT", "OPUSDT", "NEARUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "RENDERUSDT", "FETUSDT", "ARBUSDT", "INJUSDT",
]


def simulate_detail(df, signals, tp_pct, sl_pct, max_bars=48):
    opens, highs, lows, closes = (df[c].values for c in ("open", "high", "low", "close"))
    sig = signals.values
    n = len(df)
    trades, pos, entry, entry_idx = [], False, 0.0, -1
    for i in range(n):
        if pos and i >= entry_idx:
            target = entry * (1 + tp_pct / 100)
            stop = entry * (1 - sl_pct / 100)
            if opens[i] <= stop:
                exit_p, reason = opens[i], "sl"
            elif opens[i] >= target:
                exit_p, reason = opens[i], "tp"
            elif lows[i] <= stop:
                exit_p, reason = stop, "sl"
            elif highs[i] >= target:
                exit_p, reason = target, "tp"
            elif (i - entry_idx) >= max_bars:
                exit_p, reason = closes[i], "time"
            else:
                exit_p = None
            if exit_p is not None:
                trades.append({"idx": entry_idx,
                               "net": (exit_p - entry) / entry * 100 - 0.08})
                pos = False
        if (not pos) and (i < n - 1) and sig[i]:
            pos, entry, entry_idx = True, opens[i + 1], i + 1
    return trades


def build_regimes(btc: pd.DataFrame, rank_window=750, dom_window=48):
    close = btc["close"]
    tr = pd.concat([btc["high"] - btc["low"],
                    (btc["high"] - close.shift(1)).abs(),
                    (btc["low"] - close.shift(1)).abs()], axis=1).max(axis=1)
    atr_pct = tr.rolling(14).mean() / close * 100
    vol_rank = atr_pct.rolling(rank_window).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True)
    tercile = pd.Series(np.where(vol_rank.isna(), "n/a",
                                 np.where(vol_rank < 0.33, "VOL-düşük",
                                          np.where(vol_rank < 0.66, "VOL-orta", "VOL-yüksek"))),
                        index=btc.index)
    return tercile, vol_rank


def dominance_series(btc: pd.DataFrame, alt_dfs: dict, dom_window=48):
    idx = pd.DatetimeIndex(btc["time"])
    btc_norm = (btc["close"] / btc["close"].iloc[0]).reset_index(drop=True)
    basket = np.zeros(len(btc))
    cnt = 0
    for sym, df in alt_dfs.items():
        if sym == "BTCUSDT" or len(df) < 1000:
            continue
        d = df.set_index("time")
        d = d[~d.index.duplicated()]
        norm = d["close"] / d["close"].iloc[0]
        basket += norm.reindex(idx, method="ffill").fillna(1.0).values
        cnt += 1
    ratio = btc_norm / (basket / max(1, cnt))
    prev = ratio.shift(dom_window)
    dom = np.where(prev.isna(), "DOM n/a",
                   np.where(ratio > prev, "DOM↑", "DOM↓"))
    return pd.Series(dom), ratio


def agg(g):
    if len(g) == 0:
        return pd.Series({"işlem": 0, "WR%": 0.0, "PF": 0.0, "Net%": 0.0})
    gain = g.loc[g["net"] > 0, "net"].sum()
    loss = abs(g.loc[g["net"] <= 0, "net"].sum())
    return pd.Series({"işlem": len(g), "WR%": round(100 * (g["net"] > 0).mean(), 1),
                      "PF": round(gain / loss, 2) if loss > 0 else 99.9,
                      "Net%": round(g["net"].sum(), 2)})


def main():
    print("=" * 105)
    print(f"  🔬 15m REJİM KAPISI — UZUN PENCERE DOĞRULAMASI ({N_BARS} bar ≈ {N_BARS * 15 / 60 / 24:.0f} gün)")
    print("=" * 105)
    data = {}
    for sym in ALL_SYMBOLS:
        try:
            data[sym] = fetch_klines_range(sym, interval="15m", total=N_BARS)
        except Exception as e:
            print(f"⚠️ {sym}: {e}")
    n_min = min(len(d) for d in data.values())
    data = {s: d.tail(N_BARS).reset_index(drop=True) for s, d in data.items()}
    print(f"Veri: {len(data)} coin x {n_min} bar\n")

    btc = data["BTCUSDT"]
    for rank_w, wtag in [(750, "750 (analiz)"), (500, "500 (canlı-feasible)")]:
        _, vr = build_regimes(btc, rank_w)
        print(f"vol-rank penceresi {wtag}: geçerli bar {int(vr.notna().sum())}/{len(btc)}")

    tercile, _ = build_regimes(btc, 750)
    dom, ratio = dominance_series(btc, data, 48)
    dom96, _ = dominance_series(btc, data, 96)

    print("Trade'ler etiketleniyor (10 strateji × 17 coin)...")
    t_map = pd.Series(range(len(btc)), index=pd.DatetimeIndex(btc["time"]))
    tagged = []
    for sym, df in data.items():
        if sym == "BTCUSDT":
            pass
        d = df
        pos = d["time"].map(t_map).ffill().fillna(0).astype(int).values
        for code, ver in STRATS:
            if ver == "v2":
                sigs = gen_v2(d, code, "15m")
            elif ver == "v3":
                sigs = generate_signals_v3(d, code)
            else:
                sigs = generate_signals_v4(d, code)
            if int(sigs.sum()) < 1:
                continue
            for t in simulate_detail(d, sigs, TP, SL):
                i = min(t["idx"], len(btc) - 1)
                tagged.append({"sym": sym, "strat": code, "idx": t["idx"], "net": t["net"],
                               "vol": tercile.iloc[i], "dom": dom.iloc[i], "dom96": dom96.iloc[i]})
    tag = pd.DataFrame(tagged)
    tag = tag[tag["vol"] != "n/a"]
    tag["cell"] = tag["vol"] + " × " + tag["dom"]
    print(f"Etiketli işlem: {len(tag)} (n/a hariç)\n")

    print("── Tam pencere rejim tablosu (tanımlayıcı) ──")
    print(tag.groupby("vol").apply(agg, include_groups=False).to_string())
    print(tag.groupby("dom").apply(agg, include_groups=False).to_string())
    print(tag.groupby("cell").apply(agg, include_groups=False).sort_values("Net%", ascending=False).to_string())

    half = N_BARS // 2
    print("\n" + "=" * 105)
    print("  İKİ YÖNLÜ TEMİZ YARI-BÖLME TESTİ (kova seçimi ≥100 işlem, Net% en iyi)")
    print("=" * 105)
    verdicts = []
    for sel_name, sel_slice, test_slice in [("A→B", tag[tag["idx"] < half], tag[tag["idx"] >= half]),
                                            ("B→A", tag[tag["idx"] >= half], tag[tag["idx"] < half])]:
        t_sel = sel_slice.groupby("cell").apply(agg, include_groups=False)
        t_sel = t_sel[t_sel["işlem"] >= 100]
        if t_sel.empty:
            print(f"[{sel_name}] seçim yarısında ≥100 işlemli kova yok")
            continue
        best = t_sel["Net%"].idxmax()
        r_sel = t_sel.loc[best]
        r_test = test_slice[test_slice["cell"] == best].pipe(agg)
        ok = r_test["işlem"] > 0 and r_test["Net%"] > 0 and r_test["PF"] >= 1.2
        verdicts.append(ok)
        print(f"[{sel_name}] seçim: {best} → IS PF {r_sel['PF']:.2f}, Net {r_sel['Net%']:+.1f}% ({int(r_sel['işlem'])})")
        print(f"         OOS : {best} → PF {r_test['PF']:.2f}, WR %{r_test['WR%']:.1f}, Net {r_test['Net%']:+.1f}% ({int(r_test['işlem'])})  {'✅ TUTTU' if ok else '❌ TUTMADI'}")

    # Üçlü kırılım: kapılı havuz portföyü
    print("\n── Üçlü kırılım: kapılı vs filtresiz havuz (N/3 barlık dilimler) ──")
    third = N_BARS // 3
    gate_mask = ((tag["vol"] == "VOL-yüksek") & (tag["dom"] == "DOM↑"))
    for k in range(3):
        lo, hi = k * third, (k + 1) * third
        seg = tag[(tag["idx"] >= lo) & (tag["idx"] < hi)]
        gated = seg[gate_mask.reindex(seg.index, fill_value=False)]
        print(f"dilim {k + 1}: filtresiz {agg(seg)['işlem']} işlem / PF {agg(seg)['PF']:.2f} / Net {agg(seg)['Net%']:+.1f}%  |  "
              f"kapılı {agg(gated)['işlem']} işlem / PF {agg(gated)['PF']:.2f} / Net {agg(gated)['Net%']:+.1f}%")

    # Eşik duyarlılığı (tam pencere, tanımlayıcı)
    print("\n── Eşik duyarlılığı (tanımlayıcı, tam pencere) ──")
    for dom_name, dom_s in [("DOM 48s", dom), ("DOM 96s", dom96)]:
        for vthr in (0.50, 0.66, 0.75):
            _, vrank = build_regimes(btc, 750)
            lab = pd.Series(np.where(vrank.isna(), "n/a",
                                     np.where(vrank < 0.33, "VOL-düşük",
                                              np.where(vrank < vthr, "VOL-orta", "VOL-yüksek"))), index=btc.index)
            m = (lab.reindex(tag["vol"].index, method=None) is not None)
            vlab = lab.iloc[tag["idx"].clip(0, len(btc) - 1)].values
            dlab = dom_s.iloc[tag["idx"].clip(0, len(btc) - 1)].values
            sel = tag[(vlab == "VOL-yüksek") & (dlab == "DOM↑")]
            r = agg(sel)
            print(f"{dom_name} + vol>{vthr:.2f}: {int(r['işlem'])} işlem, WR %{r['WR%']:.1f}, PF {r['PF']:.2f}, Net {r['Net%']:+.1f}%")

    print("\n" + "=" * 105)
    if len(verdicts) == 2 and all(verdicts):
        print("  ✅ SONUÇ: Kapı her iki yönde de OOS'ta tuttu → entegrasyon için kanıt güçlü.")
    elif any(verdicts):
        print("  🟡 SONUÇ: Kapı tek yönde tuttu → karara dikkat (kırılgan olabilir).")
    else:
        print("  ❌ SONUÇ: Kapı uzun pencerede doğrulanamadı → entegrasyon önerilmez.")
    print("=" * 105)

    out_file = Path("outputs/spot_15m_regime_long.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    tag.to_json(out_file, orient="records", force_ascii=False)
    print(f"💾 Trade-detaylı log: {out_file}")

if __name__ == "__main__":
    main()
