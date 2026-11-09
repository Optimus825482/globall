"""GEOMETRİ GÖLGESİ — alternatif stop/hedef varyantını GERÇEK değerlendirmeye sokar (2026-11-09)

NEDEN VAR
---------
§14'teki karşı-olgusal backtest şunu gösterdi: mevcut geometri (SL %1,5 / hedef
≈%2,4) brüt break-even için **%38,5 isabet** isterken aday havuzu %28 veriyor;
**hiçbir hedef/olasılık varyantı** EV'yi pozitife çeviremiyor. Ama o analiz
`mfe_pct` üzerinden yapıldı ve **sıralama** (stop mu önce, hedef mi?) bilgisini
taşımıyordu — alt/üst sınır aralığı veriyordu.

Bu modül o sınırı kaldırır: alternatif geometriyi **gerçek bar penceresi** üzerinde,
gerçek değerlendirme döngüsünün kullandığı **aynı** `_first_stop_or_target_bar`
fonksiyonuyla (belirsiz barda SL kabul eden muhafazakâr sözleşme) hesaplar.
Yani karşı-olgusal değil, **ölçüm**.

VARSAYILAN VARYANT: SL **%0,9**, hedef **ATR×4**
-----------------------------------------------
* SL %0,9 — §14'te ölçülen geometri: mevcut isabet ve hedefle brüt break-even
  için gereken stop ≈ %0,94. %0,9 bunun en yakın yuvarlak değeri.
* Hedef ATR×4 — `target_pct`'yi **olasılıktan tamamen ayırır** (§13 bozukluğu),
  oynaklığa bağlar. §14'te ATR×4 en yakın EV'yi veren ATR çarpanıydı.
* Hedef [%0,4 … %6,0] aralığına kırpılır: ATR aşırı küçük/büyük olduğunda
  anlamsız hedefler üretilmesin (ör. ATR %0,05 → %0,2 hedef komik, maliyet %0,35).

KARAR DEĞİŞMEZ
--------------
Bu modül **hiçbir kararı etkilemez**. Sonuç `outcome_details.shadow_geometry`
altına yazılır; gerçek `target_pct`/`stop`/`net_pct` alanlarına dokunulmaz.
`GEOMETRY_SHADOW_ENABLED=0` ile tamamen kapanır.

2-3 hafta sonra karşılaştırma:
    SELECT outcome_details->'shadow_geometry'->>'status_reason' sr, COUNT(*),
           AVG((outcome_details->'shadow_geometry'->>'net_pct')::float) ev
      FROM velocity_candidates
     WHERE outcome_details ? 'shadow_geometry'
     GROUP BY 1;
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from app.config import config

#: `_first_stop_or_target_bar` ile AYNI sözleşme: (durum, bar) döndürür.
FirstHitFn = Callable[[Sequence[Sequence[Any]], float, float, float],
                      "tuple[Optional[str], Optional[Sequence[Any]]]"]


def _f(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None  # NaN/inf ele


def enabled() -> bool:
    return bool(getattr(config, "GEOMETRY_SHADOW_ENABLED", True))


def params() -> dict[str, float | bool]:
    return {
        "enabled": enabled(),
        "sl_pct": float(getattr(config, "GEOMETRY_SHADOW_SL_PCT", 0.9)),
        "atr_mult": float(getattr(config, "GEOMETRY_SHADOW_ATR_MULT", 4.0)),
        "target_min_pct": float(getattr(config, "GEOMETRY_SHADOW_TARGET_MIN", 0.4)),
        "target_max_pct": float(getattr(config, "GEOMETRY_SHADOW_TARGET_MAX", 6.0)),
    }


def target_pct_for(atr_pct: Any) -> float | None:
    """ATR'den gölge hedefi üret (olasılıktan BAĞIMSIZ), aralığa kırp.

    ATR okunamıyorsa ``None`` — uydurma hedef üretilmez (kayıt `skipped` olur).
    """
    atr = _f(atr_pct)
    if atr is None or atr <= 0:
        return None
    p = params()
    return round(min(float(p["target_max_pct"]), max(float(p["target_min_pct"]),
                                                      atr * float(p["atr_mult"]))), 4)


def evaluate(*, window: Sequence[Sequence[Any]], entry: Any, atr_pct: Any,
             cost_pct: float, first_hit_fn: FirstHitFn,
             now_ms: int, due_ms: int) -> dict[str, Any]:
    """Alternatif geometriyi AYNI pencere üzerinde değerlendir (karar etkilemez).

    Döndürür: `outcome_details.shadow_geometry` altına yazılacak sözlük.
    Gerçek alanlara DOKUNMAZ; `first_hit_fn` gerçek değerlendirmenin kullandığı
    fonksiyondur (aynı belirsizlik sözleşmesi → ölçüm tutarlı).
    """
    p = params()
    out: dict[str, Any] = {
        "variant": "sl0.9_atrx4",
        "enabled": bool(p["enabled"]),
        "sl_pct": p["sl_pct"],
        "atr_mult": p["atr_mult"],
    }
    if not p["enabled"]:
        out["skipped"] = "disabled"
        return out

    entry_f = _f(entry)
    target = target_pct_for(atr_pct)
    out["atr_pct"] = _f(atr_pct)
    out["target_pct"] = target
    out["bars"] = len(window or [])
    if entry_f is None or entry_f <= 0 or target is None:
        out["skipped"] = "entry/atr gecersiz"
        out["status_reason"] = None
        return out

    sl_pct = float(p["sl_pct"])
    first_hit, hit_bar = first_hit_fn(window, entry_f, target, sl_pct)
    hit_target = first_hit == "take_profit"
    hit_stop = first_hit == "stop_loss"
    expired = int(now_ms) >= int(due_ms)
    ambiguous = bool(
        hit_stop and hit_bar is not None
        and (float(hit_bar[2]) / entry_f - 1) * 100 >= target
    )

    if hit_target:
        out.update({"status_reason": "TARGET_HIT", "exit_pct": round(target, 4),
                    "net_pct": round(target - cost_pct, 4),
                    "intrabar_ambiguous": False, "hit_sec": _sec_of(hit_bar, window)})
    elif hit_stop:
        out.update({"status_reason": "STOPPED_OUT", "exit_pct": round(-sl_pct, 4),
                    "net_pct": round(-sl_pct - cost_pct, 4),
                    "intrabar_ambiguous": ambiguous, "hit_sec": _sec_of(hit_bar, window)})
    elif expired:
        # Gerçek değerlendirmedeki kapanış kuralıyla aynı: son mumun kapanışı.
        last_close = _f(window[-1][4]) if window and len(window[-1]) > 4 else None
        exit_pct = None if last_close is None else (last_close / entry_f - 1) * 100
        out.update({"status_reason": "MAX_HORIZON_EXPIRED",
                    "exit_pct": None if exit_pct is None else round(exit_pct, 4),
                    "net_pct": None if exit_pct is None else round(exit_pct - cost_pct, 4),
                    "intrabar_ambiguous": False})
    else:
        out.update({"status_reason": "PENDING", "exit_pct": None, "net_pct": None})
    return out


def _sec_of(bar: Optional[Sequence[Any]], window: Sequence[Sequence[Any]]) -> int | None:
    """Temasın sinyalden kaç saniye sonra olduğu (bar açılış zamanından)."""
    if bar is None or not window:
        return None
    try:
        start = int(window[0][0])
        return max(0, int((int(bar[0]) + 59_999 - start) / 1000))
    except (TypeError, ValueError, IndexError):
        return None
