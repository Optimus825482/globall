"""FX SEANS PENCERELERİ — likidite ve ölü bölge farkındalığı (2026-11-09)

NEDEN VAR
---------
Araştırmanın P2-10 maddesi "seans filtreleri" (Londra/NY geçişi) idi ve
`pandas_market_calendars` öneriliyordu. **Üretim imajında pandas YOK**
(`requirements.txt` bilinçli yalın: numpy + scikit-learn). FX seans sınırları
ise sabit UTC saatleridir — bunun için pandas'a ihtiyaç yok. Bu yüzden aynı
işlev **bağımlılıksız** (yalnız `datetime`) uygulandı.

NEDEN ÖNEMLİ (ölçülebilir etki)
------------------------------
1. **Ölü bölge** (21:00–01:00 UTC ve hafta sonu): spread genişler, hacim düşer,
   stop avı artar. Bu pencerede sinyal üretmek, gerçek kenar olsa bile
   maliyetle yenir. `liquidity_score` bu pencerede düşük döner.
2. **Londra/NY örtüşmesi** (12:00–16:00 UTC): günün en yüksek likiditesi;
   kırılım/momentum stratejileri burada daha az yanlış sinyal üretir.
3. **Seans açılış/kapanış ±15 dk**: spread sıçraması ve ilk dakika gürültüsü.
   `spread_risk_window` bu pencereleri işaretler.

KULLANIM
--------
Saf fonksiyonlar; yan etki yok, global durum yok → test etmesi kolay.
Çağıran (radar/analyzer) kararı kendi verir; bu modül **karar vermez**,
yalnız bağlam üretir.

    >>> from datetime import datetime, timezone
    >>> describe(datetime(2026, 11, 9, 13, 30, tzinfo=timezone.utc))["overlap"]
    True

NOT: Yaz saati (DST) bilinçli olarak YOK SAYILIR. Sabit UTC pencereleri
kullanmak, DST'yi takip eden kütüphanelere göre daha az sürpriz üretir
(Londra BST'de 07:00 UTC = 08:00 yerel; sınır yine sabit kalır). Bu bir
yaklaşımdır ve `LIQUIDITY_*` skorları da yaklaşıktır — kesin saat garantisi
değil, filtre bağlamıdır.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

#: Seans pencereleri — SABİT UTC. (başlangıç saati dahil, bitiş saati hariç)
SESSIONS: dict[str, tuple[time, time]] = {
    "asia": (time(0, 0), time(9, 0)),        # Tokyo
    "london": (time(7, 0), time(16, 0)),
    "new_york": (time(12, 0), time(21, 0)),
}

#: Londra ∩ New York — günün en likit penceresi.
OVERLAP = (time(12, 0), time(16, 0))

#: Ölü/tehlikeli likidite penceresi (NY kapanışı sonrası).
DEAD = (time(21, 0), time(23, 59, 59))

#: Seans sınırına bu kadar dakika kala/içinde spread riski işaretlenir.
SPREAD_RISK_MINUTES = 15

#: FX piyasası: Cuma 21:00 UTC kapanış → Pazar 21:00 UTC açılış.
WEEKEND_CLOSE_WEEKDAY = 4   # Cuma (Monday=0)
WEEKEND_OPEN_WEEKDAY = 6    # Pazar
WEEKEND_HOUR = 21

#: Skorlar — kaba ama sıralamayı doğru veren değerler.
LIQUIDITY_SCORES = {
    "overlap": 1.0,
    "london": 0.80,
    "new_york": 0.80,
    "asia": 0.50,
    "dead": 0.20,
    "closed": 0.0,
}


def _as_utc(dt: datetime | None) -> datetime:
    """Naif datetime'ı UTC kabul et; farklı saat dilimini UTC'ye çevir."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _in_window(t: time, window: tuple[time, time]) -> bool:
    start, end = window
    if start <= end:
        return start <= t < end
    return t >= start or t < end  # gece yarısını aşan pencere


def is_weekend_closed(dt: datetime) -> bool:
    """FX hafta sonu kapalı mı? (Cuma 21:00 UTC → Pazar 21:00 UTC)"""
    d = _as_utc(dt)
    wd = d.weekday()
    if wd == WEEKEND_CLOSE_WEEKDAY and d.hour >= WEEKEND_HOUR:
        return True
    if wd == 5:  # Cumartesi
        return True
    if wd == WEEKEND_OPEN_WEEKDAY and d.hour < WEEKEND_HOUR:
        return True
    return False


def active_sessions(dt: datetime | None = None) -> list[str]:
    """Aynı anda açık olan seansların listesi (boş = FX kapalı)."""
    d = _as_utc(dt)
    if is_weekend_closed(d):
        return []
    t = d.time()
    return [name for name, window in SESSIONS.items() if _in_window(t, window)]


def in_overlap(dt: datetime | None = None) -> bool:
    """Londra ∩ New York penceresinde mi?"""
    d = _as_utc(dt)
    if is_weekend_closed(d):
        return False
    return _in_window(d.time(), OVERLAP)


def is_dead_zone(dt: datetime | None = None) -> bool:
    """Düşük likidite bölgesi mi? (hafta sonu VEYA 21:00+ UTC)"""
    d = _as_utc(dt)
    if is_weekend_closed(d):
        return True
    return _in_window(d.time(), DEAD)


def liquidity_score(dt: datetime | None = None) -> float:
    """0.0 (kapalı) – 1.0 (Londra/NY örtüşmesi). Kaba likidite vekili."""
    d = _as_utc(dt)
    if is_weekend_closed(d):
        return LIQUIDITY_SCORES["closed"]
    if in_overlap(d):
        return LIQUIDITY_SCORES["overlap"]
    sessions = active_sessions(d)
    if not sessions:
        return LIQUIDITY_SCORES["dead"]
    if "london" in sessions:
        return LIQUIDITY_SCORES["london"]
    if "new_york" in sessions:
        return LIQUIDITY_SCORES["new_york"]
    if "asia" in sessions:
        return LIQUIDITY_SCORES["asia"]
    return LIQUIDITY_SCORES["dead"]


def _minutes_to(d: datetime, target: time) -> int:
    """`d`'den sonraki ilk `target` saatine kalan dakika (0..1439)."""
    now = d.replace(second=0, microsecond=0)
    tgt = now.replace(hour=target.hour, minute=target.minute)
    if tgt <= now:
        tgt += timedelta(days=1)
    return int((tgt - now).total_seconds() // 60)


def spread_risk_window(dt: datetime | None = None,
                       window_minutes: int = SPREAD_RISK_MINUTES) -> str | None:
    """Seans açılış/kapanışa çok yakınsa ``"open"``/``"close"``, değilse ``None``.

    ±15 dk içinde spread sıçraması ve ilk dakika gürültüsü beklenir; yeni giriş
    için en kötü zamandır (stop avı + kayma).
    """
    d = _as_utc(dt)
    if is_weekend_closed(d):
        return None
    minutes = d.hour * 60 + d.minute
    for window in SESSIONS.values():
        for edge in (window[0], window[1]):
            edge_min = edge.hour * 60 + edge.minute
            delta = abs(minutes - edge_min)
            delta = min(delta, 1440 - delta)  # gece yarısını aşan fark
            if delta <= window_minutes:
                return "open" if edge is window[0] else "close"
    return None


def describe(dt: datetime | None = None) -> dict[str, Any]:
    """Tek çağrıda seans bağlamı (radar/rapor yüzeyleri için)."""
    d = _as_utc(dt)
    sessions = active_sessions(d)
    overlap = in_overlap(d)
    dead = is_dead_zone(d)
    closed = is_weekend_closed(d)
    score = liquidity_score(d)
    risk = spread_risk_window(d)
    # Sıradaki açılışa kalan dakika (yalnız bilgi amaçlı).
    next_open_min = None
    if not closed:
        upcoming = [_minutes_to(d, w[0]) for w in SESSIONS.values()
                    if not _in_window(d.time(), w)]
        next_open_min = min(upcoming) if upcoming else None
    return {
        "utc": d.strftime("%Y-%m-%d %H:%M"),
        "sessions": sessions,
        "overlap": overlap,
        "dead_zone": dead,
        "market_closed": closed,
        "liquidity_score": round(score, 3),
        "spread_risk": risk,
        "next_session_open_min": next_open_min,
        "label": _label(sessions, overlap, dead, closed),
    }


def _label(sessions: list[str], overlap: bool, dead: bool, closed: bool) -> str:
    if closed:
        return "PİYASA KAPALI (hafta sonu)"
    if overlap:
        return "Londra+NY örtüşmesi (en likit)"
    if dead:
        return "Ölü bölge (düşük likidite)"
    if not sessions:
        return "Seans dışı"
    names = {"asia": "Asya", "london": "Londra", "new_york": "New York"}
    return " + ".join(names.get(s, s) for s in sessions)
