"""İSTATİSTİKSEL DOĞRULAMA ARTEFAKTI (2026-11-09)

NEDEN VAR
---------
`scripts/edge_significance.py` (Reality Check / SPA / StepM / MCS) ve
`scripts/purged_cpcv_report.py` (PSR / DSR / PBO / MinTRL) şimdiye kadar
YALNIZ stdout'a yazıyordu: sonuç uçucuydu. Aynı sayıyı panele veya LLM
bağlamına taşımak mümkün değildi, yani "hangi strateji istatistiksel olarak
gürültü" bilgisi karar veren hiçbir yüzeye ulaşmıyordu.

Artık iki betik de tek bir JSON artefaktına **bölüm bölüm** yazar
(`significance`, `cpcv`) ve burası onu okuyup LLM için KISA hükme indirir.

KURAL (fail-closed): artefakt yoksa/eskimişse LLM'e "doğrulama yapılmamış"
bilgisi gider. Uydurma hüküm ÜRETİLMEZ — "kenar var" demek, kanıt yokken
verilebilecek en pahalı yanlıştır.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

#: Artefakt bundan eskiyse "taze değil" sayılır: strateji seti/örneklem
#: değiştiğinde eski hüküm yanıltıcı olur. 30 gün = kaba bir tazelik sınırı.
STALE_DAYS = 30.0
DEFAULT_ARTIFACT = Path(__file__).resolve().parents[1] / "artifacts" / "edge_validation.json"

_lock = threading.Lock()
_cache: dict[str, Any] = {"path": None, "mtime": None, "data": None, "checked_at": 0.0}


def _artifact_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.getenv("EDGE_VALIDATION_ARTIFACT")
    return Path(env) if env else DEFAULT_ARTIFACT


def write_section(section: str, payload: dict[str, Any], path: str | Path | None = None) -> str:
    """Bir bölümü artefakta yazar; diğer bölümleri KORUR.

    Betikler ayrı ayrı koşabildiği için (biri diğerini ezmemeli) okuma-yazma
    birleştirir. Dönen değer yazılan dosyanın yolu.
    """
    target = _artifact_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    try:
        if target.exists():
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
    except (OSError, ValueError):
        data = {}
    data[str(section)] = {"generated_at": time.time(), "payload": payload}
    data["updated_at"] = time.time()
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    invalidate_cache()
    return str(target)


def invalidate_cache() -> None:
    with _lock:
        _cache.update({"path": None, "mtime": None, "data": None, "checked_at": 0.0})


def load(path: str | Path | None = None, *, max_age_seconds: float = 60.0) -> dict[str, Any] | None:
    """Artefaktı oku (mtime önbellekli). Yok/bozuksa ``None``."""
    target = _artifact_path(path)
    try:
        mtime = target.stat().st_mtime
    except OSError:
        return None
    now = time.time()
    with _lock:
        if (_cache["path"] == str(target) and _cache["mtime"] == mtime
                and now - float(_cache["checked_at"] or 0.0) < max_age_seconds):
            return _cache["data"]
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    with _lock:
        _cache.update({"path": str(target), "mtime": mtime, "data": data, "checked_at": now})
    return data


def _age_days(data: dict[str, Any]) -> float | None:
    ts = data.get("updated_at")
    if not isinstance(ts, (int, float)) or ts <= 0:
        return None
    return max(0.0, (time.time() - float(ts)) / 86400.0)


def summary(path: str | Path | None = None) -> dict[str, Any]:
    """Artefaktın LLM/panel için kompakt özeti (fail-closed)."""
    data = load(path)
    if not data:
        return {"available": False, "reason": "doğrulama artefaktı yok — betikler koşturulmalı",
                "significance": None, "cpcv": None, "stale": True}
    age = _age_days(data)
    sig = (data.get("significance") or {}).get("payload") or None
    cpcv = (data.get("cpcv") or {}).get("payload") or None
    out: dict[str, Any] = {
        "available": bool(sig or cpcv),
        "age_days": None if age is None else round(age, 2),
        "stale": bool(age is not None and age > STALE_DAYS),
        "significance": None,
        "cpcv": None,
    }
    if sig:
        pv = sig.get("pvalues") or {}
        out["significance"] = {
            "verdict": sig.get("verdict"),
            "spa_p": pv.get("spa"),
            "reality_check_p": pv.get("reality_check"),
            "stepm_p": pv.get("stepm"),
            "n_periods": pv.get("n_periods"),
            "size": pv.get("size"),
            "mcs_included": sig.get("mcs_included") or [],
            "stepm_superior": sig.get("stepm_superior") or [],
        }
    if cpcv:
        best = cpcv.get("best")
        rows = {r.get("name"): r for r in (cpcv.get("strategies") or []) if isinstance(r, dict)}
        out["cpcv"] = {
            "verdict": cpcv.get("verdict"),
            "best": best,
            "n_trials": cpcv.get("n_trials"),
            "pbo": cpcv.get("pbo"),
            "thresholds": cpcv.get("thresholds"),
            # Yalnız hükmü olan satırlar: LLM'e 50 kolon dökmeyelim.
            "strategies": {
                name: {"psr": r.get("psr"), "dsr": r.get("dsr"), "mintrl": r.get("mintrl")}
                for name, r in rows.items()
            },
        }
    return out


def compact_lines(path: str | Path | None = None) -> list[str]:
    """LLM bağlamına gidecek 2-4 satırlık metin (kanıt yoksa açıkça söyler)."""
    s = summary(path)
    if not s.get("available"):
        return ["İstatistiksel doğrulama (SPA/DSR/PBO): KAYIT YOK — 'kenar var' iddiası doğrulanmamış sayılmalı."]
    lines: list[str] = []
    sig = s.get("significance")
    if sig:
        lines.append(
            f"Edge anlamlılığı: {sig.get('verdict')} "
            f"(SPA p={sig.get('spa_p')}, RC p={sig.get('reality_check_p')}, "
            f"StepM p={sig.get('stepm_p')}, {sig.get('n_periods')} dönem, alfa={sig.get('size')})"
        )
        if sig.get("mcs_included"):
            lines.append("Model güvenilirlik kümesi (MCS) içindekiler: " + ", ".join(sig["mcs_included"][:12]))
    cpcv = s.get("cpcv")
    if cpcv:
        lines.append(
            f"PSR/DSR/PBO: {cpcv.get('verdict')} (en iyi: {cpcv.get('best')}, "
            f"deneme={cpcv.get('n_trials')}, PBO={cpcv.get('pbo')}, eşikler={cpcv.get('thresholds')})"
        )
    if s.get("stale"):
        lines.append(f"UYARI: bu doğrulama {s.get('age_days')} gün önce üretildi ve ESKİMİŞ sayılıyor.")
    return lines
