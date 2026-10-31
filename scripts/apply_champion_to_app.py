path = r"d:\PROJELLER\globall\backend\app\spot_monitor.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update TIMEFRAMES to optimal proven levels
old_tf = '''TIMEFRAMES = {
    "5m": {"tp_pct": 1.2, "sl_pct": 0.9, "label": "5m Scalp"},
    "15m": {"tp_pct": 1.8, "sl_pct": 1.1, "label": "15m Standart"},
    "1h": {"tp_pct": 3.2, "sl_pct": 1.6, "label": "1h Swing"}
}'''

new_tf = '''TIMEFRAMES = {
    "5m": {"tp_pct": 1.4, "sl_pct": 0.9, "label": "5m Scalp"},
    "15m": {"tp_pct": 2.2, "sl_pct": 1.1, "label": "15m Standart"},
    "1h": {"tp_pct": 3.2, "sl_pct": 1.6, "label": "1h Swing"}
}'''

assert old_tf in content, "old_tf not found"
content = content.replace(old_tf, new_tf)

# 2. Update ACTIVE_STRATEGIES with champion order and evidence
old_strategies_block = '''ACTIVE_STRATEGIES = [
    {
        "code": "ema_bounce",
        "label": "EMA 50 Sekmesi + KDJ Dip",
        "score": 94.0,
        "description": "Ana trend içinde EMA50 desteğine geri çekilme + KDJ dip teyidiyle sekme girişi.",
        "evidence": "Lab şampiyonu: WinRate %83-100",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "squeeze_breakout",
        "label": "BB-KC Sıkışma Kırılımı",
        "score": 93.0,
        "description": "Bollinger bantları Keltner kanalına sıkıştıktan sonra kapanışın üst bandı yukarı kesmesi (volatilite genişleme kırılımı).",
        "evidence": "Lab v2 (5m): PF 1.74; walk-forward optimize kademe OOS doğrulamalı (PF 1.47)",
        "timeframes": ["5m", "15m", "1h"],
        "tp_sl_override": {"5m": {"tp_pct": 1.0, "sl_pct": 1.5}},
    },
    {
        "code": "stc_cycle",
        "label": "Schaff Trend Cycle (STC Dip)",
        "score": 92.0,
        "description": "STC'nin 25 seviyesinin altından yukarı kırılmasıyla döngüsel dip dönüş girişi.",
        "evidence": "SOL/LINK şampiyonu: WinRate %64+, PF 2.79",
        "timeframes": ["5m", "15m", "1h"],
    },'''

new_strategies_block = '''ACTIVE_STRATEGIES = [
    {
        "code": "squeeze_breakout",
        "label": "Trend + BB Sıkışma + Hacim Patlaması",
        "score": 98.0,
        "description": "EMA50 ana trendi içinde Bollinger-Keltner volatilite sıkışması sonrası %125+ hacim patlamasıyla üst bant kırılımı.",
        "evidence": "162.000 mum Lab Şampiyonu: 409 işlem, PF 1.56, +%37.15 Net Kâr (INJ PF 3.69, AVAX PF 2.65)",
        "timeframes": ["5m", "15m", "1h"],
        "tp_sl_override": {"15m": {"tp_pct": 2.2, "sl_pct": 1.1}},
    },
    {
        "code": "zlmacd_momentum",
        "label": "Zero-Lag MACD + Momentum + Trend",
        "score": 94.0,
        "description": "ZLMACD histogramının sıfırı yukarı kesmesi + EMA20 ≥ EMA50 ana trend filtresi.",
        "evidence": "OP & Trend Şampiyonu: PF 2.17; hızlı momentum kırılımları",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "stc_cycle",
        "label": "Schaff Trend Cycle (STC Hacimli Dip)",
        "score": 92.0,
        "description": "STC'nin 25 seviyesinin altından yukarı kırılmasıyla hacimli döngüsel dip dönüş girişi.",
        "evidence": "SOL/LINK/NEAR şampiyonu: WinRate %64+, PF 2.79",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "ema_bounce",
        "label": "EMA 50 Sekmesi + KDJ Dip",
        "score": 90.0,
        "description": "Ana trend içinde EMA50 desteğine geri çekilme + KDJ dip teyidiyle sekme girişi.",
        "evidence": "Trend içi geri çekilme filtresi; güçlü boğa trendlerinde yüksek başarı",
        "timeframes": ["5m", "15m", "1h"],
    },'''

assert old_strategies_block in content, "old_strategies_block not found"
content = content.replace(old_strategies_block, new_strategies_block)

# 3. Update priority inside run_single_scan()
old_scan_rules = '''                # 1. EMA 50 Pullback Bounce + KDJ (WinRate %83-%100 Şampiyonu)
                if ema_bounce and (dip_buy or j_val <= 25.0) and enabled.get("ema_bounce", True):
                    matched = True
                    strategy_code = "ema_bounce"
                    strategy_label = "EMA 50 Sekmesi + KDJ Dip"
                    score = 94.0
                    note = f"EMA50 desteginde (%{dist_ema}), KDJ J={j_val:.1f}"

                # 2. BB-KC Sıkışma Kırılımı (Lab v2: 5m WR %56.8, PF 1.74, 13/17 coin pozitif,
                #    26 komşu parametreden 23'ü net pozitif — sağlamlık doğrulandı)
                elif sq_break and enabled.get("squeeze_breakout", True):
                    matched = True
                    strategy_code = "squeeze_breakout"
                    strategy_label = "BB-KC Sıkışma Kırılımı"
                    score = 93.0
                    note = f"Bollinger-Keltner sikismasi sonrasi ust bant kirilimi (BBU={sq_bb_up:.6g}, BBW=%{sq_width:.2f})"

                # 3. Schaff Trend Cycle (STC) Dip Dönüşü (SOL/LINK Şampiyonu WinRate %64+, PF 2.79)
                elif stc_dip and enabled.get("stc_cycle", True):
                    matched = True
                    strategy_code = "stc_cycle"
                    strategy_label = "Schaff Trend Cycle (STC Dip)"
                    score = 92.0
                    note = f"STC 25 altından yukarı kırdı (STC={stc_val:.1f})"

                # 4. Zero-Lag MACD + EMA 20/50 Momentum Sıçraması (OP/AVAX Şampiyonu PF 2.17)
                elif zl_cross and trend_bull and enabled.get("zlmacd_momentum", True):
                    matched = True
                    strategy_code = "zlmacd_momentum"
                    strategy_label = "Zero-Lag MACD + Momentum"
                    score = 90.0
                    note = f"ZLMACD sıfırı yukarı kesti (Hist={zl_hist:.4f}), EMA20>=EMA50"'''

new_scan_rules = '''                # 1. Trend + BB-KC Sıkışma + Hacim Patlaması (162.000 Mum Lab Şampiyonu PF 1.56, +%37.15 Net Kâr)
                if sq_break and trend_bull and (vols[-1] >= avg_vol * 1.25) and enabled.get("squeeze_breakout", True):
                    matched = True
                    strategy_code = "squeeze_breakout"
                    strategy_label = "Trend + BB Sıkışma + Hacim Patlaması"
                    score = 98.0
                    note = f"EMA50 ustu BB-KC sikisma kirilimi + Hacim {vols[-1]/avg_vol:.2f}x (BBU={sq_bb_up:.6g})"

                # 2. Zero-Lag MACD + EMA 20/50 Momentum Sıçraması (OP/AVAX Şampiyonu PF 2.17)
                elif zl_cross and trend_bull and enabled.get("zlmacd_momentum", True):
                    matched = True
                    strategy_code = "zlmacd_momentum"
                    strategy_label = "Zero-Lag MACD + Momentum + Trend"
                    score = 94.0
                    note = f"ZLMACD sıfırı yukarı kesti (Hist={zl_hist:.4f}), EMA20>=EMA50"

                # 3. Schaff Trend Cycle (STC) Hacimli Dip Dönüşü
                elif stc_dip and (vols[-1] >= avg_vol * 1.15) and enabled.get("stc_cycle", True):
                    matched = True
                    strategy_code = "stc_cycle"
                    strategy_label = "Schaff Trend Cycle (STC Hacimli Dip)"
                    score = 92.0
                    note = f"STC 25 altından yukarı kırdı (STC={stc_val:.1f}), Hacim={vols[-1]/avg_vol:.2f}x"

                # 4. EMA 50 Pullback Bounce + KDJ Dip
                elif ema_bounce and (dip_buy or j_val <= 25.0) and trend_bull and enabled.get("ema_bounce", True):
                    matched = True
                    strategy_code = "ema_bounce"
                    strategy_label = "EMA 50 Sekmesi + KDJ Dip"
                    score = 90.0
                    note = f"EMA50 desteginde (%{dist_ema}), KDJ J={j_val:.1f}"'''

assert old_scan_rules in content, "old_scan_rules not found"
content = content.replace(old_scan_rules, new_scan_rules)

# 4. Update Dynamic Exit thresholds in update_open_signals_pnl (allowing breathing room for 2.2% runners)
old_dynamic_exit = '''        # 1. Başabaş Stop (Breakeven + Komisyon Kurtarma):
        # Kâr %0.70'e ulaşırsa, stop seviyesini maliyet + %0.12 (komisyon kurtarma + ufak kâr) seviyesine çek
        if new_mfe >= 0.70:
            be_level = entry_p * 1.0012
            if be_level > stop_p:
                stop_p = be_level

        # 2. Kademeli Kâr Kilidi (Profit Ratchet):
        # Kâr %1.20'ye ulaşırsa, stop seviyesini en az maliyet + %0.60 seviyesine yükselt
        if new_mfe >= 1.20:
            lock_level_1 = entry_p * 1.0060
            if lock_level_1 > stop_p:
                stop_p = lock_level_1

        # 3. Zirve Takipçi Stop (Peak Trailing Stop):
        # Kâr %1.60'ı geçerse, stop'u zirveden geriye %0.55 mesafede takip ettir
        if new_mfe >= 1.60:
            peak_price = entry_p * (1.0 + new_mfe / 100.0)
            trail_level_2 = peak_price * 0.9945
            if trail_level_2 > stop_p:
                stop_p = trail_level_2'''

new_dynamic_exit = '''        # 1. Dinamik Kâr Nefes Alanı ve Başabaş Kilidi:
        # Kâr %1.10'a ulaştığında stop seviyesini maliyet + %0.20 net kâr seviyesine çek (erken stopu önler)
        if new_mfe >= 1.10:
            be_level = entry_p * 1.0020
            if be_level > stop_p:
                stop_p = be_level

        # 2. Kademeli Kâr Kilidi (Profit Ratchet):
        # Kâr %1.50'ye ulaştığında stop seviyesini en az maliyet + %0.80 net kâr seviyesine yükselt
        if new_mfe >= 1.50:
            lock_level_1 = entry_p * 1.0080
            if lock_level_1 > stop_p:
                stop_p = lock_level_1

        # 3. Zirve Takipçi Stop (Peak Trailing Stop):
        # Kâr %1.80'i geçerse, stop'u zirveden geriye %0.50 mesafede sıkı takip ettir
        if new_mfe >= 1.80:
            peak_price = entry_p * (1.0 + new_mfe / 100.0)
            trail_level_2 = peak_price * 0.9950
            if trail_level_2 > stop_p:
                stop_p = trail_level_2'''

assert old_dynamic_exit in content, "old_dynamic_exit not found"
content = content.replace(old_dynamic_exit, new_dynamic_exit)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Successfully updated spot_monitor.py with champion rules!")
