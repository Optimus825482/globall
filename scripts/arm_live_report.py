#!/usr/bin/env python3
"""CANLI KOL İZLEME — ayar değişikliği gerçekten işledi mi, kâr etti mi? (2026-11-12)

NEDEN
-----
2026-11-12'de iki canlı kolun sembol listesi ölçümle değiştirildi:
  * `lb_symbols`       : USDCHF, USDJPY çıkarıldı · AUDUSD, NAS100 eklendi
  * `ema_adx_symbols`  : USDJPY, US30 eklendi
Kod varsayılanı **kayıtlı ayar dosyasını EZMEZ** → panelden girilmediyse eski liste
yürürlükte kalır. Bu betik iki soruyu yanıtlar:

  1. **Ayar işledi mi?** → çıkarılan sembollerde yeni giriş var mı? (olmamalı)
     ve eklenenlerde giriş başladı mı? (olmalı)
  2. **Kâr ediyor mu?** → kol×sembol bazında n / isabet / net / PF; kill kriteri
     (n≥20 ve PF<1,0 → kapat) uygulanır. Yetersiz örneklemde SAYI üretmez.

KAYNAK: `trades` tablosu (canlı kapanmış FX işlemleri; `strategy` kolonu) ve
`decision_logs` (tarama/ret kayıtları — işlem olmasa da canlılık kanıtı).

Kullanim:
    python scripts/arm_live_report.py --days 14
    python scripts/arm_live_report.py --since 2026-11-12 --strategies london_breakout,ema_adx_pullback
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 2026-11-12 ölçümünde çıkarılan / eklenen semboller (ayar uygulandı mı kontrolü)
REMOVED = {"london_breakout": ["USDCHF", "USDJPY"], "ema_adx_pullback": []}
ADDED = {"london_breakout": ["AUDUSD", "NAS100"], "ema_adx_pullback": ["USDJPY", "US30"]}
MIN_N = 20


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


def pf_of(pnls: list[float]) -> float | None:
    gw = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p < 0)
    if gl <= 0:
        return None if gw <= 0 else float("inf")
    return gw / gl


def main() -> int:
    ap = argparse.ArgumentParser(description="Canlı kol izleme (ayar etkisi + kârlılık)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--since", default="", help="YYYY-MM-DD (verilirse --days yok sayılır)")
    ap.add_argument("--strategies", default="london_breakout,ema_adx_pullback")
    ap.add_argument("--out", default=os.path.join(ROOT, "outputs", "arm_live_report.json"))
    args = ap.parse_args()

    if args.since:
        since = dt.datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()
    else:
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)).timestamp()
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]

    url = db_url()
    if not url:
        print("[HATA] DATABASE_URL yok")
        return 2
    import psycopg

    out: dict = {"baslangic": dt.datetime.fromtimestamp(since, dt.timezone.utc).isoformat(timespec="seconds"),
                 "semboller": {}, "ayar_kontrolu": {}, "verdict": {}}

    with psycopg.connect(url) as conn:
        # 1) Kapanmış işlemler: kol × sembol
        rows = conn.execute(
            "SELECT strategy, symbol, pnl, pnl_pct, exit_time FROM trades"
            " WHERE exit_time >= %s AND strategy = ANY(%s)", (since, strategies)).fetchall()
        if not rows:
            print("[UYARI] `trades` tablosunda bu aralıkta FX işlemi yok.")
            print("        (Yerelde canlı FX işlemi olmaz — bu betik SUNUCUDA koşulmalı.)")

        agg: dict[tuple[str, str], list[float]] = {}
        for st, sym, pnl, _pct, _t in rows:
            agg.setdefault((str(st), str(sym).upper()), []).append(float(pnl or 0.0))

        print(f"\n=== KOL × SEMBOL (son {((dt.datetime.now(dt.timezone.utc).timestamp()-since)/86400):.0f} gün) ===")
        print(f"{'kol':<20}{'sembol':<9}{'n':>4}{'isabet%':>9}{'net':>10}{'PF':>7}  karar")
        for (st, sym), pnls in sorted(agg.items(), key=lambda kv: -sum(kv[1])):
            n = len(pnls)
            wins = sum(1 for p in pnls if p > 0)
            net = sum(pnls)
            pf = pf_of(pnls)
            if n < MIN_N:
                verdict = f"YETERSİZ (n<{MIN_N})"
            elif pf is not None and pf < 1.0:
                verdict = "KAPAT (PF<1,0)"
            else:
                verdict = "DEVAM"
            print(f"{st:<20}{sym:<9}{n:>4}{100.0*wins/n:>9.1f}{net:>10.2f}"
                  f"{(f'{pf:.2f}' if pf is not None else '—'):>7}  {verdict}")
            out["semboller"][f"{st}:{sym}"] = {
                "n": n, "win_pct": round(100.0 * wins / n, 1), "net": round(net, 2),
                "pf": (round(pf, 3) if pf is not None and pf != float("inf") else pf),
                "verdict": verdict}

        # 2) Ayar uygulandı mı: çıkarılan sembollerde giriş OLMAMALI
        # TUZAK: defter tamamen boşsa "çıkarılan sembolde işlem yok" kanıt DEĞİLDİR —
        # sıfır, "ayar işledi" ile "hiç işlem olmadı"yı ayırt edemez.
        book_active = len(rows) > 0
        print("\n=== AYAR KONTROLÜ ===")
        if not book_active:
            print("  ÖLÇÜLEMEDİ: bu aralıkta hiç kapanmış işlem yok → ayar etkisi kanıtlanamaz.")
        for st in strategies:
            for sym in REMOVED.get(st, []):
                n = conn.execute(
                    "SELECT count(*) FROM trades WHERE strategy=%s AND symbol=%s AND entry_time >= %s",
                    (st, sym, since)).fetchone()[0]
                ok = (n == 0)
                if not book_active:
                    tag = "ÖLÇÜLEMEDİ (defter boş)"
                elif ok:
                    tag = "✅ ayar işledi"
                else:
                    tag = "⚠️ AYAR İŞLEMEMİŞ (panelden güncelle)"
                print(f"  {st:<20}{sym:<9} çıkarıldı → yeni işlem: {n} {tag}")
                out["ayar_kontrolu"][f"{st}:{sym}"] = {
                    "beklenen": "0 işlem", "gercek": n,
                    "ok": (ok if book_active else None)}
            for sym in ADDED.get(st, []):
                n = conn.execute(
                    "SELECT count(*) FROM trades WHERE strategy=%s AND symbol=%s AND entry_time >= %s",
                    (st, sym, since)).fetchone()[0]
                scan = conn.execute(
                    "SELECT count(*) FROM decision_logs WHERE strategy ILIKE %s AND symbol=%s"
                    " AND timestamp >= %s",
                    (f"%{st.split('_')[0]}%", sym, since)).fetchone()[0]
                print(f"  {st:<20}{sym:<9} eklendi   → yeni işlem: {n} (tarama kaydı: {scan})")
                out["ayar_kontrolu"][f"{st}:{sym}"] = {"beklenen": ">0 (zamanla)", "islem": n,
                                                       "tarama": scan}

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nYazıldı: {args.out}")
    print("NOT: n<20 olan satırlarda PF'e karar verilmez (kill kriteri: n≥20 ve PF<1,0). "
          "Çıkarılan sembollerde işlem görmeye devam ediyorsa ayar panelden uygulanmamıştır.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
