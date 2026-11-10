"""RUTİN KAYIT DEFTERİ (2026-11-10)

Desen: hummingbot/condor `routines/base.py` (MIT) — rutinler **sınıf/fonksiyon + kayıt defteri**
olarak tanımlanır, keşifle bulunur, kendi aralığında koşar, hatası süreci öldürmez.

NEDEN
-----
Bugüne kadar ölçüm/prob işleri (gölge raporu, kalibrasyon, beklenti taraması) **elle** veya
endpoint çağrısıyla koşuyordu; "geçen haftaya göre ne değişti" sorusu her seferinde sıfırdan
kuruluyordu. Bu modül rutinleri tek yerde toplar ve her koşunun sonucunu `routine_runs`
tablosuna yazar (panelde zaman serisi görünür).

TASARIM
-------
* `RoutineSpec`: ad, açıklama, aralık (sn), handler (async), `requires_mt5` (sunucuda MT5 YOK).
* `@routine(...)` dekoratörü kaydeder; `app.routines.<modül>` import edilince keşfedilir.
* `run_once(name)`: hata izolasyonu + süre ölçümü + DB kaydı; **hata rutini öldürmez**.
* `routine_loop()`: `_start_background` ile başlatılır; yalnız **vadesi gelen** rutinleri koşar.
* `requires_mt5=True` rutinler sunucuda ÇALIŞMAZ (MT5 terminali yok) — köprü makinesinde
  `python -m app.routines` ile koşulur; sunucu onları "yerel gerekli" diye raporlar.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("scalper.routines")


@dataclass
class RoutineSpec:
    name: str
    description: str
    interval_sec: int
    handler: Callable[[], Awaitable[Dict[str, Any]]]
    requires_mt5: bool = False
    output_note: str = ""
    tags: List[str] = field(default_factory=list)


_REGISTRY: Dict[str, RoutineSpec] = {}
_DISCOVERED = False


def routine(name: str, description: str, interval_sec: int, *, requires_mt5: bool = False,
            output_note: str = "", tags: Optional[List[str]] = None):
    """Rutin kayıt dekoratörü."""
    def deco(fn: Callable[[], Awaitable[Dict[str, Any]]]) -> Callable[[], Awaitable[Dict[str, Any]]]:
        _REGISTRY[str(name)] = RoutineSpec(
            name=str(name), description=str(description), interval_sec=int(interval_sec),
            handler=fn, requires_mt5=bool(requires_mt5), output_note=str(output_note),
            tags=list(tags or []))
        return fn
    return deco


def discover() -> Dict[str, RoutineSpec]:
    """`app.routines` paketindeki modülleri import ederek kayıtları toplar (idempotent)."""
    global _DISCOVERED
    if _DISCOVERED:
        return _REGISTRY
    import app.routines as pkg  # noqa: F401  (paket kendisi)
    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name in ("base", "__init__"):
            continue
        try:
            importlib.import_module(f"app.routines.{mod.name}")
        except Exception as exc:  # noqa: BLE001 - tek modül patlasa diğerleri yüklenmeli
            logger.warning("[RUTİN] modül yüklenemedi %s: %s", mod.name, exc)
    _DISCOVERED = True
    return _REGISTRY


def all_routines() -> List[RoutineSpec]:
    return sorted(discover().values(), key=lambda r: r.name)


def get(name: str) -> Optional[RoutineSpec]:
    return discover().get(str(name))


async def run_once(name: str, *, force: bool = False) -> Dict[str, Any]:
    """Bir rutini koşar; sonucu DB'ye yazar. `force=False` ise aralık dolmadan atlar."""
    from app import database
    spec = get(name)
    if spec is None:
        return {"ok": False, "error": f"rutin yok: {name}"}
    if spec.requires_mt5 and not _mt5_available():
        return {"ok": False, "skipped": True,
                "error": "bu rutin MT5 terminali ister (sunucuda yok) — köprü makinesinde koşulmalı"}
    if not force:
        last = await database.last_routine_run_ts(spec.name)
        if last and (time.time() - last) < spec.interval_sec:
            return {"ok": True, "skipped": True,
                    "error": f"aralık dolmadı ({int(time.time() - last)}s < {spec.interval_sec}s)"}
    started = time.time()
    ok = False
    try:
        result = await spec.handler()
        ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
        if not isinstance(result, dict):
            result = {"ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001 - rutin hatası süreci öldürmemeli
        logger.exception("[RUTİN] %s hata", spec.name)
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    dur = int((time.time() - started) * 1000)
    try:
        await database.save_routine_run(spec.name, started, dur, ok, result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[RUTİN] sonuç yazılamadı %s: %s", spec.name, exc)
    return {"name": spec.name, "ok": ok, "duration_ms": dur, "result": result}


def _mt5_available() -> bool:
    try:
        import MetaTrader5  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


async def routine_loop(poll_sec: int = 300) -> None:
    """Arka plan döngüsü: vadesi gelen rutinleri koşar (hata izolasyonlu, asla çıkmaz)."""
    discover()
    logger.info("[RUTİN] döngü başladı · %d rutin · poll=%ss", len(_REGISTRY), poll_sec)
    while True:
        try:
            for spec in all_routines():
                if spec.requires_mt5:
                    continue          # sunucuda MT5 yok
                try:
                    await run_once(spec.name, force=False)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[RUTİN] %s koşamadı: %s", spec.name, exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[RUTİN] döngü hatası: %s", exc)
        await asyncio.sleep(max(30, int(poll_sec)))
