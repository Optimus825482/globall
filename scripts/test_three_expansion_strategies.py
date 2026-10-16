"""Multi-Strategy Expansion Backtester & Simulator (7 Days 5M Data).

Evaluates 3 potential new / revitalized strategy engines:
1. Strategy 1: New York Opening Range Breakout (NY ORB) on US30, USTEC, XAUUSD.
2. Strategy 2: Fair Value Gap (FVG) / Imbalance Mitigation Pullback Engine.
3. Strategy 3: S3 SuperTrend Pullback Engine Revitalized with Smart Quality Gates.

Outputs performance metrics (Win Rate, Total Trades, Net PnL, Profit Factor, Drawdown).
"""
import os
import sys
import json
import datetime
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.routers import forex
from scripts.replay_24h_dss_vs_baseline import fetch_symbol_bars

TEST_SYMBOLS = [
    ("BTCUSD", "BTC-USD", 0.02),
    ("XAUUSD", "GC=F", 0.07),
    ("US30", "YM=F", 0.02),
    ("USTEC", "NQ=F", 0.02),
    ("EURUSD", "EURUSD=X", 0.15),
    ("GBPUSD", "GBPUSD=X", 0.15),
]

def load_data_for_symbols():
    data = {}
    for sym, yf, r_pct in TEST_SYMBOLS:
        bars = fetch_symbol_bars(sym, yf, days=7)
        if bars and len(bars) >= 100:
            data[sym] = (bars, r_pct)
            print(f"✅ {sym}: {len(bars)} bar yüklendi.")
        else:
            print(f"❌ {sym}: Veri yüklenemedi!")
    return data


# ==============================================================================
# STRATEGY 1: NEW YORK OPENING RANGE BREAKOUT (NY ORB)
# ==============================================================================
def run_ny_orb_simulation(data: Dict[str, Tuple[List[Any], float]]) -> Dict[str, Any]:
    print("\n" + "="*80)
    print("🚀 [STRATEJİ 1] NEW YORK OPENING RANGE BREAKOUT (NY ORB) TESTİ (13:30 - 16:30 UTC)")
    print("="*80)

    results = {}
    target_syms = ["US30", "USTEC", "XAUUSD"]

    for sym in target_syms:
        if sym not in data:
            continue
        bars, risk_pct = data[sym]
        spec = forex.get_symbol_trading_specs(sym)
        pip_size = spec["pip_size"]
        pip_val = spec["pip_val"]
        digits = spec["digits"]

        balance = 1000.0
        trades = []
        positions = []
        day_trades = {}  # {day_str: count}
        orb_boxes = {}   # {day_str: {"hi": float, "lo": float, "built": bool}}

        for idx in range(35, len(bars)):
            cur_bar = bars[idx]
            cur_ts = cur_bar[0]
            cur_price = cur_bar[4]
            dt = datetime.datetime.fromtimestamp(cur_ts, datetime.timezone.utc)
            day_str = dt.strftime("%Y-%m-%d")
            hour = dt.hour
            minute = dt.minute

            # Build ORB Box between 13:30 and 13:45 UTC (First 15-minute bar of Wall Street open)
            if day_str not in orb_boxes:
                orb_boxes[day_str] = {"hi": 0.0, "lo": 0.0, "built": False, "bars": []}

            box = orb_boxes[day_str]
            if hour == 13 and (30 <= minute < 45):
                box["bars"].append(cur_bar)
                box["hi"] = max(box["hi"] if box["hi"] > 0 else cur_bar[2], cur_bar[2])
                box["lo"] = min(box["lo"] if box["lo"] > 0 else cur_bar[3], cur_bar[3])
                if minute == 40:  # 13:40 candle ends at 13:45
                    box["built"] = True

            # 1. Update Positions
            still_open = []
            for pos in positions:
                b_h, b_l, b_c = cur_bar[2], cur_bar[3], cur_bar[4]
                closed = False
                exit_price = 0.0
                exit_reason = ""

                if pos["direction"] == "BUY":
                    if b_l <= pos["sl_price"]:
                        closed = True
                        exit_price = pos["sl_price"]
                        exit_reason = "SL_HIT"
                    elif b_h >= pos["tp_price"]:
                        closed = True
                        exit_price = pos["tp_price"]
                        exit_reason = "TP_HIT"
                    else:
                        pnl_p = (b_h - pos["entry_price"]) / pip_size
                        if pnl_p >= pos["sl0_pips"] * 0.40 and not pos["be_locked"]:
                            pos["be_locked"] = True
                            pos["sl_price"] = pos["entry_price"] + (pos["sl0_pips"] * 0.20 * pip_size)
                else:
                    if b_h >= pos["sl_price"]:
                        closed = True
                        exit_price = pos["sl_price"]
                        exit_reason = "SL_HIT"
                    elif b_l <= pos["tp_price"]:
                        closed = True
                        exit_price = pos["tp_price"]
                        exit_reason = "TP_HIT"
                    else:
                        pnl_p = (pos["entry_price"] - b_l) / pip_size
                        if pnl_p >= pos["sl0_pips"] * 0.40 and not pos["be_locked"]:
                            pos["be_locked"] = True
                            pos["sl_price"] = pos["entry_price"] - (pos["sl0_pips"] * 0.20 * pip_size)

                # End of day force close at 21:00 UTC
                if not closed and hour >= 21:
                    closed = True
                    exit_price = cur_price
                    exit_reason = "EOD"

                if closed:
                    pnl_p = (exit_price - pos["entry_price"]) / pip_size if pos["direction"] == "BUY" else (pos["entry_price"] - exit_price) / pip_size
                    pnl_usd = round(pnl_p * pos["lots"] * pip_val, 2)
                    balance = round(balance + pnl_usd, 2)
                    pos["pnl_usd"] = pnl_usd
                    pos["exit_reason"] = exit_reason
                    trades.append(pos)
                else:
                    still_open.append(pos)
            positions = still_open

            # 2. Check Breakout Entry (Window: 13:45 to 16:30 UTC)
            if box["built"] and box["hi"] > box["lo"] and day_trades.get(day_str, 0) == 0 and len(positions) == 0:
                in_window = (hour == 13 and minute >= 45) or (14 <= hour < 16) or (hour == 16 and minute <= 30)
                if in_window:
                    bar_body = abs(cur_bar[4] - cur_bar[1])
                    bar_span = max(1e-5, cur_bar[2] - cur_bar[3])
                    body_ratio = bar_body / bar_span

                    action = None
                    if cur_price > box["hi"]:
                        action = "BUY"
                    elif cur_price < box["lo"]:
                        action = "SELL"

                    if action and body_ratio >= 0.30:
                        box_size_pips = (box["hi"] - box["lo"]) / pip_size
                        sl_p = max(spec["sl_pips"] * 0.6, min(spec["sl_pips"] * 1.5, box_size_pips * 0.75))
                        tp_p = sl_p * 1.8

                        risk_usd = balance * risk_pct
                        raw_lots = risk_usd / (sl_p * pip_val)
                        lots = round(max(0.01, min(10.0, raw_lots)), 2)

                        sl_px = cur_price - (sl_p * pip_size) if action == "BUY" else cur_price + (sl_p * pip_size)
                        tp_px = cur_price + (tp_p * pip_size) if action == "BUY" else cur_price - (tp_p * pip_size)

                        positions.append({
                            "symbol": sym,
                            "direction": action,
                            "lots": lots,
                            "entry_price": cur_price,
                            "sl_price": round(sl_px, digits),
                            "tp_price": round(tp_px, digits),
                            "sl0_pips": sl_p,
                            "be_locked": False,
                        })
                        day_trades[day_str] = 1

        wins = [t for t in trades if t["pnl_usd"] > 0]
        losses = [t for t in trades if t["pnl_usd"] < 0]
        tot_pnl = round(sum(t["pnl_usd"] for t in trades), 2)
        wr = round(len(wins) / len(trades) * 100, 1) if trades else 0.0
        gross_win = sum(t["pnl_usd"] for t in wins)
        gross_loss = abs(sum(t["pnl_usd"] for t in losses))
        pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else 99.0

        results[sym] = {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": wr,
            "net_pnl": tot_pnl,
            "profit_factor": pf,
        }
        print(f"  {sym:8s}: {len(trades):2d} işlem | {len(wins):2d} W / {len(losses):2d} L | WR: %{wr:4.1f} | Net PnL: ${tot_pnl:+7.2f} | PF: {pf:4.2f}")

    return results


# ==============================================================================
# STRATEGY 2: FAIR VALUE GAP (FVG) MITIGATION PULLBACK ENGINE
# ==============================================================================
def run_fvg_pullback_simulation(data: Dict[str, Tuple[List[Any], float]]) -> Dict[str, Any]:
    print("\n" + "="*80)
    print("🚀 [STRATEJİ 2] FAIR VALUE GAP (FVG) MITIGATION PULLBACK TESTİ (Tüm Varlıklar)")
    print("="*80)

    results = {}

    for sym, (bars, risk_pct) in data.items():
        spec = forex.get_symbol_trading_specs(sym)
        pip_size = spec["pip_size"]
        pip_val = spec["pip_val"]
        digits = spec["digits"]

        balance = 1000.0
        trades = []
        positions = []
        active_fvg = None  # {"type": "BULLISH_FVG", "top": float, "bottom": float, "created_idx": int}

        for idx in range(35, len(bars)):
            cur_bar = bars[idx]
            cur_ts = cur_bar[0]
            cur_price = cur_bar[4]

            # 1. Update Positions
            still_open = []
            for pos in positions:
                b_h, b_l, b_c = cur_bar[2], cur_bar[3], cur_bar[4]
                closed = False
                exit_price = 0.0
                exit_reason = ""

                if pos["direction"] == "BUY":
                    if b_l <= pos["sl_price"]:
                        closed = True
                        exit_price = pos["sl_price"]
                        exit_reason = "SL_HIT"
                    elif b_h >= pos["tp_price"]:
                        closed = True
                        exit_price = pos["tp_price"]
                        exit_reason = "TP_HIT"
                    else:
                        pnl_p = (b_h - pos["entry_price"]) / pip_size
                        if pnl_p >= pos["sl0_pips"] * 0.40 and not pos["be_locked"]:
                            pos["be_locked"] = True
                            pos["sl_price"] = pos["entry_price"] + (pos["sl0_pips"] * 0.20 * pip_size)
                else:
                    if b_h >= pos["sl_price"]:
                        closed = True
                        exit_price = pos["sl_price"]
                        exit_reason = "SL_HIT"
                    elif b_l <= pos["tp_price"]:
                        closed = True
                        exit_price = pos["tp_price"]
                        exit_reason = "TP_HIT"
                    else:
                        pnl_p = (pos["entry_price"] - b_l) / pip_size
                        if pnl_p >= pos["sl0_pips"] * 0.40 and not pos["be_locked"]:
                            pos["be_locked"] = True
                            pos["sl_price"] = pos["entry_price"] - (pos["sl0_pips"] * 0.20 * pip_size)

                if closed:
                    pnl_p = (exit_price - pos["entry_price"]) / pip_size if pos["direction"] == "BUY" else (pos["entry_price"] - exit_price) / pip_size
                    pnl_usd = round(pnl_p * pos["lots"] * pip_val, 2)
                    balance = round(balance + pnl_usd, 2)
                    pos["pnl_usd"] = pnl_usd
                    pos["exit_reason"] = exit_reason
                    trades.append(pos)
                else:
                    still_open.append(pos)
            positions = still_open

            # 2. Detect 3-Bar FVG
            # Bar -3, Bar -2, Bar -1
            b_prev2 = bars[idx - 2]
            b_prev1 = bars[idx - 1]
            b_now = cur_bar

            # Bullish FVG: Bar -2 leaves gap between Bar -3 High and Bar Now Low
            if b_prev2[2] < b_now[3]:
                active_fvg = {
                    "type": "BULLISH_FVG",
                    "top": b_now[3],
                    "bottom": b_prev2[2],
                    "created_idx": idx,
                }
            elif b_prev2[3] > b_now[2]:
                active_fvg = {
                    "type": "BEARISH_FVG",
                    "top": b_prev2[3],
                    "bottom": b_now[2],
                    "created_idx": idx,
                }

            # 3. Check Pullback Entry into Active FVG (within 8 bars)
            if active_fvg and len(positions) == 0:
                age = idx - active_fvg["created_idx"]
                if age > 8:
                    active_fvg = None
                    continue

                action = None
                if active_fvg["type"] == "BULLISH_FVG":
                    # Pullback into gap zone
                    if b_now[3] <= active_fvg["top"] and cur_price >= active_fvg["bottom"]:
                        action = "BUY"
                elif active_fvg["type"] == "BEARISH_FVG":
                    if b_now[2] >= active_fvg["bottom"] and cur_price <= active_fvg["top"]:
                        action = "SELL"

                if action:
                    bar_body = abs(cur_bar[4] - cur_bar[1])
                    bar_span = max(1e-5, cur_bar[2] - cur_bar[3])
                    body_ratio = bar_body / bar_span

                    sub_closes = [b[4] for b in bars[max(0, idx - 30):idx + 1]]
                    ema21 = float(np.mean(sub_closes[-21:])) if len(sub_closes) >= 21 else cur_price
                    dist_ema21_pct = ((cur_price - ema21) / ema21) * 100.0 if ema21 else 0.0

                    dt = datetime.datetime.fromtimestamp(cur_ts, datetime.timezone.utc)
                    ok_asset, _ = forex.asset_quality_gate(sym, action, body_ratio, dist_ema21_pct, adx=22.0, hour_utc=dt.hour)

                    if ok_asset:
                        sl_p = spec["sl_pips"]
                        tp_p = sl_p * 1.8
                        risk_usd = balance * risk_pct
                        raw_lots = risk_usd / (sl_p * pip_val)
                        lots = round(max(0.01, min(10.0, raw_lots)), 2)

                        sl_px = cur_price - (sl_p * pip_size) if action == "BUY" else cur_price + (sl_p * pip_size)
                        tp_px = cur_price + (tp_p * pip_size) if action == "BUY" else cur_price - (tp_p * pip_size)

                        positions.append({
                            "symbol": sym,
                            "direction": action,
                            "lots": lots,
                            "entry_price": cur_price,
                            "sl_price": round(sl_px, digits),
                            "tp_price": round(tp_px, digits),
                            "sl0_pips": sl_p,
                            "be_locked": False,
                        })
                        active_fvg = None  # FVG mitigated

        wins = [t for t in trades if t["pnl_usd"] > 0]
        losses = [t for t in trades if t["pnl_usd"] < 0]
        tot_pnl = round(sum(t["pnl_usd"] for t in trades), 2)
        wr = round(len(wins) / len(trades) * 100, 1) if trades else 0.0
        gross_win = sum(t["pnl_usd"] for t in wins)
        gross_loss = abs(sum(t["pnl_usd"] for t in losses))
        pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else 99.0

        results[sym] = {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": wr,
            "net_pnl": tot_pnl,
            "profit_factor": pf,
        }
        print(f"  {sym:8s}: {len(trades):3d} işlem | {len(wins):2d} W / {len(losses):2d} L | WR: %{wr:4.1f} | Net PnL: ${tot_pnl:+7.2f} | PF: {pf:4.2f}")

    return results


# ==============================================================================
# STRATEGY 3: REVITALIZED S3 SUPERTREND PULLBACK ENGINE
# ==============================================================================
def run_s3_supertrend_simulation(data: Dict[str, Tuple[List[Any], float]]) -> Dict[str, Any]:
    print("\n" + "="*80)
    print("🚀 [STRATEJİ 3] S3 SUPERTREND PULLBACK + AKILLI KALKAN MOTORU TESTİ")
    print("="*80)

    results = {}

    for sym, (bars, risk_pct) in data.items():
        spec = forex.get_symbol_trading_specs(sym)
        pip_size = spec["pip_size"]
        pip_val = spec["pip_val"]
        digits = spec["digits"]

        balance = 1000.0
        trades = []
        positions = []

        for idx in range(35, len(bars)):
            cur_bar = bars[idx]
            cur_ts = cur_bar[0]
            cur_price = cur_bar[4]

            # 1. Update Positions
            still_open = []
            for pos in positions:
                b_h, b_l, b_c = cur_bar[2], cur_bar[3], cur_bar[4]
                closed = False
                exit_price = 0.0
                exit_reason = ""

                if pos["direction"] == "BUY":
                    if b_l <= pos["sl_price"]:
                        closed = True
                        exit_price = pos["sl_price"]
                        exit_reason = "SL_HIT"
                    elif b_h >= pos["tp_price"]:
                        closed = True
                        exit_price = pos["tp_price"]
                        exit_reason = "TP_HIT"
                    else:
                        pnl_p = (b_h - pos["entry_price"]) / pip_size
                        if pnl_p >= pos["sl0_pips"] * 0.40 and not pos["be_locked"]:
                            pos["be_locked"] = True
                            pos["sl_price"] = pos["entry_price"] + (pos["sl0_pips"] * 0.20 * pip_size)
                else:
                    if b_h >= pos["sl_price"]:
                        closed = True
                        exit_price = pos["sl_price"]
                        exit_reason = "SL_HIT"
                    elif b_l <= pos["tp_price"]:
                        closed = True
                        exit_price = pos["tp_price"]
                        exit_reason = "TP_HIT"
                    else:
                        pnl_p = (pos["entry_price"] - b_l) / pip_size
                        if pnl_p >= pos["sl0_pips"] * 0.40 and not pos["be_locked"]:
                            pos["be_locked"] = True
                            pos["sl_price"] = pos["entry_price"] - (pos["sl0_pips"] * 0.20 * pip_size)

                if closed:
                    pnl_p = (exit_price - pos["entry_price"]) / pip_size if pos["direction"] == "BUY" else (pos["entry_price"] - exit_price) / pip_size
                    pnl_usd = round(pnl_p * pos["lots"] * pip_val, 2)
                    balance = round(balance + pnl_usd, 2)
                    pos["pnl_usd"] = pnl_usd
                    pos["exit_reason"] = exit_reason
                    trades.append(pos)
                else:
                    still_open.append(pos)
            positions = still_open

            # 2. Check S3 Entry
            if len(positions) == 0:
                sub_bars = bars[max(0, idx - 100):idx + 1]
                closes = [b[4] for b in sub_bars]
                highs = [b[2] for b in sub_bars]
                lows = [b[3] for b in sub_bars]
                opens = [b[1] for b in sub_bars]

                tech = forex._compute_technical_indicators(closes, highs, lows, opens, sym)
                if not tech:
                    continue

                st_dir = int(tech.get("supertrend_dir", 0))
                rsi = float(tech.get("rsi", 50.0))
                adx = float(tech.get("adx", 20.0))
                dist_ema21 = float(tech.get("dist_ema21_pct", 0.0))
                body_ratio = float(tech.get("body_ratio", 0.5))

                # S3 Pullback condition:
                # ST is bullish, RSI healthy pullback zone (38 <= RSI <= 58), price bouncing above EMA21
                action = None
                if st_dir == 1 and 38.0 <= rsi <= 55.0 and dist_ema21 > -0.20:
                    action = "BUY"
                elif st_dir == -1 and 45.0 <= rsi <= 62.0 and dist_ema21 < 0.20:
                    action = "SELL"

                if action:
                    dt = datetime.datetime.fromtimestamp(cur_ts, datetime.timezone.utc)
                    ok_asset, _ = forex.asset_quality_gate(sym, action, body_ratio, dist_ema21, adx, hour_utc=dt.hour)
                    if ok_asset:
                        sl_p = spec["sl_pips"]
                        tp_p = sl_p * 1.8
                        risk_usd = balance * risk_pct
                        raw_lots = risk_usd / (sl_p * pip_val)
                        lots = round(max(0.01, min(10.0, raw_lots)), 2)

                        sl_px = cur_price - (sl_p * pip_size) if action == "BUY" else cur_price + (sl_p * pip_size)
                        tp_px = cur_price + (tp_p * pip_size) if action == "BUY" else cur_price - (tp_p * pip_size)

                        positions.append({
                            "symbol": sym,
                            "direction": action,
                            "lots": lots,
                            "entry_price": cur_price,
                            "sl_price": round(sl_px, digits),
                            "tp_price": round(tp_px, digits),
                            "sl0_pips": sl_p,
                            "be_locked": False,
                        })

        wins = [t for t in trades if t["pnl_usd"] > 0]
        losses = [t for t in trades if t["pnl_usd"] < 0]
        tot_pnl = round(sum(t["pnl_usd"] for t in trades), 2)
        wr = round(len(wins) / len(trades) * 100, 1) if trades else 0.0
        gross_win = sum(t["pnl_usd"] for t in wins)
        gross_loss = abs(sum(t["pnl_usd"] for t in losses))
        pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else 99.0

        results[sym] = {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": wr,
            "net_pnl": tot_pnl,
            "profit_factor": pf,
        }
        print(f"  {sym:8s}: {len(trades):3d} işlem | {len(wins):2d} W / {len(losses):2d} L | WR: %{wr:4.1f} | Net PnL: ${tot_pnl:+7.2f} | PF: {pf:4.2f}")

    return results


def main():
    print("⏳ Canlı piyasa verileri çekiliyor (7 Günlük 5M Barlar)...")
    data = load_data_for_symbols()
    if not data:
        print("❌ Veri temin edilemedi!")
        return

    r1 = run_ny_orb_simulation(data)
    r2 = run_fvg_pullback_simulation(data)
    r3 = run_s3_supertrend_simulation(data)

    out_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "three_expansion_strategies_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"ny_orb": r1, "fvg_pullback": r2, "s3_revitalized": r3}, f, indent=2, ensure_ascii=False)

    print("\n" + "="*80)
    print(f"🎉 TÜM 3 STRATEJİNİN TESTİ TAMAMLANDI! Sonuçlar: {out_file}")
    print("="*80)


if __name__ == "__main__":
    main()
