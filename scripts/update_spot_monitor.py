import re

path = r"d:\PROJELLER\globall\backend\app\spot_monitor.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update TIMEFRAMES
old_tf = '''TIMEFRAMES = {
    "5m": {"tp_pct": 1.5, "sl_pct": 0.9, "label": "5m Scalp"},
    "15m": {"tp_pct": 2.2, "sl_pct": 1.2, "label": "15m Standart"},
    "1h": {"tp_pct": 4.0, "sl_pct": 2.0, "label": "1h Swing"}
}'''

new_tf = '''TIMEFRAMES = {
    "5m": {"tp_pct": 1.2, "sl_pct": 0.9, "label": "5m Scalp"},
    "15m": {"tp_pct": 1.8, "sl_pct": 1.1, "label": "15m Standart"},
    "1h": {"tp_pct": 3.2, "sl_pct": 1.6, "label": "1h Swing"}
}'''

assert old_tf in content, "old_tf not found"
content = content.replace(old_tf, new_tf)

# 2. Update _compute_live_strategy_stats wins query
old_wins = "COUNT(*) FILTER (WHERE status = 'WIN_TP') AS wins,"
new_wins = "COUNT(*) FILTER (WHERE status IN ('WIN_TP', 'WIN_TRAILING', 'WIN_EXPIRED') OR (status <> 'OPEN' AND net_pnl_try > 0)) AS wins,"
assert old_wins in content, "old_wins not found"
content = content.replace(old_wins, new_wins)

# 3. Update update_open_signals_pnl
old_pnl_func = '''async def update_open_signals_pnl(conn):
    """Açık pozisyonları anlık fiyatlarla denetler, TP veya SL tetiklendiyse kapatır."""
    open_rows = await conn.fetch("SELECT * FROM spot_monitor_signals WHERE status = 'OPEN'")
    if not open_rows:
        return

    prices = _fetch_all_prices()
    now_utc = datetime.now(timezone.utc)

    for row in open_rows:
        sym = row["symbol"]
        curr_p = prices.get(sym)
        if not curr_p:
            continue

        entry_p = row["entry_price"]
        target_p = row["target_price"]
        stop_p = row["stop_price"]
        pnl_pct = ((curr_p - entry_p) / entry_p) * 100.0

        # MFE / MAE güncelleme
        old_mfe = row["mfe_pct"] or 0.0
        old_mae = row["mae_pct"] or 0.0
        new_mfe = max(old_mfe, pnl_pct)
        new_mae = min(old_mae, pnl_pct)

        status = "OPEN"
        exit_price = None
        exit_time = None
        net_try = 0.0
        comm_try = row["commission_try"] or (TRADE_SIZE_TRY * COMMISSION_RATE * 2)

        # TP Hedefine Ulaştı mı?
        if curr_p >= target_p:
            status = "WIN_TP"
            exit_price = target_p
            exit_time = now_utc
            gross_profit = TRADE_SIZE_TRY * ((target_p - entry_p) / entry_p)
            net_try = gross_profit - comm_try

        # Stop-Loss Seviyesine İndi mi?
        elif curr_p <= stop_p:
            status = "LOSS_SL"
            exit_price = stop_p
            exit_time = now_utc
            gross_loss = TRADE_SIZE_TRY * ((stop_p - entry_p) / entry_p)
            net_try = gross_loss - comm_try

        # Süre Aşımı (24 saat geçtiyse ve kapanmadıysa anlık fiyattan realize et)
        elif (now_utc - row["detected_at"]).total_seconds() > (3600 if row["timeframe"] == "5m" else (9000 if row["timeframe"] == "15m" else 21600)):
            status = "EXPIRED"
            exit_price = curr_p
            exit_time = now_utc
            gross_ret = TRADE_SIZE_TRY * (pnl_pct / 100.0)
            net_try = gross_ret - comm_try

        if status != "OPEN":
            await conn.execute("""
                UPDATE spot_monitor_signals
                SET status = $1, exit_price = $2, exit_time = $3,
                    pnl_pct = $4, mfe_pct = $5, mae_pct = $6, net_pnl_try = $7
                WHERE id = $8
            """, status, exit_price, exit_time, pnl_pct, new_mfe, new_mae, net_try, row["id"])
        else:
            # Açık durumu anlık metriklerle güncelle
            await conn.execute("""
                UPDATE spot_monitor_signals
                SET pnl_pct = $1, mfe_pct = $2, mae_pct = $3
                WHERE id = $4
            """, pnl_pct, new_mfe, new_mae, row["id"])'''

new_pnl_func = '''async def update_open_signals_pnl(conn):
    """Açık pozisyonları anlık fiyatlarla denetler, Dinamik Takipçi Stop (Dynamic Exit Architect) ile kârı kilitler ve kapatır."""
    open_rows = await conn.fetch("SELECT * FROM spot_monitor_signals WHERE status = 'OPEN'")
    if not open_rows:
        return

    prices = _fetch_all_prices()
    now_utc = datetime.now(timezone.utc)

    for row in open_rows:
        sym = row["symbol"]
        curr_p = prices.get(sym)
        if not curr_p:
            continue

        entry_p = row["entry_price"]
        target_p = row["target_price"]
        stop_p = row["stop_price"]
        pnl_pct = ((curr_p - entry_p) / entry_p) * 100.0

        # MFE / MAE güncelleme
        old_mfe = row["mfe_pct"] or 0.0
        old_mae = row["mae_pct"] or 0.0
        new_mfe = max(old_mfe, pnl_pct)
        new_mae = min(old_mae, pnl_pct)

        # ----------------------------------------------------
        # DYNAMIC EXIT ARCHITECT: Kademeli Kâr Kilidi & Takipçi Stop
        # ----------------------------------------------------
        # 1. Başabaş Stop (Breakeven + Komisyon Kurtarma):
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
                stop_p = trail_level_2

        status = "OPEN"
        exit_price = None
        exit_time = None
        net_try = 0.0
        comm_try = row["commission_try"] or (TRADE_SIZE_TRY * COMMISSION_RATE * 2)

        # TP Hedefine Ulaştı mı?
        if curr_p >= target_p:
            status = "WIN_TP"
            exit_price = target_p
            exit_time = now_utc
            gross_profit = TRADE_SIZE_TRY * ((target_p - entry_p) / entry_p)
            net_try = gross_profit - comm_try

        # Stop-Loss veya Takipçi Kâr Stop Seviyesine İndi mi?
        elif curr_p <= stop_p:
            exit_price = stop_p
            exit_time = now_utc
            gross_diff = TRADE_SIZE_TRY * ((stop_p - entry_p) / entry_p)
            net_try = gross_diff - comm_try
            if stop_p > entry_p:
                status = "WIN_TRAILING"  # Kârla / Başabaşla kapandı
            else:
                status = "LOSS_SL"  # Başlangıç zararıyla stop oldu

        # Süre Aşımı (5m için 60 dk, 15m için 150 dk, 1h için 360 dk)
        elif (now_utc - row["detected_at"]).total_seconds() > (3600 if row["timeframe"] == "5m" else (9000 if row["timeframe"] == "15m" else 21600)):
            exit_price = curr_p
            exit_time = now_utc
            gross_ret = TRADE_SIZE_TRY * (pnl_pct / 100.0)
            net_try = gross_ret - comm_try
            if net_try > 0:
                status = "WIN_EXPIRED"
            else:
                status = "EXPIRED"

        if status != "OPEN":
            await conn.execute("""
                UPDATE spot_monitor_signals
                SET status = $1, exit_price = $2, exit_time = $3,
                    pnl_pct = $4, mfe_pct = $5, mae_pct = $6, net_pnl_try = $7,
                    stop_price = $8
                WHERE id = $9
            """, status, exit_price, exit_time, pnl_pct, new_mfe, new_mae, net_try, stop_p, row["id"])
        else:
            # Açık durumu anlık metriklerle ve güncellenmiş stop_price ile kaydet
            await conn.execute("""
                UPDATE spot_monitor_signals
                SET pnl_pct = $1, mfe_pct = $2, mae_pct = $3, stop_price = $4
                WHERE id = $5
            """, pnl_pct, new_mfe, new_mae, stop_p, row["id"])'''

assert old_pnl_func in content, "old_pnl_func not found"
content = content.replace(old_pnl_func, new_pnl_func)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Successfully updated spot_monitor.py!")
