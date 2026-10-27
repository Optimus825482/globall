#!/usr/bin/env python3
"""Kilitli 3dk MACD + HA Supertrend ustune iki ek kapı.

Kapilar bu kosudan once sabitlendi. Sembol basina MACD, stop veya risk
aranmadi. Ayni 8 hafta, her Pazartesi 1000 USD, risk %5.

1) Rejim: sinyal mumunda ADX(14) < 20 ise giris yok. Esik her sembolde ayni,
   deger o sembolun kendi mumlarindan gelir.
2) Takvim: pariteyi olusturan para biriminin yuksek etkili aciklamasi.
   Aciklamadan 15 dk once ve 15 dk sonra yeni islem yok.
   Sonraki 15 dk kapanisi para biriminin isareti olur. Bu isaret 120 dk
   boyunca ters yondeki girisi keser. BoJ'un dakikasi sabit degil; sadece
   karanlik pencere, yon yok.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import macd_hast_3m_multi as multi  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

SYMBOLS = ("EURUSD", "USDJPY", "EURJPY", "GBPJPY", "USDCAD")
PAIRS = {
    "EURUSD": ("EUR", "USD"),
    "USDJPY": ("USD", "JPY"),
    "EURJPY": ("EUR", "JPY"),
    "GBPJPY": ("GBP", "JPY"),
    "USDCAD": ("USD", "CAD"),
}
PROXIES = {
    "USD": ("EURUSD", True),
    "EUR": ("EURUSD", False),
    "GBP": ("GBPUSD", False),
    "JPY": ("USDJPY", True),
    "CAD": ("USDCAD", True),
}
ADX_MIN = 20.0
BLACKOUT_S = 15 * 60
REACTION_S = 15 * 60
BIAS_S = 120 * 60
BAR_S = 180


def utc(y: int, m: int, d: int, hh: int, mm: int) -> int:
    return int(datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp())


# Saatler UTC. ABD yaz saati (UTC-4) BLS 08:30 ET = 12:30 UTC.
# ECB saati o gunun sayfasinda yok; bankanin duzenli slotu 14:15 / 14:45 CEST.
# BoJ duyurusu 03:30 BST sonrasi herhangi bir dakika; yon uretilmez.
EVENTS = [
    {"ccy": "CAD", "t": utc(2026, 9, 2, 13, 45), "name": "BoC"},
    {"ccy": "USD", "t": utc(2026, 9, 4, 12, 30), "name": "ABD istihdam"},
    {"ccy": "EUR", "t": utc(2026, 9, 10, 12, 15), "name": "ECB karar"},
    {"ccy": "EUR", "t": utc(2026, 9, 10, 12, 45), "name": "ECB basin"},
    {"ccy": "USD", "t": utc(2026, 9, 11, 12, 30), "name": "ABD TUFE"},
    {"ccy": "USD", "t": utc(2026, 9, 16, 18, 0), "name": "FOMC"},
    {"ccy": "USD", "t": utc(2026, 9, 16, 18, 30), "name": "FOMC basin"},
    {"ccy": "GBP", "t": utc(2026, 9, 17, 11, 0), "name": "BoE"},
    {"ccy": "JPY", "start": utc(2026, 9, 18, 2, 15), "end": utc(2026, 9, 18, 6, 45), "name": "BoJ"},
    {"ccy": "USD", "t": utc(2026, 10, 2, 12, 30), "name": "ABD istihdam"},
    {"ccy": "USD", "t": utc(2026, 10, 14, 12, 30), "name": "ABD TUFE"},
]


def reaction(bars: list[eng.Bar], t_event: int, invert: bool) -> tuple[int | None, int | None]:
    pre = None
    for bar in bars:
        if bar.t + BAR_S <= t_event:
            pre = bar.close
        elif bar.t + BAR_S >= t_event + REACTION_S:
            if pre is None or bar.close == pre:
                return None, bar.t + BAR_S
            sign = 1 if bar.close > pre else -1
            if invert:
                sign = -sign
            return sign, bar.t + BAR_S
    return None, None


def build_events(books: dict[str, list[eng.Bar]]) -> list[dict]:
    ready = []
    for event in EVENTS:
        if "start" in event:
            ready.append({
                "ccy": event["ccy"],
                "name": event["name"],
                "blackout": (event["start"], event["end"]),
                "sign": None,
                "known": None,
                "until": None,
            })
            continue
        symbol, invert = PROXIES[event["ccy"]]
        sign, known = reaction(books[symbol], event["t"], invert)
        ready.append({
            "ccy": event["ccy"],
            "name": event["name"],
            "blackout": (event["t"] - BLACKOUT_S, event["t"] + BLACKOUT_S),
            "sign": sign,
            "known": known,
            "until": None if known is None else known + BIAS_S,
        })
    return ready


def news_ok(symbol: str, side: int, entry_t: int, events: list[dict]) -> bool:
    base, quote = PAIRS[symbol]
    for event in events:
        if event["ccy"] not in (base, quote):
            continue
        left, right = event["blackout"]
        if left <= entry_t <= right:
            return False
        if event["sign"] is None or event["known"] is None:
            continue
        if event["known"] <= entry_t <= event["until"]:
            if event["ccy"] == base and side != event["sign"]:
                return False
            if event["ccy"] == quote and side != -event["sign"]:
                return False
    return True


def mask(bars, signals, adx, mode: str, symbol: str, events: list[dict]) -> list:
    out = list(signals)
    for i, sig in enumerate(signals):
        if sig is None or i + 1 >= len(bars):
            continue
        side = sig[0]
        if mode in ("adx", "tam"):
            if adx[i] is None or adx[i] < ADX_MIN:
                out[i] = None
                continue
        if mode == "tam" and not news_ok(symbol, side, bars[i + 1].t, events):
            out[i] = None
    return out


def run_symbol(symbol, bars, costs, series, adx, events, cal, mode: str) -> list[dict]:
    gated = series if mode == "baz" else mask(bars, series, adx, mode, symbol, events)
    detail = []
    for start, end, label in cal:
        row = wk.simulate(
            bars, gated, costs["spread_price"], costs["unit_per_lot_per_price"],
            costs["volume_min"], costs["volume_max"], costs["volume_step"],
            start, end, multi.RISK,
        )
        detail.append({"week": label, **row})
    return detail


def pack(detail: list[dict]) -> dict:
    fridays = [row["friday"] for row in detail]
    return {
        "hits": sum(1 for row in detail if row["hit"]),
        "min_friday": min(fridays),
        "max_friday": max(fridays),
        "sum_pnl": round(sum(value - wk.START_CASH for value in fridays), 2),
        "detail": detail,
    }


def main() -> None:
    eng.attach_terminal()
    offset = eng.server_offset_s()
    _name, anchor = multi.load_m3("EURUSD", offset)
    cal = wk.weeks_ending(anchor[-1].t, wk.WEEKS)
    needed = set(SYMBOLS) | {name for name, _inv in PROXIES.values()}
    books: dict[str, list] = {}
    costs_of = {}
    resolved_of = {}
    for symbol in sorted(needed):
        resolved, bars = multi.load_m3(symbol, offset)
        books[symbol] = bars
        resolved_of[symbol] = resolved
        costs_of[symbol] = eng.symbol_costs(resolved)
    events = build_events(books)
    modes = ("baz", "adx", "tam")
    symbols = {}
    for symbol in SYMBOLS:
        bars = books[symbol]
        series = wk.signals_macd_st(bars)
        _p, _m, adx = eng.adx_dmi(bars, 14)
        symbols[symbol] = {
            "resolved": resolved_of[symbol],
            "spread": costs_of[symbol]["spread_price"],
            "modes": {
                mode: pack(run_symbol(symbol, bars, costs_of[symbol], series, adx, events, cal, mode))
                for mode in modes
            },
        }
    combined = {mode: [] for mode in modes}
    for _s, _e, label in cal:
        for mode in modes:
            book = []
            for body in symbols.values():
                row = next(item for item in body["modes"][mode]["detail"] if item["week"] == label)
                book.append(row["friday"])
            combined[mode].append({
                "week": label,
                "sum_friday": round(sum(book), 2),
                "sum_pnl": round(sum(book) - wk.START_CASH * len(SYMBOLS), 2),
                "books_at_target": sum(1 for value in book if value >= wk.TARGET),
            })
    report = {
        "rule": "3m MACD + HA Supertrend, risk %5. Ek: ADX>=20 ve takvim.",
        "locked": {
            "adx_min": ADX_MIN,
            "blackout_min": 15,
            "reaction_min": 15,
            "bias_min": 120,
            "risk": multi.RISK,
        },
        "events": [
            {
                "name": event["name"],
                "ccy": event["ccy"],
                "sign": event["sign"],
                "blackout_utc": [
                    datetime.fromtimestamp(event["blackout"][0], timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    datetime.fromtimestamp(event["blackout"][1], timezone.utc).strftime("%Y-%m-%d %H:%M"),
                ],
            }
            for event in events
        ],
        "symbols": symbols,
        "combined": combined,
        "eight_week_pnl": {mode: round(sum(row["sum_pnl"] for row in rows), 2) for mode, rows in combined.items()},
        "positive_weeks": {mode: sum(1 for row in rows if row["sum_pnl"] > 0) for mode, rows in combined.items()},
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macd_hast_3m_adaptif.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        "file": path,
        "eight_week_pnl": report["eight_week_pnl"],
        "positive_weeks": report["positive_weeks"],
        "combined": combined,
        "symbols": {
            symbol: {mode: {"hits": body["modes"][mode]["hits"], "min": body["modes"][mode]["min_friday"], "pnl": body["modes"][mode]["sum_pnl"]} for mode in modes}
            for symbol, body in symbols.items()
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
