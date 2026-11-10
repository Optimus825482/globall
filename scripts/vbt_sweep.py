#!/usr/bin/env python3
"""VECTORBT STRATEJİ TARAMASI — OOS + maliyet (2026-11-10)

Girdi: `outputs/vbt_data/<SEMBOL>_<TF>.csv` (MT5'ten, UTC damgalı; `vbt_export_mt5.py`).
Kurulum: izole venv (`.venv-vbt`) — vectorbt 1.2.0 (py3.12 + numpy 2.x uyumlu, test edildi).

DİSİPLİN
--------
* Sinyal **bir bar geciktirilir** (`shift(1)`): bar kapanışında üretilen sinyal ancak sonraki
  barda işlem görür (aynı-bar dolum iyimserliği yok).
* **IS/OOS**: ilk %70 eğitim, son %30 test. En iyi parametre IS'te seçilir, **OOS'ta raporlanır**.
  Referans olarak ızgaranın OOS medyanı da yazılır (aşırı uyum göstergesi).
* **Maliyet**: sembol başına ölçülmüş tur maliyeti (spread+komisyon, pip→fiyat oranı) / 2 → `fees`
  (yan başına). Ayrıca `--stress` ile maliyet 2× koşulur.
* `freq` zorunlu (Sharpe yıllıklandırması): 1h → '1h', 1d → '1D'.

Kullanim:
    .venv-vbt/Scripts/python.exe scripts/vbt_sweep.py --tfs 1h,1d
"""
from __future__ import annotations

import argparse
import itertools
import os
import sys

import numpy as np
import pandas as pd

try:
    import vectorbt as vbt
except ImportError:
    print("[HATA] vectorbt yok — `.venv-vbt` ile koşun.")
    raise SystemExit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "outputs", "vbt_data")

#: ölçülen TUR maliyeti (fiyat oranı) — spread + komisyon; yan başına yarısı `fees`e girer.
COST = {  # sembol: tur maliyeti (oran)
    "EURUSD": 0.00009, "GBPUSD": 0.00010, "USDJPY": 0.00008,
    "XAUUSD": 0.00007, "US30": 0.00003, "NAS100": 0.00003, "BTCUSD": 0.00012,
}
FREQ = {"1h": "1h", "1d": "1D", "30m": "30min", "5m": "5min", "4h": "4h", "15m": "15min"}


def load(sym: str, tf: str) -> pd.DataFrame | None:
    p = os.path.join(DATA, f"{sym}_{tf}.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p, parse_dates=["ts_utc"], index_col="ts_utc")
    return df[["open", "high", "low", "close", "volume"]].sort_index()


# --------------------------------------------------------------------------- stratejiler

def sig_ma_cross(df: pd.DataFrame, fast: int, slow: int):
    c = df["close"]
    f, s = c.ewm(span=fast, adjust=False).mean(), c.ewm(span=slow, adjust=False).mean()
    return (f > s), (f < s)


def sig_donchian(df: pd.DataFrame, n: int):
    hi = df["high"].rolling(n).max().shift(1)
    lo = df["low"].rolling(n).min().shift(1)
    c = df["close"]
    return (c > hi), (c < lo)


def sig_rsi2(df: pd.DataFrame, th: float, trend: int):
    c = df["close"]
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 2, adjust=False).mean()
    rsi2 = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    sma_t = c.rolling(trend).mean()
    sma5 = c.rolling(5).mean()
    return ((c > sma_t) & (rsi2 < th)), (c > sma5)


def sig_boll_adx(df: pd.DataFrame, n: int, k: float, adx_max: float):
    c = df["close"]
    mid = c.rolling(n).mean()
    sd = c.rolling(n).std()
    lower, upper = mid - k * sd, mid + k * sd
    # ADX(14)
    h, l = df["high"], df["low"]
    up_move, dn_move = h.diff(), -l.diff()
    plus_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm, index=c.index).ewm(alpha=1 / 14, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus_dm, index=c.index).ewm(alpha=1 / 14, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / 14, adjust=False).mean()
    return ((c < lower) & (adx < adx_max)), (c > mid)


def sig_mom(df: pd.DataFrame, n: int):
    c = df["close"]
    roc = c.pct_change(n)
    return (roc > 0), (roc < 0)


def grid_for(tf: str):
    """(ad, fn, param-ızgarası) — küçük ve yorumlanabilir tutuldu."""
    g = [
        ("ma_cross", sig_ma_cross, [{"fast": f, "slow": s} for f in (5, 10, 20, 50) for s in (30, 60, 120, 200)]),
        ("donchian", sig_donchian, [{"n": n} for n in (10, 20, 40, 55, 100)]),
        ("rsi2", sig_rsi2, [{"th": t, "trend": tr} for t in (5, 10, 15) for tr in (50, 200)]),
        ("boll_adx", sig_boll_adx, [{"n": n, "k": k, "adx_max": a}
                                    for n in (20, 50) for k in (2.0, 2.5) for a in (20, 25)]),
        ("mom", sig_mom, [{"n": n} for n in (5, 10, 20, 50)]),
    ]
    return g


def run_one(close: pd.Series, entry: pd.Series, exit_: pd.Series, tf: str, cost: float, stress: float):
    e = entry.fillna(False).shift(1).fillna(False).astype(bool)
    x = exit_.fillna(False).shift(1).fillna(False).astype(bool)
    if e.sum() < 5:
        return None
    pf = vbt.Portfolio.from_signals(
        close, e, x, fees=cost / 2.0 * stress, slippage=0.0, size=1.0, size_type="percent",
        init_cash=10_000, freq=FREQ[tf], direction="longonly")
    # vectorbt 1.2.0: tek tek metot adları sürümler arası değişiyor → `stats()` sözlüğü
    # tek ve kararlı yol (anahtarlar: 'Total Trades', 'Sharpe Ratio', 'Profit Factor', ...).
    st = pf.stats()
    tr = int(st.get("Total Trades", 0) or 0)
    if tr < 5:
        return None
    return {
        "sharpe": float(st.get("Sharpe Ratio", 0.0) or 0.0),
        "total_ret": float(st.get("Total Return [%]", 0.0) or 0.0) / 100.0,
        "max_dd": float(st.get("Max Drawdown [%]", 0.0) or 0.0) / 100.0,
        "pf": float(st.get("Profit Factor", 0.0) or 0.0),
        "win": float(st.get("Win Rate [%]", 0.0) or 0.0) / 100.0,
        "trades": tr,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="vectorbt strateji taraması (IS/OOS)")
    ap.add_argument("--symbols", default="EURUSD,GBPUSD,USDJPY,XAUUSD,US30,NAS100,BTCUSD")
    ap.add_argument("--tfs", default="1h,1d")
    ap.add_argument("--is-frac", type=float, default=0.70)
    ap.add_argument("--min-trades", type=int, default=20)
    ap.add_argument("--stress", type=float, default=1.0, help="maliyet çarpanı (2 = stres)")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    rows = []
    for tf in [t.strip() for t in args.tfs.split(",") if t.strip()]:
        for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
            df = load(sym, tf)
            if df is None or len(df) < 300:
                continue
            cut = int(len(df) * args.is_frac)
            tr_df, te_df = df.iloc[:cut], df.iloc[cut:]
            cost = COST.get(sym, 0.0001)
            for name, fn, grid in grid_for(tf):
                best = None
                for params in grid:
                    try:
                        en, ex = fn(tr_df, **params)
                    except Exception:  # noqa: BLE001
                        continue
                    r = run_one(tr_df["close"], en, ex, tf, cost, args.stress)
                    if not r or r["trades"] < args.min_trades:
                        continue
                    if best is None or r["sharpe"] > best[0]["sharpe"]:
                        best = (r, params)
                if best is None:
                    continue
                # OOS: seçilen parametreyle test dilimi
                try:
                    en, ex = fn(te_df, **best[1])
                except Exception:  # noqa: BLE001
                    continue
                oos = run_one(te_df["close"], en, ex, tf, cost, args.stress)
                if not oos:
                    continue
                rows.append({"sym": sym, "tf": tf, "strat": name, **best[1],
                             "is_sharpe": round(best[0]["sharpe"], 2),
                             "oos_sharpe": round(oos["sharpe"], 2),
                             "oos_ret_pct": round(100 * oos["total_ret"], 1),
                             "oos_pf": round(oos["pf"], 2),
                             "oos_win": round(100 * oos["win"], 1),
                             "oos_dd_pct": round(100 * oos["max_dd"], 1),
                             "oos_trades": oos["trades"]})
    if not rows:
        print("sonuç yok")
        return 1
    out = pd.DataFrame(rows).sort_values("oos_sharpe", ascending=False)
    pd.set_option("display.width", 200, "display.max_rows", 200)
    print(f"\n=== IS→OOS TARAMA (maliyet ×{args.stress}) — ilk {args.top} ===")
    print(out.head(args.top).to_string(index=False))
    pos = out[(out["oos_sharpe"] > 0.5) & (out["oos_pf"] > 1.2) & (out["oos_trades"] >= args.min_trades)]
    print(f"\nOOS'ta Sharpe>0.5 & PF>1.2 & işlem>={args.min_trades}: {len(pos)} / {len(out)}")
    if len(pos):
        print(pos.to_string(index=False))
    print("\nstrateji bazında OOS medyanı (aşırı uyum göstergesi: IS-OOS farkı):")
    agg = out.groupby("strat").agg(n=("oos_sharpe", "size"), is_=("is_sharpe", "median"),
                                   oos=("oos_sharpe", "median"), pf=("oos_pf", "median"))
    agg["fark"] = (agg["is_"] - agg["oos"]).round(2)
    print(agg.sort_values("oos", ascending=False).to_string())
    p = os.path.join(ROOT, "outputs", "vbt_sweep_results.csv")
    out.to_csv(p, index=False)
    print(f"\nCSV: {os.path.relpath(p, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
