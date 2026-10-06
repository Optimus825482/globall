#!/usr/bin/env python3
"""Hibrit Portföy & Rejim Kalkanı Replay (Geriye Dönük Kanıt Betiği).

AMAÇ:
Önerilen hibrit mimariyi 10 coin × 9000 saatlik piyasa döngüsünde (IS Ayı %70 + OOS Boğa %30)
birebir simüle etmek ve kanıtlamak.

PORTFÖY MODELİ:
1) MODEL 1 [Saf Trend/Breakout]:
   - Filtresiz trend pullback/momentum (RSI21>50, RSI7<40 → al, RSI7>60 → çık, SL 2.0 ATR).
2) MODEL 2 [Güçlendirilmiş Trend/Breakout]:
   - MODEL 1 + BTC > EMA200 (1H) Makro Kalkanı + Coin EMA34 > EMA144 Boğa Yapısı Teyidi.
3) MODEL 3 [Bağımsız Dip Avcısı — S2 Snapback]:
   - RSI7 < 20 & RSI14 < 30 → al; RSI7 > 50 → çık; SL 1.5 ATR.
4) MODEL 4 [HİBRİT ENSEMBLE PORTFÖY (%50 Model 2 + %50 Model 3)]:
   - Eşzamanlı iki bağımsız alt-strateji:
     * Trendde Model 2 kâr yazar.
     * Dump/panik anlarında Model 3 dipten V-zıplaması toplar.
     * Sermaye %50-%50 tahsis edilir, toplam portföy bileşik eğrisi takip edilir.

KOMİSYON: %0.1/side spot taker.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from dataclasses import dataclass, field
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


@dataclass
class SimState:
    equity: float = 1.0
    peak: float = 1.0
    maxdd: float = 0.0
    trades: int = 0
    wins: int = 0
    equity_curve: List[float] = field(default_factory=list)


def run_hybrid_replay(bars: List[dict], rsi7: List, rsi14: List, rsi21: List,
                      atrs: List, ema34: List, ema144: List,
                      btc_gate: List[float], start: int, end: int) -> Dict[str, SimState]:
    """Her barda 4 modeli eşzamanlı çalıştırır."""
    m1 = SimState()  # Saf Trend
    m2 = SimState()  # Guclendirilmis Trend (BTC Gate + EMA Teyit)
    m3 = SimState()  # Dip Avcisi (S2 Snapback)
    
    # M4 Hibrit: %50 M2 + %50 M3
    m4 = SimState()

    pos1: Optional[Tuple[float, float]] = None
    pos2: Optional[Tuple[float, float]] = None
    pos3: Optional[Tuple[float, float]] = None

    # M4 alt bilesen equity'leri
    eq2_for_m4 = 0.5
    eq3_for_m4 = 0.5

    for i in range(start, end):
        c = bars[i]["c"]
        l = bars[i]["l"]
        r7 = rsi7[i]
        r14 = rsi14[i]
        r21 = rsi21[i]
        a = atrs[i]
        e34 = ema34[i]
        e144 = ema144[i]
        bg = btc_gate[i]

        # -----------------------------
        # MODEL 1: Saf Trend Pullback
        # -----------------------------
        if pos1 is not None:
            ent, sl = pos1
            if c <= sl:
                net = (c / ent) * (1.0 - FEE) * (1.0 - FEE) - 1.0
                m1.trades += 1
                m1.equity *= (1.0 + net)
                if net >= 0: m1.wins += 1
                pos1 = None
            elif r7 is not None and r7 > 60:
                net = (c / ent) * (1.0 - FEE) * (1.0 - FEE) - 1.0
                m1.trades += 1
                m1.equity *= (1.0 + net)
                if net >= 0: m1.wins += 1
                pos1 = None
        else:
            if r7 is not None and r21 is not None and a is not None:
                if r21 > 50 and r7 < 35:
                    pos1 = (c, c - 2.0 * a)

        m1.peak = max(m1.peak, m1.equity)
        m1.maxdd = max(m1.maxdd, 1.0 - m1.equity / m1.peak)

        # --------------------------------------------------
        # MODEL 2: Güçlendirilmiş Trend (BTC Gate + EMA34/144)
        # --------------------------------------------------
        if pos2 is not None:
            ent, sl = pos2
            if c <= sl:
                net = (c / ent) * (1.0 - FEE) * (1.0 - FEE) - 1.0
                m2.trades += 1
                m2.equity *= (1.0 + net)
                eq2_for_m4 *= (1.0 + net)
                if net >= 0: m2.wins += 1
                pos2 = None
            elif r7 is not None and r7 > 60:
                net = (c / ent) * (1.0 - FEE) * (1.0 - FEE) - 1.0
                m2.trades += 1
                m2.equity *= (1.0 + net)
                eq2_for_m4 *= (1.0 + net)
                if net >= 0: m2.wins += 1
                pos2 = None
        else:
            if r7 is not None and r21 is not None and a is not None and e34 is not None and e144 is not None:
                # Kalkan 1: BTC > EMA200
                # Kalkan 2: Coin EMA34 > EMA144 & c > EMA144
                btc_ok = bg is not None and bg > 1.0
                trend_ok = e34 > e144 and c > e144
                if btc_ok and trend_ok and r21 > 50 and r7 < 35:
                    pos2 = (c, c - 2.0 * a)

        m2.peak = max(m2.peak, m2.equity)
        m2.maxdd = max(m2.maxdd, 1.0 - m2.equity / m2.peak)

        # -----------------------------
        # MODEL 3: S2 Snapback Dip Avcısı
        # -----------------------------
        if pos3 is not None:
            ent, sl = pos3
            if c <= sl:
                net = (c / ent) * (1.0 - FEE) * (1.0 - FEE) - 1.0
                m3.trades += 1
                m3.equity *= (1.0 + net)
                eq3_for_m4 *= (1.0 + net)
                if net >= 0: m3.wins += 1
                pos3 = None
            elif r7 is not None and r7 > 50:
                net = (c / ent) * (1.0 - FEE) * (1.0 - FEE) - 1.0
                m3.trades += 1
                m3.equity *= (1.0 + net)
                eq3_for_m4 *= (1.0 + net)
                if net >= 0: m3.wins += 1
                pos3 = None
        else:
            if r7 is not None and r14 is not None and a is not None:
                if r7 < 20 and r14 < 30:
                    pos3 = (c, c - 1.5 * a)

        m3.peak = max(m3.peak, m3.equity)
        m3.maxdd = max(m3.maxdd, 1.0 - m3.equity / m3.peak)

        # ---------------------------------------------
        # MODEL 4: Hibrit Ensemble (%50 M2 + %50 M3)
        # ---------------------------------------------
        m4_total_equity = eq2_for_m4 + eq3_for_m4
        m4.equity = m4_total_equity
        m4.peak = max(m4.peak, m4.equity)
        m4.maxdd = max(m4.maxdd, 1.0 - m4.equity / m4.peak)

    m4.trades = m2.trades + m3.trades
    m4.wins = m2.wins + m3.wins

    return {"M1_SafTrend": m1, "M2_GucluTrend": m2, "M3_DipAvcisi": m3, "M4_HibritEnsemble": m4}


def buyhold(bars: List[dict], start: int, end: int) -> float:
    if end <= start: return 0.0
    return bars[end - 1]["c"] / bars[start]["c"] - 1.0


def main():
    coins = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT"]
    print("=" * 110)
    print("HİBRİT PORTFÖY REPLAY (10 Coin × 9000 Saatlik IS/OOS Piyasası)")
    print("=" * 110)
    print("Binance 1H barlar yukleniyor...")

    btc_bars = fetch_klines("BTCUSDT", "1h", 9000)
    btc_closes = [b["c"] for b in btc_bars]
    btc_ema200 = ema_series(btc_closes, 200)
    btc_gate_series = [btc_closes[i] / btc_ema200[i] if btc_ema200[i] > 0 else None for i in range(len(btc_closes))]

    results = {}
    bh_map = {}

    for sym in coins:
        bars = fetch_klines(sym, "1h", 9000)
        n = len(bars)
        closes = [b["c"] for b in bars]
        r7 = wilder_rsi(closes, 7)
        r14 = wilder_rsi(closes, 14)
        r21 = wilder_rsi(closes, 21)
        atrs = atr_series(bars, 14)
        e34 = ema_series(closes, 34)
        e144 = ema_series(closes, 144)

        warm = 30
        split = warm + int((n - warm) * 0.70)

        results[sym] = {
            "IS": run_hybrid_replay(bars, r7, r14, r21, atrs, e34, e144, btc_gate_series, warm, split),
            "OOS": run_hybrid_replay(bars, r7, r14, r21, atrs, e34, e144, btc_gate_series, split, n),
        }
        bh_map[sym] = (buyhold(bars, warm, split), buyhold(bars, split, n))
        print(f"[OK] {sym}: {n} bar yuklendi.")

    models = ["M1_SafTrend", "M2_GucluTrend", "M3_DipAvcisi", "M4_HibritEnsemble"]
    model_labels = {
        "M1_SafTrend": "M1 Saf Trend",
        "M2_GucluTrend": "M2 Kalkan+Trend",
        "M3_DipAvcisi": "M3 S2 Dip",
        "M4_HibritEnsemble": "M4 HİBRİT (%50+%50)",
    }

    for window in ("IS", "OOS"):
        print()
        print("=" * 115)
        w_title = "IS (%70 AYI DÖNEMİ — PİYASA ÇÖKÜŞÜ)" if window == "IS" else "OOS (%30 BOĞA DÖNEMİ — RALLİ)"
        print(f"{w_title} — NET GETİRİ (%) | Komisyon %0.1/side dahil")
        print("=" * 115)
        hdr = f"{'COIN':10s}" + "".join(f"{model_labels[m]:>20s}" for m in models) + f"{'B&H':>12s}"
        print(hdr)
        print("-" * 115)

        for sym in coins:
            row = f"{sym:10s}"
            for m in models:
                res = results[sym][window][m]
                row += f"{(res.equity - 1.0) * 100:>+19.1f}%"
            bh = bh_map[sym][0] if window == "IS" else bh_map[sym][1]
            row += f"{bh * 100:>+11.1f}%"
            print(row)

        print("-" * 115)
        # Topluluk Özeti
        for m in models:
            rets = [results[sym][window][m].equity - 1.0 for sym in coins]
            poss = sum(1 for r in rets if r > 0)
            avg_ret = sum(rets) / len(rets)
            trades = sum(results[sym][window][m].trades for sym in coins)
            wrs = [100.0 * results[sym][window][m].wins / max(1, results[sym][window][m].trades) for sym in coins]
            avg_wr = sum(wrs) / len(wrs)
            mdds = [results[sym][window][m].maxdd * 100.0 for sym in coins]
            avg_mdd = sum(mdds) / len(mdds)

            print(f"{model_labels[m]:20s} -> Pozitif: {poss:>2}/10 | Ort Getiri: {avg_ret*100:>+6.1f}% | "
                  f"Ort WR: {avg_wr:5.1f}% | Ort MaxDD: %{avg_mdd:4.1f} | Toplam İşlem: {trades}")
        print("=" * 115)


if __name__ == "__main__":
    main()
