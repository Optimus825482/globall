#!/usr/bin/env python3
"""mRSI S7 Parametre Optimizasyon ve Duyarlılık Testi.

Metodoloji:
1) Binance'den 10 coinin 9000 bar klines verisini çek ve önbellekle.
2) Grid Search parametreleri:
   - rsi7_entry_cross: [30, 35, 40] (RSI7'nin yukarı kestiği eşik)
   - rsi7_exit: [55, 60, 65, 70, 80] (Kâr alma eşiği)
   - sl_mult: [1.0, 1.5, 2.0]
   - btc_gate: [False, True] (BTC > EMA200 yapısal boğa filtresi)
   - exit_on_ema_break: [144, 34] (EMA altı bar kapanışında çıkış)
3) Metrikler: IS ve OOS için Net Getiri, Pozitif Coin Sayısı, WR, Toplam İşlem.
4) En iyi parametreleri belirle ve raporla.
"""
from __future__ import annotations

import itertools
import json
import sys
import time
import urllib.request
from typing import Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://api.binance.com/api/v3/klines"
FEE = 0.001
USER_AGENT = "Mozilla/5.0"


def fetch_klines(symbol: str, interval: str = "1h", total: int = 9000) -> List[dict]:
    out: List[dict] = []
    end_time = None
    while len(out) < total:
        url = f"{BASE}?symbol={symbol}&interval={interval}&limit=1000"
        if end_time:
            url += f"&endTime={end_time}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            batch = json.loads(r.read().decode("utf-8"))
        if not batch:
            break
        out = batch + out
        end_time = batch[0][0] - 1
        if len(batch) < 1000:
            break
        time.sleep(0.12)
    bars = []
    for k in out:
        bars.append({
            "t": int(k[0]) / 1000.0,
            "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]),
        })
    return bars


def wilder_rsi(closes: List[float], length: int) -> List[Optional[float]]:
    n = len(closes)
    rsi: List[Optional[float]] = [None] * n
    if n <= length:
        return rsi
    gains = losses = 0.0
    for i in range(1, length + 1):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    ag, al = gains / length, losses / length
    rsi[length] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(length + 1, n):
        ch = closes[i] - closes[i - 1]
        ag = (ag * (length - 1) + max(ch, 0.0)) / length
        al = (al * (length - 1) + max(-ch, 0.0)) / length
        rsi[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return rsi


def atr_series(bars: List[dict], length: int = 14) -> List[Optional[float]]:
    n = len(bars)
    atr: List[Optional[float]] = [None] * n
    trs: List[float] = []
    for i in range(1, n):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        if len(trs) >= length:
            atr[i] = sum(trs[-length:]) / length
    return atr


def ema_series(closes: List[float], n: int) -> List[float]:
    if not closes:
        return []
    alpha = 2.0 / (n + 1.0)
    out: List[float] = [closes[0]]
    for c in closes[1:]:
        out.append(out[-1] + alpha * (c - out[-1]))
    return out


def simulate_s7(bars: List[dict], rsi7: List, rsi21: List, atrs: List,
                 ema34: List, ema144: List, start: int, end: int,
                 rsi7_cross: float, rsi7_exit: float, sl_mult: float,
                 exit_ema: int, tp_mult: Optional[float] = None,
                 btc_gate: Optional[List[float]] = None) -> Tuple[float, int, int, float]:
    """Döndürür: (net_return, trades, wins, maxdd)"""
    equity = 1.0
    peak = 1.0
    maxdd = 0.0
    trades = 0
    wins = 0
    pos: Optional[Tuple[float, float, Optional[float]]] = None  # (entry, sl, tp)

    for i in range(start, end):
        r7 = rsi7[i]
        r21 = rsi21[i]
        a = atrs[i]
        e34 = ema34[i]
        e144 = ema144[i]
        c = bars[i]["c"]

        if pos is not None:
            entry, sl, tp = pos
            # Stop check
            if c <= sl:
                gross = c / entry - 1.0
                net = (1.0 + gross) * (1.0 - FEE) * (1.0 - FEE) - 1.0
                trades += 1
                equity *= (1.0 + net)
                peak = max(peak, equity)
                maxdd = max(maxdd, 1.0 - equity / peak)
                if net >= 0:
                    wins += 1
                pos = None
                continue
            
            # TP check (opsiyonel)
            if tp is not None and c >= tp:
                gross = c / entry - 1.0
                net = (1.0 + gross) * (1.0 - FEE) * (1.0 - FEE) - 1.0
                trades += 1
                equity *= (1.0 + net)
                peak = max(peak, equity)
                maxdd = max(maxdd, 1.0 - equity / peak)
                wins += 1
                pos = None
                continue

            # Exit check: RSI7 > rsi7_exit VEYA close < exit_ema
            ema_exit_val = e144 if exit_ema == 144 else (e34 if exit_ema == 34 else None)
            is_exit = False
            if r7 is not None and r7 > rsi7_exit:
                is_exit = True
            elif ema_exit_val is not None and c < ema_exit_val:
                is_exit = True
            
            if is_exit:
                gross = c / entry - 1.0
                net = (1.0 + gross) * (1.0 - FEE) * (1.0 - FEE) - 1.0
                trades += 1
                equity *= (1.0 + net)
                peak = max(peak, equity)
                maxdd = max(maxdd, 1.0 - equity / peak)
                if net >= 0:
                    wins += 1
                pos = None
                continue

        # Giriş kontrolleri
        if i <= 0 or r7 is None or r21 is None or a is None or e34 is None or e144 is None:
            continue
        prev_r7 = rsi7[i - 1]
        prev_e34 = ema34[i - 1]
        if prev_r7 is None or prev_e34 is None:
            continue

        # BTC gate check
        if btc_gate is not None:
            if btc_gate[i] is None or btc_gate[i] <= 1.0:
                continue

        # S7 kuralları
        # 1) close > EMA144
        if c <= e144:
            continue
        # 2) EMA34 > EMA144
        if e34 <= e144:
            continue
        # 3) RSI21 > 50
        if r21 <= 50:
            continue
        # 4) RSI7 bu barda rsi7_cross'u yukarı kesti
        if not (prev_r7 < rsi7_cross and r7 >= rsi7_cross):
            continue
        # 5) Bu bar veya önceki barda low <= EMA34
        l_now = bars[i]["l"]
        l_prev = bars[i - 1]["l"]
        if not (l_now <= e34 or l_prev <= prev_e34):
            continue

        entry = c
        sl = entry - sl_mult * a
        tp = entry + tp_mult * a if tp_mult is not None else None
        pos = (entry, sl, tp)

    return equity - 1.0, trades, wins, maxdd


def main():
    coins = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT"]
    print("Binance klines verileri yukleniyor...")

    btc_bars = fetch_klines("BTCUSDT", "1h", 9000)
    btc_closes = [b["c"] for b in btc_bars]
    btc_ema200 = ema_series(btc_closes, 200)
    btc_gate_series = [btc_closes[i] / btc_ema200[i] if btc_ema200[i] > 0 else None for i in range(len(btc_closes))]

    market_data = {}
    for sym in coins:
        bars = fetch_klines(sym, "1h", 9000)
        n = len(bars)
        closes = [b["c"] for b in bars]
        warm = 30
        split = warm + int((n - warm) * 0.70)
        market_data[sym] = {
            "bars": bars,
            "rsi7": wilder_rsi(closes, 7),
            "rsi21": wilder_rsi(closes, 21),
            "atrs": atr_series(bars, 14),
            "ema34": ema_series(closes, 34),
            "ema144": ema_series(closes, 144),
            "warm": warm,
            "split": split,
            "n": n,
        }
        print(f"Loaded {sym}: {n} bars")

    # Grid Parametreleri
    param_grid = {
        "rsi7_cross": [30, 35, 40],
        "rsi7_exit": [50, 55, 60, 70],
        "sl_mult": [1.0, 1.5, 2.0],
        "exit_ema": [34, 144],
        "tp_mult": [None, 2.0, 3.0],
        "use_btc_gate": [False, True],
    }

    keys = list(param_grid.keys())
    combinations = list(itertools.product(*[param_grid[k] for k in keys]))
    print(f"\nToplam {len(combinations)} parametre kombinasyonu taranıyor...\n")

    summary_list = []

    for comb in combinations:
        params = dict(zip(keys, comb))
        
        # IS & OOS değerlendirme
        is_rets, is_trades, is_wins = [], 0, 0
        oos_rets, oos_trades, oos_wins = [], 0, 0

        for sym, d in market_data.items():
            gate = btc_gate_series if params["use_btc_gate"] else None
            
            # IS
            ret_is, tr_is, w_is, _ = simulate_s7(
                d["bars"], d["rsi7"], d["rsi21"], d["atrs"], d["ema34"], d["ema144"],
                d["warm"], d["split"],
                params["rsi7_cross"], params["rsi7_exit"], params["sl_mult"],
                params["exit_ema"], params["tp_mult"], gate
            )
            is_rets.append(ret_is)
            is_trades += tr_is
            is_wins += w_is

            # OOS
            ret_oos, tr_oos, w_oos, _ = simulate_s7(
                d["bars"], d["rsi7"], d["rsi21"], d["atrs"], d["ema34"], d["ema144"],
                d["split"], d["n"],
                params["rsi7_cross"], params["rsi7_exit"], params["sl_mult"],
                params["exit_ema"], params["tp_mult"], gate
            )
            oos_rets.append(ret_oos)
            oos_trades += tr_oos
            oos_wins += w_oos

        is_pos = sum(1 for r in is_rets if r > 0)
        is_avg_ret = sum(is_rets) / len(is_rets)
        is_wr = (is_wins / is_trades * 100) if is_trades > 0 else 0.0

        oos_pos = sum(1 for r in oos_rets if r > 0)
        oos_avg_ret = sum(oos_rets) / len(oos_rets)
        oos_wr = (oos_wins / oos_trades * 100) if oos_trades > 0 else 0.0

        summary_list.append({
            "params": params,
            "is_pos": is_pos,
            "is_avg_ret": is_avg_ret,
            "is_wr": is_wr,
            "is_trades": is_trades,
            "oos_pos": oos_pos,
            "oos_avg_ret": oos_avg_ret,
            "oos_wr": oos_wr,
            "oos_trades": oos_trades,
        })

    # OOS pozitif coin ve ortalama getiriye göre sırala
    summary_list.sort(key=lambda x: (x["oos_pos"], x["oos_avg_ret"]), reverse=True)

    print("=" * 125)
    print("EN IYI 15 OPTIMIZE KOMBINASYON (OOS Sirali)")
    print("=" * 125)
    print(f"{'CROSS':>5} | {'EXIT':>4} | {'SL':>4} | {'EMA_X':>5} | {'TP':>4} | {'BTC':>5} || {'OOS POS':>7} | {'OOS RET':>8} | {'OOS WR':>7} | {'OOS TR':>6} || {'IS POS':>6} | {'IS RET':>8} | {'IS WR':>7} | {'IS TR':>5}")
    print("-" * 125)

    for item in summary_list[:15]:
        p = item["params"]
        btc_s = "EVET" if p["use_btc_gate"] else "HAYIR"
        tp_s = f"{p['tp_mult']:.1f}" if p["tp_mult"] is not None else "YOK"
        print(f"{p['rsi7_cross']:>5} | {p['rsi7_exit']:>4} | {p['sl_mult']:>4.1f} | {p['exit_ema']:>5} | {tp_s:>4} | {btc_s:>5} || "
              f"{item['oos_pos']:>2}/10   | {item['oos_avg_ret']*100:>+7.1f}% | {item['oos_wr']:>6.1f}% | {item['oos_trades']:>6} || "
              f"{item['is_pos']:>2}/10  | {item['is_avg_ret']*100:>+7.1f}% | {item['is_wr']:>6.1f}% | {item['is_trades']:>5}")

    print("=" * 125)


if __name__ == "__main__":
    main()
