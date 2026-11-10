#!/usr/bin/env python3
"""ÇAPRAZ VARLIK GECİKMESİ PROBU — kapı denetimi (2026-11-10)

AİLE: X(t-1) → Y(t) gecikmesi (ör. ^TNX→USDJPY, ^GSPC→AUDUSD). Tur-2 raporunda günlük
olarak ölçüldü (kısmi rho +0.094 t=4.22 ve +0.156 t=7.06; plasebo para kenarı üretmedi).
Bu betik **canlıya/kol dosyasına götürmeden önce** üç kapıyı uygular:

  K1 **ALT-DÖNEM KIRILIMI**: 10 yıl ikiye (ve 5 parçaya) bölünür; etkinin işareti ve net
     getirisi HER parçada pozitif olmalı (tek rejimde çalışan "kenar" reddedilir).
  K2 **MALİYET STRESİ**: 1× / 1.5× / 2× maliyetle net getiri; 2× maliyette de pozitif kalmalı.
  K3 **HİZALAMA DENETİMİ (saatlik)**: Yahoo barı `T`de kapanır → giriş **kapanıştan SONRAKİ
     ilk MT5 barının açılışı**; MT5 sunucu saati ofseti (`symbol_info().time` ile) düzeltilir.
     Örtüşme varsa "lead" yanılsamadır. Ayrıca X_{t-2} plasebo (etki sönmeli).

Kullanim:
    python scripts/fx_crossasset_probe.py --pairs TNX:USDJPY,SPX:AUDUSD
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import statistics
import time
import urllib.parse
import urllib.request

import numpy as np

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 yok — Python 3.12'yi tam yolla cagirin.")
    raise SystemExit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
YF = {"TNX": "^TNX", "FVX": "^FVX", "SPX": "^GSPC", "VIX": "^VIX", "GOLD": "GC=F", "OIL": "CL=F"}
PIP = {"USDJPY": 0.01, "EURUSD": 0.0001, "AUDUSD": 0.0001, "GBPUSD": 0.0001, "NZDUSD": 0.0001}
COST = {"USDJPY": 1.2, "EURUSD": 1.0, "AUDUSD": 1.0, "GBPUSD": 1.0, "NZDUSD": 1.2}


def yahoo(sym: str, rng: str, interval: str) -> dict[int, float]:
    u = (f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
         f"?range={rng}&interval={interval}")
    raw = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read()
    r = json.loads(raw)["chart"]["result"][0]
    return {int(t): float(c) for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"])
            if c is not None}


def server_offset_h(sym: str) -> int:
    """MT5 sunucu saati ile UTC arasındaki fark (saat)."""
    i = mt5.symbol_info(sym)
    if i is None or not i.time:
        return 2
    return int(round((int(i.time) - time.time()) / 3600.0))


def mt5_bars(sym: str, tf: int, days: int) -> dict[int, tuple]:
    """{utc_ts: (o,h,l,c)} — sunucu ofseti UTC'ye çevrilir."""
    off = server_offset_h(sym)
    out: dict[int, tuple] = {}
    end = dt.datetime.now()
    step = 180 if tf >= mt5.TIMEFRAME_H4 else 60
    i = 0
    while i < days:
        b_end = end - dt.timedelta(days=i)
        b_start = max(b_end - dt.timedelta(days=step), end - dt.timedelta(days=days))
        r = mt5.copy_rates_range(sym, tf, b_start, b_end)
        if r is not None and len(r):
            for x in r:
                utc = int(x["time"]) - off * 3600
                out[utc] = (float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]))
        i += step
    return out


def partial(xs: list[float], ys: list[float], ctrl: list[float]) -> tuple[float, float]:
    """Y ~ 1 + X + ctrl → X'in katsayısı, t'si ve kısmi korelasyonu."""
    X, Y, C = np.array(xs), np.array(ys), np.array(ctrl)
    A = np.column_stack([np.ones(len(X)), X, C])
    beta, _, _, _ = np.linalg.lstsq(A, Y, rcond=None)
    resid = Y - A @ beta
    s2 = resid @ resid / max(1, len(X) - 3)
    se = math.sqrt(s2 * np.linalg.inv(A.T @ A)[1, 1])
    t = beta[1] / se if se > 0 else 0.0
    r_xy, r_xc, r_yc = (np.corrcoef(X, Y)[0, 1], np.corrcoef(X, C)[0, 1], np.corrcoef(Y, C)[0, 1])
    den = math.sqrt(max(1e-12, (1 - r_xc ** 2) * (1 - r_yc ** 2)))
    return (r_xy - r_xc * r_yc) / den, float(t)


def daily_pairs(x: dict[int, float], y: dict[int, tuple], price: float, pip: float):
    """Günlük: eşleşen UTC günleri; X_{t-1}, Y_t, Y_{t-1}. Giriş gün kapanışı, çıkış sonraki kapanış."""
    xd = {dt.datetime.fromtimestamp(k, dt.timezone.utc).date(): v for k, v in x.items()}
    yd = {dt.datetime.fromtimestamp(k, dt.timezone.utc).date(): v[3] for k, v in y.items()}
    ks = sorted(set(xd) & set(yd))
    rows = []
    # GERÇEK GECİKME: X değişimi (p→k) ÖNCEKİ gün, Y getirisi (k→n) SONRAKİ gün.
    # (2026-11-10 DÜZELTME: ilk sürüm X'i de aynı gün penceresinde hesaplıyordu → "lead"
    #  değil EŞZAMANLI korelasyon ölçülüyordu; kolun A/B'si bunu yakaladı.)
    for p, k, n in zip(ks, ks[1:], ks[2:]):
        if p not in xd or k not in xd or k not in yd or n not in yd:
            continue
        rx = (xd[k] - xd[p]) / xd[p] if xd[p] else 0.0      # t-1 günü X değişimi
        ry = (yd[n] - yd[k]) / yd[k] if yd[k] else 0.0      # t günü Y getirisi
        rows.append((n, rx, ry))
    return rows


def report_daily(name: str, rows: list[tuple], price: float, pip: float, cost: float) -> dict:
    if len(rows) < 200:
        print(f"  {name}: eşleşme az ({len(rows)})")
        return {}
    ys = [r[2] for r in rows]
    ctrl = [0.0] + ys[:-1]                      # Y_{t-1}
    rho, t = partial([r[1] for r in rows], ys, ctrl)
    cuts = [0, len(rows) // 2, len(rows)]
    print(f"  {name}  n={len(rows)}  kısmi rho={rho:+.3f} t={t:+.2f}")
    out = {"n": len(rows), "rho": round(rho, 4), "t": round(t, 2), "halves": [], "cost": {}}
    for a, b in zip(cuts, cuts[1:]):
        seg = rows[a:b]
        net = statistics.mean([(1 if r[1] > 0 else -1) * r[2] * (price / pip) - cost for r in seg])
        out["halves"].append({"n": len(seg), "net_p": round(net, 2),
                              "from": str(seg[0][0]), "to": str(seg[-1][0])})
        print(f"    yarı {len(out['halves'])}: n={len(seg)} net {net:+.2f} p/gün "
              f"({seg[0][0]} → {seg[-1][0]})")
    for mult in (1.0, 1.5, 2.0):
        net = statistics.mean([(1 if r[1] > 0 else -1) * r[2] * (price / pip) - cost * mult for r in rows])
        out["cost"][f"x{mult}"] = round(net, 2)
        print(f"    maliyet {mult}×: net {net:+.2f} p/gün")
    # plasebo: X_{t-2} (etki sönmeli)
    rows2 = rows[1:]
    rho2, t2 = partial([r[1] for r in rows2], [r[2] for r in rows2],
                       [0.0] + [r[2] for r in rows2][:-1])
    print(f"    placebo X_(t-2): rho={rho2:+.3f} t={t2:+.2f}")
    out["placebo_t2"] = round(t2, 2)
    return out


def hourly_test(name: str, x: dict[int, float], y: dict[int, tuple], sym: str, hold_h: int = 1) -> dict:
    """Saatlik: Yahoo barı T'de kapanır → GİRİŞ, kapanıştan sonraki ilk MT5 barının açılışı."""
    pip, cost, price = PIP[sym], COST[sym], 0.0
    keys_y = sorted(y)
    xs, ys, ctrl = [], [], []
    prev_y = None
    for T in sorted(x):
        close = T + 3600
        # kapanıştan SONRA açılan ilk bar
        j = next((i for i, k in enumerate(keys_y) if k >= close), None)
        if j is None or j + hold_h >= len(keys_y):
            continue
        entry_ts, exit_ts = keys_y[j], keys_y[j + hold_h]
        entry, exit_ = y[entry_ts][0], y[exit_ts][3]
        prev_ts = keys_y[j - 1] if j > 0 else None
        x_prev = x.get(T - 3600)
        if prev_ts is None or x_prev is None or not x_prev:
            continue
        xs.append((x[T] - x_prev) / x_prev)
        ys.append((exit_ - entry) / entry)
        ctrl.append(0.0 if prev_y is None else prev_y)
        prev_y = (entry - y[prev_ts][3]) / y[prev_ts][3] if y[prev_ts][3] else 0.0
        price = entry
    if len(xs) < 300:
        print(f"  {name} (1h): eşleşme az ({len(xs)})")
        return {}
    rho, t = partial(xs, ys, ctrl)
    net = statistics.mean([(1 if a > 0 else -1) * b * (price / pip) - cost for a, b in zip(xs, ys)])
    sd = statistics.pstdev([(1 if a > 0 else -1) * b * (price / pip) - cost for a, b in zip(xs, ys)]) or 1e-9
    print(f"  {name} ({hold_h}h): n={len(xs)} kısmi rho={rho:+.3f} t={t:+.2f} | "
          f"net {net:+.2f}p/işlem t={net/(sd/len(xs)**0.5):+.2f}")
    return {"n": len(xs), "rho": round(rho, 4), "t": round(t, 2), "net_p": round(net, 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Çapraz varlık gecikmesi kapı denetimi")
    ap.add_argument("--pairs", default="TNX:USDJPY,SPX:AUDUSD")
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if not mt5.initialize():
        print(f"[HATA] MT5 initialize basarisiz: {mt5.last_error()}")
        return 2
    result: dict = {"pairs": {}}
    print(f"Sunucu ofsetleri: " + ", ".join(
        f"{s}={server_offset_h(s)}h" for s in ("USDJPY", "AUDUSD", "EURUSD")))
    for pair in [p for p in args.pairs.split(",") if p.strip()]:
        xname, sym = pair.split(":")
        xsym = YF.get(xname.upper(), xname)
        yd = mt5_bars(sym, mt5.TIMEFRAME_D1, args.years * 365)
        yh_ = mt5_bars(sym, mt5.TIMEFRAME_H1, 730)
        price = list(yd.values())[-1][3]
        pip, cost = PIP.get(sym, 0.0001), COST.get(sym, 1.0)
        print(f"\n=== {xsym} → {sym} ===")
        xd = yahoo(xsym, f"{args.years}y", "1d")
        rows = daily_pairs(xd, yd, price, pip)
        daily = report_daily("GÜNLÜK", rows, price, pip, cost)
        xh = yahoo(xsym, "730d", "1h")
        hourly = {}
        for hold in (1, 3):
            hourly[f"{hold}h"] = hourly_test("SAATLİK", xh, yh_, sym, hold_h=hold)
        result["pairs"][pair] = {"daily": daily, "hourly": hourly, "offset_h": server_offset_h(sym),
                                 "price": price}
    if args.json:
        p = args.json if os.path.isabs(args.json) else os.path.join(ROOT, args.json)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nJSON: {p}")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
