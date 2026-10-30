"""Mum formasyonları, destek/direnç seviyeleri ve piyasa yapısı (2026-10-30).

Saf fonksiyonlar (ağ/DB yok): mum listesi (`time/open/high/low/close`) alır. Forex sohbeti ve LLM
işlem incelemesi "karar destek" verisi olarak kullanır. Seviyeler HER ZAMAN üretilir: fiyat tarihsel
düşük/yüksekte olsa bile (swing yoksa) pivot, önceki gün/hafta, EMA, Fibonacci ve yuvarlak seviyeler
iki yönde de aday verir.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

Bar = Dict[str, float]


# --------------------------------------------------------------------------- mum formasyonları

def _m(b: Bar) -> Tuple[float, float, float, float, float]:
    o, h, l, c = b["open"], b["high"], b["low"], b["close"]
    return abs(c - o), h - l, h - max(o, c), min(o, c) - l, c - o     # body, range, upper, lower, signed


def _prior_trend(bars: List[Bar], end: int, n: int = 5) -> int:
    """end'den önceki n barın eğilimi: +1 yukarı, -1 aşağı, 0 yatay."""
    if end < 2:
        return 0
    start = max(0, end - n)
    chg = bars[end - 1]["close"] - bars[start]["close"]
    rng = max(b["high"] for b in bars[start:end]) - min(b["low"] for b in bars[start:end])
    if rng <= 0 or abs(chg) < 0.25 * rng:
        return 0
    return 1 if chg > 0 else -1


def detect_patterns(bars: List[Bar], lookback: int = 3) -> List[Dict[str, Any]]:
    """Son `lookback` barda biten formasyonlar. `bars_ago=0` son (oluşmakta olabilen) mum.

    bias: BUY (yükseliş sinyali) / SELL (düşüş sinyali) / NEUTRAL. strength 1-3: bağlama (trend sonu) uyumla artar.
    """
    out: List[Dict[str, Any]] = []
    n = len(bars)
    if n < 8:
        return out
    avg_range = float(np.mean([b["high"] - b["low"] for b in bars[-20:]])) or 1e-12
    for i in range(max(2, n - lookback), n):
        cur = bars[i]
        body, rng, up, lo, sgn = _m(cur)
        if rng <= 0:
            continue
        ago = n - 1 - i
        trend = _prior_trend(bars, i)
        found: List[Tuple[str, str, int]] = []
        big = rng >= 1.2 * avg_range

        if body <= 0.1 * rng:
            found.append(("Doji (kararsızlık)", "NEUTRAL", 1))
        if lo >= 2 * body and up <= 0.15 * rng and body >= 0.05 * rng:
            found.append(("Çekiç (dipten dönüş)", "BUY", 3 if trend < 0 else 1) if trend <= 0
                         else ("Asılı adam (tepeden dönüş)", "SELL", 2))
        if up >= 2 * body and lo <= 0.15 * rng and body >= 0.05 * rng:
            found.append(("Kayan yıldız (tepeden dönüş)", "SELL", 3 if trend > 0 else 1) if trend >= 0
                         else ("Ters çekiç", "BUY", 1))
        if body >= 0.85 * rng and big:
            found.append(("Güçlü yeşil mum (marubozu)", "BUY", 2) if sgn > 0 else ("Güçlü kırmızı mum (marubozu)", "SELL", 2))

        prev = bars[i - 1]
        pbody, prng, _pu, _pl, psgn = _m(prev)
        if prng > 0:
            # yutan
            if psgn < 0 < sgn and cur["open"] <= prev["close"] and cur["close"] >= prev["open"] and body > pbody:
                found.append(("Yutan boğa (yükseliş dönüşü)", "BUY", 3 if trend < 0 else 2))
            if psgn > 0 > sgn and cur["open"] >= prev["close"] and cur["close"] <= prev["open"] and body > pbody:
                found.append(("Yutan ayı (düşüş dönüşü)", "SELL", 3 if trend > 0 else 2))
            # harami
            if pbody >= 0.6 * prng and body < 0.5 * pbody and max(cur["open"], cur["close"]) <= max(prev["open"], prev["close"]) \
                    and min(cur["open"], cur["close"]) >= min(prev["open"], prev["close"]) and psgn * sgn < 0:
                found.append(("Harami", "BUY" if psgn < 0 else "SELL", 1))
            # iç mum
            if cur["high"] <= prev["high"] and cur["low"] >= prev["low"]:
                found.append(("İç mum (sıkışma)", "NEUTRAL", 1))
            # delici / kara bulut
            mid = (prev["open"] + prev["close"]) / 2
            if psgn < 0 < sgn and cur["open"] < prev["close"] and mid < cur["close"] < prev["open"] and pbody >= 0.6 * prng:
                found.append(("Delici hat", "BUY", 2))
            if psgn > 0 > sgn and cur["open"] > prev["close"] and prev["open"] < cur["close"] < mid and pbody >= 0.6 * prng:
                found.append(("Kara bulut örtüsü", "SELL", 2))

        if i >= 2:
            a, b = bars[i - 2], bars[i - 1]
            abody, arng, _au, _al, asgn = _m(a)
            bbody, brng, _bu, _bl, _bs = _m(b)
            if arng > 0 and brng > 0:
                amid = (a["open"] + a["close"]) / 2
                if asgn < 0 and abody >= 0.5 * arng and bbody <= 0.3 * brng + 1e-12 and sgn > 0 and cur["close"] > amid:
                    found.append(("Sabah yıldızı (yükseliş dönüşü)", "BUY", 3))
                if asgn > 0 and abody >= 0.5 * arng and bbody <= 0.3 * brng + 1e-12 and sgn < 0 and cur["close"] < amid:
                    found.append(("Akşam yıldızı (düşüş dönüşü)", "SELL", 3))
                # üç beyaz asker / üç kara karga
                if all(_m(x)[4] > 0 for x in (a, b, cur)) and a["close"] < b["close"] < cur["close"] \
                        and a["open"] <= b["open"] <= a["close"] and b["open"] <= cur["open"] <= b["close"]:
                    found.append(("Üç beyaz asker (güçlü yükseliş)", "BUY", 3))
                if all(_m(x)[4] < 0 for x in (a, b, cur)) and a["close"] > b["close"] > cur["close"] \
                        and a["close"] <= b["open"] <= a["open"] and b["close"] <= cur["open"] <= b["open"]:
                    found.append(("Üç kara karga (güçlü düşüş)", "SELL", 3))
        for name, bias, strength in found:
            out.append({"name": name, "bias": bias, "bars_ago": ago, "strength": strength})
    return out


# --------------------------------------------------------------------------- piyasa yapısı

def _swings(bars: List[Bar], window: int = 3) -> List[Tuple[int, float, str]]:
    sw: List[Tuple[int, float, str]] = []
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    for i in range(window, len(bars) - window):
        if highs[i] == max(highs[i - window:i + window + 1]):
            sw.append((i, highs[i], "H"))
        if lows[i] == min(lows[i - window:i + window + 1]):
            sw.append((i, lows[i], "L"))
    return sw


def market_structure(bars: List[Bar]) -> Dict[str, Any]:
    """Tepe/dip yapısı (HH-HL / LH-LL / yatay) ve kırılım durumu."""
    if len(bars) < 30:
        return {"yapi": "yetersiz veri"}
    sw = _swings(bars[-120:], 3)
    hs = [p for _i, p, k in sw if k == "H"][-3:]
    ls = [p for _i, p, k in sw if k == "L"][-3:]
    if len(hs) >= 2 and len(ls) >= 2:
        if hs[-1] > hs[-2] and ls[-1] > ls[-2]:
            yapi = "yükselen tepe ve dipler (yükseliş yapısı)"
        elif hs[-1] < hs[-2] and ls[-1] < ls[-2]:
            yapi = "alçalan tepe ve dipler (düşüş yapısı)"
        else:
            yapi = "karışık/yatay yapı"
    else:
        yapi = "belirsiz"
    price = bars[-1]["close"]
    prior = bars[-21:-1]
    hi20, lo20 = max(b["high"] for b in prior), min(b["low"] for b in prior)
    state = "son 20 mumun yükseğini kırdı" if price > hi20 else "son 20 mumun düşüğünü kırdı" if price < lo20 else "aralık içinde"
    return {"yapi": yapi, "kirilim": state, "aralik_yuksek": hi20, "aralik_dusuk": lo20}


# --------------------------------------------------------------------------- seviyeler

def _ema(values: List[float], n: int) -> Optional[float]:
    if len(values) < n:
        return None
    a = 2 / (n + 1)
    v = float(np.mean(values[:n]))
    for x in values[n:]:
        v = a * x + (1 - a) * v
    return v


def _round_levels(price: float) -> List[float]:
    if price <= 0:
        return []
    step = 10 ** (math.floor(math.log10(price)) - (2 if price < 10 else 1))
    step = step / 2 if step * 2 <= price * 0.02 else step
    base = math.floor(price / step) * step
    return [base + k * step for k in range(-2, 4)]


def key_levels(frames: Dict[str, List[Bar]], price: float, atr: Optional[float], top: int = 5) -> Dict[str, Any]:
    """Destek/direnç adayları: swing, önceki gün/hafta, pivot, EMA, Fibonacci, yuvarlak seviye.

    Birbirine `tol` içindeki seviyeler birleştirilir (çakışan kaynak = daha güçlü). Her yönde en yakın `top` adet.
    """
    atr = atr or price * 0.002
    tol = max(atr * 0.35, price * 0.0003)
    cands: List[Tuple[float, str, float]] = []        # (fiyat, etiket, ağırlık)

    for tf, w, name in (("1h", 1.0, "1 saat"), ("4h", 1.5, "4 saat"), ("1d", 2.0, "günlük")):
        bars = frames.get(tf) or []
        if len(bars) < 15:
            continue
        for _i, p, k in _swings(bars[-150:], 3):
            cands.append((p, f"{name} swing {'tepe' if k == 'H' else 'dip'}", w))
        closes = [b["close"] for b in bars]
        for n in (50, 200):
            e = _ema(closes, n)
            if e:
                cands.append((e, f"EMA{n} ({name})", 0.8 + (0.4 if n == 200 else 0)))

    daily = frames.get("1d") or []
    if len(daily) >= 3:
        pd = daily[-2]
        ph, pl, pc = pd["high"], pd["low"], pd["close"]
        cands += [(ph, "önceki gün yükseği", 1.6), (pl, "önceki gün düşüğü", 1.6)]
        piv = (ph + pl + pc) / 3
        cands += [(piv, "günlük pivot", 1.2), (2 * piv - pl, "pivot R1", 1.0), (piv + (ph - pl), "pivot R2", 0.8),
                  (2 * piv - ph, "pivot S1", 1.0), (piv - (ph - pl), "pivot S2", 0.8)]
        wk = daily[-5:]
        cands += [(max(b["high"] for b in wk), "haftalık yüksek", 1.6), (min(b["low"] for b in wk), "haftalık düşük", 1.6)]
    h1 = frames.get("1h") or []
    if len(h1) >= 24:
        d24 = h1[-24:]
        cands += [(max(b["high"] for b in d24), "son 24 saat yükseği", 1.4), (min(b["low"] for b in d24), "son 24 saat düşüğü", 1.4)]
    h4 = frames.get("4h") or []
    if len(h4) >= 40:
        seg = h4[-100:]
        hi, lo = max(b["high"] for b in seg), min(b["low"] for b in seg)
        for r, lab in ((0.382, "Fib %38.2"), (0.5, "Fib %50"), (0.618, "Fib %61.8")):
            cands.append((hi - (hi - lo) * r, lab, 0.9))
        cands += [(hi, "4 saat aralık yüksek", 1.0), (lo, "4 saat aralık düşük", 1.0)]
    for lv in _round_levels(price):
        cands.append((lv, "yuvarlak seviye", 0.6))

    cands.sort(key=lambda x: x[0])
    clusters: List[Dict[str, Any]] = []
    for p, label, w in cands:
        if clusters and p - clusters[-1]["max"] <= tol:
            c = clusters[-1]
            c["prices"].append(p)
            c["weights"].append(w)
            c["max"] = p
            if label not in c["labels"]:
                c["labels"].append(label)
        else:
            clusters.append({"prices": [p], "weights": [w], "labels": [label], "max": p})
    levels = []
    for c in clusters:
        wsum = sum(c["weights"])
        lvl = sum(p * w for p, w in zip(c["prices"], c["weights"])) / wsum
        levels.append({"price": lvl, "labels": c["labels"][:4], "strength": round(wsum, 1),
                       "distance_atr": round(abs(price - lvl) / atr, 2) if atr else None,
                       "distance_pct": round(abs(price - lvl) / price * 100, 2)})
    supports = sorted([l for l in levels if l["price"] < price - tol * 0.5], key=lambda l: price - l["price"])[:top]
    resist = sorted([l for l in levels if l["price"] > price + tol * 0.5], key=lambda l: l["price"] - price)[:top]
    return {"supports": supports, "resistances": resist}


# --------------------------------------------------------------------------- grafik verisi

def compact_chart(bars: List[Bar], n: int) -> List[List[float]]:
    """Son n mum [açılış, yüksek, düşük, kapanış] (LLM'e kısa grafik)."""
    if not bars:
        return []
    price = bars[-1]["close"]
    d = 2 if price >= 100 else 4 if price >= 1 else 5
    return [[round(b["open"], d), round(b["high"], d), round(b["low"], d), round(b["close"], d)] for b in bars[-n:]]


def key_ranges(frames: Dict[str, List[Bar]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    h1 = frames.get("1h") or []
    d1 = frames.get("1d") or []
    if len(h1) >= 24:
        out["son_24s_yuksek"] = max(b["high"] for b in h1[-24:])
        out["son_24s_dusuk"] = min(b["low"] for b in h1[-24:])
    if len(d1) >= 3:
        out["onceki_gun"] = {"yuksek": d1[-2]["high"], "dusuk": d1[-2]["low"], "kapanis": d1[-2]["close"]}
        wk = d1[-5:]
        out["hafta_yuksek"] = max(b["high"] for b in wk)
        out["hafta_dusuk"] = min(b["low"] for b in wk)
    return out


TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
SQUEEZE_SPAN_ATR = 2.5          # pencere genişliği (yüksek-düşük) bu kadar ATR'yi aşana kadar mumlar "aynı sıkışma"dır
BIG_MOVE_ATR = 2.0              # bir mumun aralığı ≥ bu kadar ATR ise "büyük hareket" sayılır


def consolidation(bars: List[Bar], minutes: int) -> Dict[str, Any]:
    """Fiyat kaç dakikadır dar bantta? (kullanıcı sorusu: "kaç dakikadır yatay?").

    Sondan geriye mumlar eklenir; pencerenin (yüksek-düşük) aralığı `SQUEEZE_SPAN_ATR`×ATR'yi aşınca durulur.
    Döner: {mum, dakika, yuksek, dusuk, genislik_atr, son_buyuk_hareket_dakika_once}. Veri yetersizse {}.
    """
    if len(bars) < 20 or minutes <= 0:
        return {}
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[-14:]) / 14.0
    if atr <= 0:
        return {}
    hi, lo, n = bars[-1]["high"], bars[-1]["low"], 1
    for b in reversed(bars[:-1]):
        nh, nl_ = max(hi, b["high"]), min(lo, b["low"])
        if nh - nl_ > SQUEEZE_SPAN_ATR * atr:
            break
        hi, lo, n = nh, nl_, n + 1
    since_big = None
    for k, tr in enumerate(reversed(trs)):
        if tr >= BIG_MOVE_ATR * atr:
            since_big = k * minutes
            break
    price = bars[-1]["close"]
    d = 2 if price >= 100 else 4 if price >= 1 else 5
    return {"mum": n, "dakika": n * minutes, "yuksek": round(hi, d), "dusuk": round(lo, d),
            "genislik_atr": round((hi - lo) / atr, 2), "son_buyuk_hareket_dakika_once": since_big}
