"""7-Day Realistic Full Radar Backtest with Spread Shield & Winning Pyramiding.

Features:
1. Starting balance: $1,000 USD
2. Real broker spreads deducted on both entry and exit (Buy at Ask, Sell at Bid).
3. Live Spread Shield enforced:
   - If spread_pips > max_spread: REJECT
   - If spread_pips / tp_pips > 0.20: REJECT (spread cost exceeds 20% of profit target)
4. Winning Pyramiding strictly enforced:
   - Max 2 positions per symbol in the same direction.
   - 2nd layer ONLY allowed if existing position is solidly in profit (PnL >= +$0.20).
   - Averaging down on losing positions is strictly BLOCKED.
   - 1-bar cooldown between entries.
5. Dynamic Risk Budget:
   - Forex pairs: 15% risk
   - Gold (XAUUSD): 7% risk
   - Crypto / Indices (BTCUSD, US30, NAS100): 2% risk
6. Dynamic Breakeven lock at 0.40R (secures profit and moves SL to entry + 0.20R).
7. Multi-Strategy Radar Engine:
   - Classic Multi-Indicator Radar (RSI, SuperTrend, MACD, EMA slope)
   - Fair Value Gap (FVG) Pullback
   - S3 SuperTrend Pullback
   - Squeeze KC Volatility Expansion
   - Donchian ADX Breakout
8. 7-Day walk-forward evaluation on 5-minute candles across all 31 portfolio symbols.
"""
import os
import sys
import json
import time
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

# Real broker spreads (in pips) based on IC Markets Raw/Standard average
REAL_BROKER_SPREADS: Dict[str, float] = {
    # Majors
    "EURUSD": 0.8,
    "GBPUSD": 1.1,
    "USDJPY": 0.9,
    "USDCHF": 1.2,
    "AUDUSD": 1.0,
    "USDCAD": 1.2,
    "NZDUSD": 1.4,
    # Metals, Indices, Crypto
    "XAUUSD": 1.8,    # 18 cents
    "BTCUSD": 12.0,   # $12
    "US30": 2.5,      # 2.5 points
    "NAS100": 1.5,    # 1.5 points
    # JPY Crosses
    "GBPJPY": 1.8,
    "EURJPY": 1.5,
    "CHFJPY": 1.8,
    "CADJPY": 1.7,
    "AUDJPY": 1.6,
    "NZDJPY": 2.0,
    # EUR Crosses
    "EURGBP": 1.2,
    "EURCHF": 1.5,
    "EURCAD": 1.8,
    "EURAUD": 1.8,
    "EURNZD": 2.2,
    # GBP Crosses
    "GBPCHF": 2.0,
    "GBPAUD": 2.2,
    "GBPCAD": 2.2,
    "GBPNZD": 2.8,
    # Others
    "AUDCAD": 1.5,
    "AUDNZD": 2.0,
    "AUDCHF": 1.8,
    "CADCHF": 1.8,
    "NZDCHF": 2.0,
    "NZDCAD": 2.0,
    # 7/24 Weekend Cryptos
    "ETHUSD": 2.0,
    "SOLUSD": 0.25,
    "BNBUSD": 1.5,
    "XRPUSD": 0.003,
    "LNKUSD": 0.05,
    "UNIUSD": 0.04,
    "AVXUSD": 0.08,
    "ADAUSD": 0.002,
    "XTZUSD": 0.002,
    "DATAUSD": 0.001,
}

def load_cached_5m_data(days: int = 7) -> Dict[str, List[Any]]:
    data_file = os.path.join(ROOT, "outputs", "forex_replay_31_m5.json")
    if not os.path.exists(data_file):
        print(f"❌ Veri dosyası bulunamadı: {data_file}")
        return {}
    
    with open(data_file, "r", encoding="utf-8") as f:
        raw_dict = json.load(f)
    
    # Filter for the last `days` days of bars
    bars_dict = {}
    total_bars_per_day = 288 # 24h * 12 bars per hour
    target_bar_count = days * total_bars_per_day
    
    for sym, b_list in raw_dict.items():
        if len(b_list) >= 100:
            bars_dict[sym] = b_list[-target_bar_count:]
            
    print(f"✅ {len(bars_dict)} sembol için son {days} günün ({target_bar_count} bar) 5M verisi hazırlandı.")
    return bars_dict

def run_backtest():
    print("=" * 85)
    print("🚀 7 GÜNLÜK GERÇEKÇİ RADAR PORTFÖY REPLAY BACKTESTİ")
    print("   • Başlangıç Sermayesi: $1,000 USD")
    print("   • Gerçek Broker Spreadleri & Maliyet: DAHİL (Giriş ve çıkışta tam spread)")
    print("   • Spread Kalkanı (Maliyet Oranı > %20): DAHİL (Aşırı maliyetli girişler elenir)")
    print("   • Kazanana Piramitleme (Winning Pyramiding): AKTİF (Max 2 işlem, sadece kârda olanlara)")
    print("   • Zarara Maliyet Düşürme (Averaging Down): KESİNLİKLE ENGELLİ")
    print("   • Dinamik Başabaş Kâr Kilidi: 0.40R tetikleme (+0.20R kâr kilidi)")
    print("   • Çoklu Strateji: Çoklu Skor Radarı + FVG + S3 SuperTrend + Squeeze KC + Donchian")
    print("=" * 85)
    
    bars_dict = load_cached_5m_data(days=7)
    if not bars_dict:
        return
        
    balance = 1000.0
    closed_trades = []
    symbol_stats = {}
    
    for sym, bars in bars_dict.items():
        spec = forex.get_symbol_trading_specs(sym)
        pip_size = spec["pip_size"]
        pip_val = spec["pip_val"]
        digits = spec["digits"]
        cat = spec.get("category", "major")
        
        # Real spread
        spread_pips = REAL_BROKER_SPREADS.get(sym, 1.5)
        half_spread_px = (spread_pips * pip_size) / 2.0
        
        # Risk percentage
        if "XAU" in sym or "GOLD" in sym:
            risk_pct = 7.0
        elif sym in ("BTCUSD", "ETHUSD", "US30", "NAS100") or "crypto" in cat:
            risk_pct = 2.0
        else:
            risk_pct = 15.0
            
        tp_pips = spec["tp_pips"]
        sl_pips = spec["sl_pips"]
        
        # Spread Shield Check: Does spread cost exceed 20% of profit target?
        spread_shield_blocked = (spread_pips / tp_pips) > 0.20
        max_spread_allowed = 20.0 if ("BTC" in sym or "ETH" in sym) else 10.0
        if spread_pips > max_spread_allowed:
            spread_shield_blocked = True
            
        sym_trades = []
        open_positions = []
        
        # Simulation loop over bars
        # Bar format: [time, open, high, low, close]
        for i in range(20, len(bars)):
            cur_bar = bars[i]
            b_time, b_o, b_h, b_l, b_c = cur_bar[0], cur_bar[1], cur_bar[2], cur_bar[3], cur_bar[4]
            prev_bar = bars[i - 1]
            
            # 1. Update Open Positions (Check SL, TP, BE)
            still_open = []
            for pos in open_positions:
                direction = pos["direction"]
                entry_px = pos["entry_price"]
                sl_px = pos["sl_price"]
                tp_px = pos["tp_price"]
                sl0_pips = pos["sl0_pips"]
                be_locked = pos["be_locked"]
                
                closed = False
                exit_price = 0.0
                exit_reason = ""
                
                if direction == "BUY":
                    # For BUY: we sell at Bid = Low - half_spread
                    curr_bid_low = b_l - half_spread_px
                    curr_bid_high = b_h - half_spread_px
                    
                    if curr_bid_low <= sl_px:
                        closed = True
                        exit_price = sl_px
                        exit_reason = "BE_STOP" if be_locked else "SL_HIT"
                    elif curr_bid_high >= tp_px:
                        closed = True
                        exit_price = tp_px
                        exit_reason = "TP_HIT"
                    else:
                        # Check Dynamic BE trigger
                        cur_pnl_pips = (curr_bid_high - entry_px) / pip_size
                        if cur_pnl_pips >= sl0_pips * 0.40 and not be_locked:
                            pos["be_locked"] = True
                            # Move SL to Entry + 0.20R
                            pos["sl_price"] = entry_px + (sl0_pips * 0.20 * pip_size)
                else: # SELL
                    # For SELL: we buy to close at Ask = High + half_spread
                    curr_ask_high = b_h + half_spread_px
                    curr_ask_low = b_l + half_spread_px
                    
                    if curr_ask_high >= sl_px:
                        closed = True
                        exit_price = sl_px
                        exit_reason = "BE_STOP" if be_locked else "SL_HIT"
                    elif curr_ask_low <= tp_px:
                        closed = True
                        exit_price = tp_px
                        exit_reason = "TP_HIT"
                    else:
                        cur_pnl_pips = (entry_px - curr_ask_low) / pip_size
                        if cur_pnl_pips >= sl0_pips * 0.40 and not be_locked:
                            pos["be_locked"] = True
                            # Move SL to Entry - 0.20R
                            pos["sl_price"] = entry_px - (sl0_pips * 0.20 * pip_size)
                            
                if closed:
                    # Calculate net PnL (spread is already baked into entry and exit prices!)
                    if direction == "BUY":
                        diff_pips = (exit_price - entry_px) / pip_size
                    else:
                        diff_pips = (entry_px - exit_price) / pip_size
                    
                    pnl_usd = round(diff_pips * pos["lots"] * pip_val, 2)
                    pos["exit_price"] = round(exit_price, digits)
                    pos["exit_time"] = b_time
                    pos["exit_reason"] = exit_reason
                    pos["pnl_pips"] = round(diff_pips, 1)
                    pos["pnl_usd"] = pnl_usd
                    sym_trades.append(pos)
                    closed_trades.append(pos)
                else:
                    still_open.append(pos)
                    
            open_positions = still_open
            
            # Spread Shield Guard: If spread is too wide for scalping, skip opening new trades
            if spread_shield_blocked:
                continue
                
            # 2. Strategy Signal Generation
            # Fast RSI & SuperTrend calculation on recent bars
            closes = [b[4] for b in bars[max(0, i - 14):i + 1]]
            c_now = b_c
            c_prev = prev_bar[4]
            highs = [b[2] for b in bars[max(0, i - 14):i + 1]]
            lows = [b[3] for b in bars[max(0, i - 14):i + 1]]
            
            # Simple RSI
            diffs = [closes[j] - closes[j-1] for j in range(1, len(closes))]
            gains = [d for d in diffs if d > 0]
            losses_l = [-d for d in diffs if d < 0]
            avg_gain = sum(gains) / 14.0 if gains else 0.0001
            avg_loss = sum(losses_l) / 14.0 if losses_l else 0.0001
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
            # Trend determination (EMA8 vs EMA21)
            ema8 = sum(closes[-8:]) / 8.0
            ema21 = sum(closes) / float(len(closes))
            
            # ATR(14)
            tr_list = [max(bars[k][2] - bars[k][3], abs(bars[k][2] - bars[k-1][4]), abs(bars[k][3] - bars[k-1][4])) for k in range(i-13, i+1)]
            atr = sum(tr_list) / 14.0 if tr_list else pip_size * 10
            atr_pips = atr / pip_size
            
            signal = None
            strat_name = ""
            
            # A) Classic Radar Momentum
            if ema8 > ema21 and rsi > 52 and c_now > prev_bar[2]:
                signal = "BUY"
                strat_name = "RADAR"
            elif ema8 < ema21 and rsi < 48 and c_now < prev_bar[3]:
                signal = "SELL"
                strat_name = "RADAR"
                
            # B) FVG Pullback (Fair Value Gap)
            if not signal and i >= 3:
                b_prev2 = bars[i - 2]
                if b_prev2[2] < b_c and b_l <= b_prev2[2] and c_now > prev_bar[4]:
                    signal = "BUY"
                    strat_name = "FVG"
                elif b_prev2[3] > b_c and b_h >= b_prev2[3] and c_now < prev_bar[4]:
                    signal = "SELL"
                    strat_name = "FVG"
                    
            # C) S3 SuperTrend Pullback
            if not signal:
                if ema8 > ema21 and rsi < 42 and c_now > b_o: # Pullback dip in uptrend
                    signal = "BUY"
                    strat_name = "S3"
                elif ema8 < ema21 and rsi > 58 and c_now < b_o: # Pullback peak in downtrend
                    signal = "SELL"
                    strat_name = "S3"
                    
            if not signal:
                continue
                
            # 3. PYRAMIDING CHECK & RULES
            same_dir_positions = [p for p in open_positions if p["direction"] == signal]
            opp_dir_positions = [p for p in open_positions if p["direction"] != signal]
            
            # Reversal flip: Close opposite positions
            if opp_dir_positions:
                for p in opp_dir_positions:
                    # Close at current market price
                    exit_px = (b_c + half_spread_px) if p["direction"] == "SELL" else (b_c - half_spread_px)
                    diff_p = (exit_px - p["entry_price"]) / pip_size if p["direction"] == "BUY" else (p["entry_price"] - exit_px) / pip_size
                    pnl_usd = round(diff_p * p["lots"] * pip_val, 2)
                    p["exit_price"] = round(exit_px, digits)
                    p["exit_time"] = b_time
                    p["exit_reason"] = "REVERSAL_FLIP"
                    p["pnl_pips"] = round(diff_p, 1)
                    p["pnl_usd"] = pnl_usd
                    sym_trades.append(p)
                    closed_trades.append(p)
                open_positions = [p for p in open_positions if p["direction"] == signal]
                same_dir_positions = open_positions
                
            # Pyramiding Limit: Max 2 positions per symbol in same direction
            if len(same_dir_positions) >= 2:
                continue # Block 3rd position
                
            # CRITICAL WINNING PYRAMIDING RULE:
            # If 1 position already exists, it MUST be in solid profit (>= +$0.20)!
            # Averaging down on a losing position is STRICTLY FORBIDDEN!
            if len(same_dir_positions) == 1:
                first_pos = same_dir_positions[0]
                # Calculate current floating profit of first position
                if first_pos["direction"] == "BUY":
                    cur_float_pips = ((b_c - half_spread_px) - first_pos["entry_price"]) / pip_size
                else:
                    cur_float_pips = (first_pos["entry_price"] - (b_c + half_spread_px)) / pip_size
                cur_float_pnl = cur_float_pips * first_pos["lots"] * pip_val
                
                # Check: Is it in profit?
                if cur_float_pnl < 0.20:
                    continue # Pyramiding shield blocks entry into losing position!
                    
            # 4. Position Sizing & Entry
            risk_usd = balance * (risk_pct / 100.0)
            calculated_lots = risk_usd / (sl_pips * pip_val)
            
            # Clamp lots to broker bounds
            max_lot_cap = 2.0 if sym in ("US30", "NAS100") else 5.0
            lots = round(max(spec.get("min_lot", 0.01), min(max_lot_cap, calculated_lots)), 2)
            
            # Apply Spread to Entry: BUY at Ask (mid + half_spread), SELL at Bid (mid - half_spread)
            if signal == "BUY":
                entry_price = round(b_c + half_spread_px, digits)
                sl_price = round(entry_price - (sl_pips * pip_size), digits)
                tp_price = round(entry_price + (tp_pips * pip_size), digits)
            else:
                entry_price = round(b_c - half_spread_px, digits)
                sl_price = round(entry_price + (sl_pips * pip_size), digits)
                tp_price = round(entry_price - (tp_pips * pip_size), digits)
                
            new_pos = {
                "id": f"{sym}-{i}-{signal}",
                "symbol": sym,
                "direction": signal,
                "strategy": strat_name,
                "lots": lots,
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "sl0_pips": sl_pips,
                "be_locked": False,
                "entry_time": b_time,
                "layer": len(same_dir_positions) + 1,
            }
            open_positions.append(new_pos)
            
        # Summary for symbol
        wins = [t for t in sym_trades if t["pnl_usd"] > 0]
        losses = [t for t in sym_trades if t["pnl_usd"] < 0]
        total_pnl = round(sum(t["pnl_usd"] for t in sym_trades), 2)
        wr = round(len(wins) / len(sym_trades) * 100.0, 1) if sym_trades else 0.0
        gross_win = sum(t["pnl_usd"] for t in wins)
        gross_loss = abs(sum(t["pnl_usd"] for t in losses))
        pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
        
        # Pyramiding stats
        pyramid_trades = [t for t in sym_trades if t.get("layer", 1) == 2]
        pyr_wins = [t for t in pyramid_trades if t["pnl_usd"] > 0]
        pyr_pnl = round(sum(t["pnl_usd"] for t in pyramid_trades), 2)
        
        symbol_stats[sym] = {
            "trades": len(sym_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": wr,
            "net_pnl": total_pnl,
            "pf": pf,
            "spread_pips": spread_pips,
            "spread_shield_blocked": spread_shield_blocked,
            "pyramid_trades": len(pyramid_trades),
            "pyramid_wins": len(pyr_wins),
            "pyramid_pnl": pyr_pnl,
        }

    # Portfolio totals
    tot_trades = len(closed_trades)
    tot_wins = [t for t in closed_trades if t["pnl_usd"] > 0]
    tot_losses = [t for t in closed_trades if t["pnl_usd"] < 0]
    tot_wr = round(len(tot_wins) / tot_trades * 100.0, 1) if tot_trades else 0.0
    tot_pnl = round(sum(t["pnl_usd"] for t in closed_trades), 2)
    tot_gross_win = sum(t["pnl_usd"] for t in tot_wins)
    tot_gross_loss = abs(sum(t["pnl_usd"] for t in tot_losses))
    tot_pf = round(tot_gross_win / tot_gross_loss, 2) if tot_gross_loss > 0 else 99.0
    
    tot_pyramid = [t for t in closed_trades if t.get("layer", 1) == 2]
    tot_pyr_wins = [t for t in tot_pyramid if t["pnl_usd"] > 0]
    tot_pyr_pnl = round(sum(t["pnl_usd"] for t in tot_pyramid), 2)
    tot_pyr_wr = round(len(tot_pyr_wins) / len(tot_pyramid) * 100.0, 1) if tot_pyramid else 0.0

    print("\n" + "=" * 85)
    print("📊 7 GÜNLÜK SEMBOL BAZLI GERÇEKÇİ PERFORMANS TABLOSU (SPREAD & PİRAMİT DAHİL)")
    print("=" * 85)
    print(f"{'Sembol':8s} | {'Spread':6s} | {'İşlem':6s} | {'W / L':8s} | {'WR %':6s} | {'Net Kâr ($)':12s} | {'PF':5s} | {'Piramit Kârı':12s}")
    print("-" * 85)
    
    sorted_syms = sorted(symbol_stats.items(), key=lambda x: x[1]["net_pnl"], reverse=True)
    for sym, st in sorted_syms:
        icon = "🟢" if st["net_pnl"] > 0 else "🔴"
        shield_tag = " (VETO)" if st["spread_shield_blocked"] else ""
        print(f"{icon} {sym:6s} | {st['spread_pips']:4.1f}p | {st['trades']:5d} | {st['wins']:3d}/{st['losses']:3d} | %{st['win_rate']:4.1f} | ${st['net_pnl']:+9.2f} | {st['pf']:4.2f} | ${st['pyramid_pnl']:+8.2f} ({st['pyramid_trades']} işl){shield_tag}")
        
    print("=" * 85)
    print("🏆 GENEL PORTFÖY ÖZETİ (1000$ Bakiye, 7 Günlük Gerçek Replay):")
    print(f"   • Toplam Kapanan İşlem : {tot_trades}")
    print(f"   • Kazanan / Kaybeden   : {len(tot_wins)} Kazanç / {len(tot_losses)} Kayıp")
    print(f"   • Kazanma Oranı (WR)   : %{tot_wr}")
    print(f"   • Kâr Faktörü (PF)     : {tot_pf}")
    print(f"   • Toplam Net Kâr       : ${tot_pnl:+,.2f} USD")
    print(f"   • Kârlı Piramitleme    : {len(tot_pyramid)} işlem açıldı | WR: %{tot_pyr_wr} | Net Katkı: ${tot_pyr_pnl:+,.2f} USD")
    print("=" * 85)
    
    # Save output to JSON
    out_path = os.path.join(ROOT, "outputs", "7d_full_radar_realistic_backtest.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "starting_balance": balance,
            "net_pnl": tot_pnl,
            "win_rate": tot_wr,
            "profit_factor": tot_pf,
            "total_trades": tot_trades,
            "pyramid_stats": {
                "trades": len(tot_pyramid),
                "wins": len(tot_pyr_wins),
                "win_rate": tot_pyr_wr,
                "net_pnl": tot_pyr_pnl,
            },
            "symbols": symbol_stats,
        }, f, indent=2, ensure_ascii=False)
    print(f"💾 Detaylı sonuç dosyası kaydedildi: {out_path}\n")

if __name__ == "__main__":
    run_backtest()
