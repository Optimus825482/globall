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


def execute_market_order(cmd: dict) -> dict:
    """MT5 üzerinde piyasa emri açar."""
    symbol = cmd.get("symbol", "EURUSD").upper()
    direction = cmd.get("direction", "BUY").upper()
    lots = float(cmd.get("lots", 0.01))
    sl_pips = float(cmd.get("sl_pips", 15.0))
    tp_pips = float(cmd.get("tp_pips", 25.0))
    comment = str(cmd.get("comment", "Scalper Global"))[:31]

    # Sembolü aktif et ve bilgileri çek
    if not mt5.symbol_select(symbol, True):
        return {"success": False, "error": f"Sembol seçilemedi: {symbol}"}

    s_info = mt5.symbol_info(symbol)
    if not s_info:
        return {"success": False, "error": f"Sembol bilgisi alınamadı: {symbol}"}

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return {"success": False, "error": f"Canlı fiyat alınamadı: {symbol}"}

    point = s_info.point
    digits = s_info.digits
    pip_size = point * 10 if digits in (3, 5) else point

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

    # Dolum modunu broker desteğine göre seç
    filling = mt5.ORDER_FILLING_IOC
    if s_info.filling_mode & mt5.SYMBOL_FILLING_IOC:
        filling = mt5.ORDER_FILLING_IOC
    elif s_info.filling_mode & mt5.SYMBOL_FILLING_FOK:
        filling = mt5.ORDER_FILLING_FOK

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
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"  🏁 [POZİSYON KAPATILDI]: Bilet #{ticket} | {symbol} Kapatıldı @ {price}")
        return {"success": True, "ticket": ticket}
    else:
        comment_err = res.comment if res else str(mt5.last_error())
        print(f"  ❌ [KAPATMA HATASI]: {comment_err}")
        return {"success": False, "error": comment_err}


def sync_with_server(api_base: str) -> list:
    """MT5 durumunu web sunucusuna raporlar ve bekleyen komutları çeker."""
    acc = mt5.account_info()
    if not acc:
        return []

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

    # Açık Pozisyonlar
    positions = []
    for p in mt5.positions_get() or []:
        positions.append({
            "ticket": p.ticket,
            "symbol": p.symbol,
            "direction": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
            "lots": p.volume,
            "entry_price": p.price_open,
            "current_price": p.price_current,
            "sl_price": p.sl,
            "tp_price": p.tp,
            "pnl_usd": round(p.profit, 2),
            "open_time": datetime.datetime.fromtimestamp(p.time, datetime.timezone.utc).strftime("%H:%M:%S UTC"),
        })

    # Son 20 kapanan işlem (deal)
    deals = []
    now = datetime.datetime.now()
    from_date = now - datetime.timedelta(days=2)
    history = mt5.history_deals_get(from_date, now) or []
    for d in reversed(history[-20:]):
        if d.entry == mt5.DEAL_ENTRY_OUT:  # Kapanış işlemleri
            deals.append({
                "ticket": d.position_id,
                "symbol": d.symbol,
                "direction": "BUY" if d.type == mt5.DEAL_TYPE_SELL else "SELL",
                "lots": d.volume,
                "price": d.price,
                "profit": round(d.profit, 2),
                "commission": round(d.commission, 2),
                "time": datetime.datetime.fromtimestamp(d.time, datetime.timezone.utc).strftime("%H:%M:%S UTC"),
            })

    payload = {
        "account": account_data,
        "positions": positions,
        "deals": deals,
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
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("commands", [])
    except Exception as e:
        return []


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
    while True:
        try:
            commands = sync_with_server(args.api)
            sync_counter += 1

            if sync_counter % 20 == 0:
                acc = mt5.account_info()
                pos_count = len(mt5.positions_get() or [])
                if acc:
                    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Eşitlendi: Bakiye=${acc.balance:.2f} | Equity=${acc.equity:.2f} | Açık MT5 Pozisyon: {pos_count}")

            for cmd in commands:
                action = cmd.get("action")
                print(f"\n⚡ [WEB SİNYALİ ALINDI]: {action} -> {cmd}")
                if action == "OPEN_ORDER":
                    execute_market_order(cmd)
                elif action == "CLOSE_ORDER":
                    execute_close_order(cmd)

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
