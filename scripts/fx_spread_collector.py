#!/usr/bin/env python3
"""Scalper Agent Global - Gercek Broker Spread Toplayici (MT5 IC Markets).

MT5 terminalinden belirtilen semboller icin canli spread ornekleri toplar
(symbol_info().spread, POINT cinsinden) ve pip cinsinden istatistik uretip
JSON profil dosyasi yazar.

Kullanim:
  "C:\\...\\python.exe" fx_spread_collector.py --minutes 12 --out D:\\scalperagent_global\\outputs\\fx_spread_reality.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import sys
import time

# Windows konsolunda Turkce cp1254 karakter kodlamasi hatasini onle (mt5_bridge ile ayni)
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 kutuphanesi bulunamadi! 'pip install MetaTrader5' ile kurun.")
    sys.exit(1)

# ---- Baglanti parametreleri (mt5_bridge.py ile birebir ayni) ----
DEFAULT_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5 IC Markets Global\terminal64.exe"
DEFAULT_LOGIN = int(os.environ.get("MT5_LOGIN", 53077151))
DEFAULT_PASSWORD = os.environ.get("MT5_PASSWORD", "gE&w5OzpUyQmWx")
DEFAULT_SERVER = os.environ.get("MT5_SERVER", "ICMarketsSC-Demo")

DEFAULT_OUT = r"D:\scalperagent_global\outputs\fx_spread_reality.json"
SAMPLE_INTERVAL_SEC = 2.0

# ---- Sabit sembol ve pip_size tanimlari (1 pip'in fiyat birimi) ----
SYMBOLS: dict[str, float] = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDJPY": 0.01,
    "USDCHF": 0.0001,
    "USDCAD": 0.0001,
    "NZDUSD": 0.0001,
    "EURJPY": 0.01,
    "GBPJPY": 0.01,
    "EURNZD": 0.0001,
    "GBPNZD": 0.0001,
    "EURCHF": 0.0001,
    "GBPCHF": 0.0001,
    "XAUUSD": 0.1,
    "BTCUSD": 1.0,
}

# ---- FALLBACK: baglanti kurulamazsa literatur spread degerleri (pip) ----
FALLBACK_SPREADS: dict[str, float] = {
    "EURUSD": 1.2,
    "GBPUSD": 1.5,
    "USDJPY": 1.4,
    "USDCHF": 1.6,
    "USDCAD": 1.8,
    "NZDUSD": 1.8,
    "EURJPY": 1.8,
    "GBPJPY": 2.8,
    "EURNZD": 2.5,
    "GBPNZD": 4.0,
    "EURCHF": 1.8,
    "GBPCHF": 2.2,
    "XAUUSD": 2.5,
    "BTCUSD": 12.0,
}


def connect_mt5_retriable(path: str, login: int, password: str, server: str, attempts: int = 3, wait: float = 5.0) -> bool:
    """MT5'e baglanir; basarisizsa 3 deneme yapar (5 sn arayla)."""
    for i in range(1, attempts + 1):
        print(f"[{i}/{attempts}] MT5 initialize deneniyor (login={login}, server={server})...")
        if os.path.exists(path):
            init_res = mt5.initialize(path=path, login=login, password=password, server=server, timeout=30000)
        else:
            print(f"[UYARI] Terminal yolu bulunamadi: {path} -> varsayilan attach deneniyor.")
            init_res = mt5.initialize(login=login, password=password, server=server, timeout=30000)

        if init_res:
            acc = mt5.account_info()
            if not acc:
                print(f"[HATA] Initialize OK ama hesap bilgisi alinamadi: {mt5.last_error()}")
                mt5.shutdown()
            else:
                print("MT5 BAGLANDI (gercek MT5 veri yolu).")
                print(f"  - Hesap : {acc.login} ({acc.name})")
                print(f"  - Sunucu: {acc.server}")
                print(f"  - Bakiye: {acc.balance:,.2f} {acc.currency}")
                return True
        else:
            print(f"[HATA] MT5 initialize basarisiz: {mt5.last_error()}")

        if i < attempts:
            print(f"  5 sn bekleyip tekrar denenecek...")
            time.sleep(wait)

    return False


def percentile_95(sorted_vals: list[float]) -> float:
    """Basit index (nearest-rank) yontemiyle p95."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    idx = max(0, min(n - 1, int(math.ceil(0.95 * n)) - 1))
    return sorted_vals[idx]


def build_fallback_result(reason: str, out_path: str, minutes: int) -> None:
    """Baglanti kurulamazsa literatur degerlerle fallback JSON yazar (sessiz gecilmez)."""
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {
        "meta": {
            "collected_at_utc": now_utc,
            "minutes": minutes,
            "samples_per_symbol": 0,
            "source": "fallback-literature",
            "fallback_reason": reason,
        },
        "symbols": {},
    }
    for sym, fb in FALLBACK_SPREADS.items():
        result["symbols"][sym] = {
            "avg_pips": fb,
            "min_pips": fb,
            "p95_pips": fb,
            "max_pips": fb,
            "samples": 0,
            "source": "fallback-literature",
        }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"[FALLBACK YAZILDI] {out_path}")
    print(f"[ACIKLAMA] MT5 baglantisi kurulamadigi icin GERCEK broker verisi TOPLANAMADI.")
    print(f"[ACIKLAMA] Sebep: {reason}")
    print(f"[ACIKLAMA] Tum 14 sembol icin literatur spread degerleri kullanildi (source=fallback-literature).")


def main() -> None:
    parser = argparse.ArgumentParser(description="MT5 Gercek Spread Toplayici")
    parser.add_argument("--minutes", type=int, default=12, help="Ornekleme suresi (dakika)")
    parser.add_argument("--out", type=str, default=DEFAULT_OUT, help="Cikti JSON yolu")
    parser.add_argument("--terminal", type=str, default=DEFAULT_TERMINAL_PATH)
    parser.add_argument("--login", type=int, default=DEFAULT_LOGIN)
    parser.add_argument("--password", type=str, default=DEFAULT_PASSWORD)
    parser.add_argument("--server", type=str, default=DEFAULT_SERVER)
    args = parser.parse_args()

    duration_sec = max(1, int(args.minutes * 60))
    print("=" * 70)
    print("MT5 GERCEK SPREAD TOPLAYICI - IC Markets")
    print(f"Sembol sayisi : {len(SYMBOLS)}")
    print(f"Sure          : {args.minutes} dk ({duration_sec} sn), ornekleme araligi {SAMPLE_INTERVAL_SEC:.0f} sn")
    print(f"Cikti         : {args.out}")
    print("=" * 70)

    connected = connect_mt5_retriable(args.terminal, args.login, args.password, args.server)
    if not connected:
        build_fallback_result(
            "MT5 initialize 3 denemede basarisiz (terminal kapali / hesap bilgileri hatali olabilir).",
            args.out,
            args.minutes,
        )
        sys.exit(2)

    # Sembolleri Market Watch'a al
    active_symbols: list[str] = []
    failed_symbols: list[str] = []
    for sym, pip_size in SYMBOLS.items():
        if mt5.symbol_select(sym, True):
            si = mt5.symbol_info(sym)
            if si is None:
                print(f"[UYARI] {sym}: secildi ama symbol_info None -> ornekleme disi.")
                failed_symbols.append(sym)
                continue
            print(f"[OK] {sym}: point={si.point}, digits={si.digits}, ilk spread={si.spread} point")
            active_symbols.append(sym)
        else:
            print(f"[HATA] {sym}: Market Watch'a alinamadi ({mt5.last_error()}) -> ornekleme disi.")
            failed_symbols.append(sym)

    if not active_symbols:
        mt5.shutdown()
        build_fallback_result("MT5 baglandi ama hicbir sembol Market Watch'a alinamadi.", args.out, args.minutes)
        sys.exit(2)

    # Ornekleme dongusu: her 2 sn'de bir tum aktif sembollerin spread'ini topla
    samples: dict[str, list[float]] = {sym: [] for sym in active_symbols}
    start_t = time.time()
    iter_no = 0
    print("-" * 70)
    print(f"Ornekleme basladi: {len(active_symbols)} sembol x {duration_sec} sn")
    while True:
        iter_no += 1
        for sym in active_symbols:
            si = mt5.symbol_info(sym)
            if si is None:
                continue
            spread_points = float(si.spread)  # POINT cinsinden
            if spread_points <= 0:
                # Kotasyon yok / kotu tick -> ornekleme alma
                continue
            pip_size = SYMBOLS[sym]
            spread_pips = spread_points * float(si.point) / pip_size
            samples[sym].append(spread_pips)

        elapsed = time.time() - start_t
        if iter_no % 15 == 0 or elapsed >= duration_sec:
            done = sum(1 for s in active_symbols if samples[s])
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {elapsed:6.0f}/{duration_sec} sn | "
                  f"iterasyon {iter_no} | veri alan sembol: {done}/{len(active_symbols)} | "
                  f"EURUSD={samples.get('EURUSD', [])[-1] if samples.get('EURUSD') else '-'}")
        if elapsed >= duration_sec:
            break
        time.sleep(SAMPLE_INTERVAL_SEC)

    mt5.shutdown()
    print("MT5 baglantisi kapatildi.")

    # JSON uret
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {
        "meta": {
            "collected_at_utc": now_utc,
            "minutes": args.minutes,
            "samples_per_symbol": min((len(v) for v in samples.values() if v), default=0),
            "source": "MT5 ICMarketsSC-Demo",
            "mt5_server": args.server,
            "mt5_login": args.login,
            "excluded_symbols": failed_symbols,
        },
        "symbols": {},
    }

    for sym in SYMBOLS:
        vals = samples.get(sym, [])
        if not vals:
            # Baglanti vardi ama bu sembol icin veri toplanamadi -> literatur degerle doldur
            # (sessiz gecilmez: sembol bazli source isaretlenir, meta'ya excluded_symbols yazilir)
            fb = FALLBACK_SPREADS[sym]
            result["symbols"][sym] = {
                "avg_pips": fb,
                "min_pips": fb,
                "p95_pips": fb,
                "max_pips": fb,
                "samples": 0,
                "source": "fallback-literature",
                "note": "MT5 verisi toplanamadi, literatur degeri kullanildi",
            }
            print(f"[UYARI] {sym}: veri yok -> literatur fallback ({fb} pip) kullanildi.")
            continue

        svals = sorted(vals)
        n = len(svals)
        avg = sum(svals) / n
        result["symbols"][sym] = {
            "avg_pips": round(avg, 2),
            "min_pips": round(svals[0], 2),
            "p95_pips": round(percentile_95(svals), 2),
            "max_pips": round(svals[-1], 2),
            "samples": n,
            "source": "mt5",
        }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print("=" * 70)
    print(f"[YAZILDI] {args.out}")
    print(f"[KAYNAK]  MT5 ICMarketsSC-Demo (gercek broker verisi)")
    print("-" * 70)
    print(f"{'Sembol':<10} {'avg':>7} {'min':>7} {'p95':>7} {'max':>9} {'ornek':>6}")
    for sym in SYMBOLS:
        d = result["symbols"][sym]
        print(f"{sym:<10} {d['avg_pips']:>7.2f} {d['min_pips']:>7.2f} {d['p95_pips']:>7.2f} {d['max_pips']:>9.2f} {d['samples']:>6}")
    print("=" * 70)


if __name__ == "__main__":
    main()
