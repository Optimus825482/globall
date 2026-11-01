"""API endpoints for Binance TR Spot Monitor & Simulator."""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional
from app import spot_monitor

router = APIRouter(prefix="/api/spot-monitor", tags=["spot-monitor"])

class TradeSizePayload(BaseModel):
    size: float = Field(..., ge=50.0, le=50000.0, description="Alım/işlem büyüklüğü (TRY)")

@router.get("/dashboard")
async def get_dashboard():
    """Anlık spot sinyalleri, başarı yüzdeleri ve portföy simülasyonunu döndürür."""
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

@router.post("/trade-size")
async def update_trade_size(size: float):
    """Spot Monitor alım/işlem büyüklüğünü (TRY) günceller."""
    try:
        return await spot_monitor.set_trade_size(size)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.post("/fee-mode")
async def update_fee_mode(mode: str):
    """Ücret senaryosunu değiştirir: 'bnb' (%0.15 round-trip) veya 'base' (%0.20).

    Simülatörün gerçekçiliği buna bağlı; lab sonuçları %0.08 varsayımıyla üretildi."""
    try:
        return await spot_monitor.set_fee_mode(mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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

@router.post("/close/{signal_id}")
async def close_position(signal_id: int):
    """Açık bir spot simülasyon pozisyonunu manuel olarak anlık fiyattan kapatır."""
    try:
        res = await spot_monitor.close_spot_position_manual(signal_id)
        if not res.get("success"):
            raise HTTPException(status_code=400, detail=res.get("message"))
        return res
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.post("/close-all")
async def close_all_positions():
    """Tüm açık spot simülasyon pozisyonlarını tek tıkla anlık fiyattan kapatır."""
    try:
        return await spot_monitor.close_all_spot_positions_manual()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/forward-test")
async def forward_test_report(frozen_id: int | None = None):
    """Dondurulmuş modelin İLERİ test karnesi (salt okuma).

    Model dondurulduktan sonra üretilen, hiç görülmemiş tahminlerin gerçek
    sonuçları. Kapıyı geçenler ve geçmeyenler AYRI raporlanır; hiçbir parametre
    ayarlanmaz. Bu bir kanıt aracıdır, optimizasyon aracı değil.
    """
    try:
        from app import ml_forward_test
        return await ml_forward_test.forward_report(frozen_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ─── TSMOM (günlük momentum kanalı) ───────────────────────────────────────────

@router.get("/tsmom")
async def tsmom_dashboard():
    """TSMOM günlük kanalı: rejim, hedefler, açık pozisyonlar, portföy.

    Mevcut 5 dakikalık taramadan BAĞIMSIZ çalışır — farklı zaman dilimi,
    farklı portföy. 7 yıllık doğrulamada kabul kriterlerini geçen tek
    yaklaşım (Sharpe 1.01, maxDD -%9.31, 10/10 sembol pozitif).
    """
    try:
        from app import tsmom
        return await tsmom.get_dashboard()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/tsmom/rebalance")
async def tsmom_rebalance(force: bool = False):
    """TSMOM'u elle yeniden dengeler (günde bir kez; force ile zorlanır)."""
    try:
        from app import tsmom
        return await tsmom.run_rebalance(force=force)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
