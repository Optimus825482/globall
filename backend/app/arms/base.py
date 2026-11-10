"""SİNYAL KOLU SÖZLEŞMESİ (2026-11-10)

Desen: hummingbot/condor `agents/<rol>/controllers/` + `loops/` (MIT) — bir kol **dosya**
olarak tanımlanır, `signal()` sözleşmesine uyar, replay ve canlı aynı dosyayı kullanır.

SÖZLEŞME (condor'da yazılı olan, bizde kilitlenen)
--------------------------------------------------
1. Çıktı serisi bar sayısıyla AYNI uzunlukta olmalı.
2. Değerler yalnız **+1 / −1 / 0**:
   * `+1` → bu barda LONG adayı,
   * `−1` → bu barda SHORT adayı,
   * `0`  → **yeni sinyal YOK**. `0` bir pozisyonu **KAPATMAZ**; çıkış ayrı katmanın işidir
     (SL/TP/trailing/zaman-stopu). Bu ayrım, "sinyal" ile "pozisyon yönetimi"ni karıştırmayı
     önler — çıkış tarafının ayrı ölçülmesi bu sayede mümkün.
3. `signal()` **saf** olmalı: girdi → çıktı, yan etki yok, durum tutmaz (deterministik).
4. Kod **vektörize** yazılır (pandas/numpy mantığı): satır satır pozisyon yöneten döngü YOK.
   (Sinyal üretimi toplu; pozisyon yönetimi ayrı katman.)
5. Kol kendi `symbols` listesini bildirir; motor o listeyi `blocked_symbols` ve
   `proof_scope` kapılarıyla birlikte uygular.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

SIGNAL_LONG = 1
SIGNAL_SHORT = -1
SIGNAL_NONE = 0
VALID_SIGNALS = frozenset({SIGNAL_LONG, SIGNAL_SHORT, SIGNAL_NONE})


@dataclass
class ArmSpec:
    """Bir sinyal kolunun tanımı."""
    name: str
    description: str
    timeframe: str
    symbols: List[str]
    handler: Callable[..., List[int]]
    evidence: str = ""          # ölçüm/kanıt notu (hangi veri, hangi sonuç)
    tags: List[str] = field(default_factory=list)
    vectorized: bool = True     # sözleşme gereği True; satır-döngüsü bilinçli istisna ise False


_REGISTRY: Dict[str, ArmSpec] = {}


def register_arm(spec: ArmSpec) -> ArmSpec:
    """Kolu kaydeder (ad benzersiz; sessizce ezmez)."""
    if spec.name in _REGISTRY:
        raise ValueError(f"kol adı zaten kayıtlı: {spec.name}")
    _REGISTRY[spec.name] = spec
    return spec


def all_arms() -> List[ArmSpec]:
    _discover()
    return sorted(_REGISTRY.values(), key=lambda a: a.name)


def get_arm(name: Any) -> Optional[ArmSpec]:
    _discover()
    return _REGISTRY.get(str(name or ""))


_DISCOVERED = False


def _discover() -> None:
    """`app.arms` paketindeki kol modüllerini import eder (idempotent)."""
    global _DISCOVERED
    if _DISCOVERED:
        return
    import importlib
    import pkgutil

    import app.arms as pkg
    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name in ("base", "__init__"):
            continue
        try:
            importlib.import_module(f"app.arms.{mod.name}")
        except Exception:  # noqa: BLE001 - tek kol patlasa diğerleri yüklenmeli
            pass
    _DISCOVERED = True


def validate_signals(series: Sequence[int], n_bars: int, arm_name: str = "?") -> List[str]:
    """Sözleşme denetimi: uzunluk + değer kümesi. Dönen liste boşsa geçerli."""
    errs: List[str] = []
    if len(series) != n_bars:
        errs.append(f"{arm_name}: uzunluk uyuşmuyor ({len(series)} != {n_bars})")
    bad = {int(v) for v in series if int(v) not in VALID_SIGNALS}
    if bad:
        errs.append(f"{arm_name}: geçersiz sinyal değerleri {sorted(bad)} (yalnız +1/-1/0)")
    return errs


def signals_to_rows(bars: Sequence[Any], series: Sequence[int]) -> List[int]:
    """Yardımcı: sinyal serisini bar zaman damgalarıyla hizalar (replay/canlı için)."""
    if len(bars) != len(series):
        raise ValueError("bar sayısı ile sinyal sayısı eşleşmiyor")
    return [int(s) for s in series]
