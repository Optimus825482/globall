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

from app import forex_patterns as fp
from app.technical_analysis import _adx, _atr, _bollinger, _ema, _macd, _rsi

logger = logging.getLogger("scalper.forex_research")

# Araştırma işleri (MT5 bekleme, HTTP, analiz) ASYNCIO'NUN VARSAYILAN HAVUZUNDAN AYRI çalışır: bu işler
# saniyelerce thread tutar; ortak havuzu (DB ve diğer `to_thread` çağrıları) açlığa düşürmemeli.
_RESEARCH_POOL = ThreadPoolExecutor(max_workers=12, thread_name_prefix="research")


async def run_blocking(fn, *args):
    """Bloke eden araştırma fonksiyonunu özel havuzda çalıştırır (olay döngüsü ve varsayılan havuz serbest kalır)."""
    import asyncio
    return await asyncio.get_running_loop().run_in_executor(_RESEARCH_POOL, lambda: fn(*args))

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
    # Karar desteği: çok kaynaklı seviyeler, mum formasyonları, piyasa yapısı, kısa grafik, aralıklar.
    atr_1h = (frames.get("1h") or {}).get("atr") or atr
    levels = fp.key_levels({tf: candles[tf] for tf in ("1h", "4h", "1d") if tf in candles}, price, atr_1h)
    patterns = {tf: fp.detect_patterns(candles[tf]) for tf in ("5m", "15m", "1h", "4h", "1d") if tf in candles}
    structure = {tf: fp.market_structure(candles[tf]) for tf in ("15m", "1h", "4h", "1d") if tf in candles}
    chart = {tf: fp.compact_chart(candles[tf], n) for tf, n in (("15m", 16), ("1h", 24), ("4h", 12), ("1d", 10)) if tf in candles}
    sup = levels["supports"][0]["price"] if levels["supports"] else ref.get("support")
    res = levels["resistances"][0]["price"] if levels["resistances"] else ref.get("resistance")
    return {
        "symbol": symbol, "ok": True, "price": price, "price_source": price_src, "price_age": price_age,
        "bias": bias, "score": round(avg, 2), "frames": frames, "sources": sources, "candles": candles,
        "support": sup, "resistance": res, "levels": levels, "patterns": patterns, "structure": structure,
        "chart": chart, "ranges": fp.key_ranges(candles),
        "atr": atr, "stop_distance": round(atr * 1.5, 6) if atr else None,
    }


def compact_for_llm(a: Dict[str, Any]) -> Dict[str, Any]:
    """Analiz sonucunun modele verilen kısa hali (seviyeler, formasyonlar, yapı, grafik, aralıklar)."""
    price = a["price"]

    def lv(rows):
        return [{"fiyat": round(r["price"], 5 if price < 10 else 2), "kaynak": r["labels"], "guc": r["strength"],
                 "uzaklik_atr": r.get("distance_atr"), "uzaklik_yuzde": r.get("distance_pct")} for r in rows]

    pats = {tf: [{"ad": p["name"], "yon": p["bias"], "kac_mum_once": p["bars_ago"], "guc": p["strength"]} for p in ps]
            for tf, ps in (a.get("patterns") or {}).items() if ps}
    return {
        "destekler": lv((a.get("levels") or {}).get("supports", [])),
        "direncler": lv((a.get("levels") or {}).get("resistances", [])),
        "mum_formasyonlari": pats,
        "piyasa_yapisi": {tf: {"yapi": st.get("yapi"), "kirilim": st.get("kirilim")} for tf, st in (a.get("structure") or {}).items()},
        "aralıklar": a.get("ranges"),
        "son_mumlar_OHLC": a.get("chart"),
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
    lv = a.get("levels") or {}
    if lv.get("supports") or lv.get("resistances"):
        def fmt_lv(rows):
            return ", ".join(f"{_fmt(r['price'], price)} ({r['labels'][0]})" for r in rows[:3]) or "—"
        lines.append(f"Destekler: {fmt_lv(lv.get('supports', []))}. Dirençler: {fmt_lv(lv.get('resistances', []))}.")
    else:
        levels = []
        if a.get("support"):
            levels.append(f"yakın destek {_fmt(a['support'], price)}")
        if a.get("resistance"):
            levels.append(f"yakın direnç {_fmt(a['resistance'], price)}")
        if levels:
            lines.append(", ".join(levels).capitalize() + ".")
    pat_parts = []
    for tf in ("5m", "15m", "1h", "4h", "1d"):
        for p in (a.get("patterns") or {}).get(tf, []):
            if p["bias"] != "NEUTRAL" and p["bars_ago"] <= 1 and p["strength"] >= 2:
                pat_parts.append(f"{TF_LABEL[tf]}: {p['name']} ({p['bias']}{', son mum' if p['bars_ago'] == 0 else ''})")
    if pat_parts:
        lines.append("Mum formasyonları: " + "; ".join(pat_parts[:4]) + ".")
    st = a.get("structure") or {}
    if st.get("4h") or st.get("1d"):
        lines.append("Yapı: " + ", ".join(f"{TF_LABEL[tf]} {st[tf]['yapi']}" for tf in ("1h", "4h", "1d")
                                          if st.get(tf) and st[tf].get("yapi") not in (None, "belirsiz", "yetersiz veri")) + ".")
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

# TradingView sembolleri: (scanner pazarı, kod). Haber akışı için aynı kod kullanılır.
_TV = {
    "XAUUSD": ("cfd", "OANDA:XAUUSD"), "XAGUSD": ("cfd", "OANDA:XAGUSD"),
    "BTCUSD": ("crypto", "BINANCE:BTCUSDT"), "ETHUSD": ("crypto", "BINANCE:ETHUSDT"),
    "USTEC": ("cfd", "OANDA:NAS100USD"), "NAS100": ("cfd", "OANDA:NAS100USD"), "US30": ("cfd", "OANDA:US30USD"),
}

# Investing.com RSS: sembol sınıfına göre kategori akışları (+ genel piyasa özeti).
_INVESTING_FEEDS = {
    "gold": ["news_11", "market_overview"], "crypto": ["news_301", "market_overview"], "fx": ["news_1", "market_overview"],
    "index": ["news_25", "market_overview"],
}
# Akışlar sembole özel değil: başlık bu anahtar sözcüklerden birini içeriyorsa alınır.
_RELEVANCE = {
    "gold": ("gold", "bullion", "xau", "precious", "fed", "inflation", "pce", "dollar", "treasury", "yield"),
    "crypto": ("bitcoin", "btc", "crypto", "ether", "etf", "binance", "stablecoin"),
    "index": ("nasdaq", "dow", "s&p", "wall street", "stocks", "fed", "inflation", "yield"),
}
_CCY_WORDS = {
    "USD": ("dollar", "usd", "fed", "treasury", "powell", "payroll", "pce", "inflation", "cpi"),
    "EUR": ("euro", "eur", "ecb", "lagarde", "eurozone"), "GBP": ("pound", "sterling", "gbp", "boe", "bank of england"),
    "JPY": ("yen", "jpy", "boj", "bank of japan"), "AUD": ("aussie", "aud", "rba", "australia"),
    "NZD": ("kiwi", "nzd", "rbnz"), "CAD": ("loonie", "cad", "boc", "canada"), "CHF": ("franc", "chf", "snb", "swiss"),
}


def _asset_class(sym: str) -> str:
    sym = sym.upper()
    if sym.startswith(("XAU", "XAG")):
        return "gold"
    if sym.startswith(("BTC", "ETH")):
        return "crypto"
    if sym in ("USTEC", "NAS100", "US30"):
        return "index"
    return "fx"


def _keywords(sym: str) -> tuple:
    cls = _asset_class(sym)
    if cls == "fx":
        out: list = []
        for ccy in (sym[:3], sym[3:]):
            out.extend(_CCY_WORDS.get(ccy, ()))
        return tuple(out)
    return _RELEVANCE.get(cls, ())


def _parse_rss(body: bytes, via: str, now: float, max_age_hours: float) -> List[Dict[str, Any]]:
    # XXE / "billion laughs": RSS'te DTD olmaz; içeren yanıt reddedilir (defusedxml yerine).
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        logger.warning("haber yanıtı DTD içeriyor, reddedildi (%s)", via)
        return []
    try:
        root = ET.fromstring(body)  # noqa: S314 - DTD yukarıda elendi
    except ET.ParseError:
        return []
    out: List[Dict[str, Any]] = []
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
        src = (it.findtext("source") or "").strip() or via
        out.append({"title": title[:200], "source": src[:40], "via": via, "age_hours": round(max(age_h, 0), 1), "ts": ts})
    return out


def _http_bytes(url: str, headers: Optional[Dict[str, str]] = None, data: Optional[bytes] = None) -> bytes:
    h = dict(UA)
    h.update(headers or {})
    try:
        with urlopen(Request(url, headers=h, data=data), timeout=HTTP_TIMEOUT_SEC) as resp:  # noqa: S310 - sabit host
            return resp.read(MAX_BODY_BYTES)
    except Exception as exc:  # noqa: BLE001
        logger.info("haber/veri HTTP hatası (%s): %s", url.split("?")[0][-48:], exc)
        return b""


def _google_headlines(sym: str, now: float, max_age_hours: float) -> List[Dict[str, Any]]:
    query = NEWS_QUERY.get(sym)
    if not query:
        query = f"{sym[:3]} {sym[3:]} forex" if re.fullmatch(r"[A-Z]{6}", sym) else sym
    url = f"https://news.google.com/rss/search?q={quote(query)}%20when:2d&hl=en-US&gl=US&ceid=US:en"
    return _parse_rss(_http_bytes(url), "Google News", now, max_age_hours)


def _investing_headlines(sym: str, now: float, max_age_hours: float) -> List[Dict[str, Any]]:
    keys = _keywords(sym)
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for feed in _INVESTING_FEEDS.get(_asset_class(sym), ["news_1"]):
        for item in _parse_rss(_http_bytes(f"https://www.investing.com/rss/{feed}.rss"), "Investing.com", now, max_age_hours):
            low = item["title"].lower()
            norm = _norm_title(item["title"])
            if norm in seen:      # aynı haber birden çok akışta çıkabilir
                continue
            if not keys or any(k in low for k in keys):
                seen.add(norm)
                out.append(item)
    return out


def _tradingview_headlines(sym: str, now: float, max_age_hours: float) -> List[Dict[str, Any]]:
    spec = _TV.get(sym)
    code = spec[1] if spec else (f"OANDA:{sym}" if re.fullmatch(r"[A-Z]{6}", sym) else None)
    if not code:
        return []
    body = _http_bytes(f"https://news-headlines.tradingview.com/v2/headlines?client=web&lang=en&symbol={quote(code, safe='')}")
    try:
        items = json.loads(body).get("items", [])
    except Exception:  # noqa: BLE001
        return []
    out: List[Dict[str, Any]] = []
    for it in items[:60]:
        try:
            ts = float(it["published"])
            title = str(it["title"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        age_h = (now - ts) / 3600
        if not title or age_h > max_age_hours or age_h < -1:
            continue
        out.append({"title": title[:200], "source": str(it.get("source") or "TradingView")[:40], "via": "TradingView",
                    "age_hours": round(max(age_h, 0), 1), "ts": ts})
    return out


# Dış kaynaktan gelen başlıklar LLM istemine girer: talimat/JSON enjeksiyonu denemeleri elenir.
_INJECTION_RE = re.compile(
    r"(ignore|disregard|forget|override)\W+(\w+\W+){0,4}(instruction|rule|prompt|above|previous)"
    r"|system\s+prompt|developer\s+(message|mode)|\byou\s+(must|should|are\s+now|will)\b|\bas\s+an\s+ai\b"
    r"|\bassistant\b|respond\s+with|output\s+(only\s+)?json|return\s+(only\s+)?json|\"decision\"|\"confidence\""
    r"|\bapprove\s+(this|the)\s+(trade|order)|\breject\s+(this|the)\s+(trade|order)",
    re.IGNORECASE,
)


def sanitize_headline(title: str, max_len: int = 160) -> Optional[str]:
    """Başlığı veri olarak güvenli hale getirir; talimat benzeri içerik taşıyorsa None (elenir)."""
    t = "".join(ch for ch in str(title or "") if ch.isprintable())
    t = re.sub(r"[{}\[\]<>`\\]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t or _INJECTION_RE.search(t):
        return None
    return t[:max_len]


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()[:70]


def fetch_headlines(symbol: str, max_items: int = 8, max_age_hours: float = 36.0) -> List[Dict[str, Any]]:
    """Üç kaynaktan güncel başlıklar: Google News + Investing.com RSS + TradingView haber akışı.

    Kaynaklar paralel çekilir; biri çökerse diğerleri sürer. Aynı haber (benzer başlık) bir kez
    sayılır; en yeni üstte. Her kaydın `via` alanı kaynağı gösterir.
    """
    sym = symbol.upper()
    now = time.time()
    fetchers = (_google_headlines, _investing_headlines, _tradingview_headlines)
    with ThreadPoolExecutor(max_workers=len(fetchers)) as pool:
        results = list(pool.map(lambda f: _safe(f, sym, now, max_age_hours), fetchers))
    merged: List[Dict[str, Any]] = []
    seen: set = set()
    for item in sorted((i for r in results for i in r), key=lambda x: x["ts"], reverse=True):
        clean = sanitize_headline(item["title"])
        if clean is None:
            logger.warning("talimat benzeri haber başlığı elendi (%s)", item.get("via"))
            continue
        item["title"] = clean
        key = _norm_title(item["title"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    # Kaynak çeşitliliği: her kaynaktan en az 2 başlık (varsa) listeye girsin, kalanı yeniliğe göre.
    picked: List[Dict[str, Any]] = []
    for via in ("TradingView", "Investing.com", "Google News"):
        picked.extend([m for m in merged if m["via"] == via][:2])
    for m in merged:
        if len(picked) >= max_items:
            break
        if m not in picked:
            picked.append(m)
    picked.sort(key=lambda x: x["ts"], reverse=True)
    for x in picked:
        x.pop("ts", None)
    return picked[:max_items]


def _safe(fn, *args) -> List[Dict[str, Any]]:
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001
        logger.info("haber kaynağı hatası (%s): %s", getattr(fn, "__name__", "?"), exc)
        return []


def describe_headlines(symbol: str, items: List[Dict[str, Any]]) -> str:
    name = SYMBOL_NAME.get(symbol, symbol)
    if not items:
        return f"{name} için son 36 saatte öne çıkan haber başlığı bulunamadı (Google News, Investing.com, TradingView tarandı)."
    counts: Dict[str, int] = {}
    for x in items:
        counts[x["via"]] = counts.get(x["via"], 0) + 1
    srcs = ", ".join(f"{k} {v}" for k, v in counts.items())
    lines = [f"{name} için son haberlerden {len(items)} başlık ({srcs}):"]
    for x in items[:5]:
        age = f"{x['age_hours']:.0f} sa önce" if x["age_hours"] >= 1 else "az önce"
        lines.append(f"• {x['title']} ({x['source']}, {age})")
    return "\n".join(lines)


# --------------------------------------------------------------------------- TradingView teknik özeti (halka açık)

_TV_COLS = ["Recommend.All|1", "Recommend.All|5", "Recommend.All|15", "Recommend.All|30", "Recommend.All|60",
            "Recommend.All|240", "Recommend.All", "close"]
_TV_LABELS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
_tv_cache: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}


def _tv_word(v: float) -> str:
    return ("güçlü AL" if v >= 0.5 else "AL" if v >= 0.1 else "güçlü SAT" if v <= -0.5
            else "SAT" if v <= -0.1 else "nötr")


def tradingview_technicals(symbol: str) -> Optional[Dict[str, Any]]:
    """TradingView'in halka açık tarayıcı verisi: 1dk–günlük teknik reyting (-1 SAT … +1 AL) ve fiyat."""
    sym = symbol.upper()
    spec = _TV.get(sym) or (("forex", f"OANDA:{sym}") if re.fullmatch(r"[A-Z]{6}", sym) else None)
    if not spec:
        return None
    now = time.time()
    hit = _tv_cache.get(sym)
    if hit and now - hit[0] < 60:
        return hit[1]
    body = json.dumps({"symbols": {"tickers": [spec[1]]}, "columns": _TV_COLS}).encode()
    raw = _http_bytes(f"https://scanner.tradingview.com/{spec[0]}/scan", {"Content-Type": "application/json"}, body)
    result: Optional[Dict[str, Any]] = None
    try:
        row = json.loads(raw)["data"][0]["d"]
        ratings = {tf: round(float(v), 2) for tf, v in zip(_TV_LABELS, row[:7]) if v is not None}
        if ratings:
            avg = sum(ratings.values()) / len(ratings)
            result = {"ratings": ratings, "words": {tf: _tv_word(v) for tf, v in ratings.items()},
                      "average": round(avg, 2), "summary": _tv_word(avg), "price": row[7]}
    except Exception:  # noqa: BLE001
        result = None
    _tv_cache[sym] = (now, result)
    return result


def describe_tradingview(symbol: str, tv: Optional[Dict[str, Any]]) -> str:
    name = SYMBOL_NAME.get(symbol, symbol)
    if not tv:
        return f"{name} için TradingView teknik özeti alınamadı."
    parts = [f"{TF_LABEL[tf]} {w}" for tf, w in tv["words"].items() if tf in TF_LABEL]
    return (f"TradingView teknik özeti ({name}): genel {tv['summary']}. " + ", ".join(parts) + ".")


# --------------------------------------------------------------------------- fırsat taraması (TradingView toplu)

SCAN_UNIVERSE = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "EURJPY", "GBPJPY",
                 "EURGBP", "AUDJPY", "AUDNZD", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD", "USTEC", "US30"]
_SCAN_WEIGHTS = {"15m": 1.0, "1h": 2.0, "4h": 2.0, "1d": 3.0}


def scan_opportunities(symbols: Optional[List[str]] = None, top: int = 5) -> Optional[Dict[str, Any]]:
    """Tüm evreni TradingView'in toplu tarayıcısıyla (pazar başına 1 istek) sıralar.

    Sıra puanı: 15dk/1sa/4sa/günlük reytinglerin ağırlıklı ortalamasının mutlağı × zaman dilimi uyumu.
    Sonuç yalnız ADAY listesidir; asıl derin analiz üst adaylara ayrıca yapılır.
    """
    syms = [x.upper() for x in (symbols or SCAN_UNIVERSE)]
    by_market: Dict[str, List[Tuple[str, str]]] = {}
    for sym in syms:
        spec = _TV.get(sym) or (("forex", f"OANDA:{sym}") if re.fullmatch(r"[A-Z]{6}", sym) else None)
        if spec:
            by_market.setdefault(spec[0], []).append((sym, spec[1]))

    def _one(item):
        market, pairs = item
        body = json.dumps({"symbols": {"tickers": [c for _s, c in pairs]}, "columns": _TV_COLS}).encode()
        raw = _http_bytes(f"https://scanner.tradingview.com/{market}/scan", {"Content-Type": "application/json"}, body)
        try:
            data = json.loads(raw)["data"]
        except Exception:  # noqa: BLE001
            return []
        code_to_sym = {c: s_ for s_, c in pairs}
        return [(code_to_sym.get(d["s"]), d["d"]) for d in data if code_to_sym.get(d["s"])]

    with ThreadPoolExecutor(max_workers=max(1, len(by_market))) as pool:
        rows = [r for part in pool.map(_one, by_market.items()) for r in part]
    ranked: List[Dict[str, Any]] = []
    for sym, d in rows:
        ratings = {tf: float(v) for tf, v in zip(_TV_LABELS, d[:7]) if v is not None}
        use = {tf: ratings[tf] for tf in _SCAN_WEIGHTS if tf in ratings}
        if len(use) < 3:
            continue
        total_w = sum(_SCAN_WEIGHTS[tf] for tf in use)
        avg = sum(v * _SCAN_WEIGHTS[tf] for tf, v in use.items()) / total_w
        sign = 1 if avg >= 0 else -1
        agree = sum(1 for v in use.values() if v * sign > 0.05) / len(use)
        ranked.append({"symbol": sym, "direction": "BUY" if avg >= 0 else "SELL", "average": round(avg, 2),
                       "agreement": round(agree, 2), "score": round(abs(avg) * agree, 3),
                       "summary": _tv_word(avg), "price": d[7],
                       "ratings": {tf: round(v, 2) for tf, v in ratings.items()}})
    if not ranked:
        return None
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return {"top": ranked[:top], "all": ranked, "scanned": len(ranked)}


def describe_scan(scan: Optional[Dict[str, Any]]) -> str:
    if not scan:
        return "Fırsat taraması yapılamadı (TradingView verisi alınamadı)."
    lines = [f"{scan['scanned']} enstrüman tarandı; en net yönlü olanlar (TradingView teknik reytingi, çoklu zaman dilimi uyumuna göre):"]
    for r in scan["top"][:5]:
        name = SYMBOL_NAME.get(r["symbol"], r["symbol"])
        name = name if name == r["symbol"] else f"{name} ({r['symbol']})"
        lines.append(f"• {name}: {r['summary']} — zaman dilimi uyumu %{int(r['agreement'] * 100)}")
    return "\n".join(lines)
