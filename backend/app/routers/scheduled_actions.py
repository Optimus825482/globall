"""Zamanlanmış işler (sohbetten kurulan hatırlatıcı / kapatma): liste ve iptal."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app import database, scheduled_actions
from app.api_common import require_admin

router = APIRouter(prefix="/api/scheduled", tags=["scheduled"])


@router.get("")
async def list_jobs(request: Request, limit: int = 30):
    require_admin(request)      # zamanlı kapatma emir üretir: yalnız yönetici görür/iptal eder
    jobs = await database.sched_list(min(max(limit, 1), 100))
    for j in jobs:
        j["due_label"] = scheduled_actions.fmt_due(j["due_ts"])
        if j["kind"] == "close_positions":
            j["summary"] = "Pozisyon kapatma — " + scheduled_actions.describe_params(j["params"])
        else:
            j["summary"] = "Hatırlatıcı — " + str((j["params"] or {}).get("message") or "")[:120]
    return {"jobs": jobs}


@router.post("/{job_id}/cancel")
async def cancel_job(request: Request, job_id: int):
    require_admin(request)
    if not await database.sched_cancel(job_id):
        raise HTTPException(status_code=404, detail="İş bulunamadı ya da artık beklemede değil")
    return {"ok": True}
