"""GÖLGE MODLAR RAPORU (2026-11-09)

NEDEN: sistemde kararı DEĞİŞTİRMEDEN ölçüm yapan birden çok mekanizma var
(LLM kararları, ML kalibrasyonu, geometri, risk kapısı, kanıt kapısı). Hangisinin
kaç örnek topladığı, hangisinin karar eşiğine yaklaştığı **tek ekranda**
görünmüyordu; kullanıcı her biri için ayrı sekmeye bakmak zorundaydı.

TASARIM: her gölge için tek satır — mod, örnek sayısı, karar eşiği, hazır mı,
ve "bu gölge neyi ölçüyor" tek cümle. Hiçbir satır UYDURULMAZ: veri yoksa
`n=None` + "veri yok" yazar.

Hepsi okuma; hiçbir ayarı DEĞİŞTİRMEZ.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from app.config import config  # FOREX_ONLY: spot hattı kapalıysa sayaç dolmaz

logger = logging.getLogger("scalper.shadow_report")

#: Karar için gereken en az örnek (mekanizmaya göre).
NEEDED = {
    "llm_shadow": 80,          # `ml_probability.MIN_SAMPLES` ile aynı kalibrasyon eşiği
    "ml_calibration": 200,     # `ml_calibration_report.MIN_SAMPLES`
    "geometry_shadow": 300,    # `report_geometry_shadow --min-samples`
}


def _item(key: str, label: str, *, mode: str, active: bool, measures: str,
          n: Optional[int] = None, needed: Optional[int] = None,
          metric: Optional[str] = None, note: str = "",
          detail: Optional[str] = None, stalled: bool = False) -> dict[str, Any]:
    ready = bool(n is not None and needed and n >= needed)
    return {
        "key": key, "label": label, "mode": mode, "active": bool(active),
        "measures": measures, "n": n, "needed": needed, "ready": ready,
        # 2026-11-12: `stalled` = "bu kurulumda örnek ÜRETİLMEZ" (0/200 gibi satırlar
        # "hat çalışmıyor" sanılmasın). UI bunu rozetle gösterir.
        "stalled": bool(stalled),
        "progress_pct": (round(100.0 * min(n, needed) / needed, 1)
                         if (n is not None and needed) else None),
        "metric": metric, "note": note, "detail_endpoint": detail,
    }


async def build() -> dict[str, Any]:
    """Tüm gölge modların durumu (her blok kendi hatasını yutar)."""
    items: list[dict[str, Any]] = []

    # 1) LLM kararları gölgesi — reddedilenler de fiyatla izlenir.
    try:
        from app import database
        n_rows = await database.count_llm_review_shadow_rows()
        items.append(_item(
            "llm_shadow", "LLM Trader kararları (gölge sonuç)", mode="on", active=True,
            measures="Veto/danışman kararlarının sonucu: reddedilen işlem sonradan TP mi SL mi gördü",
            n=n_rows, needed=NEEDED["llm_shadow"],
            metric=f"{n_rows} çözülmüş karar",
            note="Güven kalibrasyonu ve eşik önerisi bu veriden çıkar.",
            detail="/api/llm-review/summary"))
    except Exception as exc:  # noqa: BLE001
        items.append(_item("llm_shadow", "LLM Trader kararları (gölge sonuç)", mode="on",
                           active=False, measures="LLM karar gölgesi",
                           note=f"okunamadı: {type(exc).__name__}"))

    # 2) ML kalibrasyonu (spot/velocity) — karar DEĞİŞMEZ, yalnız sayaç.
    try:
        from app import ml_shadow
        c = ml_shadow.counters() or {}
        obs = c.get("observations")
        items.append(_item(
            "ml_calibration", "ML isabet olasılığı kalibrasyonu", mode="on" if c.get("enabled") else "off",
            active=bool(c.get("enabled")),
            measures="Modelin 'isabet olasılığı' dürüst mü (Brier/ECE) + çekimserlik oranı",
            n=int(obs) if isinstance(obs, (int, float)) else None,
            needed=NEEDED["ml_calibration"],
            metric=(f"gözlem {obs}, çekimser %{c.get('abstain_rate_pct')}" if obs else None),
            note=("Artefakt yüklü" if c.get("artifact_loaded") else "Kalibrasyon eğrisi (artefakt) yok"),
            detail="/api/reports/ml-calibration",
            # Spot/velocity hattı kapalıysa bu sayaç HİÇ dolmaz — 0/200 yanıltmasın.
            stalled=(not obs and bool(getattr(config, "FOREX_ONLY", False)))))
    except Exception as exc:  # noqa: BLE001
        items.append(_item("ml_calibration", "ML isabet olasılığı kalibrasyonu", mode="off",
                           active=False, measures="ML kalibrasyon gölgesi",
                           note=f"okunamadı: {type(exc).__name__}"))

    # 3) Geometri gölgesi (SL %0,9 / hedef ATR×4) — karar DEĞİŞMEZ.
    try:
        from app import database, geometry_shadow
        n = await database.count_geometry_shadow_rows()
        on = geometry_shadow.enabled()
        items.append(_item(
            "geometry_shadow", "Geometri gölgesi (SL %0,9 · hedef ATR×4)", mode="on" if on else "off",
            active=on,
            measures="Farklı SL/hedef oranı aynı sinyallerde daha iyi EV verir mi",
            n=n, needed=NEEDED["geometry_shadow"],
            metric=f"{n} aday",
            note=("Kök neden geometri hipotezi: break-even için isabet %67 gerekiyor, gerçek %56."
                  if n else "Henüz aday yazılmadı — gölge açıkken ilk işlemlerden sonra dolar."),
            detail="/api/reports/ml-calibration",
            stalled=(not on)))
    except Exception as exc:  # noqa: BLE001
        items.append(_item("geometry_shadow", "Geometri gölgesi", mode="off", active=False,
                           measures="SL/hedef oranı gölgesi", note=f"okunamadı: {type(exc).__name__}"))

    # 3b) FOREX ML SKOR GÖLGESİ (2026-11-10): artifact'tan hesaplanan isabet
    # olasılığı her yeni karara yazılır; sonucu mevcut LLM gölge hattı izler
    # → prequential IC/join için yeni altyapı gerekmez.
    try:
        from app import database, forex_ml
        art = forex_ml.load_scoring_model()
        n = await database.count_llm_ml_prob_rows()
        stream = await database.get_forex_ml_prequential()
        n_res = len(stream)
        metric = f"model: lojistik, {len(art.get('feature_names') or [])} özellik" if art else None
        note = ("artifact yok: önce Forex ML sekmesinden eğit" if not art else
                "yalnız eğitim tarihinden SONRAKİ kararlar skorlanır (in-sample sızıntı yok)")
        # PREQUENTIAL IC: çözülmüş kararlarda model olasılığının sıralama gücü.
        # n_res >= 40 altında ölçüm gürültülü → "birikiyor" yazar, sayı uydurmaz.
        if n_res >= 40:
            ic = forex_ml._spearman([x["prob"] for x in stream], [float(x["hit"]) for x in stream])
            if ic is not None:
                metric = (f"prequential IC {ic:+.3f} (n={n_res}) "
                          f"{'✓' if ic > 0.1 else 'zayıf' if ic > 0 else 'sinyal yok'}")
        items.append(_item(
            "forex_ml_shadow", "Forex ML isabet olasılığı (skor gölgesi)", mode="shadow",
            active=art is not None,
            measures="Modelin karar anındaki isabet olasılığı vs gerçekleşen sonuç (prequential)",
            n=n, needed=300, metric=metric, note=note + f" · çözülmüş {n_res}",
            detail="/api/reports/ml-calibration"))
    except Exception as exc:  # noqa: BLE001
        items.append(_item("forex_ml_shadow", "Forex ML skor gölgesi", mode="unknown",
                           active=False, measures="Forex ML skor gölgesi",
                           note=f"okunamadı: {type(exc).__name__}"))

    # 4) Portföy risk kapısı — varsayılan `shadow` (yalnız loglar).
    try:
        from app import portfolio_risk
        from app.routers import forex as _fx
        st = portfolio_risk.settings_cfg(_fx._AUTO_SETTINGS)
        mode = str(st.get("mode") or "shadow")
        items.append(_item(
            "risk_gate", "Portföy risk kapısı", mode=mode, active=(mode != "off"),
            measures="Korelasyon/yığılma/drawdown gerekçesiyle işlem engellenmeli mi",
            note=("GÖLGE: engellemez, yalnız 'engellerdi' yazar" if mode == "shadow"
                  else "ENFORCE: gerçekten engeller/ lotu küçültür" if mode == "enforce"
                  else "kapalı"),
            detail="/api/portfolio/gate-log"))
    except Exception as exc:  # noqa: BLE001
        items.append(_item("risk_gate", "Portföy risk kapısı", mode="unknown", active=False,
                           measures="Risk kapısı gölgesi", note=f"okunamadı: {type(exc).__name__}"))

    # 5) Kanıt kapısı (P2) — varsayılan `off`.
    try:
        from app.routers import forex as _fx
        mode = str(getattr(_fx._AUTO_SETTINGS, "abstain_gate_mode", "off") or "off")
        items.append(_item(
            "abstain_gate", "Kanıt kapısı (Wilson alt sınırı)", mode=mode, active=(mode != "off"),
            measures="Sembolün kapanmış işlemleri break-even ÜSTÜNDE bir kenar kanıtlıyor mu",
            note=("ÖLÇÜM: replay defterinde hiç tetiklenmiyor; GERÇEK defterde (isabet %56,2 vs "
                  "break-even %67,2) TAM DURDURUCU → açmak iş kararı"
                  if mode == "off" else
                  "GÖLGE: engellemez, 'engellerdi' diye loglar" if mode == "shadow"
                  else "ENFORCE: kenar kanıtlanmamış sembolde işlem açılmaz")))
    except Exception as exc:  # noqa: BLE001
        items.append(_item("abstain_gate", "Kanıt kapısı", mode="unknown", active=False,
                           measures="Kanıt kapısı gölgesi", note=f"okunamadı: {type(exc).__name__}"))

    visible = [i for i in items if i["mode"] != "off"]
    return {
        "generated_at": time.time(),
        "count": len(items),
        "active_shadow": sum(1 for i in visible if i["active"] and i["mode"] in ("shadow", "on")),
        "ready_for_decision": sum(1 for i in visible if i["ready"]),
        # Kullanıcı kararı: pasif (off) mekanizmalar raporda GİZLENİR; sayı
        # `hidden_off`'ta dürüstlük için durur.
        "hidden_off": sum(1 for i in items if i["mode"] == "off"),
        "items": visible,
        "note": ("Gölge = kararı DEĞİŞTİRMEZ, yalnız ölçer. `enforce` yazan bir kapı kararı "
                 "değiştirir; `n/needed` karar için gereken örnek ilerlemesidir."),
    }
