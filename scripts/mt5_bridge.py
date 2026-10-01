#!/usr/bin/env python3
"""Scalper Agent Global - IC Markets MetaTrader 5 (MT5) Canlı Köprü İşçisi.

Bu script, kullanıcının Windows bilgisayarındaki IC Markets MT5 terminaline bağlanır,
canlı bakiye ve pozisyonları web paneline (https://global.erkanerdem.online) eşitler ve
otonom scalper sinyallerini gerçek MT5 Demo hesabında milisaniyeler içinde icra eder.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
import urllib.request
import urllib.error

# Windows konsolunda Türkçe cp1254 karakter kodlaması hatasını önle
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 kütüphanesi bulunamadı! 'pip install MetaTrader5' komutuyla yükleyin.")
    sys.exit(1)


# Varsayılan Konfigürasyon
DEFAULT_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5 IC Markets Global\terminal64.exe"
DEFAULT_LOGIN = int(os.environ.get("MT5_LOGIN", 53077151))
DEFAULT_PASSWORD = os.environ.get("MT5_PASSWORD", "gE&w5OzpUyQmWx")
DEFAULT_SERVER = os.environ.get("MT5_SERVER", "ICMarketsSC-Demo")
DEFAULT_API_URL = os.environ.get("SCALPER_API_URL", "https://global.erkanerdem.online")

# Sert Risk Sınırları (Asla aşılamaz)
HARD_MAX_FOREX_LOT = 0.05
HARD_MAX_GOLD_LOT = 0.02
HARD_MIN_GOLD_COOLDOWN_SEC = 60.0
LAST_GOLD_EXIT_TIME = 0.0


def print_banner():
    print(r"""
======================================================================
  ⚡ SCALPER AGENT GLOBAL - IC MARKETS MT5 OTOMATİK KÖPRÜ (BRIDGE) ⚡
======================================================================
    """)


def connect_mt5(path: str, login: int, password: str, server: str) -> bool:
    """MT5 Terminaline bağlanır."""
    if not os.path.exists(path):
        print(f"[UYARI] Belirtilen MT5 yolu bulunamadı: {path}")
        print("Varsayılan yüklü terminal aranıyor...")
        init_res = mt5.initialize(login=login, password=password, server=server, timeout=30000)
    else:
        init_res = mt5.initialize(path=path, login=login, password=password, server=server, timeout=30000)

    if not init_res:
        err = mt5.last_error()
        print(f"[HATA] MT5 Bağlantısı Başarısız! Hata Kodu: {err}")
        return False

    acc = mt5.account_info()
    if not acc:
        print("[HATA] Hesap bilgileri alınamadı!")
        return False

    print(f"✓ MT5 Başarıyla Bağlandı!")
    print(f"  • Hesap No : {acc.login} ({acc.name})")
    print(f"  • Sunucu   : {acc.server}")
    print(f"  • Bakiye   : ${acc.balance:,.2f} {acc.currency}")
    print(f"  • Özsermaye: ${acc.equity:,.2f} {acc.currency}")
    print(f"  • Kaldıraç : 1:{acc.leverage}")
    return True


def get_symbol_trading_specs(
    symbol: str,
    base_sl: float = 12.0,
    base_tp: float = 22.0,
    base_be: float = 10.0,
    base_trail: float = 16.0,
    atr_pips: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Her parite ve emtia için doğru pip büyüklüğünü (pip_size),
    volatilite çarpanını (mult), basamak sayısını (digits) ve lot başına 1 pip dolar değerini döner.

    Özellikle Ons Altın (XAUUSD) için:
    - MT5 ve uluslararası piyasalarda 1 pip = 0.10 USD (10 point / 10 cent) kabul edilir.
    - Altın'ın yüksek oynaklığı ($4,200 seviyesinde dakikalık mumlar $2 - $5 hareket eder)
      nedeniyle 3.0x taban volatilite tamponu (min 36 pip / $3.60 USD) ve dinamik ATR tamponu uygulanır.
    - Erken başabaş (breakeven) stop kilitlenmesini engellemek için altın BE eşiği en az 25 pip ($2.50) olmalıdır.
    - Standart Forex paritelerinde de erken boğulmayı önlemek için BE eşiği en az 10.0 pip olmalıdır.
    """
    s = str(symbol).upper().replace("/", "").strip()
    clean_sym = s.split(".")[0].split("+")[0].split("-")[0].replace("#", "").strip()
    base_be_floored = max(14.0, base_be)

    if "XAU" in clean_sym or "GOLD" in clean_sym:
        pip_size = 0.10          # 1 pip = 0.10 USD (10 cent / 10 point)
        mult = 3.0               # 3.0x volatilite nefes alma çarpanı
        digits = 2
        pip_val = 10.0           # 1 lot (100 oz) * 0.10 USD = $10.0
        base_sl_pips = round(base_sl * mult, 1)
        base_tp_pips = round(base_tp * mult, 1)

        if atr_pips is not None and atr_pips > 0:
            eff_sl_pips = max(base_sl_pips, round(atr_pips * 1.5, 1))
        else:
            eff_sl_pips = base_sl_pips

        eff_tp_pips = max(base_tp_pips, round(eff_sl_pips * 1.83, 1))
        eff_be_pips = max(25.0, round(eff_sl_pips * 0.7, 1))
        eff_trail_pips = max(40.0, round(eff_sl_pips * 1.2, 1))

    elif "XAG" in clean_sym or "SILVER" in clean_sym:
        pip_size = 0.01          # 1 pip = 0.01 USD
        mult = 2.0
        digits = 3
        pip_val = 50.0           # 1 lot (5000 oz) * 0.01 USD = $50.0
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(20.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    elif "USOIL" in clean_sym or "OIL" in clean_sym or "WTI" in clean_sym:
        pip_size = 0.01          # 1 pip = 0.01 USD (1 cent)
        mult = 2.0
        digits = 2
        pip_val = 10.0           # 1 lot (1000 varil) * 0.01 USD = $10.0
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(20.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    elif "JPY" in clean_sym:
        pip_size = 0.01          # 1 pip = 0.01 JPY (10 point)
        mult = 1.0
        digits = 3
        pip_val = 6.60
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(10.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    elif "BTC" in clean_sym:
        pip_size = 1.0           # 1 pip = $1.00
        mult = 5.0
        digits = 2
        pip_val = 1.0
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(40.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    else:
        # Standart Forex (EURUSD, GBPUSD, AUDUSD, NZDUSD, USDCAD, USDCHF)
        pip_size = 0.0001        # 1 pip = 0.0001 (10 point)
        mult = 1.0
        digits = 5
        pip_val = 10.0
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(10.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    return {
        "pip_size": pip_size,
        "digits": digits,
        "pip_val": pip_val,
        "mult": mult,
        "sl_pips": eff_sl_pips,
        "tp_pips": eff_tp_pips,
        "be_pips": eff_be_pips,
        "trail_pips": eff_trail_pips,
    }


def execute_market_order(cmd: dict) -> dict:
    """MT5 üzerinde piyasa emri açar."""
    symbol = cmd.get("symbol", "EURUSD").upper()
    direction = cmd.get("direction", "BUY").upper()
    raw_lots = float(cmd.get("lots", 0.01))
    sl_pips = float(cmd.get("sl_pips", 12.0))
    tp_pips = float(cmd.get("tp_pips", 22.0))
    comment = str(cmd.get("comment", "Scalper Global"))[:31]

    # SERT LOT TAVANI KORUMASI: Forex max 0.05 lot, Ons Altın (XAUUSD) & BTC max 0.02 lot
    is_gold = ("XAU" in symbol or "GOLD" in symbol)
    is_gold_or_crypto = is_gold or ("BTC" in symbol)
    configured_cap = float(CURRENT_SETTINGS.get("max_gold_lot", HARD_MAX_GOLD_LOT)) if is_gold_or_crypto else float(CURRENT_SETTINGS.get("max_forex_lot", HARD_MAX_FOREX_LOT))
    lot_ceiling = min(HARD_MAX_GOLD_LOT if is_gold_or_crypto else HARD_MAX_FOREX_LOT, max(0.01, configured_cap))
    if raw_lots > lot_ceiling:
        print(f"  🛡️ [SERT LOT TAVANI UYGULANDI]: {raw_lots} lot -> {lot_ceiling} lot olarak sınırlandırıldı ({symbol})")
        lots = lot_ceiling
    else:
        lots = raw_lots
    lots = round(max(0.01, lots), 2)

    # Ons Altın (XAUUSD) Soğuma Koruması (Kapanıştan sonra en az 180 sn bekleme kuralı)
    if is_gold:
        cd_sec = float(CURRENT_SETTINGS.get("gold_cooldown_sec", HARD_MIN_GOLD_COOLDOWN_SEC))
        elapsed = time.time() - LAST_GOLD_EXIT_TIME
        if elapsed < cd_sec:
            err = f"Ons Altın soğuma kalkanı aktif: {int(cd_sec - elapsed)} sn kaldı (min {cd_sec:.0f}s)"
            print(f"  🛑 {err}")
            return {"success": False, "error": err}

    # Reversal Flip Kontrolü: Aynı sembolde ters yönde pozisyon varsa önce kapat
    open_positions = mt5.positions_get(symbol=symbol) or []
    for pos in open_positions:
        pos_dir = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
        if pos_dir != direction:
            print(f"  🔄 [TREND DÖNÜŞÜ (FLIP)]: Bilet #{pos.ticket} {pos_dir} pozisyonu kapatılıyor -> Yeni {direction} açılacak...")
            execute_close_order({"ticket": pos.ticket})
            time.sleep(0.3)

    # Sembolü aktif et ve bilgileri çek
    if not mt5.symbol_select(symbol, True):
        return {"success": False, "error": f"Sembol seçilemedi: {symbol}"}

    s_info = mt5.symbol_info(symbol)
    if not s_info:
        return {"success": False, "error": f"Sembol bilgisi alınamadı: {symbol}"}

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return {"success": False, "error": f"Canlı fiyat alınamadı: {symbol}"}

    spec = get_symbol_trading_specs(symbol)
    # Altın için stop mesafesini dinamik spec koruma seviyesinin altına düşürme
    if is_gold:
        sl_pips = max(sl_pips, spec["sl_pips"])
        tp_pips = max(tp_pips, spec["tp_pips"])

    digits = s_info.digits if s_info else spec["digits"]
    pip_size = spec["pip_size"]

    if direction == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
        sl = round(price - (sl_pips * pip_size), digits) if sl_pips > 0 else 0.0
        tp = round(price + (tp_pips * pip_size), digits) if tp_pips > 0 else 0.0
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
        sl = round(price + (sl_pips * pip_size), digits) if sl_pips > 0 else 0.0
        tp = round(price - (tp_pips * pip_size), digits) if tp_pips > 0 else 0.0

    # Dolum modunu broker desteğine göre seç (bitmask: 1=FOK, 2=IOC)
    filling = mt5.ORDER_FILLING_IOC
    if s_info.filling_mode & 2:
        filling = mt5.ORDER_FILLING_IOC
    elif s_info.filling_mode & 1:
        filling = mt5.ORDER_FILLING_FOK
    else:
        filling = mt5.ORDER_FILLING_RETURN

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lots,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 25,
        "magic": 825482,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"  ⚡ [İŞLEM AÇILDI]: Bilet #{res.order} | {symbol} {direction} {lots} Lot @ {price} (TP: {tp}, SL: {sl})")
        return {"success": True, "ticket": res.order, "price": price}
    else:
        comment_err = res.comment if res else str(mt5.last_error())
        print(f"  ❌ [İŞLEM BAŞARISIZ]: {comment_err} (Kod: {res.retcode if res else 'None'})")
        return {"success": False, "error": comment_err}


def execute_close_order(cmd: dict) -> dict:
    """Belirli bir MT5 açık pozisyonunu kapatır."""
    ticket = int(cmd.get("ticket", 0))
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return {"success": False, "error": f"Pozisyon #{ticket} bulunamadı veya kapalı"}

    pos = positions[0]
    symbol = pos.symbol
    direction = "SELL" if pos.type == mt5.POSITION_TYPE_BUY else "BUY"
    order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY

    s_info = mt5.symbol_info(symbol)
    filling = mt5.ORDER_FILLING_IOC
    if s_info and (s_info.filling_mode & 2):
        filling = mt5.ORDER_FILLING_IOC
    elif s_info and (s_info.filling_mode & 1):
        filling = mt5.ORDER_FILLING_FOK
    else:
        filling = mt5.ORDER_FILLING_RETURN

    tick = mt5.symbol_info_tick(symbol)
    price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": pos.volume,
        "type": order_type,
        "position": ticket,
        "price": price,
        "deviation": 25,
        "magic": 825482,
        "comment": "Scalper Close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"  🏁 [POZİSYON KAPATILDI]: Bilet #{ticket} | {symbol} Kapatıldı @ {price}")
        if "XAU" in symbol or "GOLD" in symbol:
            global LAST_GOLD_EXIT_TIME
            LAST_GOLD_EXIT_TIME = time.time()
        return {"success": True, "ticket": ticket}
    else:
        comment_err = res.comment if res else str(mt5.last_error())
        print(f"  ❌ [KAPATMA HATASI]: {comment_err}")
        return {"success": False, "error": comment_err}


def execute_modify_sltp(cmd: dict) -> dict:
    """Açık pozisyonun SL veya TP seviyesini günceller (Breakeven & Trailing)."""
    ticket = int(cmd.get("ticket", 0))
    sl = float(cmd.get("sl", 0.0))
    tp = float(cmd.get("tp", 0.0))
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return {"success": False, "error": f"Pozisyon #{ticket} bulunamadı"}

    pos = positions[0]
    symbol = pos.symbol
    s_info = mt5.symbol_info(symbol)
    digits = s_info.digits if s_info else 5
    sl = round(sl, digits)
    tp = round(tp, digits) if tp > 0 else pos.tp

    spec = get_symbol_trading_specs(symbol)
    pip_size = spec["pip_size"]
    if abs(sl - pos.sl) < (0.3 * pip_size) and (tp == 0.0 or abs(tp - pos.tp) < (0.3 * pip_size)):
        return {"success": True, "ticket": ticket, "message": "no changes"}

    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol": symbol,
        "sl": sl,
        "tp": tp,
    }

    res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"  🛡️ [DİNAMİK SL GÜNCELLENDİ]: Bilet #{ticket} ({symbol}) -> Yeni SL: {sl} (BE/Trailing)")
        return {"success": True, "ticket": ticket}
    else:
        err_msg = res.comment if res else str(mt5.last_error())
        print(f"  ⚠️ [SL GÜNCELLEME UYARISI]: Bilet #{ticket} -> {err_msg}")
        return {"success": False, "error": err_msg}


def execute_close_all(cmd: dict) -> dict:
    """Tüm açık MT5 pozisyonlarını sırayla kapatır."""
    positions = mt5.positions_get() or []
    if not positions:
        print("  ℹ️ Kapatılacak açık MT5 pozisyonu yok.")
        return {"success": True, "closed_count": 0}

    print(f"\n🚨 [TOPLU KAPATMA BAŞLATILDI]: {len(positions)} açık MT5 pozisyonu kapatılıyor...")
    closed_count = 0
    for p in positions:
        res = execute_close_order({"ticket": p.ticket})
        if res.get("success"):
            closed_count += 1
        time.sleep(0.1)

    print(f"  🏁 [TOPLU KAPATMA TAMAMLANDI]: {closed_count}/{len(positions)} pozisyon kapatıldı.\n")
    return {"success": True, "closed_count": closed_count}


POSITION_PROTECTION_MAP: Dict[int, str] = {}  # ticket -> "BREAKEVEN" | "TRAILING"
CURRENT_SETTINGS: Dict[str, float] = {
    "breakeven_pips": 14.0,
    "trailing_stop_pips": 20.0,
    "sl_pips": 12.0,
    "tp_pips": 26.0,
    "max_forex_lot": 0.05,
    "max_gold_lot": 0.02,
    "gold_cooldown_sec": 60.0,
}


def check_and_apply_dynamic_exits(be_pips: float, trail_pips: float):
    """Her açık MT5 pozisyonu için Breakeven ve Trailing Stop seviyelerini yerel olarak denetler ve uygular."""
    positions = mt5.positions_get() or []
    if not positions:
        POSITION_PROTECTION_MAP.clear()
        return

    active_tickets = {p.ticket for p in positions}
    for old_t in list(POSITION_PROTECTION_MAP.keys()):
        if old_t not in active_tickets:
            POSITION_PROTECTION_MAP.pop(old_t, None)

    for p in positions:
        ticket = p.ticket
        sym = p.symbol
        s_info = mt5.symbol_info(sym)
        if not s_info:
            continue

        spec = get_symbol_trading_specs(sym, base_be=be_pips, base_trail=trail_pips)
        digits = s_info.digits if s_info else spec["digits"]
        pip_size = spec["pip_size"]
        eff_be_pips = spec["be_pips"]
        eff_trail_pips = spec["trail_pips"]

        direction = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
        entry_p = p.price_open
        cur_p = p.price_current
        cur_sl = p.sl
        cur_tp = p.tp

        if direction == "BUY":
            pnl_pips = (cur_p - entry_p) / pip_size
        else:
            pnl_pips = (entry_p - cur_p) / pip_size

        target_sl = None

        # 1. BREAKEVEN (Başabaş Koruması)
        # Fiyat eff_be_pips kadar kâra ulaştığında, SL'i girişe (+tampon ile) taşı
        if eff_be_pips > 0 and pnl_pips >= eff_be_pips:
            buffer_pips = 5.0 if ("XAU" in sym or "GOLD" in sym) else (15.0 if "BTC" in sym else 3.0)
            be_sl = round(entry_p + (buffer_pips * pip_size if direction == "BUY" else -buffer_pips * pip_size), digits)
            if direction == "BUY":
                if cur_sl < be_sl:
                    target_sl = be_sl
            else:
                if cur_sl == 0.0 or cur_sl > be_sl:
                    target_sl = be_sl
            if POSITION_PROTECTION_MAP.get(ticket) != "TRAILING":
                POSITION_PROTECTION_MAP[ticket] = "BREAKEVEN"

        # 2. TRAILING STOP (İz Süren Stop)
        # Fiyat eff_trail_pips kadar kârda ise fiyatın arkasından takip et
        if eff_trail_pips > 0 and pnl_pips >= eff_trail_pips:
            trail_dist = eff_trail_pips * pip_size
            if direction == "BUY":
                cand_sl = round(cur_p - trail_dist, digits)
                if target_sl is None and cand_sl > cur_sl:
                    target_sl = cand_sl
                elif target_sl is not None and cand_sl > target_sl:
                    target_sl = cand_sl
            else:
                cand_sl = round(cur_p + trail_dist, digits)
                if target_sl is None and (cur_sl == 0.0 or cand_sl < cur_sl):
                    target_sl = cand_sl
                elif target_sl is not None and cand_sl < target_sl:
                    target_sl = cand_sl
            POSITION_PROTECTION_MAP[ticket] = "TRAILING"

        # Eğer yeni bir SL seviyesi belirlendiyse ve mevcut SL'den farklıysa emri MT5'e gönder
        if target_sl is not None and abs(target_sl - cur_sl) >= (0.3 * pip_size):
            req = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": sym,
                "sl": target_sl,
                "tp": cur_tp,
            }
            res = mt5.order_send(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                label = "İz Süren Stop" if (trail_pips > 0 and pnl_pips >= trail_pips) else "Başabaş (BE)"
                print(f"  🛡️ [{label.upper()} KİLİTLENDİ]: Bilet #{ticket} ({sym} {direction}) | Yeni SL: {target_sl} (Kâr: +{pnl_pips:.1f}p)")


def sync_with_server(api_base: str):
    """MT5 durumunu web sunucusuna raporlar ve bekleyen komutları çeker."""
    acc = mt5.account_info()
    if not acc:
        return False, [], {}, "MT5 hesabı bağlı değil"

    account_data = {
        "login": acc.login,
        "name": acc.name,
        "server": acc.server,
        "balance": acc.balance,
        "equity": acc.equity,
        "margin": acc.margin,
        "free_margin": acc.margin_free,
        "leverage": acc.leverage,
        "currency": acc.currency,
    }

    # Açık Pozisyonlar (Dinamik Koruma ve Rozet Bilgileri Dahil)
    positions = []
    be_threshold = float(CURRENT_SETTINGS.get("breakeven_pips", 10.0))
    trail_threshold = float(CURRENT_SETTINGS.get("trailing_stop_pips", 16.0))

    for p in mt5.positions_get() or []:
        ticket = p.ticket
        sym = p.symbol
        s_info = mt5.symbol_info(sym)
        spec = get_symbol_trading_specs(sym, base_be=be_threshold, base_trail=trail_threshold)
        digits = s_info.digits if s_info else spec["digits"]
        pip_size = spec["pip_size"]
        eff_be_pips = spec["be_pips"]
        eff_trail_pips = spec["trail_pips"]

        direction = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
        entry_p = p.price_open
        cur_p = p.price_current
        cur_sl = p.sl
        cur_tp = p.tp

        if direction == "BUY":
            pnl_pips = round((cur_p - entry_p) / pip_size, 1)
        else:
            pnl_pips = round((entry_p - cur_p) / pip_size, 1)

        # Koruma Durumunu (Rozet) Belirle
        prot = POSITION_PROTECTION_MAP.get(ticket, "NORMAL")

        # Gerçek Stop Seviyesine Göre Doğrulama
        if cur_sl > 0:
            if direction == "BUY":
                if cur_sl >= round(entry_p + 1.0 * pip_size, digits):
                    prot = "TRAILING"
                elif cur_sl >= round(entry_p - 0.2 * pip_size, digits) and prot != "TRAILING":
                    prot = "BREAKEVEN"
            else:
                if cur_sl <= round(entry_p - 1.0 * pip_size, digits):
                    prot = "TRAILING"
                elif cur_sl <= round(entry_p + 0.2 * pip_size, digits) and prot != "TRAILING":
                    prot = "BREAKEVEN"

        # Kâr Pip Değerine Göre Doğrulama
        if prot == "NORMAL":
            if eff_trail_pips > 0 and pnl_pips >= eff_trail_pips:
                prot = "TRAILING"
            elif eff_be_pips > 0 and pnl_pips >= eff_be_pips:
                prot = "BREAKEVEN"

        prot_label = (
            "İz Süren Stop (Trailing)" if prot == "TRAILING"
            else ("Başabaş (BE)" if prot == "BREAKEVEN" else "Sabit SL")
        )

        positions.append({
            "ticket": ticket,
            "symbol": sym,
            "direction": direction,
            "lots": p.volume,
            "entry_price": entry_p,
            "current_price": cur_p,
            "sl_price": cur_sl,
            "tp_price": cur_tp,
            "pnl_usd": round(p.profit, 2),
            "pnl_pips": pnl_pips,
            "protection": prot,
            "protection_label": prot_label,
            "breakeven_activated": (prot in ("BREAKEVEN", "TRAILING")),
            "trailing_activated": (prot == "TRAILING"),
            "open_time": datetime.datetime.fromtimestamp(p.time, datetime.timezone.utc).strftime("%H:%M:%S UTC"),
        })

    # Kapanan işlem geçmişi (Broker zaman dilimi farkını tolere etmek için +2 gün buffer)
    deals = []
    now = datetime.datetime.now()
    from_date = now - datetime.timedelta(days=30)
    to_date = now + datetime.timedelta(days=2)
    history = mt5.history_deals_get(from_date, to_date) or []

    # Sadece kapanış (OUT) işlemlerini filtrele
    out_deals = [d for d in history if d.entry == mt5.DEAL_ENTRY_OUT]
    # En son 300 kapanmış işlemi dahil et
    for d in reversed(out_deals[-300:]):
        pos_id = d.position_id
        # Pozisyonun açılış biletini bul (in_deal)
        in_deal = None
        for cand in history:
            if cand.position_id == pos_id and cand.entry == mt5.DEAL_ENTRY_IN:
                in_deal = cand
                break

        entry_p = in_deal.price if in_deal else d.price
        open_time_str = datetime.datetime.fromtimestamp(in_deal.time, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if in_deal else "-"
        close_time_str = datetime.datetime.fromtimestamp(d.time, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        direction = "BUY" if in_deal and in_deal.type == mt5.DEAL_TYPE_BUY else ("SELL" if d.type == mt5.DEAL_TYPE_BUY else "BUY")

        comment = str(d.comment or "")
        reason = "IC Markets MT5"
        if "[tp" in comment.lower():
            reason = "🎯 Kâr Al (TP)"
        elif "[sl" in comment.lower():
            reason = "🛑 Zarar Durdur (SL)"
        elif "[be" in comment.lower():
            reason = "🛡️ Başabaş (BE)"
        elif comment:
            reason = comment

        dur_sec = max(1, d.time - (in_deal.time if in_deal else d.time))
        dur_human = f"{dur_sec // 60} dk {dur_sec % 60} sn" if dur_sec >= 60 else f"{dur_sec} sn"

        # PnL Pip hesabı
        pips = 0.0
        spec = get_symbol_trading_specs(d.symbol)
        pip_size = spec["pip_size"]
        if direction == "BUY":
            pips = round((d.price - entry_p) / pip_size, 1)
        else:
            pips = round((entry_p - d.price) / pip_size, 1)

        deals.append({
            "id": f"MT5-{pos_id}",
            "ticket": pos_id,
            "symbol": d.symbol,
            "display": d.symbol,
            "direction": direction,
            "lots": d.volume,
            "entry_price": entry_p,
            "exit_price": d.price,
            "profit": round(d.profit, 2),
            "pnl_usd": round(d.profit, 2),
            "pnl_pips": pips,
            "commission": round(d.commission, 2),
            "swap": round(d.swap, 2),
            "open_time": open_time_str,
            "exit_time": close_time_str,
            "duration_sec": dur_sec,
            "duration_human": dur_human,
            "exit_reason": reason,
            "exit_reason_title": reason,
            "outcome": "WIN" if d.profit >= 0 else "LOSS",
        })

    # Altın kapanışlarını takip et (Soğuma kalkanı için son kapanış zamanı)
    for d in out_deals[-15:]:
        d_sym = str(d.symbol).upper()
        if "XAU" in d_sym or "GOLD" in d_sym:
            global LAST_GOLD_EXIT_TIME
            if float(d.time) > LAST_GOLD_EXIT_TIME:
                LAST_GOLD_EXIT_TIME = float(d.time)

    # MT5 Terminalinden anlık canlı fiyatları topla
    ticks_data = {}
    for s_check in ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD", "XAGUSD", "USOIL"]:
        t = mt5.symbol_info_tick(s_check)
        if t and t.bid > 0:
            ticks_data[s_check] = {"bid": float(t.bid), "ask": float(t.ask), "last": float(t.last if t.last > 0 else t.ask)}

    payload = {
        "account": account_data,
        "positions": positions,
        "deals": deals,
        "ticks": ticks_data,
        "version": "1.0.0",
    }

    req_url = f"{api_base.rstrip('/')}/api/forex/mt5/sync"
    req = urllib.request.Request(
        req_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "ScalperMT5Bridge/1.0"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=7.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, data.get("commands", []), data.get("settings", {}), None
    except urllib.error.HTTPError as he:
        return False, [], {}, f"HTTP {he.code}: {he.reason}"
    except Exception as e:
        return False, [], {}, str(e)


def main():
    parser = argparse.ArgumentParser(description="Scalper Agent IC Markets MT5 Bridge")
    parser.add_argument("--login", type=int, default=DEFAULT_LOGIN, help="MT5 Demo Hesap No")
    parser.add_argument("--password", type=str, default=DEFAULT_PASSWORD, help="MT5 Şifre")
    parser.add_argument("--server", type=str, default=DEFAULT_SERVER, help="MT5 Sunucu Adı")
    parser.add_argument("--terminal", type=str, default=DEFAULT_TERMINAL_PATH, help="MT5 terminal64.exe yolu")
    parser.add_argument("--api", type=str, default=DEFAULT_API_URL, help="Scalper Agent Web API adresi")
    args = parser.parse_args()

    print_banner()
    print(f"[*] API Sunucusu : {args.api}")
    print(f"[*] MT5 Hesabı   : {args.login} ({args.server})")
    print(f"[*] Terminal Yolu: {args.terminal}")
    print("-" * 70)

    if not connect_mt5(args.terminal, args.login, args.password, args.server):
        print("\n[ÇIKIŞ] Bağlantı kurulamadı. MT5'in açık ve Otomatik İşlem (Algo Trading) butonunun yeşil olduğundan emin olun.")
        sys.exit(1)

    print("\n[✓] Canlı Köprü Dinleme Döngüsü Başlatıldı. Çıkmak için Ctrl+C'ye basın.\n")

    sync_counter = 0
    last_err_time = 0.0
    first_sync = True

    while True:
        try:
            be_pips = float(CURRENT_SETTINGS.get("breakeven_pips", 10.0))
            trail_pips = float(CURRENT_SETTINGS.get("trailing_stop_pips", 16.0))
            # Her açık MT5 pozisyonu için yerel Dinamik Başabaş (BE) ve İz Süren Stop (Trailing) uygula
            check_and_apply_dynamic_exits(be_pips, trail_pips)

            success, commands, settings, err_msg = sync_with_server(args.api)

            if success:
                sync_counter += 1
                CURRENT_SETTINGS.update(settings)
                be_pips = float(CURRENT_SETTINGS.get("breakeven_pips", 10.0))
                trail_pips = float(CURRENT_SETTINGS.get("trailing_stop_pips", 16.0))

                if first_sync or sync_counter % 15 == 0:
                    first_sync = False
                    acc = mt5.account_info()
                    pos_count = len(mt5.positions_get() or [])
                    if acc:
                        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 🟢 Web Paneliyle Senkronize: Bakiye=${acc.balance:.2f} | Equity=${acc.equity:.2f} | Açık MT5 Pozisyon: {pos_count} (BE: {be_pips}p, Trail: {trail_pips}p)")
            else:
                now_t = time.time()
                if now_t - last_err_time > 10.0:
                    last_err_time = now_t
                    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ⚠️ Sunucu senkronizasyon uyarısı: {err_msg}")

            for cmd in commands:
                action = cmd.get("action")
                print(f"\n⚡ [WEB SİNYALİ ALINDI]: {action} -> {cmd}")
                if action == "OPEN_ORDER":
                    execute_market_order(cmd)
                elif action == "CLOSE_ORDER":
                    execute_close_order(cmd)
                elif action == "CLOSE_ALL":
                    execute_close_all(cmd)
                elif action == "MODIFY_SLTP":
                    execute_modify_sltp(cmd)

            time.sleep(1.5)

        except KeyboardInterrupt:
            print("\n[DURDURULDU] Kullanıcı tarafından çıkış yapıldı.")
            break
        except Exception as e:
            print(f"[UYARI] Döngü hatası: {e}")
            time.sleep(3.0)

    mt5.shutdown()
    print("[KAPATILDI] MT5 bağlantısı güvenle kapatıldı.")


if __name__ == "__main__":
    main()
