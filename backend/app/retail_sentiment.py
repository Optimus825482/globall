"""PERAKENDE KONUMLANMA (Myfxbook topluluk outlook) — 2026-11-12

NEDEN
-----
Kriptoda Binance türev verisi var (`derivatives_service`), FX'te **perakende
konumlanma** hiç yoktu. Kalabalığın hangi tarafta olduğu, fiyattan türetilemeyen
tek ücretsiz kitle verisi: EURUSD %88 long gibi bir okuma, "herkes aynı tarafta →
karşı yön riski" hipotezini ölçülebilir kılar.

KAYNAK (2026-11-12 canlı doğrulandı)
------------------------------------
Myfxbook ücretsiz API: `login.json` (e-posta+şifre → session) sonra
`get-community-outlook.json`. Anahtar yok; **ücretsiz sınır 100 istek/24s**.
Cloudflare düz `curl`ü 403'lüyor; `curl_cffi` + `impersonate="safari17_0"`
**HTTP 200** dönüyor (ForexFactory dersinin aynısı).
REDDEDİLENLER (bugün denendi): widget ucu `getOutlookData.json` anahtarsız ama
**boş** döndü; Dukascopy SWFX 403; FXSSI API 404; DailyFX 403.

DİSİPLİN
--------
* **BAĞLAMDIR, KAPI DEĞİL.** Karar akışını değiştirmez (COT/seans/varlık nabzı
  ile aynı sınıf). Kapıya çevirmek, "aşırı konumlanma → sonraki 24s getiri"
  ölçümü 6-8 hafta biriktikten sonra ve replay A/B ile olur.
* **Uydurma yok:** veri yoksa "veri yok" der, nötr saymaz.
* KOTA KORUMASI: tur aralığı en az `RET_SENT_MIN_INTERVAL` (varsayılan 30 dk =
  48 istek/gün), günlük sert tavan 90 istek. Aşımda ağa çıkmaz.
* Session IP'ye bağlı ve ~1 ay geçerli; DB'de tutulur, `Invalid session`
  gelince bir kez yeniden login denenir.

Kullanim (modül):
    from app import retail_sentiment as rs
    rs.refresh_blocking()          # turu tazeler (gerekirse)
    rs.compact_lines("EURUSD")     # LLM'e düz metin
    rs.summary("EURUSD")           # panel/araç sözlüğü
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Tur aralığı (sn). Ücretsiz kota 100/24s → 30 dk = 48 istek.
RET_SENT_MIN_INTERVAL = float(os.getenv("MYFXBOOK_MIN_INTERVAL", "1800"))
#: Günlük sert istek tavanı (kotanın altında güvenlik payı).
RET_SENT_DAILY_CAP = int(os.getenv("MYFXBOOK_DAILY_CAP", "90"))
#: Session yaşı (sn) — 30 gün; IP değişimi ayrıca hata ile yakalanır.
RET_SENT_SESSION_TTL = 30 * 86400.0
#: Kullanıcıya gösterilecek en az pozisyon (altında okuma gürültü).
RET_SENT_MIN_POSITIONS = int(os.getenv("MYFXBOOK_MIN_POSITIONS", "500"))
#: "Kalabalık" eşiği: tek taraf %70 ve üzeri (görüntü eşiği, işlem kuralı değil).
RET_SENT_CROWD_PCT = float(os.getenv("MYFXBOOK_CROWD_PCT", "70"))

_API = "https://www.myfxbook.com/api"

_lock = threading.Lock()
_state: Dict[str, Any] = {
    "fetched_at": None,       # son BAŞARILI çekim (epoch)
    "rows": {},               # {SYMBOL: satır}
    "session": None,
    "session_at": 0.0,
    "day": None,
    "day_calls": 0,
    "last_error": None,
    "last_attempt": None,
    "calls_total": 0,
}


def _creds() -> tuple[str, str]:
    email = (os.getenv("MYFXBOOK_EMAIL") or "").strip()
    pwd = (os.getenv("MYFXBOOK_PASSWORD") or "").strip()
    if email and pwd:
        return email, pwd
    # .env doğrudan okunur (üretimde ortam değişkeni gelir; gelmezse dosya yolu).
    try:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for line in open(os.path.join(root, "backend", ".env"), encoding="utf-8"):
            if line.startswith("MYFXBOOK_EMAIL="):
                email = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("MYFXBOOK_PASSWORD="):
                pwd = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return email, pwd


def _http():
    """curl_cffi oturumu (Cloudflare'ı geçen tek yol). Yoksa None → fail-closed."""
    try:
        from curl_cffi import requests as cr
    except Exception:  # noqa: BLE001
        return None
    return cr.Session(impersonate="safari17_0")


def _quota_ok() -> bool:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if _state["day"] != today:
        _state["day"] = today
        _state["day_calls"] = 0
    return _state["day_calls"] < RET_SENT_DAILY_CAP


def _login(sess) -> Optional[str]:
    email, pwd = _creds()
    if not (email and pwd):
        _state["last_error"] = "kimlik yok (MYFXBOOK_EMAIL/PASSWORD)"
        return None
    if not _quota_ok():
        _state["last_error"] = f"günlük kota doldu ({RET_SENT_DAILY_CAP})"
        return None
    try:
        _state["day_calls"] += 1
        _state["calls_total"] += 1
        r = sess.get(f"{_API}/login.json", params={"email": email, "password": pwd}, timeout=40)
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        _state["last_error"] = f"login hatası: {type(exc).__name__}"
        return None
    if data.get("error") or not data.get("session"):
        _state["last_error"] = f"login reddedildi: {str(data.get('message'))[:80]}"
        return None
    return str(data["session"])


def _fetch_outlook(sess, session: str) -> Optional[List[dict]]:
    if not _quota_ok():
        _state["last_error"] = f"günlük kota doldu ({RET_SENT_DAILY_CAP})"
        return None
    try:
        _state["day_calls"] += 1
        _state["calls_total"] += 1
        r = sess.get(f"{_API}/get-community-outlook.json",
                     params={"session": session}, timeout=40)
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        _state["last_error"] = f"outlook hatası: {type(exc).__name__}"
        return None
    if data.get("error"):
        msg = str(data.get("message") or "")
        if "session" in msg.lower():
            return "INVALID_SESSION"  # type: ignore[return-value]
        _state["last_error"] = f"outlook reddedildi: {msg[:80]}"
        return None
    return list(data.get("symbols") or [])


def _normalize(items: List[dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for it in items:
        sym = str(it.get("name") or "").strip().upper()
        if not sym:
            continue
        try:
            long_pct = float(it.get("longPercentage") or 0.0)
            short_pct = float(it.get("shortPercentage") or 0.0)
        except (TypeError, ValueError):
            continue
        tot = int(it.get("totalPositions") or 0)
        if long_pct <= 0 and short_pct <= 0:
            continue
        out[sym] = {
            "symbol": sym,
            "long_pct": round(long_pct, 1),
            "short_pct": round(short_pct, 1),
            "long_positions": int(it.get("longPositions") or 0),
            "short_positions": int(it.get("shortPositions") or 0),
            "total_positions": tot,
            "avg_long_price": float(it.get("avgLongPrice") or 0.0),
            "avg_short_price": float(it.get("avgShortPrice") or 0.0),
            "source": "myfxbook",
        }
    return out


def _load_session_from_db() -> Optional[str]:
    """Süreç yeniden başladığında DB'deki session'ı kullan (her restart'ta login = kota)."""
    try:
        from app import database
        import asyncio
        data = asyncio.run(database.get_retail_sentiment_session())
    except Exception as exc:  # noqa: BLE001
        logger.debug("[RetailSentiment] session okunamadı: %s", exc)
        return None
    sess = str((data or {}).get("session") or "")
    created = float((data or {}).get("created_at") or 0.0)
    if sess and (time.time() - created) < RET_SENT_SESSION_TTL:
        _state["session"] = sess
        _state["session_at"] = created
        return sess
    return None


async def hydrate_if_empty() -> bool:
    """Bellek boşsa son turu DB'den yükle (ağa çıkmadan).

    İlk sayfa yüklemesi "veri yok" göstermesin: 30 dk'lık tur aralığında DB'de
    zaten taze satır vardır. DB de boşsa False döner (gerçekten veri yok).
    """
    if _state.get("rows"):
        return False
    try:
        from app import database
        data = await database.get_retail_sentiment_latest()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[RetailSentiment] hydrate hatası: %s", exc)
        return False
    rows = {}
    for r in (data or {}).get("rows") or []:
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        rows[sym] = {
            "symbol": sym,
            "long_pct": float(r.get("long_pct") or 0.0),
            "short_pct": float(r.get("short_pct") or 0.0),
            "long_positions": int(r.get("long_positions") or 0),
            "short_positions": int(r.get("short_positions") or 0),
            "total_positions": int(r.get("total_positions") or 0),
            "avg_long_price": float(r.get("avg_long_price") or 0.0),
            "avg_short_price": float(r.get("avg_short_price") or 0.0),
            "source": "myfxbook",
        }
    if rows:
        _state["rows"] = rows
        _state["fetched_at"] = (data or {}).get("fetched_at")
        return True
    return False


def refresh_blocking(force: bool = False) -> dict:
    """Turu tazeler (tur aralığından önce değil). Dönen değer durum özeti."""
    with _lock:
        now = time.time()
        last = _state["fetched_at"]
        if not force and last and (now - last) < RET_SENT_MIN_INTERVAL:
            return summary_status()
        _state["last_attempt"] = now
        sess = _http()
        if sess is None:
            _state["last_error"] = "curl_cffi yok (Cloudflare için gerekli)"
            return summary_status()

        session = _state["session"]
        if not session or (now - float(_state["session_at"] or 0)) > RET_SENT_SESSION_TTL:
            session = _load_session_from_db() or _login(sess)
            if not session:
                return summary_status()
            _state["session"], _state["session_at"] = session, now
            _persist_session(session)

        items = _fetch_outlook(sess, session)
        if items == "INVALID_SESSION":
            session = _login(sess)
            if not session:
                return summary_status()
            _state["session"], _state["session_at"] = session, now
            _persist_session(session)
            items = _fetch_outlook(sess, session)
        if not items or items == "INVALID_SESSION":
            return summary_status()

        rows = _normalize(items)
        if not rows:
            _state["last_error"] = "yanıt geldi ama ayrıştırılabilir satır yok"
            return summary_status()
        _state["rows"] = rows
        _state["fetched_at"] = now
        _state["last_error"] = None
        _persist_rows(list(rows.values()), now)
        logger.info("[RetailSentiment] %d sembol çekildi (gün içi istek: %d)",
                    len(rows), _state["day_calls"])
        return summary_status()


def _persist_session(session: str) -> None:
    try:
        from app import database
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(database.save_retail_sentiment_session(session))
        else:
            asyncio.run(database.save_retail_sentiment_session(session))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[RetailSentiment] session kalıcılaştırılamadı: %s", exc)


def _persist_rows(rows: List[dict], ts: float) -> None:
    try:
        from app import database
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(database.save_retail_sentiment(rows, ts))
        else:
            asyncio.run(database.save_retail_sentiment(rows, ts))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[RetailSentiment] geçmiş yazılamadı: %s", exc)


def _row_for(symbol: Optional[str]) -> Optional[dict]:
    if not symbol:
        return None
    s = str(symbol).strip().upper()
    rows = _state.get("rows") or {}
    if s in rows:
        return rows[s]
    # Broker adı farkı (USTEC/NAS100) ve altın kısaltması
    alias = {"USTEC": "NAS100", "GOLD": "XAUUSD", "GER40": "DE40", "GER30": "DE40"}
    return rows.get(alias.get(s, ""))


def summary(symbol: Optional[str] = None) -> Dict[str, Any]:
    """Panel/araç yüzeyi. `available=False` ise sebep yazılır, nötr SAYILMAZ."""
    ts = _state.get("fetched_at")
    rows = _state.get("rows") or {}
    if not ts or not rows:
        return {
            "available": False,
            "reason": _state.get("last_error") or "henüz çekim yapılmadı",
            "source": "myfxbook",
            "fetched_at": None,
            "age_min": None,
            "calls_today": _state.get("day_calls", 0),
            "daily_cap": RET_SENT_DAILY_CAP,
            "min_interval_min": RET_SENT_MIN_INTERVAL / 60.0,
        }
    row = _row_for(symbol)
    base = {
        "available": True,
        "source": "myfxbook",
        "fetched_at": float(ts),
        "age_min": round((time.time() - float(ts)) / 60.0, 1),
        "symbols": len(rows),
        "calls_today": _state.get("day_calls", 0),
        "daily_cap": RET_SENT_DAILY_CAP,
        "min_interval_min": RET_SENT_MIN_INTERVAL / 60.0,
        "crowd_pct": RET_SENT_CROWD_PCT,
    }
    if row is None:
        base["symbol"] = None
        base["note"] = ("Bu sembol Myfxbook kapsamında yok (endeksler genelde yok); "
                        "uydurulmaz." if symbol else "Sembol verilmedi.")
        return base
    long_pct = float(row["long_pct"])
    thin = int(row.get("total_positions") or 0) < RET_SENT_MIN_POSITIONS
    crowded_long = long_pct >= RET_SENT_CROWD_PCT
    crowded_short = (100.0 - long_pct) >= RET_SENT_CROWD_PCT
    base.update({
        "symbol": row["symbol"],
        "long_pct": long_pct,
        "short_pct": float(row["short_pct"]),
        "positions": int(row.get("total_positions") or 0),
        "thin_sample": thin,
        "crowded": "LONG" if crowded_long else ("SHORT" if crowded_short else None),
        "contrarian": ("SHORT" if crowded_long else ("LONG" if crowded_short else None)),
        "avg_long_price": row.get("avg_long_price"),
        "avg_short_price": row.get("avg_short_price"),
    })
    return base


def summary_status() -> Dict[str, Any]:
    """Fetch sonrası durum (tur içi kullanım)."""
    return {
        "ok": bool(_state.get("fetched_at")),
        "fetched_at": _state.get("fetched_at"),
        "symbols": len(_state.get("rows") or {}),
        "error": _state.get("last_error"),
        "calls_today": _state.get("day_calls", 0),
        "calls_total": _state.get("calls_total", 0),
    }


def brief(symbol: Optional[str]) -> Dict[str, Any]:
    """Radar/fırsat yükü için TÜKETİME HAZIR kısa alan (yok ise boş sözlük).

    TEK KAYNAK: radar, fırsat taraması ve snapshot aynı biçimi kullanır.
    Boş sözlük = "bu sembolde kapsam/veri yok" — 0/nötr ile karıştırılmaz.
    """
    try:
        s = summary(symbol)
    except Exception:  # noqa: BLE001
        return {}
    if not s.get("available") or s.get("symbol") is None:
        return {}
    return {
        "long_pct": s["long_pct"],
        "short_pct": s["short_pct"],
        "positions": s.get("positions"),
        "crowded": s.get("crowded"),
        "contrarian": s.get("contrarian"),
        "thin_sample": bool(s.get("thin_sample")),
        "age_min": s.get("age_min"),
        "source": "myfxbook",
    }


def compact_lines(symbol: Optional[str] = None) -> List[str]:
    """LLM'e giden kısa satır(lar). BÜYÜKLÜK yazılır, "yüksek/düşük" yorumu LLM'e bırakılmaz."""
    s = summary(symbol)
    if not s.get("available"):
        return [f"Perakende konumlanma: YOK ({s.get('reason')}) — kalabalık yönü okunamadı, uydurulmaz."]
    if s.get("symbol") is None:
        return [f"Perakende konumlanma: {s.get('symbols')} sembol çekildi; "
                f"{symbol or 'sembol'} kapsamda yok (endeksler Myfxbook'ta yok)."]
    bits = [
        f"Perakende konumlanma (Myfxbook, {s['age_min']:.0f} dk önce, {s['positions']} pozisyon): "
        f"{s['symbol']} %{s['long_pct']:.0f} long / %{s['short_pct']:.0f} short"
    ]
    if s.get("crowded"):
        bits.append(f"KALABALIK {s['crowded']} (eşik %{RET_SENT_CROWD_PCT:.0f}) → karşı yön "
                    f"{s['contrarian']} riski; bu bir KAPI değil, bağlamdır.")
    if s.get("thin_sample"):
        bits.append(f"örneklem ince ({s['positions']} pozisyon < {RET_SENT_MIN_POSITIONS}) → okuma zayıf.")
    # Ortalama giriş fiyatı: kalabalığın maliyeti (fiyat o seviyenin altındaysa long'lar zararda)
    alp, asp = s.get("avg_long_price"), s.get("avg_short_price")
    if alp and asp:
        bits.append(f"ortalama giriş: long {alp:.5g} / short {asp:.5g}.")
    return [" ".join(bits)]


def ensure_fresh_async() -> None:
    """Arka planda tazeleme (istek yolunu bloklamadan). Tur aralığı içindeyse no-op."""
    last = _state.get("fetched_at")
    if last and (time.time() - float(last)) < RET_SENT_MIN_INTERVAL:
        return
    if _lock.locked():
        return
    threading.Thread(target=refresh_blocking, kwargs={"force": False},
                     name="retail-sentiment", daemon=True).start()
