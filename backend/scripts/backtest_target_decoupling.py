"""HEDEF-OLASILIK BAĞINI AYIRMA — karşı-olgusal backtest (2026-11-09)

SORU
----
§13'te ölçüldü: `target_pct` ile `ml_hit_probability` bağlı (Spearman 0.537) ve
**en yüksek olasılıklı dilim hedefe DAHA AZ değiyor** (Q3 %32.4 → Q5 %29.9).
Hedefi olasılıktan AYIRMAK (sabit veya yalnız ATR tabanlı) bu bozukluğu düzeltir
mi ve **beklenen değeri** iyileştirir mi?

VERİDEN ÖLÇÜLEN İKTİSAT (65.471 aday, 180 gün)
---------------------------------------------
  STOPPED_OUT          n=34.083   net=-1.850%   exit=-1.500%  (SABİT stop)
  TARGET_HIT           n=18.258   net=+2.022%   exit=+2.372%
  MAX_HORIZON_EXPIRED  n=13.130   net=-0.365%   exit=-0.015%
  → stop = 1.500% (sabit), işlem maliyeti ≈ 0.35 puan, taban EV = -0.473%

YÖNTEM — ve DÜRÜST SINIRI
-------------------------
`mfe_pct` (gerçekleşen maksimum elverişli hareket) karşı-olgusal hedef için
kullanılabilir: `mfe_pct >= T'` ise T' seviyesine **bir noktada** ulaşılmıştır.
ANCAK bu, "stop'tan ÖNCE ulaşıldı" demek DEĞİLDİR — MFE zamanlaması veride yok.

Bu yüzden iki SINIR hesaplanır (varsayım uydurmak yerine):

  * **alt sınır (garanti)**: `touched_target=True` VE `T' <= target_pct`
    → gerçek (daha büyük) hedefe stop'tan önce ulaşılmış; küçük hedefe de
    kesinlikle ulaşılmıştır.
  * **üst sınır**: `mfe_pct >= T'` (sıralama bilinmiyor; iyimser).

Gerçek değer bu ikisinin arasındadır. **Üst sınır bile negatifse** karar kesin:
hedef seçimi bunu kurtaramaz. **Alt sınır pozitifse** karar kesin: kazanç var.

VARYANTLAR
----------
  mevcut      : gerçekleşen `net_pct` (bugünkü tasarım)
  sabit T'    : tüm adaylara aynı hedef (0.5% … 3.0% ızgarası)
  ATR×k       : hedef = k × atr_pct (olasılıktan BAĞIMSIZ — ayrıştırılmış)
  olasılıklı  : mevcut tasarım (karşılaştırma tabanı)

KARAR ÖLÇÜTLERİ
---------------
  * hedefe değme oranının **olasılık dilimlerinde tekdüzeliği** (asıl hipotez)
  * EV (stop ve maliyet ölçülen değerlerden)
  * bootstrap %95 GA (varyant − mevcut)
  * ilk yarı / ikinci yarı kararlılığı (aşırı uyum kokusu)

KULLANIM
--------
    python -m scripts.backtest_target_decoupling --days 180
    ... --grid 0.5,1.0,1.5,2.0,2.5,3.0 --atr-mult 4,6,8 --boot 2000
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SL_PCT = 1.50        # veriden: STOPPED_OUT exit_pct ortalaması = -1.500
COST_PP = 0.35       # veriden: |net| - |exit| ≈ 0.35 puan (fee+kayma+spread)


async def _fetch(days: int) -> list[dict]:
    import asyncpg

    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL gerekli")
    cutoff = (time.time() - days * 86400) if days > 0 else None
    sql = """
        SELECT ml_hit_probability AS p, velocity_score AS v, target_pct AS t,
               atr_pct AS atr, mfe_pct AS mfe, touched_target AS hit,
               net_pct AS net, exit_pct AS ex,
               outcome_details->>'status_reason' AS why,
               created_at AS ts
          FROM velocity_candidates
         WHERE mfe_pct IS NOT NULL AND target_pct IS NOT NULL
           AND ml_hit_probability IS NOT NULL AND net_pct IS NOT NULL
           AND ($1::double precision IS NULL OR evaluated_at >= $1)
         ORDER BY created_at ASC
    """
    conn = await asyncpg.connect(url)
    try:
        return [dict(r) for r in await conn.fetch(sql, cutoff)]
    finally:
        await conn.close()


def _ev(p: float, target_pct: float, sl_pct: float = SL_PCT, cost: float = COST_PP) -> float:
    """Beklenen değer (puan): kazanç +T-cost, kayıp -SL-cost."""
    return p * (target_pct - cost) + (1.0 - p) * (-sl_pct - cost)


def _mono(hit_by_q: list[float]) -> dict:
    """Dilim isabet oranları tekdüze ARTAN mı? (hipotez: artmalı)"""
    arr = np.asarray(hit_by_q, dtype=float)
    if arr.size < 3:
        return {"monotonic_up": False, "spearman": None}
    ranks_q = np.arange(1, arr.size + 1, dtype=float)
    sq = np.argsort(np.argsort(ranks_q)).astype(float)
    sa = np.argsort(np.argsort(arr)).astype(float)
    rho = float(np.corrcoef(sq, sa)[0, 1]) if arr.std() > 0 else 0.0
    return {"monotonic_up": bool(np.all(np.diff(arr) >= 0)),
            "spearman": round(rho, 3)}


def _quintile_rates(p: np.ndarray, win_mask: np.ndarray, q: int = 5) -> list[float]:
    order = np.argsort(p, kind="mergesort")
    n = p.size
    out = []
    for i in range(q):
        lo, hi = int(i * n / q), int((i + 1) * n / q)
        idx = order[lo:hi]
        out.append(float(win_mask[idx].mean()) if idx.size else 0.0)
    return out


def _fmt_pct(x: float) -> str:
    return f"{x:+.3f}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Hedef-olasılık ayrıştırma backtesti")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--grid", default="0.5,1.0,1.5,2.0,2.5,3.0",
                    help="sabit hedef ızgarası (%)")
    ap.add_argument("--atr-mult", default="4,6,8", help="ATR çarpanları")
    ap.add_argument("--boot", type=int, default=2000, help="bootstrap tekrarı")
    ap.add_argument("--sl", type=float, default=SL_PCT)
    ap.add_argument("--cost", type=float, default=COST_PP)
    args = ap.parse_args(argv)

    rows = asyncio.run(_fetch(args.days))
    if len(rows) < 500:
        print(f"Yetersiz veri: {len(rows)} aday (min 500).")
        return 1

    p = np.array([r["p"] for r in rows], dtype=float)
    t = np.array([r["t"] for r in rows], dtype=float)
    atr = np.array([r["atr"] if r["atr"] is not None else np.nan for r in rows], dtype=float)
    mfe = np.array([r["mfe"] for r in rows], dtype=float)
    hit = np.array([bool(r["hit"]) for r in rows], dtype=bool)
    net = np.array([r["net"] for r in rows], dtype=float)
    ts = np.array([float(r["ts"]) for r in rows], dtype=float)
    n = p.size

    print("=" * 96)
    print(f"HEDEF-OLASILIK AYRIŞTIRMA BACKTESTİ · n={n:,} aday · son {args.days} gün")
    print(f"ölçülen sabitler: stop={args.sl:.2f}%  maliyet={args.cost:.2f} puan  "
          f"(bunlar VERİDEN, varsayım değil)")
    print("=" * 96)

    # --- 0) MEVCUT TASARIM ---
    base_ev = float(net.mean())
    hit_rate = float(hit.mean())
    print(f"\n[0] MEVCUT TASARIM")
    print(f"    hedef ort={t.mean():.3f}%  isabet={hit_rate:.3f}  taban EV={_fmt_pct(base_ev)} puan")
    print(f"    -> break-even için gereken isabet (T={t.mean():.2f}): "
          f"{(-args.sl - args.cost) / (t.mean() - args.cost - (-args.sl - args.cost)) * -1:.3f}")
    be = (args.sl + args.cost) / (t.mean() - args.cost + args.sl + args.cost)
    print(f"    -> GERÇEK break-even isabet = {be:.3f}  (mevcut {hit_rate:.3f})")
    print(f"    olasılık dilimlerinde isabet: "
          f"{[round(x, 3) for x in _quintile_rates(p, hit)]}  {_mono(_quintile_rates(p, hit))}")

    # --- 1) SABİT HEDEF IZGARASI ---
    grid = [float(x) for x in args.grid.split(",") if x.strip()]
    print(f"\n[1] SABİT HEDEF — alt sınır 'guaranteed', üst sınır 'MFE>=T' (iyimser)")
    print(f"    {'T%':>6}{'isabet_alt':>12}{'isabet_üst':>12}{'EV_alt':>10}{'EV_üst':>10}"
          f"{'BE isabet':>11}  tekdüze(alt/üst)")
    results = []
    for tp in grid:
        # alt sınır: gerçek hedefe ulaşmış VE küçültülmüş hedef gerçek hedeften küçük/eşit
        low = hit & (tp <= t)
        high = mfe >= tp
        p_low, p_high = float(low.mean()), float(high.mean())
        ev_low, ev_high = _ev(p_low, tp, args.sl, args.cost), _ev(p_high, tp, args.sl, args.cost)
        mono_low = _mono(_quintile_rates(p, low))
        mono_high = _mono(_quintile_rates(p, high))
        be_t = (args.sl + args.cost) / (tp - args.cost + args.sl + args.cost)
        results.append({"target": tp, "p_low": p_low, "p_high": p_high,
                        "ev_low": ev_low, "ev_high": ev_high, "be": be_t,
                        "mono_low": mono_low, "mono_high": mono_high})
        print(f"    {tp:>6.2f}{p_low:>12.3f}{p_high:>12.3f}{ev_low:>+10.3f}{ev_high:>+10.3f}"
              f"{be_t:>11.3f}  {str(mono_low['monotonic_up']):>6}/{str(mono_high['monotonic_up'])}")

    # --- 2) ATR TABANLI (olasılıktan BAĞIMSIZ) ---
    mults = [float(x) for x in args.atr_mult.split(",") if x.strip()]
    print(f"\n[2] ATR TABANLI HEDEF (olasılıktan BAĞIMSIZ — 'ayrıştırılmış')")
    print(f"    {'k×ATR':>7}{'hedef ort%':>12}{'isabet_üst':>12}{'EV_üst':>10}{'BE isabet':>11}")
    atr_results = []
    valid_atr = np.isfinite(atr) & (atr > 0)
    for k in mults:
        tp_arr = k * np.where(valid_atr, atr, np.nan)
        m = np.isfinite(tp_arr) & (tp_arr > 0.05)
        if m.sum() < 100:
            print(f"    {k:>7.1f}   yetersiz geçerli ATR ({int(m.sum())})")
            continue
        high = (mfe >= tp_arr)[m]
        p_high = float(high.mean())
        tp_mean = float(np.nanmean(tp_arr[m]))
        ev_high = _ev(p_high, tp_mean, args.sl, args.cost)
        be_t = (args.sl + args.cost) / (tp_mean - args.cost + args.sl + args.cost)
        atr_results.append({"k": k, "target_mean": tp_mean, "p_high": p_high,
                            "ev_high": ev_high, "be": be_t})
        print(f"    {k:>7.1f}{tp_mean:>12.3f}{p_high:>12.3f}{ev_high:>+10.3f}{be_t:>11.3f}")

    # --- 3) BOOTSTRAP: en iyi sabit hedef vs mevcut ---
    if results:
        best = max(results, key=lambda r: r["ev_high"])
        rng = np.random.default_rng(7)
        idx = np.arange(n)
        diffs = np.empty(args.boot)
        for b in range(args.boot):
            s = rng.choice(idx, size=n, replace=True)
            tp = best["target"]
            w = (mfe[s] >= tp)
            ev_v = _ev(float(w.mean()), tp, args.sl, args.cost)
            diffs[b] = ev_v - float(net[s].mean())
        lo, hi = np.percentile(diffs, [2.5, 97.5])
        print(f"\n[3] BOOTSTRAP — en iyi sabit hedef T={best['target']:.2f}% vs MEVCUT "
              f"({args.boot} tekrar)")
        print(f"    ΔEV = {best['ev_high'] - base_ev:+.3f} puan  ·  %95 GA = [{lo:+.3f}, {hi:+.3f}]")
        print(f"    -> {'ANLAMLI (GA sıfırı içermiyor)' if lo > 0 or hi < 0 else 'ANLAMSIZ (GA sıfırı içeriyor)'}")

    # --- 4) KARARLILIK: ilk yarı / ikinci yarı ---
    if n > 1000:
        cut = np.median(ts)
        first, second = ts <= cut, ts > cut
        print(f"\n[4] KARARLILIK (zaman yarıları) — aşırı uyum kokusu")
        print(f"    {'varyant':<18}{'EV 1.yarı':>12}{'EV 2.yarı':>12}  tutarlı")
        for r in results:
            tp = r["target"]
            evs = []
            for m in (first, second):
                w = (mfe[m] >= tp)
                evs.append(_ev(float(w.mean()), tp, args.sl, args.cost))
            ok = (evs[0] > base_ev and evs[1] > base_ev)
            print(f"    T={tp:<16.2f}{evs[0]:>+12.3f}{evs[1]:>+12.3f}  {ok}")
        base_halves = [float(net[first].mean()), float(net[second].mean())]
        print(f"    {'MEVCUT':<18}{base_halves[0]:>+12.3f}{base_halves[1]:>+12.3f}")

    # --- HÜKÜM ---
    print("\n" + "=" * 96)
    print("HÜKÜM")
    print("=" * 96)
    any_low_positive = [r for r in results if r["ev_low"] > 0]
    any_high_positive = [r for r in results if r["ev_high"] > 0]
    if any_low_positive:
        print(f"  KESİN KAZANÇ: alt sınırda bile pozitif EV → "
              f"T={[r['target'] for r in any_low_positive]}")
    elif any_high_positive:
        print(f"  ÜST SINIRDA pozitif: T={[r['target'] for r in any_high_positive]} "
              f"— sıralama belirsizliği nedeniyle KESİN DEĞİL, ölçüm gerekir")
    else:
        print("  HEDEF SEÇİMİ KURTARMIYOR: üst sınırda (iyimser) bile EV negatif.")
        print("  Sebep maliyet+stop yapısı: EV = p·(T−c) − (1−p)·(SL+c) ve break-even")
        print("  isabet oranları ulaşılan hiçbir T'de yakalanmıyor.")
    print()
    print(f"  Mevcut taban EV = {base_ev:+.3f} puan · stop={args.sl:.2f}% · maliyet={args.cost:.2f} puan")
    print(f"  Maliyetin risk birimine oranı = {args.cost / args.sl * 100:.1f}%  "
          f"(maliyet düşürme, hedef oynamaktan daha büyük kaldıraç olabilir)")
    print("\n  SINIR: `mfe_pct` sıralama bilgisi taşımaz; gerçek değer [alt, üst]")
    print("  aralığındadır. Canlı doğrulama için: yeni hedefle yeniden değerlendirme.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
