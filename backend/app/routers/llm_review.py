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
