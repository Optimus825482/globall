"""COT POZİSYONLARINI İNDİR — CFTC TFF raporu → artefakt JSON (2026-11-09)

NE YAPAR
--------
CFTC'nin yıllık TFF (Traders in Financial Futures) zip'ini indirir, FX para
birimlerini ayıklar ve `backend/artifacts/cot_positions.json` yazar. Üretim
katmanı (`app/cot_positions.py`) yalnız bu artefaktı okur — **çalışma anında
CFTC'ye gidilmez** (ağ hatası/gecikme sinyal yolunu etkilemez).

DOĞRULANMIŞ KAYNAK
------------------
    https://www.cftc.gov/files/dea/history/fut_fin_txt_YYYY.zip

`fut_disagg_txt_YYYY.zip` DENENDİ ve YALNIZ EMTİA içeriyor (333 market, hiç FX
yok). FX sözleşmeleri TFF raporunda. Zip içindeki dosya: `FinFutYY.txt`.

KULLANIM
--------
    python -m scripts.fetch_cot_positions                      # bu yıl, indir, yaz
    ... --year 2025 --year 2026                                # iki yıl birleştir
    ... --file cot.zip                                          # ağ yerine yerel zip
    ... --out artifacts/cot_positions.json
    ... --dry-run                                               # yazma, özet bas

NOT: COT haftalıktır ve **3 gün gecikmelidir** (Salı pozisyonu Cuma yayınlanır).
Sinyal kapısı olarak kullanmak backtest ister; bu betik yalnız BAĞLAM üretir.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import cot_positions as cot  # noqa: E402

URL_TEMPLATE = "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"
DEFAULT_OUT = ROOT / "artifacts" / "cot_positions.json"
UA = "Mozilla/5.0 (compatible; GloballCOTFetcher/1.0)"


def _read_zip(source: Path) -> list[dict]:
    """Zip içindeki TFF metnini CSV satırlarına çevir."""
    with zipfile.ZipFile(source) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".txt")]
        if not names:
            raise SystemExit(f"Zip içinde .txt yok: {z.namelist()}")
        with z.open(names[0]) as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
            return list(csv.DictReader(text))


def _download(year: int, dest: Path) -> Path:
    url = URL_TEMPLATE.format(year=year)
    print(f"indiriliyor: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    if not data:
        raise SystemExit(f"Boş yanıt: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"  {len(data)/1024:.0f} KB → {dest}")
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CFTC TFF COT → artefakt JSON")
    ap.add_argument("--year", type=int, action="append", help="yıl (birden fazla verilebilir)")
    ap.add_argument("--file", help="ağ yerine yerel zip kullan")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--dry-run", action="store_true", help="artefaktı yazma")
    ap.add_argument("--keep-zip", action="store_true", help="indirilen zip'i silme")
    args = ap.parse_args(argv)

    tmp_dir = ROOT / "artifacts" / "cot_src"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    sources: list[Path] = []
    if args.file:
        p = Path(args.file)
        if not p.exists():
            raise SystemExit(f"Dosya yok: {p}")
        sources = [p]
    else:
        years = args.year or [date.today().year]
        for year in years:
            dest = tmp_dir / f"fut_fin_txt_{year}.zip"
            sources.append(_download(year, dest))

    all_rows: list[dict] = []
    for src in sources:
        rows = _read_zip(src)
        print(f"  {src.name}: {len(rows)} satır")
        all_rows.extend(rows)

    parsed = cot.parse_rows(all_rows)
    if not parsed:
        raise SystemExit("FX satırı bulunamadı — kaynak dosya beklenen şema değil.")

    artifact = cot.build_artifact(parsed)

    print()
    print("=" * 96)
    print(f"COT POZİSYONLANMA · rapor {artifact['report_date']} · {len(artifact['currencies'])} para birimi")
    print(f"kaynak: {artifact['source']}  (haftalık, ~3 gün gecikmeli)")
    print("=" * 96)
    print(f"{'kur':<6}{'OI':>10}{'lev_net':>12}{'lev %OI':>9}{'asset %OI':>11}"
          f"{'bias':>7}{'duruş':>9}{'kalabalık':>11}{'Δhafta':>9}")
    print("-" * 96)
    for cur, s in sorted(artifact["currencies"].items(),
                         key=lambda kv: -abs(kv[1]["bias"])):
        am = "-" if s["asset_mgr_net_pct"] is None else f"{s['asset_mgr_net_pct']:+.1f}"
        wow = "-" if s["change_wow_pct"] is None else f"{s['change_wow_pct']:+.2f}"
        crowd = f"%{s['crowding_pct']:.0f}" + (" ⚠" if s["crowded"] else "")
        print(f"{cur:<6}{s['open_interest']:>10,.0f}{s['lev_net']:>+12,.0f}"
              f"{s['lev_net_pct']:>+9.1f}{am:>11}{s['bias']:>+7.2f}"
              f"{s['stance']:>9}{crowd:>11}{wow:>9}")
    print("-" * 96)
    div = [c for c, s in artifact["currencies"].items() if s.get("divergence")]
    if div:
        print(f"Ayrışma (sıcak para ile gerçek para ZIT yönde): {', '.join(sorted(div))}")
    if artifact.get("unavailable"):
        print(f"Bu raporda YOK (uydurulmadı): {', '.join(artifact['unavailable'])}")
    print()
    print("Yorum: `bias` = tanh(lev_net_pct/15). COT haftalık ve gecikmelidir;")
    print("       skorlamaya sokmak backtest ister — bu çıktı BAĞLAMdır, sinyal değil.")

    if args.dry_run:
        print("\n[dry-run] artefakt yazılmadı.")
        return 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nartefakt yazıldı: {out}")
    if not args.keep_zip:
        for src in sources:
            if src.parent == tmp_dir:
                try:
                    src.unlink()
                except OSError:
                    pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
