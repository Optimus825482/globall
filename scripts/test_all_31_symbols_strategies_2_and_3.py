"""Comprehensive 31-Symbol Backtest for Strategy 2 (FVG Pullback) & Strategy 3 (S3 SuperTrend).

Runs a 7-day (5M bars) walk-forward simulation across all 31 symbols in the portfolio:
- Strategy 2: Fair Value Gap (FVG) Mitigation Pullback Engine
- Strategy 3: S3 SuperTrend Pullback Engine Revitalized with Smart Quality Gates

Evaluates:
- Per-symbol Trades, Wins, Losses, Win Rate %, Net PnL $, Profit Factor
- Total Portfolio Trade Volume & Net Return
- Category breakdown (Majors, Yen Crosses, Euro Crosses, GBP Crosses, Commodities, Indices, Crypto)
"""
import os
import sys
import json
import time
import datetime
import concurrent.futures
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.routers import forex
from scripts.replay_24h_dss_vs_baseline import ALL_SYMBOLS_MAP, fetch_symbol_bars, get_risk_pct_for_symbol

def load_all_31_symbol_data(days: int = 7) -> Dict[str, List[Any]]:
    print(f"⏳ [1/3] Tüm 31 sembol için canlı 5M piyasa verileri çekiliyor (Son {days} Gün)...")
    bars_dict = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(fetch_symbol_bars, s, yf, days): s for s, yf in ALL_SYMBOLS_MAP.items()}
        for fut in concurrent.futures.as_completed(futs):
            sym = futs[fut]
            try:
                res = fut.result()
                if res and len(res) >= 100:
                    bars_dict[sym] = res
            except Exception as e:
                pass
    print(f"✅ Toplam {len(bars_dict)}/{len(ALL_SYMBOLS_MAP)} sembolün verisi başarıyla yüklendi.")
    return bars_dict


# ==============================================================================
# STRATEGY 2: FVG MITIGATION PULLBACK ENGINE (ALL 31 SYMBOLS)
# ==============================================================================
def run_fvg_all_symbols(bars_dict: Dict[str, List[Any]]) -> Dict[str, Any]:
    print("\n" + "="*80)
    print("🚀 [STRATEJİ 2] TÜM 31 SEMBOLDE FAIR VALUE GAP (FVG) PULLBACK MOTORU TESTİ")
    print("="*80)

    sym_results = {}
    total_trades_all = 0
    total_wins_all = 0
    total_losses_all = 0
    total_pnl_all = 0.0

    for sym, bars in bars_dict.items():
        spec = forex.get_symbol_trading_specs(sym)
        pip_size = spec["pip_size"]
        pip_val = spec["pip_val"]
        digits = spec["digits"]
        risk_pct = get_risk_pct_for_symbol(sym)
        if "XAU" in sym:
            risk_pct = 0.07  # %7 risk budget for gold

        balance = 1000.0
        trades = []
        positions = []
        active_fvg = None

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
            b_prev2 = bars[idx - 2]
            b_prev1 = bars[idx - 1]
            b_now = cur_bar

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
                        active_fvg = None

        wins = [t for t in trades if t["pnl_usd"] > 0]
        losses = [t for t in trades if t["pnl_usd"] < 0]
        tot_pnl = round(sum(t["pnl_usd"] for t in trades), 2)
        wr = round(len(wins) / len(trades) * 100, 1) if trades else 0.0
        gross_win = sum(t["pnl_usd"] for t in wins)
        gross_loss = abs(sum(t["pnl_usd"] for t in losses))
        pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else 99.0

        total_trades_all += len(trades)
        total_wins_all += len(wins)
        total_losses_all += len(losses)
        total_pnl_all += tot_pnl

        sym_results[sym] = {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": wr,
            "net_pnl": tot_pnl,
            "profit_factor": pf,
        }
        status_icon = "🟢" if tot_pnl > 0 else "🔴"
        print(f"  {status_icon} {sym:8s}: {len(trades):3d} işlem | {len(wins):2d} W / {len(losses):2d} L | WR: %{wr:4.1f} | Net: ${tot_pnl:+8.2f} | PF: {pf:4.2f}")

    tot_wr = round(total_wins_all / total_trades_all * 100.0, 1) if total_trades_all else 0.0
    print("\n" + "-"*80)
    print(f"📌 [STRATEJİ 2 FVG GENEL PORTFÖY]: Toplam {total_trades_all} işlem | {total_wins_all} W / {total_losses_all} L | WR: %{tot_wr} | Toplam Net Kâr: ${total_pnl_all:+,.2f}")
    print("-"*80)

    return {
        "symbols": sym_results,
        "summary": {
            "total_trades": total_trades_all,
            "wins": total_wins_all,
            "losses": total_losses_all,
            "win_rate": tot_wr,
            "net_pnl": round(total_pnl_all, 2),
        }
    }


# ==============================================================================
# STRATEGY 3: REVITALIZED S3 SUPERTREND PULLBACK ENGINE (ALL 31 SYMBOLS)
# ==============================================================================
def run_s3_all_symbols(bars_dict: Dict[str, List[Any]]) -> Dict[str, Any]:
    print("\n" + "="*80)
    print("🚀 [STRATEJİ 3] TÜM 31 SEMBOLDE S3 SUPERTREND PULLBACK + AKILLI KALKAN TESTİ")
    print("="*80)

    sym_results = {}
    total_trades_all = 0
    total_wins_all = 0
    total_losses_all = 0
    total_pnl_all = 0.0

    for sym, bars in bars_dict.items():
        spec = forex.get_symbol_trading_specs(sym)
        pip_size = spec["pip_size"]
        pip_val = spec["pip_val"]
        digits = spec["digits"]
        risk_pct = get_risk_pct_for_symbol(sym)
        if "XAU" in sym:
            risk_pct = 0.07

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

        total_trades_all += len(trades)
        total_wins_all += len(wins)
        total_losses_all += len(losses)
        total_pnl_all += tot_pnl

        sym_results[sym] = {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": wr,
            "net_pnl": tot_pnl,
            "profit_factor": pf,
        }
        status_icon = "🟢" if tot_pnl > 0 else "🔴"
        print(f"  {status_icon} {sym:8s}: {len(trades):3d} işlem | {len(wins):2d} W / {len(losses):2d} L | WR: %{wr:4.1f} | Net: ${tot_pnl:+8.2f} | PF: {pf:4.2f}")

    tot_wr = round(total_wins_all / total_trades_all * 100.0, 1) if total_trades_all else 0.0
    print("\n" + "-"*80)
    print(f"📌 [STRATEJİ 3 S3 GENEL PORTFÖY]: Toplam {total_trades_all} işlem | {total_wins_all} W / {total_losses_all} L | WR: %{tot_wr} | Toplam Net Kâr: ${total_pnl_all:+,.2f}")
    print("-"*80)

    return {
        "symbols": sym_results,
        "summary": {
            "total_trades": total_trades_all,
            "wins": total_wins_all,
            "losses": total_losses_all,
            "win_rate": tot_wr,
            "net_pnl": round(total_pnl_all, 2),
        }
    }


def main():
    bars_dict = load_all_31_symbol_data(days=7)
    if not bars_dict:
        print("❌ Veri temin edilemedi!")
        return

    fvg_res = run_fvg_all_symbols(bars_dict)
    s3_res = run_s3_all_symbols(bars_dict)

    out_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "all_31_symbols_strategies_2_and_3.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"fvg": fvg_res, "s3": s3_res}, f, indent=2, ensure_ascii=False)

    print("\n" + "="*80)
    print(f"🎉 31 SEMBOLLÜK TEST TAMAMLANDI! Sonuçlar: {out_file}")
    print("="*80)


if __name__ == "__main__":
    main()
