"""Sohbetten "BTC'yi takibe al": sembolü kendi belirlediği aralıklarla otomatik analiz eder, fırsat çıkarsa DEMO hesapta işlem açar.

Kullanıcı sohbette "takibi durdur" yazarak ya da "Zamanlanmış işler" şeridindeki Durdur düğmesiyle takibi bitirir.

Güvenceler
  - Fırsat taramasıyla AYNI kapılar (TradingView uyumu, teknik puan ≥ 2,5, haber, seviye/lot küçültme, portföy risk kapısı, lot bütçesi,
    yalnız DEMO, açık pozisyon/soğuma): gözetimsiz çalıştığı için gevşetilmiş "açık komut" eşiği KULLANILMAZ.
  - Takip başına en çok `MAX_OPENS` işlem ve `MAX_HOURS` süre; aynı anda en çok `MAX_WATCHES` takip.
  - Kurulum/durdurma yalnız yönetici (sohbet kapısı); işler veritabanında durur, yeniden başlatmada devam eder.
Aralık uyarlanır: sıcak sinyal (güçlü teknik puan) 2 dk, sıkışma 3 dk, normal 5 dk, trendsiz/sakin 10 dk, işlem açıldıktan sonra 15 dk.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app import database

logger = logging.getLogger("scalper.watch")

MAX_WATCHES = 3
MAX_OPENS = 3
MAX_HOURS = 24
MIN_INTERVAL, MAX_INTERVAL = 120, 900

_TR_FOLD = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
_START = ("takibe al", "takibe basla", "takip et ", "takip et.", "izlemeye al", "izleme al")
_STOP_WORDS = ("durdur", "bitir", "iptal", "kapat", "birak", "sonlandir", "dur ")
_RUNNING: set = set()
_TASKS: set = set()          # create_task referansı (GC iptal etmesin)


def _fold(text: str) -> str:
    return str(text or "").translate(_TR_FOLD).lower() + " "


def parse_watch_request(text: str, symbols: List[str]) -> Optional[Dict[str, Any]]:
    """Saf fonksiyon: {"action": "start"|"stop", "symbol": str|None} ya da None."""
    t = _fold(text)
    if ("takip" in t or "takib" in t or "izle" in t) and any(w in t for w in _STOP_WORDS) and "takibe al" not in t:
        return {"action": "stop", "symbol": symbols[0] if len(symbols) == 1 else None}
    if any(w in t for w in _START) and len(symbols) == 1:
        return {"action": "start", "symbol": symbols[0]}
    return None


def next_interval_sec(analysis: Dict[str, Any], opened: bool) -> int:
    """Bir sonraki analizin zamanı: sinyal sıcaksa sık, piyasa sakinse seyrek (120-900 sn)."""
    if opened:
        return 900
    score = abs(float(analysis.get("score") or 0)) if analysis.get("ok") else 0.0
    ind = analysis.get("indicators") or {}
    squeeze = any(((v.get("bollinger") or {}).get("sikisma") or v.get("bb_keltner_sikisma")) for v in ind.values() if isinstance(v, dict))
    frames = analysis.get("frames") or {}
    trending = bool((frames.get("4h") or frames.get("1h") or {}).get("trending"))
    if analysis.get("ok") and score >= 2.0:
        sec = 120
    elif squeeze:
        sec = 180
    elif not trending:
        sec = 600
    else:
        sec = 300
    return max(MIN_INTERVAL, min(MAX_INTERVAL, sec))


def _label(sec: float) -> str:
    return f"{int(sec // 60)} dk"


async def start_watch(symbol: str) -> str:
    jobs = [j for j in await database.sched_list(100) if j["status"] == "pending" and j["kind"] == "watch"]
    for j in jobs:
        if (j["params"] or {}).get("symbol") == symbol:
            return f"✅ **{symbol} zaten takipte** (#{j['id']}). Durdurmak için \"{symbol} takibini durdur\" yaz ya da şeritteki Durdur düğmesine bas."
    if len(jobs) >= MAX_WATCHES:
        return f"⚠️ En çok {MAX_WATCHES} takip aynı anda çalışabilir. Önce birini durdur (\"takibi durdur\")."
    params = {"symbol": symbol, "runs": 0, "opens": 0, "started_ts": time.time(), "interval": 120}
    job_id = await database.sched_create("watch", time.time() + 5, params, f"{symbol} takibe al")
    return (f"👁️ **{symbol} takibe alındı** (#{job_id})\n\n"
            f"- Kendi belirlediğim aralıklarla (sıcak sinyalde 2 dk, normalde 5 dk, sakin piyasada 10 dk) çoklu zaman dilimi analizi, "
            f"TradingView özeti ve ekonomik takvimi kontrol ederim.\n"
            f"- Fırsat taramasındaki **aynı kapılardan** geçen net bir fırsat çıkarsa DEMO hesapta işlem açarım "
            f"(takip başına en çok {MAX_OPENS} işlem, en çok {MAX_HOURS} saat).\n"
            f"- Durdurmak için sohbete \"{symbol} takibini durdur\" yaz ya da *Zamanlanmış işler* şeridindeki **Durdur** düğmesine bas.")


async def stop_watches(symbol: Optional[str]) -> str:
    jobs = [j for j in await database.sched_list(100) if j["status"] == "pending" and j["kind"] == "watch"
            and (symbol is None or (j["params"] or {}).get("symbol") == symbol)]
    if not jobs:
        return "Durduracak aktif takip yok." if symbol is None else f"{symbol} için aktif takip yok."
    for j in jobs:
        await database.sched_cancel(j["id"])
    names = ", ".join(str((j["params"] or {}).get("symbol")) for j in jobs)
    return f"⏹️ **Takip durduruldu:** {names}. Daha önce açılan işlemler etkilenmez."


async def handle_text(text: str, symbols: List[str]) -> Optional[str]:
    req = parse_watch_request(text, symbols)
    if not req:
        return None
    return await start_watch(req["symbol"]) if req["action"] == "start" else await stop_watches(req["symbol"])


def describe_job(job: Dict[str, Any]) -> str:
    p = job.get("params") or {}
    return (f"Takip — {p.get('symbol')} · her ~{_label(p.get('interval', 300))} analiz · "
            f"{p.get('runs', 0)} tur, {p.get('opens', 0)}/{MAX_OPENS} işlem açıldı")


async def _is_pending(job_id: int) -> bool:
    return any(j["id"] == job_id and j["status"] == "pending" for j in await database.sched_list(100))


async def run_watch_once(job: Dict[str, Any]) -> None:
    """Tek takip turu: analiz → fırsat kapıları → (varsa) DEMO işlem → bir sonraki tur zamanı."""
    from app import forex_research, opportunity_trades
    from app.routers import forex as fx
    from app.routers import forex_chat

    job_id = job["id"]
    p = dict(job.get("params") or {})
    sym = str(p.get("symbol") or "")
    now = time.time()
    note = ""
    opened_now = False
    analysis: Dict[str, Any] = {}
    try:
        if now - float(p.get("started_ts") or now) > MAX_HOURS * 3600:
            await database.sched_update(job_id, "done", f"{MAX_HOURS} saat doldu, takip kendiliğinden bitti")
            return
        if not fx._MT5_STATE.get("connected"):
            note = "MT5 köprüsü bağlı değil; bir sonraki turda denenecek"
        else:
            await forex_research.run_blocking(forex_research.mt5_request, sym)
            await forex_research.run_blocking(forex_research.mt5_wait, sym)
            analysis = await forex_research.run_blocking(forex_research.analyze_symbol, sym)
            if not analysis.get("ok"):
                note = "analiz verisi alınamadı"
            else:
                scan = await forex_research.run_blocking(forex_research.scan_opportunities, [sym], 1)
                from app.forex_news import get_forex_news
                items = await get_forex_news(force_refresh=False)
                cal = forex_chat.compact_calendar(items, time.time(), forex_research.currencies_for(sym), [sym])
                await forex_chat.attach_surprise_z(cal)
                bias, score = analysis.get("bias"), analysis.get("score")
                if not await _is_pending(job_id):                       # kullanıcı bu arada durdurdu
                    return
                if int(p.get("opens", 0)) >= MAX_OPENS:
                    note = "işlem sınırına ulaşıldı"
                else:
                    result = await asyncio.wait_for(opportunity_trades.open_from_scan({sym: analysis}, scan or {}, cal), timeout=20)
                    if result["opened"]:
                        o = result["opened"][0]
                        opened_now = True
                        p["opens"] = int(p.get("opens", 0)) + 1
                        note = f"{o['direction']} işlem AÇILDI: {o['lots']} lot, stop {o['sl_pips']:.0f}, hedef {o['tp_pips']:.0f}"
                    else:
                        why = result["skipped"][0]["reason"] if result["skipped"] else "kapılar geçmedi"
                        note = f"{bias} ({score:+.1f}): işlem yok — {why}"
    except Exception as exc:  # noqa: BLE001 - tek tur hatası takibi bitirmez
        logger.warning("takip turu hatası (%s): %s: %s", sym, type(exc).__name__, exc)
        note = f"tur hatası ({type(exc).__name__}), yeniden denenecek"
    if not await _is_pending(job_id):
        return
    interval = next_interval_sec(analysis, opened_now)
    p.update(runs=int(p.get("runs", 0)) + 1, interval=interval, last_run=time.time())
    stamp = time.strftime("%H:%M", time.gmtime(time.time() + 3 * 3600))
    done = opened_now and int(p["opens"]) >= MAX_OPENS
    if done:
        await database.sched_update(job_id, "done", f"[{stamp}] {note}; işlem sınırına ulaşıldı, takip bitti")
        return
    await database.sched_reschedule(job_id, time.time() + interval, p, f"[{stamp}] {note}")


def spawn_if_idle(job: Dict[str, Any]) -> None:
    """Takip turunu arka planda başlatır (aynı takip aynı anda iki kez çalışmaz; kapatma işlerini geciktirmez)."""
    jid = job["id"]
    if jid in _RUNNING:
        return
    _RUNNING.add(jid)

    async def _go():
        try:
            await run_watch_once(job)
        finally:
            _RUNNING.discard(jid)

    task = asyncio.create_task(_go())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
