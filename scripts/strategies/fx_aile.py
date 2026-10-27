"""FX spread-duyarli giris-strateji ailesi (replay_strateji_gunluk eklentisi).

Dort birbirinden farkli mantik; parametreler SABIT (grid yok, varyant yok).
Kapsam: EURUSD, GBPUSD, USDJPY, USDCAD, USDCHF, GBPJPY, EURJPY, NZDUSD; M15 ve M30.
`spread_min_mult = 8.0`: sarmalayici, SL pip < 8 x spread pip olan adayi reddeder
(bu dosyada kapi uygulanmaz, yalniz alan tanimlanir).

  fx_londra_aralik    07:00-08:00 UTC araligi; 08:00-12:00 UTC arasinda kapanis aralik disina
                      cikinca yonunde giris, gunde yon basina 1. Aralik yuksekligi >= 0.8*ATR14
                      (ATR, aralik bitisindeki son bar; yani 08:00 oncesi bilinen deger) sarti.
                      SL = aralik/2 (en az 1.0*ATR14), TP 2R.
  fx_ema200_rsi_geri  EMA200 tarafi + ADX(14)>=20; RSI(14) 50'nin altindan (BUY) 50 ve uzerine
                      kapanisla doner (rsi[i-1]<50<=rsi[i]) ve kapanis EMA21 ustunde; SELL ters.
                      07-20 UTC. SL 2.5*ATR, TP 1.5R.
  fx_bb_donus_m30     BB(20, 2.5): onceki bar bandin DISINDA kapanmis, bu bar bant ICINE kapanir,
                      ADX(14)[i] < 20 -> ters yon (ust disindan donus SELL, alt disindan BUY).
                      07-20 UTC. SL 2.0*ATR, TP 1.0R. (Ad M30 odakli; M15'te de kosulur.)
  fx_donchian_gunluk  Donchian(20) kirilimi (kapanis onceki 20 barin en yuksegini/dusugunu asar),
                      kapanis, son KAPANMIS gunun EMA(50)'si tarafinda, ADX(14)>=25.
                      SL 2.0*ATR, TP 0 (motor trailing).

Notlar
- `side(s, b, i)` yalniz i ve oncesi barlari okur. Gun-durumlari (Londra araligi) ve gunluk EMA
  ileri tek gecisle uretilir; uzun seride yeniden hesap ayni karari verir.
- Gunluk EMA: barlar UTC gunlere resample edilir; bar i icin yalniz i'nin gunu ONCESINDEKI gunlerin
  kapanislari kullanilir (gun, sonraki gunun ilk barinda kapanir). Hafta sonu Pazar mini-gunu
  (yalniz 21-24 UTC barlari) kendi gun mumu olarak seriye girer.
- Londra stratejisinde SL araliga bagli degisken oldugu icin `atr[i]` bilerek etkin SL-mesafesi
  olarak doldurulur (sl_atr=1.0): sinyal barinda max(aralik/2, ATR14), diger barlarda ATR14.
  Motor sl = sl_atr * atr[i] hesapladigi icin SL = aralik/2 (en az 1 ATR). Diger stratejiler
  "atr" vermez; sarmalayici wk.atr(b, 14) ekler.
- Bar.t = bar ACILIS zamani (unix sn, UTC). "Seans 07-20" = karar barinin acilis saati [7, 20).
"""
from __future__ import annotations

import math
import os
import sys
from datetime import datetime, timezone

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import ha_supertrend_mt5_7d as eng  # noqa: E402
import xau_week_double_8w as wk  # noqa: E402

PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "USDCAD", "USDCHF", "GBPJPY", "EURJPY", "NZDUSD")
SPREAD_MIN_MULT = 8.0
SESSION_START_H = 7
SESSION_END_H = 20


# ------------------------------------------------------------------ yardimcilar
def _bollinger(closes: list, n: int, mult: float):
    """SMA(n) +- mult*populasyon stdev (TV). (alt, ust)"""
    N = len(closes)
    lo: list = [None] * N
    up: list = [None] * N
    for i in range(n - 1, N):
        w = closes[i - n + 1:i + 1]
        m = sum(w) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
        lo[i], up[i] = m - mult * sd, m + mult * sd
    return lo, up


def _tf_sec(bars: list) -> int:
    diffs = sorted(int(bars[k + 1].t - bars[k].t) for k in range(min(len(bars) - 1, 400)))
    return diffs[len(diffs) // 2] if diffs else 900


def _ok(*vals) -> bool:
    return all(v is not None for v in vals)


def _in_session(bar) -> bool:
    return SESSION_START_H <= int(bar.t % 86400) // 3600 < SESSION_END_H


# ------------------------------------------------------------------ 1) Londra araligi
RANGE_START_MIN = 7 * 60
RANGE_END_MIN = 8 * 60
WINDOW_END_MIN = 12 * 60
RANGE_MIN_ATR = 0.8


def _londra_series(b, closes):
    n = len(b)
    tf = _tf_sec(b)
    need = max(1, 3600 // tf)
    atr14 = wk.atr(b, 14)
    atr_eff = list(atr14)
    sig = [0] * n
    day = None
    rhi = rlo = None
    cnt = 0
    range_ok = None  # aralik kapaninca (08:00 sonrasi ilk aday bar) gun basina bir kez karar verilir
    last_range_atr = None
    fired = {1: False, -1: False}
    for i in range(n):
        dt = datetime.fromtimestamp(b[i].t, timezone.utc)
        d = dt.date()
        if d != day:
            day, rhi, rlo, cnt, range_ok, last_range_atr = d, None, None, 0, None, None
            fired = {1: False, -1: False}
        m_open = dt.hour * 60 + dt.minute
        m_close = m_open + tf // 60
        if RANGE_START_MIN <= m_open and m_close <= RANGE_END_MIN:
            rhi = b[i].high if rhi is None else max(rhi, b[i].high)
            rlo = b[i].low if rlo is None else min(rlo, b[i].low)
            cnt += 1
            last_range_atr = atr14[i]
            continue
        if cnt < need or rhi is None or m_open < RANGE_END_MIN or m_close > WINDOW_END_MIN:
            continue
        if range_ok is None:
            range_ok = last_range_atr is not None and (rhi - rlo) >= RANGE_MIN_ATR * last_range_atr
        if not range_ok:
            continue
        c = b[i].close
        side = 1 if c > rhi else (-1 if c < rlo else 0)
        if side and not fired[side]:
            fired[side] = True
            sig[i] = side
            half = (rhi - rlo) / 2.0
            if atr14[i] is not None:
                atr_eff[i] = max(half, atr14[i])
    return {"sig": sig, "atr": atr_eff}


def _londra_side(s, b, i):
    return s["sig"][i]


# ------------------------------------------------------------------ 2) EMA200 + RSI geri donus
def _rsi_geri_series(b, closes):
    _p, _m, adx = eng.adx_dmi(b, 14)
    return {"rsi": eng.rsi_wilder(closes, 14), "ema200": wk.ema(closes, 200),
            "ema21": wk.ema(closes, 21), "adx": adx}


def _rsi_geri_side(s, b, i):
    if i < 1 or not _in_session(b[i]):
        return 0
    r0, r1, e200, e21, adx = s["rsi"][i - 1], s["rsi"][i], s["ema200"][i], s["ema21"][i], s["adx"][i]
    if not _ok(r0, r1, e200, e21, adx) or adx < 20:
        return 0
    c = b[i].close
    if r0 < 50 <= r1 and c > e200 and c > e21:
        return 1
    if r0 > 50 >= r1 and c < e200 and c < e21:
        return -1
    return 0


# ------------------------------------------------------------------ 3) BB donus
def _bb_donus_series(b, closes):
    lo, up = _bollinger(closes, 20, 2.5)
    _p, _m, adx = eng.adx_dmi(b, 14)
    return {"bb_lo": lo, "bb_up": up, "adx": adx}


def _bb_donus_side(s, b, i):
    if i < 1 or not _in_session(b[i]):
        return 0
    lo0, up0, lo1, up1, adx = s["bb_lo"][i - 1], s["bb_up"][i - 1], s["bb_lo"][i], s["bb_up"][i], s["adx"][i]
    if not _ok(lo0, up0, lo1, up1, adx) or adx >= 20:
        return 0
    c0, c1 = b[i - 1].close, b[i].close
    if not (lo1 <= c1 <= up1):
        return 0
    if c0 < lo0:
        return 1
    if c0 > up0:
        return -1
    return 0


# ------------------------------------------------------------------ 4) Donchian + gunluk EMA50
DONCH_N = 20
D_EMA = 50


def _daily_ema_prev(b):
    """Bar basina: o barin gunu ONCESINDEKI son kapanmis gunun EMA(50)'si (yoksa None)."""
    n = len(b)
    days = wk.resample(b, 86400)
    dema = wk.ema([d.close for d in days], D_EMA)
    out: list = [None] * n
    k = 0  # days[k] = bar i'nin gunu; son kapanmis gun = k-1
    for i in range(n):
        day_start = b[i].t // 86400 * 86400
        while k < len(days) and days[k].t < day_start:
            k += 1
        out[i] = dema[k - 1] if k >= 1 else None
    return out


def _donch_series(b, closes):
    n = len(b)
    hi: list = [None] * n  # bar i dahil degil, onceki DONCH_N barin en yuksegi
    lo: list = [None] * n
    for i in range(DONCH_N, n):
        hi[i] = max(x.high for x in b[i - DONCH_N:i])
        lo[i] = min(x.low for x in b[i - DONCH_N:i])
    _p, _m, adx = eng.adx_dmi(b, 14)
    return {"dc_hi": hi, "dc_lo": lo, "dema": _daily_ema_prev(b), "adx": adx}


def _donch_side(s, b, i):
    hi, lo, de, adx = s["dc_hi"][i], s["dc_lo"][i], s["dema"][i], s["adx"][i]
    if not _ok(hi, lo, de, adx) or adx < 25:
        return 0
    c = b[i].close
    if c > hi and c > de:
        return 1
    if c < lo and c < de:
        return -1
    return 0


STRATEGIES = {
    "fx_londra_aralik": {"series": _londra_series, "side": _londra_side, "sl_atr": 1.0, "tp_r": 2.0,
                         "symbols": set(PAIRS), "spread_min_mult": SPREAD_MIN_MULT},
    "fx_ema200_rsi_geri": {"series": _rsi_geri_series, "side": _rsi_geri_side, "sl_atr": 2.5, "tp_r": 1.5,
                           "symbols": set(PAIRS), "spread_min_mult": SPREAD_MIN_MULT},
    "fx_bb_donus_m30": {"series": _bb_donus_series, "side": _bb_donus_side, "sl_atr": 2.0, "tp_r": 1.0,
                        "symbols": set(PAIRS), "spread_min_mult": SPREAD_MIN_MULT},
    "fx_donchian_gunluk": {"series": _donch_series, "side": _donch_side, "sl_atr": 2.0, "tp_r": 0.0,
                           "symbols": set(PAIRS), "spread_min_mult": SPREAD_MIN_MULT},
}
