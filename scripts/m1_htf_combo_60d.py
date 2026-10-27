#!/usr/bin/env python3
"""XAUUSD ve BTCUSD, 1 dakika, 60 gun.

Secim: MT5 uzerinde kagit test. 15dk Heikin Ashi Supertrend yonu ile 1dk girisi
birlestirir. Hedef, her sembolde hafta ici gunde en az 15 kazanc ve net arti.
Kurallar sonuc gorulmeden kilitlendi. Emir yok.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_m1_gunluk_60d as scalp  # noqa: E402

WINDOW_SEC = 60 * 86400
GOLD_SESSION = (7, 20)


def resample_15m(bars: list[eng.Bar]) -> list[eng.Bar]:
    out: list[eng.Bar] = []
    key = None
    cur: eng.Bar | None = None
    for bar in bars:
        bucket = bar.t // 900 * 900
        if bucket != key:
            if cur is not None:
                out.append(cur)
            key = bucket
            cur = eng.Bar(bucket, bar.open, bar.high, bar.low, bar.close)
        else:
            assert cur is not None
            cur = eng.Bar(bucket, cur.open, max(cur.high, bar.high), min(cur.low, bar.low), bar.close)
    if cur is not None:
        out.append(cur)
    return out


def allow(ts: int, symbol: str) -> bool:
    if symbol == "BTCUSD":
        return True
    return eng.hour_in_span(ts, GOLD_SESSION)


def mask(signals: list[int], bias: list[int]) -> list[int]:
    return [side if side and bias[i] == side else 0 for i, side in enumerate(signals)]


def main() -> None:
    eng.self_check()
    eng.attach_terminal()
    offset = eng.server_offset_s()
    report: dict = {"target": "her sembolde hafta ici >=15 kazanc ve net arti", "symbols": {}}
    for symbol in ("XAUUSD", "BTCUSD"):
        resolved, bars = scalp.fetch_m1(symbol, offset)
        costs = eng.symbol_costs(resolved)
        last_ts = bars[-1].t
        window_start = last_ts - WINDOW_SEC
        spread = costs["spread_price"]
        vol = scalp.atr(bars, 14)
        bias = eng.htf_side(bars, resample_15m(bars), 900)
        closes = [bar.close for bar in bars]
        trend = scalp.ema(closes, 21)
        rsi = eng.rsi_wilder(closes, 7)
        ha = eng.heikin_ashi(bars)
        _mid, upper, lower = scalp.bollinger(closes, 20, 2.0)

        pull = [0] * len(bars)
        burst = [0] * len(bars)
        revert = [0] * len(bars)
        for i in range(1, len(bars)):
            if not allow(bars[i].t, symbol) or vol[i] is None or trend[i] is None:
                continue
            if vol[i] * 1.6 < spread * 6:
                continue
            if bias[i] == 1 and bars[i - 1].close > trend[i] and bars[i].low <= trend[i] and bars[i].close > trend[i] and ha[i].close > ha[i].open:
                pull[i] = 1
            elif bias[i] == -1 and bars[i - 1].close < trend[i] and bars[i].high >= trend[i] and bars[i].close < trend[i] and ha[i].close < ha[i].open:
                pull[i] = -1
            if rsi[i] is None:
                continue
            if bias[i] == 1 and ha[i].close > ha[i].open and closes[i] > trend[i] and 55 < rsi[i] < 80:
                burst[i] = 1
            elif bias[i] == -1 and ha[i].close < ha[i].open and closes[i] < trend[i] and 20 < rsi[i] < 45:
                burst[i] = -1
            if lower[i] is None or upper[i] is None:
                continue
            if bias[i] == 1 and bars[i].low < lower[i] and bars[i].close > lower[i] and bars[i].close > bars[i].open:
                revert[i] = 1
            elif bias[i] == -1 and bars[i].high > upper[i] and bars[i].close < upper[i] and bars[i].close < bars[i].open:
                revert[i] = -1

        specs = {
            "15dk_geri_cekilme": (pull, 1.0, 1.6, 20, 5),
            "15dk_momentum": (burst, 1.0, 1.6, 15, 8),
            "15dk_bant": (revert, 0.8, 1.2, 12, 3),
        }
        cells = {}
        for name, (signals, sl, tp, hold, cool) in specs.items():
            cells[name] = scalp.run_scalp(
                bars, signals, spread=spread, unit=costs["unit_per_lot_per_price"],
                vmin=costs["volume_min"], vmax=costs["volume_max"], vstep=costs["volume_step"],
                window_start=window_start, sl_mult=sl, tp_mult=tp, time_stop=hold, cooldown=cool, vol=vol,
            )
        report["symbols"][symbol] = {
            "resolved": resolved,
            "spread": spread,
            "spread_source": costs["spread_source"],
            "window_start_utc": datetime.fromtimestamp(window_start, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "last_utc": datetime.fromtimestamp(last_ts, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "calendar_days": round((last_ts - max(window_start, bars[0].t)) / 86400, 1),
            "strategies": cells,
        }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "m1_htf_combo_60d.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
