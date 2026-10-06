#!/usr/bin/env python3
"""Forex Otonom Scalper — 7 Günlük Walk-Forward Replay (Eski vs Yeni A/B).

Aynı Yahoo Finance 5M mum serisi üzerinde iki varyantı bar-bar simüle eder:

  OLD  — CMO/CCI'siz skor, sabit spec TP/SL, DXY/korelasyon/saat filtresi yok
  NEW  — CMO+CCI+üçlü teyit, ATR çıkış motoru + kısmi kâr, DXY rejim vetosu,
         FX korelasyon kalkanı, zayıf saat kalkanı

Ek olarak NEW varyantında yeni kapılardan (DXY / SAAT / KORELASYON) bloklanan
her aday giriş için "gölge defter" tutulur: filtre ne reddettiğini ölçer
(kapı bazında varsayımsal PnL — negatifse filtre doğru karar vermiş demektir).

Kullanım:
    python scripts/forex_replay_backtest.py --days 7
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.app.routers import forex  # noqa: E402
from backend.app.forex_correlation import FXCorrelationMonitor  # noqa: E402

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
INDICATOR_WINDOW = 260      # bar — canlı motor ~576 bar (2d) kullanır; hız için kırpıldı
CORR_REFRESH_EVERY = 36     # bar (≈ 3 saat)
MAX_OPEN_POSITIONS = 6
MAX_PER_SYMBOL_DIR = 3
PYRAMID_MIN_PROFIT_USD = 0.20
RISK_PCT = 1.0
BALANCE = 10000.0
TRADES_PER_BAR_CAP = 3
SHADOW_MAX_CONCURRENT = 60
BASE_BE_PIPS = 14.0         # canlı ayar varsayılanları (Motorla aynı)
BASE_TRAIL_PIPS = 20.0
BLOCKED_HOURS: List[int] = []
CATEGORY_SPREAD_PIPS = {"major": 1.2, "commodity": 2.5, "crypto": 12.0, "index": 3.0, "cross": 2.0}
# Replay-local sembol tanımları: canlı FOREX_SYMBOLS'ta olmayan test adayları (JPY kross'ları)
REPLAY_SYMBOL_DEFS = {
    "GBPJPY": {"pip_size": 0.01, "digits": 3, "category": "cross"},
    "EURJPY": {"pip_size": 0.01, "digits": 3, "category": "cross"},
    "AUDJPY": {"pip_size": 0.01, "digits": 3, "category": "cross"},
}
# Gölge defter tutulan kapılar (yeni özellikler)
SHADOW_GATES = ("DXY", "SAAT", "KORELASYON", "ADX", "SUPERTREND", "EV",
                "SEANS", "VOLATİLİTE", "UZAMA", "REJIM", "VWAP")

# EV kalkanı (canlı motorla aynı; WR 45 = 2026-10-06 30g replay kararı)
EV_WINDOW_SEC = 24 * 3600
EV_MIN_TRADES = 10
EV_MAX_WIN_RATE = 45.0
EV_LOSS_RISK_MULT = 3.0
EV_GUARD = True

# Ayarlanabilir tuning parametreleri (CLI ile override edilir)
TUN_MIN_SCORE = 70.0
TUN_SL_ATR_MULT = 1.1
TUN_TP_ATR_MULT = 1.4
TUN_RR_FLOOR = 1.5
TUN_HEADROOM_FOREX = 3.5
TUN_ADX_MIN = 0.0           # 0 = ADX kalkanı kapalı
TUN_ST_FILTER = False       # SuperTrend yön teyidi kapalı/kapalı

# 2026-10-06 varyant mekanikleri (30 günlük replay A/B ile test ediliyor)
FX_MAJORS = {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"}
TUN_FX_MIN_SCORE = 0.0      # 0 = majörler için ayrı eşik yok (min_score geçerli)
TUN_GOLD_DXY_SOFT = False   # (Tarihi) XAUUSD DXY yumuşatma — canlı artık tam muaf
TUN_GOLD_DXY_BUMP = 5.0

# 2026-10-06 araştırma mekanizmaları (majör güçlendirme + volatilite-adaptif trailing)
TUN_CHANDLIER = 0.0         # >0: trailing = MFE − chandelier×ATR(giriş) (0 = sabit pip trail)
TUN_MAJOR_HOURS = None      # (başlangıç, biti) UTC saat aralığı — majörler yalnız bu pencerede (None = kapalı)
TUN_MAJOR_MIN_ATR = 0.0     # majörler minimum ATR(pips) — ölü piyasa filtresi (0 = kapalı)
TUN_MAJOR_MAX_EXT = 0.0     # majörlerde fiyatın EMA21'den maks. ATR-katı uzaması — kovalamama (0 = kapalı)
GATED_EXTRAS: set = set()   # --gate-extras: majör kapılarına (seans+minATR) tabi tutulacak ek adaylar

# 2026-10-06 altın/BTC geliştirme testleri
TUN_GOLD_SESSION = False    # altın için de seans penceresi (majör kapısıyla aynı 7-20 UTC)
TUN_BTC_EMA200 = False      # BTC girişlerine EMA200(1h) yapısal rejim kapısı (BUY>EMA, SELL<EMA)
TUN_BTC_VWAP = False        # BTC girişlerine günlük VWAP kapısı (BUY>VWAP, SELL<VWAP; hacim gerektirir)
TUN_CRYPTO_SL_MULT = 0.0    # kripto kategorisi özel SL ATR çarpanı (0 = global sl_mult)
TUN_BTC_MIN_SCORE = 0.0     # BTC özel skor eşiği (0 = global min_score)

# 2026-10-06 "kazananı koştur" testi (kullanıcı sorusu: trailing devreye girince sabit TP kalksa?)
TUN_TP_MODE = "tp"          # "tp" | "no_tp_on_trail" (trailing aktiflenince TP çekilir) | "no_tp" (TP hiç yok)

# 2026-10-06 altın volatilite-adaptif BE/trailing (kullanıcı isteği: BE/SL/TP/trail her işlemde
# o işlemin giriş ATR'ine göre ölçeklensin). SL/TP zaten ATR çıkış motorunda; burada BE tetiği
# (min_be_pips tabanı) ve trailing mesafesi giriş ATR'ine bağlanır (XAUUSD'ye özel).
TUN_GOLD_VOL_EXITS = False
TUN_VOL_BE_MULT = 0.8       # BE tetik tabanı: be_mult × giriş-ATR (pip) — $1 dolar kuralı yine alt sınır
TUN_VOL_TRAIL_MULT = 1.5    # trailing mesafesi: trail_mult × giriş-ATR (pip)


# ---------------------------------------------------------------------------
# Veri çekme
# ---------------------------------------------------------------------------
def fetch_candles(yf_sym: str, days: int) -> Optional[List[Tuple]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_sym}?interval=5m&range={days}d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data["chart"]["result"][0]
            quote = result["indicators"]["quote"][0]
            ts = result.get("timestamp", [])
            o, h, l, c = quote.get("open", []), quote.get("high", []), quote.get("low", []), quote.get("close", [])
            bars = []
            for i in range(min(len(ts), len(c))):
                if None in (o[i], h[i], l[i], c[i]):
                    continue
                bars.append((float(ts[i]), float(o[i]), float(h[i]), float(l[i]), float(c[i])))
            return bars
    except Exception as exc:
        print(f"[VERI HATASI] {yf_sym}: {exc}")
        return None


def fetch_all(days: int) -> Dict[str, List[Tuple]]:
    data: Dict[str, List[Tuple]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        futs = {ex.submit(fetch_candles, yf, days): fx for fx, yf in forex.YAHOO_SYMBOL_MAP.items()}
        for fut in concurrent.futures.as_completed(futs, timeout=180):
            fx = futs[fut]
            try:
                bars = fut.result()
                if bars and len(bars) >= 300:
                    data[fx] = bars
                else:
                    print(f"[UYARI] {fx}: yetersiz bar ({len(bars) if bars else 0}) — atlandı")
            except Exception:
                pass
    return data


# ---------------------------------------------------------------------------
# Simülasyon pozisyonu ve çıkış motoru
# ---------------------------------------------------------------------------
@dataclass
class SimPos:
    symbol: str
    direction: str
    lots: float
    entry_price: float
    sl_price: float
    tp_price: float
    pip_size: float
    pip_val: float
    digits: int
    opened_bar: int
    fill_adjust: float = 0.0
    be_locked: bool = False
    partial_taken: bool = False
    partial_target_pips: float = 0.0
    partial_realized_usd: float = 0.0
    trail_active: bool = False
    entry_atr_pips: float = 0.0
    mfe_pips: float = 0.0


class Book:
    def __init__(self, name: str):
        self.name = name
        self.balance = BALANCE
        self.realized = 0.0
        self.positions: List[SimPos] = []
        self.closed: List[Dict] = []
        self.per_symbol: Dict[str, Dict[str, float]] = {}


def be_headroom_pips(symbol: str) -> float:
    s = symbol.upper()
    if "XAU" in s or "GOLD" in s:
        return 4.0
    if "BTC" in s:
        return 25.0
    return TUN_HEADROOM_FOREX


def size_lots(symbol: str, sl_pips: float, pip_val: float) -> float:
    risk_usd = BALANCE * (RISK_PCT / 100.0)
    raw = risk_usd / (sl_pips * pip_val) if sl_pips > 0 else 0.01
    s = symbol.upper()
    if "NAS" in s or "USTEC" in s or "US30" in s or "SPX" in s:
        return round(max(0.10, min(round(raw * 10) / 10, 0.20)), 2)
    if "OIL" in s or "WTI" in s:
        return round(max(0.50, min(raw, 1.0)), 2)
    if "XAU" in s or "GOLD" in s or "BTC" in s or "ETH" in s:
        return round(max(0.01, min(raw, 0.02)), 2)
    return round(max(0.01, min(raw, 0.05)), 2)


def open_position(cand: Dict, sl_pips: float, tp_pips: float, partial_pips: float, idx: int) -> Optional[SimPos]:
    sym = cand["symbol"]
    half_spread = cand["spread_pips"] * cand["pip_size"] / 2.0
    mid = cand["price"]
    if cand["action"] == "BUY":
        entry = round(mid + half_spread, cand["digits"])
        sl = round(entry - sl_pips * cand["pip_size"], cand["digits"])
        tp = round(entry + tp_pips * cand["pip_size"], cand["digits"])
    else:
        entry = round(mid - half_spread, cand["digits"])
        sl = round(entry + sl_pips * cand["pip_size"], cand["digits"])
        tp = round(entry - tp_pips * cand["pip_size"], cand["digits"])
    lots = size_lots(sym, sl_pips, cand["pip_val"])
    # Canlı motorla aynı risk normalizasyonu (tek kaynak: forex.apply_risk_normalization)
    lots, risk_skip = forex.apply_risk_normalization(sym, lots, sl_pips, cand["pip_val"], BALANCE * RISK_PCT / 100.0)
    if risk_skip:
        return None
    return SimPos(
        symbol=sym, direction=cand["action"], lots=lots,
        entry_price=entry, sl_price=sl, tp_price=tp, pip_size=cand["pip_size"],
        pip_val=cand["pip_val"], digits=cand["digits"], opened_bar=idx,
        partial_target_pips=partial_pips, fill_adjust=half_spread,
        entry_atr_pips=cand.get("atr_pips", 0.0),
    )


def manage_position(pos: SimPos, bar: Tuple, eff_trail_pips: float, eff_be_pips: float,
                    chandelier_mult: float = 0.0, tp_mode: str = "tp",
                    min_be_pips: float = 0.0) -> Optional[Tuple[str, float, float]]:
    """Bir bar'da pozisyonu yönetir. Dönüş: (reason, exit_price, partial_realized) veya None.

    Sıra (muhafazakâr): SL önce → BE kilidi → kısmi kâr → trailing → TP.
    Kısmi kâr gerçekleşmesi pozisyona yazılır; balance'a close_position'da eklenir.
    tp_mode: "no_tp_on_trail" → trailing aktiflenince TP emri çekilir (kazananı koştur);
             "no_tp" → TP hiç yok. Aktifleşen barın kendisinde TP hâlâ geçerlidir
             (canlıda TP broker tarafında bekleyen emirdir; MODIFY_SLTP ancak sonraki
             tick'te etkili olur — muhafazakâr model: bar-başı trail bayrağına bakılır).
    min_be_pips: BE kilidinin EN ERKEN tetiklenme tabanı (pip) — volatilite-adaptif BE
             için kullanılır (0 = kapalı; $1 dolar kuralı yine kendi eşikte çalışır).
    """
    ts, o, h, l, c = bar
    pip = pos.pip_size
    direction = pos.direction
    entry = pos.entry_price
    trail_pre = pos.trail_active  # bar-başı değer — TP silahı bu bar için buna bakar

    # (1) SL önce (muhafazakâr) — çıkışta spread maliyeti uygulanır
    if direction == "BUY" and l <= pos.sl_price:
        reason = "BE" if (pos.be_locked and pos.sl_price >= entry) else "SL"
        return (reason, round(pos.sl_price - pos.fill_adjust, pos.digits), 0.0)
    if direction == "SELL" and h >= pos.sl_price:
        reason = "BE" if (pos.be_locked and pos.sl_price <= entry) else "SL"
        return (reason, round(pos.sl_price + pos.fill_adjust, pos.digits), 0.0)

    ext = h if direction == "BUY" else l
    pnl_extreme_pips = (ext - entry) / pip if direction == "BUY" else (entry - ext) / pip
    pips_for_1usd = max(0.5, round(1.0 / max(0.0001, pos.lots * pos.pip_val), 1))
    headroom = be_headroom_pips(pos.symbol)

    # MFE takibi (girişten beri en iyi fiyat, pip) — chandelier trailing için
    if pos.mfe_pips < pnl_extreme_pips:
        pos.mfe_pips = pnl_extreme_pips

    # (2) BE kilidi ($1 net kâr garantisinin üstünde, %40 kâr kilidi)
    if not pos.be_locked:
        is_dollar_be = pnl_extreme_pips >= (pips_for_1usd + headroom)
        is_pip_be = eff_be_pips > 0 and pnl_extreme_pips >= eff_be_pips
        if (is_dollar_be or is_pip_be) and pnl_extreme_pips >= min_be_pips:
            locked = max(pips_for_1usd, round(pnl_extreme_pips * 0.40, 1))
            if direction == "BUY":
                cand = round(entry + locked * pip, pos.digits)
                if cand > pos.sl_price and cand < ext:
                    pos.sl_price = cand
                    pos.be_locked = True
            else:
                cand = round(entry - locked * pip, pos.digits)
                if (pos.sl_price == 0 or cand < pos.sl_price) and cand > ext:
                    pos.sl_price = cand
                    pos.be_locked = True

    # (3) Kısmi kâr (yalnızca NEW — OLD'da partial_target_pips=0)
    if pos.partial_target_pips > 0 and not pos.partial_taken and pnl_extreme_pips >= pos.partial_target_pips:
        pos.partial_taken = True
        close_lots = round(pos.lots / 2.0, 2)
        if 0.01 <= close_lots < pos.lots:
            partial_realized = round(pos.partial_target_pips * close_lots * pos.pip_val, 2)
            pos.lots = round(pos.lots - close_lots, 2)
            pos.partial_realized_usd = round(pos.partial_realized_usd + partial_realized, 2)
            remaining_dpp = max(0.0001, pos.lots * pos.pip_val)
            lock_pips = max(0.5, round(1.0 / remaining_dpp, 1))
            if direction == "BUY":
                lock_sl = round(entry + lock_pips * pip, pos.digits)
                if lock_sl > pos.sl_price:
                    pos.sl_price = lock_sl
            else:
                lock_sl = round(entry - lock_pips * pip, pos.digits)
                if lock_sl < pos.sl_price:
                    pos.sl_price = lock_sl
            pos.be_locked = True

    # (4) Trailing (BE sonrası): chandelier (MFE − mult×ATR_giriş) veya sabit pip trail
    if pos.be_locked:
        pips_1usd_now = max(0.5, round(1.0 / max(0.0001, pos.lots * pos.pip_val), 1))
        if chandelier_mult > 0 and pos.entry_atr_pips > 0:
            # Volatilite-adaptif: kâr tepesinden volatilite nefes payı kadar geri ver
            giveback = chandelier_mult * pos.entry_atr_pips
            cand_pips = pos.mfe_pips - giveback
            if direction == "BUY":
                cand = round(entry + cand_pips * pip, pos.digits)
                min_safe = round(entry + pips_1usd_now * pip, pos.digits)
                cand = max(cand, min_safe)
                if cand > pos.sl_price:
                    pos.sl_price = cand
                    pos.trail_active = True
            else:
                cand = round(entry - cand_pips * pip, pos.digits)
                min_safe = round(entry - pips_1usd_now * pip, pos.digits)
                cand = min(cand, min_safe)
                if pos.sl_price == 0 or cand < pos.sl_price:
                    pos.sl_price = cand
                    pos.trail_active = True
        elif eff_trail_pips > 0:
            trail_dist = eff_trail_pips * pip
            if direction == "BUY":
                cand = round(c - trail_dist, pos.digits)
                min_safe = round(entry + pips_1usd_now * pip, pos.digits)
                cand = max(cand, min_safe)
                if cand > pos.sl_price and cand > entry:
                    pos.sl_price = cand
                    pos.trail_active = True
            else:
                cand = round(c + trail_dist, pos.digits)
                min_safe = round(entry - pips_1usd_now * pip, pos.digits)
                cand = min(cand, min_safe)
                if (pos.sl_price == 0 or cand < pos.sl_price) and cand < entry:
                    pos.sl_price = cand
                    pos.trail_active = True

    # (5) TP — tp_mode'a göre silahlanır (bkz. docstring)
    if tp_mode == "no_tp" or (tp_mode == "no_tp_crypto" and ("BTC" in pos.symbol.upper() or "ETH" in pos.symbol.upper())):
        tp_armed = False
    elif tp_mode == "no_tp_on_trail":
        tp_armed = not trail_pre          # muhafazakâr: aktifleşen barda TP hâlâ geçerli
    elif tp_mode == "no_tp_on_trail_live":
        tp_armed = not pos.trail_active   # canlıya yakın: aktifleşen barda da TP çekilir
    else:
        tp_armed = True
    if tp_armed:
        if direction == "BUY" and h >= pos.tp_price:
            return ("TP", round(pos.tp_price - pos.fill_adjust, pos.digits), 0.0)
        if direction == "SELL" and l <= pos.tp_price:
            return ("TP", round(pos.tp_price + pos.fill_adjust, pos.digits), 0.0)
    return None


def close_position(book: Book, pos: SimPos, reason: str, exit_price: float, closed_ts: float = 0.0) -> float:
    if pos.direction == "BUY":
        pnl_pips = (exit_price - pos.entry_price) / pos.pip_size
    else:
        pnl_pips = (pos.entry_price - exit_price) / pos.pip_size
    pnl_usd = round(pnl_pips * pos.lots * pos.pip_val, 2)
    total = round(pnl_usd + pos.partial_realized_usd, 2)
    book.balance = round(book.balance + total, 2)
    book.realized = round(book.realized + total, 2)
    st = book.per_symbol.setdefault(pos.symbol, {"n": 0, "wins": 0, "pnl": 0.0})
    st["n"] = int(st["n"]) + 1
    st["pnl"] = round(st["pnl"] + total, 2)
    if total >= 0:
        st["wins"] = int(st["wins"]) + 1
    book.closed.append({
        "symbol": pos.symbol, "direction": pos.direction, "lots": pos.lots,
        "pnl_usd": total, "reason": reason, "trail": pos.trail_active,
        "closed_ts": closed_ts,
    })
    return total


def float_pnl(pos: SimPos, mark: float) -> float:
    if pos.direction == "BUY":
        pnl_pips = (mark - pos.entry_price) / pos.pip_size
    else:
        pnl_pips = (pos.entry_price - mark) / pos.pip_size
    return pnl_pips * pos.lots * pos.pip_val


def manage_book(book: Book, by_ts: Dict[str, Dict[float, Tuple]], ts: float, chandelier_mult: float = 0.0,
                tp_mode: str = "tp"):
    still = []
    for pos in book.positions:
        bar = by_ts[pos.symbol].get(ts)
        if bar is None:
            still.append(pos)
            continue
        spec = forex.get_symbol_trading_specs(pos.symbol, base_be=BASE_BE_PIPS, base_trail=BASE_TRAIL_PIPS)
        eff_trail = spec["trail_pips"]
        min_be = 0.0
        if TUN_GOLD_VOL_EXITS and ("XAU" in pos.symbol.upper() or "GOLD" in pos.symbol.upper()) and pos.entry_atr_pips > 0:
            # Volatilite-adaptif (giriş ATR'ine göre, işlem başına sabit):
            # trailing mesafesi ve BE tetik tabanı o işlemin volatilitesine ölçeklenir.
            eff_trail = max(eff_trail, TUN_VOL_TRAIL_MULT * pos.entry_atr_pips)
            min_be = TUN_VOL_BE_MULT * pos.entry_atr_pips
        res = manage_position(pos, bar, eff_trail, spec["be_pips"], chandelier_mult, tp_mode, min_be)
        if res and res[0] in ("SL", "BE", "TP"):
            close_position(book, pos, res[0], res[1], closed_ts=ts)
        else:
            still.append(pos)
    book.positions = still


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
def run_replay(data: Dict[str, List[Tuple]], days: int, entry_start_ts: Optional[float] = None,
               entry_end_ts: Optional[float] = None, symbol_filter: Optional[set] = None,
               add_symbols: Optional[set] = None) -> Dict[str, Any]:
    # Ek metrikler: NEW defteri için bar-bazlı özkaynak örnekleme (maks. düşüş için)
    eq_ts: List[float] = []
    eq_new: List[float] = []
    last_close: Dict[str, float] = {}
    # Yalnızca canlı motorun izin listesindeki semboller (SPX500/XAGUSD/USOIL işlem yapmaz);
    # --add-symbols ile test adayları eklenebilir (canlı allowed_symbols'a dokunmaz)
    allowed = set(forex.ForexAutoPaperSettings().allowed_symbols)
    if symbol_filter:
        allowed &= {s.upper() for s in symbol_filter}
    if add_symbols:
        allowed |= {s.upper() for s in add_symbols}
    symbols = [s for s in data if s != "DXY" and s in allowed]
    by_ts = {s: {b[0]: b for b in data[s]} for s in symbols}
    # Birleşim zaman ekseni: her sembol kendi seansında bar üretir; kesişim örneklemi kısaltır
    all_ts = set()
    for s in symbols:
        all_ts.update(b[0] for b in data[s])
    common_ts = sorted(all_ts)
    span_days = (common_ts[-1] - common_ts[0]) / 86400.0 if common_ts else 0.0
    print(f"[REPLAY] {len(symbols)} sembol | {len(common_ts)} birleşik 5M bar | span ~{span_days:.1f} gün")
    warmup = INDICATOR_WINDOW

    books = {"OLD": Book("OLD"), "NEW": Book("NEW")}
    shadow_book: Dict[str, Dict[str, Any]] = {}
    corr = FXCorrelationMonitor()
    closes_cache: Dict[str, List[float]] = {}
    last_entry_bar: Dict[Tuple[str, str], int] = {}
    cursors: Dict[str, int] = {s: 0 for s in symbols}

    orig_dxy = forex._TECHNICAL_CACHE.get("DXY")
    dxy_list = data.get("DXY") or []

    # BTC EMA200(1h) rejim serisi: 5m barlar saatlik kapanışlara indirgenir, EMA200 saat
    # kapanışları üzerinden hesaplanır; 5m bar SAATİN İÇİNDEYKEN bir önceki TAMAMLANMIŞ
    # saatin EMA'sı kullanılır (look-ahead yok).
    btc_ema200_by_hour: Dict[int, float] = {}
    if TUN_BTC_EMA200 and "BTCUSD" in data:
        hourly: Dict[int, float] = {}
        for b in data["BTCUSD"]:
            hourly[int(b[0] // 3600)] = b[4]
        ema = None
        for hk in sorted(hourly):
            c_h = hourly[hk]
            ema = c_h if ema is None else ema + (2.0 / 201.0) * (c_h - ema)
            btc_ema200_by_hour[hk] = ema

    # BTC günlük VWAP: UTC günü başından itibaren kümülatif Σ(tp×v)/Σv (tp=(h+l+c)/3)
    btc_vwap_by_ts: Dict[float, float] = {}
    if TUN_BTC_VWAP and "BTCUSD" in data:
        vols = _load_btc_volume_map()
        cum_qv = cum_v = 0.0
        cur_day: Optional[int] = None
        for b in data["BTCUSD"]:
            day = int(b[0] // 86400)
            if day != cur_day:
                cur_day, cum_qv, cum_v = day, 0.0, 0.0
            tp = (b[2] + b[3] + b[4]) / 3.0
            v = float(vols.get(b[0], 0.0) or 0.0)
            cum_qv += tp * v
            cum_v += v
            if cum_v > 0:
                btc_vwap_by_ts[b[0]] = cum_qv / cum_v

    for idx, ts in enumerate(common_ts):
        # Pencere sonu: o haftanın kapanışıyla dur; kalan pozisyonlar aşağıda
        # pencere içi son fiyatla kapatılır (hafta-sonu ötesine taşmaz).
        if entry_end_ts is not None and ts >= entry_end_ts:
            break
        # Sembol imleçlerini ilerlet: bars[:cursor] bu adımda kullanılabilir veri
        fresh = {}
        for s in symbols:
            bars = data[s]
            ci = cursors[s]
            while ci < len(bars) and bars[ci][0] <= ts:
                ci += 1
            cursors[s] = ci
            if ci > 0:
                last_close[s] = bars[ci - 1][4]
            fresh[s] = ci > 0 and bars[ci - 1][0] == ts and ci >= 30

        if idx < warmup:
            continue
        hour = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).hour

        # DXY rejimi (yalnız NEW): test edilmiş get_dxy_regime'i yeniden kullanmak için
        # geçici olarak _TECHNICAL_CACHE["DXY"] set edilir.
        dxy_regime = None
        if dxy_list:
            dxy_i = _bar_index_at_or_before(dxy_list, ts)
            if dxy_i is not None and dxy_i >= 15:
                w = dxy_list[max(0, dxy_i - INDICATOR_WINDOW):dxy_i + 1]
                if len(w) >= 15:
                    forex._TECHNICAL_CACHE["DXY"] = forex._compute_technical_indicators(
                        [b[4] for b in w], [b[2] for b in w], [b[3] for b in w], [b[1] for b in w], "DXY")
                    dxy_regime = forex.get_dxy_regime()

        # 1) Açık pozisyonları yönet (her iki defter + gölge defterler)
        # Chandelier yalnız NEW ve gölge defterlerde; OLD tarihi sabit pip trail kullanır
        chand = TUN_CHANDLIER
        for book in books.values():
            manage_book(book, by_ts, ts, chandelier_mult=(chand if book.name == "NEW" else 0.0),
                        tp_mode=(TUN_TP_MODE if book.name == "NEW" else "tp"))
        for sh in shadow_book.values():
            manage_book(sh["book"], by_ts, ts, chandelier_mult=chand)

        # Özkaynak örnekleme (NEW): kapanmış kâr + açık pozisyonların işaret fiyatıyla floating PnL
        if idx >= warmup:
            eq_ts.append(ts)
            eq_new.append(books["NEW"].balance + sum(
                float_pnl(p, last_close.get(p.symbol, p.entry_price)) for p in books["NEW"].positions))

        # 2) Korelasyon matrisi (periyodik)
        if idx % CORR_REFRESH_EVERY == 0:
            for s in symbols:
                ci = cursors[s]
                closes_cache[s] = [b[4] for b in data[s][max(0, ci - 250):ci]]
            try:
                corr.maybe_refresh(closes_cache, interval_sec=0)
            except Exception:
                pass

        # 3) Aday üretimi + kapılar (her iki varyant) — yalnız taze barı ve işlem penceresi içinde
        in_window = (entry_start_ts is None or ts >= entry_start_ts) and (entry_end_ts is None or ts < entry_end_ts)
        candidates: Dict[str, List[Dict]] = {"OLD": [], "NEW": []}
        blocked_events: List[Tuple[str, Dict]] = []

        for sym in symbols:
            if not in_window or not fresh[sym]:
                continue
            bars = data[sym]
            ci = cursors[sym]
            window = bars[max(0, ci - INDICATOR_WINDOW):ci]
            if len(window) < 30:
                continue
            closes = [b[4] for b in window]
            highs = [b[2] for b in window]
            lows = [b[3] for b in window]
            opens = [b[1] for b in window]
            item = next((i for i in forex.FOREX_SYMBOLS if i["symbol"] == sym), None)
            item = item or REPLAY_SYMBOL_DEFS.get(sym)
            pip_size = item["pip_size"] if item else 0.0001
            spread_pips = CATEGORY_SPREAD_PIPS.get(item["category"] if item else "index", 3.0)
            is_commodity = ("XAU" in sym or "GOLD" in sym or "OIL" in sym)
            is_fx_major = sym in FX_MAJORS
            if sym == "BTCUSD" and TUN_BTC_MIN_SCORE > 0:
                base_req = TUN_BTC_MIN_SCORE
            elif is_commodity:
                base_req = 78.0
            elif is_fx_major and TUN_FX_MIN_SCORE > 0:
                base_req = TUN_FX_MIN_SCORE
            else:
                base_req = TUN_MIN_SCORE
            max_spread = 20.0 if ("BTC" in sym or "ETH" in sym) else 3.0
            close_now = closes[-1]

            for vname in ("OLD", "NEW"):
                book = books[vname]
                tech = forex._compute_technical_indicators(closes, highs, lows, opens, sym,
                                                           include_momentum=(vname == "NEW"))
                if not tech:
                    continue
                action = tech.get("action")
                if action not in ("BUY", "SELL"):
                    continue
                score = float(tech["score"])
                atr_pips = tech["atr"] / pip_size if pip_size > 0 else 15.0
                spec = forex.get_symbol_trading_specs(sym, atr_pips=atr_pips)

                def cand(gate_note: Optional[str] = None) -> Dict:
                    return {
                        "symbol": sym, "action": action, "score": score, "price": close_now,
                        "atr_pips": atr_pips, "pip_size": pip_size, "pip_val": spec["pip_val"],
                        "digits": spec["digits"], "spread_pips": spread_pips, "gate": gate_note,
                    }

                # ---- Kapı zinciri (NEW: yeni kapılar da devrede; OLD: yalnız ortak kapılar) ----
                if vname == "NEW" and EV_GUARD:
                    ev_rows = [c["pnl_usd"] for c in book.closed
                               if c["symbol"] == sym and c.get("closed_ts", 0.0) >= ts - EV_WINDOW_SEC]
                    ev_stats = {
                        "n": len(ev_rows),
                        "net": round(sum(ev_rows), 2),
                        "win_rate": round(100.0 * sum(1 for p in ev_rows if p >= 0) / len(ev_rows), 1) if ev_rows else 0.0,
                    }
                    ev_risk_floor = BALANCE * RISK_PCT / 100.0 * EV_LOSS_RISK_MULT
                    if forex.ev_guard_decision(ev_stats, EV_MIN_TRADES, EV_MAX_WIN_RATE, ev_risk_floor):
                        blocked_events.append(("EV", cand("EV")))
                        continue
                if vname == "NEW" and BLOCKED_HOURS and forex.is_entry_hour_blocked(hour, BLOCKED_HOURS):
                    blocked_events.append(("SAAT", cand("SAAT")))
                    continue
                if vname == "NEW":
                    veto = forex.dxy_entry_veto(sym, action, dxy_regime)
                    if veto == "dxy_conflict":
                        if TUN_GOLD_DXY_SOFT and ("XAU" in sym or "GOLD" in sym):
                            # XAUUSD: sert veto yerine ekstra skor eşiği (kategori bazlı yumuşatma)
                            weak_bump = TUN_GOLD_DXY_BUMP
                        else:
                            blocked_events.append(("DXY", cand("DXY")))
                            continue
                    else:
                        weak_bump = 5.0 if veto == "dxy_strict_neutral" else 0.0
                else:
                    weak_bump = 0.0
                # 5c. Majör güçlendirme kapıları (2026-10-06 araştırma mekanizmaları, yalnız NEW):
                # Asya seansı chop'u, ölü piyasa ve kovalama (EMA21 uzaması) girişleri eler.
                # --gate-extras ile eklenen adaylar, --gold-session ile altın da kapsanır.
                _gate_syms = sym in FX_MAJORS or sym in GATED_EXTRAS or (TUN_GOLD_SESSION and ("XAU" in sym or "GOLD" in sym))
                if vname == "NEW" and _gate_syms:
                    if TUN_MAJOR_HOURS and not (TUN_MAJOR_HOURS[0] <= hour < TUN_MAJOR_HOURS[1]):
                        blocked_events.append(("SEANS", cand("SEANS")))
                        continue
                    if TUN_MAJOR_MIN_ATR > 0 and atr_pips < TUN_MAJOR_MIN_ATR:
                        blocked_events.append(("VOLATİLİTE", cand("VOLATİLİTE")))
                        continue
                    if TUN_MAJOR_MAX_EXT > 0 and float(tech.get("ema21", 0.0)) > 0 and atr_pips > 0:
                        ext_atr = ((close_now - float(tech["ema21"])) if action == "BUY"
                                   else (float(tech["ema21"]) - close_now)) / (atr_pips * pip_size)
                        if ext_atr > TUN_MAJOR_MAX_EXT:
                            blocked_events.append(("UZAMA", cand("UZAMA")))
                            continue
                # 5d. BTC rejim kapıları (yalnız NEW): yapısal EMA200(1h) ve günlük VWAP yön hizası
                if vname == "NEW" and sym == "BTCUSD":
                    if TUN_BTC_EMA200:
                        ema_val = btc_ema200_by_hour.get(int(ts // 3600) - 1)
                        if ema_val is not None and ((action == "BUY" and close_now <= ema_val) or (action == "SELL" and close_now >= ema_val)):
                            blocked_events.append(("REJIM", cand("REJIM")))
                            continue
                    if TUN_BTC_VWAP:
                        vw = btc_vwap_by_ts.get(ts)
                        if vw is not None and ((action == "BUY" and close_now <= vw) or (action == "SELL" and close_now >= vw)):
                            blocked_events.append(("VWAP", cand("VWAP")))
                            continue
                if spread_pips > max_spread:
                    continue  # ortak kapı — gölge izlenmez
                req = base_req + weak_bump
                if score < req:
                    continue  # SKOR — sinyal taban eşiği, gölge izlenmez
                if vname == "NEW" and TUN_ADX_MIN > 0 and float(tech.get("adx", 25.0)) < TUN_ADX_MIN:
                    blocked_events.append(("ADX", cand("ADX")))
                    continue
                if vname == "NEW" and TUN_ST_FILTER:
                    st_dir = int(tech.get("supertrend_dir", 0))
                    if st_dir != 0 and ((action == "BUY" and st_dir < 0) or (action == "SELL" and st_dir > 0)):
                        blocked_events.append(("SUPERTREND", cand("SUPERTREND")))
                        continue
                bias = forex.get_usd_bias(sym, action)
                if vname == "NEW" and bias != "USD_NEUTRAL":
                    pos_biases = [(p.symbol, forex.get_usd_bias(p.symbol, p.direction)) for p in book.positions]
                    ok, _r = corr.cluster_check(sym, bias, pos_biases)
                    if not ok:
                        blocked_events.append(("KORELASYON", cand("KORELASYON")))
                        continue
                same_dir = [p for p in book.positions if p.symbol == sym and p.direction == action]
                if len(same_dir) >= MAX_PER_SYMBOL_DIR:
                    continue
                if same_dir:
                    dir_pnl = sum(p.partial_realized_usd + float_pnl(p, close_now) for p in same_dir)
                    if dir_pnl < PYRAMID_MIN_PROFIT_USD:
                        continue
                if (sym, action) in last_entry_bar and idx - last_entry_bar[(sym, action)] < 1:
                    continue
                candidates[vname].append(cand())

        # 4) Skor sırasına göre açılış (eski USD-yön sayacı kaldırıldı — korelasyon kalkanı koruyor)
        for vname, book in books.items():
            opened = 0
            for cand_d in sorted(candidates[vname], key=lambda x: -x["score"]):
                if len(book.positions) >= MAX_OPEN_POSITIONS or opened >= TRADES_PER_BAR_CAP:
                    break
                spec = forex.get_symbol_trading_specs(cand_d["symbol"], atr_pips=cand_d["atr_pips"])
                if vname == "NEW":
                    sl_mult_eff = TUN_SL_ATR_MULT
                    if TUN_CRYPTO_SL_MULT > 0 and ("BTC" in cand_d["symbol"] or "ETH" in cand_d["symbol"]):
                        sl_mult_eff = TUN_CRYPTO_SL_MULT
                    levels = forex.get_atr_exit_levels(
                        cand_d["atr_pips"], spec["sl_pips"], spec["tp_pips"],
                        sl_atr_mult=sl_mult_eff, tp_atr_mult=TUN_TP_ATR_MULT, rr_floor=TUN_RR_FLOOR)
                    sl_pips, tp_pips = levels["sl_pips"], levels["tp_pips"]
                    partial = levels["first_target_pips"]
                else:
                    sl_pips, tp_pips, partial = spec["sl_pips"], spec["tp_pips"], 0.0
                pos = open_position(cand_d, sl_pips, tp_pips, partial, idx)
                if pos is None:
                    continue  # Risk kalkanı: en küçük mümkün lot bile sert risk sınırını aşıyor
                book.positions.append(pos)
                last_entry_bar[(cand_d["symbol"], cand_d["action"])] = idx
                opened += 1

        # 5) Gölge defterler: NEW'in yeni kapılarının reddettikleri (cap'li)
        for gate, cand_d in blocked_events:
            if gate not in SHADOW_GATES:
                continue
            sh = shadow_book.setdefault(gate, {"book": Book(f"SHADOW-{gate}"), "blocked": 0})
            sh["blocked"] += 1
            if len(sh["book"].positions) >= SHADOW_MAX_CONCURRENT:
                continue
            spec = forex.get_symbol_trading_specs(cand_d["symbol"], atr_pips=cand_d["atr_pips"])
            levels = forex.get_atr_exit_levels(
                cand_d["atr_pips"], spec["sl_pips"], spec["tp_pips"],
                sl_atr_mult=TUN_SL_ATR_MULT, tp_atr_mult=TUN_TP_ATR_MULT, rr_floor=TUN_RR_FLOOR)
            spos = open_position(cand_d, levels["sl_pips"], levels["tp_pips"], levels["first_target_pips"], idx)
            if spos is not None:
                sh["book"].positions.append(spos)

        if idx % 300 == 0:
            print(f"  ... bar {idx}/{len(common_ts)} | OLD: {len(books['OLD'].closed)} işlem ${books['OLD'].balance:+.2f} | "
                  f"NEW: {len(books['NEW'].closed)} işlem ${books['NEW'].balance:+.2f}")

    # 6) Kalan pozisyonları kapat — pencere tanımlıysa pencere içi son bar fiyatıyla
    for book in list(books.values()) + [sh["book"] for sh in shadow_book.values()]:
        for pos in list(book.positions):
            bars_sym = data[pos.symbol]
            last_bar = bars_sym[-1]
            if entry_end_ts is not None:
                for b in reversed(bars_sym):
                    if b[0] < entry_end_ts:
                        last_bar = b
                        break
            reason = "EOM" if entry_end_ts is None else "HAFTA_KAPANIS"
            close_position(book, pos, reason, last_bar[4], closed_ts=last_bar[0])
        book.positions = []

    if orig_dxy is not None:
        forex._TECHNICAL_CACHE["DXY"] = orig_dxy
    else:
        forex._TECHNICAL_CACHE.pop("DXY", None)

    report: Dict[str, Any] = {"days": days, "bars": len(common_ts), "variants": {}, "gate_attribution": {}}
    if entry_start_ts or entry_end_ts:
        report["entry_window"] = {
            "start_ts": entry_start_ts,
            "end_ts": entry_end_ts,
            "start": datetime.datetime.fromtimestamp(entry_start_ts, datetime.timezone.utc).isoformat() if entry_start_ts else None,
            "end": datetime.datetime.fromtimestamp(entry_end_ts, datetime.timezone.utc).isoformat() if entry_end_ts else None,
        }
    for vname, book in books.items():
        wins = sum(1 for t in book.closed if t["pnl_usd"] >= 0)
        n = len(book.closed)
        daily: Dict[str, float] = {}
        for t in book.closed:
            if not t.get("closed_ts"):
                continue
            d = datetime.datetime.fromtimestamp(t["closed_ts"], datetime.timezone.utc).strftime("%Y-%m-%d")
            daily[d] = round(daily.get(d, 0.0) + t["pnl_usd"], 2)
        var = {
            "trades": n,
            "win_rate": round(100 * wins / n, 1) if n else 0.0,
            "net_pnl_usd": round(book.realized, 2),
            "avg_pnl_usd": round(book.realized / n, 3) if n else 0.0,
            "balance": book.balance,
            "per_symbol": book.per_symbol,
            "daily_pnl": dict(sorted(daily.items())),
        }
        by_reason: Dict[str, Dict[str, float]] = {}
        for t in book.closed:
            r = "TRAIL" if t.get("trail") else str(t["reason"])
            st_r = by_reason.setdefault(r, {"n": 0, "pnl_usd": 0.0})
            st_r["n"] = int(st_r["n"]) + 1
            st_r["pnl_usd"] = round(st_r["pnl_usd"] + t["pnl_usd"], 2)
        var["exit_reasons"] = by_reason
        if vname == "NEW" and eq_new:
            peak = eq_new[0]
            max_dd = 0.0
            for e in eq_new:
                peak = max(peak, e)
                max_dd = max(max_dd, peak - e)
            var["max_drawdown_usd"] = round(max_dd, 2)
            var["equity_start"] = round(eq_new[0], 2)
            var["equity_end"] = round(eq_new[-1], 2)
        report["variants"][vname] = var
    for gate, sh in shadow_book.items():
        n = len(sh["book"].closed)
        pnl = round(sum(c["pnl_usd"] for c in sh["book"].closed), 2)
        wins = sum(1 for c in sh["book"].closed if c["pnl_usd"] >= 0)
        report["gate_attribution"][gate] = {
            "blocked": sh["blocked"],
            "shadow_trades": n,
            "shadow_win_rate": round(100 * wins / n, 1) if n else 0.0,
            "shadow_pnl_usd": pnl,
        }
    return report


def fetch_btc_volume_map(days: int = 32) -> Dict[float, float]:
    """Yahoo BTC-USD 5m hacim serisi (ts -> volume) — VWAP kapısı için; disk önbellekli."""
    cache = os.path.join(ROOT, "outputs", f"btc_volume_{days}d.json")
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return {float(k): float(v) for k, v in json.load(f).items()}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?interval=5m&range={days}d"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    res = d["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    ts = res.get("timestamp", [])
    vol = q.get("volume", [])
    out = {float(ts[i]): float(vol[i]) for i in range(min(len(ts), len(vol))) if vol[i] is not None}
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return out


def _load_btc_volume_map() -> Dict[float, float]:
    try:
        return fetch_btc_volume_map(32)
    except Exception as exc:
        print(f"[UYARI] BTC hacim verisi alınamadı — VWAP kapısı etksiz: {exc}")
        return {}


def _bar_index_at_or_before(bars: List[Tuple], ts: float) -> Optional[int]:
    lo, hi = 0, len(bars) - 1
    if not bars or bars[0][0] > ts:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if bars[mid][0] <= ts:
            lo = mid
        else:
            hi = mid - 1
    return lo


def main():
    global TUN_MIN_SCORE, TUN_SL_ATR_MULT, TUN_TP_ATR_MULT, TUN_RR_FLOOR, TUN_HEADROOM_FOREX
    global TUN_ADX_MIN, TUN_ST_FILTER, BLOCKED_HOURS, EV_GUARD
    global TUN_FX_MIN_SCORE, TUN_GOLD_DXY_SOFT, TUN_GOLD_DXY_BUMP, EV_WINDOW_SEC, EV_MAX_WIN_RATE
    global TUN_CHANDLIER, TUN_MAJOR_HOURS, TUN_MAJOR_MIN_ATR, TUN_MAJOR_MAX_EXT, GATED_EXTRAS
    global TUN_GOLD_SESSION, TUN_BTC_EMA200, TUN_BTC_VWAP, TUN_CRYPTO_SL_MULT, TUN_BTC_MIN_SCORE, TUN_TP_MODE
    global TUN_GOLD_VOL_EXITS, TUN_VOL_BE_MULT, TUN_VOL_TRAIL_MULT
    parser = argparse.ArgumentParser(description="Forex replay A/B (eski vs yeni algoritma)")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--cache", default="")
    parser.add_argument("--out", default=os.path.join(ROOT, "outputs", "forex_replay_7d_report.json"))
    parser.add_argument("--window", choices=["full", "recent", "prior"], default="full",
                        help="recent: son 7 gün (in-sample) | prior: önceki 7 gün (out-of-sample)")
    parser.add_argument("--start", default="", help="Giriş penceresi başlangıcı (YYYY-MM-DD, UTC) — window'u geçersiz kılar")
    parser.add_argument("--end", default="", help="Giriş penceresi sonu, dahil değil (YYYY-MM-DD, UTC)")
    parser.add_argument("--symbols", default="", help="Virgüllü sembol filtresi (örn: XAUUSD,US30,NAS100) — yalnız bu semboller işlenir")
    parser.add_argument("--add-symbols", default="", help="Virgüllü ek aday semboller (örn: XAGUSD,USOIL,GBPJPY) — izin listesine EKLENİR (test-only)")
    parser.add_argument("--gate-extras", default="", help="Virgüllü: --add-symbols ile eklenen sembollerden majör kapılarına (seans+minATR) tabi tutulacaklar")
    parser.add_argument("--min-score", type=float, default=75.0)
    parser.add_argument("--sl-mult", type=float, default=1.1)
    parser.add_argument("--tp-mult", type=float, default=1.4)
    parser.add_argument("--rr-floor", type=float, default=1.5)
    parser.add_argument("--headroom", type=float, default=3.5)
    parser.add_argument("--adx-min", type=float, default=0.0, help="ADX eşiği (0 = kapalı)")
    parser.add_argument("--st-filter", action="store_true", help="SuperTrend yön teyidini aç")
    parser.add_argument("--hours", default="", help="Engellenecek UTC saatleri, virgüllü (örn 5,15)")
    parser.add_argument("--no-ev-guard", action="store_true", help="Sembol EV kalkanını kapat")
    parser.add_argument("--fx-min-score", type=float, default=0.0, help="FX majörleri için ayrı skor eşiği (0 = min_score ile aynı)")
    parser.add_argument("--gold-dxy-soft", action="store_true", help="(Eski) XAUUSD DXY vetosunu +skora indirmek için — canlıda artık XAUUSD tamamen muaf, etki etmez")
    parser.add_argument("--gold-dxy-bump", type=float, default=5.0, help="XAUUSD DXY yumuşatma ekstra skoru")
    parser.add_argument("--ev-window", type=float, default=24.0, help="EV kalkanı bakış penceresi (saat)")
    parser.add_argument("--ev-wr", type=float, default=45.0, help="EV kronik kayıp WR eşiği (%%) — canlı default 45")
    parser.add_argument("--st-period", type=int, default=10, help="SuperTrend period (canlı default 10)")
    parser.add_argument("--st-mult", type=float, default=3.0, help="SuperTrend ATR çarpanı (canlı default 3.0)")
    parser.add_argument("--gold-session", action="store_true", help="Altın için de majör seans penceresini uygula (7-20 UTC)")
    parser.add_argument("--btc-ema200", action="store_true", help="BTC girişlerine EMA200(1h) rejim kapısı")
    parser.add_argument("--btc-vwap", action="store_true", help="BTC girişlerine günlük VWAP kapısı (hacim verisi çeker)")
    parser.add_argument("--crypto-sl-mult", type=float, default=0.0, help="Kripto özel SL ATR çarpanı (0 = global)")
    parser.add_argument("--btc-min-score", type=float, default=0.0, help="BTC özel skor eşiği (0 = global min_score)")
    parser.add_argument("--no-tp-on-trail", action="store_true", help="Trailing aktiflenince sabit TP emri çekilir — muhafazakâr model (aktifleşen barda TP geçerli)")
    parser.add_argument("--no-tp-on-trail-live", action="store_true", help="Trailing aktiflenince TP çekilir — canlıya yakın model (aktifleşen barda da geçersiz; MODIFY_SLTP saniyeler içinde etkili olur)")
    parser.add_argument("--no-tp-crypto", action="store_true", help="TP yalnız BTC/ETH'de kapalı")
    parser.add_argument("--no-tp", action="store_true", help="Sabit TP tamamen kapalı (aşırı uç kontrolü)")
    parser.add_argument("--gold-vol-exits", action="store_true", help="Altında BE tetiği ve trailing mesafesi giriş-ATR'ine göre ölçeklenir")
    parser.add_argument("--vol-be-mult", type=float, default=0.8, help="BE tetik tabanı çarpanı (× giriş-ATR, pip)")
    parser.add_argument("--vol-trail-mult", type=float, default=1.5, help="Trailing mesafe çarpanı (× giriş-ATR, pip)")
    parser.add_argument("--chandelier", type=float, default=0.0, help="MFE−ATR chandelier trailing çarpanı (0 = sabit pip trail; scalping için ~2.0)")
    parser.add_argument("--major-hours", default="7-20", help="Majörler için UTC saat penceresi '7-20' (canlı default 7-20; boş = kapalı)")
    parser.add_argument("--major-min-atr", type=float, default=4.0, help="Majörler minimum ATR(pips) tabanı (canlı default 4.0; 0 = kapalı)")
    parser.add_argument("--major-max-ext", type=float, default=0.0, help="Majörlerde EMA21'den maks. ATR-katı uzama — kovalamama (0 = kapalı)")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    TUN_MIN_SCORE = args.min_score
    TUN_SL_ATR_MULT = args.sl_mult
    TUN_TP_ATR_MULT = args.tp_mult
    TUN_RR_FLOOR = args.rr_floor
    TUN_HEADROOM_FOREX = args.headroom
    TUN_ADX_MIN = args.adx_min
    TUN_ST_FILTER = args.st_filter
    EV_GUARD = not args.no_ev_guard
    TUN_FX_MIN_SCORE = args.fx_min_score
    TUN_GOLD_DXY_SOFT = args.gold_dxy_soft
    TUN_GOLD_DXY_BUMP = args.gold_dxy_bump
    EV_WINDOW_SEC = args.ev_window * 3600.0
    EV_MAX_WIN_RATE = args.ev_wr
    TUN_CHANDLIER = args.chandelier
    if args.major_hours:
        parts = args.major_hours.split("-")
        TUN_MAJOR_HOURS = (int(parts[0]), int(parts[1]))
    TUN_MAJOR_MIN_ATR = args.major_min_atr
    TUN_MAJOR_MAX_EXT = args.major_max_ext
    GATED_EXTRAS = {s.strip().upper() for s in args.gate_extras.split(",") if s.strip()}
    TUN_GOLD_SESSION = args.gold_session
    TUN_BTC_EMA200 = args.btc_ema200
    TUN_BTC_VWAP = args.btc_vwap
    TUN_CRYPTO_SL_MULT = args.crypto_sl_mult
    TUN_BTC_MIN_SCORE = args.btc_min_score
    if args.no_tp:
        TUN_TP_MODE = "no_tp"
    elif args.no_tp_crypto:
        TUN_TP_MODE = "no_tp_crypto"
    elif args.no_tp_on_trail_live:
        TUN_TP_MODE = "no_tp_on_trail_live"
    elif args.no_tp_on_trail:
        TUN_TP_MODE = "no_tp_on_trail"
    TUN_GOLD_VOL_EXITS = args.gold_vol_exits
    TUN_VOL_BE_MULT = args.vol_be_mult
    TUN_VOL_TRAIL_MULT = args.vol_trail_mult
    # SuperTrend parametre denemesi: canlı fonksiyonu parametreyle sarmala (canlı kod değişmez)
    if (args.st_period, args.st_mult) != (10, 3.0):
        _orig_st = forex._compute_supertrend
        def _st_patched(h, l, c, period=10, mult=3.0, _o=_orig_st, _p=args.st_period, _m=args.st_mult):
            return _o(h, l, c, _p, _m)
        forex._compute_supertrend = _st_patched
    BLOCKED_HOURS = [int(h) for h in args.hours.split(",") if h.strip().isdigit()]
    cfg_str = (f"{args.tag} | min_score={TUN_MIN_SCORE} sl_mult={TUN_SL_ATR_MULT} tp_mult={TUN_TP_ATR_MULT} "
               f"rr_floor={TUN_RR_FLOOR} headroom={TUN_HEADROOM_FOREX} adx_min={TUN_ADX_MIN} st={TUN_ST_FILTER} "
               f"ev_guard={EV_GUARD} ev_win={args.ev_window}h ev_wr={args.ev_wr} fx_min_score={TUN_FX_MIN_SCORE or '-'} "
               f"goldDXYsoft={TUN_GOLD_DXY_SOFT}(+{TUN_GOLD_DXY_BUMP}) chandelier={TUN_CHANDLIER or '-'} "
               f"stP={args.st_period} stM={args.st_mult} goldSession={TUN_GOLD_SESSION} btcEMA200={TUN_BTC_EMA200} "
               f"btcVWAP={TUN_BTC_VWAP} cryptoSL={TUN_CRYPTO_SL_MULT or '-'} btcScore={TUN_BTC_MIN_SCORE or '-'} "
               f"majorHours={args.major_hours or '-'} majorMinAtr={TUN_MAJOR_MIN_ATR or '-'} majorMaxExt={TUN_MAJOR_MAX_EXT or '-'} "
               f"tpMode={TUN_TP_MODE} goldVol={TUN_GOLD_VOL_EXITS}(be={TUN_VOL_BE_MULT} trail={TUN_VOL_TRAIL_MULT}) "
               f"hours={BLOCKED_HOURS or 'kapalı'} window={args.window} pencere={args.start or '-'}→{args.end or '-'}")
    if args.tag:
        print(f"[KONFIG] {cfg_str}")

    cache_path = args.cache or os.path.join(ROOT, "outputs", f"forex_replay_data_{args.days}d.json")
    if os.path.exists(cache_path):
        print(f"[VERI] Önbellekten yükleniyor: {cache_path}")
        with open(cache_path, encoding="utf-8") as f:
            raw = json.load(f)
        data = {sym: [tuple(b) for b in bars] for sym, bars in raw.items()}
    else:
        print(f"[VERI] Yahoo Finance'ten {args.days} gün 5M mum çekiliyor...")
        data = fetch_all(args.days)
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({sym: [list(b) for b in bars] for sym, bars in data.items()}, f)
        print(f"[VERI] Önbelleğe yazıldı: {cache_path} ({len(data)} sembol)")

    entry_start_ts = None
    entry_end_ts = None
    if args.start:
        entry_start_ts = datetime.datetime.strptime(args.start, "%Y-%m-%d").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    if args.end:
        entry_end_ts = datetime.datetime.strptime(args.end, "%Y-%m-%d").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    elif args.window in ("recent", "prior"):
        all_last = max(bars[-1][0] for bars in data.values())
        split_ts = all_last - 7 * 86400
        if args.window == "recent":
            entry_start_ts = split_ts
        else:
            entry_end_ts = split_ts

    t0 = time.time()
    sym_filter = {s.strip().upper() for s in args.symbols.split(",") if s.strip()} or None
    add_syms = {s.strip().upper() for s in getattr(args, "add_symbols", "").split(",") if s.strip()} or None
    report = run_replay(data, args.days, entry_start_ts=entry_start_ts, entry_end_ts=entry_end_ts,
                        symbol_filter=sym_filter, add_symbols=add_syms)
    report["config"] = cfg_str
    print(f"\n[REPLAY BİTTİ] {time.time() - t0:.1f} sn")

    print("\n" + "=" * 76)
    print(f"{'VARYANT':8s} {'İŞLEM':>6s} {'KAZANMA':>8s} {'NET PnL':>10s} {'İŞLEM BAŞINA':>13s}")
    print("-" * 76)
    for vname, v in report["variants"].items():
        print(f"{vname:8s} {v['trades']:>6d} {v['win_rate']:>7.1f}% {v['net_pnl_usd']:>+10.2f} {v['avg_pnl_usd']:>+13.3f}")
    print("-" * 76)
    new_v = report["variants"]["NEW"]
    if new_v.get("max_drawdown_usd") is not None:
        print(f"NEW Özkaynak: ${new_v['equity_start']:.2f} → ${new_v['equity_end']:.2f} | Maks. Düşüş: ${new_v['max_drawdown_usd']:.2f}")
    if new_v.get("daily_pnl"):
        print("\nGÜNLÜK PnL (NEW):")
        for d, pnl in new_v["daily_pnl"].items():
            bar = "+" * max(0, int(pnl / 2)) + "-" * max(0, int(-pnl / 2))
            print(f"  {d}  ${pnl:>+9.2f}  {bar}")
    print("\nKAPI KATKI ANALİZİ (NEW'in engellediklerinin gölge defter sonuçları):")
    print(f"{'KAPI':12s} {'ENGEL':>6s} {'GÖLGE İŞLEM':>11s} {'GÖLGE WR':>9s} {'GÖLGE PnL':>10s}  YORUM")
    print("-" * 76)
    for gate, g in report["gate_attribution"].items():
        verdict = "✓ doğru eledi" if g["shadow_pnl_usd"] < 0 else "✗ kâr kesiyor — eşik gevşetilmeli"
        print(f"{gate:12s} {g['blocked']:>6d} {g['shadow_trades']:>11d} {g['shadow_win_rate']:>8.1f}% {g['shadow_pnl_usd']:>+10.2f}  {verdict}")

    print("\nSembol bazlı NEW:")
    for sym, st in sorted(report["variants"]["NEW"]["per_symbol"].items(), key=lambda kv: kv[1]["pnl"]):
        print(f"  {sym:9s} n:{int(st['n']):>3d} win%:{100 * st['wins'] / max(1, st['n']):5.1f} pnl:${st['pnl']:+8.2f}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[RAPOR] {args.out}")


if __name__ == "__main__":
    main()
