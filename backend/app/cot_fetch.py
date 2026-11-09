"""CFTC TFF COT — İNDİRME + ARTEFAKT ÜRETİMİ (2026-11-09)

NEDEN BU MODÜL VAR
------------------
`app/cot_positions.py` yalnız **artefakt okur** ve açıkça "ağ erişimi yok, indirme
betiğin işi" der. İndirme tek bir yerde (`scripts/fetch_cot_positions.py`) ve
yalnız ELLE çalıştırılabiliyordu. Bu modül LLM bağlamına bağlandıktan sonra boşluk
görünür oldu: üretimde hiç kimse betiği çalıştırmadığı için LLM her seferinde
"COT pozisyonlanma verisi yok" diyordu (kullanıcı raporu, 2026-11-09).

Artık indirme/ayrıştırma/yazma tek uygulamada:
  * CLI  → `python -m scripts.fetch_cot_positions`
  * panel → `POST /api/system/cot-refresh` (Ayarlar'daki düğme)
  * otomatik → `cot_refresh_background_loop` (artefakt bayatlayınca)
Üçü de `refresh()` çağırır; kopya kod yok, davranış tek yerde.

KAYNAK: CFTC TFF raporu (`fut_fin_txt_YYYY.zip`) — **haftalık** ve ~3 gün
gecikmeli. `fut_disagg_txt` yalnız emtia içindir; FX için TFF doğru rapordur.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import urllib.request
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Optional

from app import cot_positions as cot

logger = logging.getLogger("scalper.cot")

URL_TEMPLATE = "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "artifacts" / "cot_positions.json"
UA = "Mozilla/5.0 (compatible; GloballCOTFetcher/1.0)"

#: CFTC haftalık yayınlar; bu süreden eski artefakt "bayat" sayılır ve otomatik
#: tazeleme tetiklenir. 9 gün = bir haftalık yayın + tatil payı.
STALE_AFTER_DAYS = 9.0


def _read_zip(source: Path) -> list[dict]:
    """Zip içindeki TFF metnini CSV satırlarına çevir."""
    with zipfile.ZipFile(source) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".txt")]
        if not names:
            raise ValueError(f"Zip içinde .txt yok: {z.namelist()}")
        with z.open(names[0]) as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
            return list(csv.DictReader(text))


def _download(year: int, dest: Path) -> Path:
    url = URL_TEMPLATE.format(year=year)
    logger.info("COT indiriliyor: %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    if not data:
        raise ValueError(f"Boş yanıt: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    logger.info("COT indirildi: %.0f KB → %s", len(data) / 1024, dest)
    return dest


def refresh(*, years: Optional[list[int]] = None, source_zip: Optional[str] = None,
            out: Optional[str] = None, keep_zip: bool = False) -> dict[str, Any]:
    """COT raporunu indir/aç ve artefaktı yaz. Hata FIRLATMAZ; sonuç sözlüğü döner."""
    out_path = Path(out) if out else DEFAULT_OUT
    tmp_dir = ROOT / "artifacts" / "cot_src"
    result: dict[str, Any] = {"ok": False, "artifact_path": str(out_path)}
    try:
        sources: list[Path] = []
        if source_zip:
            p = Path(source_zip)
            if not p.exists():
                raise ValueError(f"Dosya yok: {p}")
            sources = [p]
        else:
            tmp_dir.mkdir(parents=True, exist_ok=True)
            # İçinde bulunduğumuz yıl BOŞ dönebilir (CFTC dosyayı yıl boyunca
            # büyütür ama bazı dönemlerde 404/boş olur) → önceki yıla da bak.
            target_years = years or [date.today().year]
            for year in target_years:
                dest = tmp_dir / f"fut_fin_txt_{year}.zip"
                try:
                    sources.append(_download(year, dest))
                except Exception as exc:  # noqa: BLE001 - bir yıl düşerse diğeri denenir
                    logger.info("COT indirme başarısız (%s): %s", year, exc)
            if not sources:
                raise ValueError("Hiçbir yıl indirilemedi (CFTC erişilemiyor olabilir)")

        all_rows: list[dict] = []
        for src in sources:
            all_rows.extend(_read_zip(src))

        parsed = cot.parse_rows(all_rows)
        if not parsed:
            raise ValueError("FX satırı bulunamadı — kaynak dosya beklenen şema değil.")

        artifact = cot.build_artifact(parsed)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
        cot.reset_cache()                      # okuma yolu yeni dosyayı görsün
        result.update({
            "ok": True,
            "report_date": artifact.get("report_date"),
            "currencies": len(artifact.get("currencies") or {}),
            "unavailable": artifact.get("unavailable") or [],
            "source": artifact.get("source"),
        })
        logger.info("COT artefaktı yazıldı: rapor %s · %d para birimi",
                    artifact.get("report_date"), len(artifact.get("currencies") or {}))
    except Exception as exc:  # noqa: BLE001 - çağıran yüzeyler (panel/döngü) çökmemeli
        result["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("COT tazeleme başarısız: %s", result["error"])
    finally:
        if not keep_zip:
            for src in (tmp_dir.glob("fut_fin_txt_*.zip") if tmp_dir.exists() else []):
                try:
                    src.unlink()
                except OSError:
                    pass
    return result


def artifact_age_days() -> Optional[float]:
    """Artefaktın **rapor** yaşı (gün). Artefakt yoksa/bozuksa `None`."""
    data = cot.load_artifact()
    if not data:
        return None
    return cot._age_days(data.get("report_date"))


def is_stale(max_age_days: float = STALE_AFTER_DAYS) -> bool:
    age = artifact_age_days()
    return age is None or age > float(max_age_days)


async def cot_refresh_background_loop() -> None:
    """COT artefaktını BAYATLADIĞINDA otomatik tazeler.

    NEDEN: üretici yalnız elle çalıştırılabilen bir betikti; kimse çalıştırmayınca
    LLM bağlamı sessizce "COT verisi yok" diyordu (2026-11-09 kullanıcı raporu).
    CFTC haftalık yayınlar → günde bir kontrol yeterli.
    """
    import asyncio

    await asyncio.sleep(45)          # açılış yükünü (market warmup) bekletme
    while True:
        try:
            if is_stale():
                age = artifact_age_days()
                logger.info("[COT] artefakt bayat (yaş: %s) → otomatik tazeleniyor",
                            "yok" if age is None else f"{age:.1f} gün")
                res = await asyncio.to_thread(refresh)
                if res.get("ok"):
                    logger.info("[COT] otomatik tazeleme tamam: rapor %s", res.get("report_date"))
                else:
                    logger.warning("[COT] otomatik tazeleme başarısız: %s", res.get("error"))
        except asyncio.CancelledError:
            logger.info("[COT] arka plan döngüsü durduruldu.")
            raise
        except Exception as exc:  # noqa: BLE001 - döngü asla ölmesin
            logger.warning("[COT] döngü hatası: %s", exc)
        await asyncio.sleep(24 * 3600)
