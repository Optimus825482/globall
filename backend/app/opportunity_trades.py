"""Sohbet "Fırsat taraması": Forex / Bitcoin / Altın'da yönlü fırsat bulunca kayıtlı DEMO hesapta işlem açar.

Akış: TradingView toplu taraması → en net adaylar derin analiz (8 dilim, MT5 öncelikli) → burada çok katmanlı
kapılar → geçenler için `forex.open_scan_position` radarın kullandığı MT5 komut kuyruğuyla DEMO hesaba emir yazar.
Açılan işlemler kapanınca Raporlar > İşlem Raporu'nda `Fırsat Taraması (Sohbet)` stratejisiyle görünür.

Güvenceler
  - Yalnızca sohbetteki "Fırsat taraması" düğmesi (mode=opportunity_scan) işlem açar; serbest metin açmaz.
  - Yalnızca DEMO hesap (bkz. `open_scan_position`); motorun açık pozisyon sınırı ve sembol başına tek pozisyon geçerli.
  - Giriş yalnızca MT5 fiyatı varken: Yahoo/MT5 fiyat farkı sahte stop/hedef üretmesin.
  - Kapılar: TradingView yönü + kendi 8 dilimli analizimiz AYNI yönde, zaman dilimi uyumu; haber: açıklanmamış yakın
    yüksek etkili veri varsa bekler, AÇIKLANMIŞ verinin sonucu teknik yönü destekler (skor eşiği gevşer) ya da bloklar;
    karşı seviye (direnç/destek) stop mesafesinden uzak; sembolde soğuma süresi.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("scalper.opportunity")

OPPORTUNITY_UNIVERSE = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "EURJPY", "GBPJPY",
                        "EURGBP", "AUDJPY", "AUDNZD", "XAUUSD", "BTCUSD"]
DEEP_ANALYSIS_TOP = 4              # taramada en net N sembol derin analiz edilir

SYMBOL_COOLDOWN_SEC = 30 * 60      # aynı sembolde yeni giriş için bekleme (bellek içi)
SL_ATR_MULT = 1.5                  # stop = 1 saatlik ATR × 1.5
RR = 1.5                           # hedef = stop × 1.5
MIN_AGREEMENT = 0.75               # TradingView zaman dilimi uyumu
MIN_TV_AVG = 0.25                  # TradingView ağırlıklı reytingin mutlak değeri
MIN_OWN_SCORE = 2.5                # kendi analiz puanımızın mutlak değeri
NEWS_BLOCK_MIN = 30                # AÇIKLANMAMIŞ yüksek etkili veriye bu kadar dakika kala giriş yok (sonucu bilinmiyor)
NEWS_LOOKBACK_MIN = 180            # AÇIKLANMIŞ verinin sonucu bu süre boyunca yönü etkiler
NEWS_DECISIVE = 1.0                # ağırlıklı net etki bu eşiği aşarsa destekler/bloklar (2★=1, 3★=2)
NEWS_SUPPORT_SCORE_RELIEF = 0.5    # veri yönü destekliyorsa teknik puan eşiği bu kadar gevşer
LEVEL_CLEARANCE = 0.8              # karşı seviye en az stop mesafesinin bu katı uzakta olmalı

_last_open: Dict[str, float] = {}  # sembol -> son açılış zamanı (süreç ömrü)


def news_effect(calendar: Optional[Dict[str, Any]], symbol: str, bias: str) -> Dict[str, Any]:
    """Son `NEWS_LOOKBACK_MIN` dakikada AÇIKLANAN verilerin sonucu bu sembolün yönüne ne yapıyor?

    Her açıklanan olay (2★ ağırlık 1, 3★ ağırlık 2) sembolün BUY/SELL tarafını destekler ya da zayıflatır
    (`yon`: +1/-1, verinin beklenti/gerçekleşen sonucundan). Net etki işlem yönüyle aynı işaretteyse DESTEKLER,
    zıtsa ÇELİŞİR. Döner: {"net", "verdict": supports|opposes|neutral, "lines": [...]}.
    """
    sign = 1 if bias == "BUY" else -1
    net, lines = 0.0, []
    for r in (calendar or {}).get("aciklanan_son_6_saat") or []:
        try:
            ago = -int(r.get("dakika", 0))
            d = int((r.get("yon") or {}).get(symbol, 0))
        except (TypeError, ValueError):
            continue
        if d == 0 or ago < 0 or ago > NEWS_LOOKBACK_MIN:
            continue
        w = 2.0 if int(r.get("stars") or 0) >= 3 else 1.0
        net += w * d
        verdict = r.get("sonuc") or f"gerçekleşen {r.get('actual')}, beklenen {r.get('forecast')}"
        lines.append(f"{r.get('currency', '')} {r.get('title')} ({verdict}) → {'BUY' if d > 0 else 'SELL'} yönünü destekler")
    aligned = net * sign
    verdict = "supports" if aligned >= NEWS_DECISIVE else "opposes" if aligned <= -NEWS_DECISIVE else "neutral"
    return {"net": net, "verdict": verdict, "lines": lines}


def plan_trade(analysis: Dict[str, Any], scan_row: Optional[Dict[str, Any]], calendar: Optional[Dict[str, Any]],
               pip_size: float) -> Dict[str, Any]:
    """Saf karar fonksiyonu: {ok, reason, plan?}. Ağ/DB/MT5 yok (test edilebilir)."""
    sym = analysis.get("symbol")
    if not analysis.get("ok"):
        return {"ok": False, "reason": "analiz verisi yok"}
    bias = analysis.get("bias")
    if bias not in ("BUY", "SELL"):
        return {"ok": False, "reason": f"net yön yok (teknik: {bias})"}
    if not scan_row or scan_row.get("direction") != bias:
        return {"ok": False, "reason": "TradingView yönü kendi analizimizle uyumsuz"}
    if float(scan_row.get("agreement", 0)) < MIN_AGREEMENT or abs(float(scan_row.get("average", 0))) < MIN_TV_AVG:
        return {"ok": False, "reason": "zaman dilimleri yeterince hemfikir değil"}
    if analysis.get("price_source") not in ("mt5_tick", "mt5_mum"):
        return {"ok": False, "reason": "MT5 anlık fiyatı yok (emir MT5'ten gideceği için gerekli)"}
    atr = (analysis.get("frames", {}).get("1h") or {}).get("atr") or analysis.get("atr")
    price = float(analysis.get("price") or 0)
    if not atr or price <= 0 or pip_size <= 0:
        return {"ok": False, "reason": "ATR/fiyat verisi eksik"}
    for e in (calendar or {}).get("yaklasan_24_saat") or []:
        try:
            if int(e.get("stars") or 0) >= 3 and 0 <= int(e.get("dakika", 9999)) <= NEWS_BLOCK_MIN:
                return {"ok": False, "reason": f"{NEWS_BLOCK_MIN} dk içinde yüksek etkili veri: {e.get('title', '')}"}
        except (TypeError, ValueError):
            continue
    # Açıklanmış verinin SONUCU teknik yönü destekler ya da bloklar (veri varsa bile sonuca bakılır).
    effect = news_effect(calendar, sym, bias)
    if effect["verdict"] == "opposes":
        return {"ok": False, "reason": "açıklanan veri teknik yönle çelişiyor: " + "; ".join(effect["lines"][:2])}
    min_score = MIN_OWN_SCORE - (NEWS_SUPPORT_SCORE_RELIEF if effect["verdict"] == "supports" else 0.0)
    if abs(float(analysis.get("score", 0))) < min_score:
        return {"ok": False, "reason": "teknik sinyal gücü düşük"}
    sl_dist = SL_ATR_MULT * float(atr)
    tp_dist = RR * sl_dist
    lv = analysis.get("levels") or {}
    opposing = (lv.get("resistances") if bias == "BUY" else lv.get("supports")) or []
    if opposing:
        gap = abs(float(opposing[0]["price"]) - price)
        if gap < LEVEL_CLEARANCE * sl_dist:
            kind = "dirence" if bias == "BUY" else "desteğe"
            return {"ok": False, "reason": f"{kind} çok yakın ({gap / pip_size:.0f} pip); hedefe yer yok"}
    return {"ok": True, "reason": "tüm kapılar geçti", "plan": {
        "symbol": sym, "direction": bias, "entry_price": price, "sl_pips": round(sl_dist / pip_size, 1),
        "tp_pips": round(tp_dist / pip_size, 1), "atr_pips": round(float(atr) / pip_size, 1), "score": analysis.get("score"),
        "news": effect,
        "note": f"Teknik {bias} ({float(analysis.get('score', 0)):+.1f}), TradingView {scan_row.get('summary')}, "
                f"uyum %{int(float(scan_row.get('agreement', 0)) * 100)}"
                + (f"; haber DESTEKLİYOR: {effect['lines'][0]}" if effect["verdict"] == "supports" else "")}}


async def open_from_scan(analyses: Dict[str, Dict[str, Any]], scan: Dict[str, Any],
                         calendar: Optional[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Tarama sırasına göre adayları değerlendirir; uygun olanlar için DEMO hesaba emir yazar.

    Dönen: {"opened": [...], "skipped": [{"symbol","reason"}]}.
    """
    from app.routers import forex as fx

    rows = {r["symbol"]: r for r in (scan or {}).get("all", [])}
    opened: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for sym, analysis in analyses.items():
        spec = fx.get_symbol_trading_specs(sym)
        verdict = plan_trade(analysis, rows.get(sym), calendar, float(spec.get("pip_size") or 0))
        if not verdict["ok"]:
            skipped.append({"symbol": sym, "reason": verdict["reason"]})
            continue
        plan = verdict["plan"]
        if time.time() - _last_open.get(sym, 0.0) < SYMBOL_COOLDOWN_SEC:
            skipped.append({"symbol": sym, "reason": "bu sembolde yakın zamanda işlem açıldı (soğuma)"})
            continue
        res = fx.open_scan_position(sym, plan["direction"], plan["sl_pips"], plan["tp_pips"], plan["atr_pips"],
                                    float(plan.get("score") or 0), plan["note"])
        if not res.get("ok"):
            skipped.append({"symbol": sym, "reason": res.get("reason", "emir yazılamadı")})
            continue
        _last_open[sym] = time.time()
        opened.append({"symbol": sym, "direction": plan["direction"], "lots": res["lots"], "risk_usd": res["risk_usd"],
                       "sl_pips": plan["sl_pips"], "tp_pips": plan["tp_pips"], "cmd_id": res["cmd_id"], "note": plan["note"]})
        logger.info("Fırsat işlemi demo hesaba iletildi: %s %s %s lot (%s)", sym, plan["direction"], res["lots"], res["cmd_id"])
    return {"opened": opened, "skipped": skipped}


def describe_opening(result: Dict[str, List[Dict[str, Any]]], names: Dict[str, str]) -> str:
    lines: List[str] = []
    for o in result["opened"]:
        nm = names.get(o["symbol"], o["symbol"])
        lines.append(f"• {nm} {o['direction']}: demo hesapta işlem açıldı — {o['lots']} lot, stop {o['sl_pips']:.0f} pip, "
                     f"hedef {o['tp_pips']:.0f} pip, risk ${o['risk_usd']:.2f}. {o['note']}")
    for s_ in result["skipped"]:
        nm = names.get(s_["symbol"], s_["symbol"])
        lines.append(f"• {nm}: açılmadı — {s_['reason']}")
    if not result["opened"]:
        lines.insert(0, "Şu an tüm kapılardan geçen yönlü fırsat yok; işlem açılmadı.")
    return "\n".join(lines)
