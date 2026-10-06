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

import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

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
                 atrs: List, entry_fn, exit_fn, sl_mult: float, start: int, end: int) -> Result:
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
            elif exit_fn(r7, r14, r21):
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
        if entry_fn(r7, r14, r21):
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
     lambda r7, r14, r21: r7 > 50),
    ("S2 SNAPBACK (7<20&14<30)", 1.5,
     lambda r7, r14, r21: r7 < 20 and r14 < 30,
     lambda r7, r14, r21: r7 > 50),
    ("S3 MOMENTUM (tümü>50)", 2.0,
     lambda r7, r14, r21: r7 > 55 and r14 > 55 and r21 > 50,
     lambda r7, r14, r21: r7 < 50),
    ("S4 PULLBACK (21>50, 7<35)", 2.0,
     lambda r7, r14, r21: r21 > 50 and r7 < 35,
     lambda r7, r14, r21: r7 > 60),
]


def main():
    for symbol in ("NEARUSDT", "MOVRUSDT"):
        print("=" * 84)
        print(f"SEMBOl: {symbol} | 1h | Binance spot | komisyon %0.1/side")
        print("=" * 84)
        bars = fetch_klines(symbol, "1h", 9000)
        n = len(bars)
        closes = [b["c"] for b in bars]
        rsi7 = wilder_rsi(closes, 7)
        rsi14 = wilder_rsi(closes, 14)
        rsi21 = wilder_rsi(closes, 21)
        atrs = atr_series(bars, 14)
        warm = 30
        split = warm + int((n - warm) * 0.70)
        bh = buyhold(bars, warm, n)
        bh_is = buyhold(bars, warm, split)
        bh_oos = buyhold(bars, split, n)
        print(f"Bar sayısı: {n} | IS: {warm}-{split} | OOS: {split}-{n} | Buy&Hold toplam: {bh:+.1%} (IS {bh_is:+.1%} / OOS {bh_oos:+.1%})")
        header = (f"{'STRATEJİ':26s} {'PENCERE':5s} {'İŞLEM':>5s} {'WR':>6s} {'NET':>8s} {'maxDD':>6s} {'MARJ':>6s} {'İŞLEM/SN?':>4s}")
        print(header)
        for name, sl_mult, efn, xfn in STRATS:
            for label, s, e in (("IS", warm, split), ("OOS", split, n)):
                r = run_strategy(name, bars, rsi7, rsi14, rsi21, atrs, efn, xfn, sl_mult, s, e)
                wr = 100.0 * r.wins / r.trades if r.trades else 0.0
                net = r.equity - 1.0
                dd = r.maxdd
                margin = net / dd if dd > 0 else 0.0
                print(f"{name:26s} {label:5s} {r.trades:>5d} {wr:>5.1f}% {net:>+7.1%} {dd:>5.1%} {margin:>6.2f}")
        print()


if __name__ == "__main__":
    main()
