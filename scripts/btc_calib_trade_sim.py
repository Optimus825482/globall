#!/usr/bin/env python3
"""Son konsolidasyon: (1) 4h zaman dilimi, (2) gerçek SL/TP işlem simülasyonu,
(3) çeyrek bazlı kararlılık, (4) 'long-only vs her-zaman-long' risk-düzeltilmiş kıyas.
"""
import datetime as dt
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import btc_momentum_calibration as C  # noqa: E402


def trade_sim(feat, sig, sl_mult, tp_mult, max_hold_bars, atr_period=14, cost_pct=0.0072):
    """Sinyal barının kapanışından girer; ATR bazlı SL/TP; max_hold sonra kapanış."""
    c, h, l = feat["c"], feat["h"], feat["l"]
    atr = C.atr_pct_series(h, l, c, atr_period) / 100.0 * c  # fiyat cinsinden ATR
    n = feat["n"]
    idx = np.where(sig)[0]
    trades = []
    i = 0
    taken_until = -1
    for k in idx:
        if k <= taken_until:
            continue
        entry = c[k]
        a = atr[k]
        if not np.isfinite(a) or a <= 0:
            continue
        sl = entry - sl_mult * a
        tp = entry + tp_mult * a
        exit_px = None
        end = min(n - 1, k + max_hold_bars)
        for j in range(k + 1, end + 1):
            if l[j] <= sl:
                exit_px = sl
                break
            if h[j] >= tp:
                exit_px = tp
                break
        if exit_px is None:
            exit_px = c[end]
            end = end
        gross = (exit_px / entry - 1.0) * 100.0
        trades.append({"entry_i": k, "exit_i": end, "gross": gross, "net": gross - cost_pct,
                       "bars": end - k})
        taken_until = end  # örtüşmesiz: tek pozisyon
    return trades


def summarize_trades(trades, label):
    if not trades:
        print(f"  {label}: işlem yok")
        return None
    net = np.array([t["net"] for t in trades])
    gross = np.array([t["gross"] for t in trades])
    wr = (net > 0).mean() * 100
    expct = net.mean()
    pnl = net.sum()
    print(f"  {label}: n={len(net):4d} WR={wr:5.1f}% ort_net={expct:+.4f}% topl_net={pnl:+.2f}% "
          f"gross_ort={gross.mean():+.4f}% maxDD~{np.min(np.cumsum(net)):+.2f}%")
    return {"n": len(net), "wr": wr, "exp": expct, "pnl": pnl}


print("=" * 96)
print("(1) 4h ZAMAN DİLİMİ — BTC 'günlük yükseliş' doğal ölçek")
print("=" * 96)
feat4h = C.build_features(C.fetch_klines("BTCUSDT", "4h", 240))
print(f"  4h bar: {feat4h['n']} ({dt.datetime.utcfromtimestamp(feat4h['t'][0]/1000):%Y-%m-%d} → "
      f"{dt.datetime.utcfromtimestamp(feat4h['t'][-1]/1000):%Y-%m-%d})")
# 8h = 2 bar (4h), 24h = 6 bar
for gate in ("none", "ema200", "supertrend"):
    for r8, atr, sl, adx in [(0.5, 0.35, 0.10, 20.0), (1.0, 0.5, 0.20, 20.0), (0.3, 0.25, 0.05, 15.0)]:
        thr = {"ret8": r8, "atr": atr, "slope": sl, "adx": adx, "di": 20.0}
        for hb in (2, 3, 6):
            fwd, mfe, mae = C.forward_stats(feat4h, hb)
            sig = C.mask_for(feat4h, thr, "long", gate) & ~np.isnan(fwd)
            valid = ~np.isnan(fwd)
            if sig.sum() < 20:
                continue
            base = fwd[valid].mean()
            cost = C.cost_scenarios(float(feat4h["c"][-1]), hb * 4)["realistic"]
            net = fwd[sig].mean() - cost
            print(f"  gate={gate:10} H={hb*4:2}h r8>={r8} atr>={atr} n={sig.sum():4d} "
                  f"net={net:+.3f} base={base:+.3f} ex={net-base:+.3f}")

print("\n" + "=" * 96)
print("(2) GERÇEK SL/TP İŞLEM SİMÜLASYONU (15m, ATR bazlı, örtüşmesiz tek pozisyon)")
print("=" * 96)
feat15 = C.build_features(C.fetch_klines("BTCUSDT", "15m", 240))
print("  15m:")
for gate in ("none", "supertrend"):
    for (r8, atr, sl, adx) in [(1.2, 0.5, 0.15, 25.0), (0.5, 0.5, 0.06, 15.0)]:
        thr = {"ret8": r8, "atr": atr, "slope": sl, "adx": adx, "di": 20.0}
        sig = C.mask_for(feat15, thr, "long", gate)
        for (slm, tpm, mh) in [(2.0, 4.0, 96), (1.5, 3.0, 32), (2.0, 6.0, 96)]:
            tr = trade_sim(feat15, sig, slm, tpm, mh)
            summarize_trades(tr, f"gate={gate:10} r8>={r8} SL{slm}ATR TP{tpm}ATR max{mh}b")

# referans: her zaman long (SuperTrend boğa) — filtre yok
st_bull = (feat15["st_dir"] > 0) & ~np.isnan(feat15["ret_8h"])
tr_ref = trade_sim(feat15, st_bull, 2.0, 4.0, 96)
summarize_trades(tr_ref, "REF: her zaman long (SuperTrend boğa)")

print("\n" + "=" * 96)
print("(3) ÇEYREK BAZLI KARARLILIK (en iyi 15m aday, H=8h forward)")
print("=" * 96)
thr = {"ret8": 1.2, "atr": 0.5, "slope": 0.15, "adx": 25.0, "di": 20.0}
fwd8, mfe8, mae8 = C.forward_stats(feat15, 32)
sig = C.mask_for(feat15, thr, "long", "none")
n = feat15["n"]
quarters = [(0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0)]
print(f"  {'çeyrek':22}{'n_sig':>6}{'net%':>9}{'base%':>9}{'excess%':>9}{'hit%':>7}")
for a, b in quarters:
    ia, ib = int(n * a), int(n * b)
    wm = np.zeros(n, dtype=bool)
    wm[ia:ib] = True
    e = C.eval_mask(feat15, fwd8, mfe8, mae8, sig & wm, "long", 0.0072)
    if not e.get("n"):
        print(f"  {dt.datetime.utcfromtimestamp(feat15['t'][ia]/1000):%Y-%m-%d}→{dt.datetime.utcfromtimestamp(feat15['t'][ib-1]/1000):%Y-%m-%d}: sinyal yok")
        continue
    d0 = dt.datetime.utcfromtimestamp(feat15["t"][ia] / 1000).strftime("%Y-%m-%d")
    d1 = dt.datetime.utcfromtimestamp(feat15["t"][ib - 1] / 1000).strftime("%Y-%m-%d")
    print(f"  {d0}→{d1:12}{e['n']:6d}{e['sig_avg_net']:+9.3f}{e['base_avg']:+9.3f}"
          f"{e['excess']:+9.3f}{e['hit']:7.1f}")
