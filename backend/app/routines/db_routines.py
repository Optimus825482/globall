"""Sunucu tarafı (DB-only) rutinler — MT5 gerektirmez.

`requires_mt5=True` olan ölçüm probları (beklenti/MFE/seçicilik) köprü makinesinde koşar;
buradakiler panelde zaman serisi üretmek için sunucuda koşar.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.routines.base import routine

logger = logging.getLogger("scalper.routines.db")


@routine("shadow_snapshot",
         "Gölge modlar raporunun anlık görüntüsü (hangi mekanizma kaç örnek topladı / karar eşiği)",
         interval_sec=6 * 3600, output_note="shadow_report.build() özet sayaçları",
         tags=["shadow", "reports"])
async def shadow_snapshot() -> Dict[str, Any]:
    """`shadow_report.build()` → sayaç özeti. Zaman serisi `routine_runs`'ta birikir."""
    from app import shadow_report
    rep = await shadow_report.build()
    return {
        "ok": True,
        "count": rep.get("count"),
        "active_shadow": rep.get("active_shadow"),
        "ready_for_decision": rep.get("ready_for_decision"),
        "hidden_off": rep.get("hidden_off"),
        "items": [{"key": i["key"], "mode": i["mode"], "n": i["n"], "ready": i["ready"]}
                  for i in rep.get("items", [])],
    }


@routine("proof_scope_snapshot",
         "Kanıt kapsamı ayarının anlık görüntüsü (hangi semboller açık, ne zaman değişti)",
         interval_sec=12 * 3600, output_note="proof_scope_enabled + sembol listesi",
         tags=["scope", "reports"])
async def proof_scope_snapshot() -> Dict[str, Any]:
    """Kanıt kapsamı ayarını kaydeder — kapsam değişimi zaman serisinden okunabilsin."""
    from app.routers import forex as fx
    st = fx._AUTO_SETTINGS
    return {
        "ok": True,
        "enabled": bool(getattr(st, "proof_scope_enabled", False)),
        "symbols": sorted(str(x).upper() for x in (getattr(st, "proof_scope_symbols", []) or [])),
        "blocked_symbols": sorted(str(x).upper() for x in (getattr(st, "blocked_symbols", []) or [])),
        "tokyo_drift_enabled": bool(getattr(st, "tokyo_drift_enabled", False)),
        "tokyo_windows": getattr(st, "tokyo_drift_windows", {}) or {},
    }


@routine("llm_calibration_snapshot",
         "LLM güven kalibrasyonu özeti (OOS skill / eşik önerisi) — ölçüm birikimini izler",
         interval_sec=24 * 3600, output_note="llm_calibration özeti", tags=["llm", "calibration"])
async def llm_calibration_snapshot() -> Dict[str, Any]:
    """Kalibrasyon modülünün özetini kaydeder (veri yoksa 'birikiyor' der, sayı uydurmaz)."""
    from app import llm_calibration
    try:
        summary = llm_calibration.summary() if hasattr(llm_calibration, "summary") else None
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if summary is None:
        return {"ok": True, "note": "özet fonksiyonu yok — modül API'si değişmiş olabilir"}
    return {"ok": True, "summary": summary}


@routine("retail_sentiment",
         "Perakende konumlanma (Myfxbook topluluk outlook) — 30 dk tur, geçmişi loglar",
         interval_sec=1800,
         output_note="retail_sentiment_history satır sayısı + kalabalık pariteler",
         tags=["sentiment", "context"])
async def retail_sentiment_snapshot() -> Dict[str, Any]:
    """Kalabalığın tarafını çeker ve **geçmişe yazar**.

    Panel açık olmasa da log birikmeli: veri geriye dönük alınamıyor, ölçüm
    ("aşırı konumlanma → ileri getiri") ancak bu tablo biriktikçe yapılabilir.
    Ücretsiz kota 100 istek/24s → tur aralığı 30 dk (48 istek), modül içinde
    günlük sert tavan da var. Ağ çağrısı iş parçacığına alınır (olay döngüsü bloklanmaz).
    """
    import asyncio

    from app import retail_sentiment as rs

    st = await asyncio.to_thread(rs.refresh_blocking, False)
    rows = rs._state.get("rows") or {}  # noqa: SLF001 — modül API'si
    crowded = sorted(
        ({"symbol": r["symbol"], "long_pct": r["long_pct"]}
         for r in rows.values() if float(r["long_pct"]) >= rs.RET_SENT_CROWD_PCT
         or float(r["short_pct"]) >= rs.RET_SENT_CROWD_PCT),
        key=lambda x: -abs(x["long_pct"] - 50.0))
    return {
        "ok": bool(st.get("ok")),
        "symbols": st.get("symbols"),
        "error": st.get("error"),
        "calls_today": st.get("calls_today"),
        "crowded": crowded[:8],
    }
