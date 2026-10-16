"""BTCUSD 7-Day Deep Loss Diagnostic & Feature Importance Analyzer.

Analyzes every single winning vs losing trade on BTCUSD over the last 7 days (5M bars),
pinpointing the exact indicator values, market regimes, and trigger conditions
that caused losing trades to enter, and simulates targeted improvements.
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
from scripts.replay_24h_dss_vs_baseline import fetch_symbol_bars, Position, Account, STARTING_BALANCE

def run_btcusd_deep_loss_diagnostics(days: int = 7):
    print(f"\n================================================================================")
    print(f"🔍 BTCUSD 7 GÜNLÜK DERİN ZARAR ANALİZİ VE SİNYAL TEŞHİS MOTORU ({days} Gün)")
    print(f"================================================================================\n")

    # 1. Fetch 5M data for BTCUSD
    bars = fetch_symbol_bars("BTCUSD", "BTC-USD", days=days)
    if not bars or len(bars) < 100:
        print("❌ BTCUSD verisi temin edilemedi!")
        return

    print(f"✅ Toplam {len(bars)} adet 5M barı yüklendi.")
    print(f"📅 Başlangıç: {datetime.datetime.fromtimestamp(bars[0][0], datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"📅 Bitiş:     {datetime.datetime.fromtimestamp(bars[-1][0], datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    spec = forex.get_symbol_trading_specs("BTCUSD")
    pip_size = spec["pip_size"]
    pip_val = spec["pip_val"]
    digits = spec["digits"]

    # Account state
    balance = 1000.0
    positions: List[Dict[str, Any]] = []
    closed_trades: List[Dict[str, Any]] = []
    trade_id_counter = 0

    streak_losses = 0
    cooldown_until = 0.0

    # Walk forward bar by bar
    for idx in range(35, len(bars)):
        cur_bar = bars[idx]
        cur_ts = cur_bar[0]
        cur_price = cur_bar[4]

        sub_bars = bars[max(0, idx - 100):idx + 1]
        closes = [b[4] for b in sub_bars]
        highs = [b[2] for b in sub_bars]
        lows = [b[3] for b in sub_bars]
        opens = [b[1] for b in sub_bars]

        tech = forex._compute_technical_indicators(closes, highs, lows, opens, "BTCUSD")
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

        # Moving averages for overextension analysis
        ema9 = float(tech.get("ema9", cur_price))
        ema21 = float(tech.get("ema21", cur_price))
        ema50 = float(tech.get("ema50", cur_price))
        dist_ema21_pct = round(((cur_price - ema21) / ema21) * 100.0, 3)
        dist_ema50_pct = round(((cur_price - ema50) / ema50) * 100.0, 3)

        # Candle metrics
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
                    pnl_pips = (b_h - pos["entry_price"]) / pos["pip_size"]
                    pos["mfe_pips"] = max(pos["mfe_pips"], pnl_pips)
                    be_trig = max(pos["sl0_pips"] * 0.40, pos["entry_atr"] * 0.8)
                    if pnl_pips >= be_trig and not pos["be_locked"]:
                        pos["be_locked"] = True
                        lock_p = max(1.5, pos["sl0_pips"] * 0.20)
                        pos["sl_price"] = round(pos["entry_price"] + (lock_p * pos["pip_size"]), pos["digits"])
                    if pos["be_locked"] and pnl_pips >= pos["sl0_pips"] * 1.0:
                        trail_sl = round(b_c - (pos["entry_atr"] * 1.0 * pos["pip_size"]), pos["digits"])
                        if pos["sl_price"] == 0 or trail_sl > pos["sl_price"]:
                            pos["sl_price"] = trail_sl
                            pos["trail_active"] = True
            else: # SELL
                if b_h >= pos["sl_price"]:
                    closed = True
                    exit_price = pos["sl_price"]
                    exit_reason = "BE_HIT" if (pos["be_locked"] and pos["sl_price"] <= pos["entry_price"]) else "SL_HIT"
                elif b_l <= pos["tp_price"]:
                    closed = True
                    exit_price = pos["tp_price"]
                    exit_reason = "TP_HIT"
                else:
                    pnl_pips = (pos["entry_price"] - b_l) / pos["pip_size"]
                    pos["mfe_pips"] = max(pos["mfe_pips"], pnl_pips)
                    be_trig = max(pos["sl0_pips"] * 0.40, pos["entry_atr"] * 0.8)
                    if pnl_pips >= be_trig and not pos["be_locked"]:
                        pos["be_locked"] = True
                        lock_p = max(1.5, pos["sl0_pips"] * 0.20)
                        pos["sl_price"] = round(pos["entry_price"] - (lock_p * pos["pip_size"]), pos["digits"])
                    if pos["be_locked"] and pnl_pips >= pos["sl0_pips"] * 1.0:
                        trail_sl = round(b_c + (pos["entry_atr"] * 1.0 * pos["pip_size"]), pos["digits"])
                        if pos["sl_price"] == 0 or trail_sl < pos["sl_price"]:
                            pos["sl_price"] = trail_sl
                            pos["trail_active"] = True

            if closed:
                pnl_p = (exit_price - pos["entry_price"]) / pos["pip_size"] if pos["direction"] == "BUY" else (pos["entry_price"] - exit_price) / pos["pip_size"]
                pnl_usd = round(pnl_p * pos["lots"] * pos["pip_val"], 2)
                balance = round(balance + pnl_usd, 2)

                # Streak loss tracking
                if pnl_usd < 0 and exit_reason == "SL_HIT":
                    streak_losses += 1
                    if streak_losses >= 2:
                        cooldown_until = cur_ts + 900.0  # 15 min lock
                        streak_losses = 0
                elif pnl_usd > 0:
                    streak_losses = 0

                pos_record = {
                    **pos,
                    "exit_time": cur_ts,
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "pnl_usd": pnl_usd,
                    "pnl_pips": pnl_p,
                    "duration_bars": (idx - pos["entry_bar_idx"]),
                }
                closed_trades.append(pos_record)
            else:
                still_open.append(pos)

        positions = still_open

        # 2. Check New Entry
        if action in ("BUY", "SELL") and len(positions) == 0:
            dss_score, dss_tier = forex.calculate_dss_score(
                sym="BTCUSD",
                action=action,
                htf_trend=htf_trend,
                csm_diff=0.0,
                rsi_5m=rsi,
                macd_hist=macd_hist,
                fvg_type=fvg_type,
                supertrend_dir=supertrend_dir,
                spread_pips=spread,
                atr_pips=atr,
            )

            is_valid_tier = (dss_tier in ("A+", "B"))
            st_aligned = (action == "BUY" and supertrend_dir >= 0) or (action == "SELL" and supertrend_dir <= 0)
            in_cooldown = cur_ts < cooldown_until

            if is_valid_tier and st_aligned and not in_cooldown:
                atr_exits = forex.get_atr_exit_levels(atr, spec["sl_pips"], spec["tp_pips"])
                sl_p = atr_exits["sl_pips"]
                tp_p = max(atr_exits["tp_pips"], sl_p * 1.8)

                risk_usd = balance * 0.02  # %2 risk
                raw_lots = risk_usd / (sl_p * pip_val)
                lots = round(max(0.01, min(10.0, raw_lots)), 2)

                sl_px = cur_price - (sl_p * pip_size) if action == "BUY" else cur_price + (sl_p * pip_size)
                tp_px = cur_price + (tp_p * pip_size) if action == "BUY" else cur_price - (tp_p * pip_size)

                trade_id_counter += 1
                positions.append({
                    "id": f"BTC-{trade_id_counter}",
                    "direction": action,
                    "lots": lots,
                    "entry_price": cur_price,
                    "sl_price": round(sl_px, digits),
                    "tp_price": round(tp_px, digits),
                    "entry_time": cur_ts,
                    "entry_bar_idx": idx,
                    "pip_size": pip_size,
                    "pip_val": pip_val,
                    "digits": digits,
                    "entry_atr": atr,
                    "sl0_pips": sl_p,
                    "tp0_pips": tp_p,
                    "be_locked": False,
                    "trail_active": False,
                    "mfe_pips": 0.0,
                    "tier": dss_tier,
                    # Snapshot metrics at entry for deep diagnostic:
                    "entry_rsi": rsi,
                    "entry_cmo": cmo,
                    "entry_cci": cci,
                    "entry_macd": macd,
                    "entry_macd_hist": macd_hist,
                    "entry_adx": adx,
                    "entry_score": score,
                    "entry_htf_trend": htf_trend,
                    "entry_st_dir": supertrend_dir,
                    "entry_fvg": fvg_type,
                    "entry_hour_utc": hour_utc,
                    "entry_dist_ema21_pct": dist_ema21_pct,
                    "entry_dist_ema50_pct": dist_ema50_pct,
                    "entry_body_ratio": body_ratio,
                    "entry_ema9": ema9,
                    "entry_ema21": ema21,
                    "entry_ema50": ema50,
                })

    # Close any remaining position
    for pos in positions:
        exit_price = bars[-1][4]
        pnl_p = (exit_price - pos["entry_price"]) / pos["pip_size"] if pos["direction"] == "BUY" else (pos["entry_price"] - exit_price) / pos["pip_size"]
        pnl_usd = round(pnl_p * pos["lots"] * pos["pip_val"], 2)
        balance = round(balance + pnl_usd, 2)
        closed_trades.append({
            **pos,
            "exit_time": bars[-1][0],
            "exit_price": exit_price,
            "exit_reason": "REPLAY_END",
            "pnl_usd": pnl_usd,
            "pnl_pips": pnl_p,
            "duration_bars": len(bars) - 1 - pos["entry_bar_idx"],
        })

    # ==============================================================================
    # 3. STATISTICAL ANALYSIS: WINNERS VS LOSERS
    # ==============================================================================
    winners = [t for t in closed_trades if t["pnl_usd"] > 0]
    losers = [t for t in closed_trades if t["pnl_usd"] < 0 and t["exit_reason"] == "SL_HIT"]
    breakevens = [t for t in closed_trades if t["exit_reason"] == "BE_HIT"]

    total_n = len(closed_trades)
    win_n = len(winners)
    loss_n = len(losers)
    be_n = len(breakevens)

    tot_pnl = sum(t["pnl_usd"] for t in closed_trades)
    gross_win = sum(t["pnl_usd"] for t in winners)
    gross_loss = sum(t["pnl_usd"] for t in losers)
    win_rate = (win_n / total_n * 100.0) if total_n > 0 else 0.0

    print(f"\n📊 TOPLAM PERFORMANS ÖZETİ:")
    print(f"  Toplam İşlem: {total_n}")
    print(f"  Kazanan:      {win_n} (%{win_rate:.1f}) | Kâr: +${gross_win:.2f}")
    print(f"  Kaybeden SL:  {loss_n} (%{loss_n/total_n*100:.1f}) | Zarar: -${abs(gross_loss):.2f}")
    print(f"  Başabaş BE:   {be_n} (%{be_n/total_n*100:.1f})")
    print(f"  Net Sonuç:    ${tot_pnl:+.2f} (Bakiye: ${balance:.2f})")

    # ==============================================================================
    # 4. YÖN DAĞILIMI (BUY vs SELL)
    # ==============================================================================
    buy_trades = [t for t in closed_trades if t["direction"] == "BUY"]
    sell_trades = [t for t in closed_trades if t["direction"] == "SELL"]

    buy_win = len([t for t in buy_trades if t["pnl_usd"] > 0])
    buy_loss = len([t for t in buy_trades if t["pnl_usd"] < 0])
    sell_win = len([t for t in sell_trades if t["pnl_usd"] > 0])
    sell_loss = len([t for t in sell_trades if t["pnl_usd"] < 0])

    print(f"\n🧭 YÖN ANALİZİ:")
    print(f"  BUY İşlemleri:  Toplam {len(buy_trades):3d} | Kazanç: {buy_win:3d} | Kayıp: {buy_loss:3d} (WR: %{buy_win/max(1, len(buy_trades))*100:.1f}) | Net: ${sum(t['pnl_usd'] for t in buy_trades):+.2f}")
    print(f"  SELL İşlemleri: Toplam {len(sell_trades):3d} | Kazanç: {sell_win:3d} | Kayıp: {sell_loss:3d} (WR: %{sell_win/max(1, len(sell_trades))*100:.1f}) | Net: ${sum(t['pnl_usd'] for t in sell_trades):+.2f}")

    # ==============================================================================
    # 5. METRİK KARŞILAŞTIRMASI (KAZANANLAR vs KAYBEDENLER)
    # ==============================================================================
    def stats_for(trades, key):
        vals = [float(t.get(key, 0.0)) for t in trades]
        if not vals:
            return 0.0, 0.0, 0.0
        return float(np.mean(vals)), float(np.median(vals)), float(np.std(vals))

    metrics_to_check = [
        ("entry_rsi", "Giriş RSI(14)"),
        ("entry_cmo", "Giriş CMO(14)"),
        ("entry_cci", "Giriş CCI(20)"),
        ("entry_adx", "Giriş ADX(14) Trend Gücü"),
        ("entry_macd_hist", "Giriş MACD Histogramı"),
        ("entry_score", "Giriş Radar Skoru"),
        ("entry_atr", "Giriş ATR (Pip)"),
        ("entry_dist_ema21_pct", "EMA21'e Uzaklık (% Overextension)"),
        ("entry_dist_ema50_pct", "EMA50'e Uzaklık (%)"),
        ("entry_body_ratio", "Mum Gövde Oranı (Body/Range)"),
        ("duration_bars", "İşlem Süresi (5M Bar Sayısı)"),
    ]

    print(f"\n🔬 GÖSTERGE DÜZEYİNDE KARŞILAŞTIRMA (KAZANAN vs KAYBEDEN):")
    print(f"{'GÖSTERGE':<35} | {'KAZANAN (Ort/Med)':<20} | {'KAYBEDEN (Ort/Med)':<20} | {'FARK / TESPİT':<20}")
    print("-" * 105)

    diagnostic_summary = {}
    for key, label in metrics_to_check:
        w_mean, w_med, _ = stats_for(winners, key)
        l_mean, l_med, _ = stats_for(losers, key)
        diff = l_mean - w_mean
        print(f"{label:<35} | {w_mean:7.2f} / {w_med:7.2f}     | {l_mean:7.2f} / {l_med:7.2f}     | Diff: {diff:+7.2f}")
        diagnostic_summary[key] = {
            "label": label,
            "win_mean": round(w_mean, 2),
            "win_median": round(w_med, 2),
            "loss_mean": round(l_mean, 2),
            "loss_median": round(l_med, 2),
            "diff": round(diff, 2),
        }

    # ==============================================================================
    # 6. ZARAR TÜRLERİ VE KÖK NEDEN KÜMELEMESİ (FAILURE MODES)
    # ==============================================================================
    print(f"\n🚨 KAYBEDEN İŞLEMLERİN KÖK NEDEN KÜMELEMESİ (120 Kayıp):")

    # KÜME 1: Aşırı Uzama / FOMO Girişi (Overextended Entry)
    # Fiyat EMA21'den %0.4'ten fazla uzaklaşmışken girilen işlemler (Tepeden BUY, Dipten SELL)
    overextended_losses = [t for t in losers if abs(t["entry_dist_ema21_pct"]) > 0.35]
    print(f"  1. Aşırı Uzama / FOMO Girişi (|Fiyat - EMA21| > %0.35):")
    print(f"     -> {len(overextended_losses)} kayıp ({len(overextended_losses)/loss_n*100:.1f}%), Toplam Kayıp: -${abs(sum(t['pnl_usd'] for t in overextended_losses)):.2f}")

    # KÜME 2: Düşük Trend / Testere (Chop / ADX < 22)
    # ADX trend gücü 22'nin altındayken yatay testere piyasasında stop avı
    chop_losses = [t for t in losers if t["entry_adx"] < 22.0]
    print(f"  2. Ölü Piyasa / Testere Tuzağı (ADX < 22.0):")
    print(f"     -> {len(chop_losses)} kayıp ({len(chop_losses)/loss_n*100:.1f}%), Toplam Kayıp: -${abs(sum(t['pnl_usd'] for t in chop_losses)):.2f}")

    # KÜME 3: HTF Trend Çelişkisi (Counter-HTF Trap)
    # 15M HTF trend ile ters yönde giriş
    htf_conflict_losses = [t for t in losers if (t["direction"] == "BUY" and t["entry_htf_trend"] == "BEARISH") or (t["direction"] == "SELL" and t["entry_htf_trend"] == "BULLISH")]
    print(f"  3. 15M HTF Trend Çelişkisi (Trende Karşı Giriş):")
    print(f"     -> {len(htf_conflict_losses)} kayıp ({len(htf_conflict_losses)/loss_n*100:.1f}%), Toplam Kayıp: -${abs(sum(t['pnl_usd'] for t in htf_conflict_losses)):.2f}")

    # KÜME 4: Zayıf Mum / İtici Güçsüz Mum (Body Ratio < 0.30 - Fitil Tuzağı)
    wick_trap_losses = [t for t in losers if t["entry_body_ratio"] < 0.30]
    print(f"  4. Zayıf Gövde / Doji / Fitil Tuzağı (Mum Gövdesi < %30):")
    print(f"     -> {len(wick_trap_losses)} kayıp ({len(wick_trap_losses)/loss_n*100:.1f}%), Toplam Kayıp: -${abs(sum(t['pnl_usd'] for t in wick_trap_losses)):.2f}")

    # KÜME 5: Seans Dışı / Likidite Boşluğu (NY Kapanış / Gece Asya Geçişi)
    session_trap_losses = [t for t in losers if t["entry_hour_utc"] in (21, 22, 23, 0)]
    print(f"  5. Gece Likidite Boşluğu (21:00 - 01:00 UTC):")
    print(f"     -> {len(session_trap_losses)} kayıp ({len(session_trap_losses)/loss_n*100:.1f}%), Toplam Kayıp: -${abs(sum(t['pnl_usd'] for t in session_trap_losses)):.2f}")

    # ==============================================================================
    # 7. SİMÜLASYON: GELİŞTİRİLMİŞ AKILLI FİLTRE VE ÇÖZÜMLERİN TESTİ
    # ==============================================================================
    print(f"\n🛠️ GELİŞTİRME SİMÜLASYONU: Hatalı İşlemleri Engelleyen Akıllı Kalkan Testi:")

    def passes_smart_filter(t):
        # 1. Aşırı uzama filtresi: Fiyat 5M EMA21'den %0.35'ten fazla uzaklaşmışsa FOMO girişini engelle
        if abs(t["entry_dist_ema21_pct"]) > 0.35:
            return False, "OVEREXTENDED_EMA21"
        # 2. ADX Trend Gücü Kapısı: ADX < 20 ise testerede işlem açma
        if t["entry_adx"] < 20.0:
            return False, "WEAK_TREND_ADX"
        # 3. Fitil Tuzağı: Mum gövdesi barın en az %30'u olmalı (Doji/Fitil tepesi değil)
        if t["entry_body_ratio"] < 0.28:
            return False, "WICK_DOJI_TRAP"
        # 4. HTF Trend Mutlak Uyumu: 15M trend ters ise girme
        if (t["direction"] == "BUY" and t["entry_htf_trend"] == "BEARISH") or (t["direction"] == "SELL" and t["entry_htf_trend"] == "BULLISH"):
            return False, "COUNTER_HTF_TREND"
        return True, "PASSED"

    filtered_trades = []
    blocked_winners = 0
    blocked_losers = 0
    saved_usd = 0.0
    missed_win_usd = 0.0

    for t in closed_trades:
        ok, reason = passes_smart_filter(t)
        if ok:
            filtered_trades.append(t)
        else:
            if t["pnl_usd"] < 0:
                blocked_losers += 1
                saved_usd += abs(t["pnl_usd"])
            else:
                blocked_winners += 1
                missed_win_usd += t["pnl_usd"]

    new_tot_pnl = sum(t["pnl_usd"] for t in filtered_trades)
    new_wins = len([t for t in filtered_trades if t["pnl_usd"] > 0])
    new_losses = len([t for t in filtered_trades if t["pnl_usd"] < 0 and t["exit_reason"] == "SL_HIT"])
    new_wr = (new_wins / max(1, len(filtered_trades))) * 100.0

    print(f"  Engellenen Zararlı İşlem (Kurtarılan): {blocked_losers} Adet (+${saved_usd:.2f}) 🛡️")
    print(f"  Filtreye Takılan Kazançlı İşlem:      {blocked_winners} Adet (-${missed_win_usd:.2f})")
    print(f"  Net Kâr Farkı (İyileşme):             +${(saved_usd - missed_win_usd):+.2f} 🚀")
    print(f"  -------------------------------------------------------------")
    print(f"  Önceki Durum:    {total_n} İşlem | %{win_rate:.1f} WR | Net: ${tot_pnl:+.2f}")
    print(f"  Akıllı Filtreli: {len(filtered_trades)} İşlem | %{new_wr:.1f} WR | Net: ${new_tot_pnl:+.2f}")

    # Output detailed report json
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "btcusd_7d_loss_diagnosis.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    report_data = {
        "days": days,
        "total_trades": total_n,
        "win_rate": round(win_rate, 2),
        "total_pnl": round(tot_pnl, 2),
        "winners_count": win_n,
        "losers_count": loss_n,
        "be_count": be_n,
        "gross_win": round(gross_win, 2),
        "gross_loss": round(gross_loss, 2),
        "buy_trades": {"total": len(buy_trades), "win": buy_win, "loss": buy_loss, "pnl": round(sum(t['pnl_usd'] for t in buy_trades), 2)},
        "sell_trades": {"total": len(sell_trades), "win": sell_win, "loss": sell_loss, "pnl": round(sum(t['pnl_usd'] for t in sell_trades), 2)},
        "metrics_summary": diagnostic_summary,
        "clusters": {
            "overextended_ema21": {"count": len(overextended_losses), "loss_usd": round(sum(t['pnl_usd'] for t in overextended_losses), 2)},
            "chop_adx_below_22": {"count": len(chop_losses), "loss_usd": round(sum(t['pnl_usd'] for t in chop_losses), 2)},
            "htf_conflict": {"count": len(htf_conflict_losses), "loss_usd": round(sum(t['pnl_usd'] for t in htf_conflict_losses), 2)},
            "wick_trap": {"count": len(wick_trap_losses), "loss_usd": round(sum(t['pnl_usd'] for t in wick_trap_losses), 2)},
            "session_liquidity_trap": {"count": len(session_trap_losses), "loss_usd": round(sum(t['pnl_usd'] for t in session_trap_losses), 2)},
        },
        "simulation": {
            "original_trades": total_n,
            "original_net_pnl": round(tot_pnl, 2),
            "original_win_rate": round(win_rate, 2),
            "filtered_trades": len(filtered_trades),
            "filtered_net_pnl": round(new_tot_pnl, 2),
            "filtered_win_rate": round(new_wr, 2),
            "blocked_losers": blocked_losers,
            "saved_loss_usd": round(saved_usd, 2),
            "net_improvement_usd": round(saved_usd - missed_win_usd, 2),
        }
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Detaylı Teşhis Raporu Kaydedildi: {out_path}")

if __name__ == "__main__":
    run_btcusd_deep_loss_diagnostics(days=7)
