#!/usr/bin/env python3
"""
scripts/test_crypto_weekend_backtest.py
---------------------------------------
IC Markets MT5 üzerinde listelenen ve 7/24 kesintisiz işlem gören 18 Kripto Para
(Crypto) sembolünün son 7 günlük (2,016 bar M5) piyasa geçmişi üzerinde:
  - Strateji 2: FVG Imbalance Pullback
  - Strateji 3: Revitalized S3 SuperTrend Pullback
performans testini koşturur ve hafta sonu portföyü için en karlı adayları belirler.
"""

import sys
import os
import math
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import MetaTrader5 as mt5
from backend.app.routers import forex


def calculate_st(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 10, multiplier: float = 3.0):
    n = len(closes)
    hl2 = (highs + lows) / 2.0
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    atr = np.zeros(n)
    if n >= period:
        atr[period - 1] = np.mean(tr[:period])
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    st = np.zeros(n)
    direction = np.zeros(n, dtype=int)
    up = hl2 - (multiplier * atr)
    dn = hl2 + (multiplier * atr)

    for i in range(period, n):
        if closes[i - 1] > up[i - 1]:
            up[i] = max(up[i], up[i - 1])
        if closes[i - 1] < dn[i - 1]:
            dn[i] = min(dn[i], dn[i - 1])

        if i == period:
            direction[i] = 1 if closes[i] > dn[i] else -1
        else:
            if direction[i - 1] == 1:
                direction[i] = -1 if closes[i] < up[i] else 1
            else:
                direction[i] = 1 if closes[i] > dn[i] else -1

        st[i] = up[i] if direction[i] == 1 else dn[i]
    return direction, atr


def calculate_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    rsi = np.full(n, 50.0)
    if n < period + 1:
        return rsi
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period + 1, n):
        gain = gains[i - 1]
        loss = losses[i - 1]
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def calculate_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    adx = np.full(n, 20.0)
    if n < period * 2:
        return adx
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    atr_smooth = np.zeros(n)
    plus_di_smooth = np.zeros(n)
    minus_di_smooth = np.zeros(n)
    atr_smooth[period] = np.sum(tr[1:period + 1])
    plus_di_smooth[period] = np.sum(plus_dm[1:period + 1])
    minus_di_smooth[period] = np.sum(minus_dm[1:period + 1])

    for i in range(period + 1, n):
        atr_smooth[i] = atr_smooth[i - 1] - (atr_smooth[i - 1] / period) + tr[i]
        plus_di_smooth[i] = plus_di_smooth[i - 1] - (plus_di_smooth[i - 1] / period) + plus_dm[i]
        minus_di_smooth[i] = minus_di_smooth[i - 1] - (minus_di_smooth[i - 1] / period) + minus_dm[i]

    dx = np.zeros(n)
    for i in range(period, n):
        if atr_smooth[i] > 0:
            p_di = 100.0 * (plus_di_smooth[i] / atr_smooth[i])
            m_di = 100.0 * (minus_di_smooth[i] / atr_smooth[i])
            di_sum = p_di + m_di
            dx[i] = 100.0 * (abs(p_di - m_di) / di_sum) if di_sum > 0 else 0.0

    adx[period * 2 - 1] = np.mean(dx[period:period * 2])
    for i in range(period * 2, n):
        adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx


def run_crypto_backtests():
    if not mt5.initialize():
        print("[HATA] MetaTrader 5 baslatilamadi:", mt5.last_error())
        return

    syms = [s.name for s in mt5.symbols_get() if getattr(s, 'path', '').startswith('Crypto')]
    print("=" * 85)
    print(f"IC MARKETS 7/24 KRIPTO PARALAR - 7 GÜNLÜK BACKTEST (TOPLAM {len(syms)} SEMBOL)")
    print("=" * 85)

    fvg_results = []
    s3_results = []

    for sym in syms:
        mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym)
        if not info:
            continue

        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 2016)
        if rates is None or len(rates) < 200:
            continue

        bars = [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rates]
        highs = np.array([b[2] for b in bars])
        lows = np.array([b[3] for b in bars])
        closes = np.array([b[4] for b in bars])

        contract_size = float(info.trade_contract_size)
        digits = int(info.digits)
        point = float(info.point)
        min_lot = float(info.volume_min)
        max_lot = float(info.volume_max)
        vol_step = float(info.volume_step)

        # Pip Size & Pip Val:
        # Fiyat basamaklarına göre pip tanımı
        if digits == 2:
            pip_size = 1.0 if closes[-1] > 500 else 0.10
        elif digits >= 4:
            pip_size = 0.001 if closes[-1] > 10 else 0.0001
        else:
            pip_size = 0.01

        # 1 lot için 1 pip hareketin USD değeri = pip_size * contract_size
        pip_val = pip_size * contract_size
        risk_pct = 0.02  # Standart Kripto %2 risk bütçesi

        st_dir, atr_arr = calculate_st(highs, lows, closes)
        rsi_arr = calculate_rsi(closes)
        adx_arr = calculate_adx(highs, lows, closes)

        # ATR bazlı dinamik stop mesafesi (pip cinsinden)
        med_atr = np.median(atr_arr[-500:]) if len(atr_arr) > 500 else point * 50
        sl_pips = max(5.0, round((med_atr * 1.5) / pip_size, 1))

        # -------------------------------------------------------------
        # TEST 1: STRATEJI 2 (FVG IMBALANCE PULLBACK)
        # -------------------------------------------------------------
        balance = 1000.0
        trades_fvg = []
        positions_fvg = []
        active_fvg = None

        for idx in range(35, len(bars)):
            cur_bar = bars[idx]
            cur_ts = cur_bar[0]
            cur_price = cur_bar[4]

            # Update Positions
            still_open = []
            for pos in positions_fvg:
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
                    trades_fvg.append(pos)
                else:
                    still_open.append(pos)
            positions_fvg = still_open

            # Detect FVG
            b_prev2 = bars[idx - 2]
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

            # Check Pullback Entry
            if active_fvg and len(positions_fvg) == 0:
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
                        tp_p = sl_pips * 1.8
                        risk_usd = balance * risk_pct
                        raw_lots = risk_usd / (sl_pips * pip_val) if (sl_pips * pip_val) > 0 else min_lot
                        lots = round(max(min_lot, min(max_lot, raw_lots)), 2)
                        # round to volume step
                        if vol_step >= 1.0:
                            lots = round(round(lots / vol_step) * vol_step)
                        lots = max(min_lot, lots)

                        sl_px = cur_price - (sl_pips * pip_size) if action == "BUY" else cur_price + (sl_pips * pip_size)
                        tp_px = cur_price + (tp_p * pip_size) if action == "BUY" else cur_price - (tp_p * pip_size)

                        positions_fvg.append({
                            "symbol": sym,
                            "direction": action,
                            "lots": lots,
                            "entry_price": cur_price,
                            "sl_price": round(sl_px, digits),
                            "tp_price": round(tp_px, digits),
                            "sl0_pips": sl_pips,
                            "be_locked": False,
                        })
                        active_fvg = None

        wins_fvg = [t for t in trades_fvg if t["pnl_usd"] > 0]
        losses_fvg = [t for t in trades_fvg if t["pnl_usd"] < 0]
        tot_pnl_fvg = round(sum(t["pnl_usd"] for t in trades_fvg), 2)
        wr_fvg = round((len(wins_fvg) / len(trades_fvg) * 100), 1) if trades_fvg else 0.0
        fvg_results.append({
            "symbol": sym,
            "trades": len(trades_fvg),
            "wins": len(wins_fvg),
            "losses": len(losses_fvg),
            "wr": wr_fvg,
            "pnl": tot_pnl_fvg,
        })

        # -------------------------------------------------------------
        # TEST 2: STRATEJI 3 (S3 SUPERTREND PULLBACK)
        # -------------------------------------------------------------
        balance_s3 = 1000.0
        trades_s3 = []
        positions_s3 = []

        for idx in range(35, len(bars)):
            cur_bar = bars[idx]
            cur_ts = cur_bar[0]
            cur_price = cur_bar[4]

            # Update Positions
            still_open_s3 = []
            for pos in positions_s3:
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
                    elif st_dir[idx] < 0:
                        closed = True
                        exit_price = cur_price
                        exit_reason = "ST_FLIP"
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
                    elif st_dir[idx] > 0:
                        closed = True
                        exit_price = cur_price
                        exit_reason = "ST_FLIP"
                    else:
                        pnl_p = (pos["entry_price"] - b_l) / pip_size
                        if pnl_p >= pos["sl0_pips"] * 0.40 and not pos["be_locked"]:
                            pos["be_locked"] = True
                            pos["sl_price"] = pos["entry_price"] - (pos["sl0_pips"] * 0.20 * pip_size)

                if closed:
                    pnl_p = (exit_price - pos["entry_price"]) / pip_size if pos["direction"] == "BUY" else (pos["entry_price"] - exit_price) / pip_size
                    pnl_usd = round(pnl_p * pos["lots"] * pip_val, 2)
                    balance_s3 = round(balance_s3 + pnl_usd, 2)
                    pos["pnl_usd"] = pnl_usd
                    pos["exit_reason"] = exit_reason
                    trades_s3.append(pos)
                else:
                    still_open_s3.append(pos)
            positions_s3 = still_open_s3

            # Check S3 Entry
            if len(positions_s3) == 0:
                s_dir = st_dir[idx]
                r_now = rsi_arr[idx]
                r_prev = rsi_arr[idx - 1]
                r_win = list(rsi_arr[max(0, idx - 6):idx])
                adx_val = adx_arr[idx]

                act = forex.s3_pullback_entry(
                    st_dir=int(s_dir),
                    close=cur_price,
                    ema200=0.0,
                    use_ema200=False,
                    adx=float(adx_val),
                    adx_min=20.0,
                    rsi_now=float(r_now),
                    rsi_prev=float(r_prev),
                    rsi_window=[float(x) for x in r_win],
                    rsi_lo=40.0,
                    atr_price=float(atr_arr[idx]),
                    pip_size=float(pip_size),
                    day_counts={},
                    max_per_day=0,
                )

                if act:
                    bar_body = abs(cur_bar[4] - cur_bar[1])
                    bar_span = max(1e-5, cur_bar[2] - cur_bar[3])
                    body_ratio = bar_body / bar_span

                    sub_closes = [b[4] for b in bars[max(0, idx - 30):idx + 1]]
                    ema21 = float(np.mean(sub_closes[-21:])) if len(sub_closes) >= 21 else cur_price
                    dist_ema21_pct = ((cur_price - ema21) / ema21) * 100.0 if ema21 else 0.0

                    dt = datetime.datetime.fromtimestamp(cur_ts, datetime.timezone.utc)
                    ok_asset, _ = forex.asset_quality_gate(sym, act, body_ratio, dist_ema21_pct, adx=adx_val, hour_utc=dt.hour)

                    if ok_asset:
                        tp_p = sl_pips * 2.0
                        risk_usd = balance_s3 * risk_pct
                        raw_lots = risk_usd / (sl_pips * pip_val) if (sl_pips * pip_val) > 0 else min_lot
                        lots = round(max(min_lot, min(max_lot, raw_lots)), 2)
                        if vol_step >= 1.0:
                            lots = round(round(lots / vol_step) * vol_step)
                        lots = max(min_lot, lots)

                        sl_px = cur_price - (sl_pips * pip_size) if act == "BUY" else cur_price + (sl_pips * pip_size)
                        tp_px = cur_price + (tp_p * pip_size) if act == "BUY" else cur_price - (tp_p * pip_size)

                        positions_s3.append({
                            "symbol": sym,
                            "direction": act,
                            "lots": lots,
                            "entry_price": cur_price,
                            "sl_price": round(sl_px, digits),
                            "tp_price": round(tp_px, digits),
                            "sl0_pips": sl_pips,
                            "be_locked": False,
                        })

        wins_s3 = [t for t in trades_s3 if t["pnl_usd"] > 0]
        losses_s3 = [t for t in trades_s3 if t["pnl_usd"] < 0]
        tot_pnl_s3 = round(sum(t["pnl_usd"] for t in trades_s3), 2)
        wr_s3 = round((len(wins_s3) / len(trades_s3) * 100), 1) if trades_s3 else 0.0
        s3_results.append({
            "symbol": sym,
            "trades": len(trades_s3),
            "wins": len(wins_s3),
            "losses": len(losses_s3),
            "wr": wr_s3,
            "pnl": tot_pnl_s3,
        })

    mt5.shutdown()

    # PRINT SUMMARY TABLES
    print("\n" + "=" * 85)
    print("STRATEJI 2: FVG IMBALANCE PULLBACK - KRIPTO 7 GÜNLÜK SONUÇLARI")
    print("=" * 85)
    print(f"{'Sembol':<10} | {'İşlem':<6} | {'Kazan':<6} | {'Kayıp':<6} | {'WR (%)':<8} | {'Net PnL (USD)':<15}")
    print("-" * 85)
    fvg_results.sort(key=lambda x: x["pnl"], reverse=True)
    tot_trades_fvg = sum(x["trades"] for x in fvg_results)
    tot_wins_fvg = sum(x["wins"] for x in fvg_results)
    tot_pnl_all_fvg = round(sum(x["pnl"] for x in fvg_results), 2)
    tot_wr_fvg = round(tot_wins_fvg / tot_trades_fvg * 100, 1) if tot_trades_fvg else 0.0

    for r in fvg_results:
        mark = "[+]" if r["pnl"] > 0 else "[-]"
        print(f"{r['symbol']:<10} | {r['trades']:<6} | {r['wins']:<6} | {r['losses']:<6} | %{r['wr']:<7.1f} | {r['pnl']:+12.2f} USD {mark}")
    print("-" * 85)
    print(f"{'TOPLAM':<10} | {tot_trades_fvg:<6} | {tot_wins_fvg:<6} | {tot_trades_fvg - tot_wins_fvg:<6} | %{tot_wr_fvg:<7.1f} | {tot_pnl_all_fvg:+12.2f} USD")

    print("\n" + "=" * 85)
    print("STRATEJI 3: S3 SUPERTREND PULLBACK - KRIPTO 7 GÜNLÜK SONUÇLARI")
    print("=" * 85)
    print(f"{'Sembol':<10} | {'İşlem':<6} | {'Kazan':<6} | {'Kayıp':<6} | {'WR (%)':<8} | {'Net PnL (USD)':<15}")
    print("-" * 85)
    s3_results.sort(key=lambda x: x["pnl"], reverse=True)
    tot_trades_s3 = sum(x["trades"] for x in s3_results)
    tot_wins_s3 = sum(x["wins"] for x in s3_results)
    tot_pnl_all_s3 = round(sum(x["pnl"] for x in s3_results), 2)
    tot_wr_s3 = round(tot_wins_s3 / tot_trades_s3 * 100, 1) if tot_trades_s3 else 0.0

    for r in s3_results:
        mark = "[+]" if r["pnl"] > 0 else "[-]"
        print(f"{r['symbol']:<10} | {r['trades']:<6} | {r['wins']:<6} | {r['losses']:<6} | %{r['wr']:<7.1f} | {r['pnl']:+12.2f} USD {mark}")
    print("-" * 85)
    print(f"{'TOPLAM':<10} | {tot_trades_s3:<6} | {tot_wins_s3:<6} | {tot_trades_s3 - tot_wins_s3:<6} | %{tot_wr_s3:<7.1f} | {tot_pnl_all_s3:+12.2f} USD")

    grand_trades = tot_trades_fvg + tot_trades_s3
    grand_wins = tot_wins_fvg + tot_wins_s3
    grand_pnl = round(tot_pnl_all_fvg + tot_pnl_all_s3, 2)
    grand_wr = round(grand_wins / grand_trades * 100, 1) if grand_trades else 0.0

    print("\n" + "=" * 85)
    print("GENEL KRIPTO PORTFÖYÜ BİRLEŞİK ÖZETİ (HAFTA SONU AKTİF ENSTRÜMANLARI)")
    print("=" * 85)
    print(f"Toplam İşlem Sayısı: {grand_trades}")
    print(f"Toplam Kazanan     : {grand_wins}")
    print(f"Toplam Kaybeden    : {grand_trades - grand_wins}")
    print(f"Genel Kazanma Oranı: %{grand_wr:.1f}")
    print(f"GENEL NET KÂR      : {grand_pnl:+,.2f} USD")
    print("=" * 85)


if __name__ == "__main__":
    run_crypto_backtests()
