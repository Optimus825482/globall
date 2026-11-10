#!/usr/bin/env python3
"""SEÇİCİLİK PROBU — "bu işlem lehte 0.5R'ye gider mi?" ÖNGÖRÜLEBİLİR Mİ? (2026-11-10)

NEDEN
-----
Ölçüm zinciri netleştirdi: (1) çıkış/hedef ayarı kanalları pozitife çevirmiyor
(P(MFE>=0.5R)=%31 vs başabaş %67), (2) basit özelliklerle (skor/stop/saat/yön) seçicilik
YOK (lojistik AUC 0.576). Bu betik üçüncü soruyu yanıtlar: **giriş ANINDA bilinen daha zengin
özelliklerle lehte hareketi öngörebilir miyiz?**

YÖNTEM (disiplin)
-----------------
* Etiket: **MFE>=0.5R** (lehte en iyi hareket / risk) — M1 barlarından, giriş-çıkış arası.
* Özellikler YALNIZ giriş anında bilinenlerden türetilir (look-ahead YOK): saat/gün, yön,
  kanal, skor, stop mesafesi, maliyet/stop oranı, son 30/60 dk momentum ve volatilite,
  önceki 60 dk içindeki konum.
* Ayrım **KRONOLOJİK**: ilk %70 eğitim, son %30 test (rastgele CV sızıntı üretir).
* **Permütasyon kontrolü:** etiketler karıştırılınca AUC 0.5'e düşmeli.
* Karar metriği AUC değil **ekonomi**: eşik üstünde kalan işlemlerin P(MFE>=0.5R) değeri
  başabaş eğrisinin üstüne çıkıyor mu + kapsam (kaç işlem kalıyor).

Kullanim:
    python scripts/fx_selectivity_probe.py --days 60 --json outputs/selectivity.json
"""
from __future__ import annotations

import argparse
import bisect
import collections
import datetime as dt
import json
import os
import statistics
import sys

import numpy as np

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 yok — Python 3.12'yi tam yolla cagirin.")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def vpu(sym: str, vol: float) -> float:
    i = mt5.symbol_info(sym)
    if i is None or not i.trade_tick_size or not i.trade_tick_value:
        return 0.0
    return (float(i.trade_tick_value) / float(i.trade_tick_size)) * float(vol)


def load_trades(days: int) -> list[dict]:
    deals = mt5.history_deals_get(dt.datetime.now() - dt.timedelta(days=days), dt.datetime.now())
    if deals is None:
        return []
    pos: dict[int, dict] = {}
    for d in deals:
        if d.entry == 0:
            pos[d.position_id] = {"pid": d.position_id, "sym": d.symbol, "open": d.price,
                                  "cm": str(d.comment or "").strip(), "t": d.time,
                                  "dir": "BUY" if d.type == 0 else "SELL", "vol": 0.0}
        else:
            p = pos.get(d.position_id)
            if p is None:
                continue
            p["vol"] += d.volume
            p["ct"] = d.time
    return [p for p in pos.values() if "ct" in p and p["vol"] > 0]


def channel_of(cm: str) -> str:
    parts = cm.split()
    return " ".join(parts[:-1]) if parts and parts[-1].lstrip("-").isdigit() else (cm or "?")


def m1_window(sym: str, t0: float, t1: float) -> list[tuple]:
    r = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1,
                             dt.datetime.fromtimestamp(t0 - 7200, dt.timezone.utc),
                             dt.datetime.fromtimestamp(t1 + 600, dt.timezone.utc))
    if r is None:
        return []
    return [(int(x["time"]), float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]))
            for x in r]


def features_for(t: dict, bars: list[tuple], keys: list[int], spread_pips: float) -> dict | None:
    """Giriş anında bilinen özellikler (look-ahead yok)."""
    i = bisect.bisect_right(keys, t["t"]) - 1
    if i < 65:
        return None
    info = mt5.symbol_info(t["sym"])
    if info is None:
        return None
    pip = float(info.point) * (10.0 if info.digits in (3, 5) else 1.0)
    win = bars[i - 60:i + 1]
    closes = [b[4] for b in win]
    highs = [b[2] for b in win]
    lows = [b[3] for b in win]
    rets = [(closes[j] - closes[j - 1]) / pip for j in range(1, len(closes))]
    vol60 = statistics.pstdev(rets) or 1e-9
    mom30 = (closes[-1] - closes[-31]) / pip / vol60 if len(closes) > 31 else 0.0
    mom60 = (closes[-1] - closes[0]) / pip / vol60
    hi, lo = max(highs), min(lows)
    pos_in_range = ((closes[-1] - lo) / (hi - lo)) if hi > lo else 0.5
    hour = dt.datetime.fromtimestamp(t["t"], dt.timezone.utc).hour
    return {"hour_sin": np.sin(2 * np.pi * hour / 24), "hour_cos": np.cos(2 * np.pi * hour / 24),
            "dow": dt.datetime.fromtimestamp(t["t"], dt.timezone.utc).weekday(),
            "dir": 1.0 if t["dir"] == "BUY" else 0.0, "score": float(t.get("score", -1) or -1),
            "vol60_pips": vol60, "mom30": mom30, "mom60": mom60, "pos_in_range": pos_in_range,
            "spread_pips": spread_pips}


def main() -> int:
    ap = argparse.ArgumentParser(description="MFE etiketli seçicilik probu (kronolojik OOS)")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--threshold-r", type=float, default=0.5, help="etiket eşiği: MFE >= bu R")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if not mt5.initialize():
        print(f"[HATA] MT5 initialize basarisiz: {mt5.last_error()}")
        return 2
    trades = load_trades(args.days)
    if not trades:
        print("Kapanmış işlem yok.")
        return 1

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    cache: dict[tuple, list[tuple]] = {}
    spread_cache: dict[str, float] = {}
    rows: list[dict] = []
    skipped = collections.Counter()
    for t in trades:
        o = mt5.history_orders_get(position=t["pid"])
        sls = [float(x.sl) for x in (o or []) if float(getattr(x, "sl", 0) or 0) > 0]
        tps = [float(x.tp) for x in (o or []) if float(getattr(x, "tp", 0) or 0) > 0]
        if not sls:
            skipped["sl_yok"] += 1
            continue
        i = mt5.symbol_info(t["sym"])
        pip = float(i.point) * (10.0 if i.digits in (3, 5) else 1.0)
        risk_price = abs(t["open"] - sls[-1])
        risk = risk_price * vpu(t["sym"], t["vol"])
        if risk <= 0:
            skipped["risk_yok"] += 1
            continue
        k = (t["sym"], int(t["t"] // 1800))
        if k not in cache:
            cache[k] = m1_window(t["sym"], t["t"], t["ct"])
        bars = cache[k]
        if not bars:
            skipped["bar_yok"] += 1
            continue
        keys = [b[0] for b in bars]
        if t["sym"] not in spread_cache:
            info = mt5.symbol_info(t["sym"])
            spread_cache[t["sym"]] = (float(info.spread) * float(info.point) / pip) if pip else 1.0
        feat = features_for({"sym": t["sym"], "t": t["t"], "dir": t["dir"],
                             "score": int(t["cm"].split()[-1]) if t["cm"].split()[-1].lstrip("-").isdigit() else -1},
                            bars, keys, spread_cache[t["sym"]])
        if feat is None:
            skipped["ozellik_yok"] += 1
            continue
        mfe = 0.0
        for ts, _o, hi, lo, _c in bars:
            if ts < t["t"] or ts > t["ct"]:
                continue
            fav = (hi - t["open"]) if t["dir"] == "BUY" else (t["open"] - lo)
            mfe = max(mfe, fav * vpu(t["sym"], t["vol"]) / risk)
        feat.update({"ch": channel_of(t["cm"]), "sym": t["sym"], "t": t["t"], "mfe": mfe,
                     "label": 1 if mfe >= args.threshold_r else 0,
                     "stop_pips": risk_price / pip, "cost_R": (spread_cache[t["sym"]] / (risk_price / pip)) if risk_price else 0.0,
                     "tgt_R": (abs(tps[-1] - t["open"]) / risk_price) if tps else 0.0})
        rows.append(feat)

    rows.sort(key=lambda r: r["t"])
    n = len(rows)
    base = sum(r["label"] for r in rows) / n
    print(f"örneklem: {n} işlem | etiket MFE>={args.threshold_r}R | taban oran %{100 * base:.1f} | "
          f"atlanan {dict(skipped)}")
    by_ch: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        by_ch[r["ch"]].append(r)
    print("kanal bazında taban oran: " + " · ".join(
        f"{k} n={len(v)} %{100 * sum(x['label'] for x in v) / len(v):.0f}"
        for k, v in sorted(by_ch.items(), key=lambda kv: -len(kv[1]))[:6]))
    ch_counts = collections.defaultdict(int)
    for r in rows:
        ch_counts[r["ch"]] += 1

    feats = ["hour_sin", "hour_cos", "dow", "dir", "score", "vol60_pips", "mom30", "mom60",
             "pos_in_range", "spread_pips", "cost_R", "stop_pips"]
    X = np.array([[r[f] for f in feats] for r in rows], dtype=float)
    y = np.array([r["label"] for r in rows])
    cut = int(n * 0.7)
    Xtr, ytr, Xte, yte = X[:cut], y[:cut], X[cut:], y[cut:]
    sc = StandardScaler().fit(Xtr)
    clf = LogisticRegression(max_iter=2000, C=0.5)
    clf.fit(sc.transform(Xtr), ytr)
    p_te = clf.predict_proba(sc.transform(Xte))[:, 1]
    auc_te = roc_auc_score(yte, p_te) if len(set(yte)) > 1 else float("nan")
    # permütasyon kontrolü (etiket karıştır)
    rng = np.random.default_rng(7)
    perm_aucs = []
    for _ in range(30):
        yp = rng.permutation(ytr)
        c2 = LogisticRegression(max_iter=1000, C=0.5).fit(sc.transform(Xtr), yp)
        perm_aucs.append(roc_auc_score(yte, c2.predict_proba(sc.transform(Xte))[:, 1]))
    print(f"\nKRONOLOJİK OOS: eğitim {cut} / test {n - cut} | AUC = {auc_te:.3f} "
          f"| permütasyon AUC = {statistics.mean(perm_aucs):.3f} (kontrol)")
    print(f"eğitim taban %{100 * ytr.mean():.1f} → test taban %{100 * yte.mean():.1f}")

    print("\nEŞİK EKONOMİSİ (test kümesi): kapsam + ulaşma olasılığı (başabaş: TP=R için 1/(1+TP))")
    print(f"{'eşik(p>=)':>10}{'kapsam':>9}{'P(MFE>=eşik)':>15}{'başabaş için TP':>17}{'yorum':>28}")
    for thr in (0.0, 0.2, 0.3, 0.4, 0.5):
        sel = p_te >= thr
        if sel.sum() < 10:
            continue
        p_hit = float(yte[sel].mean())
        cover = 100.0 * sel.sum() / len(yte)
        tgt_need = (1 - p_hit) / p_hit if p_hit > 0 else 99.0
        verdict = "KAPSAM TÜMÜ (referans)" if thr == 0 else (
            "kurtarıyor" if tgt_need < args.threshold_r * 0.9 else "yetmiyor")
        print(f"{thr:>10.1f}{cover:>8.0f}%{100 * p_hit:>14.1f}%{tgt_need:>17.2f}R{verdict:>28}")

    if args.json:
        p = args.json if os.path.isabs(args.json) else os.path.join(ROOT, args.json)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"n": n, "base_rate": base, "auc_oos": auc_te,
                       "perm_auc": statistics.mean(perm_aucs), "features": feats,
                       "coef": dict(zip(feats, [round(float(c), 4) for c in clf.coef_[0]])),
                       "rows": [{"ch": r["ch"], "sym": r["sym"], "mfe": round(r["mfe"], 3),
                                 "label": r["label"], "t": r["t"]} for r in rows]}, f,
                      ensure_ascii=False, indent=2)
        print(f"\nJSON: {p}")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
