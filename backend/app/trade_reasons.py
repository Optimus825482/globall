"""KAPANIŞ NEDENİ KANONİKLEŞTİRME — "SL ama kazanç" çelişkisini onarır (2026-11-09)

SORUN (ölçüldü)
---------------
MT5 işlem export'unda **240/276 işlem** "🛑 Zarar Durdur (SL)" etiketliydi ve
bunların **152'si KAZANÇ**. Kapanış nedeni alanı köprüden gelen serbest metindir;
EA trailing-stop / scalper-close kapanışlarını da "SL" diye işaretliyor.

NEDEN KRİTİK
------------
* "Çıkış kuralı A/B" ölçümü tam olarak kapanış nedenine dayanır → etiket bozuksa
  canlı veriyle hiçbir çıkış varyantı doğrulanamaz.
* Raporlarda "SL isabeti" gibi sayaçlar yanlış dolar.
* `app/routers/forex.py` içindeki `normalize_close_reason()` seri-SL sigortası
  `SL_HIT` bekler; kazançlı bir kapanışın SL sayılması sigortayı yanlış tetikler.

KURAL — kanıt önceliği
----------------------
1. **Fiyat kanıtı** varsa (entry/exit + sl/tp seviyeleri): çıkış SL'ye mi TP'ye mi
   yakın → kod oradan belirlenir (`source="price"`). En güvenilir yol.
2. **Metin kanıtı**: neden metnindeki anahtar kelimeler (trailing / kısmi / TP /
   SL / flip / gün sonu / manuel / scalper close).
3. **MANTIK KAPISI (bu modülün asıl işi):** kârlı bir işlem **SL_HIT olamaz** —
   zarar durdurma tanımı gereği kaybı sınırlar. Çelişki varsa metin trailing/kısmi
   diyorsa o koda, demiyorsa `OTHER_WIN`'e düşürülür ve `contradiction=True`
   işaretlenir. Aynı şekilde zararlı bir işlem `TP_HIT` olamaz.
4. Hiçbiri yoksa PnL işaretine göre `OTHER_WIN` / `OTHER_LOSS`, PnL yoksa `UNKNOWN`.

Bu fonksiyon **saf**tır (girdi → çıktı, yan etki yok) ve hiçbir kararı
değiştirmez; yalnız ölçüm/rapor alanını düzeltir.
"""
from __future__ import annotations

from typing import Any

#: Kanonik kodlar (CSV/DB'de makine-okur alan).
SL_HIT = "SL_HIT"
TP_HIT = "TP_HIT"
TRAILING = "TRAILING"
PARTIAL = "PARTIAL"
SCALPER_CLOSE = "SCALPER_CLOSE"
REVERSAL = "REVERSAL"
EOD = "EOD"
MANUAL = "MANUAL"
OTHER_WIN = "OTHER_WIN"
OTHER_LOSS = "OTHER_LOSS"
UNKNOWN = "UNKNOWN"

#: Kod → Türkçe etiket (UI/CSV). Metin eşleşmesinde de kullanılan adlar.
LABELS: dict[str, str] = {
    SL_HIT: "Zarar Durdur (SL)",
    TP_HIT: "Kâr Al (TP)",
    TRAILING: "İz Süren Stop (Trailing)",
    PARTIAL: "Kısmi Kâr (Partial)",
    SCALPER_CLOSE: "Scalper Kapanış",
    REVERSAL: "Trend Dönüşü (Flip)",
    EOD: "Zaman/Seans Sonu",
    MANUAL: "Manuel Kapatma",
    OTHER_WIN: "Diğer (Kazanç)",
    OTHER_LOSS: "Diğer (Kayıp)",
    UNKNOWN: "Bilinmiyor",
}

#: Sıra ÖNEMLİ: "trailing"/"kısmi" ifadeleri "stop"/"zarar" kelimesini de
#: içerebildiği için önce onlar denenir.
_NEEDLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (TRAILING, ("trailing", "iz süren", "iz suren", "takipçi", "takipci", "chandelier")),
    (PARTIAL, ("partial", "kısmi", "kismi")),
    (REVERSAL, ("flip", "reversal", "dönüş", "donus")),
    (EOD, ("eod", "gün sonu", "gun sonu", "seans", "zaman sınırı", "zaman siniri", "time limit")),
    (MANUAL, ("manuel", "manual")),
    (SCALPER_CLOSE, ("scalper close", "scalper kapanış", "scalper kapanis")),
    (TP_HIT, ("kâr al", "kar al", "take profit", "tp hit", "(tp)")),
    (SL_HIT, ("zarar durdur", "zarar kes", "stop loss", "sl hit", "(sl)")),
)

#: Fiyat kanıtında "seviyeye değdi" sayılan göreli tolerans.
PRICE_TOLERANCE_RATIO = 0.0008  # fiyatın %0.08'i


def _f(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN ele


def _code_from_text(reason_text: str) -> str | None:
    text = str(reason_text or "").strip().lower()
    if not text:
        return None
    for code, needles in _NEEDLES:
        if any(n in text for n in needles):
            return code
    return None


def _code_from_price(*, direction: str | None, exit_price: float | None,
                     sl_price: float | None, tp_price: float | None) -> str | None:
    """Çıkış fiyatı SL/TP seviyesine değdi mi? (en güvenilir kanıt)"""
    if exit_price is None:
        return None
    tol = abs(exit_price) * PRICE_TOLERANCE_RATIO
    for code, level in ((TP_HIT, tp_price), (SL_HIT, sl_price)):
        if level is None:
            continue
        if abs(exit_price - level) <= max(tol, 1e-9):
            return code
    return None


def canonical_exit_reason(*, reason_text: Any = None, pnl_usd: Any = None,
                          entry_price: Any = None, exit_price: Any = None,
                          direction: Any = None, sl_price: Any = None,
                          tp_price: Any = None) -> dict[str, Any]:
    """Kapanış nedenini kanonik koda çevir + mantık çelişkisini onar.

    Döndürür: ``{"code", "label", "source", "contradiction", "raw"}``
    """
    raw = str(reason_text or "").strip()
    pnl = _f(pnl_usd)
    text_code = _code_from_text(raw)
    price_code = _code_from_price(
        direction=str(direction or "").upper() or None,
        exit_price=_f(exit_price), sl_price=_f(sl_price), tp_price=_f(tp_price))

    code = price_code or text_code
    source = "price" if price_code else ("text" if text_code else "none")
    contradiction = False

    # ---- MANTIK KAPISI: kârlı işlem SL olamaz, zararlı işlem TP olamaz ----
    if code == SL_HIT and pnl is not None and pnl > 0:
        contradiction = True
        # Trailing/kısmi ipucu varsa o koda düşür; yoksa nötr kazanç kodu.
        code = text_code if text_code in (TRAILING, PARTIAL, SCALPER_CLOSE) else OTHER_WIN
        source = "repaired"
    elif code == TP_HIT and pnl is not None and pnl < 0:
        contradiction = True
        code = text_code if text_code in (TRAILING, PARTIAL) else OTHER_LOSS
        source = "repaired"

    # ---- Hiçbir kanıt yoksa PnL işaretine göre ----
    if code is None:
        if pnl is None:
            code = UNKNOWN
        else:
            code = OTHER_WIN if pnl >= 0 else OTHER_LOSS
        source = "pnl"

    return {
        "code": code,
        "label": LABELS.get(code, code),
        "source": source,
        "contradiction": contradiction,
        "raw": raw or None,
    }


def is_stop_like(code: Any) -> bool:
    """Kayıp kapatan çıkış mı? (SL sigortası/sayaçları için)"""
    return str(code or "") in {SL_HIT, TRAILING, OTHER_LOSS}


def is_target_like(code: Any) -> bool:
    """Kâr kapatan çıkış mı?"""
    return str(code or "") in {TP_HIT, PARTIAL, OTHER_WIN}
