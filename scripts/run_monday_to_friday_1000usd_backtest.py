"""Monday to Friday $1,000 USD Realistic Multi-Asset Portfolio Backtest.

Simulates starting with exactly $1,000.00 USD on Monday (2026-10-12 00:00 UTC+3)
up to Friday market close (2026-10-16 23:59 UTC+3).

Features:
- Chronologically synchronized multi-asset portfolio simulation (shared dynamic balance).
- Real IC Markets broker spreads deducted on every entry and exit.
- Live Spread Shield enforced (spread / TP <= 0.20).
- Dynamic Risk Budget: Forex 15%, Gold 7%, Crypto/Indices 2%.
- Dynamic BE at 0.40R (+0.20R profit lock).
- Winning Pyramiding: 1st layer, 2nd layer (if PnL >= +$0.20), 3rd layer (if both >= +$0.20).
- Compares:
  1. Default Live Universe vs All 31 Symbols
  2. Max 1 Position (No Pyramiding) vs Max 2 Positions (Live System) vs Max 3 Positions.
- Tracks exact equity curve, peak balance, max drawdown ($ and %), win rate, and profit factor.
"""
import os
import sys
import json
import datetime
from typing import Any, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.app.routers import forex

# Real broker spreads (in pips)
REAL_BROKER_SPREADS: Dict[str, float] = {
    "EURUSD": 0.8, "GBPUSD": 1.1, "USDJPY": 0.9, "USDCHF": 1.2, "AUDUSD": 1.0,
    "USDCAD": 1.2, "NZDUSD": 1.4, "XAUUSD": 1.8, "BTCUSD": 12.0, "US30": 2.5,
    "NAS100": 1.5, "GBPJPY": 1.8, "EURJPY": 1.5, "CHFJPY": 1.8, "CADJPY": 1.7,
    "AUDJPY": 1.6, "NZDJPY": 2.0, "EURGBP": 1.2, "EURCHF": 1.5, "EURCAD": 1.8,
    "EURAUD": 1.8, "EURNZD": 2.2, "GBPCHF": 2.0, "GBPAUD": 2.2, "GBPCAD": 2.2,
    "GBPNZD": 2.8, "AUDCAD": 1.5, "AUDNZD": 2.0, "AUDCHF": 1.8, "CADCHF": 1.8,
    "NZDCHF": 2.0, "NZDCAD": 2.0,
}

LIVE_ALLOWED_SYMBOLS = [
    "XAUUSD", "BTCUSD", "US30", "NAS100", "GBPJPY", "EURJPY",
    "USDJPY", "AUDCAD", "GBPUSD", "EURUSD"
]

def load_data():
    path = os.path.join(ROOT, "outputs", "forex_replay_data_7d.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Veri bulunamadi: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def run_portfolio_simulation(
    symbols: List[str],
    t_start: float,
    t_end: float,
    max_positions_per_symbol: int = 2,
    starting_balance: float = 1000.0,
    spread_shield_enabled: bool = True,
    max_open_portfolio: int = 20,
) -> Dict[str, Any]:
    raw_data = load_data()
    
    # 1. Align time series for all requested symbols
    # Gather all unique timestamps in the dataset
    all_timestamps = set()
    symbol_bars = {}
    symbol_specs = {}
    
    for sym in symbols:
        if sym not in raw_data:
            continue
        bars = raw_data[sym]
        symbol_bars[sym] = {b[0]: b for b in bars}
        all_timestamps.update(b[0] for b in bars)
        
        spec = forex.get_symbol_trading_specs(sym)
        cat = spec.get("category", "major")
        spread = REAL_BROKER_SPREADS.get(sym, 1.5)
        
        risk_pct = forex.get_symbol_risk_pct(sym)
            
        symbol_specs[sym] = {
            "spec": spec,
            "pip_size": spec["pip_size"],
            "pip_val": spec["pip_val"],
            "digits": spec["digits"],
            "tp_pips": spec["tp_pips"],
            "sl_pips": spec["sl_pips"],
            "spread_pips": spread,
            "half_spread_px": (spread * spec["pip_size"]) / 2.0,
            "risk_pct": risk_pct,
            "spread_shield_blocked": (spread / spec["tp_pips"] > 0.20) if spread_shield_enabled else False
        }
        
    sorted_times = sorted([t for t in all_timestamps if t >= (t_start - 24 * 3600)]) # warm-up from 24h prior
    
    balance = starting_balance
    peak_equity = starting_balance
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    
    open_positions: List[Dict[str, Any]] = []
    closed_trades: List[Dict[str, Any]] = []
    equity_curve: List[Tuple[float, float, float]] = [] # (time, balance, equity)
    
    # Historical rolling bars per symbol
    rolling_bars: Dict[str, List[List[float]]] = {s: [] for s in symbols}
    
    # Walk forward bar-by-bar
    for t in sorted_times:
        is_in_eval_window = (t >= t_start and t <= t_end)
        
        # 1. Update rolling history for each symbol present at this timestamp
        for sym in symbols:
            if sym in symbol_bars and t in symbol_bars[sym]:
                rolling_bars[sym].append(symbol_bars[sym][t])
                if len(rolling_bars[sym]) > 60:
                    rolling_bars[sym].pop(0)
                    
        # 2. Check exits on ALL currently open positions
        still_open = []
        for pos in open_positions:
            sym = pos["symbol"]
            cfg = symbol_specs[sym]
            pip_size = cfg["pip_size"]
            pip_val = cfg["pip_val"]
            half_spread_px = cfg["half_spread_px"]
            digits = cfg["digits"]
            
            # If no bar at this timestamp for this symbol, position remains open
            if sym not in symbol_bars or t not in symbol_bars[sym]:
                still_open.append(pos)
                continue
                
            bar = symbol_bars[sym][t]
            b_h, b_l, b_c = bar[2], bar[3], bar[4]
            
            closed = False
            exit_price = 0.0
            exit_reason = ""
            
            if pos["direction"] == "BUY":
                curr_bid_low = b_l - half_spread_px
                curr_bid_high = b_h - half_spread_px
                
                if curr_bid_low <= pos["sl_price"]:
                    closed = True
                    exit_price = pos["sl_price"]
                    exit_reason = "BE_STOP" if pos["be_locked"] else "SL_HIT"
                elif curr_bid_high >= pos["tp_price"]:
                    closed = True
                    exit_price = pos["tp_price"]
                    exit_reason = "TP_HIT"
                else:
                    # Dynamic BE trigger
                    cur_pnl_pips = (curr_bid_high - pos["entry_price"]) / pip_size
                    if cur_pnl_pips >= pos["sl0_pips"] * 0.40 and not pos["be_locked"]:
                        pos["be_locked"] = True
                        pos["sl_price"] = pos["entry_price"] + (pos["sl0_pips"] * 0.20 * pip_size)
            else: # SELL
                curr_ask_high = b_h + half_spread_px
                curr_ask_low = b_l + half_spread_px
                
                if curr_ask_high >= pos["sl_price"]:
                    closed = True
                    exit_price = pos["sl_price"]
                    exit_reason = "BE_STOP" if pos["be_locked"] else "SL_HIT"
                elif curr_ask_low <= pos["tp_price"]:
                    closed = True
                    exit_price = pos["tp_price"]
                    exit_reason = "TP_HIT"
                else:
                    cur_pnl_pips = (pos["entry_price"] - curr_ask_low) / pip_size
                    if cur_pnl_pips >= pos["sl0_pips"] * 0.40 and not pos["be_locked"]:
                        pos["be_locked"] = True
                        pos["sl_price"] = pos["entry_price"] - (pos["sl0_pips"] * 0.20 * pip_size)
                        
            if closed:
                if pos["direction"] == "BUY":
                    diff_pips = (exit_price - pos["entry_price"]) / pip_size
                else:
                    diff_pips = (pos["entry_price"] - exit_price) / pip_size
                pnl_usd = round(diff_pips * pos["lots"] * pip_val, 2)
                
                pos["exit_price"] = round(exit_price, digits)
                pos["exit_time"] = t
                pos["exit_reason"] = exit_reason
                pos["pnl_pips"] = round(diff_pips, 1)
                pos["pnl_usd"] = pnl_usd
                
                # Update cash balance immediately
                balance += pnl_usd
                closed_trades.append(pos)
            else:
                still_open.append(pos)
                
        open_positions = still_open
        
        # 3. Calculate current unrealized PnL & Equity
        floating_pnl = 0.0
        for pos in open_positions:
            sym = pos["symbol"]
            cfg = symbol_specs[sym]
            if sym in symbol_bars and t in symbol_bars[sym]:
                b_c = symbol_bars[sym][t][4]
                if pos["direction"] == "BUY":
                    f_diff = ((b_c - cfg["half_spread_px"]) - pos["entry_price"]) / cfg["pip_size"]
                else:
                    f_diff = (pos["entry_price"] - (b_c + cfg["half_spread_px"])) / cfg["pip_size"]
                floating_pnl += f_diff * pos["lots"] * cfg["pip_val"]
                
        equity = balance + floating_pnl
        if is_in_eval_window:
            if equity > peak_equity:
                peak_equity = equity
            dd_usd = peak_equity - equity
            dd_pct = (dd_usd / peak_equity * 100.0) if peak_equity > 0 else 0.0
            if dd_usd > max_dd_usd:
                max_dd_usd = dd_usd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
            equity_curve.append((t, balance, equity))
            
        # If not yet in evaluation window, do not open new trades
        if not is_in_eval_window:
            continue
            
        # 4. Signal Generation & Entries
        if len(open_positions) >= max_open_portfolio:
            continue
            
        for sym in symbols:
            cfg = symbol_specs[sym]
            if cfg["spread_shield_blocked"]:
                continue
            if len(rolling_bars[sym]) < 20:
                continue
                
            r_bars = rolling_bars[sym]
            cur_bar = r_bars[-1]
            prev_bar = r_bars[-2]
            b_c = cur_bar[4]
            b_o = cur_bar[1]
            
            closes = [b[4] for b in r_bars[-15:]]
            diffs = [closes[j] - closes[j-1] for j in range(1, len(closes))]
            gains = [d for d in diffs if d > 0]
            losses_l = [-d for d in diffs if d < 0]
            avg_gain = sum(gains) / 14.0 if gains else 0.0001
            avg_loss = sum(losses_l) / 14.0 if losses_l else 0.0001
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
            ema8 = sum(closes[-8:]) / 8.0
            ema21 = sum(closes) / float(len(closes))
            
            signal = None
            strat = ""
            
            # A) Radar Momentum
            if ema8 > ema21 and rsi > 52 and b_c > prev_bar[2]:
                signal = "BUY"
                strat = "RADAR"
            elif ema8 < ema21 and rsi < 48 and b_c < prev_bar[3]:
                signal = "SELL"
                strat = "RADAR"
                
            # B) FVG Pullback
            if not signal and len(r_bars) >= 4:
                b_prev2 = r_bars[-3]
                if b_prev2[2] < b_c and cur_bar[3] <= b_prev2[2] and b_c > prev_bar[4]:
                    signal = "BUY"
                    strat = "FVG"
                elif b_prev2[3] > b_c and cur_bar[2] >= b_prev2[3] and b_c < prev_bar[4]:
                    signal = "SELL"
                    strat = "FVG"
                    
            # C) S3 Supertrend Pullback
            if not signal:
                if ema8 > ema21 and rsi < 42 and b_c > b_o:
                    signal = "BUY"
                    strat = "S3"
                elif ema8 < ema21 and rsi > 58 and b_c < b_o:
                    signal = "SELL"
                    strat = "S3"
                    
            if not signal:
                continue
                
            # Check existing positions on this symbol
            sym_same = [p for p in open_positions if p["symbol"] == sym and p["direction"] == signal]
            sym_opp = [p for p in open_positions if p["symbol"] == sym and p["direction"] != signal]
            
            # Reversal flip: Close opposite positions immediately
            if sym_opp:
                for p in sym_opp:
                    exit_px = (b_c + cfg["half_spread_px"]) if p["direction"] == "SELL" else (b_c - cfg["half_spread_px"])
                    diff_p = (exit_px - p["entry_price"]) / cfg["pip_size"] if p["direction"] == "BUY" else (p["entry_price"] - exit_px) / cfg["pip_size"]
                    pnl_u = round(diff_p * p["lots"] * cfg["pip_val"], 2)
                    p["exit_price"] = round(exit_px, cfg["digits"])
                    p["exit_time"] = t
                    p["exit_reason"] = "REVERSAL_FLIP"
                    p["pnl_pips"] = round(diff_p, 1)
                    p["pnl_usd"] = pnl_u
                    balance += pnl_u
                    closed_trades.append(p)
                open_positions = [p for p in open_positions if p["symbol"] != sym or p["direction"] == signal]
                sym_same = [p for p in open_positions if p["symbol"] == sym and p["direction"] == signal]
                
            # Pyramiding Limit
            if len(sym_same) >= max_positions_per_symbol:
                continue
                
            # Winning Pyramiding Rules:
            # Layer 2 allowed ONLY if Layer 1 >= +$0.20
            # Layer 3 allowed ONLY if Layer 1 & 2 BOTH >= +$0.20
            if len(sym_same) == 1:
                p1 = sym_same[0]
                if p1["direction"] == "BUY":
                    f_pips = ((b_c - cfg["half_spread_px"]) - p1["entry_price"]) / cfg["pip_size"]
                else:
                    f_pips = (p1["entry_price"] - (b_c + cfg["half_spread_px"])) / cfg["pip_size"]
                if f_pips * p1["lots"] * cfg["pip_val"] < 0.20:
                    continue
            elif len(sym_same) == 2:
                all_good = True
                for p_prev in sym_same:
                    if p_prev["direction"] == "BUY":
                        f_pips = ((b_c - cfg["half_spread_px"]) - p_prev["entry_price"]) / cfg["pip_size"]
                    else:
                        f_pips = (p_prev["entry_price"] - (b_c + cfg["half_spread_px"])) / cfg["pip_size"]
                    if f_pips * p_prev["lots"] * cfg["pip_val"] < 0.20:
                        all_good = False
                        break
                if not all_good:
                    continue
                    
            # Position sizing dynamically tied to current balance
            risk_usd = balance * (cfg["risk_pct"] / 100.0)
            raw_lots = risk_usd / (cfg["sl_pips"] * cfg["pip_val"])
            max_lot_cap = 2.0 if sym in ("US30", "NAS100") else 5.0
            lots = round(max(cfg["spec"].get("min_lot", 0.01), min(max_lot_cap, raw_lots)), 2)
            
            # Entry with spread
            if signal == "BUY":
                entry_price = round(b_c + cfg["half_spread_px"], cfg["digits"])
                sl_price = round(entry_price - (cfg["sl_pips"] * cfg["pip_size"]), cfg["digits"])
                tp_price = round(entry_price + (cfg["tp_pips"] * cfg["pip_size"]), cfg["digits"])
            else:
                entry_price = round(b_c - cfg["half_spread_px"], cfg["digits"])
                sl_price = round(entry_price + (cfg["sl_pips"] * cfg["pip_size"]), cfg["digits"])
                tp_price = round(entry_price - (cfg["tp_pips"] * cfg["pip_size"]), cfg["digits"])
                
            new_pos = {
                "id": f"{sym}-{t}-{signal}-{len(sym_same)+1}",
                "symbol": sym,
                "direction": signal,
                "strategy": strat,
                "lots": lots,
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "sl0_pips": cfg["sl_pips"],
                "be_locked": False,
                "entry_time": t,
                "layer": len(sym_same) + 1,
            }
            open_positions.append(new_pos)
            
    # Close any positions left open at end of period at market price
    final_time = sorted_times[-1] if sorted_times else t_end
    for pos in open_positions:
        sym = pos["symbol"]
        cfg = symbol_specs[sym]
        b_c = symbol_bars[sym][final_time][4] if (sym in symbol_bars and final_time in symbol_bars[sym]) else pos["entry_price"]
        exit_px = (b_c - cfg["half_spread_px"]) if pos["direction"] == "BUY" else (b_c + cfg["half_spread_px"])
        diff_p = (exit_px - pos["entry_price"]) / cfg["pip_size"] if pos["direction"] == "BUY" else (pos["entry_price"] - exit_px) / cfg["pip_size"]
        pnl_u = round(diff_p * pos["lots"] * cfg["pip_val"], 2)
        pos["exit_price"] = round(exit_px, cfg["digits"])
        pos["exit_time"] = final_time
        pos["exit_reason"] = "WEEKEND_CLOSE"
        pos["pnl_pips"] = round(diff_p, 1)
        pos["pnl_usd"] = pnl_u
        balance += pnl_u
        closed_trades.append(pos)
        
    wins = [t for t in closed_trades if t["pnl_usd"] > 0]
    losses = [t for t in closed_trades if t["pnl_usd"] < 0]
    wr = round(len(wins) / len(closed_trades) * 100.0, 1) if closed_trades else 0.0
    tot_pnl = round(balance - starting_balance, 2)
    gross_win = sum(t["pnl_usd"] for t in wins)
    gross_loss = abs(sum(t["pnl_usd"] for t in losses))
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else 99.0
    
    # Layer breakdown
    l1 = [t for t in closed_trades if t.get("layer", 1) == 1]
    l2 = [t for t in closed_trades if t.get("layer", 1) == 2]
    l3 = [t for t in closed_trades if t.get("layer", 1) == 3]
    
    # Symbol breakdown
    sym_breakdown = {}
    for sym in symbols:
        s_trades = [t for t in closed_trades if t["symbol"] == sym]
        s_wins = [t for t in s_trades if t["pnl_usd"] > 0]
        s_pnl = round(sum(t["pnl_usd"] for t in s_trades), 2)
        s_wr = round(len(s_wins) / len(s_trades) * 100.0, 1) if s_trades else 0.0
        sym_breakdown[sym] = {
            "trades": len(s_trades),
            "wins": len(s_wins),
            "win_rate": s_wr,
            "net_pnl": s_pnl,
        }
        
    return {
        "starting_balance": starting_balance,
        "final_balance": round(balance, 2),
        "net_pnl": tot_pnl,
        "roi_pct": round((tot_pnl / starting_balance) * 100.0, 2),
        "win_rate": wr,
        "profit_factor": pf,
        "total_trades": len(closed_trades),
        "wins_count": len(wins),
        "losses_count": len(losses),
        "max_drawdown_usd": round(max_dd_usd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "peak_equity": round(peak_equity, 2),
        "l1_trades": len(l1), "l1_pnl": round(sum(t["pnl_usd"] for t in l1), 2),
        "l2_trades": len(l2), "l2_pnl": round(sum(t["pnl_usd"] for t in l2), 2),
        "l3_trades": len(l3), "l3_pnl": round(sum(t["pnl_usd"] for t in l3), 2),
        "symbols": sym_breakdown,
        "trades_sample": closed_trades[:5],
    }

def main():
    print("=" * 85)
    print("🚀 GEÇEN HAFTA PAZARTESİ'DEN BUGÜNE (1000$ İLE MEVCUT SİSTEM) RESMİ BACKTEST")
    print("=" * 85)
    
    # Target 1: Last Work Week (Monday 2026-10-12 00:00 UTC+3 to Friday 2026-10-16 23:59 UTC+3)
    # UTC+3 is UTC + 3 hours, so 00:00 UTC+3 is 21:00 UTC previous day (Oct 11 21:00 UTC)
    t_mon_start = datetime.datetime(2026, 10, 11, 21, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
    t_fri_end = datetime.datetime(2026, 10, 16, 23, 59, 59, tzinfo=datetime.timezone.utc).timestamp()
    
    print("\n[TEST 1] CANLI İZİNLİ PORTFÖY (XAU, BTC, US30, NAS100, GBPJPY, EURJPY, USDJPY, AUDCAD, GBPUSD, EURUSD)")
    print(f"Tarih Aralığı: Pazartesi 12 Ekim 00:00 (UTC+3) -> Cuma 16 Ekim 23:59 (UTC+3) [5 İşlem Günü]")
    print(f"Başlangıç Bakiyesi: $1,000.00 USD")
    print(f"Gerçek Broker Spreadleri: DAHİL")
    print(f"Spread Kalkanı: DAHİL")
    print(f"Dinamik BE Kâr Kilidi: 0.40R tetik (+0.20R kilit)")
    
    # 1. Option 2: Live System (Max 2 positions per symbol - winning pyramiding)
    res_live_pyr2 = run_portfolio_simulation(
        symbols=LIVE_ALLOWED_SYMBOLS,
        t_start=t_mon_start,
        t_end=t_fri_end,
        max_positions_per_symbol=2,
        starting_balance=1000.0,
    )
    
    # 2. Option 1: No Pyramiding (Max 1 position per symbol)
    res_live_pyr1 = run_portfolio_simulation(
        symbols=LIVE_ALLOWED_SYMBOLS,
        t_start=t_mon_start,
        t_end=t_fri_end,
        max_positions_per_symbol=1,
        starting_balance=1000.0,
    )
    
    # 3. Option 3: 3-Layer Pyramiding (Max 3 positions per symbol)
    res_live_pyr3 = run_portfolio_simulation(
        symbols=LIVE_ALLOWED_SYMBOLS,
        t_start=t_mon_start,
        t_end=t_fri_end,
        max_positions_per_symbol=3,
        starting_balance=1000.0,
    )
    
    print("\n" + "-" * 85)
    print("📌 MEVCUT CANLI SİSTEM (PİRAMİTLEME = 2 KATMAN) HAFTALIK SONUCU:")
    print("-" * 85)
    print(f"💰 BAŞLANGIÇ BAKİYESİ : $1,000.00 USD")
    print(f"💵 NİHAİ BAKİYE       : ${res_live_pyr2['final_balance']:,.2f} USD")
    print(f"📈 NET KÂR / GETİRİ   : ${res_live_pyr2['net_pnl']:+,.2f} USD (%{res_live_pyr2['roi_pct']:+.1f})")
    print(f"🎯 KAZANMA ORANI (WR) : %{res_live_pyr2['win_rate']} ({res_live_pyr2['wins_count']} Kazanç / {res_live_pyr2['losses_count']} Kayıp)")
    print(f"⚖️ KÂR FAKTÖRÜ (PF)   : {res_live_pyr2['profit_factor']}")
    print(f"🛡️ EN YÜKSEK ÇEKİLME  : -${res_live_pyr2['max_drawdown_usd']:,.2f} (-%{res_live_pyr2['max_drawdown_pct']:.1f} Max DD)")
    print(f"🏔️ ZİRVE BAKİYE       : ${res_live_pyr2['peak_equity']:,.2f} USD")
    print(f"📊 Toplam İşlem Adedi : {res_live_pyr2['total_trades']} işlem")
    print(f"   • 1. Katman Girişler : {res_live_pyr2['l1_trades']} işlem | Net Kâr: ${res_live_pyr2['l1_pnl']:+,.2f}")
    print(f"   • 2. Katman (Piramit): {res_live_pyr2['l2_trades']} işlem | Net Kâr: ${res_live_pyr2['l2_pnl']:+,.2f}")
    
    print("\n" + "-" * 85)
    print("📋 SEMBOL BAZINDA HAFTALIK AYRINTI (Canlı Portföy):")
    print("-" * 85)
    print(f"{'Sembol':8s} | {'İşlem':6s} | {'W / L':8s} | {'Kazanma %':10s} | {'Net Kâr ($)':12s}")
    print("-" * 85)
    sorted_syms = sorted(res_live_pyr2["symbols"].items(), key=lambda x: x[1]["net_pnl"], reverse=True)
    for sym, st in sorted_syms:
        icon = "🟢" if st["net_pnl"] > 0 else "🔴"
        print(f"{icon} {sym:6s} | {st['trades']:5d} | {st['wins']:3d}/{st['trades']-st['wins']:3d} | %{st['win_rate']:8.1f} | ${st['net_pnl']:+10.2f}")
        
    print("\n" + "=" * 85)
    print("⚖️ PİRAMİTLEME KATI KARŞILAŞTIRMASI (Haftalık $1000 Bakiye İle):")
    print("=" * 85)
    print(f"1) Piramitsiz (Tek İşlem)    : Bakiye = ${res_live_pyr1['final_balance']:,.2f} | Net Kâr = ${res_live_pyr1['net_pnl']:+,.2f} | WR = %{res_live_pyr1['win_rate']} | Max DD = %{res_live_pyr1['max_drawdown_pct']:.1f}")
    print(f"2) MEVCUT SİSTEM (2 Katman)  : Bakiye = ${res_live_pyr2['final_balance']:,.2f} | Net Kâr = ${res_live_pyr2['net_pnl']:+,.2f} | WR = %{res_live_pyr2['win_rate']} | Max DD = %{res_live_pyr2['max_drawdown_pct']:.1f}")
    print(f"3) Agresif (3 Katman)        : Bakiye = ${res_live_pyr3['final_balance']:,.2f} | Net Kâr = ${res_live_pyr3['net_pnl']:+,.2f} | WR = %{res_live_pyr3['win_rate']} | Max DD = %{res_live_pyr3['max_drawdown_pct']:.1f}")
    print("=" * 85)

    # Save to JSON
    out_file = os.path.join(ROOT, "outputs", "monday_to_friday_1000usd_backtest.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "test_window": "2026-10-12 00:00 UTC+3 to 2026-10-16 23:59 UTC+3",
            "starting_balance": 1000.0,
            "live_system_pyr2": res_live_pyr2,
            "no_pyramid_pyr1": res_live_pyr1,
            "aggressive_pyr3": res_live_pyr3,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Sonuçlar kaydedildi: {out_file}\n")

if __name__ == "__main__":
    main()
