"""Ekonomik takvim açıklamalarından SEMBOL BAZLI YÖN çıkarımı (2026-10-14).

Kullanıcı talebi: "açıklanan ekonomik veri o sembolde BUY yönünü destekliyorsa
filtreler kaldırılıp işlem açılsın; karşıt yönde ise radar sinyali engellensin."

Bu modül kararı VERMEZ, yalnız **yön kanıtı** üretir. Karar `forex.py` giriş
zincirinde verilir ve ayarla kapatılabilir.

Sözleşme:
  * Yalnız **AÇIKLANMIŞ** olaylar kullanılır (`actual` dolu ve ayrıştırılabilir).
    Beklenti/önceki değerle spekülasyon YAPILMAZ — kullanıcı "açıklandıktan sonra" dedi.
  * Yön, `forex_news.evaluate_event_outcome` ile bulunur (birim kapısı ve ters
    yorumlanan aileler orada zaten doğrulanmış — TÜFE/faiz düz, işsizlik/başvuru ve
    petrol stokları ters).
  * Para birimi gücü → sembol yönü eşlemesi `forex_news.format_pair_directional_impacts`
    ile AYNI kuraldır (tek kaynak orada; burada sayısal karşılığı).
  * Yönü savunulamayan sembol (endeksler, XAUUSD×AUD) **nötr** döner: otonom işlem
    için kanıtsız yön kullanılmaz.
"""

from __future__ import annotations

import datetime
import time
from typing import Any, Dict, List, Optional

try:
    from app import forex_news
except ImportError:  # pragma: no cover - paket dışı çalıştırma
    from . import forex_news  # type: ignore


# Açıklamadan sonra yönün geçerli sayıldığı varsayılan pencere (15 dakika = 900 sn).
# Radar ve aktif taramalarda 30 dakika (1800 sn) besleyici olarak parametrik çağrılır.
DEFAULT_WINDOW_SEC = 900.0


def symbol_direction(currency: str, is_bullish: bool, symbol: str) -> int:
    """Para birimi güçleniyorsa sembolün hangi yönü desteklenir?

    Döner: +1 (BUY desteklenir) · -1 (SELL desteklenir) · 0 (belirsiz/nötr).
    """
    c = (currency or "").upper().strip()
    sym = (symbol or "").upper().strip()
    if not c or not sym:
        return 0

    # Ham petrol: USD güçlenince petrol ↓, CAD güçlenince ↑
    if sym == "USOIL":
        if c == "CAD":
            return 1 if is_bullish else -1
        if c == "USD":
            return -1 if is_bullish else 1
        return 0

    # Altın: USD güçlenince XAUUSD ↓, USD zayıflayınca XAUUSD ↑
    if sym == "XAUUSD":
        if c == "USD":
            return -1 if is_bullish else 1
        return 0

    # Bitcoin: USD güçlenince BTCUSD ↓, USD zayıflayınca BTCUSD ↑
    if sym == "BTCUSD":
        if c == "USD":
            return -1 if is_bullish else 1
        return 0

    # Endeksler ve XAUUSD×AUD: yön savunulamaz → nötr (karışık makro tepki)
    if sym in ("US30", "NAS100"):
        return 0
    if sym == "XAUUSD" and c == "AUD":
        return 0

    # Standart 6 karakterli pariteler (BASE + QUOTE)
    if len(sym) == 6 and sym[:3].isalpha() and sym[3:].isalpha():
        base, quote = sym[:3], sym[3:6]
        if c == base:
            return 1 if is_bullish else -1
        if c == quote:
            return -1 if is_bullish else 1
        return 0

    return 0


def _iso_to_ts(iso: Any) -> Optional[float]:
    """ISO-8601 ('2026-10-08T18:00:00Z') → epoch saniye; ayrıştırılamazsa None."""
    if not iso:
        return None
    s = str(iso).strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def released_biases(
    events: List[Dict[str, Any]],
    now_ts: float,
    window_sec: float = DEFAULT_WINDOW_SEC,
) -> Dict[str, Dict[str, Any]]:
    """Açıklanmış + penceredeki olaylardan sembol başına net yön üretir.

    Dönen sözlük: {SEMBOL: {"dir": -1|0|1, "hits": n, "remaining_sec": int, "remaining_min": float, "events": [...]}}
    Aynı sembole zıt yönde iki olay düşerse `dir` 0'a döner (çelişki = kanıt yok).
    """
    out: Dict[str, Dict[str, Any]] = {}
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        ev_ts = _iso_to_ts(ev.get("date_iso"))
        if ev_ts is None:
            continue
        age = float(now_ts) - ev_ts
        # age < 0 → henüz açıklanmadı; age > pencere → bayat.
        if age < 0 or age > window_sec:
            continue

        title = ev.get("original_title") or ev.get("title") or ""
        res = forex_news.evaluate_event_outcome(
            title, ev.get("forecast"), ev.get("previous"), ev.get("actual"))
        if not res or not res.get("side"):
            continue  # açıklanmamış / ayrıştırılamayan / beklentiye uygun → yön yok
        is_bullish = res.get("side") == "bullish"

        cur = str(ev.get("currency") or ev.get("country") or "").upper().strip()
        syms = ev.get("affected_symbols") or forex_news.map_symbols_for_event(
            cur, str(ev.get("title") or ""))
        
        rem_sec = max(0, int(window_sec - age))
        rem_min = round(rem_sec / 60.0, 1)

        for s in syms or []:
            d = symbol_direction(cur, is_bullish, str(s))
            if d == 0:
                continue
            slot = out.setdefault(str(s).upper(), {
                "dir": 0,
                "hits": 0,
                "remaining_sec": rem_sec,
                "remaining_min": rem_min,
                "events": []
            })
            slot["dir"] += d
            slot["hits"] += 1
            slot["remaining_sec"] = max(slot.get("remaining_sec", 0), rem_sec)
            slot["remaining_min"] = round(slot["remaining_sec"] / 60.0, 1)
            slot["events"].append({
                "title": ev.get("title"),
                "currency": cur,
                "side": res.get("side"),
                "label": res.get("label_tr"),
                "direction": d,
                "age_sec": int(age),
                "remaining_sec": rem_sec,
                "remaining_min": rem_min,
            })

    for slot in out.values():
        raw = slot["dir"]
        slot["dir"] = 1 if raw > 0 else (-1 if raw < 0 else 0)
        slot["raw"] = raw
    return out


# --- Kısa ömürlü bellek önbelleği (tarama döngüsü her adayda olay listesini
# yeniden hesaplamasın; takvim 5 dk TTL ile zaten önbellekli) ---------------
_CACHE: Dict[str, Any] = {"ts": 0.0, "biases": {}}
CACHE_TTL_SEC = 30.0


def refresh_biases(events: List[Dict[str, Any]], now_ts: Optional[float] = None,
                   window_sec: float = DEFAULT_WINDOW_SEC,
                   force: bool = False) -> Dict[str, Dict[str, Any]]:
    """`released_biases` sonucunu 30 sn boyunca önbellekten döner."""
    now = float(now_ts if now_ts is not None else time.time())
    if not force and (now - float(_CACHE["ts"])) < CACHE_TTL_SEC:
        return _CACHE["biases"]  # type: ignore[return-value]
    _CACHE["biases"] = released_biases(events, now, window_sec)
    _CACHE["ts"] = now
    return _CACHE["biases"]  # type: ignore[return-value]


def bias_for(symbol: str) -> Dict[str, Any]:
    """Önbellekten tek sembolün yönü; yoksa nötr sözlük."""
    slot = (_CACHE["biases"] or {}).get(str(symbol or "").upper())
    if not slot:
        return {"dir": 0, "hits": 0, "events": []}
    return slot
