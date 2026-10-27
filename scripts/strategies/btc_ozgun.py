"""BTCUSD ozgun giris-strateji ailesi (replay_strateji_gunluk eklentisi).

Klasik gosterge kombinasyonlarinin (MACD/RSI/Stoch/BB/Keltner/Donchian/Supertrend/HMA/Vortex/
UT Bot/ORB/NR7/pullback) disinda, yapisal/istatistiksel fikirler. Parametreler SABIT (grid yok).

  btc_saat_profili      Son 20 gundeki ayni UTC saat kovasinin ort. log-getirisi t-istatistigi
                        |t|>=2 ise kova basinda o isaretle giris; SL 1.5*ATR, TP 1.0R.
                        Neden ozgun: depoda gun-ici mevsimsellik / zaman-kovasi istatistigi
                        hic denenmedi, yalniz fiyat/gosterge kosullari vardi.
  btc_likidite_supurme  Son 20 barin dibini >=0.2*ATR fitille supurup ustunde kapanis -> BUY
                        (ayna SELL); SL = supurme ucunun 0.3*ATR otesi, TP 2R.
                        Neden ozgun: depoda stop-avi / likidite supurme (fitil-reddi) mantigi yok,
                        yalniz kirilim-takibi ve gosterge-asiri-bolge donusleri denendi.
  btc_xau_oncu          XAUUSD 12 barlik log-getiri z-skoru (60 bar) |z|>=2 iken BTC henuz tepki
                        vermediyse (kendi 12 bar getirisi ters/duz) ayni yonde giris; SL 1.5*ATR, TP 1.5R.
                        Neden ozgun: depoda cok-varlikli (lead-lag) giris yok, tum stratejiler
                        tek sembolun kendi barlarina bakiyordu.
  btc_govde_yigini      3 ardisik barda CLV>=0.7 (ayna <=0.3) ve her bar aralik genislemesi ->
                        3. bar kapanisinda giris; SL = 3 barin ucu, TP 2R; 10 bar tekrar yok.
                        Neden ozgun: depoda mum-ici kapanis konumu (CLV) / mum anatomisi hic
                        kullanilmadi, yalniz gosterge ve fiyat-seviyesi kosullari vardi.
  btc_verimlilik_rejimi Kaufman ER(20) ile rejim anahtari: ER>=0.6 trend (EMA20 geri cekilme),
                        ER<=0.2 yatay (aralik ucundan donus); SL 1.5*ATR, TP 1.5R.
                        Neden ozgun: depoda fiyat-yolu verimliligi ile iki zit mantik arasinda
                        otomatik secim yok; ADX filtresi tek yonlu bir kapiydi.

Notlar
- `side(s, b, i)` yalniz i ve oncesi barlari okur; tum durumlar ileri tek gecisle (bar <= i)
  uretilir, uzun seride yeniden hesap ayni karari verir (testlerle kanitli).
- Motor sinyal barinin kapanisindan SONRAKI bar acilisinda girer (i = son kapanmis bar).
  `btc_saat_profili` karari saat kovasinin ilk barinin kapanisinda verilir (karar girdisi yalniz
  onceki gunlerin kovalaridir; giris bir sonraki barin acilisi).
- Degisken SL'li stratejilerde (likidite_supurme, govde_yigini) motorun `atr[i]` serisi
  sinyal barinda etkin SL-mesafesi olarak ezilir ve sl_atr=1.0 kullanilir (btc_aile ile ayni teknik).
  Etkin mesafe sinyal barinin KAPANISINDAN hesaplanir.
- Bar.t = bar ACILIS zamani (unix sn, UTC).

Ek tasarim kararlari (brief belirsizliklerinde, sabit):
- saat_profili: kova getirisi = ln(kovanin son kapanisi / ilk acilisi), yalniz TAM kovalar
  (saat basina tf'ye gore tum barlar var); son 20 tam gun, n >= 10 gerekli, std (ddof=1) > 0.
- likidite_supurme: ayni barin hem alt hem ust dibi supurmesi belirsiz -> sinyal yok.
- xau_oncu: z baz penceresi = onceki 60 adet 12-bar getiri (mevcut dahil degil), >= 30 gecerli;
  hizalanan XAU bari BTC barindan en fazla 1 bar (tf) eski olabilir (hafta sonu / kapali piyasada
  bayat XAU ile sinyal uretilmez); 12 barlik pencerelerin zaman acigi <= 14*tf olmali.
  XAU yuklemesi `_XAU_LOADER(tf_adi)` (test icin enjekte edilebilir).
- govde_yigini: CLV ve aralik-genisleme sarti 3 barin her birinde aranir (i-3'e bakar);
  10 bar tekrar-yok, YALNIZ gerceklesen sinyalden sayilir (her iki yon).
- verimlilik_rejimi: trend yonu = sign(C[i]-C[i-20]); BUY: low<=EMA20<kapanis ve kapanis>acilis
  (SELL ayna). Yatay: 20-bar (i-20..i-1) high/low araliginda onceki kapanis >=%90 (<=%10) konumunda
  ve bu bar onceki kapanisin altinda (ustunde) kapanir -> SELL (BUY).
"""
from __future__ import annotations

import bisect
import json
import math
import os
import sys

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import xau_week_double_8w as wk  # noqa: E402

_ROOT = os.path.dirname(_SCRIPTS)


# ------------------------------------------------------------------ yardimcilar
def _tf_sec(bars: list) -> int:
    diffs = sorted(int(bars[k + 1].t - bars[k].t) for k in range(min(len(bars) - 1, 400)))
    return diffs[len(diffs) // 2] if diffs else 900


def _ok(*vals) -> bool:
    return all(v is not None for v in vals)


# ------------------------------------------------------------------ 1) saat profili
PROFIL_GUN = 20
PROFIL_MIN_N = 10
PROFIL_T = 2.0


def _saat_series(b, closes):
    n = len(b)
    tf = _tf_sec(b)
    per = max(1, 3600 // tf)
    sig = [0] * n
    hist: dict = {h: [] for h in range(24)}  # saat -> onceki gunlerin tam-kova log-getirileri
    cur_key = None
    cur_hour = 0
    cur_open = cur_close = 0.0
    cur_cnt = 0
    for i in range(n):
        t = int(b[i].t)
        key = t // 3600
        if key != cur_key:
            # biten kovayi kapat (yalniz tam kovalar tarihe girer)
            if cur_key is not None and cur_cnt == per and cur_open > 0 and cur_close > 0:
                hist[cur_hour].append(math.log(cur_close / cur_open))
            cur_key, cur_hour, cur_open, cur_cnt = key, key % 24, b[i].open, 0
            if t % 3600 == 0:  # kovanin ilk bari: karar yalniz onceki gunlerin kovalarindan
                vals = hist[cur_hour][-PROFIL_GUN:]
                m = len(vals)
                if m >= PROFIL_MIN_N:
                    mean = sum(vals) / m
                    var = sum((v - mean) ** 2 for v in vals) / (m - 1)
                    if var > 0:
                        tstat = mean / math.sqrt(var) * math.sqrt(m)
                        if abs(tstat) >= PROFIL_T:
                            sig[i] = 1 if mean > 0 else -1
        cur_close = b[i].close
        cur_cnt += 1
    return {"sig": sig}


def _saat_side(s, b, i):
    return s["sig"][i]


# ------------------------------------------------------------------ 2) likidite supurme
SUP_N = 20
SUP_FITIL = 0.2
SUP_SL = 0.3


def _sup_series(b, closes):
    n = len(b)
    atr14 = wk.atr(b, 14)
    atr_eff = list(atr14)
    sig = [0] * n
    for i in range(SUP_N, n):
        a = atr14[i]
        if a is None or a <= 0:
            continue
        ll = min(x.low for x in b[i - SUP_N:i])
        hh = max(x.high for x in b[i - SUP_N:i])
        c = b[i].close
        buy = (ll - b[i].low) >= SUP_FITIL * a and c > ll
        sell = (b[i].high - hh) >= SUP_FITIL * a and c < hh
        if buy == sell:  # ikisi birden (belirsiz) ya da hicbiri
            continue
        if buy:
            sig[i] = 1
            atr_eff[i] = (c - b[i].low) + SUP_SL * a
        else:
            sig[i] = -1
            atr_eff[i] = (b[i].high - c) + SUP_SL * a
    return {"sig": sig, "atr": atr_eff}


def _sup_side(s, b, i):
    return s["sig"][i]


# ------------------------------------------------------------------ 3) XAU oncusu
XAU_RET_N = 12
XAU_Z_WIN = 60
XAU_Z = 2.0
_TF_NAME = {300: "m5", 900: "m15"}
_XAU_CACHE: dict = {}


def _default_xau_loader(tf_name: str) -> list:
    """outputs/replay_cache_xaubtc_<tf>.json -> XAUUSD satirlari [[ts,o,h,l,c],...]."""
    if tf_name not in _XAU_CACHE:
        path = os.path.join(_ROOT, "outputs", f"replay_cache_xaubtc_{tf_name}.json")
        with open(path, encoding="utf-8") as fh:
            _XAU_CACHE[tf_name] = json.load(fh)["XAUUSD"]
    return _XAU_CACHE[tf_name]


_XAU_LOADER = _default_xau_loader  # testlerde sentetik XAU ile degistirilir


def _xau_z(xt: list, xc: list, tf: int) -> list:
    """Her XAU indeksi k icin (yalniz k ve oncesini kullanan) 12 barlik log-getiri z-skoru."""
    m = len(xc)
    r12: list = [None] * m
    for k in range(XAU_RET_N, m):
        if xt[k] - xt[k - XAU_RET_N] <= (XAU_RET_N + 2) * tf and xc[k] > 0 and xc[k - XAU_RET_N] > 0:
            r12[k] = math.log(xc[k] / xc[k - XAU_RET_N])
    z: list = [None] * m
    for k in range(XAU_RET_N + XAU_Z_WIN, m):
        if r12[k] is None:
            continue
        base = [v for v in r12[k - XAU_Z_WIN:k] if v is not None]
        if len(base) < XAU_Z_WIN // 2:
            continue
        mu = sum(base) / len(base)
        sd = math.sqrt(sum((v - mu) ** 2 for v in base) / len(base))
        if sd > 0:
            z[k] = (r12[k] - mu) / sd
    return z


def _xau_series(b, closes):
    n = len(b)
    tf = _tf_sec(b)
    tf_name = _TF_NAME.get(tf)
    if tf_name is None:
        raise ValueError(f"btc_xau_oncu: desteklenmeyen bar araligi {tf} sn (300 / 900)")
    rows = sorted(_XAU_LOADER(tf_name), key=lambda r: r[0])
    xt = [int(r[0]) for r in rows]
    xc = [float(r[4]) for r in rows]
    z = _xau_z(xt, xc, tf)
    sig = [0] * n
    for i in range(XAU_RET_N, n):
        t = int(b[i].t)
        j = bisect.bisect_right(xt, t) - 1  # yalniz t_xau <= t_btc
        if j < 0 or t - xt[j] > tf:
            continue
        zz = z[j]
        if zz is None or abs(zz) < XAU_Z:
            continue
        if t - int(b[i - XAU_RET_N].t) > (XAU_RET_N + 2) * tf:
            continue
        c0 = b[i - XAU_RET_N].close
        if c0 <= 0 or b[i].close <= 0:
            continue
        rb = math.log(b[i].close / c0)
        if zz > 0 and rb <= 0:
            sig[i] = 1
        elif zz < 0 and rb >= 0:
            sig[i] = -1
    return {"sig": sig}


def _xau_side(s, b, i):
    return s["sig"][i]


# ------------------------------------------------------------------ 4) govde yigini
GY_CLV = 0.7
GY_COOLDOWN = 10


def _clv(x):
    rng = x.high - x.low
    return None if rng <= 0 else (x.close - x.low) / rng


def _govde_series(b, closes):
    n = len(b)
    atr14 = wk.atr(b, 14)
    atr_eff = list(atr14)
    sig = [0] * n
    last = None
    for i in range(3, n):
        if last is not None and i - last <= GY_COOLDOWN:
            continue
        bars3 = b[i - 2:i + 1]
        clvs = [_clv(x) for x in bars3]
        if not all(v is not None for v in clvs):
            continue
        rngs = [x.high - x.low for x in b[i - 3:i + 1]]
        if not all(rngs[k + 1] > rngs[k] for k in range(3)):
            continue
        if all(v >= GY_CLV for v in clvs):
            sig[i] = 1
            atr_eff[i] = b[i].close - min(x.low for x in bars3)
        elif all(v <= 1.0 - GY_CLV for v in clvs):
            sig[i] = -1
            atr_eff[i] = max(x.high for x in bars3) - b[i].close
        else:
            continue
        last = i
    return {"sig": sig, "atr": atr_eff}


def _govde_side(s, b, i):
    return s["sig"][i]


# ------------------------------------------------------------------ 5) verimlilik rejimi
ER_N = 20
ER_TREND = 0.6
ER_RANGE = 0.2
ER_EDGE = 0.10


def _er_series(b, closes):
    n = len(b)
    ema20 = wk.ema(closes, 20)
    er: list = [None] * n
    for i in range(ER_N, n):
        path = sum(abs(closes[k] - closes[k - 1]) for k in range(i - ER_N + 1, i + 1))
        if path > 0:
            er[i] = abs(closes[i] - closes[i - ER_N]) / path
    sig = [0] * n
    for i in range(ER_N + 1, n):
        e, m = er[i], ema20[i]
        if e is None or m is None:
            continue
        c, o = b[i].close, b[i].open
        if e >= ER_TREND:
            d = c - closes[i - ER_N]
            if d > 0 and b[i].low <= m < c and c > o:
                sig[i] = 1
            elif d < 0 and b[i].high >= m > c and c < o:
                sig[i] = -1
        elif e <= ER_RANGE:
            hh = max(x.high for x in b[i - ER_N:i])
            ll = min(x.low for x in b[i - ER_N:i])
            if hh <= ll:
                continue
            pos = (closes[i - 1] - ll) / (hh - ll)
            if pos >= 1.0 - ER_EDGE and c < closes[i - 1]:
                sig[i] = -1
            elif pos <= ER_EDGE and c > closes[i - 1]:
                sig[i] = 1
    return {"sig": sig, "er": er, "ema20": ema20}


def _er_side(s, b, i):
    return s["sig"][i]


STRATEGIES = {
    "btc_saat_profili": {"series": _saat_series, "side": _saat_side, "sl_atr": 1.5, "tp_r": 1.0,
                         "symbols": {"BTCUSD"}, "spread_min_mult": None},
    "btc_likidite_supurme": {"series": _sup_series, "side": _sup_side, "sl_atr": 1.0, "tp_r": 2.0,
                             "symbols": {"BTCUSD"}, "spread_min_mult": None},
    "btc_xau_oncu": {"series": _xau_series, "side": _xau_side, "sl_atr": 1.5, "tp_r": 1.5,
                     "symbols": {"BTCUSD"}, "spread_min_mult": None},
    "btc_govde_yigini": {"series": _govde_series, "side": _govde_side, "sl_atr": 1.0, "tp_r": 2.0,
                         "symbols": {"BTCUSD"}, "spread_min_mult": None},
    "btc_verimlilik_rejimi": {"series": _er_series, "side": _er_side, "sl_atr": 1.5, "tp_r": 1.5,
                              "symbols": {"BTCUSD"}, "spread_min_mult": None},
}
