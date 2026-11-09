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
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import cot_fetch  # noqa: E402

DEFAULT_OUT = ROOT / "artifacts" / "cot_positions.json"


def main(argv=None) -> int:
    """İnce CLI: mantık `app/cot_fetch.py` (panel ucu ve otomatik döngüyle AYNI kod).

    2026-11-09: indirme mantığı `app/cot_fetch`'e taşındı. Sebep: yalnız betikten
    erişilebilen bir üretici, LLM bağlamına bağlanan veriyi üretimde hiç
    üretemiyordu ("COT verisi yok").
    """
    ap = argparse.ArgumentParser(description="CFTC TFF COT → artefakt JSON")
    ap.add_argument("--year", type=int, action="append", help="yıl (birden fazla verilebilir)")
    ap.add_argument("--file", help="ağ yerine yerel zip kullan")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--dry-run", action="store_true", help="artefaktı yazma")
    ap.add_argument("--keep-zip", action="store_true", help="indirilen zip'i silme")
    args = ap.parse_args(argv)

    res = cot_fetch.refresh(years=args.year, source_zip=args.file,
                            out=args.out, keep_zip=args.keep_zip)
    if not res.get("ok"):
        print(f"HATA: {res.get('error')}")
        return 1

    artifact = json.loads(Path(args.out).read_text(encoding="utf-8"))
    print()
    print("=" * 96)
    print(f"COT POZİSYONLANMA · rapor {artifact['report_date']} · {len(artifact['currencies'])} para birimi")
    print(f"kaynak: {artifact['source']}  (haftalık, ~3 gün gecikmeli)")
    print("=" * 96)
    print(f"{'kur':<6}{'OI':>10}{'lev_net':>12}{'lev %OI':>9}{'asset %OI':>11}"
          f"{'bias':>7}{'duruş':>9}{'kalabalık':>11}{'Δhafta':>9}")
    print("-" * 96)
    for cur, st in sorted(artifact["currencies"].items(), key=lambda kv: -abs(kv[1]["bias"])):
        am = "-" if st["asset_mgr_net_pct"] is None else f"{st['asset_mgr_net_pct']:+.1f}"
        wow = "-" if st["change_wow_pct"] is None else f"{st['change_wow_pct']:+.2f}"
        crowd = f"%{st['crowding_pct']:.0f}" + (" ⚠" if st["crowded"] else "")
        print(f"{cur:<6}{st['open_interest']:>10,.0f}{st['lev_net']:>+12,.0f}"
              f"{st['lev_net_pct']:>+9.1f}{am:>11}{st['bias']:>+7.2f}"
              f"{st['stance']:>9}{crowd:>11}{wow:>9}")
    print("-" * 96)
    div = [c for c, st in artifact["currencies"].items() if st.get("divergence")]
    if div:
        print(f"Ayrışma (sıcak para ile gerçek para ZIT yönde): {', '.join(sorted(div))}")
    if artifact.get("unavailable"):
        print(f"Bu raporda YOK (uydurulmadı): {', '.join(artifact['unavailable'])}")
    print()
    print("Yorum: `bias` = tanh(lev_net_pct/15). COT haftalık ve gecikmelidir;")
    print("       skorlamaya sokmak backtest ister — bu çıktı BAĞLAMdır, sinyal değil.")
    if args.dry_run:
        print()
        print("[dry-run] artefakt yazılmadı.")
        return 0
    print()
    print(f"artefakt yazıldı: {res['artifact_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
