"""US30, USTEC, and XAUUSD 7-Day Deep Loss Diagnostic & Filter Optimization Engine.

Analyzes every single trade (winners vs losers) across:
1. XAUUSD (Gold)
2. US30 (Dow Jones 30 CFD / Futures)
3. USTEC (Nasdaq 100 CFD / Futures)

Identifies feature distributions at trade entry (Score, Body Ratio, EMA Distance, ADX, Session UTC)
and simulates specific smart quality gates to maximize Net PnL and Win Rate.
"""
import os
import sys
import json
import time
import datetime
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.routers import forex
from scripts.replay_24h_dss_vs_baseline import fetch_symbol_bars, calculate_lots, Position, Account, STARTING_BALANCE

SYMBOL_CONFIGS = [
    {
        "sym": "XAUUSD",
        "yf_sym": "GC=F",
        "name": "Altın (XAUUSD)",
        "risk_pct": 0.07,  # %7 risk ($70)
        "test_body_ratios": [0.30, 0.35, 0.40],
        "test_ema_dists": [0.20, 0.25, 0.30, 0.40],
        "test_adxs": [18.0, 20.0, 22.0],
    },
    {
        "sym": "US30",
        "yf_sym": "YM=F",
        "name": "Dow Jones 30 (US30)",
        "risk_pct": 0.02,  # %2 risk ($20)
        "test_body_ratios": [0.30, 0.35, 0.40],
        "test_ema_dists": [0.15, 0.20, 0.25, 0.30],
        "test_adxs": [18.0, 20.0, 22.0],
    },
    {
        "sym": "USTEC",
        "yf_sym": "NQ=F",
        "name": "Nasdaq 100 (USTEC)",
        "risk_pct": 0.02,  # %2 risk ($20)
        "test_body_ratios": [0.30, 0.35, 0.40],
        "test_ema_dists": [0.15, 0.20, 0.25, 0.30],
        "test_adxs": [18.0, 20.0, 22.0],
    },
]


def run_single_symbol_diagnosis(sym: str, yf_sym: str, risk_pct: float, days: int = 7) -> Dict[str, Any]:
    print(f"\n================================================================================")
    print(f"🔍 {sym} ({yf_sym}) 7 GÜNLÜK DERİN ZARAR ANALİZİ BAŞLATILIYOR ({days} Gün, Risk: %{risk_pct*100:.0f})")
    print(f"================================================================================\n")

    bars = fetch_symbol_bars(sym, yf_sym, days=days)
    if not bars or len(bars) < 100:
        print(f"❌ {sym} için veri temin edilemedi!")
        return {}

    print(f"✅ Toplam {len(bars)} adet 5M barı yüklendi.")
    print(f"📅 Başlangıç: {datetime.datetime.fromtimestamp(bars[0][0], datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"📅 Bitiş:     {datetime.datetime.fromtimestamp(bars[-1][0], datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    spec = forex.get_symbol_trading_specs(sym)
    pip_size = spec["pip_size"]
    pip_val = spec["pip_val"]
    digits = spec["digits"]

    balance = 1000.0
    positions: List[Dict[str, Any]] = []
    closed_trades: List[Dict[str, Any]] = []
    trade_id_counter = 0

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
        cmo = float(tech.get("cmo", 0.0))
        cci = float(tech.get("cci", 0.0))
        macd = float(tech.get("macd", 0.0))
        macd_hist = float(tech.get("macd_hist", 0.0))
        atr = float(tech.get("atr_pips", 50.0))
        adx = float(tech.get("adx", 20.0))
        supertrend_dir = int(tech.get("supertrend_dir", 0))
        action = tech.get("action", "HOLD")
        score = float(tech.get("score", 0.0))
        htf_trend = tech.get("htf_trend", "NEUTRAL")
        fvg_type = tech.get("fvg_type", "NONE")
        spread = 1.5

        ema21 = float(tech.get("ema21", cur_price))
        ema50 = float(tech.get("ema50", cur_price))
        dist_ema21_pct = round(((cur_price - ema21) / ema21) * 100.0, 3) if ema21 else 0.0
        dist_ema50_pct = round(((cur_price - ema50) / ema50) * 100.0, 3) if ema50 else 0.0

        bar_range = cur_bar[2] - cur_bar[3]
        bar_body = abs(cur_bar[4] - cur_bar[1])
        body_ratio = round((bar_body / max(1e-5, bar_range)), 2)

        hour_utc = datetime.datetime.fromtimestamp(cur_ts, datetime.timezone.utc).hour

        # 1. Update Open Positions
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
                        cooldown_until = cur_ts + 900.0  # 15 dk
                        streak_losses = 0
                elif pnl_usd > 0:
                    streak_losses = 0

                pos["exit_price"] = exit_price
                pos["exit_reason"] = exit_reason
                pos["exit_time"] = cur_ts
                pos["pnl_usd"] = pnl_usd
                pos["pnl_pips"] = round(pnl_p, 1)
                pos["duration_bars"] = idx - pos["entry_idx"]
                closed_trades.append(pos)
            else:
                still_open.append(pos)

        positions = still_open

        # 2. Check New Entry (DSS Rules)
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

            trade_id_counter += 1
            pos_dict = {
                "id": f"{sym}-{trade_id_counter}",
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
                # Indicator snapshot at entry
                "score": score,
                "rsi": rsi,
                "cmo": cmo,
                "cci": cci,
                "macd_hist": macd_hist,
                "adx": adx,
                "supertrend_dir": supertrend_dir,
                "htf_trend": htf_trend,
                "fvg_type": fvg_type,
                "body_ratio": body_ratio,
                "dist_ema21_pct": dist_ema21_pct,
                "dist_ema50_pct": dist_ema50_pct,
            }
            positions.append(pos_dict)

    # 3. Analyze Trades
    wins = [t for t in closed_trades if t["pnl_usd"] > 0]
    losses = [t for t in closed_trades if t["pnl_usd"] < 0]
    breakevens = [t for t in closed_trades if t["pnl_usd"] == 0]

    total_n = len(closed_trades)
    win_n = len(wins)
    loss_n = len(losses)
    wr = round(win_n / total_n * 100.0, 1) if total_n else 0.0
    tot_pnl = round(sum(t["pnl_usd"] for t in closed_trades), 2)

    print(f"\n📊 [TEMEL PERFORMANS ({sym})]")
    print(f"Toplam İşlem: {total_n} | Kazanan: {win_n} | Kaybeden: {loss_n} | BE: {len(breakevens)}")
    print(f"Kazanma Oranı (WR): %{wr} | Net Kâr/Zarar: ${tot_pnl:+.2f}")

    def get_stats(trade_list: List[Dict[str, Any]], field: str) -> Dict[str, float]:
        if not trade_list:
            return {"mean": 0.0, "median": 0.0, "p25": 0.0, "p75": 0.0}
        vals = [float(t[field]) for t in trade_list]
        return {
            "mean": round(float(np.mean(vals)), 3),
            "median": round(float(np.median(vals)), 3),
            "p25": round(float(np.percentile(vals, 25)), 3),
            "p75": round(float(np.percentile(vals, 75)), 3),
        }

    fields = ["score", "adx", "body_ratio", "dist_ema21_pct", "rsi", "duration_bars"]
    factor_comp = {}
    for f in fields:
        factor_comp[f] = {
            "winners": get_stats(wins, f),
            "losers": get_stats(losses, f),
        }

    # 4. Simulation of Smart Quality Gates
    # Test combinations of body_ratio, dist_ema21_pct, adx
    def sim_gate(min_body: float, max_dist_ema21: float, min_adx: float, session_filter: bool = False) -> Dict[str, Any]:
        kept = []
        for t in closed_trades:
            if t["body_ratio"] < min_body:
                continue
            if abs(t["dist_ema21_pct"]) > max_dist_ema21:
                continue
            if t["adx"] < min_adx:
                continue
            if session_filter and (t["entry_hour"] < 13 or t["entry_hour"] >= 21):
                # Major US Session only (13:00 - 21:00 UTC)
                continue
            kept.append(t)
        
        k_wins = [t for t in kept if t["pnl_usd"] > 0]
        k_losses = [t for t in kept if t["pnl_usd"] < 0]
        k_tot = len(kept)
        k_wr = round(len(k_wins) / k_tot * 100.0, 1) if k_tot else 0.0
        k_pnl = round(sum(t["pnl_usd"] for t in kept), 2)
        elim_losses = loss_n - len(k_losses)
        elim_wins = win_n - len(k_wins)
        return {
            "min_body": min_body,
            "max_dist_ema21": max_dist_ema21,
            "min_adx": min_adx,
            "session_filter": session_filter,
            "total_trades": k_tot,
            "wins": len(k_wins),
            "losses": len(k_losses),
            "win_rate": k_wr,
            "net_pnl": k_pnl,
            "eliminated_losses": elim_losses,
            "eliminated_wins": elim_wins,
        }

    sim_results = []
    # Test individual gates
    sim_results.append({"name": "Mevcut Sistem (Filtresiz)", **sim_gate(0.0, 999.0, 0.0)})
    sim_results.append({"name": "Yalnız Gövde Teyidi (body >= 0.35)", **sim_gate(0.35, 999.0, 0.0)})
    sim_results.append({"name": "Yalnız ADX Kalkanı (adx >= 20.0)", **sim_gate(0.0, 999.0, 20.0)})

    # Test parameter grid
    if "XAU" in sym:
        # Gold has specific volatility
        for b in [0.30, 0.35]:
            for d in [0.25, 0.30, 0.40]:
                for a in [18.0, 20.0]:
                    sim_results.append({
                        "name": f"Kombine (body>={b}, dist<={d}%, adx>={a})",
                        **sim_gate(b, d, a)
                    })
    else:
        # Index CFDs (US30 / USTEC)
        for b in [0.30, 0.35]:
            for d in [0.20, 0.25, 0.30]:
                for a in [18.0, 20.0]:
                    sim_results.append({
                        "name": f"Kombine (body>={b}, dist<={d}%, adx>={a})",
                        **sim_gate(b, d, a)
                    })
        # Test with US session filter
        sim_results.append({
            "name": "Kombine + ABD Seansı Filtresi (13-21 UTC)",
            **sim_gate(0.35, 0.25, 20.0, session_filter=True)
        })

    # Sort results by net_pnl descending
    sim_results.sort(key=lambda x: x["net_pnl"], reverse=True)
    best_config = sim_results[0]

    return {
        "symbol": sym,
        "name": yf_sym,
        "baseline": {
            "total_trades": total_n,
            "wins": win_n,
            "losses": loss_n,
            "win_rate": wr,
            "net_pnl": tot_pnl,
        },
        "factor_comparison": factor_comp,
        "best_config": best_config,
        "top_configs": sim_results[:5],
    }


def main():
    print("🚀 US30, USTEC ve XAUUSD 7 Günlük Çoklu Varlık Teşhis Motoru Başlatılıyor...")
    all_reports = {}
    for cfg in SYMBOL_CONFIGS:
        res = run_single_symbol_diagnosis(cfg["sym"], cfg["yf_sym"], cfg["risk_pct"])
        if res:
            all_reports[cfg["sym"]] = res

    out_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "triplet_7d_loss_diagnosis.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_reports, f, indent=2, ensure_ascii=False)

    print(f"\n================================================================================")
    print(f"🎉 TÜM TEŞHİSLER TAMAMLANDI! Sonuçlar '{out_file}' dosyasına yazıldı.")
    print(f"================================================================================")


if __name__ == "__main__":
    main()
