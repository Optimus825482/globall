"""Forex / Altın / BTC sohbeti için bağımsız araştırma katmanı (2026-10-30).

Radar ve otonom motor kararlarından BAĞIMSIZ: kendi mum verisini çeker (Yahoo
chart API), çok zaman dilimli teknik analiz yapar ve Google News RSS'ten güncel
başlıkları toplar. Hepsi sınırlı süreli, kısa önbellekli ve hata durumunda
sessizce "veri yok" döner — sohbet asla bunlar yüzünden bloke olmaz.

Haber başlıkları DIŞ kaynaktır: modele "veri" olarak verilir, talimat olarak
değil (bkz. forex_chat.SYSTEM_PROMPT).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
from urllib.request import Request, urlopen

import numpy as np

from app.technical_analysis import _adx, _atr, _bollinger, _ema, _macd, _rsi

logger = logging.getLogger("scalper.forex_research")

HTTP_TIMEOUT_SEC = 6.0
MAX_BODY_BYTES = 1_500_000
UA = {"User-Agent": "Mozilla/5.0 (compatible; ScalperResearch/1.0)"}

# Yahoo sembol eşlemesi (forex.YAHOO_SYMBOL_MAP içe aktarılmaz: ağır router bağımlılığı).
YAHOO = {
    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
    "USTEC": "^NDX", "NAS100": "^NDX", "US30": "^DJI",
}
_FX_CODES = ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY")
NEWS_QUERY = {
    "XAUUSD": "gold price XAUUSD", "XAGUSD": "silver price", "BTCUSD": "Bitcoin price",
    "ETHUSD": "Ethereum price", "USTEC": "Nasdaq 100", "US30": "Dow Jones",
}
SYMBOL_NAME = {"XAUUSD": "Altın", "XAGUSD": "Gümüş", "BTCUSD": "Bitcoin", "ETHUSD": "Ethereum",
               "USTEC": "Nasdaq 100", "US30": "Dow Jones"}

# (periyot, yahoo interval, yahoo range, ağırlık). 3dk ve 4sa Yahoo'da yok: 1dk / 1sa'ten türetilir.
TIMEFRAMES: List[Tuple[str, str, str, float]] = [
    ("1m", "1m", "2d", 0.5),
    ("3m", "1m", "2d", 0.5),     # 1 dakikalıktan türetilir
    ("5m", "5m", "5d", 1.0),
    ("15m", "15m", "5d", 1.5),
    ("30m", "30m", "1mo", 1.5),
    ("1h", "60m", "1mo", 2.0),
    ("4h", "60m", "3mo", 2.5),   # 1 saatlikten türetilir
    ("1d", "1d", "1y", 3.0),
]
_DERIVED_SEC = {"3m": 180, "4h": 4 * 3600}
TF_LABEL = {"1m": "1 dk", "3m": "3 dk", "5m": "5 dk", "15m": "15 dk", "30m": "30 dk",
            "1h": "1 saat", "4h": "4 saat", "1d": "Günlük"}
MIN_BARS = 60
MT5_WAIT_SEC = 7.0

_cache: Dict[Tuple[str, str], Tuple[float, List[Dict[str, float]]]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = {"1m": 30.0, "3m": 30.0, "5m": 45.0, "15m": 60.0, "30m": 120.0, "1h": 180.0, "4h": 300.0, "1d": 600.0}


def yahoo_ticker(symbol: str) -> Optional[str]:
    sym = symbol.upper()
    if sym in YAHOO:
        return YAHOO[sym]
    if re.fullmatch(r"[A-Z]{6}", sym) and sym[:3] in _FX_CODES and sym[3:] in _FX_CODES:
        return f"{sym}=X"
    return None


def currencies_for(symbol: str) -> set:
    """Takvimde ilgili olacak para birimleri (altın/BTC/endeks → USD)."""
    sym = symbol.upper()
    if re.fullmatch(r"[A-Z]{6}", sym) and sym[:3] in _FX_CODES and sym[3:] in _FX_CODES:
        return {sym[:3], sym[3:]}
    return {"USD"}


def _http_json(url: str) -> Optional[dict]:
    try:
        with urlopen(Request(url, headers=UA), timeout=HTTP_TIMEOUT_SEC) as resp:  # noqa: S310 - sabit host
            return json.loads(resp.read(MAX_BODY_BYTES))
    except Exception as exc:  # noqa: BLE001
        logger.info("araştırma HTTP hatası (%s): %s", url.split("?")[0][-40:], exc)
        return None


def _yahoo_candles(ticker: str, interval: str, rng: str) -> List[Dict[str, float]]:
    data = _http_json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker, safe='')}?interval={interval}&range={rng}")
    try:
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
    except Exception:  # noqa: BLE001
        return []
    out: List[Dict[str, float]] = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        out.append({"time": int(t), "open": float(o), "high": float(h), "low": float(l), "close": float(c)})
    return out


def _resample(candles: List[Dict[str, float]], bucket_sec: int) -> List[Dict[str, float]]:
    groups: Dict[int, List[Dict[str, float]]] = {}
    for c in candles:
        groups.setdefault(int(c["time"]) // bucket_sec, []).append(c)
    out = []
    for key in sorted(groups):
        g = groups[key]
        out.append({"time": key * bucket_sec, "open": g[0]["open"], "high": max(x["high"] for x in g),
                    "low": min(x["low"] for x in g), "close": g[-1]["close"]})
    return out


def _yahoo_tf(symbol: str, tf: str) -> List[Dict[str, float]]:
    ticker = yahoo_ticker(symbol)
    spec = next((t for t in TIMEFRAMES if t[0] == tf), None)
    if not ticker or not spec:
        return []
    key = (ticker, tf)
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL.get(tf, 120.0):
            return hit[1]
    candles = _yahoo_candles(ticker, spec[1], spec[2])
    if tf in _DERIVED_SEC:
        candles = _resample(candles, _DERIVED_SEC[tf])
    if candles:
        with _cache_lock:
            _cache[key] = (now, candles)
    return candles


# --------------------------------------------------------------------------- MT5 köprüsü

def _fx():
    """Forex router'ı (MT5 mum/fiyat önbellekleri). Ağır bağımlılık: geç içe aktarılır."""
    from app.routers import forex as fx
    return fx


def mt5_request(symbol: str) -> None:
    """Köprüye bu sembolün TÜM periyotlarını izlemesini söyler (sonraki senkronda mumlar gelir)."""
    fx = _fx()
    for tf, *_ in TIMEFRAMES:
        fx._note_forex_viewed(symbol, tf)


def mt5_candles(symbol: str, tf: str) -> List[Dict[str, float]]:
    try:
        fx = _fx()
        return list(fx._fetch_mt5_candles(fx._clean_forex_chart_symbol(symbol), tf, 300) or [])
    except Exception as exc:  # noqa: BLE001
        logger.info("MT5 mum okunamadı (%s %s): %s", symbol, tf, exc)
        return []


def mt5_bridge_alive() -> bool:
    """Köprü son 60 sn içinde senkron yaptı mı? (Değilse mum beklemenin anlamı yok.)"""
    try:
        st = _fx()._MT5_STATE
        return bool(st.get("connected") and time.time() - float(st.get("last_ping", 0.0) or 0.0) < 60.0)
    except Exception:  # noqa: BLE001
        return False


def mt5_wait(symbol: str, timeout: float = MT5_WAIT_SEC) -> int:
    """Köprü mumlarının gelmesini bekler (talepten sonra birkaç sn sürebilir). Gelen periyot sayısını döner."""
    if not mt5_bridge_alive():
        return sum(1 for tf, *_ in TIMEFRAMES if len(mt5_candles(symbol, tf)) >= MIN_BARS)
    deadline = time.time() + timeout
    have = 0
    while True:
        have = sum(1 for tf, *_ in TIMEFRAMES if len(mt5_candles(symbol, tf)) >= MIN_BARS)
        if have == len(TIMEFRAMES) or time.time() >= deadline:
            return have
        time.sleep(0.5)


def get_candles(symbol: str, tf: str) -> Tuple[List[Dict[str, float]], str]:
    """(mumlar, kaynak). MT5 köprüsü öncelikli; yeterli mum yoksa Yahoo."""
    bars = mt5_candles(symbol, tf)
    if len(bars) >= MIN_BARS:
        return bars, "mt5"
    return _yahoo_tf(symbol, tf), "yahoo"


def live_price(symbol: str, fallback: Optional[float] = None) -> Tuple[Optional[float], str, Optional[float]]:
    """(fiyat, kaynak, yaş_sn). Önce MT5 anlık tik; yoksa son MT5 1dk mumu; yoksa verilen yedek."""
    try:
        fx = _fx()
        key = fx.canonical_symbol(symbol)
        px = fx._LIVE_PRICES_CACHE.get(key)
        ts = float(fx._PRICE_TS.get(key, 0.0) or 0.0)
        if px and fx._PRICE_SOURCE.get(key) == "mt5_tick" and ts and time.time() - ts < 60:
            return float(px), "mt5_tick", round(time.time() - ts, 1)
    except Exception as exc:  # noqa: BLE001
        logger.info("MT5 anlık fiyat okunamadı (%s): %s", symbol, exc)
    one = mt5_candles(symbol, "1m")
    if one:
        return float(one[-1]["close"]), "mt5_mum", None
    return fallback, "yahoo", None


# --------------------------------------------------------------------------- teknik analiz

def _swing_levels(highs: List[float], lows: List[float], price: float, window: int = 3) -> Tuple[Optional[float], Optional[float]]:
    """Fiyatın altındaki en yakın swing dip (destek) ve üstündeki en yakın swing tepe (direnç)."""
    sup: List[float] = []
    res: List[float] = []
    n = len(highs)
    for i in range(window, n - window):
        if highs[i] == max(highs[i - window:i + window + 1]) and highs[i] > price:
            res.append(highs[i])
        if lows[i] == min(lows[i - window:i + window + 1]) and lows[i] < price:
            sup.append(lows[i])
    return (max(sup) if sup else None), (min(res) if res else None)


def analyze_candles(candles: List[Dict[str, float]]) -> Optional[Dict[str, Any]]:
    """Tek zaman dilimi için: trend, momentum, volatilite, seviyeler ve -6..+6 arası yön puanı."""
    if len(candles) < 60:
        return None
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    price = closes[-1]
    ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
    ema200 = _ema(closes, 200) if len(closes) >= 200 else None
    rsi = _rsi(closes, 14)
    macd = _macd(closes)
    adx_res = _adx(highs, lows, closes)
    adx = adx_res.get("adx") if isinstance(adx_res, dict) else adx_res
    atr = _atr(highs, lows, closes)
    boll = _bollinger(closes)
    support, resistance = _swing_levels(highs[-80:], lows[-80:], price)
    # np.float64 / None karışımı: skorda yalnızca mevcut göstergeler sayılır.
    score = 0.0
    if ema20 and ema50:
        score += 1.0 if price > ema20 > ema50 else -1.0 if price < ema20 < ema50 else 0.0
    if ema200:
        score += 1.0 if price > ema200 else -1.0
    hist = None
    if isinstance(macd, dict):
        hist = macd.get("histogram", macd.get("hist"))
        if hist is not None:
            score += 1.0 if hist > 0 else -1.0
    if rsi is not None:
        score += 1.0 if 52 < rsi < 70 else -1.0 if 30 < rsi < 48 else 0.0
    slope = (closes[-1] - closes[-11]) / closes[-11] if len(closes) > 11 else 0.0
    score += 1.0 if slope > 0 else -1.0
    trending = bool(adx is not None and adx >= 22)
    if not trending:
        score *= 0.5   # trendsiz piyasada yön güvenilmez
    overbought = bool(rsi is not None and rsi >= 72)
    oversold = bool(rsi is not None and rsi <= 28)
    return {
        "price": price, "ema20": ema20, "ema50": ema50, "ema200": ema200, "rsi": rsi, "macd_hist": hist,
        "adx": adx, "atr": atr, "bb_pos": (boll or {}).get("position") if boll else None,
        "support": support, "resistance": resistance, "score": round(score, 2),
        "trending": trending, "overbought": overbought, "oversold": oversold,
    }


def _dir_word(score: float) -> str:
    return "yukarı" if score >= 1.5 else "aşağı" if score <= -1.5 else "yatay"


def _fmt(v: Optional[float], price: float) -> str:
    if v is None:
        return "—"
    d = 2 if price >= 100 else 4 if price >= 1 else 5
    return f"{v:.{d}f}"


def analyze_symbol(symbol: str) -> Dict[str, Any]:
    """8 zaman dilimli analiz + anlık fiyat + toplam yön + seviyeler (MT5 öncelikli). Ağ/IO yapar: thread'de çağır."""
    frames: Dict[str, Dict[str, Any]] = {}
    sources: Dict[str, str] = {}
    candles: Dict[str, List[Dict[str, float]]] = {}
    with ThreadPoolExecutor(max_workers=len(TIMEFRAMES)) as pool:
        fetched = list(pool.map(lambda spec: (spec[0], *get_candles(symbol, spec[0])), TIMEFRAMES))
    for tf, bars, src in fetched:
        res = analyze_candles(bars)
        if res:
            frames[tf] = res
            sources[tf] = src
            candles[tf] = bars
    if not frames:
        return {"symbol": symbol, "ok": False, "error": "Fiyat verisi alınamadı"}
    weights = {tf: w for tf, _i, _r, w in TIMEFRAMES}
    total_w = sum(weights[tf] for tf in frames)
    avg = sum(frames[tf]["score"] * weights[tf] for tf in frames) / total_w   # ≈ -6..+6
    last_close = (frames.get("1m") or frames.get("5m") or next(iter(frames.values())))["price"]
    price, price_src, price_age = live_price(symbol, fallback=last_close)
    price = price or last_close
    ref = frames.get("4h") or frames.get("1h") or next(iter(frames.values()))
    daily = frames.get("1d")
    bias = "BUY" if avg >= 2.0 else "SELL" if avg <= -2.0 else "BEKLE"
    # Üst zaman dilimi ters ise güveni düşür: kısa vade BUY ama günlük SELL → BEKLE.
    if daily and bias == "BUY" and daily["score"] <= -2:
        bias = "BEKLE"
    if daily and bias == "SELL" and daily["score"] >= 2:
        bias = "BEKLE"
    atr = ref.get("atr")
    return {
        "symbol": symbol, "ok": True, "price": price, "price_source": price_src, "price_age": price_age,
        "bias": bias, "score": round(avg, 2), "frames": frames, "sources": sources, "candles": candles,
        "support": ref.get("support"), "resistance": ref.get("resistance"),
        "atr": atr, "stop_distance": round(atr * 1.5, 6) if atr else None,
    }


def describe_analysis(a: Dict[str, Any]) -> str:
    """Sade Türkçe bulgu metni (kullanıcıya canlı gösterilen kart + modele bağlam)."""
    name = SYMBOL_NAME.get(a["symbol"], a["symbol"])
    if not a.get("ok"):
        return f"{name}: {a.get('error', 'veri yok')}."
    price = a["price"]
    label = name if name == a["symbol"] else f"{name} ({a['symbol']})"
    lines = [f"{label} şu an {_fmt(price, price)}; teknik yön: {a['bias']} (puan {a['score']:+.1f})."]
    parts = [f"{TF_LABEL[tf]} {_dir_word(a['frames'][tf]['score'])}" for tf, *_ in TIMEFRAMES if tf in a["frames"]]
    lines.append("Zaman dilimleri: " + ", ".join(parts) + ".")
    ref = a["frames"].get("4h") or a["frames"].get("1h") or {}
    notes = []
    if ref.get("rsi") is not None:
        r = ref["rsi"]
        notes.append("aşırı alım bölgesinde" if r >= 70 else "aşırı satım bölgesinde" if r <= 30
                     else f"momentum dengeli (RSI {r:.0f})")
    if ref.get("adx") is not None:
        notes.append("trend güçlü" if ref["adx"] >= 25 else "trend zayıf/yatay" if ref["adx"] < 20 else "trend orta")
    if notes:
        lines.append("4 saatlikte " + ", ".join(notes) + ".")
    levels = []
    if a.get("support"):
        levels.append(f"yakın destek {_fmt(a['support'], price)}")
    if a.get("resistance"):
        levels.append(f"yakın direnç {_fmt(a['resistance'], price)}")
    if levels:
        lines.append(", ".join(levels).capitalize() + ".")
    if a.get("stop_distance"):
        lines.append(f"Normal oynaklığa göre stop mesafesi yaklaşık {_fmt(a['stop_distance'], price)}.")
    lines.append(describe_sources(a))
    return " ".join(lines)


def describe_sources(a: Dict[str, Any]) -> str:
    src = a.get("sources", {})
    yahoo = [TF_LABEL[tf] for tf, *_ in TIMEFRAMES if src.get(tf) == "yahoo"]
    n_mt5 = sum(1 for v in src.values() if v == "mt5")
    if a.get("price_source") == "mt5_tick":
        age = a.get("price_age")
        px = "fiyat MT5'ten anlık" + (f" ({age:.0f} sn önce)" if age is not None and age >= 1 else "")
    elif a.get("price_source") == "mt5_mum":
        px = "fiyat MT5 mumundan"
    else:
        px = "fiyat Yahoo'dan (MT5 anlık fiyatı gelmedi)"
    if not yahoo:
        return f"Veri: MT5 köprüsü, {len(src)} zaman diliminin hepsi; {px}."
    if n_mt5 == 0:
        return f"Veri: MT5 verisi henüz gelmedi, hepsi Yahoo'dan; {px}."
    return f"Veri: {n_mt5} dilim MT5'ten, {', '.join(yahoo)} Yahoo'dan; {px}."


# --------------------------------------------------------------------------- haber başlıkları

def fetch_headlines(symbol: str, max_items: int = 8, max_age_hours: float = 36.0) -> List[Dict[str, Any]]:
    """Google News RSS: sembolle ilgili güncel başlıklar (en yeni üstte)."""
    sym = symbol.upper()
    query = NEWS_QUERY.get(sym)
    if not query:
        query = f"{sym[:3]} {sym[3:]} forex" if re.fullmatch(r"[A-Z]{6}", sym) else sym
    url = f"https://news.google.com/rss/search?q={quote(query)}%20when:2d&hl=en-US&gl=US&ceid=US:en"
    try:
        with urlopen(Request(url, headers=UA), timeout=HTTP_TIMEOUT_SEC) as resp:  # noqa: S310 - sabit host
            body = resp.read(MAX_BODY_BYTES)
        # XXE / "billion laughs": RSS'te DTD olmaz; içeren yanıt reddedilir (defusedxml yerine).
        if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
            logger.warning("haber yanıtı DTD içeriyor, reddedildi (%s)", sym)
            return []
        root = ET.fromstring(body)  # noqa: S314 - DTD yukarıda elendi
    except Exception as exc:  # noqa: BLE001
        logger.info("haber araması hatası (%s): %s", sym, exc)
        return []
    now = time.time()
    items: List[Dict[str, Any]] = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        try:
            ts = parsedate_to_datetime(it.findtext("pubDate") or "").timestamp()
        except Exception:  # noqa: BLE001
            continue
        age_h = (now - ts) / 3600
        if age_h > max_age_hours or age_h < -1:
            continue
        src = (it.findtext("source") or "").strip()
        items.append({"title": title[:200], "source": src[:40], "age_hours": round(max(age_h, 0), 1), "ts": ts})
    items.sort(key=lambda x: x["ts"], reverse=True)
    for x in items:
        x.pop("ts", None)
    return items[:max_items]


def describe_headlines(symbol: str, items: List[Dict[str, Any]]) -> str:
    name = SYMBOL_NAME.get(symbol, symbol)
    if not items:
        return f"{name} için son 36 saatte öne çıkan haber başlığı bulunamadı."
    lines = [f"{name} için son haberlerden {len(items)} başlık:"]
    for x in items[:4]:
        age = f"{x['age_hours']:.0f} sa önce" if x["age_hours"] >= 1 else "az önce"
        lines.append(f"• {x['title']} ({age})")
    return "\n".join(lines)
