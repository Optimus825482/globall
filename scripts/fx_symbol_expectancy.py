#!/usr/bin/env python3
"""SEMBOL BAZLI GERÇEK BEKLENTİ (R) + MALİYET + KARARLILIK (2026-11-10)

NEDEN
-----
"Kârlılık neden düşük" sorusu bugüne kadar replay çıktısından tartışıldı; **broker
defterinin kendi ölçümü** yoktu. Bu betik gerçek dolumlardan işlem başına R
beklentisini çıkarır ve şu iki soruyu sayıyla yanıtlar:

  1) Kazanan/kaybeden oranı (payoff) kaç? → beklenti = isabet×ort_kazanç − kayıp×ort_kayıp
  2) Hangi sembol YAPISAL olarak zararlı (60 günün İKİ YARISINDA da negatif)?

MALİYET
-------
Komisyon GERÇEKTİR (deal.commission). Spread, MT5 tick akışından ölçülür
(`copy_ticks_range` → p50/p95), `mt5_spread_profile` tablosuna bağımlı değildir.
cost_R = (komisyon + spread_maliyeti) / stop_riski → "maliyet stop mesafesinin
yüzde kaçı" sorusunun cevabı.

KARARLILIK (neden yarıya bölüyoruz)
-----------------------------------
Tek dönemde negatif çıkan sembol gürültü olabilir. Bu yüzden pencere ikiye
bölünür ve **kural yalnız iki yarıda da negatif olan + n ≥ --min-n** sembollere
uygulanır. Yine de bu bir IN-SAMPLE seçimdir; kalıcı blok kararı replay A/B ile
teyit edilmelidir.

Kullanim:
    python scripts/fx_symbol_expectancy.py --days 60
    python scripts/fx_symbol_expectancy.py --days 60 --split-days 30 --json outputs/fx_expectancy.json
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import statistics
import sys

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 yok — Python 3.12'yi tam yolla cagirin.")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def value_per_unit(symbol: str, volume: float) -> float:
    i = mt5.symbol_info(symbol)
    if i is None or not i.trade_tick_size or not i.trade_tick_value:
        return 0.0
    return (float(i.trade_tick_value) / float(i.trade_tick_size)) * float(volume)


def initial_risk_price(symbol: str, pid: int) -> float:
    """Giriş emrinin SL'sinden stop mesafesi (fiyat). 0 = okunamadı."""
    orders = mt5.history_orders_get(position=pid)
    if orders is None or not len(orders):
        return 0.0
    sls = [float(o.sl) for o in orders if float(getattr(o, "sl", 0) or 0) > 0]
    return sls[-1] if sls else 0.0


def measure_spread(symbols: set[str], days: int) -> dict[str, dict]:
    """Tick akışından gerçek spread dağılımı (pip cinsinden p50/p95)."""
    out: dict[str, dict] = {}
    end = dt.datetime.now()
    start = end - dt.timedelta(days=max(1, days))
    for s in sorted(symbols):
        i = mt5.symbol_info(s)
        if i is None:
            continue
        pip = float(i.point) * (10.0 if i.digits in (3, 5) else 1.0)
        ticks = mt5.copy_ticks_range(s, start, end, mt5.COPY_TICKS_ALL)
        if ticks is None or not len(ticks):
            out[s] = {"p50_pips": None, "p95_pips": None, "n": 0}
            continue
        sp = sorted((float(t["ask"]) - float(t["bid"])) / pip for t in ticks
                    if float(t["ask"]) > float(t["bid"]) > 0)
        if not sp:
            out[s] = {"p50_pips": None, "p95_pips": None, "n": len(ticks)}
            continue
        out[s] = {"p50_pips": round(sp[len(sp) // 2], 3),
                  "p95_pips": round(sp[int(len(sp) * 0.95) - 1], 3), "n": len(ticks)}
    return out


def load_positions(days: int, symbols: set[str] | None) -> list[dict]:
    frm = dt.datetime.now() - dt.timedelta(days=days)
    deals = mt5.history_deals_get(frm, dt.datetime.now())
    if deals is None:
        raise RuntimeError(f"history_deals_get basarisiz: {mt5.last_error()}")
    pos: dict[int, dict] = {}
    for d in deals:
        sym = str(getattr(d, "symbol", "") or "")
        if not sym or (symbols and sym not in symbols):
            continue
        pid = int(getattr(d, "position_id", 0) or 0)
        if pid <= 0:
            continue
        r = pos.setdefault(pid, {"position_id": pid, "symbol": sym, "volume": 0.0,
                                 "profit": 0.0, "commission": 0.0, "swap": 0.0,
                                 "open_time": None, "open_price": None, "close_time": None})
        r["profit"] += float(getattr(d, "profit", 0.0) or 0.0)
        r["commission"] += float(getattr(d, "commission", 0.0) or 0.0)
        r["swap"] += float(getattr(d, "swap", 0.0) or 0.0)
        if int(getattr(d, "entry", 0) or 0) == 0:
            r["open_time"] = float(getattr(d, "time", 0) or 0)
            r["open_price"] = float(getattr(d, "price", 0.0) or 0.0)
        else:
            r["close_time"] = float(getattr(d, "time", 0) or 0)
            r["volume"] += float(getattr(d, "volume", 0.0) or 0.0)
    return [r for r in pos.values() if r["close_time"] and r["open_price"] and r["volume"] > 0]


def main() -> int:
    ap = argparse.ArgumentParser(description="Sembol bazlı gerçek beklenti (R) ölçümü")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--split-days", type=int, default=30, help="kararlılık yarısı (gün)")
    ap.add_argument("--min-n", type=int, default=30, help="karar için en az işlem")
    ap.add_argument("--spread-days", type=int, default=2, help="tick spread örnekleme penceresi")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if not mt5.initialize():
        print(f"[HATA] MT5 initialize basarisiz: {mt5.last_error()}")
        return 2
    ai = mt5.account_info()
    if ai:
        print(f"Hesap {ai.login} {ai.server} | equity {ai.equity:.2f} {ai.currency} | para birimi {ai.currency}")

    syms = {s.strip().upper() for s in args.symbols.split(",") if s.strip()} or None
    rows = load_positions(args.days, syms)
    if not rows:
        print("Kapanmış pozisyon yok.")
        return 1
    now = dt.datetime.now().timestamp()
    cut = now - args.split_days * 86400

    spreads = measure_spread({r["symbol"] for r in rows}, args.spread_days)
    stats = collections.defaultdict(lambda: collections.defaultdict(float))
    skipped = collections.Counter()
    detail: list[dict] = []

    for r in rows:
        sym = r["symbol"]
        sl = initial_risk_price(sym, r["position_id"])
        if not (r["open_price"] and sl):
            skipped["sl_yok"] += 1
            continue
        vpu = value_per_unit(sym, r["volume"])
        if vpu <= 0:
            skipped["deger_yok"] += 1
            continue
        risk = abs(r["open_price"] - sl) * vpu
        if risk <= 0:
            skipped["risk_sifir"] += 1
            continue
        net = r["profit"] + r["commission"] + r["swap"]
        sp_pips = (spreads.get(sym) or {}).get("p50_pips")
        info = mt5.symbol_info(sym)
        pip = (float(info.point) * (10.0 if info.digits in (3, 5) else 1.0)) if info else 0.0
        spread_cost = (sp_pips * pip * vpu) if (sp_pips and pip) else 0.0
        cost = abs(r["commission"]) + spread_cost
        R = net / risk
        half = "ilk" if r["open_time"] < cut else "son"
        a = stats[sym]
        a["n"] += 1
        a["net"] += net
        a["R"] += R
        a["cost"] += cost
        a["risk"] += risk
        a["sl_pips"] += abs(r["open_price"] - sl) / pip if pip else 0.0
        a[f"n_{half}"] += 1
        a[f"R_{half}"] += R
        if net > 0:
            a["win"] += 1
            a["winR"] += R
        else:
            a["loss"] += 1
            a["lossR"] += R
        detail.append({"symbol": sym, "net": round(net, 2), "R": round(R, 4),
                       "cost_R": round(cost / risk, 4), "win": net > 0,
                       "open_time": r["open_time"]})

    hdr = (f"{'sembol':<9}{'n':>5}{'isabet%':>8}{'kazR':>7}{'kayR':>7}{'payoff':>8}"
           f"{'beklentiR':>10}{'net$':>9}{'maliyetR':>9}{'stop_pip':>9}{'ilkR':>7}{'sonR':>7}  karar")
    print("\n" + hdr)
    print("-" * len(hdr))
    block_list: list[str] = []
    keep_list: list[str] = []
    tot = collections.defaultdict(float)
    for sym, a in sorted(stats.items(), key=lambda kv: kv[1]["R"] / max(1.0, kv[1]["n"])):
        n = int(a["n"])
        wr = 100.0 * a["win"] / n
        aw = a["winR"] / a["win"] if a["win"] else 0.0
        al = a["lossR"] / a["loss"] if a["loss"] else 0.0
        exp = a["R"] / n
        payoff = (aw / abs(al)) if al else 0.0
        r_ilk = a["R_ilk"] / a["n_ilk"] if a["n_ilk"] else 0.0
        r_son = a["R_son"] / a["n_son"] if a["n_son"] else 0.0
        cost_R = a["cost"] / a["risk"] if a["risk"] else 0.0
        verdict = "—"
        if n >= args.min_n:
            if exp < 0 and r_ilk < 0 and r_son < 0:
                verdict = "NEGATİF (iki yarıda da)"
                block_list.append(sym)
            elif exp > 0 and r_ilk > 0 and r_son > 0:
                verdict = "POZİTİF (iki yarıda da)"
                keep_list.append(sym)
            else:
                verdict = "belirsiz"
        print(f"{sym:<9}{n:>5}{wr:>8.1f}{aw:>7.2f}{al:>7.2f}{payoff:>8.2f}"
              f"{exp:>10.3f}{a['net']:>9.0f}{cost_R:>9.3f}"
              f"{(a['sl_pips'] / n if n else 0):>9.1f}{r_ilk:>7.2f}{r_son:>7.2f}  {verdict}")
        for k in ("n", "net", "R", "cost", "risk", "win", "loss", "winR", "lossR"):
            tot[k] += a[k]
    n = int(tot["n"])
    aw = tot["winR"] / tot["win"] if tot["win"] else 0.0
    al = tot["lossR"] / tot["loss"] if tot["loss"] else 0.0
    be = 100.0 * abs(al) / (aw + abs(al)) if (aw + abs(al)) else 0.0
    print("-" * len(hdr))
    print(f"TOPLAM    {n:>5}{100.0 * tot['win'] / n:>8.1f}{aw:>7.2f}{al:>7.2f}"
          f"{(aw / abs(al) if al else 0):>8.2f}{tot['R'] / n:>10.3f}{tot['net']:>9.0f}"
          f"{tot['cost'] / tot['risk']:>9.3f}")
    print(f"\n  ölçülen payoff  : kazanan {aw:.2f}R / kaybeden {al:.2f}R → oran {aw / abs(al) if al else 0:.2f}")
    print(f"  bu payoff için break-even isabet : {be:.1f}%  (gerçek {100.0 * tot['win'] / n:.1f}%)")
    print(f"  atlanan işlem   : {dict(skipped)}")
    if block_list:
        print(f"\n  NEGATİF GÜVENİLİR (n≥{args.min_n}, iki yarıda da negatif): {', '.join(block_list)}")
    if keep_list:
        print(f"  POZİTİF GÜVENİLİR: {', '.join(keep_list)}")
    print(f"  spread örneklemi: son {args.spread_days} gün tick (p50); komisyon GERÇEK deal alanından")

    payload = {"days": args.days, "split_days": args.split_days, "min_n": args.min_n,
               "account": getattr(ai, "login", None),
               "total": {"n": n, "win_pct": round(100.0 * tot["win"] / n, 2),
                         "avg_win_R": round(aw, 3), "avg_loss_R": round(al, 3),
                         "payoff": round(aw / abs(al), 3) if al else None,
                         "expectancy_R": round(tot["R"] / n, 4), "net_usd": round(tot["net"], 2),
                         "break_even_win_pct": round(be, 2),
                         "cost_R": round(tot["cost"] / tot["risk"], 4) if tot["risk"] else None},
               "by_symbol": {s: {k: round(v, 4) for k, v in a.items()} for s, a in stats.items()},
               "block_candidates": block_list, "keep_candidates": keep_list,
               "spreads": spreads, "skipped": dict(skipped)}
    if args.json:
        path = args.json if os.path.isabs(args.json) else os.path.join(ROOT, args.json)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"JSON: {path}")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
