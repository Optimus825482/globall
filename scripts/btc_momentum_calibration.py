#!/usr/bin/env python3
"""BTCUSD momentum-katmanı kalibrasyonu (V4 'günlük yükseliş' filtresinin BTC'ye taşınması).

NEDEN: V4'ün altcoin momentum filtresi
    ret_8h >= +2%  AND  ATR% >= 0.5  AND  ADX >= 25 (+DI>20)  AND  slope >= 0.3
BTC'de anlamsız çünkü eşikler 20-50x katı kalibre (BTC 15m ATR% medyanı ~0.22, eşik 0.5).
Bu script BTC'ye ÖZEL eşik grid'ini train/test + walk-forward ile tarar ve
maliyet-sonrası NET edge'i ölçer. KABUL: lift>1.2x VE test'te tutuyor VE n>=50 VE net>0.

Veri: Binance Global public REST (api.binance.com, keyless). Kapanmamış son mum atılır.

Kullanım:
    python scripts/btc_momentum_calibration.py --days 240
    python scripts/btc_momentum_calibration.py --validate   # briefteki 26/5924 bulgusunu doğrula
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "outputs")
CACHE_DIR = os.path.join(OUT_DIR, "btc_cache")
BASE_URL = "https://api.binance.com/api/v3/klines"
INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
               "1h": 3_600_000, "4h": 14_400_000}


# ---------------------------------------------------------------------------
# 1) VERİ
# ---------------------------------------------------------------------------
def fetch_klines(symbol: str, interval: str, days: int, use_cache: bool = True) -> list[list]:
    """Binance Global'den geriye doğru sayfalayarak `days` günlük kapanmış mum çeker.

    Dönen bar: [open_time_ms, o, h, l, c, v]. Son (oluşmakta olan) mum ATILIR.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f"{symbol}_{interval}_{days}d.json")
    if use_cache and os.path.exists(cache_path):
        age_h = (time.time() - os.path.getmtime(cache_path)) / 3600
        if age_h < 6:
            with open(cache_path, encoding="utf-8") as fh:
                return json.load(fh)

    step = INTERVAL_MS[interval]
    end = int(time.time() * 1000)
    start = end - days * 86_400_000
    bars: list[list] = []
    cursor = end
    while cursor > start:
        url = (f"{BASE_URL}?symbol={symbol}&interval={interval}"
               f"&limit=1000&endTime={cursor}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            chunk = json.loads(resp.read().decode())
        if not chunk:
            break
        bars = chunk + bars
        cursor = int(chunk[0][0]) - 1
        time.sleep(0.12)
    # normalize
    out = [[int(b[0]), float(b[1]), float(b[2]), float(b[3]), float(b[4]), float(b[5])] for b in bars]
    out.sort(key=lambda r: r[0])
    # kapanmamış son mumu at (açılış + aralık > şimdi)
    if out and out[-1][0] + step > int(time.time() * 1000):
        out = out[:-1]
    # tekilleştir
    seen = set()
    dedup = []
    for r in out:
        if r[0] not in seen:
            seen.add(r[0])
            dedup.append(r)
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(dedup, fh)
    return dedup


# ---------------------------------------------------------------------------
# 2) GÖSTERGELER (V4 kanonik tanımlarına birebir uyumlu)
# ---------------------------------------------------------------------------
def wilder_series(vals: np.ndarray, period: int) -> np.ndarray:
    """Wilder düzleştirme: ilk değer ilk `period`'un ortalaması, sonra özyineleme."""
    n = len(vals)
    out = np.full(n, np.nan)
    if n < period:
        return out
    out[period - 1] = float(np.mean(vals[:period]))
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + vals[i]) / period
    return out


def true_range(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    n = len(c)
    tr = np.full(n, np.nan)
    if n < 2:
        return tr
    tr[1:] = np.maximum(h[1:] - l[1:],
                        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return tr


def atr_pct_series(h, l, c, period=14) -> np.ndarray:
    """V4 `_atr` tanımı: son `period` barın TR basit ortalaması / fiyat × 100."""
    n = len(c)
    tr = true_range(h, l, c)
    out = np.full(n, np.nan)
    for i in range(period, n):
        seg = tr[i - period + 1:i + 1]
        if np.any(np.isnan(seg)):
            continue
        m = float(np.mean(seg))
        if c[i]:
            out[i] = m / c[i] * 100.0
    return out


def adx_series(h, l, c, period=14):
    """Kanonik ADX: Wilder +DI/-DI, DX, sonra Wilder ADX. (adx, +di, -di) döner."""
    n = len(c)
    adxv = np.full(n, np.nan)
    pdiv = np.full(n, np.nan)
    mdiv = np.full(n, np.nan)
    if n < 2 * period + 2:
        return adxv, pdiv, mdiv
    tr = true_range(h, l, c)[1:]
    up = h[1:] - h[:-1]
    dn = l[:-1] - l[1:]
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    trw = wilder_series(tr, period)
    plusw = wilder_series(plus, period)
    minusw = wilder_series(minus, period)
    valid = ~np.isnan(trw)
    dx = np.zeros(len(trw))
    pdi_arr = np.zeros(len(trw))
    mdi_arr = np.zeros(len(trw))
    for k in range(len(trw)):
        a = trw[k]
        if np.isnan(a):
            continue
        p = 100.0 * plusw[k] / a if a else 0.0
        m = 100.0 * minusw[k] / a if a else 0.0
        pdi_arr[k] = p
        mdi_arr[k] = m
        dx[k] = 100.0 * abs(p - m) / (p + m) if (p + m) else 0.0
    dx_valid = dx[valid]
    adxw = wilder_series(dx_valid, period)
    for k in range(len(trw)):
        if np.isnan(trw[k]):
            continue
        bar = 1 + k  # tr/plus index k -> bar k+1
        pdiv[bar] = pdi_arr[k]
        mdiv[bar] = mdi_arr[k]
    # adxw[j] -> bar 1 + (period-1+j) = period + j
    for j in range(len(adxw)):
        if not np.isnan(adxw[j]):
            adxv[period + j] = adxw[j]
    return adxv, pdiv, mdiv


def linreg_slope_pct_series(c, period=10) -> np.ndarray:
    """V4 `_linreg_slope_pct`: son `period` barın eğimi, ortalamaya göre %/bar."""
    n = len(c)
    out = np.full(n, np.nan)
    xs = np.arange(period, dtype=np.float64)
    xc = xs - xs.mean()
    denom = float((xc ** 2).sum())
    for i in range(period - 1, n):
        ys = c[i - period + 1:i + 1]
        mean_y = float(ys.mean())
        if mean_y == 0:
            continue
        slope = float((xc * (ys - mean_y)).sum() / denom)
        out[i] = slope / mean_y * 100.0
    return out


def ema_series(vals, period) -> np.ndarray:
    n = len(vals)
    out = np.full(n, np.nan)
    if n < period:
        return out
    cur = float(np.mean(vals[:period]))
    out[period - 1] = cur
    alpha = 2.0 / (period + 1)
    for i in range(period, n):
        cur = alpha * float(vals[i]) + (1 - alpha) * cur
        out[i] = cur
    return out


def rsi_series(c, period=14) -> np.ndarray:
    n = len(c)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    d = np.diff(c)
    gains = np.where(d > 0, d, 0.0)
    losses = np.where(d < 0, -d, 0.0)
    ag = float(np.mean(gains[:period]))
    al = float(np.mean(losses[:period]))
    out[period] = 100.0 if al == 0 and ag > 0 else (50.0 if al == 0 else 100 - 100 / (1 + ag / al))
    for i in range(period, len(d)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
        out[i + 1] = 100.0 if al == 0 and ag > 0 else (50.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return out


def atr_wilder_series(h, l, c, period=14) -> np.ndarray:
    tr = true_range(h, l, c)
    tr[0] = np.nan
    return wilder_series(np.nan_to_num(tr[1:], nan=0.0), period) if False else _wilder_aligned(tr, period)


def _wilder_aligned(tr, period):
    n = len(tr)
    out = np.full(n, np.nan)
    vals = tr[1:]
    ws = wilder_series(vals, period)
    for k in range(len(ws)):
        out[1 + k] = ws[k]
    return out


def supertrend_series(h, l, c, period=10, factor=3.0):
    """Standart SuperTrend (Wilder ATR). Yön: +1 boğa, -1 ayı."""
    n = len(c)
    atr = _wilder_aligned(true_range(h, l, c), period)
    direction = np.full(n, 0, dtype=int)
    line = np.full(n, np.nan)
    prev_line = np.nan
    prev_dir = 1
    for i in range(n):
        if np.isnan(atr[i]):
            continue
        mid = (h[i] + l[i]) / 2.0
        upper = mid + factor * atr[i]
        lower = mid - factor * atr[i]
        if np.isnan(prev_line):
            d = 1 if c[i] >= lower else -1
            ln = lower if d == 1 else upper
        else:
            d = 1 if c[i] >= prev_line else -1
            if d == 1:
                ln = max(lower, prev_line) if prev_dir == 1 else lower
            else:
                ln = min(upper, prev_line) if prev_dir == -1 else upper
        direction[i] = d
        line[i] = ln
        prev_line, prev_dir = ln, d
    return line, direction


def mfi_series(h, l, c, v, period=14) -> np.ndarray:
    n = len(c)
    out = np.full(n, np.nan)
    typical = (h + l + c) / 3.0
    flow = typical * v
    for i in range(period, n):
        pos = neg = 0.0
        for j in range(i - period + 1, i + 1):
            if typical[j] > typical[j - 1]:
                pos += flow[j]
            elif typical[j] < typical[j - 1]:
                neg += flow[j]
        out[i] = 100 - 100 / (1 + pos / neg) if neg else (100.0 if pos > 0 else 50.0)
    return out


def bb_width_pct_series(c, period=20, std_mult=2.0) -> np.ndarray:
    n = len(c)
    out = np.full(n, np.nan)
    for i in range(period - 1, n):
        seg = c[i - period + 1:i + 1]
        m = float(seg.mean())
        sd = float(seg.std())
        if m:
            out[i] = (2 * std_mult * sd) / m * 100.0
    return out


# ---------------------------------------------------------------------------
# 3) ÖZELLİK MATRİSİ
# ---------------------------------------------------------------------------
def build_features(bars: list[list]) -> dict:
    t = np.array([b[0] for b in bars], dtype=np.float64)
    o = np.array([b[1] for b in bars])
    h = np.array([b[2] for b in bars])
    l = np.array([b[3] for b in bars])
    c = np.array([b[4] for b in bars])
    v = np.array([b[5] for b in bars])
    n = len(c)

    ret_8h = np.full(n, np.nan)          # 32 bar (15m) = 8 saat
    if n > 32:
        ret_8h[32:] = (c[32:] / c[:-32] - 1.0) * 100.0

    atr_pct = atr_pct_series(h, l, c, 14)
    adx, plus_di, minus_di = adx_series(h, l, c, 14)
    slope = linreg_slope_pct_series(c, 10)
    ema50 = ema_series(c, 50)
    ema200 = ema_series(c, 200)
    st_line, st_dir = supertrend_series(h, l, c, 10, 3.0)
    rsi = rsi_series(c, 14)
    mfi = mfi_series(h, l, c, v, 14)
    bbw = bb_width_pct_series(c, 20, 2.0)

    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "n": n,
            "ret_8h": ret_8h, "atr_pct": atr_pct, "adx": adx, "plus_di": plus_di,
            "minus_di": minus_di, "slope": slope, "ema50": ema50, "ema200": ema200,
            "st_line": st_line, "st_dir": st_dir, "rsi": rsi, "mfi": mfi, "bbw": bbw}


def forward_stats(feat: dict, horizon_bars: int):
    """Her bar için ileri getiri + MFE/MAE (yön-bağımsız, uzun perspektifinden)."""
    c, h, l, n = feat["c"], feat["h"], feat["l"], feat["n"]
    fwd = np.full(n, np.nan)
    mfe = np.full(n, np.nan)
    mae = np.full(n, np.nan)
    for i in range(n - horizon_bars):
        entry = c[i]
        if not entry:
            continue
        fwd[i] = (c[i + horizon_bars] / entry - 1.0) * 100.0
        seg_h = h[i + 1:i + horizon_bars + 1]
        seg_l = l[i + 1:i + horizon_bars + 1]
        mfe[i] = (seg_h.max() / entry - 1.0) * 100.0
        mae[i] = (seg_l.min() / entry - 1.0) * 100.0
    return fwd, mfe, mae


# ---------------------------------------------------------------------------
# 4) DEĞERLENDİRME
# ---------------------------------------------------------------------------
def mask_for(feat: dict, thr: dict, direction: str, gate: str) -> np.ndarray:
    """Eşik sözlüğü + yön + trend kapısı → boolean sinyal maskesi."""
    n = feat["n"]
    valid = (np.arange(n) >= 210)  # EMA200 + ADX ısınma payı
    for key in ("ret_8h", "atr_pct", "adx", "slope", "ema200"):
        valid &= ~np.isnan(feat[key])
    valid &= ~np.isnan(feat["st_dir"])

    atr_ok = feat["atr_pct"] >= thr["atr"]
    adx_ok = feat["adx"] >= thr["adx"]
    if direction == "long":
        mom = feat["ret_8h"] >= thr["ret8"]
        sl = feat["slope"] >= thr["slope"]
        di = feat["plus_di"] > thr["di"]
        gate_ok = np.ones(n, dtype=bool)
        if gate == "ema200":
            gate_ok = feat["c"] > feat["ema200"]
        elif gate == "supertrend":
            gate_ok = feat["st_dir"] > 0
        elif gate == "both":
            gate_ok = (feat["c"] > feat["ema200"]) & (feat["st_dir"] > 0)
        return valid & mom & atr_ok & adx_ok & sl & di & gate_ok

    # short: ayna simetri
    mom = feat["ret_8h"] <= -thr["ret8"]
    sl = feat["slope"] <= -thr["slope"]
    di = feat["minus_di"] > thr["di"]
    gate_ok = np.ones(n, dtype=bool)
    if gate == "ema200":
        gate_ok = feat["c"] < feat["ema200"]
    elif gate == "supertrend":
        gate_ok = feat["st_dir"] < 0
    elif gate == "both":
        gate_ok = (feat["c"] < feat["ema200"]) & (feat["st_dir"] < 0)
    return valid & mom & atr_ok & adx_ok & sl & di & gate_ok


def eval_mask(feat: dict, fwd: np.ndarray, mfe: np.ndarray, mae: np.ndarray,
              sig: np.ndarray, direction: str, cost_pct: float) -> dict:
    """Bir sinyal maskesinin baz-orana göre edge'ini ölçer (maliyet NET)."""
    n = feat["n"]
    base_valid = ~np.isnan(fwd)
    base = fwd[base_valid]
    if len(base) == 0:
        return {"n": 0}
    sig_valid = sig & base_valid
    idx = np.where(sig_valid)[0]
    k = len(idx)
    if k == 0:
        return {"n": 0, "base_avg": float(base.mean())}

    sign = 1.0 if direction == "long" else -1.0
    sig_ret_gross = sign * fwd[idx]
    sig_ret_net = sig_ret_gross - cost_pct
    base_ret = base if direction == "long" else -base

    hit = float((sig_ret_net > 0).mean()) * 100.0
    base_hit = float((base_ret > 0).mean()) * 100.0

    sig_avg_net = float(sig_ret_net.mean())
    base_avg = float(base_ret.mean())
    # lift: ortalama getiri oranı (baz negatifse işaret-duyarlı mutlak fark da verilir)
    ret_lift = (sig_avg_net / base_avg) if base_avg not in (0.0,) else float("nan")
    hit_lift = (hit / base_hit) if base_hit else float("nan")

    mfe_sig = float((sign * mfe[idx]).mean()) if direction == "long" else float((-mfe[idx]).mean())
    mae_sig = float((sign * mae[idx]).mean()) if direction == "long" else float((-mae[idx]).mean())

    return {"n": k,
            "exposure_pct": round(100.0 * k / len(base), 2),
            "sig_avg_net": round(sig_avg_net, 4),
            "sig_avg_gross": round(float(sig_ret_gross.mean()), 4),
            "base_avg": round(base_avg, 4),
            "excess": round(sig_avg_net - base_avg, 4),
            "ret_lift": round(ret_lift, 3) if np.isfinite(ret_lift) else None,
            "hit": round(hit, 1),
            "base_hit": round(base_hit, 1),
            "hit_lift": round(hit_lift, 3) if np.isfinite(hit_lift) else None,
            "mfe_mean": round(mfe_sig, 3),
            "mae_mean": round(mae_sig, 3)}


# ---------------------------------------------------------------------------
# 5) MALİYET
# ---------------------------------------------------------------------------
def cost_scenarios(px: float, horizon_h: int) -> dict:
    """BTCUSD CFD round-trip maliyeti (%) — MT5 p95 spread 5 pips (pip_size=1.0)."""
    real = {"spread": 5.0, "commission": 0.0, "slippage": 1.0, "funding_per_8h": 0.0}
    cons = {"spread": 15.0, "commission": 0.0, "slippage": 3.0, "funding_per_8h": 0.03}
    out = {}
    for name, s in (("realistic", real), ("conservative", cons)):
        spread_pct = s["spread"] / px * 100.0
        slip_pct = s["slippage"] / px * 100.0
        funding = s["funding_per_8h"] * (horizon_h / 8.0)
        out[name] = round(spread_pct + s["commission"] + slip_pct + funding, 4)
    return out


# ---------------------------------------------------------------------------
# 6) GRID + OVERFIT KONTROLÜ
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=240)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--horizons", default="2,4,8,24")
    ap.add_argument("--validate", action="store_true",
                    help="Briefteki 26/5924 V4 filtresi bulgusunu doğrula ve çık.")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    print(f"[VERI] {args.symbol} çekiliyor ({args.days} gün, 15m)...", flush=True)
    bars = fetch_klines(args.symbol, "15m", args.days, use_cache=not args.no_cache)
    print(f"[VERI] {len(bars)} kapanmış 15m bar "
          f"({dt.datetime.utcfromtimestamp(bars[0][0]/1000):%Y-%m-%d} → "
          f"{dt.datetime.utcfromtimestamp(bars[-1][0]/1000):%Y-%m-%d} UTC)", flush=True)

    feat = build_features(bars)
    last_px = float(feat["c"][-1])
    print(f"[VERI] son kapanış ${last_px:,.2f}", flush=True)
    med_atr = float(np.nanmedian(feat["atr_pct"]))
    med_ret8 = float(np.nanmedian(feat["ret_8h"]))
    med_slope = float(np.nanmedian(feat["slope"]))
    print(f"[OLCUM] medyan ATR%={med_atr:.3f} ret_8h={med_ret8:+.3f}% slope={med_slope:.4f}", flush=True)

    # --- V4 filtre doğrulama (brief: son ~62 günde 26/5924) ---
    if args.validate:
        v4_thr = {"ret8": 2.0, "atr": 0.5, "adx": 25.0, "slope": 0.3, "di": 20.0}
        look = 5924
        sl = slice(max(0, len(bars) - look - 1), len(bars) - 1)
        sub = {k: (v[sl] if isinstance(v, np.ndarray) and v.ndim == 1 and len(v) == feat["n"] else v)
               for k, v in feat.items()}
        sub["n"] = len(sub["c"])
        sig = mask_for(sub, v4_thr, "long", "none")
        sig[~np.isfinite(sub["ret_8h"])] = False
        fwd_v, _, _ = forward_stats(sub, 16)
        e = eval_mask(sub, fwd_v, fwd_v, fwd_v, sig, "long", 0.06)
        print(f"[V4-DOGRULAMA] {sub['n']} bar içinde filtre {int(sig.sum())} kez tetikledi "
              f"({100*sig.sum()/sub['n']:.2f}%)", flush=True)
        if e.get("n"):
            print(f"[V4-DOGRULAMA] +4s sig_avg={e['sig_avg_gross']:+.3f}%  base={e['base_avg']:+.3f}%  "
                  f"lift={e['ret_lift']}", flush=True)
        return

    horizons_h = [int(x) for x in args.horizons.split(",")]
    grid = {
        "atr": [0.15, 0.25, 0.35, 0.5],
        "ret8": [0.3, 0.5, 0.8, 1.2],
        "slope": [0.03, 0.06, 0.10, 0.15],
        "adx": [15.0, 20.0, 25.0],
        "di": [20.0],
    }
    gates = ["none", "ema200", "supertrend", "both"]
    directions = ["long", "short"]

    results = {}
    for horizon_h in horizons_h:
        hb = horizon_h * 4  # 15m bar
        fwd, mfe, mae = forward_stats(feat, hb)
        costs = cost_scenarios(last_px, horizon_h)
        n = feat["n"]
        half = n // 2
        train_idx = np.zeros(n, dtype=bool)
        train_idx[:half] = True
        test_idx = ~train_idx
        # walk-forward pencereleri
        k_wf = 6
        wf_bounds = [(int(n * j / k_wf), int(n * (j + 1) / k_wf)) for j in range(k_wf)]

        rows = []
        for direction in directions:
            for gate in gates:
                for atr in grid["atr"]:
                    for ret8 in grid["ret8"]:
                        for slope in grid["slope"]:
                            for adx in grid["adx"]:
                                thr = {"atr": atr, "ret8": ret8, "slope": slope,
                                       "adx": adx, "di": 20.0}
                                full = mask_for(feat, thr, direction, gate)
                                if full.sum() < 20:
                                    continue
                                for cname, cost in costs.items():
                                    ev = eval_mask(feat, fwd, mfe, mae, full, direction, cost)
                                    if ev.get("n", 0) < 20:
                                        continue
                                    tr = eval_mask(feat, fwd, mfe, mae, full & train_idx, direction, cost)
                                    te = eval_mask(feat, fwd, mfe, mae, full & test_idx, direction, cost)
                                    wf = []
                                    for (a, b) in wf_bounds:
                                        wm = np.zeros(n, dtype=bool)
                                        wm[a:b] = True
                                        wf.append(eval_mask(feat, fwd, mfe, mae, full & wm, direction, cost))
                                    rows.append({
                                        "direction": direction, "gate": gate, "cost": cname,
                                        "horizon_h": horizon_h, "cost_pct": cost,
                                        "thr": dict(thr), "full": ev, "train": tr, "test": te,
                                        "wf": [{"n": w.get("n", 0),
                                                "excess": w.get("excess"),
                                                "hit_lift": w.get("hit_lift")} for w in wf],
                                    })
        results[horizon_h] = rows
        print(f"[GRID] {horizon_h}s: {len(rows)} kombinasyon değerlendirildi", flush=True)

    # --- Özet: kabul kriterine en yakın adaylar ---
    def accept_score(r):
        fr, tr, te = r["full"], r["train"], r["test"]
        if not fr.get("n") or not tr.get("n") or not te.get("n"):
            return -99
        hl = fr.get("hit_lift") or 0
        excess = fr.get("excess") or -99
        net = fr.get("sig_avg_net") or -99
        return (1 if (hl > 1.2 and net > 0 and excess > 0) else 0) * 100 + hl * 10 + excess

    print("\n=== EN IYI 12 ADAY (tam pencere, hit_lift'e göre) ===", flush=True)
    flat = [r for rows in results.values() for r in rows]
    flat.sort(key=lambda r: ((r["full"].get("hit_lift") or 0)), reverse=True)
    for r in flat[:12]:
        fr, te, tr = r["full"], r["test"], r["train"]
        wf_ok = sum(1 for w in r["wf"] if (w["excess"] or -9) > 0)
        print(f"  {r['direction']:5} {r['gate']:10} {r['cost']:12} H={r['horizon_h']:2}h "
              f"ATR{ r['thr']['atr']:.2f} r8{ r['thr']['ret8']:.1f} sl{r['thr']['slope']:.2f} adx{r['thr']['adx']:.0f} | "
              f"n={fr['n']:4d} net={fr['sig_avg_net']:+.3f} base={fr['base_avg']:+.3f} "
              f"hitL={fr['hit_lift']} retL={fr['ret_lift']} | "
              f"TR n={tr.get('n',0):3d} ex={tr.get('excess')} TE n={te.get('n',0):3d} ex={te.get('excess')} | "
              f"WF+={wf_ok}/{len(r['wf'])}", flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"btc_momentum_calibration_{args.days}d.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"meta": {"symbol": args.symbol, "days": args.days, "bars": len(bars),
                            "last_price": last_px, "med_atr_pct": med_atr,
                            "med_ret_8h": med_ret8, "med_slope": med_slope,
                            "generated_utc": dt.datetime.utcnow().isoformat() + "Z"},
                   "results": {str(k): v for k, v in results.items()}}, fh, ensure_ascii=False, indent=2)
    print(f"\n[CIKTI] → {out_path}", flush=True)


if __name__ == "__main__":
    main()
