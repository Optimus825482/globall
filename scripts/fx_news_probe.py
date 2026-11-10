#!/usr/bin/env python3
"""HABER/SÜRPRİZ AİLESİ PROBU — sürpriz yönünde devam mı, dönüş mü? (2026-11-10)

NEDEN
-----
Bar-tabanlı ailelerin majörlerde kenarı yok (replay PF 0.26) ve takvim ailesi günde ~6 işlem
üretiyor. Literatürde ölçülmüş bir başka aile var: **makro sürpriz sonrası fiyat keşfi**
(Andersen-Bollerslev-Diebold-Vega, AER 93(1):38-62, 2003; Faust-Rogers-Wang-Wright, JME
54:1051-1068, 2007; Evans-Lyons, JFE 88(1):26-50, 2008 — etkinin ~2/3'ü order flow ile
KADEMELİ emilir). Bu, "sıçramayı yakala" DEĞİLDİR: sıçrama anında spread 3-10× açılır ve
kayma artar → o aile maliyetle ölür (Bessembinder 1994, Wei 1991). Burada ölçülen:
**t0+90 sn'de girip 15/60 dk tutmak** (spread normale döndükten sonra).

VERİ
----
Olaylar: PostgreSQL `calendar_surprises` (title_key, ts_key, currency, surprise=z cinsinden).
Fiyat: MT5 M1 barları (`--tf` ile değiştirilebilir; M1 derinliği ~3 ay).
Maliyet: gerçek tick spread (p50) + komisyon (pip cinsine çevrilir).

KONTROLLER (kontrolsüz haber sonucu kanıt sayılmaz)
---------------------------------------------------
  1. **Ters yön**: aynı giriş/çıkış, zıt pozisyon (ayna) → simetrik negatif olmalı.
  2. **Zayıf sürpriz**: |z| < 0.5 olaylar → etki görünmemeli.
  3. **Sahte olay**: giriş saatleri rastgele kaydırılır (permütasyon) → etki sönmeli.

Kullanim:
    python scripts/fx_news_probe.py --entry-delay-sec 90 --hold-min 60
    python scripts/fx_news_probe.py --min-abs-z 1.5 --json outputs/news_probe.json
"""
from __future__ import annotations

import argparse
import bisect
import collections
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


def db_url() -> str:
    u = (os.environ.get("DATABASE_URL") or "").strip()
    if u:
        return u
    try:
        with open(os.path.join(ROOT, "backend", ".env"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("DATABASE_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass
    return ""


def load_events() -> list[dict]:
    """`calendar_surprises` → [{ts, currency, z}]."""
    import psycopg
    url = db_url()
    if not url:
        return []
    out: list[dict] = []
    with psycopg.connect(url) as c:
        for title, ts_key, cur, z in c.execute(
                "SELECT title_key, ts_key, currency, surprise FROM calendar_surprises").fetchall():
            try:
                ts = dt.datetime.fromisoformat(str(ts_key).replace("Z", "+00:00")).timestamp()
            except Exception:  # noqa: BLE001
                continue
            out.append({"title": title, "ts": ts, "currency": str(cur or "").upper(),
                        "z": float(z or 0.0)})
    return sorted(out, key=lambda e: e["ts"])


def symbols_for(currency: str) -> list[tuple[str, int]]:
    """Para birimi → [(sembol, yön)] ; yön +1 = para birimi DEĞER KAZANIRSA o sembol yükselir."""
    if not currency:
        return []
    out = [(f"{currency}USD", +1), (f"USD{currency}", -1),
           (f"{currency}JPY", +1), (f"EUR{currency}", +1), (f"GBP{currency}", +1)]
    if currency == "USD":
        out = [("EURUSD", -1), ("GBPUSD", -1), ("USDJPY", +1), ("USDCAD", +1), ("USDCHF", +1)]
    seen, res = set(), []
    for sym, sign in out:
        s = BROKER_ALIAS.get(sym, sym)
        if s in seen:
            continue
        if mt5.symbol_info(s) is not None:
            seen.add(s)
            res.append((s, sign))
    return res


def load_m1(sym: str, years: float) -> tuple[list[int], list[tuple]]:
    out: list[tuple] = []
    end = dt.datetime.now()
    days = int(years * 365.25)
    i = 0
    while i < days:
        b_end = end - dt.timedelta(days=i)
        b_start = max(b_end - dt.timedelta(days=30), end - dt.timedelta(days=days))
        r = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1, b_start, b_end)
        if r is not None and len(r):
            out.extend((int(x["time"]), float(x["open"]), float(x["close"])) for x in r)
        i += 30
    out.sort(key=lambda b: b[0])
    return [b[0] for b in out], out


def price_at(keys: list[int], bars: list[tuple], ts: float) -> float | None:
    j = bisect.bisect_right(keys, ts) - 1
    if j < 0 or j >= len(bars):
        return None
    return bars[j][1]          # bar açılışı ≈ o anki fiyat


def cost_pips(sym: str, days: int = 3) -> float:
    i = mt5.symbol_info(sym)
    if i is None:
        return 1.0
    pip = float(i.point) * (10.0 if i.digits in (3, 5) else 1.0)
    end = dt.datetime.now()
    t = mt5.copy_ticks_range(sym, end - dt.timedelta(days=days), end, mt5.COPY_TICKS_ALL)
    sp = None
    if t is not None and len(t):
        vals = sorted((float(x["ask"]) - float(x["bid"])) for x in t if float(x["ask"]) > float(x["bid"]) > 0)
        if vals:
            sp = vals[len(vals) // 2]
    if sp is None:
        sp = float(i.spread) * float(i.point)
    per_pip = (float(i.trade_tick_value) / float(i.trade_tick_size)) * pip if i.trade_tick_size else 0.0
    comm_pips = (2.0 * 3.5 / per_pip) if per_pip else 0.0
    return (sp / pip if pip else 0.0) + comm_pips


def main() -> int:
    ap = argparse.ArgumentParser(description="Haber/sürpriz ailesi probu (maliyet sonrası + kontrol)")
    ap.add_argument("--entry-delay-sec", type=int, default=90, help="olaydan sonra giriş gecikmesi")
    ap.add_argument("--hold-min", type=int, default=60, help="tutma süresi (dakika)")
    ap.add_argument("--min-abs-z", type=float, default=0.0, help="yalnız bu |z| üstü olaylar")
    ap.add_argument("--years", type=float, default=0.3, help="M1 geçmiş derinliği (yıl)")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if not mt5.initialize():
        print(f"[HATA] MT5 initialize basarisiz: {mt5.last_error()}")
        return 2
    events = load_events()
    if not events:
        print("[UYARI] calendar_surprises boş — önce takvim/sürpriz üreticisi koşmalı.")
        return 1
    events = [e for e in events if abs(e["z"]) >= args.min_abs_z]
    print(f"Olay: {len(events)} | giriş t0+{args.entry_delay_sec}s | tutuş {args.hold_min} dk | "
          f"|z|>={args.min_abs_z}")

    cache: dict[str, tuple[list[int], list[tuple]]] = {}
    costs: dict[str, float] = {}
    stats: dict[str, dict] = collections.defaultdict(lambda: {"n": 0, "sum": 0.0, "vals": []})
    detail: list[dict] = []
    for e in events:
        for sym, sign in symbols_for(e["currency"]):
            if sym not in cache:
                cache[sym] = load_m1(sym, args.years)
                costs[sym] = cost_pips(sym)
            keys, bars = cache[sym]
            if len(bars) < 1000:
                continue
            t_in = e["ts"] + args.entry_delay_sec
            t_out = t_in + args.hold_min * 60
            p_in, p_out = price_at(keys, bars, t_in), price_at(keys, bars, t_out)
            if not p_in or not p_out:
                continue
            i = mt5.symbol_info(sym)
            pip = float(i.point) * (10.0 if i.digits in (3, 5) else 1.0)
            direction = (1 if e["z"] > 0 else -1) * sign        # sürpriz yönünde
            gross = direction * (p_out - p_in) / pip
            net = gross - costs[sym]
            stats[sym]["n"] += 1
            stats[sym]["sum"] += net
            stats[sym]["vals"].append(net)
            detail.append({"ts": e["ts"], "cur": e["currency"], "title": e["title"], "z": round(e["z"], 2),
                           "sym": sym, "dir": direction, "gross": round(gross, 2), "net": round(net, 2)})

    print(f"\n{'sembol':<9}{'n':>5}{'isabet%':>8}{'brüt/1h':>10}{'net/1h':>9}{'t':>7}")
    tot: list[float] = []
    for sym, st in sorted(stats.items(), key=lambda kv: -kv[1]["sum"] / max(1, kv[1]["n"])):
        n = st["n"]
        if n < 5:
            continue
        vals = st["vals"]
        m = statistics.mean(vals)
        sd = statistics.pstdev(vals) or 1e-9
        gross = m + costs[sym]
        print(f"{sym:<9}{n:>5}{100 * sum(1 for v in vals if v > 0) / n:>8.1f}{gross:>10.2f}"
              f"{m:>9.2f}{m / (sd / n ** 0.5):>7.2f}")
        tot.extend(vals)
    if tot:
        m = statistics.mean(tot)
        sd = statistics.pstdev(tot) or 1e-9
        print(f"{'TOPLAM':<9}{len(tot):>5}{'':>8}{'':>10}{m:>9.2f}{m / (sd / len(tot) ** 0.5):>7.2f}")

    # KONTROL 1: ters yön (ayna)
    mirror = [-x - 2 * 0 for x in tot]     # net'ler zaten tek yön; ayna için brüt ters çevrilir
    if tot:
        g = statistics.mean([d["gross"] for d in detail])
        c = statistics.mean([costs[d["sym"]] for d in detail])
        print(f"\nKONTROL 1 (ters yön): brüt {-g:+.2f}p − maliyet {c:.2f} = net {-g - c:+.2f}p "
              f"(beklenen: ilk yönün aynası)")
    # KONTROL 2: zayıf sürprizler
    weak = [d for d in detail if abs(d["z"]) < 0.5]
    if len(weak) >= 5:
        print(f"KONTROL 2 (|z|<0.5, n={len(weak)}): net {statistics.mean([d['net'] for d in weak]):+.2f}p "
              f"(etki görünmemeli)")
    # KONTROL 3: olay saatlerini rastgele kaydır (permütasyon)
    if len(detail) >= 20:
        rng = random.Random(11)
        perm: list[float] = []
        for d in detail:
            sym = d["sym"]
            keys, bars = cache[sym]
            for _ in range(3):
                shift = rng.choice([-7200, -3600, 3600, 7200, 10800])
                p_in = price_at(keys, bars, d["ts"] + args.entry_delay_sec + shift)
                p_out = price_at(keys, bars, d["ts"] + args.entry_delay_sec + shift + args.hold_min * 60)
                if not p_in or not p_out:
                    continue
                i = mt5.symbol_info(sym)
                pip = float(i.point) * (10.0 if i.digits in (3, 5) else 1.0)
                perm.append(d["dir"] * (p_out - p_in) / pip - costs[sym])
        if perm:
            print(f"KONTROL 3 (saat kaydırma, n={len(perm)}): net {statistics.mean(perm):+.2f}p "
                  f"(etki sönmeli; gerçek sonuçla karşılaştır)")
    if args.json:
        p = args.json if os.path.isabs(args.json) else os.path.join(ROOT, args.json)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"events": len(events), "entry_delay_sec": args.entry_delay_sec,
                       "hold_min": args.hold_min, "costs": costs,
                       "by_symbol": {s: {"n": v["n"], "net_mean": round(v["sum"] / v["n"], 3)}
                                     for s, v in stats.items() if v["n"]},
                       "detail": detail}, f, ensure_ascii=False, indent=2)
        print(f"\nJSON: {p}")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
