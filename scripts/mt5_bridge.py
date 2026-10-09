#!/usr/bin/env python3
"""Scalper Agent Global - IC Markets MetaTrader 5 (MT5) Canlı Köprü İşçisi.

Bu script, kullanıcının Windows bilgisayarındaki IC Markets MT5 terminaline bağlanır,
canlı bakiye ve pozisyonları web paneline (https://global.erkanerdem.online) eşitler ve
otonom scalper sinyallerini gerçek MT5 Demo hesabında milisaniyeler içinde icra eder.
"""
from __future__ import annotations

import argparse
import calendar
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

# Sert Risk Sınırları (Broker tavanı)
HARD_MAX_FOREX_LOT = 50.0
HARD_MAX_GOLD_LOT = 50.0
HARD_MIN_GOLD_COOLDOWN_SEC = 60.0
LAST_GOLD_EXIT_TIME = 0.0
LAST_BTC_EXIT_TIME = 0.0
KNOWN_DEAL_TICKETS: set = set()
RECENTLY_CLOSED_TICKETS: dict = {}
INITIALIZED_DEALS = False
TZ_UTC3 = datetime.timezone(datetime.timedelta(hours=3), name="UTC+3")

# ── Broker mum push'u (2026-10-07) ───────────────────────────────────────────
# Panel grafiği Yahoo (GC=F vadeli) yerine BROKER'ın kendi mumlarını kullansın:
# köprü, backend'in `candle_watch` listesindeki (sembol, periyot) çiftleri
# MT5'ten `copy_rates_from_pos` ile çeker ve sync payload'ında `candles` olarak
# gönderir. Böylece geçmiş + canlı AYNI broker kotasyonudur (vadeli/spot baz
# farkı sıfır) ve grafik işlem gören fiyatla birebir olur.
CANDLE_WATCH: list = []                # backend'den gelen son izleme listesi
_SERVER_UTC_OFFSET: "int | None" = None  # MT5 sunucu saati ↔ UTC farkı (sn)
CANDLE_BARS = 300                      # çift başına çekilecek mum sayısı
# Mum push'unu seyrelt: her senkronda ~200 KB göndermek gereksizdi. 3 turda bir
# (≈4,5 sn) gönderilir; TTL 30 sn olduğundan backend'de bayatlama olmaz.
_CANDLE_PUSH_EVERY = 3
_CANDLE_TICK = 0

MT5_TIMEFRAMES = {
    "1m": mt5.TIMEFRAME_M1,
    "5m": mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "30m": mt5.TIMEFRAME_M30,
    "1h": mt5.TIMEFRAME_H1,
    "4h": mt5.TIMEFRAME_H4,
    "1d": mt5.TIMEFRAME_D1,
}


def _get_server_utc_offset() -> int:
    """MT5 zaman damgaları broker terminal saatiyle birebirdir. Çift kayma olmaması için ofset 0 döner."""
    return 0


def _next_watch_candles() -> dict:
    """`fetch_watch_candles`'i seyreltilmiş olarak çağır (her `_CANDLE_PUSH_EVERY` turda bir)."""
    global _CANDLE_TICK
    _CANDLE_TICK += 1
    if _CANDLE_TICK % _CANDLE_PUSH_EVERY != 0:
        return {}
    return fetch_watch_candles()


def fetch_watch_candles() -> dict:
    """`CANDLE_WATCH` listesindeki çiftler için broker mumlarını döndür.

    Dönüş: { "XAUUSD|5m": [ {time,open,high,low,close}, ... ] }  (time = UTC saniye)
    """
    out: dict = {}
    if not CANDLE_WATCH:
        return out
    offset = _get_server_utc_offset()
    for item in CANDLE_WATCH:
        try:
            sym_req = str(item.get("symbol", "")).upper()
            tf_key = str(item.get("interval", ""))
            tf = MT5_TIMEFRAMES.get(tf_key)
            if not tf or not sym_req:
                continue
            res_sym = resolve_mt5_symbol(sym_req)
            # Market Watch'a ekle: seçili değilse copy_rates boş dönebilir
            try:
                mt5.symbol_select(res_sym, True)
            except Exception:
                pass
            rates = mt5.copy_rates_from_pos(res_sym, tf, 0, CANDLE_BARS)
            if rates is None or len(rates) == 0:
                continue
            bars = []
            for r in rates:
                # r["time"] broker sunucu saatinde (epoch sanılır) → UTC'ye indir
                t_utc = int(r["time"]) - offset
                bars.append({
                    "time": t_utc,
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                })
            if bars:
                out[f"{sym_req}|{tf_key}"] = bars
        except Exception as e:
            print(f"  ⚠️ [MUM ÇEKME UYARISI] {item}: {e}")
    return out


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


# Bilinen Sembol Eşleşmeleri (Web Paneli <-> IC Markets MT5)
SYMBOL_ALIAS_MAP = {
    "NAS100": ["USTEC", "NAS100", "US100", "NDX"],
    "USTEC": ["USTEC", "NAS100"],
    "US30": ["US30", "DJ30", "WS30"],
    "ETHUSD": ["ETHUSD"],
    "ETH": ["ETHUSD"],
    "BTCUSD": ["BTCUSD"],
    "BTC": ["BTCUSD"],
    "GOLD": ["XAUUSD"],
    "XAUUSD": ["XAUUSD"],
    "SILVER": ["XAGUSD"],
    "USOIL": ["XTIUSD", "WTICRUDE", "WTI", "USOUSD", "OIL"],
    "UKOIL": ["XBRUSD", "BRENT", "UKOUSD"],
    "BRENT": ["XBRUSD", "UKOIL"],
    "WTI": ["XTIUSD", "USOIL"],
}

REVERSE_SYMBOL_ALIAS_MAP = {
    "USTEC": "NAS100",
    "US30": "US30",
    "XTIUSD": "USOIL",
    "XBRUSD": "UKOIL",
}


def resolve_mt5_symbol(symbol: str) -> str:
    """Web panelinden gelen sembolü MT5 terminalindeki gerçek sembol adı ile eşleştirir."""
    raw = str(symbol).upper().replace("/", "").strip()
    if mt5.symbol_info(raw) is not None:
        return raw

    clean = raw.split(".")[0].split("+")[0].split("-")[0].replace("#", "").strip()
    candidates = SYMBOL_ALIAS_MAP.get(raw, []) + SYMBOL_ALIAS_MAP.get(clean, [])
    for cand in candidates:
        if mt5.symbol_info(cand) is not None:
            return cand

    try:
        all_syms = mt5.symbols_get()
        if all_syms:
            names = [s.name for s in all_syms]
            if clean in ("USOIL", "OIL", "WTI"):
                for n in names:
                    if "XTIUSD" in n:
                        return n
            if clean in ("UKOIL", "BRENT"):
                for n in names:
                    if "XBRUSD" in n:
                        return n
            if clean in ("NAS100", "USTEC", "US100", "NDX"):
                for n in names:
                    if "USTEC" in n:
                        return n
            for n in names:
                if clean in n:
                    return n
    except Exception:
        pass

    if candidates:
        return candidates[0]

    return raw


def get_symbol_trading_specs(
    symbol: str,
    base_sl: float = 8.0,
    base_tp: float = 20.0,
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
      nedeniyle 3.0x taban volatilite tamponu (min 24 pip / $2.40 USD) ve dinamik ATR tamponu uygulanır.
    - Erken başabaş (breakeven) stop kilitlenmesini engellemek için altın BE eşiği en az 25 pip ($2.50) olmalıdır.
    - Standart Forex paritelerinde de erken boğulmayı önlemek için BE eşiği en az 10.0 pip olmalıdır.
    """
    s = str(symbol).upper().replace("/", "").strip()
    clean_sym = s.split(".")[0].split("+")[0].split("-")[0].replace("#", "").strip()
    base_be_floored = max(10.0, base_be)

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

    elif "USOIL" in clean_sym or "OIL" in clean_sym or "WTI" in clean_sym or "XTI" in clean_sym or "XBR" in clean_sym:
        pip_size = 0.01          # 1 pip = 0.01 USD (1 cent)
        mult = 2.0
        digits = 2
        pip_val = 1.0            # IC Markets: 1 lot (100 varil) * 0.01 USD = $1.00
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

    elif "ETH" in clean_sym:
        pip_size = 1.0           # 1 pip = $1.00
        mult = 2.0
        digits = 2
        pip_val = 1.0            # IC Markets: contract_size 1.0 -> 1 lot * $1.0 = $1.00
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(20.0, round(base_be_floored * mult, 1))
        eff_trail_pips = round(base_trail * mult, 1)

    elif "USTEC" in clean_sym or "NAS100" in clean_sym or "US100" in clean_sym or "NDX" in clean_sym:
        pip_size = 1.0           # 1 pip = 1.0 index point
        mult = 2.5
        digits = 2
        pip_val = 1.0            # IC Markets: contract_size 1.0 -> 1 lot * 1.0 point = $1.00
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(20.0, round(base_be_floored * mult, 1))
        eff_trail_pips = max(35.0, round(base_trail * mult, 1))

    elif "US30" in clean_sym or "DJ30" in clean_sym or "WS30" in clean_sym:
        pip_size = 1.0           # 1 pip = 1.0 index point
        mult = 3.0
        digits = 2
        pip_val = 1.0            # IC Markets: contract_size 1.0 -> 1 lot * 1.0 point = $1.00
        eff_sl_pips = round(base_sl * mult, 1)
        eff_tp_pips = round(base_tp * mult, 1)
        eff_be_pips = max(25.0, round(base_be_floored * mult, 1))
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
    raw_symbol = cmd.get("symbol", "EURUSD").upper()
    direction = cmd.get("direction", "BUY").upper()
    raw_lots = float(cmd.get("lots", 0.01))
    sl_pips = float(cmd.get("sl_pips", 12.0))
    tp_pips = float(cmd.get("tp_pips", 22.0))
    comment = str(cmd.get("comment", "Scalper Global"))[:31]

    # Sembolü MT5 broker formatına çözümle (Örn: USOIL -> XTIUSD)
    symbol = resolve_mt5_symbol(raw_symbol)
    if symbol != raw_symbol:
        print(f"  🔄 [SEMBOL EŞLEŞTİRME]: {raw_symbol} -> MT5 Sembolü: {symbol}")

    is_gold = ("XAU" in symbol or "GOLD" in symbol)
    is_crypto = ("BTC" in symbol or "ETH" in symbol)
    # "SPX" dalı emekliye ayrılan SPX500 için KALIR (bkz. forex.py _RETIRED_FOREX_SYMBOLS):
    # köprüde arşiv/manuel kayıt gelebilir; sınıflama doğru kalsın.
    is_index = ("USTEC" in symbol or "NAS100" in symbol or "US30" in symbol or "US100" in symbol or "DJ30" in symbol or "SPX" in symbol)
    is_oil = ("XTI" in symbol or "XBR" in symbol or "OIL" in symbol or "USOIL" in raw_symbol)

    # Ons Altın (XAUUSD) Soğuma Koruması (İlk startta dikkate alınmaz; yalnızca canlı kapanıştan sonra çalışır)
    global LAST_GOLD_EXIT_TIME, LAST_BTC_EXIT_TIME
    if is_gold and LAST_GOLD_EXIT_TIME > 0:
        cd_sec = float(CURRENT_SETTINGS.get("gold_cooldown_sec", HARD_MIN_GOLD_COOLDOWN_SEC))
        now_t = time.time()
        elapsed = now_t - LAST_GOLD_EXIT_TIME
        if 0 <= elapsed < cd_sec:
            rem = min(cd_sec, max(0.0, cd_sec - elapsed))
            err = f"Ons Altın soğuma kalkanı aktif: {int(rem)} sn kaldı (min {cd_sec:.0f}s)"
            print(f"  🛑 {err}")
            return {"success": False, "error": err}
        elif elapsed < 0:
            # Zaman kayması koruması (broker timezone uyumsuzluğu)
            LAST_GOLD_EXIT_TIME = 0.0

    # Bitcoin (BTCUSD) Soğuma Koruması (İlk startta dikkate alınmaz; canlı kapanış sonrası 60s)
    if is_crypto and LAST_BTC_EXIT_TIME > 0:
        cd_sec = 60.0
        now_t = time.time()
        elapsed = now_t - LAST_BTC_EXIT_TIME
        if 0 <= elapsed < cd_sec:
            rem = min(cd_sec, max(0.0, cd_sec - elapsed))
            err = f"Bitcoin soğuma kalkanı aktif: {int(rem)} sn kaldı (min 60s)"
            print(f"  🛑 {err}")
            return {"success": False, "error": err}
        elif elapsed < 0:
            LAST_BTC_EXIT_TIME = 0.0

    # Sembolü aktif et ve bilgileri çek
    if not mt5.symbol_select(symbol, True):
        err = f"Sembol seçilemedi: {symbol} (Orijinal: {raw_symbol}, Hata: {mt5.last_error()})"
        print(f"  ❌ [İŞLEM BAŞARISIZ]: {err}")
        return {"success": False, "error": err}

    s_info = mt5.symbol_info(symbol)
    if not s_info:
        err = f"Sembol bilgisi alınamadı: {symbol} (Orijinal: {raw_symbol})"
        print(f"  ❌ [İŞLEM BAŞARISIZ]: {err}")
        return {"success": False, "error": err}

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        err = f"Canlı fiyat alınamadı: {symbol}"
        print(f"  ❌ [İŞLEM BAŞARISIZ]: {err}")
        return {"success": False, "error": err}

    # Minimum, Maksimum ve Adım (Step) Lot Kısıtları
    min_vol = float(s_info.volume_min) if s_info.volume_min > 0 else 0.01
    step_vol = float(s_info.volume_step) if s_info.volume_step > 0 else 0.01
    max_vol = float(s_info.volume_max) if s_info.volume_max > 0 else 50.0

    # Broker ve Yapılandırma Lot Kısıtları (Sunucu dinamik bakiye risk lotunu hesaplar)
    configured_cap = float(CURRENT_SETTINGS.get("max_gold_lot", HARD_MAX_GOLD_LOT)) if is_gold else float(CURRENT_SETTINGS.get("max_forex_lot", HARD_MAX_FOREX_LOT))
    lot_ceiling = min(max_vol, max(min_vol, configured_cap))

    lots = min(raw_lots, lot_ceiling)
    if lots < min_vol:
        print(f"  ℹ️ [LOT DÜZENLENDİ]: Talep edilen {raw_lots} lot sembol minimumu {min_vol} lotun altında! {min_vol} lot olarak ayarlandı ({symbol})")
        lots = min_vol

    # Step yuvarlama
    if step_vol > 0:
        steps = round((lots - min_vol) / step_vol)
        lots = round(min_vol + (steps * step_vol), 2)
    lots = round(max(min_vol, min(lots, max_vol)), 2)

    # Reversal Flip Kontrolü: Aynı sembolde ters yönde pozisyon varsa önce kapat
    open_positions = (mt5.positions_get(symbol=symbol) or []) + (mt5.positions_get(symbol=raw_symbol) or [])
    checked_tickets = set()
    for pos in open_positions:
        if pos.ticket in checked_tickets:
            continue
        checked_tickets.add(pos.ticket)
        pos_dir = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
        if pos_dir != direction:
            print(f"  🔄 [TREND DÖNÜŞÜ (FLIP)]: Bilet #{pos.ticket} {pos_dir} pozisyonu kapatılıyor -> Yeni {direction} açılacak...")
            execute_close_order({"ticket": pos.ticket})
            time.sleep(0.3)

    # Aynı sembolde aynı yönde maksimum 3 pozisyon ve Kârdaki Pozisyona Ekleme denetimi
    _raw_active = (mt5.positions_get(symbol=symbol) or []) + (mt5.positions_get(symbol=raw_symbol) or [])
    # Ticket bazlı tekrar eleme (symbol == raw_symbol olduğunda çift sayımı engeller)
    _seen = set()
    active_now = []
    for _p in _raw_active:
        if _p.ticket not in _seen:
            _seen.add(_p.ticket)
            active_now.append(_p)
    # Aynı sembolde aynı yönde maksimum açık pozisyon kontrolü (Varsayılan: 1)
    max_pos = int(cmd.get("max_positions_per_symbol") or CURRENT_SETTINGS.get("max_positions_per_symbol", 1))
    same_dir_positions = [p for p in active_now
                          if ("BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL") == direction]
    same_dir_count = len(same_dir_positions)
    if same_dir_count >= max_pos:
        err = f"{symbol} için {direction} yönünde zaten {same_dir_count} açık pozisyon var (Maksimum {max_pos} kuralı)."
        print(f"  🛑 {err}")
        return {"success": False, "error": err}

    if same_dir_positions:
        total_dir_profit = sum(getattr(pos, "profit", 0.0) for pos in same_dir_positions)
        if total_dir_profit < 0.20:
            err = f"{symbol} {direction} yönünde açık {same_dir_count} pozisyon henüz kârda değil (${total_dir_profit:+.2f}). Zarara ekleme engellendi!"
            print(f"  🛑 [PİRAMİTLEME ENGELİ]: {err}")
            return {"success": False, "error": err}

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
        # Kısmi Kâr Al hedefini açılan pozisyona bağla (server: partial_pips)
        partial_pips = float(cmd.get("partial_pips", 0.0) or 0.0)
        if partial_pips > 0 and bool(CURRENT_SETTINGS.get("partial_tp_enabled", True)):
            time.sleep(0.2)
            for p in (mt5.positions_get(symbol=symbol) or []):
                p_dir = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
                if p_dir == direction and abs(float(p.volume) - lots) < 1e-6 and p.ticket not in PARTIAL_TP_MAP:
                    PARTIAL_TP_MAP[p.ticket] = {"target_pips": partial_pips, "done": False}
                    print(f"  💰 [KISMİ TP PLANI]: Bilet #{p.ticket} ilk kâr hedefi +{partial_pips:.1f}p")
                    break
        # Pozisyon bazlı BE/Trail çıkış planı (server: be_pips/trail_pips/be_lock_ratio — ATR'li).
        # Yoksa dynamic exits mevcut ATR'siz spec fallback'ine düşer (eski davranış korunur).
        cmd_be = float(cmd.get("be_pips", 0.0) or 0.0)
        cmd_trail = float(cmd.get("trail_pips", 0.0) or 0.0)
        if cmd_be > 0 or cmd_trail > 0:
            time.sleep(0.1)
            for p in (mt5.positions_get(symbol=symbol) or []):
                p_dir = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
                if p_dir == direction and abs(float(p.volume) - lots) < 1e-6 and p.ticket not in POSITION_EXITS:
                    POSITION_EXITS[p.ticket] = {
                        "be_pips": cmd_be,
                        "trail_pips": cmd_trail,
                        "be_lock_ratio": float(cmd.get("be_lock_ratio", 0.0) or 0.0),
                        "sl_pips": float(cmd.get("sl_pips", 0.0) or 0.0),
                    }
                    print(f"  🎯 [ÇIKIŞ PLANI]: Bilet #{p.ticket} BE {cmd_be:.1f}p / Trail {cmd_trail:.1f}p (motor cmd)")
                    break
        return {"success": True, "ticket": res.order, "price": price}
    else:
        comment_err = res.comment if res else str(mt5.last_error())
        print(f"  ❌ [İŞLEM BAŞARISIZ]: {comment_err} (Kod: {res.retcode if res else 'None'})")
        return {"success": False, "error": comment_err}


def execute_close_order(cmd: dict) -> dict:
    """Belirli bir MT5 açık pozisyonunu kapatır."""
    ticket = int(cmd.get("ticket", 0))
    now_t = time.time()
    if ticket in RECENTLY_CLOSED_TICKETS or ticket in KNOWN_DEAL_TICKETS:
        print(f"  ℹ️ [MÜKERRER EMİR ATLANDI]: Bilet #{ticket} zaten az önce kapatılmış.")
        return {"success": True, "ticket": ticket, "already_closed": True}

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
        RECENTLY_CLOSED_TICKETS[ticket] = time.time()
        if "XAU" in symbol or "GOLD" in symbol:
            global LAST_GOLD_EXIT_TIME
            LAST_GOLD_EXIT_TIME = time.time()
        if "BTC" in symbol:
            global LAST_BTC_EXIT_TIME
            LAST_BTC_EXIT_TIME = time.time()
        return {"success": True, "ticket": ticket}
    else:
        comment_err = res.comment if res else str(mt5.last_error())
        print(f"  ❌ [KAPATMA HATASI]: {comment_err}")
        return {"success": False, "error": comment_err}


def execute_close_partial(cmd: dict) -> dict:
    """Açık MT5 pozisyonunun belirtilen hacmini kısmen kapatır (Kısmi Kâr Al)."""
    ticket = int(cmd.get("ticket", 0))
    volume = float(cmd.get("volume", 0.0))
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return {"success": False, "error": f"Pozisyon #{ticket} bulunamadı veya kapalı"}

    pos = positions[0]
    symbol = pos.symbol
    s_info = mt5.symbol_info(symbol)
    min_vol = float(s_info.volume_min) if s_info and s_info.volume_min > 0 else 0.01
    step_vol = float(s_info.volume_step) if s_info and s_info.volume_step > 0 else 0.01

    if volume < min_vol or volume >= float(pos.volume):
        return {"success": False, "error": f"Kısmi hacim geçersiz: {volume} (min {min_vol}, pozisyon {pos.volume})"}
    if step_vol > 0:
        steps = round((volume - min_vol) / step_vol)
        volume = round(min_vol + (steps * step_vol), 2)
        if volume < min_vol or volume >= float(pos.volume):
            return {"success": False, "error": f"Kısmi hacim lot adımına uymuyor: {volume} (step {step_vol})"}

    order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    filling = mt5.ORDER_FILLING_IOC
    if s_info and (s_info.filling_mode & 2):
        filling = mt5.ORDER_FILLING_IOC
    elif s_info and (s_info.filling_mode & 1):
        filling = mt5.ORDER_FILLING_FOK
    else:
        filling = mt5.ORDER_FILLING_RETURN

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return {"success": False, "error": f"Canlı fiyat alınamadı: {symbol}"}
    price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "position": ticket,
        "price": price,
        "deviation": 25,
        "magic": 825482,
        "comment": "Scalper Partial",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"  💰 [KISMİ KAPATMA]: Bilet #{ticket} | {symbol} {volume} lot kapatıldı @ {price}")
        return {"success": True, "ticket": ticket, "volume": volume}
    comment_err = res.comment if res else str(mt5.last_error())
    print(f"  ❌ [KISMİ KAPATMA HATASI]: {comment_err}")
    return {"success": False, "error": comment_err}


def execute_modify_sltp(cmd: dict) -> dict:
    """Açık pozisyonun SL veya TP seviyesini günceller (Breakeven & Trailing).

    `tp` semantiği:
      - `tp > 0`        → TP bu seviyeye ayarlanır,
      - `tp == 0`       → MEVCUT TP KORUNUR (`pos.tp`) — eski davranış, aynen korunur,
      - `tp_action == "cancel"` → TP EMRİ SİLİNİR (mt5'te TP=0.0 gönderilir). Motor
        `tp_cancel_on_trail` ayarı açıkken trailing devreye girince bu sinyali yollar;
        `tp=0` bunu ifade EDEMEZDİ (0 zaten "koru" demek).
    """
    ticket = int(cmd.get("ticket", 0))
    sl = float(cmd.get("sl", 0.0))
    tp = float(cmd.get("tp", 0.0))
    cancel_tp = str(cmd.get("tp_action", "") or "").strip().lower() == "cancel"
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return {"success": False, "error": f"Pozisyon #{ticket} bulunamadı"}

    pos = positions[0]
    symbol = pos.symbol
    s_info = mt5.symbol_info(symbol)
    digits = s_info.digits if s_info else 5
    sl = round(sl, digits)
    tp = 0.0 if cancel_tp else (round(tp, digits) if tp > 0 else pos.tp)

    spec = get_symbol_trading_specs(symbol)
    pip_size = spec["pip_size"]
    # "Değişiklik yok" kısayolu: iptal isteğinde TP'nin ZATEN olmaması değişiklik yokluğudur;
    # aksi hâlde `tp == 0.0` burada yanlışlıkla "dokunma" sayılır ve iptal hiç uygulanmazdı.
    tp_unchanged = (pos.tp == 0.0) if cancel_tp else (tp == 0.0 or abs(tp - pos.tp) < (0.3 * pip_size))
    if abs(sl - pos.sl) < (0.3 * pip_size) and tp_unchanged:
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
        if cancel_tp:
            print(f"  🎯 [TP İPTAL EDİLDİ]: Bilet #{ticket} ({symbol}) -> Sabit TP kaldırıldı, "
                  f"kazanç trailing/BE kilidiyle taşınacak (Yeni SL: {sl})")
        else:
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
PARTIAL_TP_MAP: Dict[int, Dict[str, Any]] = {}  # ticket -> {"target_pips": float, "done": bool}
# ticket -> pozisyon bazlı çıkış parametreleri (server cmd'den; ATR'li motor değerleri).
# Köprü artık BE/Trail'i kendi ATR'siz spec'inden DEĞİL, işlemi açan motorun değerlerinden yönetir —
# spec çift kopyası (backend köprü ayrışması) kaynaklı erken-kar kesme/trailing sıkı-kilit düzeltmesi.
POSITION_EXITS: Dict[int, Dict[str, float]] = {}
CURRENT_SETTINGS: Dict[str, float] = {
    "breakeven_pips": 14.0,
    "trailing_stop_pips": 20.0,
    "sl_pips": 8.0,
    "tp_pips": 20.0,
    "max_forex_lot": 10.0,
    "max_gold_lot": 10.0,
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
    for old_t in list(PARTIAL_TP_MAP.keys()):
        if old_t not in active_tickets:
            PARTIAL_TP_MAP.pop(old_t, None)
    for old_t in list(POSITION_EXITS.keys()):
        if old_t not in active_tickets:
            POSITION_EXITS.pop(old_t, None)

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

        # Pozisyon bazlı çıkış planı (motor cmd'siyle açılan işlem) — spec fallback'i ezer
        pos_exits = POSITION_EXITS.get(ticket)
        if pos_exits:
            if float(pos_exits.get("be_pips", 0.0)) > 0:
                eff_be_pips = float(pos_exits["be_pips"])
            if float(pos_exits.get("trail_pips", 0.0)) > 0:
                eff_trail_pips = float(pos_exits["trail_pips"])

        direction = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
        entry_p = p.price_open
        cur_p = p.price_current
        cur_sl = p.sl
        cur_tp = p.tp

        if direction == "BUY":
            pnl_pips = (cur_p - entry_p) / pip_size
        else:
            pnl_pips = (entry_p - cur_p) / pip_size

        # 0. KISMİ KÂR ALMA (Partial TP): İlk kâr hedefinde pozisyonun yarısı
        # kapatılır; kalan pozisyon için SL başabaş üstü net kâra çekilir.
        partial_cfg = PARTIAL_TP_MAP.get(ticket)
        if partial_cfg and not partial_cfg.get("done") and bool(CURRENT_SETTINGS.get("partial_tp_enabled", True)):
            target_pips = float(partial_cfg.get("target_pips", 0.0) or 0.0)
            if target_pips > 0 and pnl_pips >= target_pips:
                partial_cfg["done"] = True
                half = round(float(p.volume) / 2.0, 2)
                vol_min = float(s_info.volume_min) if s_info.volume_min > 0 else 0.01
                closed_half = False
                if vol_min <= half < float(p.volume):
                    cres = execute_close_partial({"ticket": ticket, "volume": half})
                    closed_half = bool(cres.get("success"))
                remaining_vol = max(vol_min, round(float(p.volume) - half, 2)) if closed_half else float(p.volume)
                lock_dpp = max(0.0001, remaining_vol * spec["pip_val"])
                lock_pips = max(0.5, round(1.0 / lock_dpp, 1))
                if direction == "BUY":
                    lock_sl = round(entry_p + (lock_pips * pip_size), digits)
                    if lock_sl > cur_sl and lock_sl < cur_p:
                        mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "symbol": sym, "sl": lock_sl, "tp": cur_tp})
                        print(f"  🛡️ [KISMİ TP KİLİDİ]: Bilet #{ticket} ({sym}) SL {lock_sl} (başabaş üstü net kâr)")
                else:
                    lock_sl = round(entry_p - (lock_pips * pip_size), digits)
                    if (cur_sl == 0.0 or lock_sl < cur_sl) and lock_sl > cur_p:
                        mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "symbol": sym, "sl": lock_sl, "tp": cur_tp})
                        print(f"  🛡️ [KISMİ TP KİLİDİ]: Bilet #{ticket} ({sym}) SL {lock_sl} (başabaş üstü net kâr)")

        target_sl = None
        cur_profit = getattr(p, "profit", 0.0)
        vol = p.volume
        pip_val = spec["pip_val"]
        dollar_per_pip = max(0.0001, vol * pip_val)
        pips_for_1usd = max(0.5, round(1.0 / dollar_per_pip, 1))

        # Piyasa gürültüsü ve broker toleransı için dinamik nefes payı (headroom)
        # Erken boğulmayı engeller, fiyatın kâra doğru rahatça koşmasını sağlar
        min_headroom_pips = 4.0 if ("XAU" in sym or "GOLD" in sym) else (25.0 if "BTC" in sym else 3.5)

        # 1. BREAKEVEN (Başabaş / Volatilite ve R Tabanlı Net Kâr Kilidi)
        # Erken boğulmayı engeller: En az min_trigger_pips (0.4*SL veya 0.5*ATR veya eff_be_pips veya $1 güvencesi)
        is_gold_sym = ("XAU" in sym or "GOLD" in sym)
        is_crypto_sym = ("BTC" in sym)
        # Gerçek işlem SL'i (cmd'den) — ATR'siz spec SL'i değil; BE tetik R-hesabı bunu kullanmalı
        sl_nominal_pips = float(pos_exits["sl_pips"]) if (pos_exits and float(pos_exits.get("sl_pips", 0.0)) > 0) else spec.get("sl_pips", 15.0)
        atr_nominal_pips = (eff_trail_pips / 1.2) if eff_trail_pips > 0 else 15.0

        r_trigger = sl_nominal_pips * 0.40
        atr_trigger = atr_nominal_pips * 0.50
        min_trigger_pips = max(pips_for_1usd + min_headroom_pips, r_trigger, atr_trigger, eff_be_pips if eff_be_pips > 0 else 0.0)

        if pnl_pips >= min_trigger_pips:
            # Kilitlenecek kâr mesafesi: Asla 1$ (pips_for_1usd) altına inmez!
            be_lock_ratio = float(CURRENT_SETTINGS.get("gold_be_lock_ratio", 0.6)) if is_gold_sym else 0.40
            # Pozisyonun motor cmd'siyle gelen kilit oranı (varsa) ayarı ezer — backend/köprü tutarlılığı
            if pos_exits and 0 < float(pos_exits.get("be_lock_ratio", 0.0)) < 1:
                be_lock_ratio = float(pos_exits["be_lock_ratio"])
            locked_pips = max(pips_for_1usd, round(pnl_pips * be_lock_ratio, 1))
            if direction == "BUY":
                be_sl = round(entry_p + (locked_pips * pip_size), digits)
                if cur_sl < be_sl and be_sl < cur_p:
                    target_sl = be_sl
                    if POSITION_PROTECTION_MAP.get(ticket) != "TRAILING":
                        POSITION_PROTECTION_MAP[ticket] = "BREAKEVEN"
            else:
                be_sl = round(entry_p - (locked_pips * pip_size), digits)
                if (cur_sl == 0.0 or cur_sl > be_sl) and be_sl > cur_p:
                    target_sl = be_sl
                    if POSITION_PROTECTION_MAP.get(ticket) != "TRAILING":
                        POSITION_PROTECTION_MAP[ticket] = "BREAKEVEN"

        # 2. TRAILING STOP (İz Süren Stop)
        # Sembole ve volatiliteye göre belirlenen mesafeden fiyatı takip et
        # BE kilitlendikten sonra VEYA pnl_pips >= eff_trail_pips olduğunda
        if eff_trail_pips > 0 and (POSITION_PROTECTION_MAP.get(ticket) == "BREAKEVEN" or pnl_pips >= eff_trail_pips):
            trail_dist = eff_trail_pips * pip_size
            if direction == "BUY":
                cand_sl = round(cur_p - trail_dist, digits)
                # Trailing SL asla 1$ Breakeven seviyesinin altına düşmez!
                min_safe_sl = round(entry_p + (pips_for_1usd * pip_size), digits)
                cand_sl = max(cand_sl, min_safe_sl)
                if cand_sl > entry_p:
                    if target_sl is None and cand_sl > cur_sl:
                        target_sl = cand_sl
                        POSITION_PROTECTION_MAP[ticket] = "TRAILING"
                    elif target_sl is not None and cand_sl > target_sl:
                        target_sl = cand_sl
                        POSITION_PROTECTION_MAP[ticket] = "TRAILING"
            else:
                cand_sl = round(cur_p + trail_dist, digits)
                # Trailing SL asla 1$ Breakeven seviyesinin üstüne çıkmaz!
                min_safe_sl = round(entry_p - (pips_for_1usd * pip_size), digits)
                cand_sl = min(cand_sl, min_safe_sl)
                if cand_sl < entry_p:
                    if target_sl is None and (cur_sl == 0.0 or cand_sl < cur_sl):
                        target_sl = cand_sl
                        POSITION_PROTECTION_MAP[ticket] = "TRAILING"
                    elif target_sl is not None and cand_sl < target_sl:
                        target_sl = cand_sl
                        POSITION_PROTECTION_MAP[ticket] = "TRAILING"

        # TP İPTALİ (opt-in `tp_cancel_on_trail`): trailing bu pozisyonda devreye girdiyse
        # ve pozisyonun hâlâ sabit TP emri varsa, TP çekilir — kazanan trend TP'ye
        # takılmadan trailing/BE kilidiyle koşar. Motor (`forex.py`) ile aynı mekanizma:
        # orada paper tarafı tp_price=0 yapar, burada gerçek MT5 emri kaldırılır.
        cancel_tp = (
            POSITION_PROTECTION_MAP.get(ticket) == "TRAILING"
            and bool(CURRENT_SETTINGS.get("tp_cancel_on_trail", False))
            and cur_tp > 0
        )

        # Eğer yeni bir SL seviyesi belirlendiyse ve mevcut SL'den farklıysa emri MT5'e gönder
        if (target_sl is not None and abs(target_sl - cur_sl) >= (0.3 * pip_size)) or cancel_tp:
            req = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": sym,
                "sl": target_sl if target_sl is not None else cur_sl,
                "tp": 0.0 if cancel_tp else cur_tp,
            }
            res = mt5.order_send(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                if cancel_tp:
                    print(f"  🎯 [TP İPTAL EDİLDİ]: Bilet #{ticket} ({sym} {direction}) — trailing aktif "
                          f"(+{pnl_pips:.1f}p), sabit TP kaldırıldı, kazanç trailing kilidiyle taşınacak")
                else:
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
    server_offset = _get_server_utc_offset()

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

        mapped_sym = REVERSE_SYMBOL_ALIAS_MAP.get(sym, sym)
        pos_open_ts = int(p.time)
        positions.append({
            "ticket": ticket,
            "symbol": mapped_sym,
            "mt5_symbol": sym,
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
            "open_time": datetime.datetime.fromtimestamp(pos_open_ts, datetime.timezone.utc).strftime("%H:%M:%S"),
            # Açık pozisyonun strateji etiketi (emir açılışındaki yorum; panel rozet için)
            "strategy_tag": str(getattr(p, "comment", "") or "").strip(),
        })

    # Kapanan işlem geçmişi (Broker zaman dilimi farkını tolere etmek için +2 gün buffer)
    deals = []
    now = datetime.datetime.now()
    from_date = now - datetime.timedelta(days=30)
    to_date = now + datetime.timedelta(days=2)
    history = mt5.history_deals_get(from_date, to_date) or []

    # Sadece kapanış (OUT) işlemlerini filtrele
    out_deals = [d for d in history if d.entry == mt5.DEAL_ENTRY_OUT]
    # Açılış (IN) işlemlerini pozisyon bazında hızlı erişim için indexle
    in_deals_by_pos = {cand.position_id: cand for cand in history if cand.entry == mt5.DEAL_ENTRY_IN}
    # En son 300 kapanmış işlemi dahil et
    for d in reversed(out_deals[-300:]):
        pos_id = d.position_id
        # Pozisyonun açılış biletini bul (in_deal)
        in_deal = in_deals_by_pos.get(pos_id)

        entry_p = in_deal.price if in_deal else d.price
        in_deal_ts = int(in_deal.time) if in_deal else None
        close_ts = int(d.time)
        open_time_str = datetime.datetime.fromtimestamp(in_deal_ts, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if in_deal_ts else "-"
        close_time_str = datetime.datetime.fromtimestamp(close_ts, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        direction = "BUY" if in_deal and in_deal.type == mt5.DEAL_TYPE_BUY else ("SELL" if d.type == mt5.DEAL_TYPE_BUY else "BUY")

        # Strateji etiketi: emir AÇILIRKEN yazılan `comment` giriş (IN) deal'inde durur
        # (kapanış deal'inde MT5 onu "[tp ...]/[sl ...]" ile ezer). Panelde/reportta
        # işlemin hangi algoritmayla açıldığı bu alandan okunur (2026-10-08).
        strategy_tag = str(in_deal.comment or "").strip() if in_deal else ""

        comment = str(d.comment or "")
        comment_l = comment.lower()
        d_reason_code = getattr(d, "reason", -1)
        reason = "IC Markets MT5"
        if "[tp" in comment_l or "tp " in comment_l or d_reason_code == getattr(mt5, "DEAL_REASON_TP", 5):
            reason = "🎯 Kâr Al (TP)"
        elif "[sl" in comment_l or "sl " in comment_l or d_reason_code == getattr(mt5, "DEAL_REASON_SL", 4):
            reason = "🛑 Zarar Durdur (SL)"
        elif "[be" in comment_l or "be " in comment_l:
            reason = "🛡️ Başabaş (BE)"
        elif d_reason_code == getattr(mt5, "DEAL_REASON_SO", 6):
            reason = "🛑 Stop Out (SO)"
        elif d.profit < -0.01 and "scalper close" not in comment_l:
            reason = f"🛑 Zarar ({comment if comment else 'SL/Piyasa'})"
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

        mapped_deal_sym = REVERSE_SYMBOL_ALIAS_MAP.get(d.symbol, d.symbol)
        deals.append({
            "id": f"MT5-{pos_id}",
            "ticket": pos_id,
            "symbol": mapped_deal_sym,
            "mt5_symbol": d.symbol,
            "display": mapped_deal_sym,
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
            "time": close_ts,
            "closed_at_ts": close_ts,
            "duration_sec": dur_sec,
            "duration_human": dur_human,
            "exit_reason": reason,
            "exit_reason_title": reason,
            "outcome": "WIN" if d.profit >= 0 else "LOSS",
            # Emir açılışında yazılan strateji etiketi ("EAP-M5", "DONCH", "RADAR"...)
            # Broker yorumu 31 kr; backend bunu tam strateji adına çevirir.
            "strategy_tag": strategy_tag,
        })

    # Altın ve BTC kapanışlarını takip et (İlk startta geçmiş deals kalkanı tetiklemez!)
    global LAST_GOLD_EXIT_TIME, LAST_BTC_EXIT_TIME, INITIALIZED_DEALS, KNOWN_DEAL_TICKETS
    if not INITIALIZED_DEALS:
        for d in out_deals:
            KNOWN_DEAL_TICKETS.add(d.ticket)
        INITIALIZED_DEALS = True
        LAST_GOLD_EXIT_TIME = 0.0  # İlk start verildiğinde kalkan dikkate alınmaz
        LAST_BTC_EXIT_TIME = 0.0
    else:
        for d in out_deals:
            if d.ticket not in KNOWN_DEAL_TICKETS:
                KNOWN_DEAL_TICKETS.add(d.ticket)
                d_sym = str(d.symbol).upper()
                if "XAU" in d_sym or "GOLD" in d_sym:
                    # Canlı çalışma sırasında yeni bir altın pozisyonu kapandı: yerel zaman damgası
                    LAST_GOLD_EXIT_TIME = time.time()
                if "BTC" in d_sym:
                    # Canlı çalışma sırasında yeni bir BTC pozisyonu kapandı: yerel zaman damgası (60s kuralı)
                    LAST_BTC_EXIT_TIME = time.time()

    # MT5 Terminalinden anlık canlı fiyatları topla
    ticks_data = {}
    # ETHUSD 2026-10-07'de forex evreninden çıkarıldı — burada da kotasyon istenmez.
    check_syms = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "BTCUSD", "NAS100", "US30", "XAUUSD"]
    for s_check in check_syms:
        res_sym = resolve_mt5_symbol(s_check)
        t = mt5.symbol_info_tick(res_sym)
        if t and t.bid > 0:
            t_obj = {"bid": float(t.bid), "ask": float(t.ask), "last": float(t.last if t.last > 0 else t.ask)}
            ticks_data[s_check] = t_obj
            if res_sym != s_check:
                ticks_data[res_sym] = t_obj

    payload = {
        "account": account_data,
        "positions": positions,
        "deals": deals,
        "ticks": ticks_data,
        "candles": _next_watch_candles(),
        "version": "1.0.1",
    }

    req_url = f"{api_base.rstrip('/')}/api/forex/mt5/sync"
    req = urllib.request.Request(
        req_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "ScalperMT5Bridge/1.0"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # Backend "panelde şu mumlar bakılıyor" der → sonraki senkronda broker'dan çekilir
            watch = data.get("candle_watch")
            if isinstance(watch, list):
                CANDLE_WATCH.clear()
                CANDLE_WATCH.extend(watch)
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
                res = None
                if action == "OPEN_ORDER":
                    res = execute_market_order(cmd)
                elif action == "CLOSE_ORDER":
                    res = execute_close_order(cmd)
                elif action == "CLOSE_PARTIAL":
                    res = execute_close_partial(cmd)
                elif action == "CLOSE_ALL":
                    res = execute_close_all(cmd)
                elif action == "MODIFY_SLTP":
                    res = execute_modify_sltp(cmd)

                if res and not res.get("success"):
                    print(f"  ❌ [İŞLEM İPTAL/HATA]: {res.get('error')}")

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
