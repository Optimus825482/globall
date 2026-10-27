#!/usr/bin/env python3
"""8 haftada 1000->2000 tavanı. Stop'lu kusursuz seçici.

Bu bir strateji değildir. Her barda her iki yönü dener, stop'tan önce
hedefe ulaşanları sayar. Gerçek bir kural bunu seçemez. Amaç: o haftanın
fiyatı, sabit risk ve 1.2 ATR stop ile çiftlemeye yetecek hareketi
barındırıyor mu.

Aynı mumda stop, hedeften önce sayılır. Spread yok: tavan bilinçli olarak
cömert. Cömert tavan 2000'e yetmiyorsa hiçbir stop'lu kural yetmez.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = (
    "XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY",
    "USDCAD", "EURCAD", "GBPCAD", "EURNZD", "GBPNZD", "NZDUSD",
)
ATR_MULT = 1.2
RR_LIST = (2.0, 3.0)


def clean_trades(bars, vol, start: int, end: int, rr: float) -> tuple[int, float]:
    """Üst üste binmeyen, stop yemeden rr hedefine varan işlem sayısı ve en iyi tek R."""
    n = len(bars)
    count = 0
    best_r = 0.0
    i = 0
    while i < n - 1:
        if bars[i].t < start or bars[i + 1].t > end:
            i += 1
            continue
        atr = vol[i]
        if atr is None or atr <= 0:
            i += 1
            continue
        risk_px = ATR_MULT * atr
        entry_i = i + 1
        entry = bars[entry_i].open
        hit_j = None
        for side in (1, -1):
            mfe = 0.0
            for j in range(entry_i, n):
                if bars[j].t > end:
                    break
                if side == 1:
                    if bars[j].low <= entry - risk_px:
                        break
                    favor = bars[j].high - entry
                else:
                    if bars[j].high >= entry + risk_px:
                        break
                    favor = entry - bars[j].low
                if favor > mfe:
                    mfe = favor
                if favor >= rr * risk_px:
                    hit_j = j
                    break
            r_here = mfe / risk_px
            if r_here > best_r:
                best_r = r_here
            if hit_j is not None:
                break
        if hit_j is None:
            i += 1
            continue
        count += 1
        i = hit_j + 1
    return count, best_r


def friday(count: int, risk: float, rr: float) -> float:
    cash = wk.START_CASH
    gain = 1.0 + risk * rr
    for _ in range(count):
        cash *= gain
    return cash


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=140)
    cal = wk.weeks_ending(anchor[-1].t, wk.WEEKS)
    rows = []
    for symbol in SYMBOLS:
        try:
            _resolved, bars = eng.fetch_bars(symbol, "15m", offset, lookback_days=140)
        except SystemExit as exc:
            rows.append({"symbol": symbol, "error": str(exc)})
            continue
        vol = wk.atr(bars, 14)
        for start, end, label in cal:
            cell = {"symbol": symbol, "week": label}
            for rr in RR_LIST:
                count, best = clean_trades(bars, vol, start, end, rr)
                cell[f"n{int(rr)}"] = count
                cell[f"best{int(rr)}"] = round(best, 2)
                cell[f"fri5_{int(rr)}"] = round(friday(count, 0.05, rr), 2)
                cell[f"fri2_{int(rr)}"] = round(friday(count, 0.02, rr), 2)
            rows.append(cell)
            print(
                f"{symbol:8} {label}  2R={cell['n2']:3} fri5={cell['fri5_2']:8.0f}  "
                f"3R={cell['n3']:3} fri5={cell['fri5_3']:8.0f}  best={cell['best2']:.1f}R",
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hafta_tavan_8w.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"note": "kusursuz secici tavan, strateji degil", "rows": rows, "weeks": [w[2] for w in cal]}, fh, ensure_ascii=False, indent=2)
    short = []
    for row in rows:
        if "error" in row:
            continue
        if row["fri5_2"] < wk.TARGET and row["fri5_3"] < wk.TARGET:
            short.append(row)
    print(json.dumps({"file": path, "weeks_short_of_2000_at_5pct": len(short), "short": short}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
