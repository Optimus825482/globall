"""Deeper Loss Inspection for US30, USTEC, and XAUUSD.
Analyzes:
1. Hourly/Session loss distribution (UTC 00-08 Asia, 08-13 London, 13-21 NY, 21-24 Late).
2. Realistic EMA distance thresholds for high-volatility indices (0.4% - 0.8%).
3. RSI extremity / Counter-trend traps.
4. HTF trend divergence.
"""
import os
import sys
import json
import datetime
from typing import Any, Dict, List
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.app.routers import forex
from scripts.replay_24h_dss_vs_baseline import fetch_symbol_bars

def analyze_symbol(sym: str, yf_sym: str, risk_pct: float):
    bars = fetch_symbol_bars(sym, yf_sym, days=7)
    if not bars:
        return
    spec = forex.get_symbol_trading_specs(sym)
    pip_size = spec["pip_size"]
    pip_val = spec["pip_val"]
    digits = spec["digits"]

    balance = 1000.0
    positions = []
    trades = []
    streak_losses = 0
    cooldown_until = 0.0

    for idx in range(35, len(bars)):
        cur_bar = bars[idx]
        cur_ts = cur_bar[0]
        cur_price = cur_bar[4]

        sub_bars = bars[max(0, idx - 100):idx + 1]
        closes = [b[4] for b in sub_bars]
        highs = [b[2] for b in sub_bars]
        lows = [b[3] for b in sub_bars]
        opens = [b[1] for b in sub_bars]

        tech = forex._compute_technical_indicators(closes, highs, lows, opens, sym)
        if not tech:
            continue

        rsi = float(tech.get("rsi", 50.0))
        adx = float(tech.get("adx", 20.0))
        supertrend_dir = int(tech.get("supertrend_dir", 0))
        action = tech.get("action", "HOLD")
        score = float(tech.get("score", 0.0))
        htf_trend = tech.get("htf_trend", "NEUTRAL")
        atr = float(tech.get("atr_pips", 50.0))

        ema21 = float(tech.get("ema21", cur_price))
        dist_ema21_pct = round(((cur_price - ema21) / ema21) * 100.0, 3) if ema21 else 0.0
        bar_range = cur_bar[2] - cur_bar[3]
        bar_body = abs(cur_bar[4] - cur_bar[1])
        body_ratio = round((bar_body / max(1e-5, bar_range)), 2)
        hour_utc = datetime.datetime.fromtimestamp(cur_ts, datetime.timezone.utc).hour

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
                    exit_reason = "BE_HIT" if (pos["be_locked"] and pos["sl_price"] >= pos["entry_price"]) else "SL_HIT"
                elif b_h >= pos["tp_price"]:
                    closed = True
                    exit_price = pos["tp_price"]
                    exit_reason = "TP_HIT"
                else:
                    pnl_pips = (b_h - pos["entry_price"]) / pip_size
                    be_trigger = max(pos["sl0_pips"] * 0.40, pos["entry_atr"] * 0.8)
                    if pnl_pips >= be_trigger and not pos["be_locked"]:
                        pos["be_locked"] = True
                        lock_pips = max(1.5, pos["sl0_pips"] * 0.20)
                        pos["sl_price"] = round(pos["entry_price"] + (lock_pips * pip_size), digits)
                    if pos["be_locked"] and pnl_pips >= pos["sl0_pips"] * 1.0:
                        trail_sl = round(b_c - (pos["entry_atr"] * 1.0 * pip_size), digits)
                        if trail_sl > pos["sl_price"]:
                            pos["sl_price"] = trail_sl
            else:
                if b_h >= pos["sl_price"]:
                    closed = True
                    exit_price = pos["sl_price"]
                    exit_reason = "BE_HIT" if (pos["be_locked"] and pos["sl_price"] <= pos["entry_price"]) else "SL_HIT"
                elif b_l <= pos["tp_price"]:
                    closed = True
                    exit_price = pos["tp_price"]
                    exit_reason = "TP_HIT"
                else:
                    pnl_pips = (pos["entry_price"] - b_l) / pip_size
                    be_trigger = max(pos["sl0_pips"] * 0.40, pos["entry_atr"] * 0.8)
                    if pnl_pips >= be_trigger and not pos["be_locked"]:
                        pos["be_locked"] = True
                        lock_pips = max(1.5, pos["sl0_pips"] * 0.20)
                        pos["sl_price"] = round(pos["entry_price"] - (lock_pips * pip_size), digits)
                    if pos["be_locked"] and pnl_pips >= pos["sl0_pips"] * 1.0:
                        trail_sl = round(b_c + (pos["entry_atr"] * 1.0 * pip_size), digits)
                        if pos["sl_price"] == 0 or trail_sl < pos["sl_price"]:
                            pos["sl_price"] = trail_sl

            if closed:
                pnl_p = (exit_price - pos["entry_price"]) / pip_size if pos["direction"] == "BUY" else (pos["entry_price"] - exit_price) / pip_size
                pnl_usd = round(pnl_p * pos["lots"] * pip_val, 2)
                balance = round(balance + pnl_usd, 2)

                if pnl_usd < 0 and exit_reason == "SL_HIT":
                    streak_losses += 1
                    if streak_losses >= 2:
                        cooldown_until = cur_ts + 900.0
                        streak_losses = 0
                elif pnl_usd > 0:
                    streak_losses = 0

                pos["exit_price"] = exit_price
                pos["pnl_usd"] = pnl_usd
                pos["exit_reason"] = exit_reason
                pos["duration_bars"] = idx - pos["entry_idx"]
                trades.append(pos)
            else:
                still_open.append(pos)

        positions = still_open

        if len(positions) == 0 and action in ("BUY", "SELL"):
            if cur_ts < cooldown_until:
                continue
            st_aligned = (action == "BUY" and supertrend_dir >= 0) or (action == "SELL" and supertrend_dir <= 0)
            if not st_aligned:
                continue
            req_score = 78.0 if "XAU" in sym else 75.0
            if score < req_score:
                continue

            atr_exits = forex.get_atr_exit_levels(atr, spec["sl_pips"], spec["tp_pips"])
            sl_p = atr_exits["sl_pips"]
            tp_p = max(atr_exits["tp_pips"], sl_p * 1.8)

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
                "entry_time": cur_ts,
                "entry_idx": idx,
                "entry_hour": hour_utc,
                "sl0_pips": sl_p,
                "tp0_pips": tp_p,
                "entry_atr": atr,
                "be_locked": False,
                "score": score,
                "rsi": rsi,
                "adx": adx,
                "body_ratio": body_ratio,
                "dist_ema21_pct": dist_ema21_pct,
                "htf_trend": htf_trend,
            })

    print(f"\n==========================================")
    print(f"📌 {sym} SEANS & FAKTÖR ANALİZİ ({len(trades)} işlem)")
    print(f"==========================================")
    
    # 1. Session Breakdown
    sessions = {
        "Asya (00-08 UTC)": [t for t in trades if 0 <= t["entry_hour"] < 8],
        "Londra (08-13 UTC)": [t for t in trades if 8 <= t["entry_hour"] < 13],
        "NY / Wall Street (13-21 UTC)": [t for t in trades if 13 <= t["entry_hour"] < 21],
        "Gece Kapanış (21-24 UTC)": [t for t in trades if 21 <= t["entry_hour"] < 24],
    }
    for s_name, s_trades in sessions.items():
        s_wins = [t for t in s_trades if t["pnl_usd"] > 0]
        s_wr = round(len(s_wins) / len(s_trades) * 100, 1) if s_trades else 0.0
        s_pnl = round(sum(t["pnl_usd"] for t in s_trades), 2)
        print(f"  {s_name:28s}: {len(s_trades):3d} işlem | {len(s_wins):2d} W / {len(s_trades)-len(s_wins):2d} L | WR: %{s_wr:4.1f} | Net: ${s_pnl:+7.2f}")

    # 2. HTF Trend Alignment
    htf_aligned = [t for t in trades if (t["direction"] == "BUY" and t["htf_trend"] == "BULLISH") or (t["direction"] == "SELL" and t["htf_trend"] == "BEARISH")]
    htf_opposing = [t for t in trades if (t["direction"] == "BUY" and t["htf_trend"] == "BEARISH") or (t["direction"] == "SELL" and t["htf_trend"] == "BULLISH")]
    htf_neutral = [t for t in trades if t["htf_trend"] == "NEUTRAL"]

    print(f"\n  -- HTF (15M) Trend Uyumu --")
    for lbl, group in [("HTF Uyumlu", htf_aligned), ("HTF Zıt", htf_opposing), ("HTF Nötr", htf_neutral)]:
        g_wins = [t for t in group if t["pnl_usd"] > 0]
        g_wr = round(len(g_wins) / len(group) * 100, 1) if group else 0.0
        g_pnl = round(sum(t["pnl_usd"] for t in group), 2)
        print(f"  {lbl:28s}: {len(group):3d} işlem | {len(g_wins):2d} W / {len(group)-len(g_wins):2d} L | WR: %{g_wr:4.1f} | Net: ${g_pnl:+7.2f}")

    # 3. Wider Grid Simulation (Appropriate for indices)
    print(f"\n  -- Optimize Grid Testleri --")
    grid_tests = [
        {"name": "Mevcut", "filter": lambda t: True},
        {"name": "Gövde >= 0.30", "filter": lambda t: t["body_ratio"] >= 0.30},
        {"name": "Gövde >= 0.35", "filter": lambda t: t["body_ratio"] >= 0.35},
        {"name": "Gövde>=0.30 + dist<=0.50%", "filter": lambda t: t["body_ratio"] >= 0.30 and abs(t["dist_ema21_pct"]) <= 0.50},
        {"name": "Gövde>=0.30 + dist<=0.40%", "filter": lambda t: t["body_ratio"] >= 0.30 and abs(t["dist_ema21_pct"]) <= 0.40},
        {"name": "Gövde>=0.30 + dist<=0.30%", "filter": lambda t: t["body_ratio"] >= 0.30 and abs(t["dist_ema21_pct"]) <= 0.30},
        {"name": "Gövde>=0.30 + ADX>=20", "filter": lambda t: t["body_ratio"] >= 0.30 and t["adx"] >= 20.0},
        {"name": "Gövde>=0.30 + dist<=0.50% + ADX>=18", "filter": lambda t: t["body_ratio"] >= 0.30 and abs(t["dist_ema21_pct"]) <= 0.50 and t["adx"] >= 18.0},
        {"name": "HTF Zıt İşlemleri Engelle", "filter": lambda t: not ((t["direction"] == "BUY" and t["htf_trend"] == "BEARISH") or (t["direction"] == "SELL" and t["htf_trend"] == "BULLISH"))},
        {"name": "Asya Seansı Hariç (08-22 UTC)", "filter": lambda t: 8 <= t["entry_hour"] < 22},
    ]

    for gt in grid_tests:
        f_trades = [t for t in trades if gt["filter"](t)]
        f_wins = [t for t in f_trades if t["pnl_usd"] > 0]
        f_wr = round(len(f_wins) / len(f_trades) * 100, 1) if f_trades else 0.0
        f_pnl = round(sum(t["pnl_usd"] for t in f_trades), 2)
        print(f"  {gt['name']:40s}: {len(f_trades):3d} işlem | {len(f_wins):2d} W / {len(f_trades)-len(f_wins):2d} L | WR: %{f_wr:4.1f} | Net: ${f_pnl:+7.2f}")

for sym, yf, r_pct in [("XAUUSD", "GC=F", 0.07), ("US30", "YM=F", 0.02), ("USTEC", "NQ=F", 0.02)]:
    analyze_symbol(sym, yf, r_pct)
