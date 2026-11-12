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

2026-11-09: dördüncü blok eklendi — `market_pulse` KÜRESEL VARLIK NABZI
(VIX / DXY / ABD 10Y verim / altın / petrol / S&P 500). Öncesinde bu
cross-asset serileri hiçbir yüzeyde yoktu; LLM "finans uzmanı" rolüne
rağmen risk iştahı ve faiz okumasını uyduruyordu.

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
        try:
            lev = float(st.get("lev_net_pct"))
        except (TypeError, ValueError):
            lev = 0.0
        am_raw = st.get("asset_mgr_net_pct")
        if st.get("crowded"):
            side = "LONG" if float(st.get("lev_net") or 0) > 0 else "SHORT"
            notes.append(f"{cur}: kalabalık {side} (|lev| {abs(lev):.1f}%OI, yüzdeli̇k "
                         f"{st.get('crowding_pct')}%) → ters hareket riski yüksek")
        # AYRIŞMA ARTIK EŞİKLİ: yalnız iki taraf da ANLAMLI büyüklükteyse
        # (2026-11-09: eşiksiz hâlde 7 para biriminin 6'sı "ayrışma" diyordu →
        # uyarı bilgi taşımıyordu). Sayılar da yazılır ki LLM büyüklüğü tartabilsin.
        # `divergence_material` yoksa (eski/harici yük) yüzdelerden YENİDEN hesapla —
        # eski `divergence` bayrağına körlemesine güvenmek eşiği atlatırdı.
        material = st.get("divergence_material")
        if material is None:
            from app.cot_positions import is_material_divergence
            material = is_material_divergence(st)
        if material and am_raw is not None:
            try:
                am = float(am_raw)
            except (TypeError, ValueError):
                am = 0.0
            notes.append(f"{cur}: sıcak para (lev {lev:+.1f}%OI) ile gerçek para "
                         f"(asset-mgr {am:+.1f}%OI) ZIT yönde → sinyal güvenilirliği düşük")
        elif st.get("divergence") and not material:
            notes.append(f"{cur}: lev/asset-mgr işaretleri zıt ama bir taraf nötre yakın "
                         f"(lev {lev:+.1f}%OI) → ayrışma sayılmadı")
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


def cross_asset_block() -> dict[str, Any]:
    """Küresel varlık nabzı (VIX/DXY/10Y/altın/petrol/SPX) — fail-closed."""
    from app import market_pulse as mp

    s = mp.summary()
    if not s.get("available"):
        return {**s, "note": ("Küresel varlık nabzı YOK: " + str(s.get("reason"))
                              + " — risk iştahı/faiz/emtia okunamadı, uydurulmaz.")}
    return {**s, "note": " | ".join(s.get("notes") or []) or "Cross-asset belirgin çapraz sinyal yok."}


def retail_block(symbol: str | None = None) -> dict[str, Any]:
    """Perakende konumlanma (Myfxbook topluluk outlook) — fail-closed.

    2026-11-12: FX'te kalabalık yönü hiçbir yüzeyde yoktu (kriptoda Binance türev
    verisi var). Bu blok KAPI DEĞİL: karar akışını değiştirmez, yalnız LLM'e
    "herkes hangi tarafta" bilgisini sayıyla verir.
    """
    from app import retail_sentiment as rs

    s = rs.summary(symbol)
    rs.ensure_fresh_async()  # tur aralığı içindeyse no-op
    if not s.get("available"):
        return {**s, "note": f"Perakende konumlanma YOK ({s.get('reason')}) — uydurulmaz."}
    if s.get("symbol") is None:
        return {**s, "note": "Sembol Myfxbook kapsamında değil (endeksler yok)."}
    return {**s, "note": " | ".join(rs.compact_lines(symbol))}


def sentiment_block(symbol: str | None = None) -> dict[str, Any]:
    """BİLEŞİK sentiment endeksi (−100 SHORT … +100 LONG) — fail-closed.

    2026-11-12: dört kanal (açıklanmış ekonomik veri, COT, küresel nabız,
    perakende kalabalığı) tek skora indirgenir. BAĞLAMDIR, KAPI DEĞİL;
    ağırlıklar yargıdır, ölçülmüş kenar değildir.
    """
    from app import sentiment_index as si

    if not symbol:
        return {"available": False, "reason": "sembol verilmedi"}
    try:
        r = si.summarize(symbol)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "available": True,
        "symbol": r["symbol"],
        "score": r["score"],
        "label": r["label"],
        "coverage": r["coverage"],
        "missing": r["missing"],
        "components": {k: v.get("score") for k, v in r["components"].items() if v["available"]},
        "note": r["note"],
    }


def macro_context(symbol: str | None = None, *, now: float | None = None) -> dict[str, Any]:
    """Altı bloğu tek sözlükte toplar (LLM bağlamına doğrudan gömülebilir)."""
    return {
        "seans_ve_likidite": sessions_block(now),
        "cot_pozisyonlanma": cot_block(symbol),
        "istatistiksel_dogrulama": edge_block(),
        "kuresel_varlik_nabzi": cross_asset_block(),
        "perakende_konumlanma": retail_block(symbol),
        "bilesik_sentiment": sentiment_block(symbol),
    }


def compact_lines(symbol: str | None = None) -> list[str]:
    """LLM'e düz metin olarak gidecek kısa satırlar (dossier/araç çıktısı)."""
    ctx = macro_context(symbol)
    ses = ctx["seans_ve_likidite"]
    lines = [f"Seans: {ses.get('label')} (UTC {ses.get('utc')}) · likidite {ses.get('liquidity_score')} · {ses.get('note')}"]
    cot = ctx["cot_pozisyonlanma"]
    if cot.get("available"):
        # ÖZET satırı kısa tutulur; bayraklar ve BÜYÜKLÜKLER para birimi
        # satırlarına yazılır. LLM uzun "|" zincirinden büyüklük okuyamıyordu.
        cur_map = cot.get("currencies") or {}
        mat = [c for c, st in cur_map.items() if st.get("divergence_material")]
        crowd = [c for c, st in cur_map.items() if st.get("crowded")]
        bits = []
        if mat:
            bits.append(f"anlamlı ayrışma {len(mat)}/{len(cur_map)} ({', '.join(sorted(mat))})")
        if crowd:
            bits.append(f"kalabalık: {', '.join(sorted(crowd))}")
        ozet = "; ".join(bits) if bits else "belirgin kalabalık/ayrışma yok"
        lines.append(f"COT ({cot.get('report_date')}, {cot.get('age_days')} gün): {ozet}")
        # Yalnız "veri YOK" bilgisi ayrıca yazılır (sessiz boşluk olmasın); geri
        # kalan yorum satırları aşağıdaki para birimi satırlarında zaten var.
        if cot.get("unavailable_for"):
            lines.append(f"  COT satırı doğrudan yok: {', '.join(cot.get('unavailable_for') or [])}")
        for cur, st in cur_map.items():
            try:
                lev = float(st.get("lev_net_pct"))
            except (TypeError, ValueError):
                lev = 0.0
            am = st.get("asset_mgr_net_pct")
            flags = []
            if st.get("crowded"):
                flags.append(f"⚠KALABALIK %{st.get('crowding_pct')}")
            if st.get("divergence_material"):
                try:
                    am_f = float(am)
                except (TypeError, ValueError):
                    am_f = 0.0
                flags.append(f"⚠AYRIŞMA (lev {lev:+.1f} / am {am_f:+.1f} %OI)")
            lines.append(
                f"  {cur}: bias {st.get('bias')} ({st.get('stance')}) · lev {lev:+.1f}%OI"
                + (f" · am {float(am):+.1f}%OI" if am is not None else "")
                + f" · haftalık {st.get('change_wow_pct')}pp"
                + (f" · {' · '.join(flags)}" if flags else "")
            )
    else:
        lines.append(f"COT: {cot.get('reason')}")
    lines.extend(ctx["istatistiksel_dogrulama"].get("lines") or [])
    lines.extend(cross_asset_lines())
    # Perakende konumlanma: özet satırı tek satırdır, kalabalık/örneklem uyarıları
    # aynı satıra büyüklükle yazılır (LLM "yüksek/düşük"ü kendisi tartmasın).
    ret = ctx.get("perakende_konumlanma") or {}
    if ret.get("available") and ret.get("symbol"):
        lines.append(compact_retail_line(ret))
    elif ret.get("note"):
        lines.append(f"Perakende konumlanma: {ret.get('note')}")
    sent = ctx.get("bilesik_sentiment") or {}
    if sent.get("available"):
        comps = sent.get("components") or {}
        if comps:
            lines.append(
                f"Bileşik sentiment: {sent['score']:+.0f}/100 ({sent['label']}) · "
                + " · ".join(f"{k} {v:+.0f}" for k, v in comps.items())
                + f" · kapsam %{sent['coverage'] * 100:.0f}"
                + (f" · eksik: {', '.join(sent['missing'])}" if sent.get("missing") else "")
            )
    elif sent.get("reason"):
        lines.append(f"Bileşik sentiment: YOK ({sent['reason']})")
    return lines


def compact_retail_line(ret: dict[str, Any]) -> str:
    """Perakende konumlanma satırı (tek kaynak: retail_sentiment.compact_lines)."""
    from app import retail_sentiment as rs

    got = rs.compact_lines(ret.get("symbol"))
    return got[0] if got else "Perakende konumlanma: okunamadı."


def cross_asset_lines() -> list[str]:
    """Varlık nabzı satırları — `market_pulse.compact_lines` tek kaynaktır."""
    from app import market_pulse as mp
    return mp.compact_lines()
