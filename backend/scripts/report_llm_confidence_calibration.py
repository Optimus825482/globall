"""LLM GÜVEN KALİBRASYONU — CLI (2026-11-09)

Mantık `app/llm_calibration.py` içindedir; Ayarlar panelindeki
"Kalibrasyonu Çalıştır" düğmesi de AYNI modülü kullanır (tek uygulama).

    python -m scripts.report_llm_confidence_calibration
    ... --days 60 --min-samples 150 --save artifacts/llm_confidence_calibration.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import llm_calibration as lc  # noqa: E402


def _print(report: dict) -> None:
    print("=" * 84)
    print(f"LLM GÜVEN KALİBRASYONU · {report['reviews']} çözülmüş karar · eşleşen {report['samples']}")
    print("=" * 84)
    if not report.get("fitted"):
        print("
EĞRİ KURULMADI:", report.get("reason"))
        return
    print(f"taban isabet={report['base_rate']:.3f} · ort. R kazanç={report['avg_win_r']:+.2f} "
          f"kayıp={report['avg_loss_r']:+.2f} · BREAK-EVEN={report['break_even']:.3f}")
    raw, cald = report["metrics_raw"], report["metrics_calibrated"]
    print(f"
{'metrik':<12}{'ham':>10}{'kalibre':>10}   (küçük iyi)")
    print("-" * 84)
    for key, label in (("brier", "Brier"), ("log_loss", "log-loss"), ("ece", "ECE")):
        r, c = raw.get(key), cald.get(key)
        d = "" if (r is None or c is None) else ("  ✓ iyileşti" if c < r else "  ✗ kötüleşti")
        print(f"{label:<12}{(r if r is not None else -1):>10.4f}{(c if c is not None else -1):>10.4f}{d}")
    print(f"{'Brier skill':<12}{report['brier_skill_raw']:>10.3f}"
          f"{report['brier_skill_calibrated']:>10.3f}   (>0 = taban orandan iyi)")
    print("
Güvenilirlik kovaları (kalibre sonrası; gap<0 = hâlâ aşırı güvenli):")
    print(f"  {'kova':<12}{'n':>6}{'güven':>9}{'gerçek':>9}{'gap':>9}")
    for b in report["bins"]:
        print(f"  {b['lo']:.1f}-{b['hi']:.1f}   {b['samples']:>6}{b['confidence']:>9.3f}"
              f"{b['accuracy']:>9.3f}{b['gap']:>+9.3f}")
    t = report["threshold"]
    print("
EŞİK ÖNERİSİ")
    print(f"  önerilen llm_review_min_confidence = {t['suggested_min_confidence']}")
    print(f"  gerekçe: {t['reason']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="LLM güven kalibrasyonu ve eşik önerisi")
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--min-samples", type=int, default=None)
    ap.add_argument("--save", nargs="?", const=str(lc.DEFAULT_ARTIFACT), default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    report = asyncio.run(lc.run(args.days, min_samples=args.min_samples, save=args.save))
    _print(report)
    if report.get("artifact_path"):
        print(f"
artefakt yazıldı: {report['artifact_path']}")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
