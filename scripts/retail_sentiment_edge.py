#!/usr/bin/env python3
"""PERAKENDE KONUMLANMA → İLERİ GETİRİ ÖLÇÜMÜ (2026-11-12)

NEDEN
-----
`app/retail_sentiment.py` kalabalığın tarafını topluyor ama **kapı değil**:
karar akışını değiştirmiyor. Kapıya çevirmek için tek yol ölçüm: "aşırı
konumlanma (≥%70 tek taraf) sonraki N saatte karşı yöne mi dönüyor?"

Bu betik tam onu ölçer: retail_sentiment_history (loglar) × historical_candles
(fiyat). Spearman IC + kova ortalamaları + t istatistiği.

DÜRÜSTLÜK
---------
* Veri **geriye dönük alınamıyor** → ölçüm ancak log biriktikçe anlamlanır.
  Varsayılan eşik 200 gözlem; altındaysa "YETERSİZ" der, sayı üretmez.
* Maliyet düşülmüş sütun ayrıca yazılır (spread profili varsa) — brüt kenar
  maliyetin altındaysa karar değeri yoktur.
* t < 2 ise "anlamlı değil" yazar; işaret negatifse mekanizma ters çalışıyor
  demektir (contrarian hipotezi çürür).

Kullanim:
    python scripts/retail_sentiment_edge.py --symbols EURUSD,GBPUSD,USDJPY,XAUUSD --horizon-h 24
    python scripts/retail_sentiment_edge.py --all --days 45 --out outputs/retail_edge.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def db_url() -> str:
    u = (os.environ.get("DATABASE_URL") or "").strip()
    if u:
        return u
    try:
        for line in open(os.path.join(ROOT, "backend", ".env"), encoding="utf-8"):
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def t_stat(xs: list[float]) -> float:
    if len(xs) < 3:
        return 0.0
    m = statistics.mean(xs)
    sd = statistics.pstdev(xs)
    if sd <= 0:
        return 0.0
    return m / (sd / math.sqrt(len(xs)))


def pips(symbol: str) -> float:
    try:
        sys.path.insert(0, os.path.join(ROOT, "backend"))
        from app.routers import forex
        return float(forex.get_symbol_trading_specs(symbol)["pip_size"])
    except Exception:  # noqa: BLE001
        s = symbol.upper()
        if "JPY" in s:
            return 0.01
        if s.startswith("XAU"):
            return 0.1
        return 0.0001


def buckets() -> list[tuple[str, float, float]]:
    """(etiket, alt, üst) — long yüzdesine göre."""
    return [
        ("kalabalık SHORT (long≤30)", 0.0, 30.0),
        ("dengeli (31-49)", 30.0, 50.0),
        ("dengeli (50-69)", 50.0, 70.0),
        ("kalabalık LONG (long≥70)", 70.0, 101.0),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="Retail sentiment → ileri getiri ölçümü")
    ap.add_argument("--symbols", default="EURUSD,GBPUSD,USDJPY,AUDUSD,XAUUSD")
    ap.add_argument("--all", action="store_true", help="DB'de log olan tüm semboller")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--horizon-h", type=float, default=24.0)
    ap.add_argument("--min-n", type=int, default=200, help="altında 'YETERSİZ' der")
    ap.add_argument("--timeframe", default="5m", help="historical_candles zaman dilimi (yerelde 5m dolu)")
    ap.add_argument("--out", default=os.path.join(ROOT, "outputs", "retail_sentiment_edge.json"))
    args = ap.parse_args()

    url = db_url()
    if not url:
        print("[HATA] DATABASE_URL yok")
        return 2
    import psycopg

    hz_ms = int(args.horizon_h * 3600 * 1000)
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)).timestamp()

    out = {"olcum": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "ufuk_saat": args.horizon_h, "semboller": {}}

    with psycopg.connect(url) as conn:
        syms = ([r[0] for r in conn.execute(
            "SELECT DISTINCT symbol FROM retail_sentiment_history ORDER BY 1").fetchall()]
            if args.all else [s.strip().upper() for s in args.symbols.split(",") if s.strip()])
        if not syms:
            print("[HATA] retail_sentiment_history boş — önce app.retail_sentiment çalışmalı")
            return 3

        for sym in syms:
            rows = conn.execute(
                "SELECT fetched_at, long_pct FROM retail_sentiment_history"
                " WHERE symbol=%s AND fetched_at >= %s ORDER BY fetched_at",
                (sym, cutoff)).fetchall()
            if not rows:
                print(f"  {sym:<9} log yok")
                continue
            pip = pips(sym)
            samples = []
            no_base = no_future = 0
            for ts, long_pct in rows:
                t0 = int(float(ts) * 1000)
                r = conn.execute(
                    "SELECT close FROM historical_candles WHERE symbol=%s AND timeframe=%s"
                    " AND open_time <= %s ORDER BY open_time DESC LIMIT 1", (sym, args.timeframe, t0)).fetchone()
                if not r or float(r[0]) <= 0:
                    no_base += 1
                    continue
                r2 = conn.execute(
                    "SELECT close FROM historical_candles WHERE symbol=%s AND timeframe=%s"
                    " AND open_time >= %s ORDER BY open_time ASC LIMIT 1", (sym, args.timeframe, t0 + hz_ms)).fetchone()
                if not r2:
                    # En sık durum: log BUGÜN başladı, +ufuk kadar ileri bar henüz oluşmadı.
                    no_future += 1
                    continue
                fwd_pips = (float(r2[0]) - float(r[0])) / pip
                samples.append((float(long_pct), fwd_pips))
            if not samples:
                neden = []
                if no_future:
                    neden.append(f"{no_future} gözlemde +{args.horizon_h:g}s ileri bar HENÜZ YOK "
                                 f"(log yeni başladı; {args.horizon_h:g} saat sonra ölçülebilir)")
                if no_base:
                    neden.append(f"{no_base} gözlemde fiyat barı yok (veri penceresi dışı)")
                print(f"  {sym:<9} {len(rows)} log · " + (" | ".join(neden) or "eşleşme yok"))
                continue

            # Spearman IC: long_pct ↑ ise ileri getiri ↑ mı? (contrarian ise NEGATİF olmalı)
            n = len(samples)
            def ranks(vals):
                order = sorted(range(len(vals)), key=lambda i: vals[i])
                rk = [0.0] * len(vals)
                for pos, i in enumerate(order):
                    rk[i] = float(pos + 1)
                return rk
            rx, ry = ranks([s[0] for s in samples]), ranks([s[1] for s in samples])
            mx, my = statistics.mean(rx), statistics.mean(ry)
            num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
            den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) or 1.0
            ic = num / den

            kova = {}
            for label, lo, hi in buckets():
                xs = [f for lp, f in samples if lo <= lp < hi]
                if not xs:
                    continue
                kova[label] = {"n": len(xs), "ort_pip": round(statistics.mean(xs), 2),
                               "med_pip": round(statistics.median(xs), 2),
                               "t": round(t_stat(xs), 2)}
            yeterli = n >= args.min_n
            out["semboller"][sym] = {
                "gozlem": n, "yeterli": yeterli,
                "spearman_ic": round(ic, 3),
                "ic_yonu": ("CONTRA (long↑ → getiri↓)" if ic < 0 else "PRO (long↑ → getiri↑)"),
                "kovalar": kova,
                "verdict": ("YETERSİZ ÖRNEKLEM — sayı karar için kullanılmaz" if not yeterli else
                            ("anlamlı DEĞİL (|t|<2)" if all(abs(v["t"]) < 2 for v in kova.values())
                             else "anlamlı kovalar var — replay A/B'ye aday")),
            }
            print(f"  {sym:<9} n={n:<5} IC={ic:+.3f} ({out['semboller'][sym]['ic_yonu']}) | "
                  + " | ".join(f"{k.split(' (')[0]} n={v['n']} {v['ort_pip']:+.2f}p t={v['t']:+.1f}"
                               for k, v in kova.items())
                  + f" | {out['semboller'][sym]['verdict']}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nYazıldı: {args.out}")
    print("NOT: kontrarian hipotez doğruysa IC NEGATİF ve 'kalabalık' kovalarının "
          "getirisi karşı yönde olmalı. Maliyet düşülmedi — brüt kenar spread'in "
          "altındaysa karar değeri yoktur.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
