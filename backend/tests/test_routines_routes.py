"""Rutin panel UÇ YOLLARI — frontend ile backend aynı yolu kullanmalı (2026-11-12)

CANLI HATA: Raporlar > Rutinler sayfası "API 404" veriyordu. Sebep: bu router'daki
TÜM uçlar `/api/...` altında tanımlıyken rutin uçları `/system/routines` (başında
`/api` yok) idi; frontend `/api/system/routines` çağırıyordu.

Bu test iki yolu da kilitler: biri kaldırılırsa/yanlış yazılırsa kırılır.
"""
from __future__ import annotations


def _paths() -> set[str]:
    from app.routers import system

    return {getattr(r, "path", "") for r in system.router.routes}


def test_rutin_liste_yolu_api_onekli_kayitli():
    paths = _paths()
    assert "/api/system/routines" in paths, "frontend bu yolu çağırıyor (RoutinesReport)"


def test_rutin_liste_eski_yol_da_calisiyor():
    assert "/system/routines" in _paths(), "eski yol kaldırılmamalı (geri uyum)"


def test_rutin_calistirma_yolu_api_onekli():
    paths = _paths()
    assert "/api/system/routines/{name}/run" in paths
    assert "/system/routines/{name}/run" in paths


def test_tum_system_uclari_api_onekli():
    """Regresyon: bu router'da `/api` öneki olmayan yeni uç eklenmesin.

    İstisnalar bilinçli: eski `/health`, `/system/agents` (geri uyum) ve
    rutinlerin eski yolları.
    """
    # Bilinçli istisnalar: /health eski sağlık yolu; /system/arms backend kayıt
    # listesi (frontend çağırmıyor); rutinlerin eski yolları geri uyum için duruyor.
    izinli = {"/health", "/system/arms", "/system/routines",
              "/system/routines/{name}/run", "/system/agents"}
    eksik = [p for p in _paths()
             if p.startswith("/") and not p.startswith("/api")
             and p not in izinli and "{" not in p.split("/")[1:2]]
    assert not eksik, f"/api öneki olmayan uçlar: {sorted(eksik)}"
