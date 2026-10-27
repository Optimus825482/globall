#!/usr/bin/env python3
"""Supertrend cizgisine gore 3R. Secim testten once.

dokunus: fiyat cizgiye deger, kapanis cizginin dogru tarafinda kalir.
yakin: cizgiye 0.3 ATR'den yakin ama delmemis.
uzak: kapanis cizgiden 1 ATR'den uzakta.
Stop 1.2 ATR. Hedef 3R. Risk %5. ADX en az 20, DI ayni yon.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genis_arama_holdout as ga  # noqa: E402
import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = ga.SYMBOLS
TEST_FROM = "2026-08-31"


def orders_for(bars, kind: str) -> list:
    st, direction = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    plus, minus, adx = eng.adx_dmi(bars, 14)
    vol = wk.atr(bars, 14)
    out = [None] * len(bars)
    for i, bar in enumerate(bars):
        if st[i] is None or vol[i] is None or vol[i] <= 0 or adx[i] is None or adx[i] < 20:
            continue
        if plus[i] is None or minus[i] is None:
            continue
        if direction[i] == -1 and plus[i] > minus[i]:
            side = 1
            gap = bar.close - st[i]
            touched = bar.low <= st[i] and bar.close > st[i]
        elif direction[i] == 1 and minus[i] > plus[i]:
            side = -1
            gap = st[i] - bar.close
            touched = bar.high >= st[i] and bar.close < st[i]
        else:
            continue
        near = 0 <= gap <= 0.3 * vol[i] and not touched
        far = gap >= vol[i]
        if kind == "dokunus" and not touched:
            continue
        if kind == "yakin" and not near:
            continue
        if kind == "uzak" and not far:
            continue
        if side == 1:
            out[i] = (1, bar.close - 1.2 * vol[i])
        else:
            out[i] = (-1, bar.close + 1.2 * vol[i])
    return out


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = eng.fetch_bars("EURUSD", "15m", offset, lookback_days=160)
    cal = wk.weeks_ending(anchor[-1].t, 18)
    train = [row for row in cal if row[2] < TEST_FROM]
    test = [row for row in cal if row[2] >= TEST_FROM][-8:]
    report = {"train": [row[2] for row in train], "test": [row[2] for row in test], "symbols": {}, "passed_all_8": []}
    for tf in ("15m", "5m"):
        for symbol in SYMBOLS:
            resolved, bars = eng.fetch_bars(symbol, tf, offset, lookback_days=160)
            costs = eng.symbol_costs(resolved)
            best = None
            built = {}
            for kind in ("dokunus", "yakin", "uzak"):
                orders = orders_for(bars, kind)
                built[kind] = orders
                detail = ga.play(bars, orders, costs, train, 3.0)
                key = ga.rank_of(detail)
                if best is None or key > best[0]:
                    best = (key, kind)
            kind = best[1]
            test_detail = ga.play(bars, built[kind], costs, test, 3.0)
            te = ga.rank_of(test_detail)
            trades = sum(row["trades"] for row in test_detail)
            wins = sum(row["winners"] for row in test_detail)
            label = f"{symbol}|{tf}"
            report["symbols"][label] = {
                "resolved": resolved,
                "chosen": kind,
                "train_hits": best[0][0],
                "train_min": round(best[0][1], 2),
                "test_hits": te[0],
                "test_min": round(te[1], 2),
                "test_pnl": round(te[2], 2),
                "test_trades": trades,
                "test_winners": wins,
            }
            if te[0] == 8:
                report["passed_all_8"].append(label)
            rate = wins / trades if trades else 0
            print(
                f"{label:16} secim={kind:8} egitim {best[0][0]}/{len(train)} min={best[0][1]:.0f} | test {te[0]}/8 min={te[1]:.0f} pnl={te[2]:.0f} islem={trades} oran={rate:.2f}",
                flush=True,
            )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "st_cizgi_3r.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"file": path, "passed_all_8": report["passed_all_8"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
