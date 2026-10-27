#!/usr/bin/env python3
"""Gunluk %50 hedefi (1000 -> 1500 USD) taramasi. XAUUSD ve BTCUSD, MT5 verisi.

Kurallar kosudan once kilitlendi. Secim yapilmaz; her strateji x risk seviyesi
icin gun gun sonuc yazilir. 7 hafta (son 49 gun) ve 14 hafta (son 98 gun).

Veri: MetaTrader 5 (mt5_bridge ile ayni terminal), 5 dk giris, 15 dk filtre.
1 dk mum 14 haftayi kapsamiyor (terminal maxbars), bu yuzden 5 dk.

Her gun bagimsiz: 00:00 UTC'de 1000 USD. Hedef 1500 USD. Gun ici kasa
birikimli (kazanc risk tabanina eklenir). Hedefe ulasilinca o gun islem durur.
Kasa 300 USD altina duserse o gun durur (iflas). Gun sonunda acik pozisyon
kapatilir. XAUUSD giris 07:00-21:00 UTC, 21:00'de kapanis. BTCUSD tum gun,
23:55 barinda kapanis.

Stop 1.2 ATR(14, 5 dk). Hedef 2R. 1R lehte gorulunce stop girise. Giris bir
sonraki 5 dk acilisinda. Tek pozisyon. Spread anlik snapshot. Komisyon yok
(bilinmiyor, sifir yazilmadi). Risk seviyeleri: kasa %2, %5, %10, %20.

Stratejiler (GOSTERGELER.HTML icinden, TradingView formulleriyle):
  hast_stochrsi_adx : HA Supertrend(10,3) yonu + StochRSI(14,14,3,3) K/D bolge
                      kesisimi (<20 / >80) + ADX(14) >= 20
  ema_9_21_st       : EMA9/EMA21 kesisimi + Supertrend(10,3) yonu
  bb_sikisma_kirilim: Bollinger(20,2) bant genisligi 50 barin en dusugu
                      sonrasi kapanisin bant disina cikisi + DI yonu
  donchian_adx      : Donchian(20) kirilimi + ADX(14) >= 25 + DI yonu
  keltner_geri      : Keltner(EMA20, 2*ATR10) icinde EMA20'ye geri cekilme
                      sonrasi Supertrend yonunde devam mumu
  zl_wt_ust         : ZL-MACD (TV) 15 dk yonu + 5 dk WaveTrend 53 bolge kesisimi
  ichimoku_tk       : Tenkan(9)/Kijun(26) kesisimi, fiyat bulutun ayni tarafinda
  rsi2_ema200       : RSI(2) < 10 ve kapanis > EMA200 long; RSI(2) > 90 ve
                      kapanis < EMA200 short (Connors)
  chandelier_adx    : Chandelier Exit(22, 3 ATR) yon degisimi + ADX >= 20
  psar_adx          : Parabolic SAR(0.02, 0.2) yon degisimi + ADX >= 25
  TAVAN (strateji degil): her barda, 1.2 ATR stop yemeden 2R'ye ulasan yon
                      biliniyormus gibi alinir. Bu cikis modeliyle gunun ust siniri.
Emir gonderilmez.
"""
from __future__ import annotations

import bisect
import json
import math
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ha_supertrend_mt5_7d as eng  # noqa: E402
import stochrsi_hast_adx_60d as combo  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402
import zlmacd_wavetrend_mtf_xau_btc as base  # noqa: E402
import zlwt_tarama_xau_btc as zlwt  # noqa: E402

SYMBOLS = ("XAUUSD", "BTCUSD")
TF, TF_SEC = "5m", 300
FILTER_TF, FILTER_SEC = "15m", 900
LOOKBACK_DAYS = 110
WEEKS = (7, 14)
START_CASH = 1000.0
TARGET = 1500.0
RUIN = 300.0
RISKS = (0.02, 0.05, 0.10, 0.20)
STOP_ATR = 1.2
RR = 2.0
XAU_HOURS = (7, 21)
OUT_NAME = "gunluk_tavan_tarama_xau_btc.json"
STRATS = (
    "hast_stochrsi_adx", "ema_9_21_st", "bb_sikisma_kirilim", "donchian_adx", "keltner_geri",
    "zl_wt_ust", "ichimoku_tk", "rsi2_ema200", "chandelier_adx", "psar_adx",
)


# ------------------------------------------------------------------ gostergeler (TV)
def sma(values: list, period: int) -> list:
    out: list = [None] * len(values)
    for i in range(period - 1, len(values)):
        win = values[i - period + 1:i + 1]
        if any(v is None for v in win):
            continue
        out[i] = sum(win) / period
    return out


def stdev_pop(values: list, period: int) -> list:
    out: list = [None] * len(values)
    for i in range(period - 1, len(values)):
        win = values[i - period + 1:i + 1]
        m = sum(win) / period
        out[i] = math.sqrt(sum((v - m) ** 2 for v in win) / period)
    return out


def bollinger(closes: list[float], period: int = 20, mult: float = 2.0):
    """TV: basis SMA(20), ust/alt = basis +- 2*stdev (populasyon)."""
    basis = sma(closes, period)
    sd = stdev_pop(closes, period)
    upper = [None if b is None else b + mult * s for b, s in zip(basis, sd)]
    lower = [None if b is None else b - mult * s for b, s in zip(basis, sd)]
    bbw = [None if b is None or b == 0 else (u - l) / b for b, u, l in zip(basis, upper, lower)]
    return basis, upper, lower, bbw


def donchian(bars: list[eng.Bar], period: int = 20):
    hi: list = [None] * len(bars)
    lo: list = [None] * len(bars)
    for i in range(period - 1, len(bars)):
        hi[i] = max(b.high for b in bars[i - period + 1:i + 1])
        lo[i] = min(b.low for b in bars[i - period + 1:i + 1])
    return hi, lo


def keltner(bars: list[eng.Bar], length: int = 20, mult: float = 2.0, atr_len: int = 10):
    """TV Keltner: basis EMA(20), bantlar basis +- 2*ATR(10) (RMA)."""
    closes = [b.close for b in bars]
    basis = wk.ema(closes, length)
    a = wk.atr(bars, atr_len)
    upper = [None if x is None or y is None else x + mult * y for x, y in zip(basis, a)]
    lower = [None if x is None or y is None else x - mult * y for x, y in zip(basis, a)]
    return basis, upper, lower


def ichimoku(bars: list[eng.Bar], t: int = 9, k: int = 26, s: int = 52, disp: int = 26):
    """TV: tenkan=(HH9+LL9)/2, kijun=(HH26+LL26)/2, spanA=(t+k)/2, spanB=(HH52+LL52)/2, 26 bar ileri."""
    n = len(bars)

    def mid(p):
        out: list = [None] * n
        for i in range(p - 1, n):
            out[i] = (max(b.high for b in bars[i - p + 1:i + 1]) + min(b.low for b in bars[i - p + 1:i + 1])) / 2.0
        return out

    tenkan, kijun, raw_b = mid(t), mid(k), mid(s)
    raw_a = [None if a is None or b is None else (a + b) / 2.0 for a, b in zip(tenkan, kijun)]
    span_a: list = [None] * n
    span_b: list = [None] * n
    for i in range(n):
        if i - disp >= 0:
            span_a[i] = raw_a[i - disp]
            span_b[i] = raw_b[i - disp]
    return tenkan, kijun, span_a, span_b


def chandelier(bars: list[eng.Bar], length: int = 22, mult: float = 3.0):
    """TV Chandelier Exit: long = HH(22) - 3*ATR(22); short = LL(22) + 3*ATR(22). Yon: kapanis stop'u gecince."""
    n = len(bars)
    a = wk.atr(bars, length)
    long_stop: list = [None] * n
    short_stop: list = [None] * n
    direction = [0] * n
    for i in range(length - 1, n):
        if a[i] is None:
            continue
        hh = max(b.high for b in bars[i - length + 1:i + 1])
        ll = min(b.low for b in bars[i - length + 1:i + 1])
        ls = hh - mult * a[i]
        ss = ll + mult * a[i]
        if long_stop[i - 1] is not None and bars[i - 1].close > long_stop[i - 1]:
            ls = max(ls, long_stop[i - 1])
        if short_stop[i - 1] is not None and bars[i - 1].close < short_stop[i - 1]:
            ss = min(ss, short_stop[i - 1])
        long_stop[i], short_stop[i] = ls, ss
        prev = direction[i - 1]
        if short_stop[i - 1] is not None and bars[i].close > short_stop[i - 1]:
            direction[i] = 1
        elif long_stop[i - 1] is not None and bars[i].close < long_stop[i - 1]:
            direction[i] = -1
        else:
            direction[i] = prev if prev != 0 else 1
    return long_stop, short_stop, direction


def psar(bars: list[eng.Bar], start: float = 0.02, inc: float = 0.02, maximum: float = 0.2):
    """TV Parabolic SAR (ta.sar)."""
    n = len(bars)
    sar: list = [None] * n
    direction = [0] * n
    if n < 2:
        return sar, direction
    up = bars[1].close > bars[0].close
    ep = bars[0].high if up else bars[0].low
    val = bars[0].low if up else bars[0].high
    af = start
    for i in range(1, n):
        val = val + af * (ep - val)
        if up:
            val = min(val, bars[i - 1].low, bars[i - 2].low if i >= 2 else bars[i - 1].low)
            if bars[i].high > ep:
                ep, af = bars[i].high, min(af + inc, maximum)
            if bars[i].low < val:
                up, val, ep, af = False, ep, bars[i].low, start
        else:
            val = max(val, bars[i - 1].high, bars[i - 2].high if i >= 2 else bars[i - 1].high)
            if bars[i].low < ep:
                ep, af = bars[i].low, min(af + inc, maximum)
            if bars[i].high > val:
                up, val, ep, af = True, ep, bars[i].high, start
        sar[i] = val
        direction[i] = 1 if up else -1
    return sar, direction


def prepare(bars: list[eng.Bar], f15: list[eng.Bar]) -> dict:
    closes = [b.close for b in bars]
    p = {"bars": bars, "closes": closes, "atr": wk.atr(bars, 14)}
    p["st"], p["st_dir"] = eng.supertrend(eng.heikin_ashi(bars), 10, 3.0)
    p["k"], p["d"] = combo.stoch_rsi(closes)
    p["pdi"], p["mdi"], p["adx"] = eng.adx_dmi(bars, 14)
    p["ema9"], p["ema21"], p["ema200"] = wk.ema(closes, 9), wk.ema(closes, 21), wk.ema(closes, 200)
    p["bb_mid"], p["bb_up"], p["bb_lo"], p["bbw"] = bollinger(closes)
    p["dc_hi"], p["dc_lo"] = donchian(bars, 20)
    p["kc_mid"], p["kc_up"], p["kc_lo"] = keltner(bars)
    p["tenkan"], p["kijun"], p["span_a"], p["span_b"] = ichimoku(bars)
    p["rsi2"] = eng.rsi_wilder(closes, 2)
    p["ce_long"], p["ce_short"], p["ce_dir"] = chandelier(bars)
    p["sar"], p["sar_dir"] = psar(bars)
    p["wt1"], p["wt2"] = zlwt.wavetrend_tv(bars)
    zl15, sig15, _h = zlwt.zl_macd_tv([b.close for b in f15])
    m15 = base.align(bars, f15, TF_SEC, FILTER_SEC)
    p["zl15_side"] = [base.side_of(zl15, sig15, j) if j >= 0 else 0 for j in m15]
    return p


# ------------------------------------------------------------------ sinyaller
def side_at(strat: str, p: dict, i: int) -> int:
    b = p["bars"]
    if strat == "hast_stochrsi_adx":
        k, d = p["k"], p["d"]
        if None in (k[i], d[i], k[i - 1], d[i - 1], p["adx"][i]) or p["adx"][i] < 20:
            return 0
        if k[i - 1] <= d[i - 1] and k[i] > d[i] and k[i] < 20 and p["st_dir"][i] == -1:
            return 1
        if k[i - 1] >= d[i - 1] and k[i] < d[i] and k[i] > 80 and p["st_dir"][i] == 1:
            return -1
        return 0
    if strat == "ema_9_21_st":
        if base.cross_up(p["ema9"], p["ema21"], i) and p["st_dir"][i] == -1:
            return 1
        if base.cross_down(p["ema9"], p["ema21"], i) and p["st_dir"][i] == 1:
            return -1
        return 0
    if strat == "bb_sikisma_kirilim":
        if i < 60 or p["bbw"][i - 1] is None or p["pdi"][i] is None:
            return 0
        win = [v for v in p["bbw"][i - 50:i] if v is not None]
        if len(win) < 40 or p["bbw"][i - 1] > min(win) * 1.1:
            return 0
        if b[i].close > p["bb_up"][i] and p["pdi"][i] > p["mdi"][i]:
            return 1
        if b[i].close < p["bb_lo"][i] and p["mdi"][i] > p["pdi"][i]:
            return -1
        return 0
    if strat == "donchian_adx":
        if p["dc_hi"][i - 1] is None or p["adx"][i] is None or p["adx"][i] < 25:
            return 0
        if b[i].close > p["dc_hi"][i - 1] and p["pdi"][i] > p["mdi"][i]:
            return 1
        if b[i].close < p["dc_lo"][i - 1] and p["mdi"][i] > p["pdi"][i]:
            return -1
        return 0
    if strat == "keltner_geri":
        mid = p["kc_mid"]
        if mid[i] is None or mid[i - 1] is None:
            return 0
        touched_up = b[i - 1].low <= mid[i - 1] and b[i].close > mid[i] and b[i].close > b[i].open
        touched_dn = b[i - 1].high >= mid[i - 1] and b[i].close < mid[i] and b[i].close < b[i].open
        if touched_up and p["st_dir"][i] == -1 and b[i].close < p["kc_up"][i]:
            return 1
        if touched_dn and p["st_dir"][i] == 1 and b[i].close > p["kc_lo"][i]:
            return -1
        return 0
    if strat == "zl_wt_ust":
        z = zlwt.wt_zone_cross(p, i, 53.0)
        return z if z and p["zl15_side"][i] == z else 0
    if strat == "ichimoku_tk":
        sa, sb = p["span_a"][i], p["span_b"][i]
        if sa is None or sb is None:
            return 0
        top, bot = max(sa, sb), min(sa, sb)
        if base.cross_up(p["tenkan"], p["kijun"], i) and b[i].close > top:
            return 1
        if base.cross_down(p["tenkan"], p["kijun"], i) and b[i].close < bot:
            return -1
        return 0
    if strat == "rsi2_ema200":
        r, e = p["rsi2"][i], p["ema200"][i]
        if r is None or e is None:
            return 0
        if r < 10 and b[i].close > e:
            return 1
        if r > 90 and b[i].close < e:
            return -1
        return 0
    if strat == "chandelier_adx":
        if p["adx"][i] is None or p["adx"][i] < 20:
            return 0
        if p["ce_dir"][i] == 1 and p["ce_dir"][i - 1] == -1:
            return 1
        if p["ce_dir"][i] == -1 and p["ce_dir"][i - 1] == 1:
            return -1
        return 0
    if strat == "psar_adx":
        if p["adx"][i] is None or p["adx"][i] < 25:
            return 0
        if p["sar_dir"][i] == 1 and p["sar_dir"][i - 1] == -1:
            return 1
        if p["sar_dir"][i] == -1 and p["sar_dir"][i - 1] == 1:
            return -1
        return 0
    raise ValueError(strat)


def build_series(strat: str, p: dict) -> list:
    bars = p["bars"]
    out: list = [None] * len(bars)
    for i in range(1, len(bars)):
        s = side_at(strat, p, i)
        if s == 0 or p["atr"][i] is None or p["atr"][i] <= 0:
            continue
        out[i] = (s, bars[i].close - STOP_ATR * p["atr"][i] if s == 1 else bars[i].close + STOP_ATR * p["atr"][i])
    return out


def build_tavan(p: dict, spread: float, horizon: int = 96) -> list:
    """Ileriyi bilen sinyal: sonraki acilista girilince 2R stop'tan once doluyor mu (bar ici: stop once)."""
    bars = p["bars"]
    out: list = [None] * len(bars)
    for i in range(1, len(bars) - 2):
        a = p["atr"][i]
        if a is None or a <= 0:
            continue
        entry_raw = bars[i + 1].open
        for s in (1, -1):
            if s == 1:
                net = entry_raw + spread
                stop = bars[i].close - STOP_ATR * a
                risk = net - stop
                if risk <= spread:
                    continue
                tp = net + RR * risk
                ok = False
                for j in range(i + 1, min(len(bars), i + 1 + horizon)):
                    if bars[j].low <= stop:
                        break
                    if bars[j].high >= tp:
                        ok = True
                        break
            else:
                net = entry_raw
                stop = bars[i].close + STOP_ATR * a + spread
                risk = stop - net
                if risk <= spread:
                    continue
                tp = net - spread - RR * risk
                ok = False
                for j in range(i + 1, min(len(bars), i + 1 + horizon)):
                    if bars[j].high >= stop - spread:
                        break
                    if bars[j].low <= tp:
                        ok = True
                        break
            if ok:
                out[i] = (s, bars[i].close - STOP_ATR * a if s == 1 else bars[i].close + STOP_ATR * a)
                break
    return out


# ------------------------------------------------------------------ gunluk simulasyon
def open_pos(order, raw, spread, unit, vmin, vmax, vstep, cash, risk, i, t):
    side, stop_line = order
    if side == 1:
        net, stop = raw + spread, stop_line
        risk_px = net - stop
        tp = net + RR * risk_px
    else:
        net, stop = raw, stop_line + spread
        risk_px = stop - net
        tp = net - spread - RR * risk_px
    if risk_px <= spread or unit <= 0 or cash <= 0:
        return None
    vol = eng.floor_volume(cash * risk / (risk_px * unit), vmin, vmax, vstep)
    if vol is None:
        return None
    return {"side": side, "net": net, "stop": stop, "tp": tp, "risk_px": risk_px, "vol": vol, "i": i, "entry_t": t, "adx": None, "be": False}


def sim_day(bars, series, i0, i1, spread, unit, vmin, vmax, vstep, risk, hours, close_hour) -> dict:
    """[i0, i1) bar araligi tek gun. Gun basi 1000. Hedefte veya iflasta durur."""
    cash = START_CASH
    pos = pending = None
    trades = []
    hit_t = None
    stopped = None
    peak, dd = cash, 0.0
    for i in range(i0, i1):
        bar = bars[i]
        hour = datetime.fromtimestamp(bar.t, timezone.utc).hour
        last_bar = i == i1 - 1 or (close_hour is not None and hour >= close_hour)
        if pos is not None and last_bar:
            base._realize(trades, pos, bar.open, "gun_sonu", spread, unit, cash)
            cash += trades[-1]["pnl"]
            pos = None
            pending = None
            if close_hour is not None and hour >= close_hour:
                break
        hour_ok = hours is None or hours[0] <= hour < hours[1]
        if pending is not None and pos is None and hour_ok and stopped is None:
            pos = open_pos(pending, bar.open, spread, unit, vmin, vmax, vstep, cash, risk, i, bar.t)
        pending = None
        if pos is not None:
            closed = base._manage(bar, pos, spread)
            if closed is not None:
                raw_exit, reason = closed
                base._realize(trades, pos, raw_exit, reason, spread, unit, cash)
                cash += trades[-1]["pnl"]
                pos = None
        equity = cash
        if pos is not None:
            equity = cash + ((bar.close - pos["net"]) if pos["side"] == 1 else (pos["net"] - (bar.close + spread))) * pos["vol"] * unit
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
        if stopped is None and pos is None:
            if cash >= TARGET:
                stopped, hit_t = "hedef", bar.t
            elif cash <= RUIN:
                stopped = "iflas"
        if stopped is None and pos is None and series[i] is not None:
            pending = series[i]
    if pos is not None:
        base._realize(trades, pos, bars[i1 - 1].close, "gun_sonu", spread, unit, cash)
        cash += trades[-1]["pnl"]
    return {"end": round(cash, 2), "trades": len(trades), "winners": sum(1 for t in trades if t["pnl"] > 0),
            "hit": cash >= TARGET, "ruin": stopped == "iflas", "dd": round(dd, 2),
            "hit_utc": None if hit_t is None else datetime.fromtimestamp(hit_t, timezone.utc).strftime("%H:%M")}


def day_slices(bars: list[eng.Bar], start_ts: int, end_ts: int, weekdays_only: bool) -> list[tuple[str, int, int]]:
    times = [b.t for b in bars]
    out = []
    day = datetime.fromtimestamp(start_ts, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = datetime.fromtimestamp(end_ts, timezone.utc)
    while day < end_day:
        nxt = day + timedelta(days=1)
        if not (weekdays_only and day.weekday() >= 5):
            i0 = bisect.bisect_left(times, int(day.timestamp()))
            i1 = bisect.bisect_left(times, int(nxt.timestamp()))
            if i1 - i0 >= 60:
                out.append((day.strftime("%Y-%m-%d"), i0, i1))
        day = nxt
    return out


def summarize(rows: list[dict]) -> dict:
    ends = [r["end"] for r in rows]
    return {
        "days": len(rows),
        "hit_days": sum(1 for r in rows if r["hit"]),
        "hit_rate": None if not rows else round(sum(1 for r in rows if r["hit"]) / len(rows), 3),
        "positive_days": sum(1 for r in rows if r["end"] > START_CASH),
        "ruin_days": sum(1 for r in rows if r["ruin"]),
        "mean_end": None if not ends else round(statistics.mean(ends), 2),
        "median_end": None if not ends else round(statistics.median(ends), 2),
        "worst_end": None if not ends else min(ends),
        "best_end": None if not ends else max(ends),
        "sum_pnl": round(sum(e - START_CASH for e in ends), 2),
        "trades": sum(r["trades"] for r in rows),
        "winners": sum(r["winners"] for r in rows),
    }


def self_check() -> None:
    bars = []
    for i in range(400):
        c = 100 + 5 * math.sin(i / 20.0) + i * 0.02
        bars.append(eng.Bar(i * 300, c, c + 0.4, c - 0.4, c))
    sar, d = psar(bars)
    assert sar[-1] is not None and d[-1] in (1, -1)
    ls, ss, cd = chandelier(bars)
    assert ls[-1] is not None and ls[-1] < bars[-1].high
    t, k, sa, sb = ichimoku(bars)
    assert sa[-1] is not None and sb[-1] is not None and t[-1] is not None
    basis, up, lo, bbw = bollinger([b.close for b in bars])
    assert up[-1] > basis[-1] > lo[-1] and bbw[-1] > 0
    sl = day_slices(bars, 0, 400 * 300, False)
    assert len(sl) == 2 and sl[0][1] == 0 and sl[0][2] == 288, sl


def main() -> None:
    self_check()
    eng.attach_terminal()
    offset = eng.server_offset_s()
    retrieved = datetime.now(timezone.utc)
    today0 = retrieved.replace(hour=0, minute=0, second=0, microsecond=0)
    end_ts = int(today0.timestamp())
    windows = {f"{w}w": int((today0 - timedelta(days=7 * w)).timestamp()) for w in WEEKS}
    report = {
        "source": "MetaTrader 5 copy_rates (mt5_bridge terminali), bid mum", "retrieved_utc": retrieved.strftime("%Y-%m-%d %H:%M:%S"),
        "entry_tf": TF, "filter_tf": FILTER_TF, "start_cash": START_CASH, "target": TARGET, "ruin": RUIN,
        "risks": RISKS, "stop_atr": STOP_ATR, "rr": RR, "strategies": STRATS,
        "windows": {k: datetime.fromtimestamp(v, timezone.utc).strftime("%Y-%m-%d") + " .. " + today0.strftime("%Y-%m-%d") for k, v in windows.items()},
        "symbols": {},
    }
    for symbol in SYMBOLS:
        resolved, bars = eng.fetch_bars(symbol, TF, offset, lookback_days=LOOKBACK_DAYS)
        _r, f15 = eng.fetch_bars(symbol, FILTER_TF, offset, lookback_days=LOOKBACK_DAYS)
        costs = eng.symbol_costs(resolved)
        spread, unit = costs["spread_price"], costs["unit_per_lot_per_price"]
        vmin, vmax, vstep = costs["volume_min"], costs["volume_max"], costs["volume_step"]
        p = prepare(bars, f15)
        series = {s: build_series(s, p) for s in STRATS}
        series["TAVAN"] = build_tavan(p, spread)
        hours = XAU_HOURS if symbol == "XAUUSD" else None
        close_hour = 21 if symbol == "XAUUSD" else None
        weekdays = symbol == "XAUUSD"
        slices14 = day_slices(bars, windows["14w"], end_ts, weekdays)
        print(symbol, resolved, "bar", len(bars), "gun", len(slices14), "spread", spread, flush=True)
        sym_out = {"resolved": resolved, "spread_price": spread, "unit": unit, "volume_min": vmin,
                   "bars_5m": len(bars), "first_utc": datetime.fromtimestamp(bars[0].t, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                   "days_14w": len(slices14), "signal_counts": {s: sum(x is not None for x in series[s]) for s in series},
                   "results": {}}
        for s in list(STRATS) + ["TAVAN"]:
            for risk in RISKS:
                rows = []
                for label, i0, i1 in slices14:
                    r = sim_day(bars, series[s], i0, i1, spread, unit, vmin, vmax, vstep, risk, hours, close_hour)
                    r["day"] = label
                    rows.append(r)
                key = f"{s}|{risk}"
                sym_out["results"][key] = {
                    "14w": summarize(rows),
                    "7w": summarize([r for r in rows if r["day"] >= datetime.fromtimestamp(windows["7w"], timezone.utc).strftime("%Y-%m-%d")]),
                    "days": rows,
                }
                a, b = sym_out["results"][key]["14w"], sym_out["results"][key]["7w"]
                print(f"  {key:28s} 14h: hedef {a['hit_days']}/{a['days']} ort {a['mean_end']} iflas {a['ruin_days']} | 7h: hedef {b['hit_days']}/{b['days']} ort {b['mean_end']}", flush=True)
        report["symbols"][symbol] = sym_out
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUT_NAME)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("yazildi", path)


if __name__ == "__main__":
    main()
