#!/usr/bin/env python3
"""5-15-30 MACD ustune ADX ve ADR.

Esikler kosudan once kilitli.
ADX 25: 5 dk ADX(14) en az 25.
ADX 25 + DI: yon, DI ile ayni.
ADR 80: gunun o ana kadarki araligi, son 14 tam gunun
ortalama araliginin %80'ine vardiysa islem yok.
Kagit 10000 USD, risk %1. Stop 1.2 ATR.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import macd_mtf_5_15_30 as baz  # noqa: E402
import macd_mtf_onay as mtf  # noqa: E402
import macd_sifir_kesim as tek  # noqa: E402

FILTERS = ("adx25", "adx25_di", "adr80", "adx25_adr80")


def day_of(ts: int):
    return datetime.fromtimestamp(ts, timezone.utc).date()


def adr_block(bars) -> list[bool]:
    """True ise gun tukenmis, islem acilmaz."""
    n = len(bars)
    block = [True] * n
    day_high = None
    day_low = None
    current = None
    done: list[float] = []
    for i, bar in enumerate(bars):
        day = day_of(bar.t)
        if day != current:
            if day_high is not None:
                done.append(day_high - day_low)
            current = day
            day_high = bar.high
            day_low = bar.low
        else:
            day_high = max(day_high, bar.high)
            day_low = min(day_low, bar.low)
        if len(done) >= 14:
            adr = sum(done[-14:]) / 14.0
            if adr > 0 and (day_high - day_low) < 0.8 * adr:
                block[i] = False
        else:
            block[i] = False
    return block


def apply_filter(bars, sides, name: str) -> list[int]:
    plus, minus, adx = eng.adx_dmi(bars, 14)
    tired = adr_block(bars) if "adr" in name else [False] * len(bars)
    out = [0] * len(sides)
    for i, side in enumerate(sides):
        if side == 0 or tired[i]:
            continue
        if name.startswith("adx25"):
            if adx[i] is None or adx[i] < 25:
                continue
            if name == "adx25_di":
                if plus[i] is None or minus[i] is None:
                    continue
                if side == 1 and plus[i] <= minus[i]:
                    continue
                if side == -1 and minus[i] <= plus[i]:
                    continue
        out[i] = side
    return out


def base_sides(bars5) -> list[int]:
    bars15 = tek.wk.resample(bars5, 900)
    bars30 = tek.wk.resample(bars5, 1800)
    raw = mtf.zero_cross(bars5)
    masks = (
        mtf.align(bars5, bars15, 900, 300),
        mtf.align(bars5, bars30, 1800, 300),
    )
    return baz.confirm(raw, list(masks))


def main() -> None:
    tek.eng.attach_terminal()
    offset = tek.eng.server_offset_s()
    _name, anchor = tek.eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    last = anchor[-1].t
    report = {"rule": "5-15-30 arti ADX 25 / DI / ADR %80", "symbols": {}}
    for symbol in tek.SYMBOLS:
        try:
            resolved, bars5 = tek.eng.fetch_bars(symbol, "5m", offset, lookback_days=90)
        except SystemExit as exc:
            print(symbol, exc, flush=True)
            continue
        costs = tek.eng.symbol_costs(resolved)
        sides = base_sides(bars5)
        vol = tek.wk.atr(bars5, 14)
        report["symbols"][symbol] = {"spread": costs["spread_price"], "filters": {}}
        for name in FILTERS:
            gated = apply_filter(bars5, sides, name)
            cells = {}
            for days in tek.WINDOWS:
                start = last - days * 86400
                if bars5[0].t > start:
                    cells[str(days)] = {"note": "veri_kisiti"}
                    continue
                cells[str(days)] = tek.simulate(
                    bars5, gated, vol, costs["spread_price"], costs["unit_per_lot_per_price"],
                    costs["volume_min"], costs["volume_max"], costs["volume_step"], start, last,
                )
            report["symbols"][symbol]["filters"][name] = cells
            row = cells.get("60", {})
            print(
                f"{symbol:8} {name:12} 60g islem={row.get('trades')} net={row.get('net')} pf={row.get('pf')} dd={row.get('dd')} oran={row.get('win_rate')}",
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macd_mtf_5_15_30_filtre.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
