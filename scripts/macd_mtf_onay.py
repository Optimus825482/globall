#!/usr/bin/env python3
"""Coklu zaman onayi. Kesim alt dilimde, renk ust dilimde.

Yesil: histogram sifirin ustu. Kirmizi: sifirin alti.
Al: alt dilimde histogram sifiri yukari keser ve ust dilimler yesil.
Sat: alt dilimde histogram sifiri asagi keser ve ust dilimler kirmizi.
Ust mum, alt mum kapanmadan kapanmis olmali.
MACD 12, 26, 9. Giris sonraki acilis. Stop 1.2 ATR. Ters sinyalde cikis.
Kagit 10000 USD, risk %1. Spread anlik.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macd_sifir_kesim as tek  # noqa: E402

COMBOS = (
    ("1-3", "1m", ("3m",)),
    ("3-5", "3m", ("5m",)),
    ("5-15", "5m", ("15m",)),
    ("3-5-15", "3m", ("5m", "15m")),
)
TF_SEC = {"1m": 60, "3m": 180, "5m": 300, "15m": 900}


def color_of(bars) -> list[int]:
    closes = [bar.close for bar in bars]
    macd, sig = tek.macd_hist(closes)
    out = [0] * len(bars)
    for i in range(len(bars)):
        if macd[i] is None or sig[i] is None:
            continue
        hist = macd[i] - sig[i]
        if hist > 0:
            out[i] = 1
        elif hist < 0:
            out[i] = -1
    return out


def zero_cross(bars) -> list[int]:
    closes = [bar.close for bar in bars]
    macd, sig = tek.macd_hist(closes)
    out = [0] * len(bars)
    for i in range(1, len(bars)):
        if None in (macd[i], macd[i - 1], sig[i], sig[i - 1]):
            continue
        prev = macd[i - 1] - sig[i - 1]
        cur = macd[i] - sig[i]
        if prev <= 0 < cur:
            out[i] = 1
        elif prev >= 0 > cur:
            out[i] = -1
    return out


def align(trigger, higher, higher_sec: int, trigger_sec: int) -> list[int]:
    """Her alt mumda, o mum kapanmadan kapanmis son ust rengi."""
    color = color_of(higher)
    out = [0] * len(trigger)
    j = 0
    last = 0
    for i, bar in enumerate(trigger):
        close_t = bar.t + trigger_sec
        while j < len(higher) and higher[j].t + higher_sec <= close_t:
            last = color[j]
            j += 1
        out[i] = last
    return out


def confirmed(trigger_bars, raw: list[int], frames: dict, uppers: tuple[str, ...], trigger_tf: str) -> list[int]:
    masks = [align(trigger_bars, frames[name], TF_SEC[name], TF_SEC[trigger_tf]) for name in uppers]
    out = [0] * len(raw)
    for i, side in enumerate(raw):
        if side == 0:
            continue
        if all(mask[i] == side for mask in masks):
            out[i] = side
    return out


def main() -> None:
    tek.eng.attach_terminal()
    offset = tek.eng.server_offset_s()
    _name, anchor = tek.eng.fetch_bars("EURUSD", "15m", offset, lookback_days=80)
    last = anchor[-1].t
    report = {
        "rule": "Alt dilimde histogram sifir kesimi. Ust dilim ayni renkse islem.",
        "combos": [name for name, _t, _u in COMBOS],
        "symbols": {},
    }
    for symbol in tek.SYMBOLS:
        try:
            resolved, frames = tek.load_frames(symbol, offset)
            costs = tek.eng.symbol_costs(resolved)
        except SystemExit as exc:
            print(symbol, exc, flush=True)
            continue
        report["symbols"][symbol] = {"resolved": resolved, "spread": costs["spread_price"], "combos": {}}
        prepared = {}
        for tf, bars in frames.items():
            prepared[tf] = (bars, zero_cross(bars), tek.wk.atr(bars, 14))
        for name, trigger_tf, uppers in COMBOS:
            bars, raw, vol = prepared[trigger_tf]
            sides = confirmed(bars, raw, frames, uppers, trigger_tf)
            cells = {}
            for days in tek.WINDOWS:
                start = last - days * 86400
                if bars[0].t > start:
                    cells[str(days)] = {"note": "veri_kisiti"}
                    continue
                cells[str(days)] = tek.simulate(
                    bars, sides, vol, costs["spread_price"], costs["unit_per_lot_per_price"],
                    costs["volume_min"], costs["volume_max"], costs["volume_step"], start, last,
                )
            report["symbols"][symbol]["combos"][name] = cells
            row = cells.get("7", {})
            print(
                f"{symbol:8} {name:8} 7g islem={row.get('trades')} net={row.get('net')} pf={row.get('pf')} oran={row.get('win_rate')}",
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macd_mtf_onay.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
