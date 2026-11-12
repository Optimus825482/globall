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
         "Perakende konumlanma (Myfxbook topluluk outlook) — 15 dk tur, TÜM alanları loglar",
         interval_sec=900,
         output_note="retail_sentiment_history satır sayısı + kalabalık pariteler",
         tags=["sentiment", "context"])
async def retail_sentiment_snapshot() -> Dict[str, Any]:
    """Kalabalığın tarafını çeker ve **geçmişe yazar**.

    Panel açık olmasa da log birikmeli: veri geriye dönük alınamıyor, ölçüm
    ("aşırı konumlanma → ileri getiri") ancak bu tablo biriktikçe yapılabilir.
    2026-11-12: tur aralığı 30 dk → **15 dk** (96 istek/24s; ücretsiz kota 100).
    Modül içinde günlük sert tavan (95) var; aşılırsa ağa çıkılmaz.
    TÜM alanlar yazılır (yüzde, pozisyon, ortalama giriş fiyatı, hacim) — geçmiş
    geriye dönük alınamadığı için ileride farklı analizlerde kullanılabilsin. Ağ çağrısı iş parçacığına alınır (olay döngüsü bloklanmaz).
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


#: Bileşik sentiment endeksinin loglanacağı semboller (canlı evrenin çekirdeği).
SENTIMENT_LOG_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
    "EURJPY", "GBPJPY", "EURGBP", "XAUUSD", "US30", "NAS100", "JP225", "UK100", "DE40",
]


@routine("sentiment_index_log",
         "Bileşik sentiment skorunu loglar (−100…+100) — ileri getiri ölçümü için",
         interval_sec=1800,
         output_note="sentiment_index_history satır sayısı + en uç skorlar",
         tags=["sentiment", "context", "measurement"])
async def sentiment_index_log() -> Dict[str, Any]:
    """Skoru **geçmişe yazar** — 4-6 hafta sonra IC ölçülebilsin.

    Neden rutin: takvim `actual` değerleri, COT raporu ve perakende turu o anki
    hâlleridir; geriye dönük skor üretilemez. Panel açık olmasa da birikmeli.
    Ağırlıklar yargıdır; ölçüm `scripts/sentiment_index_edge.py` ile yapılır.
    """
    import asyncio
    import time

    from app import database, sentiment_index as si

    def _compute() -> list:
        # Takvimi ısıt: 24s yaş-ağırlıklı ölçüm için güncel actual'lar şart.
        try:
            from app import forex_news_bias as nb
            from app.forex_news import get_forex_news
            events = asyncio.run(get_forex_news())
            if events:
                nb.refresh_biases(events, time.time(), window_sec=1800.0)
                si.refresh_calendar(events, time.time())
        except Exception as exc:  # noqa: BLE001
            logger.debug("sentiment rutin takvim ısıtma atlandı: %s", exc)
        try:
            from app import retail_sentiment as rs
            rs.warm_sync()
        except Exception:  # noqa: BLE001
            pass
        out = []
        for sym in SENTIMENT_LOG_SYMBOLS:
            try:
                r = si.summarize(sym)
                out.append({"symbol": r["symbol"], "score": r["score"],
                            "coverage": r["coverage"], "label": r["label"],
                            "components": {k: v.get("score")
                                           for k, v in r["components"].items() if v["available"]}})
            except Exception:  # noqa: BLE001 — tek sembol turu düşürmesin
                continue
        return out

    rows = await asyncio.to_thread(_compute)
    n = await database.save_sentiment_index(rows, time.time()) if rows else 0
    ranked = sorted(rows, key=lambda r: -abs(r["score"]))
    return {
        "ok": bool(rows),
        "logged": n,
        "symbols": len(rows),
        "extremes": [{"symbol": r["symbol"], "score": r["score"]} for r in ranked[:5]],
    }


@routine("arm_live_monitor",
         "Canlı kol izleme: kol×sembol PF + 'ayar panelden uygulandı mı' kontrolü "
         "(kill kriteri n≥20 & PF<1,0). Önemliyse push gönderir.",
         interval_sec=3 * 86400,
         output_note="kol×sembol n/PF + çıkarılan sembollerde yeni işlem sayısı",
         tags=["monitor", "arms", "measurement"])
async def arm_live_monitor() -> Dict[str, Any]:
    """3 günde bir: 2026-11-12 sembol-listesi değişikliğinin etkisini raporlar.

    Pencere: `ARM_MONITOR_SINCE` (varsayılan 2026-11-12 = ölçüm/ayar tarihi) →
    tarih sabit, pencere kendiliğinden büyür. Bu sayede "çıkarılan sembolde yeni
    işlem var mı" kontrolü **değişiklik sonrası** dönemi görür; kayan pencere
    kullanılsaydı değişiklik öncesi işlemler yanlış alarm üretirdi.

    Önemli sonuç (çıkarılması gereken sembol veya ayar uygulanmamış) varsa push gider.
    Sonuç her hâlükârda `routine_runs`'a yazılır → Raporlar > Rutinler.
    """
    import asyncio
    import os

    from app import arm_live_monitor as alm

    since = (os.getenv("ARM_MONITOR_SINCE") or "2026-11-12").strip()
    try:
        report = await asyncio.to_thread(alm.build_report, days=14, since=since)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "since": since}

    msg = alm.push_message(report)
    pushed, push_err = False, None
    if msg:
        try:
            from app.alerting import deliver_web_push
            res = await deliver_web_push(msg, title="Kol izleme raporu",
                                         url="/forex/reports", tag="arm-live-monitor")
            pushed = bool((res or {}).get("ok"))
        except Exception as exc:  # noqa: BLE001
            push_err = f"{type(exc).__name__}: {exc}"

    return {
        "ok": True,
        "since": since,
        "pushed": pushed,
        **({"push_error": push_err} if push_err else {}),
        "karar_gereken": report.get("karar_gereken") or [],
        "uyarilar": report.get("uyarilar") or [],
        "semboller": {k: {"n": v["n"], "pf": v["pf"], "verdict": v["verdict"]}
                      for k, v in (report.get("semboller") or {}).items()},
        "ayar_kontrolu": report.get("ayar_kontrolu") or {},
    }
