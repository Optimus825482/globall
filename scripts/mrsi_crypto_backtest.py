#!/usr/bin/env python3
"""mRSI (RSI 7/14/21) — Spot Coin 1H Strateji Backtest.

Girdi: Binance spot klines (1h) — NEARUSDT, MOVRUSDT
Stratejiler (yalnız LONG — spot):
  S1 UCLU-OS   : Üçlü aşırı satım (RSI7<30 & RSI14<30 & RSI21<30) → al; çıkış RSI7>50
  S2 SNAPBACK  : Ekstrem dip (RSI7<20 & RSI14<30) → al; çıkış RSI7>50
  S3 MOMENTUM  : Üçlü momentum (RSI7>55 & RSI14>55 & RSI21>50) → al; çıkış RSI7<50
  S4 PULLBACK  : Rejim RSI21>50 & hızlı dip RSI7<35 → al; çıkış RSI7>60
Tümünde: SL = 2.0×ATR14 (S2: 1.5×ATR), komisyon %0.1/side, bar kapanışında karar.
Rapor: IS (%70) / OOS (%30) bölünmesi + buy&hold kıyası.
Kullanım: python scripts/mrsi_crypto_backtest.py
"""
from __future__ import annotations

import inspect
import json
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://api.binance.com/api/v3/klines"
FEE = 0.001  # %0.1 spot taker, side başına
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
        time.sleep(0.15)
    bars = []
    for k in out:
        # k: [openTime, o, h, l, c, v, closeTime, ...]
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


def s7_entry(r7, r14, r21, i, bars, ema34, ema144, rsi7) -> bool:
    if i <= 0 or ema34 is None or ema144 is None:
        return False
    e34_now = ema34[i]
    e144_now = ema144[i]
    e34_prev = ema34[i - 1]
    r7_prev = rsi7[i - 1]

    if e34_now is None or e144_now is None or e34_prev is None or r7_prev is None:
        return False
    if r7 is None or r21 is None:
        return False

    c = bars[i]["c"]
    # 1) close > EMA(144)
    if not (c > e144_now):
        return False
    # 2) EMA(34) > EMA(144)
    if not (e34_now > e144_now):
        return False
    # 3) RSI(21) > 50
    if not (r21 > 50):
        return False
    # 4) RSI(7) bu barda 40'ı yukarı kesti: rsi7[i-1] < 40 <= rsi7[i]
    if not (r7_prev < 40 and r7 >= 40):
        return False
    # 5) Bu bar veya önceki barda low <= EMA(34)
    l_now = bars[i]["l"]
    l_prev = bars[i - 1]["l"]
    if not (l_now <= e34_now or l_prev <= e34_prev):
        return False

    return True


def s7_exit(r7, r14, r21, i, bars, ema34, ema144, rsi7) -> bool:
    if r7 is not None and r7 > 80:
        return True
    if ema144 is not None and ema144[i] is not None:
        if bars[i]["c"] < ema144[i]:
            return True
    return False


def _call_cond(fn, r7, r14, r21, i, bars, ema34, ema144, rsi7) -> bool:
    sig = inspect.signature(fn)
    if len(sig.parameters) <= 3:
        return fn(r7, r14, r21)
    return fn(r7, r14, r21, i, bars, ema34, ema144, rsi7)


@dataclass
class Result:
    name: str
    trades: int = 0
    wins: int = 0
    equity: float = 1.0
    peak: float = 1.0
    maxdd: float = 0.0
    bars_in_market: int = 0
    total_bars: int = 0
    trade_pnls: List[float] = field(default_factory=list)


def run_strategy(name: str, bars: List[dict], rsi7: List, rsi14: List, rsi21: List,
                 atrs: List, entry_fn, exit_fn, sl_mult: float, start: int, end: int,
                 gate_series: Optional[List] = None, gate_threshold: Optional[float] = None,
                 ema34: Optional[List] = None, ema144: Optional[List] = None) -> Result:
    res = Result(name=name, total_bars=end - start)
    pos: Optional[Tuple[float, float]] = None  # (entry_price, sl_price)
    for i in range(start, end):
        r7, r14, r21 = rsi7[i], rsi14[i], rsi21[i]
        a = atrs[i]
        if pos is not None:
            res.bars_in_market += 1
            entry, sl = pos
            c = bars[i]["c"]
            if c <= sl:  # stop (bar kapanış kontrolü — conservative)
                gross = c / entry - 1.0
                net = (1.0 + gross) * (1.0 - FEE) * (1.0 - FEE) - 1.0
                res.trades += 1
                res.trade_pnls.append(net)
                res.equity *= (1.0 + net)
                res.peak = max(res.peak, res.equity)
                res.maxdd = max(res.maxdd, 1.0 - res.equity / res.peak)
                if net >= 0:
                    res.wins += 1
                pos = None
            elif _call_cond(exit_fn, r7, r14, r21, i, bars, ema34, ema144, rsi7):
                gross = c / entry - 1.0
                net = (1.0 + gross) * (1.0 - FEE) * (1.0 - FEE) - 1.0
                res.trades += 1
                res.trade_pnls.append(net)
                res.equity *= (1.0 + net)
                res.peak = max(res.peak, res.equity)
                res.maxdd = max(res.maxdd, 1.0 - res.equity / res.peak)
                if net >= 0:
                    res.wins += 1
                pos = None
            continue
        if r7 is None or r14 is None or r21 is None or a is None:
            continue
        # Piyasa-rejim kapısı: referans seri eşiğin altındaysa giriş yok
        # (EMA200 kapısı: yapısal durum; RSI kapısından farkı — anlık dip ile tetik çakışmaz)
        if gate_threshold is not None:
            if gate_series is None or gate_series[i] is None or gate_series[i] <= gate_threshold:
                continue
        if _call_cond(entry_fn, r7, r14, r21, i, bars, ema34, ema144, rsi7):
            entry = bars[i]["c"]
            pos = (entry, entry - sl_mult * a)
    return res


def buyhold(bars: List[dict], start: int, end: int) -> float:
    if end <= start:
        return 0.0
    return bars[end - 1]["c"] / bars[start]["c"] - 1.0


STRATS = [
    ("S1 UCLU-OS (tümü<30)", 2.0,
     lambda r7, r14, r21: r7 < 30 and r14 < 30 and r21 < 30,
     lambda r7, r14, r21: r7 > 50, False),
    ("S2 SNAPBACK (7<20&14<30)", 1.5,
     lambda r7, r14, r21: r7 < 20 and r14 < 30,
     lambda r7, r14, r21: r7 > 50, False),
    ("S3 MOMENTUM (tümü>50)", 2.0,
     lambda r7, r14, r21: r7 > 55 and r14 > 55 and r21 > 50,
     lambda r7, r14, r21: r7 < 50, False),
    ("S4 PULLBACK (21>50, 7<35)", 2.0,
     lambda r7, r14, r21: r21 > 50 and r7 < 35,
     lambda r7, r14, r21: r7 > 60, False),
    ("S5 S1+BTC-rejim", 2.0,
     lambda r7, r14, r21: r7 < 30 and r14 < 30 and r21 < 30,
     lambda r7, r14, r21: r7 > 50, True),
    ("S6 S2+BTC-rejim", 1.5,
     lambda r7, r14, r21: r7 < 20 and r14 < 30,
     lambda r7, r14, r21: r7 > 50, True),
    ("S7 EMA34/144+mRSI", 2.0,
     s7_entry,
     s7_exit, False),
]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="mRSI 1h spot backtest — çoklu coin matris")
    parser.add_argument("--coins", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,SUIUSDT")
    args = parser.parse_args()
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]

    # Piyasa-rejim referansı: BTC fiyatı / EMA200(1h) oranı (>1 = yapısal yukarı rejim)
    btc_bars = fetch_klines("BTCUSDT", "1h", 9000)
    btc_closes = [b["c"] for b in btc_bars]
    alpha = 2.0 / 201.0
    ema = [btc_closes[0]]
    for c in btc_closes[1:]:
        ema.append(ema[-1] + alpha * (c - ema[-1]))
    btc_gate = [btc_closes[i] / ema[i] if ema[i] > 0 else None for i in range(len(btc_closes))]

    results: dict = {}  # results[coin][strat_name][window] = Result
    bh_map: dict = {}
    meta: dict = {}
    for symbol in coins:
        try:
            bars = fetch_klines(symbol, "1h", 9000)
        except Exception as exc:
            print(f"[VERI HATASI] {symbol}: {exc} — atlandı")
            continue
        n = len(bars)
        closes = [b["c"] for b in bars]
        rsi7 = wilder_rsi(closes, 7)
        rsi14 = wilder_rsi(closes, 14)
        rsi21 = wilder_rsi(closes, 21)
        atrs = atr_series(bars, 14)
        ema34 = ema_series(closes, 34)
        ema144 = ema_series(closes, 144)
        warm = 30
        split = warm + int((n - warm) * 0.70)
        results[symbol] = {}
        for name, sl_mult, efn, xfn, gated in STRATS:
            kwargs = {"gate_series": btc_gate, "gate_threshold": 1.0} if gated else {}
            results[symbol][name] = {
                "IS": run_strategy(name, bars, rsi7, rsi14, rsi21, atrs, efn, xfn, sl_mult, warm, split, ema34=ema34, ema144=ema144, **kwargs),
                "OOS": run_strategy(name, bars, rsi7, rsi14, rsi21, atrs, efn, xfn, sl_mult, split, n, ema34=ema34, ema144=ema144, **kwargs),
            }
        bh_map[symbol] = (buyhold(bars, warm, split), buyhold(bars, split, n), buyhold(bars, warm, n))
        meta[symbol] = {"bars": n, "split": split, "first": bars[warm]["t"], "last": bars[-1]["t"]}
        print(f"[OK] {symbol}: {n} bar ({time.strftime('%Y-%m-%d', time.gmtime(bars[warm]['t']))} -> {time.strftime('%Y-%m-%d', time.gmtime(bars[-1]['t']))})")

    strat_names = [s[0] for s in STRATS]
    for window in ("IS", "OOS"):
        print()
        print("=" * 108)
        print(f"{window} — NET GETİRİ (%) | komisyon %0.1/side | yalnız LONG | bar kapanışında karar")
        print("=" * 108)
        hdr = f"{'COIN':10s}" + "".join(f"{n.split()[0]:>12s}" for n in strat_names) + f"{'B&H':>10s}"
        print(hdr)
        for sym in results:
            row = f"{sym:10s}"
            for name in strat_names:
                r = results[sym][name][window]
                row += f"{(r.equity - 1.0) * 100:>+11.1f}%"
            bh_is, bh_oos, _bh = bh_map[sym]
            row += f"{(bh_is if window == 'IS' else bh_oos) * 100:>+9.1f}%"
            print(row)
        # Topluluk özeti: pozitif coin sayısı + ortalama marj
        print("-" * 108)
        for name in strat_names:
            nets = [results[sym][name][window].equity - 1.0 for sym in results]
            poss = sum(1 for x in nets if x > 0)
            trades = sum(results[sym][name][window].trades for sym in results)
            wrs = [100.0 * results[sym][name][window].wins / max(1, results[sym][name][window].trades) for sym in results]
            margins = [(results[sym][name][window].equity - 1.0) / results[sym][name][window].maxdd
                       for sym in results if results[sym][name][window].maxdd > 0]
            avg_m = sum(margins) / len(margins) if margins else 0.0
            print(f"{name.split()[0]:10s} topluluk: {poss}/{len(nets)} coin pozitif | {trades} işlem | ort WR {sum(wrs)/len(wrs):5.1f}% | ort marj {avg_m:+.2f}")
    print()
    print("Not: S4 = pullback-in-trend (RSI21>50 & RSI7<35 → al, RSI7>60 çık) — araştırmanın önerilen deseni; S3 momentum kovalama beklenen kötü.")


if __name__ == "__main__":
    main()
