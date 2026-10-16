#!/usr/bin/env python3
"""
24 Saatlik Forex & Kripto & Endeks Replay Backtest:
Mevcut Sistem (Baseline) vs Yeni Karar Destek Sistemi (DSS Confluence & A+ Tier)

Başlangıç Bakiyesi: 1.000$
İşlem Başına Risk: Bakiyenin %10'u (100$ Bütçe)
Test Süresi: Son 24 Saat (5 Dakikalık Barlar)
"""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.app.routers import forex

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
STARTING_BALANCE = 1000.0
RISK_PCT = 0.10  # Bakiyenin %10'u ile işlem açma
MAX_CONCURRENT_POSITIONS = 5

ALL_SYMBOLS_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
    "NZDUSD": "NZDUSD=X",
    "XAUUSD": "GC=F",
    "BTCUSD": "BTC-USD",
    "US30": "^DJI",
    "NAS100": "^NDX",
    "EURGBP": "EURGBP=X",
    "EURJPY": "EURJPY=X",
    "GBPJPY": "GBPJPY=X",
    "AUDCAD": "AUDCAD=X",
    "CADJPY": "CADJPY=X",
    "CHFJPY": "CHFJPY=X",
    "AUDJPY": "AUDJPY=X",
    "NZDJPY": "NZDJPY=X",
    "EURCHF": "EURCHF=X",
    "EURCAD": "EURCAD=X",
    "EURAUD": "EURAUD=X",
    "EURNZD": "EURNZD=X",
    "GBPCHF": "GBPCHF=X",
    "GBPAUD": "GBPAUD=X",
    "GBPCAD": "GBPCAD=X",
    "GBPNZD": "GBPNZD=X",
    "AUDNZD": "AUDNZD=X",
    "AUDCHF": "AUDCHF=X",
    "NZDCAD": "NZDCAD=X",
    "CADCHF": "CADCHF=X",
}


@dataclass
class Position:
    id: str
    symbol: str
    direction: str  # BUY / SELL
    lots: float
    entry_price: float
    sl_price: float
    tp_price: float
    entry_time: float
    pip_size: float
    pip_val: float
    digits: int
    entry_atr: float
    sl0_pips: float
    tp0_pips: float
    be_locked: bool = False
    trail_active: bool = False
    mfe_pips: float = 0.0
    tier: str = "CLASSIC"


@dataclass
class Account:
    name: str
    balance: float = STARTING_BALANCE
    equity: float = STARTING_BALANCE
    realized_pnl: float = 0.0
    positions: List[Position] = field(default_factory=list)
    closed_trades: List[Dict[str, Any]] = field(default_factory=list)
    peak_balance: float = STARTING_BALANCE
    max_drawdown_usd: float = 0.0
    max_drawdown_pct: float = 0.0
    blocked_trades_count: int = 0
    blocked_reasons: Dict[str, int] = field(default_factory=dict)
    streak_losses: Dict[str, int] = field(default_factory=dict)
    cooldown_until: Dict[str, float] = field(default_factory=dict)
    cooldown_blocks_count: int = 0


def get_risk_pct_for_symbol(sym: str) -> float:
    """FX %15, XAUUSD %5, BTCUSD/US30/USTEC %2 risk bütçesi."""
    sym_u = str(sym).upper()
    if any(k in sym_u for k in ("BTC", "US30", "NAS100", "USTEC")):
        return 0.02  # %2 risk ($20 başlangıç)
    elif any(k in sym_u for k in ("XAU", "GOLD")):
        return 0.05  # %5 risk ($50 başlangıç)
    return 0.15      # Forex Pariteleri için %15 risk ($150 başlangıç)


def calculate_lots(balance: float, sl_pips: float, pip_val: float, spec: Dict[str, Any], sym: str) -> float:
    """FX için %10, BTC/US30/USTEC/XAU için %3 risk ile dinamik lot hesabı."""
    risk_pct = get_risk_pct_for_symbol(sym)
    risk_usd = balance * risk_pct
    if sl_pips <= 0 or pip_val <= 0:
        return spec.get("min_lot", 0.01)
    
    raw_lots = risk_usd / (sl_pips * pip_val)
    min_lot = spec.get("min_lot", 0.01)
    max_lot = min(spec.get("max_lot", 10.0), 10.0)  # Broker koruma tavanı
    lots = round(max(min_lot, min(max_lot, raw_lots)), 2)
    return lots


def fetch_symbol_bars(sym: str, yf_sym: str, days: int = 7) -> Optional[List[Tuple[float, float, float, float, float]]]:
    """Fetch 5m bars for symbol from Yahoo Finance or fallback to cached json."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_sym}?interval=5m&range={min(7, max(1, days))}d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            res = data["chart"]["result"][0]
            quote = res["indicators"]["quote"][0]
            ts = res.get("timestamp", [])
            o, h, l, c = quote.get("open", []), quote.get("high", []), quote.get("low", []), quote.get("close", [])
            bars = []
            for i in range(min(len(ts), len(c))):
                if None in (o[i], h[i], l[i], c[i]):
                    continue
                bars.append((float(ts[i]), float(o[i]), float(h[i]), float(l[i]), float(c[i])))
            if len(bars) >= 100:
                return bars
    except Exception:
        pass
    return None


def load_all_bars(days: int = 7) -> Dict[str, List[Tuple[float, float, float, float, float]]]:
    """Load fresh 5m bars for all symbols, falling back to cache if needed."""
    print(f"⏳ [1/4] Canlı piyasa verileri çekiliyor (Son {days} Gün 5M Barlar)...")
    data: Dict[str, List[Tuple[float, float, float, float, float]]] = {}
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_symbol_bars, s, yf, days): s for s, yf in ALL_SYMBOLS_MAP.items()}
        for fut in concurrent.futures.as_completed(futs, timeout=60):
            sym = futs[fut]
            try:
                res = fut.result()
                if res:
                    data[sym] = res
            except Exception:
                pass

    # Check if we need cache fallback
    cache_path = os.path.join(ROOT, "outputs", "forex_replay_31_m5.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            min_needed = min(1500, days * 200)
            for sym, cbars in cached.items():
                if sym not in data or len(data[sym]) < min_needed:
                    data[sym] = [tuple(b) for b in cbars]
        except Exception as e:
            print(f"⚠️ Cache fallback hatası: {e}")

    print(f"✅ Toplam {len(data)} sembol için veri hazırlandı.")
    return data


def run_replay(days: int = 7, target_symbols: Optional[List[str]] = None):
    t_start_wall = time.time()
    data = load_all_bars(days=days)
    if not data:
        print("❌ HATA: Test verisi bulunamadı!")
        return

    target_syms_set = None
    if target_symbols:
        target_syms_set = set()
        for s in target_symbols:
            su = s.strip().upper()
            if su in ("USTEC", "NDX", "NASDAQ"):
                target_syms_set.add("NAS100")
            else:
                target_syms_set.add(su)

    # Find the common window
    all_ts = set()
    for sym, bars in data.items():
        all_ts.update(b[0] for b in bars)
    sorted_ts = sorted(list(all_ts))
    
    bars_needed = days * 288
    if len(sorted_ts) > bars_needed:
        replay_ts = sorted_ts[-bars_needed:]
    else:
        replay_ts = sorted_ts
        
    start_dt = datetime.datetime.fromtimestamp(replay_ts[0], datetime.timezone.utc)
    end_dt = datetime.datetime.fromtimestamp(replay_ts[-1], datetime.timezone.utc)
    sym_disp = ", ".join(sorted(target_syms_set)) if target_syms_set else "TÜM 31 SEMBOL"
    print(f"\n📅 [2/4] Replay Zaman Aralığı: {start_dt.strftime('%Y-%m-%d %H:%M')} -> {end_dt.strftime('%Y-%m-%d %H:%M')} UTC ({days} Gün)")
    print(f"🎯 Hedef Semboller: {sym_disp}")
    print(f"💰 Başlangıç Bakiyesi: ${STARTING_BALANCE:,.2f} | FX: %15, XAU: %5, BTC/US30/USTEC: %2 Risk | 15 Dk Soğuma")

    # Systems to test
    acc_baseline = Account(name="Mevcut Sistem (Baseline / Klasik)")
    acc_dss = Account(name="Yeni Karar Destek Sistemi (DSS & A+ Confluence)")

    # Index by symbol for fast time slicing
    by_ts: Dict[str, Dict[float, Tuple[float, float, float, float, float]]] = {}
    for s, bars in data.items():
        by_ts[s] = {b[0]: b for b in bars}

    trade_id_counter = 1
    dss_prevented_losses = 0.0

    print("\n⚡ [3/4] 24 Saatlik Walk-Forward Simülasyonu Koşuluyor...")

    # Iterate bar by bar
    for step_idx, cur_ts in enumerate(replay_ts):
        # 1. Collect current prices and 1-bar price changes for all symbols up to cur_ts
        ticks: Dict[str, Dict[str, Any]] = {}
        candles_map: Dict[str, List[Dict[str, Any]]] = {}

        for sym, bars in data.items():
            # Find bars up to cur_ts
            idx = -1
            for i, b in enumerate(bars):
                if b[0] == cur_ts:
                    idx = i
                    break
                elif b[0] > cur_ts:
                    idx = i - 1
                    break
            if idx < 30:  # Need at least 30 bars for indicators
                continue
            
            sub_bars = bars[max(0, idx - 100):idx + 1]
            cur_bar = sub_bars[-1]
            open_ref = sub_bars[max(0, len(sub_bars) - 24)][1]
            chg_pct = round(((cur_bar[4] - open_ref) / open_ref) * 100.0, 3)
            
            closes = [b[4] for b in sub_bars]
            highs = [b[2] for b in sub_bars]
            lows = [b[3] for b in sub_bars]
            opens = [b[1] for b in sub_bars]
            tech = forex._compute_technical_indicators(closes, highs, lows, opens, sym)
            if not tech:
                continue
            
            ticks[sym] = {
                "symbol": sym,
                "price": cur_bar[4],
                "bid": cur_bar[4],
                "ask": cur_bar[4] + 0.0001,  # baseline spread
                "change_pct": chg_pct,
                "high": cur_bar[2],
                "low": cur_bar[3],
                "open": cur_bar[1],
                "close": cur_bar[4],
                "time": cur_bar[0],
                "action": tech.get("action", "HOLD"),
                "score": tech.get("score", 50.0),
                "trend": tech.get("trend", "NEUTRAL"),
                "rsi": tech.get("rsi", 50.0),
                "cmo": tech.get("cmo", 0.0),
                "cci": tech.get("cci", 0.0),
                "macd": tech.get("macd", 0.0),
                "macd_hist": tech.get("macd_hist", 0.0),
                "atr": tech.get("atr", 10.0),
                "atr_pips": tech.get("atr_pips", tech.get("atr", 10.0)),
                "adx": tech.get("adx", 20.0),
                "supertrend": tech.get("supertrend", cur_bar[4]),
                "supertrend_dir": tech.get("supertrend_dir", 0),
                "fvg_type": tech.get("fvg_type", "NONE"),
                "fvg_gap": tech.get("fvg_gap", 0.0),
                "spread_pips": 1.2,
            }

        if len(ticks) < 10:
            continue

        # 2. Compute Currency Strength Matrix (CSM) for this exact bar
        csm_data = forex.compute_currency_strength_matrix(ticks)

        # 4. Check position exits for both accounts
        for acc in (acc_baseline, acc_dss):
            still_open: List[Position] = []
            for pos in acc.positions:
                bar = by_ts.get(pos.symbol, {}).get(cur_ts)
                if not bar:
                    still_open.append(pos)
                    continue

                b_o, b_h, b_l, b_c = bar[1], bar[2], bar[3], bar[4]
                closed = False
                exit_price = 0.0
                exit_reason = ""

                # Check SL first
                if pos.direction == "BUY":
                    if b_l <= pos.sl_price:
                        closed = True
                        exit_price = pos.sl_price
                        exit_reason = "BE_HIT" if (pos.be_locked and pos.sl_price >= pos.entry_price) else "SL_HIT"
                    elif b_h >= pos.tp_price:
                        closed = True
                        exit_price = pos.tp_price
                        exit_reason = "TP_HIT"
                    else:
                        # Trailing & BE update
                        pnl_pips = (b_h - pos.entry_price) / pos.pip_size
                        if pnl_pips > pos.mfe_pips:
                            pos.mfe_pips = pnl_pips
                        
                        # BE and Trailing update
                        if acc.name.startswith("Yeni"):
                            # Asimetri Düzeltmesi (DSS): 0.40R veya 0.8 ATR kârda BE tetiklenir (forex.py calculate_breakeven_target paritesi)
                            be_trigger_pips = max(pos.sl0_pips * 0.40, pos.entry_atr * 0.8)
                            if pnl_pips >= be_trigger_pips and not pos.be_locked:
                                pos.be_locked = True
                                # Kâr kilidi: en az 0.20R kâr kilitlenir (ör. 10 pip SL'de +2.0 pip / ~$30)
                                lock_pips = max(1.5, pos.sl0_pips * 0.20)
                                pos.sl_price = round(pos.entry_price + (lock_pips * pos.pip_size), pos.digits)
                            # Trailing stop: 1.0R kâr aşıldığında tepe noktasından 1.0 ATR mesafeden takip eder
                            if pos.be_locked and pnl_pips >= pos.sl0_pips * 1.0:
                                trail_sl = round(b_c - (pos.entry_atr * 1.0 * pos.pip_size), pos.digits)
                                if trail_sl > pos.sl_price:
                                    pos.sl_price = trail_sl
                                    pos.trail_active = True
                        else:
                            # Baseline early $1 BE (Mevcut Sistem)
                            if pnl_pips >= 1.5 and not pos.be_locked:
                                pos.be_locked = True
                                pos.sl_price = pos.entry_price + (0.5 * pos.pip_size)

                else:  # SELL
                    if b_h >= pos.sl_price:
                        closed = True
                        exit_price = pos.sl_price
                        exit_reason = "BE_HIT" if (pos.be_locked and pos.sl_price <= pos.entry_price) else "SL_HIT"
                    elif b_l <= pos.tp_price:
                        closed = True
                        exit_price = pos.tp_price
                        exit_reason = "TP_HIT"
                    else:
                        pnl_pips = (pos.entry_price - b_l) / pos.pip_size
                        if pnl_pips > pos.mfe_pips:
                            pos.mfe_pips = pnl_pips
                        
                        if acc.name.startswith("Yeni"):
                            be_trigger_pips = max(pos.sl0_pips * 0.40, pos.entry_atr * 0.8)
                            if pnl_pips >= be_trigger_pips and not pos.be_locked:
                                pos.be_locked = True
                                lock_pips = max(1.5, pos.sl0_pips * 0.20)
                                pos.sl_price = round(pos.entry_price - (lock_pips * pos.pip_size), pos.digits)
                            if pos.be_locked and pnl_pips >= pos.sl0_pips * 1.0:
                                trail_sl = round(b_c + (pos.entry_atr * 1.0 * pos.pip_size), pos.digits)
                                if pos.sl_price == 0 or trail_sl < pos.sl_price:
                                    pos.sl_price = trail_sl
                                    pos.trail_active = True
                        else:
                            if pnl_pips >= 1.5 and not pos.be_locked:
                                pos.be_locked = True
                                pos.sl_price = pos.entry_price - (0.5 * pos.pip_size)

                if closed:
                    pnl_p = (exit_price - pos.entry_price) / pos.pip_size if pos.direction == "BUY" else (pos.entry_price - exit_price) / pos.pip_size
                    pnl_usd = round(pnl_p * pos.lots * pos.pip_val, 2)
                    acc.balance = round(acc.balance + pnl_usd, 2)
                    acc.realized_pnl = round(acc.realized_pnl + pnl_usd, 2)
                    
                    # Ardışık 2 zararda 15 dk (900 sn) soğuma kuralı (DSS)
                    if acc.name.startswith("Yeni"):
                        if pnl_usd < 0 and exit_reason == "SL_HIT":
                            acc.streak_losses[pos.symbol] = acc.streak_losses.get(pos.symbol, 0) + 1
                            if acc.streak_losses[pos.symbol] >= 2:
                                acc.cooldown_until[pos.symbol] = cur_ts + 900.0  # 15 dk (900 sn) soğuma
                                acc.streak_losses[pos.symbol] = 0
                        elif pnl_usd > 0:
                            acc.streak_losses[pos.symbol] = 0

                    # Track drawdown
                    if acc.balance > acc.peak_balance:
                        acc.peak_balance = acc.balance
                    dd_usd = acc.peak_balance - acc.balance
                    dd_pct = (dd_usd / acc.peak_balance) * 100.0 if acc.peak_balance > 0 else 0.0
                    if dd_usd > acc.max_drawdown_usd:
                        acc.max_drawdown_usd = dd_usd
                        acc.max_drawdown_pct = dd_pct

                    acc.closed_trades.append({
                        "id": pos.id,
                        "symbol": pos.symbol,
                        "direction": pos.direction,
                        "tier": pos.tier,
                        "lots": pos.lots,
                        "entry_price": pos.entry_price,
                        "exit_price": exit_price,
                        "pnl_usd": pnl_usd,
                        "pnl_pips": round(pnl_p, 1),
                        "reason": exit_reason,
                        "time": cur_ts,
                    })
                else:
                    still_open.append(pos)

            acc.positions = still_open

        # 5. Evaluate New Entries for both systems
        # Check available candidate symbols
        for sym, t in ticks.items():
            if target_syms_set and sym not in target_syms_set:
                continue
            action = t.get("action", "HOLD")
            score = float(t.get("score", 0.0))
            if action not in ("BUY", "SELL"):
                continue

            spec = forex.get_symbol_trading_specs(sym)
            pip_size = spec["pip_size"]
            pip_val = spec["pip_val"]
            digits = spec["digits"]
            cur_price = t["price"]
            atr = float(t.get("atr_pips", 10.0))
            spread = float(t.get("spread_pips", 1.5))
            fvg_type = t.get("fvg_type", "NONE")
            supertrend_dir = int(t.get("supertrend_dir", 0))
            rsi = float(t.get("rsi", 50.0))
            cmo = float(t.get("cmo", 0.0))
            macd = float(t.get("macd", 0.0))
            csm_diff, csm_bias = forex.get_symbol_csm_differential(sym, csm_data)

            # --- SYSTEM 1: MEVCUT SİSTEM (Baseline) ---
            # Req: score >= 75 (FX) or 78 (Gold)
            min_req_score = 78.0 if "XAU" in sym or "USOIL" in sym else (76.0 if "BTC" in sym else 75.0)
            if score >= min_req_score and len(acc_baseline.positions) < MAX_CONCURRENT_POSITIONS:
                # Check if position already exists for this symbol
                if not any(p.symbol == sym for p in acc_baseline.positions):
                    # Classic SL/TP
                    sl_p = spec["sl_pips"]
                    tp_p = spec["tp_pips"]
                    lots = calculate_lots(acc_baseline.balance, sl_p, pip_val, spec, sym)
                    sl_px = cur_price - (sl_p * pip_size) if action == "BUY" else cur_price + (sl_p * pip_size)
                    tp_px = cur_price + (tp_p * pip_size) if action == "BUY" else cur_price - (tp_p * pip_size)

                    trade_id_counter += 1
                    acc_baseline.positions.append(Position(
                        id=f"BASE-{trade_id_counter}",
                        symbol=sym,
                        direction=action,
                        lots=lots,
                        entry_price=cur_price,
                        sl_price=round(sl_px, digits),
                        tp_price=round(tp_px, digits),
                        entry_time=cur_ts,
                        pip_size=pip_size,
                        pip_val=pip_val,
                        digits=digits,
                        entry_atr=atr,
                        sl0_pips=sl_p,
                        tp0_pips=tp_p,
                        tier="CLASSIC",
                    ))

            # --- SYSTEM 2: YENİ KARAR DESTEK SİSTEMİ (DSS & A+ Confluence) ---
            # Calculate DSS Multi-Factor Confluence
            dss_score, dss_tier = forex.calculate_dss_score(
                sym=sym,
                action=action,
                htf_trend="BULLISH" if t.get("trend") == "BULLISH" else "BEARISH",
                csm_diff=csm_diff,
                rsi_5m=rsi,
                macd_hist=macd,
                fvg_type=fvg_type,
                supertrend_dir=supertrend_dir,
                spread_pips=spread,
                atr_pips=atr,
            )

            # DSS Quality Gates:
            # 1. Tier Gate: Only A+ (Institutional) or B (High Quality with CSM alignment)
            is_valid_tier = (dss_tier == "A+") or (dss_tier == "B" and (
                (action == "BUY" and csm_bias in ("BULLISH", "NEUTRAL") and csm_diff >= -5.0) or
                (action == "SELL" and csm_bias in ("BEARISH", "NEUTRAL") and csm_diff <= 5.0)
            ))
            
            # 2. Spread / Profit Target Risk Filter
            tp_target_pips = spec["tp_pips"]
            spread_ratio_ok = (spread / max(1.0, tp_target_pips)) <= 0.20

            # 3. SuperTrend Multi-timeframe Confluence
            st_aligned = (action == "BUY" and supertrend_dir >= 0) or (action == "SELL" and supertrend_dir <= 0)

            # 4. Ardışık 2 Zarar Sonrası 15 Dakika Soğuma Süresi Denetimi
            is_in_cooldown = acc_dss.cooldown_until.get(sym, 0.0) > cur_ts
            if is_in_cooldown:
                acc_dss.cooldown_blocks_count += 1

            # Evaluate entry
            if is_valid_tier and spread_ratio_ok and st_aligned and not is_in_cooldown and len(acc_dss.positions) < MAX_CONCURRENT_POSITIONS:
                if not any(p.symbol == sym for p in acc_dss.positions):
                    # Volatility-adapted breathing exits (Dynamic Exit Architect)
                    atr_exits = forex.get_atr_exit_levels(atr, spec["sl_pips"], spec["tp_pips"])
                    sl_p = atr_exits["sl_pips"]
                    # 1.8R dinamik hedef (Asimetri çözümü: kârı erken kesme!)
                    tp_p = max(atr_exits["tp_pips"], sl_p * 1.8)
                    lots = calculate_lots(acc_dss.balance, sl_p, pip_val, spec, sym)
                    sl_px = cur_price - (sl_p * pip_size) if action == "BUY" else cur_price + (sl_p * pip_size)
                    tp_px = cur_price + (tp_p * pip_size) if action == "BUY" else cur_price - (tp_p * pip_size)

                    trade_id_counter += 1
                    acc_dss.positions.append(Position(
                        id=f"DSS-{trade_id_counter}",
                        symbol=sym,
                        direction=action,
                        lots=lots,
                        entry_price=cur_price,
                        sl_price=round(sl_px, digits),
                        tp_price=round(tp_px, digits),
                        entry_time=cur_ts,
                        pip_size=pip_size,
                        pip_val=pip_val,
                        digits=digits,
                        entry_atr=atr,
                        sl0_pips=sl_p,
                        tp0_pips=tp_p,
                        tier=dss_tier,
                    ))
            else:
                # If baseline took it but DSS rejected it, track why
                if score >= min_req_score:
                    acc_dss.blocked_trades_count += 1
                    if is_in_cooldown:
                        acc_dss.blocked_reasons["STREAK_LOSS_COOLDOWN_15M"] = acc_dss.blocked_reasons.get("STREAK_LOSS_COOLDOWN_15M", 0) + 1
                    elif not spread_ratio_ok:
                        acc_dss.blocked_reasons["SPREAD_COST_TOO_HIGH"] = acc_dss.blocked_reasons.get("SPREAD_COST_TOO_HIGH", 0) + 1
                    elif not is_valid_tier:
                        acc_dss.blocked_reasons["DSS_SCORE_BELOW_TIER"] = acc_dss.blocked_reasons.get("DSS_SCORE_BELOW_TIER", 0) + 1
                    elif not st_aligned:
                        acc_dss.blocked_reasons["SUPERTREND_CONFLICT"] = acc_dss.blocked_reasons.get("SUPERTREND_CONFLICT", 0) + 1

    # Close remaining positions at last bar price
    for acc in (acc_baseline, acc_dss):
        for pos in acc.positions:
            last_bar = by_ts.get(pos.symbol, {}).get(replay_ts[-1])
            if last_bar:
                exit_price = last_bar[4]
                pnl_p = (exit_price - pos.entry_price) / pos.pip_size if pos.direction == "BUY" else (pos.entry_price - exit_price) / pos.pip_size
                pnl_usd = round(pnl_p * pos.lots * pos.pip_val, 2)
                acc.balance = round(acc.balance + pnl_usd, 2)
                acc.realized_pnl = round(acc.realized_pnl + pnl_usd, 2)
                acc.closed_trades.append({
                    "id": pos.id,
                    "symbol": pos.symbol,
                    "direction": pos.direction,
                    "tier": pos.tier,
                    "lots": pos.lots,
                    "entry_price": pos.entry_price,
                    "exit_price": exit_price,
                    "pnl_usd": pnl_usd,
                    "pnl_pips": round(pnl_p, 1),
                    "reason": "END_OF_REPLAY",
                    "time": replay_ts[-1],
                })
        acc.positions.clear()

    # --- 6. Results & Statistical Comparison ---
    print("\n" + "=" * 80)
    print("📊 [4/4] 48 SAATLİK REPLAY PERFORMANS RAPORU (1.000$ Bakiye | FX: %15, XAU: %5, BTC/US30/USTEC: %2 Risk | 15 Dk Soğuma)")
    print("=" * 80)

    for acc in (acc_baseline, acc_dss):
        trades = acc.closed_trades
        n_trades = len(trades)
        wins = [t for t in trades if t["pnl_usd"] > 0]
        losses = [t for t in trades if t["pnl_usd"] < 0]
        be_trades = [t for t in trades if t["pnl_usd"] == 0]
        win_rate = (len(wins) / n_trades * 100.0) if n_trades > 0 else 0.0
        
        gross_profit = sum(t["pnl_usd"] for t in wins)
        gross_loss = abs(sum(t["pnl_usd"] for t in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
        avg_trade = (acc.realized_pnl / n_trades) if n_trades > 0 else 0.0
        return_pct = ((acc.balance - STARTING_BALANCE) / STARTING_BALANCE) * 100.0

        print(f"\n🔹 {acc.name.upper()}")
        print("-" * 80)
        print(f"  • Başlangıç Bakiyesi       : ${STARTING_BALANCE:,.2f}")
        print(f"  • Bitiş Bakiyesi           : ${acc.balance:,.2f}")
        print(f"  • Net Kâr / Zarar          : ${acc.realized_pnl:+,.2f} ({return_pct:+.2f}%)")
        print(f"  • Toplam İşlem Sayısı      : {n_trades} (Kazanç: {len(wins)}, Kayıp: {len(losses)}, Başabaş: {len(be_trades)})")
        print(f"  • Kazanma Oranı (Win Rate) : %{win_rate:.1f}")
        print(f"  • Kâr Faktörü (PF)         : {profit_factor:.2f}")
        print(f"  • Brüt Kâr                 : +${gross_profit:,.2f}")
        print(f"  • Brüt Kayıp               : -${gross_loss:,.2f}")
        print(f"  • Ortalama İşlem PnL       : ${avg_trade:+,.2f}")
        print(f"  • Maksimum Düşüş (Max DD)  : -${acc.max_drawdown_usd:,.2f} (%{acc.max_drawdown_pct:.2f})")
        
        # Reasons breakdown
        reasons: Dict[str, int] = {}
        for t in trades:
            reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
        print(f"  • Çıkış Nedenleri Dağılımı : {reasons}")

        if acc.name.startswith("Yeni"):
            print(f"  • DSS Tarafından Engellenen Zayıf Girişler: {acc.blocked_trades_count} adet")
            print(f"    └─ 15 Dk Soğuma Kalkanı ile Engellenen Sinyaller : {acc.cooldown_blocks_count} adet")
            print(f"    └─ Engel Nedenleri Dağılımı: {acc.blocked_reasons}")

    # Head to head comparison table
    print("\n" + "=" * 80)
    print("🏆 DOĞRUDAN KARŞILAŞTIRMA TABLOSU")
    print("=" * 80)
    print(f"{'METRİK':<26} | {'MEVCUT SİSTEM (BASELINE)':<24} | {'YENİ DSS SİSTEMİ':<24}")
    print("-" * 80)
    
    b_trades = len(acc_baseline.closed_trades)
    d_trades = len(acc_dss.closed_trades)
    b_wr = (len([t for t in acc_baseline.closed_trades if t["pnl_usd"] > 0]) / max(1, b_trades)) * 100
    d_wr = (len([t for t in acc_dss.closed_trades if t["pnl_usd"] > 0]) / max(1, d_trades)) * 100
    b_ret = ((acc_baseline.balance - STARTING_BALANCE) / STARTING_BALANCE) * 100
    d_ret = ((acc_dss.balance - STARTING_BALANCE) / STARTING_BALANCE) * 100
    
    b_gp = sum(t["pnl_usd"] for t in acc_baseline.closed_trades if t["pnl_usd"] > 0)
    b_gl = abs(sum(t["pnl_usd"] for t in acc_baseline.closed_trades if t["pnl_usd"] < 0))
    b_pf = (b_gp / b_gl) if b_gl > 0 else (99.0 if b_gp > 0 else 0.0)

    d_gp = sum(t["pnl_usd"] for t in acc_dss.closed_trades if t["pnl_usd"] > 0)
    d_gl = abs(sum(t["pnl_usd"] for t in acc_dss.closed_trades if t["pnl_usd"] < 0))
    d_pf = (d_gp / d_gl) if d_gl > 0 else (99.0 if d_gp > 0 else 0.0)

    print(f"{'Son Bakiye ($)':<26} | ${acc_baseline.balance:<23,.2f} | ${acc_dss.balance:<23,.2f}")
    print(f"{'Net Kâr ($)':<26} | ${acc_baseline.realized_pnl:<+23,.2f} | ${acc_dss.realized_pnl:<+23,.2f}")
    print(f"{'Toplam Getiri (%)':<26} | %{b_ret:<+23.2f} | %{d_ret:<+23.2f}")
    print(f"{'Kazanma Oranı (%)':<26} | %{b_wr:<23.1f} | %{d_wr:<23.1f}")
    print(f"{'Kâr Faktörü (PF)':<26} | {b_pf:<24.2f} | {d_pf:<24.2f}")
    print(f"{'Maksimum Drawdown ($)':<26} | -${acc_baseline.max_drawdown_usd:<23,.2f} | -${acc_dss.max_drawdown_usd:<23,.2f}")
    print(f"{'Toplam İşlem Sayısı':<26} | {b_trades:<24} | {d_trades:<24}")
    print("=" * 80)

    # Save detailed JSON report
    out_report = {
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "starting_balance": STARTING_BALANCE,
        "risk_pct": RISK_PCT,
        "baseline": {
            "balance": acc_baseline.balance,
            "net_pnl": acc_baseline.realized_pnl,
            "trades_count": len(acc_baseline.closed_trades),
            "win_rate": b_wr,
            "profit_factor": b_pf,
            "max_dd_usd": acc_baseline.max_drawdown_usd,
            "trades": acc_baseline.closed_trades,
        },
        "dss_system": {
            "balance": acc_dss.balance,
            "net_pnl": acc_dss.realized_pnl,
            "trades_count": len(acc_dss.closed_trades),
            "win_rate": d_wr,
            "profit_factor": d_pf,
            "max_dd_usd": acc_dss.max_drawdown_usd,
            "blocked_count": acc_dss.blocked_trades_count,
            "blocked_reasons": acc_dss.blocked_reasons,
            "trades": acc_dss.closed_trades,
        }
    }
    out_file = os.path.join(ROOT, "outputs", "replay_24h_dss_comparison.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out_report, f, indent=2)
    print(f"\n💾 Ayrıntılı Replay Raporu kaydedildi: {out_file}")
    print(f"⏱️ Toplam Çalışma Süresi: {time.time() - t_start_wall:.1f} saniye.\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Walk-Forward Replay: Baseline vs DSS")
    parser.add_argument("--days", type=int, default=7, help="Replay test gün sayısı (varsayılan: 7)")
    parser.add_argument("--symbols", type=str, default="", help="Test edilecek semboller (virgülle, ör: BTCUSD,US30,NAS100)")
    args = parser.parse_args()

    sym_list = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    run_replay(days=args.days, target_symbols=sym_list)
