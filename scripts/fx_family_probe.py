#!/usr/bin/env python3
"""FX AİLE PROBU — takvim/fixing ailelerini KENDİ VERİMİZDE ve MALİYET SONRASI test (2026-11-10)

NEDEN
-----
Bar-tabanlı trend/kırılım ailelerinin majörlerde kenarı ölçüldü ve YOK (replay PF 0.26).
Bu yüzden "takvim/fixing" aileleri araştırıldı; literatürde iddia edilen etkiler var:
  * Tokyo fix (09:55 JST): Ito & Yamada, JIE 109 (2017) "Puzzles in the Tokyo fixing" — kalıcı
    USD alım dengesizliği. Gotobi günleri (ayın 5/10/15/20/25/30'u) etkisi daha güçlü.
  * WMR/16:00 Londra fix: Krohn-Mueller-Whelan, JF 79(1) (2024) — ay sonu rebalans akışı.
İddiaların çoğu TAKVİM bloglarından geliyor (sayı zayıf kanıt). Bu betik iddiayı
**kendi broker verimizde** ve **maliyet düşülerek** ölçer, üstüne KONTROL grubu koyar
(kontrol olmadan takvim etkisi kanıtlanmış sayılmaz: aynı saatler, gotobi OLMAYAN günler).

KURALLAR
--------
1. Ölçüm M1 barlardan; giriş/çıkış SAATİ sabit (iddiadaki pencere).
2. Maliyet gerçek: tick'ten ölçülen p50 spread + komisyon (pip cinsine çevrilir).
3. Kontroller: (a) aynı saatler, gotobi olmayan iş günleri; (b) aynı sayıda RASTGELE gün.
4. Yıl bazında da kırılır (etki tek yılda mı, kalıcı mı).

Kullanim:
    python scripts/fx_family_probe.py --family gotobi --years 2 --symbols USDJPY,EURJPY
    python scripts/fx_family_probe.py --family all --years 3 --json outputs/family_probe.json
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import os
import random
import statistics
import sys

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 yok — Python 3.12'yi tam yolla cagirin.")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROKER_ALIAS = {"NAS100": "USTEC"}


def pip_of(sym: str) -> float:
    i = mt5.symbol_info(sym)
    if i is None:
        return 0.0
    return float(i.point) * (10.0 if i.digits in (3, 5) else 1.0)


def usd_per_pip_per_lot(sym: str) -> float:
    i = mt5.symbol_info(sym)
    if i is None or not i.trade_tick_value or not i.trade_tick_size:
        return 0.0
    tick_val = float(i.trade_tick_value)
    tick_size = float(i.trade_tick_size)
    return (tick_val / tick_size) * pip_of(sym)


TF_MAP = {"M1": None, "M5": None, "M15": None, "M30": None, "H1": None}


def load_m1(sym: str, years: int, tf: str = "M1", chunk_days: int = 30) -> list[tuple]:
    """Barlar (ts_saniye, o,h,l,c). NOT: terminal `maxbars` (100k) tek isteği sınırlar →
    dilimleme şart. Derinlik zaman dilimine bağlı: H1 5 yıl var, M1 yalnız ~3 ay."""
    out: list[tuple] = []
    end = dt.datetime.now()
    days = int(years * 365.25)
    i = 0
    while i < days:
        b_end = end - dt.timedelta(days=i)
        b_start = max(b_end - dt.timedelta(days=chunk_days), end - dt.timedelta(days=days))
        r = mt5.copy_rates_range(sym, TF_MAP[tf], b_start, b_end)
        if r is not None and len(r):
            out.extend((int(x["time"]), float(x["open"]), float(x["high"]),
                        float(x["low"]), float(x["close"])) for x in r)
        i += chunk_days
    out.sort(key=lambda b: b[0])
    return out


def idx_at(bars: list[tuple], ts: float) -> int | None:
    """ts anına en yakın barın indeksi (bar açılışı <= ts)."""
    keys = [b[0] for b in bars]
    j = bisect.bisect_right(keys, ts) - 1
    return j if j >= 0 else None


def cost_pips(sym: str, spread_p50: float, comm_per_lot_side: float) -> float:
    """Tur başına toplam maliyet (pip): spread (tek yön, giriş) + komisyon 2 yön."""
    per_pip = usd_per_pip_per_lot(sym) or 1.0
    comm_pips = (2.0 * comm_per_lot_side) / per_pip
    return spread_p50 + comm_pips


def measure_spread_p50(sym: str, days: int = 3) -> float:
    end = dt.datetime.now()
    t = mt5.copy_ticks_range(sym, end - dt.timedelta(days=days), end, mt5.COPY_TICKS_ALL)
    pip = pip_of(sym)
    if t is None or not len(t) or pip <= 0:
        i = mt5.symbol_info(sym)
        return (float(i.spread) * float(i.point) / pip) if i and pip else 1.0
    sp = sorted((float(x["ask"]) - float(x["bid"])) / pip for x in t if float(x["ask"]) > float(x["bid"]) > 0)
    return sp[len(sp) // 2] if sp else 1.0


# --------------------------------------------------------------------------- aileler

def gotobi_days(d0: dt.date, d1: dt.date) -> set[dt.date]:
    """5/10/15/20/25/30 (hafta sonuna düşerse ÖNCEKİ iş günü)."""
    out = set()
    cur = d0
    while cur <= d1:
        for dom in (5, 10, 15, 20, 25, 30):
            try:
                d = cur.replace(day=dom)
            except ValueError:
                continue
            while d.weekday() >= 5:  # Cmt/Paz → önceki iş günü
                d -= dt.timedelta(days=1)
            out.add(d)
        # ayın ilk gününe atla
        cur = (cur.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    return out


def trade_window(bars: list[tuple], entry_ts: float, exit_ts: float, direction: int) -> float | None:
    """Pip cinsinden brüt getiri (yön × fiyat farkı)."""
    i, j = idx_at(bars, entry_ts), idx_at(bars, exit_ts)
    if i is None or j is None or j < i:
        return None
    pip = entry_pip
    return direction * (bars[j][4] - bars[i][1]) / pip


def main() -> int:
    ap = argparse.ArgumentParser(description="Takvim/fixing aile probu (maliyet sonrası + kontrol)")
    ap.add_argument("--family", default="gotobi", choices=["gotobi", "eom", "hourofday", "all"])
    ap.add_argument("--years", type=int, default=2)
    ap.add_argument("--symbols", default="USDJPY,EURJPY,GBPJPY,USDCHF")
    ap.add_argument("--comm-per-lot-side", type=float, default=3.5,
                    help="komisyon USD/lot/yon (ICMarkets raw ~3.5)")
    ap.add_argument("--tf", default="H1", choices=["M1", "M5", "M15", "M30", "H1"],
                    help="H1 önerilir: terminal geçmişi H1'de 5 yıl, M1'de ~3 ay")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if not mt5.initialize():
        print(f"[HATA] MT5 initialize basarisiz: {mt5.last_error()}")
        return 2
    global entry_pip
    TF_MAP.update({"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                   "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1})
    chunk = 30 if args.tf == "M1" else 90 if args.tf in ("M5", "M15") else 180
    ai = mt5.account_info()
    if ai:
        print(f"Hesap {ai.login} {ai.server} | {args.years} yıl M1 | aile={args.family}")

    result: dict = {"years": args.years, "family": args.family, "symbols": {}}
    today = dt.date.today()
    start = today - dt.timedelta(days=int(args.years * 365.25))
    gset = gotobi_days(start, today)

    for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        b_sym = BROKER_ALIAS.get(sym, sym)
        if mt5.symbol_info(b_sym) is None:
            print(f"  {sym}: terminalde yok — atlandı")
            continue
        if not mt5.symbol_info(b_sym).visible:
            mt5.symbol_select(b_sym, True)
        bars = load_m1(b_sym, args.years, args.tf, chunk)
        if len(bars) < 500:
            print(f"  {sym}: yeterli M1 yok ({len(bars)}) — atlandı")
            continue
        entry_pip = pip_of(b_sym)
        sp = measure_spread_p50(b_sym)
        cst = cost_pips(b_sym, sp, args.comm_per_lot_side)
        days = sorted({dt.datetime.fromtimestamp(b[0], dt.timezone.utc).date() for b in bars})
        print(f"\n=== {sym} | M1 {len(bars):,} bar | gün {days[0]}→{days[-1]} | "
              f"spread p50 {sp:.2f}p | maliyet {cst:.2f}p/tur")

        fam: dict = {}
        if args.family in ("hourofday", "all"):
            # SAAT AİLESİ: 5 yıl H1 üzerinde saat başına NET (maliyet düşülmüş) ortalama getiri.
            # Uzun (LONG) yön; SELL tarafı ayrı satırda (işaret ters). Kontrol: t istatistiği.
            per_hour: dict = {}
            for h in range(24):
                rets = []
                for d in days:
                    base = dt.datetime.combine(d, dt.time(0, 0), dt.timezone.utc).timestamp()
                    r = trade_window(bars, base + h * 3600, base + (h + 1) * 3600, +1)
                    if r is not None:
                        rets.append(r - cst)
                if len(rets) >= 60:
                    m = statistics.mean(rets); sd = statistics.pstdev(rets) or 1e-9
                    per_hour[f"{h:02d}:00"] = {"n": len(rets), "net_ort_pip": round(m, 3),
                                               "t": round(m / (sd / len(rets) ** 0.5), 2)}
            fam["hourofday_LONG"] = per_hour
            print("  saat (UTC)  n     net_ort_pip     t   [LONG yönü; negatif→SELL tarafı kârlı]")
            for k, v in sorted(per_hour.items(), key=lambda kv: -kv[1]["net_ort_pip"]):
                print(f"   {k}  {v['n']:>5}  {v['net_ort_pip']:>+10.3f}  {v['t']:>7.2f}")
        if args.family in ("gotobi", "all"):
            # A2: gotobi günü D için fix anı 09:55 JST = 00:55 UTC (D).
            #  * prefix: giriş 07:00 JST = 22:00 UTC (D-1) → çıkış 00:55 UTC (D), LONG USD/JPY
            #  * postfix: giriş 00:55 UTC (D) → çıkış 01:30 UTC (D), SHORT (fix sonrası geri dönüş)
            windows = {
                "gotobi_prefix_LONG": (-1 * 22 * 60, 0 * 60 + 55, +1),   # d-1 22:00 → d 00:55
                "gotobi_postfix_SHORT": (0 * 60 + 55, 1 * 60 + 30, -1),  # d 00:55 → d 01:30
            }
            for label, (in_min, out_min, direction) in windows.items():
                g, ctrl, rnd = [], [], []
                rng = random.Random(1234)

                def _ret(d: dt.date) -> float | None:
                    base = dt.datetime.combine(d, dt.time(0, 0), dt.timezone.utc)
                    ts_in = base.timestamp() + in_min * 60
                    ts_out = base.timestamp() + out_min * 60
                    return trade_window(bars, ts_in, ts_out, direction)

                for d in days:
                    r = _ret(d)
                    if r is None:
                        continue
                    (g if d in gset else ctrl).append(r)
                pool = [d for d in days if d not in gset]
                for d in rng.sample(pool, min(len(pool), max(30, len(g) * 3))):
                    r = _ret(d)
                    if r is not None:
                        rnd.append(r)

                def stat(xs: list[float], c: float) -> dict:
                    if not xs:
                        return {"n": 0}
                    net = [x - c for x in xs]
                    m, s = statistics.mean(net), (statistics.pstdev(net) or 1e-9)
                    wins = sum(1 for x in net if x > 0)
                    gp = sum(x for x in net if x > 0)
                    gl = -sum(x for x in net if x < 0) or 1e-9
                    return {"n": len(xs), "brut_ort_pip": round(statistics.mean(xs), 3),
                            "net_ort_pip": round(m, 3), "isabet_pct": round(100 * wins / len(xs), 1),
                            "t": round(m / (s / len(xs) ** 0.5), 2),
                            "PF": round(gp / gl, 3), "net_toplam_pip": round(sum(net), 1)}
                fam[label] = {"gotobi": stat(g, cst), "kontrol": stat(ctrl, cst),
                              "rastgele": stat(rnd, cst)}
                for k, v in fam[label].items():
                    if v.get("n"):
                        print(f"  {label:<22} {k:<9} n={v['n']:>4} net {v['net_ort_pip']:+.3f}p "
                              f"isabet %{v['isabet_pct']:<5} t={v['t']:>5} PF={v['PF']:.2f} "
                              f"toplam {v['net_toplam_pip']:+.0f}p")
        result["symbols"][sym] = {"bars": len(bars), "spread_p50": round(sp, 3),
                                  "cost_pips": round(cst, 3), "families": fam}

    if args.json:
        p = args.json if os.path.isabs(args.json) else os.path.join(ROOT, args.json)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nJSON: {p}")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
