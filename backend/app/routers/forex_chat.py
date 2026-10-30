"""Forex / Altın / BTC uzman sohbeti (2026-10-30).

Eski sohbet kripto (Binance) bağlamıyla çalışıyordu. Bu uç; radar, DXY/CSM,
oturumlar, ekonomik takvim (açıklanan + yaklaşan), açık pozisyonlar ve bahsedilen
sembolün kapı durumunu PARALEL ve kısa zaman aşımıyla toplar, tek bir kompakt
bağlam olarak modele verir. Araç döngüsü yok: yanıt doğrudan akar (hızlı).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import llm_analysis
from app.api_common import rate_limit

logger = logging.getLogger("scalper.routers.forex_chat")

router = APIRouter(prefix="/api/forex", tags=["forex-chat"])

PART_TIMEOUT_SEC = 4.0
# Akıl yürüten modeller düşünme jetonlarını da bu sınırdan harcar; 700 yanıtı ortadan kesiyordu.
MAX_ANSWER_TOKENS = 2000

# Kullanıcı yazısında geçen ad → sembol (Türkçe/gündelik adlar dahil).
_ALIASES = {
    "ALTIN": "XAUUSD", "GOLD": "XAUUSD", "XAU": "XAUUSD", "XAUUSD": "XAUUSD",
    "GUMUS": "XAGUSD", "GÜMÜŞ": "XAGUSD", "SILVER": "XAGUSD", "XAGUSD": "XAGUSD",
    "BTC": "BTCUSD", "BITCOIN": "BTCUSD", "BTCUSD": "BTCUSD",
    "NASDAQ": "USTEC", "NAS100": "USTEC", "USTEC": "USTEC", "US30": "US30", "DOW": "US30",
}
_FX = re.compile(r"\b(?:EUR|GBP|AUD|NZD|USD|CAD|CHF|JPY)(?:EUR|GBP|AUD|NZD|USD|CAD|CHF|JPY)\b")

SYSTEM_PROMPT = (
    "Sen Altın (XAUUSD), Bitcoin (BTCUSD) ve Forex piyasaları için deneyimli bir işlem asistanısın. "
    "Kullanıcı tek bir bireysel trader; hesap DEMO/paper'dır.\n"
    "KURALLAR:\n"
    "- Yalnızca Türkçe, sade ve kısa yaz. Teknik terimleri (RSI, EMA, ATR, kapı, skor…) ancak gerekirse ve "
    "günlük dille açıklayarak kullan; sayı yığma.\n"
    "- YANIT BİÇİMİ (Markdown, hep aynı düzen; ekranda renkli gösterilir):\n"
    "  ## <BUY, SELL veya BEKLE> — <tek cümlelik sonuç>  (başlıkta yönü BUY / SELL / BEKLE yaz)\n"
    "  ### Neden\n"
    "  - en fazla 3 kısa madde; önemli sözcükleri **kalın** yaz (yön için **BUY**/**SELL**, güç için **güçlü**/**zayıf**)\n"
    "  ### Dikkat\n"
    "  - yaklaşan haber / seans / maliyet uyarısı (yoksa bu bölümü yazma)\n"
    "  ### Risk\n"
    "  - tek cümle: stop ve pozisyon büyüklüğü hatırlatması\n"
    "  Birden fazla sembol sorulursa her biri için ayrı '## ' başlığı aç. Selamlaşma ya da basit soruda "
    "bu düzeni zorlama, kısa düz yanıt ver.\n"
    "- Yalnızca aşağıdaki 'VERİ' bölümündeki bilgilere dayan: radar, kapı durumu, DXY/dolar, oturum, ekonomik takvim, "
    "pozisyonlar. Veri yoksa veya eskiyse bunu açıkça söyle; rakam uydurma.\n"
    "- Yaklaşan yüksek etkili veri (NFP, CPI, faiz kararı…) varsa mutlaka uyar: açıklamadan önce işlem açma.\n"
    "- Açıklanan verilerde gerçekleşen/beklenen farkını ve hangi pariteye ne yönde etki ettiğini sade anlat.\n"
    "- Emir açma/kapama talimatı verme, kesin kazanç vaat etme; 'bu bir yatırım tavsiyesi değildir' deme, "
    "bunun yerine riski (stop, pozisyon büyüklüğü) kısaca hatırlat.\n"
    "- 'blocked_by' kodları: direction=yön belirsiz, dxy=dolar rejimi ters, major_session=büyük seans kapalı, "
    "spread=işlem maliyeti yüksek, score=güç yetersiz, adx=trend zayıf, veri=veri eksik. Bunları kod olarak yazma, "
    "'yön belirsiz', 'maliyet yüksek' gibi düz Türkçe ile söyle.\n"
    "- Soru piyasa dışıysa tek cümleyle kibarca konuya yönlendir."
)


def _mentioned_symbols(text: str) -> List[str]:
    up = (text or "").upper().replace("İ", "I")
    found: List[str] = []
    for word in re.findall(r"[A-ZÇĞÖŞÜ0-9]+", up):
        sym = _ALIASES.get(word)
        if sym and sym not in found:
            found.append(sym)
    for m in _FX.findall(up):
        if m not in found:
            found.append(m)
    return found[:3]


async def _guard(coro, name: str):
    """Bir bağlam parçası yavaş/hatalı olursa sohbet bloke olmaz; parça atlanır."""
    try:
        return await asyncio.wait_for(coro, timeout=PART_TIMEOUT_SEC)
    except Exception as exc:  # noqa: BLE001 - kısmi bağlam kabul edilir
        logger.info("forex sohbet bağlamı atlandı (%s): %s", name, exc)
        return None


def _pick(d: Dict[str, Any], keys) -> Dict[str, Any]:
    return {k: d[k] for k in keys if k in d and d[k] not in (None, "", [])}


def compact_radar(radar: Any) -> Dict[str, Any]:
    if not isinstance(radar, dict):
        return {}
    cand_keys = ("symbol", "direction", "action", "score", "blocked_by", "blocking_gate", "reason", "verdict", "note")
    cands = [_pick(c, cand_keys) for c in (radar.get("candidates") or [])[:8] if isinstance(c, dict)]
    sigs = [_pick(c, cand_keys) for c in (radar.get("signals") or [])[:5] if isinstance(c, dict)]
    return {
        "guclu_sinyaller": sigs,
        "izleme_listesi": cands,
        "not": radar.get("scan_note"),
        "dxy": radar.get("dxy"),
        "para_birimi_gucu": radar.get("csm"),
        "oturumlar": radar.get("sessions"),
        "guncelleme": radar.get("updated_at"),
    }


def compact_calendar(items: Any, now_ts: float) -> Dict[str, Any]:
    """Son 6 saatte açıklananlar (sonuçlarıyla) + önümüzdeki 12 saatin yüksek etkili olayları."""
    from app.forex_news_bias import _iso_to_ts

    released: List[Dict[str, Any]] = []
    upcoming: List[Dict[str, Any]] = []
    for ev in items or []:
        if not isinstance(ev, dict):
            continue
        ts = _iso_to_ts(ev.get("date_iso"))
        if ts is None:
            continue
        age = now_ts - ts
        row = _pick(ev, ("title", "currency", "stars", "forecast", "previous", "actual"))
        row["dakika"] = round(-age / 60) if age < 0 else -round(age / 60)
        outcome = ev.get("outcome") or {}
        if outcome.get("label_tr") or outcome.get("comparison_tr"):
            row["sonuc"] = outcome.get("label_tr") or outcome.get("comparison_tr")
        side = outcome.get("side")
        if side:
            from app.forex_news_bias import symbol_direction
            cur = str(ev.get("currency") or ev.get("country") or "").upper().strip()
            try:
                row["etki"] = [f"{s} {symbol_direction(cur, side == 'bullish', str(s))}"
                               for s in (ev.get("affected_symbols") or [])[:4]]
            except Exception:  # noqa: BLE001
                pass
        if 0 <= age <= 6 * 3600 and ev.get("actual") not in (None, ""):
            released.append(row)
        elif -12 * 3600 <= age < 0 and int(ev.get("stars") or 0) >= 2:
            upcoming.append(row)
    released.sort(key=lambda r: r["dakika"], reverse=True)
    upcoming.sort(key=lambda r: r["dakika"])
    return {"aciklanan_son_6_saat": released[:8], "yaklasan_12_saat": upcoming[:8]}


def compact_status(status: Any) -> Dict[str, Any]:
    if not isinstance(status, dict):
        return {}
    pos_keys = ("symbol", "direction", "entry", "price", "pnl", "profit", "sl", "tp", "lots")
    positions = [_pick(p, pos_keys) for p in (status.get("open_positions") or status.get("positions") or [])[:8]
                 if isinstance(p, dict)]
    return {
        "acik_pozisyonlar": positions,
        "bakiye": status.get("balance"),
        "ozkaynak": status.get("equity"),
        "gunluk_kar_zarar": status.get("daily_pnl") or status.get("today_pnl"),
    }


async def build_context(user_text: str) -> Dict[str, Any]:
    """Tüm parçalar paralel; her biri en fazla PART_TIMEOUT_SEC bekler."""
    from app.routers import forex as fx

    now_ts = time.time()
    symbols = _mentioned_symbols(user_text)

    async def _news():
        from app.forex_news import get_forex_news
        return await get_forex_news(force_refresh=False)

    async def _gates():
        out = {}
        for sym in symbols:
            snap = await asyncio.to_thread(fx.get_symbol_gate_snapshot, sym)
            out[sym] = _pick(snap, ("action", "verdict", "verdict_level", "blocking_gate"))
            out[sym]["kapilar"] = [
                _pick(g, ("label", "status", "detail")) for g in (snap.get("gates") or [])[:10] if isinstance(g, dict)
            ]
        return out

    radar, status, news, gates = await asyncio.gather(
        _guard(fx.get_forex_radar(use_cache=True), "radar"),
        _guard(fx.get_forex_auto_paper_status(), "durum"),
        _guard(_news(), "takvim"),
        _guard(_gates(), "kapilar"),
    )
    ctx: Dict[str, Any] = {
        "saat_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(now_ts)),
        "radar": compact_radar(radar),
        "takvim": compact_calendar(news, now_ts),
        "hesap": compact_status(status),
    }
    if gates:
        ctx["sembol_durumu"] = gates
    if not radar:
        ctx["uyari"] = "Radar verisi şu an alınamadı; piyasa yorumu sınırlı."
    return ctx


@router.post("/chat")
async def forex_chat(payload: dict, request: Request):
    messages = [m for m in (payload.get("messages") or []) if isinstance(m, dict) and m.get("content")]
    if not messages or messages[-1].get("role") != "user":
        raise HTTPException(status_code=400, detail="Son mesaj kullanıcıdan olmalı")
    if not rate_limit("forex_chat", rate_per_sec=0.5, burst=4):
        raise HTTPException(status_code=429, detail="Çok sık soruyorsun, birkaç saniye bekle")
    last_text = str(messages[-1]["content"])[:2000]
    trimmed = [{"role": m.get("role", "user"), "content": str(m["content"])[:2000]} for m in messages[-8:]]

    async def events():
        started = time.perf_counter()
        try:
            ctx = await build_context(last_text)
            async for event in llm_analysis.stream_chat(
                ctx, trimmed, max_tokens=MAX_ANSWER_TOKENS, system_override=SYSTEM_PROMPT,
            ):
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.warning("forex sohbet hatası: %s", exc)
            yield f"event: error\ndata: {json.dumps({'error': 'Yanıt üretilemedi, tekrar dene'}, ensure_ascii=False)}\n\n"
        finally:
            logger.info("forex sohbet: %.2f sn", time.perf_counter() - started)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
