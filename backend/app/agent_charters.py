"""AJAN SÖZLEŞMELERİ — "hangi uzman ne zaman, neyi YAPMAZ" (2026-11-10)

Desen: hummingbot/condor `agents/<rol>/AGENT.md` (MIT) — frontmatter'da
`when_to_consult`, gövdede **"You handle" / "You do NOT handle"**.

NEDEN
-----
Bizim skill metinleri (`llm_skills`) serbest talimat bloklarıydı: modele **hangi uzmanın ne
zaman devreye gireceği** ve **neyi yapmadığı** söylenmiyordu. Ölçülen kusur: farklı yüzeylerde
birbirine çok benzeyen, jenerik cevaplar (21-AI konsensüsünün sabit üretim şüphesiyle aynı aile).
Sınır koymak, hem yönlendirmeyi hem cevap ayrışmasını iyileştirir.

TASARIM
-------
* Sözleşmeler saf veri (`CHARTERS`); `routing_block()` sistem istemine kompakt tablo olarak girer.
* `charter_block(active)` seçili uzmanların **not_for** satırlarını sert kısıt olarak ekler
  ("Bu uzman şunları YAPMAZ: …").
* Hiçbir karar değiştirmez; yalnız istem metni. LLM kapalıysa hiç çağrılmaz.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

#: İsim, `llm_skills.name` ile BİREBİR eşleşmeli (seed adları: app/database.py).
CHARTERS: List[Dict[str, str]] = [
    {
        "name": "Forex Makro Okuma",
        "when_to_consult": ("Seans/faiz/DXY/COT gibi makro bağlam sorulduğunda; bir paritede "
                            "yön kararının makro gerekçesi isteniyorsa."),
        "not_for": ("Emir gönderme/kapatma, lot veya risk bütçesi değiştirme, teknik seviye "
                    "hesabı (bunlar Trade Manager / Risk uzmanları)."),
    },
    {
        "name": "Scalper Trade Manager",
        "when_to_consult": ("Giriş/çıkış kuralları, SL-TP geometrisi, trailing/BE davranışı ve "
                            "işlem yönetimi konuşulduğunda."),
        "not_for": ("Makro yorum, haber takvimi yorumu, gerçek emir iletimi (panel/manuel onay)."),
    },
    {
        "name": "Risk Yönetimi Disiplini",
        "when_to_consult": ("Pozisyon boyutu, portföy ısısı, korelasyon/yiğılma, drawdown merdiveni "
                            "ve sermaye koruma sorularında."),
        "not_for": ("Sinyal üretme veya yön tahmini; performans ölçümü (Raporlar tarafı)."),
    },
    {
        "name": "Veri ve Haber Etki Okuma",
        "when_to_consult": ("Verinin tazeliği/kalitesi, takvim olayı etkisi, COT/sürpriz verisi "
                            "okunması gerektiğinde."),
        "not_for": ("Veri uydurma; kaynağı doğrulanmamış sayı verme; emir/pozisyon işlemleri."),
    },
]

_BY_NAME: Dict[str, Dict[str, str]] = {c["name"].strip().lower(): c for c in CHARTERS}


def all_charters() -> List[Dict[str, str]]:
    return [dict(c) for c in CHARTERS]


def get_charter(name: Any) -> Optional[Dict[str, str]]:
    return _BY_NAME.get(str(name or "").strip().lower())


def routing_block() -> str:
    """Sistem istemine giren kompakt yönlendirme tablosu (uzman → ne zaman)."""
    if not CHARTERS:
        return ""
    lines = ["UZMAN YÖNLENDİRME (hangi konuda hangi uzman devreye girer):"]
    for c in CHARTERS:
        lines.append(f"- {c['name']}: {c['when_to_consult']}")
    return "\n".join(lines)


def charter_block(active_skills: Optional[Iterable[Any]]) -> str:
    """Seçili uzmanların YAPMADIKLARI listesi — sert kısıt olarak isteme eklenir."""
    out: List[str] = []
    for key in (active_skills or []):
        c = get_charter(key)
        if not c:
            continue
        out.append(f"- {c['name']} şunları YAPMAZ: {c['not_for']}")
    if not out:
        return ""
    return "UZMAN SINIRLARI:\n" + "\n".join(out)
