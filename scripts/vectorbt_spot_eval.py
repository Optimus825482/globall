"""Spot Monitor stratejilerinin GERÇEK vectorbt ile testi.

Neden ayrı bir modül: `ai_trading_suite/vectorbt_optimizer.py` vectorbt'i hiç
çağırmıyor — `win_rate = 55 + tp/sl*3.5 + ret_mean*100` gibi formüllerle sayı
UYDURUYOR. Ölçüm aracı olarak kullanılamaz. Bu modül gerçek kütüphaneyi kullanır.

Yöntem (spot-strategy-lab SKILL.md §4 kriterleriyle uyumlu):
  • Sinyal: giriş anında `entry_signal` bool dizisi.
  • Çıkış: sabit TP (%1.5) / SL (%0.9) — canlı 5m geometrisiyle aynı.
  • Maliyet: round-trip %0.15 (veya seçilen ücret modu) düşülür.
  • Ölçüm: vectorbt `Portfolio.from_signals` → WR, PF, ortalama getiri, süre.
  • Vektörize olduğu için 50 sembol × 17.000 bar saniyeler içinde taranır.

Kullanım:
    python -m scripts.vectorbt_spot_eval            # tüm stratejiler
    python -m scripts.vectorbt_spot_eval --symbols 20 --days 60
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "backend"))
sys.path.insert(0, _ROOT)

logger = logging.getLogger("scalper.vectorbt_spot")

# Canlı 5m geometrisi (spot_monitor.TIMEFRAMES / TRAIL_ACTIVATE_PCT ile aynı)
TP_PCT = 1.5
SL_PCT = 0.9
FEE_ROUND_TRIP_PCT = 0.15
WARMUP = 100


def _signals_series(H, L, C, V, T):
    """Her strateji için eşzamanlı bool giriş dizileri.

    Faz-farkı: gösterge fonksiyonları seri sonundan hesaplar, yani bir barın
    sinyali "o bara KADAR olan veriyle" üretilir — ileriye bakmaz. Yine de
    vektörleştirmek için her bar için tam seri hesaplamak gerekir; bu pahalıdır,
    bu yüzden göstergeleri TAM seri üzerinde hesaplayıp sonra kaydırıyoruz.

    Kaydırma kuralı: bar i'nin sinyali, i-1'e kadar hesaplanmış göstergelere
    dayanmalıdır (kapanış bilinmeden işlem açılmaz). Bu yüzden tüm sinyaller
    `shift(1)` uygulanmış gibi değerlendirilir.
    """
    import app.technical_analysis as ta

    n = len(C)
    out = {}
    Hn, Ln, Cn, Vn = np.asarray(H), np.asarray(L), np.asarray(C), np.asarray(V)

    # EMA serileri (kendi vektörel uygulamamız — proje fonksiyonu kısa
    # seride None döndürüyor ve tüm karşılaştırmayı çökertiyor)
    e20 = _ema_np(Cn, 20)
    e50 = _ema_np(Cn, 50)
    trend = e20 >= e50

    # RVOL (20 bar)
    avgv = np.full(n, np.nan)
    for i in range(20, n):
        s = Vn[i - 20:i].sum()
        avgv[i] = (s / 20.0) if s > 0 else 1.0
    avgv = np.nan_to_num(avgv, nan=1.0)
    rvol = np.divide(Vn, avgv, out=np.ones(n), where=avgv > 0)

    # KDJ (tam seri)
    kdj = ta._kdj(list(Hn), list(Ln), list(Cn), 9, 3) or {}
    j_arr = np.full(n, 50.0)
    dip = np.zeros(n, dtype=bool)
    if kdj:
        # Tek nokta değeri: son bar için. Sinyal dizisini vektörel kurmak için
        # STOCHASTIC tabanlı seri hesabı yapılır.
        k_ser, d_ser = _kdj_series(Hn, Ln, Cn, 9, 3)
        j_arr = 3.0 * k_ser - 2.0 * d_ser
        dip = (j_arr > d_ser) & (np.roll(j_arr, 1) <= np.roll(d_ser, 1))

    # Bollinger + Keltner sıkışma
    bb_kc = _bb_kc_series(Hn, Ln, Cn)

    # ZLMACD
    zl = _zlema(Cn, 12) - _zlema(Cn, 26)
    zl_sig = _zlema(zl, 9)
    zl_cross = (zl > zl_sig) & (np.roll(zl, 1) <= np.roll(zl_sig, 1))

    # LinReg eğim
    slope = _rolling_slope(Cn, 14)
    slope_turn = (slope > 0) & (np.roll(slope, 1) <= 0)

    # STC
    stc = _stc_series(Cn, 10, 23, 50)
    stc_dip = (stc > 25) & (np.roll(stc, 1) <= 25)

    # SuperTrend
    st_bull_arr = _supertrend_series(Hn, Ln, Cn, 10, 3.0)

    # EMA pullback: düşük, EMA50'ye %1 toleransla değdi, kapanış üstünde
    near_e50 = (np.abs(Ln - e50) / np.maximum(e50, 1e-12)) <= 0.010
    bounce = near_e50 & (Cn > e50)

    # Zaman-çapalı RVOL: saat-grubu ortalamasının 2 katı
    tod_rvol = _rvol_tod_series(T, Vn, Cn, e20)

    # Sinyaller — bar i'nin kararı i barının kapanışında verilir, i+1'de dolar.
    # vectorbt `from_signals` bu kaydırmayı `shift` ile yapar; biz sinyali
    # i barına yazıp `from_signals(..., shift=1)` benzeri davranış için
    # entries'i bir bar ileri kaydırıyoruz.
    def shift1(arr):
        z = np.zeros_like(arr, dtype=bool)
        z[1:] = arr[:-1]
        return z

    out["squeeze_breakout"] = shift1(bb_kc & trend & (rvol >= 1.25))
    out["rvol_tod_spike"] = shift1(tod_rvol)
    out["kdj_pure_dip"] = shift1(dip & (j_arr <= 12))
    out["ema_bounce"] = shift1(bounce & dip & trend)
    out["supertrend_pullback"] = shift1(st_bull_arr & dip)
    out["zlmacd_momentum"] = shift1(zl_cross & trend)
    out["linreg_slope_turn"] = shift1(slope_turn)
    out["stc_cycle"] = shift1(stc_dip & (rvol >= 1.15))

    # Referans: her 13. bar (rastgele beklenti seviyesi)
    rnd = np.zeros(n, dtype=bool)
    rnd[::13] = True
    out["__RASTGELE__"] = shift1(rnd)

    # İlk WARMUP barı geçersiz
    for k in out:
        out[k][:WARMUP] = False
    return out


# ─── vektörel gösterge yardımcıları ───────────────────────────────────────────

def _kdj_series(H, L, C, period=9, signal=3):
    n = len(C)
    k = np.full(n, 50.0)
    d = np.full(n, 50.0)
    alpha = 1.0 / signal
    for i in range(n):
        lo = H[max(0, i - period + 1):i + 1]
        if len(lo) == 0:
            continue
        low_min = L[max(0, i - period + 1):i + 1].min()
        high_max = H[max(0, i - period + 1):i + 1].max()
        rng = high_max - low_min
        rsv = ((C[i] - low_min) / rng * 100.0) if rng > 0 else 50.0
        pv_k = k[i - 1] if i > 0 else 50.0
        pv_d = d[i - 1] if i > 0 else 50.0
        k[i] = pv_k + alpha * (rsv - pv_k)
        d[i] = pv_d + alpha * (k[i] - pv_d)
    return k, d


def _zlema(values, period):
    """Zero-lag EMA: gecikme payı kadar kaydırılmış seriye EMA."""
    n = len(values)
    lag = max(1, (period - 1) // 2)
    shifted = np.full(n, np.nan)
    for i in range(n):
        idx = i - lag
        shifted[i] = values[idx] if idx >= 0 else values[i]
    return _ema_np(shifted, period)


def _ema_np(values, period):
    n = len(values)
    out = np.full(n, np.nan)
    alpha = 2.0 / (period + 1.0)
    prev = None
    for i in range(n):
        v = values[i]
        if np.isnan(v):
            continue
        prev = v if prev is None else (v * alpha + prev * (1 - alpha))
        out[i] = prev
    return np.nan_to_num(out, nan=0.0)


def _rolling_slope(values, period):
    n = len(values)
    out = np.zeros(n)
    x = np.arange(period)
    denom = ((x - x.mean()) ** 2).sum()
    for i in range(period - 1, n):
        w = values[i - period + 1:i + 1]
        out[i] = ((x - x.mean()) * (w - w.mean())).sum() / denom if denom else 0.0
    return out


def _bb_kc_series(H, L, C, bb_p=20, bb_mult=2.0, kc_p=20, kc_mult=1.5):
    n = len(C)
    out = np.zeros(n, dtype=bool)
    for i in range(max(bb_p, kc_p), n):
        cw = C[i - bb_p + 1:i + 1]
        mid = cw.mean()
        sd = cw.std()
        upper_bb = mid + bb_mult * sd
        lower_bb = mid - bb_mult * sd
        tr = np.maximum(H[i - kc_p + 1:i + 1] - L[i - kc_p + 1:i + 1],
                        np.abs(H[i - kc_p + 1:i + 1] - np.roll(C, 1)[i - kc_p + 1:i + 1]))
        rangema = tr.mean()
        upper_kc = mid + kc_mult * rangema
        lower_kc = mid - kc_mult * rangema
        # sıkışma: BB, KC'nin İÇİNDE -> sonra kırılım (kapanış üst BB üstünde)
        squeeze = (lower_bb > lower_kc) and (upper_bb < upper_kc)
        if squeeze and C[i] > upper_bb:
            out[i] = True
    return out


def _stc_series(C, period=10, fast=23, slow=50):
    n = len(C)
    macd = _ema_np(C, fast) - _ema_np(C, slow)
    out = np.full(n, 50.0)
    k = 50.0
    prev_stoch = 50.0
    for i in range(period, n):
        w = macd[i - period + 1:i + 1]
        lo, hi = w.min(), w.max()
        stoch = ((macd[i] - lo) / (hi - lo) * 100.0) if hi > lo else 0.0
        prev_stoch = prev_stoch + 0.5 * (stoch - prev_stoch)
        k = k + 0.5 * (prev_stoch - k)
        out[i] = k
    return out


def _supertrend_series(H, L, C, period=10, factor=3.0):
    n = len(C)
    bull = np.zeros(n, dtype=bool)
    tr = np.maximum(H[1:] - L[1:], np.maximum(np.abs(H[1:] - C[:-1]), np.abs(L[1:] - C[:-1])))
    atr = np.full(n, np.nan)
    if len(tr) >= period:
        atr[period] = tr[:period].mean()
        for i in range(period + 1, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i - 1]) / period
    atr = np.nan_to_num(atr, nan=0.0)
    up = (H + L) / 2 + factor * atr
    dn = (H + L) / 2 - factor * atr
    dirn = np.ones(n)
    for i in range(1, n):
        if C[i] > up[i - 1]:
            dirn[i] = 1
        elif C[i] < dn[i - 1]:
            dirn[i] = -1
        else:
            dirn[i] = dirn[i - 1]
    bull = dirn > 0
    return bull


def _rvol_tod_series(T, V, C, e20):
    """Saat-of-gün ortalamasının 2 katı + EMA20 yukarı kesişimi."""
    n = len(C)
    out = np.zeros(n, dtype=bool)
    hour_bucket = {}
    for i in range(n):
        if T[i] <= 0:
            continue
        hb = (T[i] // 3_600_000) % 24
        hour_bucket.setdefault(hb, []).append(V[i])
    for i in range(30, n):
        hb = (T[i] // 3_600_000) % 24
        hist = hour_bucket.get(hb, [])
        if len(hist) < 10:
            continue
        mean_v = float(np.mean(hist))
        if mean_v <= 0:
            continue
        if V[i] >= mean_v * 2.0 and C[i] > e20[i] and C[i - 1] <= e20[i - 1]:
            out[i] = True
    return out


# ─── vectorbt değerlendirme ───────────────────────────────────────────────────

def evaluate_signals(close: np.ndarray, entries: np.ndarray,
                     tp_pct: float = TP_PCT, sl_pct: float = SL_PCT,
                     fee_pct: float = FEE_ROUND_TRIP_PCT):
    """Bir sinyal dizisini vectorbt ile simüle eder.

    `Portfolio.from_signals` kullanılır: TP/SL fiyat bariyerleri, komisyon,
    çakışan pozisyon kontrolü ve işlem defteri kütüphanenin kendisinden gelir
    — elle yazılmış simülasyon yerine endüstri standardı.
    """
    import vectorbt as vbt

    close = np.asarray(close, dtype=float)
    entries = np.asarray(entries, dtype=bool)
    if entries.sum() == 0:
        return None

    # vectorbt 1.2.0 API: stop'lar `tp_stop` / `sl_stop` / `sl_trail` ile verilir
    # (bkz. Portfolio.from_signals imzası). Eski `tp`/`sl` adları yok.
    pf = vbt.Portfolio.from_signals(
        close=close,
        entries=entries,
        exits=np.zeros_like(entries),      # çıkış yalnızca tp_stop/sl_stop ile
        tp_stop=(tp_pct / 100.0),
        sl_stop=(sl_pct / 100.0),
        fees=fee_pct / 100.0,
        freq="5T",
        init_cash=100_000.0,
        size=1.0,
        size_type="amount",
        accumulate=False,
    )
    trades = pf.trades
    rec = trades.records_readable
    if rec is None or len(rec) == 0:
        return None
    pnl = rec["PnL"].to_numpy(dtype=float)
    rets = rec["Return"].to_numpy(dtype=float)
    wins = pnl > 0
    gain = pnl[wins].sum()
    loss = -pnl[~wins].sum()
    return {
        "n": int(len(pnl)),
        "wr": float(wins.mean() * 100),
        "pf": float(gain / loss) if loss > 0 else float("inf"),
        "avg_ret_pct": float(np.mean(rets) * 100),
        "sum_ret_pct": float(np.sum(rets) * 100),
        "std_ret_pct": float(np.std(rets, ddof=1) * 100) if len(rets) > 1 else 0.0,
        "tstat": float(np.mean(rets) / (np.std(rets, ddof=1) / np.sqrt(len(rets))))
        if len(rets) > 1 and np.std(rets, ddof=1) > 0 else 0.0,
    }


def evaluate_trailing(close: np.ndarray, high: np.ndarray, low: np.ndarray,
                      entries: np.ndarray, fee_pct: float = FEE_ROUND_TRIP_PCT):
    """Canlı çıkış modeli: zirve takipçi (%1.5 devreye, %0.8 kilit, %0.6 takip).

    vectorbt'nin `from_signals` TP/SL'i sabit; takipçi için `from_orders` ile
    bariyer emirleri gerekir. Canlı sistemle birebir karşılaştırma bu yüzden
    ayrı bir yolda yapılır — ama giriş sinyalleri AYNI `entries` dizisidir,
    yani iki çıkış modeli adil karşılaştırılır.
    """
    close = np.asarray(close, dtype=float)
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    idx = np.flatnonzero(np.asarray(entries, dtype=bool))
    if len(idx) == 0:
        return None
    ASY, LOCK, DIST, SL0, MAXBAR = 1.5, 0.8, 0.6, 0.9, 24
    rets = []
    for i in idx:
        entry = close[i]
        stop = entry * (1 - SL0 / 100)
        peak = entry
        trail = False
        n = min(len(close) - i - 1, MAXBAR)
        if n <= 0:
            continue
        res = None
        for k in range(1, n + 1):
            hi_k, lo_k = high[i + k], low[i + k]
            if hi_k > peak:
                peak = hi_k
            if not trail and (peak - entry) / entry * 100 >= ASY:
                trail = True
            if trail:
                stop = max(stop, entry * (1 + LOCK / 100), peak * (1 - DIST / 100))
            if lo_k <= stop:
                res = (stop - entry) / entry * 100 - fee_pct
                break
        if res is None:
            res = (close[i + n] - entry) / entry * 100 - fee_pct
        rets.append(res / 100.0)
    if not rets:
        return None
    a = np.asarray(rets)
    wins = a > 0
    gain = a[wins].sum()
    loss = -a[~wins].sum()
    return {
        "n": int(len(a)),
        "wr": float(wins.mean() * 100),
        "pf": float(gain / loss) if loss > 0 else float("inf"),
        "avg_ret_pct": float(np.mean(a) * 100),
        "sum_ret_pct": float(np.sum(a) * 100),
        "std_ret_pct": float(np.std(a, ddof=1) * 100) if len(a) > 1 else 0.0,
        "tstat": float(np.mean(a) / (np.std(a, ddof=1) / np.sqrt(len(a))))
        if len(a) > 1 and np.std(a, ddof=1) > 0 else 0.0,
    }


# ─── ana akış ─────────────────────────────────────────────────────────────────

async def _load(symbols: int, days: int):
    import asyncpg
    url = os.environ.get("DATABASE_URL") or "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"
    conn = await asyncpg.connect(url)
    cutoff = int((time.time() - days * 86400) * 1000)
    rows = await conn.fetch(
        """SELECT symbol, open_time, high, low, close, volume
             FROM historical_candles
            WHERE timeframe='5m' AND symbol LIKE '%USDT' AND open_time >= $1
            ORDER BY symbol, open_time ASC""", cutoff)
    await conn.close()
    data = {}
    for r in rows:
        d = data.setdefault(r["symbol"], {"T": [], "H": [], "L": [], "C": [], "V": []})
        d["T"].append(int(r["open_time"]))
        d["H"].append(float(r["high"]))
        d["L"].append(float(r["low"]))
        d["C"].append(float(r["close"]))
        d["V"].append(float(r["volume"]))
    ordered = sorted(data.items(), key=lambda kv: -len(kv[1]["C"]))[:symbols]
    return dict(ordered)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=30)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--fee", type=float, default=FEE_ROUND_TRIP_PCT)
    args = ap.parse_args()

    data = asyncio.run(_load(args.symbols, args.days))
    print(f"sembol: {len(data)}  |  maliyet: %{args.fee} round-trip")

    from collections import defaultdict
    agg = defaultdict(lambda: defaultdict(lambda: {"tp_sl": [], "trail": []}))
    t0 = time.time()
    for si, (sym, d) in enumerate(data.items(), 1):
        sigs = _signals_series(d["H"], d["L"], d["C"], d["V"], d["T"])
        C = np.asarray(d["C"], dtype=float)
        H = np.asarray(d["H"], dtype=float)
        L = np.asarray(d["L"], dtype=float)
        for name, entries in sigs.items():
            r1 = evaluate_signals(C, entries, fee_pct=args.fee)
            if r1:
                agg[name][sym]["tp_sl"] = r1
            r2 = evaluate_trailing(C, H, L, entries, fee_pct=args.fee)
            if r2:
                agg[name][sym]["trail"] = r2
        if si % 5 == 0:
            print(f"  {si}/{len(data)} ({time.time()-t0:.0f}s)", flush=True)

    def combine(name, mode):
        vals = [v[mode] for v in agg[name].values() if v.get(mode)]
        if not vals:
            return None
        n = sum(x["n"] for x in vals)
        wins = sum(x["wr"] / 100 * x["n"] for x in vals)
        gain = 0.0
        loss = 0.0
        for x in vals:
            if x["pf"] and x["pf"] != float("inf"):
                # PF'den brüt kazanç/kayıp oranını geri kur
                pass
        # doğrudan t-stat ve ortalama ağırlıklı
        avg = sum(x["avg_ret_pct"] * x["n"] for x in vals) / n
        coins_pos = sum(1 for x in vals if x["avg_ret_pct"] > 0)
        coins_n = len(vals)
        pf = sum(x["pf"] for x in vals if x["pf"] and x["pf"] != float("inf")) / max(
            1, sum(1 for x in vals if x["pf"] and x["pf"] != float("inf")))
        tstat = np.mean([x["tstat"] for x in vals])
        return {"n": n, "wr": wins / n * 100, "pf": pf, "avg": avg,
                "coins_pos": coins_pos, "coins_n": coins_n, "tstat": tstat}

    MEAN_REV = {"kdj_pure_dip", "ema_bounce", "stc_cycle", "supertrend_pullback"}
    print()
    print("=" * 104)
    print("VECTORBT -- 60 GUN, KABUL KRITERLERI (SKILL.md §4)")
    print("  n>=20 | WR>=55 (trend) / 60 (MR) | PF>=1.50 | net>0 | 2+ coinde pozitif")
    print("=" * 104)
    for mode, title in (("trail", "CANLI MODEL: zirve takipci"), ("tp_sl", "SABIT TP/SL (%1.5/%0.9)")):
        print()
        print(f"--- {title} ---")
        print("%-21s %6s %7s %7s %8s %8s %7s  %s" % (
            "strateji", "n", "WR", "PF", "ort%", "t-stat", "pozCoin", "KARAR"))
        print("-" * 104)
        rows = []
        for name in agg:
            c = combine(name, mode)
            if not c:
                continue
            thr = 60.0 if name in MEAN_REV else 55.0
            checks = [c["n"] >= 20, c["wr"] >= thr, c["pf"] >= 1.50,
                      c["avg"] > 0, c["coins_pos"] >= 2]
            passed = sum(checks)
            dec = "TERFI ET" if passed == 5 else ("YENIDEN TEST" if passed >= 3 else "REDDET")
            rows.append((c["avg"], name, c, checks, dec))
        for _, name, c, checks, dec in sorted(rows, key=lambda r: -r[0]):
            mark = " **" if c["tstat"] > 2.0 else (" *" if c["tstat"] > 1.5 else "")
            print("%-21s %6d %6.1f%% %7.2f %+8.3f %+8.2f %4d/%-2d  %s (%d/5)%s" % (
                name, c["n"], c["wr"], c["pf"], c["avg"], c["tstat"],
                c["coins_pos"], c["coins_n"], dec, sum(checks), mark))
    print("=" * 104)
    print("t-stat ** >2.0 (%95 anlamli)   * >1.5 (zayif)")


if __name__ == "__main__":
    main()
