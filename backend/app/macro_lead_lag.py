"""Radar Faz 2 Makro Öncü-Gecikme (Macro Lead-Lag) Modülü: US10Y + VIX + DXY.

180 saniyelik bellek içi önbellekli, bloklamayan Yahoo Finance (15m/2g) çekicisi ve
saf deterministik makro uyum değerlendirme motoru. Ağ hatalarında asla istisna
fırlatmaz; güvenli biçimde None/NEUTRAL/FLAT/CALM varsayılanlarına düşer.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

_CACHE_TTL_SEC = 180.0
_FETCH_TIMEOUT_SEC = 4.0
_YAHOO_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=15m&range=2d"
)
_USER_AGENT = "Mozilla/5.0 (compatible; ScalperRadar/2.0)"

_MACRO_CACHE: Optional[Dict[str, Any]] = None
_MACRO_CACHE_TS: float = 0.0

_JPY_PAIRS = frozenset({"USDJPY", "EURJPY", "GBPJPY"})
_RISK_ON_MAJORS = frozenset({"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"})
_RISK_OFF_SENSITIVE_MAJORS = frozenset({"AUDUSD", "NZDUSD", "GBPUSD"})
_USD_BASE_MAJORS = frozenset({"USDCAD", "USDCHF"})
_CRYPTO_PREFIXES = (
    "BTC", "ETH", "SOL", "XRP", "BNB", "AVAX", "AVX", "DOGE", "LINK", "LNK",
)
_OIL_SYMBOLS = frozenset({"USOIL", "UKOIL"})


def _normalize_dxy(dxy_regime: Any) -> str:
    if isinstance(dxy_regime, dict):
        dxy_regime = dxy_regime.get("regime")
    s = str(dxy_regime or "").strip().upper()
    return s if s in ("USD_STRONG", "USD_WEAK", "USD_NEUTRAL") else "USD_NEUTRAL"


def _fetch_yahoo_closes_sync(yahoo_symbol: str) -> List[float]:
    """Yahoo Finance 15m kapanış serisini kısa zaman aşımıyla çeker; hata durumunda []."""
    encoded = urllib.parse.quote(yahoo_symbol, safe="")
    url = _YAHOO_CHART_URL.format(sym=encoded)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        payload = json.loads(raw)
        results = (payload.get("chart") or {}).get("result") or []
        if not results:
            return []
        quotes = ((results[0].get("indicators") or {}).get("quote") or [])
        if not quotes:
            return []
        closes_raw = quotes[0].get("close") or []
        out: List[float] = []
        for v in closes_raw:
            if v is None:
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(f) and f > 0.0:
                out.append(f)
        return out
    except Exception:
        return []


def _summarize_series(closes: List[float]) -> Dict[str, Optional[float]]:
    if not closes:
        return {"last": None, "change_pct_1h": None}
    last = round(closes[-1], 4)
    if len(closes) >= 5:
        prev = closes[-5]  # 4 × 15dk = 1 saat öncesi
    elif len(closes) >= 2:
        prev = closes[0]
    else:
        prev = 0.0
    if prev > 0.0:
        chg = round(((closes[-1] - prev) / prev) * 100.0, 3)
    else:
        chg = None
    return {"last": last, "change_pct_1h": chg}


def _classify_us10y(summary: Dict[str, Optional[float]]) -> Dict[str, Any]:
    chg = summary.get("change_pct_1h")
    if chg is not None and chg >= 0.35:
        direction = "RISING"
    elif chg is not None and chg <= -0.35:
        direction = "FALLING"
    else:
        direction = "FLAT"
    return {
        "last": summary.get("last"),
        "change_pct_1h": chg,
        "dir": direction,
    }


def _classify_vix(summary: Dict[str, Optional[float]]) -> Dict[str, Any]:
    last = summary.get("last")
    chg = summary.get("change_pct_1h")
    if (last is not None and last >= 22.0) or (chg is not None and chg >= 6.0):
        regime = "RISK_OFF_PANIC"
    elif (last is not None and last >= 18.0) or (chg is not None and chg >= 3.0):
        regime = "ELEVATED"
    else:
        regime = "CALM"
    return {
        "last": last,
        "change_pct_1h": chg,
        "regime": regime,
    }


async def get_macro_snapshot(dxy_regime: Optional[str] = None) -> Dict[str, Any]:
    """US10Y (^TNX), VIX (^VIX) ve DXY özetini 180 sn önbellekli ve bloklamadan döner."""
    global _MACRO_CACHE, _MACRO_CACHE_TS
    now = time.time()
    norm_dxy = _normalize_dxy(dxy_regime)

    if _MACRO_CACHE is not None and (now - _MACRO_CACHE_TS) < _CACHE_TTL_SEC:
        snap = dict(_MACRO_CACHE)
        snap["dxy_regime"] = norm_dxy
        return snap

    try:
        tnx_closes, vix_closes = await asyncio.gather(
            asyncio.to_thread(_fetch_yahoo_closes_sync, "^TNX"),
            asyncio.to_thread(_fetch_yahoo_closes_sync, "^VIX"),
        )
    except Exception:
        tnx_closes, vix_closes = [], []

    us10y = _classify_us10y(_summarize_series(tnx_closes))
    vix = _classify_vix(_summarize_series(vix_closes))

    snap = {
        "us10y": us10y,
        "vix": vix,
        "dxy_regime": norm_dxy,
        "updated_at": now,
    }
    _MACRO_CACHE = dict(snap)
    _MACRO_CACHE_TS = now
    return snap


def evaluate_macro_alignment(
    symbol: str,
    action: str,
    macro: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Sembol + yön + makro bağlamına göre destek/karşıtlık ve skor deltası [-8, +8] üretir."""
    us10y_dir = str(((macro or {}).get("us10y") or {}).get("dir") or "FLAT").upper()
    vix_regime = str(((macro or {}).get("vix") or {}).get("regime") or "CALM").upper()
    dxy = _normalize_dxy((macro or {}).get("dxy_regime"))

    act = str(action or "").strip().upper()
    if act not in ("BUY", "SELL") or not macro:
        return {
            "macro_alignment": "NEUTRAL",
            "macro_delta": 0.0,
            "macro_note": "",
            "vix_regime": vix_regime,
            "us10y_dir": us10y_dir,
        }

    sym = (
        str(symbol or "")
        .upper()
        .replace("/", "")
        .replace("_", "")
        .replace("-", "")
        .strip()
    )
    is_buy = act == "BUY"
    delta = 0.0
    drivers: List[str] = []
    asset_label = sym

    # 1. Altın / Gümüş (XAU, XAG)
    if sym.startswith(("XAU", "XAG")) or "GOLD" in sym or "SILVER" in sym:
        asset_label = "Altın" if ("XAU" in sym or "GOLD" in sym) else "Gümüş"
        if us10y_dir == "FALLING":
            delta += 3.0 if is_buy else -3.0
            drivers.append("US10Y düşüyor")
        elif us10y_dir == "RISING":
            delta += -3.0 if is_buy else 3.0
            drivers.append("US10Y yükseliyor")

        if dxy == "USD_WEAK":
            delta += 2.0 if is_buy else -2.0
            drivers.append("DXY zayıf")
        elif dxy == "USD_STRONG":
            delta += -2.0 if is_buy else 2.0
            drivers.append("DXY güçlü")

        if vix_regime == "RISK_OFF_PANIC":
            delta += 3.0 if is_buy else -2.0
            drivers.append("VIX panik (güvenli liman)")

    # 2. JPY pariteleri (USDJPY, EURJPY, GBPJPY vb.)
    elif sym in _JPY_PAIRS or (len(sym) == 6 and sym.endswith("JPY")):
        if us10y_dir == "RISING":
            delta += 3.0 if is_buy else -3.0
            drivers.append("US10Y yükseliyor")
        elif us10y_dir == "FALLING":
            delta += -3.0 if is_buy else 3.0
            drivers.append("US10Y düşüyor")

        if vix_regime == "RISK_OFF_PANIC":
            delta += -4.0 if is_buy else 3.0
            drivers.append("VIX panik (JPY güvenli liman)")

    # 3. Risk-on USD Majörleri (EURUSD, GBPUSD, AUDUSD, NZDUSD)
    elif sym in _RISK_ON_MAJORS:
        if dxy == "USD_WEAK":
            delta += 3.0 if is_buy else -3.0
            drivers.append("DXY zayıf")
        elif dxy == "USD_STRONG":
            delta += -3.0 if is_buy else 3.0
            drivers.append("DXY güçlü")

        if sym in _RISK_OFF_SENSITIVE_MAJORS and vix_regime == "RISK_OFF_PANIC":
            delta += -4.0 if is_buy else 2.0
            drivers.append("VIX panik (riskten kaçış)")

    # 4. USD-bazlı Majörler (USDCAD, USDCHF)
    elif sym in _USD_BASE_MAJORS:
        if dxy == "USD_STRONG":
            delta += 3.0 if is_buy else -3.0
            drivers.append("DXY güçlü")
        elif dxy == "USD_WEAK":
            delta += -3.0 if is_buy else 3.0
            drivers.append("DXY zayıf")

        if sym == "USDCHF" and vix_regime == "RISK_OFF_PANIC":
            delta += -2.0 if is_buy else 2.0
            drivers.append("VIX panik (CHF güvenli liman)")

    # 5. Kripto (BTC, ETH, SOL, XRP, BNB, AVAX, DOGE, LINK)
    elif any(sym.startswith(p) for p in _CRYPTO_PREFIXES):
        asset_label = "Kripto"
        if vix_regime == "RISK_OFF_PANIC":
            delta += -4.0 if is_buy else 2.0
            drivers.append("VIX panik (riskten kaçış)")
        if dxy == "USD_WEAK" and vix_regime == "CALM":
            delta += 3.0 if is_buy else -2.0
            drivers.append("DXY zayıf + VIX sakin")

    # 6. Petrol (USOIL, UKOIL)
    elif sym in _OIL_SYMBOLS or "OIL" in sym:
        asset_label = "Petrol"
        if vix_regime == "RISK_OFF_PANIC":
            delta += -3.0 if is_buy else 2.0
            drivers.append("VIX panik (riskten kaçış)")

    delta = round(max(-8.0, min(8.0, delta)), 1)
    if delta >= 2.0:
        alignment = "SUPPORTIVE"
    elif delta <= -2.0:
        alignment = "OPPOSING"
    else:
        alignment = "NEUTRAL"

    if drivers:
        dir_tr = "alım" if is_buy else "satım"
        if alignment == "SUPPORTIVE":
            suffix = f"{asset_label} {dir_tr} desteği"
        elif alignment == "OPPOSING":
            suffix = f"{asset_label} {dir_tr} karşıtı baskı"
        else:
            suffix = f"{asset_label} karışık makro etki"
        note = f"{' + '.join(drivers)} → {suffix}"
    else:
        note = ""

    return {
        "macro_alignment": alignment,
        "macro_delta": delta,
        "macro_note": note,
        "vix_regime": vix_regime,
        "us10y_dir": us10y_dir,
    }
