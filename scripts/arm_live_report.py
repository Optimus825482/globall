#!/usr/bin/env python3
"""CANLI KOL İZLEME — CLI (çekirdek: `app/arm_live_monitor.py`)

2026-11-12'de iki canlı kolun (`london_breakout`, `ema_adx_pullback`) sembol listesi
ölçümle değiştirildi. Kod varsayılanı kayıtlı ayar dosyasını EZMEZ → panelden
girilmediyse eski liste yürür. Bu betik iki soruyu yanıtlar:
  1. Ayar işledi mi? (çıkarılan sembolde yeni işlem olmamalı)
  2. Kâr ediyor mu? (kol×sembol n/isabet/net/PF; kill kriteri n≥20 ve PF<1,0)

Aynı rapor **3 günde bir otomatik** de koşar (`app/routines`, sonuç Raporlar >
Rutinler'de görünür, önemliyse push gider).

Kullanim:
    python scripts/arm_live_report.py --days 7
    python scripts/arm_live_report.py --since 2026-11-12 --strategies london_breakout
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app import arm_live_monitor as m  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Canlı kol izleme (ayar etkisi + kârlılık)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--since", default="", help="YYYY-MM-DD (verilirse --days yok sayılır)")
    ap.add_argument("--strategies", default=",".join(m.DEFAULT_STRATEGIES))
    ap.add_argument("--out", default=os.path.join(ROOT, "outputs", "arm_live_report.json"))
    args = ap.parse_args()

    strat = [s.strip() for s in args.strategies.split(",") if s.strip()]
    report = m.build_report(days=args.days, since=args.since, strategies=strat)
    print("\n".join(m.format_cli(report)))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nYazıldı: {args.out}")
    print("NOT: n<20 satırlarda PF'e karar verilmez (kill kriteri: n≥20 ve PF<1,0). "
          "Defter boşsa 'OLCULEMEDI' yazar — sıfır, 'ayar işledi' kanıtı DEĞİLDİR.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
