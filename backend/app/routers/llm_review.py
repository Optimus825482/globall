"""LLM Trader inceleme kararlarının raporu (2026-10-30).

Kararlar `llm_trade_reviews` tablosunda; her biri için fiyat izlenir ("gölge sonuç": TP / SL / zaman
aşımı). Rapor, LLM'in kararlarının işe yarayıp yaramadığını bu gölge sonuçlarla ölçer:
  - Reddedilen işlem sonradan SL'e giderse → kaçınılan zarar (LLM haklı)
  - Reddedilen işlem TP'ye giderse → kaçırılan kazanç (LLM yanıldı)
  - Onaylanan işlemlerin gölge sonuçları → isabet oranı ve güven puanı kalibrasyonu
Gölge sonuç tahminidir (trailing/kısmi kâr/gerçek spread yok); gerçek P/L Raporlar'daki işlem
listesindedir.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from app import database

router = APIRouter(prefix="/api/llm-review", tags=["llm-review"])

CLOSED = ("TP", "SL", "ZAMAN_ASIMI")


def _mean_se(vals: List[float]) -> tuple:
    n = len(vals)
    if n == 0:
        return None, None, 0
    m = sum(vals) / n
    if n < 2:
        return m, None, n
    var = sum((v - m) ** 2 for v in vals) / (n - 1)
    return m, (var / n) ** 0.5, n


def auc_score(pairs: List[tuple]) -> Any:
    """Rank tabanlı AUC: pairs = [(skor, y∈{0,1})]. Tek sınıf varsa None."""
    pos = [s for s, y in pairs if y == 1]
    neg = [s for s, y in pairs if y == 0]
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for q in neg:
            wins += 1.0 if p > q else 0.5 if p == q else 0.0
    return round(wins / (len(pos) * len(neg)), 3)


def calibration_deep(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Güven puanı kalibrasyonu (araştırma kartı 2.3): Brier skill skoru, AUC, güvenilirlik tablosu, doygunluk uyarısı.

    p_kazanç: ONAY'da güven/100; RED'de 1 − güven/100 (red güveni "kaybeder" olasılığıdır). Sonuç y = gölge pip > 0.
    Geçersiz sayılan redler ve hata kayıtları dışlanır.
    """
    pts = []
    for r in rows:
        if r.get("applied") == "reject_voided" or r.get("decision") not in ("APPROVE", "REJECT"):
            continue
        if r.get("shadow_status") not in CLOSED or r.get("shadow_pips") is None or r.get("confidence") is None:
            continue
        c = max(0.0, min(1.0, float(r["confidence"]) / 100.0))
        pts.append((c if r["decision"] == "APPROVE" else 1.0 - c, 1 if float(r["shadow_pips"]) > 0 else 0, c))
    n = len(pts)
    out: Dict[str, Any] = {"n": n}
    if n < 10:
        out["note"] = "Yetersiz örneklem (<10): kalibrasyon hesaplanmadı"
        return out
    base = sum(y for _p, y, _c in pts) / n
    brier = sum((p - y) ** 2 for p, y, _c in pts) / n
    brier_base = sum((base - y) ** 2 for _p, y, _c in pts) / n
    bss = (1.0 - brier / brier_base) if brier_base > 0 else None
    bins: Dict[int, Dict[str, float]] = {}
    for p, y, _c in sorted(pts):
        b = bins.setdefault(min(4, int(p * 5)), {"n": 0, "p": 0.0, "y": 0.0})
        b["n"] += 1
        b["p"] += p
        b["y"] += y
    out.update(base_rate=round(base, 3), brier=round(brier, 4), brier_baseline=round(brier_base, 4),
               brier_skill=round(bss, 3) if bss is not None else None, auc=auc_score([(p, y) for p, y, _c in pts]),
               reliability=[{"bin": f"{k * 20}-{k * 20 + 20}%", "n": int(v["n"]), "predicted": round(v["p"] / v["n"], 3),
                             "observed": round(v["y"] / v["n"], 3)} for k, v in sorted(bins.items())])
    tens: Dict[int, int] = {}
    for _p, _y, c in pts:
        tens[int(c * 10)] = tens.get(int(c * 10), 0) + 1
    top = max(tens.values())
    out["saturated"] = top / n > 0.8
    out["usable"] = bool(bss is not None and bss > 0 and (out["auc"] or 0) > 0.55 and not out["saturated"] and n >= 30)
    out["note"] = ("Güven puanı işe yarıyor görünüyor" if out["usable"] else
                   "Çıktıların %80'inden fazlası tek bir güven kutusunda: özellik olarak işe yaramaz" if out["saturated"] else
                   "Güven puanı taban orana karşı kanıtlanmış değil (Brier skill ≤ 0 ya da AUC düşük ya da n<30)")
    return out


def veto_value(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """LLM vetosu rastgele vetodan iyi mi (kart 2.2)? Gölge pip ortalamaları: geçen − veto edilen, kontrol kolu ile kıyas."""
    def split(flag_fn):
        a, b = [], []
        for r in rows:
            if r.get("shadow_status") not in CLOSED or r.get("shadow_pips") is None or r.get("decision") not in ("APPROVE", "REJECT"):
                continue
            if r.get("applied") == "reject_voided":
                continue
            (a if flag_fn(r) else b).append(float(r["shadow_pips"]))
        return a, b

    llm_veto, llm_pass = split(lambda r: r.get("decision") == "REJECT")
    ctl_veto, ctl_pass = split(lambda r: bool(r.get("control_veto")))
    out: Dict[str, Any] = {}
    for key, (v, p) in (("llm", (llm_veto, llm_pass)), ("random_control", (ctl_veto, ctl_pass))):
        mv, sv, nv = _mean_se(v)
        mp, sp, np_ = _mean_se(p)
        edge = (mp - mv) if (mv is not None and mp is not None) else None
        se = ((sv or 0) ** 2 + (sp or 0) ** 2) ** 0.5 if (sv is not None and sp is not None) else None
        out[key] = {"vetoed_n": nv, "vetoed_mean_pips": round(mv, 2) if mv is not None else None, "passed_n": np_,
                    "passed_mean_pips": round(mp, 2) if mp is not None else None, "edge_pips": round(edge, 2) if edge is not None else None,
                    "se": round(se, 2) if se is not None else None}
    le, ce = out["llm"]["edge_pips"], out["random_control"]["edge_pips"]
    se = out["llm"]["se"]
    n_ok = out["llm"]["vetoed_n"] >= 15 and out["llm"]["passed_n"] >= 15
    if le is None or ce is None or se is None or not n_ok:
        out["verdict"] = "Yetersiz örneklem: her kolda en az 15 sonuçlanmış karar gerekir (güvenilir hüküm için 100+)"
    elif le - ce > 2 * se:
        out["verdict"] = "LLM vetosu rastgele vetodan anlamlı biçimde daha iyi görünüyor (yine de örneklem küçük olabilir)"
    else:
        out["verdict"] = "LLM vetosunun rastgele vetodan üstünlüğü kanıtlanmadı"
    explored = [r for r in rows if r.get("exploration") and r.get("shadow_status") in CLOSED and r.get("shadow_pips") is not None]
    em, _es, en = _mean_se([float(r["shadow_pips"]) for r in explored])
    out["exploration"] = {"n": en, "mean_pips": round(em, 2) if em is not None else None}
    return out


def fail_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """LLM zaman aşımı/hata oranı ve o işlemlerin sonuçları (fail-open yanlılığı, kart 2.1)."""
    total = len(rows)
    fails = [r for r in rows if r.get("applied") in ("fail_open", "fail_closed", "hata") or r.get("decision") == "HATA"]
    closed = [float(r["shadow_pips"]) for r in fails if r.get("shadow_status") in CLOSED and r.get("shadow_pips") is not None]
    normal = [float(r["shadow_pips"]) for r in rows if r not in fails and r.get("shadow_status") in CLOSED and r.get("shadow_pips") is not None]
    mf, _s, nf = _mean_se(closed)
    mn, _s2, nn = _mean_se(normal)
    rate = (len(fails) / total) if total else 0.0
    return {"fail_count": len(fails), "fail_rate": round(rate, 3), "fail_closed_n": nf, "fail_mean_pips": round(mf, 2) if mf is not None else None,
            "normal_closed_n": nn, "normal_mean_pips": round(mn, 2) if mn is not None else None,
            "alert": bool(total >= 10 and rate > 0.3),
            "note": ("LLM çağrılarının %30'undan fazlası başarısız: onay katmanı fiilen devre dışı; sağlayıcı/zaman aşımını düzeltin" if total >= 10 and rate > 0.3
                     else "Normal")}


def _bucket(conf: Any) -> str:
    try:
        c = int(conf)
    except (TypeError, ValueError):
        return "bilinmiyor"
    return "80+" if c >= 80 else "60-79" if c >= 60 else "<60"


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Saf fonksiyon: karar satırlarından rapor özeti (test edilebilir)."""
    out: Dict[str, Any] = {
        "total": len(rows), "approved": 0, "rejected": 0, "errors": 0, "blocked": 0, "tracking": 0,
        "approved_stats": {"closed": 0, "wins": 0, "tp": 0, "sl": 0, "net_pips": 0.0},
        "rejected_stats": {"closed": 0, "would_win": 0, "would_lose": 0, "avoided_pips": 0.0, "missed_pips": 0.0},
        "calibration": {}, "by_symbol": {}, "avg_latency_ms": 0,
    }
    lat: List[int] = []
    for r in rows:
        dec = r.get("decision")
        applied = r.get("applied")
        if r.get("latency_ms"):
            lat.append(int(r["latency_ms"]))
        if dec == "APPROVE":
            out["approved"] += 1
        elif dec == "REJECT":
            out["rejected"] += 1
        else:
            out["errors"] += 1
        if applied == "blocked":
            out["blocked"] += 1
        status = r.get("shadow_status")
        if status == "IZLENIYOR":
            out["tracking"] += 1
        if status not in CLOSED or r.get("shadow_pips") is None:
            continue
        pips = float(r["shadow_pips"])
        sym = out["by_symbol"].setdefault(r.get("symbol", "?"), {"approved": 0, "rejected": 0, "approved_net_pips": 0.0,
                                                                  "rejected_net_pips": 0.0})
        if dec == "APPROVE":
            st = out["approved_stats"]
            st["closed"] += 1
            st["net_pips"] = round(st["net_pips"] + pips, 1)
            st["wins"] += 1 if pips > 0 else 0
            st["tp"] += 1 if status == "TP" else 0
            st["sl"] += 1 if status == "SL" else 0
            sym["approved"] += 1
            sym["approved_net_pips"] = round(sym["approved_net_pips"] + pips, 1)
            if applied != "reject_voided":        # nötr güven (50) kalibrasyonu bozmasın
                b = out["calibration"].setdefault(_bucket(r.get("confidence")), {"closed": 0, "wins": 0})
                b["closed"] += 1
                b["wins"] += 1 if pips > 0 else 0
        elif dec == "REJECT":
            st = out["rejected_stats"]
            st["closed"] += 1
            sym["rejected"] += 1
            sym["rejected_net_pips"] = round(sym["rejected_net_pips"] + pips, 1)
            if pips < 0:
                st["would_lose"] += 1
                st["avoided_pips"] = round(st["avoided_pips"] + (-pips), 1)
            else:
                st["would_win"] += 1
                st["missed_pips"] = round(st["missed_pips"] + pips, 1)
    a, rj = out["approved_stats"], out["rejected_stats"]
    a["win_rate"] = round(100.0 * a["wins"] / a["closed"], 1) if a["closed"] else None
    rj["correct_rate"] = round(100.0 * rj["would_lose"] / rj["closed"], 1) if rj["closed"] else None
    # LLM'in net katkısı (pip): reddettiklerinin kaçınılan zararı − kaçırdığı kazanç
    out["net_value_pips"] = round(rj["avoided_pips"] - rj["missed_pips"], 1)
    out["avg_latency_ms"] = int(sum(lat) / len(lat)) if lat else 0
    out["calibration_deep"] = calibration_deep(rows)
    out["veto_value"] = veto_value(rows)
    out["fail_stats"] = fail_stats(rows)
    for b in out["calibration"].values():
        b["win_rate"] = round(100.0 * b["wins"] / b["closed"], 1) if b["closed"] else None
    return out


@router.get("/summary")
async def llm_review_summary(days: int = Query(7, ge=1, le=365)):
    rows = await database.list_llm_reviews(since_ts=time.time() - days * 86400, limit=5000)
    return {"days": days, **summarize(rows)}


@router.get("/decisions")
async def llm_review_decisions(days: int = Query(7, ge=1, le=365), limit: int = Query(200, ge=1, le=1000)):
    rows = await database.list_llm_reviews(since_ts=time.time() - days * 86400, limit=limit)
    return {"days": days, "count": len(rows), "decisions": rows}


@router.get("/decisions/{review_id}")
async def llm_review_detail(review_id: int):
    rows = await database.list_llm_reviews(review_id=review_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Karar bulunamadı")
    return rows[0]
