"""API endpoints for Binance TR Spot Monitor & Simulator."""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from app import spot_monitor

router = APIRouter(prefix="/api/spot-monitor", tags=["spot-monitor"])

@router.get("/dashboard")
async def get_dashboard():
    """Anlık spot sinyalleri, başarı yüzdeleri ve 5.000 TL portföy simülasyonunu döndürür."""
    try:
        return await spot_monitor.get_spot_monitor_dashboard()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/strategies")
async def get_strategies():
    """Spot Monitor'de şu an aktif olan tarama stratejilerini, skorlarını, laboratuvar
    kanıtlarını ve otomatik taramadaki açık/kapalı durumlarını döndürür."""
    try:
        return await spot_monitor.get_active_strategies()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.post("/strategies/{code}/toggle")
async def toggle_strategy(code: str, enabled: bool):
    """Bir stratejinin otomatik tarama döngüsündeki aktif/pasif durumunu değiştirir (kalıcı)."""
    try:
        return await spot_monitor.set_strategy_enabled(code, enabled)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.post("/scan-now")
async def trigger_scan(background_tasks: BackgroundTasks):
    """Kullanıcının panelden 'Şimdi Tara' butonuna basarak anlık tarama başlatmasını sağlar."""
    try:
        background_tasks.add_task(spot_monitor.run_single_scan)
        return {"status": "ok", "message": "Anlık Binance TR spot taraması başlatıldı."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
