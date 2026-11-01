"""Spot Monitor sinyalleri için LLM ikinci görüş dosyası (dossier).

Forex tarafındaki `llm_trade_review.build_dossier` desenini spot'a uyarlar:
teknik özet + mum yapısı + hacim bağlamı -> LLM'e tek bir inceleme isteği.

AYIRT EDİCİ TASARIM KARARI — bu modül İŞLEM ENGELLEMEZ:
Forex yolunda LLM kararı `blocked` bayrağıyla işlemi durdurabiliyor. Burada
yalnızca kayıt üretilir (`details.llm_review`). Gerekçe ölçüm, tahmin değil:
22 özellikli bir AI kapının dürüst walk-forward'da baz çizgiyi YENMEDİĞİ
ölçüldü (-0.25% kapılı vs -0.13% baz). Doğrulanmamış bir yargıcı işlem
akışına bağlamak, kayıp üretmenin en hızlı yoludur. Önce gölge kayıt toplanır,
sonuçlar karşılaştırılır, ancak ondan sonra kapı olur.

Maliyet disiplini: LLM çağrısı yalnızca KAPANAN pozisyonlar için değil,
sinyal üretildiği anda yapılır ve `llm_review` alanına yazılır. Sinyal başına
tek çağrı; önbellek yok çünkü her sinyal farklı sembol/zaman/özellik taşır.
Çağrı başarısız olursa sessizce `None` döner — inceleme eksikliği işlemi
durdurmaz.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

from app import llm_analysis

logger = logging.getLogger("scalper.spot_llm")

MAX_REVIEW_TOKENS = 1400

# Forex isteminin çekirdek ilkeleri korunur (çoklu zaman dilimi, haber riski,
# maliyet/R:R, seviyeler, korelasyon, rejim) ama spot diliyle yeniden yazılır.
# Trailing farkındalığı KORUNUR — forex'teki kripto notuyla aynı gerekçe.
SYSTEM_PROMPT = (
    "Sen 20+ yıl deneyimli, disiplinli bir kripto spot trader'ısın. Otonom bir "
    "tarayıcı Binance TR spot paritesinde KAĞIT (paper) işlem açmak üzere; "
    "senin görevin motorun körlüğünü yakalamak ve bu sinyali kısa ve dürüst "
    "biçimde değerlendirmek.\n"
    "Bu bir KAĞIT işlemdir ve KAYIT amaçlı incelenir; kararın uygulanmaz. "
    "Yine de gerçek bir trader gibi düşün: bu sinyal kârlı olur muydu?\n"
    "ÖNEMLİ (Trailing): Bu sistemde SABİT KÂR HEDEFİ (TP) YOKTUR. İşlem, kâr "
    "%1.5'e ulaşınca stop'u maliyet + %0.8'e kilitleyen ve sonrasında zirvenin "
    "%0.6 gerisinden gelen bir ZİRVE TAKİPÇİSİ ile yönetilir. 'tp' alanının "
    "boş/0 görünmesi bir eksiklik DEĞİLDİR; bu gerekçeyle olumsuz yargı verme.\n"
    "KONTROL LİSTESİ:\n"
    "1. Trend uyumu: işlem yönü kısa/orta vadeli trendle uyumlu mu? EMA20/EMA50 "
    "ilişkisi ve ADX trend gücü ne diyor? Yatay/çöp rejimde mi?\n"
    "2. Maliyet: round-trip komisyon, basabas kazanma oranını (basabas_wr) "
    "yukarı çeker. Sinyalin olası isabeti bu eşiğin üzerinde mi?\n"
    "3. Hacim: sinyal mumu gerçek katılım mı gösteriyor, yoksa hacimsiz bir "
    "sıçrama mı? RVOL ve vol_z bölümlerine bak.\n"
    "4. Aşırılık: RSI/MFI ve Bollinger konumu geç kalınmış girişe işaret ediyor mu?\n"
    "5. Volatilite: ATR yüzdesi stop mesafesiyle orantılı mı? Çok düşükse stop "
    "gürültüde kalır; çok yüksekse hedefler anlamsızlaşır.\n"
    "6. Sembol/strateji: aynı sembol bu stratejiyle yakın zamanda kaybettirdi mi?\n"
    "Yanıtını KISA tut ve şu JSON şemasıyla ver:\n"
    '{"verdict":"ONAY"|"TEMKIN"|"KARSI","confidence":0.0-1.0,'
    '"gerekce":"tek cümle", "risk":"tek cümle"}'
)


def _pct(value: Any, digits: int = 2) -> Optional[float]:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def build_spot_dossier(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Sinyal bağlamından LLM'e verilecek kompakt dosyayı kurar.

    `ctx` beklenen anahtarlar (hepsi opsiyonel; eksik olanlar yazılmaz):
      symbol, timeframe, strategy, strategy_label, entry_price, stop_price,
      sl_pct, break_even_wr, rsi, atr_pct, adx, range_pct, avg_vol_try,
      note, ml_hit_probability, ml_target_pct, heuristic_flags,
      ema20, ema50, mfi, vol_z, bb_width_pct, recent_results
    """
    dossier: Dict[str, Any] = {
        "varlik": "SPOT",
        "sembol": str(ctx.get("symbol", "")).upper(),
        "zaman_dilimi": ctx.get("timeframe"),
        "strateji": ctx.get("strategy_label") or ctx.get("strategy"),
        "yon": "LONG",
        "giris": _pct(ctx.get("entry_price"), 8),
        # TP YOK — aşağıdaki alan bilinçli olarak boş bırakılıyor ki LLM
        # "hedef eksik" diye olumsuz yargı vermesin (isteme de yazıldı).
        "tp_pct": None,
        "sl_pct": _pct(ctx.get("sl_pct")),
        "exit_model": "zirve takipçi stop (kâr %1.5'te devreye girer, %0.8 kilit, zirveden %0.6)",
        "basabas_wr_pct": _pct(ctx.get("break_even_wr"), 1),
        "maliyet": {
            "fee_mode": ctx.get("fee_mode"),
            "round_trip_pct": _pct(ctx.get("round_trip_pct")),
        },
        "gostergeler": {
            "rsi": _pct(ctx.get("rsi"), 1),
            "mfi": _pct(ctx.get("mfi"), 1),
            "adx": _pct(ctx.get("adx"), 1),
            "atr_pct": _pct(ctx.get("atr_pct")),
            "bb_width_pct": _pct(ctx.get("bb_width_pct")),
            "vol_z": _pct(ctx.get("vol_z"), 2),
            "ema20": _pct(ctx.get("ema20"), 8),
            "ema50": _pct(ctx.get("ema50"), 8),
        },
        "likidite": {
            "son20bar_aralik_pct": _pct(ctx.get("range_pct")),
            "ortalama_bar_hacmi_try": _pct(ctx.get("avg_vol_try"), 0),
        },
    }

    # Yalnızca anlamlı alanları bırak (None/boş gürültü istemi şişirir)
    dossier["gostergeler"] = {k: v for k, v in dossier["gostergeler"].items() if v is not None}
    dossier["likidite"] = {k: v for k, v in dossier["likidite"].items() if v is not None}

    if ctx.get("note"):
        dossier["motor_notu"] = str(ctx["note"])[:280]

    # Gerçek ML modeli varsa (artifact eğitilmişse) en değerli bağlam budur
    if ctx.get("ml_hit_probability") is not None:
        dossier["ml_modeli"] = {
            "hedefe_dokunma_olasiligi": _pct(ctx.get("ml_hit_probability"), 4),
            "tahmini_getiri_pct": _pct(ctx.get("ml_target_pct"), 3),
            "not": "5dk ileri ufuk; öğrenilmiş model, kural motoru değil",
        }
    if ctx.get("heuristic_flags"):
        dossier["kural_uyarilari"] = list(ctx["heuristic_flags"])[:5]
    if ctx.get("recent_results"):
        dossier["sembol_gecmisi"] = ctx["recent_results"]

    return dossier


def _parse_review(text: str) -> Optional[Dict[str, Any]]:
    """LLM yanıtından JSON incelemesini çıkarır; biçim bozuksa None."""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    verdict = str(data.get("verdict") or "").upper()
    if verdict not in ("ONAY", "TEMKIN", "KARSI"):
        return None
    out = {"verdict": verdict, "gerekce": str(data.get("gerekce") or "")[:240],
           "risk": str(data.get("risk") or "")[:240]}
    try:
        out["confidence"] = max(0.0, min(1.0, float(data.get("confidence"))))
    except (TypeError, ValueError):
        out["confidence"] = None
    return out


async def review_signal(ctx: Dict[str, Any], timeout: float = 12.0) -> Optional[Dict[str, Any]]:
    """Bir spot sinyalini LLM'e inceletir. ASLA exception fırlatmaz.

    Dönüş: {"verdict","confidence","gerekce","risk","model","at"} veya None.
    None = inceleme yapılamadı (LLM yapılandırılmamış, zaman aşımı, biçim
    hatası). Çağıran taraf None'ı normal karşılamalı — inceleme bir BONUS,
    işlem akışının zorunlu parçası değil.
    """
    dossier = build_spot_dossier(ctx)
    # `llm_trade_review._ask_once` ile aynı desen: stream_chat delta'larını
    # biriktir. `chat()` düz metin değil sözlük döndürür; akış API'si hem
    # model adını hem hata olayını taşıdığı için inceleme için doğrusu budur.
    messages = [{"role": "user",
                 "content": "Bu spot sinyalini incele ve YALNIZCA JSON döndür."}]
    parts: list[str] = []
    model = ""

    async def _run():
        nonlocal model
        async for ev in llm_analysis.stream_chat(
                dossier, messages, max_tokens=MAX_REVIEW_TOKENS,
                system_override=SYSTEM_PROMPT, accept_reasoning=True,
                fallback=False):
            if ev["event"] == "delta":
                parts.append(str((ev["data"] or {}).get("text", "")))
            elif ev["event"] == "error":
                raise RuntimeError(str((ev["data"] or {}).get("error") or "LLM hatası"))
            elif ev["event"] == "done":
                model = str((ev["data"] or {}).get("model") or "")

    try:
        await asyncio.wait_for(_run(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.info("[spot-llm] inceleme zaman aşımı: %s", ctx.get("symbol"))
        return None
    except Exception as exc:  # noqa: BLE001 - inceleme işlemi durdurmamalı
        logger.info("[spot-llm] inceleme başarısız %s: %s", ctx.get("symbol"), exc)
        return None

    parsed = _parse_review("".join(parts))
    if not parsed:
        logger.info("[spot-llm] yanıt biçimi çözülemedi: %s", ctx.get("symbol"))
        return None
    parsed["at"] = int(time.time())
    parsed["model"] = model
    return parsed
