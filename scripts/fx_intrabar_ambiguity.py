#!/usr/bin/env python3
"""FX İNTRABAR BELİRSİZLİK BANDI + GERÇEK SWAP MALİYETİ (2026-11-10)

NEDEN (ölçülmemiş boşluk)
-------------------------
Replay (`scripts/forex_replay_backtest.py:2174`) SL ve TP'nin **aynı bar içinde**
görülmesi hâlinde "SL önce" (muhafazakâr) varsayar. Bu varsayım doğru tercihtir
ama **etkisinin büyüklüğü hiç ölçülmedi**: çıkış barında iki bariyer birlikte
düşüyorsa hangisinin önce geldiği bar verisinden ÇÖZÜLEMEZ, dolayısıyla o
işlemlerin simülasyondaki PnL'i bir varsayıma bağlıdır. Bu betik o bandı ölçer.

İkinci boşluk: **swap (taşıma) maliyeti hiçbir yerde hesaba girmiyor**
(`portfolio_risk` `cost_r` = spread + komisyon). Burada GERÇEK swap ölçülür
(kapanış deal'inin `swap` alanı), modellenmez.

YÖNTEM (neden güvenilir)
------------------------
1. Gerçek = MT5 defteri (broker dolumları). Seviyeler `history_orders_get`
   ile o pozisyona ait emirlerden alınır.
2. SL/TP seviyesi SONRADAN DEĞİŞTİYSE (trailing/BE) o işlem **belirsizlik
   kümesinden çıkarılır** ve ayrı sayılır — seviyeyi bilmeden sıra ölçülemez.
3. Belirsiz kümenin sırası **tick akışından** kesin çözülür
   (`copy_ticks_range`, COPY_TICKS_ALL). BUY pozisyon BID'den, SELL ASK'tan
   kapanır; MT5 barları BID tabanlıdır → SELL için bar spread kadar kaydırılır.
4. Tick yoksa çözülemez → "çözülemedi" diye sayılır, sayı UYDURULMAZ.

ÇIKTI
-----
* Kapanmış işlem / belirsiz / çözülen sayıları
* "SL-first" varsayımının gerçekle uyuşma oranı (isabet)
* Varsayım yanlışsa replay'in PnL sapması (USD ve işlem başına R)
* Gerçek swap toplamı, sembol bazında; swap'ın stop riskine oranı (R)

Kullanim:
    python scripts/fx_intrabar_ambiguity.py --days 60 --tf 5m
    python scripts/fx_intrabar_ambiguity.py --days 90 --json outputs/intrabar.json

NOT: `python` bir PyManager shim'i olabilir; MT5 import edilemezse Python 3.12'yi
TAM YOLLA cagirin (bkz. fx_build_tick_cache.py notu).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sys

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 yok — Python 3.12'yi tam yolla cagirin.")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: MT5 deal.reason — kapanış nedeni
REASON = {0: "CLIENT", 1: "MOBILE", 2: "WEB", 3: "EXPERT", 4: "SL", 5: "TP", 6: "SO",
          7: "ROLLOVER", 8: "VMARGIN", 9: "SPLIT", 10: "NONE"}

TFS = {"1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15}
TF_SEC = {"1m": 60, "5m": 300, "15m": 900}


# --------------------------------------------------------------------------- defter

def _deal_field(d, name, default=0.0):
    try:
        v = getattr(d, name, default)
    except Exception:  # noqa: BLE001
        return default
    return default if v is None else v


def load_trades(days: int, symbols: set[str] | None = None) -> list[dict]:
    """Kapanmış pozisyonları (position_id bazında) deftere çevir."""
    frm = dt.datetime.now() - dt.timedelta(days=days)
    deals = mt5.history_deals_get(frm, dt.datetime.now())
    if deals is None:
        raise RuntimeError(f"history_deals_get basarisiz: {mt5.last_error()}")

    pos: dict[int, dict] = {}
    for d in deals:
        if _deal_field(d, "magic", 0) is None:
            continue
        sym = str(_deal_field(d, "symbol", "") or "")
        if not sym or (symbols and sym not in symbols):
            continue
        pid = int(_deal_field(d, "position_id", 0) or 0)
        if pid <= 0:
            continue
        rec = pos.setdefault(pid, {"position_id": pid, "symbol": sym, "volume": 0.0,
                                   "open_time": None, "open_price": None,
                                   "close_time": None, "close_price": None,
                                   "profit": 0.0, "swap": 0.0, "commission": 0.0,
                                   "close_reasons": [], "n_deals": 0})
        rec["n_deals"] += 1
        rec["profit"] += float(_deal_field(d, "profit", 0.0) or 0.0)
        rec["swap"] += float(_deal_field(d, "swap", 0.0) or 0.0)
        rec["commission"] += float(_deal_field(d, "commission", 0.0) or 0.0)
        entry = int(_deal_field(d, "entry", 0) or 0)      # 0=in, 1=out
        t = float(_deal_field(d, "time", 0) or 0)
        if entry == 0:
            rec["open_time"] = t
            rec["open_price"] = float(_deal_field(d, "price", 0.0) or 0.0)
            rec["direction"] = "BUY" if int(_deal_field(d, "type", 0) or 0) == 0 else "SELL"
        else:
            rec["close_time"] = max(rec["close_time"] or 0.0, t) if rec["close_time"] else t
            rec["close_price"] = float(_deal_field(d, "price", 0.0) or 0.0)
            rec["volume"] += float(_deal_field(d, "volume", 0.0) or 0.0)
            rec["close_reasons"].append(REASON.get(int(_deal_field(d, "reason", 0) or 0), "?"))
    return [r for r in pos.values() if r.get("close_time") and r.get("open_time")]


def levels(pid: int) -> tuple[float, float, bool]:
    """Pozisyonun SL/TP seviyeleri + sonradan DEĞİŞTİ mi (trailing/BE izi)."""
    orders = mt5.history_orders_get(position=pid)
    if orders is None or not len(orders):
        return 0.0, 0.0, False
    sl = tp = 0.0
    modified = False
    first_sltp = None
    for o in orders:
        o_sl, o_tp = float(getattr(o, "sl", 0.0) or 0.0), float(getattr(o, "tp", 0.0) or 0.0)
        if o_sl or o_tp:
            if first_sltp is None:
                first_sltp = (o_sl, o_tp)
            elif (o_sl, o_tp) != first_sltp:
                modified = True
        sl, tp = o_sl or sl, o_tp or tp
    return sl, tp, modified


# --------------------------------------------------------------------------- bar / tick

def exit_bar(symbol: str, tf: str, close_ts: float, direction: str,
             spread_price: float = 0.0):
    """Kapanış anını içeren barı döndür (BID tabanlı; SELL için ASK'a kaydırılır)."""
    t0 = dt.datetime.fromtimestamp(close_ts - 3 * TF_SEC[tf])
    t1 = dt.datetime.fromtimestamp(close_ts + 3 * TF_SEC[tf])
    rates = mt5.copy_rates_range(symbol, TFS[tf], t0, t1)
    if rates is None or not len(rates):
        return None
    sec = TF_SEC[tf]
    hit = None
    for r in rates:
        ts = int(r["time"])
        if ts <= close_ts < ts + sec:
            hit = r
            break
    if hit is None:
        return None
    hi, lo = float(hit["high"]), float(hit["low"])
    if direction == "SELL" and spread_price > 0:
        hi, lo = hi + spread_price, lo + spread_price   # ASK tarafı
    return {"ts": int(hit["time"]), "high": hi, "low": lo}


def tick_winner(symbol: str, direction: str, bar_ts: int, tf: str,
                sl: float, tp: float) -> str | None:
    """Belirsiz barın sırasını gerçek tick akışından çöz. None = çözülemedi."""
    t0 = dt.datetime.fromtimestamp(bar_ts - 1)
    t1 = dt.datetime.fromtimestamp(bar_ts + TF_SEC[tf] + 1)
    ticks = mt5.copy_ticks_range(symbol, t0, t1, mt5.COPY_TICKS_ALL)
    if ticks is None or not len(ticks):
        return None
    for t in ticks:
        bid, ask = float(t["bid"]), float(t["ask"])
        px = bid if direction == "BUY" else ask        # çıkış fiyatı tarafı
        if px <= 0:
            continue
        if direction == "BUY":
            if sl and px <= sl:
                return "SL"
            if tp and px >= tp:
                return "TP"
        else:
            if sl and px >= sl:
                return "SL"
            if tp and px <= tp:
                return "TP"
    return None


def usd_per_price_unit(symbol: str, volume: float) -> float:
    """1 fiyat birimi hareketinin USD değeri (belirli lot için)."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0
    tick_size = float(info.trade_tick_size or 0.0)
    tick_value = float(info.trade_tick_value or 0.0)
    if tick_size <= 0 or tick_value <= 0:
        return 0.0
    return (tick_value / tick_size) * volume


# --------------------------------------------------------------------------- ana

def main() -> int:
    ap = argparse.ArgumentParser(description="İntrabar belirsizlik bandı + gerçek swap maliyeti")
    ap.add_argument("--days", type=int, default=60, help="geriye bakış (gün)")
    ap.add_argument("--tf", default="5m", choices=sorted(TFS), help="motorun bar periyodu")
    ap.add_argument("--symbols", default="", help="virgüllü beyaz liste (boş = hepsi)")
    ap.add_argument("--max-trades", type=int, default=0, help=">0 ise en yeni N işlem")
    ap.add_argument("--json", default="", help="JSON çıktı yolu")
    args = ap.parse_args()

    if not mt5.initialize():
        print(f"[HATA] MT5 initialize basarisiz: {mt5.last_error()}")
        return 2
    ai = mt5.account_info()
    if ai:
        print(f"Hesap: {ai.login} {ai.server} | equity {ai.equity:.2f} {ai.currency}")

    syms = {s.strip().upper() for s in args.symbols.split(",") if s.strip()} or None
    trades = load_trades(args.days, syms)
    if not trades:
        print("Kapanmış pozisyon bulunamadı.")
        return 1
    trades.sort(key=lambda r: r["close_time"] or 0)
    if args.max_trades and len(trades) > args.max_trades:
        trades = trades[-args.max_trades:]
    print(f"Kapanmış pozisyon: {len(trades)} (son {args.days} gün)")

    stats = collections.Counter()
    by_symbol = collections.defaultdict(lambda: collections.Counter())
    band_usd = 0.0
    band_r = []
    swap_by_symbol: dict[str, float] = collections.defaultdict(float)
    swap_total = comm_total = profit_total = 0.0
    ambiguous_rows: list[dict] = []

    for tr in trades:
        sym, direction = tr["symbol"], tr.get("direction") or "?"
        swap_by_symbol[sym] += tr["swap"]
        swap_total += tr["swap"]
        comm_total += tr["commission"]
        profit_total += tr["profit"]
        stats["total"] += 1
        by_symbol[sym]["total"] += 1

        reason = tr["close_reasons"][-1] if tr["close_reasons"] else "?"
        sl, tp, modified = levels(tr["position_id"])
        if not (sl and tp):
            stats["seviye_yok"] += 1
            continue
        if modified:
            stats["seviye_degisti_trailing"] += 1
            continue
        info = mt5.symbol_info(sym)
        if info is None:
            stats["sembol_yok"] += 1
            continue
        spread = float(getattr(info, "spread", 0) or 0) * float(info.point or 0.0)
        bar = exit_bar(sym, args.tf, tr["close_time"], direction, spread)
        if bar is None:
            stats["bar_yok"] += 1
            continue

        sl_touch = (bar["low"] <= sl) if direction == "BUY" else (bar["high"] >= sl)
        tp_touch = (bar["high"] >= tp) if direction == "BUY" else (bar["low"] <= tp)
        if not (sl_touch and tp_touch):
            stats["belirsiz_degil"] += 1
            # varsayım gerçekle uyuşuyor mu (tek bariyer düşmüşse kesin bilgi)
            if reason in ("SL", "TP"):
                only = "SL" if sl_touch else "TP" if tp_touch else None
                if only and only == reason:
                    stats["kesin_uyumlu"] += 1
                elif only:
                    stats["kesin_CELISKI"] += 1
            continue

        stats["belirsiz"] += 1
        by_symbol[sym]["belirsiz"] += 1
        winner = tick_winner(sym, direction, bar["ts"], args.tf, sl, tp)
        row = {"symbol": sym, "direction": direction, "close_reason": reason,
               "sl": sl, "tp": tp, "bar_ts": bar["ts"], "tick_winner": winner,
               "volume": tr["volume"], "profit": round(tr["profit"], 2)}
        # varsayımımız SL-first; gerçek/ölçülen sonuçla karşılaştır
        if winner:
            stats[f"tick_{winner}"] += 1
            if winner == "SL":
                stats["varsayim_dogru"] += 1
            else:
                stats["varsayim_YANLIS"] += 1
                # replay bu işlemi SL ile kapatırdı, gerçek TP'ye gitmiş →
                # sapma = (tp - sl) yönünde kazanç kaybı
                per_unit = usd_per_price_unit(sym, tr["volume"])
                delta = abs(tp - sl) * per_unit
                band_usd += delta
                risk = abs(tr["open_price"] - sl) * per_unit if tr["open_price"] else 0.0
                if risk > 0:
                    band_r.append(delta / risk)
                row["sapma_usd"] = round(delta, 2)
                row["sapma_r"] = round(delta / risk, 3) if risk > 0 else None
        else:
            stats["tick_cozulemedi"] += 1
        if reason == "SL":
            stats["belirsiz_gercek_SL"] += 1
        elif reason == "TP":
            stats["belirsiz_gercek_TP"] += 1
        ambiguous_rows.append(row)

    # ------------------------------------------------------------------ rapor
    n = stats["total"] or 1
    print("\n--- İNTRABAR BELİRSİZLİK ---")
    print(f"  bar periyodu            : {args.tf}")
    print(f"  seviyesi okunamayan     : {stats['seviye_yok']}")
    print(f"  seviyesi DEĞİŞEN (trail): {stats['seviye_degisti_trailing']} (ölçüm dışı)")
    print(f"  tek bariyer (belirsiz değil): {stats['belirsiz_degil']}")
    print(f"  BELİRSİZ (iki bariyer de aynı barda): {stats['belirsiz']} "
          f"({100.0 * stats['belirsiz'] / n:.1f}%)")
    print(f"    tick ile çözülen      : {stats['tick_SL'] + stats['tick_TP']}")
    print(f"    tick yok / çözülemedi : {stats['tick_cozulemedi']}")
    print(f"  varsayım (SL-first) DOĞRU: {stats['varsayim_dogru']}")
    print(f"  varsayım YANLIŞ (gerçek TP): {stats['varsayim_YANLIS']}")
    tot_res = stats["varsayim_dogru"] + stats["varsayim_YANLIS"]
    if tot_res:
        print(f"  → varsayım isabeti      : {100.0 * stats['varsayim_dogru'] / tot_res:.1f}%")
    print(f"  sapma (USD)             : {band_usd:.2f}")
    if band_r:
        print(f"  sapma (R, işlem başına) : ort {sum(band_r) / len(band_r):.2f}R "
              f"| en büyük {max(band_r):.2f}R | n={len(band_r)}")
    if stats["kesin_CELISKI"]:
        print(f"  ! tek-bariyer çelişkisi : {stats['kesin_CELISKI']} "
              f"(kanonik kapanış etiketi ile fiyat kanıtı uyuşmuyor)")

    print("\n--- GERÇEK SWAP (kapanış deal'inden, modellenmemiş) ---")
    print(f"  toplam swap             : {swap_total:.2f} {ai.currency if ai else 'USD'}")
    print(f"  toplam komisyon         : {comm_total:.2f}")
    print(f"  net (profit+swap+comm)  : {profit_total + swap_total + comm_total:.2f}")
    top = sorted(swap_by_symbol.items(), key=lambda kv: kv[1])[:8]
    for s, v in top:
        if v:
            print(f"    {s:<10} {v:>9.2f} | işlem {by_symbol[s]['total']:>3}")

    payload = {"days": args.days, "tf": args.tf, "account": getattr(ai, "login", None),
               "stats": dict(stats), "band_usd": round(band_usd, 2),
               "band_r_mean": round(sum(band_r) / len(band_r), 3) if band_r else None,
               "swap_total": round(swap_total, 2), "commission_total": round(comm_total, 2),
               "profit_total": round(profit_total, 2),
               "swap_by_symbol": {k: round(v, 2) for k, v in swap_by_symbol.items()},
               "ambiguous": ambiguous_rows}
    if args.json:
        path = args.json if os.path.isabs(args.json) else os.path.join(ROOT, args.json)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"\nJSON: {path}")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
