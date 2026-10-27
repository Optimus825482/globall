"""BTCUSD giris-strateji ailesi (replay_strateji_gunluk eklentisi).

Bes birbirinden farkli mantik; parametreler SABIT (grid yok, varyant yok):

  btc_seans_kirilim   13:30-14:30 UTC (ABD acilisi) araligi; 14:30-20:00 UTC arasinda
                      kapanis aralik disina cikinca yonunde giris, gunde yon basina 1.
                      SL = max(aralik/2, 1.0*ATR14), TP 2R.
  btc_rsi2_bb_donus   RSI(2)<5 + kapanis < BB(20,2.5) alt + kapanis > EMA200 -> BUY (ters SELL);
                      SL 3.0*ATR, TP 1.0R.
  btc_donchian55_trend  kapanis onceki 55 barin en yuksegini/dusugunu asar + EMA200 tarafi
                      + ADX(14)>=25; SL 2.0*ATR, TP yok (motor trailing).
  btc_keltner_geri_htf  EMA200 tarafi; onceki bar Keltner(20, 1.5*ATR10) orta bandinin
                      ters tarafinda kapanmis (geri cekilme), bu bar yonunde kapanir ve
                      son 3 barin en yuksegini (BUY) / en dusugunu (SELL) asar; SL 2.0*ATR, TP 2R.
  btc_nr7_kirilim     NR7 barindan hemen sonraki bar, NR7 high/low disinda kapanir + ADX>=20;
                      SL 1.5*ATR, TP 2R.

Notlar
- `side(s, b, i)` yalniz i ve oncesi barlari okur; seans stratejisinin gun-durumu da ileri
  tek gecisle (bar <= i) uretilir, bu yuzden uzun seride yeniden hesap ayni karari verir.
- Seans stratejisinde SL araliga bagli degisken oldugu icin motorun `atr[i]` serisi bilerek
  etkin SL-mesafesi olarak doldurulur (sl_atr=1.0): sinyal barinda max(aralik/2, ATR14),
  diger barlarda ATR14. Motor sl = sl_atr * atr[i] hesapladigi icin SL = aralik/2 (en az 1 ATR).
- Keltner: orta bant = EMA20; 1.5*ATR10 bant genisligi sinyal kosullarinda kullanilmaz
  (brief yalniz orta bandi ister). "Son 3 barin en yuksegi/dusugu" kosulu, geri cekilme
  teyidi anlaminda: BUY icin kapanis onceki 3 barin high'ini asar, SELL icin low'unu keser.
- Bar.t = bar ACILIS zamani (unix sn, UTC); bar kapanisi t + tf.
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


# ------------------------------------------------------------------ 1) seans kirilimi
RANGE_START_MIN = 13 * 60 + 30
RANGE_END_MIN = 14 * 60 + 30
WINDOW_END_MIN = 20 * 60


def _seans_series(b, closes):
    n = len(b)
    tf = _tf_sec(b)
    need = max(1, 3600 // tf)
    atr14 = wk.atr(b, 14)
    atr_eff = list(atr14)
    sig = [0] * n
    day = None
    rhi = rlo = None
    cnt = 0
    fired = {1: False, -1: False}
    for i in range(n):
        dt = datetime.fromtimestamp(b[i].t, timezone.utc)
        d = dt.date()
        if d != day:
            day, rhi, rlo, cnt = d, None, None, 0
            fired = {1: False, -1: False}
        m_open = dt.hour * 60 + dt.minute
        m_close = m_open + tf // 60
        if RANGE_START_MIN <= m_open and m_close <= RANGE_END_MIN:
            rhi = b[i].high if rhi is None else max(rhi, b[i].high)
            rlo = b[i].low if rlo is None else min(rlo, b[i].low)
            cnt += 1
            continue
        if cnt < need or rhi is None or m_open < RANGE_END_MIN or m_close > WINDOW_END_MIN:
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


def _seans_side(s, b, i):
    return s["sig"][i]


# ------------------------------------------------------------------ 2) RSI2 + BB donus
def _rsi2_series(b, closes):
    lo, up = _bollinger(closes, 20, 2.5)
    return {"rsi": eng.rsi_wilder(closes, 2), "bb_lo": lo, "bb_up": up, "ema200": wk.ema(closes, 200)}


def _rsi2_side(s, b, i):
    r, lo, up, e = s["rsi"][i], s["bb_lo"][i], s["bb_up"][i], s["ema200"][i]
    if not _ok(r, lo, up, e):
        return 0
    c = b[i].close
    if r < 5 and c < lo and c > e:
        return 1
    if r > 95 and c > up and c < e:
        return -1
    return 0


# ------------------------------------------------------------------ 3) Donchian55 trend
def _donch_series(b, closes):
    n = len(b)
    hi: list = [None] * n  # bar i dahil degil, onceki 55 barin en yuksegi
    lo: list = [None] * n
    for i in range(55, n):
        hi[i] = max(x.high for x in b[i - 55:i])
        lo[i] = min(x.low for x in b[i - 55:i])
    _p, _m, adx = eng.adx_dmi(b, 14)
    return {"dc_hi": hi, "dc_lo": lo, "ema200": wk.ema(closes, 200), "adx": adx}


def _donch_side(s, b, i):
    hi, lo, e, adx = s["dc_hi"][i], s["dc_lo"][i], s["ema200"][i], s["adx"][i]
    if not _ok(hi, lo, e, adx) or adx < 25:
        return 0
    c = b[i].close
    if c > hi and c > e:
        return 1
    if c < lo and c < e:
        return -1
    return 0


# ------------------------------------------------------------------ 4) Keltner geri cekilme
def _kelt_series(b, closes):
    # Keltner orta bandi = EMA20 (bant genisligi 1.5*ATR10 sinyalde kullanilmaz)
    return {"mid": wk.ema(closes, 20), "ema200": wk.ema(closes, 200)}


def _kelt_side(s, b, i):
    if i < 4:
        return 0
    mid1, e = s["mid"][i - 1], s["ema200"][i]
    if not _ok(mid1, e):
        return 0
    c, o, c1 = b[i].close, b[i].open, b[i - 1].close
    hh3 = max(x.high for x in b[i - 3:i])
    ll3 = min(x.low for x in b[i - 3:i])
    if c > e and c1 < mid1 and c > o and c > hh3:
        return 1
    if c < e and c1 > mid1 and c < o and c < ll3:
        return -1
    return 0


# ------------------------------------------------------------------ 5) NR7 kirilimi
def _nr7_series(b, closes):
    n = len(b)
    nr7 = [False] * n
    for j in range(6, n):
        rng = b[j].high - b[j].low
        nr7[j] = all(rng < (b[k].high - b[k].low) for k in range(j - 6, j))
    _p, _m, adx = eng.adx_dmi(b, 14)
    return {"nr7": nr7, "adx": adx}


def _nr7_side(s, b, i):
    if i < 7 or not s["nr7"][i - 1]:
        return 0
    adx = s["adx"][i]
    if adx is None or adx < 20:
        return 0
    c = b[i].close
    if c > b[i - 1].high:
        return 1
    if c < b[i - 1].low:
        return -1
    return 0


STRATEGIES = {
    "btc_seans_kirilim": {"series": _seans_series, "side": _seans_side, "sl_atr": 1.0, "tp_r": 2.0,
                          "symbols": {"BTCUSD"}, "spread_min_mult": None},
    "btc_rsi2_bb_donus": {"series": _rsi2_series, "side": _rsi2_side, "sl_atr": 3.0, "tp_r": 1.0,
                          "symbols": {"BTCUSD"}, "spread_min_mult": None},
    "btc_donchian55_trend": {"series": _donch_series, "side": _donch_side, "sl_atr": 2.0, "tp_r": 0.0,
                             "symbols": {"BTCUSD"}, "spread_min_mult": None},
    "btc_keltner_geri_htf": {"series": _kelt_series, "side": _kelt_side, "sl_atr": 2.0, "tp_r": 2.0,
                             "symbols": {"BTCUSD"}, "spread_min_mult": None},
    "btc_nr7_kirilim": {"series": _nr7_series, "side": _nr7_side, "sl_atr": 1.5, "tp_r": 2.0,
                        "symbols": {"BTCUSD"}, "spread_min_mult": None},
}
