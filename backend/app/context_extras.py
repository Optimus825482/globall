"""LLM BAĞLAM EKLERİ — COT + seans penceresi + istatistiksel doğrulama (2026-11-09)

NEDEN VAR
---------
`cot_positions`, `session_windows` ve `edge_validation` modülleri yazıldı ama
karar veren yüzeylere BAĞLANMAMIŞTI: COT ve seans yalnız `/api/system/health`
sağlık panelinde görünüyordu, doğrulama artefaktı ise hiçbir yerde okunmuyordu.

Artık üç LLM yüzeyi de aynı kaynaktan beslenir:
  1. `llm_trade_review.build_dossier` — işlem ikinci-görüş dosyası
  2. `routers/forex_chat` `mode="opportunity_scan"` — paneldeki "Fırsat taraması"
  3. `routers/llm_chat` — genel sohbet / tarama bağlamı

TEK UYGULAMA KURALI: aynı veriyi üç yerde üç farklı şekilde kurgulamak
sohbetin paneli, panelin LLM'i yalanlamasına yol açar. Bu yüzden bütün
biçimlendirme burada; çağıranlar yalnız `macro_context()` / `compact_lines()`
çağırır.

DÜRÜSTLÜK KURALI: her blok "veri var mı / taze mi" bilgisini TAŞIR. Veri yoksa
LLM'e "bilinmiyor" denir — COT verisi uydurulmaz, eksik veri "nötr" gibi
sunulmaz (nötr ile bilinmiyor farklı şeylerdir ve karar ikisinde aynı olmamalı).
"""
from __future__ import annotations

import re
from typing import Any, Iterable

#: COT raporu haftalık ve 3 günlük yayın gecikmesi var; bu süre içinde "taze".
COT_TTL_DAYS = 10.0
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def symbol_currencies(symbol: str) -> list[str]:
    """`EURUSD` → ``['EUR','USD']``, `XAUUSD` → ``['USD']``, `US30` → ``[]``.

    Sembolü 3'lük parçalara bölüp bilinen para birimlerini seçer (COT artefaktı
    yalnız 7 majör para birimini taşır; endeks/kripto için doğal olarak boş döner).
    """
    from app.cot_positions import CURRENCY_MARKETS

    # DİKKAT: `CURRENCY_MARKETS` piyasa adı → para birimi eşlemesidir
    # ("EURO FX - CHICAGO…" → "EUR"). Bilinen PARA BİRİMLERİ değerlerdir.
    #
    # USD de eklenir: TFF raporunda USD'nin KENDİ satırı yoktur (o rapor majör
    # para birimlerini USD'ye karşı verir), ama sembol çözümlemesinde USD'nin
    # tanınması gerekir — aksi halde `XAUUSD`/`EURUSD` yanlış çözümlenirdi.
    # Artefaktta USD satırı bulunmadığı `cot_block` içinde AÇIKÇA bildirilir.
    known = set(CURRENCY_MARKETS.values()) | {"USD"}
    sym = re.sub(r"[^A-Z]", "", str(symbol or "").upper())
    out: list[str] = []
    for i in range(0, len(sym) - 2):
        chunk = sym[i:i + 3]
        if chunk in known and chunk not in out:
            out.append(chunk)
    return out


def sessions_block(now: float | None = None) -> dict[str, Any]:
    """Seans/likidite bağlamı + LLM için kısa yorum."""
    from app import session_windows as sw

    ctx = sw.describe()
    score = float(ctx.get("liquidity_score") or 0.0)
    if ctx.get("market_closed"):
        note = "Piyasa kapalı (hafta sonu): yeni forex/emtia işlemi açılmamalı."
    elif score >= 0.8:
        note = "Likidite yüksek: spread dar, kayma riski düşük — motorun normal koşulu."
    elif score >= 0.45:
        note = "Likidite orta: normal işlem koşulu."
    else:
        note = "Likidite DÜŞÜK: spread geniş, kayma riski yüksek — bu pencerede açılan işlem istatistiksel olarak daha pahalıdır."
    if ctx.get("dead_zone") and not ctx.get("market_closed"):
        note += " Ölü bölge (21:00+ UTC): likidite çekilir."
    if ctx.get("spread_risk"):
        note += " Yüksek spread riski penceresi."
    return {**ctx, "note": note, "available": True}


def cot_block(symbol: str | None = None, *, currencies: Iterable[str] | None = None) -> dict[str, Any]:
    """COT pozisyonlanma bağlamı — sembolün para birimleri (yoksa hepsi)."""
    from app import cot_positions as cot

    want = [c.upper() for c in (currencies or []) if c]
    if not want and symbol:
        want = symbol_currencies(symbol)
    data = cot.summary()
    if not data.get("available"):
        return {"available": False, "reason": "COT raporu indirilmemiş (scripts/fetch_cot_positions.py)",
                "currencies": {}, "stale": True, "note": "Pozisyonlanma verisi YOK — kalabalık/ayrışma hakkında yorum yapılamaz."}
    all_cur = data.get("currencies") or {}
    picked = {c: all_cur[c] for c in want if c in all_cur} if want else dict(all_cur)
    missing = [c for c in want if c not in all_cur]
    stale = bool(data.get("stale"))
    notes: list[str] = []
    if missing:
        # "Sessiz boşluk" en tehlikeli hâl: LLM eksik veriyi "nötr" sanar.
        notes.append(
            "şu para birimleri COT raporunda DOĞRUDAN yok, yorum yapılmadı: "
            + ", ".join(missing)
            + (" (USD satırı TFF raporunda bulunmaz — rapor majörleri USD'ye karşı verir)" if "USD" in missing else "")
        )
    for cur, st in picked.items():
        if st.get("crowded"):
            side = "LONG" if float(st.get("lev_net") or 0) > 0 else "SHORT"
            notes.append(f"{cur}: kalabalık {side} (yüzdeli̇k {st.get('crowding_pct')}%) → ters hareket riski yüksek")
        if st.get("divergence"):
            notes.append(f"{cur}: sıcak para ile gerçek para AYRIŞIYOR (lev vs asset-mgr) → sinyal güvenilirliği düşük")
    if stale:
        notes.append(f"COT raporu eski ({data.get('age_days')} gün) — tazelenmeli.")
    return {
        "available": True,
        "report_date": data.get("report_date"),
        "age_days": data.get("age_days"),
        "stale": stale,
        "currencies": picked,
        "unavailable": data.get("unavailable") or [],
        "unavailable_for": missing,
        "note": " | ".join(notes) if notes else ("Aşırı kalabalık/ayrışma yok." if picked else "Bu sembol için COT satırı bulunamadı."),
    }


def edge_block() -> dict[str, Any]:
    """SPA/DSR/PBO doğrulama artefaktı (yoksa fail-closed)."""
    from app import edge_validation as ev

    s = ev.summary()
    return {**s, "lines": ev.compact_lines()}


def macro_context(symbol: str | None = None, *, now: float | None = None) -> dict[str, Any]:
    """Üç bloğu tek sözlükte toplar (LLM bağlamına doğrudan gömülebilir)."""
    return {
        "seans_ve_likidite": sessions_block(now),
        "cot_pozisyonlanma": cot_block(symbol),
        "istatistiksel_dogrulama": edge_block(),
    }


def compact_lines(symbol: str | None = None) -> list[str]:
    """LLM'e düz metin olarak gidecek kısa satırlar (dossier/araç çıktısı)."""
    ctx = macro_context(symbol)
    ses = ctx["seans_ve_likidite"]
    lines = [f"Seans: {ses.get('label')} (UTC {ses.get('utc')}) · likidite {ses.get('liquidity_score')} · {ses.get('note')}"]
    cot = ctx["cot_pozisyonlanma"]
    if cot.get("available"):
        lines.append(f"COT ({cot.get('report_date')}, {cot.get('age_days')} gün): {cot.get('note')}")
        for cur, st in (cot.get("currencies") or {}).items():
            lines.append(
                f"  {cur}: bias {st.get('bias')} ({st.get('stance')}) · kalabalık %{st.get('crowding_pct')}"
                f" · haftalık değişim {st.get('change_wow_pct')}pp"
            )
    else:
        lines.append(f"COT: {cot.get('reason')}")
    lines.extend(ctx["istatistiksel_dogrulama"].get("lines") or [])
    return lines
