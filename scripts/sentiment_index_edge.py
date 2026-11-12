#!/usr/bin/env python3
"""BİLEŞİK SENTIMENT SKORU → İLERİ GETİRİ ÖLÇÜMÜ (2026-11-12)

NEDEN
-----
`app/sentiment_index.py` skoru üretiyor ama gücü ÖLÇÜLMEDİ; ağırlıklar yargıdır.
"Bu endeks işe yarıyor mu" sorusunun tek dürüst cevabı: skor ile sonraki N saatlik
getiri arasındaki ilişki. Skor rutinle loglanıyor (`sentiment_index_history`).

ÖLÇTÜĞÜ ŞEY
-----------
  * **Spearman IC** (skor → ileri getiri). Pozitif = yüksek skor sonrası yukarı.
  * Kovalar: ≤−45 / −45…−20 / −20…+20 / +20…+45 / ≥+45 → ortalama ileri getiri (pip) + t.
  * "Uç" stratejisi: yalnız |skor| ≥ eşik iken skor yönünde pozisyon → net pip ve
    **maliyet düşülmüş** hâli (ölçülen spread profili varsa).
  * **Örtüşme kontrolü:** skor yavaş değiştiği için ardışık gözlemlerin ileri
    pencereleri üst üste biner → t istatistiği şişer. Varsayılan `--non-overlap`
    her sembolde en az `horizon` kadar ayrık gözlem seçer.

DÜRÜSTLÜK
---------
* `--min-n` altında "YETERSİZ ÖRNEKLEM" der, sayı üretmez.
* Veri geriye dönük üretilemez: log bugün başladıysa ileri bar HENÜZ yoktur —
  betik bunu açıkça söyler.
* Maliyet düşülmemiş sütun ayrı yazılır; brüt kenar spread'in altındaysa karar değeri yok.

Kullanim:
    python scripts/sentiment_index_edge.py --symbols EURUSD,GBPUSD --horizon-h 24
    python scripts/sentiment_index_edge.py --all --days 45 --min-n 200
    python scripts/sentiment_index_edge.py --all --horizon-h 8 --non-overlap
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
    sd = statistics.pstdev(xs)
    if sd <= 0:
        return 0.0
    return statistics.mean(xs) / (sd / math.sqrt(len(xs)))


def spearman_ic(pairs: list[tuple[float, float]]) -> float:
    """Sıra korelasyonu (bağ yok sayılır — skorlar kuantize ama yeterli)."""
    if len(pairs) < 5:
        return 0.0

    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        rk = [0.0] * len(vals)
        for pos, i in enumerate(order):
            rk[i] = float(pos + 1)
        return rk

    rx, ry = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) or 1.0
    return num / den


def pip_size(symbol: str) -> float:
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
        if s in ("US30", "NAS100", "US2000", "JP225", "UK100", "DE40"):
            return 1.0
        return 0.0001


def bucket_of(score: float, edge: float = 45.0) -> str:
    if score <= -edge:
        return f"güçlü SHORT (≤−{edge:.0f})"
    if score < -20:
        return "hafif SHORT"
    if score <= 20:
        return "dengeli"
    if score < edge:
        return "hafif LONG"
    return f"güçlü LONG (≥+{edge:.0f})"


def spread_cost_pips(symbol: str) -> float | None:
    """Ölçülen ortalama spread (pip) — `outputs/fx_spread_replay_profile.json`."""
    try:
        p = os.path.join(ROOT, "outputs", "fx_spread_replay_profile.json")
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        v = (d.get("symbols") or {}).get(symbol.upper()) or {}
        avg = v.get("avg_pips")
        return float(avg) if avg is not None else None
    except Exception:  # noqa: BLE001
        return None


def _demo(mode: str) -> int:
    """Matematiği bilinen cevaba karşı doğrular (DB gerekmez).

    'edge':  fwd = 0.12×skor + gürültü → IC belirgin pozitif olmalı.
    'noise': fwd bağımsız             → IC ~0 ve |t| < 2 olmalı.
    Bu denetim geçmeden gerçek veriye bakmak anlamsız (yanlış formül = yanlış karar).
    """
    import random
    rnd = random.Random(7)
    pairs = []
    for _ in range(600):
        score = max(-100.0, min(100.0, rnd.gauss(0, 35)))
        noise = rnd.gauss(0, 12)
        fwd = (0.12 * score + noise) if mode == "edge" else noise
        pairs.append((score, fwd))
    ic = spearman_ic(pairs)
    ext = [f if sc > 0 else -f for sc, f in pairs if abs(sc) >= 45]
    print(f"[DEMO:{mode}] n={len(pairs)} IC={ic:+.3f} | uç n={len(ext)} "
          f"ort={statistics.mean(ext) if ext else 0:+.2f}p t={t_stat(ext):+.2f}")
    if mode == "edge":
        # Sentetik ilişki gücü: fwd = 0.12×skor + N(0,12) → beklenen Spearman ≈ 0,33.
        ok = ic > 0.25 and t_stat(ext) > 3
        print("  beklenti: IC belirgin POZİTİF, uç t > 3 →", "GEÇTİ" if ok else "KALDI")
        return 0 if ok else 1
    ok = abs(ic) < 0.12 and abs(t_stat(ext)) < 2
    print("  beklenti: IC ~0, |t| < 2 →", "GEÇTİ" if ok else "KALDI")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Sentiment skoru → ileri getiri ölçümü")
    ap.add_argument("--symbols", default="EURUSD,GBPUSD,USDJPY,XAUUSD")
    ap.add_argument("--all", action="store_true", help="log olan tüm semboller")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--horizon-h", type=float, default=24.0)
    ap.add_argument("--timeframe", default="5m")
    ap.add_argument("--min-n", type=int, default=200)
    ap.add_argument("--edge", type=float, default=45.0, help="'uç' sayılan |skor| eşiği")
    ap.add_argument("--non-overlap", action="store_true", default=True,
                    help="ileri pencereleri üst üste bindirme (varsayılan açık)")
    ap.add_argument("--allow-overlap", dest="non_overlap", action="store_false")
    ap.add_argument("--out", default=os.path.join(ROOT, "outputs", "sentiment_index_edge.json"))
    ap.add_argument("--demo", choices=["", "edge", "noise"], default="",
                    help="Bilinen-cevap denetimi: 'edge' → skor getiriyi sürükler (IC yüksek), "
                         "'noise' → ilişki yok (IC ~0). DB'ye dokunmaz.")
    args = ap.parse_args()

    if args.demo:
        return _demo(args.demo)

    url = db_url()
    if not url:
        print("[HATA] DATABASE_URL yok")
        return 2
    import psycopg

    hz_ms = int(args.horizon_h * 3600 * 1000)
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)).timestamp()
    out = {"olcum": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "ufuk_saat": args.horizon_h, "ortusmesiz": bool(args.non_overlap), "semboller": {}}

    with psycopg.connect(url) as conn:
        if args.all:
            syms = [r[0] for r in conn.execute(
                "SELECT DISTINCT symbol FROM sentiment_index_history ORDER BY 1").fetchall()]
        else:
            syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if not syms:
            print("[HATA] sentiment_index_history boş — rutin (`sentiment_index_log`) çalışmalı")
            return 3

        for sym in syms:
            rows = conn.execute(
                "SELECT fetched_at, score FROM sentiment_index_history"
                " WHERE symbol=%s AND fetched_at >= %s ORDER BY fetched_at",
                (sym, cutoff)).fetchall()
            if not rows:
                print(f"  {sym:<9} log yok")
                continue
            pip = pip_size(sym)
            pairs: list[tuple[float, float]] = []
            no_future = no_base = 0
            last_used = -1e18
            for ts, score in rows:
                t0 = int(float(ts) * 1000)
                if args.non_overlap and (t0 - last_used) < hz_ms:
                    continue
                r = conn.execute(
                    "SELECT close FROM historical_candles WHERE symbol=%s AND timeframe=%s"
                    " AND open_time <= %s ORDER BY open_time DESC LIMIT 1",
                    (sym, args.timeframe, t0)).fetchone()
                if not r or float(r[0]) <= 0:
                    no_base += 1
                    continue
                r2 = conn.execute(
                    "SELECT close FROM historical_candles WHERE symbol=%s AND timeframe=%s"
                    " AND open_time >= %s ORDER BY open_time ASC LIMIT 1",
                    (sym, args.timeframe, t0 + hz_ms)).fetchone()
                if not r2:
                    no_future += 1
                    continue
                pairs.append((float(score), (float(r2[0]) - float(r[0])) / pip))
                last_used = t0

            if not pairs:
                neden = []
                if no_future:
                    neden.append(f"{no_future} gözlemde +{args.horizon_h:g}s ileri bar HENÜZ YOK "
                                 f"(log yeni başladı; {args.horizon_h:g} saat sonra ölçülebilir)")
                if no_base:
                    neden.append(f"{no_base} gözlemde fiyat barı yok")
                print(f"  {sym:<9} {len(rows)} log · " + (" | ".join(neden) or "eşleşme yok"))
                continue

            ic = spearman_ic(pairs)
            buckets: dict[str, dict] = {}
            for sc, fwd in pairs:
                b = buckets.setdefault(bucket_of(sc, args.edge), {"xs": []})
                b["xs"].append(fwd)
            cost = spread_cost_pips(sym)
            bucket_out = {}
            for name, d in buckets.items():
                xs = d["xs"]
                bucket_out[name] = {
                    "n": len(xs), "ort_pip": round(statistics.mean(xs), 2),
                    "med_pip": round(statistics.median(xs), 2),
                    "t": round(t_stat(xs), 2),
                    "ort_net_pip": (round(statistics.mean(xs) - cost, 2)
                                    if cost is not None else None),
                }

            # "Uç" stratejisi: |skor| >= edge iken skor yönünde pozisyon
            ext = [fwd if sc > 0 else -fwd for sc, fwd in pairs if abs(sc) >= args.edge]
            ext_mean = statistics.mean(ext) if ext else None
            n = len(pairs)
            yeterli = n >= args.min_n
            verdict = ("YETERSİZ ÖRNEKLEM — sayı karar için kullanılmaz" if not yeterli else
                       ("anlamlı DEĞİL (|t|<2)" if all(abs(v["t"]) < 2 for v in bucket_out.values())
                        else "anlamlı kova var — kapı adayı"))
            out["semboller"][sym] = {
                "gozlem": n, "yeterli": yeterli, "spearman_ic": round(ic, 3),
                "kovalar": bucket_out,
                "uc_stratejisi": {
                    "n": len(ext),
                    "ort_pip": round(ext_mean, 2) if ext_mean is not None else None,
                    "t": round(t_stat(ext), 2) if ext else 0.0,
                    "ort_net_pip": (round(ext_mean - cost, 2)
                                    if (ext_mean is not None and cost is not None) else None),
                    "spread_maliyeti_pip": cost,
                },
                "verdict": verdict,
            }
            marks = " ".join(f"{k.split(' (')[0]}:n={v['n']} {v['ort_pip']:+.2f}p t={v['t']:+.1f}"
                             f"({'net ' + format(v['ort_net_pip'], '+.2f') + 'p' if v['ort_net_pip'] is not None else 'net ?'})"
                             for k, v in bucket_out.items())
            print(f"  {sym:<9} n={n:<5} IC={ic:+.3f} | {marks} | {verdict}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nYazıldı: {args.out}")
    print("NOT: IC > 0 = yüksek skor sonrası yukarı. 'Uç' sütununda net = brüt − ölçülen "
          "spread. maliyet sonrası pozitif değilse kenar maliyeti karşılamıyor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
