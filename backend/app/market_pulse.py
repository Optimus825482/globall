"""KÜRESEL VARLIK NABZI — cross-asset LLM bağlamı (2026-11-09)

NEDEN VAR
---------
2026-11-09 LLM bağlam denetimi üç yüzeyin (dossier / fırsat taraması / sohbet)
fiyat·ATR·COT·seans·takvim·haber·DXY açısından zengin ama VIX, ABD tahvil
verimi ve altın/petrol gibi cross-asset serilerinde TAMAMEN boş olduğunu
gösterdi. "Finans piyasası uzmanı" rolü risk iştahı / faiz / emtia okuması
olmadan kalıcı uydurma davranışına açıktır.

KAYNAK SEÇİMİ (ölçümle — iddiayla değil; 2026-11-09 canlı test)
---------------------------------------------------------------
- Yahoo Finance v8 chart API: anahtarsız, UA'lı düz istekle 7/7 sembol canlı
  döndü (^VIX 20.65, DX-Y.NYB 101.902, ^TNX 4.876, GC=F, CL=F, ^GSPC,
  EURUSD=X). Proje zaten `forex_research._yahoo_candles` ile aynı API'yi
  kullanıyor → burada yeni HTTP yolu YAZILMADI, o yardımcı yeniden kullanıldı.
- stooq.com CSV: TÜM semboller 404 ("page does not exist") → KARA LİSTE
  (Investing.com 403 dersinin aynısı; tekrar denenmez).
- FRED / FMP: API anahtarı ister → çağrılmaz (kotaya takılan anahtarlı kaynağı
  yedek yapma dersi).

DÜRÜSTLÜK KURALLARI
-------------------
- Bir varlık çekilemezse satırı "veri yok"tur; nötr sanılmaz, uydurulmaz.
- Yorumlar sabit kural tablosudur (klasik makro okuma); büyüklükler sayılarla
  yazılır ki LLM "yüksek/düşük"i kendisi tartmasın.
- Bu modül KARAR VERMEZ, skor üretmez: BAĞLAMDIR — kanal ya da sinyal değil.
  Skorlamaya/kapıya sokmak ayrı ve ölçülmüş bir iş istemez (COT dersinin
  aynısı).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Yahoo çağrısı sembol başına 1 istek; 6 varlık × 4/çeyrek-saat ≈ 24 istek/sa.
#: Rate limit'e takılmayacak kadar az, LLM bağlamı için yeterince taze.
PULSE_TTL_SEC = 900.0

#: Değişim penceresi (günlük bar cinsinden): "son 5 işlem günü".
CHANGE_WINDOW = 5

#: (anahtar, Yahoo sembolü, etiket, tür). `tür` yorum kurallarını seçer;
#: "plain" sadece yön/büyüklük satırı üretir.
ASSETS: tuple[tuple[str, str, str, str], ...] = (
    ("vix", "^VIX", "VIX (risk iştahı)", "vix"),
    ("dxy", "DX-Y.NYB", "Dolar Endeksi", "dxy"),
    ("us10y", "^TNX", "ABD 10Y tahvil verimi", "us10y"),
    ("gold", "GC=F", "Altın (COMEX)", "plain"),
    ("oil", "CL=F", "WTI Petrol", "plain"),
    ("spx", "^GSPC", "S&P 500", "plain"),
)

_CACHE_LOCK = threading.Lock()
_CACHE: Optional[tuple[float, dict[str, Any]]] = None


def reset_cache() -> None:
    """Test ve manuel tazeleme için: önbelleği sıfırla."""
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None


def _fetch_candles(ticker: str) -> list[dict[str, float]]:
    """`forex_research._yahoo_candles`'a ince sarmalayıcı (hata izole et)."""
    try:
        from app.forex_research import _yahoo_candles
        return _yahoo_candles(ticker, "1d", "1mo")
    except Exception:  # noqa: BLE001 — tek varlık tüm nabzı öldürmemeli
        logger.info("varlık nabzı çekim hatası: %s", ticker, exc_info=True)
        return []


def _change_row(candles: list[dict[str, float]]) -> Optional[dict[str, float]]:
    """Son kapanış + `CHANGE_WINDOW` gün önce kapanış (yetersiz bar → None)."""
    closes = [c["close"] for c in candles if c.get("close")]
    if len(closes) <= CHANGE_WINDOW:
        return None
    last, prev = closes[-1], closes[-1 - CHANGE_WINDOW]
    if prev <= 0:
        return None
    # Yuvarlama: bu sözlük makro_baglam JSON'una gidiyor; ham float
    # (20.739999771...) LLM metninde ve health panelinde kirli görünür.
    return {"last": round(last, 4), "prev": round(prev, 4),
            "chg_pct": round((last / prev - 1.0) * 100.0, 2),
            "chg_abs": round(last - prev, 4)}


def _pct(x: float) -> str:
    """`%+0.45` biçimli Türkçe yüzde (mevcut rapor stili: işaret + 2 hane)."""
    return f"%{x:+.2f}".replace("+", "+").replace("-", "-")


def _vix_note(v: float, chg: float) -> str:
    """CBOE klasik eşikleri: <15 sakin, 15-20 normal, 20-25 gergin, >25 stres."""
    if v < 15:
        rejim = "sakin rejim — sıkışma kırılımları sahteleşebilir"
    elif v < 20:
        rejim = "normal gerginlik"
    elif v < 25:
        rejim = "gergin — risk iştahı tartılı"
    else:
        rejim = "STRES rejimi — yeni işlem açma boyutu küçültülmeli"
    return f"{rejim} (5g {_pct(chg)})"


def _dxy_note(chg: float) -> str:
    if chg > 1.0:
        return "dolar GÜÇLÜ baskı yönünde — majör FX ve altın için ağırlaşan karşı rüzgâr"
    if chg > 0.2:
        return "dolar hafif baskı yönünde"
    if chg < -1.0:
        return "dolar belirgin zayıf — majör FX ve altın için destek"
    if chg < -0.2:
        return "dolar hafif zayıf"
    return "dolar yatay"


def _rate_note(chg_pct: float, chg_abs: float) -> str:
    """^TNX yüzde cinsinden verir (2026-11-09 canlı ölçüm: 4.876 = %4.88)."""
    bp = chg_abs * 100  # 1 puan = 1% → 100 baz puan
    yon = "yükseliyor (USD'ye destek, riskli varlıklara baskı)" if bp > 0 else "düşüyor (risk-on rüzgârı)"
    return f"5g {chg_abs:+.2f} pp ({bp:+.0f} baz puan) — faiz beklentileri {yon}"


def _interpret(rows: dict[str, dict[str, Any]]) -> list[str]:
    """Sabit kural tablosu — uydurma yok, her not ölçülen sayıya bağlı."""
    notes: list[str] = []
    vix, dxy, y = rows.get("vix"), rows.get("dxy"), rows.get("us10y")
    gold, spx, oil = rows.get("gold"), rows.get("spx"), rows.get("oil")

    if vix:
        notes.append(f"VIX {vix['last']:.2f}: {_vix_note(vix['last'], vix['chg_pct'])}")
    if dxy:
        notes.append(f"DXY {dxy['last']:.2f}: {_dxy_note(dxy['chg_pct'])}")
    if y:
        notes.append(f"ABD 10Y %{y['last']:.2f}: {_rate_note(y['chg_pct'], y['chg_abs'])}")
    if gold:
        notes.append(f"Altın {gold['last']:.2f} USD (5g {_pct(gold['chg_pct'])})")
    if oil:
        notes.append(f"WTI petrol {oil['last']:.2f} USD (5g {_pct(oil['chg_pct'])})")
    if spx:
        notes.append(f"S&P 500 {spx['last']:.2f} (5g {_pct(spx['chg_pct'])})")

    # Çapraz okuma: yalnız İKİ tarafın da verisi VARSA kurulur (sessiz boşluk kuralı).
    if dxy and gold:
        if dxy["chg_pct"] > 0.2 and gold["chg_pct"] > 0.2:
            notes.append("Dolar ile altın BİRLİKTE yükseliyor → güvenli liman/ihtiyatlılık talebi baskın olabilir; "
                         "altın rallisini yalnız 'dolar zayıf' diye okuma.")
        elif dxy["chg_pct"] < -0.2 and gold["chg_pct"] < -0.2:
            notes.append("Dolar zayıflarken altın da düşüyor → likidite çekilmesi/temizliği şüphesi; klasik korelasyon bozuk.")
    if vix and spx and vix["chg_pct"] > 2.0 and spx["chg_pct"] < -1.0:
        notes.append("VIX yükselişi ile S&P düşüşü uyumlu → risk iştahı DARALIYOR; uzun (buy) fikirlerde kanıt eşiği artmalı.")
    return notes


def pulse(*, force: bool = False) -> dict[str, Any]:
    """Cross-asset anlık görüntü (TTL'li). Hata satır bazında izole edilir."""
    global _CACHE
    now = time.time()
    with _CACHE_LOCK:
        if not force and _CACHE and now - _CACHE[0] < PULSE_TTL_SEC:
            return _CACHE[1]

    assets: dict[str, Any] = {}
    for key, ticker, label, kind in ASSETS:
        row = _change_row(_fetch_candles(ticker))
        assets[key] = ({"label": label, "available": True, **row} if row
                       else {"label": label, "available": False,
                             "reason": f"{ticker} serisi çekilemedi/yetersiz"})
    ok = {k: v for k, v in assets.items() if v.get("available")}
    missing = [k for k, v in assets.items() if not v.get("available")]
    result: dict[str, Any] = {
        "available": bool(ok),
        "updated_at": now,
        "assets": assets,
        "missing": missing,
        "notes": _interpret(ok) if ok else [],
    }
    if not ok:
        result["reason"] = ("Yahoo chart API'ye ulaşılamadı — cross-asset bağlam yok "
                            "(risk iştahı/faiz/emtia uydurulmaz).")
    if missing:
        result["partial"] = True
    with _CACHE_LOCK:
        _CACHE = (now, result)
    return result


#: context_extras/health çağrılarının tek kapısı — ad, sözlük sözleşmesini taşır.
summary = pulse


def cached_summary() -> dict[str, Any]:
    """AĞ ÇAĞIRMADAN son nabzı ver (health/liveness yoluna güvenli).

    Health uçları ağa çıkmamalı (deploy-düzeltmesi dersi, routers/system.py).
    İlk ölçüm ilk LLM yüzeyi çağrısında ısınır.
    """
    with _CACHE_LOCK:
        if _CACHE is None:
            return {"available": False, "warming": True,
                    "reason": "ilk ölçüm bir LLM bağlam çağrısında yapılır"}
        return dict(_CACHE[1])


def compact_lines() -> list[str]:
    """LLM'e düz metin giden kısa satırlar (context_extras tüketir)."""
    s = summary()
    if not s.get("available"):
        return [f"Küresel varlık nabzı: {s.get('reason')}"]
    lines = ["Küresel varlık nabzı (son 5 işlem günü):"]
    for key, _ticker, _label, _kind in ASSETS:
        a = (s.get("assets") or {}).get(key) or {}
        if a.get("available"):
            if key == "us10y":
                lines.append(f"  ABD 10Y verim %{a['last']:.2f} ({a['chg_abs']:+.2f} pp)")
            else:
                lines.append(f"  {a.get('label', key)}: {a['last']:.2f} ({_pct(a['chg_pct'])})")
        else:
            # Savunmalı okuma: satırı silmemek için ASSETS'teki etikete düş.
            lines.append(f"  {a.get('label') or _label}: veri yok")
    lines.extend(f"  ↳ {n}" for n in (s.get("notes") or []))
    return lines
