"""Portföy/işlem analitiği: saf fonksiyonlar (araştırma raporu: kartlar 1.7, 2.5, 2.8, 3.8, 3.9).

- cell_stats (2.5): strateji × sembol × seans hücrelerinde Beta-Binomial büzülmüş kazanma oranı ve ALT SINIR (nokta tahmin değil).
- strategy_allocation (3.8): yavaş, sınırlı, büzülmüş risk ağırlığı ÖNERİSİ (uygulanmaz; eşit-risk tabanına karşı gölgede ölçülür).
- effective_bets (3.9): işaretli getiri korelasyonundan etkin bahis sayısı (ENB) ve korelasyon kümeleri.
- simulate_exit_variants / compare_variants (1.7): kaydedilmiş fiyat yolunda alternatif çıkış kuralları (BE@1R, kısmi kâr, trailing) A/B.
- entry_features (2.8): meta-etiketleme veri seti için deterministik confluence özellikleri ve sert-veto bayrakları (HİPOTEZ olarak loglanır).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.portfolio_risk import shrunk_win_rate_lower

MIN_CELL_N = 30
PRIOR_M = 30.0


def session_of(ts: Optional[float]) -> str:
    """UTC saatine göre seans: asya (0-7), londra (7-12), ny (12-20), gece (20-24)."""
    if ts is None:
        return "bilinmiyor"
    h = datetime.fromtimestamp(float(ts), timezone.utc).hour
    return "asya" if h < 7 else "londra" if h < 12 else "ny" if h < 20 else "gece"


def _r(row: Dict[str, Any]) -> Optional[float]:
    try:
        sl = float(row.get("sl_pips") or 0)
        return float(row["last_pnl_pips"]) / sl if sl > 0 else None
    except (KeyError, TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- 2.5 hücre bazlı kenar

def cell_stats(rows: List[Dict[str, Any]], prior_m: float = PRIOR_M, min_n: int = MIN_CELL_N) -> Dict[str, Any]:
    """Kapanmış pozisyonlardan hücre başına büzülmüş kazanma oranı + alt sınır + büzülmüş ortalama R.

    Hücre = (strateji_etiketi, sembol, seans). n < min_n hücreler raporlanmaz (sahte keşif/çoklu dilimleme uyarısı).
    Büzülme: p = (kazanç + m·p_havuz)/(n + m); ortalama R de havuz ortalamasına çekilir. Geçit olarak p_lower kullanılır.
    """
    closed = [r for r in rows if r.get("closed_at") and r.get("last_pnl_pips") is not None and _r(r) is not None]
    out: Dict[str, Any] = {"n_total": len(closed), "min_n": min_n, "cells": [], "n_cells_total": 0}
    if not closed:
        return out
    pool_p = sum(1 for r in closed if float(r["last_pnl_pips"]) > 0) / len(closed)
    pool_r = sum(_r(r) for r in closed) / len(closed)
    cells: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for r in closed:
        key = (str(r.get("strategy_tag") or "?"), str(r.get("symbol") or "?"), session_of(r.get("open_ts")))
        cells.setdefault(key, []).append(r)
    out["n_cells_total"] = len(cells)
    for (strat, sym, sess), rs in cells.items():
        n = len(rs)
        wins = sum(1 for r in rs if float(r["last_pnl_pips"]) > 0)
        mean_r = sum(_r(r) for r in rs) / n
        rec = {"strategy": strat, "symbol": sym, "session": sess, "n": n, "wins": wins, "p_raw": round(wins / n, 3),
               "p_shrunk": round((wins + prior_m * pool_p) / (n + prior_m), 3),
               "p_lower": round(shrunk_win_rate_lower(wins, n, prior_p=pool_p, m=prior_m), 3),
               "mean_r_shrunk": round((n * mean_r + prior_m * pool_r) / (n + prior_m), 3), "reportable": n >= min_n}
        if rec["reportable"]:
            out["cells"].append(rec)
    out["cells"].sort(key=lambda c: c["p_lower"], reverse=True)
    out["pool"] = {"p": round(pool_p, 3), "mean_r": round(pool_r, 3)}
    out["note"] = (f"{out['n_cells_total']} hücreden {len(out['cells'])} tanesi n≥{min_n}. Çoklu dilimleme sahte keşif üretir: "
                   "yalnızca önceden kayıtlı bu üç boyut kullanılır; alt sınır > havuz oranı değilse hücre 'kanıtlı' sayılmaz.")
    return out


def cell_lookup(stats: Dict[str, Any], strategy: str, symbol: str, ts: Optional[float]) -> Optional[Dict[str, Any]]:
    sess = session_of(ts)
    for c in stats.get("cells", []):
        if c["strategy"] == strategy and c["symbol"] == symbol and c["session"] == sess:
            return c
    return None


# --------------------------------------------------------------------------- 3.8 strateji bazlı risk tahsisi (öneri)

def strategy_allocation(rows: List[Dict[str, Any]], half_life: float = 40.0, floor: float = 0.5, cap: float = 1.5,
                        shrink_m: float = 10.0) -> Dict[str, Any]:
    """Azalan ağırlıklı, sıfıra büzülmüş beklentiden ağırlık önerisi; eşit-risk tabanıyla %50/50 karışım, [floor, cap] sınırlı.

    n_eff < 30 olan stratejiye ağırlık > 1 verilmez; kalıcı kapatma yoktur (taban 0.5). ÖNERİDİR, uygulanmaz.
    """
    by: Dict[str, List[Tuple[float, float]]] = {}
    for r in rows:
        if not r.get("closed_at") or _r(r) is None:
            continue
        by.setdefault(str(r.get("strategy_tag") or "?"), []).append((float(r["closed_at"]), _r(r)))
    stats: Dict[str, Dict[str, float]] = {}
    for strat, items in by.items():
        items.sort(key=lambda x: x[0], reverse=True)                      # en yeni önce
        w = [0.5 ** (i / half_life) for i in range(len(items))]
        sw = sum(w)
        e = sum(wi * ri for wi, (_t, ri) in zip(w, items)) / (sw + shrink_m)
        mean_all = sum(ri for _t, ri in items) / len(items)
        sd = (sum((ri - mean_all) ** 2 for _t, ri in items) / max(1, len(items) - 1)) ** 0.5 if len(items) >= 5 else 1.0
        n_eff = sw ** 2 / sum(wi ** 2 for wi in w)
        stats[strat] = {"n": len(items), "n_eff": n_eff, "expectancy_r": e, "sd_r": sd or 1.0, "score": max(0.0, e / (sd or 1.0))}
    if not stats:
        return {"strategies": [], "note": "Kapanmış işlem yok"}
    mean_score = sum(s["score"] for s in stats.values()) / len(stats)
    out = []
    for strat, s in sorted(stats.items(), key=lambda kv: -kv[1]["score"]):
        rel = (s["score"] / mean_score) if mean_score > 0 else 1.0
        weight = max(floor, min(cap, 0.5 * 1.0 + 0.5 * rel))
        capped = s["n_eff"] < 30 and weight > 1.0
        if capped:
            weight = 1.0
        out.append({"strategy": strat, "n": s["n"], "n_eff": round(s["n_eff"], 1), "expectancy_r": round(s["expectancy_r"], 3),
                    "suggested_weight": round(weight, 2), "capped_by_sample": capped})
    return {"strategies": out, "note": "Öneri: uygulanmaz. Dinamik tahsis, eşit-risk tabanına karşı gölgede ölçülmeden açılmamalı."}


# --------------------------------------------------------------------------- 3.9 etkin bahis sayısı (ENB) ve kümeler

def effective_bets(returns_by_symbol: Dict[str, List[float]], signs: Dict[str, float], cluster_rho: float = 0.7) -> Dict[str, Any]:
    """İşaretli (yön × getiri) korelasyon: aynı yönde korele pozisyonlar pozitif. ENB = exp(özdeğer entropisi).

    ENB < 0.5 × pozisyon sayısı → "tek tema" uyarısı. PCA-ENB tek başına güvenilmez; kümeler (ρ > cluster_rho) ayrıca verilir.
    """
    import numpy as np
    syms = [s for s, v in returns_by_symbol.items() if len(v) >= 20]
    n = len(syms)
    if n < 2:
        return {"n": n, "enb": float(n), "avg_abs_corr": 0.0, "clusters": [], "warning": False,
                "note": "En az 2 pozisyon ve 20+ getiri gerekir"}
    length = min(len(returns_by_symbol[s]) for s in syms)
    mat = np.array([[signs.get(s, 1.0) * x for x in returns_by_symbol[s][-length:]] for s in syms], dtype=float)
    corr = np.corrcoef(mat)
    corr = np.nan_to_num(corr, nan=0.0)
    eig = np.clip(np.linalg.eigvalsh(corr), 1e-12, None)
    p = eig / eig.sum()
    enb = float(np.exp(-np.sum(p * np.log(p))))
    iu = np.triu_indices(n, 1)
    avg_abs = float(np.mean(np.abs(corr[iu])))
    avg_signed = float(np.mean(corr[iu]))          # >0: aynı yönde yığılma · <0: hedge (özdeğer entropisi işaretten bağımsızdır)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, j in zip(*iu):
        if corr[i, j] > cluster_rho:
            parent[find(int(i))] = find(int(j))
    groups: Dict[int, List[str]] = {}
    for i, s in enumerate(syms):
        groups.setdefault(find(i), []).append(s)
    clusters = [sorted(g) for g in groups.values() if len(g) > 1]
    return {"n": n, "enb": round(enb, 2), "avg_abs_corr": round(avg_abs, 3), "avg_signed_corr": round(avg_signed, 3), "clusters": clusters,
            "warning": bool(n >= 3 and enb < 0.5 * n),
            "note": "ENB düşükse pozisyonlar aslında tek bahis gibi davranır (aynı yönde yığılma)."}


# --------------------------------------------------------------------------- 1.7 çıkış varyantları (A/B, kayıtlı yolda)

def simulate_exit_variants(path: List[float], sl_pips: float, tp_pips: float) -> Dict[str, float]:
    """Yön-ayarlı pip yolu (giriş=0) üzerinde dört çıkış kuralının sonucu (pip). Yol örneklemlidir (≈20 sn): yaklaşıktır.

    baseline: sabit SL/TP · be_1r: +1R'de stop girişe · partial_1r: +1R'de yarısı kapanır, kalan BE'ye + TP ·
    trail_1r: +1R'den sonra stop = en iyi − 1R (TP yine geçerli).
    """
    sl = abs(sl_pips)
    tp = tp_pips if tp_pips and tp_pips > 0 else float("inf")
    if sl <= 0 or not path:
        return {}

    def run(variant: str) -> float:
        stop, best, partial_done, locked = -sl, 0.0, False, 0.0
        for x in path:
            best = max(best, x)
            if variant in ("be_1r", "partial_1r") and best >= sl:
                stop = max(stop, 0.0)
                if variant == "partial_1r" and not partial_done:
                    partial_done, locked = True, 0.5 * sl
            if variant == "trail_1r" and best >= sl:
                stop = max(stop, best - sl)
            if x >= tp:
                res = tp
                return locked + 0.5 * res if variant == "partial_1r" and partial_done else res
            if x <= stop:
                res = stop
                return locked + 0.5 * res if variant == "partial_1r" and partial_done else res
        res = path[-1]
        return locked + 0.5 * res if variant == "partial_1r" and partial_done else res

    return {v: round(run(v), 2) for v in ("baseline", "be_1r", "partial_1r", "trail_1r")}


def compare_variants(rows: List[Dict[str, Any]], min_n: int = 30) -> Dict[str, Any]:
    """Kayıtlı yolu olan kararlar için varyant ortalamaları. n < min_n → yalnızca bilgi (karar için yetersiz)."""
    import json
    acc: Dict[str, List[float]] = {}
    used = 0
    for r in rows:
        try:
            path = json.loads(r["path"]) if isinstance(r.get("path"), str) else (r.get("path") or [])
        except Exception:  # noqa: BLE001
            continue
        res = simulate_exit_variants([float(x) for x in path], float(r.get("sl_pips") or 0), float(r.get("tp_pips") or 0))
        if not res:
            continue
        used += 1
        for k, v in res.items():
            acc.setdefault(k, []).append(v)
    means = {k: round(sum(v) / len(v), 2) for k, v in acc.items()}
    base = means.get("baseline")
    return {"n": used, "means_pips": means, "vs_baseline": {k: round(v - base, 2) for k, v in means.items() if base is not None and k != "baseline"},
            "decisive": used >= min_n,
            "note": ("Örneklem yetersiz: yalnızca bilgi, varsayılan çıkış değiştirilmez" if used < min_n else
                     "Fark, standart hata/çoklu test düzeltmesiyle sınanmadan uygulanmamalı; yol örneklemi 20 sn'dir (yaklaşık).")}


# --------------------------------------------------------------------------- 2.8 confluence özellikleri (meta-etiket veri seti)

def entry_features(direction: str, analysis: Dict[str, Any], spread_pips: float, pip_size: float, news_minutes: Optional[float],
                   now: float) -> Dict[str, Any]:
    """Giriş anının deterministik özellikleri + sert-veto BAYRAKLARI (kural değil, test edilecek hipotez olarak loglanır)."""
    d = 1.0 if str(direction).upper() == "BUY" else -1.0
    frames = analysis.get("frames") or {}
    price = float(analysis.get("price") or 0)
    atr1h = float((frames.get("1h") or {}).get("atr") or analysis.get("atr") or 0)
    agree = sum(1 for tf in ("15m", "1h", "4h", "1d") if tf in frames and frames[tf].get("score", 0) * d > 0)
    lv = analysis.get("levels") or {}
    opp = (lv.get("resistances") if d > 0 else lv.get("supports")) or []
    clearance = (abs(float(opp[0]["price"]) - price) / atr1h) if opp and atr1h > 0 else None
    ema20 = (frames.get("1h") or {}).get("ema20")
    extension = (abs(price - float(ema20)) / atr1h) if ema20 and atr1h > 0 else None
    spread_atr = (spread_pips * pip_size / atr1h) if atr1h > 0 and pip_size > 0 else None
    f = {"session": session_of(now), "htf_agree_count": agree, "htf_frames": len(frames),
         "level_clearance_atr": round(clearance, 2) if clearance is not None else None,
         "extension_atr": round(extension, 2) if extension is not None else None,
         "spread_atr_ratio": round(spread_atr, 3) if spread_atr is not None else None,
         "news_minutes": news_minutes, "ta_bias": analysis.get("bias"), "ta_score": analysis.get("score")}
    flags = []
    if extension is not None and extension > 3.0:
        flags.append("asiri_uzama_3atr")
    if clearance is not None and clearance < 0.5:
        flags.append("karsi_seviye_0.5atr")
    if agree <= 1 and len(frames) >= 3:
        flags.append("ust_dilim_uyumsuz")
    if spread_atr is not None and spread_atr > 0.15:
        flags.append("spread_atr_yuksek")
    if news_minutes is not None and news_minutes <= 15:
        flags.append("haber_15dk")
    f["hard_flags"] = flags
    return f
