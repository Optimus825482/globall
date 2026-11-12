"""BİLEŞİK SENTIMENT ENDEKSİ — parite başına −100…+100 (2026-11-12)

Erkan'ın tanımı: "haber + ekonomik veri + temel göstergelerin analizi; ortası 0,
sol SHORT, sağ LONG; yüzde olarak hangi tarafa ne kadar yakın".

HAM VERİ UYDURULMAZ — depoda zaten olan dört kanal birleştirilir:
  1. **Takvim/haber**   → `forex_news_bias.bias_for`  (açıklanmış olayların
     beklentiye göre yönü; yalnız `actual` dolu olanlar, spekülasyon yok)
  2. **Temel/pozisyon** → `cot_positions.summary`     (CFTC net pozisyon, %OI)
  3. **Küresel nabız**  → `market_pulse.summary`      (DXY, ABD 10Y, VIX, S&P)
  4. **Kalabalık**      → `retail_sentiment.summary`  (Myfxbook perakende; TERS yön)

DÖRT KURAL (disiplin)
---------------------
* **BAĞLAMDIR, KAPI DEĞİL.** Karar akışını, lotu, radar sıralamasını DEĞİŞTİRMEZ.
* **Kapsam şeffaf:** veri olmayan bileşen skora girmez; `coverage` oranı ve
  `missing` listesi döner. Eksik veri "nötr" sayılmaz — ağırlığı düşer.
* **Ağırlıklar yargıdır, kanıt değil.** Varsayılanlar aşağıda; `WEIGHTS` ile
  tek yerden değişir. Ölçülmüş bir kenar DEĞİL — ölçüm yolu: skoru logla,
  ileri getiriyle IC'ye bak (`scripts/sentiment_index_edge.py`).
* **Yön kuralı tek yerde:** `symbol_currencies` + USD/risk haritası; her bileşen
  aynı işaret kuralına uyar (+ = LONG, − = SHORT).

Semboller: FX pariteleri, XAUUSD (altın), endeksler (risk iştahı), kripto.
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Bileşen ağırlıkları (yargı — kanıt değil). Toplam normalize edilir.
WEIGHTS: Dict[str, float] = {
    "takvim": float(os.getenv("SENT_WEIGHT_TAKVIM", "0.35")),
    "cot": float(os.getenv("SENT_WEIGHT_COT", "0.20")),
    "kuresel": float(os.getenv("SENT_WEIGHT_KURESEL", "0.25")),
    "perakende": float(os.getenv("SENT_WEIGHT_PERAKENDE", "0.20")),
}
#: |skor| bu eşiğin altındaysa "dengeli/nötr" etiketi (görüntü ayarı).
#: Ekonomik veri penceresi (sn) — endeks için 24 saat: "son günün verisi".
CAL_WINDOW_SEC = float(os.getenv("SENT_CAL_WINDOW_H", "24")) * 3600.0
#: Yarı-ömür (sn): 8 saatlik eski veri yarı ağırlıkla sayılır.
CAL_HALFLIFE_SEC = float(os.getenv("SENT_CAL_HALFLIFE_H", "8")) * 3600.0
NEUTRAL_BAND = float(os.getenv("SENT_NEUTRAL_BAND", "20"))
#: Bu eşiğin üstü "belirgin eğilim" (görüntü ayarı).
STRONG_BAND = float(os.getenv("SENT_STRONG_BAND", "45"))

_CCY = ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD")
#: Risk iştahından beslenen "risk-on" para birimleri / varlıklar
_RISK_ON = {"AUD", "NZD", "CAD", "BTC", "ETH", "XRP"}
_RISK_OFF = {"JPY", "CHF", "XAU", "USD"}
#: Endeks benzeri semboller: yön tamamen risk iştahına bağlı
_INDEX_LIKE = ("US30", "NAS100", "US2000", "JP225", "UK100", "DE40", "GER40",
               "HK50", "SWI20", "AUS200", "SPX", "USTEC")


def _clamp(v: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _scaled(chg_pct: Optional[float], full_at: float) -> Optional[float]:
    """Yüzde değişimi −100…+100'e ölçekler (`full_at` = ~%76 güce denk hareket).

    `tanh` kullanılır, kelepçe değil: sert günler (±%1+ DXY) bileşenin TAMAMINI
    ele geçirmesin, ama yön bilgisi korunsun. Kelepçe (clamp) denendi ve tek bir
    bileşenin skoru ±100'e sabitleyip diğer üç bileşeni gölgelemesine yol açtı.
    """
    if chg_pct is None:
        return None
    try:
        return 100.0 * math.tanh(float(chg_pct) / max(1e-9, full_at))
    except (TypeError, ValueError):
        return None


def split_symbol(symbol: str) -> Tuple[Optional[str], Optional[str]]:
    """EURUSD → (EUR, USD). Tanınmayan/base'i USD olmayan kripto için (None, None)."""
    s = str(symbol or "").upper().strip()
    for i in range(1, len(s)):
        a, b = s[:i], s[i:]
        if a in _CCY and b in _CCY:
            return a, b
    return None, None


def is_index_like(symbol: str) -> bool:
    s = str(symbol or "").upper()
    return any(s.startswith(k) for k in _INDEX_LIKE) or s in _INDEX_LIKE


def is_crypto(symbol: str) -> bool:
    s = str(symbol or "").upper()
    return any(s.startswith(k) for k in ("BTC", "ETH", "XRP", "SOL", "DOGE", "ADA"))


# ---------------------------------------------------------------- bileşenler
_CAL_CACHE: Dict[str, Any] = {"ts": 0.0, "by_symbol": {}, "events": 0}
_CAL_TTL = 120.0


def _iso_ts(v: Any) -> Optional[float]:
    """ISO-8601 (Z'li) → epoch. Ayrıştırılamazsa None (spekülasyon yok)."""
    if not v:
        return None
    txt = str(v).strip().replace("Z", "+00:00")
    try:
        import datetime as _dt
        return _dt.datetime.fromisoformat(txt).timestamp()
    except ValueError:
        return None


def refresh_calendar(events: List[Dict[str, Any]], now_ts: Optional[float] = None,
                     force: bool = False) -> Dict[str, Any]:
    """Son `CAL_WINDOW_SEC` içindeki AÇIKLANMIŞ verilerden sembol yönü (yaş ağırlıklı).

    Neden `forex_news_bias.bias_for` değil: o 30 dakikalık **ticaret filtresi**
    önbelleğidir; sentiment endeksi ise "son günün verisi" demek. Burada pencere
    24 saat ve ağırlık `0.5 ** (yaş / yarı_ömür)` ile azalıyor.
    Yalnız `actual` dolu ve ayrıştırılabilir olaylar kullanılır (spekülasyon yok).
    """
    now = float(now_ts if now_ts is not None else time.time())
    if not force and (now - float(_CAL_CACHE["ts"])) < _CAL_TTL:
        return _CAL_CACHE
    by_sym: Dict[str, List[Tuple[int, float, str, float]]] = {}
    n_used = 0
    try:
        from app import forex_news as fn
        from app.forex_news_bias import symbol_direction
    except Exception as exc:  # noqa: BLE001
        logger.debug("takvim bileşeni modülleri yok: %s", exc)
        return _CAL_CACHE
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        ts = _iso_ts(ev.get("date_iso"))
        if ts is None:
            continue
        age = now - ts
        if age < 0 or age > CAL_WINDOW_SEC:
            continue
        title = ev.get("original_title") or ev.get("title") or ""
        try:
            res = fn.evaluate_event_outcome(
                title, ev.get("forecast"), ev.get("previous"), ev.get("actual"))
        except Exception:  # noqa: BLE001
            continue
        if not res or not res.get("side"):
            continue
        cur = str(ev.get("currency") or ev.get("country") or "").upper().strip()
        try:
            syms = ev.get("affected_symbols") or fn.map_symbols_for_event(
                cur, str(ev.get("title") or ""))
        except Exception:  # noqa: BLE001
            syms = []
        w = 0.5 ** (age / max(1.0, CAL_HALFLIFE_SEC))
        for s_sym in syms or []:
            try:
                d = symbol_direction(cur, res.get("side") == "bullish", str(s_sym))
            except Exception:  # noqa: BLE001
                d = 0
            if not d:
                continue
            by_sym.setdefault(str(s_sym).upper(), []).append(
                (int(d), float(w), str(ev.get("title") or "")[:60], float(age)))
            n_used += 1
    _CAL_CACHE["ts"] = now
    _CAL_CACHE["by_symbol"] = by_sym
    _CAL_CACHE["events"] = n_used
    return _CAL_CACHE


def _component_calendar(symbol: str) -> Tuple[Optional[float], Dict[str, Any]]:
    """Açıklanmış ekonomik veriden yön (24s pencere, yaş ağırlıklı)."""
    c = _CAL_CACHE
    if not c["ts"]:
        return None, {"available": False,
                      "reason": "takvim henüz ısıtılmadı (refresh_calendar çağrılmadı)"}
    items = (c["by_symbol"] or {}).get(str(symbol).upper()) or []
    if not items:
        return None, {"available": False,
                      "reason": "son 24 saatte bu sembole yön veren açıklanmış veri yok"}
    wsum = sum(w for _d, w, _t, _a in items) or 1.0
    net = sum(d * w for d, w, _t, _a in items) / wsum          # -1..+1
    # Kanıt gücü: toplam ağırlık 2'ye ulaşınca tam güç (≈ birkaç taze olay)
    strength = min(1.0, wsum / 2.0)
    score = _clamp(100.0 * net * strength)
    last = sorted(items, key=lambda x: x[3])[0]
    return score, {
        "available": True,
        "events": len(items),
        "last_event": last[2],
        "age_hours": round(last[3] / 3600.0, 1),
        "detail": (f"{len(items)} açıklanmış olay (24s, yarı-ömür "
                   f"{CAL_HALFLIFE_SEC / 3600:.0f}s) · net {net:+.2f} · güç {strength:.2f}"),
    }


def _component_cot(symbol: str) -> Tuple[Optional[float], Dict[str, Any]]:
    """CFTC net pozisyon (bias −1…+1). USD satırı yoksa taban tek başına, yarı güç."""
    try:
        from app import cot_positions
        cur = (cot_positions.summary().get("currencies") or {})
    except Exception as exc:  # noqa: BLE001
        return None, {"available": False, "reason": f"modül: {type(exc).__name__}"}
    if not cur:
        return None, {"available": False, "reason": "COT verisi yok"}
    base, quote = split_symbol(symbol)
    if base is None:
        # Endeks/kripto: COT satırı yok → bileşen devre dışı (uydurulmaz).
        return None, {"available": False, "reason": "bu sembolde COT satırı yok"}
    def bias_of(c: str) -> Optional[float]:
        slot = cur.get(c)
        if not isinstance(slot, dict):
            return None
        try:
            return float(slot.get("bias"))
        except (TypeError, ValueError):
            return None
    b_base, b_quote = bias_of(base), bias_of(quote)
    if b_base is None and b_quote is None:
        return None, {"available": False, "reason": "iki para biriminde de COT yok"}
    if b_quote is None:
        # Bilinen boşluk: USD'nin COT satırı yok → taban tek başına, yarı güç.
        return _clamp(50.0 * b_base), {
            "available": True, "base": base, "quote_missing": quote,
            "detail": f"{base} bias {b_base:+.2f}; {quote} COT satırı yok → yarı güç",
        }
    if b_base is None:
        return _clamp(-50.0 * b_quote), {
            "available": True, "quote": quote, "base_missing": base,
            "detail": f"{quote} bias {b_quote:+.2f}; {base} COT satırı yok → yarı güç",
        }
    return _clamp(100.0 * (b_base - b_quote)), {
        "available": True, "base": base, "quote": quote,
        "detail": f"{base} {b_base:+.2f} − {quote} {b_quote:+.2f}",
    }


def _component_global(symbol: str) -> Tuple[Optional[float], Dict[str, Any]]:
    """DXY + ABD 10Y → USD yönü; S&P/VIX → risk iştahı. Sembole göre haritalanır."""
    try:
        from app import market_pulse
        s = market_pulse.summary()
    except Exception as exc:  # noqa: BLE001
        return None, {"available": False, "reason": f"modül: {type(exc).__name__}"}
    assets = s.get("assets") or {}
    if not s.get("available") or not assets:
        return None, {"available": False, "reason": s.get("reason") or "varlık nabzı yok"}

    def chg(key: str) -> Optional[float]:
        a = assets.get(key) or {}
        if not a.get("available"):
            return None
        try:
            return float(a.get("chg_pct"))
        except (TypeError, ValueError):
            return None

    # Ölçek (tipik günlük hareket): DXY %0,5 · 10Y %2,5 · S&P %1,2 · VIX %5
    usd_bits = [x for x in (_scaled(chg("dxy"), 0.5), _scaled(chg("us10y"), 2.5)) if x is not None]
    risk_bits = [x for x in (_scaled(chg("spx"), 1.2),
                             None if chg("vix") is None else -_scaled(chg("vix"), 5.0))
                 if x is not None]
    if not usd_bits and not risk_bits:
        return None, {"available": False, "reason": "DXY/10Y/S&P/VIX hiçbiri yok"}
    usd = sum(usd_bits) / len(usd_bits) if usd_bits else 0.0
    risk = sum(risk_bits) / len(risk_bits) if risk_bits else 0.0

    base, quote = split_symbol(symbol)
    if is_index_like(symbol):
        score, why = risk, f"risk iştahı {risk:+.0f}"
    elif is_crypto(symbol):
        # Kripto: risk-on + zayıf dolar destekler
        score, why = 0.7 * risk - 0.3 * usd, f"risk {risk:+.0f} − 0.3×USD {usd:+.0f}"
    elif str(symbol).upper().startswith(("XAU", "GOLD")):
        # Altın: zayıf dolar + risk-off
        score, why = -0.6 * usd - 0.4 * risk, f"−0.6×USD {usd:+.0f} − 0.4×risk {risk:+.0f}"
    elif base == "USD":
        score, why = 0.8 * usd - 0.2 * risk, f"0.8×USD {usd:+.0f} − 0.2×risk {risk:+.0f}"
    elif quote == "USD":
        score, why = -0.8 * usd + 0.2 * risk, f"−0.8×USD {usd:+.0f} + 0.2×risk {risk:+.0f}"
    elif base in _RISK_ON or quote in _RISK_OFF:
        score, why = 0.7 * risk - 0.3 * usd, f"0.7×risk {risk:+.0f} − 0.3×USD {usd:+.0f}"
    elif base in _RISK_OFF or quote in _RISK_ON:
        score, why = -0.7 * risk + 0.3 * usd, f"−0.7×risk {risk:+.0f} + 0.3×USD {usd:+.0f}"
    else:
        score, why = 0.0, "kur haritası yok (nötr)"
    return _clamp(score), {
        "available": True, "usd": round(usd, 1), "risk": round(risk, 1),
        "detail": why,
    }


def _component_retail(symbol: str) -> Tuple[Optional[float], Dict[str, Any]]:
    """Perakende kalabalığı TERS yönde okunur (contrarian)."""
    try:
        from app import retail_sentiment as rs
        try:
            rs.warm_sync()   # soğuk süreçte DB'deki son turu yükle (ağa çıkmaz)
        except Exception:  # noqa: BLE001
            pass
        s = rs.summary(symbol)
    except Exception as exc:  # noqa: BLE001
        return None, {"available": False, "reason": f"modül: {type(exc).__name__}"}
    if not s.get("available"):
        return None, {"available": False, "reason": s.get("reason") or "veri yok"}
    if s.get("symbol") is None:
        return None, {"available": False, "reason": "sembol Myfxbook kapsamında yok"}
    long_pct = float(s.get("long_pct") or 50.0)
    thin = bool(s.get("thin_sample"))
    score = _clamp(-(long_pct - 50.0) * 2.0)   # %88 long → −76
    if thin:
        score *= 0.5
    return score, {
        "available": True, "long_pct": long_pct, "positions": s.get("positions"),
        "thin_sample": thin,
        "detail": f"perakende %{long_pct:.0f} long → ters yön {score:+.0f}"
                  + (" (ince örneklem, yarı güç)" if thin else ""),
    }


def summarize(symbol: str) -> Dict[str, Any]:
    """Tek sembolün bileşik sentiment skoru (−100 SHORT … +100 LONG)."""
    sym = str(symbol or "").upper().strip()
    parts = {
        "takvim": _component_calendar(sym),
        "cot": _component_cot(sym),
        "kuresel": _component_global(sym),
        "perakende": _component_retail(sym),
    }
    comps: Dict[str, Dict[str, Any]] = {}
    num = wsum = 0.0
    total_w = sum(WEIGHTS.values()) or 1.0
    for name, (score, meta) in parts.items():
        w = float(WEIGHTS.get(name, 0.0))
        avail = score is not None
        comps[name] = {
            "score": round(score, 1) if avail else None,
            "weight": w,
            "available": avail,
            **meta,
        }
        if avail:
            num += w * float(score)
            wsum += w
    score = round(num / wsum, 1) if wsum > 0 else 0.0
    coverage = round(wsum / total_w, 3)
    if abs(score) < NEUTRAL_BAND:
        label = "DENGELİ (nötr bant)"
    elif score > 0:
        label = "LONG eğilim" + (" (belirgin)" if score >= STRONG_BAND else "")
    else:
        label = "SHORT eğilim" + (" (belirgin)" if score <= -STRONG_BAND else "")
    missing = [k for k, v in comps.items() if not v["available"]]
    return {
        "symbol": sym,
        "score": score,
        "label": label,
        "coverage": coverage,
        "missing": missing,
        "components": comps,
        "note": (f"Bileşik sentiment {score:+.0f}/100 ({label}); kapsam %{coverage * 100:.0f}. "
                 "Bu bir KAPI değil, bağlamdır — karar akışını değiştirmez."
                 + (f" Eksik bileşen: {', '.join(missing)}." if missing else "")),
        "weights": dict(WEIGHTS),
    }


def compact_lines(symbol: str) -> List[str]:
    """LLM bağlamı için tek satır (büyüklük + bileşen kırılımı)."""
    s = summarize(symbol)
    bits = [f"{k} {v['score']:+.0f}" for k, v in s["components"].items()
            if v["available"]]
    return [
        f"Bileşik sentiment {s['symbol']}: {s['score']:+.0f}/100 ({s['label']}) · "
        + (" · ".join(bits) if bits else "bileşen yok")
        + f" · kapsam %{s['coverage'] * 100:.0f}"
    ]


def summarize_many(symbols: List[str]) -> List[Dict[str, Any]]:
    return [summarize(s) for s in symbols if str(s or "").strip()]
