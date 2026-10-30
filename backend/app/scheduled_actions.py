"""Sohbetten kurulan zamanlanmış işler: hatırlatıcı ve "saat X'te pozisyonları kapat".

Sohbette "cuma 23:50'de BTC ve coinler hariç tüm pozisyonları kapat" gibi bir istek, LLM'e gitmeden bu modülde
ayrıştırılır, veritabanına yazılır ve `scheduler_loop` zamanı gelince çalıştırır (yeniden başlatmaya dayanıklı).

Güvenceler
  - İzinli iş türleri yalnızca `close_positions` ve `reminder` (serbest eylem yok; LLM metni komuta dönüşmez).
  - Kapatma yalnızca DEMO hesapta ve köprü bağlıyken çalışır; köprü yoksa `RETRY_WINDOW_SEC` boyunca denenir.
  - Zamanı `STALE_SEC`'ten fazla geçmiş kapatma işi (sunucu kapalıydı) ÇALIŞTIRILMAZ, "kaçırıldı" olarak işaretlenir.
  - Zaman: Türkiye saati (UTC+3, yaz saati yok).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app import database

logger = logging.getLogger("scalper.scheduler")

TR_TZ = timezone(timedelta(hours=3))
POLL_SEC = 15
RETRY_WINDOW_SEC = 15 * 60        # köprü bağlı değilse kapatma bu süre boyunca denenir
STALE_SEC = 15 * 60               # zamanı bu kadar geçmiş kapatma işi çalıştırılmaz
REMINDER_STALE_SEC = 6 * 3600     # hatırlatıcı bu süreden sonra yine iletilir ama "gecikmeli" yazılır

WEEKDAYS = {"pazartesi": 0, "salı": 1, "sali": 1, "çarşamba": 2, "carsamba": 2, "perşembe": 3, "persembe": 3,
            "cuma": 4, "cumartesi": 5, "pazar": 6}
WEEKDAY_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
CRYPTO_PREFIXES = ("BTC", "ETH", "XRP", "LTC", "SOL", "DOGE", "ADA", "BNB", "DOT", "AVAX", "LINK", "MATIC", "TRX")
CRYPTO_WORDS = ("btc", "bitcoin", "coin", "coın", "krıpto", "kripto", "crypto", "eth", "ethereum", "xrp", "ripple")
GOLD_WORDS = ("altın", "altin", "xau", "gold")
EXCLUDE_WORDS = ("hariç", "haric", "harıc", "dışında", "disinda", "haricinde", "hariçte")
_TIME_RE = re.compile(r"(?<![\d.:])([01]?\d|2[0-3])[:.]([0-5]\d)(?![\d:])")
# "23 50 de kapat" gibi iki nokta/nokta olmadan yazılan saat: yalnızca ardından ek (de/da/te/ta) geliyorsa saat sayılır
_TIME_SPACE_RE = re.compile(r"(?<![\d.:])([01]?\d|2[0-3])\s([0-5]\d)\s*['’]?\s*(?:de|da|te|ta)\b")


def is_crypto(symbol: str) -> bool:
    return str(symbol or "").upper().startswith(CRYPTO_PREFIXES)


def is_gold(symbol: str) -> bool:
    return str(symbol or "").upper().startswith(("XAU", "GOLD"))


def _norm(text: str) -> str:
    return str(text or "").replace("İ", "i").replace("I", "ı").lower()


def _has_any(t: str, words) -> bool:
    return any(w in t for w in words)


def parse_schedule_request(text: str, now_ts: float, symbols: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Saf fonksiyon: {kind, due_ts, params, text} ya da None (zamanlama isteği değil).

    Tetik: açık bir saat (SS:DD) + "kapat" ya da "hatırlat" fiili. `symbols`: metinde geçen semboller (çağıran bulur).
    """
    t = _norm(text)
    m = _TIME_RE.search(t) or _TIME_SPACE_RE.search(t)
    if not m:
        return None
    wants_close = "kapat" in t and "kapatt" not in t and "kapatıl" not in t
    wants_remind = "hatırlat" in t or "hatirlat" in t
    if not (wants_close or wants_remind):
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    now = datetime.fromtimestamp(now_ts, TR_TZ)
    target_day = None
    for word, wd in WEEKDAYS.items():
        if re.search(rf"\b{word}", t):
            # "cumartesi"/"cuma" ve "pazar"/"pazartesi" öneki çakışır: en uzun eşleşme kazanır
            if target_day is None or len(word) > target_day[0]:
                target_day = (len(word), wd)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target_day is not None:
        delta = (target_day[1] - now.weekday()) % 7
        candidate = candidate + timedelta(days=delta)
        if candidate <= now:
            candidate += timedelta(days=7)
    elif "yarın" in t or "yarin" in t:
        candidate += timedelta(days=1)
    elif candidate <= now:
        candidate += timedelta(days=1)
    due_ts = candidate.timestamp()

    if wants_close:
        has_excl = _has_any(t, EXCLUDE_WORDS)
        mentioned = [s.upper() for s in (symbols or [])]
        params: Dict[str, Any] = {"exclude_groups": [], "exclude_symbols": [], "only_symbols": []}
        if has_excl:
            if _has_any(t, CRYPTO_WORDS):
                params["exclude_groups"].append("crypto")
            if _has_any(t, GOLD_WORDS):
                params["exclude_groups"].append("gold")
            params["exclude_symbols"] = [s for s in mentioned if not (is_crypto(s) and "crypto" in params["exclude_groups"])
                                         and not (is_gold(s) and "gold" in params["exclude_groups"])]
            if not params["exclude_groups"] and not params["exclude_symbols"]:
                return None                         # neyin hariç olduğu anlaşılamadı: yanlış kapatma riski, işlem kurulmaz
        elif mentioned:
            params["only_symbols"] = mentioned
        elif not _has_any(t, ("pozisyon", "işlem", "islem", "hepsini", "tümünü", "tumunu", "tüm", "tum")):
            return None
        return {"kind": "close_positions", "due_ts": due_ts, "params": params, "text": str(text)[:500]}
    return {"kind": "reminder", "due_ts": due_ts, "params": {"message": str(text)[:300]}, "text": str(text)[:500]}


def select_positions(positions: List[Dict[str, Any]], params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Kapatılacak pozisyonlar (saf fonksiyon)."""
    groups = set(params.get("exclude_groups") or [])
    ex_syms = {str(s).upper() for s in params.get("exclude_symbols") or []}
    only = {str(s).upper() for s in params.get("only_symbols") or []}
    out = []
    for p in positions or []:
        sym = str(p.get("symbol", "")).upper()
        if not sym or p.get("ticket") is None:
            continue
        if only and sym not in only:
            continue
        if sym in ex_syms or ("crypto" in groups and is_crypto(sym)) or ("gold" in groups and is_gold(sym)):
            continue
        out.append(p)
    return out


def describe_job(job: Dict[str, Any]) -> str:
    """Zamanlanmış iş şeridi satırı."""
    if job["kind"] == "close_positions":
        return "Pozisyon kapatma — " + describe_params(job["params"])
    if job["kind"] == "watch":
        from app import symbol_watch
        return symbol_watch.describe_job(job)
    return "Hatırlatıcı — " + str((job["params"] or {}).get("message") or "")[:120]


def fmt_due(due_ts: float) -> str:
    d = datetime.fromtimestamp(due_ts, TR_TZ)
    return f"{WEEKDAY_TR[d.weekday()]} {d:%d.%m %H:%M} (TSİ)"


def describe_params(params: Dict[str, Any]) -> str:
    bits = []
    if params.get("only_symbols"):
        bits.append("yalnızca " + ", ".join(params["only_symbols"]))
    else:
        bits.append("tüm pozisyonlar")
    ex = []
    if "crypto" in (params.get("exclude_groups") or []):
        ex.append("kripto (BTC/coinler)")
    if "gold" in (params.get("exclude_groups") or []):
        ex.append("altın")
    ex += list(params.get("exclude_symbols") or [])
    if ex:
        bits.append("hariç: " + ", ".join(ex))
    return "; ".join(bits)


def confirmation_text(job: Dict[str, Any], job_id: int, positions: List[Dict[str, Any]]) -> str:
    when = fmt_due(job["due_ts"])
    if job["kind"] == "reminder":
        return (f"⏰ **Hatırlatıcı kuruldu** (#{job_id}) — {when}\n\nZamanı gelince bu sayfada bildirim göstereceğim. "
                f"İptal için *Zamanlanmış işler* kartındaki İptal düğmesini kullan.")
    chosen = select_positions(positions, job["params"])
    now_list = ", ".join(f"{p.get('symbol')} {p.get('direction', '')}" for p in chosen) or "şu an kapanacak pozisyon yok"
    kept = [p for p in positions if p not in chosen]
    kept_list = ", ".join(str(p.get("symbol")) for p in kept) or "—"
    return (f"🕒 **Zamanlanmış kapatma kuruldu** (#{job_id}) — {when}\n\n"
            f"- Kapsam: {describe_params(job['params'])}\n"
            f"- Şu anki duruma göre kapanacaklar: {now_list}\n"
            f"- Açık kalacaklar: {kept_list}\n\n"
            f"Saat gelince açık pozisyonlar o andaki listeye göre yeniden seçilir ve kapatma emri MT5 köprüsüne iletilir "
            f"(yalnızca DEMO hesap). Zamanı {STALE_SEC // 60} dk'dan fazla geçerse (sunucu kapalıysa) **çalıştırılmaz**. "
            f"İptal: *Zamanlanmış işler* kartı.")


async def create_from_text(text: str, symbols: Optional[List[str]] = None) -> Optional[str]:
    """Metin zamanlama isteğiyse işi kaydeder ve kullanıcıya gösterilecek onay metnini döner; değilse None."""
    from app import symbol_watch
    watched = await symbol_watch.handle_text(text, [s.upper() for s in (symbols or [])])
    if watched:
        return watched
    job = parse_schedule_request(text, time.time(), symbols)
    if not job:
        return None
    # Aynı iş (tür + zaman + kapsam) zaten bekliyorsa ikinci kez kurma ("hatırlıyor musun?" gibi tekrar mesajları)
    for ex in await database.sched_list(50):
        if (ex.get("status") == "pending" and ex.get("kind") == job["kind"] and abs(float(ex["due_ts"]) - job["due_ts"]) < 60
                and (ex.get("params") or {}) == job["params"]):
            return (f"✅ Bu iş **zaten kurulu** (#{ex['id']}) — {fmt_due(ex['due_ts'])}. Yeniden kurmadım; "
                    f"iptal etmek için *Zamanlanmış işler* şeridindeki İptal düğmesini kullan.")
    job_id = await database.sched_create(job["kind"], job["due_ts"], job["params"], job["text"])
    from app.routers import forex as fx
    return confirmation_text(job, job_id, list(fx._MT5_STATE.get("open_positions") or []))


def _execute_close(job: Dict[str, Any], now: float) -> tuple:
    """(status, result). status None → beklemede kalır (köprü yok), tekrar denenir."""
    from app.routers import forex as fx
    st = fx._MT5_STATE
    if not st.get("connected"):
        return None, "MT5 köprüsü bağlı değil; bağlanınca denenecek"
    if "demo" not in str((st.get("account") or {}).get("server") or "").lower():
        return "failed", "Zamanlanmış kapatma yalnızca DEMO hesapta çalışır"
    chosen = select_positions(list(st.get("open_positions") or []), job["params"])
    if not chosen:
        return "done", "Kapatılacak pozisyon yoktu"
    pending = {(c.get("action"), c.get("ticket")) for c in st.get("pending_commands") or []}
    queued = []
    for p in chosen:
        if ("CLOSE_ORDER", p["ticket"]) in pending:
            continue
        st["pending_commands"].append({"id": f"CMD-SCHED-{p['ticket']}", "action": "CLOSE_ORDER", "ticket": p["ticket"]})
        queued.append(f"{p.get('symbol')} #{p['ticket']}")
    fx._log_auto_decision("EXIT", f"🕒 [Zamanlanmış kapatma #{job['id']}]: {len(queued)} pozisyon için kapatma emri kuyruğa alındı")
    fx._invalidate_status_cache()
    return "done", f"{len(queued)} pozisyon için kapatma emri MT5'e iletildi: " + ", ".join(queued)


async def run_due_jobs(now: Optional[float] = None) -> int:
    now = time.time() if now is None else now
    handled = 0
    due = sorted(await database.sched_due(now), key=lambda j: j["kind"] == "watch")      # kapatma/hatırlatıcı önce, takip turu en son
    for job in due:
        late = now - float(job["due_ts"])
        try:
            if job["kind"] == "watch":
                from app import symbol_watch
                symbol_watch.spawn_if_idle(job)             # uzun analiz arka planda; kapatma işlerini geciktirmez
                handled += 1
                continue
            if job["kind"] == "reminder":
                msg = str((job["params"] or {}).get("message") or "")
                tail = " (gecikmeli: sunucu kapalıydı)" if late > REMINDER_STALE_SEC else ""
                await database.sched_update(job["id"], "done", f"⏰ Hatırlatıcı: {msg}{tail}")
            elif job["kind"] == "close_positions":
                if late > STALE_SEC:
                    await database.sched_update(job["id"], "missed", f"Zamanı {int(late // 60)} dk geçtiği için çalıştırılmadı")
                else:
                    status, result = _execute_close(job, now)
                    if status is None and late > RETRY_WINDOW_SEC:
                        status, result = "failed", result
                    await database.sched_update(job["id"], status, result)
            else:
                await database.sched_update(job["id"], "failed", f"bilinmeyen iş türü: {job['kind']}")
            handled += 1
        except Exception as exc:  # noqa: BLE001 - tek iş hatası döngüyü durdurmaz
            logger.warning("zamanlanmış iş #%s hatası: %s: %s", job.get("id"), type(exc).__name__, exc)
            await database.sched_update(job["id"], "failed", f"{type(exc).__name__}: {exc}"[:300])
    return handled


async def scheduler_loop() -> None:
    logger.info("zamanlanmış iş döngüsü başladı (%d sn)", POLL_SEC)
    while True:
        try:
            await run_due_jobs()
        except Exception as exc:  # noqa: BLE001
            logger.warning("zamanlayıcı döngü hatası: %s", exc)
        await asyncio.sleep(POLL_SEC)
