"""COT (Commitments of Traders) KURUMSAL POZİSYONLANMA — FX bağlamı (2026-11-09)

NEDEN VAR (araştırma P2-8)
--------------------------
Araştırmanın "fiyat-dışı en yakın gerçek kenar" dediği veri bu: CFTC'nin haftalık
COT raporu, FX vadeli işlemlerinde **kimin hangi yönde ne kadar** pozisyon
tuttuğunu söyler. Mevcut modüller (haber/yanlılık, takvim, OI/funding) fiyat ve
olay türevi; COT **pozisyonlanma** türevi ve farklı bilgi taşır.

KAYNAK — DOĞRULANMIŞ DOSYA
--------------------------
Varsayılan `fut_disagg_txt_YYYY.zip` **YALNIZ EMTİA** içeriyor (333 market, hiç
FX yok — ölçüldü). FX sözleşmeleri TFF (Traders in Financial Futures) raporunda:

    https://www.cftc.gov/files/dea/history/fut_fin_txt_YYYY.zip   (632 KB, 2026)

Bu dosya `Dealer_*`, `Asset_Mgr_*`, `Lev_Money_*` kolonlarını taşır — eski
`Noncommercial_*` yerine. Bu bizim için **daha iyi**: "sıcak para" (leveraged
money) ile "gerçek para" (asset manager) ayrışır ve ikisinin ayrışması başlı
başına bilgi taşır.

BULUNAN PARA BİRİMLERİ (dosyada doğrulandı)
-------------------------------------------
EUR, GBP, JPY, CHF, CAD, AUD, MXN. **NZD ve USD endeksi bu dosyada YOK** —
uydurulmaz, `summary()` yalnız bulunanları döndürür.

ÖLÇÜLEN ÖRNEK (2026-11-03 raporu)
---------------------------------
    EUR: OI=876,122  lev_net=-78,559 (-9.0% OI)  asset_net=+144,925 (+16.5%)
    JPY: OI=380,641  lev_net=-14,817 (-3.9% OI)  asset_net= +79,387 (+20.9%)

Bu ayrışma (sıcak para kısa, gerçek para uzun) modülün `divergence` alanıdır.

NE DÖNDÜRÜR — ve NE DÖNDÜRMEZ
-----------------------------
`bias()` bir **bağlam** üretir (yön duruşu + kalabalıklık + ayrışma), bir **al/sat
sinyali** değildir. Skorlamaya/kapıya sokmak backtest ister; bu modül bilgi katmanıdır.

Üretim-güvenli: yalnız standart kütüphane (`json`, `math`, `os`, `time`).
Ağ erişimi YOK — indirme `scripts/fetch_cot_positions.py` işidir, artefakt JSON
olarak taşınır.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from typing import Any, Iterable

#: Market adı öneki → ISO para birimi. Dosyada DOĞRULANMIŞ adlar.
CURRENCY_MARKETS: dict[str, str] = {
    "EURO FX - CHICAGO MERCANTILE EXCHANGE": "EUR",
    "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE": "GBP",
    "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE": "JPY",
    "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE": "CHF",
    "CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE": "CAD",
    "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE": "AUD",
    "MEXICAN PESO - CHICAGO MERCANTILE EXCHANGE": "MXN",
}

#: `bias` ölçeği: lev_net_pct'in bu değeri "tam güçlü" sayılır (tanh ölçeği).
BIAS_SCALE_PCT = 15.0
#: |bias| bu eşiğin altındaysa NEUTRAL.
NEUTRAL_BAND = 0.25
#: Kalabalık sayılma yüzdelik eşiği.
CROWDED_PERCENTILE = 90.0
#: Artefakt bu kadar günden eskiyse `stale=True` (haftalık rapor → 8 gün tolerans).
STALE_DAYS = 8

_cache: dict[str, Any] = {"path": None, "mtime": None, "data": None, "checked_at": 0.0}
_lock = threading.Lock()


def _num(value, default: float | None = None) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else default


def _market_to_currency(name: str) -> str | None:
    upper = (name or "").strip().upper()
    for prefix, currency in CURRENCY_MARKETS.items():
        if upper == prefix.upper():
            return currency
    return None


def parse_rows(rows: Iterable[dict]) -> list[dict[str, Any]]:
    """TFF CSV satırlarını (ham dict) para birimi × hafta istatistiklerine indirger.

    Saf fonksiyon: ağ/disk yok → test edilebilir. Çapraz kurlar (ör.
    "EURO FX/BRITISH POUND XRATE") `CURRENCY_MARKETS`'te olmadığı için ATILIR.
    """
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        currency = _market_to_currency(row.get("Market_and_Exchange_Names") or "")
        if not currency:
            continue
        date = (row.get("Report_Date_as_YYYY-MM-DD") or "").strip()
        if not date:
            continue
        oi = _num(row.get("Open_Interest_All"))
        lev_l = _num(row.get("Lev_Money_Positions_Long_All"))
        lev_s = _num(row.get("Lev_Money_Positions_Short_All"))
        am_l = _num(row.get("Asset_Mgr_Positions_Long_All"))
        am_s = _num(row.get("Asset_Mgr_Positions_Short_All"))
        dl = _num(row.get("Dealer_Positions_Long_All"))
        ds = _num(row.get("Dealer_Positions_Short_All"))
        if oi is None or oi <= 0 or lev_l is None or lev_s is None:
            continue
        lev_net = lev_l - lev_s
        am_net = (am_l - am_s) if (am_l is not None and am_s is not None) else None
        dealer_net = (dl - ds) if (dl is not None and ds is not None) else None
        out.append({
            "currency": currency,
            "date": date,
            "open_interest": oi,
            "lev_long": lev_l,
            "lev_short": lev_s,
            "lev_net": lev_net,
            "lev_net_pct": round(100.0 * lev_net / oi, 3),
            "asset_mgr_net": None if am_net is None else round(am_net, 0),
            "asset_mgr_net_pct": (None if am_net is None
                                  else round(100.0 * am_net / oi, 3)),
            "dealer_net": None if dealer_net is None else round(dealer_net, 0),
        })
    out.sort(key=lambda r: (r["currency"], r["date"]))
    return out


def _percentile_rank(values: list[float], x: float) -> float:
    """`values` içinde `x`'in yüzdelik sırası (0-100). Boşsa 50 (nötr)."""
    if not values:
        return 50.0
    below = sum(1 for v in values if v < x)
    equal = sum(1 for v in values if v == x)
    return 100.0 * (below + 0.5 * equal) / len(values)


def _stance(bias: float) -> str:
    if bias >= NEUTRAL_BAND:
        return "LONG"
    if bias <= -NEUTRAL_BAND:
        return "SHORT"
    return "NEUTRAL"


def compute_currency_stats(series: list[dict[str, Any]]) -> dict[str, Any]:
    """Tek para biriminin zaman serisinden güncel durum + tarihsel istatistik."""
    if not series:
        return {}
    latest = series[-1]
    hist_pct = [float(r["lev_net_pct"]) for r in series]
    lev_pct = float(latest["lev_net_pct"])
    bias = math.tanh(lev_pct / BIAS_SCALE_PCT)
    # Kalabalıklık: MUTLAK pozisyon büyüklüğünün tarihsel yüzdeliği.
    crowding = _percentile_rank([abs(v) for v in hist_pct], abs(lev_pct))
    # Haftalık değişim (sadece lev_net_pct farkı — ölçek bağımsız).
    wow = None
    if len(series) >= 2:
        wow = round(lev_pct - float(series[-2]["lev_net_pct"]), 3)
    # Ayrışma: sıcak para ile gerçek para zıt yönde mi?
    divergence = None
    am_pct = latest.get("asset_mgr_net_pct")
    if am_pct is not None:
        divergence = (lev_pct > 0) != (am_pct > 0)
    return {
        "date": latest["date"],
        "open_interest": latest["open_interest"],
        "lev_net": latest["lev_net"],
        "lev_net_pct": lev_pct,
        "asset_mgr_net": latest.get("asset_mgr_net"),
        "asset_mgr_net_pct": am_pct,
        "dealer_net": latest.get("dealer_net"),
        "bias": round(bias, 3),
        "stance": _stance(bias),
        "crowding_pct": round(crowding, 1),
        "crowded": crowding >= CROWDED_PERCENTILE,
        "change_wow_pct": wow,
        "divergence": divergence,
        "weeks": len(series),
    }


def build_artifact(parsed: list[dict[str, Any]]) -> dict[str, Any]:
    """`parse_rows` çıktısından kalıcılaştırılabilir artefakt üret."""
    by_currency: dict[str, list[dict]] = {}
    for row in parsed:
        by_currency.setdefault(row["currency"], []).append(row)
    currencies = {cur: compute_currency_stats(rows)
                  for cur, rows in sorted(by_currency.items())}
    report_date = max((r["date"] for r in parsed), default=None)
    return {
        "source": "CFTC TFF (fut_fin_txt)",
        "report_date": report_date,
        "generated_at": time.time(),
        "currencies": currencies,
        "unavailable": [c for c in ("NZD",) if c not in currencies],
        "notes": (
            "lev_net_pct = Leveraged Money net / Open Interest (%). "
            "bias = tanh(lev_net_pct/15). Haftalık rapor — 3 gün gecikmelidir."
        ),
    }


# ---------------------------------------------------------------------------
# Artefakt okuma (üretim yolu — ağ yok)
# ---------------------------------------------------------------------------

def _artifact_path() -> str:
    # `config` NESNESİNİ import etmiyoruz: bu modül saf kalsın (test edilebilirlik).
    explicit = os.getenv("COT_ARTIFACT_PATH")
    if explicit:
        return explicit
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "artifacts", "cot_positions.json")


def load_artifact(path: str | None = None, max_age_seconds: float = 60.0) -> dict[str, Any] | None:
    """Artefaktı mtime kontrollü oku (değişmediyse önbellekten). Yoksa None."""
    target = path or _artifact_path()
    now = time.time()
    with _lock:
        same = _cache.get("path") == target
        if same and now - float(_cache.get("checked_at") or 0) < max_age_seconds:
            return _cache.get("data")
        _cache["path"] = target
        _cache["checked_at"] = now
        try:
            mtime = os.path.getmtime(target)
        except OSError:
            _cache["data"] = None
            _cache["mtime"] = None
            return None
        if same and _cache.get("mtime") == mtime:
            return _cache.get("data")
        try:
            with open(target, "r", encoding="utf-8") as f:
                payload = json.load(f)
            data = payload if isinstance(payload, dict) and "currencies" in payload else None
        except Exception:
            data = None
        _cache["mtime"] = mtime
        _cache["data"] = data
        return data


def _age_days(report_date: str | None) -> float | None:
    if not report_date:
        return None
    try:
        from datetime import date
        y, m, d = (int(x) for x in report_date.split("-"))
        return round((date.today() - date(y, m, d)).total_seconds() / 86400.0, 1)
    except Exception:
        return None


def bias(currency: str, *, artifact: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Tek para birimi için pozisyonlanma bağlamı; veri yoksa None."""
    data = artifact if artifact is not None else load_artifact()
    if not data:
        return None
    stats = (data.get("currencies") or {}).get(str(currency or "").upper())
    if not stats:
        return None
    return dict(stats, stale=bool((_age_days(stats.get("date")) or 0) > STALE_DAYS))


def summary(artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    """Tüm para birimleri + tazelik (rapor/UI yüzeyi)."""
    data = artifact if artifact is not None else load_artifact()
    if not data:
        return {"available": False, "currencies": {}, "report_date": None, "stale": True}
    age = _age_days(data.get("report_date"))
    return {
        "available": True,
        "report_date": data.get("report_date"),
        "age_days": age,
        "stale": bool(age is not None and age > STALE_DAYS),
        "generated_at": data.get("generated_at"),
        "currencies": data.get("currencies") or {},
        "unavailable": data.get("unavailable") or [],
    }


def reset_cache() -> None:
    with _lock:
        _cache.update({"path": None, "mtime": None, "data": None, "checked_at": 0.0})
